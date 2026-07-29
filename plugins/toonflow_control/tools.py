"""Pure supervisory handlers for Toonflow Control Contract 1.0."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .client import ToonflowControlClient, ToonflowControlError

_CAPABILITY_FIELDS = ("contract_version", "operations", "route_profiles")
_PROJECT_FIELDS = ("contract_version", "project_id")
_RUN_FIELDS = (
    "contract_version",
    "run_id",
    "project_id",
    "operation",
    "route_profile",
    "shot_ids",
    "state",
    "artifacts",
    "failure",
    "created_at",
    "updated_at",
)
_ARTIFACT_FIELDS = (
    "owner_type",
    "owner_id",
    "artifact_id",
    "sha256",
    "mime_type",
    "composition_kind",
    "state",
)
_SELECTION_FIELDS = ("contract_version", "run_id", "artifact_id", "selected")


def toonflow_capabilities(
    _args: dict[str, Any],
    *,
    client: ToonflowControlClient | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    return _execute(
        lambda active: _public_object(
            active.capabilities(),
            _CAPABILITY_FIELDS,
        ),
        client,
    )


def toonflow_create_project(
    args: dict[str, Any],
    *,
    client: ToonflowControlClient | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    def operation(active: ToonflowControlClient) -> dict[str, Any]:
        requested_routes = [
            value
            for value in (
                args.get("image_route_profile"),
                args.get("video_route_profile"),
            )
            if isinstance(value, str)
        ]
        if requested_routes:
            capabilities = _capabilities(active)
            for route in requested_routes:
                _require_advertised(
                    route,
                    capabilities["route_profiles"],
                    "route profile",
                )
        payload = _pick(
            args,
            (
                "name",
                "intro",
                "aspect_ratio",
                "image_route_profile",
                "video_route_profile",
            ),
        )
        return _public_object(active.create_project(payload), _PROJECT_FIELDS)

    return _execute(operation, client)


def toonflow_run(
    args: dict[str, Any],
    *,
    client: ToonflowControlClient | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    def operation(active: ToonflowControlClient) -> dict[str, Any]:
        capabilities = _capabilities(active)
        _require_advertised(
            args.get("operation"),
            capabilities["operations"],
            "operation",
        )
        _require_advertised(
            args.get("route_profile"),
            capabilities["route_profiles"],
            "route profile",
        )
        payload = _pick(
            args,
            (
                "project_id",
                "operation",
                "route_profile",
                "shot_ids",
                "prompt",
                "idempotency_key",
            ),
        )
        return _public_run(active.create_run(payload))

    return _execute(operation, client)


def toonflow_run_status(
    args: dict[str, Any],
    *,
    client: ToonflowControlClient | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    return _execute(
        lambda active: _public_run(active.get_run(_required_text(args, "run_id"))),
        client,
    )


def toonflow_cancel_run(
    args: dict[str, Any],
    *,
    client: ToonflowControlClient | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    def operation(active: ToonflowControlClient) -> dict[str, Any]:
        _capabilities(active)
        return _public_run(active.cancel_run(_required_text(args, "run_id")))

    return _execute(operation, client)


def toonflow_select_artifact(
    args: dict[str, Any],
    *,
    client: ToonflowControlClient | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    def operation(active: ToonflowControlClient) -> dict[str, Any]:
        _capabilities(active)
        run_id = _required_text(args, "run_id")
        payload = _pick(
            args,
            (
                "owner_type",
                "owner_id",
                "artifact_id",
                "sha256",
                "shot_id",
                "video_track_id",
            ),
        )
        return _public_object(
            active.select_artifact(run_id, payload),
            _SELECTION_FIELDS,
        )

    return _execute(operation, client)


def _execute(
    operation: Callable[[ToonflowControlClient], dict[str, Any]],
    client: ToonflowControlClient | None,
) -> dict[str, Any]:
    try:
        return {
            "success": True,
            "toonflow": operation(client or ToonflowControlClient()),
        }
    except ToonflowControlError as exc:
        return {
            "success": False,
            "failure": {
                "class": exc.failure_class,
                "retryable": exc.retryable,
                "user_action": exc.user_action,
                "message": str(exc),
            },
        }
    except (KeyError, TypeError, ValueError):
        return {
            "success": False,
            "failure": {
                "class": "invalid_request",
                "retryable": False,
                "user_action": "Correct the Toonflow tool arguments.",
                "message": "The Toonflow tool request is invalid.",
            },
        }


def _capabilities(client: ToonflowControlClient) -> dict[str, Any]:
    value = client.capabilities()
    if value.get("contract_version") != "1.0":
        raise ToonflowControlError(
            "Toonflow Control Contract 1.0 is required.",
            failure_class="contract_mismatch",
            user_action="Run a compatible Toonflow Control API.",
        )
    operations = value.get("operations")
    route_profiles = value.get("route_profiles")
    if not isinstance(operations, list) or not isinstance(route_profiles, list):
        raise ToonflowControlError(
            "Toonflow returned invalid capabilities.",
            failure_class="invalid_response",
        )
    return {
        "operations": operations,
        "route_profiles": route_profiles,
    }


def _require_advertised(
    value: object,
    advertised: list[Any],
    label: str,
) -> None:
    if not isinstance(value, str) or value not in advertised:
        raise ToonflowControlError(
            f"The requested Toonflow {label} is not advertised.",
            failure_class="capability_unavailable",
            user_action=f"Choose an advertised Toonflow {label}.",
        )


def _required_text(args: dict[str, Any], key: str) -> str:
    value = args[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _pick(args: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: args[key] for key in keys if key in args}


def _public_object(
    value: dict[str, Any],
    fields: tuple[str, ...],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ToonflowControlError(
            "Toonflow returned an invalid response object.",
            failure_class="invalid_response",
        )
    return {key: value[key] for key in fields if key in value}


def _public_run(value: dict[str, Any]) -> dict[str, Any]:
    public = _public_object(value, _RUN_FIELDS)
    artifacts = public.get("artifacts")
    if isinstance(artifacts, list):
        public["artifacts"] = [
            _public_object(item, _ARTIFACT_FIELDS)
            for item in artifacts
            if isinstance(item, dict)
        ]
    failure = public.get("failure")
    if isinstance(failure, dict):
        public["failure"] = _public_object(failure, ("code", "message"))
    return public
