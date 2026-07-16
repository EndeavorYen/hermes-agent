from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageFont

from plugins import story_video
from plugins.story_video import hooks
from plugins.story_video.state import StoryVideoStateStore, parse_operator_call
from plugins.story_video.visual_judge import (
    CANDIDATE_REVIEW_SCHEMA,
    _compile_prompt,
    _measured_voice_chunk_subtitle_cues,
    _next_batch_work_group,
    _promote_auto_terminal_fallbacks,
    _review_instructions,
    _shot_contract_hash,
    _source_image_qc_blockers,
    configure_plugin_llm,
    story_video_quality_control,
)


def test_measured_voice_chunk_cues_fail_closed_on_unverified_chunk() -> None:
    segment = {
        "display_text": "第一句。第二句。",
        "timeline_duration_sec": 2.36,
        "voice_chunks": [
            {
                "voice_chunk_id": "S00_SH00__C01",
                "display_text": "第一句。",
                "start_sec": 0.0,
                "speech_end_sec": 1.0,
                "alignment_status": "PASS",
                "pronunciation_status": "PASS",
                "prosody_status": "PASS",
            },
            {
                "voice_chunk_id": "S00_SH00__C02",
                "display_text": "第二句。",
                "start_sec": 1.18,
                "speech_end_sec": 2.18,
                "alignment_status": "PASS",
                "pronunciation_status": "FAIL",
                "prosody_status": "PASS",
            },
        ],
    }

    with pytest.raises(ValueError, match="pronunciation_status"):
        _measured_voice_chunk_subtitle_cues(segment, scene_id="S00")


def test_quality_tool_schema_exposes_native_batch_chunk() -> None:
    from plugins.story_video.schemas import STORY_VIDEO_QUALITY_CONTROL_SCHEMA

    actions = STORY_VIDEO_QUALITY_CONTROL_SCHEMA["parameters"]["properties"][
        "action"
    ]["enum"]
    properties = STORY_VIDEO_QUALITY_CONTROL_SCHEMA["parameters"]["properties"]

    assert "run_batch_chunk" in actions
    assert "run_id" in properties
    assert "project_dir" in properties


def test_quality_tool_schema_exposes_native_voice_phase() -> None:
    from plugins.story_video.schemas import STORY_VIDEO_QUALITY_CONTROL_SCHEMA

    actions = STORY_VIDEO_QUALITY_CONTROL_SCHEMA["parameters"]["properties"][
        "action"
    ]["enum"]

    assert "run_voice_phase" in actions


def test_auto_native_batch_requires_matching_scoped_authorization(
    tmp_path, monkeypatch
) -> None:
    from plugins.story_video import visual_judge

    store = StoryVideoStateStore(tmp_path)
    call = parse_operator_call(
        "故事影片：恐龍起源｜30秒｜電影感寫實。全自動製作。"
    )
    assert call is not None
    context = store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=call,
        original_request="故事影片：恐龍起源｜30秒｜電影感寫實。全自動製作。",
    )
    context = store.update(context, phase="batch", auto_mode=True)
    authorization = store.autopilot_authorization(context)
    assert authorization is not None
    calls: list[str] = []
    monkeypatch.setattr(
        visual_judge,
        "_run_batch_chunk",
        lambda *_args, **_kwargs: calls.append("run")
        or {"success": True, "work_status": "in_progress"},
    )

    missing = json.loads(
        story_video_quality_control(
            {"action": "run_batch_chunk"},
            session_id="session-1",
            store=store,
        )
    )
    wrong = json.loads(
        story_video_quality_control(
            {
                "action": "run_batch_chunk",
                "authorization_id": "wrong-authorization-id",
            },
            session_id="session-1",
            store=store,
        )
    )
    accepted = json.loads(
        story_video_quality_control(
            {
                "action": "run_batch_chunk",
                "authorization_id": authorization["authorization_id"],
            },
            session_id="session-1",
            store=store,
        )
    )

    assert missing["error_type"] == "story_video_operator_authorization_required"
    assert wrong["error_type"] == "story_video_operator_authorization_required"
    assert accepted["success"] is True
    assert calls == ["run"]


def test_auto_native_voice_requires_matching_scoped_authorization(
    tmp_path, monkeypatch
) -> None:
    from plugins.story_video import visual_judge

    store = StoryVideoStateStore(tmp_path)
    call = parse_operator_call(
        "故事影片：恐龍起源｜30秒｜電影感寫實。全自動製作。"
    )
    assert call is not None
    context = store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=call,
        original_request="故事影片：恐龍起源｜30秒｜電影感寫實。全自動製作。",
    )
    context = store.update(context, phase="voice", auto_mode=True)
    authorization = store.autopilot_authorization(context)
    assert authorization is not None
    calls: list[str] = []
    monkeypatch.setattr(
        visual_judge,
        "_run_voice_phase",
        lambda *_args, **_kwargs: calls.append("run")
        or {"success": True, "work_status": "complete"},
    )

    missing = json.loads(
        story_video_quality_control(
            {"action": "run_voice_phase"},
            session_id="session-1",
            store=store,
        )
    )
    accepted = json.loads(
        story_video_quality_control(
            {
                "action": "run_voice_phase",
                "authorization_id": authorization["authorization_id"],
            },
            session_id="session-1",
            store=store,
        )
    )

    assert missing["error_type"] == "story_video_operator_authorization_required"
    assert accepted["success"] is True
    assert accepted["authorization_verified"] is True
    assert calls == ["run"]


def test_native_batch_chunk_rejudges_legacy_selection_without_generation(
    tmp_path, monkeypatch
) -> None:
    from plugins.story_video import visual_judge

    store, context, shot = _context(tmp_path)
    ledger_path = context.project_dir / "scene_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["quality_contract_version"] = 5
    ledger["engagement_profile"] = {
        "mode": "discovery_documentary",
        "energy": "balanced",
    }
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    context = store.update(context, phase="batch", auto_mode=True)
    image = context.project_dir / "images" / "legacy.png"
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b"legacy")
    manifest_path = (
        context.project_dir / "manifests" / "shot_candidate_manifest.json"
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "outputs": [
                    {
                        "shot_id": shot["shot_id"],
                        "candidate_id": "S00_SH00_C01",
                        "selected": True,
                        "status": "selected_current",
                        "provider": "openai-codex",
                        "candidate_path": str(image),
                        "local_path": str(image),
                        "quality_contract_version": 2,
                        "quality_dimensions": {"text_alignment": 88},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    captured: dict = {}

    def fake_judge(_context, **kwargs):
        captured.update(kwargs)
        return {"success": True, "status": "selected"}

    monkeypatch.setattr(visual_judge, "_judge_candidates", fake_judge)

    payload = visual_judge._run_batch_chunk(
        context,
        state_store=store,
        llm=object(),
    )

    assert payload["work_status"] == "in_progress"
    assert payload["wave"] == "legacy_rejudge"
    assert payload["generated_candidates"] == 0
    assert captured["shot_id"] == "S00_SH00"


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
    ledger = json.loads((context.project_dir / "scene_ledger.json").read_text())
    shot = ledger["scenes"][0]["shots"][0]
    return {
        "candidate_id": candidate_id,
        "path": str(path),
        "provider": provider,
        "model": "gpt-image-2-high",
        "response_id": f"img_{candidate_id}",
        "shot_contract_hash": _shot_contract_hash(shot),
    }


def _release_cards(context) -> None:
    release_art = context.project_dir / "release_art"
    release_art.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "hero_source": release_art / "hero_source.png",
        "opening_card": release_art / "opening_card.png",
        "ending_card": release_art / "ending_card.png",
        "thumbnail": release_art / "thumbnail.jpg",
    }
    for name, path in artifacts.items():
        path.write_bytes(name.encode())
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "release_art_manifest.json").write_text(
        json.dumps(
            {
                "schema": "story_video_release_art_manifest_v1",
                "run_id": context.run_id,
                "status": "PASS",
                "provider": "openai-codex",
                "response_id": "img_release_test",
                "artifacts": {
                    name: {
                        "path": str(path.relative_to(context.project_dir)),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                    for name, path in artifacts.items()
                },
            }
        ),
        encoding="utf-8",
    )


def _dimensions(score: int) -> dict:
    return {
        "text_alignment": score,
        "focal_clarity": score,
        "evidence_specificity": score,
        "professional_quality": score,
        "scientific_credibility": score,
        "continuity_and_diversity": score,
        "narrative_engagement": score,
        "story_moment_clarity": score,
        "cinematic_impact": score,
        "style_consistency": score,
    }


def test_visual_judge_scores_story_engagement_from_artifact_evidence() -> None:
    dimensions = CANDIDATE_REVIEW_SCHEMA["properties"]["candidates"]["items"][
        "properties"
    ]["dimensions"]
    instructions = _review_instructions(
        {
            "engagement_role": "breathe",
            "composition_energy": "calm",
            "calm_reason": "讓觀眾消化剛揭示的結果",
        },
        ["C01"],
    )

    assert "narrative_engagement" in dimensions["required"]
    assert "story_moment_clarity" in dimensions["required"]
    assert "cinematic_impact" in dimensions["required"]
    assert "style_consistency" in dimensions["required"]
    candidate_schema = CANDIDATE_REVIEW_SCHEMA["properties"]["candidates"]["items"]
    assert "focal_point_normalized" in candidate_schema["required"]
    assert "Intentional calm" in instructions
    assert "static_catalog" in instructions
    assert "generic documentary" in instructions
    assert "subtitle collision" not in instructions


def test_visual_judge_requires_style_comparison_when_anchor_is_available() -> None:
    instructions = _review_instructions(
        {"shot_id": "S00_SH01"},
        ["C01"],
        style_bible={"style_id": "theatrical-discovery-v1"},
        has_style_anchor=True,
    )

    assert "Style reference image appears before candidate images" in instructions
    assert "style_consistency" in instructions
    assert "style_drift" in instructions


def test_compile_prompt_passes_selected_openai_anchor_as_style_reference(tmp_path) -> None:
    _store, context, anchor_shot = _context(tmp_path)
    ledger_path = context.project_dir / "scene_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    target_shot = {
        **anchor_shot,
        "shot_id": "S00_SH01",
        "subject": "early dinosaur looking toward a distant dust plume",
        "action": "turns its head as the plume rises",
    }
    ledger["quality_contract_version"] = 4
    ledger["style_bible"] = {
        "style_id": "theatrical-discovery-v1",
        "anchor_shot_id": "S00_SH00",
        "medium": "cinematic photoreal reconstruction",
        "palette": "mineral greens and volcanic amber",
        "lighting": "motivated shafts with deep dimensional contrast",
        "lens_language": "low 35mm hero perspective and selective focus",
        "texture": "tactile skin, dust, and vegetation",
        "atmosphere": "wonder with controlled danger",
        "subject_treatment": "one dominant story action",
        "forbidden_drift": ["flat encyclopedia plate"],
    }
    ledger["scenes"][0]["shots"].append(target_shot)
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    anchor_path = context.project_dir / "images_candidates" / "S00_SH00" / "anchor.png"
    anchor_path.parent.mkdir(parents=True, exist_ok=True)
    anchor_path.write_bytes(b"selected-openai-anchor")
    manifest_path = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "outputs": [
                    {
                        "shot_id": "S00_SH00",
                        "candidate_id": "anchor",
                        "local_path": str(anchor_path.relative_to(context.project_dir)),
                        "provider": "openai-codex",
                        "selected": True,
                        "status": "selected_current",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = _compile_prompt(context, shot_id="S00_SH01")

    assert result["success"] is True
    assert result["reference_image_urls"] == [str(anchor_path)]
    assert result["style_reference_policy"] == (
        "style_only_do_not_copy_subject_or_composition"
    )


def test_visual_judge_does_not_require_camera_motion_inside_reveal_source_frame() -> None:
    instructions = _review_instructions(
        {
            "shot_scale": "establishing",
            "action": "slow low-altitude push-in",
            "story_moment": "the camera pushes in to reveal the aftermath valley",
            "visual_truth_mode": "reconstruction",
        },
        ["C01"],
    )

    assert "Do not require camera motion to be visible inside the still" in instructions
    assert "A coherent reconstruction may contain the declared environmental evidence" in instructions


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
    provider = registered_tools["story_video_quality_control"]["schema"][
        "parameters"
    ]["properties"]["provider"]
    assert provider["enum"] == ["openai-codex"]


def test_candidate_judge_forces_openai_provider_before_inference(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    candidate = _candidate(context, "S00_SH00_C01")
    llm = FakeLlm(
        [
            {
                "candidate_id": "S00_SH00_C01",
                "hard_blockers": [],
                "blocker_codes": [],
                "dimensions": _dimensions(90),
                "evidence": ["the declared action and evidence are visibly readable"],
            }
        ]
    )

    result = json.loads(
        story_video_quality_control(
            {
                "action": "judge_candidates",
                "shot_id": "S00_SH00",
                "repair_round": 1,
                "candidates": [candidate],
            },
            session_id="session-1",
            store=store,
            llm=llm,
        )
    )

    assert result["success"] is True
    assert llm.calls[0]["provider"] == "openai-codex"


def test_candidate_judge_refreshes_legacy_manifest_summary_from_outputs(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    manifest_path = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "selected_shot_count": 0,
                "generated_candidate_count": 0,
                "current_shot_id": "STALE_SHOT",
                "outputs": [],
                "attempt_history": [],
            }
        ),
        encoding="utf-8",
    )
    candidate = _candidate(context, "S00_SH00_C01")
    llm = FakeLlm(
        [
            {
                "candidate_id": candidate["candidate_id"],
                "hard_blockers": [],
                "blocker_codes": [],
                "dimensions": _dimensions(90),
                "evidence": ["the declared action and evidence are visibly readable"],
            }
        ]
    )

    result = json.loads(
        story_video_quality_control(
            {
                "action": "judge_candidates",
                "shot_id": "S00_SH00",
                "repair_round": 1,
                "candidates": [candidate],
            },
            session_id="session-1",
            store=store,
            llm=llm,
        )
    )

    assert result["success"] is True
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["selected_shot_count"] == 1
    assert manifest["generated_candidate_count"] == 1
    assert manifest["current_shot_id"] == "S00_SH00"


def test_candidate_judge_reuses_content_addressed_qc_result(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    candidate = _candidate(context, "S00_SH00_C01")
    first_llm = FakeLlm(
        [{
            "candidate_id": candidate["candidate_id"],
            "hard_blockers": [],
            "blocker_codes": [],
            "dimensions": _dimensions(90),
            "evidence": ["the declared action and evidence are visibly readable"],
        }]
    )
    first = json.loads(story_video_quality_control(
        {
            "action": "judge_candidates",
            "shot_id": "S00_SH00",
            "repair_round": 1,
            "candidates": [candidate],
        },
        session_id="session-1",
        store=store,
        llm=first_llm,
    ))
    second_llm = FakeLlm([])
    second = json.loads(story_video_quality_control(
        {
            "action": "judge_candidates",
            "shot_id": "S00_SH00",
            "repair_round": 1,
            "candidates": [candidate],
        },
        session_id="session-1",
        store=store,
        llm=second_llm,
    ))

    assert first["success"] is True
    assert second["success"] is True
    assert second["cache_hit"] is True
    assert second["selected_candidate_id"] == candidate["candidate_id"]
    assert second_llm.calls == []
    manifest = json.loads(
        (context.project_dir / "manifests" / "shot_candidate_manifest.json").read_text()
    )
    assert manifest["outputs"][0]["artifact_sha256"]
    assert manifest["outputs"][0]["quality_contract_version"] == 4


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
    assert payload["max_repair_rounds"] == 3
    assert "Evidence that must be readable" in payload["prompt"]
    assert (context.project_dir / payload["prompt_path"]).is_file()


def test_source_image_qc_ignores_subtitle_packaging_blockers() -> None:
    blockers, codes = _source_image_qc_blockers(
        ["subtitle-safe area is occupied", "the fossil anatomy is malformed"],
        ["subtitle_collision", "anatomy_geometry"],
    )

    assert blockers == ["the fossil anatomy is malformed"]
    assert codes == {"anatomy_geometry"}


def test_compile_prompt_ignores_subtitle_packaging_feedback(tmp_path) -> None:
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
    assert payload["repair_feedback_applied"] is False
    assert payload["strategy_reset"] is False
    assert payload["candidate_id_hint"] == "S00_SH00_C03"
    assert "Prior QC blocker" not in payload["prompt"]
    assert "subtitle-safe area is occupied by the fossil" not in payload["prompt"]
    assert "Change the failing visual evidence" in payload["prompt"]


def test_compile_prompt_uses_previous_candidate_as_targeted_edit_source(
    tmp_path,
) -> None:
    store, context, shot = _context(tmp_path)
    candidate = _candidate(context, "S00_SH00_C01")
    prior = {
        "shot_id": "S00_SH00",
        "candidate_id": candidate["candidate_id"],
        "status": "repair_required",
        "repair_strategy": "initial",
        "shot_contract_hash": _shot_contract_hash(shot),
        "provider": "openai-codex",
        "candidate_path": candidate["path"],
        "local_path": candidate["path"],
        "hard_blockers": ["one branch line is disconnected"],
        "blocker_codes": ["anatomy_geometry"],
    }
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps({"outputs": [prior], "attempt_history": [prior]}),
        encoding="utf-8",
    )

    payload = json.loads(story_video_quality_control(
        {"action": "compile_prompt", "shot_id": "S00_SH00"},
        session_id="session-1",
        store=store,
    ))

    assert payload["success"] is True
    assert payload["repair_strategy"] == "targeted_repair"
    assert payload["source_image_url"] == candidate["path"]
    assert payload["source_candidate_id"] == candidate["candidate_id"]
    assert payload["generation_mode"] == "image_edit"


def test_exhausted_prompt_does_not_repair_post_composite_subtitle_layout(
    tmp_path,
) -> None:
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
    assert payload["strategy_reset"] is False
    assert payload["candidate_id_hint"] == "S00_SH00_CONTEXT_C01"
    assert payload["remaining_strategy_reset_candidates"] == 0
    assert "subtitle collision" not in payload["prompt"]


def test_compile_prompt_replans_context_after_failed_layout_reset(tmp_path) -> None:
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

    assert payload["success"] is True
    assert payload["repair_strategy"] == "contextual_replan"
    assert payload["candidate_id_hint"] == "S00_SH00_CONTEXT_C01"
    assert payload["hard_blockers"] == []


def test_compile_prompt_reframes_scientific_evidence_after_layout_reset(
    tmp_path,
) -> None:
    store, context, _shot = _context(tmp_path)
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps({"outputs": [{
            "shot_id": "S00_SH00",
            "status": "quality_budget_exhausted",
            "repair_round": 1,
            "strategy_reset": True,
            "hard_blockers": [
                "科學與解剖辨識不足：無法可信辨識為纖細的顎部化石。",
                "牙齒幾何疑似失真。",
            ],
        }]}),
        encoding="utf-8",
    )

    payload = json.loads(story_video_quality_control(
        {"action": "compile_prompt", "shot_id": "S00_SH00"},
        session_id="session-1",
        store=store,
    ))

    assert payload["success"] is True
    assert payload["repair_strategy"] == "evidence_reframe"
    assert payload["candidate_id_hint"] == "S00_SH00_EVIDENCE_C01"
    assert "fragmentary evidence" in payload["prompt"]
    assert "one-time composition strategy reset" not in payload["prompt"]
    assert "macro evidence shot" not in payload["prompt"]
    assert "close-up shot" in payload["prompt"]
    assert payload["effective_shot_contract"]["shot_scale"] == "close_up"


def test_judge_preserves_append_only_attempt_history(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    old_attempt = {
        "shot_id": "S00_SH00", "candidate_id": "S00_SH00_C01",
        "status": "repair_required", "repair_strategy": "targeted_repair",
        "repair_round": 1, "hard_blockers": ["subtitle collision"],
    }
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps({"outputs": [old_attempt], "attempt_history": [old_attempt]}),
        encoding="utf-8",
    )
    candidate = _candidate(context, "S00_SH00_C02")
    candidate["repair_strategy"] = "targeted_repair"
    llm = FakeLlm([{
        "candidate_id": "S00_SH00_C02",
        "hard_blockers": ["malformed ankle geometry"],
        "blocker_codes": ["anatomy_geometry"],
        "dimensions": _dimensions(70),
        "evidence": ["ankle geometry is visibly malformed"],
    }])

    story_video_quality_control(
        {
            "action": "judge_candidates", "shot_id": "S00_SH00",
            "repair_round": 2, "candidates": [candidate],
        },
        session_id="session-1",
        store=store,
        llm=llm,
    )

    manifest = json.loads(
        (manifests / "shot_candidate_manifest.json").read_text(encoding="utf-8")
    )
    assert [row["candidate_id"] for row in manifest["attempt_history"]] == [
        "S00_SH00_C01", "S00_SH00_C02"
    ]
    assert len(manifest["outputs"]) == 1
    assert manifest["outputs"][0]["candidate_id"] == "S00_SH00_C02"
    assert manifest["outputs"][0]["blocker_codes"] == ["anatomy_geometry"]


def test_repeated_blocker_without_score_gain_pivots_before_fifth_round(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    old_attempt = {
        "shot_id": "S00_SH00",
        "candidate_id": "S00_SH00_C01",
        "status": "repair_required",
        "repair_strategy": "targeted_repair",
        "repair_round": 1,
        "quality_score": 70.0,
        "hard_blockers": ["malformed ankle geometry"],
        "blocker_codes": ["anatomy_geometry"],
    }
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps({"outputs": [old_attempt], "attempt_history": [old_attempt]}),
        encoding="utf-8",
    )
    candidate = _candidate(context, "S00_SH00_C02")
    candidate["repair_strategy"] = "targeted_repair"
    llm = FakeLlm([{
        "candidate_id": "S00_SH00_C02",
        "hard_blockers": ["ankle geometry remains malformed"],
        "blocker_codes": ["anatomy_geometry"],
        "dimensions": _dimensions(71),
        "evidence": ["the same ankle defect remains visible"],
    }])

    judged = json.loads(story_video_quality_control(
        {
            "action": "judge_candidates",
            "shot_id": "S00_SH00",
            "repair_round": 2,
            "candidates": [candidate],
        },
        session_id="session-1",
        store=store,
        llm=llm,
    ))
    compiled = json.loads(story_video_quality_control(
        {"action": "compile_prompt", "shot_id": "S00_SH00"},
        session_id="session-1",
        store=store,
    ))

    assert judged["status"] == "quality_budget_exhausted"
    assert judged["convergence_stalled"] is True
    assert compiled["repair_strategy"] == "evidence_reframe"
    assert compiled["candidate_id_hint"] == "S00_SH00_EVIDENCE_C01"


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


def test_next_batch_work_group_batches_fresh_shots_without_extra_candidates(
    tmp_path,
) -> None:
    _store, context, shot = _context(tmp_path)
    ledger_path = context.project_dir / "scene_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["scenes"][0]["shots"] = [
        {**shot, "shot_id": f"S00_SH0{index}", "subject": f"subject {index}"}
        for index in range(4)
    ]
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    payload = _next_batch_work_group(context, max_items=3)

    assert payload["work_status"] == "ready"
    assert payload["operation"] == "generate_batch"
    assert payload["parallelism"] == 3
    assert [item["shot_id"] for item in payload["work_items"]] == [
        "S00_SH00",
        "S00_SH01",
        "S00_SH02",
    ]
    assert [item["candidate_id_hint"] for item in payload["work_items"]] == [
        "S00_SH00_C01",
        "S00_SH01_C01",
        "S00_SH02_C01",
    ]
    assert payload["remaining_shot_count"] == 4


def test_next_batch_work_group_locks_declared_style_anchor_before_parallel_batch(
    tmp_path,
) -> None:
    _store, context, shot = _context(tmp_path)
    ledger_path = context.project_dir / "scene_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["scenes"][0]["shots"] = [
        {**shot, "shot_id": f"S00_SH0{index}", "subject": f"subject {index}"}
        for index in range(4)
    ]
    ledger["quality_contract_version"] = 4
    ledger["style_bible"] = {
        "style_id": "theatrical-discovery-v1",
        "anchor_shot_id": "S00_SH02",
        "medium": "cinematic photoreal reconstruction",
        "palette": "mineral green and volcanic amber",
        "lighting": "motivated shafts with dimensional contrast",
        "lens_language": "low 35mm hero perspective",
        "texture": "tactile skin, dust, and vegetation",
        "atmosphere": "wonder with controlled danger",
        "subject_treatment": "one dominant story action",
        "forbidden_drift": ["flat encyclopedia plate"],
    }
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    payload = _next_batch_work_group(context, max_items=3)

    assert payload["operation"] == "generate"
    assert payload["parallelism"] == 1
    assert [item["shot_id"] for item in payload["work_items"]] == ["S00_SH02"]


def test_next_batch_work_group_keeps_repairs_singleton(tmp_path) -> None:
    _store, context, shot = _context(tmp_path)
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
            "status": "repair_required",
            "selected": False,
            "repair_round": 1,
            "hard_blockers": ["subtitle collision"],
        }]}),
        encoding="utf-8",
    )

    payload = _next_batch_work_group(context, max_items=3)

    assert payload["operation"] == "repair"
    assert payload["parallelism"] == 1
    assert [item["shot_id"] for item in payload["work_items"]] == ["S00_SH00"]


def test_next_batch_work_replans_contract_after_visual_strategies_exhausted(
    tmp_path,
) -> None:
    store, context, shot = _context(tmp_path)
    contract_hash = _shot_contract_hash(shot)
    attempts = [
        {
            "shot_id": "S00_SH00",
            "candidate_id": "S00_SH00_LAYOUT_C01",
            "status": "quality_budget_exhausted",
            "selected": False,
            "repair_strategy": "layout_reset",
            "hard_blockers": ["the subtitle safe area covers the focal subject"],
            "blocker_codes": ["subtitle_collision"],
            "shot_contract_hash": contract_hash,
        },
        {
            "shot_id": "S00_SH00",
            "candidate_id": "S00_SH00_CONTEXT_C01",
            "status": "quality_budget_exhausted",
            "selected": False,
            "repair_strategy": "contextual_replan",
            "hard_blockers": ["the visible evidence does not support the narration"],
            "blocker_codes": ["other"],
            "shot_contract_hash": contract_hash,
        },
        {
            "shot_id": "S00_SH00",
            "candidate_id": "S00_SH00_DOC_C01",
            "status": "quality_budget_exhausted",
            "selected": False,
            "repair_strategy": "documentary_context",
            "hard_blockers": ["the subtitle safe area covers the focal subject"],
            "blocker_codes": ["subtitle_collision"],
            "shot_contract_hash": contract_hash,
        },
    ]
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps({"outputs": [attempts[-1]], "attempt_history": attempts}),
        encoding="utf-8",
    )

    payload = json.loads(story_video_quality_control(
        {"action": "next_batch_work"}, session_id="session-1", store=store
    ))

    assert payload["success"] is True
    assert payload["work_status"] == "ready"
    assert payload["operation"] == "replan_shot_contract"
    assert payload["shot_id"] == "S00_SH00"
    assert payload["replan_revision"] == 1
    assert payload["max_replan_revisions"] == 2
    assert payload["immutable_contract"]["narration_text"] == shot["narration_text"]
    assert "subject" in payload["mutable_fields"]
    assert "intentional_scale_repeat_reason" in payload["mutable_fields"]
    assert payload["hard_blockers"] == []
    assert payload["blocker_codes"] == []
    assert "post-composite QC stage" in payload["replan_directive"]


def test_replan_shot_contract_preserves_truth_fields_and_resets_generation(
    tmp_path,
) -> None:
    store, context, shot = _context(tmp_path)
    old_hash = _shot_contract_hash(shot)
    exhausted = {
        "shot_id": "S00_SH00",
        "candidate_id": "S00_SH00_DOC_C01",
        "status": "quality_budget_exhausted",
        "selected": False,
        "repair_strategy": "documentary_context",
        "hard_blockers": ["the evidence is not visible"],
        "blocker_codes": ["other"],
        "shot_contract_hash": old_hash,
    }
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    manifest_path = manifests / "shot_candidate_manifest.json"
    prior = {
        **exhausted,
        "candidate_id": "S00_SH00_CONTEXT_C01",
        "repair_strategy": "contextual_replan",
    }
    manifest_path.write_text(
        json.dumps({"outputs": [exhausted], "attempt_history": [prior, exhausted]}),
        encoding="utf-8",
    )

    payload = json.loads(story_video_quality_control(
        {
            "action": "replan_shot_contract",
            "shot_id": "S00_SH00",
            "redesigned_shot": {
                "narration_text": "must not replace the approved narration",
                "viewer_takeaway": "must not change the approved meaning",
                "subject": "one fossil footprint pressed into a dry mud layer",
                "action": "a loose edge flakes away and reveals the complete footprint",
                "evidence_detail": "toe impressions and displaced mud rim are readable",
                "shot_scale": "close_up",
                "camera_angle": "low side angle",
                "focal_point": "the newly revealed footprint",
                "subtitle_safe_area": "bottom 20 percent clear",
                "acceptance_criteria": [
                    "one footprint is the only focal subject",
                    "the evidence is readable without labels",
                ],
            },
        },
        session_id="session-1",
        store=store,
    ))

    assert payload["success"] is True
    assert payload["work_status"] == "ready"
    assert payload["operation"] == "generate"
    assert payload["contract_reset"] is True
    assert payload["replan_revision"] == 1
    assert payload["shot_contract_hash"] != old_hash
    ledger = json.loads(
        (context.project_dir / "scene_ledger.json").read_text(encoding="utf-8")
    )
    replanned = ledger["scenes"][0]["shots"][0]
    assert replanned["narration_text"] == shot["narration_text"]
    assert replanned["viewer_takeaway"] == shot["viewer_takeaway"]
    assert replanned["subject"] == "one fossil footprint pressed into a dry mud layer"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["outputs"] == []
    assert manifest["contract_replans"][0]["old_shot_contract_hash"] == old_hash
    assert manifest["contract_replans"][0]["new_shot_contract_hash"] == payload[
        "shot_contract_hash"
    ]


def test_replan_shot_contract_rejects_new_ledger_quality_violation(tmp_path) -> None:
    store, context, base_shot = _context(tmp_path)
    shots = []
    for index, scale in enumerate(("medium", "medium", "wide")):
        shot = dict(base_shot)
        shot["shot_id"] = f"S00_SH0{index}"
        shot["shot_scale"] = scale
        shots.append(shot)
    ledger_path = context.project_dir / "scene_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["scenes"][0]["shots"] = shots
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    selected = []
    for shot in shots[:2]:
        selected.append(
            {
                "shot_id": shot["shot_id"],
                "candidate_id": f"{shot['shot_id']}_C01",
                "status": "selected_current",
                "selected": True,
                "shot_contract_hash": _shot_contract_hash(shot),
            }
        )
    target = shots[2]
    target_hash = _shot_contract_hash(target)
    attempts = [
        {
            "shot_id": target["shot_id"],
            "candidate_id": f"{target['shot_id']}_C0{index}",
            "status": "quality_budget_exhausted",
            "selected": False,
            "repair_strategy": strategy,
            "hard_blockers": ["the evidence is not visible"],
            "blocker_codes": ["other"],
            "shot_contract_hash": target_hash,
        }
        for index, strategy in enumerate(
            ("layout_reset", "contextual_replan", "documentary_context"),
            start=1,
        )
    ]
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps(
            {
                "outputs": [*selected, attempts[-1]],
                "attempt_history": attempts,
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        story_video_quality_control(
            {
                "action": "replan_shot_contract",
                "shot_id": target["shot_id"],
                "redesigned_shot": {
                    "subject": "one fossil footprint in a comparison row",
                    "action": "the third footprint becomes visible",
                    "evidence_detail": "all three prints remain equally readable",
                    "shot_scale": "medium",
                    "camera_angle": "eye level",
                    "focal_point": "the third footprint",
                    "subtitle_safe_area": "upper right clear",
                    "acceptance_criteria": ["three prints remain readable"],
                },
            },
            session_id="session-1",
            store=store,
        )
    )

    assert payload["success"] is False
    assert "repeated_shot_scale_without_reason:medium:3" in payload["error"]
    unchanged = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert unchanged["scenes"][0]["shots"][2]["shot_scale"] == "wide"

    accepted = json.loads(
        story_video_quality_control(
            {
                "action": "replan_shot_contract",
                "shot_id": target["shot_id"],
                "redesigned_shot": {
                    "subject": "one fossil footprint in a comparison row",
                    "action": "the third footprint becomes visible",
                    "evidence_detail": "all three prints remain equally readable",
                    "shot_scale": "medium",
                    "camera_angle": "eye level",
                    "focal_point": "the third footprint",
                    "subtitle_safe_area": "upper right clear",
                    "acceptance_criteria": ["three prints remain readable"],
                    "intentional_scale_repeat_reason": (
                        "Keep equal visual weight across the three-print comparison."
                    ),
                },
            },
            session_id="session-1",
            store=store,
        )
    )

    assert accepted["success"] is True
    repaired = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert repaired["scenes"][0]["shots"][2][
        "intentional_scale_repeat_reason"
    ]


def test_replan_handler_accepts_the_same_exhausted_state_returned_by_next_work(
    tmp_path,
) -> None:
    store, context, shot = _context(tmp_path)
    contract_hash = _shot_contract_hash(shot)
    attempts = [
        {
            "shot_id": "S00_SH00",
            "candidate_id": "S00_SH00_C01",
            "status": "repair_required",
            "selected": False,
            "repair_strategy": "initial",
            "hard_blockers": ["subtitle collision"],
            "blocker_codes": ["subtitle_collision"],
            "shot_contract_hash": contract_hash,
        },
        {
            "shot_id": "S00_SH00",
            "candidate_id": "S00_SH00_C02",
            "status": "repair_required",
            "selected": False,
            "repair_strategy": "targeted_repair",
            "hard_blockers": ["scientific identity is unclear"],
            "blocker_codes": ["scientific_identity"],
            "shot_contract_hash": contract_hash,
        },
        {
            "shot_id": "S00_SH00",
            "candidate_id": "S00_SH00_C03",
            "status": "quality_budget_exhausted",
            "selected": False,
            "repair_strategy": "targeted_repair",
            "hard_blockers": ["scientific identity and subtitle collision"],
            "blocker_codes": ["scientific_identity", "subtitle_collision"],
            "shot_contract_hash": contract_hash,
        },
    ]
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps({"outputs": [attempts[-1]], "attempt_history": attempts}),
        encoding="utf-8",
    )
    next_work = json.loads(story_video_quality_control(
        {"action": "next_batch_work"}, session_id="session-1", store=store
    ))
    assert next_work["operation"] == "replan_shot_contract"

    payload = json.loads(story_video_quality_control(
        {
            "action": "replan_shot_contract",
            "shot_id": "S00_SH00",
            "redesigned_shot": {
                "subject": "one physical museum comparison display",
                "action": "one small model becomes three across a wooden divider",
                "evidence_detail": "the bounded increase remains visibly subordinate",
                "shot_scale": "wide",
                "camera_angle": "eye level",
                "focal_point": "the one-to-three comparison",
                "subtitle_safe_area": "upper right clear",
                "acceptance_criteria": [
                    "the physical divider is visible",
                    "the subtitle area is empty",
                ],
            },
        },
        session_id="session-1",
        store=store,
    ))

    assert payload["success"] is True
    assert payload["replan_revision"] == 1


def test_replan_shot_contract_rejects_premature_redesign(tmp_path) -> None:
    store, _context_value, _shot = _context(tmp_path)

    payload = json.loads(story_video_quality_control(
        {
            "action": "replan_shot_contract",
            "shot_id": "S00_SH00",
            "redesigned_shot": {
                "subject": "a different subject",
                "action": "a different action",
                "evidence_detail": "different evidence",
                "shot_scale": "medium",
                "camera_angle": "eye level",
                "focal_point": "new focal point",
                "subtitle_safe_area": "lower third clear",
                "acceptance_criteria": ["new evidence is visible"],
            },
        },
        session_id="session-1",
        store=store,
    ))

    assert payload["success"] is False
    assert payload["error_type"] == "story_video_quality_contract_error"
    assert "only allowed after visual repair strategies are exhausted" in payload[
        "error"
    ]


def test_next_batch_work_stops_after_bounded_contract_replans(tmp_path) -> None:
    store, context, shot = _context(tmp_path)
    contract_hash = _shot_contract_hash(shot)
    exhausted = {
        "shot_id": "S00_SH00",
        "candidate_id": "S00_SH00_DOC_C01",
        "status": "quality_budget_exhausted",
        "selected": False,
        "repair_strategy": "documentary_context",
        "hard_blockers": ["the evidence is still not visible"],
        "blocker_codes": ["other"],
        "shot_contract_hash": contract_hash,
    }
    attempts = [
        {
            **exhausted,
            "candidate_id": "S00_SH00_CONTEXT_C01",
            "repair_strategy": "contextual_replan",
        },
        exhausted,
    ]
    replans = [
        {"shot_id": "S00_SH00", "revision": 1},
        {"shot_id": "S00_SH00", "revision": 2},
    ]
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps({
            "outputs": [exhausted],
            "attempt_history": attempts,
            "contract_replans": replans,
        }),
        encoding="utf-8",
    )

    payload = json.loads(story_video_quality_control(
        {"action": "next_batch_work"}, session_id="session-1", store=store
    ))

    assert payload["success"] is False
    assert payload["work_status"] == "human_review_required"
    assert payload["shot_id"] == "S00_SH00"
    assert payload["replan_revision"] == 2
    assert payload["error"] == "Automatic shot-contract replanning exhausted."


def test_auto_mode_uses_continuity_hold_after_contract_replans_exhausted(
    tmp_path,
) -> None:
    store, context, shot = _context(tmp_path)
    ledger_path = context.project_dir / "scene_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    previous_shot = {
        **shot,
        "shot_id": "S00_SH_PREV",
        "narration_text": "前一個已通過的鏡頭。",
        "subject": "可信的前景環境",
    }
    ledger["scenes"][0]["shots"] = [previous_shot, shot]
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    context = store.update(context, phase="batch", auto_mode=True)

    previous_path = context.project_dir / "images" / "S00_SH_PREV.png"
    previous_path.parent.mkdir(parents=True, exist_ok=True)
    previous_path.write_bytes(b"selected-openai-source")
    failed_path = context.project_dir / "images_candidates" / "S00_SH00_C02.png"
    failed_path.parent.mkdir(parents=True, exist_ok=True)
    failed_path.write_bytes(b"scientifically-unsafe-candidate")
    current_hash = _shot_contract_hash(shot)
    failed = {
        "shot_id": "S00_SH00",
        "candidate_id": "S00_SH00_C02",
        "status": "quality_budget_exhausted",
        "selected": False,
        "repair_strategy": "targeted_repair",
        "shot_contract_hash": current_hash,
        "provider": "openai-codex",
        "candidate_path": str(failed_path),
        "local_path": str(failed_path),
        "quality_score": 84.05,
        "hard_blockers": ["the scientific branch geometry is disconnected"],
        "blocker_codes": ["anatomy_geometry", "scientific_identity"],
        "vision_evidence": {"status": "PASS", "response_id": "resp_failed"},
    }
    attempts = [
        {**failed, "candidate_id": "S00_SH00_C01"},
        failed,
    ]
    previous = {
        "shot_id": "S00_SH_PREV",
        "candidate_id": "S00_SH_PREV_C01",
        "status": "selected_current",
        "selected": True,
        "shot_contract_hash": _shot_contract_hash(previous_shot),
        "provider": "openai-codex",
        "judge_provider": "openai-codex",
        "candidate_path": str(previous_path),
        "local_path": str(previous_path),
        "quality_score": 91.0,
        "hard_blockers": [],
        "blocker_codes": [],
        "vision_evidence": {"status": "PASS", "response_id": "resp_previous"},
    }
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps({
            "outputs": [previous, failed],
            "attempt_history": attempts,
            "contract_replans": [
                {"shot_id": "S00_SH00", "revision": 1},
                {"shot_id": "S00_SH00", "revision": 2},
            ],
        }),
        encoding="utf-8",
    )

    payload = json.loads(story_video_quality_control(
        {"action": "next_batch_work"}, session_id="session-1", store=store
    ))

    assert payload["work_status"] == "complete"
    manifest = json.loads(
        (manifests / "shot_candidate_manifest.json").read_text(encoding="utf-8")
    )
    selected = next(
        row for row in manifest["outputs"] if row["shot_id"] == "S00_SH00"
    )
    assert selected["selected"] is True
    assert selected["status"] == "selected_current"
    assert selected["candidate_id"] == "S00_SH00_CONTINUITY_HOLD"
    assert selected["auto_terminal_fallback"]["type"] == "continuity_hold"
    assert selected["auto_terminal_fallback"]["source_shot_id"] == "S00_SH_PREV"
    assert selected["final_qc_review_required"] is True
    assert (context.project_dir / selected["local_path"]).read_bytes() == (
        previous_path.read_bytes()
    )


def test_auto_mode_uses_best_available_draft_when_no_continuity_source(
    tmp_path,
) -> None:
    store, context, shot = _context(tmp_path)
    context = store.update(context, phase="batch", auto_mode=True)
    candidate = _candidate(context, "S00_SH00_C02")
    failed = {
        "shot_id": "S00_SH00",
        "candidate_id": candidate["candidate_id"],
        "status": "quality_budget_exhausted",
        "selected": False,
        "repair_strategy": "targeted_repair",
        "shot_contract_hash": _shot_contract_hash(shot),
        "provider": "openai-codex",
        "candidate_path": candidate["path"],
        "local_path": candidate["path"],
        "quality_score": 81.0,
        "hard_blockers": ["the first-shot evidence remains ambiguous"],
        "blocker_codes": ["scientific_identity"],
        "vision_evidence": {"status": "PASS", "response_id": "resp_failed"},
    }
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps({
            "outputs": [failed],
            "attempt_history": [
                {**failed, "candidate_id": "S00_SH00_C01", "quality_score": 72.0},
                failed,
            ],
            "contract_replans": [
                {"shot_id": "S00_SH00", "revision": 1},
                {"shot_id": "S00_SH00", "revision": 2},
            ],
        }),
        encoding="utf-8",
    )

    payload = json.loads(story_video_quality_control(
        {"action": "next_batch_work"}, session_id="session-1", store=store
    ))

    assert payload["work_status"] == "complete"
    manifest = json.loads(
        (manifests / "shot_candidate_manifest.json").read_text(encoding="utf-8")
    )
    selected = manifest["outputs"][0]
    assert selected["candidate_id"] == "S00_SH00_BEST_AVAILABLE_DRAFT"
    assert selected["auto_terminal_fallback"]["type"] == "best_available_draft"
    assert selected["final_qc_review_required"] is True
    assert selected["image_qc_blocker_codes"] == ["scientific_identity"]


def test_end_to_end_budget_never_forces_a_hard_blocked_draft(tmp_path) -> None:
    store, context, shot = _context(tmp_path)
    context = store.update(context, phase="batch", auto_mode=True)
    candidate = _candidate(context, "S00_SH00_C02")
    failed = {
        "shot_id": "S00_SH00",
        "candidate_id": candidate["candidate_id"],
        "status": "quality_budget_exhausted",
        "selected": False,
        "shot_contract_hash": _shot_contract_hash(shot),
        "provider": "openai-codex",
        "candidate_path": candidate["path"],
        "local_path": candidate["path"],
        "quality_score": 81.0,
        "hard_blockers": ["the first-shot evidence remains ambiguous"],
        "blocker_codes": ["scientific_identity"],
        "vision_evidence": {"status": "PASS", "response_id": "resp_failed"},
    }
    manifest = {
        "outputs": [failed],
        "attempt_history": [failed],
    }

    updated = _promote_auto_terminal_fallbacks(
        context,
        manifest,
        shot_ids=["S00_SH00"],
        force_exhausted_shot_ids=["S00_SH00"],
    )

    assert updated["outputs"][0]["selected"] is False
    assert updated["outputs"][0]["hard_blockers"] == [
        "the first-shot evidence remains ambiguous"
    ]


def test_end_to_end_budget_accepts_only_clean_bounded_best_effort(tmp_path) -> None:
    store, context, shot = _context(tmp_path)
    context = store.update(context, phase="batch", auto_mode=True)
    candidate = _candidate(context, "S00_SH00_C02")
    failed = {
        "shot_id": "S00_SH00",
        "candidate_id": candidate["candidate_id"],
        "status": "quality_budget_exhausted",
        "selected": False,
        "shot_contract_hash": _shot_contract_hash(shot),
        "provider": "openai-codex",
        "candidate_path": candidate["path"],
        "local_path": candidate["path"],
        "quality_score": 78.0,
        "hard_blockers": [],
        "blocker_codes": [],
        "vision_evidence": {"status": "PASS", "response_id": "resp_clean"},
    }
    manifest = {"outputs": [failed], "attempt_history": [failed]}

    updated = _promote_auto_terminal_fallbacks(
        context,
        manifest,
        shot_ids=["S00_SH00"],
        force_exhausted_shot_ids=["S00_SH00"],
    )

    assert updated["outputs"][0]["selected"] is True
    assert updated["outputs"][0]["auto_terminal_fallback"]["type"] == (
        "best_available_draft"
    )


def test_next_batch_work_replans_after_three_candidates_for_one_contract(tmp_path) -> None:
    store, context, shot = _context(tmp_path)
    contract_hash = _shot_contract_hash(shot)
    attempts = [
        {
            "shot_id": "S00_SH00",
            "candidate_id": f"S00_SH00_C{index:02d}",
            "status": "quality_budget_exhausted" if index == 3 else "repair_required",
            "selected": False,
            "repair_strategy": "targeted_repair",
            "hard_blockers": ["scientific identity remains ambiguous"],
            "blocker_codes": ["scientific_identity"],
            "shot_contract_hash": contract_hash,
        }
        for index in range(1, 4)
    ]
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps({"outputs": [attempts[-1]], "attempt_history": attempts}),
        encoding="utf-8",
    )

    payload = json.loads(story_video_quality_control(
        {"action": "next_batch_work"}, session_id="session-1", store=store
    ))

    assert payload["operation"] == "replan_shot_contract"
    assert payload["candidate_budget_exhausted"] is True


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


def test_next_batch_work_resets_output_when_scene_ledger_contract_changed(
    tmp_path,
) -> None:
    store, context, shot = _context(tmp_path)
    stale = _candidate(context, "S00_SH00_C01")
    stale_row = {
        "shot_id": "S00_SH00",
        "shot_scale": "establishing",
        "candidate_id": "S00_SH00_C01",
        "selected": False,
        "status": "quality_budget_exhausted",
        "provider": "openai-codex",
        "candidate_path": stale["path"],
        "quality_score": 70.0,
        "hard_blockers": ["no visible action"],
        "blocker_codes": ["missing_story_moment"],
        "generation_prompt": (
            "Primary subject: an old ash valley. Observable action: slow camera push."
        ),
    }
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    manifest_path = manifests / "shot_candidate_manifest.json"
    manifest_path.write_text(
        json.dumps({"outputs": [stale_row], "attempt_history": [stale_row]}),
        encoding="utf-8",
    )

    payload = json.loads(story_video_quality_control(
        {"action": "next_batch_work"}, session_id="session-1", store=store
    ))

    current_hash = _shot_contract_hash(shot)
    assert payload["work_status"] == "ready"
    assert payload["operation"] == "generate"
    assert payload["repair_strategy"] == "initial"
    assert payload["shot_contract_hash"] == current_hash
    assert current_hash[:8].upper() in payload["candidate_id_hint"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["outputs"] == []
    assert manifest["attempt_history"] == [stale_row]
    assert manifest["contract_events"][0]["event"] == "shot_contract_superseded"
    assert manifest["contract_events"][0]["shot_id"] == "S00_SH00"


def test_contract_reset_takes_priority_over_stale_selected_rejudges(tmp_path) -> None:
    store, context, shot = _context(tmp_path)
    ledger_path = context.project_dir / "scene_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger.update({
        "quality_contract_version": 3,
        "audience_profile": {"age_band": "general"},
        "engagement_profile": {"mode": "discovery_documentary"},
    })
    second = {**shot, "shot_id": "S00_SH01", "subject": "second subject"}
    ledger["scenes"][0]["shots"].append(second)
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    stale_changed = {
        "shot_id": "S00_SH00",
        "shot_scale": "establishing",
        "candidate_id": "S00_SH00_OLD_C01",
        "selected": False,
        "status": "quality_budget_exhausted",
        "provider": "openai-codex",
    }
    selected_stale_review = {
        "shot_id": "S00_SH01",
        "candidate_id": "S00_SH01_C01",
        "selected": True,
        "status": "selected_current",
        "provider": "openai-codex",
        "local_path": "images/S00_SH01.png",
        "quality_dimensions": {"text_alignment": 90},
    }
    selected_path = context.project_dir / "images" / "S00_SH01.png"
    selected_path.parent.mkdir(parents=True, exist_ok=True)
    selected_path.write_bytes(b"selected")
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps({
            "outputs": [stale_changed, selected_stale_review],
            "attempt_history": [stale_changed, selected_stale_review],
        }),
        encoding="utf-8",
    )

    payload = json.loads(story_video_quality_control(
        {"action": "next_batch_work"}, session_id="session-1", store=store
    ))

    assert payload["shot_id"] == "S00_SH00"
    assert payload["operation"] == "generate"
    assert payload["contract_reset"] is True


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


def test_next_batch_work_grandfathers_clean_legacy_selection(
    tmp_path,
) -> None:
    store, context, shot = _context(tmp_path)
    ledger_path = context.project_dir / "scene_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger.update(
        {
            "quality_contract_version": 3,
            "audience_profile": {
                "age_band": "general",
                "knowledge_level": "newcomer",
                "attention_style": "curious_explorer",
                "safety_intensity": "standard",
            },
            "engagement_profile": {
                "mode": "discovery_documentary",
                "energy": "balanced",
                "humor": "none",
                "sensationalism_forbidden": True,
            },
        }
    )
    shot.update(
        {
            "engagement_role": "reveal",
            "attention_hook": "足跡如何留下",
            "story_moment": "腳掌剛離開泥面",
            "action_consequence": "清楚足跡留在地面",
            "composition_energy": "curious",
            "viewer_emotion": "discovery",
            "engagement_criteria": ["foot and track form a readable causal instant"],
            "visual_truth_mode": "reconstruction",
        }
    )
    ledger["scenes"][0]["shots"][0] = shot
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    candidate = _candidate(context, "S00_SH00_C01")
    legacy_dimensions = _dimensions(88)
    legacy_dimensions.pop("narrative_engagement")
    legacy_dimensions.pop("story_moment_clarity")
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps(
            {
                "shots": [
                    {
                        "shot_id": "S00_SH00",
                        "prompt": "Legacy prompt bound to the selected image.",
                    }
                ],
                "outputs": [
                    {
                        "shot_id": "S00_SH00",
                        "candidate_id": "S00_SH00_C01",
                        "selected": True,
                        "status": "selected_current",
                        "provider": "openai-codex",
                        "model": "gpt-image-2-high",
                        "generation_response_id": "img_old",
                        "candidate_path": candidate["path"],
                        "local_path": candidate["path"],
                        "repair_round": 1,
                        "quality_dimensions": legacy_dimensions,
                        "quality_score": 88.0,
                        "hard_blockers": [],
                        "blocker_codes": [],
                        "vision_evidence": {"status": "PASS", "response_id": "resp_old"},
                        "shot_contract_hash": _shot_contract_hash(shot),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        story_video_quality_control(
            {"action": "next_batch_work"},
            session_id="session-1",
            store=store,
        )
    )

    assert payload["work_status"] == "complete"
    manifest = json.loads(
        (manifests / "shot_candidate_manifest.json").read_text(encoding="utf-8")
    )
    selected = manifest["outputs"][0]
    assert selected["legacy_qc_grandfathered"] is True
    assert selected["quality_contract_version"] == 2
    assert manifest["selection_events"][0]["event"] == "legacy_qc_grandfathered"


def test_legacy_rejudge_ignores_exhausted_generation_strategies(tmp_path) -> None:
    store, context, shot = _context(tmp_path)
    ledger_path = context.project_dir / "scene_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["quality_contract_version"] = 3
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    contract_hash = _shot_contract_hash(shot)
    candidate = _candidate(context, "S00_SH00_DOC_C01")
    legacy_dimensions = _dimensions(76)
    legacy_dimensions.pop("narrative_engagement")
    legacy_dimensions.pop("story_moment_clarity")
    strategies = (
        "layout_reset",
        "evidence_reframe",
        "contextual_replan",
        "documentary_context",
    )
    attempts = [
        {
            "shot_id": "S00_SH00",
            "candidate_id": f"S00_SH00_{strategy.upper()}_C01",
            "status": "quality_budget_exhausted",
            "selected": False,
            "repair_strategy": strategy,
            "hard_blockers": ["the generated evidence is not credible"],
            "blocker_codes": ["other"],
            "shot_contract_hash": contract_hash,
        }
        for strategy in strategies
    ]
    selected = {
        **attempts[-1],
        "candidate_id": "S00_SH00_DOC_C01",
        "selected": True,
        "status": "selected_current",
        "provider": "openai-codex",
        "model": "gpt-image-2-high",
        "generation_response_id": "img_selected",
        "candidate_path": candidate["path"],
        "local_path": candidate["path"],
        "quality_dimensions": legacy_dimensions,
        "quality_score": 76.0,
        "hard_blockers": [],
        "vision_evidence": {"status": "PASS", "response_id": "resp_old"},
    }
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps(
            {
                "outputs": [selected],
                "attempt_history": attempts,
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        story_video_quality_control(
            {"action": "next_batch_work"},
            session_id="session-1",
            store=store,
        )
    )

    assert payload["success"] is True
    assert payload["work_status"] == "complete"
    manifest = json.loads(
        (manifests / "shot_candidate_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["outputs"][0]["legacy_qc_grandfathered"] is True


def test_legacy_rejudge_falls_back_to_existing_project_local_asset(tmp_path) -> None:
    store, context, shot = _context(tmp_path)
    ledger_path = context.project_dir / "scene_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger.update(
        {
            "quality_contract_version": 3,
            "audience_profile": {
                "age_band": "general",
                "knowledge_level": "newcomer",
                "attention_style": "curious_explorer",
                "safety_intensity": "standard",
            },
            "engagement_profile": {
                "mode": "discovery_documentary",
                "energy": "balanced",
                "humor": "none",
                "sensationalism_forbidden": True,
            },
        }
    )
    shot.update(
        {
            "engagement_role": "reveal",
            "attention_hook": "看見結果",
            "story_moment": "結果剛形成",
            "action_consequence": "證據清楚可見",
            "composition_energy": "curious",
            "viewer_emotion": "discovery",
            "engagement_criteria": ["result is readable"],
            "visual_truth_mode": "direct_evidence",
        }
    )
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    local_asset = context.project_dir / "images" / "S00_SH00.png"
    local_asset.parent.mkdir(parents=True, exist_ok=True)
    local_asset.write_bytes(b"selected")
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps(
            {
                "outputs": [
                    {
                        "shot_id": "S00_SH00",
                        "candidate_id": "S00_SH00_C01",
                        "selected": True,
                        "status": "selected_current",
                        "provider": "openai-codex",
                        "candidate_path": "cache/removed.png",
                        "local_path": "images/S00_SH00.png",
                        "quality_contract_version": 3,
                        "quality_dimensions": _dimensions(90),
                        "focal_point_normalized": {"x": 0.5, "y": 0.5},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        story_video_quality_control(
            {"action": "next_batch_work"},
            session_id="session-1",
            store=store,
        )
    )

    assert payload["operation"] == "rejudge_existing"
    assert payload["candidate"]["path"] == "images/S00_SH00.png"


def test_next_batch_work_promotes_stored_clean_candidate_after_strategy_exhaustion(
    tmp_path,
) -> None:
    store, context, _shot = _context(tmp_path)
    candidate = _candidate(context, "S00_SH00_DOC_C01")
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    attempts = [
        {
            "shot_id": "S00_SH00",
            "candidate_id": "S00_SH00_EVIDENCE_C01",
            "status": "quality_budget_exhausted",
            "repair_strategy": "evidence_reframe",
            "hard_blockers": ["malformed anatomy"],
            "blocker_codes": ["anatomy_geometry"],
        },
        {
            "shot_id": "S00_SH00",
            "candidate_id": "S00_SH00_CONTEXT_C01",
            "status": "quality_budget_exhausted",
            "repair_strategy": "contextual_replan",
            "hard_blockers": ["subtitle collision"],
            "blocker_codes": ["subtitle_collision"],
        },
        {
            "shot_id": "S00_SH00",
            "candidate_id": "S00_SH00_DOC_C01",
            "status": "quality_budget_exhausted",
            "repair_strategy": "documentary_context",
            "provider": "openai-codex",
            "candidate_path": candidate["path"],
            "local_path": candidate["path"],
            "quality_score": 76.0,
            "hard_blockers": [],
            "blocker_codes": ["other"],
            "vision_evidence": {"status": "PASS", "response_id": "resp_qc"},
        },
    ]
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps({"outputs": [attempts[-1]], "attempt_history": attempts}),
        encoding="utf-8",
    )

    payload = json.loads(story_video_quality_control(
        {"action": "next_batch_work"}, session_id="session-1", store=store
    ))

    assert payload["work_status"] == "complete"
    assert (context.project_dir / "images" / "S00_SH00.png").is_file()
    manifest = json.loads(
        (manifests / "shot_candidate_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["outputs"][0]["selected"] is True
    assert manifest["outputs"][0]["status"] == "selected_current"
    assert manifest["outputs"][0]["best_effort_selected"] is True
    assert manifest["selection_events"][0]["candidate_id"] == "S00_SH00_DOC_C01"


def test_next_batch_work_rejudges_prior_clean_camera_reveal_after_bad_repair_loop(
    tmp_path,
) -> None:
    store, context, shot = _context(tmp_path)
    shot.update({
        "shot_scale": "establishing",
        "action": "低空緩慢推進",
        "story_moment": "鏡頭低空推進後揭示整座荒涼河谷",
        "visual_truth_mode": "reconstruction",
    })
    ledger_path = context.project_dir / "scene_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["scenes"][0]["shots"][0] = shot
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    prior = _candidate(context, "S00_SH00_C01")
    attempts = [
        {
            "shot_id": "S00_SH00",
            "candidate_id": "S00_SH00_C01",
            "selected": True,
            "status": "selected_current",
            "provider": "openai-codex",
            "candidate_path": prior["path"],
            "local_path": prior["path"],
            "quality_score": 88.0,
            "hard_blockers": [],
            "vision_evidence": {"status": "PASS", "response_id": "resp_original"},
            "generation_prompt": "original camera reveal prompt",
            "quality_dimensions": _dimensions(88),
        },
        {
            "shot_id": "S00_SH00",
            "candidate_id": "S00_SH00_TRUTH_C01",
            "status": "quality_budget_exhausted",
            "repair_strategy": "truth_reframe",
            "hard_blockers": ["mixed evidence and reconstruction"],
            "blocker_codes": ["mixed_evidence_reconstruction"],
        },
        {
            "shot_id": "S00_SH00",
            "candidate_id": "S00_SH00_STORY_C01",
            "status": "quality_budget_exhausted",
            "repair_strategy": "story_reframe",
            "hard_blockers": ["no visible action"],
            "blocker_codes": ["missing_story_moment"],
        },
        {
            "shot_id": "S00_SH00",
            "candidate_id": "S00_SH00_AUDIENCE_C01",
            "status": "quality_budget_exhausted",
            "repair_strategy": "audience_reframe",
            "hard_blockers": ["no visible action"],
            "blocker_codes": ["missing_story_moment"],
        },
    ]
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps({"outputs": [attempts[-1]], "attempt_history": attempts}),
        encoding="utf-8",
    )

    payload = json.loads(story_video_quality_control(
        {"action": "next_batch_work"}, session_id="session-1", store=store
    ))

    assert payload["work_status"] == "ready"
    assert payload["operation"] == "rejudge_existing"
    assert payload["candidate_budget"] == 0
    assert payload["candidate"]["candidate_id"] == "S00_SH00_C01_CAMERA_REVEAL_REVIEW"
    candidate_path = Path(payload["candidate"]["path"])
    if not candidate_path.is_absolute():
        candidate_path = context.project_dir / candidate_path
    assert candidate_path.resolve() == Path(prior["path"]).resolve()
    assert payload["candidate"]["generation_prompt"] == "original camera reveal prompt"


def test_next_batch_work_treats_subtitle_collision_as_post_composite_qc(
    tmp_path,
) -> None:
    store, context, _shot = _context(tmp_path)
    candidate = _candidate(context, "S00_SH00_DOC_C01")
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    attempts = [
        {
            "shot_id": "S00_SH00",
            "candidate_id": "S00_SH00_LAYOUT_C01",
            "status": "quality_budget_exhausted",
            "repair_strategy": "layout_reset",
            "hard_blockers": ["bottom subtitle band is occupied"],
            "blocker_codes": ["subtitle_collision"],
        },
        {
            "shot_id": "S00_SH00",
            "candidate_id": "S00_SH00_CONTEXT_C01",
            "status": "quality_budget_exhausted",
            "repair_strategy": "contextual_replan",
            "hard_blockers": ["bottom subtitle band is occupied"],
            "blocker_codes": ["subtitle_collision"],
        },
        {
            "shot_id": "S00_SH00",
            "candidate_id": "S00_SH00_DOC_C01",
            "status": "quality_budget_exhausted",
            "repair_strategy": "documentary_context",
            "provider": "openai-codex",
            "candidate_path": candidate["path"],
            "local_path": candidate["path"],
            "quality_score": 82.0,
            "hard_blockers": ["bottom subtitle band is occupied"],
            "blocker_codes": ["subtitle_collision"],
            "vision_evidence": {"status": "PASS", "response_id": "resp_qc"},
        },
    ]
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps({"outputs": [attempts[-1]], "attempt_history": attempts}),
        encoding="utf-8",
    )

    payload = json.loads(story_video_quality_control(
        {"action": "next_batch_work"}, session_id="session-1", store=store
    ))

    assert payload["work_status"] == "complete"
    manifest = json.loads(
        (manifests / "shot_candidate_manifest.json").read_text(encoding="utf-8")
    )
    selected = manifest["outputs"][0]
    assert selected["selected"] is True
    assert selected["packaging_fallback"] is None
    assert selected["hard_blockers"] == []
    assert selected["ignored_source_image_qc_blockers"] == [
        "bottom subtitle band is occupied"
    ]
    assert selected["post_composite_subtitle_qc"] is True
    assert selected["best_effort_quality_floor"] == 75.0
    assert manifest["selection_events"][0]["quality_floor"] == 75.0


def test_next_batch_work_ignores_subtitle_layout_at_replanned_contract_cap(
    tmp_path,
) -> None:
    store, context, shot = _context(tmp_path)
    contract_hash = _shot_contract_hash(shot)
    candidate = _candidate(context, "S00_SH00_REPLAN_C02")
    attempts = [
        {
            "shot_id": "S00_SH00",
            "candidate_id": "S00_SH00_REPLAN_C01",
            "status": "repair_required",
            "repair_strategy": "initial",
            "shot_contract_hash": contract_hash,
            "hard_blockers": ["bottom subtitle band is occupied"],
            "blocker_codes": ["subtitle_collision"],
        },
        {
            "shot_id": "S00_SH00",
            "candidate_id": candidate["candidate_id"],
            "status": "repair_required",
            "repair_strategy": "targeted_repair",
            "shot_contract_hash": contract_hash,
            "provider": "openai-codex",
            "candidate_path": candidate["path"],
            "local_path": candidate["path"],
            "quality_score": 89.7,
            "hard_blockers": ["bottom subtitle band is occupied"],
            "blocker_codes": ["subtitle_collision"],
            "vision_evidence": {"status": "PASS", "response_id": "resp_qc"},
        },
    ]
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps({
            "outputs": [attempts[-1]],
            "attempt_history": attempts,
            "contract_replans": [
                {"shot_id": "S00_SH00", "revision": 1},
                {"shot_id": "S00_SH00", "revision": 2},
            ],
        }),
        encoding="utf-8",
    )

    payload = json.loads(story_video_quality_control(
        {"action": "next_batch_work"}, session_id="session-1", store=store
    ))

    assert payload["work_status"] == "complete"
    manifest = json.loads(
        (manifests / "shot_candidate_manifest.json").read_text(encoding="utf-8")
    )
    selected = manifest["outputs"][0]
    assert selected["selected"] is True
    assert selected["status"] == "selected_current"
    assert selected["packaging_fallback"] is None
    assert selected["ignored_source_image_qc_blocker_codes"] == [
        "subtitle_collision"
    ]


def test_judge_uses_candidate_prompt_after_repair_plan_is_exhausted(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    candidate = _candidate(context, "S00_SH00_MANUAL_C01")
    candidate["prompt"] = "Bound compiled prompt used to generate this exact candidate."
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    attempts = [
        {
            "shot_id": "S00_SH00",
            "candidate_id": f"S00_SH00_{strategy}",
            "status": "quality_budget_exhausted",
            "repair_strategy": strategy,
            "hard_blockers": ["subtitle collision"],
            "blocker_codes": ["subtitle_collision"],
        }
        for strategy in ("layout_reset", "contextual_replan", "documentary_context")
    ]
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps({"outputs": [attempts[-1]], "attempt_history": attempts}),
        encoding="utf-8",
    )
    llm = FakeLlm([
        {
            "candidate_id": candidate["candidate_id"],
            "dimensions": _dimensions(90),
            "hard_blockers": [],
            "evidence": ["The focal evidence is clear and the frame is usable."],
        }
    ])

    payload = json.loads(story_video_quality_control(
        {
            "action": "judge_candidates",
            "shot_id": "S00_SH00",
            "repair_round": 1,
            "candidates": [candidate],
        },
        session_id="session-1",
        store=store,
        llm=llm,
    ))

    assert payload["success"] is True
    assert payload["selected_candidate_id"] == candidate["candidate_id"]
    assert "Bound compiled prompt" in llm.calls[0]["input"][0]["text"]


def test_judge_prefers_candidate_bound_prompt_over_mutable_repair_prompt(
    tmp_path,
) -> None:
    store, context, _shot = _context(tmp_path)
    candidate = _candidate(context, "S00_SH00_C01_V3_REVIEW")
    candidate["generation_prompt"] = (
        "Original environment prompt bound to this exact selected image."
    )
    llm = FakeLlm([
        {
            "candidate_id": candidate["candidate_id"],
            "dimensions": _dimensions(90),
            "hard_blockers": [],
            "evidence": ["The original contracted environment is clearly visible."],
        }
    ])

    payload = json.loads(story_video_quality_control(
        {
            "action": "judge_candidates",
            "shot_id": "S00_SH00",
            "repair_round": 1,
            "candidates": [candidate],
        },
        session_id="session-1",
        store=store,
        llm=llm,
    ))

    assert payload["success"] is True
    review_text = llm.calls[0]["input"][0]["text"]
    assert "Original environment prompt" in review_text
    assert "Viewer takeaway:" not in review_text
    manifest = json.loads(
        (context.project_dir / "manifests" / "shot_candidate_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["outputs"][0]["generation_prompt"] == (
        candidate["generation_prompt"]
    )


def test_judge_ignores_subtitle_collision_for_clean_source_image_qc(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    candidate = _candidate(context, "S00_SH00_MANUAL_C01")
    candidate["prompt"] = "Bound compiled prompt for a subtitle-layout retry."
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    attempts = [
        {
            "shot_id": "S00_SH00",
            "candidate_id": f"S00_SH00_{strategy}",
            "status": "quality_budget_exhausted",
            "repair_strategy": strategy,
            "hard_blockers": ["bottom subtitle band is occupied"],
            "blocker_codes": ["subtitle_collision"],
        }
        for strategy in ("layout_reset", "contextual_replan", "documentary_context")
    ]
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps({"outputs": [attempts[-1]], "attempt_history": attempts}),
        encoding="utf-8",
    )
    llm = FakeLlm([
        {
            "candidate_id": candidate["candidate_id"],
            "dimensions": _dimensions(88),
            "hard_blockers": ["bottom subtitle band is occupied"],
            "blocker_codes": ["subtitle_collision"],
            "evidence": ["The image is strong except for the declared subtitle band."],
        }
    ])

    payload = json.loads(story_video_quality_control(
        {
            "action": "judge_candidates",
            "shot_id": "S00_SH00",
            "repair_round": 1,
            "candidates": [candidate],
        },
        session_id="session-1",
        store=store,
        llm=llm,
    ))

    assert payload["success"] is True
    assert payload["packaging_fallback_selected"] is False
    manifest = json.loads(
        (manifests / "shot_candidate_manifest.json").read_text(encoding="utf-8")
    )
    selected = manifest["outputs"][0]
    assert selected["packaging_fallback"] is None
    assert selected["hard_blockers"] == []
    assert selected["blocker_codes"] == []


def test_next_batch_work_carries_adaptive_repair_strategy(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "shot_candidate_manifest.json").write_text(json.dumps({
        "outputs": [{
            "shot_id": "S00_SH00", "status": "quality_budget_exhausted",
            "selected": False, "repair_round": 1, "strategy_reset": True,
            "hard_blockers": ["科學與解剖辨識不足", "牙齒幾何疑似失真"],
        }]
    }), encoding="utf-8")

    payload = json.loads(story_video_quality_control(
        {"action": "next_batch_work"}, session_id="session-1", store=store
    ))

    assert payload["work_status"] == "ready"
    assert payload["operation"] == "repair"
    assert payload["repair_strategy"] == "evidence_reframe"
    assert payload["candidate_id_hint"] == "S00_SH00_EVIDENCE_C01"


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


def test_third_failed_round_reports_quality_budget_exhausted(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    llm = FakeLlm(
        [
            {
                "candidate_id": "S00_SH00_C03",
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
                "candidates": [_candidate(context, "S00_SH00_C03")],
                "repair_round": 3,
            },
            session_id="session-1",
            store=store,
        )
    )

    assert payload["success"] is False
    assert payload["status"] == "quality_budget_exhausted"
    assert payload["repair_round"] == 3


def test_candidate_suffix_can_select_when_only_subtitle_layout_was_flagged(
    tmp_path,
) -> None:
    store, context, _shot = _context(tmp_path)
    llm = FakeLlm(
        [
            {
                "candidate_id": "S00_SH00_C03",
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
                "candidates": [_candidate(context, "S00_SH00_C03")],
                "repair_round": 1,
            },
            session_id="session-1",
            store=store,
            llm=llm,
        )
    )

    assert payload["success"] is True
    assert payload["status"] == "selected"
    assert payload["selected_candidate_id"] == "S00_SH00_C03"
    assert payload["repair_round"] == 3


def test_layout_strategy_candidate_is_selected_when_only_subtitle_layout_was_flagged(
    tmp_path,
) -> None:
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

    assert payload["success"] is True
    assert payload["status"] == "selected"
    manifest = json.loads(
        (context.project_dir / "manifests" / "shot_candidate_manifest.json").read_text()
    )
    assert manifest["outputs"][0]["strategy_reset"] is True
    assert manifest["outputs"][0]["hard_blockers"] == []


def test_clean_final_semantic_candidate_is_selected_at_bounded_floor(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    attempts = [
        {
            "shot_id": "S00_SH00",
            "candidate_id": "S00_SH00_EVIDENCE_C01",
            "status": "quality_budget_exhausted",
            "repair_strategy": "evidence_reframe",
            "hard_blockers": ["malformed anatomy"],
            "blocker_codes": ["anatomy_geometry"],
        },
        {
            "shot_id": "S00_SH00",
            "candidate_id": "S00_SH00_CONTEXT_C01",
            "status": "quality_budget_exhausted",
            "repair_strategy": "contextual_replan",
            "hard_blockers": ["subtitle collision"],
            "blocker_codes": ["subtitle_collision"],
        },
    ]
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps({"outputs": [attempts[-1]], "attempt_history": attempts}),
        encoding="utf-8",
    )
    candidate = _candidate(context, "S00_SH00_DOC_C01")
    candidate["repair_strategy"] = "documentary_context"
    llm = FakeLlm([{
        "candidate_id": "S00_SH00_DOC_C01",
        "hard_blockers": [],
        "blocker_codes": [],
        "dimensions": _dimensions(76),
        "evidence": ["clean documentary context with reserved subtitle region"],
    }])

    payload = json.loads(story_video_quality_control(
        {
            "action": "judge_candidates",
            "shot_id": "S00_SH00",
            "repair_round": 1,
            "candidates": [candidate],
        },
        session_id="session-1",
        store=store,
        llm=llm,
    ))

    assert payload["success"] is True
    assert payload["status"] == "selected"
    assert payload["best_effort_selected"] is True
    assert payload["selected_candidate_id"] == "S00_SH00_DOC_C01"


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
    _release_cards(context)
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
                        "focal_point_normalized": {"x": 0.72, "y": 0.41},
                        "final_qc_review_required": True,
                        "auto_terminal_fallback": {
                            "type": "continuity_hold",
                            "source_shot_id": "S00_SH_PREV",
                        },
                        "packaging_fallback": {
                            "type": "adaptive_subtitle_band",
                            "subtitle_position": "top",
                            "resolved_blocker_codes": ["subtitle_collision"],
                        },
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
    assert render_input["post_speech_hold_sec"] == 0.18
    assert render_input["max_post_speech_hold_sec"] == 0.6
    assert render_input["motion_policy"] == "cinematic_focus_push"
    assert render_input["zoom_max"] == 1.1
    assert render_input["subtitle"]["position"] == "bottom"
    assert render_input["subtitle"]["production_stage"] == "post_composite"
    assert render_input["subtitle"]["preferred_sentences_per_cue"] == 1
    assert render_input["subtitle"]["max_sentences_per_cue"] == 2
    assert render_input["subtitle"]["min_cue_duration_sec"] == 1.5
    assert render_input["subtitle"]["hide_outside_speech"] is True
    scene = render_input["scenes"][0]
    assert scene["selected"] is True
    assert scene["audio"] == "audio/qwen/S00.wav"
    assert scene["narration"] == "直立腿讓早期恐龍移動得更有效率。"
    assert scene["shots"][0] == {
        "shot_id": "S00_SH00",
        "selected": True,
        "image": "images/S00_SH00.png",
        "narration": "直立腿讓早期恐龍移動得更有效率。",
        "subtitle_position": "bottom",
        "focus_end": {"x": 0.72, "y": 0.41},
        "final_qc_review_required": True,
        "auto_terminal_fallback": {
            "type": "continuity_hold",
            "source_shot_id": "S00_SH_PREV",
        },
    }
    assert render_input["opening_card"]["image"] == "release_art/opening_card.png"
    assert render_input["opening_card"]["duration_sec"] == 3.0
    assert render_input["ending_card"]["image"] == "release_art/ending_card.png"
    assert render_input["ending_card"]["duration_sec"] == 5.0


def test_release_art_actions_compile_cinematic_prompt_and_compose_cards(
    tmp_path, monkeypatch
) -> None:
    store, context, _shot = _context(tmp_path)
    ledger_path = context.project_dir / "scene_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["quality_contract_version"] = 4
    ledger["style_bible"] = {
        "style_id": "theatrical-discovery-v1",
        "anchor_shot_id": "S00_SH00",
        "medium": "cinematic photoreal reconstruction",
        "palette": "mineral green and volcanic amber",
        "lighting": "motivated shafts with dimensional contrast",
        "lens_language": "low 35mm hero perspective",
        "texture": "tactile skin, dust, and vegetation",
        "atmosphere": "wonder with controlled danger",
        "subject_treatment": "one dominant story action",
        "forbidden_drift": ["flat encyclopedia plate"],
    }
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    anchor = context.project_dir / "images_candidates" / "S00_SH00" / "anchor.png"
    anchor.parent.mkdir(parents=True, exist_ok=True)
    anchor.write_bytes(b"approved-style-anchor")
    manifest_path = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "outputs": [
                    {
                        "shot_id": "S00_SH00",
                        "local_path": str(anchor.relative_to(context.project_dir)),
                        "provider": "openai-codex",
                        "selected": True,
                        "status": "selected_current",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "plugins.story_video.release_art._font",
        lambda size, *, bold=False: ImageFont.load_default(size=size),
    )

    compiled = json.loads(
        story_video_quality_control(
            {"action": "compile_release_art"},
            session_id="session-1",
            store=store,
        )
    )

    assert compiled["success"] is True
    assert compiled["provider"] == "openai-codex"
    assert "cinematic hero image" in compiled["prompt"].lower()
    assert "no generated text" in compiled["prompt"].lower()
    assert "Style bible lock: theatrical-discovery-v1" in compiled["prompt"]
    assert compiled["reference_image_urls"] == [str(anchor)]
    source = context.project_dir / "images_candidates" / "RELEASE_HERO_C01.png"
    source.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1280, 720), (23, 71, 102)).save(source)

    registered = json.loads(
        story_video_quality_control(
            {
                "action": "register_release_art",
                "release_art_candidate": {
                    "path": str(source),
                    "provider": "openai-codex",
                    "model": "gpt-image-2-high",
                    "response_id": "img_release_01",
                },
            },
            session_id="session-1",
            store=store,
        )
    )

    assert registered["success"] is True
    for relative in (
        "release_art/hero_source.png",
        "release_art/opening_card.png",
        "release_art/ending_card.png",
        "release_art/thumbnail.jpg",
        "manifests/release_art_manifest.json",
    ):
        assert (context.project_dir / relative).is_file()
    manifest = json.loads(
        (context.project_dir / "manifests" / "release_art_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["provider"] == "openai-codex"
    assert manifest["response_id"] == "img_release_01"
    assert manifest["status"] == "PASS"
    assert manifest["run_id"] == context.run_id


def test_register_release_art_rejects_non_openai_source(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    source = context.project_dir / "candidate.png"
    Image.new("RGB", (1280, 720), "black").save(source)

    payload = json.loads(
        story_video_quality_control(
            {
                "action": "register_release_art",
                "release_art_candidate": {
                    "path": str(source),
                    "provider": "xai",
                },
            },
            session_id="session-1",
            store=store,
        )
    )

    assert payload["success"] is False
    assert "OpenAI" in payload["error"]


def test_prepare_render_fails_closed_without_dedicated_release_art(tmp_path) -> None:
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
                "outputs": [
                    {
                        "shot_id": "S00_SH00",
                        "selected": True,
                        "local_path": "images/S00_SH00.png",
                        "provider": "openai-codex",
                    }
                ]
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

    assert payload["success"] is False
    assert "dedicated release art" in payload["error"]


def test_prepare_render_rejects_release_art_from_stale_run(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    _release_cards(context)
    manifest_path = context.project_dir / "manifests" / "release_art_manifest.json"
    release_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    release_manifest["run_id"] = "stale-run"
    manifest_path.write_text(json.dumps(release_manifest), encoding="utf-8")
    image = context.project_dir / "images" / "S00_SH00.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"selected-image")
    audio = context.project_dir / "audio" / "qwen" / "S00.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"narration")
    manifests = context.project_dir / "manifests"
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps(
            {
                "outputs": [
                    {
                        "shot_id": "S00_SH00",
                        "selected": True,
                        "local_path": "images/S00_SH00.png",
                        "provider": "openai-codex",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (manifests / "narration_manifest.json").write_text(
        json.dumps(
            {
                "outputs": [
                    {
                        "scene_id": "S00",
                        "audio": "audio/qwen/S00.wav",
                        "display_text": "旁白",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        story_video_quality_control(
            {"action": "prepare_render"}, session_id="session-1", store=store
        )
    )

    assert payload["success"] is False
    assert "stale" in payload["error"].lower()


def test_prepare_render_copies_verified_segment_timing_to_matching_shot(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    _release_cards(context)
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
                "outputs": [
                    {
                        "shot_id": "S00_SH00",
                        "selected": True,
                        "local_path": "images/S00_SH00.png",
                        "provider": "openai-codex",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (manifests / "narration_manifest.json").write_text(
        json.dumps(
            {
                "schema": "story_video_narration_manifest_v4",
                "provider": "local_qwen",
                "outputs": [
                    {
                        "scene_id": "S00",
                        "audio": str(audio),
                        "display_text": (
                            "直立腿讓早期恐龍移動得更有效率。"
                            "牠們還能迅速改變方向。"
                        ),
                        "segments": [
                            {
                                "shot_id": "S00_SH00",
                                "display_text": (
                                    "直立腿讓早期恐龍移動得更有效率。"
                                    "牠們還能迅速改變方向。"
                                ),
                                "timeline_duration_sec": 4.37,
                                "speech_end_sec": 4.19,
                                "alignment_status": "PASS",
                                "pronunciation_status": "PASS",
                                "prosody_status": "PASS",
                                "voice_chunks": [
                                    {
                                        "voice_chunk_id": "S00_SH00__C01",
                                        "display_text": "直立腿讓早期恐龍移動得更有效率。",
                                        "start_sec": 0.0,
                                        "speech_end_sec": 2.41,
                                        "alignment_status": "PASS",
                                        "pronunciation_status": "PASS",
                                        "prosody_status": "PASS",
                                    },
                                    {
                                        "voice_chunk_id": "S00_SH00__C02",
                                        "display_text": "牠們還能迅速改變方向。",
                                        "start_sec": 2.59,
                                        "speech_end_sec": 4.19,
                                        "alignment_status": "PASS",
                                        "pronunciation_status": "PASS",
                                        "prosody_status": "PASS",
                                    },
                                ],
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        story_video_quality_control(
            {"action": "prepare_render"}, session_id="session-1", store=store
        )
    )

    assert payload["success"] is True
    render_input = json.loads(
        (context.project_dir / "render_input.json").read_text(encoding="utf-8")
    )
    assert render_input["scenes"][0]["shots"][0]["timeline_duration_sec"] == 4.37
    assert render_input["scenes"][0]["shots"][0]["speech_end_sec"] == 4.19
    assert render_input["scenes"][0]["shots"][0]["subtitle_timing_source"] == (
        "measured_voice_chunks"
    )
    assert render_input["scenes"][0]["shots"][0]["subtitle_cues"] == [
        {
            "text": "直立腿讓早期恐龍移動得更有效率。",
            "start_sec": 0.0,
            "end_sec": 2.41,
            "sentence_count": 1,
        },
        {
            "text": "牠們還能迅速改變方向。",
            "start_sec": 2.59,
            "end_sec": 4.19,
            "sentence_count": 1,
        },
    ]


def test_prepare_render_uses_verified_semantic_shot_groups(tmp_path) -> None:
    store, context, first_shot = _context(tmp_path)
    _release_cards(context)
    second_shot = {
        **first_shot,
        "shot_id": "S00_SH01",
        "narration_text": "牠的步態也更有效率。",
    }
    ledger_path = context.project_dir / "scene_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["scenes"][0]["shots"].append(second_shot)
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    for shot_id in ("S00_SH00", "S00_SH01"):
        image = context.project_dir / "images" / f"{shot_id}.png"
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(f"image-{shot_id}".encode())
    audio = context.project_dir / "audio" / "qwen" / "S00.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"narration")
    manifests = context.project_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "shot_candidate_manifest.json").write_text(
        json.dumps(
            {
                "outputs": [
                    {
                        "shot_id": shot_id,
                        "selected": True,
                        "local_path": f"images/{shot_id}.png",
                        "provider": "openai-codex",
                    }
                    for shot_id in ("S00_SH00", "S00_SH01")
                ]
            }
        ),
        encoding="utf-8",
    )
    (context.project_dir / "render_input.json").write_text(
        json.dumps(
            {
                "scenes": [
                    {
                        "scene_id": "S00",
                        "shots": [
                            {
                                "shot_id": "S00_SH00__S00_SH01",
                                "source_shot_ids": ["S00_SH00", "S00_SH01"],
                                "representative_shot_id": "S00_SH01",
                                "image": "images/S00_SH01.png",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (manifests / "narration_manifest.json").write_text(
        json.dumps(
            {
                "schema": "story_video_narration_manifest_v4",
                "outputs": [
                    {
                        "scene_id": "S00",
                        "audio": str(audio),
                        "display_text": (
                            "直立腿讓早期恐龍移動得更有效率。牠的步態也更有效率。"
                        ),
                        "segments": [
                            {
                                "shot_id": "S00_SH00__S00_SH01",
                                "display_text": (
                                    "直立腿讓早期恐龍移動得更有效率。"
                                    "牠的步態也更有效率。"
                                ),
                                "timeline_duration_sec": 7.25,
                                "speech_end_sec": 7.07,
                                "alignment_status": "PASS",
                                "pronunciation_status": "PASS",
                                "prosody_status": "PASS",
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        story_video_quality_control(
            {"action": "prepare_render"}, session_id="session-1", store=store
        )
    )

    assert payload["success"] is True
    render_input = json.loads(
        (context.project_dir / "render_input.json").read_text(encoding="utf-8")
    )
    assert render_input["scenes"][0]["shots"] == [
        {
            "shot_id": "S00_SH00__S00_SH01",
            "selected": True,
            "image": "images/S00_SH01.png",
                "narration": (
                    "直立腿讓早期恐龍移動得更有效率。牠的步態也更有效率。"
                ),
                "subtitle_position": "bottom",
            "source_shot_ids": ["S00_SH00", "S00_SH01"],
            "representative_shot_id": "S00_SH01",
            "timeline_duration_sec": 7.25,
            "speech_end_sec": 7.07,
        }
    ]

    narration_path = manifests / "narration_manifest.json"
    narration_manifest = json.loads(narration_path.read_text(encoding="utf-8"))
    narration_segment = narration_manifest["outputs"][0]["segments"][0]
    narration_segment["source_shot_ids"] = ["S00_SH00"]
    narration_segment["representative_shot_id"] = "S00_SH00"
    narration_path.write_text(json.dumps(narration_manifest), encoding="utf-8")

    rejected = json.loads(
        story_video_quality_control(
            {"action": "prepare_render"}, session_id="session-1", store=store
        )
    )

    assert rejected["success"] is False
    assert "semantic narration does not cover source shots: S00_SH01" in rejected["error"]


def test_prepare_render_prefers_branded_release_cards(tmp_path) -> None:
    store, context, _shot = _context(tmp_path)
    image = context.project_dir / "images" / "S00_SH00.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"selected-image")
    audio = context.project_dir / "audio" / "qwen" / "S00.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"narration")
    _release_cards(context)
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
        "duration_sec": 3.0,
        "precomposed": True,
    }
    assert render_input["ending_card"] == {
        "title": "探索仍在繼續",
        "image": "release_art/ending_card.png",
        "duration_sec": 5.0,
        "precomposed": True,
    }
