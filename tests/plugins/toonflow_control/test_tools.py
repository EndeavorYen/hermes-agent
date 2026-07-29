from __future__ import annotations

import json
from typing import Any

import pytest

from plugins.toonflow_control import schemas, tools
from plugins.toonflow_control.client import ToonflowControlError


class RecordingClient:
    def __init__(
        self,
        *,
        capabilities: dict[str, Any] | None = None,
        run: dict[str, Any] | None = None,
        failure: ToonflowControlError | None = None,
    ) -> None:
        self.capability_value = capabilities or {
            "contract_version": "1.0",
            "operations": ["generate_shots", "produce_story_film"],
            "route_profiles": [
                "image.standard",
                "image.allowed_high_scale",
                "video.subscription",
            ],
        }
        self.run_value = run or {
            "contract_version": "1.0",
            "run_id": "run-1",
            "project_id": 1,
            "operation": "generate_shots",
            "route_profile": "image.standard",
            "shot_ids": [1],
            "state": "processing",
            "artifacts": [],
            "created_at": 1,
            "updated_at": 2,
        }
        self.failure = failure
        self.capability_calls = 0
        self.create_project_calls: list[dict[str, Any]] = []
        self.create_run_calls: list[dict[str, Any]] = []
        self.get_run_calls: list[str] = []
        self.cancel_run_calls: list[str] = []
        self.select_calls: list[tuple[str, dict[str, Any]]] = []

    def _raise(self) -> None:
        if self.failure:
            raise self.failure

    def capabilities(self) -> dict[str, Any]:
        self._raise()
        self.capability_calls += 1
        return self.capability_value

    def create_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._raise()
        self.create_project_calls.append(payload)
        return {"contract_version": "1.0", "project_id": 12}

    def create_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._raise()
        self.create_run_calls.append(payload)
        return self.run_value

    def get_run(self, run_id: str) -> dict[str, Any]:
        self._raise()
        self.get_run_calls.append(run_id)
        return self.run_value

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        self._raise()
        self.cancel_run_calls.append(run_id)
        return {**self.run_value, "state": "cancelled"}

    def select_artifact(
        self,
        run_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self._raise()
        self.select_calls.append((run_id, payload))
        return {
            "contract_version": "1.0",
            "run_id": run_id,
            "artifact_id": payload["artifact_id"],
            "selected": True,
        }


def _schema_names() -> set[str]:
    return {schema["name"] for schema in schemas.TOOL_SCHEMAS}


def test_schemas_are_exact_and_expose_no_provider_controls():
    assert _schema_names() == {
        "toonflow_capabilities",
        "toonflow_create_project",
        "toonflow_run",
        "toonflow_run_status",
        "toonflow_cancel_run",
        "toonflow_select_artifact",
    }
    encoded = json.dumps(schemas.TOOL_SCHEMAS).lower()
    for forbidden in (
        "provider",
        "model",
        "api_key",
        "oauth",
        "browser",
        "bridge",
    ):
        assert forbidden not in encoded
    for schema in schemas.TOOL_SCHEMAS:
        assert schema["parameters"]["additionalProperties"] is False


def test_run_rejects_unadvertised_route_without_creating_run():
    client = RecordingClient(
        capabilities={
            "contract_version": "1.0",
            "operations": ["generate_shots"],
            "route_profiles": ["image.standard"],
        }
    )
    result = tools.toonflow_run(
        {
            "project_id": 1,
            "operation": "generate_shots",
            "route_profile": "image.allowed_high_scale",
            "shot_ids": [1],
            "idempotency_key": "request-1",
        },
        client=client,
    )
    assert result["success"] is False
    assert result["failure"]["class"] == "capability_unavailable"
    assert client.create_run_calls == []


def test_run_rejects_unadvertised_operation_without_creating_run():
    client = RecordingClient(
        capabilities={
            "contract_version": "1.0",
            "operations": [],
            "route_profiles": ["image.standard"],
        }
    )
    result = tools.toonflow_run(
        {
            "project_id": 1,
            "operation": "generate_shots",
            "route_profile": "image.standard",
            "shot_ids": [1],
            "idempotency_key": "request-1",
        },
        client=client,
    )
    assert result["failure"]["class"] == "capability_unavailable"
    assert client.create_run_calls == []


def test_project_route_options_are_capability_checked():
    client = RecordingClient(
        capabilities={
            "contract_version": "1.0",
            "operations": ["generate_shots"],
            "route_profiles": ["image.standard"],
        }
    )
    result = tools.toonflow_create_project(
        {
            "name": "Demo",
            "image_route_profile": "image.allowed_high_scale",
        },
        client=client,
    )
    assert result["failure"]["class"] == "capability_unavailable"
    assert client.create_project_calls == []


def test_successful_run_passes_only_control_contract_fields():
    client = RecordingClient()
    result = tools.toonflow_run(
        {
            "project_id": 1,
            "operation": "generate_shots",
            "route_profile": "video.subscription",
            "shot_ids": [2],
            "prompt": "Animate the selected frame.",
            "idempotency_key": "request-1",
        },
        client=client,
    )
    assert result["success"] is True
    assert client.capability_calls == 1
    assert client.create_run_calls == [
        {
            "project_id": 1,
            "operation": "generate_shots",
            "route_profile": "video.subscription",
            "shot_ids": [2],
            "prompt": "Animate the selected frame.",
            "idempotency_key": "request-1",
        }
    ]


def test_story_film_run_passes_creative_brief_to_toonflow_unchanged():
    client = RecordingClient(
        run={
            "contract_version": "1.0",
            "run_id": "run-story-1",
            "project_id": 1,
            "operation": "produce_story_film",
            "route_profile": "video.subscription",
            "shot_ids": [],
            "state": "queued",
            "artifacts": [],
            "created_at": 1,
            "updated_at": 1,
        }
    )
    creative_brief = {
        "title": "末班光影",
        "story": "一名疲憊乘客在末班地鐵遇見改變人生的陌生人。",
        "cast": "一名三十多歲上班族與一名神秘旅客",
        "visual_style": "cinematic realism",
        "continuity_rules": ["角色服裝與髮型跨鏡頭一致"],
        "target_duration_seconds": 30,
        "aspect_ratio": "16:9",
    }

    result = tools.toonflow_run(
        {
            "project_id": 1,
            "operation": "produce_story_film",
            "route_profile": "video.subscription",
            "shot_ids": [],
            "creative_brief": creative_brief,
            "idempotency_key": "story-film-1",
        },
        client=client,
    )

    assert result["success"] is True
    assert client.create_run_calls == [
        {
            "project_id": 1,
            "operation": "produce_story_film",
            "route_profile": "video.subscription",
            "shot_ids": [],
            "creative_brief": creative_brief,
            "idempotency_key": "story-film-1",
        }
    ]


def test_run_schema_advertises_toonflow_owned_story_film_contract():
    parameters = schemas.TOONFLOW_RUN_SCHEMA["parameters"]

    assert "produce_story_film" in parameters["properties"]["operation"]["enum"]
    assert parameters["properties"]["shot_ids"]["minItems"] == 0
    brief = parameters["properties"]["creative_brief"]
    assert brief["additionalProperties"] is False
    assert set(brief["required"]) == {
        "title",
        "story",
        "target_duration_seconds",
        "aspect_ratio",
    }
    assert brief["properties"]["target_duration_seconds"]["const"] == 30
    assert brief["properties"]["aspect_ratio"]["const"] == "16:9"


def test_status_returns_toonflow_run_without_bridge_fields():
    client = RecordingClient(
        run={
            "run_id": "run-1",
            "state": "processing",
            "bridge_job_id": "must-not-escape",
        }
    )
    result = tools.toonflow_run_status(
        {"run_id": "run-1"},
        client=client,
    )
    assert result["success"] is True
    assert "bridge_job_id" not in json.dumps(result)


@pytest.mark.parametrize(
    ("handler", "payload", "recording_attr"),
    [
        (tools.toonflow_cancel_run, {"run_id": "run-1"}, "cancel_run_calls"),
        (
            tools.toonflow_select_artifact,
            {
                "run_id": "run-1",
                "owner_type": "image",
                "owner_id": 10,
                "artifact_id": "artifact-1",
                "sha256": "a" * 64,
                "shot_id": 2,
            },
            "select_calls",
        ),
    ],
)
def test_optional_mutations_negotiate_capabilities_first(
    handler,
    payload,
    recording_attr,
):
    client = RecordingClient()
    result = handler(payload, client=client)
    assert result["success"] is True
    assert client.capability_calls == 1
    assert getattr(client, recording_attr)


def test_normalized_client_failure_is_returned_without_exception_details():
    client = RecordingClient(
        failure=ToonflowControlError(
            "Toonflow is unavailable.",
            failure_class="provider_unavailable",
            retryable=True,
            user_action="Start Toonflow.",
            status_code=503,
        )
    )
    result = tools.toonflow_capabilities({}, client=client)
    assert result == {
        "success": False,
        "failure": {
            "class": "provider_unavailable",
            "retryable": True,
            "user_action": "Start Toonflow.",
            "message": "Toonflow is unavailable.",
        },
    }
