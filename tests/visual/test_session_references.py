import json


def test_original_reference_request_requires_explicit_original_semantics():
    from agent.visual.session_references import prompt_requests_original_visual_references

    assert prompt_requests_original_visual_references(
        "以 G1 和 G4 為主要參考，幫我換個背景"
    ) is False
    assert prompt_requests_original_visual_references(
        "以原 ref 為主要構圖參考，幫我換個背景"
    ) is True
    assert prompt_requests_original_visual_references(
        "請沿用原始 reference 的角色特徵"
    ) is True
    assert prompt_requests_original_visual_references(
        "用原本的 ref 再產兩張不同姿勢"
    ) is True
    assert prompt_requests_original_visual_references(
        "請沿用原來的 reference"
    ) is True


def test_visual_arsenal_outputs_keep_candidate_indices_for_named_reuse():
    from agent.visual.session_references import (
        collect_recent_visual_reference_entries,
        filter_visual_reference_entries_for_prompt,
    )

    messages = [
        {
            "role": "tool",
            "content": json.dumps(
                {
                    "library_root": "/tmp/visual-arsenal",
                    "absolute_output_image_paths": [
                        "/tmp/visual-arsenal/assets/g1.jpg",
                        "/tmp/visual-arsenal/assets/g2.jpg",
                        "/tmp/visual-arsenal/assets/g3.jpg",
                        "/tmp/visual-arsenal/assets/g4.jpg",
                    ],
                }
            ),
        }
    ]

    entries = collect_recent_visual_reference_entries(messages, limit=4)
    selected = filter_visual_reference_entries_for_prompt(
        entries,
        "以 G1 和 G4 為主要參考，幫我換個背景",
    )

    assert [entry["uri"] for entry in selected] == [
        "/tmp/visual-arsenal/assets/g1.jpg",
        "/tmp/visual-arsenal/assets/g4.jpg",
    ]
    assert [entry["user_ref_index"] for entry in selected] == [1, 4]


def test_visual_arsenal_output_fields_ignore_untrusted_library_root():
    from agent.visual.session_references import collect_recent_visual_reference_entries

    messages = [
        {
            "role": "tool",
            "content": json.dumps(
                {
                    "library_root": "/tmp/not-visual-library",
                    "absolute_output_image_paths": ["/tmp/not-visual-library/private.jpg"],
                }
            ),
        }
    ]

    assert collect_recent_visual_reference_entries(messages) == []


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
