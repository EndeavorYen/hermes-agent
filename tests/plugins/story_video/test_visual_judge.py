from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from plugins import story_video
from plugins.story_video import hooks
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
    registered_hooks = {}

    class FakeContext:
        llm = FakeLlm([])

        def register_tool(self, *, name, toolset, schema, handler):
            registered_tools[name] = {
                "toolset": toolset,
                "schema": schema,
                "handler": handler,
            }

        def register_hook(self, name, callback):
            registered_hooks[name] = callback

    story_video.register(FakeContext())

    assert set(registered_tools) == {
        "story_video_control",
        "story_video_quality_control",
    }
    assert registered_tools["story_video_quality_control"]["toolset"] == "story_video"
    assert registered_tools["story_video_quality_control"]["schema"]["name"] == "story_video_quality_control"
    assert registered_hooks["auto_continue_llm_output"] is hooks.auto_continue_llm_output


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
    assert payload["candidate_budget"] == 1
    assert payload["generation_policy"] == "qc_driven_selective_regeneration"
    assert payload["max_repair_rounds"] == 5
    assert "Evidence that must be readable" in payload["prompt"]
    assert (context.project_dir / payload["prompt_path"]).is_file()


def test_compile_prompt_includes_latest_qc_blocker_in_repair_directive(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps({"outputs": [{
            "shot_id": "S00_SH00",
            "status": "repair_required",
            "repair_round": 2,
            "hard_blockers": ["subtitle-safe area is occupied by the fossil"],
        }]}),
        encoding="utf-8",
    )

    payload = json.loads(story_video_quality_control(
        {"action": "compile_prompt", "shot_id": "S00_SH00"},
        session_id="session-1",
        store=store,
    ))

    assert payload["success"] is True
    assert payload["repair_feedback_applied"] is True
    assert payload["strategy_reset"] is False
    assert payload["candidate_id_hint"] == "S00_SH00_C03"
    assert "Prior QC blocker" in payload["prompt"]
    assert "subtitle-safe area is occupied by the fossil" in payload["prompt"]
    assert "materially change the composition" in payload["prompt"]


def test_exhausted_prompt_allows_one_layout_strategy_reset(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps({"outputs": [{
            "shot_id": "S00_SH00",
            "status": "quality_budget_exhausted",
            "repair_round": 5,
            "strategy_reset": False,
            "hard_blockers": ["subtitle collision on the right third"],
        }]}),
        encoding="utf-8",
    )

    payload = json.loads(story_video_quality_control(
        {"action": "compile_prompt", "shot_id": "S00_SH00"},
        session_id="session-1",
        store=store,
    ))

    assert payload["success"] is True
    assert payload["strategy_reset"] is True
    assert payload["candidate_id_hint"] == "S00_SH00_LAYOUT_C01"
    assert payload["remaining_strategy_reset_candidates"] == 1
    assert "one-time composition strategy reset" in payload["prompt"]


def test_compile_prompt_refuses_a_second_layout_strategy_reset(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps({"outputs": [{
            "shot_id": "S00_SH00",
            "status": "quality_budget_exhausted",
            "repair_round": 1,
            "strategy_reset": True,
            "hard_blockers": ["subtitle collision remains"],
        }]}),
        encoding="utf-8",
    )

    payload = json.loads(story_video_quality_control(
        {"action": "compile_prompt", "shot_id": "S00_SH00"},
        session_id="session-1",
        store=store,
    ))

    assert payload["success"] is False
    assert payload["status"] == "human_review_required"
    assert payload["hard_blockers"] == ["subtitle collision remains"]


def test_next_batch_work_repairs_first_blocked_shot_before_new_shots(tmp_path) -> None:
    store, context, shot = _context(tmp_path)
    ledger_path = context.project_dir / "scene_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    second = {**shot, "shot_id": "S00_SH01", "subject": "second subject"}
    ledger["scenes"][0]["shots"].append(second)
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps({"outputs": [{
            "shot_id": "S00_SH00",
            "status": "repair_required",
            "selected": False,
            "repair_round": 1,
            "hard_blockers": ["subtitle collision"],
        }]}),
        encoding="utf-8",
    )

    payload = json.loads(story_video_quality_control(
        {"action": "next_batch_work"}, session_id="session-1", store=store
    ))

    assert payload["success"] is True
    assert payload["work_status"] == "ready"
    assert payload["operation"] == "repair"
    assert payload["shot_id"] == "S00_SH00"
    assert payload["candidate_id_hint"] == "S00_SH00_C02"
    assert payload["remaining_shot_count"] == 2


def test_next_batch_work_advances_in_ledger_order_after_selection(tmp_path) -> None:
    store, context, shot = _context(tmp_path)
    ledger_path = context.project_dir / "scene_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["scenes"][0]["shots"].append(
        {**shot, "shot_id": "S00_SH01", "subject": "second subject"}
    )
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps({"outputs": [{
            "shot_id": "S00_SH00",
            "status": "selected_current",
            "selected": True,
            "repair_round": 1,
        }]}),
        encoding="utf-8",
    )

    payload = json.loads(story_video_quality_control(
        {"action": "next_batch_work"}, session_id="session-1", store=store
    ))

    assert payload["work_status"] == "ready"
    assert payload["operation"] == "generate"
    assert payload["shot_id"] == "S00_SH01"
    assert payload["candidate_id_hint"] == "S00_SH01_C01"
    assert payload["remaining_shot_count"] == 1


def test_next_batch_work_returns_complete_when_every_shot_is_selected(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps({"outputs": [{
            "shot_id": "S00_SH00", "status": "selected_current", "selected": True
        }]}),
        encoding="utf-8",
    )

    payload = json.loads(story_video_quality_control(
        {"action": "next_batch_work"}, session_id="session-1", store=store
    ))

    assert payload == {
        "success": True,
        "action": "next_batch_work",
        "work_status": "complete",
        "remaining_shot_count": 0,
    }


def test_judge_sends_one_candidate_to_openai_and_selects_it_when_it_passes(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    candidates = [_candidate(context, "C01")]
    llm = FakeLlm(
        [
            {
                "candidate_id": "C01",
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
    assert payload["selected_candidate_id"] == "C01"
    assert llm.calls[0]["provider"] == "openai-codex"
    image_inputs = [item for item in llm.calls[0]["input"] if item["type"] == "image"]
    assert len(image_inputs) == 1
    selected = context.project_dir / "images" / "S00_SH00.png"
    assert selected.read_bytes() == b"image-C01"
    manifest = json.loads(
        (context.project_dir / "manifests" / "shot_candidate_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    current = [row for row in manifest["outputs"] if row["selected"]]
    assert len(current) == 1
    assert current[0]["candidate_id"] == "C01"
    assert current[0]["quality_score"] == 91
    assert current[0]["judge_provider"] == "openai-codex"
    assert current[0]["vision_evidence"]["response_id"] == "resp_story_video_judge"
    rejected = [row for row in manifest["outputs"] if not row["selected"]]
    assert rejected == []
    assert not (context.project_dir / "manifests" / "shot_candidate_manifest.json.tmp").exists()


def test_judge_rejects_multiple_candidates_in_one_round_to_protect_quota(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    llm = FakeLlm([])

    payload = json.loads(
        story_video_quality_control(
            {
                "action": "judge_candidates",
                "shot_id": "S00_SH00",
                "candidates": [_candidate(context, "C01"), _candidate(context, "C02")],
                "repair_round": 1,
            },
            session_id="session-1",
            store=store,
            llm=llm,
        )
    )

    assert payload["success"] is False
    assert payload["error_type"] == "story_video_single_candidate_required"
    assert llm.calls == []


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


def test_fifth_failed_round_reports_quality_budget_exhausted(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    llm = FakeLlm(
        [
            {
                "candidate_id": "S00_SH00_C05",
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
                "candidates": [_candidate(context, "S00_SH00_C05")],
                "repair_round": 5,
            },
            session_id="session-1",
            store=store,
        )
    )

    assert payload["success"] is False
    assert payload["status"] == "quality_budget_exhausted"
    assert payload["repair_round"] == 5


def test_candidate_suffix_prevents_repair_round_from_resetting(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    llm = FakeLlm(
        [
            {
                "candidate_id": "S00_SH00_C05",
                "hard_blockers": ["subtitle collision"],
                "dimensions": _dimensions(90),
                "evidence": ["subtitle-safe area is occupied"],
            }
        ]
    )

    payload = json.loads(
        story_video_quality_control(
            {
                "action": "judge_candidates",
                "shot_id": "S00_SH00",
                "candidates": [_candidate(context, "S00_SH00_C05")],
                "repair_round": 1,
            },
            session_id="session-1",
            store=store,
            llm=llm,
        )
    )

    assert payload["success"] is False
    assert payload["status"] == "quality_budget_exhausted"
    assert payload["repair_round"] == 5


def test_failed_layout_strategy_reset_exhausts_after_one_candidate(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    candidate = _candidate(context, "S00_SH00_LAYOUT_C01")
    candidate["strategy_reset"] = True
    llm = FakeLlm(
        [
            {
                "candidate_id": "S00_SH00_LAYOUT_C01",
                "hard_blockers": ["subtitle-safe area remains occupied"],
                "dimensions": _dimensions(90),
                "evidence": ["focal fossil still crosses the reserved band"],
            }
        ]
    )

    payload = json.loads(story_video_quality_control(
        {
            "action": "judge_candidates",
            "shot_id": "S00_SH00",
            "candidates": [candidate],
            "repair_round": 1,
        },
        session_id="session-1",
        store=store,
        llm=llm,
    ))

    assert payload["success"] is False
    assert payload["status"] == "quality_budget_exhausted"
    manifest = json.loads(
        (context.project_dir / "manifests" / "shot_candidate_manifest.json").read_text()
    )
    assert manifest["outputs"][0]["strategy_reset"] is True


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


def test_prepare_render_writes_exact_renderer_v2_contract(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    image = context.project_dir / "images" / "S00_SH00.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"selected-image")
    audio = context.project_dir / "audio" / "qwen" / "S00.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"narration")
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps(
            {
                "provider": "openai-codex",
                "judge_provider": "openai-codex",
                "outputs": [
                    {
                        "shot_id": "S00_SH00",
                        "selected": True,
                        "status": "selected_current",
                        "local_path": "images/S00_SH00.png",
                        "provider": "openai-codex",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (manifests / "narration_manifest.json").write_text(
        json.dumps(
            {
                "provider": "local_qwen",
                "outputs": [
                    {
                        "scene_id": "S00",
                        "audio": str(audio),
                        "display_text": "直立腿讓早期恐龍移動得更有效率。",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        story_video_quality_control(
            {"action": "prepare_render"},
            session_id="session-1",
            store=store,
        )
    )

    assert payload["success"] is True
    render_input = json.loads(
        (context.project_dir / "render_input.json").read_text(encoding="utf-8")
    )
    assert render_input["schema"] == "story_video_render_input_v2"
    assert render_input["resolution"] == {"width": 1920, "height": 1080}
    assert render_input["post_speech_hold_sec"] == 0.85
    assert render_input["max_post_speech_hold_sec"] == 1.5
    assert render_input["zoom_max"] == 1.025
    scene = render_input["scenes"][0]
    assert scene["selected"] is True
    assert scene["audio"] == "audio/qwen/S00.wav"
    assert scene["narration"] == "直立腿讓早期恐龍移動得更有效率。"
    assert scene["shots"][0] == {
        "shot_id": "S00_SH00",
        "selected": True,
        "image": "images/S00_SH00.png",
        "narration": "直立腿讓早期恐龍移動得更有效率。",
    }
    assert render_input["opening_card"]["image"] == "images/S00_SH00.png"
    assert render_input["ending_card"]["image"] == "images/S00_SH00.png"


def test_prepare_render_prefers_branded_release_cards(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    image = context.project_dir / "images" / "S00_SH00.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"selected-image")
    audio = context.project_dir / "audio" / "qwen" / "S00.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"narration")
    release_art = context.project_dir / "release_art"
    release_art.mkdir(parents=True)
    (release_art / "opening_card.png").write_bytes(b"opening")
    (release_art / "ending_card.png").write_bytes(b"ending")
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps({"outputs": [{
            "shot_id": "S00_SH00", "selected": True,
            "local_path": "images/S00_SH00.png", "provider": "openai-codex"
        }]}), encoding="utf-8"
    )
    (manifests / "narration_manifest.json").write_text(
        json.dumps({"outputs": [{
            "scene_id": "S00", "audio": "audio/qwen/S00.wav",
            "display_text": "旁白"
        }]}), encoding="utf-8"
    )

    payload = json.loads(story_video_quality_control(
        {"action": "prepare_render"}, session_id="session-1", store=store
    ))

    assert payload["success"] is True
    render_input = json.loads((context.project_dir / "render_input.json").read_text())
    assert render_input["opening_card"] == {
        "title": context.topic,
        "image": "release_art/opening_card.png",
        "duration_sec": 2.0,
    }
    assert render_input["ending_card"] == {
        "title": "探索仍在繼續",
        "image": "release_art/ending_card.png",
        "duration_sec": 5.0,
    }
