from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_visual_agent_report_summarizes_health_without_raw_prompts(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from scripts.visual_agent_report import build_visual_agent_report

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    _record_request_attempt_artifact(
        ledger,
        request_id="vrq_image",
        attempt_id="vat_image",
        artifact_id="var_image",
        kind="image",
        created_at="2026-06-20T00:01:00Z",
    )
    _record_request_attempt_artifact(
        ledger,
        request_id="vrq_video",
        attempt_id="vat_video",
        artifact_id="var_video",
        kind="video",
        created_at="2026-06-20T00:02:00Z",
    )
    ledger.record_delivery(
        request_id="vrq_image",
        attempt_id="vat_image",
        artifact_id="var_image",
        platform="slack",
        destination_id="D123",
        delivery_status="sent",
        delivered_at="2026-06-20T00:03:00Z",
    )
    request_id = ledger.record_request(
        user_prompt="private prompt that must not appear",
        normalized_intent={"modality": "image"},
        modality="image",
        operation="text_to_image",
        platform="slack",
        channel_id="D123",
        user_id="U123",
        message_id="msg-error",
        conversation_id="slack:D123",
        created_at="2026-06-20T00:04:00Z",
        status="failed",
    )
    ledger.record_attempt(
        request_id=request_id,
        attempt_id="vat_error",
        candidate_index=0,
        provider="xai",
        model="grok-imagine",
        prompt_original="private prompt that must not appear",
        prompt_mediated="private mediated prompt that must not appear",
        provider_error_type="content_moderation",
        provider_error_message="blocked",
        created_at="2026-06-20T00:04:00Z",
    )

    payload = build_visual_agent_report(
        ledger.path,
        since="2026-06-20T00:00:00Z",
    )

    assert payload["delivery"]["sent"] == 1
    assert payload["artifacts"]["image"] == 1
    assert payload["artifacts"]["video"] == 1
    assert payload["provider_errors"]["content_moderation"] == 1
    assert payload["source_metadata"]["missing_request_source_metadata"] == 0
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "private prompt" not in serialized
    assert "raw_prompts" not in payload


def test_visual_agent_report_cli_outputs_json(tmp_path, capsys):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from scripts.visual_agent_report import main

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    _record_request_attempt_artifact(
        ledger,
        request_id="vrq_image",
        attempt_id="vat_image",
        artifact_id="var_image",
        kind="image",
        created_at="2026-06-20T00:01:00Z",
    )

    exit_code = main(
        [
            "--ledger-path",
            str(ledger.path),
            "--since-local-date",
            "2026-06-20",
            "--timezone",
            "UTC",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out)["artifacts"]["image"] == 1


def test_visual_agent_report_script_runs_when_called_by_file_path(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    _record_request_attempt_artifact(
        ledger,
        request_id="vrq_image",
        attempt_id="vat_image",
        artifact_id="var_image",
        kind="image",
        created_at="2026-06-20T00:01:00Z",
    )
    script = Path(__file__).resolve().parents[2] / "scripts" / "visual_agent_report.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--ledger-path",
            str(ledger.path),
            "--since",
            "2026-06-20T00:00:00Z",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["artifacts"]["image"] == 1


def test_visual_agent_report_handles_historical_schema_without_message_id_column(
    tmp_path,
):
    from scripts.visual_agent_report import build_visual_agent_report

    ledger_path = tmp_path / "visual.sqlite3"
    _create_historical_report_schema(ledger_path)

    payload = build_visual_agent_report(
        ledger_path,
        since="2026-06-20T00:00:00Z",
    )

    assert payload["requests"]["total"] == 1
    assert payload["artifacts"]["image"] == 1
    assert payload["delivery"]["sent"] == 1
    assert payload["source_metadata"]["missing_request_source_metadata"] == 1


def _record_request_attempt_artifact(
    ledger,
    *,
    request_id: str,
    attempt_id: str,
    artifact_id: str,
    kind: str,
    created_at: str,
) -> None:
    ledger.record_request(
        request_id=request_id,
        user_prompt="product showcase",
        normalized_intent={"modality": kind},
        modality=kind,
        operation="generated",
        platform="slack",
        channel_id="D123",
        user_id="U123",
        message_id=f"msg-{artifact_id}",
        conversation_id="slack:D123",
        created_at=created_at,
        status="completed",
    )
    ledger.record_attempt(
        request_id=request_id,
        attempt_id=attempt_id,
        candidate_index=0,
        provider="fake",
        model=f"fake-{kind}",
        prompt_original="product showcase",
        prompt_mediated="product showcase",
        created_at=created_at,
    )
    ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        kind=kind,
        local_path=f"/tmp/{artifact_id}.{'mp4' if kind == 'video' else 'png'}",
        mime_type="video/mp4" if kind == "video" else "image/png",
        is_stable=True,
        freshness_status="fresh",
        created_at=created_at,
    )


def _create_historical_report_schema(path):
    import sqlite3

    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE visual_requests (
                request_id TEXT PRIMARY KEY,
                conversation_id TEXT,
                user_id TEXT,
                platform TEXT,
                channel_id TEXT,
                thread_id TEXT,
                user_prompt TEXT,
                normalized_intent_json TEXT,
                modality TEXT,
                operation TEXT,
                created_at TEXT,
                policy_context_json TEXT,
                status TEXT
            );
            CREATE TABLE visual_attempts (
                attempt_id TEXT PRIMARY KEY,
                request_id TEXT,
                candidate_index INTEGER,
                provider TEXT,
                model TEXT,
                strategy_id TEXT,
                strategy_version TEXT,
                prompt_original TEXT,
                prompt_mediated TEXT,
                prompt_negative TEXT,
                parameters_requested_json TEXT,
                parameters_effective_json TEXT,
                input_artifacts_json TEXT,
                provider_request_id TEXT,
                provider_latency_ms INTEGER,
                provider_cost_estimate REAL,
                provider_error_type TEXT,
                provider_error_message TEXT,
                created_at TEXT
            );
            CREATE TABLE visual_artifacts (
                artifact_id TEXT PRIMARY KEY,
                attempt_id TEXT,
                request_id TEXT,
                kind TEXT,
                local_path TEXT,
                source_url TEXT,
                content_hash TEXT,
                perceptual_hash TEXT,
                mime_type TEXT,
                bytes INTEGER,
                width INTEGER,
                height INTEGER,
                duration_ms INTEGER,
                frame_count INTEGER,
                created_at TEXT,
                expires_at TEXT,
                is_stable INTEGER,
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
                message_id TEXT,
                delivery_status TEXT,
                error_type TEXT,
                error_message TEXT,
                delivered_at TEXT
            );
            INSERT INTO visual_requests (
                request_id, conversation_id, user_id, platform, channel_id,
                thread_id, user_prompt, normalized_intent_json, modality,
                operation, created_at, policy_context_json, status
            ) VALUES (
                'vrq_image', 'slack:D123', 'U123', 'slack', 'D123',
                NULL, 'private prompt', '{}', 'image', 'generated',
                '2026-06-20T00:01:00Z', '{}', 'completed'
            );
            INSERT INTO visual_attempts (
                attempt_id, request_id, candidate_index, provider, model,
                prompt_original, prompt_mediated, created_at
            ) VALUES (
                'vat_image', 'vrq_image', 0, 'fake', 'fake-image',
                'private prompt', 'private mediated prompt',
                '2026-06-20T00:01:00Z'
            );
            INSERT INTO visual_artifacts (
                artifact_id, attempt_id, request_id, kind, local_path,
                mime_type, is_stable, freshness_status, created_at
            ) VALUES (
                'var_image', 'vat_image', 'vrq_image', 'image',
                '/tmp/var_image.png', 'image/png', 1, 'fresh',
                '2026-06-20T00:01:00Z'
            );
            INSERT INTO visual_deliveries (
                delivery_id, request_id, attempt_id, artifact_id, platform,
                destination_id, message_id, delivery_status, delivered_at
            ) VALUES (
                'vdl_image', 'vrq_image', 'vat_image', 'var_image',
                'slack', 'D123', 'msg-image', 'sent',
                '2026-06-20T00:02:00Z'
            );
            """
        )
