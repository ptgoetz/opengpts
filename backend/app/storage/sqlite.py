import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Union
from uuid import uuid4

import structlog
from langchain_core.messages import AnyMessage

from app.agent import AgentType, get_agent_executor
from app.agent_types.constants import FINISH_NODE_KEY
from app.schema import Assistant, Thread, UploadedFile, User
from app.storage import BaseStorage

from app.constants import DOMAIN_DATABASE_PATH

logger = structlog.get_logger()


class SqliteStorage(BaseStorage):

    @classmethod
    @contextmanager
    def _connect(cls):
        conn = sqlite3.connect(DOMAIN_DATABASE_PATH)
        conn.row_factory = sqlite3.Row  # Enable dictionary access to row items.
        try:
            yield conn
        finally:
            conn.close()

    def run_migrations(self):
        db_exists = os.path.exists(DOMAIN_DATABASE_PATH)
        current_dir = os.path.dirname(__file__)
        migrations_path = os.path.join(current_dir, '../migrations')

        with self._connect() as conn:
            cursor = conn.cursor()

            current_version = 0
            if db_exists:
                # Check if migration_version table exists
                cursor.execute("""
                    SELECT name FROM sqlite_master WHERE type='table' AND name='migration_version';
                """)
                if cursor.fetchone() is None:
                    # Migration table does not exist, assume version 3
                    current_version = 3
                else:
                    # Get the current migration version
                    cursor.execute("SELECT MAX(version) AS version FROM migration_version;")
                    current_version = cursor.fetchone()["version"]

            # List and sort migration files
            migration_files = sorted(
                (f for f in os.listdir(migrations_path) if f.endswith('.up.sql')),
                key=lambda x: int(x.split('_')[0])
            )

            logger.info(f"Migrations found: {migration_files}")
            logger.info(f"Current migration version: {current_version}")

            # Apply migrations that are newer than the current version
            for migration in migration_files:
                version = int(migration.split('_')[0])
                if version > current_version:
                    logger.info(f"Applying migration {migration}")
                    with open(os.path.join(migrations_path, migration), 'r') as f:
                        conn.executescript(f.read())
                        current_version = version  # Update current version after successful migration
            cursor.execute("INSERT INTO migration_version (version) VALUES (?);", (version,))
            conn.commit()

    def list_assistants(self, user_id: str) -> List[Assistant]:
        """List all assistants for the current user."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row  # Enable dictionary-like row access
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM assistant WHERE user_id = ?", (user_id,))
            rows = cursor.fetchall()

            # Deserialize the 'config' field from a JSON string to a dict for each row
            assistants = []
            for row in rows:
                assistant_data = dict(row)  # Convert sqlite3.Row to dict
                assistant_data["config"] = (
                    json.loads(assistant_data["config"])
                    if "config" in assistant_data and assistant_data["config"]
                    else {}
                )
                assistant_data["metadata"] = (
                    json.loads(assistant_data["metadata"])
                    if assistant_data["metadata"] is not None
                    else None
                )
                assistant = Assistant(**assistant_data)
                assistants.append(assistant)

            return assistants


    def list_all_assistants(self) -> List[Assistant]:
        """List all assistants for all users."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM assistant")
            rows = cursor.fetchall()

            assistants = []
            for row in rows:
                assistant_data = dict(row)
                assistant_data["config"] = (
                    json.loads(assistant_data["config"])
                    if "config" in assistant_data and assistant_data["config"]
                    else {}
                )
                assistant_data["metadata"] = (
                    json.loads(assistant_data["metadata"])
                    if assistant_data["metadata"] is not None
                    else None
                )
                assistant = Assistant(**assistant_data)
                assistants.append(assistant)

            return assistants


    def get_assistant(self, user_id: str, assistant_id: str) -> Optional[Assistant]:
        """Get an assistant by ID."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM assistant WHERE assistant_id = ? AND (user_id = ? OR public = 1)",
                (assistant_id, user_id),
            )
            row = cursor.fetchone()
            if not row:
                return None
            assistant_data = dict(row)  # Convert sqlite3.Row to dict
            assistant_data["config"] = (
                json.loads(assistant_data["config"])
                if "config" in assistant_data and assistant_data["config"]
                else {}
            )
            assistant_data["metadata"] = (
                json.loads(assistant_data["metadata"])
                if assistant_data["metadata"] is not None
                else None
            )
            return Assistant(**assistant_data)


    def list_public_assistants(self, assistant_ids: Sequence[str]) -> List[Assistant]:
        """List all the public assistants."""
        assistant_ids_tuple = tuple(
            assistant_ids
        )  # SQL requires a tuple for the IN operator.
        placeholders = ", ".join("?" for _ in assistant_ids)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT * FROM assistant WHERE assistant_id IN ({placeholders}) AND public = 1",
                assistant_ids_tuple,
            )
            rows = cursor.fetchall()
            return [Assistant(**dict(row)) for row in rows]

    def put_assistant(
            self,
            user_id: str,
            assistant_id: str,
            *,
            name: str,
            config: dict,
            public: bool = False,
            metadata: Optional[dict]
    ) -> Assistant:
        """Modify an assistant."""
        updated_at = datetime.now(timezone.utc)
        with self._connect() as conn:
            cursor = conn.cursor()
            # Convert the config dict to a JSON string for storage.
            config_str = json.dumps(config)
            cursor.execute(
                """
                INSERT INTO assistant (assistant_id, user_id, name, config, updated_at, public, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(assistant_id) 
                DO UPDATE SET 
                    user_id = EXCLUDED.user_id, 
                    name = EXCLUDED.name, 
                    config = EXCLUDED.config, 
                    updated_at = EXCLUDED.updated_at, 
                    public = EXCLUDED.public,
                    metadata = EXCLUDED.metadata
                """,
                (assistant_id, user_id, name, config_str, updated_at.isoformat(), public, json.dumps(metadata)),
            )
            conn.commit()
            return Assistant(
                assistant_id=assistant_id,
                user_id=user_id,
                name=name,
                config=config,
                updated_at=updated_at,
                public=public,
                metadata=metadata,
            )


    def assistant_count(self) -> int:
        """Get assistant row count"""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM assistant")
            count = cursor.fetchone()[0]
            return count


    def list_threads(self, user_id: str) -> List[Thread]:
        """List all threads for the current user."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM thread WHERE user_id = ?", (user_id,))
            rows = cursor.fetchall()
            threads = []
            for row in rows:
                thread_data = dict(row)
                thread_data["metadata"] = (
                    json.loads(thread_data["metadata"])
                    if thread_data["metadata"] is not None
                    else None
                )
                thread = Thread(**thread_data)
                threads.append(thread)
            return threads


    def get_thread(self, user_id: str, thread_id: str) -> Optional[Thread]:
        """Get a thread by ID."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM thread WHERE thread_id = ? AND user_id = ?",
                (thread_id, user_id),
            )
            row = cursor.fetchone()
            if not row:
                return None
            thread_data = dict(row)
            thread_data["metadata"] = (
                json.loads(thread_data["metadata"])
                if thread_data["metadata"] is not None
                else None
            )
            return Thread(**thread_data)

    def thread_count(self) -> int:
        """Get thread row count."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM thread")
            count = cursor.fetchone()[0]
            return count


    def get_thread_state(self, user_id: str, thread_id: str):
        """Get state for a thread."""
        app = get_agent_executor([], AgentType.GPT_35_TURBO, "", False)
        state = app.get_state({"configurable": {"thread_id": thread_id}})
        return {
            "values": state.values,
            "next": state.next,
        }


    def update_thread_state(
            self,
            user_id: str,
            thread_id: str,
            values: Union[Sequence[AnyMessage], Dict[str, Any]],
            as_node: Optional[str] = FINISH_NODE_KEY,
    ):
        """Add state to a thread."""
        app = get_agent_executor([], AgentType.GPT_35_TURBO, "", False)
        app.update_state(
            {"configurable": {"thread_id": thread_id}},
            values,
            as_node=as_node,
        )


    def get_thread_history(self, user_id: str, thread_id: str):
        """Get the history of a thread."""
        app = get_agent_executor([], AgentType.GPT_35_TURBO, "", False)
        return [
            {
                "values": c.values,
                "next": c.next,
                "config": c.config,
                "parent": c.parent_config,
            }
            for c in app.get_state_history({"configurable": {"thread_id": thread_id}})
        ]


    def put_thread(
        self, user_id: str, thread_id: str, *, assistant_id: str, name: str, metadata: Optional[dict]
    ) -> Thread:
        """Modify a thread."""
        updated_at = datetime.now(timezone.utc)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO thread (thread_id, user_id, assistant_id, name, updated_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(thread_id) 
                DO UPDATE SET 
                    user_id = EXCLUDED.user_id,
                    assistant_id = EXCLUDED.assistant_id, 
                    name = EXCLUDED.name, 
                    updated_at = EXCLUDED.updated_at,
                    metadata = EXCLUDED.metadata
                """,
                (thread_id, user_id, assistant_id, name, updated_at, json.dumps(metadata)),
            )
            conn.commit()
            return {
                "thread_id": thread_id,
                "user_id": user_id,
                "assistant_id": assistant_id,
                "name": name,
                "updated_at": updated_at,
                "metadata": metadata,
            }

    def get_or_create_user(self, sub: str) -> tuple[User, bool]:
        """Returns a tuple of the user and a boolean indicating whether the user was created."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM "user" WHERE sub = ?', (sub,))
            user_row = cursor.fetchone()

            if user_row:
                # Convert sqlite3.Row to a User object
                user = User(
                    user_id=user_row["user_id"],
                    sub=user_row["sub"],
                    created_at=user_row["created_at"],
                )
                return user, False

            # SQLite doesn't support RETURNING *, so we need to manually fetch the created user.
            cursor.execute(
                'INSERT INTO "user" (user_id, sub, created_at) VALUES (?, ?, ?)',
                (str(uuid4()), sub, datetime.now()),
            )
            conn.commit()

            # Fetch the newly created user
            cursor.execute('SELECT * FROM "user" WHERE sub = ?', (sub,))
            new_user_row = cursor.fetchone()

            new_user = User(
                user_id=new_user_row["user_id"],
                sub=new_user_row["sub"],
                created_at=new_user_row["created_at"],
            )
            return new_user, True


    def delete_thread(self, user_id: str, thread_id: str):
        """Delete a thread by ID."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM thread WHERE thread_id = ? AND user_id = ?",
                (thread_id, user_id),
            )
            conn.commit()


    def delete_assistant(self, user_id: str, assistant_id: str) -> None:
        """Delete an assistant by ID."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM assistant WHERE assistant_id = ? AND user_id = ?",
                (assistant_id, user_id),
            )
            conn.commit()

    def get_assistant_files(self, assistant_id: str) -> list[UploadedFile]:
        """Get a list of files associated with an assistant."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM file_owners
                WHERE assistant_id = ?
                """,
                (assistant_id,)
            )
            rows = cursor.fetchall()
            return [
                UploadedFile(
                    file_id=str(row["file_id"]),
                    file_path=row["file_path"],
                    file_hash=row["file_hash"],
                    embedded=row["embedded"],
                )
                for row in rows
            ]


    def get_thread_files(self, thread_id: str) -> list[UploadedFile]:
        """Get a list of files associated with a thread."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM file_owners
                WHERE thread_id = ?
                """,
                (thread_id,)
            )
            rows = cursor.fetchall()
            return [
                UploadedFile(
                    file_id=str(row["file_id"]),
                    file_path=row["file_path"],
                    file_hash=row["file_hash"],
                    embedded=row["embedded"],
                )
                for row in rows
            ]


    def get_file(self, file_path: str) -> Optional[UploadedFile]:
        """Get a file by path."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM file_owners
                WHERE file_path = ?
                """,
                (file_path,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            return UploadedFile(
                file_id=str(row["file_id"]),
                file_path=row["file_path"],
                file_hash=row["file_hash"],
                embedded=row["embedded"],
            )

    def put_file_owner(
        self,
        file_id: str,
        file_path: str,
        file_hash: str,
        embedded: bool,
        assistant_id: Optional[str],
        thread_id: Optional[str],
    ) -> UploadedFile:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO file_owners (file_id, file_path, file_hash, embedded, assistant_id, thread_id)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_path)
                DO UPDATE SET 
                    file_id = EXCLUDED.file_id,
                    file_hash = EXCLUDED.file_hash,
                    embedded = EXCLUDED.embedded,
                    assistant_id = EXCLUDED.assistant_id,
                    thread_id = EXCLUDED.thread_id
                """,
                (file_id, file_path, file_hash, embedded, assistant_id, thread_id),
            )
            conn.commit()
            return UploadedFile(
                file_id=file_id,
                file_path=file_path,
                file_hash=file_hash,
                embedded=embedded,
            )
