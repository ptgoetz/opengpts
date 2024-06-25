import os
import pickle

from langgraph.checkpoint import CheckpointAt

from app.storage import BaseStorage
from app.storage.postgres import PostgresStorage
from app.storage.sqlite import SqliteStorage

_storage = None


def get_storage() -> BaseStorage:
    db_type = os.environ.get("S4_AGENT_SERVER_DB_TYPE", "postgres")
    global _storage
    if _storage is None:
        if db_type == "postgres":
            _storage = PostgresStorage()
        elif db_type == "sqlite":
            _storage = SqliteStorage()
        else:
            raise ValueError(f"Invalid storage type: {db_type}")
    return _storage
