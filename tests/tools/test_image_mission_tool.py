from __future__ import annotations

import json

import pytest
from PIL import Image


def _write_test_image(path, *, color=(255, 255, 255), accent=(255, 0, 0)):
    image = Image.new("RGB", (256, 256), color)
    for x in range(72, 184):
        for y in range(72, 184):
            image.putpixel((x, y), accent)
    image.save(path)


def _write_blank_image(path):
    Image.new("RGB", (256, 256), (255, 255, 255)).save(path)


def test_task_budget_scales_with_prompt_complexity():
    from tools.image_mission_tool import resolve_attempt_budget

    assert resolve_attempt_budget(
        "simple red circle",
        budget="task",
        reference_images=[],
    ) == 3
    assert resolve_attempt_budget(
        "photoreal portrait preserving the exact face, hands, outfit, and product logo",
        budget="task",
        reference_images=["/tmp/ref.png"],
    ) == 8


def test_visual_qc_marks_blur_and_deformity_as_fatal():
    from tools.image_mission_tool import evaluate_visual_qc

    report = evaluate_visual_qc(
        analysis=(
            "The image is visibly blurry with deformed hands, warped fingers, "
            "and obvious anatomy artifacts."
        ),
        prompt="adult portrait with natural hands",
    )

    assert report.passed is False
    assert report.fatal is True
    assert "blur" in report.issues
    assert "deformed_anatomy" in report.issues
    assert report.score < 70


def test_visual_qc_failure_to_analyze_is_fatal():
    from tools.image_mission_tool import evaluate_visual_qc

    report = evaluate_visual_qc(
        analysis="There was a problem with the request and the image could not be analyzed.",
        prompt="portrait",
    )

    assert report.passed is False
    assert report.fatal is True
    assert "qc_unavailable" in report.issues


def test_visual_qc_json_failure_to_analyze_is_fatal():
    from tools.image_mission_tool import evaluate_visual_qc

    report = evaluate_visual_qc(
        analysis=json.dumps({
            "success": False,
            "analysis": "There was a problem with the request and the image could not be analyzed.",
        }),
        prompt="portrait",
    )

    assert report.passed is False
    assert report.fatal is True
    assert "qc_unavailable" in report.issues


def test_visual_qc_treats_slight_soft_edge_as_nonfatal():
    from tools.image_mission_tool import evaluate_visual_qc

    report = evaluate_visual_qc(
        analysis=json.dumps({
            "quality_score": 85,
            "adherence_score": 72,
            "fatal_issues": [],
            "issues": [
                "Background is not pure white; it has visible gray radial banding/vignette.",
                "Circle appears slightly soft at the edge rather than perfectly crisp.",
            ],
            "summary": "Clean simple circle, but not perfectly vector-crisp.",
        }),
        prompt="single red circle centered on pure white background",
    )

    assert report.passed is True
    assert report.fatal is False
    assert "blur" not in report.issues
    assert report.score >= 70


def test_deterministic_qc_rejects_missing_and_blank_images(tmp_path):
    from tools.image_mission_tool import evaluate_deterministic_qc

    missing = evaluate_deterministic_qc(str(tmp_path / "missing.png"), aspect_ratio="square")
    assert missing.passed is False
    assert missing.fatal is True
    assert "missing_image" in missing.issues

    blank_path = tmp_path / "blank.png"
    _write_blank_image(blank_path)
    blank = evaluate_deterministic_qc(str(blank_path), aspect_ratio="square")
    assert blank.passed is False
    assert blank.fatal is True
    assert "blank_or_nearly_uniform" in blank.issues

    valid_path = tmp_path / "valid.png"
    _write_test_image(valid_path)
    valid = evaluate_deterministic_qc(str(valid_path), aspect_ratio="square")
    assert valid.passed is True
    assert valid.fatal is False
    assert valid.width == 256
    assert valid.height == 256


def test_visual_qc_flags_semantic_text_and_reference_failures_as_fatal():
    from tools.image_mission_tool import evaluate_visual_qc

    report = evaluate_visual_qc(
        analysis=json.dumps({
            "quality_score": 88,
            "adherence_score": 35,
            "fatal_issues": [
                "semantic mismatch: generated a dog instead of a handbag",
                "unreadable intended text",
                "reference image drift: identity changed",
            ],
            "issues": [],
            "summary": "The image is clean but does not match the request.",
        }),
        prompt="product photo of a handbag with readable SALE text using the reference identity",
    )

    assert report.passed is False
    assert report.fatal is True
    assert "semantic_mismatch" in report.issues
    assert "unreadable_text" in report.issues
    assert "reference_drift" in report.issues
    assert report.score < 70


@pytest.mark.asyncio
async def test_mission_skips_qc_failed_image_and_returns_best_candidate(tmp_path):
    from tools.image_mission_tool import run_image_generation_mission

    bad_path = tmp_path / "bad.png"
    good_path = tmp_path / "good.png"
    _write_test_image(bad_path)
    _write_test_image(good_path)
    generated_prompts: list[str] = []

    def fake_generate(**kwargs):
        generated_prompts.append(kwargs["prompt"])
        if len(generated_prompts) == 1:
            return json.dumps({
                "success": True,
                "image": str(bad_path),
                "provider": "openai-codex",
                "model": "gpt-image-2-medium",
                "prompt": kwargs["prompt"],
            })
        return json.dumps({
            "success": True,
            "image": str(good_path),
            "provider": "openai-codex",
            "model": "gpt-image-2-medium",
            "prompt": kwargs["prompt"],
        })

    async def fake_qc(image_path: str, prompt: str):
        if image_path.endswith("bad.png"):
            return "blurry face, deformed hands, warped fingers"
        return json.dumps({
            "quality_score": 94,
            "adherence_score": 91,
            "fatal_issues": [],
            "issues": [],
            "summary": "sharp image, coherent anatomy, clean details",
        })

    result = await run_image_generation_mission(
        prompt="adult portrait with natural hands",
        aspect_ratio="portrait",
        budget="task",
        generate_once=fake_generate,
        inspect_image=fake_qc,
    )

    assert result["success"] is True
    assert result["image"] == str(good_path)
    assert result["attempt_count"] == 2
    assert result["best"]["qc"]["score"] >= 90
    assert result["attempts"][0]["accepted"] is False
    assert result["attempts"][0]["qc"]["fatal"] is True
    assert any("sharp, anatomically coherent" in prompt for prompt in generated_prompts)


@pytest.mark.asyncio
async def test_mission_runs_deterministic_before_vision_and_retries(tmp_path):
    from tools.image_mission_tool import run_image_generation_mission

    blank_path = tmp_path / "blank.png"
    good_path = tmp_path / "good.png"
    _write_blank_image(blank_path)
    _write_test_image(good_path)
    seen_by_vision: list[str] = []

    def fake_generate(**kwargs):
        image = blank_path if kwargs["attempt_index"] == 1 else good_path
        return json.dumps({
            "success": True,
            "image": str(image),
            "provider": "openai-codex",
            "model": "gpt-image-2-medium",
            "prompt": kwargs["prompt"],
        })

    async def fake_qc(image_path: str, prompt: str):
        seen_by_vision.append(image_path)
        return json.dumps({
            "quality_score": 95,
            "adherence_score": 92,
            "fatal_issues": [],
            "issues": [],
            "summary": "sharp and matches the prompt",
        })

    result = await run_image_generation_mission(
        prompt="simple red square",
        aspect_ratio="square",
        budget="task",
        generate_once=fake_generate,
        inspect_image=fake_qc,
    )

    assert result["success"] is True
    assert result["image"] == str(good_path)
    assert seen_by_vision == [str(good_path)]
    assert result["attempts"][0]["deterministic_qc"]["fatal"] is True
    assert "blank_or_nearly_uniform" in result["attempts"][0]["deterministic_qc"]["issues"]
    assert "vision_qc" not in result["attempts"][0]
    assert result["attempts"][1]["vision_qc"]["passed"] is True


@pytest.mark.asyncio
async def test_mission_extends_task_budget_for_close_nonfatal_qc_misses(tmp_path):
    from tools.image_mission_tool import run_image_generation_mission

    image_paths = []
    for index in range(1, 5):
        path = tmp_path / f"candidate-{index}.png"
        _write_test_image(path)
        image_paths.append(path)

    def fake_generate(**kwargs):
        image = image_paths[kwargs["attempt_index"] - 1]
        return json.dumps({
            "success": True,
            "image": str(image),
            "provider": "openai-codex",
            "model": "gpt-image-2-medium",
            "prompt": kwargs["prompt"],
        })

    async def fake_qc(image_path: str, prompt: str):
        if image_path.endswith("candidate-4.png"):
            return json.dumps({
                "quality_score": 91,
                "adherence_score": 88,
                "fatal_issues": [],
                "issues": [],
                "summary": "now matches the prompt",
            })
        return json.dumps({
            "quality_score": 74,
            "adherence_score": 55,
            "fatal_issues": [],
            "issues": ["composition close but semantic details are incomplete"],
            "summary": "close but not quite aligned",
        })

    result = await run_image_generation_mission(
        prompt="simple red square",
        aspect_ratio="square",
        budget="task",
        generate_once=fake_generate,
        inspect_image=fake_qc,
    )

    assert result["success"] is True
    assert result["attempt_count"] == 4
    assert result["max_attempts"] == 4
    assert "qc-near-miss" in result["strategy"]["extensions"]


@pytest.mark.asyncio
async def test_mission_returns_qc_failed_when_all_candidates_have_fatal_issues(tmp_path):
    from tools.image_mission_tool import run_image_generation_mission

    image_paths = []
    for index in range(1, 4):
        path = tmp_path / f"{index}.png"
        _write_test_image(path)
        image_paths.append(path)

    def fake_generate(**kwargs):
        image = image_paths[kwargs["attempt_index"] - 1]
        return json.dumps({
            "success": True,
            "image": str(image),
            "provider": "openai-codex",
            "model": "gpt-image-2-medium",
            "prompt": kwargs["prompt"],
        })

    async def fake_qc(image_path: str, prompt: str):
        return "low quality, blurry, distorted anatomy, extra fingers"

    result = await run_image_generation_mission(
        prompt="portrait with detailed hands",
        aspect_ratio="portrait",
        budget="conservative",
        generate_once=fake_generate,
        inspect_image=fake_qc,
    )

    assert result["success"] is False
    assert result["image"] is None
    assert result["error_type"] == "qc_failed"
    assert result["best_candidate"]["image"].endswith(".png")
    assert all(attempt["accepted"] is False for attempt in result["attempts"])


def test_image_generate_mission_tool_is_registered():
    import tools.image_mission_tool  # noqa: F401
    from tools.registry import registry

    entry = registry.get_entry("image_generate_mission")
    assert entry is not None
    assert entry.toolset == "image_gen"
    assert entry.is_async is True
    assert "hybrid QC" in entry.schema["description"]
    assert "deterministic" in entry.schema["description"]
    assert "semantic" in entry.schema["description"]


def test_mission_requirements_need_generation_and_vision(monkeypatch):
    import tools.image_mission_tool as mission

    monkeypatch.setattr(mission, "check_image_generation_requirements", lambda: True)
    monkeypatch.setattr("tools.vision_tools.check_vision_requirements", lambda: False)
    assert mission.check_image_mission_requirements() is False

    monkeypatch.setattr("tools.vision_tools.check_vision_requirements", lambda: True)
    assert mission.check_image_mission_requirements() is True

    monkeypatch.setattr(mission, "check_image_generation_requirements", lambda: False)
    assert mission.check_image_mission_requirements() is False


def test_plain_image_generate_points_quality_sensitive_requests_to_mission_tool():
    from tools.image_generation_tool import IMAGE_GENERATE_SCHEMA

    description = IMAGE_GENERATE_SCHEMA["description"]
    assert "image_generate_mission" in description
    assert "hybrid QC" in description
    assert "semantic" in description
    assert "reference drift" in description
    assert "blur" in description
    assert "deformed" in description
