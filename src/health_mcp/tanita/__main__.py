"""Initial OAuth authentication CLI.

Usage:
    python -m health_mcp.tanita.auth          # Run initial OAuth flow
    python -m health_mcp.tanita.auth --reset-profile  # Clear cached profile
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from dotenv import set_key

from health_mcp.config import DB_PATH, DOTENV_PATH

AUTH_ENDPOINT = "https://www.healthplanet.jp/oauth/auth"
TOKEN_ENDPOINT = "https://www.healthplanet.jp/oauth/token"


def _reset_profile() -> None:
    """Delete cached profile from SQLite."""
    from health_mcp.storage.sqlite import HealthStorage

    storage = HealthStorage(str(DB_PATH))
    storage.init_db()
    storage.delete_profile()
    print("Profile cache cleared. Next call to get_profile will re-fetch from API.")


def _run_oauth_flow() -> None:
    """Run the initial OAuth 2.0 authorization code flow."""
    client_id = os.environ.get("HEALTH_PLANET_CLIENT_ID", "")
    client_secret = os.environ.get("HEALTH_PLANET_CLIENT_SECRET", "")
    redirect_uri = os.environ.get("HEALTH_PLANET_REDIRECT_URI", "")

    if not client_id or not client_secret:
        print("Error: HEALTH_PLANET_CLIENT_ID and HEALTH_PLANET_CLIENT_SECRET must be set in .env")
        sys.exit(1)

    # Step 1: Build authorization URL
    params = urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "innerscan",
        "response_type": "code",
    })
    auth_url = f"{AUTH_ENDPOINT}?{params}"
    print("\n=== Tanita HealthPlanet Authorization ===")
    print(f"\nOpen the following URL in your browser:\n\n  {auth_url}\n")
    print('Click "Allow Access", then paste the full redirect URL below.')

    # Step 2: Get redirect URL from user
    redirect_url = input("Redirect URL: ").strip()

    # Step 3: Extract authorization code
    parsed = urlparse(redirect_url)
    qs = parse_qs(parsed.query)
    code_list = qs.get("code", [])
    if not code_list:
        print("Error: 'code' parameter not found in the redirect URL.")
        sys.exit(1)
    code = code_list[0]

    # Step 4: Exchange code for tokens
    response = httpx.post(
        TOKEN_ENDPOINT,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "code": code,
            "grant_type": "authorization_code",
        },
    )
    if response.status_code != 200:
        print(f"Error: Token request failed ({response.status_code}): {response.text}")
        sys.exit(1)

    data = response.json()
    access_token = data["access_token"]
    refresh_token = data["refresh_token"]
    expires_in: int = data.get("expires_in", 10800)
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()

    # Step 5: Write tokens to .env (set_key) and os.environ
    set_key(str(DOTENV_PATH), "HEALTH_PLANET_ACCESS_TOKEN", access_token)
    set_key(str(DOTENV_PATH), "HEALTH_PLANET_REFRESH_TOKEN", refresh_token)
    set_key(str(DOTENV_PATH), "HEALTH_PLANET_TOKEN_EXPIRES_AT", expires_at)

    os.environ["HEALTH_PLANET_ACCESS_TOKEN"] = access_token
    os.environ["HEALTH_PLANET_REFRESH_TOKEN"] = refresh_token
    os.environ["HEALTH_PLANET_TOKEN_EXPIRES_AT"] = expires_at

    print(f"\nTokens saved to {DOTENV_PATH}")
    print(f"Access token expires at: {expires_at}")
    print("\nAuthentication complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Tanita HealthPlanet auth CLI")
    parser.add_argument(
        "--reset-profile",
        action="store_true",
        help="Clear cached profile data (re-fetched on next get_profile call)",
    )
    args = parser.parse_args()

    # load_dotenv is already called by health_mcp.config import

    if args.reset_profile:
        _reset_profile()
    else:
        _run_oauth_flow()


if __name__ == "__main__":
    main()
