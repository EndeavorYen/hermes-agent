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
