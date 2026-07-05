import json
import sqlite3


def test_visual_evidence_self_smoke_passes_in_isolated_home(tmp_path, capsys):
    from scripts.visual_evidence_self_smoke import main

    exit_code = main(["--work-dir", str(tmp_path), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["success"] is True
    assert payload["proof"]["duplicate_artifact_delivery_count"] == 0
    assert payload["proof"]["missing_source_metadata_count"] == 0
    assert payload["feedback"]["count"] >= 2
    assert payload["judgments"]["count"] >= 2
    assert "raw_prompt" not in json.dumps(payload).lower()


def test_visual_evidence_report_supports_legacy_runtime_schema(tmp_path):
    from scripts.visual_evidence_report import build_visual_evidence_report

    db_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE visual_requests (
                request_id TEXT PRIMARY KEY,
                user_prompt TEXT NOT NULL,
                normalized_intent_json TEXT NOT NULL,
                modality TEXT NOT NULL,
                operation TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE visual_attempts (
                attempt_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL
            );
            CREATE TABLE visual_artifacts (
                artifact_id TEXT PRIMARY KEY,
                attempt_id TEXT NOT NULL,
                request_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                local_path TEXT,
                source_url TEXT,
                content_hash TEXT,
                freshness_status TEXT NOT NULL
            );
            CREATE TABLE visual_deliveries (
                delivery_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                attempt_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                destination_id TEXT NOT NULL,
                thread_id TEXT,
                delivery_status TEXT NOT NULL
            );
            CREATE TABLE visual_feedback (
                feedback_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL
            );
            INSERT INTO visual_requests VALUES ('vrq_1', 'redacted', '{}', 'image', 'generate', 'now', 'completed');
            INSERT INTO visual_attempts VALUES ('vat_1', 'vrq_1');
            INSERT INTO visual_artifacts VALUES ('var_1', 'vat_1', 'vrq_1', 'image', '/tmp/a.png', NULL, 'sha256:a', 'fresh');
            INSERT INTO visual_deliveries VALUES ('vdl_1', 'vrq_1', 'vat_1', 'var_1', 'slack', 'C1', 'T1', 'sent');
            INSERT INTO visual_feedback VALUES ('vfb_1', 'vrq_1');
            """
        )

    payload = build_visual_evidence_report(db_path)

    assert payload["success"] is True
    assert payload["proof"]["duplicate_artifact_delivery_count"] == 0
    assert payload["proof"]["missing_source_metadata_count"] == 0


def test_visual_evidence_report_accepts_legacy_remote_source_without_hash(tmp_path):
    from scripts.visual_evidence_report import build_visual_evidence_report

    db_path = tmp_path / "remote.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE visual_requests (request_id TEXT PRIMARY KEY);
            CREATE TABLE visual_attempts (attempt_id TEXT PRIMARY KEY, request_id TEXT);
            CREATE TABLE visual_artifacts (
                artifact_id TEXT PRIMARY KEY,
                attempt_id TEXT,
                request_id TEXT,
                kind TEXT,
                local_path TEXT,
                source_url TEXT,
                content_hash TEXT,
                freshness_status TEXT
            );
            CREATE TABLE visual_deliveries (
                delivery_id TEXT PRIMARY KEY,
                request_id TEXT,
                attempt_id TEXT,
                artifact_id TEXT,
                platform TEXT,
                destination_id TEXT,
                thread_id TEXT,
                delivery_status TEXT
            );
            CREATE TABLE visual_feedback (feedback_id TEXT PRIMARY KEY, request_id TEXT);
            INSERT INTO visual_requests VALUES ('vrq_remote');
            INSERT INTO visual_attempts VALUES ('vat_remote', 'vrq_remote');
            INSERT INTO visual_artifacts VALUES (
                'var_remote',
                'vat_remote',
                'vrq_remote',
                'video',
                NULL,
                'https://vidgen.x.ai/xai-vidgen-bucket/current.mp4',
                NULL,
                'unknown'
            );
            """
        )

    payload = build_visual_evidence_report(db_path)

    assert payload["success"] is True
    assert payload["proof"]["missing_source_metadata_count"] == 0


def test_visual_evidence_report_can_scope_to_request(tmp_path):
    from scripts.visual_evidence_report import build_visual_evidence_report

    db_path = tmp_path / "scoped.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE visual_requests (id TEXT PRIMARY KEY);
            CREATE TABLE visual_attempts (id TEXT PRIMARY KEY, request_id TEXT);
            CREATE TABLE visual_artifacts (
                id TEXT PRIMARY KEY,
                request_id TEXT,
                kind TEXT,
                local_path TEXT,
                uri TEXT,
                content_hash TEXT,
                freshness_status TEXT
            );
            CREATE TABLE visual_deliveries (
                id TEXT PRIMARY KEY,
                request_id TEXT,
                artifact_id TEXT,
                destination TEXT,
                destination_id TEXT,
                thread_id TEXT,
                platform TEXT,
                delivery_status TEXT
            );
            CREATE TABLE visual_feedback (id TEXT PRIMARY KEY, request_id TEXT);
            INSERT INTO visual_requests VALUES ('vrq_good'), ('vrq_bad');
            INSERT INTO visual_attempts VALUES ('vat_good', 'vrq_good'), ('vat_bad', 'vrq_bad');
            INSERT INTO visual_artifacts VALUES ('var_good', 'vrq_good', 'image', '/tmp/a.png', NULL, 'sha256:a', 'fresh');
            INSERT INTO visual_artifacts VALUES ('var_bad', 'vrq_bad', 'image', NULL, NULL, NULL, NULL);
            INSERT INTO visual_deliveries VALUES ('vdl_good', 'vrq_good', 'var_good', 'slack:C:T', 'C', 'T', 'slack', 'sent');
            INSERT INTO visual_feedback VALUES ('vfb_good', 'vrq_good'), ('vfb_bad', 'vrq_bad');
            """
        )

    payload = build_visual_evidence_report(db_path, request_id="vrq_good")

    assert payload["success"] is True
    assert payload["requests"]["count"] == 1
    assert payload["proof"]["missing_source_metadata_count"] == 0


def test_visual_evidence_report_cli_outputs_json(tmp_path, capsys):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from scripts.visual_evidence_report import main

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed")

    exit_code = main(["--db-path", str(tmp_path / "visual.sqlite3"), "--request-id", request_id, "--json"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert '"success": true' in out
