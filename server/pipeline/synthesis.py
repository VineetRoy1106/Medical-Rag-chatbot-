"""
Curalink Pipeline — Stage 8: Synthesis + Self-RAG Grounding
Call 3 to Groq LLaMA 3.1 70B.
Generates structured XML response, enforces grounding — removes unsupported claims.
"""

import os
from typing import List
from groq import AsyncGroq
from tenacity import retry, stop_after_attempt, wait_exponential
from models.schemas import (
    PublicationMetadata, ClinicalTrialMetadata,
    ResearchInsight, FollowUpSuggestion,
    GroundingTag, SYNTHESIS_XML_PROMPT
)
from models.xml_parser import parse_synthesis_response
from observability.langsmith import traced

client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))


@traced(name="Synthesis + Self-RAG Grounding", metadata={"stage": 8, "call": "groq_llama_70b"})
async def run_synthesis(
    papers:       List[PublicationMetadata],
    trials:       List[ClinicalTrialMetadata],
    query:        str,
    disease:      str,
    patient_name: str = "the patient",
    location:     str = "Not specified",
    history:      list = None,
    system_prompt_override: str = None,
) -> dict:
    """
    Call 3 — Generate structured response grounded in retrieved sources.
    Self-RAG: drops any claim tagged [unsupported].
    Returns structured dict ready for QueryResponse assembly.
    """

    papers_block = _build_papers_block(papers)
    trials_block = _build_trials_block(trials)
    history_block = _build_history_block(history or [])

    prompt = SYNTHESIS_XML_PROMPT.format(
        patient_name=patient_name or "the patient",
        disease=disease,
        query=query,
        location=location or "Not specified",
        papers_block=papers_block,
        trials_block=trials_block,
        history_block=history_block,
    )

    raw = await _call_groq(prompt, system_prompt_override=system_prompt_override)
    parsed = parse_synthesis_response(raw, papers, trials)

    # ── Assemble ResearchInsight objects
    research_insights = []
    for paper in papers:
        insight_data = parsed["insights"].get(paper.id)
        if not insight_data:
            continue

        # Self-RAG: skip unsupported claims
        if insight_data.get("grounding_tag") == "unsupported":
            print(f"[Self-RAG Grounding] Dropped unsupported insight for: {paper.title[:60]}")
            continue

        research_insights.append(ResearchInsight(
            paper_id=paper.id,
            title=paper.title,
            key_finding=insight_data.get("key_finding", ""),
            relevance_explanation=insight_data.get("relevance_explanation", ""),
            study_type=paper.publication_type or "research-article",
            study_subject=paper.study_subject.value if hasattr(paper.study_subject, 'value') else str(paper.study_subject),
            year=paper.year,
            source=paper.source.value if hasattr(paper.source, 'value') else str(paper.source),
            url=paper.url,
            authors=paper.authors[:5],
            journal=paper.journal,
            confidence_score=round(paper.final_score, 3),
            grounding_tag=insight_data.get("grounding_tag", "fully_supported"),
            supporting_snippet=insight_data.get("supporting_snippet"),
            cited_by_count=paper.cited_by_count,
            is_open_access=paper.is_open_access,
        ))

    # ── Apply trial notes from LLM
    for trial in trials:
        note_data = parsed["trial_notes"].get(trial.nct_id) or parsed["trial_notes"].get(trial.id)
        if note_data:
            trial.relevance_note = note_data.get("relevance_note", "")

    # ── Build sources list (full attribution)
    sources = _build_sources(papers, research_insights)

    return {
        "condition_overview":    parsed["condition_overview"],
        "research_insights":     research_insights,
        "clinical_trials":       trials,
        "follow_up_suggestions": parsed["follow_up_suggestions"],
        "sources":               sources,
    }


def _build_papers_block(papers: List[PublicationMetadata]) -> str:
    lines = []
    for p in papers:
        authors_str = "; ".join(p.authors[:4]) + (" et al." if len(p.authors) > 4 else "")
        lines.append(
            f"<paper>\n"
            f"  <id>{p.id}</id>\n"
            f"  <title>{p.title}</title>\n"
            f"  <authors>{authors_str}</authors>\n"
            f"  <journal>{p.journal or 'Unknown'}</journal>\n"
            f"  <year>{p.year}</year>\n"
            f"  <study_subject>{p.study_subject}</study_subject>\n"
            f"  <publication_type>{p.publication_type or 'research-article'}</publication_type>\n"
            f"  <citations>{p.cited_by_count}</citations>\n"
            f"  <open_access>{p.is_open_access}</open_access>\n"
            f"  <final_score>{round(p.final_score, 3)}</final_score>\n"
            f"  <llm_relevance_score>{p.llm_relevance_score or 'N/A'}</llm_relevance_score>\n"
            f"  <url>{p.url}</url>\n"
            f"  <abstract>{p.abstract[:800]}</abstract>\n"
            f"</paper>"
        )
    return "\n".join(lines)


def _build_trials_block(trials: List[ClinicalTrialMetadata]) -> str:
    lines = []
    for t in trials:
        loc_str = "; ".join(
            f"{l.city or ''} {l.country or ''}".strip()
            for l in t.locations[:5]
        )
        contact_str = "; ".join(
            f"{c.name or ''} ({c.email or c.phone or ''})"
            for c in t.contacts[:2]
        )
        lines.append(
            f"<trial>\n"
            f"  <id>{t.nct_id}</id>\n"
            f"  <title>{t.title}</title>\n"
            f"  <status>{t.status}</status>\n"
            f"  <phase>{t.phase or 'N/A'}</phase>\n"
            f"  <conditions>{'; '.join(t.conditions)}</conditions>\n"
            f"  <interventions>{'; '.join(t.interventions)}</interventions>\n"
            f"  <locations>{loc_str}</locations>\n"
            f"  <contacts>{contact_str}</contacts>\n"
            f"  <eligibility_summary>{(t.eligibility.criteria_text or '')[:300]}</eligibility_summary>\n"
            f"  <url>{t.url}</url>\n"
            f"  <summary>{t.brief_summary or ''}</summary>\n"
            f"</trial>"
        )
    return "\n".join(lines)


def _build_history_block(history: list) -> str:
    if not history:
        return "No prior conversation."
    lines = []
    for msg in history[-8:]:
        role    = msg.get("role", "user")
        content = msg.get("content", {})
        if isinstance(content, dict):
            text = content.get("query", content.get("condition_overview", str(content)))[:200]
        else:
            text = str(content)[:200]
        lines.append(f"{role.upper()}: {text}")
    return "\n".join(lines)


def _build_sources(papers: List[PublicationMetadata], insights: List[ResearchInsight]) -> list:
    insight_ids = {i.paper_id for i in insights}
    sources = []
    for p in papers:
        if p.id not in insight_ids:
            continue
        insight = next((i for i in insights if i.paper_id == p.id), None)
        sources.append({
            "title":    p.title,
            "authors":  p.authors[:5],
            "year":     p.year,
            "platform": p.source.value if hasattr(p.source, 'value') else str(p.source),
            "url":      p.url,
            "snippet":  insight.supporting_snippet if insight else (p.abstract[:150] + "..."),
            "doi":      p.doi,
            "pmid":     p.pmid,
            "journal":  p.journal,
            "study_subject": p.study_subject.value if hasattr(p.study_subject, 'value') else str(p.study_subject),
            "cited_by_count": p.cited_by_count,
            "is_open_access": p.is_open_access,
        })
    return sources


# @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
# async def _call_groq(prompt: str, system_prompt_override: str = None) -> str:
#     system = system_prompt_override or (
#         ""You are Curalink, a warm and compassionate AI medical research assistant who genuinely cares about patients. "
#             "You speak like a knowledgeable friend — clear, human, supportive — never cold or robotic. "
#             "Always address the patient by name and acknowledge the difficulty of their situation. "
#             "Respond ONLY with valid XML. No preamble, no markdown. "
#             "Every claim must be directly supported by the provided abstracts. "
#             "Filter clinical trials strictly by the patient location provided. "
#             "Tag unsupported claims as <grounding_tag>unsupported</grounding_tag> — they will be removed.""
#     )
#     response = await client.chat.completions.create(
#         model="meta-llama/llama-4-scout-17b-16e-instruct",
#         messages=[
#             {"role": "system", "content": system},
#             {"role": "user",   "content": prompt}
#         ],
#         temperature=0.2,
#         max_tokens=3000,
#     )
#     return response.choices[0].message.content



@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=4, max=30))
async def _call_groq(prompt: str, system_prompt_override: str = None) -> str:
    system = system_prompt_override or (
        "You are Curalink, a warm and compassionate AI medical research assistant who genuinely cares about patients. "
        "You speak like a knowledgeable friend — clear, human, supportive — never cold or robotic. "
        "Always address the patient by name and acknowledge the difficulty of their situation. "
        "Respond ONLY with valid XML. No preamble, no markdown. "
        "Every claim must be directly supported by the provided abstracts. "
        "Filter clinical trials strictly by the patient location provided. "
        "Tag unsupported claims as <grounding_tag>unsupported</grounding_tag> — they will be removed."
    )
    response = await client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt}
        ],
        temperature=0.2,
        max_tokens=3000,
    )
    return response.choices[0].message.content