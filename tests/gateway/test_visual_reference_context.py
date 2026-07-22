import json


def test_visual_generation_loads_previous_history_even_with_current_attachments():
    from gateway.run import _should_load_previous_visual_history

    assert _should_load_previous_visual_history(
        "基於這個動作，再產四張讓我挑選",
        current_attachment_paths=["/tmp/current-reference.jpg"],
    )


def test_visual_artifact_start_index_continues_across_session_rollover():
    from gateway.run import _visual_artifact_start_index_for_turn

    prior_history = [
        {
            "role": "tool",
            "content": json.dumps(
                {
                    "success": True,
                    "session_visual_artifacts": [
                        {"label": "G7", "user_ref_index": 7, "uri": "/tmp/g7.jpg"}
                    ],
                }
            ),
        }
    ]

    assert _visual_artifact_start_index_for_turn([], prior_history) == 8


def test_visual_reference_context_falls_back_across_session_rollover():
    from gateway.run import _visual_reference_context_for_turn

    prior_history = [
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

    references = _visual_reference_context_for_turn(
        "以 G1 和 G4 為主要參考，幫我換個背景，然後把鞋脫了",
        current_attachment_paths=[],
        agent_history=[],
        fallback_agent_history=prior_history,
    )

    assert [entry["uri"] for entry in references] == [
        "/tmp/visual-arsenal/assets/g1.jpg",
        "/tmp/visual-arsenal/assets/g4.jpg",
    ]
    assert [entry["source"] for entry in references] == [
        "previous_visual_arsenal_output",
        "previous_visual_arsenal_output",
    ]


def test_named_visual_references_search_full_history_in_prompt_order_with_roles():
    from gateway.run import _visual_reference_context_for_turn

    history = []
    for start in range(1, 21, 4):
        history.append(
            {
                "role": "tool",
                "content": json.dumps(
                    {
                        "success": True,
                        "session_visual_artifacts": [
                            {
                                "label": f"G{index}",
                                "user_ref_index": index,
                                "uri": f"/tmp/g{index}.jpg",
                            }
                            for index in range(start, start + 4)
                        ],
                    }
                ),
            }
        )

    references = _visual_reference_context_for_turn(
        "以 G2 鎖定人物身分，G15 取動作與構圖，產出一張新圖",
        current_attachment_paths=[],
        agent_history=history,
    )

    assert [entry["uri"] for entry in references] == [
        "/tmp/g2.jpg",
        "/tmp/g15.jpg",
    ]
    assert [entry["role_hint"] for entry in references] == [
        "character_identity",
        "pose_composition",
    ]


def test_named_g_references_survive_positional_reattachment_across_session_rollover():
    from gateway.run import _visual_reference_context_for_turn

    prior_history = [
        {
            "role": "tool",
            "content": json.dumps(
                {
                    "success": True,
                    "session_visual_artifacts": [
                        {"label": "G1", "user_ref_index": 1, "uri": "/tmp/g1.jpg"}
                    ],
                }
            ),
        }
    ]
    current_history = [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "name": "visual_package_generate",
                        "arguments": json.dumps(
                            {
                                "attachments": [
                                    "/tmp/original-ref1.jpg",
                                    "/tmp/original-ref2.jpg",
                                ],
                                "reference_binding": {
                                    "reference_order": [
                                        {"index": 1, "role_hint": "character_identity"},
                                        {"index": 2, "role_hint": "pose_composition"},
                                    ]
                                },
                            }
                        ),
                    }
                }
            ],
        },
        {
            "role": "tool",
            "content": json.dumps(
                {
                    "success": True,
                    "session_visual_artifacts": [
                        {"label": "G2", "user_ref_index": 2, "uri": "/tmp/g2.jpg"}
                    ],
                }
            ),
        },
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "name": "visual_package_generate",
                        "arguments": json.dumps(
                            {
                                "attachments": [
                                    "/tmp/g3.jpg",
                                    "/tmp/g4.jpg",
                                    "/tmp/g1.jpg",
                                ],
                                "reference_binding": {
                                    "reference_order": [
                                        {"index": 1, "role_hint": "visual_reference"},
                                        {"index": 2, "role_hint": "visual_reference"},
                                        {"index": 3, "role_hint": "visual_reference"},
                                    ]
                                },
                            }
                        ),
                    }
                }
            ],
        },
    ]

    references = _visual_reference_context_for_turn(
        "G1 的人物，套用 G2 的姿勢",
        current_attachment_paths=[],
        agent_history=current_history,
        fallback_agent_history=prior_history,
    )

    assert [entry["uri"] for entry in references] == [
        "/tmp/g1.jpg",
        "/tmp/g2.jpg",
    ]
    assert [entry["role_hint"] for entry in references] == [
        "character_identity",
        "pose_composition",
    ]


def test_named_ref_followup_recovers_original_uploads_after_generated_candidates():
    from gateway.run import _visual_reference_context_for_turn

    history = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "用 ref1 的人物套用 ref2 的動作"},
                {"type": "image_url", "image_url": {"url": "/tmp/ref1.jpg"}},
                {"type": "image_url", "image_url": {"url": "/tmp/ref2.jpg"}},
            ],
        },
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "name": "visual_package_generate",
                        "arguments": json.dumps(
                            {
                                "attachments": ["/tmp/ref1.jpg", "/tmp/ref2.jpg"],
                                "reference_binding": {
                                    "reference_order": [
                                        {"index": 1, "role_hint": "character_identity"},
                                        {"index": 2, "role_hint": "pose_composition"},
                                    ]
                                },
                            }
                        ),
                    }
                }
            ],
        },
        {
            "role": "tool",
            "content": json.dumps(
                {
                    "success": True,
                    "images": ["/tmp/cache/images/xai_candidate_g1.jpg"],
                }
            ),
        },
    ]

    references = _visual_reference_context_for_turn(
        "完全保持 ref1 的人物特徵，只套用 ref2 的動作，重新產出",
        current_attachment_paths=[],
        agent_history=history,
    )

    assert [entry["uri"] for entry in references] == [
        "/tmp/ref1.jpg",
        "/tmp/ref2.jpg",
    ]
    assert [entry["role_hint"] for entry in references] == [
        "character_identity",
        "pose_composition",
    ]


def test_current_attachment_wins_over_rollover_fallback():
    from gateway.run import _visual_reference_context_for_turn

    prior_history = [
        {
            "role": "tool",
            "content": json.dumps(
                {
                    "success": True,
                    "images": ["/tmp/old-selected.jpg"],
                }
            ),
        }
    ]

    references = _visual_reference_context_for_turn(
        "參考這張，幫我換個背景",
        current_attachment_paths=["/tmp/current-upload.jpg"],
        agent_history=[],
        fallback_agent_history=prior_history,
    )

    assert [entry["uri"] for entry in references] == ["/tmp/current-upload.jpg"]


def test_current_attachment_precedes_but_does_not_hide_named_rollover_reference():
    from gateway.run import _visual_reference_context_for_turn

    prior_history = [
        {
            "role": "tool",
            "content": json.dumps(
                {
                    "success": True,
                    "session_visual_artifacts": [
                        {"label": "G2", "user_ref_index": 2, "uri": "/tmp/g2.jpg"}
                    ],
                }
            ),
        }
    ]

    references = _visual_reference_context_for_turn(
        "把目前附件和 G2 一起作為參考",
        current_attachment_paths=["/tmp/current-upload.jpg"],
        agent_history=[],
        fallback_agent_history=prior_history,
    )

    assert [entry["uri"] for entry in references] == [
        "/tmp/current-upload.jpg",
        "/tmp/g2.jpg",
    ]


def test_runtime_metadata_does_not_pollute_named_reference_selection():
    from gateway.run import _visual_reference_context_for_turn

    prior_history = [
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
    message = '''[Thread context — prior messages in this thread (not yet in conversation history):]
[thread parent] simon: 用 xAI 產四張圖片
[End of thread context]

以 G1 和 G4 為主要參考，幫我換個背景，然後把鞋脫了

Raphael State Observer (ephemeral, internal):
task_state: casual_or_direct

Visual Arsenal default for Slack image work:
- Example feedback may mention G2 and G3 and story-video workflow.
'''

    references = _visual_reference_context_for_turn(
        message,
        current_attachment_paths=[],
        agent_history=[],
        fallback_agent_history=prior_history,
    )

    assert [entry["uri"] for entry in references] == [
        "/tmp/visual-arsenal/assets/g1.jpg",
        "/tmp/visual-arsenal/assets/g4.jpg",
    ]
