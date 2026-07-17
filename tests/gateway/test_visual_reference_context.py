import json


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
