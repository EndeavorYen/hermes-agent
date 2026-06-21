import json
from types import SimpleNamespace

import pytest


_ONE_PIXEL_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00"
    b"\x90wS\xde"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.mark.asyncio
async def test_visual_package_generate_returns_selected_image_and_video(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "image.png"
    video = tmp_path / "video.mp4"
    image.write_bytes(_ONE_PIXEL_PNG)
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")

    monkeypatch.setattr(
        visual_package_tool,
        "generate_image",
        lambda **kwargs: {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image-fixture",
        },
    )
    monkeypatch.setattr(
        visual_package_tool,
        "generate_video",
        lambda **kwargs: {
            "success": True,
            "video": str(video),
            "provider": "fixture",
            "model": "video-fixture",
        },
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {"prompt": "請產出一張圖片和一段影片：霧黑鋼筆，柔和窗光。"}
        )
    )

    assert payload["success"] is True
    assert payload["images"] == [str(image)]
    assert payload["videos"] == [str(video)]
    assert payload["package_status"] == "success"
    assert payload["delivery_metadata"]["selected_visual_artifact_ids"]


@pytest.mark.asyncio
async def test_visual_package_generate_uses_selected_image_for_video(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "image.png"
    video = tmp_path / "video.mp4"
    image.write_bytes(_ONE_PIXEL_PNG)
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    video_calls = []

    monkeypatch.setattr(
        visual_package_tool,
        "generate_image",
        lambda **kwargs: {"success": True, "image": str(image), "provider": "fixture", "model": "image-fixture"},
    )

    def fake_generate_video(**kwargs):
        video_calls.append(kwargs)
        return {"success": True, "video": str(video), "provider": "fixture", "model": "video-fixture"}

    monkeypatch.setattr(visual_package_tool, "generate_video", fake_generate_video)

    await visual_package_tool._handle_visual_package_generate(
        {"prompt": "image plus short video of a matte black pen"}
    )

    assert video_calls[0]["image_url"] == str(image)


@pytest.mark.asyncio
async def test_visual_package_video_aspect_follows_selected_source_image(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "portrait.png"
    video = tmp_path / "video.mp4"
    image.write_bytes(_ONE_PIXEL_PNG)
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    video_calls = []

    def fake_probe_media_reference(ref):
        return SimpleNamespace(
            sha256=f"hash:{ref}",
            is_stable=True,
            freshness_status="fresh",
            local_path=str(ref) if str(ref).startswith("/") else None,
            mime_type="image/png" if str(ref).endswith(".png") else "video/mp4",
            bytes=10,
            width=720 if str(ref).endswith(".png") else 0,
            height=1280 if str(ref).endswith(".png") else 0,
        )

    monkeypatch.setattr(visual_package_tool, "probe_media_reference", fake_probe_media_reference)
    monkeypatch.setattr(
        visual_package_tool,
        "generate_image",
        lambda **kwargs: {"success": True, "image": str(image), "provider": "fixture", "model": "image-fixture"},
    )

    def fake_generate_video(**kwargs):
        video_calls.append(kwargs)
        return {"success": True, "video": str(video), "provider": "fixture", "model": "video-fixture"}

    monkeypatch.setattr(visual_package_tool, "generate_video", fake_generate_video)

    await visual_package_tool._handle_visual_package_generate(
        {"prompt": "image plus video", "aspect_ratio": "16:9"}
    )

    assert video_calls[0]["aspect_ratio"] == "9:16"


@pytest.mark.asyncio
async def test_visual_package_generate_selects_successful_remote_video_url(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "image.png"
    image.write_bytes(_ONE_PIXEL_PNG)

    monkeypatch.setattr(
        visual_package_tool,
        "generate_image",
        lambda **kwargs: {"success": True, "image": str(image), "provider": "fixture", "model": "image-fixture"},
    )
    monkeypatch.setattr(
        visual_package_tool,
        "generate_video",
        lambda **kwargs: {
            "success": True,
            "video": "https://vidgen.x.ai/xai-vidgen-bucket/current.mp4",
            "provider": "fixture",
            "model": "video-fixture",
        },
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {"prompt": "請產出一張圖片和一段影片：霧黑鋼筆。"}
        )
    )

    assert payload["success"] is True
    assert payload["videos"] == ["https://vidgen.x.ai/xai-vidgen-bucket/current.mp4"]
    assert len(payload["delivery_metadata"]["selected_visual_artifact_ids"]) == 2


@pytest.mark.asyncio
async def test_visual_package_generates_multiple_image_candidates_and_posts_only_winner(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    paths = []
    for index in range(2):
        path = tmp_path / f"image-{index}.png"
        path.write_bytes(_ONE_PIXEL_PNG)
        paths.append(path)
    calls = []

    def fake_generate_image(**kwargs):
        calls.append(kwargs)
        return {
            "success": True,
            "image": str(paths[len(calls) - 1]),
            "provider": "fixture",
            "model": "image",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(
        visual_package_tool,
        "generate_video",
        lambda **kwargs: {"success": False, "error": "not requested", "provider": "fixture", "model": "video"},
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {"prompt": "請產出一張圖片：霧黑鋼筆。", "candidate_budget": 2, "include_video": False}
        )
    )

    assert len(calls) == 2
    assert len(payload["images"]) == 1
    assert len(
        {
            entry["artifact_id"]
            for entry in payload["delivery_metadata"]["visual_artifacts"].values()
        }
    ) == 2
    assert len(payload["delivery_metadata"]["selected_visual_artifact_ids"]) == 1


@pytest.mark.asyncio
async def test_visual_package_records_shadow_learning_but_keeps_delivery_selected_only(monkeypatch, tmp_path):
    from agent.visual.tracking import default_visual_ledger_path
    from agent.visual.self_validation import run_visual_self_validation
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "image.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    monkeypatch.setattr(
        visual_package_tool,
        "generate_image",
        lambda **kwargs: {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image",
        },
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {"prompt": "請產出一張圖片：霧黑鋼筆。", "include_video": False}
        )
    )

    assert payload["success"] is True
    assert payload["rankings"]["image"]["decision"] in {"post", "ask_user"}
    assert payload["delivery_metadata"]["selected_visual_artifact_ids"]
    assert payload["learning"]["mode"] == "shadow"
    validation = run_visual_self_validation(
        default_visual_ledger_path(),
        request_id=payload["visual_request_id"],
    )
    assert validation["success"] is True


@pytest.mark.asyncio
async def test_visual_package_reads_controlled_strategy_without_prompt_mutation(monkeypatch, tmp_path):
    from agent.visual.intent_signature import build_intent_signature
    from agent.visual.strategy_activation import record_strategy_activation
    from agent.visual.tracking import default_visual_ledger_path
    from scripts.visual_strategy_activation_report import build_strategy_activation_report
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "image.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    prompt = "請產出一張圖片：霧黑鋼筆。"
    intent_signature = build_intent_signature(
        {
            "kind": "visual_package",
            "wants_image": True,
            "wants_video": False,
            "aspect_ratio": "16:9",
            "modality": "package",
            "operation": "visual_package_generate",
        }
    )
    ledger = visual_package_tool.VisualAttemptLedger(default_visual_ledger_path())
    ledger.initialize()
    activation_id = record_strategy_activation(
        ledger,
        shadow_update_id="vsh_demo",
        intent_signature=intent_signature,
        strategy_signature="vstrat_controlled_demo",
        activation_status="controlled",
        promotion_decision={
            "decision": "promote_controlled",
            "allowed": True,
            "confidence": 0.88,
        },
        metadata={"atom_signatures": ["composition.full_subject_visible@v1"]},
    )
    image_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        return {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {"prompt": prompt, "include_video": False, "candidate_budget": 1}
        )
    )

    assert payload["success"] is True
    assert payload["learning"]["mode"] == "controlled_read_only"
    assert payload["learning"]["strategy_plan"]["activation_status"] == "controlled"
    assert payload["learning"]["strategy_plan"]["activation_id"] == activation_id
    assert payload["learning"]["strategy_plan"]["prompt_mutation_allowed"] is False
    assert image_calls[0]["prompt"] == prompt
    report = build_strategy_activation_report(default_visual_ledger_path())
    assert report["strategy_activations"]["read_count"] == 1
    assert report["strategy_activations"]["prompt_mutation_read_count"] == 0


@pytest.mark.asyncio
async def test_visual_package_records_quality_judgment_for_candidates(monkeypatch, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "image.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    monkeypatch.setattr(
        visual_package_tool,
        "generate_image",
        lambda **kwargs: {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image",
        },
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {"prompt": "請產出一張圖片：霧黑鋼筆。", "include_video": False, "candidate_budget": 1}
        )
    )

    ledger = VisualAttemptLedger(default_visual_ledger_path())
    rankings = _list_rows(ledger, "visual_rankings")
    quality_judgments = [
        row
        for row in _list_rows(ledger, "visual_judgments")
        if row["judge_name"] == "visual_quality_judge"
    ]
    assert quality_judgments
    assert quality_judgments[0]["metadata"]["intent_signature"].startswith("visig_")
    assert quality_judgments[0]["metadata"]["strategy_signature"].startswith("vstrat_")
    assert quality_judgments[0]["metadata"]["modality"] == "image"
    assert "judge_sources" in quality_judgments[0]["metadata"]
    assert rankings[0]["scores"]["reward"]["dimensions"]["aesthetic_fit"] != 0.5


@pytest.mark.asyncio
async def test_visual_package_retries_empty_image_response_before_ranking(monkeypatch, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "retry-image.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    calls = []

    def fake_generate_image(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return {
                "success": False,
                "error": "empty_response",
                "provider": "fixture",
                "model": "image",
            }
        return {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {"prompt": "請產出一張圖片：霧黑鋼筆。", "include_video": False, "candidate_budget": 1}
        )
    )

    assert len(calls) == 2
    assert payload["success"] is True
    assert payload["images"] == [str(image)]
    assert payload["generation_payloads"]["image"][0]["failure"]["failure_class"] == "empty_response"
    assert payload["generation_payloads"]["image"][0]["recovery"]["decision"] == "retry"
    assert payload["generation_payloads"]["image"][1]["retry_of"] == 0
    attempts = VisualAttemptLedger(default_visual_ledger_path())._list("visual_attempts")
    assert attempts[0]["metadata"]["failure"]["failure_class"] == "empty_response"
    assert attempts[1]["metadata"]["retry_of"] == 0


def _list_rows(ledger, table):
    return ledger._list(table)
