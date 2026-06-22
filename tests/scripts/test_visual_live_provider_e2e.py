import json
import os
import time


def test_visual_live_provider_e2e_leaves_candidate_budget_to_feedback_policy_by_default(monkeypatch, tmp_path):
    from scripts import visual_live_provider_e2e

    captured = {}

    def fake_package(args):
        captured.update(args)
        return {
            "success": True,
            "visual_request_id": "",
            "images": [str(tmp_path / "image.png")],
            "videos": [str(tmp_path / "video.mp4")],
            "generation_payloads": {
                "image": {"success": True, "provider": "xai", "model": "image"},
                "video": {"success": True, "provider": "xai", "model": "video"},
            },
        }

    monkeypatch.setattr(visual_live_provider_e2e, "run_visual_package", fake_package)

    visual_live_provider_e2e.build_visual_live_provider_e2e_report(
        mode="fixture",
        work_dir=tmp_path,
    )

    assert "candidate_budget" not in captured


def test_visual_live_provider_e2e_live_preserves_runtime_hermes_home(monkeypatch, tmp_path):
    from scripts import visual_live_provider_e2e

    runtime_home = tmp_path / "runtime-home"
    work_dir = tmp_path / "work"
    captured = {}
    monkeypatch.setenv("HERMES_HOME", str(runtime_home))
    monkeypatch.setattr(visual_live_provider_e2e, "image_requirements_available", lambda: True)
    monkeypatch.setattr(visual_live_provider_e2e, "video_requirements_available", lambda: True)

    def fake_package(_args):
        captured["hermes_home"] = os.environ.get("HERMES_HOME")
        return {
            "success": True,
            "visual_request_id": "",
            "images": [str(tmp_path / "image.png")],
            "videos": [str(tmp_path / "video.mp4")],
            "generation_payloads": {
                "image": {"success": True, "provider": "xai", "model": "image"},
                "video": {"success": True, "provider": "xai", "model": "video"},
            },
        }

    monkeypatch.setattr(visual_live_provider_e2e, "run_visual_package", fake_package)

    visual_live_provider_e2e.build_visual_live_provider_e2e_report(
        mode="live",
        work_dir=work_dir,
    )

    assert captured["hermes_home"] == str(runtime_home)


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


def test_visual_live_provider_default_suite_declares_core_portrait_quality_contract(monkeypatch, tmp_path):
    from scripts import visual_live_provider_e2e

    def fake_report(**_kwargs):
        return {
            "success": True,
            "failures": [],
            "payload": {"success": True},
            "evidence": {
                "quality_gate": {"success": True, "min_score": 0.82, "quality_issues": []},
                "image_count": 1,
                "video_count": 1,
                "recovery_summary": {
                    "provider_failure_count": 0,
                    "provider_failure_classes": {},
                    "provider_error_codes": {},
                    "retry_attempt_count": 0,
                    "negotiation_attempted": False,
                    "negotiation_success": False,
                    "content_moderation_recovered": False,
                    "recovered_failure_classes": [],
                },
            },
        }

    monkeypatch.setattr(
        visual_live_provider_e2e,
        "build_visual_live_provider_e2e_report",
        fake_report,
    )

    suite = visual_live_provider_e2e.build_visual_live_provider_e2e_suite_report(
        mode="fixture",
        work_dir=tmp_path,
    )

    assert suite["quality_contract_summary"] == {
        "contract_case_count": 1,
        "contract_case_ids": ["fashion_portrait_video"],
        "required_dimensions": [
            "subject_beauty",
            "face_naturalness",
            "glamour_impact",
            "fashion_material_quality",
            "pose_composition",
        ],
        "core_quality_dimensions": [
            "subject_beauty",
            "face_naturalness",
            "glamour_impact",
            "fashion_material_quality",
            "pose_composition",
        ],
        "core_quality_dimensions_missing": [],
        "core_quality_coverage_ready": True,
        "image_first_video_contract_case_ids": ["fashion_portrait_video"],
    }
    fashion_case = next(case for case in suite["cases"] if case["case_id"] == "fashion_portrait_video")
    assert fashion_case["quality_contract"]["quality_focus"] == [
        "adult_fashion_portrait",
        "natural_face",
        "legwear_material",
        "long_leg_composition",
        "tasteful_glamour",
        "image_first_video",
    ]
    assert "prompt" not in json.dumps(suite, ensure_ascii=False)


def test_visual_live_provider_fashion_probe_uses_provider_safe_prompt_wording():
    from scripts.visual_live_provider_e2e import DEFAULT_E2E_CASES

    fashion_case = next(case for case in DEFAULT_E2E_CASES if case["case_id"] == "fashion_portrait_video")
    prompt = fashion_case["prompt"].lower()

    assert "tights" not in prompt
    assert "glamour" not in prompt
    assert "semi-opaque legwear" in prompt
    assert "polished editorial" in prompt
    assert fashion_case["quality_contract"]["required_dimensions"] == [
        "subject_beauty",
        "face_naturalness",
        "glamour_impact",
        "fashion_material_quality",
        "pose_composition",
    ]


def test_visual_live_provider_e2e_suite_aggregates_recovery_summary(monkeypatch, tmp_path):
    from scripts import visual_live_provider_e2e

    reports = [
        {
            "success": True,
            "failures": [],
            "payload": {"success": True},
            "evidence": {
                "recovery_summary": {
                    "provider_failure_count": 1,
                    "provider_failure_classes": {"content_moderation": 1},
                    "provider_error_codes": {"api_error": 1},
                    "retry_attempt_count": 1,
                    "negotiation_attempted": True,
                    "negotiation_success": True,
                    "content_moderation_recovered": True,
                    "recovered_failure_classes": ["content_moderation"],
                }
            },
        },
        {
            "success": True,
            "failures": [],
            "payload": {"success": True},
            "evidence": {
                "recovery_summary": {
                    "provider_failure_count": 0,
                    "provider_failure_classes": {},
                    "provider_error_codes": {},
                    "retry_attempt_count": 0,
                    "negotiation_attempted": False,
                    "negotiation_success": False,
                    "content_moderation_recovered": False,
                    "recovered_failure_classes": [],
                }
            },
        },
    ]

    monkeypatch.setattr(
        visual_live_provider_e2e,
        "build_visual_live_provider_e2e_report",
        lambda **_kwargs: reports.pop(0),
    )

    suite = visual_live_provider_e2e.build_visual_live_provider_e2e_suite_report(
        mode="fixture",
        work_dir=tmp_path,
        cases=[
            {"case_id": "fashion_portrait_video"},
            {"case_id": "product_photo_video"},
        ],
    )

    assert suite["success"] is True
    assert suite["recovery_summary"] == {
        "provider_failure_count": 1,
        "provider_failure_classes": {"content_moderation": 1},
        "provider_error_codes": {"api_error": 1},
        "retry_attempt_count": 1,
        "negotiation_attempted_case_count": 1,
        "negotiation_success_case_count": 1,
        "content_moderation_recovered_case_count": 1,
        "recovered_failure_classes": ["content_moderation"],
    }


def test_visual_live_provider_e2e_fixture_suite_exercises_video_quality_repair(tmp_path):
    from scripts.visual_live_provider_e2e import build_visual_live_provider_e2e_suite_report

    suite = build_visual_live_provider_e2e_suite_report(
        mode="fixture",
        work_dir=tmp_path,
        cases=[
            {
                "case_id": "video_quality_repair",
                "prompt": "Create one image and one short video: clean product photography.",
                "candidate_budget": 1,
                "video_budget": 1,
                "duration": 4,
                "force_video_quality_repair": True,
            }
        ],
    )

    assert suite["success"] is True
    assert suite["quality_repair_summary"]["attempt_count"] == 1
    assert suite["quality_repair_summary"]["success_count"] == 1
    assert suite["quality_repair_summary"]["selected_repair_count"] == 1
    assert suite["quality_repair_summary"]["by_modality"]["video"]["attempt_count"] == 1
    case = suite["cases"][0]
    assert case["evidence"]["quality_repair_summary"]["success_count"] == 1
    assert case["payload"]["video_count"] == 1


def test_visual_live_provider_e2e_suite_times_out_one_case_and_continues(monkeypatch, tmp_path):
    from scripts import visual_live_provider_e2e

    calls = []

    def fake_report(**kwargs):
        calls.append(kwargs["prompt"])
        if kwargs["prompt"] == "slow prompt":
            time.sleep(1)
        return {
            "success": True,
            "failures": [],
            "payload": {"success": True},
            "evidence": {
                "recovery_summary": {
                    "provider_failure_count": 0,
                    "provider_failure_classes": {},
                    "provider_error_codes": {},
                    "retry_attempt_count": 0,
                    "negotiation_attempted": False,
                    "negotiation_success": False,
                    "content_moderation_recovered": False,
                    "recovered_failure_classes": [],
                }
            },
        }

    monkeypatch.setattr(
        visual_live_provider_e2e,
        "build_visual_live_provider_e2e_report",
        fake_report,
    )

    suite = visual_live_provider_e2e.build_visual_live_provider_e2e_suite_report(
        mode="fixture",
        work_dir=tmp_path,
        case_timeout_seconds=0.01,
        cases=[
            {"case_id": "slow_case", "prompt": "slow prompt"},
            {"case_id": "fast_case", "prompt": "fast prompt"},
        ],
    )

    assert calls == ["slow prompt", "fast prompt"]
    assert suite["success"] is False
    assert suite["failures"] == ["slow_case:case_timeout"]
    assert suite["case_count"] == 2
    assert suite["cases"][0]["success"] is False
    assert suite["cases"][0]["failures"] == ["case_timeout"]
    assert suite["cases"][0]["evidence"]["case_timeout_seconds"] == 0.01
    assert suite["cases"][0]["recovery_summary"]["provider_failure_classes"] == {
        "case_timeout": 1,
    }
    assert suite["cases"][1]["success"] is True
    assert suite["recovery_summary"]["provider_failure_classes"] == {"case_timeout": 1}


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


def test_visual_live_provider_e2e_counts_provider_error_schema_columns():
    from scripts.visual_live_provider_e2e import _provider_failure_counters

    classes, codes = _provider_failure_counters(
        [
            {
                "provider_error_type": "api_error",
                "provider_error_message": (
                    'xAI image generation failed (400): {"code":"Client specified an invalid argument",'
                    '"error":"Generated image rejected by content moderation."}'
                ),
            }
        ]
    )

    assert classes["content_moderation"] == 1
    assert codes["api_error"] == 1


def test_visual_live_provider_e2e_ignores_internal_missing_video_source_error():
    from scripts.visual_live_provider_e2e import _provider_failure_counters

    classes, codes = _provider_failure_counters(
        [
            {
                "provider": "xai-oauth",
                "provider_error_type": "connection_error",
                "provider_error_message": "Failed to resolve api.x.ai",
            },
            {
                "provider": "",
                "provider_error_type": "missing_video_source_image",
                "provider_error_message": "Image-first video generation requires a selected source image.",
            },
        ]
    )

    assert classes == {"provider_unavailable": 1}
    assert codes == {"connection_error": 1}


def test_visual_live_provider_quality_gate_exports_preference_dimension_failures():
    from scripts.visual_live_provider_e2e import _quality_gate

    gate = _quality_gate(
        payload={
            "delivery_metadata": {
                "selected_visual_artifact_ids": ["var_bad"],
            }
        },
        artifacts=[{"artifact_id": "var_bad"}],
        judgments=[
            {
                "judge_name": "visual_quality_judge",
                "artifact_id": "var_bad",
                "score": 0.42,
                "details": {
                    "quality_issues": ["face_unnatural", "stockings_bad"],
                    "preference_dimensions": {
                        "face_naturalness": 0.28,
                        "fashion_material_quality": 0.31,
                        "pose_composition": 0.76,
                    },
                },
            }
        ],
        threshold=0.55,
    )

    assert gate["success"] is False
    assert gate["preference_dimension_failures"] == [
        {
            "artifact_id": "var_bad",
            "dimension": "face_naturalness",
            "score": 0.28,
            "issue": "face_unnatural",
        },
        {
            "artifact_id": "var_bad",
            "dimension": "fashion_material_quality",
            "score": 0.31,
            "issue": "stockings_bad",
        },
    ]
    assert gate["preference_dimension_failures_by_artifact"] == {
        "var_bad": gate["preference_dimension_failures"]
    }


def test_visual_live_provider_e2e_reports_moderation_recovery_summary(monkeypatch, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path
    from scripts.visual_live_provider_e2e import inspect_visual_e2e_evidence

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ledger = VisualAttemptLedger(default_visual_ledger_path())
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="fashion portrait",
        normalized_intent={"kind": "visual_package"},
        modality="package",
        operation="visual_package_generate",
        status="started",
    )
    ledger.record_attempt(
        request_id=request_id,
        candidate_index=0,
        provider="xai-oauth",
        model="grok-imagine-image-quality",
        prompt_original="fashion portrait",
        prompt_mediated="fashion portrait",
        parameters_requested={},
        parameters_effective={},
        status="failed",
        error_type="api_error",
        error_message='xAI image generation failed (400): {"error":"Generated image rejected by content moderation."}',
    )
    recovered_attempt_id = ledger.record_attempt(
        request_id=request_id,
        candidate_index=1,
        provider="xai",
        model="grok-imagine-image-quality",
        prompt_original="policy compliant fashion portrait",
        prompt_mediated="policy compliant fashion portrait",
        parameters_requested={},
        parameters_effective={},
        status="completed",
    )
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=recovered_attempt_id,
        kind="image",
        local_path=str(tmp_path / "image.jpg"),
        uri=str(tmp_path / "image.jpg"),
        content_hash="sha256:recovered-image",
        mime_type="image/jpeg",
        is_stable=True,
        freshness_status="fresh",
    )
    ledger.record_judgment(
        request_id=request_id,
        attempt_id=recovered_attempt_id,
        artifact_id=artifact_id,
        judge_name="visual_quality_judge",
        score=0.82,
        verdict="pass",
        details={
            "version": "visual_quality_judge.v0.1",
            "confidence": 0.82,
            "quality_issues": [],
            "scores": {"aesthetic_fit": 0.82, "composition": 0.9},
        },
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
        scores={"reward": {"confidence": 0.82}},
        metadata={"active_learning": {"action": "auto_post"}},
    )

    evidence = inspect_visual_e2e_evidence(
        {
            "success": True,
            "visual_request_id": request_id,
            "images": [str(tmp_path / "image.jpg")],
            "videos": [],
            "generation_payloads": {
                "image": [
                    {"success": False, "error_type": "api_error"},
                    {"success": True, "retry_of": 0},
                ],
            },
            "delivery_metadata": {
                "selected_visual_artifact_ids": [artifact_id],
            },
        },
        require_video=False,
    )

    assert evidence["recovery_summary"] == {
        "provider_failure_count": 1,
        "provider_failure_classes": {"content_moderation": 1},
        "provider_error_codes": {"api_error": 1},
        "retry_attempt_count": 1,
        "negotiation_attempted": True,
        "negotiation_success": True,
        "content_moderation_recovered": True,
        "recovered_failure_classes": ["content_moderation"],
    }


def test_visual_live_provider_e2e_inspects_selected_artifact_quality_gate(monkeypatch, tmp_path):
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
        content_hash="sha256:selected-low-quality",
        mime_type="image/jpeg",
        is_stable=True,
        freshness_status="fresh",
    )
    ledger.record_judgment(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        judge_name="visual_quality_judge",
        score=0.42,
        verdict="review",
        details={
            "version": "visual_quality_judge.v0.1",
            "confidence": 0.42,
            "scores": {"aesthetic_fit": 0.35, "composition": 0.49},
        },
        metadata={
            "intent_signature": "visig_demo",
            "strategy_signature": "vstrat_demo",
            "modality": "image",
        },
    )

    evidence = inspect_visual_e2e_evidence(
        {
            "visual_request_id": request_id,
            "images": [str(tmp_path / "image.jpg")],
            "videos": [],
            "delivery_metadata": {
                "selected_visual_artifact_ids": [artifact_id],
            },
        },
        require_video=False,
    )

    assert evidence["quality_gate"]["success"] is False
    assert evidence["quality_gate"]["min_score"] == 0.42
    assert evidence["quality_gate"]["low_quality_artifacts"] == [artifact_id]


def test_visual_live_provider_e2e_quality_gate_reports_selected_quality_issues(monkeypatch, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path
    from scripts.visual_live_provider_e2e import inspect_visual_e2e_evidence

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ledger = VisualAttemptLedger(default_visual_ledger_path())
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="fashion portrait",
        normalized_intent={"kind": "visual_package", "category": "portrait"},
        modality="package",
        operation="visual_package_generate",
        status="started",
    )
    attempt_id = ledger.record_attempt(
        request_id=request_id,
        candidate_index=0,
        provider="xai",
        model="grok-imagine-image-quality",
        prompt_original="fashion portrait",
        prompt_mediated="fashion portrait",
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
        content_hash="sha256:selected-quality-issue",
        mime_type="image/jpeg",
        is_stable=True,
        freshness_status="fresh",
    )
    ledger.record_judgment(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        judge_name="visual_quality_judge",
        score=0.84,
        verdict="review",
        details={
            "version": "visual_quality_judge.v0.1",
            "confidence": 0.84,
            "quality_issues": ["subject_not_attractive", "stockings_bad"],
            "scores": {"aesthetic_fit": 0.84, "composition": 0.9},
        },
        metadata={
            "intent_signature": "visig_demo",
            "strategy_signature": "vstrat_demo",
            "modality": "image",
        },
    )

    evidence = inspect_visual_e2e_evidence(
        {
            "visual_request_id": request_id,
            "images": [str(tmp_path / "image.jpg")],
            "videos": [],
            "delivery_metadata": {
                "selected_visual_artifact_ids": [artifact_id],
            },
        },
        require_video=False,
    )

    assert evidence["quality_gate"]["quality_issue_artifacts"] == [artifact_id]
    assert evidence["quality_gate"]["quality_issues_by_artifact"] == {
        artifact_id: ["subject_not_attractive", "stockings_bad"],
    }
    assert evidence["quality_gate"]["quality_issues"] == [
        "stockings_bad",
        "subject_not_attractive",
    ]


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


def test_visual_live_provider_e2e_fails_when_selected_quality_issue_present():
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
            "inline_vision_judgment_count": 1,
            "quality_gate": {
                "success": True,
                "min_score": 0.84,
                "threshold": 0.55,
                "quality_issues": ["subject_not_attractive"],
                "quality_issue_artifacts": ["var_bad_face"],
            },
            "providers": ["xai"],
        },
        mode="live",
        require_video=False,
    )

    assert "selected_quality_issue_detected" in failures


def test_visual_live_provider_e2e_fails_when_video_skips_ranked_image_source():
    from scripts.visual_live_provider_e2e import _payload_failures

    failures = _payload_failures(
        {"success": True, "images": ["/tmp/image.png"], "videos": ["/tmp/video.mp4"]},
        {
            "image_count": 1,
            "video_count": 1,
            "judgment_count": 2,
            "ranking_count": 2,
            "learning_trace_count": 2,
            "judgments_with_learning_metadata": 2,
            "inline_vision_judgment_count": 1,
            "quality_gate": {
                "success": True,
                "min_score": 0.82,
                "threshold": 0.55,
                "quality_issues": [],
            },
            "video_source": {
                "source_image_artifact_id": None,
                "ranked_selected_image_artifact_id": "var_selected_image",
                "uses_ranked_selected_image": False,
            },
            "providers": ["xai"],
        },
        mode="live",
        require_video=True,
    )

    assert "video_not_using_ranked_image_source" in failures


def test_visual_live_provider_e2e_extracts_video_source_evidence_from_payload():
    from scripts.visual_live_provider_e2e import _video_source_evidence

    evidence = _video_source_evidence(
        {
            "generation_strategy": {
                "image_first_for_video": True,
                "video_source_artifact_id": "var_selected_image",
            },
            "rankings": {
                "image": {"selected_artifact_id": "var_selected_image"},
                "video": {"selected_artifact_id": "var_selected_video"},
            },
        },
        require_video=True,
    )

    assert evidence == {
        "require_video": True,
        "image_first_for_video": True,
        "source_image_artifact_id": "var_selected_image",
        "ranked_selected_image_artifact_id": "var_selected_image",
        "uses_ranked_selected_image": True,
    }


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


def test_visual_live_provider_e2e_fails_when_quality_score_below_threshold():
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
            "inline_vision_judgment_count": 1,
            "quality_gate": {
                "success": False,
                "min_score": 0.41,
                "threshold": 0.55,
                "low_quality_artifacts": ["var_low"],
            },
            "providers": ["xai"],
        },
        mode="live",
        require_video=False,
    )

    assert "quality_gate_failed" in failures


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
