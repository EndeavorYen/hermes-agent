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

