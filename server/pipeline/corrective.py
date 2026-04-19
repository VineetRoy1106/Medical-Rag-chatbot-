"""
Curalink Pipeline — Stage 7: Corrective RAG
Fires only when rerank verdict is 'ambiguous' or 'incorrect'.
Performs targeted re-retrieval for weak aspects.
"""

from typing import List, Tuple
from models.schemas import (
    PublicationMetadata, ClinicalTrialMetadata,
    CorrectiveRAGResult, RetrievalVerdictEnum
)
from pipeline.retrieval import run_retrieval
from pipeline.embedder import run_embedding, run_scoring
from observability.langsmith import traced


@traced(name="Corrective RAG Re-retrieval", metadata={"stage": 7, "conditional": True})
async def run_corrective_rag(
    corrective:      CorrectiveRAGResult,
    existing_papers: List[PublicationMetadata],
    existing_trials: List[ClinicalTrialMetadata],
    disease:         str,
    query:           str,
    location:        str = "",
) -> Tuple[List[PublicationMetadata], List[ClinicalTrialMetadata], CorrectiveRAGResult]:
    """
    Conditional stage — only runs when verdict is ambiguous or incorrect.
    Fetches additional papers for weak aspects, merges with existing results.
    """

    if corrective.verdict == RetrievalVerdictEnum.CORRECT:
        print("[Corrective RAG] Verdict CORRECT — skipping re-retrieval")
        return existing_papers, existing_trials, corrective

    print(f"[Corrective RAG] Verdict: {corrective.verdict} — triggering re-retrieval")
    corrective.fired = True

    # Build targeted queries from weak aspects + requery terms
    targeted_queries = []
    for aspect in corrective.weak_aspects[:3]:
        targeted_queries.append(f"{disease} {aspect}")
    for term in corrective.requery_terms[:2]:
        targeted_queries.append(term)

    if not targeted_queries:
        targeted_queries = [f"{disease} {query} comprehensive review"]

    print(f"[Corrective RAG] Re-querying with: {targeted_queries}")

    # Re-retrieve with targeted queries
    new_papers, new_trials = await run_retrieval(
        query_variants=targeted_queries,
        disease=disease,
        original_query=query,
        location=location,
    )

    corrective.reretrieval_count = len(new_papers)

    # Merge: combine existing + new, deduplicate
    existing_ids = {p.id for p in existing_papers}
    merged_papers = list(existing_papers)
    for p in new_papers:
        if p.id not in existing_ids:
            merged_papers.append(p)
            existing_ids.add(p.id)

    existing_trial_ids = {t.id for t in existing_trials}
    merged_trials = list(existing_trials)
    for t in new_trials:
        if t.id not in existing_trial_ids:
            merged_trials.append(t)
            existing_trial_ids.add(t.id)

    # Re-score the merged pool
    merged_papers, merged_trials = await run_scoring(
        merged_papers, merged_trials, query, disease, location
    )

    # Re-embed merged pool to rerank by semantic relevance
    merged_papers, merged_trials = await run_embedding(
        merged_papers, merged_trials, query, disease,
        top_k_papers=20, top_k_trials=15
    )

    print(f"[Corrective RAG] After merge: {len(merged_papers)} papers, {len(merged_trials)} trials")
    return merged_papers, merged_trials, corrective
