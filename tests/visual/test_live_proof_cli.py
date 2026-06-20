from __future__ import annotations

import pytest

from scripts.visual_agent_live_proof import _resolve_since


def test_resolve_since_converts_local_date_to_utc_midnight():
    assert (
        _resolve_since(
            since=None,
            since_local_date="2026-06-20",
            timezone_name="Asia/Taipei",
        )
        == "2026-06-19T16:00:00Z"
    )


def test_resolve_since_rejects_ambiguous_since_inputs():
    with pytest.raises(ValueError, match="Use either"):
        _resolve_since(
            since="2026-06-20T00:00:00Z",
            since_local_date="2026-06-20",
            timezone_name="Asia/Taipei",
        )


def test_cli_can_skip_source_metadata_for_historical_rows(tmp_path, capsys):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from scripts.visual_agent_live_proof import main

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    for kind in ("image", "video"):
        request_id = f"vrq_{kind}"
        attempt_id = f"vat_{kind}"
        artifact_id = f"var_{kind}"
        ledger.record_request(
            request_id=request_id,
            user_prompt="product showcase",
            normalized_intent={"modality": kind},
            modality=kind,
            operation="generated",
            created_at="2026-06-20T00:01:00Z",
        )
        ledger.record_attempt(
            request_id=request_id,
            attempt_id=attempt_id,
            candidate_index=0,
            provider="fake",
            model=f"fake-{kind}",
            prompt_original="product showcase",
            prompt_mediated="product showcase",
            created_at="2026-06-20T00:01:00Z",
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
            created_at="2026-06-20T00:01:00Z",
        )
        ledger.record_delivery(
            request_id=request_id,
            attempt_id=attempt_id,
            artifact_id=artifact_id,
            platform="slack",
            destination_id="D123",
            delivery_status="sent",
            delivered_at="2026-06-20T00:01:00Z",
        )

    exit_code = main(
        [
            "--ledger-path",
            str(ledger.path),
            "--since",
            "2026-06-20T00:00:00Z",
            "--platform",
            "slack",
            "--destination-id",
            "D123",
            "--no-require-source-metadata",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert '"success": true' in captured.out
