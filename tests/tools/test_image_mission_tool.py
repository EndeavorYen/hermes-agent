from __future__ import annotations

import json

import pytest


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


@pytest.mark.asyncio
async def test_mission_skips_qc_failed_image_and_returns_best_candidate():
    from tools.image_mission_tool import run_image_generation_mission

    generated_prompts: list[str] = []

    def fake_generate(**kwargs):
        generated_prompts.append(kwargs["prompt"])
        if len(generated_prompts) == 1:
            return json.dumps({
                "success": True,
                "image": "/tmp/bad.png",
                "provider": "openai-codex",
                "model": "gpt-image-2-medium",
                "prompt": kwargs["prompt"],
            })
        return json.dumps({
            "success": True,
            "image": "/tmp/good.png",
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
    assert result["image"] == "/tmp/good.png"
    assert result["attempt_count"] == 2
    assert result["best"]["qc"]["score"] >= 90
    assert result["attempts"][0]["accepted"] is False
    assert result["attempts"][0]["qc"]["fatal"] is True
    assert any("sharp, anatomically coherent" in prompt for prompt in generated_prompts)


@pytest.mark.asyncio
async def test_mission_returns_qc_failed_when_all_candidates_have_fatal_issues():
    from tools.image_mission_tool import run_image_generation_mission

    def fake_generate(**kwargs):
        return json.dumps({
            "success": True,
            "image": f"/tmp/{kwargs['attempt_index']}.png",
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
    assert "visual QC" in entry.schema["description"]


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
    assert "blur" in description
    assert "deformed" in description
