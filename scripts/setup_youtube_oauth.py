"""One-time helper: create a YouTube API OAuth client + refresh token.

Run this ON YOUR MACHINE (not on GitHub Actions, not on Hermes) once, to
produce the two credentials that go into GitHub Secrets:

  1. YOUTUBE_CLIENT_SECRETS  -> the OAuth client_secrets JSON (as a single-line string)
  2. YOUTUBE_REFRESH_TOKEN   -> the refresh token

Prerequisites:
  - You created an OAuth 2.0 Client ID in Google Cloud Console
    (https://console.cloud.google.com/apis/credentials) with the
    "YouTube Data API v3" enabled.
  - You downloaded the client_secret_*.json for that client.

Usage:
  pip install google-api-python-client google-auth-oauthlib
  python scripts/setup_youtube_oauth.py /path/to/client_secret.json

It opens a browser, asks you to approve, then prints the two values to paste
into GitHub Secrets. Never commit the printed values.
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    secret_file = sys.argv[1]

    try:
        with open(secret_file) as f:
            info = json.load(f)
    except Exception as exc:  # noqa: BLE001
        print(f"Could not read client secrets: {exc}")
        return 1

    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    SCOPES = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
    ]

    flow = InstalledAppFlow.from_client_config(info, SCOPES)
    creds = flow.run_local_server(port=0)

    # Persist so re-running refreshes instead of re-consenting.
    token_file = "token.json"
    with open(token_file, "w") as f:
        f.write(creds.to_json())
    print(f"Tokens saved to {token_file}")

    client_json = json.dumps(info)
    print("\n" + "=" * 60)
    print("PASTE INTO GITHUB SECRET  YOUTUBE_CLIENT_SECRETS")
    print("(single-line JSON):")
    print(client_json)
    print("=" * 60)
    print("\nRefresh token (set as GitHub Secret  YOUTUBE_REFRESH_TOKEN):")
    print(creds.refresh_token)
    print("\nAlso test the token refreshes:")
    creds.refresh(Request())
    print("Token refresh OK.")

    print("\nThen set the other GitHub Secrets: GOOGLE_API_KEY, GROQ_API_KEY,")
    print("PEXELS_API_KEY (all optional but recommended).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
