from __future__ import annotations

import hashlib
import json

from plugins.story_video.sequence_quality import (
    build_sequence_quality_report,
    validate_sequence_quality_report,
    write_sequence_quality_report,
)
from plugins.story_video.shot_contract import shot_contract_hash


def _shot(shot_id: str) -> dict:
    return {
        "shot_id": shot_id,
        "narration_text": "一句完整旁白。另一句完整旁白。",
        "narrative_role": "reveal",
        "viewer_takeaway": "看懂具體證據",
        "subject": "清楚可辨識的證據",
        "action": "證據改變原本的猜測",
        "evidence_detail": "關鍵細節清楚可見",
        "shot_scale": "close_up",
        "camera_angle": "eye level",
        "focal_point": "primary evidence",
        "subtitle_safe_area": "bottom 20 percent clear",
        "acceptance_criteria": ["evidence is readable"],
        "risk_class": "normal",
        "engagement_role": "reveal",
        "attention_hook": "先看到結果",
        "story_moment": "線索翻轉猜測",
        "action_consequence": "帶出下一個問題",
        "composition_energy": "awe",
        "viewer_emotion": "surprise",
        "engagement_criteria": ["the reveal is immediately clear"],
        "visual_truth_mode": "direct_evidence",
    }


def _fixture(tmp_path, *, duplicate: bool = False) -> tuple[dict, dict]:
    shots = [_shot("S00_SH00"), _shot("S01_SH00")]
    ledger = {
        "quality_contract_version": 6,
        "scenes": [
            {"scene_id": "S00", "shots": [shots[0]]},
            {"scene_id": "S01", "shots": [shots[1]]},
        ],
    }
    outputs = []
    for index, shot in enumerate(shots):
        path = tmp_path / "images" / f"{shot['shot_id']}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = b"same-image" if duplicate else f"image-{index}".encode()
        path.write_bytes(payload)
        artifact_sha = hashlib.sha256(payload).hexdigest()
        outputs.append(
            {
                "shot_id": shot["shot_id"],
                "selected": True,
                "status": "selected_current",
                "local_path": str(path.relative_to(tmp_path)),
                "artifact_sha256": artifact_sha,
                "shot_contract_hash": shot_contract_hash(shot),
                "quality_score": 90,
                "quality_dimensions": {
                    "text_alignment": 90,
                    "evidence_specificity": 90,
                    "narrative_engagement": 90,
                    "story_moment_clarity": 90,
                    "cinematic_impact": 90,
                    "professional_quality": 90,
                    "style_consistency": 90,
                },
                "vision_evidence": {
                    "status": "PASS",
                    "response_id": f"resp-{index}",
                },
                "provider": "openai-codex",
                "judge_provider": "openai-codex",
            }
        )
    return ledger, {"provider": "openai-codex", "outputs": outputs}


def test_sequence_quality_rejects_same_bytes_at_different_paths(tmp_path) -> None:
    ledger, manifest = _fixture(tmp_path, duplicate=True)

    report = build_sequence_quality_report(tmp_path, ledger, manifest)

    assert report["status"] == "REPAIR_REQUIRED"
    assert report["metrics"]["unique_artifact_count"] == 1
    assert report["repair_shot_ids"] == ["S00_SH00", "S01_SH00"]
    assert "duplicate artifact sha256 used by: S00_SH00,S01_SH00" in report["violations"]


def test_sequence_quality_rejects_inherited_or_stale_assessment(tmp_path) -> None:
    ledger, manifest = _fixture(tmp_path)
    manifest["outputs"][1].update(
        {
            "quality_score_origin": "source_asset",
            "vision_evidence_applies_to_shot_id": "S00_SH00",
            "final_qc_review_required": True,
        }
    )

    report = build_sequence_quality_report(tmp_path, ledger, manifest)

    assert report["status"] == "REPAIR_REQUIRED"
    assert report["repair_shot_ids"] == ["S01_SH00"]
    assert "S01_SH00 assessment is inherited from another artifact or shot" in report[
        "violations"
    ]
    assert "S01_SH00 requires final visual QC" in report["violations"]


def test_sequence_quality_report_is_bound_to_current_files(tmp_path) -> None:
    ledger, manifest = _fixture(tmp_path)
    path = write_sequence_quality_report(tmp_path, ledger, manifest)
    report = json.loads(path.read_text(encoding="utf-8"))

    assert report["status"] == "PASS"
    assert validate_sequence_quality_report(tmp_path, ledger, manifest, report) == ()

    (tmp_path / "images" / "S01_SH00.png").write_bytes(b"changed-after-review")

    violations = validate_sequence_quality_report(tmp_path, ledger, manifest, report)

    assert "sequence_quality_report is stale or does not match current artifacts" in violations


def test_sequence_quality_requires_all_story_dimensions_at_threshold(tmp_path) -> None:
    ledger, manifest = _fixture(tmp_path)
    manifest["outputs"][0]["quality_dimensions"]["cinematic_impact"] = 79

    report = build_sequence_quality_report(tmp_path, ledger, manifest)

    assert report["status"] == "REPAIR_REQUIRED"
    assert "S00_SH00 cinematic evidence score<80" in report["violations"]


def test_sequence_quality_rejects_non_finite_model_scores(tmp_path) -> None:
    ledger, manifest = _fixture(tmp_path)
    manifest["outputs"][0]["quality_score"] = float("nan")
    manifest["outputs"][0]["quality_dimensions"]["style_consistency"] = float(
        "inf"
    )

    report = build_sequence_quality_report(tmp_path, ledger, manifest)

    assert "S00_SH00 overall quality score<80" in report["violations"]
    assert "S00_SH00 style evidence score<80" in report["violations"]
