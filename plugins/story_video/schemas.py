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
                "enum": [
                    "guide",
                    "status",
                    "validate",
                    "repair",
                    "list_voices",
                    "select_voice",
                    "voice_status",
                ],
                "description": "Control action for the active story-video project.",
            },
            "section": {
                "type": "string",
                "enum": ["help", "status", "examples", "voices"],
                "description": "Read-only operator guide section when action=guide.",
            },
            "repair_request": {
                "type": "string",
                "description": "Issue being repaired when action=repair.",
            },
            "voice_id": {
                "type": "string",
                "description": (
                    "Registered narrator profile identifier when action=select_voice."
                ),
            },
        },
        "required": ["action"],
    },
}


STORY_VIDEO_VOICE_MANAGER_SCHEMA = {
    "name": "story_video_voice_manager",
    "description": (
        "Manage local versioned Qwen Base voice-clone profiles. Tuning creates a "
        "new immutable version; archiving preserves existing project bindings; "
        "deletion fails when a project still references the voice."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "add", "tune", "archive", "delete"],
            },
            "voice_id": {
                "type": "string",
                "description": "Stable operator-facing voice identity.",
            },
            "display_name": {"type": "string"},
            "reference_audio": {
                "type": "string",
                "description": "Absolute path to a clean, authorized local recording.",
            },
            "reference_transcript": {
                "type": "string",
                "description": "Exact transcript of the reference recording.",
            },
            "consent": {
                "type": "string",
                "enum": ["user_confirmed_self_recording"],
            },
            "tuning": {
                "type": "object",
                "properties": {
                    "speed": {"type": "number", "minimum": 0.85, "maximum": 1.2},
                    "pitch_shift_semitones": {
                        "type": "number",
                        "minimum": -3,
                        "maximum": 3,
                    },
                    "expressiveness": {
                        "type": "string",
                        "enum": ["restrained", "natural", "lively", "dramatic"],
                    },
                },
                "additionalProperties": False,
            },
        },
        "required": ["action"],
    },
}


STORY_VIDEO_AUDIO_DIRECTOR_SCHEMA = {
    "name": "story_video_audio_director",
    "description": (
        "Compile and inspect a story-video character dubbing contract. Supports "
        "creative, remake, and exact read-aloud modes and locks each speaker to "
        "one concrete local voice profile before synthesis."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["compile", "bind_cast", "status"],
            },
            "mode": {
                "type": "string",
                "enum": ["creative", "remake", "read_aloud"],
            },
            "source_text": {"type": "string"},
            "speakers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "speaker_id": {"type": "string"},
                        "display_name": {"type": "string"},
                        "role": {
                            "type": "string",
                            "enum": ["narrator", "lead", "supporting", "extra"],
                        },
                        "voice_id": {"type": "string"},
                        "variant": {"type": "object"},
                    },
                    "required": ["speaker_id", "display_name", "role", "voice_id"],
                },
            },
            "utterances": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "utterance_id": {"type": "string"},
                        "scene_id": {"type": "string"},
                        "shot_id": {"type": "string"},
                        "speaker_id": {"type": "string"},
                        "display_text": {"type": "string"},
                        "emotion": {"type": "string"},
                        "pace": {"type": "string"},
                        "source_start": {"type": "integer"},
                        "source_end": {"type": "integer"},
                        "source_refs": {"type": "array", "items": {"type": "object"}},
                    },
                    "required": [
                        "utterance_id",
                        "scene_id",
                        "shot_id",
                        "speaker_id",
                        "display_text",
                    ],
                },
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
        "status for the active story-video project. run_batch_chunk is purpose-limited "
        "to the verified story-video project: it sends only purpose-created story "
        "prompts and generated source art to the configured OpenAI provider, and writes "
        "only project-local production artifacts after authorization_id validation."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "compile_prompt",
                    "judge_candidates",
                    "run_batch_chunk",
                    "run_voice_phase",
                    "next_batch_work",
                    "replan_shot_contract",
                    "compile_release_art",
                    "register_release_art",
                    "prepare_render",
                    "status",
                ],
            },
            "shot_id": {
                "type": "string",
                "description": "Shot id from scene_ledger.json.",
            },
            "provider": {
                "type": "string",
                "enum": ["openai-codex"],
                "description": (
                    "Explicit authorized provider provenance for OpenAI vision QC."
                ),
            },
            "authorization_id": {
                "type": "string",
                "description": (
                    "Verified purpose-limited operator authorization bound to this "
                    "run, project directory, OpenAI image generation, OpenAI vision "
                    "QC, and project-local artifact writes. Required for auto-mode "
                    "run_batch_chunk."
                    " Also required for auto-mode run_voice_phase, which runs only the "
                    "locked offline local Qwen narrator and project-local voice QC."
                ),
            },
            "run_id": {
                "type": "string",
                "description": (
                    "Active story-video run identifier used only to resolve the "
                    "canonical run context when the MCP process does not inherit the "
                    "originating Hermes session."
                ),
            },
            "project_dir": {
                "type": "string",
                "description": (
                    "Absolute active story-video project directory paired with run_id "
                    "for canonical MCP context resolution. It does not broaden the "
                    "authorization beyond project-local artifact writes."
                ),
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
                                "style_reframe",
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
            "release_art_candidate": {
                "type": "object",
                "description": (
                    "Dedicated text-free release hero returned by OpenAI image generation."
                ),
                "properties": {
                    "path": {"type": "string"},
                    "provider": {
                        "type": "string",
                        "enum": ["openai-codex"],
                    },
                    "model": {"type": "string"},
                    "response_id": {"type": "string"},
                },
                "required": ["path", "provider", "response_id"],
            },
            "release_art_candidates": {
                "type": "array",
                "minItems": 2,
                "maxItems": 2,
                "description": (
                    "Distinct text-free opening and ending sources returned by OpenAI "
                    "image generation for release-art v2."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "role": {"type": "string", "enum": ["opening", "ending"]},
                        "path": {"type": "string"},
                        "provider": {
                            "type": "string",
                            "enum": ["openai-codex"],
                        },
                        "model": {"type": "string"},
                        "response_id": {"type": "string"},
                    },
                    "required": ["role", "path", "provider", "response_id"],
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
