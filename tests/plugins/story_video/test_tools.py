from __future__ import annotations

import json

from plugins.story_video.audit import ProviderAudit, ProviderAuditEvent
from plugins.story_video.state import StoryVideoStateStore, parse_operator_call
from plugins.story_video.tools import story_video_control, validate_phase


def _active_context(tmp_path):
    store = StoryVideoStateStore(tmp_path)
    call = parse_operator_call("故事影片：恐龍起源｜5分｜真實照片")
    assert call is not None
    context = store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=call,
        original_request="start",
    )
    return store, context


def _quality_shots(count: int = 40) -> list[dict]:
    scales = ("close_up", "medium", "wide", "macro", "medium", "insert", "medium", "establishing")
    shots = []
    for index in range(count):
        shot_id = f"S00_SH{index:02d}"
        shots.append(
            {
                "shot_id": shot_id,
                "narration_text": f"第 {index} 個旁白片段",
                "narrative_role": "evidence",
                "viewer_takeaway": "觀眾看懂一個具體證據",
                "subject": "可辨識的主要證據",
                "action": "主體執行與旁白相符的動作",
                "evidence_detail": "關鍵細節清楚可見",
                "shot_scale": scales[index % len(scales)],
                "camera_angle": "eye level",
                "focal_point": "primary evidence",
                "subtitle_safe_area": "bottom 20 percent clear",
                "acceptance_criteria": ["evidence is immediately readable"],
                "risk_class": "high" if index == 0 else "normal",
            }
        )
    return shots


def _write_planning_fixture(context, *, report_status: str = "PASS", shot_count: int = 40) -> dict:
    shots = _quality_shots(shot_count)
    ledger = {
        "schema": "story_video_scene_ledger_v2",
        "production_type": "science_explainer",
        "target_duration_sec": 300 if shot_count == 40 else 60,
        "visual_style": "photoreal professional science documentary",
        "scenes": [
            {
                "scene_id": "S00",
                "narrative_role": "evidence",
                "viewer_takeaway": "觀眾看懂一個具體證據",
                "shots": shots,
            }
        ],
    }
    (context.project_dir / "PROJECT_CONTRACT.md").write_text("contract", encoding="utf-8")
    (context.project_dir / "script.md").write_text(
        "### S00\nfinal narration script", encoding="utf-8"
    )
    (context.project_dir / "storyboard.md").write_text("storyboard", encoding="utf-8")
    (context.project_dir / "scene_ledger.json").write_text(
        json.dumps(ledger), encoding="utf-8"
    )
    (context.project_dir / "production_checklist.json").write_text(
        json.dumps({"quality_mode": "quality_first", "status": "planning"}),
        encoding="utf-8",
    )
    (context.project_dir / "script_quality_report.json").write_text(
        json.dumps(
            {
                "schema": "story_video_script_quality_v1",
                "quality_contract_version": 2,
                "status": report_status,
                "production_type": "science_explainer",
                "shot_count": shot_count,
                "checks": {
                    "visual_evidence": "PASS",
                    "narrative_roles": "PASS",
                    "claim_confidence": "PASS",
                },
            }
        ),
        encoding="utf-8",
    )
    (context.project_dir / "pronunciation_lexicon.json").write_text(
        json.dumps(
            {
                "schema": "story_video_pronunciation_lexicon_v1",
                "language": "zh-TW",
                "review_status": "PASS",
                "entries": [],
            }
        ),
        encoding="utf-8",
    )
    return ledger


def _write_candidate_manifest(context, shots: list[dict]) -> None:
    outputs = []
    for index, shot in enumerate(shots):
        shot_id = shot["shot_id"]
        image = context.project_dir / "images" / f"{shot_id}.png"
        prompt = context.project_dir / "prompts" / f"{shot_id}.txt"
        image.parent.mkdir(parents=True, exist_ok=True)
        prompt.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(f"selected-{shot_id}".encode())
        prompt.write_text(f"prompt for {shot_id}", encoding="utf-8")
        shot["selected_asset_path"] = str(image.relative_to(context.project_dir))
        outputs.append(
            {
                "shot_id": shot_id,
                "shot_scale": shot["shot_scale"],
                "selected": True,
                "status": "selected_current",
                "provider": "openai-codex",
                "judge_provider": "openai-codex",
                "prompt_path": str(prompt.relative_to(context.project_dir)),
                "local_path": str(image.relative_to(context.project_dir)),
                "quality_score": 88,
                "hard_blockers": [],
                "vision_evidence": {"status": "PASS", "response_id": f"resp_{index}"},
            }
        )
    path = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": "story_video_shot_candidate_manifest_v1",
                "provider": "openai-codex",
                "judge_provider": "openai-codex",
                "quality_threshold": 80,
                "outputs": outputs,
            }
        ),
        encoding="utf-8",
    )


def _write_render_fixture(
    context,
    *,
    hard_burned: bool = True,
    motion_policy: str = "stable center zoom 1.0 -> 1.025",
) -> None:
    output = context.project_dir / "renders" / "final.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"rendered video")
    manifest = {
        "cards": {
            "opening": {"status": "PASS", "duration_sec": 3.0},
            "ending": {"status": "PASS", "duration_sec": 4.0},
        },
        "timeline": {
            "motion_policy": motion_policy,
            "selected_shot_count": 8,
            "shot_density_status": "PASS",
        },
        "output": {
            "path": "renders/final.mp4",
            "subtitles": {"hard_burned": hard_burned},
        },
        "qc_report": "render_qc.json",
    }
    for path in (
        context.project_dir / "render_manifest.json",
        context.project_dir / "manifests" / "render_manifest.json",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest), encoding="utf-8")
    (context.project_dir / "render_qc.json").write_text(
        json.dumps(
            {
                "visual_source_contract": {"provider_qc": "PASS"},
                "artifact_quality_evidence": {
                    "caption_visibility": {
                        "status": "PASS",
                        "hard_burned": hard_burned,
                    },
                    "motion": {"status": "PASS"},
                    "shot_density": {
                        "status": "PASS",
                        "selected_shot_count": 8,
                    },
                    "title_cards": {
                        "status": "PASS",
                        "opening": True,
                        "ending": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def test_planning_validation_blocks_with_exact_missing_artifacts(tmp_path) -> None:
    _store, context = _active_context(tmp_path)

    proof = validate_phase(context)

    assert proof.ok is False
    assert "storyboard.md" in proof.missing
    assert "scene_ledger.json" in proof.missing
    assert proof.marker == "STORY_VIDEO_PHASE_PROOF: planning BLOCKED"


def test_planning_validation_passes_and_advances_to_keyframes(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    _write_planning_fixture(context)

    proof = validate_phase(context)
    result = json.loads(
        story_video_control(
            {"action": "validate"},
            session_id="session-1",
            store=store,
        )
    )

    assert proof.ok is True
    assert proof.marker == "STORY_VIDEO_PHASE_PROOF: planning PASS"
    assert result["success"] is True
    assert result["proof"] == "STORY_VIDEO_PHASE_PROOF: planning PASS"
    assert store.for_session("session-1").phase == "keyframes"
    assert result["next_call"] == "繼續"


def test_planning_validation_rejects_missing_or_failed_script_quality(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    _write_planning_fixture(context, report_status="BLOCKED")

    blocked = validate_phase(context)
    (context.project_dir / "script_quality_report.json").unlink()
    missing = validate_phase(context)

    assert blocked.ok is False
    assert "script_quality_report.status=BLOCKED" in blocked.violations
    assert "script_quality_report.json" in missing.missing


def test_planning_validation_requires_the_final_script_artifact(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    _write_planning_fixture(context)
    (context.project_dir / "script.md").unlink()

    proof = validate_phase(context)

    assert proof.ok is False
    assert "script.md" in proof.missing


def test_planning_validation_requires_voice_compatible_script_headings(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    _write_planning_fixture(context)
    (context.project_dir / "script.md").write_text(
        "### Shot 01\n三疊紀。", encoding="utf-8"
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert "script.md requires ### S00-style narration headings" in proof.violations


def test_planning_validation_rejects_spoken_alias_leakage_into_script(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    _write_planning_fixture(context)
    (context.project_dir / "script.md").write_text(
        "### S00\n恐龍最早出現在三碟紀。", encoding="utf-8"
    )
    (context.project_dir / "pronunciation_lexicon.json").write_text(
        json.dumps(
            {
                "schema": "story_video_pronunciation_lexicon_v1",
                "language": "zh-TW",
                "review_status": "PASS",
                "entries": [
                    {
                        "display": "三疊紀",
                        "spoken": "三碟紀",
                        "expected_pinyin": "san1 die2 ji4",
                        "source": "taiwan_mandarin_review",
                        "risk": "high",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert "script.md contains spoken alias for high-risk term: 三疊紀" in proof.violations


def test_planning_validation_requires_pronunciation_lexicon(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    _write_planning_fixture(context)
    (context.project_dir / "pronunciation_lexicon.json").unlink()

    blocked = validate_phase(context)

    assert blocked.ok is False
    assert "pronunciation_lexicon.json" in blocked.missing

    (context.project_dir / "pronunciation_lexicon.json").write_text(
        json.dumps(
            {
                "schema": "story_video_pronunciation_lexicon_v1",
                "language": "zh-TW",
                "review_status": "PASS",
                "entries": [],
            }
        ),
        encoding="utf-8",
    )
    passed = validate_phase(context)

    assert passed.ok is True


def test_planning_validation_rejects_unchanged_high_risk_pronunciation_alias(
    tmp_path,
) -> None:
    _store, context = _active_context(tmp_path)
    _write_planning_fixture(context)
    lexicon = {
        "schema": "story_video_pronunciation_lexicon_v1",
        "language": "zh-TW",
        "review_status": "PASS",
        "entries": [
            {
                "display": "三疊紀",
                "spoken": "三疊紀",
                "expected_pinyin": "san1 die2 ji4",
                "source": "taiwan_mandarin_review",
                "risk": "high",
            }
        ],
    }
    (context.project_dir / "pronunciation_lexicon.json").write_text(
        json.dumps(lexicon, ensure_ascii=False), encoding="utf-8"
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert (
        "pronunciation_lexicon entry[0] high-risk spoken alias is unchanged"
        in proof.violations
    )


def test_planning_validation_accepts_corrected_high_risk_pronunciation_alias(
    tmp_path,
) -> None:
    _store, context = _active_context(tmp_path)
    _write_planning_fixture(context)
    lexicon = {
        "schema": "story_video_pronunciation_lexicon_v1",
        "language": "zh-TW",
        "review_status": "PASS",
        "entries": [
            {
                "display": "三疊紀",
                "spoken": "三碟紀",
                "expected_pinyin": "san1 die2 ji4",
                "source": "taiwan_mandarin_review",
                "risk": "high",
            }
        ],
    }
    (context.project_dir / "pronunciation_lexicon.json").write_text(
        json.dumps(lexicon, ensure_ascii=False), encoding="utf-8"
    )

    proof = validate_phase(context)

    assert proof.ok is True


def test_planning_validation_rejects_shallow_scene_ledger(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    _write_planning_fixture(context)
    (context.project_dir / "scene_ledger.json").write_text(
        json.dumps(
            {
                "production_type": "science_explainer",
                "target_duration_sec": 300,
                "scenes": [{"scene_id": "S00", "viewer_takeaway": "too shallow"}],
            }
        ),
        encoding="utf-8",
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert "S00.shots" in proof.violations


def test_planning_validation_enforces_v3_engagement_fields(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    ledger = _write_planning_fixture(context)
    roles = ("hook", "build", "reveal", "reaction", "payoff", "breathe")
    energies = ("curious", "tense", "awe", "kinetic", "curious", "calm")
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
    for index, shot in enumerate(ledger["scenes"][0]["shots"]):
        shot.update(
            {
                "engagement_role": roles[index % len(roles)],
                "attention_hook": "先看見結果，再追問原因",
                "story_moment": "主體完成一個可見動作",
                "action_consequence": "動作留下可辨識結果",
                "composition_energy": energies[index % len(energies)],
                "viewer_emotion": "curiosity",
                "engagement_criteria": ["the decisive instant is readable"],
                "visual_truth_mode": "direct_evidence",
            }
        )
        if shot["engagement_role"] == "breathe":
            shot["calm_reason"] = "讓觀眾消化剛揭示的內容"
    del ledger["scenes"][0]["shots"][0]["story_moment"]
    (context.project_dir / "scene_ledger.json").write_text(
        json.dumps(ledger), encoding="utf-8"
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert "S00_SH00.story_moment" in proof.violations


def test_control_status_returns_active_project_and_policy(tmp_path) -> None:
    store, context = _active_context(tmp_path)

    result = json.loads(
        story_video_control(
            {"action": "status"},
            session_id="session-1",
            store=store,
        )
    )

    assert result["success"] is True
    assert result["project_dir"] == str(context.project_dir)
    assert result["phase"] == "planning"
    assert result["provider_policy"]["image"] == ["openai", "openai-codex"]
    assert result["provider_policy"]["tts"] == ["local-qwen"]


def test_control_without_active_session_fails_closed(tmp_path) -> None:
    result = json.loads(
        story_video_control(
            {"action": "status"},
            session_id="missing",
            store=StoryVideoStateStore(tmp_path),
        )
    )

    assert result["success"] is False
    assert result["error_type"] == "story_video_context_missing"


def test_blocked_validation_sets_repair_next_call(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    (context.project_dir / "PROJECT_CONTRACT.md").write_text(
        "contract", encoding="utf-8"
    )

    result = json.loads(
        story_video_control(
            {"action": "validate"},
            session_id="session-1",
            store=store,
        )
    )

    assert result["success"] is False
    assert result["next_call"].startswith("修正：")
    assert "script.md" in result["next_call"]
    assert store.for_session("session-1").repair_request


def test_keyframe_validation_requires_selected_openai_provenance(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="keyframes")
    ledger = _write_planning_fixture(context)
    shots = ledger["scenes"][0]["shots"][:3]
    manifest_path = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "provider": "openai-codex",
                "outputs": [
                    {"shot_id": shot["shot_id"], "selected": True}
                    for shot in shots
                ],
            }
        ),
        encoding="utf-8",
    )

    blocked = validate_phase(context)
    _write_candidate_manifest(context, shots)
    passed = validate_phase(context)

    assert blocked.ok is False
    assert "selected keyframe missing OpenAI vision score evidence" in blocked.violations
    assert passed.ok is True


def test_story_video_control_synchronizes_candidate_manifest_phase(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="batch")
    manifest_path = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps({"phase": "keyframes", "outputs": []}),
        encoding="utf-8",
    )

    story_video_control(
        {"action": "status"},
        session_id="session-1",
        store=store,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["phase"] == "batch"


def test_keyframe_validation_rejects_noncanonical_nested_candidate_manifest(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="keyframes")
    ledger = _write_planning_fixture(context)
    shot = ledger["scenes"][0]["shots"][0]
    manifest_path = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "provider": "openai-codex",
                "judge_provider": "openai-codex",
                "shots": [
                    {
                        "shot_id": shot["shot_id"],
                        "candidates": [{"selected": True, "judge_score": 80}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert (
        "shot candidate manifest must contain canonical outputs[] from "
        "story_video_quality_control"
    ) in proof.violations


def test_keyframe_accepts_nonempty_openai_chat_completion_response_id(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="keyframes")
    ledger = _write_planning_fixture(context)
    shots = ledger["scenes"][0]["shots"][:3]
    _write_candidate_manifest(context, shots)
    manifest_path = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for output in manifest["outputs"]:
        output["vision_evidence"]["response_id"] = "chatcmpl_openai_story_judge"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    proof = validate_phase(context)

    assert proof.ok is True


def test_batch_validation_accepts_scene_ledger_selected_asset_path(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="batch")
    ledger = _write_planning_fixture(context, shot_count=8)
    shots = ledger["scenes"][0]["shots"]
    _write_candidate_manifest(context, shots)
    (context.project_dir / "scene_ledger.json").write_text(
        json.dumps(ledger),
        encoding="utf-8",
    )

    proof = validate_phase(context)

    assert proof.ok is True


def test_batch_autopilot_promotes_legacy_scale_repeat_reason_and_transitions(
    tmp_path,
) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="batch", auto_mode=True)
    ledger = _write_planning_fixture(context, shot_count=8)
    shots = ledger["scenes"][0]["shots"]
    for shot in shots[1:4]:
        shot["shot_scale"] = "medium"
    shots[3]["scale_repetition_reason"] = (
        "Keep equal visual weight while comparing three adjacent subjects."
    )
    _write_candidate_manifest(context, shots)
    (context.project_dir / "scene_ledger.json").write_text(
        json.dumps(ledger), encoding="utf-8"
    )

    payload = json.loads(
        story_video_control(
            {"action": "validate"},
            session_id="session-1",
            store=store,
        )
    )

    assert payload["success"] is True
    assert payload["proof"] == "STORY_VIDEO_PHASE_PROOF: batch PASS"
    assert payload["phase"] == "voice"
    repaired = json.loads(
        (context.project_dir / "scene_ledger.json").read_text(encoding="utf-8")
    )
    assert repaired["scenes"][0]["shots"][3][
        "intentional_scale_repeat_reason"
    ] == shots[3]["scale_repetition_reason"]


def test_batch_validation_rejects_selected_asset_from_superseded_shot_contract(
    tmp_path,
) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="batch")
    ledger = _write_planning_fixture(context, shot_count=8)
    shots = ledger["scenes"][0]["shots"]
    _write_candidate_manifest(context, shots)
    shots[0]["shot_scale"] = "macro"
    (context.project_dir / "scene_ledger.json").write_text(
        json.dumps(ledger),
        encoding="utf-8",
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert f"{shots[0]['shot_id']} selected candidate uses superseded shot contract" in (
        proof.violations
    )


def test_batch_validation_rejects_missing_and_duplicate_selected_shots(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="batch")
    ledger = _write_planning_fixture(context, shot_count=8)
    shots = ledger["scenes"][0]["shots"]
    _write_candidate_manifest(context, shots[:-1])
    duplicate = context.project_dir / "images" / f"{shots[0]['shot_id']}.png"
    shots[1]["selected_asset_path"] = str(duplicate.relative_to(context.project_dir))
    (context.project_dir / "scene_ledger.json").write_text(
        json.dumps(ledger), encoding="utf-8"
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert f"{shots[-1]['shot_id']}.selected_asset" in proof.missing
    assert "duplicate selected asset files" in proof.violations


def test_voice_validation_rejects_local_macos_timing_draft(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="voice")
    audio = context.project_dir / "audio" / "S00.aiff"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"local draft audio")
    manifest_path = context.project_dir / "manifests" / "narration_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "provider": "local",
                "engine": "macOS say",
                "voice": "Meijia",
                "rate": 60,
                "outputs": [{"scene_id": "S00", "audio": str(audio)}],
            }
        ),
        encoding="utf-8",
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert "production narration provider is local, expected local-qwen" in proof.violations


def test_voice_validation_requires_complete_v4_acoustic_contract(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="voice")
    audio = context.project_dir / "audio" / "qwen" / "S00.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"local qwen production audio")
    profile = context.project_dir / "voice_profiles" / "simon_primary.json"
    profile.parent.mkdir(parents=True)
    profile.write_text(
        json.dumps(
            {
                "profile_id": "simon_primary",
                "status": "locked_by_user",
                "provider": "local_qwen",
            }
        ),
        encoding="utf-8",
    )
    manifest_path = context.project_dir / "manifests" / "narration_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    pronunciation_path = context.project_dir / "qc" / "pronunciation_qc_report.json"
    pronunciation_path.parent.mkdir(parents=True)
    pronunciation_path.write_text(
        json.dumps(
            {
                "schema": "story_video_pronunciation_qc_v2",
                "status": "PASS",
                "language": "zh-TW",
                "method": "lexicon_plus_independent_asr",
                "acoustic_evidence": [
                    {
                        "shot_id": "S00_SH00",
                        "alignment_status": "PASS",
                        "pronunciation_status": "PASS",
                        "prosody_status": "PASS",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "story_video_narration_manifest_v4",
                "provider": "local_qwen",
                "engine": "Qwen3-TTS via MLX-Audio",
                "language": "zh-TW",
                "voice_role": "narrator",
                "voice": "simon_primary",
                "rate": "1.06x",
                "profile_status": "locked_by_user",
                "voice_contract_status": "PASS",
                "voice_profile": str(profile),
                "model": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
                "inference_mode": "offline",
                "network_fallback": "forbidden",
                "pronunciation_status": "PASS",
                "alignment_status": "PASS",
                "prosody_status": "PASS",
                "outputs": [
                    {
                        "scene_id": "S00",
                        "audio": str(audio),
                        "display_text": "三疊紀。",
                        "spoken_text": "三碟紀。",
                        "pronunciation_status": "PASS",
                        "segments": [
                            {
                                "shot_id": "S00_SH00",
                                "timeline_duration_sec": 1.25,
                                "alignment_status": "PASS",
                                "pronunciation_status": "PASS",
                                "prosody_status": "PASS",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    proof = validate_phase(context)

    assert proof.ok is True

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["outputs"][0]["segments"][0]["prosody_status"] = "FAIL"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    failed = validate_phase(context)

    assert failed.ok is False
    assert (
        "audio narration segment[0].segments[0] prosody is not PASS"
        in failed.violations
    )


def test_voice_validation_blocks_local_qwen_without_pronunciation_proof(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="voice")
    audio = context.project_dir / "audio" / "qwen" / "S00.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"local qwen production audio")
    profile = context.project_dir / "voice_profiles" / "simon_primary.json"
    profile.parent.mkdir(parents=True)
    profile.write_text(
        json.dumps(
            {
                "profile_id": "simon_primary",
                "status": "locked_by_user",
                "provider": "local_qwen",
            }
        ),
        encoding="utf-8",
    )
    manifest_path = context.project_dir / "manifests" / "narration_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "provider": "local_qwen",
                "engine": "Qwen3-TTS via MLX-Audio",
                "language": "zh-TW",
                "voice": "simon_primary",
                "rate": "1.06x",
                "profile_status": "locked_by_user",
                "voice_contract_status": "PASS",
                "voice_profile": str(profile),
                "model": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
                "inference_mode": "offline",
                "network_fallback": "forbidden",
                "outputs": [{"scene_id": "S00", "audio": str(audio)}],
            }
        ),
        encoding="utf-8",
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert "qc/pronunciation_qc_report.json" in proof.missing


def test_voice_validation_accepts_locked_azure_narration_manifest(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(
        context,
        phase="voice",
        provider_policy={**context.provider_policy, "tts": ["azure"]},
    )
    audio = context.project_dir / "audio" / "azure" / "S00.mp3"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"azure production audio")
    manifest_path = context.project_dir / "manifests" / "narration_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "provider": "azure",
                "engine": "Azure AI Speech",
                "language": "zh-TW",
                "voice_role": "narrator",
                "voice": "zh-TW-HsiaoChenNeural",
                "rate": "+6%",
                "profile_status": "locked_by_user",
                "voice_contract_status": "PASS",
                "outputs": [{"scene_id": "S00", "audio": str(audio)}],
            }
        ),
        encoding="utf-8",
    )

    proof = validate_phase(context)

    assert proof.ok is True


def test_render_validation_requires_clean_provider_audit(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="render")
    _write_render_fixture(context)

    blocked = validate_phase(context)
    ProviderAudit(context).append_event(
        ProviderAuditEvent(
            kind="api",
            phase="planning",
            provider="openai-codex",
            model="gpt-5.5",
            status="ok",
        )
    )
    passed = validate_phase(context)

    assert blocked.ok is False
    assert "provider audit has no events" in blocked.violations
    assert passed.ok is True


def test_render_validation_blocks_soft_subtitles_and_static_motion(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="render")
    _write_render_fixture(
        context,
        hard_burned=False,
        motion_policy="stable static hold",
    )
    ProviderAudit(context).append_event(
        ProviderAuditEvent(
            kind="api",
            phase="render",
            provider="openai-codex",
            model="gpt-5.6-sol",
            status="ok",
        )
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert "primary render has no hard-burned subtitles" in proof.violations
    assert "primary render has no non-static motion policy" in proof.violations


def test_render_validation_requires_shot_density_evidence(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="render")
    _write_render_fixture(context)
    manifest_path = context.project_dir / "render_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["timeline"].pop("selected_shot_count")
    manifest["timeline"].pop("shot_density_status")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    qc_path = context.project_dir / "render_qc.json"
    qc = json.loads(qc_path.read_text(encoding="utf-8"))
    qc["artifact_quality_evidence"].pop("shot_density")
    qc_path.write_text(json.dumps(qc), encoding="utf-8")
    ProviderAudit(context).append_event(
        ProviderAuditEvent(
            kind="api",
            phase="render",
            provider="openai-codex",
            model="gpt-5.6-terra",
            status="ok",
        )
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert "render manifest lacks selected-shot density evidence" in proof.violations
    assert "render QC lacks selected-shot density evidence" in proof.violations


def test_render_validation_requires_opening_and_ending_cards(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="render")
    _write_render_fixture(context)
    for relative in ("render_manifest.json", "manifests/render_manifest.json"):
        path = context.project_dir / relative
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["cards"].pop("ending")
        path.write_text(json.dumps(manifest), encoding="utf-8")
    qc_path = context.project_dir / "render_qc.json"
    qc = json.loads(qc_path.read_text(encoding="utf-8"))
    qc["artifact_quality_evidence"]["title_cards"]["ending"] = False
    qc_path.write_text(json.dumps(qc), encoding="utf-8")
    ProviderAudit(context).append_event(
        ProviderAuditEvent(
            kind="api",
            phase="render",
            provider="openai-codex",
            model="gpt-5.6-sol",
            status="ok",
        )
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert "render manifest lacks opening and ending cards" in proof.violations
    assert "render QC lacks opening and ending card evidence" in proof.violations
