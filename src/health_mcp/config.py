import os
from pathlib import Path

from dotenv import load_dotenv

# Anchor: src/health_mcp/config.py → parent=health_mcp → parent=src → parent=PROJECT_ROOT
# __file__ is always the source tree path via editable install (.pth), independent of cwd.
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent
DOTENV_PATH: Path = PROJECT_ROOT / ".env"

load_dotenv(DOTENV_PATH)


def _resolve_db_path() -> Path:
    raw = os.environ.get("SQLITE_DB_PATH", "")
    if not raw:
        return PROJECT_ROOT / "data" / "health.db"
    p = Path(raw)
    if p.is_absolute():
        return p
    return (PROJECT_ROOT / p).resolve()


DB_PATH: Path = _resolve_db_path()
