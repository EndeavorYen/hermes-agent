#!/usr/bin/env python3
"""Upload videos to YouTube using Hermes' narrow youtube.upload OAuth token.

Usage:
  python ~/.hermes/scripts/youtube_upload.py \
    --file /path/video.mp4 \
    --title 'Title' \
    --description 'Description' \
    --privacy private \
    --made-for-kids false \
    --thumbnail /path/thumb.png
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import time
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
TOKEN_PATH = HERMES_HOME / "youtube_token.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def require_deps():
    try:
        from google.oauth2.credentials import Credentials  # noqa: F401
        from google.auth.transport.requests import Request  # noqa: F401
        from googleapiclient.discovery import build  # noqa: F401
        from googleapiclient.http import MediaFileUpload  # noqa: F401
    except Exception as e:
        print(f"MISSING_DEPS: {e}", file=sys.stderr)
        print("Install with: python -m pip install google-api-python-client google-auth-oauthlib google-auth-httplib2", file=sys.stderr)
        sys.exit(2)


def load_creds():
    require_deps()
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    if not TOKEN_PATH.exists():
        raise SystemExit(f"NOT_AUTHENTICATED: No token at {TOKEN_PATH}")
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json())
        TOKEN_PATH.chmod(0o600)
    if not creds.valid:
        raise SystemExit("NOT_AUTHENTICATED: token invalid")
    return creds


def parse_bool(v: str) -> bool:
    v = v.strip().lower()
    if v in {"1", "true", "yes", "y"}:
        return True
    if v in {"0", "false", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("expected true/false")


def normalize_description_text(s: str) -> str:
    """Convert common shell/chat escaped newlines into real newlines for YouTube descriptions."""
    return s.replace("\\r\\n", "\n").replace("\\n", "\n")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--file", required=True, help="Video file to upload")
    p.add_argument("--title", required=True)
    p.add_argument("--description", default="")
    p.add_argument("--description-file", default="", help="Read description from a UTF-8 text file; preferred for multiline descriptions")
    p.add_argument("--privacy", choices=["private", "unlisted", "public"], default="private")
    p.add_argument("--made-for-kids", type=parse_bool, default=False)
    p.add_argument("--tags", default="", help="Comma-separated tags")
    p.add_argument("--category-id", default="1", help="YouTube category ID; 1=Film & Animation, 24=Entertainment, 22=People & Blogs")
    p.add_argument("--thumbnail", default="", help="Optional image file for thumbnail")
    args = p.parse_args()

    video = Path(args.file).expanduser()
    if not video.exists():
        raise SystemExit(f"video file not found: {video}")
    thumb = Path(args.thumbnail).expanduser() if args.thumbnail else None
    if thumb and not thumb.exists():
        raise SystemExit(f"thumbnail file not found: {thumb}")

    require_deps()
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = load_creds()
    youtube = build("youtube", "v3", credentials=creds)

    if args.description_file:
        desc_path = Path(args.description_file).expanduser()
        if not desc_path.exists():
            raise SystemExit(f"description file not found: {desc_path}")
        description = desc_path.read_text(encoding="utf-8")
    else:
        description = normalize_description_text(args.description)

    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    body = {
        "snippet": {
            "title": args.title,
            "description": description,
            "tags": tags,
            "categoryId": args.category_id,
        },
        "status": {
            "privacyStatus": args.privacy,
            "selfDeclaredMadeForKids": args.made_for_kids,
        },
    }

    mime_type = mimetypes.guess_type(str(video))[0] or "video/mp4"
    media = MediaFileUpload(str(video), mimetype=mime_type, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        _status, response = request.next_chunk()

    video_id = response["id"]
    thumbnail_status = None
    if thumb:
        thumb_mime = mimetypes.guess_type(str(thumb))[0] or "image/png"
        last_error = None
        for attempt in range(1, 7):
            try:
                youtube.thumbnails().set(
                    videoId=video_id,
                    media_body=MediaFileUpload(str(thumb), mimetype=thumb_mime),
                ).execute()
                thumbnail_status = "uploaded"
                break
            except Exception as e:
                last_error = e
                time.sleep(10)
        if thumbnail_status != "uploaded":
            thumbnail_status = f"failed_after_upload: {last_error}"

    print(json.dumps({
        "status": "uploaded",
        "video_id": video_id,
        "url": f"https://youtu.be/{video_id}",
        "privacy": args.privacy,
        "made_for_kids": args.made_for_kids,
        "thumbnail": thumbnail_status,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
