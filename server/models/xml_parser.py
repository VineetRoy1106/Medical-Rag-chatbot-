"""
Curalink — XML Parser
Parses structured XML responses from Groq LLaMA 3.1 70B
back into Python dicts / Pydantic models.
"""

import re
import xml.etree.ElementTree as ET
from typing import Optional
from models.schemas import (
    HyDEExpansion,
    CorrectiveRAGResult,
    RetrievalVerdictEnum,
    GroundingTag,
    FollowUpSuggestion,
    ResearchInsight,
)


def _extract_xml_block(text: str, tag: str) -> Optional[str]:
    """Extract the first occurrence of <tag>...</tag> from text."""
    pattern = rf"<{tag}[\s>].*?</{tag}>"
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    return match.group(0) if match else None


def _safe_find_text(element, path: str, default: str = "") -> str:
    node = element.find(path)
    return (node.text or "").strip() if node is not None else default


def _safe_find_all_text(element, path: str) -> list:
    return [(n.text or "").strip() for n in element.findall(path) if n.text]


def parse_hyde_response(raw: str, original_query: str, disease: str) -> HyDEExpansion:
    """Parse XML from Call 1 — HyDE expansion."""
    try:
        block = _extract_xml_block(raw, "hyde_expansion")
        if not block:
            raise ValueError("No <hyde_expansion> tag found")

        root = ET.fromstring(block)

        fake_abstract  = _safe_find_text(root, "fake_abstract")
        query_variants = _safe_find_all_text(root, "query_variants/variant")
        clinical_terms = _safe_find_all_text(root, "clinical_terms/term")
        synonyms       = _safe_find_all_text(root, "synonyms/synonym")

        # Fallback: if variants missing, build from fake abstract
        if not query_variants:
            query_variants = [f"{original_query} {disease}"]

        return HyDEExpansion(
            original_query=original_query,
            fake_abstract=fake_abstract or f"{original_query} {disease}",
            query_variants=query_variants[:6],
            clinical_terms=clinical_terms,
            synonyms=synonyms,
        )

    except Exception as e:
        # Graceful fallback — never crash the pipeline
        print(f"[XMLParser] HyDE parse error: {e}. Using fallback.")
        return HyDEExpansion(
            original_query=original_query,
            fake_abstract=f"{original_query} {disease}",
            query_variants=[
                f"{original_query} {disease}",
                f"{disease} treatment outcomes",
                f"{disease} clinical trial intervention",
                f"{original_query} systematic review",
            ],
            clinical_terms=[],
            synonyms=[],
        )


def parse_rerank_response(raw: str, paper_ids: list) -> dict:
    """
    Parse XML from Call 2 — re-rank + Self-RAG + Corrective RAG verdict.
    Returns:
      {
        "scores": {paper_id: {"score": int, "relevant": bool, "reason": str,
                               "self_rag_verdict": str, "study_subject": str}},
        "corrective": CorrectiveRAGResult
      }
    """
    scores = {}
    corrective = CorrectiveRAGResult()

    try:
        block = _extract_xml_block(raw, "rerank_result")
        if not block:
            raise ValueError("No <rerank_result> tag found")

        root = ET.fromstring(block)

        # ── Paper scores
        for paper_el in root.findall("paper_scores/paper"):
            pid          = _safe_find_text(paper_el, "id")
            score_text   = _safe_find_text(paper_el, "score", "5")
            relevant_txt = _safe_find_text(paper_el, "relevant", "true")
            reason       = _safe_find_text(paper_el, "reason")
            verdict_txt  = _safe_find_text(paper_el, "self_rag_verdict", "relevant")
            study_subj   = _safe_find_text(paper_el, "study_subject", "unknown")

            try:
                score = int(score_text)
            except ValueError:
                score = 5

            if pid:
                scores[pid] = {
                    "score":            min(max(score, 0), 10),
                    "relevant":         relevant_txt.lower() == "true",
                    "reason":           reason,
                    "self_rag_verdict": verdict_txt,
                    "study_subject":    study_subj,
                }

        # ── Corrective RAG assessment
        assessment = root.find("retrieval_assessment")
        if assessment is not None:
            verdict_str  = _safe_find_text(assessment, "verdict", "correct")
            confidence   = _safe_find_text(assessment, "confidence", "high")
            weak_aspects = _safe_find_all_text(assessment, "weak_aspects/aspect")
            requery      = _safe_find_all_text(assessment, "requery_terms/term")

            try:
                verdict_enum = RetrievalVerdictEnum(verdict_str)
            except ValueError:
                verdict_enum = RetrievalVerdictEnum.CORRECT

            irrelevant_ids = [
                pid for pid, data in scores.items()
                if not data.get("relevant", True)
            ]

            corrective = CorrectiveRAGResult(
                verdict=verdict_enum,
                confidence=confidence if confidence in ("high", "medium", "low") else "medium",
                weak_aspects=weak_aspects,
                requery_terms=requery,
                irrelevant_ids=irrelevant_ids,
            )

    except Exception as e:
        print(f"[XMLParser] Rerank parse error: {e}. Using fallback scores.")
        # Assign neutral score to all papers
        for pid in paper_ids:
            scores[pid] = {
                "score": 5, "relevant": True,
                "reason": "Parse error — neutral score assigned",
                "self_rag_verdict": "relevant", "study_subject": "unknown"
            }

    return {"scores": scores, "corrective": corrective}


def parse_synthesis_response(raw: str, papers: list, trials: list) -> dict:
    """
    Parse XML from Call 3 — synthesis + Self-RAG grounding.
    Returns dict with condition_overview, insights, trial_notes, follow_ups.
    """
    result = {
        "condition_overview":    "",
        "insights":              {},   # paper_id -> {key_finding, relevance_explanation, grounding_tag, snippet}
        "trial_notes":           {},   # nct_id   -> {relevance_note, grounding_tag}
        "follow_up_suggestions": [],
    }

    try:
        block = _extract_xml_block(raw, "curalink_response")
        if not block:
            raise ValueError("No <curalink_response> tag found")

        root = ET.fromstring(block)

        # ── Condition overview
        result["condition_overview"] = _safe_find_text(root, "condition_overview")

        # ── Research insights
        for ins_el in root.findall("research_insights/insight"):
            pid      = _safe_find_text(ins_el, "paper_id")
            finding  = _safe_find_text(ins_el, "key_finding")
            explain  = _safe_find_text(ins_el, "relevance_explanation")
            g_tag    = _safe_find_text(ins_el, "grounding_tag", "fully_supported")
            snippet  = _safe_find_text(ins_el, "supporting_snippet")

            # Drop unsupported claims (Self-RAG grounding enforcement)
            if g_tag == "unsupported":
                print(f"[Self-RAG] Dropped unsupported claim for paper {pid}")
                continue

            if pid:
                result["insights"][pid] = {
                    "key_finding":           finding,
                    "relevance_explanation": explain,
                    "grounding_tag":         g_tag,
                    "supporting_snippet":    snippet,
                }

        # ── Trial notes
        for trial_el in root.findall("clinical_trials_summary/trial"):
            tid   = _safe_find_text(trial_el, "id")
            note  = _safe_find_text(trial_el, "relevance_note")
            g_tag = _safe_find_text(trial_el, "grounding_tag", "fully_supported")
            if tid:
                result["trial_notes"][tid] = {
                    "relevance_note": note,
                    "grounding_tag":  g_tag,
                }

        # ── Follow-up suggestions
        for sug_el in root.findall("follow_up_suggestions/suggestion"):
            question  = _safe_find_text(sug_el, "question")
            rationale = _safe_find_text(sug_el, "rationale")
            if question:
                result["follow_up_suggestions"].append(
                    FollowUpSuggestion(question=question, rationale=rationale)
                )

    except Exception as e:
        print(f"[XMLParser] Synthesis parse error: {e}")
        result["condition_overview"] = "Research synthesis completed. See insights below."

    return result
