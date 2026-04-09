import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from health_mcp.tanita.models import BodyCompositionRecord, Profile

TAG_WEIGHT = "6021"
TAG_BODY_FAT = "6022"


class HealthStorage:
    def __init__(self, db_path: str) -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = str(path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        """Create tables if they do not exist."""
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS profile (
                    id INTEGER PRIMARY KEY,
                    birth_date TEXT NOT NULL,
                    height_cm REAL NOT NULL,
                    sex TEXT NOT NULL,
                    fetched_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS body_composition (
                    measured_at TEXT PRIMARY KEY,
                    weight_kg REAL,
                    body_fat_pct REAL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sync_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    synced_at TEXT NOT NULL,
                    from_date TEXT NOT NULL,
                    to_date TEXT NOT NULL,
                    record_count INTEGER NOT NULL
                );
            """)

    # ------------------------------------------------------------------
    # profile
    # ------------------------------------------------------------------

    def get_profile(self) -> Profile | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM profile WHERE id = 1").fetchone()
        if row is None:
            return None
        return Profile(
            birth_date=row["birth_date"],
            height_cm=row["height_cm"],
            sex=row["sex"],
            fetched_at=datetime.fromisoformat(row["fetched_at"]),
        )

    def save_profile(self, p: Profile) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO profile (id, birth_date, height_cm, sex, fetched_at)
                VALUES (1, ?, ?, ?, ?)
                """,
                (p.birth_date, p.height_cm, p.sex, p.fetched_at.isoformat()),
            )

    def delete_profile(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM profile WHERE id = 1")

    # ------------------------------------------------------------------
    # body_composition
    # ------------------------------------------------------------------

    def upsert_records(self, records: list[BodyCompositionRecord]) -> int:
        """Insert or replace records. Returns number of records processed."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO body_composition"
                " (measured_at, weight_kg, body_fat_pct, created_at)"
                " VALUES (?, ?, ?, ?)",
                [
                    (r.measured_at.isoformat(), r.weight_kg, r.body_fat_pct, now)
                    for r in records
                ],
            )
        return len(records)

    def query_range(self, start: date, end: date) -> list[BodyCompositionRecord]:
        """Return records in [start, end] sorted newest-first."""
        start_str = f"{start.isoformat()}T00:00:00"
        end_str = f"{end.isoformat()}T23:59:59"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT measured_at, weight_kg, body_fat_pct
                FROM body_composition
                WHERE measured_at >= ? AND measured_at <= ?
                ORDER BY measured_at DESC
                """,
                (start_str, end_str),
            ).fetchall()
        return [
            BodyCompositionRecord(
                measured_at=datetime.fromisoformat(row["measured_at"]),
                weight_kg=row["weight_kg"],
                body_fat_pct=row["body_fat_pct"],
            )
            for row in rows
        ]

    def query_latest(self) -> BodyCompositionRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT measured_at, weight_kg, body_fat_pct
                FROM body_composition
                ORDER BY measured_at DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return BodyCompositionRecord(
            measured_at=datetime.fromisoformat(row["measured_at"]),
            weight_kg=row["weight_kg"],
            body_fat_pct=row["body_fat_pct"],
        )

    def query_stats(self) -> dict[str, object]:
        """Return oldest/latest measured_at and total count."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MIN(measured_at) AS oldest, MAX(measured_at) AS latest, COUNT(*) AS cnt "
                "FROM body_composition"
            ).fetchone()
        return {
            "oldest": row["oldest"],
            "latest": row["latest"],
            "count": row["cnt"],
        }

    # ------------------------------------------------------------------
    # sync_log & differential sync
    # ------------------------------------------------------------------

    def log_sync(self, from_date: date, to_date: date, record_count: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sync_log (synced_at, from_date, to_date, record_count)"
                " VALUES (?, ?, ?, ?)",
                (now, from_date.isoformat(), to_date.isoformat(), record_count),
            )

    def get_unsynced_periods(
        self, start: date, end: date, ttl_seconds: int
    ) -> list[tuple[date, date]]:
        """
        Return date ranges within [start, end] that need to be fetched from API.

        Rules:
        - Past dates: sync only if not recorded in sync_log
        - Today: sync if last sync for today was >= ttl_seconds ago
        """
        today = date.today()

        # Build set of synced past dates
        synced_dates: set[date] = set()
        today_last_synced: datetime | None = None

        with self._connect() as conn:
            # All synced date ranges (for past dates)
            past_rows = conn.execute(
                "SELECT from_date, to_date FROM sync_log ORDER BY from_date"
            ).fetchall()
            for row in past_rows:
                fd = date.fromisoformat(row["from_date"])
                td = date.fromisoformat(row["to_date"])
                d = fd
                while d <= td:
                    synced_dates.add(d)
                    from datetime import timedelta
                    d += timedelta(days=1)

            # Last sync time for today
            today_row = conn.execute(
                "SELECT synced_at FROM sync_log WHERE from_date <= ? AND to_date >= ? "
                "ORDER BY synced_at DESC LIMIT 1",
                (today.isoformat(), today.isoformat()),
            ).fetchone()
            if today_row:
                today_last_synced = datetime.fromisoformat(today_row["synced_at"])

        # Determine which dates need syncing
        needs_sync: list[date] = []
        current = start
        from datetime import timedelta

        while current <= end:
            if current < today:
                if current not in synced_dates:
                    needs_sync.append(current)
            elif current == today:
                if today_last_synced is None:
                    needs_sync.append(current)
                else:
                    now = datetime.now(timezone.utc)
                    # Normalize timezone for comparison
                    last = today_last_synced
                    if last.tzinfo is None:
                        last = last.replace(tzinfo=timezone.utc)
                    elapsed = (now - last).total_seconds()
                    if elapsed >= ttl_seconds:
                        needs_sync.append(current)
            current += timedelta(days=1)

        if not needs_sync:
            return []

        # Merge consecutive dates into ranges
        return _merge_dates_to_ranges(needs_sync)


def _merge_dates_to_ranges(dates: list[date]) -> list[tuple[date, date]]:
    """Merge a sorted list of dates into contiguous ranges."""
    from datetime import timedelta

    if not dates:
        return []
    ranges: list[tuple[date, date]] = []
    range_start = dates[0]
    prev = dates[0]
    for d in dates[1:]:
        if d == prev + timedelta(days=1):
            prev = d
        else:
            ranges.append((range_start, prev))
            range_start = d
            prev = d
    ranges.append((range_start, prev))
    return ranges
