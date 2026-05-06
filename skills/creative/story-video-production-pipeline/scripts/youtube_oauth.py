#!/usr/bin/env python3
"""YouTube Data API OAuth helper for Hermes story-video publishing.

Usage:
  python ~/.hermes/scripts/youtube_oauth.py auth-url --client-secret /path/client_secret.json
  python ~/.hermes/scripts/youtube_oauth.py auth-code 'http://localhost:1/?code=...'
  python ~/.hermes/scripts/youtube_oauth.py check
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import secrets
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERMES_HOME = Path.home() / ".hermes"
CLIENT_SECRET_PATH = HERMES_HOME / "youtube_client_secret.json"
TOKEN_PATH = HERMES_HOME / "youtube_token.json"
AUTH_URL_PATH = HERMES_HOME / "youtube_oauth_last_url.txt"
PENDING_PATH = HERMES_HOME / "youtube_oauth_pending.json"
DEFAULT_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
MANAGE_SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
REDIRECT_URI = "http://localhost"


def require_deps():
    try:
        from google.oauth2.credentials import Credentials  # noqa: F401
        from google.auth.transport.requests import Request  # noqa: F401
        from google_auth_oauthlib.flow import Flow  # noqa: F401
    except Exception as e:
        print(f"MISSING_DEPS: {e}", file=sys.stderr)
        print("Install with: python -m pip install google-api-python-client google-auth-oauthlib google-auth-httplib2", file=sys.stderr)
        sys.exit(2)


def selected_scopes(args=None):
    if args is not None and getattr(args, "manage", False):
        return MANAGE_SCOPES
    return DEFAULT_SCOPES


def cmd_auth_url(args):
    require_deps()
    from google_auth_oauthlib.flow import Flow

    scopes = selected_scopes(args)
    HERMES_HOME.mkdir(parents=True, exist_ok=True)
    src = Path(args.client_secret).expanduser()
    if not src.exists():
        print(json.dumps({"status": "error", "error": f"client secret not found: {src}"}, ensure_ascii=False))
        return 1
    if src.resolve() != CLIENT_SECRET_PATH.resolve():
        shutil.copyfile(src, CLIENT_SECRET_PATH)
    CLIENT_SECRET_PATH.chmod(0o600)

    code_verifier = secrets.token_urlsafe(64)
    flow = Flow.from_client_secrets_file(
        str(CLIENT_SECRET_PATH),
        scopes=scopes,
        redirect_uri=REDIRECT_URI,
        code_verifier=code_verifier,
        autogenerate_code_verifier=False,
    )
    auth_url, _state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )
    AUTH_URL_PATH.write_text(auth_url)
    PENDING_PATH.write_text(json.dumps({"state": _state, "code_verifier": code_verifier, "scopes": scopes}, ensure_ascii=False))
    PENDING_PATH.chmod(0o600)
    print(json.dumps({
        "status": "auth_url_generated",
        "auth_url": auth_url,
        "scopes": scopes,
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


def extract_state(s: str) -> str | None:
    s = s.strip()
    if s.startswith("http://") or s.startswith("https://"):
        q = parse_qs(urlparse(s).query)
        return q.get("state", [None])[0]
    return None


def cmd_auth_code(args):
    require_deps()
    from google_auth_oauthlib.flow import Flow

    if not CLIENT_SECRET_PATH.exists():
        print(json.dumps({"status": "error", "error": f"missing client secret: {CLIENT_SECRET_PATH}"}, ensure_ascii=False))
        return 1
    if not PENDING_PATH.exists():
        print(json.dumps({"status": "error", "error": f"missing pending OAuth session: {PENDING_PATH}; generate a fresh auth URL"}, ensure_ascii=False))
        return 1
    pending = json.loads(PENDING_PATH.read_text())
    state = extract_state(args.code)
    if state and pending.get("state") and state != pending.get("state"):
        print(json.dumps({"status": "error", "error": "OAuth state mismatch; generate a fresh auth URL"}, ensure_ascii=False))
        return 1
    code = extract_code(args.code)
    scopes = pending.get("scopes") or DEFAULT_SCOPES
    flow = Flow.from_client_secrets_file(
        str(CLIENT_SECRET_PATH),
        scopes=scopes,
        redirect_uri=REDIRECT_URI,
        code_verifier=pending["code_verifier"],
        autogenerate_code_verifier=False,
    )
    flow.fetch_token(code=code)
    creds = flow.credentials
    TOKEN_PATH.write_text(creds.to_json())
    TOKEN_PATH.chmod(0o600)
    print(json.dumps({
        "status": "authenticated",
        "token_path": str(TOKEN_PATH),
        "scopes": list(creds.scopes or scopes),
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
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), DEFAULT_SCOPES + MANAGE_SCOPES)
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
    a.add_argument("--manage", action="store_true", help="Request youtube.force-ssl scope for metadata updates, not only upload")
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
