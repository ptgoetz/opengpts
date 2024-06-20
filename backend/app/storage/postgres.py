from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence, Union

from langchain_core.messages import AnyMessage
from langchain_core.runnables import RunnableConfig

from app.agent import agent
from app.lifespan import get_pg_pool
from app.schema import Assistant, Thread, User
from app.storage import BaseStorage


class PostgresStorage(BaseStorage):
    async def list_assistants(self, user_id: str) -> List[Assistant]:
        """List all assistants for the current user."""
        async with get_pg_pool().acquire() as conn:
            return await conn.fetch(
                "SELECT * FROM assistant WHERE user_id = $1", user_id
            )

    async def get_assistant(
        self, user_id: str, assistant_id: str
    ) -> Optional[Assistant]:
        """Get an assistant by ID."""
        async with get_pg_pool().acquire() as conn:
            return await conn.fetchrow(
                "SELECT * FROM assistant WHERE assistant_id = $1 AND (user_id = $2 OR public IS true)",
                assistant_id,
                user_id,
            )

    async def list_public_assistants(self) -> List[Assistant]:
        """List all the public assistants."""
        async with get_pg_pool().acquire() as conn:
            return await conn.fetch(("SELECT * FROM assistant WHERE public IS true;"))

    async def put_assistant(
        self,
        user_id: str,
        assistant_id: str,
        *,
        name: str,
        config: dict,
        public: bool = False,
        metadata: Optional[dict]
    ) -> Assistant:
        """Modify an assistant.

        Args:
            user_id: The user ID.
            assistant_id: The assistant ID.
            name: The assistant name.
            config: The assistant config.
            public: Whether the assistant is public.
            metadata: Additional metadata.

        Returns:
            return the assistant model if no exception is raised.
        """
        updated_at = datetime.now(timezone.utc)
        async with get_pg_pool().acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    (
                        "INSERT INTO assistant (assistant_id, user_id, name, config, updated_at, public, metadata) VALUES ($1, $2, $3, $4, $5, $6, $7) "
                        "ON CONFLICT (assistant_id) DO UPDATE SET "
                        "user_id = EXCLUDED.user_id, "
                        "name = EXCLUDED.name, "
                        "config = EXCLUDED.config, "
                        "updated_at = EXCLUDED.updated_at, "
                        "public = EXCLUDED.public,"
                        "metadata = EXCLUDED.metadata;"
                    ),
                    assistant_id,
                    user_id,
                    name,
                    config,
                    updated_at,
                    public,
                    metadata,
                )
        return {
            "assistant_id": assistant_id,
            "user_id": user_id,
            "name": name,
            "config": config,
            "updated_at": updated_at,
            "public": public,
            "metadata": metadata,
        }

    async def delete_assistant(self, user_id: str, assistant_id: str) -> None:
        """Delete an assistant by ID."""
        async with get_pg_pool().acquire() as conn:
            await conn.execute(
                "DELETE FROM assistant WHERE assistant_id = $1 AND user_id = $2",
                assistant_id,
                user_id,
            )

    async def list_threads(self, user_id: str) -> List[Thread]:
        """List all threads for the current user."""
        async with get_pg_pool().acquire() as conn:
            return await conn.fetch("SELECT * FROM thread WHERE user_id = $1", user_id)

    async def get_thread(self, user_id: str, thread_id: str) -> Optional[Thread]:
        """Get a thread by ID."""
        async with get_pg_pool().acquire() as conn:
            return await conn.fetchrow(
                "SELECT * FROM thread WHERE thread_id = $1 AND user_id = $2",
                thread_id,
                user_id,
            )

    async def get_thread_state(
        self, *, user_id: str, thread_id: str, assistant: Assistant
    ):
        """Get state for a thread."""
        state = await agent.aget_state(
            {
                "configurable": {
                    **assistant["config"]["configurable"],
                    "thread_id": thread_id,
                    "assistant_id": assistant["assistant_id"],
                }
            }
        )
        return {
            "values": state.values,
            "next": state.next,
        }

    async def update_thread_state(
        self,
        config: RunnableConfig,
        values: Union[Sequence[AnyMessage], dict[str, Any]],
        *,
        user_id: str,
        assistant: Assistant,
    ):
        """Add state to a thread."""
        await agent.aupdate_state(
            {
                "configurable": {
                    **assistant["config"]["configurable"],
                    **config["configurable"],
                    "assistant_id": assistant["assistant_id"],
                }
            },
            values,
        )

    async def get_thread_history(
        self, *, user_id: str, thread_id: str, assistant: Assistant
    ):
        """Get the history of a thread."""
        return [
            {
                "values": c.values,
                "next": c.next,
                "config": c.config,
                "parent": c.parent_config,
            }
            async for c in agent.aget_state_history(
                {
                    "configurable": {
                        **assistant["config"]["configurable"],
                        "thread_id": thread_id,
                        "assistant_id": assistant["assistant_id"],
                    }
                }
            )
        ]

    async def put_thread(
        self, user_id: str, thread_id: str, *, assistant_id: str, name: str
    ) -> Thread:
        """Modify a thread."""
        updated_at = datetime.now(timezone.utc)
        assistant = await self.get_assistant(user_id, assistant_id)
        metadata = (
            {"assistant_type": assistant["config"]["configurable"]["type"]}
            if assistant
            else None
        )
        async with get_pg_pool().acquire() as conn:
            await conn.execute(
                (
                    "INSERT INTO thread (thread_id, user_id, assistant_id, name, updated_at, metadata) VALUES ($1, $2, $3, $4, $5, $6) "
                    "ON CONFLICT (thread_id) DO UPDATE SET "
                    "user_id = EXCLUDED.user_id,"
                    "assistant_id = EXCLUDED.assistant_id, "
                    "name = EXCLUDED.name, "
                    "updated_at = EXCLUDED.updated_at, "
                    "metadata = EXCLUDED.metadata;"
                ),
                thread_id,
                user_id,
                assistant_id,
                name,
                updated_at,
                metadata,
            )
            return {
                "thread_id": thread_id,
                "user_id": user_id,
                "assistant_id": assistant_id,
                "name": name,
                "updated_at": updated_at,
                "metadata": metadata,
            }

    async def delete_thread(self, user_id: str, thread_id: str):
        """Delete a thread by ID."""
        async with get_pg_pool().acquire() as conn:
            await conn.execute(
                "DELETE FROM thread WHERE thread_id = $1 AND user_id = $2",
                thread_id,
                user_id,
            )

    async def get_or_create_user(self, sub: str) -> tuple[User, bool]:
        """Returns a tuple of the user and a boolean indicating whether the user was created."""
        async with get_pg_pool().acquire() as conn:
            if user := await conn.fetchrow('SELECT * FROM "user" WHERE sub = $1', sub):
                return user, False
            user = await conn.fetchrow(
                'INSERT INTO "user" (sub) VALUES ($1) RETURNING *', sub
            )
            return user, True
