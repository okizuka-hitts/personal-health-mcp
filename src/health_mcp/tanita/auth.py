import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import set_key

logger = logging.getLogger(__name__)

AUTH_ENDPOINT = "https://www.healthplanet.jp/oauth/auth"
TOKEN_ENDPOINT = "https://www.healthplanet.jp/oauth/token"
REFRESH_THRESHOLD_MINUTES = 30


class TokenManager:
    """Manages OAuth tokens for HealthPlanet API.

    Loads tokens from .env, refreshes when expiry is within 30 minutes,
    and writes updated tokens back to .env AND os.environ simultaneously.
    """

    def __init__(self, dotenv_path: Path | None = None) -> None:
        self._dotenv_path = dotenv_path or Path(".env")
        self._access_token: str = ""
        self._refresh_token: str = ""
        self._expires_at: datetime = datetime.now(timezone.utc)

    def load_from_env(self) -> None:
        """Load token state from environment variables (populated from .env by caller)."""
        self._access_token = os.environ.get("HEALTH_PLANET_ACCESS_TOKEN", "")
        self._refresh_token = os.environ.get("HEALTH_PLANET_REFRESH_TOKEN", "")
        expires_str = os.environ.get("HEALTH_PLANET_TOKEN_EXPIRES_AT", "")
        if expires_str:
            try:
                self._expires_at = datetime.fromisoformat(expires_str)
                if self._expires_at.tzinfo is None:
                    self._expires_at = self._expires_at.replace(tzinfo=timezone.utc)
            except ValueError:
                logger.warning("Invalid TOKEN_EXPIRES_AT format: %s", expires_str)
                self._expires_at = datetime.now(timezone.utc)

    def is_refresh_needed(self) -> bool:
        """Return True if access token expires within 30 minutes."""
        threshold = datetime.now(timezone.utc) + timedelta(minutes=REFRESH_THRESHOLD_MINUTES)
        return self._expires_at <= threshold

    def refresh(self, client_id: str, client_secret: str) -> None:
        """Refresh access token using refresh token.

        Writes new tokens to .env via set_key() AND updates os.environ directly.
        Both updates are required: set_key() alone does not update os.environ.
        """
        logger.info("Refreshing access token...")
        response = httpx.post(
            TOKEN_ENDPOINT,
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": self._refresh_token,
                "redirect_uri": os.environ.get("HEALTH_PLANET_REDIRECT_URI", ""),
            },
        )
        response.raise_for_status()
        data = response.json()

        new_access = data["access_token"]
        new_refresh = data.get("refresh_token", self._refresh_token)
        expires_in: int = data.get("expires_in", 10800)  # default 3 hours
        new_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        expires_str = new_expires_at.isoformat()

        # Update .env file
        set_key(str(self._dotenv_path), "HEALTH_PLANET_ACCESS_TOKEN", new_access)
        set_key(str(self._dotenv_path), "HEALTH_PLANET_REFRESH_TOKEN", new_refresh)
        set_key(str(self._dotenv_path), "HEALTH_PLANET_TOKEN_EXPIRES_AT", expires_str)

        # Update os.environ (set_key alone does NOT update os.environ)
        os.environ["HEALTH_PLANET_ACCESS_TOKEN"] = new_access
        os.environ["HEALTH_PLANET_REFRESH_TOKEN"] = new_refresh
        os.environ["HEALTH_PLANET_TOKEN_EXPIRES_AT"] = expires_str

        # Update in-memory state
        self._access_token = new_access
        self._refresh_token = new_refresh
        self._expires_at = new_expires_at

        logger.info("Token refreshed. Expires at: %s", expires_str)

    def get_access_token(self) -> str:
        """Return valid access token, refreshing if needed."""
        if self.is_refresh_needed():
            client_id = os.environ.get("HEALTH_PLANET_CLIENT_ID", "")
            client_secret = os.environ.get("HEALTH_PLANET_CLIENT_SECRET", "")
            self.refresh(client_id, client_secret)
        return self._access_token
