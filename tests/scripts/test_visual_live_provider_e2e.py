import json


def test_visual_live_provider_e2e_fixture_records_learning_evidence(tmp_path):
    from scripts.visual_live_provider_e2e import build_visual_live_provider_e2e_report

    report = build_visual_live_provider_e2e_report(
        mode="fixture",
        work_dir=tmp_path,
        candidate_budget=1,
        video_budget=1,
    )

    assert report["success"] is True
    assert report["provider_mode"] == "fixture"
    assert report["evidence"]["image_count"] == 1
    assert report["evidence"]["video_count"] == 1
    assert report["evidence"]["judgment_count"] >= 2
    assert report["evidence"]["ranking_count"] >= 2
    assert report["evidence"]["learning_trace_count"] >= 2
    assert report["evidence"]["judgments_with_learning_metadata"] >= 2


def test_visual_live_provider_e2e_fails_closed_when_provider_unavailable(monkeypatch, tmp_path):
    from scripts import visual_live_provider_e2e

    monkeypatch.setattr(visual_live_provider_e2e, "image_requirements_available", lambda: False)
    monkeypatch.setattr(visual_live_provider_e2e, "video_requirements_available", lambda: False)

    report = visual_live_provider_e2e.build_visual_live_provider_e2e_report(
        mode="live",
        work_dir=tmp_path,
    )

    assert report["success"] is False
    assert "provider_unavailable:image" in report["failures"]
    assert "provider_unavailable:video" in report["failures"]
    assert report["payload"] is None


def test_visual_live_provider_e2e_rejects_fixture_provider_in_live_mode(monkeypatch, tmp_path):
    from scripts import visual_live_provider_e2e

    monkeypatch.setattr(visual_live_provider_e2e, "image_requirements_available", lambda: True)
    monkeypatch.setattr(visual_live_provider_e2e, "video_requirements_available", lambda: True)

    def fake_package(args):
        return {
            "success": True,
            "visual_request_id": "vrq_missing",
            "images": ["/tmp/fake.png"],
            "videos": ["/tmp/fake.mp4"],
            "generation_payloads": {
                "image": {"success": True, "provider": "fixture", "model": "image"},
                "video": {"success": True, "provider": "fixture", "model": "video"},
            },
        }

    monkeypatch.setattr(visual_live_provider_e2e, "run_visual_package", fake_package)

    report = visual_live_provider_e2e.build_visual_live_provider_e2e_report(
        mode="live",
        work_dir=tmp_path,
    )

    assert report["success"] is False
    assert "non_live_provider_detected" in report["failures"]


def test_visual_live_provider_e2e_reads_legacy_judgments_by_artifact(monkeypatch, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path
    from scripts.visual_live_provider_e2e import inspect_visual_e2e_evidence

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ledger = VisualAttemptLedger(default_visual_ledger_path())
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="test",
        normalized_intent={"kind": "visual_package"},
        modality="package",
        operation="visual_package_generate",
        status="started",
    )
    attempt_id = ledger.record_attempt(
        request_id=request_id,
        candidate_index=0,
        provider="xai",
        model="grok-imagine-image-quality",
        prompt_original="test",
        prompt_mediated="test",
        parameters_requested={},
        parameters_effective={},
        status="completed",
    )
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        local_path=str(tmp_path / "image.jpg"),
        uri=str(tmp_path / "image.jpg"),
        content_hash="sha256:test",
        mime_type="image/jpeg",
        is_stable=True,
        freshness_status="fresh",
    )
    with ledger._connect() as conn:
        conn.execute("DROP TABLE visual_judgments")
        conn.execute(
            """
            CREATE TABLE visual_judgments (
                judgment_id TEXT PRIMARY KEY,
                artifact_id TEXT,
                attempt_id TEXT,
                judge_name TEXT NOT NULL,
                judge_version TEXT NOT NULL,
                score_json TEXT NOT NULL,
                confidence REAL NOT NULL,
                raw_output_json TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute("DROP TABLE visual_rankings")
        conn.execute(
            """
            CREATE TABLE visual_rankings (
                ranking_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                ranker_version TEXT NOT NULL,
                selected_attempt_id TEXT,
                selected_artifact_id TEXT,
                score_json TEXT NOT NULL,
                confidence REAL NOT NULL,
                decision TEXT NOT NULL,
                rationale_json TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    ledger.record_judgment(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        judge_name="visual_quality_judge",
        score=0.9,
        verdict="pass",
        details={"version": "visual_quality_judge.v0.1", "scores": {"aesthetic_fit": 0.9}},
        metadata={
            "intent_signature": "visig_demo",
            "strategy_signature": "vstrat_demo",
            "modality": "image",
        },
    )
    ledger.record_ranking(
        request_id=request_id,
        selected_artifact_id=artifact_id,
        decision="post",
        scores={"reward": {"confidence": 0.9}},
        metadata={"active_learning": {"action": "auto_post"}},
    )

    evidence = inspect_visual_e2e_evidence(
        {
            "visual_request_id": request_id,
            "images": [str(tmp_path / "image.jpg")],
            "videos": [],
        },
        require_video=False,
    )

    assert evidence["judgment_count"] == 1
    assert evidence["judgments_with_learning_metadata"] == 1
    assert evidence["ranking_count"] == 1
    assert evidence["learning_trace_count"] == 1


def test_visual_live_provider_e2e_classifies_attempt_failure_root_causes(monkeypatch, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path
    from scripts.visual_live_provider_e2e import inspect_visual_e2e_evidence

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ledger = VisualAttemptLedger(default_visual_ledger_path())
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="test",
        normalized_intent={"kind": "visual_package"},
        modality="package",
        operation="visual_package_generate",
        status="started",
    )
    for candidate_index in (0, 1):
        ledger.record_attempt(
            request_id=request_id,
            candidate_index=candidate_index,
            provider="xai-oauth",
            model="grok-imagine-image-quality",
            prompt_original="test",
            prompt_mediated="test",
            parameters_requested={"aspect_ratio": "1:1"},
            parameters_effective={"aspect_ratio": "1:1"},
            status="failed",
            error_type="api_error",
            error_message=(
                "xAI image generation failed (503): upstream connect error; "
                "Connection refused"
            ),
        )

    evidence = inspect_visual_e2e_evidence(
        {
            "success": False,
            "visual_request_id": request_id,
            "images": [],
            "videos": [],
            "generation_payloads": {
                "image": [
                    {"success": False, "error_type": "api_error"},
                    {"success": False, "retry_of": 0, "error_type": "api_error"},
                ]
            },
        },
        require_video=True,
    )

    assert evidence["provider_failure_classes"]["provider_unavailable"] == 2
    assert evidence["provider_error_codes"]["api_error"] == 2
    assert evidence["retry_attempt_count"] == 1


def test_visual_live_provider_e2e_reports_provider_unavailable_after_retry():
    from scripts.visual_live_provider_e2e import _payload_failures

    failures = _payload_failures(
        {
            "success": False,
            "images": [],
            "videos": [],
            "generation_payloads": {
                "image": [
                    {"success": False, "error_type": "api_error"},
                    {"success": False, "retry_of": 0, "error_type": "api_error"},
                ]
            },
        },
        {
            "image_count": 0,
            "video_count": 0,
            "judgment_count": 0,
            "ranking_count": 2,
            "learning_trace_count": 2,
            "judgments_with_learning_metadata": 0,
            "provider_failure_classes": {"provider_unavailable": 2},
            "provider_error_codes": {"api_error": 2},
            "retry_attempt_count": 1,
            "providers": ["xai-oauth"],
        },
        mode="live",
        require_video=True,
    )

    assert "provider_unavailable_after_retry" in failures


def test_visual_live_provider_e2e_cli_fixture_json(capsys, tmp_path):
    from scripts.visual_live_provider_e2e import main

    code = main(["--mode", "fixture", "--work-dir", str(tmp_path), "--json"])
    out = capsys.readouterr().out

    assert code == 0
    assert '"success": true' in out
    payload = json.loads(out)
    assert payload["evidence"]["judgment_count"] >= 2


def test_visual_live_provider_e2e_cli_writes_report_path(capsys, tmp_path):
    from scripts.visual_live_provider_e2e import main

    report_path = tmp_path / "live-provider-e2e.json"
    code = main(
        [
            "--mode",
            "fixture",
            "--work-dir",
            str(tmp_path),
            "--report-path",
            str(report_path),
        ]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert "visual live provider e2e passed" in out
    assert str(report_path) in out
    payload = json.loads(report_path.read_text())
    assert payload["success"] is True
    assert payload["evidence"]["learning_trace_count"] >= 2


def test_visual_live_provider_e2e_cli_captures_provider_noise(
    monkeypatch,
    capsys,
    tmp_path,
):
    from scripts import visual_live_provider_e2e

    def noisy_report(**kwargs):
        print("provider noise that should not reach terminal")
        return {
            "success": True,
            "provider_mode": kwargs["mode"],
            "failures": [],
            "provider_checks": {"image": True, "video": True},
            "payload": {"success": True},
            "evidence": {"learning_trace_count": 2},
        }

    monkeypatch.setattr(visual_live_provider_e2e, "build_visual_live_provider_e2e_report", noisy_report)
    report_path = tmp_path / "report.json"
    log_path = tmp_path / "provider.log"

    code = visual_live_provider_e2e.main(
        [
            "--mode",
            "fixture",
            "--work-dir",
            str(tmp_path),
            "--report-path",
            str(report_path),
            "--capture-log-path",
            str(log_path),
        ]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert "provider noise" not in out
    assert "provider noise that should not reach terminal" in log_path.read_text()
    assert json.loads(report_path.read_text())["success"] is True


def test_visual_live_provider_e2e_requires_inline_vision_for_live_image_outputs():
    from scripts.visual_live_provider_e2e import _payload_failures

    failures = _payload_failures(
        {"success": True, "images": ["/tmp/image.png"], "videos": []},
        {
            "image_count": 1,
            "video_count": 0,
            "judgment_count": 1,
            "ranking_count": 1,
            "learning_trace_count": 1,
            "judgments_with_learning_metadata": 1,
            "inline_vision_judgment_count": 0,
            "providers": ["xai"],
        },
        mode="live",
        require_video=False,
    )

    assert "missing_inline_vision_judgment" in failures


def test_visual_live_provider_e2e_counts_legacy_score_json_inline_vision():
    from scripts.visual_live_provider_e2e import _judgment_uses_inline_vision

    assert _judgment_uses_inline_vision(
        {
            "judge_name": "visual_quality_judge",
            "score_json": {
                "evidence": {
                    "source": "inline_vision_judge",
                    "summary": "privacy-safe independent visual quality observation",
                },
                "scores": {"aesthetic_fit": 0.85},
            },
        }
    )
