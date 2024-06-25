from typing import Annotated, Any, Dict, List, Optional, Sequence, Union
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Path
from langchain.schema.messages import AnyMessage
from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field

from app.storage.option import get_storage
from app.auth.handlers import AuthedUser
from app.schema import Thread, UploadedFile

router = APIRouter()


ThreadID = Annotated[str, Path(description="The ID of the thread.")]


class ThreadPostRequest(BaseModel):
    """Payload for creating a thread."""

    name: str = Field(..., description="The name of the thread.")
    assistant_id: str = Field(..., description="The ID of the assistant to use.")
    starting_message: Optional[str] = Field(
        None, description="The starting AI message for the thread."
    )


class ThreadPutRequest(BaseModel):
    """Payload for updating a thread."""

    name: str = Field(..., description="The name of the thread.")
    assistant_id: str = Field(..., description="The ID of the assistant to use.")


class ThreadStatePostRequest(BaseModel):
    """Payload for adding state to a thread."""

    values: Union[Sequence[AnyMessage], Dict[str, Any]]


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
    thread = get_storage().get_thread(user["user_id"], tid)
    state = get_storage().get_thread_state(user["user_id"], tid)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return state


@router.post("/{tid}/state")
async def add_thread_state(
    user: AuthedUser,
    tid: ThreadID,
    payload: ThreadStatePostRequest,
):
    """Add state to a thread."""
    thread = get_storage().get_thread(user["user_id"], tid)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return get_storage().update_thread_state(user["user_id"], tid, payload.values)


@router.get("/{tid}/history")
async def get_thread_history(
    user: AuthedUser,
    tid: ThreadID,
):
    """Get all past states for a thread."""
    thread = await get_storage().get_thread(user["user_id"], tid)
    history = await get_storage().get_thread_history(user_id=user["user_id"], thread_id=tid)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return history


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
    payload: ThreadPostRequest,
) -> Thread:
    """Create a thread."""
    thread = get_storage().put_thread(
        user["user_id"],
        str(uuid4()),
        assistant_id=payload.assistant_id,
        name=payload.name,
        metadata=None,
    )
    if payload.starting_message is not None:
        message = AIMessage(id=str(uuid4()), content=payload.starting_message)
        thread = await get_storage().update_thread_state(
            user_id=user["user_id"],
            thread_id=thread["thread_id"],
            values={"messages": [message]},
        )
    return thread


@router.put("/{tid}")
async def upsert_thread(
    user: AuthedUser,
    tid: ThreadID,
    payload: ThreadPutRequest,
) -> Thread:
    """Update a thread."""
    thread = get_storage().get_thread(user["user_id"], tid)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return await get_storage().put_thread(
        user["user_id"],
        tid,
        assistant_id=payload.assistant_id,
        name=payload.name,
        metadata=thread["metadata"],
    )


@router.delete("/{tid}")
async def delete_thread(
    user: AuthedUser,
    tid: ThreadID,
):
    """Delete a thread by ID."""
    await get_storage().delete_thread(user["user_id"], tid)
    return {"status": "ok"}


@router.get("/{tid}/files")
async def get_thread_files(
    user: AuthedUser,
    tid: ThreadID,
) -> List[UploadedFile]:
    """Get a list of files associated with a thread."""
    thread = get_storage().get_thread(user["user_id"], tid)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return await get_storage().get_thread_files(tid)
