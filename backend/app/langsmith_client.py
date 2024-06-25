import os
from functools import lru_cache
from typing import Optional

import langsmith.client
from langsmith import schemas as ls_schemas
from langsmith.utils import LangSmithError, LangSmithNotFoundError

from app.schema import Thread
from app.storage.option import get_storage


@lru_cache()
def _get_or_create_langsmith_project(
    client: langsmith.client.Client,
) -> Optional[ls_schemas.TracerSession]:
    project_name = os.getenv("LANGCHAIN_PROJECT", "default")
    try:
        return client.read_project(project_name=project_name)
    except LangSmithNotFoundError:
        return client.create_project(project_name)
    except LangSmithError:
        # Maybe wrong API key
        return None


@lru_cache()
def get_langsmith_thread_url(
    client: langsmith.client.Client, thread_id: str
) -> Optional[str]:
    project = _get_or_create_langsmith_project(client)
    if not project:
        return None
    return (
        f"{client._host_url}/o/{project.tenant_id}/"
        f"projects/p/{project.id}/t/{thread_id}/"
    )


def save_langsmith_thread_url(thread: Thread, url: str) -> None:
    """Save the langsmith URL to the thread metadata if it is not already present."""

    metadata = thread["metadata"] or {}
    existing_urls = metadata.get("langsmith_urls", [])
    if url not in existing_urls:
        existing_urls.append(url)
        metadata["langsmith_urls"] = existing_urls
        get_storage().put_thread(
            user_id=thread["user_id"],
            thread_id=thread["thread_id"],
            assistant_id=thread["assistant_id"],
            name=thread["name"],
            metadata=metadata,
        )
