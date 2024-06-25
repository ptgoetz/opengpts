import pickle
from abc import ABC, abstractmethod
from typing import Any, List, Optional, Sequence, Union, Dict

from langchain_core.messages import AnyMessage, BaseMessage
from langgraph.checkpoint import Checkpoint, BaseCheckpointSaver

from app.agent_types.constants import FINISH_NODE_KEY
from app.schema import Assistant, Thread, User, UploadedFile


class BaseStorage(ABC):
    """Base class for storage backends."""

    @abstractmethod
    async def run_migrations(self):
        pass

    async def list_assistants(self, user_id: str) -> List[Assistant]:
        """List all assistants for the current user."""
        pass

    @abstractmethod
    async def list_all_assistants(self) -> List[Assistant]:
        """List all assistants for all users."""
        pass

    @abstractmethod
    async def get_assistant(self, user_id: str, assistant_id: str) -> Optional[Assistant]:
        """Get an assistant by ID."""
        pass

    # @abstractmethod
    # async def list_public_assistants(self, assistant_ids: Sequence[str]) -> List[Assistant]:
    #     """List all the public assistants."""
    #     pass

    @abstractmethod
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
        """Modify an assistant."""
        pass

    @abstractmethod
    async def assistant_count(self) -> int:
        """Get assistant row count"""
        pass

    @abstractmethod
    async def list_threads(self, user_id: str) -> List[Thread]:
        """List all threads for the current user."""
        pass

    @abstractmethod
    async def get_thread(self, user_id: str, thread_id: str) -> Optional[Thread]:
        """Get a thread by ID."""
        pass

    @abstractmethod
    async def thread_count(self) -> int:
        """Get thread row count."""
        pass

    @abstractmethod
    async def get_thread_state(self, user_id: str, thread_id: str):
        """Get state for a thread."""
        pass

    @abstractmethod
    async def update_thread_state(
            self,
            user_id: str,
            thread_id: str,
            values: Union[Sequence[AnyMessage], Dict[str, Any]],
            as_node: Optional[str] = FINISH_NODE_KEY,
    ):
        """Add state to a thread."""
        pass


    @abstractmethod
    async def get_thread_history(self, user_id: str, thread_id: str):
        """Get the history of a thread."""
        pass

    @abstractmethod
    async def put_thread(
        self, user_id: str, thread_id: str, *, assistant_id: str, name: str, metadata: Optional[dict]
    ) -> Thread:
        """Modify a thread."""
        pass

    @abstractmethod
    async def get_or_create_user(self, sub: str) -> tuple[User, bool]:
        """Returns a tuple of the user and a boolean indicating whether the user was created."""
        pass

    @abstractmethod
    async def delete_thread(self, user_id: str, thread_id: str):
        """Delete a thread by ID."""
        pass

    @abstractmethod
    async def delete_assistant(self, user_id: str, assistant_id: str) -> None:
        """Delete an assistant by ID."""
        pass

    @abstractmethod
    async def get_assistant_files(self, assistant_id: str) -> list[UploadedFile]:
        """Get a list of files associated with an assistant."""
        pass

    @abstractmethod
    async def get_thread_files(self, thread_id: str) -> list[UploadedFile]:
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


    async def get_file(self, file_path: str) -> Optional[UploadedFile]:
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

    async def put_file_owner(
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
