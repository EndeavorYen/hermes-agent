#!/usr/bin/env python3
"""YouTube Data API OAuth helper for story-video publishing.

Creates a token with only the YouTube upload scope, separate from broader Google
Workspace tokens. Intended for agents to run when a story-video pipeline needs
automatic YouTube publishing.

Usage:
  python scripts/youtube_oauth.py auth-url --client-secret /path/client_secret.json
  python scripts/youtube_oauth.py auth-code 'http://localhost:1/?code=...'
  python scripts/youtube_oauth.py check
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERMES_HOME = Path.home() / ".hermes"
CLIENT_SECRET_PATH = HERMES_HOME / "youtube_client_secret.json"
TOKEN_PATH = HERMES_HOME / "youtube_token.json"
AUTH_URL_PATH = HERMES_HOME / "youtube_oauth_last_url.txt"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
REDIRECT_URI = "http://localhost:1"


def require_deps():
    try:
        from google.oauth2.credentials import Credentials  # noqa: F401
        from google.auth.transport.requests import Request  # noqa: F401
        from google_auth_oauthlib.flow import Flow  # noqa: F401
    except Exception as e:
        print(f"MISSING_DEPS: {e}", file=sys.stderr)
        print(
            "Install with: python -m pip install google-api-python-client google-auth-oauthlib google-auth-httplib2",
            file=sys.stderr,
        )
        sys.exit(2)


def cmd_auth_url(args):
    require_deps()
    from google_auth_oauthlib.flow import Flow

    HERMES_HOME.mkdir(parents=True, exist_ok=True)
    src = Path(args.client_secret).expanduser()
    if not src.exists():
        print(json.dumps({"status": "error", "error": f"client secret not found: {src}"}, ensure_ascii=False))
        return 1
    shutil.copyfile(src, CLIENT_SECRET_PATH)
    CLIENT_SECRET_PATH.chmod(0o600)

    flow = Flow.from_client_secrets_file(str(CLIENT_SECRET_PATH), scopes=SCOPES, redirect_uri=REDIRECT_URI)
    auth_url, _state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )
    AUTH_URL_PATH.write_text(auth_url)
    print(json.dumps({
        "status": "auth_url_generated",
        "auth_url": auth_url,
        "scopes": SCOPES,
        "client_secret_path": str(CLIENT_SECRET_PATH),
        "token_path": str(TOKEN_PATH),
    }, ensure_ascii=False))
    return 0


def extract_code(s: str) -> str:
    s = s.strip()
    if s.startswith("http://") or s.startswith("https://"):
        q = parse_qs(urlparse(s).query)
        if q.get("error"):
            raise ValueError("OAuth error from redirect URL: " + q["error"][0])
        code = q.get("code", [""])[0]
        if not code:
            raise ValueError("No code= parameter found in URL")
        return code
    return s


def cmd_auth_code(args):
    require_deps()
    from google_auth_oauthlib.flow import Flow

    if not CLIENT_SECRET_PATH.exists():
        print(json.dumps({"status": "error", "error": f"missing client secret: {CLIENT_SECRET_PATH}"}, ensure_ascii=False))
        return 1
    code = extract_code(args.code)
    flow = Flow.from_client_secrets_file(str(CLIENT_SECRET_PATH), scopes=SCOPES, redirect_uri=REDIRECT_URI)
    flow.fetch_token(code=code)
    creds = flow.credentials
    TOKEN_PATH.write_text(creds.to_json())
    TOKEN_PATH.chmod(0o600)
    print(json.dumps({
        "status": "authenticated",
        "token_path": str(TOKEN_PATH),
        "scopes": list(creds.scopes or SCOPES),
        "has_refresh_token": bool(creds.refresh_token),
        "valid": bool(creds.valid),
    }, ensure_ascii=False))
    return 0


def cmd_check(_args):
    require_deps()
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    if not TOKEN_PATH.exists():
        print(f"NOT_AUTHENTICATED: No token at {TOKEN_PATH}")
        return 1
    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json())
            TOKEN_PATH.chmod(0o600)
        if creds.valid:
            print("AUTHENTICATED")
            return 0
        print("NOT_AUTHENTICATED: token invalid")
        return 1
    except Exception as e:
        print(f"NOT_AUTHENTICATED: {e}")
        return 1


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("auth-url")
    a.add_argument("--client-secret", required=True)
    c = sub.add_parser("auth-code")
    c.add_argument("code")
    sub.add_parser("check")
    args = p.parse_args()
    if args.cmd == "auth-url":
        raise SystemExit(cmd_auth_url(args))
    if args.cmd == "auth-code":
        raise SystemExit(cmd_auth_code(args))
    if args.cmd == "check":
        raise SystemExit(cmd_check(args))


if __name__ == "__main__":
    main()
