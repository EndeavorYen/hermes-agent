from __future__ import annotations

import os


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
    for artifact_id, attempt_id, modality in (
        (image_artifact_id, image_attempt_id, "image"),
        (video_artifact_id, video_attempt_id, "video"),
    ):
        ledger.record_judgment(
            request_id=request_id,
            attempt_id=attempt_id,
            artifact_id=artifact_id,
            judge_name="visual_quality_judge",
            score=0.91,
            verdict="pass",
            details={
                "overall_score": 0.91,
                "quality_issues": [],
                "preference_dimensions": {"composition": 0.9, "artifact_integrity": 0.92},
            },
            metadata={
                "intent_signature": "test-live-upload-fixture",
                "strategy_signature": "selected-artifact-quality-proof",
                "modality": modality,
            },
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
    assert report["visual"]["video_source"]["image_first_for_video"] is True
    assert report["visual"]["video_source"]["uses_ranked_selected_image"] is True

    ledger = VisualAttemptLedger(tmp_path / "visual" / "attempt_ledger.sqlite3")
    deliveries = ledger.list_deliveries(request_id=report["delivery"]["request_id"])
    assert {row["delivery_status"] for row in deliveries} == {"sent"}
    assert {row["destination_id"] for row in deliveries} == {"D_TEST"}


def test_visual_slack_delivery_video_only_blocks_internal_source_image_delivery(monkeypatch, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path
    from agent.visual.tracking import visual_delivery_metadata
    from scripts import visual_slack_delivery_e2e

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    source_path = tmp_path / "internal-source.png"
    video_path = tmp_path / "selected-video.mp4"
    source_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    video_path.write_bytes(b"\x00\x00\x00\x18ftypmp42")

    ledger = VisualAttemptLedger(default_visual_ledger_path())
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="video only",
        normalized_intent={"kind": "visual_package", "wants_image": False, "wants_video": True},
        modality="package",
        operation="visual_package_generate",
        status="completed",
    )
    source_artifact_id = ledger.record_artifact(
        request_id=request_id,
        kind="image",
        local_path=str(source_path),
        uri=str(source_path),
        content_hash="sha256:source",
        mime_type="image/png",
        is_stable=True,
        freshness_status="fresh",
    )
    video_artifact_id = ledger.record_artifact(
        request_id=request_id,
        kind="video",
        local_path=str(video_path),
        uri=str(video_path),
        content_hash="sha256:video",
        mime_type="video/mp4",
        is_stable=True,
        freshness_status="fresh",
    )
    payload = {
        "success": True,
        "visual_request_id": request_id,
        "images": [],
        "videos": [str(video_path)],
        "generation_strategy": {
            "requested_image": False,
            "generated_image": True,
            "image_first_for_video": True,
            "video_source_artifact_id": source_artifact_id,
        },
        "delivery_metadata": visual_delivery_metadata(
            request_id=request_id,
            attempt_id=None,
            artifact_ids=[source_artifact_id, video_artifact_id],
            artifact_paths=[str(source_path), str(video_path)],
            selected_artifact_ids=[source_artifact_id, video_artifact_id],
        ),
    }
    monkeypatch.setattr(visual_slack_delivery_e2e, "run_visual_package", lambda _args: payload)
    monkeypatch.setattr(
        visual_slack_delivery_e2e,
        "inspect_visual_e2e_evidence",
        lambda _payload, *, require_video: {
            "request_id": request_id,
            "image_count": 0,
            "video_count": 1,
            "artifact_count": 2,
            "judgment_count": 2,
            "ranking_count": 2,
            "video_source": {
                "image_first_for_video": True,
                "uses_ranked_selected_image": True,
            },
            "provider_failure_classes": {},
            "provider_error_codes": {},
            "retry_attempt_count": 0,
            "recovery_summary": {},
            "quality_repair_summary": {},
            "quality_gate": {},
            "storyboard_execution": {},
        },
    )

    report = visual_slack_delivery_e2e.build_visual_slack_delivery_e2e_report(
        mode="fixture",
        work_dir=tmp_path,
        target="D_TEST",
        prompt="請產生一段產品展示影片",
        require_video=True,
    )

    assert report["success"] is False
    assert "internal_source_image_delivered" in report["failures"]
    assert report["delivery"]["internal_source_image_delivered"] is True
    assert report["delivery"]["internal_source_image_artifact_ids"] == [source_artifact_id]


def test_visual_slack_delivery_allows_image_when_requested_video_has_no_fallback(
    monkeypatch,
    tmp_path,
):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path
    from agent.visual.tracking import visual_delivery_metadata
    from scripts import visual_slack_delivery_e2e

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image_path = tmp_path / "selected-image.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    ledger = VisualAttemptLedger(default_visual_ledger_path())
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="image and video with unavailable video fallback",
        normalized_intent={"kind": "visual_package", "wants_image": True, "wants_video": True},
        modality="package",
        operation="visual_package_generate",
        status="completed",
    )
    image_artifact_id = ledger.record_artifact(
        request_id=request_id,
        kind="image",
        local_path=str(image_path),
        uri=str(image_path),
        content_hash="sha256:partial-image",
        mime_type="image/png",
        is_stable=True,
        freshness_status="fresh",
    )
    fallback_diagnostic = {
        "failed_provider": "xai",
        "failed_provider_family": "xai",
        "registered_provider_names": ["fal", "xai"],
        "available_provider_names": [],
        "unavailable_provider_names": ["fal"],
        "fallback_provider_names": [],
        "setup_actions": [
            {
                "provider": "fal",
                "env_vars": ["FAL_KEY"],
                "configured_env_vars": [],
                "missing_env_vars": ["FAL_KEY"],
                "post_setup": "",
            }
        ],
    }
    payload = {
        "success": False,
        "package_status": "partial",
        "error_type": None,
        "visual_request_id": request_id,
        "images": [str(image_path)],
        "videos": [],
        "generation_strategy": {
            "requested_image": True,
            "generated_image": True,
            "image_first_for_video": True,
            "video_source_artifact_id": image_artifact_id,
        },
        "generation_payloads": {
            "video": {
                "success": False,
                "video": None,
                "error_type": "provider_quarantined",
                "provider_quarantine": {
                    "no_video_fallback_available": True,
                    "video_fallback_diagnostic": fallback_diagnostic,
                },
                "failure": {
                    "failure_class": "quota_exceeded",
                    "provider_message_code": "provider_quarantined",
                },
            }
        },
        "delivery_metadata": visual_delivery_metadata(
            request_id=request_id,
            attempt_id=None,
            artifact_ids=[image_artifact_id],
            artifact_paths=[str(image_path)],
            selected_artifact_ids=[image_artifact_id],
        ),
    }
    monkeypatch.setattr(visual_slack_delivery_e2e, "run_visual_package", lambda _args: payload)
    monkeypatch.setattr(
        visual_slack_delivery_e2e,
        "inspect_visual_e2e_evidence",
        lambda _payload, *, require_video: {
            "request_id": request_id,
            "image_count": 1,
            "video_count": 0,
            "artifact_count": 1,
            "judgment_count": 1,
            "ranking_count": 1,
            "video_source": {
                "image_first_for_video": True,
                "uses_ranked_selected_image": True,
                "single_video_source_image": True,
            },
            "provider_failure_classes": {"quota_exceeded": 1},
            "provider_error_codes": {"provider_quarantined": 1},
            "retry_attempt_count": 0,
            "recovery_summary": {
                "no_video_fallback_available_count": 1,
                "video_fallback_diagnostics": [fallback_diagnostic],
            },
            "quality_repair_summary": {},
            "quality_gate": {"success": True, "quality_issues": []},
            "storyboard_execution": {},
        },
    )

    report = visual_slack_delivery_e2e.build_visual_slack_delivery_e2e_report(
        mode="fixture",
        work_dir=tmp_path,
        target="D_TEST",
        prompt="請產生一張圖片和一段影片",
        require_video=True,
    )

    assert report["success"] is True
    assert report["failures"] == []
    assert report["delivery"]["deliverable_count"] == 1
    assert report["delivery"]["sent_count"] == 1
    assert report["delivery"]["partial_video_unavailable_delivery"] is True
    assert report["delivery"]["partial_video_unavailable_reason"] == "no_video_fallback_available"
    assert report["delivery"]["partial_video_operator_setup_actions"] == [
        {"provider": "fal", "missing_env_vars": ["FAL_KEY"], "post_setup": ""}
    ]


def test_visual_slack_delivery_allows_partial_video_flag_without_diagnostic(
    monkeypatch,
    tmp_path,
):
    from scripts.visual_slack_delivery_e2e import inspect_slack_delivery_evidence

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    evidence = inspect_slack_delivery_evidence(
        payload={
            "package_status": "partial",
            "visual_request_id": "vrq_missing_diagnostic",
            "images": [str(tmp_path / "selected-image.png")],
            "videos": [],
            "generation_strategy": {
                "requested_image": True,
            },
            "generation_payloads": {
                "video": {
                    "provider_quarantine": {
                        "no_video_fallback_available": True,
                    }
                }
            },
        },
        deliverables=[
            {
                "artifact_id": "var_selected_image",
                "kind": "image",
                "ref": str(tmp_path / "selected-image.png"),
            }
        ],
        destination_id="D_TEST",
        thread_id=None,
        record_summary={"recorded_count": 0},
    )

    assert evidence["partial_video_unavailable_delivery"] is True
    assert evidence["partial_video_unavailable_reason"] == "no_video_fallback_available"
    assert evidence["partial_video_operator_setup_actions"] == []


def test_visual_slack_delivery_fixture_records_composed_storyboard_video(tmp_path):
    from scripts.visual_slack_delivery_e2e import build_visual_slack_delivery_e2e_report

    report = build_visual_slack_delivery_e2e_report(
        mode="fixture",
        work_dir=tmp_path,
        target="D_TEST",
        prompt="請做一支 2 段分鏡的連貫產品影片：霧黑鋼筆放在白紙上，柔和窗光。",
        candidate_budget=2,
        video_budget=1,
        storyboard={
            "enabled": True,
            "shot_count": 2,
            "candidate_budget_per_shot": 2,
            "source_image_policy": "one_ranked_image_per_shot",
            "composition_target": "single_coherent_video",
            "delivery_policy": "deliver_composed_video_when_available_else_selected_clips",
        },
    )

    assert report["success"] is True
    assert report["visual"]["image_count"] == 0
    assert report["visual"]["video_count"] == 1
    assert report["visual"]["storyboard_execution"]["status"] == "composed"
    assert report["visual"]["storyboard_execution"]["delivers_composed_video"] is True
    assert report["visual"]["storyboard_execution"]["delivers_source_clips"] is False
    assert report["delivery"]["deliverable_count"] == 1
    assert report["delivery"]["sent_count"] == 1
    assert report["delivery"]["missing_delivery_artifact_ids"] == []
    assert report["delivery_manifest"]["failures"] == []


def test_visual_slack_delivery_surfaces_quality_gate_evidence(monkeypatch, tmp_path):
    from scripts import visual_slack_delivery_e2e

    quality_gate = {
        "success": False,
        "quality_issues": ["subject_not_attractive", "stockings_bad"],
        "preference_dimension_failures": [
            {"artifact_id": "var_face", "dimension": "face_naturalness", "issue": "face_unnatural", "score": 0.28},
            {
                "artifact_id": "var_stockings",
                "dimension": "fashion_material_quality",
                "issue": "stockings_bad",
                "score": 0.31,
            },
        ],
    }

    monkeypatch.setattr(
        visual_slack_delivery_e2e,
        "run_visual_package",
        lambda _args: _fake_visual_package_payload(tmp_path),
    )
    monkeypatch.setattr(
        visual_slack_delivery_e2e,
        "inspect_visual_e2e_evidence",
        lambda _payload, *, require_video: {
            "request_id": "vrq_low_quality",
            "image_count": 1,
            "video_count": 1,
            "artifact_count": 2,
            "judgment_count": 2,
            "ranking_count": 2,
            "video_source": {"image_first_for_video": True, "uses_ranked_selected_image": True},
            "provider_failure_classes": {},
            "provider_error_codes": {},
            "retry_attempt_count": 0,
            "recovery_summary": {},
            "quality_repair_summary": {},
            "quality_gate": quality_gate,
        },
    )

    report = visual_slack_delivery_e2e.build_visual_slack_delivery_e2e_report(
        mode="fixture",
        work_dir=tmp_path,
        target="D_TEST",
    )

    assert report["visual"]["quality_gate"] == quality_gate


def test_visual_slack_delivery_surfaces_inline_vision_failure_evidence(monkeypatch, tmp_path):
    from scripts import visual_slack_delivery_e2e

    monkeypatch.setattr(
        visual_slack_delivery_e2e,
        "run_visual_package",
        lambda _args: _fake_visual_package_payload(tmp_path),
    )
    monkeypatch.setattr(
        visual_slack_delivery_e2e,
        "inspect_visual_e2e_evidence",
        lambda _payload, *, require_video: {
            "request_id": "vrq_vision_failure",
            "image_count": 1,
            "video_count": 1,
            "artifact_count": 2,
            "judgment_count": 2,
            "ranking_count": 2,
            "video_source": {"image_first_for_video": True, "uses_ranked_selected_image": True},
            "provider_failure_classes": {},
            "provider_error_codes": {},
            "retry_attempt_count": 0,
            "inline_vision_failure_count": 1,
            "inline_vision_failure_classes": {"quota_exceeded": 1},
            "recovery_summary": {},
            "quality_repair_summary": {},
            "quality_gate": {},
        },
    )

    report = visual_slack_delivery_e2e.build_visual_slack_delivery_e2e_report(
        mode="fixture",
        work_dir=tmp_path,
        target="D_TEST",
    )

    assert report["visual"]["inline_vision_failure_count"] == 1
    assert report["visual"]["inline_vision_failure_classes"] == {"quota_exceeded": 1}


def test_visual_slack_delivery_fails_when_quality_gate_fails(monkeypatch, tmp_path):
    from scripts import visual_slack_delivery_e2e

    quality_gate = {
        "success": False,
        "quality_issues": ["subject_not_attractive", "stockings_bad"],
        "low_quality_artifacts": ["var_face"],
    }

    monkeypatch.setattr(
        visual_slack_delivery_e2e,
        "run_visual_package",
        lambda _args: _fake_visual_package_payload(tmp_path),
    )
    monkeypatch.setattr(
        visual_slack_delivery_e2e,
        "inspect_visual_e2e_evidence",
        lambda _payload, *, require_video: {
            "request_id": "vrq_low_quality",
            "image_count": 1,
            "video_count": 1,
            "artifact_count": 2,
            "judgment_count": 2,
            "ranking_count": 2,
            "video_source": {"image_first_for_video": True, "uses_ranked_selected_image": True},
            "provider_failure_classes": {},
            "provider_error_codes": {},
            "retry_attempt_count": 0,
            "recovery_summary": {},
            "quality_repair_summary": {},
            "quality_gate": quality_gate,
        },
    )

    report = visual_slack_delivery_e2e.build_visual_slack_delivery_e2e_report(
        mode="fixture",
        work_dir=tmp_path,
        target="D_TEST",
    )

    assert report["success"] is False
    assert "quality_gate_failed" in report["failures"]
    assert "selected_quality_issue_detected" in report["failures"]
    assert report["visual"]["quality_gate"] == quality_gate


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


def test_visual_slack_delivery_live_preserves_runtime_hermes_home(monkeypatch, tmp_path):
    from scripts import visual_slack_delivery_e2e

    runtime_home = tmp_path / "runtime-home"
    work_dir = tmp_path / "work"
    captured = {}
    monkeypatch.setenv("HERMES_HOME", str(runtime_home))

    def fake_package(_args):
        captured["hermes_home"] = os.environ.get("HERMES_HOME")
        return _fake_visual_package_payload(tmp_path)

    monkeypatch.setattr(visual_slack_delivery_e2e, "run_visual_package", fake_package)

    visual_slack_delivery_e2e.build_visual_slack_delivery_e2e_report(
        mode="live",
        upload=False,
        work_dir=work_dir,
        target="D_TEST",
    )

    assert captured["hermes_home"] == str(runtime_home)


def test_visual_slack_delivery_exports_provider_recovery_evidence(monkeypatch, tmp_path):
    from scripts import visual_slack_delivery_e2e

    monkeypatch.setattr(
        visual_slack_delivery_e2e,
        "run_visual_package",
        lambda _args: {
            "success": False,
            "visual_request_id": "vrq_provider_failure",
            "images": [],
            "videos": [],
        },
    )
    monkeypatch.setattr(
        visual_slack_delivery_e2e,
        "inspect_visual_e2e_evidence",
        lambda _payload, *, require_video: {
            "request_id": "vrq_provider_failure",
            "image_count": 0,
            "video_count": 0,
            "artifact_count": 0,
            "judgment_count": 0,
            "ranking_count": 0,
            "provider_failure_classes": {"content_moderation": 2},
            "provider_error_codes": {"api_error": 2},
            "retry_attempt_count": 1,
            "recovery_summary": {
                "provider_failure_count": 2,
                "provider_failure_classes": {"content_moderation": 2},
                "provider_error_codes": {"api_error": 2},
                "retry_attempt_count": 1,
                "negotiation_attempted": True,
                "negotiation_success": False,
            },
        },
    )

    report = visual_slack_delivery_e2e.build_visual_slack_delivery_e2e_report(
        mode="fixture",
        work_dir=tmp_path,
        target="D_TEST",
    )

    assert report["success"] is False
    assert report["visual"]["provider_failure_classes"] == {"content_moderation": 2}
    assert report["visual"]["provider_error_codes"] == {"api_error": 2}
    assert report["visual"]["retry_attempt_count"] == 1
    assert report["visual"]["recovery_summary"]["negotiation_attempted"] is True


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
