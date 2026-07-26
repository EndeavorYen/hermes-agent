#!/usr/bin/env python3
"""No-spend contract smoke for the Hermes Toonflow control plugin."""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterator

from plugins.toonflow_control.client import (
    ToonflowControlClient,
    ToonflowControlError,
)

_TERMINAL_STATES = {"succeeded", "failed", "cancelled"}
_FORBIDDEN_RESPONSE_KEYS = (
    "bridge_job",
    "provider",
    "model_id",
    "api_key",
    "billing",
    "credential",
)


def assert_public_response(value: object) -> None:
    """Reject internal orchestration and spend-bearing response fields."""

    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower()
            if any(marker in normalized for marker in _FORBIDDEN_RESPONSE_KEYS):
                raise ToonflowControlError(
                    "The control response crossed the external boundary.",
                    failure_class="boundary_violation",
                )
            assert_public_response(item)
    elif isinstance(value, list):
        for item in value:
            assert_public_response(item)


def run_smoke(
    client: Any,
    *,
    no_spend: bool,
    poll_interval: float = 0.01,
    max_polls: int = 5,
) -> dict[str, Any]:
    capabilities = client.capabilities()
    assert_public_response(capabilities)
    if capabilities.get("contract_version") != "1.0":
        raise ToonflowControlError(
            "Control Contract 1.0 is required.",
            failure_class="contract_mismatch",
        )
    if no_spend and capabilities.get("execution_mode") != "fake":
        raise ToonflowControlError(
            "The server did not prove fake execution for a no-spend smoke.",
            failure_class="no_spend_not_proven",
            user_action="Use --fake-server or an accepted fake-control fixture.",
        )
    if "generate_shots" not in capabilities.get("operations", []):
        raise ToonflowControlError(
            "The fake control operation is unavailable.",
            failure_class="capability_unavailable",
        )
    if "image.standard" not in capabilities.get("route_profiles", []):
        raise ToonflowControlError(
            "The fake control route is unavailable.",
            failure_class="capability_unavailable",
        )

    project = client.create_project(
        {
            "name": "Hermes no-spend control smoke",
            "image_route_profile": "image.standard",
        }
    )
    assert_public_response(project)
    run = client.create_run(
        {
            "idempotency_key": "hermes-no-spend-smoke-1",
            "project_id": project["project_id"],
            "operation": "generate_shots",
            "route_profile": "image.standard",
            "shot_ids": [1],
            "prompt": "Contract fixture only.",
        }
    )
    assert_public_response(run)

    for _ in range(max_polls):
        if run.get("state") in _TERMINAL_STATES:
            break
        time.sleep(poll_interval)
        run = client.get_run(str(run["run_id"]))
        assert_public_response(run)
    if run.get("state") != "succeeded":
        raise ToonflowControlError(
            "The no-spend control run did not succeed.",
            failure_class="smoke_failed",
            retryable=run.get("state") not in _TERMINAL_STATES,
        )
    return {
        "status": "ok",
        "contract_version": capabilities["contract_version"],
        "run_id": run["run_id"],
        "state": run["state"],
    }


@contextmanager
def embedded_fake_control_server() -> Iterator[tuple[str, str, dict[str, Any]]]:
    token = "hermes-no-spend-fixture-token"
    state: dict[str, Any] = {"paths": [], "provider_requests": 0}

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, status: int, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("X-Contract-Version", "1.0")
            self.end_headers()
            self.wfile.write(encoded)

        def _handle(self) -> None:
            state["paths"].append(self.path)
            if self.headers.get("Authorization") != f"Bearer {token}":
                self._reply(
                    401,
                    {
                        "contract_version": "1.0",
                        "error": {
                            "code": "unauthorized",
                            "message": "Unauthorized.",
                            "retryable": False,
                        },
                    },
                )
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length)) if length else {}
            if self.path == "/control/v1/capabilities":
                self._reply(
                    200,
                    {
                        "contract_version": "1.0",
                        "execution_mode": "fake",
                        "operations": ["generate_shots"],
                        "route_profiles": ["image.standard"],
                    },
                )
            elif self.path == "/control/v1/projects":
                assert body["image_route_profile"] == "image.standard"
                self._reply(
                    201,
                    {"contract_version": "1.0", "project_id": 1},
                )
            elif self.path == "/control/v1/runs":
                assert body["idempotency_key"] == "hermes-no-spend-smoke-1"
                self._reply(202, _fake_run("processing"))
            elif self.path == "/control/v1/runs/fake-run-1":
                self._reply(200, _fake_run("succeeded"))
            else:
                self._reply(
                    404,
                    {
                        "contract_version": "1.0",
                        "error": {
                            "code": "not_found",
                            "message": "Not found.",
                            "retryable": False,
                        },
                    },
                )

        do_GET = _handle
        do_POST = _handle

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}", token, state
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def _fake_run(state: str) -> dict[str, Any]:
    return {
        "contract_version": "1.0",
        "run_id": "fake-run-1",
        "project_id": 1,
        "operation": "generate_shots",
        "route_profile": "image.standard",
        "shot_ids": [1],
        "state": state,
        "artifacts": (
            [
                {
                    "owner_type": "image",
                    "owner_id": 1,
                    "artifact_id": "fake-artifact-1",
                    "sha256": "a" * 64,
                    "mime_type": "image/png",
                    "composition_kind": "single",
                    "state": "selected",
                }
            ]
            if state == "succeeded"
            else []
        ),
        "created_at": 1,
        "updated_at": 2,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get(
            "TOONFLOW_CONTROL_URL",
            "http://127.0.0.1:10588",
        ),
    )
    parser.add_argument("--no-spend", action="store_true")
    parser.add_argument(
        "--fake-server",
        action="store_true",
        help="Run against an embedded contract fixture that cannot generate media.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.fake_server:
        with embedded_fake_control_server() as (url, token, state):
            result = run_smoke(
                ToonflowControlClient(base_url=url, token=token),
                no_spend=args.no_spend,
            )
            result["paths"] = state["paths"]
            result["provider_requests"] = state["provider_requests"]
    else:
        result = run_smoke(
            ToonflowControlClient(base_url=args.base_url),
            no_spend=args.no_spend,
        )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
