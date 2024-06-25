import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("SEMA4AIDESKTOP_HOME", "."))
LOG_DIR = Path(os.environ.get("SEMA4AIDESKTOP_LOG", "."))
VECTOR_DATABASE_PATH = str(DATA_DIR / "chroma_db")
DOMAIN_DATABASE_PATH = str(DATA_DIR / "opengpts.db")
LOG_FILE_PATH = str(LOG_DIR / "opengpts.log")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
