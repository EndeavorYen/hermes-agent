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


def test_task_budget_expands_for_prompt_complexity_but_stays_bounded():
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
    ) == 4


def test_configured_mission_attempt_cap_is_read(monkeypatch):
    import tools.image_mission_tool as mission

    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {"image_gen": {"mission": {"max_attempts": 4}}},
    )

    assert mission._read_configured_mission_attempt_cap() == 4


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


def test_visual_qc_low_adherence_fails_even_when_quality_is_high():
    from tools.image_mission_tool import evaluate_visual_qc

    report = evaluate_visual_qc(
        analysis=json.dumps({
            "quality_score": 98,
            "adherence_score": 45,
            "fatal_issues": [],
            "issues": [],
            "summary": "Beautiful image, but it is a generic portrait instead of the requested product.",
        }),
        prompt="matte black fountain pen on white paper",
    )

    assert report.passed is False
    assert report.fatal is True
    assert "semantic_mismatch" in report.issues
    assert report.score < 70


def test_image2_prompt_composer_rewrites_sensitive_beach_fashion_prompt():
    from tools.image_mission_tool import compose_image2_prompt

    composed = compose_image2_prompt("性感美女海邊寫真", attempt_index=1)

    assert "adult fashion model" in composed
    assert "non-explicit" in composed
    assert "editorial" in composed
    assert "性感" not in composed
    assert "美女" not in composed


def test_image2_prompt_composer_includes_structured_sections():
    from tools.image_mission_tool import compose_image2_prompt

    composed = compose_image2_prompt("polished product photo of a watch", attempt_index=2)

    assert "Subject:" in composed
    assert "Setting:" in composed
    assert "Composition:" in composed
    assert "Lighting:" in composed
    assert "Material and detail:" in composed
    assert "Constraints:" in composed


def test_image2_prompt_composer_preserves_user_intent_anchors_on_retry():
    from tools.image_mission_tool import compose_image2_prompt

    composed = compose_image2_prompt(
        "matte black fountain pen on white paper, soft window light, no text, no people",
        attempt_index=2,
        previous_failure="semantic_mismatch, composition close but subject changed",
    )

    assert "User intent anchors:" in composed
    assert "matte black fountain pen" in composed
    assert "white paper" in composed
    assert "soft window light" in composed
    assert "Do not replace the requested subject" in composed
    assert "Correction scope:" in composed
    assert "Fix only the listed issue" in composed


@pytest.mark.asyncio
async def test_mission_applies_adaptive_mediator_before_attempt_prompt(tmp_path, monkeypatch):
    import tools.image_mission_tool as mission
    from tools.image2_adaptive_mediator import MediatedImagePrompt, Image2Intent

    image_path = tmp_path / "good.png"
    _write_test_image(image_path)
    generated_prompts: list[str] = []

    mediated = MediatedImagePrompt(
        user_concept="rough concept",
        final_prompt="mediated mission concept",
        intent=Image2Intent(subject="rough concept"),
        strategy="hybrid_refine",
        draft_model="test-image-prompt-draft-model",
        draft_prompt="qwen draft",
    )

    monkeypatch.setattr(
        mission,
        "_read_image2_adaptive_mediator_config",
        lambda: {"enabled": True, "memory_path": ""},
    )
    monkeypatch.setattr(
        mission,
        "_read_image_prompt_preprocessor_config",
        lambda: {"enabled": True, "model": "test-image-prompt-draft-model"},
    )
    monkeypatch.setattr(
        mission,
        "_mediate_image2_prompt",
        lambda prompt, **kwargs: mediated,
    )
    monkeypatch.setattr(
        mission,
        "_record_image2_mediator_attempt",
        lambda *args, **kwargs: None,
    )

    def fake_generate(**kwargs):
        generated_prompts.append(kwargs["prompt"])
        return json.dumps({
            "success": True,
            "image": str(image_path),
            "provider": "openai-codex",
            "model": "gpt-image-2-medium",
            "prompt": kwargs["prompt"],
        })

    async def fake_qc(image_path: str, prompt: str):
        return json.dumps({
            "quality_score": 94,
            "adherence_score": 91,
            "fatal_issues": [],
            "issues": [],
            "summary": "sharp image, coherent anatomy, clean details",
        })

    result = await mission.run_image_generation_mission(
        prompt="rough concept",
        aspect_ratio="portrait",
        budget="task",
        generate_once=fake_generate,
        inspect_image=fake_qc,
    )

    assert result["success"] is True
    assert "mediated mission concept" in generated_prompts[0]
    assert result["adaptive_mediator"]["strategy"] == "hybrid_refine"


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
async def test_mission_attempt_cap_limits_auto_budget(tmp_path):
    from tools.image_mission_tool import run_image_generation_mission

    image_paths = []
    for index in range(1, 3):
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
        prompt="photoreal portrait preserving the exact face, hands, outfit, and product logo",
        aspect_ratio="portrait",
        budget="task",
        reference_images=["/tmp/ref.png"],
        max_attempts=2,
        generate_once=fake_generate,
        inspect_image=fake_qc,
    )

    assert result["success"] is False
    assert result["error_type"] == "qc_failed"
    assert result["attempt_count"] == 2
    assert result["max_attempts"] == 2
    assert result["strategy"]["base_attempts"] == 4
    assert result["strategy"]["attempt_cap"] == 2
    assert result["strategy"]["configured_attempt_cap"] == 2


@pytest.mark.asyncio
async def test_mission_rewrites_policy_refusal_before_retry(tmp_path):
    from tools.image_mission_tool import run_image_generation_mission

    image_path = tmp_path / "safe.png"
    _write_test_image(image_path)
    prompts: list[str] = []

    def fake_generate(**kwargs):
        prompts.append(kwargs["prompt"])
        if len(prompts) == 1:
            return json.dumps({
                "success": False,
                "error": "blocked by safety policy",
                "error_type": "policy_refusal",
                "rewrite_prompt": True,
                "retryable": False,
            })
        return json.dumps({
            "success": True,
            "image": str(image_path),
            "provider": "openai-codex",
            "model": "gpt-image-2-medium",
            "prompt": kwargs["prompt"],
        })

    async def fake_qc(image_path: str, prompt: str):
        return json.dumps({
            "quality_score": 94,
            "adherence_score": 90,
            "fatal_issues": [],
            "issues": [],
            "summary": "clean editorial image",
        })

    result = await run_image_generation_mission(
        prompt="性感美女海邊寫真",
        aspect_ratio="portrait",
        budget="task",
        generate_once=fake_generate,
        inspect_image=fake_qc,
    )

    assert result["success"] is True
    assert len(prompts) == 2
    assert "adult fashion model" in prompts[1]
    assert "policy_refusal" in prompts[1]
    assert "blocked by safety policy" not in prompts[1]
    assert "性感" not in prompts[1]


@pytest.mark.asyncio
async def test_mission_empty_response_recovery_simplifies_without_generic_fallback(tmp_path):
    from tools.image_mission_tool import run_image_generation_mission

    image_path = tmp_path / "good.png"
    _write_test_image(image_path)
    prompts: list[str] = []

    def fake_generate(**kwargs):
        prompts.append(kwargs["prompt"])
        if kwargs["attempt_index"] == 1:
            return json.dumps({
                "success": False,
                "image": None,
                "error": "Codex response contained no image_generation_call result",
                "error_type": "empty_response",
                "provider": "openai-codex",
                "model": "gpt-image-2-high",
            })
        return json.dumps({
            "success": True,
            "image": str(image_path),
            "provider": "openai-codex",
            "model": "gpt-image-2-high",
            "prompt": kwargs["prompt"],
        })

    async def fake_qc(image_path: str, prompt: str):
        return json.dumps({
            "quality_score": 95,
            "adherence_score": 92,
            "fatal_issues": [],
            "issues": [],
            "summary": "sharp and matches the prompt",
        })

    result = await run_image_generation_mission(
        prompt="matte black fountain pen on white paper, soft window light, no text",
        aspect_ratio="square",
        budget="task",
        generate_once=fake_generate,
        inspect_image=fake_qc,
    )

    assert result["success"] is True
    assert result["attempts"][0]["recovery"] == {
        "state": "empty_response",
        "action": "simplify_prompt",
        "fallback_allowed": False,
        "preserve_intent": True,
    }
    assert result["strategy"]["fallback_policy"] == "preserve_intent_no_generic_fallback"
    assert "Recovery action: simplify_prompt" in prompts[1]
    assert "matte black fountain pen" in prompts[1]
    assert "Do not switch to a generic safer subject" in prompts[1]


@pytest.mark.asyncio
async def test_mission_qc_failure_recovery_repairs_semantic_mismatch_and_learns(tmp_path):
    from tools.image_mission_tool import run_image_generation_mission

    bad_path = tmp_path / "bad.png"
    good_path = tmp_path / "good.png"
    _write_test_image(bad_path)
    _write_test_image(good_path)
    prompts: list[str] = []

    def fake_generate(**kwargs):
        prompts.append(kwargs["prompt"])
        image = bad_path if kwargs["attempt_index"] == 1 else good_path
        return json.dumps({
            "success": True,
            "image": str(image),
            "provider": "openai-codex",
            "model": "gpt-image-2-high",
            "prompt": kwargs["prompt"],
        })

    async def fake_qc(image_path: str, prompt: str):
        if image_path.endswith("bad.png"):
            return json.dumps({
                "quality_score": 96,
                "adherence_score": 35,
                "fatal_issues": ["semantic mismatch: generated a generic portrait instead of a fountain pen"],
                "issues": [],
                "summary": "Beautiful image, but wrong subject.",
            })
        return json.dumps({
            "quality_score": 94,
            "adherence_score": 91,
            "fatal_issues": [],
            "issues": [],
            "summary": "sharp product image matching the prompt",
        })

    result = await run_image_generation_mission(
        prompt="matte black fountain pen on white paper, soft window light, no text",
        aspect_ratio="square",
        budget="task",
        generate_once=fake_generate,
        inspect_image=fake_qc,
    )

    assert result["success"] is True
    recovery = result["attempts"][0]["recovery"]
    assert recovery["state"] == "qc_failed"
    assert recovery["action"] == "repair_prompt"
    assert recovery["fallback_allowed"] is False
    assert "semantic_mismatch" in recovery["issues"]
    assert "Restore the requested subject" in recovery["prompt_correction"]
    assert "Recovery action: repair_prompt" in prompts[1]
    assert "semantic_mismatch" in prompts[1]
    assert "matte black fountain pen" in prompts[1]
    assert result["learning_corrections"] == [recovery["prompt_correction"]]


@pytest.mark.asyncio
async def test_mission_reports_activity_during_generation_and_qc(tmp_path, monkeypatch):
    import tools.image_mission_tool as mission

    image_path = tmp_path / "good.png"
    _write_test_image(image_path)
    events: list[str] = []
    monkeypatch.setattr(
        mission,
        "touch_activity_if_due",
        lambda state, label: events.append(label),
    )

    def fake_generate(**kwargs):
        return json.dumps({
            "success": True,
            "image": str(image_path),
            "provider": "openai-codex",
            "model": "gpt-image-2-medium",
            "prompt": kwargs["prompt"],
        })

    async def fake_qc(image_path: str, prompt: str):
        return json.dumps({
            "quality_score": 95,
            "adherence_score": 92,
            "fatal_issues": [],
            "issues": [],
            "summary": "sharp and matches the prompt",
        })

    result = await mission.run_image_generation_mission(
        prompt="simple red square",
        aspect_ratio="square",
        budget="task",
        generate_once=fake_generate,
        inspect_image=fake_qc,
    )

    assert result["success"] is True
    assert "image mission attempt 1/3: generating" in events
    assert "image mission attempt 1/3: generation complete" in events
    assert "image mission attempt 1/3: vision QC" in events


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
async def test_task_mission_does_not_extend_close_nonfatal_qc_misses(tmp_path):
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

    assert result["success"] is False
    assert result["error_type"] == "qc_failed"
    assert result["attempt_count"] == 3
    assert result["max_attempts"] == 3
    assert result["best_candidate"]["qc"]["score"] == 66
    assert "qc-near-miss" not in result["strategy"]["extensions"]


@pytest.mark.asyncio
async def test_aggressive_mission_allows_four_attempts_for_best_of(tmp_path):
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
            "model": "gpt-image-2-high",
            "prompt": kwargs["prompt"],
        })

    async def fake_qc(image_path: str, prompt: str):
        if image_path.endswith("candidate-4.png"):
            return json.dumps({
                "quality_score": 93,
                "adherence_score": 90,
                "fatal_issues": [],
                "issues": [],
                "summary": "best candidate",
            })
        return json.dumps({
            "quality_score": 72,
            "adherence_score": 60,
            "fatal_issues": [],
            "issues": ["near miss"],
            "summary": "close but not enough",
        })

    result = await run_image_generation_mission(
        prompt="photorealistic portrait with hands and exact styling",
        aspect_ratio="portrait",
        budget="aggressive",
        generate_once=fake_generate,
        inspect_image=fake_qc,
    )

    assert result["success"] is True
    assert result["attempt_count"] == 4
    assert result["max_attempts"] == 4


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
    assert "recovery state machine" in entry.schema["description"]
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
