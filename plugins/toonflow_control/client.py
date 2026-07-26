"""Strict client for Toonflow's external Control Contract 1.0."""

from __future__ import annotations

import json
import os
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse, urlunparse
from urllib.request import Request, urlopen

DEFAULT_CONTROL_URL = "http://127.0.0.1:10588"
CONTRACT_VERSION = "1.0"


class ToonflowControlError(RuntimeError):
    """A sanitized failure returned by or while contacting Toonflow."""

    def __init__(
        self,
        message: str,
        *,
        failure_class: str = "provider_unavailable",
        retryable: bool = False,
        user_action: str = "",
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_class = failure_class
        self.retryable = retryable
        self.user_action = user_action
        self.status_code = status_code


class ToonflowControlClient:
    """Dependency-free, loopback-only adapter for `/control/v1`."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        token: str | None = None,
        timeout: float = 30.0,
        allow_remote_for_tests: bool = False,
    ) -> None:
        self.base_url = _normalize_base_url(
            base_url or os.environ.get("TOONFLOW_CONTROL_URL") or DEFAULT_CONTROL_URL,
            allow_remote_for_tests=allow_remote_for_tests,
        )
        self._token = token if token is not None else os.environ.get("TOONFLOW_CONTROL_TOKEN")
        self._timeout = timeout

    def capabilities(self) -> dict[str, Any]:
        return self._request("GET", "/control/v1/capabilities")

    def create_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/control/v1/projects", payload)

    def create_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/control/v1/runs", payload)

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/control/v1/runs/{_identifier(run_id)}")

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/control/v1/runs/{_identifier(run_id)}/cancel",
        )

    def select_artifact(
        self,
        run_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/control/v1/runs/{_identifier(run_id)}/selection",
            payload,
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = (self._token or "").strip()
        if not token:
            raise ToonflowControlError(
                "Toonflow control is not configured.",
                failure_class="setup_required",
                user_action="Set TOONFLOW_CONTROL_TOKEN.",
            )
        if not path.startswith("/control/v1/"):
            raise ValueError("Toonflow control requests must use /control/v1")

        body = None
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "X-Contract-Version": CONTRACT_VERSION,
        }
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                return _decode_object(response.read())
        except HTTPError as exc:
            try:
                error_payload = _decode_error_object(exc.read())
            except Exception:
                error_payload = {}
            raise _control_error(error_payload, status_code=exc.code) from None
        except (URLError, TimeoutError, socket.timeout, OSError):
            raise ToonflowControlError(
                "Toonflow control is unavailable.",
                failure_class="provider_unavailable",
                retryable=True,
                user_action="Confirm the local Toonflow Control API is running.",
            ) from None


def _normalize_base_url(value: str, *, allow_remote_for_tests: bool) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Toonflow control URL must be an HTTP origin")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Toonflow control URL must not contain credentials")
    if parsed.query or parsed.fragment or parsed.params:
        raise ValueError("Toonflow control URL must not contain query or fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("Toonflow control URL must be an origin without a path")
    if not allow_remote_for_tests and parsed.hostname not in {
        "127.0.0.1",
        "::1",
        "localhost",
    }:
        raise ValueError("Toonflow control URL must use a loopback host")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Toonflow control URL has an invalid port") from exc
    host = parsed.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    netloc = f"{host}:{port}" if port is not None else host
    return urlunparse((parsed.scheme, netloc, "", "", "", ""))


def _identifier(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("Toonflow identifier must be a non-empty string")
    return quote(value, safe="")


def _decode_object(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ToonflowControlError(
            "Toonflow returned an invalid JSON response.",
            failure_class="invalid_response",
        ) from None
    if not isinstance(value, dict):
        raise ToonflowControlError(
            "Toonflow returned an invalid response object.",
            failure_class="invalid_response",
        )
    return value


def _decode_error_object(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _control_error(
    payload: dict[str, Any],
    *,
    status_code: int,
) -> ToonflowControlError:
    candidate = payload.get("failure")
    if not isinstance(candidate, dict):
        candidate = payload.get("error")
    details = candidate if isinstance(candidate, dict) else {}
    failure_class = details.get("class") or details.get("code")
    return ToonflowControlError(
        str(details.get("message") or "Toonflow control request failed."),
        failure_class=(
            str(failure_class) if failure_class else "provider_unavailable"
        ),
        retryable=details.get("retryable") is True,
        user_action=(
            str(details.get("user_action"))
            if isinstance(details.get("user_action"), str)
            else ""
        ),
        status_code=status_code,
    )
