import os
import uuid
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

_client = None
_db = None

async def init_db():
    global _client, _db
    uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/curalink")
    _client = AsyncIOMotorClient(uri)
    _db = _client["curalink"]
    # Create indexes
    await _db.sessions.create_index("session_id", unique=True)
    await _db.sessions.create_index("created_at")
    print("✅ MongoDB connected")

def get_db():
    return _db

async def create_session(
    patient_name: str,
    disease: str,
    location: str,
    user_id: str = None,
) -> str:
    session_id = str(uuid.uuid4())
    await _db.sessions.insert_one({
        "session_id":      session_id,
        "user_id":         user_id,
        "patient_name":    patient_name,
        "disease":         disease,
        "location":        location,
        "messages":        [],
        "context_summary": "",          # updated after each turn
        "created_at":      datetime.utcnow(),
        "updated_at":      datetime.utcnow(),
    })
    return session_id


async def update_context_summary(session_id: str, summary: str):
    """Store a concise text summary of session so far — used for follow-up context."""
    await _db.sessions.update_one(
        {"session_id": session_id},
        {"$set": {"context_summary": summary, "updated_at": datetime.utcnow()}}
    )

async def get_session(session_id: str) -> dict:
    if not session_id:
        return None
    return await _db.sessions.find_one({"session_id": session_id}, {"_id": 0})

async def append_message(session_id: str, role: str, content: dict):
    await _db.sessions.update_one(
        {"session_id": session_id},
        {
            "$push": {
                "messages": {
                    "role": role,
                    "content": content,
                    "timestamp": datetime.utcnow()
                }
            },
            "$set": {"updated_at": datetime.utcnow()}
        }
    )

async def get_recent_messages(session_id: str, limit: int = 4) -> list:
    """Get last N message pairs for context window."""
    session = await get_session(session_id)
    if not session:
        return []
    messages = session.get("messages", [])
    return messages[-limit * 2:] if len(messages) > limit * 2 else messages
