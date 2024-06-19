from typing import Annotated, Any, Dict, List, Optional, Sequence, Union
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Path
from langchain.schema.messages import AnyMessage
from pydantic import BaseModel, Field

from app.auth.handlers import AuthedUser
from app.schema import Thread
from app.storage.option import get_storage

router = APIRouter()


ThreadID = Annotated[str, Path(description="The ID of the thread.")]


class ThreadPutRequest(BaseModel):
    """Payload for creating a thread."""

    name: str = Field(..., description="The name of the thread.")
    assistant_id: str = Field(..., description="The ID of the assistant to use.")


class ThreadPostRequest(BaseModel):
    """Payload for adding state to a thread."""

    values: Union[Sequence[AnyMessage], Dict[str, Any]]
    config: Optional[Dict[str, Any]] = None


@router.get("/")
async def list_threads(user: AuthedUser) -> List[Thread]:
    """List all threads for the current user."""
    return await get_storage().list_threads(user["user_id"])


@router.get("/{tid}/state")
async def get_thread_state(
    user: AuthedUser,
    tid: ThreadID,
):
    """Get state for a thread."""
    thread = await get_storage().get_thread(user["user_id"], tid)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    assistant = await get_storage().get_assistant(
        user["user_id"], thread["assistant_id"]
    )
    if not assistant:
        raise HTTPException(status_code=400, detail="Thread has no assistant")
    return await get_storage().get_thread_state(
        user_id=user["user_id"],
        thread_id=tid,
        assistant=assistant,
    )


@router.post("/{tid}/state")
async def add_thread_state(
    user: AuthedUser,
    tid: ThreadID,
    payload: ThreadPostRequest,
):
    """Add state to a thread."""
    thread = await get_storage().get_thread(user["user_id"], tid)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    assistant = await get_storage().get_assistant(
        user["user_id"], thread["assistant_id"]
    )
    if not assistant:
        raise HTTPException(status_code=400, detail="Thread has no assistant")
    return await get_storage().update_thread_state(
        payload.config or {"configurable": {"thread_id": tid}},
        payload.values,
        user_id=user["user_id"],
        assistant=assistant,
    )


@router.get("/{tid}/history")
async def get_thread_history(
    user: AuthedUser,
    tid: ThreadID,
):
    """Get all past states for a thread."""
    thread = await get_storage().get_thread(user["user_id"], tid)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    assistant = await get_storage().get_assistant(
        user["user_id"], thread["assistant_id"]
    )
    if not assistant:
        raise HTTPException(status_code=400, detail="Thread has no assistant")
    return await get_storage().get_thread_history(
        user_id=user["user_id"],
        thread_id=tid,
        assistant=assistant,
    )


@router.get("/{tid}")
async def get_thread(
    user: AuthedUser,
    tid: ThreadID,
) -> Thread:
    """Get a thread by ID."""
    thread = await get_storage().get_thread(user["user_id"], tid)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


@router.post("")
async def create_thread(
    user: AuthedUser,
    thread_put_request: ThreadPutRequest,
) -> Thread:
    """Create a thread."""
    return await get_storage().put_thread(
        user["user_id"],
        str(uuid4()),
        assistant_id=thread_put_request.assistant_id,
        name=thread_put_request.name,
    )


@router.put("/{tid}")
async def upsert_thread(
    user: AuthedUser,
    tid: ThreadID,
    thread_put_request: ThreadPutRequest,
) -> Thread:
    """Update a thread."""
    return await get_storage().put_thread(
        user["user_id"],
        tid,
        assistant_id=thread_put_request.assistant_id,
        name=thread_put_request.name,
    )


@router.delete("/{tid}")
async def delete_thread(
    user: AuthedUser,
    tid: ThreadID,
):
    """Delete a thread by ID."""
    await get_storage().delete_thread(user["user_id"], tid)
    return {"status": "ok"}
