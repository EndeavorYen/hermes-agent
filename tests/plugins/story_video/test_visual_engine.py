from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from plugins.story_video.batch_executor import BatchRunSummary
from plugins.story_video.visual_engine import generate_story_video_image
from plugins.story_video.visual_judge import _run_batch_chunk


class FakeEngineClient:
    def __init__(self, artifact_path: Path) -> None:
        self.artifact_path = artifact_path
        self.payloads: list[dict] = []

    def generate(self, payload: dict) -> dict:
        self.payloads.append(payload)
        return {
            "success": True,
            "run": {"run_id": "run-story-keyframe", "status": "completed"},
            "artifact": {
                "artifact_id": "art-story-keyframe",
                "local_path": str(self.artifact_path),
                "provider": "openai-codex",
                "model": "gpt-image-2-medium",
            },
        }


def test_story_video_generation_uses_engine_contract_and_ordered_references(
    tmp_path: Path,
) -> None:
    output = tmp_path / "selected.png"
    output.write_bytes(b"image")
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    style = tmp_path / "style.png"
    style.write_bytes(b"style")
    client = FakeEngineClient(output)
    args = {
        "prompt": "A precise cinematic fossil close-up",
        "aspect_ratio": "16:9",
        "provider": "openai-codex",
        "image_url": str(source),
        "reference_image_urls": [str(style)],
    }

    first = generate_story_video_image(
        args,
        task_id="story-video-run-1-S00_SH01",
        client=client,
    )
    second = generate_story_video_image(
        args,
        task_id="story-video-run-1-S00_SH01",
        client=client,
    )

    assert first == second
    assert first == {
        "success": True,
        "image": str(output),
        "provider": "openai-codex",
        "model": "gpt-image-2-medium",
        "response_id": "run-story-keyframe",
        "artifact_id": "art-story-keyframe",
    }
    assert client.payloads[0] == client.payloads[1]
    payload = client.payloads[0]
    assert payload["provider"] == "openai-codex"
    assert payload["candidate_count"] == 1
    assert payload["aspect_ratio"] == "16:9"
    assert payload["max_repairs"] == 1
    assert payload["references"] == [
        {
            "index": 1,
            "artifact_id": "story-video-reference:1",
            "role": "primary_edit",
            "source_path": str(source),
        },
        {
            "index": 2,
            "artifact_id": "story-video-reference:2",
            "role": "style",
            "source_path": str(style),
        },
    ]


def test_story_video_generation_idempotency_changes_with_effective_prompt(
    tmp_path: Path,
) -> None:
    output = tmp_path / "selected.png"
    output.write_bytes(b"image")
    client = FakeEngineClient(output)

    generate_story_video_image(
        {"prompt": "initial composition", "aspect_ratio": "16:9"},
        task_id="story-video-run-1-S00_SH01",
        client=client,
    )
    generate_story_video_image(
        {"prompt": "reframed composition", "aspect_ratio": "16:9"},
        task_id="story-video-run-1-S00_SH01",
        client=client,
    )

    assert client.payloads[0]["idempotency_key"] != client.payloads[1]["idempotency_key"]


def test_story_video_generation_fails_closed_on_missing_engine_artifact(
    tmp_path: Path,
) -> None:
    client = FakeEngineClient(tmp_path / "missing.png")

    result = generate_story_video_image(
        {"prompt": "a shot"},
        task_id="story-video-run-1-S00_SH01",
        client=client,
    )

    assert result["success"] is False
    assert result["error_type"] == "visual_engine_artifact_missing"


def test_story_video_batch_runtime_injects_visual_engine_generator(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "scene_ledger.json").write_text(
        '{"scenes":[{"shots":[{"shot_id":"S00_SH01"}]}]}',
        encoding="utf-8",
    )
    captured: dict = {}

    class FakeExecutor:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

        def run_chunk(self, _context, *, cancel_check):
            return BatchRunSummary(work_status="complete", wave="initial")

    monkeypatch.setattr(
        "plugins.story_video.batch_executor.StoryVideoBatchExecutor",
        FakeExecutor,
    )

    result = _run_batch_chunk(
        SimpleNamespace(project_dir=project, run_id="run-1", auto_mode=False),
        state_store=object(),
        llm=None,
    )

    assert result["success"] is True
    assert captured["image_generator"] is generate_story_video_image
