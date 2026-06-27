import json


def test_collect_recent_visual_references_prefers_selected_image_then_original_refs():
    from agent.visual.session_references import collect_recent_visual_reference_paths

    messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_visual",
                    "function": {
                        "name": "visual_package_generate",
                        "arguments": json.dumps(
                            {
                                "prompt": "固定這位角色產出圖片",
                                "attachments": ["/tmp/original-ref.png"],
                            }
                        ),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_visual",
            "content": json.dumps(
                {
                    "success": True,
                    "images": ["/tmp/selected-image.png"],
                    "delivery_metadata": {
                        "selected_visual_artifact_ids": ["img-selected"],
                        "visual_artifacts": {
                            "/tmp/rejected.png": {
                                "artifact_id": "img-rejected",
                                "kind": "image",
                            },
                            "/tmp/selected-image.png": {
                                "artifact_id": "img-selected",
                                "kind": "image",
                            },
                        },
                    },
                }
            ),
        },
    ]

    assert collect_recent_visual_reference_paths(messages) == [
        "/tmp/selected-image.png",
        "/tmp/original-ref.png",
    ]


def test_collect_recent_visual_references_reads_user_image_context_note():
    from agent.visual.session_references import collect_recent_visual_reference_paths

    messages = [
        {
            "role": "user",
            "content": (
                "[The user sent an image~ Here's what I can see:\n"
                "character reference]\n"
                "[If you need a closer look, use vision_analyze with "
                "image_url: /tmp/user-reference.jpg ~]\n\n"
                "請固定這位角色"
            ),
        }
    ]

    assert collect_recent_visual_reference_paths(messages) == [
        "/tmp/user-reference.jpg",
    ]
