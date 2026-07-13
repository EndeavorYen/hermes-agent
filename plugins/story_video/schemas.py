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
                    "replan_shot_contract",
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
                        "generation_prompt": {"type": "string"},
                        "shot_contract_hash": {
                            "type": "string",
                            "description": (
                                "Exact shot_contract_hash returned by compile_prompt or "
                                "next_batch_work for this generated source image."
                            ),
                        },
                        "strategy_reset": {
                            "type": "boolean",
                            "description": (
                                "True only for the single layout reset returned by "
                                "compile_prompt after normal repairs are exhausted."
                            ),
                        },
                        "repair_strategy": {
                            "type": "string",
                            "enum": [
                                "initial",
                                "targeted_repair",
                                "layout_reset",
                                "evidence_reframe",
                                "contextual_replan",
                                "documentary_context",
                                "story_reframe",
                                "audience_reframe",
                                "truth_reframe",
                                "camera_reveal_policy_review",
                            ],
                            "description": (
                                "Exact adaptive repair strategy returned by compile_prompt."
                            ),
                        },
                    },
                    "required": [
                        "candidate_id",
                        "path",
                        "provider",
                        "shot_contract_hash",
                    ],
                },
            },
            "redesigned_shot": {
                "type": "object",
                "description": (
                    "Replacement visual design for action=replan_shot_contract. "
                    "Narration, takeaway, truth mode, risk, and shot id remain locked."
                ),
                "properties": {
                    "subject": {"type": "string"},
                    "action": {"type": "string"},
                    "evidence_detail": {"type": "string"},
                    "shot_scale": {
                        "type": "string",
                        "enum": [
                            "establishing",
                            "wide",
                            "medium",
                            "close_up",
                            "macro",
                            "insert",
                        ],
                    },
                    "camera_angle": {"type": "string"},
                    "focal_point": {"type": "string"},
                    "subtitle_safe_area": {"type": "string"},
                    "acceptance_criteria": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string"},
                    },
                    "attention_hook": {"type": "string"},
                    "story_moment": {"type": "string"},
                    "action_consequence": {"type": "string"},
                    "composition_energy": {"type": "string"},
                    "viewer_emotion": {"type": "string"},
                    "engagement_criteria": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "calm_reason": {"type": "string"},
                    "evidence_bridge": {"type": "string"},
                },
                "required": [
                    "subject",
                    "action",
                    "evidence_detail",
                    "shot_scale",
                    "camera_angle",
                    "focal_point",
                    "subtitle_safe_area",
                    "acceptance_criteria",
                ],
            },
        },
        "required": ["action"],
    },
}
