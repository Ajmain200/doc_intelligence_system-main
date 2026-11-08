"""
Test isolation: point the app at a throwaway SQLite DB and uploads folder *before*
any app module is imported, so tests never touch the real doc_intelligence.db.
"""
import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="docintel_tests_"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["UPLOAD_DIR"] = str(_TMP / "uploads")
os.environ["LLM_PROVIDER"] = "heuristic_fallback"  # deterministic, no network
