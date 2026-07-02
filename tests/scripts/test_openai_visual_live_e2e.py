import json
import hashlib
from pathlib import Path


def test_openai_visual_live_e2e_disabled_without_opt_in(tmp_path):
    from scripts import openai_visual_live_e2e

    def fail_generation(_args):
        raise AssertionError("provider should not run without opt-in")

    report = openai_visual_live_e2e.build_openai_visual_live_e2e_report(
        work_dir=tmp_path,
        prompt="polished product image",
        generation_fn=fail_generation,
        env={},
    )

    assert report["success"] is False
    assert report["status"] == "disabled"
    assert report["provider_mode"] == "openai-gpt-image-live"
    assert report["requires_operator_setup"] is True
    assert report["self_review"]["provider_called"] is False


def test_openai_visual_live_e2e_runs_openai_codex_provider_when_opted_in(tmp_path):
    from scripts import openai_visual_live_e2e

    output = tmp_path / "openai-output.png"
    output.write_bytes(b"generated")
    calls = []

    def fake_generation(args):
        calls.append(dict(args))
        return json.dumps(
            {
                "success": True,
                "image": str(output),
                "provider": "openai-codex",
                "model": "gpt-image-2-low",
                "response_id": "resp_openai_generation_1",
                "aspect_ratio": "square",
            }
        )

    report = openai_visual_live_e2e.build_openai_visual_live_e2e_report(
        work_dir=tmp_path,
        prompt="polished product image",
        aspect_ratio="square",
        generation_fn=fake_generation,
        env={
            "HERMES_VISUAL_LIVE_E2E": "1",
            "HERMES_OPENAI_VISUAL_LIVE_E2E": "1",
        },
    )

    assert report["success"] is True
    assert report["status"] == "completed"
    assert report["provider_mode"] == "openai-gpt-image-live"
    assert report["provider"] == {
        "name": "openai-codex",
        "model": "gpt-image-2-low",
    }
    assert report["artifact"] == {
        "path": str(output),
        "exists": True,
        "source": "openai_response",
        "durability": "provider_response_artifact",
        "history_verified": True,
    }
    assert report["result_surface_id"] == "openai-response:resp_openai_generation_1"
    assert report["provider_result"]["response_id"] == "resp_openai_generation_1"
    assert report["self_review"]["provider_called"] is True
    assert calls == [
        {
            "prompt": "polished product image",
            "aspect_ratio": "square",
            "provider": "openai-codex",
            "_disable_visual_tracking": True,
        }
    ]


def test_openai_visual_live_e2e_stamps_release_gate_provenance(tmp_path):
    from scripts import openai_visual_live_e2e

    output = tmp_path / "openai-output.png"
    output.write_bytes(b"generated")

    def fake_generation(_args):
        return json.dumps(
            {
                "success": True,
                "image": str(output),
                "provider": "openai-codex",
                "model": "gpt-image-2-low",
                "response_id": "resp_openai_generation_1",
                "aspect_ratio": "square",
            }
        )

    report = openai_visual_live_e2e.build_openai_visual_live_e2e_report(
        work_dir=tmp_path,
        prompt="polished product image",
        aspect_ratio="square",
        generation_fn=fake_generation,
        env={
            "HERMES_VISUAL_LIVE_E2E": "1",
            "HERMES_OPENAI_VISUAL_LIVE_E2E": "1",
        },
    )

    script_path = Path(openai_visual_live_e2e.__file__).resolve()
    digest_source = dict(report)
    digest_source.pop("report_digest", None)
    expected_digest = hashlib.sha256(
        json.dumps(
            digest_source,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()

    assert report["schema_version"] == 1
    assert report["kind"] == "raphael_visual_live_e2e"
    assert report["producer"] == "openai-visual-live-e2e"
    assert report["command"] == "scripts/openai_visual_live_e2e.py"
    assert report["script_path"] == str(script_path)
    assert report["script_sha256"] == hashlib.sha256(script_path.read_bytes()).hexdigest()
    assert report["script_identity_verified"] is True
    assert report["report_digest"] == expected_digest


def test_openai_visual_live_e2e_rejects_provider_success_without_result_id(tmp_path):
    from scripts import openai_visual_live_e2e

    output = tmp_path / "openai-output.png"
    output.write_bytes(b"generated")

    def fake_generation(_args):
        return json.dumps(
            {
                "success": True,
                "image": str(output),
                "provider": "openai-codex",
                "model": "gpt-image-2-low",
                "aspect_ratio": "square",
            }
        )

    report = openai_visual_live_e2e.build_openai_visual_live_e2e_report(
        work_dir=tmp_path,
        prompt="polished product image",
        aspect_ratio="square",
        generation_fn=fake_generation,
        env={
            "HERMES_VISUAL_LIVE_E2E": "1",
            "HERMES_OPENAI_VISUAL_LIVE_E2E": "1",
        },
    )

    assert report["success"] is False
    assert report["status"] == "result_surface_unverified"
    assert report["artifact"]["exists"] is True
    assert report["result_surface_id"] == ""
    assert report["self_review"]["artifact_verified"] is True
    assert "provider result id" in report["self_review"]["next_action"]


def test_openai_visual_live_e2e_cli_attaches_quality_review_report(
    monkeypatch,
    tmp_path,
    capsys,
):
    from scripts import openai_visual_live_e2e

    output = tmp_path / "openai-reviewed.png"
    output.write_bytes(b"generated")
    artifact_sha256 = hashlib.sha256(b"generated").hexdigest()
    review_digest = hashlib.sha256(b"openai quality review").hexdigest()
    transcript_report = tmp_path / "model-review-transcript.json"
    transcript_report.write_text("{}", encoding="utf-8")
    transcript_digest = hashlib.sha256(b"{}").hexdigest()
    review_report = tmp_path / "quality-review.json"
    review_report.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "raphael_visual_quality_review",
                "generated_at": "2026-06-30T13:20:00Z",
                "command": "vision-backed artifact quality review",
                "run_id": "openai-quality-review-1",
                "producer": "hermes-visual-quality-review",
                "reviewer": "independent-vision-release-review",
                "artifact_path": str(output),
                "artifact_sha256": artifact_sha256,
                "artifact_size_bytes": len(b"generated"),
                "artifact_mtime": output.stat().st_mtime,
                "artifact_identity_verified": True,
                "review_source_type": "vision_model",
                "review_model_provider": "openai",
                "review_model": "gpt-5.5-vision",
                "review_evidence_digest": review_digest,
                "review_response_id": "resp_quality_review_1",
                "review_transcript_report_path": str(transcript_report),
                "review_transcript_digest": transcript_digest,
                "review_provenance_verified": True,
                "artifact_quality_verdict": "pass",
                "dimensions": {
                    "composition": "pass",
                    "prompt_adherence": "pass",
                    "geometry": "pass",
                    "subject_quality": "pass",
                },
            }
        ),
        encoding="utf-8",
    )

    def fake_generation(_args):
        return json.dumps(
            {
                "success": True,
                "image": str(output),
                "provider": "openai-codex",
                "model": "gpt-image-2-low",
                "response_id": "resp_openai_generation_2",
            }
        )

    monkeypatch.setenv("HERMES_VISUAL_LIVE_E2E", "1")
    monkeypatch.setenv("HERMES_OPENAI_VISUAL_LIVE_E2E", "1")
    monkeypatch.setattr(openai_visual_live_e2e, "_generate_with_openai_provider", fake_generation)

    exit_code = openai_visual_live_e2e.main(
        [
            "--prompt",
            "polished final image",
            "--work-dir",
            str(tmp_path),
            "--quality-review-report",
            str(review_report),
        ]
    )

    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert report["quality_review"]["source_report_path"] == str(review_report)
    assert report["quality_review"]["run_id"] == "openai-quality-review-1"
    assert report["quality_review"]["reviewer"] == "independent-vision-release-review"
    assert report["quality_review"]["artifact_path"] == str(output)
    assert report["quality_review"]["artifact_sha256"] == artifact_sha256
    assert report["quality_review"]["artifact_size_bytes"] == len(b"generated")
    assert report["quality_review"]["artifact_identity_verified"] is True
    assert report["quality_review"]["review_source_type"] == "vision_model"
    assert report["quality_review"]["review_model_provider"] == "openai"
    assert report["quality_review"]["review_model"] == "gpt-5.5-vision"
    assert report["quality_review"]["review_evidence_digest"] == review_digest
    assert report["quality_review"]["review_response_id"] == "resp_quality_review_1"
    assert report["quality_review"]["review_transcript_report_path"] == str(
        transcript_report
    )
    assert report["quality_review"]["review_transcript_digest"] == transcript_digest
    assert report["quality_review"]["review_provenance_verified"] is True
    assert report["self_review"]["artifact_quality_verdict"] == "pass"
    assert "media release gate" in report["self_review"]["next_action"]


def test_openai_visual_live_e2e_cli_attaches_quality_review_to_existing_report(
    monkeypatch,
    tmp_path,
    capsys,
):
    from scripts import openai_visual_live_e2e

    output = tmp_path / "openai-reviewed.png"
    output.write_bytes(b"generated")
    artifact_sha256 = hashlib.sha256(b"generated").hexdigest()
    review_digest = hashlib.sha256(b"openai quality review").hexdigest()
    transcript_report = tmp_path / "model-review-transcript.json"
    transcript_report.write_text("{}", encoding="utf-8")
    transcript_digest = hashlib.sha256(b"{}").hexdigest()
    live_report = tmp_path / "openai-live-report.json"
    attached_report = tmp_path / "openai-live-report.reviewed.json"
    live_report.write_text(
        json.dumps(
            {
                "run_id": "openai-visual-live-1",
                "generated_at": "2026-06-30T13:20:00Z",
                "success": True,
                "status": "completed",
                "provider_mode": "openai-gpt-image-live",
                "result_surface_id": "openai-response:openai-visual-live-1",
                "artifact": {
                    "path": str(output),
                    "exists": True,
                    "source": "openai_response",
                    "durability": "provider_response_artifact",
                    "history_verified": True,
                },
            }
        ),
        encoding="utf-8",
    )
    review_report = tmp_path / "quality-review.json"
    review_report.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "raphael_visual_quality_review",
                "generated_at": "2026-06-30T13:25:00Z",
                "command": "vision-backed artifact quality review",
                "run_id": "openai-quality-review-1",
                "producer": "hermes-visual-quality-review",
                "reviewer": "independent-vision-release-review",
                "artifact_path": str(output),
                "artifact_sha256": artifact_sha256,
                "artifact_size_bytes": len(b"generated"),
                "artifact_mtime": output.stat().st_mtime,
                "artifact_identity_verified": True,
                "review_source_type": "vision_model",
                "review_model_provider": "openai",
                "review_model": "gpt-5.5-vision",
                "review_evidence_digest": review_digest,
                "review_response_id": "resp_quality_review_1",
                "review_transcript_report_path": str(transcript_report),
                "review_transcript_digest": transcript_digest,
                "review_provenance_verified": True,
                "artifact_quality_verdict": "pass",
                "dimensions": {
                    "composition": "pass",
                    "prompt_adherence": "pass",
                    "geometry": "pass",
                    "subject_quality": "pass",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        openai_visual_live_e2e,
        "_generate_with_openai_provider",
        lambda _args: (_ for _ in ()).throw(AssertionError("provider should not run")),
    )

    exit_code = openai_visual_live_e2e.main(
        [
            "--input-report",
            str(live_report),
            "--quality-review-report",
            str(review_report),
            "--output",
            str(attached_report),
        ]
    )

    report = json.loads(capsys.readouterr().out)
    written_report = json.loads(attached_report.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert written_report == report
    assert report["run_id"] == "openai-visual-live-1"
    assert report["quality_review"]["source_report_path"] == str(review_report)
    assert report["quality_review"]["run_id"] == "openai-quality-review-1"
    assert report["quality_review"]["reviewer"] == "independent-vision-release-review"
    assert report["quality_review"]["artifact_path"] == str(output)
    assert report["quality_review"]["artifact_sha256"] == artifact_sha256
    assert report["quality_review"]["artifact_size_bytes"] == len(b"generated")
    assert report["quality_review"]["artifact_identity_verified"] is True
    assert report["quality_review"]["review_source_type"] == "vision_model"
    assert report["quality_review"]["review_model_provider"] == "openai"
    assert report["quality_review"]["review_model"] == "gpt-5.5-vision"
    assert report["quality_review"]["review_evidence_digest"] == review_digest
    assert report["quality_review"]["review_response_id"] == "resp_quality_review_1"
    assert report["quality_review"]["review_transcript_report_path"] == str(
        transcript_report
    )
    assert report["quality_review"]["review_transcript_digest"] == transcript_digest
    assert report["quality_review"]["review_provenance_verified"] is True
    assert report["self_review"]["artifact_quality_verdict"] == "pass"
    assert "media release gate" in report["self_review"]["next_action"]


def test_openai_visual_live_e2e_rejects_quality_review_for_different_artifact(
    tmp_path,
):
    from scripts import openai_visual_live_e2e

    output = tmp_path / "openai-live.png"
    output.write_bytes(b"generated")
    reviewed_output = tmp_path / "different-reviewed.png"
    reviewed_output.write_bytes(b"different")
    review_report = tmp_path / "quality-review.json"
    review_report.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "raphael_visual_quality_review",
                "generated_at": "2026-06-30T13:25:00Z",
                "command": "vision-backed artifact quality review",
                "run_id": "openai-quality-review-1",
                "producer": "hermes-visual-quality-review",
                "reviewer": "independent-vision-release-review",
                "artifact_path": str(reviewed_output),
                "artifact_sha256": hashlib.sha256(b"different").hexdigest(),
                "artifact_size_bytes": len(b"different"),
                "artifact_mtime": reviewed_output.stat().st_mtime,
                "artifact_identity_verified": True,
                "review_source_type": "vision_model",
                "review_model_provider": "openai",
                "review_model": "gpt-5.5-vision",
                "review_evidence_digest": hashlib.sha256(b"review").hexdigest(),
                "review_response_id": "resp_quality_review_1",
                "review_transcript_report_path": str(tmp_path / "transcript.json"),
                "review_transcript_digest": hashlib.sha256(b"{}").hexdigest(),
                "review_provenance_verified": True,
                "artifact_quality_verdict": "pass",
            }
        ),
        encoding="utf-8",
    )
    live_report = {
        "run_id": "openai-visual-live-1",
        "generated_at": "2026-06-30T13:20:00Z",
        "success": True,
        "status": "completed",
        "provider_mode": "openai-gpt-image-live",
        "artifact": {
            "path": str(output),
            "exists": True,
            "source": "openai_response",
            "durability": "provider_response_artifact",
            "history_verified": True,
        },
    }

    report = openai_visual_live_e2e.attach_quality_review_report(
        live_report,
        review_report,
    )

    assert report["success"] is False
    assert report["status"] == "quality_review_artifact_mismatch"
    assert report["failure_class"] == "quality_review_artifact_mismatch"
    assert report["quality_review"]["artifact_path"] == str(reviewed_output)


def test_openai_visual_live_e2e_rejects_failing_quality_review_verdict(
    tmp_path,
):
    from scripts import openai_visual_live_e2e

    output = tmp_path / "openai-live.png"
    output.write_bytes(b"generated")
    review_report = tmp_path / "quality-review.json"
    review_report.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "raphael_visual_quality_review",
                "generated_at": "2026-06-30T13:25:00Z",
                "command": "vision-backed artifact quality review",
                "run_id": "openai-quality-review-1",
                "producer": "hermes-visual-quality-review",
                "reviewer": "independent-vision-release-review",
                "artifact_path": str(output),
                "artifact_sha256": hashlib.sha256(b"generated").hexdigest(),
                "artifact_size_bytes": len(b"generated"),
                "artifact_mtime": output.stat().st_mtime,
                "artifact_identity_verified": True,
                "review_source_type": "vision_model",
                "review_model_provider": "openai",
                "review_model": "gpt-5.5-vision",
                "review_evidence_digest": hashlib.sha256(b"review").hexdigest(),
                "review_response_id": "resp_quality_review_1",
                "review_transcript_report_path": str(tmp_path / "transcript.json"),
                "review_transcript_digest": hashlib.sha256(b"{}").hexdigest(),
                "review_provenance_verified": True,
                "artifact_quality_verdict": "fail",
            }
        ),
        encoding="utf-8",
    )
    live_report = {
        "run_id": "openai-visual-live-1",
        "generated_at": "2026-06-30T13:20:00Z",
        "success": True,
        "status": "completed",
        "provider_mode": "openai-gpt-image-live",
        "artifact": {
            "path": str(output),
            "exists": True,
            "source": "openai_response",
            "durability": "provider_response_artifact",
            "history_verified": True,
        },
    }

    report = openai_visual_live_e2e.attach_quality_review_report(
        live_report,
        review_report,
    )

    assert report["success"] is False
    assert report["status"] == "quality_review_failed"
    assert report["failure_class"] == "quality_review_failed"
    assert report["quality_review"]["artifact_quality_verdict"] == "fail"


def test_openai_visual_live_e2e_rejects_provider_self_quality_review(
    tmp_path,
):
    from scripts import openai_visual_live_e2e

    output = tmp_path / "openai-live.png"
    output.write_bytes(b"generated")
    transcript_report = tmp_path / "transcript.json"
    transcript_report.write_text("{}", encoding="utf-8")
    review_report = tmp_path / "quality-review.json"
    review_report.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "raphael_visual_quality_review",
                "generated_at": "2026-06-30T13:25:00Z",
                "command": "vision-backed artifact quality review",
                "run_id": "openai-quality-review-1",
                "producer": "hermes-visual-quality-review",
                "reviewer": "openai",
                "artifact_path": str(output),
                "artifact_sha256": hashlib.sha256(b"generated").hexdigest(),
                "artifact_size_bytes": len(b"generated"),
                "artifact_mtime": output.stat().st_mtime,
                "artifact_identity_verified": True,
                "review_source_type": "vision_model",
                "review_model_provider": "openai",
                "review_model": "gpt-5.5-vision",
                "review_evidence_digest": hashlib.sha256(b"review").hexdigest(),
                "review_response_id": "resp_quality_review_1",
                "review_transcript_report_path": str(transcript_report),
                "review_transcript_digest": hashlib.sha256(b"{}").hexdigest(),
                "review_provenance_verified": True,
                "artifact_quality_verdict": "pass",
            }
        ),
        encoding="utf-8",
    )
    live_report = {
        "run_id": "openai-visual-live-1",
        "generated_at": "2026-06-30T13:20:00Z",
        "success": True,
        "status": "completed",
        "provider_mode": "openai-gpt-image-live",
        "artifact": {
            "path": str(output),
            "exists": True,
            "source": "openai_response",
            "durability": "provider_response_artifact",
            "history_verified": True,
        },
    }

    report = openai_visual_live_e2e.attach_quality_review_report(
        live_report,
        review_report,
    )

    assert report["success"] is False
    assert report["status"] == "quality_review_unverified"
    assert report["failure_class"] == "quality_review_unverified"
    assert report["quality_review"]["reviewer"] == "openai"
