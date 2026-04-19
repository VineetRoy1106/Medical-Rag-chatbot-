"""
Curalink — User Profile & Personalization Database
Full persistence layer for:
- User profiles (demographics, conditions, preferences)
- Query history with full results
- Research bookmarks
- Conversation sessions with context
- Personalization signals derived from behavior
"""

from datetime import datetime, timedelta
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient
from db.session import get_db


# ─────────────────────────────────────────────────────────────────────────────
# COLLECTION SCHEMAS (for reference — enforced via Pydantic in schemas.py)
#
# users: {
#   user_id, name, email, age, gender, location
#   conditions: [{ name, diagnosed_date, severity, notes }]
#   medications: [{ name, dose, frequency }]
#   allergies: [str]
#   preferences: {
#     preferred_study_types: [str],   # e.g. ["human_rct", "systematic_review"]
#     language_complexity: str,        # simple | intermediate | expert
#     show_animal_studies: bool,
#     location_bias_trials: bool,
#     preferred_sources: [str],        # pubmed | openalex | both
#     email_updates: bool,
#   }
#   behavior: {
#     total_queries: int,
#     diseases_searched: [str],
#     avg_session_length: float,
#     bookmarked_papers: [str],
#     clicked_trials: [str],
#     last_active: datetime,
#   }
#   created_at, updated_at
# }
#
# sessions: {
#   session_id, user_id, disease, location
#   messages: [{ role, content, timestamp }]
#   context_summary: str   ← LLM-generated summary of session so far
#   created_at, updated_at
# }
#
# query_history: {
#   query_id, session_id, user_id
#   query, disease, location
#   hyde_queries: [str]
#   papers_returned: int
#   trials_returned: int
#   retrieval_verdict: str
#   corrective_rag_fired: bool
#   pipeline_ms: float
#   result_snapshot: { condition_overview, insight_titles: [str] }
#   created_at
# }
#
# bookmarks: {
#   bookmark_id, user_id
#   type: paper | trial
#   item_id, title, url, source, year
#   notes: str
#   tags: [str]
#   created_at
# }
# ─────────────────────────────────────────────────────────────────────────────


async def init_user_collections():
    """Create indexes for all user-related collections."""
    db = get_db()

    # Users
    await db.users.create_index("user_id",  unique=True)
    await db.users.create_index("email",    unique=True, sparse=True)

    # Query history — TTL: keep 90 days
    await db.query_history.create_index("user_id")
    await db.query_history.create_index("session_id")
    await db.query_history.create_index(
        "created_at",
        expireAfterSeconds=90 * 24 * 3600
    )

    # Bookmarks
    await db.bookmarks.create_index([("user_id", 1), ("item_id", 1)], unique=True)
    await db.bookmarks.create_index("user_id")

    print("✅ User collections initialized")


# ── User CRUD ─────────────────────────────────────────────────────────────

async def create_user(profile: dict) -> str:
    """
    Create a new user profile.
    profile keys: user_id, name, email, age, gender, location,
                  conditions, medications, allergies, preferences
    """
    db = get_db()
    now = datetime.utcnow()

    doc = {
        "user_id":     profile.get("user_id"),
        "name":        profile.get("name", ""),
        "email":       profile.get("email", ""),
        "age":         profile.get("age"),
        "gender":      profile.get("gender", ""),
        "location":    profile.get("location", ""),

        # Medical context
        "conditions":  profile.get("conditions", []),
        "medications": profile.get("medications", []),
        "allergies":   profile.get("allergies", []),

        # Personalization preferences (explicit)
        "preferences": {
            "preferred_study_types":    ["human_rct", "human_systematic_review", "human_meta_analysis"],
            "language_complexity":       "intermediate",
            "show_animal_studies":       False,
            "location_bias_trials":      True,
            "preferred_sources":         ["pubmed", "openalex"],
            "email_updates":             False,
            **profile.get("preferences", {}),
        },

        # Behavior signals (implicit — updated automatically)
        "behavior": {
            "total_queries":       0,
            "diseases_searched":   [],
            "topics_searched":     [],
            "bookmarked_papers":   [],
            "clicked_trials":      [],
            "avg_session_length":  0.0,
            "last_active":         now,
        },

        "created_at": now,
        "updated_at": now,
    }

    await db.users.insert_one(doc)
    return profile["user_id"]


async def get_user(user_id: str) -> Optional[dict]:
    db = get_db()
    return await db.users.find_one({"user_id": user_id}, {"_id": 0})


async def update_user_preferences(user_id: str, preferences: dict):
    """Update explicit user preferences."""
    db = get_db()
    update_fields = {f"preferences.{k}": v for k, v in preferences.items()}
    update_fields["updated_at"] = datetime.utcnow()
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": update_fields}
    )


async def update_user_behavior(user_id: str, query: str, disease: str):
    """
    Update implicit behavior signals after each query.
    Called automatically by the pipeline.
    """
    db = get_db()
    now = datetime.utcnow()
    await db.users.update_one(
        {"user_id": user_id},
        {
            "$inc": {"behavior.total_queries": 1},
            "$addToSet": {
                "behavior.diseases_searched": disease.lower(),
                "behavior.topics_searched":   query.lower()[:60],
            },
            "$set": {
                "behavior.last_active": now,
                "updated_at":           now,
            }
        }
    )


async def add_bookmark(user_id: str, item: dict) -> str:
    """
    Bookmark a paper or trial.
    item keys: type (paper|trial), item_id, title, url, source, year, notes, tags
    """
    db  = get_db()
    now = datetime.utcnow()
    doc = {
        "bookmark_id": f"{user_id}_{item['item_id']}",
        "user_id":     user_id,
        "type":        item.get("type", "paper"),
        "item_id":     item["item_id"],
        "title":       item.get("title", ""),
        "url":         item.get("url", ""),
        "source":      item.get("source", ""),
        "year":        item.get("year"),
        "notes":       item.get("notes", ""),
        "tags":        item.get("tags", []),
        "created_at":  now,
    }
    await db.bookmarks.update_one(
        {"user_id": user_id, "item_id": item["item_id"]},
        {"$set": doc},
        upsert=True
    )
    # Update behavior signal
    await db.users.update_one(
        {"user_id": user_id},
        {"$addToSet": {"behavior.bookmarked_papers": item["item_id"]}}
    )
    return doc["bookmark_id"]


async def get_bookmarks(user_id: str) -> list:
    db = get_db()
    cursor = db.bookmarks.find({"user_id": user_id}, {"_id": 0}).sort("created_at", -1)
    return await cursor.to_list(length=100)


async def remove_bookmark(user_id: str, item_id: str):
    db = get_db()
    await db.bookmarks.delete_one({"user_id": user_id, "item_id": item_id})


# ── Query History ─────────────────────────────────────────────────────────

async def save_query_history(
    session_id:   str,
    user_id:      Optional[str],
    query:        str,
    disease:      str,
    location:     str,
    pipeline_data: dict,
    result_snapshot: dict,
):
    """Save a query + lightweight result snapshot for history."""
    db  = get_db()
    now = datetime.utcnow()
    doc = {
        "query_id":            f"{session_id}_{now.timestamp():.0f}",
        "session_id":          session_id,
        "user_id":             user_id,
        "query":               query,
        "disease":             disease,
        "location":            location,
        "hyde_queries":        pipeline_data.get("hyde_queries", []),
        "papers_returned":     pipeline_data.get("papers_after_rerank", 0),
        "trials_returned":     pipeline_data.get("trials_after_rerank", 0),
        "retrieval_verdict":   pipeline_data.get("retrieval_verdict", "correct"),
        "corrective_rag_fired":pipeline_data.get("corrective_rag_fired", False),
        "pipeline_ms":         pipeline_data.get("total_ms", 0),
        "result_snapshot":     result_snapshot,
        "created_at":          now,
    }
    await db.query_history.insert_one(doc)


async def get_query_history(user_id: str, limit: int = 20) -> list:
    db = get_db()
    cursor = db.query_history.find(
        {"user_id": user_id},
        {"_id": 0, "result_snapshot": 0}  # omit heavy snapshot in list view
    ).sort("created_at", -1).limit(limit)
    return await cursor.to_list(length=limit)


# ── Context Management ────────────────────────────────────────────────────

async def build_personalization_context(user_id: Optional[str], disease: str) -> dict:
    """
    Build a rich personalization context dict for the pipeline.
    Used to adapt: study type preferences, location bias, language level.
    Falls back gracefully if no user_id.
    """
    if not user_id:
        return _default_context()

    user = await get_user(user_id)
    if not user:
        return _default_context()

    prefs    = user.get("preferences", {})
    behavior = user.get("behavior", {})

    # Derive preferred study types filter weights
    preferred_types = prefs.get("preferred_study_types", [
        "human_rct", "human_systematic_review", "human_meta_analysis"
    ])

    # Check if user has this disease in their profile
    user_conditions = [c["name"].lower() for c in user.get("conditions", [])]
    disease_is_personal = disease.lower() in " ".join(user_conditions)

    # Language level adapts to query count (more queries = more technical)
    total_q = behavior.get("total_queries", 0)
    if prefs.get("language_complexity") == "expert" or total_q > 50:
        language_level = "expert"
    elif prefs.get("language_complexity") == "simple" or total_q < 5:
        language_level = "simple"
    else:
        language_level = "intermediate"

    return {
        "user_id":               user_id,
        "name":                  user.get("name", ""),
        "location":              user.get("location", ""),
        "age":                   user.get("age"),
        "gender":                user.get("gender", ""),
        "conditions":            user.get("conditions", []),
        "medications":           user.get("medications", []),
        "allergies":             user.get("allergies", []),
        "preferred_study_types": preferred_types,
        "show_animal_studies":   prefs.get("show_animal_studies", False),
        "location_bias_trials":  prefs.get("location_bias_trials", True),
        "language_level":        language_level,
        "disease_is_personal":   disease_is_personal,
        "bookmarked_ids":        behavior.get("bookmarked_papers", []),
        "diseases_history":      behavior.get("diseases_searched", []),
    }


def _default_context() -> dict:
    return {
        "user_id":               None,
        "name":                  "",
        "location":              "",
        "age":                   None,
        "gender":                "",
        "conditions":            [],
        "medications":           [],
        "allergies":             [],
        "preferred_study_types": ["human_rct", "human_systematic_review"],
        "show_animal_studies":   False,
        "location_bias_trials":  True,
        "language_level":        "intermediate",
        "disease_is_personal":   False,
        "bookmarked_ids":        [],
        "diseases_history":      [],
    }


# ── Session Context Summary ───────────────────────────────────────────────

async def get_session_context_summary(session_id: str) -> str:
    """
    Returns a concise text summary of what was discussed in this session.
    Used as context for follow-up queries.
    """
    from db.session import get_session  # local import to avoid circular
    session = await get_session(session_id)
    if not session:
        return ""

    # Return stored summary if available (updated after each turn)
    if session.get("context_summary"):
        return session["context_summary"]

    # Fallback: build from message history
    disease  = session.get("disease", "")
    messages = session.get("messages", [])
    queries  = [
        m["content"].get("query", "")
        for m in messages
        if m.get("role") == "user" and isinstance(m.get("content"), dict)
    ]
    topics = list(dict.fromkeys(q for q in queries if q))[:5]
    summary = f"Disease context: {disease}. "
    if topics:
        summary += f"Previously asked about: {'; '.join(topics)}."
    return summary
