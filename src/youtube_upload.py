"""YouTube Data API v3 upload (approval-gated only).

Authenticates with OAuth2 (client secrets + refresh token from env), performs a
resumable upload, and sets title/description/tags/category/privacy (and
optionally publishAt for scheduling).

This script is ONLY invoked by the publish_approved_video workflow after the
user has explicitly approved the video via Telegram.

Secrets (env, never in code):
  YOUTUBE_CLIENT_SECRETS   -> JSON string of the OAuth client secrets
  YOUTUBE_REFRESH_TOKEN    -> OAuth refresh token
  YOUTUBE_CATEGORY_ID      -> optional; defaults to config (Education=27)

Usage:
  python src/youtube_upload.py --manifest output/pending_video_review.json \
      --index 0 --privacy unlisted [--title-index 2] [--custom-title "..."] \
      [--publish-at 2026-09-01T10:00:00Z]
"""
from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src import utils  # noqa: E402

logger = logging.getLogger("youtube_upload")


def _load_review(manifest_path: pathlib.Path, index: int) -> dict:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    reviews = data["videos"]
    if index >= len(reviews):
        raise RuntimeError(f"index {index} out of range (have {len(reviews)} reviews)")
    return reviews[index]


def build_credentials(client_secrets_json: str, refresh_token: str):
    """Build OAuth2 credentials from a client-secrets JSON string + refresh token."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    info = json.loads(client_secrets_json)
    # Accept both installed-app and web client JSON shapes.
    installed = info.get("installed") or info.get("web")
    if not installed:
        raise RuntimeError("client_secrets JSON missing 'installed'/'web' section")

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=installed["client_id"],
        client_secret=installed["client_secret"],
    )
    creds.refresh(Request())
    return creds


def upload(service, file_path: str, title: str, description: str,
           tags: list[str], category_id: int, privacy: str,
           publish_at: str | None) -> str:
    from googleapiclient.http import MediaFileUpload

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": str(category_id),
        },
        "status": {"privacyStatus": privacy},
    }
    if publish_at and privacy == "scheduled":
        body["status"]["publishAt"] = publish_at

    media = MediaFileUpload(file_path, chunksize=1024 * 1024, resumable=True)
    request = service.videos().insert(part="snippet,status", body=body,
                                      media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logger.info("Uploaded %d%%", int(status.progress() * 100))
    video_id = response["id"]
    logger.info("Upload complete. video_id=%s", video_id)
    return video_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Upload an approved video to YouTube")
    parser.add_argument("--manifest", required=True, help="path to pending_video_review.json")
    parser.add_argument("--index", type=int, default=0, help="which review in the manifest")
    parser.add_argument("--title-index", type=int, default=0,
                        help="which of the 5 suggested titles to use")
    parser.add_argument("--custom-title", default=None, help="override the title entirely")
    parser.add_argument("--privacy", default=None,
                        choices=["public", "unlisted", "private", "scheduled"])
    parser.add_argument("--publish-at", default=None,
                        help="ISO timestamp, only used when privacy=scheduled")
    args = parser.parse_args(argv)

    utils.setup_logging("youtube_upload")
    try:
        review = _load_review(pathlib.Path(args.manifest), args.index)

        title = args.custom_title or review["titles"][args.title_index]
        description = review["description"]
        tags = review["tags"]
        content_type = review["content_type"]

        settings = utils.load_config("config/settings.yaml")
        category_id = int(utils.getenv("YOUTUBE_CATEGORY_ID") or settings["youtube"]["category"])
        privacy = args.privacy or settings["youtube"]["default_privacy"]

        client_secrets = utils.getenv_required("YOUTUBE_CLIENT_SECRETS")
        refresh_token = utils.getenv_required("YOUTUBE_REFRESH_TOKEN")
        creds = build_credentials(client_secrets, refresh_token)

        from googleapiclient.discovery import build
        service = build("youtube", "v3", credentials=creds)

        video_id = upload(service, review["video_path"], title, description,
                          tags, category_id, privacy, args.publish_at)

        status = {"ok": True, "video_id": video_id, "title": title,
                  "privacy": privacy, "content_type": content_type,
                  "timestamp": utils.utc_now_iso()}
        utils.write_manifest(REPO_ROOT / "logs" / "upload_status.json", status)
        logger.info("Upload OK: id=%s privacy=%s", video_id, privacy)
        return 0
    except Exception as exc:  # noqa: BLE001 - entry point logs + exits non-zero
        logger.error("youtube_upload failed: %s", exc)
        return 1


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

if __name__ == "__main__":
    sys.exit(main())
