from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from plugins import story_video
from plugins.story_video.state import StoryVideoStateStore, parse_operator_call
from plugins.story_video.visual_judge import (
    configure_plugin_llm,
    story_video_quality_control,
)


def _context(tmp_path):
    store = StoryVideoStateStore(tmp_path)
    call = parse_operator_call("故事影片：恐龍起源｜30秒｜真實照片")
    assert call is not None
    context = store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=call,
        original_request="start",
    )
    shot = {
        "shot_id": "S00_SH00",
        "narration_text": "直立腿讓早期恐龍移動得更有效率。",
        "narrative_role": "mechanism",
        "viewer_takeaway": "直立腿提高移動效率",
        "subject": "小型早期恐龍的後肢",
        "action": "腳掌落在乾裂泥地並帶起細小塵土",
        "evidence_detail": "腿位於身體正下方，足跡與關節清楚可辨",
        "shot_scale": "close_up",
        "camera_angle": "low side angle",
        "focal_point": "hind limb and foot contact",
        "subtitle_safe_area": "bottom 20 percent clear",
        "acceptance_criteria": ["upright posture is immediately readable"],
        "risk_class": "high",
    }
    ledger = {
        "schema": "story_video_scene_ledger_v2",
        "production_type": "science_explainer",
        "target_duration_sec": 30,
        "visual_style": "photoreal professional science documentary",
        "scenes": [
            {
                "scene_id": "S00",
                "setting": "dry Late Triassic woodland",
                "shots": [shot],
            }
        ],
    }
    (context.project_dir / "scene_ledger.json").write_text(
        json.dumps(ledger), encoding="utf-8"
    )
    return store, context, shot


def _candidate(context, candidate_id: str, provider: str = "openai-codex") -> dict:
    path = context.project_dir / "images_candidates" / "S00_SH00" / f"{candidate_id}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(f"image-{candidate_id}".encode())
    return {
        "candidate_id": candidate_id,
        "path": str(path),
        "provider": provider,
        "model": "gpt-image-2-high",
        "response_id": f"img_{candidate_id}",
    }


def _dimensions(score: int) -> dict:
    return {
        "text_alignment": score,
        "focal_clarity": score,
        "evidence_specificity": score,
        "professional_quality": score,
        "scientific_credibility": score,
        "continuity_and_diversity": score,
    }


class FakeLlm:
    def __init__(self, rows: list[dict], *, provider: str = "openai-codex") -> None:
        self.rows = rows
        self.provider = provider
        self.calls = []

    def complete_structured(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            parsed={"candidates": self.rows},
            provider=self.provider,
            model="gpt-5.6-terra",
            audit={"response_id": "resp_story_video_judge"},
            usage=SimpleNamespace(total_tokens=321),
        )


def test_plugin_registers_internal_quality_tool_and_binds_host_llm() -> None:
    registered_tools = {}

    class FakeContext:
        llm = FakeLlm([])

        def register_tool(self, *, name, toolset, schema, handler):
            registered_tools[name] = {
                "toolset": toolset,
                "schema": schema,
                "handler": handler,
            }

        def register_hook(self, _name, _callback):
            return None

    story_video.register(FakeContext())

    assert set(registered_tools) == {
        "story_video_control",
        "story_video_quality_control",
    }
    assert registered_tools["story_video_quality_control"]["toolset"] == "story_video"
    assert registered_tools["story_video_quality_control"]["schema"]["name"] == "story_video_quality_control"


def test_compile_prompt_writes_traceable_prompt_and_budget(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)

    payload = json.loads(
        story_video_quality_control(
            {"action": "compile_prompt", "shot_id": "S00_SH00"},
            session_id="session-1",
            store=store,
        )
    )

    assert payload["success"] is True
    assert payload["candidate_budget"] == 3
    assert "Evidence that must be readable" in payload["prompt"]
    assert (context.project_dir / payload["prompt_path"]).is_file()


def test_judge_sends_every_candidate_as_image_input_to_openai_and_selects_best(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    candidates = [_candidate(context, "C01"), _candidate(context, "C02")]
    llm = FakeLlm(
        [
            {
                "candidate_id": "C01",
                "hard_blockers": [],
                "dimensions": _dimensions(83),
                "evidence": ["clear foot contact"],
            },
            {
                "candidate_id": "C02",
                "hard_blockers": [],
                "dimensions": _dimensions(91),
                "evidence": ["upright limb and track are immediately readable"],
            },
        ]
    )
    configure_plugin_llm(llm)

    payload = json.loads(
        story_video_quality_control(
            {
                "action": "judge_candidates",
                "shot_id": "S00_SH00",
                "candidates": candidates,
                "repair_round": 1,
            },
            session_id="session-1",
            store=store,
        )
    )

    assert payload["success"] is True
    assert payload["status"] == "selected"
    assert payload["selected_candidate_id"] == "C02"
    assert llm.calls[0]["provider"] == "openai-codex"
    image_inputs = [item for item in llm.calls[0]["input"] if item["type"] == "image"]
    assert len(image_inputs) == 2
    selected = context.project_dir / "images" / "S00_SH00.png"
    assert selected.read_bytes() == b"image-C02"
    manifest = json.loads(
        (context.project_dir / "manifests" / "shot_candidate_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    current = [row for row in manifest["outputs"] if row["selected"]]
    assert len(current) == 1
    assert current[0]["candidate_id"] == "C02"
    assert current[0]["quality_score"] == 91
    assert current[0]["judge_provider"] == "openai-codex"
    assert current[0]["vision_evidence"]["response_id"] == "resp_story_video_judge"
    assert not (context.project_dir / "manifests" / "shot_candidate_manifest.json.tmp").exists()


def test_judge_blocks_below_threshold_without_promoting_least_bad_candidate(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    llm = FakeLlm(
        [
            {
                "candidate_id": "C01",
                "hard_blockers": [],
                "dimensions": _dimensions(79),
                "evidence": ["readable but generic"],
            }
        ]
    )
    configure_plugin_llm(llm)

    payload = json.loads(
        story_video_quality_control(
            {
                "action": "judge_candidates",
                "shot_id": "S00_SH00",
                "candidates": [_candidate(context, "C01")],
                "repair_round": 1,
            },
            session_id="session-1",
            store=store,
        )
    )

    assert payload["success"] is False
    assert payload["status"] == "repair_required"
    assert payload["best_score"] == 79
    assert not (context.project_dir / "images" / "S00_SH00.png").exists()


def test_third_failed_round_reports_quality_budget_exhausted(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    llm = FakeLlm(
        [
            {
                "candidate_id": "C01",
                "hard_blockers": ["scientifically incorrect anatomy"],
                "dimensions": _dimensions(94),
                "evidence": ["limb joint is malformed"],
            }
        ]
    )
    configure_plugin_llm(llm)

    payload = json.loads(
        story_video_quality_control(
            {
                "action": "judge_candidates",
                "shot_id": "S00_SH00",
                "candidates": [_candidate(context, "C01")],
                "repair_round": 3,
            },
            session_id="session-1",
            store=store,
        )
    )

    assert payload["success"] is False
    assert payload["status"] == "quality_budget_exhausted"
    assert payload["repair_round"] == 3


def test_judge_fails_closed_before_calling_llm_for_non_openai_candidate(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    llm = FakeLlm([])
    configure_plugin_llm(llm)

    payload = json.loads(
        story_video_quality_control(
            {
                "action": "judge_candidates",
                "shot_id": "S00_SH00",
                "candidates": [_candidate(context, "C01", provider="xai")],
            },
            session_id="session-1",
            store=store,
        )
    )

    assert payload["success"] is False
    assert payload["error_type"] == "story_video_non_openai_candidate"
    assert llm.calls == []


def test_judge_fails_closed_when_review_provider_is_not_openai(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    llm = FakeLlm(
        [
            {
                "candidate_id": "C01",
                "hard_blockers": [],
                "dimensions": _dimensions(95),
                "evidence": ["looks good"],
            }
        ],
        provider="xai",
    )
    configure_plugin_llm(llm)

    payload = json.loads(
        story_video_quality_control(
            {
                "action": "judge_candidates",
                "shot_id": "S00_SH00",
                "candidates": [_candidate(context, "C01")],
            },
            session_id="session-1",
            store=store,
        )
    )

    assert payload["success"] is False
    assert payload["error_type"] == "story_video_non_openai_judge"
    assert not (context.project_dir / "images" / "S00_SH00.png").exists()


def test_status_summarizes_selected_and_blocked_shots(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    manifest_path = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "outputs": [
                    {"shot_id": "S00_SH00", "selected": True},
                    {"shot_id": "S00_SH01", "selected": False, "status": "repair_required"},
                ]
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        story_video_quality_control(
            {"action": "status"}, session_id="session-1", store=store
        )
    )

    assert payload["success"] is True
    assert payload["selected_shot_count"] == 1
    assert payload["blocked_shot_ids"] == ["S00_SH01"]
