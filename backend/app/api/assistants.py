from typing import Annotated, List, Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, HTTPException, Path, Query
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from app.agent import agent
from app.auth.handlers import AuthedUser
from app.schema import Assistant, UploadedFile
from app.storage.option import get_storage

logger = structlog.get_logger(__name__)

router = APIRouter()

FEATURED_PUBLIC_ASSISTANTS = []


class AssistantPayload(BaseModel):
    """Payload for creating an assistant."""

    name: str = Field(..., description="The name of the assistant.")
    config: dict = Field(..., description="The assistant config.")
    public: bool = Field(default=False, description="Whether the assistant is public.")
    metadata: Optional[dict] = Field(
        default=None, description="Additional metadata for the assistant."
    )


AssistantID = Annotated[str, Path(description="The ID of the assistant.")]


async def _generate_welcome_message(
    user_id: str, payload: AssistantPayload
) -> Optional[str]:
    thread = await get_storage().put_thread(
        user_id, str(uuid4()), assistant_id=None, name="", metadata=None
    )
    config = {
        "configurable": {
            **payload.config.get("configurable", {}),
            "thread_id": thread["thread_id"],
        }
    }
    human_prompt = (
        "Introduce yourself as a Sema4.ai Agent and tell me what you're capable of."
    )
    input = {"messages": [HumanMessage(content=human_prompt, id=str(uuid4()))]}

    try:
        response = await agent.ainvoke(input, config)
    except Exception:
        welcome_message = None
        logger.exception("Failed to generate welcome message.")
    else:
        welcome_message = response["messages"][1].content
    finally:
        await get_storage().delete_thread(thread["user_id"], thread["thread_id"])

    return welcome_message


@router.get("/")
async def list_assistants(user: AuthedUser) -> List[Assistant]:
    """List all assistants for the current user."""
    assistants = await get_storage().list_assistants(user["user_id"])
    return assistants


# @router.get("/public/")
# async def list_public_assistants(
#     shared_id: Annotated[
#         Optional[str], Query(description="ID of a publicly shared assistant.")
#     ] = None,
# ) -> List[Assistant]:
#     """List all public assistants."""
#     return await get_storage().list_public_assistants(
#         FEATURED_PUBLIC_ASSISTANTS + ([shared_id] if shared_id else [])
#     )


@router.get("/{aid}")
async def get_assistant(
    user: AuthedUser,
    aid: AssistantID,
) -> Assistant:
    """Get an assistant by ID."""
    assistant = await get_storage().get_assistant(user["user_id"], aid)
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")
    return assistant


@router.post("")
async def create_assistant(
    user: AuthedUser,
    payload: AssistantPayload,
) -> Assistant:
    """Create an assistant."""
    msg = await _generate_welcome_message(user["user_id"], payload)

    metadata = payload.metadata or {}
    if msg is not None:
        metadata["welcome_message"] = msg

    return await get_storage().put_assistant(
        user["user_id"],
        str(uuid4()),
        name=payload.name,
        config=payload.config,
        public=payload.public,
        metadata=metadata,
    )


@router.put("/{aid}")
async def upsert_assistant(
    user: AuthedUser,
    aid: AssistantID,
    payload: AssistantPayload,
) -> Assistant:
    """Create or update an assistant."""
    assistant = await get_storage().get_assistant(user["user_id"], aid)
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")

    msg = await _generate_welcome_message(user["user_id"], payload)
    metadata = assistant["metadata"] or {}
    if msg is not None:
        metadata["welcome_message"] = msg

    # Update metadata with payload metadata
    if payload.metadata:
        metadata.update(payload.metadata)

    return await get_storage().put_assistant(
        user["user_id"],
        aid,
        name=payload.name,
        config=payload.config,
        public=payload.public,
        metadata=metadata,
    )


@router.delete("/{aid}")
async def delete_assistant(
    user: AuthedUser,
    aid: AssistantID,
):
    """Delete an assistant by ID."""
    await get_storage().delete_assistant(user["user_id"], aid)
    return {"status": "ok"}


@router.get("/{aid}/files")
async def get_assistant_files(
    user: AuthedUser,
    aid: AssistantID,
) -> List[UploadedFile]:
    """Get an list of files associated with an assistant."""
    assistant = await get_storage().get_assistant(user["user_id"], aid)
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")
    return await get_storage().get_assistant_files(aid)
