import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastmcp import FastMCP

from health_mcp.config import DB_PATH, DOTENV_PATH
from health_mcp.storage.sqlite import HealthStorage
from health_mcp.tanita.auth import TokenManager
from health_mcp.tanita.client import HealthPlanetClient
from health_mcp.tanita.models import Profile

# Windows asyncio compatibility
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Logging (config.py already called load_dotenv, so LOG_LEVEL is available)
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger(__name__)

# Dependencies (initialised once at module load)
_token_manager = TokenManager(dotenv_path=DOTENV_PATH)
_token_manager.load_from_env()

_storage = HealthStorage(str(DB_PATH))
_storage.init_db()

_client = HealthPlanetClient(_token_manager)

_cache_ttl = int(os.environ.get("CACHE_TTL_SECONDS", "3600"))

mcp = FastMCP("personal-health-mcp")


# ---------------------------------------------------------------------------
# Shared helper: differential sync for a date range
# ---------------------------------------------------------------------------

async def _sync_range(start: date, end: date) -> None:
    """Fetch unsynced periods from API and store in SQLite."""
    periods = _storage.get_unsynced_periods(start, end, _cache_ttl)
    for from_d, to_d in periods:
        from_dt = datetime(from_d.year, from_d.month, from_d.day, 0, 0, 0)
        to_dt = datetime(to_d.year, to_d.month, to_d.day, 23, 59, 59)
        response = await _client.fetch_innerscan(from_dt, to_dt)
        records = HealthPlanetClient.parse_records(response)
        count = _storage.upsert_records(records)
        _storage.log_sync(from_d, to_d, count)
        logger.info("Synced %s – %s: %d records", from_d, to_d, count)


# ---------------------------------------------------------------------------
# T-01: get_latest_body_composition
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_latest_body_composition() -> dict[str, Any]:
    """Return the most recent body composition record within the last 30 days."""
    today = date.today()
    start = today - timedelta(days=29)
    await _sync_range(start, today)

    record = _storage.query_latest()
    if record is None:
        return {"error": "No data available"}

    # Verify the latest record is within 30 days
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    measured = record.measured_at
    if measured.tzinfo is None:
        measured = measured.replace(tzinfo=timezone.utc)
    if measured < cutoff:
        return {"error": "No data available"}

    return {
        "measured_at": record.measured_at.isoformat(),
        "weight_kg": record.weight_kg,
        "body_fat_pct": record.body_fat_pct,
    }


# ---------------------------------------------------------------------------
# T-02: get_body_composition
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_body_composition(
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Return body composition data for a date range (max 92 days).

    Args:
        start_date: Start date in YYYY-MM-DD format. Defaults to 30 days ago.
        end_date:   End date in YYYY-MM-DD format. Defaults to today.
    """
    today = date.today()
    start = date.fromisoformat(start_date) if start_date else today - timedelta(days=29)
    end = date.fromisoformat(end_date) if end_date else today

    if start > end:
        return {"error": "start_date must be before or equal to end_date"}
    if (end - start).days > 91:
        return {"error": "Date range exceeds maximum of 92 days"}

    await _sync_range(start, end)

    records = _storage.query_range(start, end)
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "count": len(records),
        "data": [
            {
                "measured_at": r.measured_at.isoformat(),
                "weight_kg": r.weight_kg,
                "body_fat_pct": r.body_fat_pct,
            }
            for r in records
        ],
    }


# ---------------------------------------------------------------------------
# T-03: get_measurements_range
# ---------------------------------------------------------------------------

@mcp.tool()
def get_measurements_range() -> dict[str, Any]:
    """Return the date range and total count of cached body composition data."""
    stats = _storage.query_stats()
    if stats["count"] == 0:
        return {
            "oldest_measurement": None,
            "latest_measurement": None,
            "total_count": 0,
            "message": (
                "No data in cache. Please call get_body_composition to sync data first."
            ),
        }
    return {
        "oldest_measurement": stats["oldest"],
        "latest_measurement": stats["latest"],
        "total_count": stats["count"],
    }


# ---------------------------------------------------------------------------
# T-04: get_profile
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_profile() -> dict[str, Any]:
    """Return user profile (birth_date, height_cm, sex) from cache or API."""
    cached = _storage.get_profile()
    if cached is not None:
        return {
            "birth_date": cached.birth_date,
            "height_cm": cached.height_cm,
            "sex": cached.sex,
        }

    # Fetch from API using today's date range
    today = date.today()
    from_dt = datetime(today.year, today.month, today.day, 0, 0, 0)
    to_dt = datetime(today.year, today.month, today.day, 23, 59, 59)

    response = await _client.fetch_innerscan(from_dt, to_dt)

    if not response.birth_date or not response.height or not response.sex:
        return {"error": "Profile data not available from API"}

    profile = Profile(
        birth_date=response.birth_date,
        height_cm=float(response.height),
        sex=response.sex,
        fetched_at=datetime.now(timezone.utc),
    )
    _storage.save_profile(profile)

    return {
        "birth_date": profile.birth_date,
        "height_cm": profile.height_cm,
        "sex": profile.sex,
    }


# ---------------------------------------------------------------------------
# T-05: list_available_metrics
# ---------------------------------------------------------------------------

@mcp.tool()
def list_available_metrics() -> dict[str, Any]:
    """Return the list of available metrics and their descriptions."""
    return {
        "metrics": [
            {
                "name": "weight_kg",
                "description": "体重 (kg)",
                "source": "Tanita Health Planet API",
                "tool": "get_latest_body_composition / get_body_composition",
            },
            {
                "name": "body_fat_pct",
                "description": "体脂肪率 (%)",
                "source": "Tanita Health Planet API",
                "tool": "get_latest_body_composition / get_body_composition",
            },
            {
                "name": "profile",
                "description": "生年月日・身長・性別（BMI・年齢・心拍ゾーン計算の前提情報）",
                "source": "Tanita Health Planet API",
                "tool": "get_profile",
            },
        ]
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
