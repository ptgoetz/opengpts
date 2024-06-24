import json
from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence, Union

from langchain_core.messages import AnyMessage
from langchain_core.runnables import RunnableConfig

from app.agent import agent
from app.lifespan import get_pg_pool
from app.schema import Assistant, Thread, User, UploadedFile
from app.storage import BaseStorage


class PostgresStorage(BaseStorage):

    async def list_all_assistants(self) -> List[Assistant]:
        raise NotImplementedError

    async def assistant_count(self) -> int:
        raise NotImplementedError

    async def thread_count(self) -> int:
        raise NotImplementedError

    async def get_assistant_files(self, assistant_id: str) -> list[UploadedFile]:
        raise NotImplementedError

    async def get_thread_files(self, thread_id: str) -> list[UploadedFile]:
        raise NotImplementedError

    async def get_file(self, file_path: str) -> Optional[UploadedFile]:
        raise NotImplementedError

    async def put_file_owner(self, file_id: str, file_path: str, file_hash: str, embedded: bool,
                             assistant_id: Optional[str], thread_id: Optional[str]) -> UploadedFile:
        raise NotImplementedError

    async def run_migrations(self):
        pass

    async def list_assistants(self, user_id: str) -> List[Assistant]:
        """List all assistants for the current user."""
        async with get_pg_pool().acquire() as conn:
            return await conn.fetch("SELECT * FROM assistant WHERE user_id = $1", user_id)

    async def get_assistant(
        self, user_id: str, assistant_id: str
    ) -> Optional[Assistant]:
        """Get an assistant by ID."""
        async with get_pg_pool().acquire() as conn:
            row =  await conn.fetchrow(
                "SELECT * FROM assistant WHERE assistant_id = $1 AND (user_id = $2 OR public IS true)",
                assistant_id,
                user_id,
            )
            if not row:
                return None
            assistant_data = dict(row)  # Convert sqlite3.Row to dict
            assistant_data["config"] = (
                assistant_data["config"]
                if "config" in assistant_data and assistant_data["config"]
                else {}
            )
            assistant_data["metadata"] = (
                assistant_data["metadata"]
                if assistant_data["metadata"] is not None
                else None
            )
            return Assistant(**assistant_data)

    async def list_public_assistants(self, assistant_ids: Sequence[str]) -> List[Assistant]:
        """List all the public assistants."""
        assistant_ids_tuple = tuple(
            assistant_ids
        )  # SQL requires a tuple for the IN operator.
        placeholders = ", ".join("?" for _ in assistant_ids)
        conn =  get_pg_pool().acquire()
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT * FROM assistant WHERE assistant_id IN ({placeholders}) AND public = 1",
            assistant_ids_tuple,
        )
        rows = cursor.fetchall()
        return [Assistant(**dict(row)) for row in rows]

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
        conn =  get_pg_pool().acquire()
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
        conn =  get_pg_pool().acquire()
        conn.execute(
            "DELETE FROM assistant WHERE assistant_id = $1 AND user_id = $2",
            assistant_id,
            user_id,
        )

    async def list_threads(self, user_id: str) -> List[Thread]:
        """List all threads for the current user."""
        with get_pg_pool().acquire() as conn:
            return conn.fetch("SELECT * FROM thread WHERE user_id = $1", user_id)

    async def get_thread(self, user_id: str, thread_id: str) -> Optional[Thread]:
        """Get a thread by ID."""
        with get_pg_pool().acquire() as conn:
            return conn.fetchrow(
                "SELECT * FROM thread WHERE thread_id = $1 AND user_id = $2",
                thread_id,
                user_id,
            )

    async def get_thread_state(
        self, *, user_id: str, thread_id: str, assistant: Assistant
    ):
        """Get state for a thread."""
        state = agent.aget_state(
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
        agent.aupdate_state(
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
            for c in agent.aget_state_history(
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
        self, user_id: str, thread_id: str, *, assistant_id: str, name: str, metadata: Optional[dict]
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
