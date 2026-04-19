"""
Curalink — User Management Routes
POST /api/users          - create profile
GET  /api/users/{id}     - get profile
PUT  /api/users/{id}/preferences - update preferences
GET  /api/users/{id}/history     - query history
POST /api/users/{id}/bookmarks   - add bookmark
GET  /api/users/{id}/bookmarks   - list bookmarks
DELETE /api/users/{id}/bookmarks/{item_id} - remove bookmark
"""

from fastapi import APIRouter, HTTPException
from models.user_schemas import (
    CreateUserRequest, UpdatePreferencesRequest,
    BookmarkRequest, UserResponse
)
from db.user_profile import (
    create_user, get_user, update_user_preferences,
    add_bookmark, get_bookmarks, remove_bookmark,
    get_query_history
)

router = APIRouter()


@router.post(
    "/users",
    summary="Create user profile",
    description="Create a full user profile with medical context, conditions, medications, and preferences.",
)
async def create_user_route(req: CreateUserRequest):
    existing = await get_user(req.user_id)
    if existing:
        raise HTTPException(status_code=409, detail="User already exists")

    await create_user(req.model_dump())
    return {"user_id": req.user_id, "status": "created"}


@router.get(
    "/users/{user_id}",
    summary="Get user profile",
)
async def get_user_route(user_id: str):
    user = await get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.put(
    "/users/{user_id}/preferences",
    summary="Update user preferences",
    description="Update study type preferences, language complexity, trial location bias, etc.",
)
async def update_preferences_route(user_id: str, req: UpdatePreferencesRequest):
    user = await get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No preferences provided")
    await update_user_preferences(user_id, updates)
    return {"status": "updated", "updated_fields": list(updates.keys())}


@router.get(
    "/users/{user_id}/history",
    summary="Get query history",
    description="Returns last 20 queries made by this user (90-day retention).",
)
async def get_history_route(user_id: str, limit: int = 20):
    user = await get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    history = await get_query_history(user_id, limit=min(limit, 50))
    return {"user_id": user_id, "history": history, "count": len(history)}


@router.post(
    "/users/{user_id}/bookmarks",
    summary="Bookmark a paper or trial",
)
async def add_bookmark_route(user_id: str, req: BookmarkRequest):
    user = await get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    bookmark_id = await add_bookmark(user_id, req.model_dump())
    return {"status": "bookmarked", "bookmark_id": bookmark_id}


@router.get(
    "/users/{user_id}/bookmarks",
    summary="List bookmarks",
)
async def list_bookmarks_route(user_id: str):
    user = await get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    bookmarks = await get_bookmarks(user_id)
    return {"user_id": user_id, "bookmarks": bookmarks, "count": len(bookmarks)}


@router.delete(
    "/users/{user_id}/bookmarks/{item_id}",
    summary="Remove a bookmark",
)
async def remove_bookmark_route(user_id: str, item_id: str):
    await remove_bookmark(user_id, item_id)
    return {"status": "removed", "item_id": item_id}
