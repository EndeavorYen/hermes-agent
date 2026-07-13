STORY_VIDEO_CONTROL_SCHEMA = {
    "name": "story_video_control",
    "description": (
        "Read or validate the active story-video workflow. Use status before "
        "continuing work and validate after completing the current phase."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "validate", "repair"],
                "description": "Control action for the active story-video project.",
            },
            "repair_request": {
                "type": "string",
                "description": "Issue being repaired when action=repair.",
            },
        },
        "required": ["action"],
    },
}


STORY_VIDEO_QUALITY_CONTROL_SCHEMA = {
    "name": "story_video_quality_control",
    "description": (
        "Compile shot-specific source-art prompts, judge OpenAI image candidates "
        "with the OpenAI vision quality gate, prepare deterministic renderer input, "
        "return the one deterministic next batch operation, or inspect shot selection "
        "status for the active story-video project."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "compile_prompt",
                    "judge_candidates",
                    "next_batch_work",
                    "prepare_render",
                    "status",
                ],
            },
            "shot_id": {
                "type": "string",
                "description": "Shot id from scene_ledger.json.",
            },
            "repair_round": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5,
                "description": "Current bounded quality repair round.",
            },
            "candidates": {
                "type": "array",
                "minItems": 1,
                "maxItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "candidate_id": {"type": "string"},
                        "path": {"type": "string"},
                        "provider": {"type": "string"},
                        "model": {"type": "string"},
                        "response_id": {"type": "string"},
                        "strategy_reset": {
                            "type": "boolean",
                            "description": (
                                "True only for the single layout reset returned by "
                                "compile_prompt after normal repairs are exhausted."
                            ),
                        },
                    },
                    "required": ["candidate_id", "path", "provider"],
                },
            },
        },
        "required": ["action"],
    },
}
