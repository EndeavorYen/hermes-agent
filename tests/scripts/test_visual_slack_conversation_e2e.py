from __future__ import annotations

import json


def _fake_delivery_report(**kwargs):
    return {
        "success": True,
        "mode": kwargs["mode"],
        "failures": [],
        "target": {
            "platform": "slack",
            "destination_id": kwargs["target"],
            "thread_id": kwargs["thread_id"],
        },
        "visual": {
            "image_count": 1,
            "video_count": 1,
            "artifact_count": 2,
            "judgment_count": 2,
            "ranking_count": 2,
        },
        "delivery": {
            "deliverable_count": 2,
            "sent_count": 2,
            "duplicate_delivery_count": 0,
            "uploaded_image_file_count": 1 if kwargs.get("upload") else 0,
            "uploaded_video_file_count": 1 if kwargs.get("upload") else 0,
            "uploaded_remote_video_url_count": 0,
        },
        "record_summary": {
            "upload_enabled": bool(kwargs.get("upload")),
        },
    }


def test_visual_slack_conversation_e2e_fixture_dispatches_slack_ingress_and_delivery(
    monkeypatch,
    tmp_path,
):
    from scripts import visual_slack_conversation_e2e

    prompt = "請幫我產出一張產品照和一段影片：霧黑鋼筆。SECRET_VISUAL_PROMPT"
    delivery_calls = []

    def fake_delivery(**kwargs):
        delivery_calls.append(kwargs)
        return _fake_delivery_report(**kwargs)

    monkeypatch.setattr(
        visual_slack_conversation_e2e,
        "build_visual_slack_delivery_e2e_report",
        fake_delivery,
    )

    report = visual_slack_conversation_e2e.build_visual_slack_conversation_e2e_report(
        mode="fixture",
        work_dir=tmp_path,
        prompt=prompt,
        target="D_TEST",
    )

    assert report["success"] is True
    assert report["mode"] == "fixture"
    assert report["ingress"]["success"] is True
    assert report["ingress"]["platform"] == "slack"
    assert report["ingress"]["chat_id"] == "D_TEST"
    assert report["ingress"]["message_type"] == "text"
    assert report["ingress"]["media_count"] == 0
    assert report["ingress"]["prompt_sha256"]
    assert report["ingress"]["prompt_length"] == len(prompt)
    assert report["conversation_route"]["success"] is True
    assert report["slack_delivery"]["delivery"]["sent_count"] == 2
    assert delivery_calls == [
        {
            "mode": "fixture",
            "work_dir": tmp_path,
            "prompt": prompt,
            "target": "D_TEST",
            "thread_id": report["ingress"]["thread_id"],
            "candidate_budget": 1,
            "video_budget": 1,
            "duration": 4,
            "require_video": True,
            "upload": None,
        }
    ]
    assert "SECRET_VISUAL_PROMPT" not in json.dumps(report, ensure_ascii=False)


def test_visual_slack_conversation_e2e_fails_when_slack_ingress_drops_message(
    monkeypatch,
    tmp_path,
):
    from scripts import visual_slack_conversation_e2e

    monkeypatch.setattr(
        visual_slack_conversation_e2e,
        "_capture_slack_message_event",
        lambda **_kwargs: {
            "success": False,
            "failures": ["slack_ingress_not_dispatched"],
            "summary": {
                "success": False,
                "platform": "slack",
                "chat_id": "D_TEST",
            },
            "event": None,
        },
    )

    report = visual_slack_conversation_e2e.build_visual_slack_conversation_e2e_report(
        mode="fixture",
        work_dir=tmp_path,
        target="D_TEST",
    )

    assert report["success"] is False
    assert "slack_ingress_not_dispatched" in report["failures"]
    assert report["slack_delivery"]["status"] == "skipped"


def test_visual_slack_conversation_e2e_exports_repair_action_from_provider_failure(
    monkeypatch,
    tmp_path,
):
    from scripts import visual_slack_conversation_e2e

    def failed_delivery(**kwargs):
        return {
            "success": False,
            "mode": kwargs["mode"],
            "failures": ["visual_generation_failed"],
            "target": {
                "platform": "slack",
                "destination_id": kwargs["target"],
                "thread_id": kwargs["thread_id"],
            },
            "visual": {
                "request_id": "vrq_failed",
                "image_count": 0,
                "video_count": 0,
                "provider_failure_classes": {"content_moderation": 2},
                "provider_error_codes": {"api_error": 2},
                "recovery_summary": {
                    "provider_failure_count": 2,
                    "provider_failure_classes": {"content_moderation": 2},
                    "provider_error_codes": {"api_error": 2},
                    "retry_attempt_count": 1,
                    "negotiation_attempted": True,
                    "negotiation_success": False,
                },
            },
            "delivery": {"deliverable_count": 0, "sent_count": 0},
        }

    monkeypatch.setattr(
        visual_slack_conversation_e2e,
        "build_visual_slack_delivery_e2e_report",
        failed_delivery,
    )

    report = visual_slack_conversation_e2e.build_visual_slack_conversation_e2e_report(
        mode="fixture",
        work_dir=tmp_path,
        target="D_TEST",
    )

    assert report["success"] is False
    assert "slack_delivery_failed" in report["failures"]
    assert {
        "type": "safe_reframe_provider_retry",
        "track": "provider",
        "reason": "slack_conversation_content_moderation_failure",
        "confidence": 0.75,
        "evidence_count": 2,
        "requires_human_feedback": False,
        "activation_status": "next_run",
        "source": "slack_conversation_e2e",
        "provider_failure_classes": {"content_moderation": 2},
        "provider_error_codes": {"api_error": 2},
    } in report["next_actions"]


def test_visual_slack_conversation_e2e_live_uses_runtime_target_resolution(
    monkeypatch,
    tmp_path,
):
    from scripts import visual_slack_conversation_e2e

    delivery_calls = []
    monkeypatch.setattr(
        visual_slack_conversation_e2e,
        "_resolve_target",
        lambda *, mode, target: "D_LIVE" if mode == "live" and target is None else target,
    )

    def fake_delivery(**kwargs):
        delivery_calls.append(kwargs)
        return _fake_delivery_report(**kwargs)

    monkeypatch.setattr(
        visual_slack_conversation_e2e,
        "build_visual_slack_delivery_e2e_report",
        fake_delivery,
    )

    report = visual_slack_conversation_e2e.build_visual_slack_conversation_e2e_report(
        mode="live",
        work_dir=tmp_path,
        target=None,
        upload=True,
    )

    assert report["success"] is True
    assert report["ingress"]["chat_id"] == "D_LIVE"
    assert delivery_calls[0]["target"] == "D_LIVE"
    assert delivery_calls[0]["upload"] is True


def test_visual_slack_conversation_e2e_live_fails_without_runtime_target(monkeypatch, tmp_path):
    from scripts import visual_slack_conversation_e2e

    monkeypatch.setattr(
        visual_slack_conversation_e2e,
        "_resolve_target",
        lambda *, mode, target: None,
    )

    report = visual_slack_conversation_e2e.build_visual_slack_conversation_e2e_report(
        mode="live",
        work_dir=tmp_path,
        target=None,
    )

    assert report["success"] is False
    assert report["failures"] == ["missing_slack_target"]
    assert report["ingress"]["status"] == "skipped"
    assert report["slack_delivery"]["status"] == "skipped"


def test_visual_slack_conversation_e2e_cli_json(monkeypatch, capsys, tmp_path):
    from scripts import visual_slack_conversation_e2e

    monkeypatch.setattr(
        visual_slack_conversation_e2e,
        "build_visual_slack_delivery_e2e_report",
        _fake_delivery_report,
    )

    code = visual_slack_conversation_e2e.main(
        ["--work-dir", str(tmp_path), "--target", "D_TEST", "--json"]
    )
    out = capsys.readouterr().out

    assert code == 0
    payload = json.loads(out)
    assert payload["success"] is True
    assert payload["ingress"]["platform"] == "slack"
    assert "prompt" not in payload["ingress"]
