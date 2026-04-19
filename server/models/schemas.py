"""
Curalink — Rich Metadata Schemas
All pipeline data flows through these Pydantic models.
LLM responses use XML tags for reliability, parsed back into these models.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Literal
from datetime import datetime
from enum import Enum


# ── Enums ──────────────────────────────────────────────────────────────────

class StudySubject(str, Enum):
    HUMAN_RCT            = "human_rct"
    HUMAN_COHORT         = "human_cohort"
    HUMAN_CASE_CONTROL   = "human_case_control"
    HUMAN_CASE_REPORT    = "human_case_report"
    HUMAN_SYSTEMATIC     = "human_systematic_review"
    HUMAN_META           = "human_meta_analysis"
    HUMAN_OBSERVATIONAL  = "human_observational"
    ANIMAL               = "animal"
    IN_VITRO             = "in_vitro"
    UNKNOWN              = "unknown"

class StudySubjectWeight(float, Enum):
    human_rct                   = 1.00
    human_systematic_review     = 0.95
    human_meta_analysis         = 0.92
    human_cohort                = 0.80
    human_case_control          = 0.75
    human_observational         = 0.70
    human_case_report           = 0.55
    unknown                     = 0.50
    animal                      = 0.15
    in_vitro                    = 0.10

class TrialStatus(str, Enum):
    RECRUITING              = "RECRUITING"
    ACTIVE_NOT_RECRUITING   = "ACTIVE_NOT_RECRUITING"
    COMPLETED               = "COMPLETED"
    ENROLLING_BY_INVITATION = "ENROLLING_BY_INVITATION"
    NOT_YET_RECRUITING      = "NOT_YET_RECRUITING"
    SUSPENDED               = "SUSPENDED"
    TERMINATED              = "TERMINATED"
    WITHDRAWN               = "WITHDRAWN"
    UNKNOWN                 = "UNKNOWN"

class RetrievalVerdictEnum(str, Enum):
    CORRECT    = "correct"
    AMBIGUOUS  = "ambiguous"
    INCORRECT  = "incorrect"

class GroundingTag(str, Enum):
    FULLY_SUPPORTED     = "fully_supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED         = "unsupported"

class DataSource(str, Enum):
    PUBMED         = "pubmed"
    OPENALEX       = "openalex"
    CLINICALTRIALS = "clinicaltrials"


# ── Query Request ──────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query:        str            = Field(...,  min_length=3,  max_length=500,  example="Deep Brain Stimulation treatment outcomes")
    disease:      str            = Field(...,  min_length=2,  max_length=200,  example="Parkinson's disease")
    patient_name: Optional[str] = Field(None, max_length=100, example="John Smith")
    location:     Optional[str] = Field(None, max_length=100, example="Toronto, Canada")
    session_id:   Optional[str] = Field(None, description="Existing session ID for follow-up queries")
    user_id:      Optional[str] = Field(None, description="User ID to load personalization profile from MongoDB")

    @field_validator("query")
    @classmethod
    def query_not_empty(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Query cannot be empty or whitespace")
        return v

    @field_validator("disease")
    @classmethod
    def disease_not_empty(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Disease cannot be empty or whitespace")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "query":        "Deep Brain Stimulation treatment outcomes",
                "disease":      "Parkinson's disease",
                "patient_name": "John Smith",
                "location":     "Toronto, Canada",
                "session_id":   None,
                "user_id":      "user_john_001",
            }
        }


# ── HyDE Expansion ─────────────────────────────────────────────────────────

class HyDEExpansion(BaseModel):
    original_query:   str
    fake_abstract:    str
    query_variants:   List[str]
    clinical_terms:   List[str]   = []
    synonyms:         List[str]   = []
    is_followup:      bool        = False
    injected_context: Optional[str] = None


# ── Publication Metadata ───────────────────────────────────────────────────

class PublicationMetadata(BaseModel):
    # ── Identity
    id:                   str
    doi:                  Optional[str] = None
    pmid:                 Optional[str] = None
    openalex_id:          Optional[str] = None
    source:               DataSource

    # ── Core content
    title:                str
    abstract:             str
    authors:              List[str]      = []
    journal:              Optional[str]  = None
    year:                 int
    publication_date:     Optional[str]  = None
    url:                  str

    # ── Study classification
    study_subject:        StudySubject   = StudySubject.UNKNOWN
    study_subject_weight: float          = 0.50
    publication_type:     Optional[str]  = None
    mesh_terms:           List[str]      = []
    keywords:             List[str]      = []

    # ── Credibility signals
    cited_by_count:       int            = 0
    is_open_access:       bool           = False
    is_peer_reviewed:     bool           = True

    # ── Scoring (populated through pipeline stages)
    semantic_score:       float          = 0.0
    recency_score:        float          = 0.0
    recency_weight:       float          = 0.25
    citation_score:       float          = 0.0
    final_score:          float          = 0.0

    # ── LLM judgments (Call 2)
    llm_relevance_score:  Optional[int]  = None
    llm_relevance_reason: Optional[str]  = None
    is_relevant:          bool           = True
    self_rag_verdict:     Optional[str]  = None

    # ── Grounding (Call 3)
    grounding_tag:        Optional[GroundingTag] = None
    supporting_snippet:   Optional[str]  = None

    # ── Pipeline provenance
    retrieved_by_query:   Optional[str]  = None
    rank_in_source:       Optional[int]  = None


# ── Clinical Trial Metadata ────────────────────────────────────────────────

class TrialContact(BaseModel):
    name:  Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role:  Optional[str] = None

class TrialLocation(BaseModel):
    facility: Optional[str] = None
    city:     Optional[str] = None
    state:    Optional[str] = None
    country:  Optional[str] = None
    zip:      Optional[str] = None

class TrialEligibility(BaseModel):
    min_age:       Optional[str] = None
    max_age:       Optional[str] = None
    gender:        Optional[str] = "All"
    criteria_text: Optional[str] = None
    inclusion:     List[str]     = []
    exclusion:     List[str]     = []

class ClinicalTrialMetadata(BaseModel):
    # ── Identity
    id:              str
    nct_id:          str
    source:          DataSource = DataSource.CLINICALTRIALS
    url:             str

    # ── Core content
    title:           str
    brief_summary:   Optional[str]     = None
    conditions:      List[str]         = []
    interventions:   List[str]         = []
    keywords:        List[str]         = []

    # ── Status
    status:          TrialStatus       = TrialStatus.UNKNOWN
    phase:           Optional[str]     = None
    start_date:      Optional[str]     = None
    completion_date: Optional[str]     = None
    enrollment:      Optional[int]     = None

    # ── Eligibility
    eligibility:     TrialEligibility  = Field(default_factory=TrialEligibility)

    # ── Location
    locations:       List[TrialLocation] = []
    contacts:        List[TrialContact]  = []

    # ── Scoring
    semantic_score:  float             = 0.0
    status_score:    float             = 0.0
    location_score:  float             = 0.0
    final_score:     float             = 0.0

    # ── LLM judgment
    llm_relevance_score: Optional[int] = None
    is_relevant:         bool          = True
    supporting_snippet:  Optional[str] = None
    relevance_note:      Optional[str] = None


# ── Corrective RAG ─────────────────────────────────────────────────────────

class CorrectiveRAGResult(BaseModel):
    verdict:           RetrievalVerdictEnum = RetrievalVerdictEnum.CORRECT
    confidence:        Literal["high", "medium", "low"] = "high"
    weak_aspects:      List[str] = []
    irrelevant_ids:    List[str] = []
    requery_terms:     List[str] = []
    fired:             bool      = False
    reretrieval_count: int       = 0


# ── Research Insight (final per-paper output) ─────────────────────────────

class ResearchInsight(BaseModel):
    paper_id:              str
    title:                 str
    key_finding:           str
    relevance_explanation: str
    study_type:            str
    study_subject:         str
    year:                  int
    source:                str
    url:                   str
    authors:               List[str]     = []
    journal:               Optional[str] = None
    confidence_score:      float         = 0.0
    grounding_tag:         str           = "fully_supported"
    supporting_snippet:    Optional[str] = None
    cited_by_count:        int           = 0
    is_open_access:        bool          = False


# ── Follow-up Suggestions ─────────────────────────────────────────────────

class FollowUpSuggestion(BaseModel):
    question:  str
    rationale: str


# ── Pipeline Timings ──────────────────────────────────────────────────────

class PipelineStages(BaseModel):
    hyde_expansion_ms:      Optional[float] = None
    retrieval_ms:           Optional[float] = None
    prefilter_ms:           Optional[float] = None
    embedding_ms:           Optional[float] = None
    scoring_ms:             Optional[float] = None
    rerank_ms:              Optional[float] = None
    corrective_rag_ms:      Optional[float] = None
    synthesis_ms:           Optional[float] = None
    total_ms:               Optional[float] = None
    groq_calls_made:        int  = 0
    corrective_rag_fired:   bool = False
    papers_retrieved:       int  = 0
    papers_after_prefilter: int  = 0
    papers_after_semantic:  int  = 0
    papers_after_rerank:    int  = 0
    trials_retrieved:       int  = 0
    trials_after_rerank:    int  = 0


# ── Full Query Response ───────────────────────────────────────────────────

class QueryResponse(BaseModel):
    session_id:            str
    query:                 str
    disease:               str
    patient_name:          Optional[str]         = None
    location:              Optional[str]          = None
    condition_overview:    str
    research_insights:     List[ResearchInsight]
    clinical_trials:       List[ClinicalTrialMetadata]
    follow_up_suggestions: List[FollowUpSuggestion]
    sources:               List[dict]             = []
    hyde_queries:          List[str]              = []
    retrieval_verdict:     str                    = "correct"
    corrective_rag:        CorrectiveRAGResult    = Field(default_factory=CorrectiveRAGResult)
    pipeline:              PipelineStages         = Field(default_factory=PipelineStages)
    timestamp:             datetime               = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


# ── XML Prompt Templates ──────────────────────────────────────────────────

HYDE_XML_PROMPT = """\
You are a medical research expert. Generate a HyDE (Hypothetical Document Embedding) expansion.

User query : {query}
Disease    : {disease}
{context_block}

Return ONLY this XML — no preamble, no explanation, no markdown:

<hyde_expansion>
  <fake_abstract>
    Write exactly 120 words: the abstract of the ideal research paper answering this query.
    Use expert clinical vocabulary. Include synonyms and technical terms naturally.
  </fake_abstract>
  <query_variants>
    <variant type="clinical_term">exact clinical terminology variant here</variant>
    <variant type="mechanism">biological mechanism / pathway variant here</variant>
    <variant type="outcome_focused">patient outcomes / quality of life variant here</variant>
    <variant type="trial_language">trial / intervention / efficacy language variant here</variant>
  </query_variants>
  <clinical_terms>
    <term>term1</term>
    <term>term2</term>
  </clinical_terms>
  <synonyms>
    <synonym>synonym1</synonym>
    <synonym>synonym2</synonym>
  </synonyms>
</hyde_expansion>"""

RERANK_XML_PROMPT = """\
You are a medical research evaluator. Score each abstract for clinical relevance.

Disease          : {disease}
Query            : {query}
Patient location : {location}

SCORING RULES (strict):
- Human RCT or systematic review about {disease} + query topic = 8-10
- Human observational / cohort study                           = 6-7
- Human case report                                            = 4-5
- Animal study                                                 = 1-2 (heavy penalty)
- In vitro / cell line                                         = 0-1 (heavy penalty)
- Unrelated to query despite keyword match                     = 0

{papers_block}

Return ONLY this XML — no preamble, no markdown:

<rerank_result>
  <paper_scores>
    <paper>
      <id>PAPER_ID</id>
      <score>0-10</score>
      <relevant>true|false</relevant>
      <study_subject>human_rct|human_cohort|human_case_report|human_systematic_review|human_meta_analysis|human_observational|animal|in_vitro|unknown</study_subject>
      <reason>One sentence explaining the score</reason>
      <self_rag_verdict>relevant|irrelevant</self_rag_verdict>
    </paper>
  </paper_scores>
  <retrieval_assessment>
    <verdict>correct|ambiguous|incorrect</verdict>
    <confidence>high|medium|low</confidence>
    <weak_aspects>
      <aspect>Describe what topic is poorly covered if any</aspect>
    </weak_aspects>
    <requery_terms>
      <term>new search term to fill gaps</term>
    </requery_terms>
  </retrieval_assessment>
</rerank_result>"""

SYNTHESIS_XML_PROMPT = """\
You are Curalink, an expert AI medical research assistant.
Generate a structured response using ONLY the provided research data.
DO NOT add any information not present in the sources. Every claim must be grounded.

Patient context:
  Name    : {patient_name}
  Disease : {disease}
  Query   : {query}
  Location: {location}

Research papers:
{papers_block}

Clinical trials:
{trials_block}

Prior conversation:
{history_block}

Return ONLY this XML — no preamble, no markdown:

<curalink_response>
  <condition_overview>
    DIRECTLY answer "{query}" — do not acknowledge the question, just answer it.
    NEVER say "I couldn't find" and stop there — always give the best available answer from papers.
    NEVER open with "Hi [name], I see/understand you are..." — vary every single response.
    Use these openers based on query type:
    - Trials: "Looking at trials near {location}... [list what exists or nearest options with city names]"
    - Eligibility: "For {disease} trials, the typical criteria include... [list real criteria from papers]"
    - Treatments: "{location} has access to... [name specific drugs like pembrolizumab, osimertinib]"
    - Supplements: "Research shows... [lead with actual finding, then caveat]"
    - General: Lead with the single most useful finding immediately — no filler.
    If no trials in {location}: name the NEAREST available trials with their actual city and country.
    ALWAYS answer with real specifics from the papers — never give generic placeholder answers.
    Use {patient_name} naturally once mid-response, not always at the very start.
  </condition_overview>

  <research_insights>
    <insight>
      <paper_id>PAPER_ID</paper_id>
      <key_finding>One clear sentence: what this paper found relevant to the query</key_finding>
      <relevance_explanation>Why this matters specifically for this patient and query</relevance_explanation>
      <grounding_tag>fully_supported|partially_supported|unsupported</grounding_tag>
      <supporting_snippet>Exact short phrase from abstract supporting this finding</supporting_snippet>
    </insight>
  </research_insights>

  <clinical_trials_summary>
    <trial>
      <id>NCT_ID</id>
      <relevance_note>Why this trial is relevant to this patient specifically</relevance_note>
      <grounding_tag>fully_supported|partially_supported</grounding_tag>
    </trial>
  </clinical_trials_summary>

  <follow_up_suggestions>
    <suggestion>
      <question>Specific follow-up question the patient should ask next</question>
      <rationale>Why this question is important given what was found</rationale>
    </suggestion>
    <suggestion>
      <question>Second specific follow-up question</question>
      <rationale>Rationale for second question</rationale>
    </suggestion>
    <suggestion>
      <question>Third specific follow-up question</question>
      <rationale>Rationale for third question</rationale>
    </suggestion>
  </follow_up_suggestions>
</curalink_response>"""
