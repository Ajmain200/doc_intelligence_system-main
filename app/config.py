import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    # Load .env from project root
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

try:
    from pydantic import BaseModel
except ImportError:
    class BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads")))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _resolve_database_url(url: str) -> str:
    """Makes relative SQLite paths (sqlite:///./x.db) relative to the project root, not the CWD."""
    prefix = "sqlite:///"
    if url.startswith(prefix) and not url.startswith(prefix + "/"):
        path = Path(url[len(prefix):])
        if not path.is_absolute():
            return f"{prefix}{(BASE_DIR / path).resolve().as_posix()}"
    return url


class Settings(BaseModel):
    PROJECT_NAME: str = "AI-Powered Document Intelligence System"
    VERSION: str = "1.0.0"
    API_V1_PREFIX: str = "/api/v1"
    
    # Storage & DB
    DATABASE_URL: str = _resolve_database_url(os.getenv("DATABASE_URL", "sqlite:///./doc_intelligence.db"))
    STORAGE_DIR: Path = UPLOAD_DIR
    
    # 1000-page PDF Processing Configurations
    PDF_PAGE_CHUNK_SIZE: int = int(os.getenv("PDF_PAGE_CHUNK_SIZE", "15"))
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "100"))
    
    # OCR settings
    TESSERACT_CMD: str = os.getenv("TESSERACT_CMD", "tesseract")
    IMAGE_DPI: int = 300
    
    # AI / LLM Configuration
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini")  # 'gemini', 'openai', or 'heuristic_fallback'
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # CORS: comma-separated list of allowed frontend origins
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    
    # Validation Rules Settings
    FINANCIAL_TOLERANCE: float = 0.05  # $0.05 allowed float rounding difference
    DUPLICATE_CHECK_ENABLED: bool = True

settings = Settings()
