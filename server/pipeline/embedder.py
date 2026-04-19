"""
Curalink Pipeline — Stages 3-5: Pre-filter, Embed, Score
Stage 3: Hard rules pre-filter (no abstract, too old, etc.)
Stage 4: Sentence transformer semantic ranking
Stage 5: Multi-signal composite scoring
"""

import re
import numpy as np
from typing import List, Tuple
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from models.schemas import (
    PublicationMetadata, ClinicalTrialMetadata,
    StudySubject, TrialStatus
)
from observability.langsmith import traced

# Load model once at module level — reused across all requests
_embedder = None

def get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        print("[Embedder] Loading all-MiniLM-L6-v2...")
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
        print("[Embedder] Model loaded")
    return _embedder


# ── Stage 3: Pre-filter ───────────────────────────────────────────────────

@traced(name="Pre-filter", metadata={"stage": 3})
async def run_prefilter(
    papers: List[PublicationMetadata],
    trials: List[ClinicalTrialMetadata],
    disease: str,
    min_year: int = 2010,
    allowed_study_subjects: list = None,
) -> Tuple[List[PublicationMetadata], List[ClinicalTrialMetadata]]:
    """Hard rules filter — remove clearly unusable results."""

    filtered_papers = []
    for p in papers:
        if not p.abstract or len(p.abstract) < 80:
            continue
        if not p.title or len(p.title) < 10:
            continue
        if p.year < min_year:
            continue
        if not p.url:
            continue
        # Respect user study type preferences
        if allowed_study_subjects:
            subj_val = p.study_subject.value if hasattr(p.study_subject, "value") else str(p.study_subject)
            if subj_val not in allowed_study_subjects:
                continue
        filtered_papers.append(p)

    filtered_trials = []
    for t in trials:
        # Must have title
        if not t.title:
            continue
        # Must have eligibility criteria (key for usefulness)
        if not t.eligibility.criteria_text and not t.eligibility.inclusion:
            continue
        # Skip withdrawn/terminated
        if t.status in (TrialStatus.WITHDRAWN, TrialStatus.TERMINATED):
            continue
        filtered_trials.append(t)

    print(f"[Pre-filter] Papers: {len(papers)} → {len(filtered_papers)}")
    print(f"[Pre-filter] Trials: {len(trials)} → {len(filtered_trials)}")
    return filtered_papers, filtered_trials


# ── Stage 4: Semantic Embedding ───────────────────────────────────────────

@traced(name="Semantic Embedding", metadata={"stage": 4})
async def run_embedding(
    papers: List[PublicationMetadata],
    trials: List[ClinicalTrialMetadata],
    query: str,
    disease: str,
    top_k_papers: int = 25,
    top_k_trials: int = 20,
) -> Tuple[List[PublicationMetadata], List[ClinicalTrialMetadata]]:
    """
    Batch embed query + all abstracts in one pass.
    Sort by cosine similarity — pure semantic, no keyword bias.
    """
    model = get_embedder()

    # Enrich query with disease for better embedding
    enriched_query = f"{query} {disease} treatment outcomes research"

    # ── Embed papers
    if papers:
        paper_texts = [f"{p.title}. {p.abstract[:400]}" for p in papers]
        all_texts   = [enriched_query] + paper_texts

        embeddings = model.encode(all_texts, batch_size=64, show_progress_bar=False)
        query_emb  = embeddings[0:1]
        paper_embs = embeddings[1:]

        sims = cosine_similarity(query_emb, paper_embs)[0]

        for i, p in enumerate(papers):
            p.semantic_score = float(sims[i])

        papers.sort(key=lambda x: x.semantic_score, reverse=True)
        papers = papers[:top_k_papers]
        print(f"[Embedding] Top paper score: {papers[0].semantic_score:.3f}")

    # ── Embed trials
    if trials:
        trial_texts = [
            f"{t.title}. {t.brief_summary or ''} {' '.join(t.conditions)} {' '.join(t.interventions)}"
            for t in trials
        ]
        all_trial_texts = [enriched_query] + trial_texts
        trial_embeddings = model.encode(all_trial_texts, batch_size=64, show_progress_bar=False)
        query_emb_t      = trial_embeddings[0:1]
        trial_embs       = trial_embeddings[1:]

        trial_sims = cosine_similarity(query_emb_t, trial_embs)[0]
        for i, t in enumerate(trials):
            t.semantic_score = float(trial_sims[i])

        trials.sort(key=lambda x: x.semantic_score, reverse=True)
        trials = trials[:top_k_trials]

    print(f"[Embedding] {len(papers)} papers, {len(trials)} trials after semantic filter")
    return papers, trials


# ── Stage 5: Multi-signal Scoring ─────────────────────────────────────────

@traced(name="Multi-signal Scoring", metadata={"stage": 5})
async def run_scoring(
    papers: List[PublicationMetadata],
    trials: List[ClinicalTrialMetadata],
    query: str,
    disease: str,
    location: str = "",
) -> Tuple[List[PublicationMetadata], List[ClinicalTrialMetadata]]:
    """
    Composite scoring formula:
      semantic    × 0.40   (cosine similarity)
      study_type  × 0.25   (human > animal penalty)
      recency     × dynamic (fast vs slow moving field)
      citations   × 0.10
      open_access × 0.05
    """
    recency_weight = _get_recency_weight(query, disease)

    for p in papers:
        p.recency_weight = recency_weight
        p.recency_score  = _recency_score(p.year)
        p.citation_score = _citation_score(p.cited_by_count)

        p.final_score = (
            p.semantic_score          * 0.40 +
            p.study_subject_weight    * 0.25 +
            p.recency_score           * recency_weight +
            p.citation_score          * 0.10 +
            (0.05 if p.is_open_access else 0.0)
        )

    # Normalize so final_score sums make sense
    papers.sort(key=lambda x: x.final_score, reverse=True)

    # Trial scoring
    location_lower = location.lower()
    for t in trials:
        t.status_score   = _trial_status_score(t.status)
        t.location_score = _trial_location_score(t, location_lower)

        t.final_score = (
            t.semantic_score  * 0.50 +
            t.status_score    * 0.30 +
            t.location_score  * 0.20
        )

    trials.sort(key=lambda x: x.final_score, reverse=True)

    print(f"[Scoring] Papers scored. Top final_score: {papers[0].final_score:.3f}" if papers else "[Scoring] No papers")
    return papers, trials


# ── Helpers ───────────────────────────────────────────────────────────────

def _recency_score(year: int) -> float:
    age = 2025 - year
    if age <= 1:  return 1.00
    if age <= 2:  return 0.92
    if age <= 4:  return 0.80
    if age <= 7:  return 0.65
    if age <= 12: return 0.45
    if age <= 20: return 0.30
    return 0.15

def _get_recency_weight(query: str, disease: str) -> float:
    """
    Fast-moving fields (immunotherapy, gene therapy, AI) → high recency weight.
    Stable fields (aspirin, insulin, established drugs) → low recency weight.
    """
    text = (query + " " + disease).lower()
    if re.search(r"immunotherapy|gene therapy|crispr|car-?t|mrna|ai diagnosis|machine learning", text):
        return 0.35
    if re.search(r"aspirin|metformin|insulin|levodopa|established|classic", text):
        return 0.12
    return 0.25

def _citation_score(cited_by: int) -> float:
    if cited_by >= 1000: return 1.0
    if cited_by >= 500:  return 0.85
    if cited_by >= 100:  return 0.65
    if cited_by >= 50:   return 0.50
    if cited_by >= 10:   return 0.30
    return 0.10

def _trial_status_score(status: TrialStatus) -> float:
    return {
        TrialStatus.RECRUITING:              1.00,
        TrialStatus.ENROLLING_BY_INVITATION: 0.90,
        TrialStatus.ACTIVE_NOT_RECRUITING:   0.75,
        TrialStatus.NOT_YET_RECRUITING:      0.65,
        TrialStatus.COMPLETED:               0.55,
        TrialStatus.SUSPENDED:               0.20,
        TrialStatus.UNKNOWN:                 0.30,
    }.get(status, 0.30)

def _trial_location_score(trial: ClinicalTrialMetadata, location_lower: str) -> float:
    if not location_lower:
        return 0.5
    location_words = set(location_lower.split())
    for loc in trial.locations:
        loc_text = " ".join(filter(None, [
            loc.city, loc.state, loc.country
        ])).lower()
        if location_words & set(loc_text.split()):
            return 1.0
    return 0.2
