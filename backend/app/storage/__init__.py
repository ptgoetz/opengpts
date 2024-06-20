from abc import ABC, abstractmethod
from typing import Any, List, Optional, Sequence, Union

from langchain_core.messages import AnyMessage
from langchain_core.runnables import RunnableConfig

from app.schema import Assistant, Thread, User


class BaseStorage(ABC):
    @abstractmethod
    async def list_assistants(self, user_id: str) -> List[Assistant]:
        pass

    @abstractmethod
    async def get_assistant(
        self, user_id: str, assistant_id: str
    ) -> Optional[Assistant]:
        """Get an assistant by ID."""
        pass

    @abstractmethod
    async def list_public_assistants(self) -> List[Assistant]:
        """List all the public assistants."""
        pass

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
        pass

    @abstractmethod
    async def delete_assistant(self, user_id: str, assistant_id: str) -> None:
        """Delete an assistant by ID."""
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
    async def get_thread_state(
        self, *, user_id: str, thread_id: str, assistant: Assistant
    ):
        """Get state for a thread."""
        pass

    @abstractmethod
    async def update_thread_state(
        self,
        config: RunnableConfig,
        values: Union[Sequence[AnyMessage], dict[str, Any]],
        *,
        user_id: str,
        assistant: Assistant,
    ):
        """Add state to a thread."""
        pass

    @abstractmethod
    async def get_thread_history(
        self, *, user_id: str, thread_id: str, assistant: Assistant
    ):
        """Get the history of a thread."""
        pass

    @abstractmethod
    async def put_thread(
        self, user_id: str, thread_id: str, *, assistant_id: str, name: str
    ) -> Thread:
        """Modify a thread."""
        pass

    @abstractmethod
    async def delete_thread(self, user_id: str, thread_id: str):
        """Delete a thread by ID."""
        pass

    @abstractmethod
    async def get_or_create_user(self, sub: str) -> tuple[User, bool]:
        """Returns a tuple of the user and a boolean indicating whether the user was created."""
        pass
