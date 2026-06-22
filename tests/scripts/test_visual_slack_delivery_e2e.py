from __future__ import annotations


def _fake_visual_package_payload(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path
    from agent.visual.tracking import visual_delivery_metadata

    image_path = tmp_path / "candidate.png"
    video_path = tmp_path / "candidate.mp4"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    video_path.write_bytes(b"\x00\x00\x00\x18ftypmp42")

    ledger = VisualAttemptLedger(default_visual_ledger_path())
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="live upload fixture",
        normalized_intent={"kind": "visual_package"},
        modality="package",
        operation="visual_package_generate",
        status="completed",
    )
    image_attempt_id = ledger.record_attempt(
        request_id=request_id,
        candidate_index=0,
        provider="xai",
        model="grok-imagine-image-quality",
        prompt_original="image",
        prompt_mediated="image",
        parameters_requested={},
        parameters_effective={},
        status="completed",
    )
    video_attempt_id = ledger.record_attempt(
        request_id=request_id,
        candidate_index=0,
        provider="xai",
        model="grok-imagine-video-quality",
        prompt_original="video",
        prompt_mediated="video",
        parameters_requested={},
        parameters_effective={},
        status="completed",
    )
    image_artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=image_attempt_id,
        kind="image",
        local_path=str(image_path),
        uri=str(image_path),
        content_hash="sha256:image-live",
        mime_type="image/png",
        is_stable=True,
        freshness_status="fresh",
    )
    video_artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=video_attempt_id,
        kind="video",
        local_path=str(video_path),
        uri=str(video_path),
        content_hash="sha256:video-live",
        mime_type="video/mp4",
        is_stable=True,
        freshness_status="fresh",
    )
    return {
        "success": True,
        "visual_request_id": request_id,
        "images": [str(image_path)],
        "videos": [str(video_path)],
        "delivery_metadata": visual_delivery_metadata(
            request_id=request_id,
            attempt_id=None,
            artifact_ids=[image_artifact_id, video_artifact_id],
            artifact_paths=[str(image_path), str(video_path)],
            selected_artifact_ids=[image_artifact_id, video_artifact_id],
        ),
    }


def test_visual_slack_delivery_fixture_records_selected_media(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from scripts.visual_slack_delivery_e2e import build_visual_slack_delivery_e2e_report

    report = build_visual_slack_delivery_e2e_report(
        mode="fixture",
        work_dir=tmp_path,
        target="D_TEST",
        thread_id="1719000000.000001",
    )

    assert report["success"] is True
    assert report["mode"] == "fixture"
    assert report["target"] == {
        "platform": "slack",
        "destination_id": "D_TEST",
        "thread_id": "1719000000.000001",
    }
    assert report["delivery"]["deliverable_count"] == 2
    assert report["delivery"]["sent_count"] == 2
    assert report["delivery"]["missing_delivery_artifact_ids"] == []
    assert report["delivery"]["duplicate_delivery_count"] == 0

    ledger = VisualAttemptLedger(tmp_path / "visual" / "attempt_ledger.sqlite3")
    deliveries = ledger.list_deliveries(request_id=report["delivery"]["request_id"])
    assert {row["delivery_status"] for row in deliveries} == {"sent"}
    assert {row["destination_id"] for row in deliveries} == {"D_TEST"}


def test_visual_slack_delivery_live_requires_upload_gate(monkeypatch, tmp_path):
    from scripts import visual_slack_delivery_e2e

    monkeypatch.setattr(
        visual_slack_delivery_e2e,
        "run_visual_package",
        lambda _args: _fake_visual_package_payload(tmp_path),
    )

    report = visual_slack_delivery_e2e.build_visual_slack_delivery_e2e_report(
        mode="live",
        upload=False,
        work_dir=tmp_path,
        target="D_TEST",
    )

    assert report["success"] is False
    assert "live_upload_not_enabled" in report["failures"]


def test_visual_slack_delivery_live_uploads_images_and_videos(monkeypatch, tmp_path):
    from agent.visual.tracking import record_visual_delivery_status
    from agent.visual.tracking import visual_delivery_context
    from scripts import visual_slack_delivery_e2e

    calls = {"images": [], "videos": []}

    class FakeSlackAdapter:
        async def send_multiple_images(self, chat_id, images, metadata=None):
            calls["images"].append((chat_id, images))
            for image_ref, _alt in images:
                context = visual_delivery_context(
                    metadata,
                    image_ref,
                    platform="slack",
                    destination_id=chat_id,
                )
                record_visual_delivery_status(context, "sent", message_id="live-image-msg")

        async def send_video(self, chat_id, video_path, metadata=None):
            calls["videos"].append((chat_id, video_path))
            context = visual_delivery_context(
                metadata,
                video_path,
                platform="slack",
                destination_id=chat_id,
            )
            record_visual_delivery_status(context, "sent", message_id="live-video-msg")
            return {"success": True}

    monkeypatch.setattr(
        visual_slack_delivery_e2e,
        "run_visual_package",
        lambda _args: _fake_visual_package_payload(tmp_path),
    )
    monkeypatch.setattr(
        visual_slack_delivery_e2e,
        "_make_live_slack_adapter",
        lambda: FakeSlackAdapter(),
    )

    report = visual_slack_delivery_e2e.build_visual_slack_delivery_e2e_report(
        mode="live",
        upload=True,
        work_dir=tmp_path,
        target="D_TEST",
    )

    assert report["success"] is True
    assert calls["images"]
    assert calls["videos"]
    assert report["delivery"]["sent_count"] == 2
    assert report["delivery"]["message_ids"] == ["live-image-msg", "live-video-msg"]
    assert report["delivery"]["uploaded_image_file_count"] == 1
    assert report["delivery"]["uploaded_video_file_count"] == 1
    assert report["delivery"]["uploaded_remote_video_url_count"] == 0
    assert report["delivery"]["missing_uploaded_artifact_ids"] == []
    assert report["delivery"]["unexpected_uploaded_artifact_ids"] == []


def test_visual_slack_delivery_live_records_adapter_returned_uploads(monkeypatch, tmp_path):
    from scripts import visual_slack_delivery_e2e

    calls = {"images": [], "videos": []}

    class FakeSlackAdapter:
        async def send_multiple_images(self, chat_id, images, metadata=None):
            calls["images"].append((chat_id, images, metadata))
            return {
                "success": True,
                "message_id": "live-image-msg",
            }

        async def send_video(self, chat_id, video_path, metadata=None):
            calls["videos"].append((chat_id, video_path, metadata))
            return {
                "success": True,
                "message_id": "live-video-msg",
            }

    monkeypatch.setattr(
        visual_slack_delivery_e2e,
        "run_visual_package",
        lambda _args: _fake_visual_package_payload(tmp_path),
    )
    monkeypatch.setattr(
        visual_slack_delivery_e2e,
        "_make_live_slack_adapter",
        lambda: FakeSlackAdapter(),
    )

    report = visual_slack_delivery_e2e.build_visual_slack_delivery_e2e_report(
        mode="live",
        upload=True,
        work_dir=tmp_path,
        target="D_TEST",
    )

    assert calls["images"]
    assert calls["videos"]
    assert report["success"] is True
    assert report["delivery"]["sent_count"] == 2
    assert report["delivery"]["message_ids"] == ["live-image-msg", "live-video-msg"]


def test_visual_slack_delivery_live_fails_without_native_video_upload_proof(monkeypatch, tmp_path):
    from agent.visual.tracking import record_visual_delivery_status
    from agent.visual.tracking import visual_delivery_context
    from scripts import visual_slack_delivery_e2e

    monkeypatch.setattr(
        visual_slack_delivery_e2e,
        "run_visual_package",
        lambda _args: _fake_visual_package_payload(tmp_path),
    )

    async def fake_upload(*, metadata, deliverables, destination_id, thread_id):
        image_artifact_ids = []
        for item in deliverables:
            context = visual_delivery_context(
                metadata,
                item["ref"],
                platform="slack",
                destination_id=destination_id,
                thread_id=thread_id,
            )
            record_visual_delivery_status(
                context,
                "sent",
                message_id=f"live-msg-{item['artifact_id']}",
            )
            if item["kind"] == "image":
                image_artifact_ids.append(item["artifact_id"])
        return {
            "upload_enabled": True,
            "uploaded_image_count": 1,
            "uploaded_video_count": 0,
            "uploaded_image_artifact_ids": image_artifact_ids,
            "uploaded_video_artifact_ids": [],
            "uploaded_image_refs": [item["ref"] for item in deliverables if item["kind"] == "image"],
            "uploaded_video_refs": [],
            "errors": [],
            "skipped_refs": [],
            "missing_context_refs": [],
            "recorded_count": 0,
        }

    monkeypatch.setattr(
        visual_slack_delivery_e2e,
        "_upload_live_slack_deliverables",
        fake_upload,
    )

    report = visual_slack_delivery_e2e.build_visual_slack_delivery_e2e_report(
        mode="live",
        upload=True,
        work_dir=tmp_path,
        target="D_TEST",
    )

    assert report["success"] is False
    assert "missing_native_uploads" in report["failures"]
    assert report["delivery"]["sent_count"] == 2
    assert report["delivery"]["uploaded_video_file_count"] == 0
    assert len(report["delivery"]["missing_uploaded_artifact_ids"]) == 1


def test_visual_slack_delivery_live_reports_upload_adapter_failures(monkeypatch, tmp_path):
    from scripts import visual_slack_delivery_e2e

    monkeypatch.setattr(
        visual_slack_delivery_e2e,
        "run_visual_package",
        lambda _args: _fake_visual_package_payload(tmp_path),
    )
    monkeypatch.setattr(
        visual_slack_delivery_e2e,
        "_make_live_slack_adapter",
        lambda: (_ for _ in ()).throw(RuntimeError("SLACK_BOT_TOKEN is not configured")),
    )

    report = visual_slack_delivery_e2e.build_visual_slack_delivery_e2e_report(
        mode="live",
        upload=True,
        work_dir=tmp_path,
        target="D_TEST",
    )

    assert report["success"] is False
    assert "live_upload_failed" in report["failures"]
    assert report["record_summary"]["errors"] == [
        "RuntimeError:SLACK_BOT_TOKEN is not configured"
    ]


def test_slack_delivery_evidence_flags_same_artifact_delivered_twice(monkeypatch, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path
    from scripts.visual_slack_delivery_e2e import inspect_slack_delivery_evidence

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ledger = VisualAttemptLedger(default_visual_ledger_path())
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="duplicate delivery",
        normalized_intent={"kind": "visual_package"},
        modality="package",
        operation="visual_package_generate",
        status="completed",
    )
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        kind="image",
        content_hash="sha256:duplicate",
    )
    for message_id in ("msg-1", "msg-2"):
        ledger.record_delivery(
            request_id=request_id,
            artifact_id=artifact_id,
            platform="slack",
            destination_id="D_TEST",
            message_id=message_id,
            delivery_status="sent",
        )

    evidence = inspect_slack_delivery_evidence(
        payload={"visual_request_id": request_id},
        deliverables=[{"artifact_id": artifact_id}],
        destination_id="D_TEST",
        thread_id=None,
    )

    assert evidence["duplicate_delivery_count"] == 1


def test_slack_delivery_evidence_flags_unexpected_artifact_delivery(monkeypatch, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path
    from scripts.visual_slack_delivery_e2e import inspect_slack_delivery_evidence

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ledger = VisualAttemptLedger(default_visual_ledger_path())
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="unexpected delivery",
        normalized_intent={"kind": "visual_package"},
        modality="package",
        operation="visual_package_generate",
        status="completed",
    )
    selected_id = ledger.record_artifact(
        request_id=request_id,
        kind="image",
        content_hash="sha256:selected",
    )
    unselected_id = ledger.record_artifact(
        request_id=request_id,
        kind="image",
        content_hash="sha256:unselected",
    )
    for artifact_id in (selected_id, unselected_id):
        ledger.record_delivery(
            request_id=request_id,
            artifact_id=artifact_id,
            platform="slack",
            destination_id="D_TEST",
            message_id=f"msg-{artifact_id}",
            delivery_status="sent",
        )

    evidence = inspect_slack_delivery_evidence(
        payload={"visual_request_id": request_id},
        deliverables=[{"artifact_id": selected_id}],
        destination_id="D_TEST",
        thread_id=None,
    )

    assert evidence["unexpected_delivery_artifact_ids"] == [unselected_id]


def test_visual_slack_delivery_fails_when_selected_video_is_remote_url(monkeypatch, tmp_path):
    from scripts import visual_slack_delivery_e2e

    payload = {
        "success": True,
        "visual_request_id": "vrq_remote_video",
        "images": [],
        "videos": ["https://vidgen.example/xai-video.mp4"],
        "delivery_metadata": {
            "visual_request_id": "vrq_remote_video",
            "selected_visual_artifact_ids": ["var_video"],
            "visual_artifacts": {
                "https://vidgen.example/xai-video.mp4": {
                    "request_id": "vrq_remote_video",
                    "artifact_id": "var_video",
                    "kind": "video",
                }
            },
        },
    }
    monkeypatch.setattr(visual_slack_delivery_e2e, "run_visual_package", lambda _args: payload)

    report = visual_slack_delivery_e2e.build_visual_slack_delivery_e2e_report(
        mode="fixture",
        work_dir=tmp_path,
        target="D_TEST",
    )

    assert report["success"] is False
    assert "video_ref_not_local_file" in report["failures"]


def test_visual_slack_delivery_cli_respects_env_upload_gate(monkeypatch, capsys):
    from scripts import visual_slack_delivery_e2e

    calls = []

    def fake_build_report(**kwargs):
        calls.append(kwargs)
        return {
            "success": True,
            "mode": kwargs["mode"],
            "failures": [],
            "target": {"platform": "slack", "destination_id": kwargs["target"], "thread_id": None},
            "visual": {},
            "delivery": {},
            "record_summary": {},
        }

    monkeypatch.setenv("HERMES_VISUAL_SLACK_LIVE_UPLOAD", "1")
    monkeypatch.setattr(
        visual_slack_delivery_e2e,
        "build_visual_slack_delivery_e2e_report",
        fake_build_report,
    )

    code = visual_slack_delivery_e2e.main(
        ["--mode", "live", "--target", "D_TEST", "--json", "--allow-failures"]
    )

    assert code == 0
    assert calls[0]["upload"] is None
    assert '"success": true' in capsys.readouterr().out


def test_make_live_slack_adapter_loads_runtime_env(monkeypatch):
    from types import SimpleNamespace

    from gateway import config as gateway_config
    from gateway.platforms import slack as slack_mod
    from scripts import visual_slack_delivery_e2e

    loaded = []

    class FakeSlackAdapter:
        def __init__(self, config):
            self.config = config
            self._app = None

    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.setattr(
        visual_slack_delivery_e2e,
        "_load_runtime_env",
        lambda: (loaded.append(True), monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")),
    )
    monkeypatch.setattr(
        gateway_config,
        "load_gateway_config",
        lambda: SimpleNamespace(platforms={}),
    )
    monkeypatch.setattr(slack_mod, "SlackAdapter", FakeSlackAdapter)
    monkeypatch.setattr(slack_mod, "AsyncWebClient", lambda token: {"token": token})

    adapter = visual_slack_delivery_e2e._make_live_slack_adapter()

    assert loaded == [True]
    assert adapter._app.client == {"token": "xoxb-test"}


def test_resolve_target_loads_runtime_env_home_channel(monkeypatch):
    from scripts import visual_slack_delivery_e2e

    loaded = []
    monkeypatch.delenv("HERMES_VISUAL_SLACK_E2E_TARGET", raising=False)
    monkeypatch.delenv("SLACK_HOME_CHANNEL", raising=False)
    monkeypatch.setattr(
        visual_slack_delivery_e2e,
        "_load_runtime_env",
        lambda: (loaded.append(True), monkeypatch.setenv("SLACK_HOME_CHANNEL", "D_TEST")),
    )

    target = visual_slack_delivery_e2e._resolve_target(mode="live", target=None)

    assert loaded == [True]
    assert target == "D_TEST"


def test_resolve_target_reads_top_level_config_home_channel(monkeypatch):
    from scripts import visual_slack_delivery_e2e

    monkeypatch.delenv("HERMES_VISUAL_SLACK_E2E_TARGET", raising=False)
    monkeypatch.delenv("SLACK_HOME_CHANNEL", raising=False)
    monkeypatch.setattr(visual_slack_delivery_e2e, "_load_runtime_env", lambda: None)
    monkeypatch.setattr(
        visual_slack_delivery_e2e,
        "_load_top_level_config_value",
        lambda key: "D_CONFIG" if key == "SLACK_HOME_CHANNEL" else None,
    )

    target = visual_slack_delivery_e2e._resolve_target(mode="live", target=None)

    assert target == "D_CONFIG"


def test_visual_e2e_automation_includes_slack_delivery_gate(monkeypatch, tmp_path):
    from scripts import visual_e2e_automation_report

    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_slack_delivery_e2e_report",
        lambda **_kwargs: {
            "success": False,
            "mode": "fixture",
            "failures": ["missing_delivery_records"],
            "delivery": {"deliverable_count": 2, "sent_count": 0},
        },
    )

    report = visual_e2e_automation_report.build_visual_e2e_automation_report(work_dir=tmp_path)

    assert report["success"] is False
    assert "slack_delivery_failed" in report["failures"]
    assert report["slack_delivery"]["failures"] == ["missing_delivery_records"]
