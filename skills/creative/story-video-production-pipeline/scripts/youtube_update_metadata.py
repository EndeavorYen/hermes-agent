#!/usr/bin/env python3
"""Update an existing YouTube video's title/description/tags/status and optional thumbnail.

Designed for story-video publishing repairs after upload. Uses the OAuth token from
~/.hermes/youtube_token.json by default. Never prints token contents.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

DEFAULT_TOKEN = Path.home() / ".hermes" / "youtube_token.json"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


def read_description(args: argparse.Namespace) -> str:
    if args.description_file:
        return Path(args.description_file).read_text(encoding="utf-8")
    if args.description is None:
        return ""
    # Accept either true multiline strings or accidental literal \n escapes.
    return args.description.replace("\\n", "\n")


def get_client(token_path: Path):
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")
        token_path.chmod(0o600)
    return build("youtube", "v3", credentials=creds)


def parse_tags(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    return [t.strip() for t in raw.split(",") if t.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair existing YouTube video metadata and thumbnail")
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--title")
    parser.add_argument("--description")
    parser.add_argument("--description-file")
    parser.add_argument("--tags", help="Comma-separated tags")
    parser.add_argument("--category-id", default=None)
    parser.add_argument("--privacy", choices=["private", "unlisted", "public"], default=None)
    parser.add_argument("--made-for-kids", choices=["true", "false"], default=None)
    parser.add_argument("--language", default="zh-Hant")
    parser.add_argument("--thumbnail")
    parser.add_argument("--token", type=Path, default=DEFAULT_TOKEN)
    args = parser.parse_args()

    if args.description and args.description_file:
        raise SystemExit("Use either --description or --description-file, not both")

    yt = get_client(args.token)
    current_resp = yt.videos().list(part="snippet,status", id=args.video_id).execute()
    if not current_resp.get("items"):
        raise SystemExit(f"Video not found or inaccessible: {args.video_id}")
    current = current_resp["items"][0]
    snippet: dict[str, Any] = current["snippet"]
    status: dict[str, Any] = current["status"]

    new_desc = read_description(args) if (args.description or args.description_file) else snippet.get("description", "")
    new_tags = parse_tags(args.tags)

    body = {
        "id": args.video_id,
        "snippet": {
            "title": args.title or snippet.get("title", ""),
            "description": new_desc,
            "tags": new_tags if new_tags is not None else snippet.get("tags", []),
            "categoryId": args.category_id or snippet.get("categoryId", "1"),
            "defaultLanguage": args.language,
            "defaultAudioLanguage": args.language,
        },
        "status": {
            "privacyStatus": args.privacy or status.get("privacyStatus", "private"),
            "selfDeclaredMadeForKids": (args.made_for_kids == "true") if args.made_for_kids is not None else status.get("selfDeclaredMadeForKids", True),
            "embeddable": status.get("embeddable", True),
            "license": status.get("license", "youtube"),
            "publicStatsViewable": status.get("publicStatsViewable", True),
        },
    }

    updated = yt.videos().update(part="snippet,status", body=body).execute()
    thumb_result = None
    if args.thumbnail:
        thumb_path = Path(args.thumbnail)
        media = MediaFileUpload(str(thumb_path), mimetype="image/jpeg" if thumb_path.suffix.lower() in {".jpg", ".jpeg"} else None, resumable=False)
        thumb_result = yt.thumbnails().set(videoId=args.video_id, media_body=media).execute()

    verify = yt.videos().list(part="snippet,status", id=args.video_id).execute()["items"][0]
    desc = verify["snippet"].get("description", "")
    result = {
        "video_id": args.video_id,
        "title": verify["snippet"].get("title"),
        "privacy": verify["status"].get("privacyStatus"),
        "made_for_kids": verify["status"].get("selfDeclaredMadeForKids"),
        "description_has_literal_backslash_n": "\\n" in desc,
        "description_real_newline_count": desc.count("\n"),
        "thumbnail_updated": thumb_result is not None,
        "thumbnail_keys": list(verify["snippet"].get("thumbnails", {}).keys()),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
