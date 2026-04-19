"""
Curalink — Main Query Route (with Personalization)
POST /api/query
"""

import time
from fastapi import APIRouter, HTTPException
from models.schemas import QueryRequest, QueryResponse, PipelineStages
from pipeline.hyde import run_hyde_expansion
from pipeline.retrieval import run_retrieval
from pipeline.embedder import run_prefilter, run_embedding, run_scoring
from pipeline.rerank import run_rerank
from pipeline.corrective import run_corrective_rag
from pipeline.synthesis import run_synthesis
from pipeline.personalization import (
    apply_personalization_to_scoring,
    build_personalized_system_prompt,
    build_personalized_hyde_context,
    get_study_type_filter,
)
from db.session import create_session, get_session, append_message, get_recent_messages, update_context_summary
from db.cache import get_cached, set_cached
from db.user_profile import (
    build_personalization_context,
    save_query_history,
    update_user_behavior,
    get_session_context_summary,
)
from observability.langsmith import traced, log_pipeline_event

router = APIRouter()


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Submit a medical research query",
    description="""
Full personalized pipeline:
1. Load user profile + personalization context from MongoDB
2. Session lookup + context injection (follow-up detection)
3. Cache check (24h TTL)
4. HyDE expansion with patient context (Groq Call 1)
5. Parallel retrieval — PubMed + OpenAlex + ClinicalTrials
6. Pre-filter (hard rules + user study type preferences)
7. Semantic embedding + cosine ranking
8. Multi-signal scoring (human/animal weights, dynamic recency, location bias)
9. Personalization scoring layer (user preferred types, bookmarks)
10. Rerank + Self-RAG + Corrective RAG verdict (Groq Call 2)
11. Corrective RAG re-retrieval (conditional)
12. Personalized synthesis + grounding check (Groq Call 3)
13. Save query history + update behavior signals
    """,
)
async def query(req: QueryRequest):
    pipeline_start = time.time()
    stages = PipelineStages()

    # ── Step 1: Load personalization context ─────────────────────────────
    persona = await build_personalization_context(
        user_id=req.user_id if hasattr(req, "user_id") else None,
        disease=req.disease,
    )

    # Override location from user profile if not provided in request
    effective_location = req.location or persona.get("location") or ""

    # ── Step 2: Session ───────────────────────────────────────────────────
    session    = await get_session(req.session_id) if req.session_id else None
    is_followup = session is not None

    if not session:
        session_id = await create_session(
            patient_name=req.patient_name or persona.get("name") or "",
            disease=req.disease,
            location=effective_location,
            user_id=persona.get("user_id"),
        )
    else:
        session_id = req.session_id

    # Build prior context for follow-ups
    prior_context = ""
    if is_followup:
        prior_context = await get_session_context_summary(session_id)
        if not prior_context:
            recent = await get_recent_messages(session_id, limit=4)
            prior_context = " | ".join(
                str(m.get("content", {}).get("query", ""))
                for m in recent if m.get("role") == "user"
            )

    # ── Step 3: Cache check (skip for follow-ups — context changes answer) ─
    if not is_followup:
        cached = await get_cached(req.query, req.disease)
        if cached:
            cached["session_id"] = session_id
            log_pipeline_event("cache_hit", {"query": req.query})
            return QueryResponse(**cached)

    # ── Step 4: HyDE Expansion (personalized) ────────────────────────────
    t = time.time()
    hyde_persona_context = build_personalized_hyde_context(persona, req.disease)
    full_prior_context   = f"{prior_context}\n{hyde_persona_context}".strip()

    hyde = await run_hyde_expansion(
        query=req.query,
        disease=req.disease,
        is_followup=is_followup,
        prior_context=full_prior_context,
    )
    stages.hyde_expansion_ms = round((time.time() - t) * 1000, 1)
    stages.groq_calls_made  += 1

    log_pipeline_event("hyde_complete", {
        "variants":    hyde.query_variants,
        "is_followup": is_followup,
        "personalized": bool(hyde_persona_context),
    })

    # ── Step 5: Parallel Retrieval ────────────────────────────────────────
    t = time.time()
    papers, trials = await run_retrieval(
        query_variants=hyde.query_variants,
        disease=req.disease,
        original_query=req.query,
        location=effective_location,
    )
    stages.retrieval_ms     = round((time.time() - t) * 1000, 1)
    stages.papers_retrieved = len(papers)
    stages.trials_retrieved = len(trials)

    if not papers and not trials:
        raise HTTPException(
            status_code=503,
            detail="No results retrieved. Check API connectivity."
        )

    # ── Step 6: Pre-filter (respects user study type preferences) ─────────
    t = time.time()
    allowed_types = get_study_type_filter(persona)
    papers, trials = await run_prefilter(
        papers, trials, req.disease,
        allowed_study_subjects=allowed_types,
    )
    stages.prefilter_ms           = round((time.time() - t) * 1000, 1)
    stages.papers_after_prefilter = len(papers)

    # ── Step 7: Semantic Embedding ────────────────────────────────────────
    t = time.time()
    papers, trials = await run_embedding(
        papers, trials, req.query, req.disease,
        top_k_papers=25, top_k_trials=20,
    )
    stages.embedding_ms          = round((time.time() - t) * 1000, 1)
    stages.papers_after_semantic = len(papers)

    # ── Step 8: Multi-signal Scoring ──────────────────────────────────────
    t = time.time()
    papers, trials = await run_scoring(
        papers, trials, req.query, req.disease, effective_location
    )
    stages.scoring_ms = round((time.time() - t) * 1000, 1)

    # ── Step 9: Personalization scoring layer ─────────────────────────────
    papers, trials = apply_personalization_to_scoring(papers, trials, persona)

    # ── Step 10: Rerank + Self-RAG + Corrective RAG ───────────────────────
    t = time.time()
    papers, trials, corrective = await run_rerank(
        papers=papers,
        trials=trials,
        query=req.query,
        disease=req.disease,
        location=effective_location,
        top_k_papers=8,
        top_k_trials=6,
    )
    stages.rerank_ms           = round((time.time() - t) * 1000, 1)
    stages.papers_after_rerank = len(papers)
    stages.trials_after_rerank = len(trials)
    stages.groq_calls_made    += 1

    # ── Step 11: Corrective RAG (conditional) ─────────────────────────────
    verdict_val = corrective.verdict.value if hasattr(corrective.verdict, "value") else str(corrective.verdict)
    if verdict_val in ("ambiguous", "incorrect"):
        t = time.time()
        papers, trials, corrective = await run_corrective_rag(
            corrective=corrective,
            existing_papers=papers,
            existing_trials=trials,
            disease=req.disease,
            query=req.query,
            location=effective_location,
        )
        stages.corrective_rag_ms    = round((time.time() - t) * 1000, 1)
        stages.corrective_rag_fired = True

        log_pipeline_event("corrective_rag_fired", {
            "verdict":      corrective.verdict,
            "weak_aspects": corrective.weak_aspects,
        })

    # ── Step 12: Personalized Synthesis + Self-RAG Grounding ─────────────
    t = time.time()
    history = await get_recent_messages(session_id, limit=4)

    # Build personalized system prompt for Groq
    personalized_system_prompt = build_personalized_system_prompt(
        context=persona,
        disease=req.disease,
        query=req.query,
    )

    synthesis = await run_synthesis(
        papers=papers,
        trials=trials,
        query=req.query,
        disease=req.disease,
        patient_name=req.patient_name or persona.get("name") or "the patient",
        location=effective_location or "Not specified",
        history=history,
        system_prompt_override=personalized_system_prompt,
    )
    stages.synthesis_ms    = round((time.time() - t) * 1000, 1)
    stages.groq_calls_made += 1
    stages.total_ms         = round((time.time() - pipeline_start) * 1000, 1)

    print(f"\n{'='*55}")
    print(f"[Pipeline] Total: {stages.total_ms}ms | Groq calls: {stages.groq_calls_made}")
    print(f"  Funnel: {stages.papers_retrieved}→{stages.papers_after_prefilter}→{stages.papers_after_semantic}→{stages.papers_after_rerank}")
    print(f"  Personalized: {bool(persona.get('user_id'))} | Corrective RAG: {stages.corrective_rag_fired}")
    print(f"{'='*55}\n")

    # ── Assemble final response ───────────────────────────────────────────
    response = QueryResponse(
        session_id=session_id,
        query=req.query,
        disease=req.disease,
        patient_name=req.patient_name or persona.get("name"),
        location=effective_location,
        condition_overview=synthesis["condition_overview"],
        research_insights=synthesis["research_insights"],
        clinical_trials=synthesis["clinical_trials"],
        follow_up_suggestions=synthesis["follow_up_suggestions"],
        sources=synthesis["sources"],
        hyde_queries=hyde.query_variants,
        retrieval_verdict=verdict_val,
        corrective_rag=corrective,
        pipeline=stages,
    )

    # ── Step 13: Persist ──────────────────────────────────────────────────
    await append_message(session_id, "user", {
        "query":   req.query,
        "disease": req.disease,
    })
    await append_message(session_id, "assistant", {
        "condition_overview": synthesis["condition_overview"],
        "papers_count":       len(synthesis["research_insights"]),
        "trials_count":       len(synthesis["clinical_trials"]),
    })

    # Update context summary for future follow-ups
    new_summary = (
        f"Disease: {req.disease}. "
        f"Topics discussed: {prior_context + ' | ' + req.query if prior_context else req.query}. "
        f"Key finding: {synthesis['condition_overview'][:150]}"
    )
    await update_context_summary(session_id, new_summary)

    # Save query history + update behavior signals
    user_id = persona.get("user_id")
    if user_id:
        await update_user_behavior(user_id, req.query, req.disease)
        await save_query_history(
            session_id=session_id,
            user_id=user_id,
            query=req.query,
            disease=req.disease,
            location=effective_location,
            pipeline_data={
                "hyde_queries":          hyde.query_variants,
                "papers_after_rerank":   stages.papers_after_rerank,
                "trials_after_rerank":   stages.trials_after_rerank,
                "retrieval_verdict":     verdict_val,
                "corrective_rag_fired":  stages.corrective_rag_fired,
                "total_ms":              stages.total_ms,
            },
            result_snapshot={
                "condition_overview": synthesis["condition_overview"][:200],
                "insight_titles":     [i.title for i in synthesis["research_insights"][:5]],
            },
        )

    # Cache only non-personalized, non-followup queries
    if not is_followup and not user_id:
        await set_cached(req.query, req.disease, response.model_dump())

    return response
