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
    (context.project_dir / "script.md").write_text("final narration script", encoding="utf-8")
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
