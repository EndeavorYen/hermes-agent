import base64
import json
from pathlib import Path
from types import SimpleNamespace

import yaml


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


def test_direct_visual_handoff_applies_raphael_runtime_media_contract():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )
    decision = {
        "mode": "visual_agent_generation",
        "route": {
            "visual_media_provider": "runtime-image-provider",
            "visual_media_model": "runtime-image-model",
            "visual_media_provider_source": "runtime_contract",
        },
        "runtime_contract": {
            "image_provider": "runtime-image-provider",
            "image_model": "runtime-image-model",
            "video_provider": "runtime-video-provider",
            "video_model": "runtime-video-model",
        },
    }

    handoff = build_direct_visual_agent_handoff(
        agent,
        "請產出一張圖片和一段影片",
        raphael_decision=decision,
    )

    assert handoff is not None
    assert handoff["arguments"]["image_provider"] == "runtime-image-provider"
    assert handoff["arguments"]["image_model"] == "runtime-image-model"
    assert handoff["arguments"]["video_provider"] == "runtime-video-provider"
    assert handoff["arguments"]["video_model"] == "runtime-video-model"
    assert handoff["plan"]["provider_contract"]["image_provider"] == (
        "runtime-image-provider"
    )


def test_direct_visual_handoff_keeps_prompt_provider_over_runtime_default():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.6-sol",
    )
    decision = {
        "mode": "visual_agent_generation",
        "route": {
            "visual_media_provider": "xai",
            "visual_media_model": "grok-imagine-image-quality",
            "visual_media_provider_source": "visual_agent_default",
        },
        "runtime_contract": {
            "image_provider": "xai",
            "image_model": "grok-imagine-image-quality",
        },
    }

    handoff = build_direct_visual_agent_handoff(
        agent,
        [
            {
                "type": "text",
                "text": "請使用 xAI 固定這位角色，產出 4 張不同姿勢的精緻圖片並完成 QC",
            },
            {"type": "image_url", "image_url": {"url": "/tmp/ref.png"}},
        ],
        raphael_decision=decision,
    )

    assert handoff is not None
    assert handoff["arguments"]["image_provider"] == "xai"
    assert handoff["arguments"]["image_provider_source"] == "prompt_override"


def test_direct_visual_handoff_preserves_compact_s_suffix_video_duration():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )
    message = [
        {
            "type": "text",
            "text": "用 xai，根據我提供的 ref , 產出 15s 性感影片，具乳，水蛇腰，翹臀，蜜大腿",
        },
        {"type": "image_url", "image_url": {"url": "/tmp/ref.png"}},
    ]

    handoff = build_direct_visual_agent_handoff(agent, message)

    assert handoff is not None
    assert handoff["arguments"]["include_video"] is True
    assert handoff["arguments"]["attachments"] == ["/tmp/ref.png"]
    assert handoff["arguments"]["duration"] == 15
    assert handoff["arguments"]["image_provider"] == "xai"


def test_direct_visual_handoff_skips_long_form_story_video_pipeline_requests():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )

    handoff = build_direct_visual_agent_handoff(
        agent,
        "幫我做一部恐龍起源的科普影片 (可用之前故事影片的 skill 或流程)，圖片走真實照片風格，請開始，大概 5mins",
    )

    assert handoff is None


def test_direct_visual_handoff_skips_narrated_multishot_long_form_video():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.6",
    )

    handoff = build_direct_visual_agent_handoff(
        agent,
        "請把這份故事做成有旁白、字幕與多段鏡頭的長篇影片",
    )

    assert handoff is None


def test_direct_visual_handoff_skips_followup_in_long_form_story_video_thread():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )
    prompt = """[Replying to: "幫我做一部恐龍起源的科普影片 (可用之前故事影片的 skill 或流程)，圖片走真實照片風格，請開始，大概 5mins"]

[Thread context — prior messages in this thread (not yet in conversation history):]
[thread parent] simon: 幫我做一部恐龍起源的科普影片 (可用之前故事影片的 skill 或流程)，圖片走真實照片風格，請開始，大概 5mins
[End of thread context]

請繼續產出影片"""

    handoff = build_direct_visual_agent_handoff(agent, prompt)

    assert handoff is None


def test_direct_visual_handoff_keeps_short_product_intro_on_visual_agent_route():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.6",
    )

    handoff = build_direct_visual_agent_handoff(
        agent,
        "Visual Agent：幫我做一部 6 秒產品介紹影片，從產品照開始。",
    )

    assert handoff is not None
    assert handoff["arguments"]["include_video"] is True


def test_explicit_visual_agent_turn_overrides_story_parent_for_current_turn():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.6",
    )
    prompt = """[Replying to: "故事影片：恐龍起源｜5分鐘｜真實照片"]

[Thread context — prior messages in this thread (not yet in conversation history):]
[thread parent] simon: 故事影片：恐龍起源｜5分鐘｜真實照片
[End of thread context]

Visual Agent：幫我做一張霧黑鋼筆產品照和 6 秒短片"""

    handoff = build_direct_visual_agent_handoff(agent, prompt)

    assert handoff is not None
    assert handoff["arguments"]["include_video"] is True


def test_explicit_visual_agent_turn_overrides_active_slack_reply_wrapper():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.6",
    )
    prompt = (
        '[Replying to: "故事影片：恐龍起源｜5分鐘｜真實照片"]\n\n'
        "Visual Agent：幫我做一張霧黑鋼筆產品照和 6 秒短片"
    )

    handoff = build_direct_visual_agent_handoff(agent, prompt)

    assert handoff is not None
    assert handoff["arguments"]["include_video"] is True


def test_explicit_visual_agent_reproduce_with_original_ref_routes_selected_delivery():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff
    from gateway.session_context import (
        reset_visual_reference_context,
        set_visual_reference_context,
    )

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.6",
    )
    prompt = """[Replying to: "用 xai imagine，locked ref 角色，給我 4 張挑選"]

[Thread context — prior messages in this thread (not yet in conversation history):]
[thread parent] user: 用 xai imagine，locked ref 角色，給我 4 張挑選
user: 沒看到圖，沒有成功上傳
[End of thread context]

visual agent : 用原本的ref, 再產2張不同姿勢的圖"""
    token = set_visual_reference_context(
        [
            {
                "uri": "/tmp/original-selected-ref.png",
                "role_hint": "edit_anchor",
                "source": "previous_tool_reference",
            }
        ]
    )
    try:
        handoff = build_direct_visual_agent_handoff(agent, prompt)
    finally:
        reset_visual_reference_context(token)

    assert handoff is not None
    assert handoff["mode"] == "pre_llm_direct"
    assert handoff["tool_name"] == "visual_agent_generate"
    assert handoff["arguments"]["attachments"] == [
        "/tmp/original-selected-ref.png"
    ]
    assert handoff["arguments"]["candidate_budget"] == 2
    assert handoff["arguments"]["image_provider"] == "xai"
    assert handoff["arguments"]["include_image"] is True
    assert handoff["arguments"]["include_video"] is False


def test_direct_visual_handoff_routes_natural_attachment_generation_request():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff
    from gateway.session_context import (
        reset_visual_reference_context,
        set_visual_reference_context,
    )

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.6-sol",
    )
    prompt = """用 xai imagine，參考附件的圖片，產出類似但不同姿勢、高品質，給我 4 張挑選

[Visual Arsenal source images]
The current Slack message includes user-uploaded source/reference images cached on this machine.
1. image_path: /tmp/current-slack-reference.png (image/png)

[Image attached at: /tmp/current-slack-reference.png]
[screenshot]"""
    token = set_visual_reference_context(
        [
            {
                "uri": "/tmp/current-slack-reference.png",
                "role_hint": "visual_reference",
                "source": "gateway_attachment",
                "user_ref_index": 0,
            }
        ]
    )
    try:
        handoff = build_direct_visual_agent_handoff(agent, prompt)
    finally:
        reset_visual_reference_context(token)

    assert handoff is not None
    assert handoff["mode"] == "pre_llm_direct"
    assert handoff["tool_name"] == "visual_agent_generate"
    assert handoff["arguments"]["attachments"] == [
        "/tmp/current-slack-reference.png"
    ]
    assert handoff["arguments"]["candidate_budget"] == 4
    assert handoff["arguments"]["candidate_budget_source"] == "user"
    assert handoff["arguments"]["image_provider"] == "xai"
    assert handoff["arguments"]["include_image"] is True
    assert handoff["arguments"]["include_video"] is False


def test_visual_agent_capability_question_does_not_trigger_generation():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.6",
    )

    handoff = build_direct_visual_agent_handoff(
        agent,
        "Does Visual Agent support video?",
    )

    assert handoff is None


def test_visual_agent_leading_capability_question_does_not_trigger_generation():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.6",
    )

    handoff = build_direct_visual_agent_handoff(
        agent,
        "Visual Agent supports video?",
    )

    assert handoff is None


def test_direct_visual_handoff_skips_grok_planner_for_openai_composition_guide():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )

    handoff = build_direct_visual_agent_handoff(
        agent,
        "現在用 openai 幫我產出構圖，一樣產出兩張不同構圖讓我挑選",
    )

    assert handoff is not None
    assert handoff["arguments"]["composition_guide_only"] is True
    assert handoff["arguments"]["image_provider"] == "openai-codex"
    assert handoff["arguments"]["candidate_budget"] == 2
    assert handoff["arguments"]["candidate_budget_source"] == "user"
    assert "visual_agent_llm_provider" not in handoff["arguments"]
    assert "visual_agent_llm_model" not in handoff["arguments"]
    assert handoff["visual_agent_llm_provider"] is None
    assert handoff["visual_agent_llm_model"] is None


def test_direct_visual_handoff_uses_current_slack_thread_intent_for_composition_guide():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )
    prompt = """[Replying to: "用 openai 幫我繪製這位人物的設定圖"]

[Thread context — prior messages in this thread (not yet in conversation history):]
[thread parent] simon: 用 openai 幫我繪製這位人物的設定圖
simon: 這四張根本看起來就一模一樣，不同畫風是指四個不同繪者的風格，請重新產生
simon: 現在用 openai 幫我產出構圖，一樣產出四張不同構圖讓我挑選
[End of thread context]

用 openai 幫我產出構圖，給我四張構圖候選，每張都有個情境的某個瞬間。請開始"""

    handoff = build_direct_visual_agent_handoff(agent, prompt)

    assert handoff is not None
    args = handoff["arguments"]
    assert args["prompt"].startswith("用 openai 幫我產出構圖")
    assert "Thread context" not in args["prompt"]
    assert args["composition_guide_only"] is True
    assert "character_design_ref_only" not in args
    assert args["candidate_budget"] == 4
    assert args["image_provider"] == "openai-codex"
    assert handoff["plan"]["reason"] == "composition_guide_request"


def test_direct_visual_handoff_attaches_raphael_control_metadata(tmp_path, monkeypatch):
    from agent.visual.agent_mode.handoff import (
        attach_direct_visual_agent_handoff_metadata,
        build_direct_visual_agent_handoff,
    )

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "plugins": {"enabled": ["raphael"], "disabled": []},
                "raphael": {
                    "enabled": True,
                    "default_conversation_mode_enabled": True,
                    "mode": "sage_king",
                },
            }
        ),
        encoding="utf-8",
    )
    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )

    handoff = build_direct_visual_agent_handoff(agent, "請產出一張圖片和一段影片")
    payload = json.loads(
        attach_direct_visual_agent_handoff_metadata(
            json.dumps({"success": True, "images": ["/tmp/current.png"]}),
            handoff,
        )
    )

    control = payload["direct_visual_agent_handoff"]["raphael_control"]
    assert control["mode"] == "visual_agent_generation"
    assert control["next_action"] == "call_visual_agent_generate"
    assert control["route"]["handoff_tool"] == "visual_agent_generate"
    assert "artifact_quality_evidence" in control["evidence"]["required_proofs"]


def test_direct_visual_handoff_reuses_canonical_decision_without_recomputing(
    monkeypatch,
):
    from agent.raphael.control import build_raphael_control_decision
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.6-terra",
    )
    control = build_raphael_control_decision("請產出一張圖片").to_dict()
    canonical = {
        "turn_id": "turn-canonical",
        "mode": control["mode"],
        "goal": control["goal"],
        "route": control["route"],
        "evidence": control["evidence"],
        "next_action": control["next_action"],
        "reference_resolution": control["reference_resolution"],
        "clarification_question": control["clarification_question"],
        "confidence": control["confidence"],
    }
    canonical["route"]["visual_agent_llm_provider"] = "xai-oauth"
    canonical["route"]["visual_agent_llm_model"] = "grok-runtime-model"

    monkeypatch.setattr(
        "agent.raphael.control.build_raphael_control_decision",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("control decision recomputed")
        ),
    )

    handoff = build_direct_visual_agent_handoff(
        agent,
        "請產出一張圖片",
        raphael_decision=canonical,
    )

    assert handoff is not None
    assert handoff["raphael_control"]["turn_id"] == "turn-canonical"
    assert handoff["arguments"]["visual_agent_llm_provider"] == "xai-oauth"
    assert handoff["arguments"]["visual_agent_llm_model"] == "grok-runtime-model"


def test_direct_visual_handoff_fails_closed_when_raphael_evidence_is_missing(
    tmp_path, monkeypatch
):
    from agent.visual.agent_mode.handoff import (
        attach_direct_visual_agent_handoff_metadata,
        build_direct_visual_agent_handoff,
        format_direct_visual_agent_handoff_response,
    )

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "plugins": {"enabled": ["raphael"], "disabled": []},
                "raphael": {
                    "enabled": True,
                    "default_conversation_mode_enabled": True,
                    "mode": "sage_king",
                },
            }
        ),
        encoding="utf-8",
    )
    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )

    handoff = build_direct_visual_agent_handoff(agent, "請產出一張圖片和一段影片")
    raw = attach_direct_visual_agent_handoff_metadata(
        json.dumps({"success": True, "images": ["/tmp/current.png"]}),
        handoff,
    )
    payload = json.loads(raw)

    assert payload["success"] is False
    assert payload["images"] == []
    assert payload["error_type"] == "raphael_evidence_gate_failed"
    gate = payload["direct_visual_agent_handoff"]["raphael_evidence_gate"]
    assert gate["passed"] is False
    assert "artifact_quality_evidence" in gate["missing_proofs"]
    assert "selected_current_artifact_only" in gate["missing_proofs"]
    assert format_direct_visual_agent_handoff_response(raw).startswith("視覺生成失敗：")


def test_raphael_evidence_gate_rejects_empty_turn_identity():
    from agent.visual.agent_mode.handoff import _evaluate_raphael_evidence_gate

    gate = _evaluate_raphael_evidence_gate(
        {
            "mission_id": "mission-current",
            "turn_id": "",
            "route": {"visual_media_provider": "xai"},
            "evidence": {"required_proofs": []},
        },
        {
            "rankings": {"selected_artifact_id": "artifact-current"},
        },
    )

    assert gate["passed"] is False
    assert "turn_identity" in gate["missing_proofs"]


def test_direct_visual_handoff_allows_payload_with_raphael_evidence(
    tmp_path, monkeypatch
):
    import agent.raphael.state as raphael_state
    from agent.raphael.finalization import enforce_raphael_completion
    from agent.raphael.kernel import prepare_raphael_turn
    from agent.raphael.runtime_contract import (
        RaphaelRuntimeContract,
        RaphaelTurnOrigin,
    )
    from agent.visual.agent_mode.handoff import (
        attach_direct_visual_agent_handoff_metadata,
        build_direct_visual_agent_handoff,
    )

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config = {
        "plugins": {"enabled": ["raphael"], "disabled": []},
        "raphael": {
            "enabled": True,
            "default_conversation_mode_enabled": True,
            "mode": "sage_king",
        },
    }
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(config),
        encoding="utf-8",
    )
    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )

    decision = prepare_raphael_turn(
        turn_id="turn-structured-evidence",
        origin=RaphaelTurnOrigin.FOREGROUND,
        runtime_contract=RaphaelRuntimeContract(
            base_provider="openai-codex",
            base_model="gpt-5.5",
            base_api_mode="codex_app_server",
            image_provider="xai",
            image_model="grok-imagine-image-quality",
            source="live_agent",
        ),
        config=config,
        user_message="請產出一張圖片",
    )
    assert decision is not None
    assert decision.mission_id
    handoff = build_direct_visual_agent_handoff(
        agent,
        "請產出一張圖片",
        raphael_decision=decision.to_dict(),
    )
    assert handoff is not None
    raw = attach_direct_visual_agent_handoff_metadata(
        json.dumps(
            {
                "success": True,
                "images": ["/tmp/current.png"],
                "generation_payloads": {"image": {"success": True}},
                "rankings": {"selected_artifact_id": "artifact-1"},
                "delivery_metadata": {
                    "selected_visual_artifact_ids": ["artifact-1"],
                    "visual_artifacts": {
                        "/tmp/current.png": {
                            "artifact_id": "artifact-1",
                            "request_id": "vrq_1",
                        }
                    },
                    "visual_quality_run": {
                        "success": True,
                        "summary": {
                            "case_count": 1,
                            "failed_case_count": 0,
                            "quality_issue_count": 0,
                        },
                        "self_review": {
                            "privacy_safe": True,
                            "raw_prompt_omitted": True,
                        },
                    },
                },
                "delivery_recovery": {
                    "status": "delivered",
                    "deliver_rejected_artifact": False,
                    "self_review": {
                        "preserves_delivery_quality_gate": True,
                        "avoids_stale_or_rejected_slack_delivery": True,
                    },
                },
                "delivery_gate": {"image": {"allowed": True}},
                "autonomous_validation": {"valid": True},
            }
        ),
        handoff,
    )
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["images"] == ["/tmp/current.png"]
    gate = payload["direct_visual_agent_handoff"]["raphael_evidence_gate"]
    assert gate["passed"] is True
    assert gate["missing_proofs"] == []
    assert {event["proof_type"] for event in gate["evidence_events"]} == set(
        gate["required_proofs"]
    )
    assert all(event["status"] == "passed" for event in gate["evidence_events"])
    assert all(
        event["turn_id"] == "turn-structured-evidence"
        for event in gate["evidence_events"]
    )
    assert all(
        event["mission_id"] == decision.mission_id
        for event in gate["evidence_events"]
    )
    assert all(event["provider"] == "xai" for event in gate["evidence_events"])
    assert all(
        event["payload_digest"].startswith("sha256:")
        for event in gate["evidence_events"]
    )
    mission = raphael_state.read_mission_state()
    assert mission is not None
    assert mission.active_artifact_id == "artifact-1"
    assert mission.proof_status == "passed"
    assert mission.phase == "proof_passed"
    finalization = enforce_raphael_completion(
        decision=decision.to_dict(),
        final_response="已產出並成功交付。",
        messages=(
            {
                "role": "tool",
                "name": "visual_agent_generate",
                "content": raw,
            },
        ),
    )
    assert finalization.status == "passed"


def test_direct_visual_handoff_allows_video_payload_with_image_first_source_evidence(
    tmp_path, monkeypatch
):
    from agent.visual.agent_mode.handoff import (
        attach_direct_visual_agent_handoff_metadata,
        build_direct_visual_agent_handoff,
    )

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "plugins": {"enabled": ["raphael"], "disabled": []},
                "raphael": {
                    "enabled": True,
                    "default_conversation_mode_enabled": True,
                    "mode": "sage_king",
                },
            }
        ),
        encoding="utf-8",
    )
    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )

    handoff = build_direct_visual_agent_handoff(agent, "請產出一段 6 秒時尚短片，主體是霧黑鋼筆")
    assert handoff is not None
    handoff["raphael_control"]["turn_id"] = "turn-video-evidence"
    handoff["raphael_control"]["mission_id"] = "mission-video-evidence"
    required = handoff["raphael_control"]["evidence"]["required_proofs"]
    assert "image_first_video_source_evidence" in required
    assert "single_ranked_video_source_image" in required

    raw = attach_direct_visual_agent_handoff_metadata(
        json.dumps(
            {
                "success": True,
                "images": [],
                "videos": ["/tmp/current.mp4"],
                "generation_payloads": {
                    "image": {"success": True, "provider": "fixture"},
                    "video": [{"success": True, "provider": "fixture"}],
                },
                "rankings": {"selected_artifact_id": "artifact-video-1"},
                "generation_strategy": {
                    "image_first_for_video": True,
                    "video_source_image": "/tmp/source.png",
                    "video_source_image_count": 1,
                    "video_source_policy": "single_ranked_selected_image",
                },
                "delivery_metadata": {
                    "selected_visual_artifact_ids": ["artifact-video-1"],
                    "visual_artifacts": {
                        "/tmp/current.mp4": {
                            "artifact_id": "artifact-video-1",
                            "request_id": "vrq_video",
                            "freshness_status": "fresh",
                            "is_stable": True,
                        }
                    },
                    "visual_quality_run": {
                        "success": True,
                        "summary": {
                            "case_count": 1,
                            "failed_case_count": 0,
                            "quality_issue_count": 0,
                            "image_first_video_source_covered_count": 1,
                            "image_first_video_source_failure_count": 0,
                            "video_source_image_count": 1,
                        },
                        "self_review": {
                            "privacy_safe": True,
                            "raw_prompt_omitted": True,
                            "image_first_video_source_covered": True,
                            "single_video_source_image": True,
                        },
                    },
                },
                "delivery_recovery": {
                    "status": "delivered",
                    "deliver_rejected_artifact": False,
                    "self_review": {
                        "preserves_delivery_quality_gate": True,
                        "avoids_stale_or_rejected_slack_delivery": True,
                    },
                },
                "delivery_gate": {"video": {"allowed": True}},
                "autonomous_validation": {"valid": True},
            }
        ),
        handoff,
    )
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["videos"] == ["/tmp/current.mp4"]
    gate = payload["direct_visual_agent_handoff"]["raphael_evidence_gate"]
    assert gate["passed"] is True
    assert gate["missing_proofs"] == []


def test_direct_visual_handoff_rejects_delivery_allowed_without_quality_metadata(
    tmp_path, monkeypatch
):
    from agent.visual.agent_mode.handoff import (
        attach_direct_visual_agent_handoff_metadata,
        build_direct_visual_agent_handoff,
    )

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "plugins": {"enabled": ["raphael"], "disabled": []},
                "raphael": {
                    "enabled": True,
                    "default_conversation_mode_enabled": True,
                    "mode": "sage_king",
                },
            }
        ),
        encoding="utf-8",
    )
    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )

    handoff = build_direct_visual_agent_handoff(agent, "請產出一張圖片")
    raw = attach_direct_visual_agent_handoff_metadata(
        json.dumps(
            {
                "success": True,
                "images": ["/tmp/current.png"],
                "generation_payloads": {"image": {"success": True, "provider": "fixture"}},
                "rankings": {"selected_artifact_id": "artifact-1"},
                "delivery_metadata": {
                    "selected_visual_artifact_ids": ["artifact-1"],
                    "visual_artifacts": {
                        "/tmp/current.png": {
                            "artifact_id": "artifact-1",
                            "request_id": "vrq_1",
                        }
                    },
                },
                "delivery_recovery": {
                    "status": "delivered",
                    "deliver_rejected_artifact": False,
                },
                "delivery_gate": {"image": {"allowed": True}},
                "autonomous_validation": {"valid": True},
            }
        ),
        handoff,
    )
    payload = json.loads(raw)
    gate = payload["direct_visual_agent_handoff"]["raphael_evidence_gate"]

    assert payload["success"] is False
    assert gate["passed"] is False
    assert "artifact_quality_evidence" in gate["missing_proofs"]


def test_direct_visual_handoff_rejects_stale_or_unmapped_selected_artifact(
    tmp_path,
    monkeypatch,
):
    from agent.visual.agent_mode.handoff import (
        attach_direct_visual_agent_handoff_metadata,
        build_direct_visual_agent_handoff,
    )

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "plugins": {"enabled": ["raphael"], "disabled": []},
                "raphael": {
                    "enabled": True,
                    "default_conversation_mode_enabled": True,
                    "mode": "sage_king",
                },
            }
        ),
        encoding="utf-8",
    )
    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )

    handoff = build_direct_visual_agent_handoff(agent, "請產出一張圖片")
    raw = attach_direct_visual_agent_handoff_metadata(
        json.dumps(
            {
                "success": True,
                "images": ["/tmp/old-rejected-or-unrelated.png"],
                "generation_payloads": {"image": {"success": True, "provider": "fixture"}},
                "delivery_metadata": {
                    "selected_visual_artifact_ids": ["missing-from-artifacts"],
                    "visual_artifacts": {},
                },
                "delivery_recovery": {
                    "deliver_rejected_artifact": False,
                    "self_review": {
                        "preserves_delivery_quality_gate": True,
                        "avoids_stale_or_rejected_slack_delivery": True,
                    },
                },
                "delivery_gate": {"image": {"allowed": True}},
                "autonomous_validation": {"valid": True},
            }
        ),
        handoff,
    )
    payload = json.loads(raw)
    gate = payload["direct_visual_agent_handoff"]["raphael_evidence_gate"]

    assert payload["success"] is False
    assert "selected_current_artifact_only" in gate["missing_proofs"]
    assert "stale_artifact_guard" in gate["missing_proofs"]
    assert "delivery_cleanliness" in gate["missing_proofs"]
    stale_event = next(
        event
        for event in gate["evidence_events"]
        if event["proof_type"] == "stale_artifact_guard"
    )
    assert stale_event["status"] == "missing"


def test_direct_visual_handoff_fails_closed_for_unknown_raphael_proof(
    tmp_path, monkeypatch
):
    from agent.visual.agent_mode.handoff import (
        attach_direct_visual_agent_handoff_metadata,
        build_direct_visual_agent_handoff,
    )

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "plugins": {"enabled": ["raphael"], "disabled": []},
                "raphael": {
                    "enabled": True,
                    "default_conversation_mode_enabled": True,
                    "mode": "sage_king",
                },
            }
        ),
        encoding="utf-8",
    )
    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )
    handoff = build_direct_visual_agent_handoff(agent, "請產出一張圖片")
    handoff["raphael_control"]["evidence"]["required_proofs"] = [
        "future_visual_proof_not_implemented"
    ]

    raw = attach_direct_visual_agent_handoff_metadata(
        json.dumps({"success": True, "images": ["/tmp/current.png"]}),
        handoff,
    )
    payload = json.loads(raw)
    gate = payload["direct_visual_agent_handoff"]["raphael_evidence_gate"]

    assert payload["success"] is False
    assert gate["passed"] is False
    assert "future_visual_proof_not_implemented" in gate["missing_proofs"]


def test_direct_visual_handoff_rejects_failed_artifact_quality_payload(
    tmp_path, monkeypatch
):
    from agent.visual.agent_mode.handoff import (
        attach_direct_visual_agent_handoff_metadata,
        build_direct_visual_agent_handoff,
    )

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "plugins": {"enabled": ["raphael"], "disabled": []},
                "raphael": {
                    "enabled": True,
                    "default_conversation_mode_enabled": True,
                    "mode": "sage_king",
                },
            }
        ),
        encoding="utf-8",
    )
    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )
    handoff = build_direct_visual_agent_handoff(agent, "請產出一張圖片")
    handoff["raphael_control"]["evidence"]["required_proofs"] = [
        "artifact_quality_evidence"
    ]

    raw = attach_direct_visual_agent_handoff_metadata(
        json.dumps(
            {
                "success": True,
                "images": ["/tmp/current.png"],
                "rankings": {"selected_artifact_id": "artifact-1"},
                "delivery_gate": {"image": {"allowed": False}},
                "autonomous_validation": {"valid": False},
            }
        ),
        handoff,
    )
    payload = json.loads(raw)
    gate = payload["direct_visual_agent_handoff"]["raphael_evidence_gate"]

    assert payload["success"] is False
    assert gate["passed"] is False
    assert "artifact_quality_evidence" in gate["missing_proofs"]


def test_direct_visual_handoff_omits_raphael_control_when_raphael_disabled(
    tmp_path, monkeypatch
):
    from agent.visual.agent_mode.handoff import (
        attach_direct_visual_agent_handoff_metadata,
        build_direct_visual_agent_handoff,
    )

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "plugins": {"enabled": ["raphael"], "disabled": []},
                "raphael": {
                    "enabled": False,
                    "default_conversation_mode_enabled": False,
                    "mode": "sage_king",
                },
            }
        ),
        encoding="utf-8",
    )
    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )

    handoff = build_direct_visual_agent_handoff(agent, "請產出一張圖片和一段影片")
    payload = json.loads(
        attach_direct_visual_agent_handoff_metadata(
            json.dumps({"success": True, "images": ["/tmp/current.png"]}),
            handoff,
        )
    )

    assert "raphael_control" not in payload["direct_visual_agent_handoff"]


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


def test_direct_visual_handoff_strips_visual_arsenal_metadata_from_prompt():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )
    message = [
        {
            "type": "text",
            "text": (
                "請用 Grok Imagine + reference 固定這位角色，產出不同姿勢候選並選最佳，只交付最佳圖片。\n\n"
                "[Visual Arsenal source images]\n"
                "The current Slack message includes user-uploaded source/reference images cached on this machine.\n"
                "1. image_path: /private/mock-hermes-home/image_cache/img_ref.png (image/png)"
            ),
        },
        {"type": "image_url", "image_url": {"url": "/tmp/ref.png"}},
    ]

    handoff = build_direct_visual_agent_handoff(agent, message)

    assert handoff is not None
    assert handoff["arguments"]["prompt"].startswith(
        "請用 Grok Imagine + reference 固定這位角色，產出不同姿勢候選並選最佳，只交付最佳圖片。"
    )
    assert handoff["arguments"]["reference_binding"]["reference_order"][0]["role_hint"] == "character_identity"
    assert "Visual Arsenal" not in handoff["arguments"]["prompt"]
    assert "image_cache" not in handoff["arguments"]["prompt"]


def test_direct_visual_handoff_ignores_image_discussion_without_generation_intent():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )

    handoff = build_direct_visual_agent_handoff(agent, "這張圖片的構圖好看嗎？")

    assert handoff is None


def test_direct_visual_handoff_ignores_text_only_visual_route_analysis():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )

    prompts = (
        "純文字回答，不使用工具。如果使用者要求 image + video，但禁止產圖，應路由到什麼 mode/provider？",
        "只做 LLM 判斷，不要呼叫任何產圖工具，請分析 image/video proof gate。",
        "Text-only visual route/provider/proof-gate analysis; no tools and no image generation.",
        "請分析如果使用者要求產圖和生成影片，應該路由到哪個 provider / proof gate？",
        "如果我要之後做 image + video，先不要實際做圖，請判斷 mode 和 provider。",
        (
            "同一個 hostile UX 測試，現在模擬真實文字任務：我要公開 Raphael，"
            "但又怕 overclaim；我要使用者 wow，但不能產圖、不能用工具、不能假綠燈。"
            "請只用六行回答：目標、成功條件、證據門檻、阻塞、修正策略、可公開說法。"
            "不要宣稱已完成。"
        ),
    )

    for prompt in prompts:
        assert build_direct_visual_agent_handoff(agent, prompt) is None


def test_direct_visual_handoff_respects_raphael_runtime_analysis_veto(monkeypatch):
    from agent.visual.agent_mode import handoff as handoff_module

    monkeypatch.setattr(
        handoff_module,
        "is_text_only_visual_analysis_request",
        lambda _prompt: False,
    )
    monkeypatch.setattr(handoff_module, "_raphael_handoff_control_enabled", lambda: True)
    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )

    handoff = handoff_module.build_direct_visual_agent_handoff(
        agent,
        "我要公開 Raphael，但不能產圖、不能用工具。請只用六行回答，不要宣稱已完成。",
    )

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


def test_direct_visual_handoff_ignores_prompt_builder_request_with_images():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )
    message = [
        {
            "type": "text",
            "text": (
                "固定這位角色，替換不同的服裝與構圖，高品質，8K，光影，性感一些。"
                "請給我 prompt 就好，不須產圖"
            ),
        },
        {"type": "image_url", "image_url": {"url": "/tmp/ref-1.png"}},
        {"type": "image_url", "image_url": {"url": "/tmp/ref-2.png"}},
    ]

    handoff = build_direct_visual_agent_handoff(agent, message)

    assert handoff is None


def test_direct_visual_handoff_ignores_suitable_xai_video_prompt_request_with_image():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff
    from agent.visual.agent_mode.handoff import is_visual_prompt_builder_request

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )
    message = [
        {
            "type": "text",
            "text": (
                "我想要用這張在 xai imagine 中產出 12s 影片，請給我合適的 prompt。"
                "稍微嬌羞，稍微性感，稍微嫵媚，稍微傲嬌，胸，整體呈現讓人有種「好婆喔！」的感覺"
            ),
        },
        {"type": "image_url", "image_url": {"url": "/tmp/ref.png"}},
    ]

    assert is_visual_prompt_builder_request(message[0]["text"]) is True
    assert build_direct_visual_agent_handoff(agent, message) is None


def test_direct_visual_handoff_defaults_reference_visual_brief_to_prompt_only():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )
    message = [
        {
            "type": "text",
            "text": "固定這位角色，替換不同的服裝與構圖，高品質，8K，光影，性感一些",
        },
        {"type": "image_url", "image_url": {"url": "/tmp/ref-1.png"}},
        {"type": "image_url", "image_url": {"url": "/tmp/ref-2.png"}},
    ]

    handoff = build_direct_visual_agent_handoff(agent, message)

    assert handoff is None


def test_direct_visual_handoff_ignores_prompt_edit_request_with_session_refs():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff
    from agent.visual.agent_mode.handoff import is_visual_prompt_builder_request
    from gateway.session_context import reset_visual_reference_context, set_visual_reference_context

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )
    token = set_visual_reference_context(
        [
            {
                "uri": "/tmp/ref-1.png",
                "role_hint": "visual_reference",
                "source": "session_visual_context",
            }
        ]
    )
    try:
        prompts = [
            "是這一版 prompt, 再修改性感一點的服裝",
            "就是我提供的那個 prompt, 你幫我修改 prompt, 替換更性感的服裝敘述",
            "你看，很普，請給我改進的 prompt",
            "產出的品質很普，請給我更生動姿勢、更像 X 爆款的改進 prompt",
        ]
        for prompt in prompts:
            assert is_visual_prompt_builder_request(prompt) is True
            assert build_direct_visual_agent_handoff(agent, prompt) is None
    finally:
        reset_visual_reference_context(token)


def test_direct_visual_handoff_ignores_negative_visual_generation_instruction():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )

    handoff = build_direct_visual_agent_handoff(
        agent,
        "Live LLM smoke. Do not generate images or video. Reply exactly OK.",
    )

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


def test_direct_visual_handoff_routes_colloquial_chinese_reference_edit():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff
    from gateway.session_context import reset_visual_reference_context, set_visual_reference_context

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.6-sol",
    )
    token = set_visual_reference_context(
        [
            {
                "uri": "/tmp/g1.png",
                "role_hint": "edit_anchor",
                "source": "previous_selected_artifact",
                "user_ref_index": 1,
            },
            {
                "uri": "/tmp/g4.png",
                "role_hint": "visual_reference",
                "source": "previous_tool_reference",
                "user_ref_index": 4,
            },
        ]
    )
    try:
        handoff = build_direct_visual_agent_handoff(
            agent,
            (
                "G1 ~ G4 都不錯，其中 G1 和 G4 更棒。現在以 G1 和 G4 "
                "為主要參考，幫我換個背景，然後把鞋給脫了露出絲襪腳底"
            ),
        )
    finally:
        reset_visual_reference_context(token)

    assert handoff is not None
    assert handoff["tool_name"] == "visual_agent_generate"
    assert handoff["arguments"]["attachments"] == ["/tmp/g1.png", "/tmp/g4.png"]
    assert handoff["arguments"]["include_image"] is True
    assert handoff["arguments"]["include_video"] is False


def test_direct_visual_handoff_routes_grok_web_alias_followup_to_xai():
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
                "role_hint": "visual_reference",
                "source": "previous_tool_reference",
                "user_ref_index": 1,
            },
        ]
    )
    try:
        handoff = build_direct_visual_agent_handoff(
            agent,
            "請使用 grok-web-imagine provider，可不可以再嘗試不同的構圖，可以類似原 ref 的構圖進行調整和優化",
        )
    finally:
        reset_visual_reference_context(token)

    assert handoff is not None
    args = handoff["arguments"]
    assert args["image_provider"] == "xai"
    assert args["candidate_budget"] == 1
    assert args["candidate_budget_source"] == "planner_default"
    assert args["attachments"] == ["/tmp/character.png"]


def test_direct_visual_handoff_routes_grok_web_alias_regenerate_to_xai():
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
        handoff = build_direct_visual_agent_handoff(
            agent,
            '[Replying to: "請使用 grok-web-imagine provider 產圖"]\n\n重新產生',
        )
    finally:
        reset_visual_reference_context(token)

    assert handoff is not None
    args = handoff["arguments"]
    assert args["image_provider"] == "xai"
    assert args["attachments"] == ["/tmp/previous-selected.png"]


def test_direct_visual_handoff_routes_traditional_chinese_regenerate_output_to_xai():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff
    from gateway.session_context import reset_visual_reference_context, set_visual_reference_context

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.6-sol",
    )
    token = set_visual_reference_context(
        [
            {
                "uri": "/tmp/locked-character.png",
                "role_hint": "character_identity",
                "source": "previous_tool_reference",
                "user_ref_index": 1,
            }
        ]
    )
    try:
        handoff = build_direct_visual_agent_handoff(
            agent,
            (
                '[Replying to: "用 xai imagine，locked ref 人物，產出類似但不同姿勢，'
                '給我 4 張挑選"]\n\n'
                "[Thread context — prior messages in this thread (not yet in conversation history):]\n"
                "[thread parent] simon: 用 xai imagine，locked ref 人物，產出類似但不同姿勢，給我 4 張挑選\n"
                "[End of thread context]\n\n"
                "請重新產出"
            ),
        )
    finally:
        reset_visual_reference_context(token)

    assert handoff is not None
    args = handoff["arguments"]
    assert args["image_provider"] == "xai"
    assert args["attachments"] == ["/tmp/locked-character.png"]
    assert args["include_image"] is True
    assert args["include_video"] is False
    assert args["candidate_budget"] == 4
    assert args["candidate_budget_source"] == "thread_context"


def test_direct_visual_handoff_promotes_current_attachment_for_direct_xai_polish():
    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff

    agent = SimpleNamespace(
        valid_tool_names={"visual_agent_generate"},
        provider="openai-codex",
        model="gpt-5.5",
    )
    message = [
        {"type": "text", "text": "用 grok web polish 試試看"},
        {"type": "image_url", "image_url": {"url": "/tmp/current-selected.png"}},
        {"type": "image_url", "image_url": {"url": "/tmp/older-reference.png"}},
    ]

    handoff = build_direct_visual_agent_handoff(agent, message)

    assert handoff is not None
    args = handoff["arguments"]
    assert args["include_image"] is True
    assert args["include_video"] is False
    assert args["polish_provider"] == "xai"
    assert args["polish_provider_source"] == "prompt_override"
    assert args["attachments"] == ["/tmp/current-selected.png", "/tmp/older-reference.png"]
    assert args["reference_binding"]["reference_order"][0] == {
        "index": 1,
        "role_hint": "edit_anchor",
        "attachment": "/tmp/current-selected.png",
        "source": "current_visual_context",
        "user_ref_index": "previous_selected_output",
    }
    assert args["reference_binding"]["reference_order"][1] == {
        "index": 2,
        "role_hint": "visual_reference",
        "attachment": "/tmp/older-reference.png",
        "source": "current_visual_context",
    }
    assert "edit target" in args["prompt"]


def test_direct_visual_handoff_promotes_session_reference_for_direct_xai_polish():
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
                "uri": "/tmp/current-selected.png",
                "role_hint": "visual_reference",
                "source": "session_visual_context",
            },
            {
                "uri": "/tmp/older-reference.png",
                "role_hint": "visual_reference",
                "source": "session_visual_context",
            },
        ]
    )
    try:
        handoff = build_direct_visual_agent_handoff(agent, "用 grok web polish 試試看")
    finally:
        reset_visual_reference_context(token)

    assert handoff is not None
    args = handoff["arguments"]
    assert args["polish_provider"] == "xai"
    assert args["attachments"] == ["/tmp/current-selected.png", "/tmp/older-reference.png"]
    assert args["reference_binding"]["reference_order"][0] == {
        "index": 1,
        "role_hint": "edit_anchor",
        "attachment": "/tmp/current-selected.png",
        "source": "session_visual_context",
        "user_ref_index": "previous_selected_output",
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


def test_direct_visual_handoff_formats_bare_tool_error_as_failure():
    from agent.visual.agent_mode.handoff import format_direct_visual_agent_handoff_response

    response = format_direct_visual_agent_handoff_response(
        json.dumps(
            {
                "error": "visual_package_generate is for image/video generation, not visual feedback",
                "request_type": "visual_feedback",
            }
        )
    )

    assert response == "視覺生成失敗：visual_package_generate is for image/video generation, not visual feedback"


def test_direct_visual_handoff_formats_resource_exhaustion_as_actionable_failure():
    from agent.visual.agent_mode.handoff import format_direct_visual_agent_handoff_response

    response = format_direct_visual_agent_handoff_response(
        json.dumps(
            {
                "success": False,
                "package_status": "failed",
                "error_type": "visual_package_resource_exhaustion",
                "error": "unable to open database file",
            }
        )
    )

    assert response == "視覺生成失敗：本機 visual package 資源耗盡，已停止避免重複產生；請重啟 gateway 後再試。"


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
