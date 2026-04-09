"""Tests for HealthStorage using in-memory SQLite."""

import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from health_mcp.storage.sqlite import HealthStorage, _merge_dates_to_ranges
from health_mcp.tanita.models import BodyCompositionRecord, Profile


@pytest.fixture
def storage(tmp_path):
    s = HealthStorage(str(tmp_path / "test.db"))
    s.init_db()
    return s


def make_record(dt: datetime, weight: float = 70.0, fat: float = 18.0) -> BodyCompositionRecord:
    return BodyCompositionRecord(measured_at=dt, weight_kg=weight, body_fat_pct=fat)


class TestProfile:
    def test_get_profile_empty(self, storage):
        assert storage.get_profile() is None

    def test_save_and_get_profile(self, storage):
        p = Profile(
            birth_date="19860101",
            height_cm=175.0,
            sex="male",
            fetched_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )
        storage.save_profile(p)
        result = storage.get_profile()
        assert result is not None
        assert result.birth_date == "19860101"
        assert result.height_cm == 175.0
        assert result.sex == "male"

    def test_delete_profile(self, storage):
        p = Profile("19860101", 175.0, "male", datetime.now(timezone.utc))
        storage.save_profile(p)
        storage.delete_profile()
        assert storage.get_profile() is None

    def test_save_profile_overwrites(self, storage):
        p1 = Profile("19860101", 175.0, "male", datetime.now(timezone.utc))
        p2 = Profile("19900202", 160.0, "female", datetime.now(timezone.utc))
        storage.save_profile(p1)
        storage.save_profile(p2)
        result = storage.get_profile()
        assert result is not None
        assert result.height_cm == 160.0


class TestBodyComposition:
    def test_upsert_and_query_range(self, storage):
        records = [
            make_record(datetime(2026, 4, 1, 8, 0)),
            make_record(datetime(2026, 4, 3, 8, 0), weight=71.0),
            make_record(datetime(2026, 4, 5, 8, 0), weight=72.0),
        ]
        storage.upsert_records(records)
        result = storage.query_range(date(2026, 4, 1), date(2026, 4, 5))
        assert len(result) == 3
        # Descending order
        assert result[0].measured_at > result[1].measured_at

    def test_query_range_excludes_outside(self, storage):
        records = [
            make_record(datetime(2026, 3, 31, 8, 0)),
            make_record(datetime(2026, 4, 1, 8, 0)),
            make_record(datetime(2026, 4, 2, 8, 0)),
        ]
        storage.upsert_records(records)
        result = storage.query_range(date(2026, 4, 1), date(2026, 4, 1))
        assert len(result) == 1

    def test_upsert_replaces_existing(self, storage):
        r1 = make_record(datetime(2026, 4, 1, 8, 0), weight=70.0)
        storage.upsert_records([r1])
        r2 = make_record(datetime(2026, 4, 1, 8, 0), weight=75.0)
        storage.upsert_records([r2])
        result = storage.query_range(date(2026, 4, 1), date(2026, 4, 1))
        assert len(result) == 1
        assert result[0].weight_kg == 75.0

    def test_query_latest(self, storage):
        records = [
            make_record(datetime(2026, 4, 1, 8, 0)),
            make_record(datetime(2026, 4, 5, 8, 0), weight=75.0),
        ]
        storage.upsert_records(records)
        latest = storage.query_latest()
        assert latest is not None
        assert latest.weight_kg == 75.0

    def test_query_latest_empty(self, storage):
        assert storage.query_latest() is None

    def test_query_stats_empty(self, storage):
        stats = storage.query_stats()
        assert stats["count"] == 0

    def test_query_stats(self, storage):
        records = [
            make_record(datetime(2026, 1, 10, 8, 0)),
            make_record(datetime(2026, 4, 7, 12, 30)),
        ]
        storage.upsert_records(records)
        stats = storage.query_stats()
        assert stats["count"] == 2
        assert "2026-01-10" in str(stats["oldest"])
        assert "2026-04-07" in str(stats["latest"])


class TestDifferentialSync:
    def test_all_unsynced_past(self, storage):
        """When nothing is synced, all past dates are returned as periods."""
        periods = storage.get_unsynced_periods(
            date(2026, 4, 1), date(2026, 4, 3), ttl_seconds=3600
        )
        # All 3 days should be in the result (as one merged range)
        flat = [d for s, e in periods for d in _dates_in_range(s, e)]
        assert date(2026, 4, 1) in flat
        assert date(2026, 4, 2) in flat
        assert date(2026, 4, 3) in flat

    def test_synced_past_not_returned(self, storage):
        """Once a past date is synced, it must not appear again."""
        storage.log_sync(date(2026, 4, 1), date(2026, 4, 3), 3)
        periods = storage.get_unsynced_periods(
            date(2026, 4, 1), date(2026, 4, 3), ttl_seconds=3600
        )
        assert periods == []

    def test_partial_sync(self, storage):
        """Only unsynced sub-range is returned."""
        storage.log_sync(date(2026, 4, 1), date(2026, 4, 2), 2)
        periods = storage.get_unsynced_periods(
            date(2026, 4, 1), date(2026, 4, 4), ttl_seconds=3600
        )
        flat = [d for s, e in periods for d in _dates_in_range(s, e)]
        assert date(2026, 4, 1) not in flat
        assert date(2026, 4, 2) not in flat
        assert date(2026, 4, 3) in flat
        assert date(2026, 4, 4) in flat

    def test_today_within_ttl_not_returned(self, storage):
        """Today's data synced within TTL should not be re-fetched."""
        today = date.today()
        storage.log_sync(today, today, 1)
        periods = storage.get_unsynced_periods(today, today, ttl_seconds=3600)
        flat = [d for s, e in periods for d in _dates_in_range(s, e)]
        assert today not in flat

    def test_today_expired_ttl_returned(self, storage):
        """Today's data synced beyond TTL should be re-fetched."""
        today = date.today()
        # Log a sync with a timestamp old enough to exceed TTL
        old_time = (
            datetime.now(timezone.utc) - timedelta(seconds=3700)
        ).isoformat()
        conn = sqlite3.connect(storage._db_path)
        conn.execute(
            "INSERT INTO sync_log (synced_at, from_date, to_date, record_count)"
            " VALUES (?, ?, ?, ?)",
            (old_time, today.isoformat(), today.isoformat(), 1),
        )
        conn.commit()
        conn.close()

        periods = storage.get_unsynced_periods(today, today, ttl_seconds=3600)
        flat = [d for s, e in periods for d in _dates_in_range(s, e)]
        assert today in flat


class TestMergeDatesToRanges:
    def test_empty(self):
        assert _merge_dates_to_ranges([]) == []

    def test_single(self):
        d = date(2026, 4, 1)
        assert _merge_dates_to_ranges([d]) == [(d, d)]

    def test_consecutive(self):
        dates = [date(2026, 4, 1), date(2026, 4, 2), date(2026, 4, 3)]
        result = _merge_dates_to_ranges(dates)
        assert result == [(date(2026, 4, 1), date(2026, 4, 3))]

    def test_gap(self):
        dates = [date(2026, 4, 1), date(2026, 4, 3)]
        result = _merge_dates_to_ranges(dates)
        assert len(result) == 2


def _dates_in_range(start: date, end: date) -> list[date]:
    result = []
    d = start
    while d <= end:
        result.append(d)
        d += timedelta(days=1)
    return result
