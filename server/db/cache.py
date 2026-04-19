import hashlib
import json
from datetime import datetime, timedelta
from db.session import get_db


def _make_cache_key(query: str, disease: str) -> str:
    raw = f"{query.lower().strip()}::{disease.lower().strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def init_cache():
    db = get_db()
    # TTL index — MongoDB auto-deletes after 24 hours
    await db.query_cache.create_index("expires_at", expireAfterSeconds=0)
    await db.query_cache.create_index("cache_key", unique=True)
    print("✅ Cache initialized with 24h TTL")


async def get_cached(query: str, disease: str) -> dict | None:
    db = get_db()
    key = _make_cache_key(query, disease)
    doc = await db.query_cache.find_one({"cache_key": key}, {"_id": 0})
    if doc:
        print(f"[Cache] HIT for key: {key[:12]}...")
        return doc.get("result")
    return None


async def set_cached(query: str, disease: str, result: dict):
    db = get_db()
    key = _make_cache_key(query, disease)
    # Serialize result (handle datetime etc.)
    serialized = json.loads(json.dumps(result, default=str))
    await db.query_cache.update_one(
        {"cache_key": key},
        {
            "$set": {
                "cache_key":  key,
                "result":     serialized,
                "query":      query,
                "disease":    disease,
                "cached_at":  datetime.utcnow(),
                "expires_at": datetime.utcnow() + timedelta(hours=24),
            }
        },
        upsert=True
    )
    print(f"[Cache] SET for key: {key[:12]}...")
