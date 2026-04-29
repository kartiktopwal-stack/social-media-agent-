"""
scripts/youtube_oauth_setup.py
─────────────────────────────────────────────────────────────────────────────
One-time YouTube OAuth 2.0 setup script.

Prerequisites:
  1. Download your OAuth 2.0 Client ID JSON from Google Cloud Console
     (APIs & Services → Credentials → OAuth 2.0 Client IDs → Download JSON)
  2. Save it as  client_secret.json  in the project root directory.

What this script does:
  • Reads client_secret.json
  • Opens a browser window for Google sign-in + consent
  • Exchanges the authorization code for access & refresh tokens
  • Saves everything to  token.json  (used by the YouTube publisher)

Usage:
    python scripts/youtube_oauth_setup.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ── Project root = parent of /scripts ────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent

CLIENT_SECRET_FILE = PROJECT_ROOT / "client_secret.json"
TOKEN_FILE = PROJECT_ROOT / "token.json"

# YouTube Data API v3 — upload scope
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _load_client_config(path: Path) -> dict:
    """Read and validate client_secret.json."""
    if not path.exists():
        print(f"\n❌  {path.name} not found at:\n   {path}\n")
        print("Download it from Google Cloud Console:")
        print("  → APIs & Services → Credentials → OAuth 2.0 Client IDs → ⬇ Download JSON")
        print(f"  → Save as  {path.name}  in the project root.\n")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Google wraps the config under "installed" (desktop) or "web" key
    key = "installed" if "installed" in data else "web" if "web" in data else None
    if key is None:
        print("❌  client_secret.json does not contain an 'installed' or 'web' application config.")
        sys.exit(1)

    return data


def _run_oauth_flow(client_secret_path: Path) -> None:
    """Run the browser-based OAuth consent flow and save token.json."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("❌  google-auth-oauthlib is not installed.")
        print("   pip install google-auth-oauthlib")
        sys.exit(1)

    print("\n🔐  Starting YouTube OAuth 2.0 authorization flow …\n")
    print("A URL will be printed below. Open it in your browser,")
    print("sign in with the Google account that owns the YouTube channel,")
    print("approve access, then copy the authorization code back here.\n")

    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_secret_path),
        scopes=SCOPES,
    )

    credentials = flow.run_console()

    if not credentials or not credentials.refresh_token:
        print("\n❌  OAuth flow completed but no refresh token was returned.")
        print("   Try revoking access at https://myaccount.google.com/permissions")
        print("   then run this script again.\n")
        sys.exit(1)

    # Build the token payload
    # Read client_secret.json to extract client_id, client_secret, token_uri
    with open(client_secret_path, "r", encoding="utf-8") as f:
        client_data = json.load(f)

    key = "installed" if "installed" in client_data else "web"
    client_info = client_data[key]

    token_data = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": client_info.get("token_uri", "https://oauth2.googleapis.com/token"),
        "client_id": client_info["client_id"],
        "client_secret": client_info["client_secret"],
        "scopes": SCOPES,
    }

    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(token_data, f, indent=2)

    print(f"\n✅  Token saved to:  {TOKEN_FILE}")
    print("   The YouTube publisher will now use this token automatically.\n")


def main() -> None:
    """Entry-point: check for existing token, run flow if needed."""
    print("=" * 60)
    print("  YouTube OAuth 2.0 Setup")
    print("=" * 60)

    # Check if token.json already exists and has a refresh_token
    if TOKEN_FILE.exists():
        try:
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if existing.get("refresh_token"):
                print(f"\n⚠️   {TOKEN_FILE.name} already exists with a valid refresh token.")
                answer = input("   Overwrite and re-authorize? [y/N]: ").strip().lower()
                if answer != "y":
                    print("   Keeping existing token. Done.\n")
                    return
        except (json.JSONDecodeError, KeyError):
            pass  # corrupted file → re-run flow

    # Validate client_secret.json exists
    _load_client_config(CLIENT_SECRET_FILE)

    # Run the flow
    _run_oauth_flow(CLIENT_SECRET_FILE)


if __name__ == "__main__":
    main()
