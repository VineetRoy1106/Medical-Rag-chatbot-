"""
Curalink Pipeline — Stage 6: Rerank + Self-RAG + Corrective RAG
Call 2 to Groq LLaMA 3.1 70B.
Scores top-20 papers, flags irrelevant ones (Self-RAG),
outputs retrieval verdict + weak aspects (Corrective RAG).
"""

import os
from typing import List, Tuple
from groq import AsyncGroq
from tenacity import retry, stop_after_attempt, wait_exponential
from models.schemas import (
    PublicationMetadata, ClinicalTrialMetadata,
    CorrectiveRAGResult, StudySubject,
    RERANK_XML_PROMPT
)
from models.xml_parser import parse_rerank_response
from observability.langsmith import traced

client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))


@traced(name="Rerank + Self-RAG + Corrective RAG", metadata={"stage": 6, "call": "groq_llama_70b"})
async def run_rerank(
    papers:   List[PublicationMetadata],
    trials:   List[ClinicalTrialMetadata],
    query:    str,
    disease:  str,
    location: str = "",
    top_k_papers: int = 8,
    top_k_trials: int = 6,
) -> Tuple[List[PublicationMetadata], List[ClinicalTrialMetadata], CorrectiveRAGResult]:
    """
    Call 2 — LLM-based re-ranking with Self-RAG and Corrective RAG.
    Takes top 20 papers from scoring stage, returns top 6-8.
    """

    # Build papers block for prompt
    papers_block = _build_papers_block(papers[:20])

    prompt = RERANK_XML_PROMPT.format(
        disease=disease,
        query=query,
        location=location or "Not specified",
        papers_block=papers_block,
    )

    raw = await _call_groq(prompt)
    parsed = parse_rerank_response(raw, [p.id for p in papers])

    scores_map: dict    = parsed["scores"]
    corrective: CorrectiveRAGResult = parsed["corrective"]

    # ── Apply LLM scores + Self-RAG filtering to papers
    for p in papers:
        if p.id in scores_map:
            data = scores_map[p.id]
            p.llm_relevance_score  = data["score"]
            p.llm_relevance_reason = data["reason"]
            p.is_relevant          = data["relevant"]
            p.self_rag_verdict     = data["self_rag_verdict"]

            # Update study subject from LLM classification if it was UNKNOWN
            if p.study_subject == StudySubject.UNKNOWN:
                subj_str = data.get("study_subject", "unknown")
                p.study_subject = _parse_study_subject(subj_str)
                p.study_subject_weight = _subject_to_weight(p.study_subject)

            # Recompute final score incorporating LLM score
            llm_normalized = (p.llm_relevance_score or 5) / 10.0
            p.final_score  = (
                p.final_score * 0.60 +   # keep existing composite score
                llm_normalized * 0.40    # blend in LLM judgment
            )

    # ── Self-RAG: filter irrelevant papers
    relevant_papers = [p for p in papers if p.is_relevant and (p.llm_relevance_score or 5) >= 3]

    # Sort by final score, take top K
    relevant_papers.sort(key=lambda x: x.final_score, reverse=True)
    final_papers = relevant_papers[:top_k_papers]

    # ── Trials: score by status + semantic (no LLM call needed for trials)
    final_trials = trials[:top_k_trials]

    dropped = len(papers) - len(relevant_papers)
    if dropped:
        print(f"[Self-RAG] Dropped {dropped} irrelevant papers")

    print(f"[Rerank] Final: {len(final_papers)} papers, {len(final_trials)} trials")
    print(f"[Corrective RAG] Verdict: {corrective.verdict}, Confidence: {corrective.confidence}")
    if corrective.weak_aspects:
        print(f"[Corrective RAG] Weak aspects: {corrective.weak_aspects}")

    return final_papers, final_trials, corrective


def _build_papers_block(papers: List[PublicationMetadata]) -> str:
    lines = []
    for p in papers:
        lines.append(
            f"<abstract>\n"
            f"  <id>{p.id}</id>\n"
            f"  <title>{p.title}</title>\n"
            f"  <year>{p.year}</year>\n"
            f"  <source>{p.source}</source>\n"
            f"  <citations>{p.cited_by_count}</citations>\n"
            f"  <study_subject_detected>{p.study_subject}</study_subject_detected>\n"
            f"  <text>{p.abstract[:600]}</text>\n"
            f"</abstract>"
        )
    return "\n".join(lines)


def _parse_study_subject(s: str) -> StudySubject:
    mapping = {
        "human_rct":              StudySubject.HUMAN_RCT,
        "human_cohort":           StudySubject.HUMAN_COHORT,
        "human_case_control":     StudySubject.HUMAN_CASE_CONTROL,
        "human_case_report":      StudySubject.HUMAN_CASE_REPORT,
        "human_systematic_review":StudySubject.HUMAN_SYSTEMATIC,
        "human_meta_analysis":    StudySubject.HUMAN_META,
        "human_observational":    StudySubject.HUMAN_OBSERVATIONAL,
        "animal":                 StudySubject.ANIMAL,
        "in_vitro":               StudySubject.IN_VITRO,
    }
    return mapping.get(s.lower(), StudySubject.UNKNOWN)


def _subject_to_weight(s: StudySubject) -> float:
    weights = {
        StudySubject.HUMAN_RCT:          1.00,
        StudySubject.HUMAN_SYSTEMATIC:   0.95,
        StudySubject.HUMAN_META:         0.92,
        StudySubject.HUMAN_COHORT:       0.80,
        StudySubject.HUMAN_CASE_CONTROL: 0.75,
        StudySubject.HUMAN_OBSERVATIONAL:0.70,
        StudySubject.HUMAN_CASE_REPORT:  0.55,
        StudySubject.UNKNOWN:            0.50,
        StudySubject.ANIMAL:             0.15,
        StudySubject.IN_VITRO:           0.10,
    }
    return weights.get(s, 0.50)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
async def _call_groq(prompt: str) -> str:
    response = await client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a strict medical research evaluator. "
                    "Always respond with valid XML only. "
                    "No preamble, no markdown, no text outside XML tags. "
                    "Apply heavy penalties to animal and in-vitro studies."
                )
            },
            {"role": "user", "content": prompt}
        ],
        temperature=0.1,
        max_tokens=2000,
    )
    return response.choices[0].message.content
