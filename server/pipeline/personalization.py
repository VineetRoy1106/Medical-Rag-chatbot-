"""
Curalink — Personalization Engine
Adapts every stage of the pipeline based on user profile stored in MongoDB.

Touches:
  - Scoring weights (study type preferences)
  - Trial location boosting
  - Synthesis prompt (language level, personal disease context)
  - Follow-up suggestions (based on prior session topics)
  - Animal study filtering (user preference)
"""

from typing import List, Optional
from models.schemas import PublicationMetadata, ClinicalTrialMetadata, StudySubject


def apply_personalization_to_scoring(
    papers:  List[PublicationMetadata],
    trials:  List[ClinicalTrialMetadata],
    context: dict,
) -> tuple:
    """
    Adjust final_score on papers and trials based on user preferences.
    Called after run_scoring(), before rerank.
    """
    preferred_types   = set(context.get("preferred_study_types", []))
    show_animal       = context.get("show_animal_studies", False)
    user_location     = context.get("location", "").lower()
    location_bias     = context.get("location_bias_trials", True)
    bookmarked_ids    = set(context.get("bookmarked_ids", []))

    filtered_papers = []
    for p in papers:
        subject_val = p.study_subject.value if hasattr(p.study_subject, "value") else str(p.study_subject)

        # Hard filter: remove animal/in-vitro if user opted out
        if not show_animal and subject_val in ("animal", "in_vitro"):
            continue

        # Boost preferred study types
        if subject_val in preferred_types:
            p.final_score = min(p.final_score + 0.08, 1.0)

        # Slight boost for already-bookmarked papers (familiar territory)
        if p.id in bookmarked_ids:
            p.final_score = min(p.final_score + 0.03, 1.0)

        filtered_papers.append(p)

    filtered_papers.sort(key=lambda x: x.final_score, reverse=True)

    # Trial location personalization
    if location_bias and user_location:
        location_words = set(user_location.split())
        for t in trials:
            for loc in t.locations:
                loc_text = " ".join(filter(None, [loc.city, loc.state, loc.country])).lower()
                if location_words & set(loc_text.split()):
                    t.final_score = min(t.final_score + 0.15, 1.0)
                    break

        trials.sort(key=lambda x: x.final_score, reverse=True)

    return filtered_papers, trials


def build_personalized_system_prompt(context: dict, disease: str, query: str) -> str:
    """
    Build a personalized system prompt for Groq synthesis call.
    Adapts language level and includes patient-specific medical context.
    """
    language_level    = context.get("language_level", "intermediate")
    name              = context.get("name", "the patient")
    age               = context.get("age")
    gender            = context.get("gender", "")
    conditions        = context.get("conditions", [])
    medications       = context.get("medications", [])
    allergies         = context.get("allergies", [])
    disease_personal  = context.get("disease_is_personal", False)

    # Language instructions
    language_instructions = {
        "simple": (
            "Use plain, clear language. Avoid jargon. "
            "Explain medical terms when you use them. "
            "Write as if explaining to someone with no medical background."
        ),
        "intermediate": (
            "Use clear clinical language. "
            "You may use standard medical terms but briefly clarify complex ones. "
            "Assume the reader has some health literacy."
        ),
        "expert": (
            "Use precise clinical and scientific language. "
            "You may use medical terminology freely. "
            "Assume the reader has medical or research expertise."
        ),
    }

    lang_instruction = language_instructions.get(language_level, language_instructions["intermediate"])

    # Patient context block
    patient_context_parts = []
    if age:
        patient_context_parts.append(f"Age: {age}")
    if gender:
        patient_context_parts.append(f"Gender: {gender}")
    if conditions:
        cond_names = [c["name"] if isinstance(c, dict) else c for c in conditions[:5]]
        patient_context_parts.append(f"Known conditions: {', '.join(cond_names)}")
    if medications:
        med_names = [m["name"] if isinstance(m, dict) else m for m in medications[:5]]
        patient_context_parts.append(f"Current medications: {', '.join(med_names)}")
    if allergies:
        patient_context_parts.append(f"Allergies: {', '.join(allergies[:5])}")

    patient_block = ""
    if patient_context_parts:
        patient_block = (
            f"\nAdditional patient context (use to personalize insights):\n"
            + "\n".join(f"  - {p}" for p in patient_context_parts)
        )

    personal_note = ""
    if disease_personal:
        personal_note = (
            f"\nIMPORTANT: {name} has {disease} in their medical history. "
            "Frame insights as directly relevant to their personal situation. "
            "Note any treatment interactions with their current medications."
        )

    return f"""You are Curalink, a warm and compassionate AI medical research assistant who genuinely cares about patients.
You speak like a knowledgeable friend — clear, human, supportive — never cold or robotic.
Respond ONLY with valid XML. No preamble, no markdown.
Every claim must be directly supported by the provided abstracts.
Tag unsupported claims as <grounding_tag>unsupported</grounding_tag>.

Language level: {language_level.upper()}
{lang_instruction}

PERSONALIZATION RULES — follow these strictly:
- Always frame findings in the context of {name}'s condition: {disease}
- Never give generic answers. Every insight must reference the patient's actual situation.
- Instead of "Vitamin D is good" say "In studies of {disease} patients, higher Vitamin D levels were linked to..."
- Instead of "There are treatments" say "For {name}'s situation with {disease}, the most relevant options found are..."
- If medications or conditions are listed below, flag any interactions or relevance found in the papers.
- Always answer the ACTUAL question asked — not a rephrasing or acknowledgment of it.
- NEVER open with "Hi [name], I understand you're dealing with..." — vary openers every time.
{patient_block}
{personal_note}
"""


def build_personalized_hyde_context(context: dict, disease: str) -> str:
    """
    Inject patient context into HyDE expansion prompt.
    Ensures query variants reflect the patient's specific situation.
    """
    parts = []

    age    = context.get("age")
    gender = context.get("gender", "")
    meds   = context.get("medications", [])

    if age:
        parts.append(f"Patient age: {age}")
    if gender:
        parts.append(f"Patient gender: {gender}")
    if meds:
        med_names = [m["name"] if isinstance(m, dict) else m for m in meds[:3]]
        parts.append(f"Current medications: {', '.join(med_names)}")

    if not parts:
        return ""

    return (
        "\nPatient profile context (generate query variants relevant to this profile):\n"
        + "\n".join(f"  - {p}" for p in parts)
    )


def get_study_type_filter(context: dict) -> List[str]:
    """
    Returns list of study subject types to actively include.
    Used in pre-filter stage to respect user preferences.
    """
    show_animal = context.get("show_animal_studies", False)
    base = [
        "human_rct", "human_cohort", "human_case_control",
        "human_case_report", "human_systematic_review",
        "human_meta_analysis", "human_observational", "unknown"
    ]
    if show_animal:
        base += ["animal", "in_vitro"]
    return base
