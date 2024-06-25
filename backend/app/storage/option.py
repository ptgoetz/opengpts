import pickle

from langgraph.checkpoint import CheckpointAt

from app.storage import BaseStorage
from app.storage.postgres import PostgresStorage

_storage = None


def get_storage() -> BaseStorage:
    global _storage
    if _storage is None:
        # TODO: Use an env var to determine which storage to use: Postgres, SQLite, etc.
        _storage = PostgresStorage()
    return _storage



