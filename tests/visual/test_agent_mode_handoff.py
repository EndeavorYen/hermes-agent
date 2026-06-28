import base64
import json
from pathlib import Path
from types import SimpleNamespace


_ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def test_direct_visual_handoff_accepts_explicit_image_to_video_request():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )
    message = [
        {"type": "text", "text": "把這張圖做成 6 秒影片"},
        {"type": "image_url", "image_url": {"url": "/tmp/source.png"}},
    ]

    handoff = build_direct_visual_agent_handoff(agent, message)

    assert handoff is not None
    assert handoff["arguments"]["prompt"] == "把這張圖做成 6 秒影片"
    assert handoff["arguments"]["attachments"] == ["/tmp/source.png"]
    assert handoff["arguments"]["include_video"] is True
    assert handoff["base_llm_provider_bypassed"] == "openai-codex"
    assert handoff["visual_agent_llm_provider"] == "xai-oauth"


def test_direct_visual_handoff_materializes_data_uri_attachment(tmp_path, monkeypatch):
    from agent.visual.agent_mode import handoff as handoff_module

    monkeypatch.setattr(handoff_module, "get_hermes_home", lambda: tmp_path)
    data_uri = "data:image/png;base64," + base64.b64encode(_ONE_PIXEL_PNG).decode("ascii")
    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )
    message = [
        {"type": "text", "text": "把這張圖做成 6 秒影片"},
        {"type": "image_url", "image_url": {"url": data_uri}},
    ]

    handoff = handoff_module.build_direct_visual_agent_handoff(agent, message)

    assert handoff is not None
    attachment = handoff["arguments"]["attachments"][0]
    assert not attachment.startswith("data:image")
    assert attachment.startswith(str(tmp_path / "cache" / "visual-agent-attachments"))
    assert Path(attachment).read_bytes() == _ONE_PIXEL_PNG


def test_direct_visual_handoff_ignores_image_discussion_without_generation_intent():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )

    handoff = build_direct_visual_agent_handoff(agent, "這張圖片的構圖好看嗎？")

    assert handoff is None


def test_direct_visual_handoff_ignores_prompt_disclosure_even_when_it_mentions_image_generation():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff
    from gateway.session_context import reset_visual_reference_context, set_visual_reference_context

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )
    token = set_visual_reference_context(
        [
            {
                "uri": "/tmp/previous-selected.png",
                "role_hint": "edit_anchor",
                "source": "previous_selected_artifact",
            }
        ]
    )
    try:
        handoff = build_direct_visual_agent_handoff(agent, "請給我剛剛產圖用的 prompt")
    finally:
        reset_visual_reference_context(token)

    assert handoff is None

    handoff = build_direct_visual_agent_handoff(agent, "請給我你使用的 prompt")

    assert handoff is None


def test_direct_visual_handoff_ignores_prompt_rewrite_request_even_when_it_mentions_image_generation():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )

    handoff = build_direct_visual_agent_handoff(agent, "請幫我優化剛剛產圖用的 prompt")

    assert handoff is None


def test_direct_visual_handoff_ignores_visual_failure_status_message():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )
    message = [
        {"type": "text", "text": "視覺生成失敗：候選圖未通過品質檢查，已停止交付。"},
        {"type": "image_url", "image_url": {"url": "/tmp/recent-ref.png"}},
    ]

    handoff = build_direct_visual_agent_handoff(agent, message)

    assert handoff is None


def test_direct_visual_handoff_uses_session_edit_anchor_for_followup_edit():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff
    from gateway.session_context import reset_visual_reference_context, set_visual_reference_context

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )
    token = set_visual_reference_context(
        [
            {
                "uri": "/tmp/previous-selected.png",
                "role_hint": "edit_anchor",
                "source": "previous_selected_artifact",
            },
            {
                "uri": "/tmp/character.png",
                "role_hint": "character_identity",
                "source": "previous_tool_reference",
                "user_ref_index": 1,
            },
            {
                "uri": "/tmp/pose.png",
                "role_hint": "pose_composition",
                "source": "previous_tool_reference",
                "user_ref_index": 2,
            },
        ]
    )
    try:
        handoff = build_direct_visual_agent_handoff(
            agent,
            "很好，但足底應該也包含連身衣，而不是露出裸足，請改進",
        )
    finally:
        reset_visual_reference_context(token)

    assert handoff is not None
    args = handoff["arguments"]
    assert args["attachments"] == [
        "/tmp/previous-selected.png",
        "/tmp/character.png",
        "/tmp/pose.png",
    ]
    assert args["include_image"] is True
    assert args["include_video"] is False
    assert args["reference_binding"] == {
        "mode": "session_visual_context",
        "reference_order_source": "session_visual_context",
        "role_policy": "preserve_session_role_hints",
        "reference_order": [
            {
                "index": 1,
                "role_hint": "edit_anchor",
                "attachment": "/tmp/previous-selected.png",
                "source": "previous_selected_artifact",
            },
            {
                "index": 2,
                "role_hint": "character_identity",
                "attachment": "/tmp/character.png",
                "source": "previous_tool_reference",
                "user_ref_index": 1,
            },
            {
                "index": 3,
                "role_hint": "pose_composition",
                "attachment": "/tmp/pose.png",
                "source": "previous_tool_reference",
                "user_ref_index": 2,
            },
        ],
    }


def test_direct_visual_handoff_formats_quality_gate_error_without_internal_label():
    from agent.visual.agent_mode.handoff import format_direct_visual_agent_handoff_response

    response = format_direct_visual_agent_handoff_response(
        json.dumps(
            {
                "success": False,
                "package_status": "failed",
                "error": "reference role transfer did not pass visual quality validation after repair",
            }
        )
    )

    assert response == "視覺生成失敗：參考圖角色/姿勢對應仍未通過品質檢查，已停止交付。"


def test_direct_visual_handoff_formats_recovery_summary_for_blocked_candidate():
    from agent.visual.agent_mode.handoff import format_direct_visual_agent_handoff_response

    response = format_direct_visual_agent_handoff_response(
        json.dumps(
            {
                "success": False,
                "package_status": "failed",
                "error": "visual candidate blocked by active-learning delivery gate",
                "delivery_recovery": {
                    "status": "blocked",
                    "blocked_modalities": ["image"],
                    "generated_candidate_available": True,
                    "actions": [
                        {
                            "modality": "image",
                            "recommended_action": "rerun_reference_repair_or_grok_web_polish",
                        }
                    ],
                },
            }
        )
    )

    assert response == "視覺生成暫停交付：已產生候選圖，但參考圖對應仍未通過品質檢查；下一步會重新修復或改用 Grok Web polish。"
