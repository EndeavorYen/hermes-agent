from __future__ import annotations

import json


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
