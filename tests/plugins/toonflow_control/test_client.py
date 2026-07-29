from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from plugins.toonflow_control.client import (
    ToonflowControlClient,
    ToonflowControlError,
)


@contextmanager
def _server(*, status: int = 200, payload: object = None):
    state: dict[str, object] = {}
    response = {"ok": True} if payload is None else payload

    class Handler(BaseHTTPRequestHandler):
        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            state["method"] = self.command
            state["path"] = self.path
            state["headers"] = dict(self.headers)
            state["body"] = self.rfile.read(length) if length else b""
            encoded = json.dumps(response).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        do_GET = _handle
        do_POST = _handle
        do_DELETE = _handle

        def log_message(self, _format: str, *_args: object) -> None:
            return

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = httpd.server_address
        yield f"http://{host}:{port}", state
    finally:
        httpd.shutdown()
        thread.join()
        httpd.server_close()


def test_client_defaults_to_loopback_control_v1(monkeypatch):
    monkeypatch.delenv("TOONFLOW_CONTROL_URL", raising=False)
    client = ToonflowControlClient(token="fixture")
    assert client.base_url == "http://127.0.0.1:10588"


@pytest.mark.parametrize(
    "url",
    [
        "https://toonflow.example",
        "http://user:pass@127.0.0.1:10588",
        "http://127.0.0.1:10588?token=secret",
        "http://127.0.0.1:10588/#fragment",
        "ftp://127.0.0.1:10588",
        "http://127.0.0.1:10588/other",
    ],
)
def test_client_rejects_unsafe_base_url(url):
    with pytest.raises(ValueError):
        ToonflowControlClient(base_url=url, token="fixture")


def test_token_is_required_before_request(monkeypatch):
    monkeypatch.delenv("TOONFLOW_CONTROL_TOKEN", raising=False)
    client = ToonflowControlClient()
    with pytest.raises(ToonflowControlError, match="not configured"):
        client.capabilities()


def test_get_run_uses_only_control_contract_and_quotes_identifier():
    with _server() as (url, state):
        client = ToonflowControlClient(
            base_url=url,
            token="control-token",
            allow_remote_for_tests=True,
        )
        client.get_run("run id/1")

    assert state["path"] == "/control/v1/runs/run%20id%2F1"
    headers = state["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer control-token"
    assert headers["Accept"] == "application/json"
    assert headers["X-Contract-Version"] == "1.0"


def test_endpoint_methods_and_object_bodies():
    cases = [
        ("capabilities", (), "GET", "/control/v1/capabilities", None),
        ("create_project", ({"name": "Demo"},), "POST", "/control/v1/projects", {"name": "Demo"}),
        ("create_run", ({"project_id": "p1"},), "POST", "/control/v1/runs", {"project_id": "p1"}),
        ("cancel_run", ("r1",), "POST", "/control/v1/runs/r1/cancel", None),
        (
            "select_artifact",
            ("r1", {"artifact_id": "a1"}),
            "POST",
            "/control/v1/runs/r1/selection",
            {"artifact_id": "a1"},
        ),
    ]
    for method_name, args, expected_method, expected_path, expected_body in cases:
        with _server() as (url, state):
            client = ToonflowControlClient(
                base_url=url,
                token="token",
                allow_remote_for_tests=True,
            )
            getattr(client, method_name)(*args)
        assert state["method"] == expected_method
        assert state["path"] == expected_path
        body = state["body"]
        assert isinstance(body, bytes)
        assert (json.loads(body) if body else None) == expected_body


def test_non_object_response_is_normalized_without_raw_body():
    with _server(payload=["not", "an", "object"]) as (url, _state):
        client = ToonflowControlClient(
            base_url=url,
            token="secret-token",
            allow_remote_for_tests=True,
        )
        with pytest.raises(ToonflowControlError) as caught:
            client.capabilities()
    assert caught.value.failure_class == "invalid_response"
    assert "secret-token" not in str(caught.value)
    assert "not" not in str(caught.value)


def test_control_error_fields_are_normalized():
    payload = {
        "failure": {
            "class": "capability_unavailable",
            "retryable": False,
            "user_action": "Choose an advertised route profile.",
            "message": "Route is unavailable.",
        }
    }
    with _server(status=409, payload=payload) as (url, _state):
        client = ToonflowControlClient(
            base_url=url,
            token="secret-token",
            allow_remote_for_tests=True,
        )
        with pytest.raises(ToonflowControlError) as caught:
            client.create_run({"route_profile": "missing"})
    error = caught.value
    assert error.status_code == 409
    assert error.failure_class == "capability_unavailable"
    assert error.retryable is False
    assert error.user_action == "Choose an advertised route profile."
    assert str(error) == "Route is unavailable."
    assert "secret-token" not in repr(error)


def test_network_error_is_normalized():
    client = ToonflowControlClient(
        base_url="http://127.0.0.1:1",
        token="secret-token",
        timeout=0.01,
    )
    with pytest.raises(ToonflowControlError) as caught:
        client.capabilities()
    assert caught.value.failure_class == "provider_unavailable"
    assert caught.value.retryable is True
    assert "secret-token" not in str(caught.value)
