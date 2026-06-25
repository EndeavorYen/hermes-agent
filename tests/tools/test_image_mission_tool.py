from __future__ import annotations

import json

import pytest


@pytest.mark.asyncio
async def test_image_generate_mission_retries_until_qc_passes():
    from tools import image_mission_tool

    calls: list[dict[str, object]] = []

    def fake_generate_once(**kwargs):
        calls.append(dict(kwargs))
        image = "/tmp/bad.png" if len(calls) == 1 else "/tmp/good.png"
        return {
            "success": True,
            "image": image,
            "provider": "fake",
            "model": "fake-image",
        }

    def fake_deterministic_check(image_path: str, **_kwargs):
        return image_mission_tool.DeterministicQcReport(
            score=95 if image_path.endswith("good.png") else 20,
            passed=image_path.endswith("good.png"),
            fatal=not image_path.endswith("good.png"),
            issues=[] if image_path.endswith("good.png") else ["blank_or_nearly_uniform"],
            summary="ok" if image_path.endswith("good.png") else "bad image",
        )

    result = await image_mission_tool.run_image_generation_mission(
        prompt="draw a clean product photo",
        aspect_ratio="square",
        max_attempts=2,
        generate_once=fake_generate_once,
        deterministic_check=fake_deterministic_check,
    )

    assert result["success"] is True
    assert result["image"] == "/tmp/good.png"
    assert result["attempt_count"] == 2
    assert [attempt["accepted"] for attempt in result["attempts"]] == [False, True]
    assert calls[0]["attempt_index"] == 1
    assert calls[1]["attempt_index"] == 2


@pytest.mark.asyncio
async def test_image_generate_mission_applies_adaptive_mediator(monkeypatch):
    from tools import image_mission_tool

    records = []

    monkeypatch.setattr(
        image_mission_tool,
        "_read_image2_adaptive_mediator_config",
        lambda: {
            "enabled": True,
            "log_attempts": True,
            "memory_path": "/tmp/not-used.jsonl",
        },
    )
    monkeypatch.setattr(
        image_mission_tool,
        "_record_image2_mediator_attempt",
        lambda mediated, **kwargs: records.append((mediated, kwargs)),
    )

    captured: dict[str, object] = {}

    def fake_generate_once(**kwargs):
        captured.update(kwargs)
        return {"success": True, "image": "/tmp/good.png", "provider": "fake"}

    def fake_deterministic_check(_image_path: str, **_kwargs):
        return image_mission_tool.DeterministicQcReport(
            score=100,
            passed=True,
            fatal=False,
            issues=[],
            summary="ok",
        )

    result = await image_mission_tool.run_image_generation_mission(
        prompt="台北雨夜 性感美女拿黑色洋桔梗",
        max_attempts=1,
        generate_once=fake_generate_once,
        deterministic_check=fake_deterministic_check,
    )

    assert result["success"] is True
    assert "adaptive_mediator" in result
    assert "black lisianthus" in str(captured["prompt"])
    assert "性感" not in str(captured["prompt"])
    assert records
    assert records[0][1]["image2_status"] == "success"


@pytest.mark.asyncio
async def test_image_generate_mission_handler_honors_configured_attempt_cap(monkeypatch):
    from tools import image_mission_tool

    calls = []

    async def fake_run_image_generation_mission(**kwargs):
        calls.append(kwargs)
        return {"success": False, "image": None, "attempt_count": kwargs["max_attempts"]}

    monkeypatch.setattr(image_mission_tool, "_read_configured_mission_attempt_cap", lambda: 1)
    monkeypatch.setattr(image_mission_tool, "run_image_generation_mission", fake_run_image_generation_mission)

    raw = await image_mission_tool._handle_image_generate_mission(
        {
            "prompt": "draw cat",
            "max_attempts": 4,
        }
    )
    payload = json.loads(raw)

    assert payload["attempt_count"] == 1
    assert calls[0]["max_attempts"] == 1


def test_image_generate_mission_registers_image_gen_tool():
    from tools.registry import discover_builtin_tools, registry

    discover_builtin_tools()

    entry = registry.get_entry("image_generate_mission")
    assert entry is not None
    assert entry.toolset == "image_gen"
    assert entry.is_async is True
