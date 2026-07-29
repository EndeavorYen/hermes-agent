"""JSON schemas for the Hermes-facing Toonflow supervisory tools."""

from __future__ import annotations

IMAGE_ROUTE_PROFILES = ["image.standard", "image.allowed_high_scale"]
VIDEO_ROUTE_PROFILES = ["video.subscription"]
ROUTE_PROFILES = [*IMAGE_ROUTE_PROFILES, *VIDEO_ROUTE_PROFILES]
OPERATIONS = ["generate_shots", "produce_story_film"]


def _schema(
    name: str,
    description: str,
    properties: dict,
    required: list[str] | None = None,
) -> dict:
    parameters = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        parameters["required"] = required
    return {
        "name": name,
        "description": description,
        "parameters": parameters,
    }


TOONFLOW_CAPABILITIES_SCHEMA = _schema(
    "toonflow_capabilities",
    "Read the logical workflow operations and route profiles advertised by Toonflow.",
    {},
)

TOONFLOW_CREATE_PROJECT_SCHEMA = _schema(
    "toonflow_create_project",
    "Create a Toonflow project with optional logical image and video routes.",
    {
        "name": {"type": "string", "minLength": 1, "maxLength": 200},
        "intro": {"type": "string", "maxLength": 10000},
        "aspect_ratio": {
            "type": "string",
            "pattern": r"^\d+:\d+$",
        },
        "image_route_profile": {
            "type": "string",
            "enum": IMAGE_ROUTE_PROFILES,
        },
        "video_route_profile": {
            "type": "string",
            "enum": VIDEO_ROUTE_PROFILES,
        },
    },
    ["name"],
)

TOONFLOW_RUN_SCHEMA = _schema(
    "toonflow_run",
    (
        "Start an idempotent Toonflow-owned run. Use generate_shots with "
        "one or more shot_ids, or produce_story_film with "
        "video.subscription, an empty shot_ids list, and one 30-second "
        "16:9 creative_brief."
    ),
    {
        "project_id": {"type": "integer", "minimum": 1},
        "operation": {"type": "string", "enum": OPERATIONS},
        "route_profile": {"type": "string", "enum": ROUTE_PROFILES},
        "shot_ids": {
            "type": "array",
            "items": {"type": "integer", "minimum": 1},
            "minItems": 0,
            "uniqueItems": True,
        },
        "prompt": {"type": "string", "maxLength": 20000},
        "creative_brief": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 200,
                },
                "story": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 20000,
                },
                "cast": {"type": "string", "maxLength": 10000},
                "visual_style": {
                    "type": "string",
                    "maxLength": 5000,
                },
                "continuity_rules": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 1000,
                    },
                    "maxItems": 20,
                },
                "target_duration_seconds": {
                    "type": "integer",
                    "const": 30,
                },
                "aspect_ratio": {
                    "type": "string",
                    "const": "16:9",
                },
            },
            "required": [
                "title",
                "story",
                "target_duration_seconds",
                "aspect_ratio",
            ],
            "additionalProperties": False,
        },
        "idempotency_key": {
            "type": "string",
            "minLength": 1,
            "maxLength": 200,
        },
    },
    [
        "project_id",
        "operation",
        "route_profile",
        "shot_ids",
        "idempotency_key",
    ],
)

TOONFLOW_RUN_STATUS_SCHEMA = _schema(
    "toonflow_run_status",
    "Read the current state and selected public artifacts for a Toonflow run.",
    {"run_id": {"type": "string", "minLength": 1, "maxLength": 500}},
    ["run_id"],
)

TOONFLOW_CANCEL_RUN_SCHEMA = _schema(
    "toonflow_cancel_run",
    "Request cancellation of a Toonflow run.",
    {"run_id": {"type": "string", "minLength": 1, "maxLength": 500}},
    ["run_id"],
)

TOONFLOW_SELECT_ARTIFACT_SCHEMA = _schema(
    "toonflow_select_artifact",
    "Select a verified Toonflow artifact for an image or video owner.",
    {
        "run_id": {"type": "string", "minLength": 1, "maxLength": 500},
        "owner_type": {"type": "string", "enum": ["image", "video"]},
        "owner_id": {"type": "integer", "minimum": 1},
        "artifact_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 500,
        },
        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "shot_id": {"type": "integer", "minimum": 1},
        "video_track_id": {"type": "integer", "minimum": 1},
    },
    ["run_id", "owner_type", "owner_id", "artifact_id", "sha256"],
)

TOOL_SCHEMAS = (
    TOONFLOW_CAPABILITIES_SCHEMA,
    TOONFLOW_CREATE_PROJECT_SCHEMA,
    TOONFLOW_RUN_SCHEMA,
    TOONFLOW_RUN_STATUS_SCHEMA,
    TOONFLOW_CANCEL_RUN_SCHEMA,
    TOONFLOW_SELECT_ARTIFACT_SCHEMA,
)
