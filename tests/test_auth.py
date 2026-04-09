"""Tests for TokenManager."""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from health_mcp.tanita.auth import TokenManager


@pytest.fixture
def dotenv_path(tmp_path) -> Path:
    p = tmp_path / ".env"
    p.write_text(
        "HEALTH_PLANET_ACCESS_TOKEN=old_access\n"
        "HEALTH_PLANET_REFRESH_TOKEN=old_refresh\n"
        f"HEALTH_PLANET_TOKEN_EXPIRES_AT={datetime.now(timezone.utc).isoformat()}\n"
    )
    return p


@pytest.fixture
def manager(dotenv_path) -> TokenManager:
    m = TokenManager(dotenv_path)
    return m


class TestIsRefreshNeeded:
    def test_expires_soon_needs_refresh(self, manager):
        manager._expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        assert manager.is_refresh_needed() is True

    def test_expires_far_no_refresh(self, manager):
        manager._expires_at = datetime.now(timezone.utc) + timedelta(hours=2)
        assert manager.is_refresh_needed() is False

    def test_exactly_30_minutes_needs_refresh(self, manager):
        manager._expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
        assert manager.is_refresh_needed() is True

    def test_already_expired_needs_refresh(self, manager):
        manager._expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        assert manager.is_refresh_needed() is True


class TestLoadFromEnv:
    def test_loads_tokens(self, manager):
        os.environ["HEALTH_PLANET_ACCESS_TOKEN"] = "tok123"
        os.environ["HEALTH_PLANET_REFRESH_TOKEN"] = "ref456"
        expires = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
        os.environ["HEALTH_PLANET_TOKEN_EXPIRES_AT"] = expires
        try:
            manager.load_from_env()
            assert manager._access_token == "tok123"
            assert manager._refresh_token == "ref456"
        finally:
            del os.environ["HEALTH_PLANET_ACCESS_TOKEN"]
            del os.environ["HEALTH_PLANET_REFRESH_TOKEN"]
            del os.environ["HEALTH_PLANET_TOKEN_EXPIRES_AT"]


class TestRefresh:
    def test_refresh_updates_env_and_memory(self, manager, dotenv_path):
        """refresh() must update both .env and os.environ."""
        manager._refresh_token = "old_refresh"
        manager._expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new_access",
            "refresh_token": "new_refresh",
            "expires_in": 10800,
        }
        mock_response.raise_for_status = MagicMock()

        with patch("health_mcp.tanita.auth.httpx.post", return_value=mock_response):
            os.environ["HEALTH_PLANET_REDIRECT_URI"] = "http://localhost/callback"
            try:
                manager.refresh("client_id", "client_secret")
            finally:
                del os.environ["HEALTH_PLANET_REDIRECT_URI"]

        # In-memory state updated
        assert manager._access_token == "new_access"
        assert manager._refresh_token == "new_refresh"

        # os.environ updated
        assert os.environ.get("HEALTH_PLANET_ACCESS_TOKEN") == "new_access"
        assert os.environ.get("HEALTH_PLANET_REFRESH_TOKEN") == "new_refresh"

        # .env file updated
        content = dotenv_path.read_text()
        assert "new_access" in content
        assert "new_refresh" in content

    def test_get_access_token_triggers_refresh_when_needed(self, manager):
        manager._access_token = "current"
        manager._expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)

        with patch.object(manager, "refresh") as mock_refresh:
            manager._access_token = "refreshed"
            mock_refresh.side_effect = lambda *a: setattr(
                manager, "_access_token", "refreshed"
            )
            os.environ["HEALTH_PLANET_CLIENT_ID"] = "cid"
            os.environ["HEALTH_PLANET_CLIENT_SECRET"] = "csecret"
            try:
                manager.get_access_token()
            finally:
                del os.environ["HEALTH_PLANET_CLIENT_ID"]
                del os.environ["HEALTH_PLANET_CLIENT_SECRET"]

        mock_refresh.assert_called_once()
