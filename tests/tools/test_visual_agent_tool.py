import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


_ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


@pytest.fixture(autouse=True)
def _isolate_runtime_provider_profiles(monkeypatch):
    from tools import visual_agent_tool

    monkeypatch.setattr(
        visual_agent_tool,
        "_runtime_provider_quality_profiles",
        lambda **_kwargs: {},
        raising=False,
    )


def test_visual_agent_registry_handler_is_synchronous():
    import inspect

    from tools.registry import discover_builtin_tools, registry

    discover_builtin_tools()
    entry = registry._tools["visual_agent_generate"]
    assert entry.is_async is False
    assert inspect.iscoroutinefunction(entry.handler) is False


def test_visual_agent_generate_plans_natural_image_plus_video_request(monkeypatch):
    from tools import visual_agent_tool

    captured = {}

    def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps(
            {
                "success": True,
                "images": ["/tmp/current.png"],
                "videos": ["/tmp/current.mp4"],
            }
        )

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )

    raw = visual_agent_tool._handle_visual_agent_generate(
        {
            "prompt": "請用這張 reference 產出一張圖片和一段 6 秒影片",
            "attachments": ["/tmp/ref.png"],
        }
    )
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["visual_agent_plan"]["tool_name"] == "visual_package_generate"
    assert payload["visual_agent_plan"]["reason"] == "image_plus_video_request"
    assert captured["prompt"] == "請用這張 reference 產出一張圖片和一段 6 秒影片"
    assert captured["attachments"] == ["/tmp/ref.png"]
    assert captured["include_image"] is True
    assert captured["include_video"] is True
    assert captured["candidate_budget"] == 1
    assert captured["candidate_budget_source"] == "user"
    assert captured["video_budget"] == 1
    assert captured["visual_production_kernel"] is True
    assert captured["max_generated_repairs"] == 2
    assert captured["visual_contract_hash"]
    assert captured["visual_intent_contract"]["original_request"] == (
        "請用這張 reference 產出一張圖片和一段 6 秒影片"
    )
    assert captured["provider_decision"]["provider"] == "xai"


def test_visual_agent_generate_routes_one_provider_from_measured_quality_profile(monkeypatch):
    from tools import visual_agent_tool

    captured = {}
    profile_lookup = {}

    def fake_profiles(*, category=None):
        profile_lookup["category"] = category
        return {
            "xai": {
                "sample_count": 12,
                "first_pass_rate": 0.5,
                "failure_rate": 0.1,
            },
            "openai-codex": {
                "sample_count": 8,
                "first_pass_rate": 0.9,
                "failure_rate": 0.0,
            },
        }

    monkeypatch.setattr(
        visual_agent_tool,
        "_runtime_provider_quality_profiles",
        fake_profiles,
    )
    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        lambda args, **_kwargs: captured.update(args)
        or json.dumps({"success": True, "images": ["/tmp/current.png"], "videos": []}),
    )

    payload = json.loads(
        visual_agent_tool._handle_visual_agent_generate(
            {"prompt": "請生成乾淨產品攝影圖片"}
        )
    )

    assert payload["success"] is True
    assert profile_lookup["category"] == "product"
    assert captured["image_provider"] == "openai-codex"
    assert captured["image_provider_source"] == "visual_kernel_quality_profile"
    assert captured["provider_decision"]["reason"] == "measured_quality_profile"
    assert captured["provider_decision"]["evidence"]["providers_evaluated"] == 2
    assert payload["visual_agent_provider_contract"]["image_provider"] == (
        "openai-codex"
    )
    assert payload["visual_agent_provider_contract"][
        "visual_media_provider_selected"
    ] == "openai-codex"
    assert payload["visual_agent_provider_contract"][
        "visual_media_provider_selection_reason"
    ] == "measured_quality_profile"


def test_visual_agent_generate_does_not_downgrade_prompt_provider_source(monkeypatch):
    from tools import visual_agent_tool

    captured = {}
    monkeypatch.setattr(
        visual_agent_tool,
        "_runtime_provider_quality_profiles",
        lambda **_kwargs: {
            "xai": {"sample_count": 12, "first_pass_rate": 0.5, "failure_rate": 0.1},
            "openai-codex": {
                "sample_count": 12,
                "first_pass_rate": 0.95,
                "failure_rate": 0.0,
            },
        },
    )
    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        lambda args, **_kwargs: captured.update(args)
        or json.dumps({"success": True, "images": ["/tmp/current.png"], "videos": []}),
    )

    payload = json.loads(
        visual_agent_tool._handle_visual_agent_generate(
            {
                "prompt": "請使用 xAI 固定這位角色，產出 4 張不同姿勢的精緻圖片並完成 QC",
                "attachments": ["/tmp/ref.png"],
                "image_provider": "xai",
                "image_provider_source": "runtime_contract",
                "candidate_budget": 4,
                "candidate_budget_source": "user",
            }
        )
    )

    assert payload["success"] is True
    assert captured["image_provider"] == "xai"
    assert captured["image_provider_source"] == "prompt_override"
    assert captured["provider_decision"]["reason"] == "explicit_override"


def test_visual_agent_generate_materializes_data_uri_attachment(monkeypatch, tmp_path):
    from tools import visual_agent_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    captured = {}
    data_uri = "data:image/png;base64," + base64.b64encode(_ONE_PIXEL_PNG).decode("ascii")

    def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps({"success": True, "images": ["/tmp/current.png"], "videos": []})

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )

    raw = visual_agent_tool._handle_visual_agent_generate(
        {
            "prompt": "請用這張 reference 產出一張圖片",
            "attachments": [data_uri],
        }
    )
    payload = json.loads(raw)

    assert payload["success"] is True
    attachment = captured["attachments"][0]
    assert not attachment.startswith("data:image")
    assert attachment.startswith(str(tmp_path / "cache" / "visual-agent-attachments"))
    assert Path(attachment).read_bytes() == _ONE_PIXEL_PNG


def test_visual_agent_generate_binds_ref_indices_to_visible_upload_order(monkeypatch):
    from tools import visual_agent_tool

    captured = {}

    def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps({"success": True, "images": ["/tmp/current.png"], "videos": []})

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )

    raw = visual_agent_tool._handle_visual_agent_generate(
        {
            "prompt": "把 ref 1 的角色，套用 ref2 的姿勢，產出圖片即可",
            "attachments": ["/tmp/upload-first-character.png", "/tmp/upload-second-pose.png"],
        }
    )
    payload = json.loads(raw)

    assert payload["success"] is True
    assert captured["attachments"] == [
        "/tmp/upload-first-character.png",
        "/tmp/upload-second-pose.png",
    ]
    assert "first uploaded image in the user's visible attachment order" in captured["prompt"]
    binding = captured["reference_binding"]
    assert binding == {
        "mode": "ordered_references",
        "reference_order_source": "user_visible_upload_order",
        "role_policy": "derive_from_user_prompt",
        "reference_order": [
            {
                "index": 1,
                "role_hint": "character_identity",
                "attachment": "/tmp/upload-first-character.png",
            },
            {
                "index": 2,
                "role_hint": "pose_composition",
                "attachment": "/tmp/upload-second-pose.png",
            },
        ],
    }


def test_visual_agent_generate_derives_roles_from_prompt_not_ref_defaults(monkeypatch):
    from tools import visual_agent_tool

    captured = {}

    def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps({"success": True, "images": ["/tmp/current.png"], "videos": []})

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )

    raw = visual_agent_tool._handle_visual_agent_generate(
        {
            "prompt": "ref1 和 ref2 都是人物，ref3 是服裝，請融合成一張圖片",
            "attachments": [
                "/tmp/upload-first-person.png",
                "/tmp/upload-second-person.png",
                "/tmp/upload-third-clothes.png",
            ],
        }
    )
    payload = json.loads(raw)

    assert payload["success"] is True
    assert captured["attachments"] == [
        "/tmp/upload-first-person.png",
        "/tmp/upload-second-person.png",
        "/tmp/upload-third-clothes.png",
    ]
    assert "Do not assume fixed roles" in captured["prompt"]
    binding = captured["reference_binding"]
    assert binding["reference_order_source"] == "user_visible_upload_order"
    assert "character_reference" not in binding
    assert "pose_reference" not in binding
    assert "character_reference_index" not in binding
    assert "pose_reference_index" not in binding
    assert binding["reference_order"] == [
        {
            "index": 1,
            "role_hint": "character_identity",
            "attachment": "/tmp/upload-first-person.png",
        },
        {
            "index": 2,
            "role_hint": "character_identity",
            "attachment": "/tmp/upload-second-person.png",
        },
        {
            "index": 3,
            "role_hint": "wardrobe",
            "attachment": "/tmp/upload-third-clothes.png",
        },
    ]


def test_visual_agent_generate_routes_text_only_video_to_image_first(monkeypatch):
    from tools import visual_agent_tool

    captured = {}

    def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps({"success": True, "images": [], "videos": ["/tmp/current.mp4"]})

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )

    raw = visual_agent_tool._handle_visual_agent_generate(
        {"prompt": "幫我產生一段 6 秒時尚短片，主體是霧黑鋼筆"}
    )
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["visual_agent_plan"]["reason"] == "text_to_video_image_first_request"
    assert captured["include_image"] is False
    assert captured["include_video"] is True
    assert captured["candidate_budget"] == 1
    assert captured["candidate_budget_source"] == "planner_default"
    assert captured["video_budget"] == 1
    assert captured["duration"] == 6
    assert payload["images"] == []


def test_visual_agent_generate_passes_storyboard_contract_for_multishot_video(monkeypatch):
    from tools import visual_agent_tool

    captured = {}

    def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps({"success": True, "images": [], "videos": ["/tmp/current.mp4"]})

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )

    raw = visual_agent_tool._handle_visual_agent_generate(
        {"prompt": "請做一支 3 段分鏡的連貫產品影片：霧黑鋼筆放在白紙上，柔和窗光。"}
    )
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["visual_agent_plan"]["reason"] == "storyboard_video_request"
    assert captured["include_image"] is False
    assert captured["include_video"] is True
    assert captured["storyboard"]["shot_count"] == 3
    assert captured["storyboard"]["source_image_policy"] == "one_ranked_image_per_shot"
    assert payload["visual_agent_plan"]["arguments"]["storyboard"]["composition_target"] == "single_coherent_video"


def test_visual_agent_generate_accepts_friendly_draw_character_prompt(monkeypatch):
    from tools import visual_agent_tool

    captured = {}

    def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps({"success": True, "images": ["/tmp/current.png"], "videos": []})

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )

    raw = visual_agent_tool._handle_visual_agent_generate(
        {"prompt": "幫我畫一位銀髮高冷美少女角色，乾淨背景"}
    )
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["visual_agent_plan"]["reason"] == "image_request"
    assert captured["include_image"] is True
    assert captured["include_video"] is False
    assert captured["candidate_budget"] == 1
    assert captured["candidate_budget_source"] == "planner_default"


def test_visual_agent_generate_routes_grok_imagine_request_to_xai_provider(monkeypatch):
    from tools import visual_agent_tool

    captured = {}

    def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps({"success": True, "images": ["/tmp/current.png"], "videos": []})

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )

    raw = visual_agent_tool._handle_visual_agent_generate(
        {
            "prompt": "請使用 Grok Imagine 固定這位角色，產出不同姿勢的精緻圖片",
            "attachments": ["/tmp/ref.png"],
        }
    )
    payload = json.loads(raw)

    assert payload["success"] is True
    assert captured["attachments"] == ["/tmp/ref.png"]
    assert captured["image_provider"] == "xai"
    assert payload["visual_agent_plan"]["arguments"]["image_provider"] == "xai"


def test_visual_agent_generate_passes_default_xai_media_provider_contract(monkeypatch):
    from tools import visual_agent_tool

    captured = {}

    def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps({"success": True, "images": ["/tmp/current.png"], "videos": []})

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )

    raw = visual_agent_tool._handle_visual_agent_generate({"prompt": "幫我產出一張圖片"})
    payload = json.loads(raw)

    assert captured["image_provider"] == "xai"
    assert captured["image_provider_source"] == "visual_agent_default"
    assert payload["visual_agent_provider_contract"]["visual_agent_llm_provider"] == "xai-oauth"
    assert payload["visual_agent_provider_contract"]["base_llm_model"] == ""


def test_visual_agent_provider_contract_records_direct_runtime_media_overrides(
    monkeypatch,
):
    from tools import visual_agent_tool

    captured = {}

    def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps(
            {"success": True, "images": ["/tmp/current.png"], "videos": []}
        )

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )

    payload = json.loads(
        visual_agent_tool._handle_visual_agent_generate(
            {
                "prompt": "請產出一張圖片和一段影片",
                "image_provider": "runtime-image-provider",
                "image_model": "runtime-image-model",
                "video_provider": "runtime-video-provider",
                "video_model": "runtime-video-model",
            }
        )
    )

    assert captured["image_provider"] == "runtime-image-provider"
    assert captured["video_provider"] == "runtime-video-provider"
    assert payload["visual_agent_provider_contract"]["image_provider"] == (
        "runtime-image-provider"
    )
    assert payload["visual_agent_provider_contract"]["image_model"] == (
        "runtime-image-model"
    )
    assert payload["visual_agent_provider_contract"]["video_provider"] == (
        "runtime-video-provider"
    )
    assert payload["visual_agent_provider_contract"]["video_model"] == (
        "runtime-video-model"
    )


def test_visual_agent_provider_contract_records_direct_llm_overrides(monkeypatch):
    from tools import visual_agent_tool

    monkeypatch.setattr(
        visual_agent_tool,
        "apply_visual_agent_llm_planner",
        lambda args: (args, None),
    )
    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        lambda args, **_kwargs: json.dumps(
            {"success": True, "images": ["/tmp/current.png"], "videos": []}
        ),
    )

    payload = json.loads(
        visual_agent_tool._handle_visual_agent_generate(
            {
                "prompt": "請產出一張圖片",
                "visual_agent_llm_provider": "openai-codex",
                "visual_agent_llm_model": "gpt-5.5",
            }
        )
    )

    contract = payload["visual_agent_provider_contract"]
    assert contract["visual_agent_llm_provider"] == "openai-codex"
    assert contract["visual_agent_llm_model"] == "gpt-5.5"


def test_visual_agent_generate_rejects_prompt_disclosure_without_regenerating(monkeypatch):
    from tools import visual_agent_tool

    def fake_visual_package_generate(args, **kwargs):
        raise AssertionError("prompt disclosure must not dispatch visual generation")

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )

    raw = visual_agent_tool._handle_visual_agent_generate(
        {"prompt": "請給我剛剛產圖用的 prompt"}
    )
    payload = json.loads(raw)

    assert payload["error"] == "visual_agent_generate is for image/video generation, not prompt disclosure"
    assert payload["request_type"] == "visual_prompt_disclosure"

    raw = visual_agent_tool._handle_visual_agent_generate(
        {"prompt": "請給我你使用的 prompt"}
    )
    payload = json.loads(raw)

    assert payload["error"] == "visual_agent_generate is for image/video generation, not prompt disclosure"
    assert payload["request_type"] == "visual_prompt_disclosure"


def test_visual_agent_generate_rejects_feedback_only_praise_without_regenerating(monkeypatch):
    from tools import visual_agent_tool

    def fake_visual_package_generate(args, **kwargs):
        raise AssertionError("visual feedback praise must not dispatch visual generation")

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )

    raw = visual_agent_tool._handle_visual_agent_generate({"prompt": "這次的產圖品質很棒!"})
    payload = json.loads(raw)

    assert payload["error"] == "visual_agent_generate requires a visual image or video request"


def test_visual_agent_generate_rejects_prompt_only_reference_brief_without_regenerating(monkeypatch):
    from tools import visual_agent_tool

    def fake_visual_package_generate(args, **kwargs):
        raise AssertionError("prompt-only visual brief must not dispatch visual generation")

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )

    raw = visual_agent_tool._handle_visual_agent_generate(
        {
            "prompt": "固定這位角色，替換不同的服裝與構圖，高品質，8K，光影，性感一些",
            "attachments": ["/tmp/ref-1.png", "/tmp/ref-2.png"],
        }
    )
    payload = json.loads(raw)

    assert payload["error"] == "visual_agent_generate requires an explicit image or video output request"
    assert payload["request_type"] == "visual_prompt_draft_default"


def test_visual_agent_generate_rejects_suitable_xai_video_prompt_request_without_generating(monkeypatch):
    from tools import visual_agent_tool

    def fake_visual_package_generate(args, **kwargs):
        raise AssertionError("prompt builder request must not dispatch visual generation")

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )

    raw = visual_agent_tool._handle_visual_agent_generate(
        {
            "prompt": (
                "我想要用這張在 xai imagine 中產出 12s 影片，請給我合適的 prompt。"
                "稍微嬌羞，稍微性感，稍微嫵媚，稍微傲嬌，胸，整體呈現讓人有種「好婆喔！」的感覺"
            ),
            "attachments": ["/tmp/ref.png"],
        }
    )
    payload = json.loads(raw)

    assert payload["error"] == "visual_agent_generate is for image/video generation, not prompt drafting"
    assert payload["request_type"] == "visual_prompt_builder"


def test_visual_agent_schema_warns_visual_briefs_default_to_prompt_only():
    from tools.visual_agent_tool import VISUAL_AGENT_SCHEMA

    description = VISUAL_AGENT_SCHEMA["description"]

    assert "explicitly asks to generate, output, deliver, revise, or regenerate media" in description
    assert "visual brief with references but no explicit media-output request" in description
    assert "answer with a stronger prompt in text" in description


def test_visual_agent_generate_uses_grok_planner_for_direct_handoff(monkeypatch):
    from tools import visual_agent_tool

    captured = {"llm_calls": []}

    def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps({"success": True, "images": ["/tmp/current.png"], "videos": []})

    def fake_call_llm(**kwargs):
        captured["llm_calls"].append(kwargs)
        call_index = len(captured["llm_calls"])
        if call_index == 1:
            content = {
                "sections": {
                    "objective": "產出一張圖片",
                    "composition": "dynamic composition",
                }
            }
        elif call_index == 2:
            content = {
                "visual_prompt": "更大膽但保留原意的 xAI 視覺提示詞",
                "sections": {
                    "objective": "更大膽但保留原意",
                    "composition": "dynamic composition with stronger focal point",
                    "negative": "no watermark, no bad hands",
                }
            }
        else:
            content = {"visual_prompt": "更大膽但保留原意的 xAI 視覺提示詞"}
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(content)
                    )
                )
            ]
        )

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )
    monkeypatch.setattr("agent.auxiliary_client.call_llm", fake_call_llm)

    raw = visual_agent_tool._handle_visual_agent_generate(
        {
            "prompt": "請產出一張圖片",
            "visual_agent_llm_provider": "xai-oauth",
            "visual_agent_llm_model": "grok-4.3",
            "visual_agent_handoff_mode": "pre_llm_direct",
        }
    )
    payload = json.loads(raw)

    assert len(captured["llm_calls"]) == 2
    assert all(call["provider"] == "xai-oauth" for call in captured["llm_calls"])
    assert all(call["model"] == "grok-4.3" for call in captured["llm_calls"])
    assert "Pass 1" in captured["llm_calls"][0]["messages"][0]["content"]
    assert "Pass 2" in captured["llm_calls"][1]["messages"][0]["content"]
    assert captured["prompt"] == "更大膽但保留原意的 xAI 視覺提示詞"
    assert captured["visual_agent_original_prompt"] == "請產出一張圖片"
    assert payload["visual_agent_llm_plan"]["status"] == "planned"
    assert payload["visual_agent_llm_plan"]["provider"] == "xai-oauth"
    assert payload["visual_agent_llm_plan"]["refinement_rounds_completed"] == 2


def test_visual_agent_grok_planner_can_run_operator_requested_three_rounds(monkeypatch):
    from tools import visual_agent_tool

    captured = {"llm_calls": []}

    def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps({"success": True, "images": ["/tmp/current.png"], "videos": []})

    def fake_call_llm(**kwargs):
        captured["llm_calls"].append(kwargs)
        call_index = len(captured["llm_calls"])
        if call_index == 1:
            content = {"sections": {"objective": "draft", "composition": "initial"}}
        elif call_index == 2:
            content = {
                "sections": {
                    "objective": "refined",
                    "composition": "stronger silhouette",
                    "negative": "no watermark",
                }
            }
        else:
            content = {"visual_prompt": "三輪審稿後的 provider-ready prompt"}
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(content)
                    )
                )
            ]
        )

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )
    monkeypatch.setattr("agent.auxiliary_client.call_llm", fake_call_llm)

    raw = visual_agent_tool._handle_visual_agent_generate(
        {
            "prompt": "請產出一張圖片",
            "visual_agent_llm_provider": "xai-oauth",
            "visual_agent_llm_model": "grok-4.3",
            "visual_agent_handoff_mode": "pre_llm_direct",
            "visual_agent_llm_rounds": 3,
            "execution_deadline_seconds": 900,
        }
    )
    payload = json.loads(raw)

    assert len(captured["llm_calls"]) == 3
    assert "Pass 3" in captured["llm_calls"][2]["messages"][0]["content"]
    assert captured["prompt"] == "三輪審稿後的 provider-ready prompt"
    assert captured["execution_deadline_seconds"] == 900
    assert payload["visual_agent_llm_plan"]["refinement_rounds_completed"] == 3
    assert payload["visual_agent_llm_plan"]["refinement_rounds_requested"] == 3


def test_visual_agent_generate_preserves_direct_handoff_reference_operation_and_budget(
    monkeypatch,
):
    from tools import visual_agent_tool

    captured = {}

    def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps({"success": True, "images": ["/tmp/current.png"], "videos": []})

    def fail_call_llm(**kwargs):
        raise RuntimeError("planner offline")

    reference_binding = {
        "mode": "ordered_references",
        "reference_order_source": "session_visual_reference_context",
        "reference_order": [
            {
                "index": 1,
                "role_hint": "edit_anchor",
                "attachment": "/tmp/previous-selected.png",
            },
            {
                "index": 2,
                "role_hint": "visual_reference",
                "attachment": "/tmp/character.png",
            },
        ],
    }

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )
    monkeypatch.setattr("agent.auxiliary_client.call_llm", fail_call_llm)

    raw = visual_agent_tool._handle_visual_agent_generate(
        {
            "prompt": (
                "請使用 grok-web-imagine provider，可不可以再嘗試不同的構圖，"
                "可以類似原 ref 的構圖進行調整和優化"
            ),
            "attachments": ["/tmp/previous-selected.png", "/tmp/character.png"],
            "include_image": True,
            "include_video": False,
            "image_provider": "grok-web-imagine",
            "image_provider_source": "prompt_override",
            "image_operation": "continue_current",
            "candidate_budget": 1,
            "candidate_budget_source": "grok_web_current_result_operation",
            "reference_binding": reference_binding,
            "visual_agent_llm_provider": "xai-oauth",
            "visual_agent_llm_model": "grok-4.3",
            "visual_agent_handoff_mode": "pre_llm_direct",
        }
    )
    payload = json.loads(raw)

    assert payload["success"] is True
    assert captured["image_provider"] == "xai"
    assert captured["image_provider_source"] == "prompt_override"
    assert captured["image_operation"] == "continue_current"
    assert captured["candidate_budget"] == 1
    assert captured["candidate_budget_source"] == "grok_web_current_result_operation"
    assert captured["reference_binding"] == reference_binding
    assert captured["include_image"] is True
    assert captured["include_video"] is False


def test_visual_agent_grok_planner_receives_reference_images_and_roles(monkeypatch, tmp_path):
    from tools import visual_agent_tool

    ref1 = tmp_path / "ref1.png"
    ref2 = tmp_path / "ref2.png"
    ref1.write_bytes(_ONE_PIXEL_PNG)
    ref2.write_bytes(_ONE_PIXEL_PNG)
    captured = {"llm_calls": []}

    def fake_visual_package_generate(args, **kwargs):
        captured["package_args"] = dict(args)
        return json.dumps({"success": True, "images": ["/tmp/current.png"], "videos": []})

    def fake_call_llm(**kwargs):
        captured["llm_calls"].append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "visual_prompt": (
                                    "Use the character identity from ref 1: silver hair, pale face, "
                                    "white cloak and purple outfit. Apply the concrete pose from ref 2: "
                                    "low-angle seated composition, one leg raised toward the camera, "
                                    "the other leg bent back on the sofa. Do not copy ref 2 identity."
                                )
                            }
                        )
                    )
                )
            ]
        )

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )
    monkeypatch.setattr("agent.auxiliary_client.call_llm", fake_call_llm)

    raw = visual_agent_tool._handle_visual_agent_generate(
        {
            "prompt": "把 ref 1 的角色，套用 ref2 的姿勢，產出圖片即可",
            "attachments": [str(ref1), str(ref2)],
            "visual_agent_llm_provider": "xai-oauth",
            "visual_agent_llm_model": "grok-4.3",
            "visual_agent_handoff_mode": "pre_llm_direct",
        }
    )
    payload = json.loads(raw)

    assert len(captured["llm_calls"]) == 2
    content = captured["llm_calls"][0]["messages"][1]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert "ref 1: character_identity" in content[0]["text"]
    assert "ref 2: pose_composition" in content[0]["text"]
    image_parts = [part for part in content if part.get("type") == "image_url"]
    assert len(image_parts) == 2
    assert image_parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert image_parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "Do not copy ref 2 identity" in captured["package_args"]["prompt"]
    assert payload["visual_agent_llm_plan"]["image_input_count"] == 2


def test_visual_agent_grok_planner_rejects_unrequested_reference_role_mapping(
    monkeypatch, tmp_path
):
    from tools import visual_agent_tool

    ref1 = tmp_path / "ref1.png"
    ref2 = tmp_path / "ref2.png"
    ref3 = tmp_path / "ref3.png"
    ref1.write_bytes(_ONE_PIXEL_PNG)
    ref2.write_bytes(_ONE_PIXEL_PNG)
    ref3.write_bytes(_ONE_PIXEL_PNG)
    captured = {"llm_calls": []}

    def fake_visual_package_generate(args, **kwargs):
        captured["package_args"] = dict(args)
        return json.dumps({"success": True, "images": ["/tmp/current.png"], "videos": []})

    def fake_call_llm(**kwargs):
        captured["llm_calls"].append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "visual_prompt": (
                                    "objective: Generate a single best anime illustration. "
                                    "reference_mapping: img_4bfef0d4850b.webp = primary full-body identity; "
                                    "img_715da3f337a7.png = eye and facial detail lock; "
                                    "img_fa4b69a470d8.png = secondary dynamic expression and hand pose reference. "
                                    "quality_target: 8k."
                                )
                            }
                        )
                    )
                )
            ]
        )

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )
    monkeypatch.setattr("agent.auxiliary_client.call_llm", fake_call_llm)

    raw = visual_agent_tool._handle_visual_agent_generate(
        {
            "prompt": "請用 Grok Imagine + reference 固定這位角色，產出不同姿勢候選並選最佳，只交付最佳圖片，動漫圖，性感一些。",
            "attachments": [str(ref1), str(ref2), str(ref3)],
            "visual_agent_llm_provider": "xai-oauth",
            "visual_agent_llm_model": "grok-4.3",
            "visual_agent_handoff_mode": "pre_llm_direct",
        }
    )
    payload = json.loads(raw)

    assert len(captured["llm_calls"]) == 2
    planner_content = captured["llm_calls"][0]["messages"][1]["content"]
    assert isinstance(planner_content, str)
    planner_text = planner_content
    assert "unassigned collective reference set" in planner_text
    assert "do not assign fixed per-image roles" in planner_text.lower()
    assert payload["visual_agent_llm_plan"]["image_input_count"] == 0

    prompt = captured["package_args"]["prompt"]
    assert "Provider-ready visual prompt" in prompt
    assert "collective reference set" in prompt
    assert "Do not assign fixed per-image roles" in prompt
    assert captured["package_args"]["reference_conditioning_policy"] == "collective_inspiration"
    assert captured["package_args"]["reference_strategy"] == {
        "mode": "unassigned_collective_generation",
        "source": "visual_agent_planner",
        "requires_new_composition": True,
        "edit_anchor": False,
    }
    assert "reference_mapping: img_4bfef0d4850b.webp = primary full-body identity" not in prompt
    assert "img_715da3f337a7.png = eye and facial detail lock" not in prompt
    assert captured["package_args"]["visual_agent_original_prompt"].startswith("請用 Grok Imagine")
    assert payload["visual_agent_llm_plan"]["status"] == "fallback_deterministic_prompt"
    assert payload["visual_agent_llm_plan"]["reason"] == "unsupported_reference_role_mapping"


def test_visual_agent_generate_falls_back_when_grok_planner_fails(monkeypatch):
    from tools import visual_agent_tool

    captured = {}

    def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps({"success": True, "images": ["/tmp/current.png"], "videos": []})

    def fail_call_llm(**kwargs):
        raise RuntimeError("planner down")

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )
    monkeypatch.setattr("agent.auxiliary_client.call_llm", fail_call_llm)

    raw = visual_agent_tool._handle_visual_agent_generate(
        {
            "prompt": "請產出一張圖片",
            "visual_agent_llm_provider": "xai-oauth",
            "visual_agent_llm_model": "grok-4.3",
        }
    )
    payload = json.loads(raw)

    assert captured["prompt"] != "請產出一張圖片"
    assert "Provider-ready visual prompt" in captured["prompt"]
    assert "Objective: 請產出一張圖片" in captured["prompt"]
    assert "Quality target" in captured["prompt"]
    assert "Negative constraints" in captured["prompt"]
    assert captured["visual_agent_original_prompt"] == "請產出一張圖片"
    assert payload["visual_agent_llm_plan"]["status"] == "fallback_deterministic_prompt"
    assert payload["visual_agent_llm_plan"]["reason"] == "RuntimeError"
    assert payload["visual_agent_llm_plan"]["prompt_changed"] is True


def test_visual_agent_generate_rejects_implicit_anime_brief_before_grok_planner(monkeypatch):
    from tools import visual_agent_tool

    def fake_visual_package_generate(args, **kwargs):
        raise AssertionError("implicit anime prompt brief must not dispatch visual generation")

    def fake_call_llm(**kwargs):
        raise AssertionError("implicit anime prompt brief must not call Grok planner")

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )
    monkeypatch.setattr("agent.auxiliary_client.call_llm", fake_call_llm)

    raw = visual_agent_tool._handle_visual_agent_generate(
        {
            "prompt": "動漫圖，性感一些",
            "visual_agent_llm_provider": "xai-oauth",
            "visual_agent_llm_model": "grok-4.3",
        }
    )
    payload = json.loads(raw)

    assert payload["error"] == "visual_agent_generate requires a visual image or video request"


def test_visual_agent_grok_planner_rejects_feedback_like_prompt(monkeypatch):
    from tools import visual_agent_tool

    captured = {}

    def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps({"success": True, "images": ["/tmp/current.png"], "videos": []})

    def fake_call_llm(**kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps({"visual_prompt": "這次的產圖品質很棒，最新的產出可以"})
                    )
                )
            ]
        )

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )
    monkeypatch.setattr("agent.auxiliary_client.call_llm", fake_call_llm)

    raw = visual_agent_tool._handle_visual_agent_generate(
        {
            "prompt": "固定這位角色，產出不同姿勢候選並選最佳，只交付最佳圖片，動漫圖，性感一些。",
            "visual_agent_llm_provider": "xai-oauth",
            "visual_agent_llm_model": "grok-4.3",
            "visual_agent_handoff_mode": "pre_llm_direct",
        }
    )
    payload = json.loads(raw)

    assert captured["prompt"] != "這次的產圖品質很棒，最新的產出可以"
    assert "Provider-ready visual prompt" in captured["prompt"]
    assert "Objective: 固定這位角色" in captured["prompt"]
    assert captured["visual_agent_original_prompt"].startswith("固定這位角色")
    assert payload["visual_agent_llm_plan"]["status"] == "fallback_deterministic_prompt"
    assert payload["visual_agent_llm_plan"]["reason"] == "feedback_like_visual_prompt"


def test_visual_agent_grok_planner_fallback_builds_provider_ready_reference_prompt(monkeypatch, tmp_path):
    from tools import visual_agent_tool

    ref1 = tmp_path / "ref1.png"
    ref2 = tmp_path / "ref2.png"
    ref1.write_bytes(_ONE_PIXEL_PNG)
    ref2.write_bytes(_ONE_PIXEL_PNG)
    captured = {}

    def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps({"success": True, "images": ["/tmp/current.png"], "videos": []})

    def fail_call_llm(**kwargs):
        raise RuntimeError("planner down")

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )
    monkeypatch.setattr("agent.auxiliary_client.call_llm", fail_call_llm)

    raw = visual_agent_tool._handle_visual_agent_generate(
        {
            "prompt": "把 ref 1 的角色，套用 ref2 的姿勢，產出圖片即可",
            "attachments": [str(ref1), str(ref2)],
            "visual_agent_llm_provider": "xai-oauth",
            "visual_agent_llm_model": "grok-4.3",
            "reference_binding": {
                "reference_order": [
                    {"index": 1, "role_hint": "character_identity", "attachment": str(ref1)},
                    {"index": 2, "role_hint": "pose_composition", "attachment": str(ref2)},
                ]
            },
        }
    )
    payload = json.loads(raw)

    prompt = captured["prompt"]
    assert "Provider-ready visual prompt" in prompt
    assert "Reference mapping" in prompt
    assert "ref 1 = character_identity" in prompt
    assert "ref 2 = pose_composition" in prompt
    assert "Role constraints" in prompt
    assert "Do not copy identity, face, hair, wardrobe, color palette, or styling from pose refs" in prompt
    assert "Negative constraints" in prompt
    assert payload["visual_agent_llm_plan"]["status"] == "fallback_deterministic_prompt"
    assert payload["visual_agent_llm_plan"]["prompt_changed"] is True


def test_visual_agent_generate_is_registered():
    from tools.registry import discover_builtin_tools, registry

    discover_builtin_tools()

    assert "visual_agent_generate" in registry._tools
    entry = registry._tools["visual_agent_generate"]
    assert entry.is_async is False
    assert entry.toolset == "image_gen"
    assert "draw/anime/character art" in entry.schema["description"]
    assert "storyboard/multi-shot" in entry.schema["description"]


def test_visual_agent_schema_says_grok_reference_uses_tool_not_text_only():
    from tools.visual_agent_tool import VISUAL_AGENT_SCHEMA

    description = VISUAL_AGENT_SCHEMA["description"]

    assert "Grok Imagine/xAI" in description
    assert "reference images" in description
    assert "not text-to-image only" in description
