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


def test_planning_validation_blocks_with_exact_missing_artifacts(tmp_path) -> None:
    _store, context = _active_context(tmp_path)

    proof = validate_phase(context)

    assert proof.ok is False
    assert "storyboard.md" in proof.missing
    assert "scene_ledger.json" in proof.missing
    assert proof.marker == "STORY_VIDEO_PHASE_PROOF: planning BLOCKED"


def test_planning_validation_passes_and_advances_to_keyframes(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    (context.project_dir / "PROJECT_CONTRACT.md").write_text("contract", encoding="utf-8")
    (context.project_dir / "storyboard.md").write_text("storyboard", encoding="utf-8")
    (context.project_dir / "scene_ledger.json").write_text("{}", encoding="utf-8")
    (context.project_dir / "production_checklist.json").write_text("{}", encoding="utf-8")

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
    assert "storyboard.md" in result["next_call"]
    assert store.for_session("session-1").repair_request


def test_keyframe_validation_requires_selected_openai_provenance(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="keyframes")
    manifest_path = context.project_dir / "manifests" / "scene_generation_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "provider": "xai",
                "outputs": [{"scene_id": "S00", "selected": True}],
            }
        ),
        encoding="utf-8",
    )

    blocked = validate_phase(context)
    manifest_path.write_text(
        json.dumps(
            {
                "provider": "openai-codex",
                "outputs": [{"scene_id": "S00", "selected": True}],
            }
        ),
        encoding="utf-8",
    )
    passed = validate_phase(context)

    assert blocked.ok is False
    assert any("not OpenAI" in item for item in blocked.violations)
    assert passed.ok is True


def test_batch_validation_accepts_scene_ledger_selected_asset_path(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="batch")
    image_path = context.project_dir / "images" / "S00.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"selected image")
    (context.project_dir / "scene_ledger.json").write_text(
        json.dumps(
            {
                "scenes": [
                    {
                        "scene_id": "S00",
                        "selected_asset_path": "images/S00.png",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    proof = validate_phase(context)

    assert proof.ok is True


def test_render_validation_requires_clean_provider_audit(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="render")
    manifest_path = context.project_dir / "manifests" / "render_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("{}", encoding="utf-8")
    (context.project_dir / "render_qc.json").write_text(
        json.dumps({"visual_source_contract": {"provider_qc": "PASS"}}),
        encoding="utf-8",
    )

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
