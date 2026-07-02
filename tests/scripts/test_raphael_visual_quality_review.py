from __future__ import annotations

import json
import hashlib

import pytest


def test_visual_quality_review_cli_writes_pass_source_report(tmp_path, capsys):
    from scripts import raphael_visual_quality_review

    artifact = tmp_path / "selected-artifact.png"
    output = tmp_path / "raphael-visual-quality-review.json"
    artifact.write_bytes(b"generated image")
    transcript_report = _write_model_review_transcript(
        tmp_path,
        artifact=artifact,
        artifact_bytes=b"generated image",
    )

    exit_code = raphael_visual_quality_review.main(
        [
            "--artifact",
            str(artifact),
            "--reviewer",
            "vision-backed-artifact-review",
            "--verdict",
            "pass",
            "--dimension",
            "composition=pass",
            "--dimension",
            "prompt_adherence=pass",
            "--dimension",
            "geometry=pass",
            "--dimension",
            "subject_quality=pass",
            "--evidence",
            "artifact was reviewed directly",
            "--review-source-type",
            "vision_model",
            "--review-model-provider",
            "openai",
            "--review-model",
            "gpt-5.5-vision",
            "--review-transcript-report",
            str(transcript_report),
            "--run-id",
            "quality-review-run-1",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    stdout_report = json.loads(capsys.readouterr().out)
    assert stdout_report == report
    assert report["schema_version"] == 1
    assert report["kind"] == "raphael_visual_quality_review"
    assert report["success"] is True
    assert report["status"] == "pass"
    assert report["producer"] == "hermes-visual-quality-review"
    assert report["reviewer"] == "vision-backed-artifact-review"
    assert report["run_id"] == "quality-review-run-1"
    assert report["generated_at"]
    assert report["command"] == "scripts/raphael_visual_quality_review.py"
    assert report["artifact_path"] == str(artifact.resolve())
    assert report["artifact_sha256"] == hashlib.sha256(b"generated image").hexdigest()
    assert report["artifact_size_bytes"] == len(b"generated image")
    assert report["artifact_mtime"] > 0
    assert report["artifact_identity_verified"] is True
    assert report["review_source_type"] == "vision_model"
    assert report["review_model_provider"] == "openai"
    assert report["review_model"] == "gpt-5.5-vision"
    assert report["review_evidence_digest"]
    assert report["review_provenance_verified"] is True
    assert report["review_response_id"] == "resp_quality_review_1"
    assert report["review_transcript_report_path"] == str(transcript_report.resolve())
    assert report["review_transcript_digest"]
    assert report["artifact_quality_verdict"] == "pass"
    assert report["dimensions"] == {
        "composition": "pass",
        "prompt_adherence": "pass",
        "geometry": "pass",
        "subject_quality": "pass",
    }
    assert report["dimensions_verified"] is True
    assert "artifact was reviewed directly" in report["evidence"]
    assert report["residual_risk"]


def _write_model_review_transcript(
    tmp_path,
    *,
    artifact,
    artifact_bytes,
    artifact_sha256=None,
):
    artifact_hash = artifact_sha256 or hashlib.sha256(artifact_bytes).hexdigest()
    transcript = tmp_path / "model-review-transcript.json"
    transcript.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "raphael_visual_quality_model_review",
                "producer": "openai-gpt-vision-review",
                "response_id": "resp_quality_review_1",
                "review_model_provider": "openai",
                "review_model": "gpt-5.5-vision",
                "artifact_path": str(artifact.resolve()),
                "artifact_sha256": artifact_hash,
                "artifact_size_bytes": len(artifact_bytes),
                "artifact_quality_verdict": "pass",
                "dimensions": {
                    "composition": "pass",
                    "prompt_adherence": "pass",
                    "geometry": "pass",
                    "subject_quality": "pass",
                },
                "evidence": [
                    "model reviewed the selected artifact",
                    "required visual quality dimensions passed",
                ],
            }
        ),
        encoding="utf-8",
    )
    return transcript


def test_visual_quality_review_cli_blocks_missing_review_provenance(tmp_path):
    from scripts import raphael_visual_quality_review

    artifact = tmp_path / "selected-artifact.png"
    output = tmp_path / "blocked-quality-review.json"
    artifact.write_bytes(b"generated image")

    exit_code = raphael_visual_quality_review.main(
        [
            "--artifact",
            str(artifact),
            "--reviewer",
            "vision-backed-artifact-review",
            "--verdict",
            "pass",
            "--dimension",
            "composition=pass",
            "--dimension",
            "prompt_adherence=pass",
            "--dimension",
            "geometry=pass",
            "--dimension",
            "subject_quality=pass",
            "--output",
            str(output),
        ]
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 2
    assert report["success"] is False
    assert report["review_provenance_verified"] is False
    assert "review_provenance_missing" in report["failure_classes"]


def test_visual_quality_review_cli_blocks_mismatched_model_review_transcript(tmp_path):
    from scripts import raphael_visual_quality_review

    artifact = tmp_path / "selected-artifact.png"
    output = tmp_path / "blocked-quality-review.json"
    artifact.write_bytes(b"generated image")
    transcript_report = _write_model_review_transcript(
        tmp_path,
        artifact=artifact,
        artifact_bytes=b"generated image",
        artifact_sha256="0" * 64,
    )

    exit_code = raphael_visual_quality_review.main(
        [
            "--artifact",
            str(artifact),
            "--reviewer",
            "vision-backed-artifact-review",
            "--verdict",
            "pass",
            "--dimension",
            "composition=pass",
            "--dimension",
            "prompt_adherence=pass",
            "--dimension",
            "geometry=pass",
            "--dimension",
            "subject_quality=pass",
            "--review-source-type",
            "vision_model",
            "--review-model-provider",
            "openai",
            "--review-model",
            "gpt-5.5-vision",
            "--review-transcript-report",
            str(transcript_report),
            "--output",
            str(output),
        ]
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 2
    assert report["success"] is False
    assert report["review_provenance_verified"] is False
    assert "review_provenance_missing" in report["failure_classes"]


def test_visual_quality_review_cli_blocks_provider_reviewer(tmp_path):
    from scripts import raphael_visual_quality_review

    artifact = tmp_path / "selected-artifact.png"
    output = tmp_path / "blocked-quality-review.json"
    artifact.write_bytes(b"generated image")

    exit_code = raphael_visual_quality_review.main(
        [
            "--artifact",
            str(artifact),
            "--reviewer",
            "grok-web-imagine-live",
            "--verdict",
            "pass",
            "--dimension",
            "composition=pass",
            "--dimension",
            "prompt_adherence=pass",
            "--dimension",
            "geometry=pass",
            "--dimension",
            "subject_quality=pass",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 2
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["success"] is False
    assert report["status"] == "blocked"
    assert report["artifact_quality_verdict"] == "blocked"
    assert "reviewer_not_independent" in report["failure_classes"]
    assert report["reviewer"] == "grok-web-imagine-live"


@pytest.mark.parametrize(
    "reviewer",
        [
            "grok-web-imagine-provider",
            "provider-grok-web-imagine",
            "openai",
            "openai-codex",
            "gpt-image-2-low",
            "image2",
            "openai-codex-provider",
            "provider-openai-codex",
            "self-reviewer",
            "live-harness-review",
        ],
)
def test_visual_quality_review_cli_blocks_decorated_provider_and_self_reviewers(
    tmp_path,
    reviewer,
):
    from scripts import raphael_visual_quality_review

    artifact = tmp_path / "selected-artifact.png"
    output = tmp_path / "blocked-quality-review.json"
    artifact.write_bytes(b"generated image")

    exit_code = raphael_visual_quality_review.main(
        [
            "--artifact",
            str(artifact),
            "--reviewer",
            reviewer,
            "--verdict",
            "pass",
            "--dimension",
            "composition=pass",
            "--dimension",
            "prompt_adherence=pass",
            "--dimension",
            "geometry=pass",
            "--dimension",
            "subject_quality=pass",
            "--output",
            str(output),
        ]
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 2
    assert report["success"] is False
    assert report["reviewer_independent"] is False
    assert "reviewer_not_independent" in report["failure_classes"]


def test_visual_quality_review_cli_blocks_non_finite_dimension_scores(tmp_path):
    from scripts import raphael_visual_quality_review

    artifact = tmp_path / "selected-artifact.png"
    output = tmp_path / "blocked-quality-review.json"
    artifact.write_bytes(b"generated image")

    exit_code = raphael_visual_quality_review.main(
        [
            "--artifact",
            str(artifact),
            "--reviewer",
            "vision-backed-artifact-review",
            "--verdict",
            "pass",
            "--dimension",
            "composition=inf",
            "--dimension",
            "prompt_adherence=inf",
            "--dimension",
            "geometry=inf",
            "--dimension",
            "subject_quality=inf",
            "--output",
            str(output),
        ]
    )

    text = output.read_text(encoding="utf-8")
    report = json.loads(text)
    assert exit_code == 2
    assert "Infinity" not in text
    assert report["success"] is False
    assert report["dimensions_verified"] is False
    assert report["malformed_dimensions"] == [
        "composition",
        "prompt_adherence",
        "geometry",
        "subject_quality",
    ]
    assert "missing_or_failing_dimensions" in report["failure_classes"]


def test_visual_quality_review_cli_blocks_missing_artifact_rejected_verdict_and_failing_dimension(
    tmp_path,
):
    from scripts import raphael_visual_quality_review

    output = tmp_path / "blocked-quality-review.json"

    exit_code = raphael_visual_quality_review.main(
        [
            "--artifact",
            str(tmp_path / "missing.png"),
            "--reviewer",
            "vision-backed-artifact-review",
            "--verdict",
            "reject",
            "--dimension",
            "composition=fail",
            "--dimension",
            "prompt_adherence=pass",
            "--dimension",
            "geometry=pass",
            "--dimension",
            "subject_quality=pass",
            "--dimension",
            "malformed-dimension",
            "--output",
            str(output),
        ]
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 2
    assert report["success"] is False
    assert "artifact_missing" in report["failure_classes"]
    assert "verdict_not_accepted" in report["failure_classes"]
    assert "missing_or_failing_dimensions" in report["failure_classes"]
    assert report["failing_dimensions"] == ["composition"]
    assert report["malformed_dimensions"] == ["malformed-dimension"]


def test_visual_quality_review_cli_blocks_missing_required_dimension(tmp_path):
    from scripts import raphael_visual_quality_review

    artifact = tmp_path / "selected-artifact.png"
    output = tmp_path / "blocked-quality-review.json"
    artifact.write_bytes(b"generated image")

    exit_code = raphael_visual_quality_review.main(
        [
            "--artifact",
            str(artifact),
            "--reviewer",
            "vision-backed-artifact-review",
            "--verdict",
            "pass",
            "--dimension",
            "composition=pass",
            "--dimension",
            "prompt_adherence=pass",
            "--dimension",
            "geometry=pass",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 2
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["success"] is False
    assert report["status"] == "blocked"
    assert report["artifact_quality_verdict"] == "blocked"
    assert report["dimensions_verified"] is False
    assert report["missing_dimensions"] == ["subject_quality"]
    assert "missing_or_failing_dimensions" in report["failure_classes"]
