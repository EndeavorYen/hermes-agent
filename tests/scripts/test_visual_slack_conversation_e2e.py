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
            "video_source": {
                "uses_ranked_selected_image": kwargs.get("require_video") is True
                and kwargs.get("include_image") is False,
            },
            "recovery_summary": {
                "provider_failure_count": 0,
                "provider_failure_classes": {},
                "provider_error_codes": {},
            },
            "quality_gate": {
                "success": True,
                "quality_issues": [],
                "preference_dimension_failures": [],
            },
        },
        "delivery": {
            "deliverable_count": 2,
            "sent_count": 2,
            "duplicate_delivery_count": 0,
            "internal_source_image_delivered": False,
            "missing_delivery_artifact_ids": [],
            "unexpected_delivery_artifact_ids": [],
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
    assert report["conversation_route"]["contract"]["raw_image_video_tool_avoidance_present"] is True
    assert report["slack_delivery"]["delivery"]["sent_count"] == 2
    assert delivery_calls == [
        {
            "mode": "fixture",
            "work_dir": tmp_path,
            "prompt": prompt,
            "attachments": [],
            "target": "D_TEST",
            "thread_id": report["ingress"]["thread_id"],
            "candidate_budget": 1,
            "video_budget": 1,
            "duration": 4,
            "require_video": True,
            "include_image": True,
            "aspect_ratio": "16:9",
            "storyboard": None,
            "upload": None,
        }
    ]
    assert report["visual_agent_plan"]["arguments"]["include_image"] is True
    assert report["visual_agent_plan"]["arguments"]["include_video"] is True
    assert report["visual_agent_plan"]["arguments"]["aspect_ratio"] == "16:9"
    assert "SECRET_VISUAL_PROMPT" not in json.dumps(report, ensure_ascii=False)


def test_visual_slack_conversation_e2e_uses_visual_agent_plan_for_text_video(
    monkeypatch,
    tmp_path,
):
    from scripts import visual_slack_conversation_e2e

    prompt = "幫我做一段 4 秒乾淨產品短片，主體是一支霧黑鋼筆"
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
    assert delivery_calls[0]["candidate_budget"] == 2
    assert delivery_calls[0]["video_budget"] == 1
    assert delivery_calls[0]["duration"] == 4
    assert delivery_calls[0]["require_video"] is True
    assert delivery_calls[0]["include_image"] is False
    assert delivery_calls[0]["aspect_ratio"] == "16:9"
    assert delivery_calls[0]["storyboard"] is None
    assert report["self_review"]["decision"] == "accept"
    assert report["self_review"]["success"] is True
    assert report["self_review"]["requires_human_feedback"] is False
    assert report["self_review"]["reduces_human_intervention"] is True
    assert report["self_review"]["image_first_video_source_covered"] is True
    assert report["self_review"]["internal_source_image_delivered"] is False
    assert report["self_review"]["duplicate_delivery_count"] == 0
    assert report["self_review"]["quality_gate_success"] is True
    assert report["self_review"]["provider_failure_count"] == 0
    assert report["self_review"]["auto_next_action_count"] == 0


def test_visual_slack_conversation_e2e_self_review_flags_quality_repair_path(
    monkeypatch,
    tmp_path,
):
    from scripts import visual_slack_conversation_e2e

    def low_quality_delivery(**kwargs):
        return {
            "success": False,
            "mode": kwargs["mode"],
            "failures": ["quality_gate_failed", "selected_quality_issue_detected"],
            "target": {
                "platform": "slack",
                "destination_id": kwargs["target"],
                "thread_id": kwargs["thread_id"],
            },
            "visual": {
                "request_id": "vrq_low_quality",
                "image_count": 1,
                "video_count": 1,
                "video_source": {"uses_ranked_selected_image": True},
                "provider_failure_classes": {},
                "provider_error_codes": {},
                "recovery_summary": {
                    "provider_failure_count": 0,
                    "provider_failure_classes": {},
                    "provider_error_codes": {},
                },
                "quality_gate": {
                    "success": False,
                    "quality_issues": ["subject_not_attractive"],
                    "preference_dimension_failures": [
                        {
                            "artifact_id": "var_face",
                            "dimension": "face_naturalness",
                            "issue": "face_unnatural",
                            "score": 0.28,
                        }
                    ],
                },
            },
            "delivery": {
                "deliverable_count": 0,
                "sent_count": 0,
                "duplicate_delivery_count": 0,
                "internal_source_image_delivered": False,
            },
        }

    monkeypatch.setattr(
        visual_slack_conversation_e2e,
        "build_visual_slack_delivery_e2e_report",
        low_quality_delivery,
    )

    report = visual_slack_conversation_e2e.build_visual_slack_conversation_e2e_report(
        mode="fixture",
        work_dir=tmp_path,
        target="D_TEST",
        repair_budget=0,
    )

    assert report["success"] is False
    assert report["self_review"]["decision"] == "needs_repair"
    assert report["self_review"]["success"] is False
    assert report["self_review"]["quality_gate_success"] is False
    assert report["self_review"]["provider_failure_count"] == 0
    assert report["self_review"]["auto_next_action_count"] >= 3
    assert report["self_review"]["requires_human_feedback"] is False


def test_visual_slack_conversation_e2e_self_review_repairs_successful_low_quality_delivery(
    monkeypatch,
    tmp_path,
):
    from scripts import visual_slack_conversation_e2e

    def low_quality_sent_delivery(**kwargs):
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
                "request_id": "vrq_sent_low_quality",
                "image_count": 0,
                "video_count": 1,
                "video_source": {"uses_ranked_selected_image": True},
                "recovery_summary": {
                    "provider_failure_count": 0,
                    "provider_failure_classes": {},
                    "provider_error_codes": {},
                },
                "quality_gate": {
                    "success": False,
                    "quality_issues": ["video_metadata_missing"],
                    "preference_dimension_failures": [],
                },
            },
            "delivery": {
                "deliverable_count": 1,
                "sent_count": 1,
                "duplicate_delivery_count": 0,
                "internal_source_image_delivered": False,
                "missing_delivery_artifact_ids": [],
                "unexpected_delivery_artifact_ids": [],
            },
        }

    monkeypatch.setattr(
        visual_slack_conversation_e2e,
        "build_visual_slack_delivery_e2e_report",
        low_quality_sent_delivery,
    )

    report = visual_slack_conversation_e2e.build_visual_slack_conversation_e2e_report(
        mode="fixture",
        work_dir=tmp_path,
        prompt="幫我做一段 4 秒乾淨產品短片，主體是一支霧黑鋼筆",
        target="D_TEST",
    )

    assert report["success"] is True
    assert report["self_review"]["decision"] == "needs_repair"
    assert report["self_review"]["success"] is False
    assert report["self_review"]["requires_human_feedback"] is False
    assert report["self_review"]["auto_next_action_count"] >= 2
    assert "increase_candidate_budget" in [action["type"] for action in report["next_actions"]]
    assert "rerank_before_slack" in [action["type"] for action in report["next_actions"]]


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
            "failures": ["missing_deliverables", "quality_gate_failed", "visual_generation_failed"],
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


def test_visual_slack_conversation_e2e_retries_provider_failure_with_repair_policy(
    monkeypatch,
    tmp_path,
):
    from scripts import visual_slack_conversation_e2e

    delivery_calls = []

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

    def fake_delivery(**kwargs):
        delivery_calls.append(kwargs)
        latest_path = tmp_path / "visual" / "self_validation" / "latest.json"
        if len(delivery_calls) == 1:
            assert not latest_path.exists()
            return failed_delivery(**kwargs)

        assert latest_path.exists()
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        assert latest["success"] is True
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
        } in latest["automation"]["self_improvement"]["next_actions"]
        return _fake_delivery_report(**kwargs)

    monkeypatch.setattr(
        visual_slack_conversation_e2e,
        "build_visual_slack_delivery_e2e_report",
        fake_delivery,
    )

    report = visual_slack_conversation_e2e.build_visual_slack_conversation_e2e_report(
        mode="fixture",
        work_dir=tmp_path,
        target="D_TEST",
        repair_budget=1,
    )

    assert report["success"] is True
    assert "slack_delivery_failed" not in report["failures"]
    assert len(delivery_calls) == 2
    assert report["initial_slack_delivery"]["success"] is False
    assert report["slack_delivery"]["success"] is True
    assert report["repair_attempt"]["attempted"] is True
    assert report["repair_attempt"]["success"] is True
    assert report["repair_attempt"]["action_type"] == "safe_reframe_provider_retry"
    assert report["repair_attempt"]["policy_written"] is True
    assert report["next_actions"]


def test_visual_slack_conversation_e2e_routes_quota_to_provider_account_action(
    monkeypatch,
    tmp_path,
):
    from scripts import visual_slack_conversation_e2e

    def quota_blocked_delivery(**kwargs):
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
                "request_id": "vrq_quota_blocked",
                "image_count": 0,
                "video_count": 0,
                "provider_failure_classes": {"quota_exceeded": 1},
                "provider_error_codes": {"personal-team-blocked:spending-limit": 1},
                "recovery_summary": {
                    "provider_failure_count": 1,
                    "provider_failure_classes": {"quota_exceeded": 1},
                    "provider_error_codes": {"personal-team-blocked:spending-limit": 1},
                    "retry_attempt_count": 0,
                    "negotiation_attempted": False,
                    "negotiation_success": False,
                },
                "quality_gate": {
                    "success": False,
                    "score_count": 0,
                    "min_score": None,
                    "quality_issues": [],
                    "preference_dimension_failures": [],
                },
            },
            "delivery": {"deliverable_count": 0, "sent_count": 0},
        }

    monkeypatch.setattr(
        visual_slack_conversation_e2e,
        "build_visual_slack_delivery_e2e_report",
        quota_blocked_delivery,
    )

    report = visual_slack_conversation_e2e.build_visual_slack_conversation_e2e_report(
        mode="fixture",
        work_dir=tmp_path,
        target="D_TEST",
        repair_budget=1,
    )

    action_types = [action["type"] for action in report["next_actions"]]
    assert report["success"] is False
    assert report["repair_attempt"]["attempted"] is False
    assert action_types == ["resolve_provider_quota_or_switch_provider"]
    assert {
        "type": "resolve_provider_quota_or_switch_provider",
        "track": "provider",
        "reason": "slack_conversation_provider_quota_exceeded",
        "confidence": 0.95,
        "evidence_count": 1,
        "requires_human_feedback": False,
        "activation_status": "next_run",
        "source": "slack_conversation_e2e",
        "provider_failure_classes": {"quota_exceeded": 1},
        "provider_error_codes": {"personal-team-blocked:spending-limit": 1},
    } in report["next_actions"]


def test_visual_slack_conversation_e2e_retries_quality_failure_with_dimension_policy(
    monkeypatch,
    tmp_path,
):
    from scripts import visual_slack_conversation_e2e

    delivery_calls = []

    def low_quality_delivery(**kwargs):
        return {
            "success": False,
            "mode": kwargs["mode"],
            "failures": ["quality_gate_failed", "selected_quality_issue_detected"],
            "target": {
                "platform": "slack",
                "destination_id": kwargs["target"],
                "thread_id": kwargs["thread_id"],
            },
            "visual": {
                "request_id": "vrq_low_quality",
                "image_count": 1,
                "video_count": 1,
                "quality_gate": {
                    "success": False,
                    "quality_issues": ["subject_not_attractive", "stockings_bad"],
                    "preference_dimension_failures": [
                        {
                            "artifact_id": "var_face",
                            "dimension": "face_naturalness",
                            "issue": "face_unnatural",
                            "score": 0.28,
                        },
                        {
                            "artifact_id": "var_stockings",
                            "dimension": "fashion_material_quality",
                            "issue": "stockings_bad",
                            "score": 0.31,
                        },
                    ],
                },
            },
            "delivery": {"deliverable_count": 0, "sent_count": 0},
        }

    def fake_delivery(**kwargs):
        delivery_calls.append(kwargs)
        latest_path = tmp_path / "visual" / "self_validation" / "latest.json"
        if len(delivery_calls) == 1:
            assert not latest_path.exists()
            return low_quality_delivery(**kwargs)

        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        actions = latest["automation"]["self_improvement"]["next_actions"]
        assert {
            "type": "repair_low_preference_dimension",
            "track": "aesthetic",
            "reason": "slack_conversation_preference_dimension_low",
            "confidence": 0.72,
            "evidence_count": 1,
            "requires_human_feedback": False,
            "activation_status": "next_run",
            "source": "slack_conversation_e2e",
            "dimension": "face_naturalness",
            "quality_issue": "face_unnatural",
            "repair_hint": "improve_face_naturalness",
        } in actions
        assert {
            "type": "repair_low_preference_dimension",
            "track": "aesthetic",
            "reason": "slack_conversation_preference_dimension_low",
            "confidence": 0.72,
            "evidence_count": 1,
            "requires_human_feedback": False,
            "activation_status": "next_run",
            "source": "slack_conversation_e2e",
            "dimension": "fashion_material_quality",
            "quality_issue": "stockings_bad",
            "repair_hint": "improve_fashion_material_quality",
        } in actions
        return _fake_delivery_report(**kwargs)

    monkeypatch.setattr(
        visual_slack_conversation_e2e,
        "build_visual_slack_delivery_e2e_report",
        fake_delivery,
    )

    report = visual_slack_conversation_e2e.build_visual_slack_conversation_e2e_report(
        mode="fixture",
        work_dir=tmp_path,
        target="D_TEST",
        repair_budget=1,
    )

    assert report["success"] is True
    assert len(delivery_calls) == 2
    assert report["initial_slack_delivery"]["success"] is False
    assert report["slack_delivery"]["success"] is True
    assert report["repair_attempt"]["attempted"] is True
    assert report["repair_attempt"]["success"] is True
    assert "repair_low_preference_dimension" in report["repair_attempt"]["action_types"]
    assert "increase_candidate_budget" in [action["type"] for action in report["next_actions"]]
    assert "rerank_before_slack" in [action["type"] for action in report["next_actions"]]


def test_visual_slack_conversation_e2e_live_repair_policy_uses_runtime_home(
    monkeypatch,
    tmp_path,
):
    from scripts import visual_slack_conversation_e2e

    runtime_home = tmp_path / "runtime-home"
    work_dir = tmp_path / "work"
    delivery_calls = []
    monkeypatch.setenv("HERMES_HOME", str(runtime_home))

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
                "provider_failure_classes": {"content_moderation": 1},
                "provider_error_codes": {"api_error": 1},
                "recovery_summary": {
                    "provider_failure_count": 1,
                    "provider_failure_classes": {"content_moderation": 1},
                    "provider_error_codes": {"api_error": 1},
                    "retry_attempt_count": 1,
                },
            },
            "delivery": {"deliverable_count": 0, "sent_count": 0},
        }

    def fake_delivery(**kwargs):
        delivery_calls.append(kwargs)
        runtime_latest = runtime_home / "visual" / "self_validation" / "latest.json"
        work_latest = work_dir / "visual" / "self_validation" / "latest.json"
        if len(delivery_calls) == 1:
            assert not runtime_latest.exists()
            assert not work_latest.exists()
            return failed_delivery(**kwargs)

        assert runtime_latest.exists()
        assert not work_latest.exists()
        return _fake_delivery_report(**kwargs)

    monkeypatch.setattr(
        visual_slack_conversation_e2e,
        "build_visual_slack_delivery_e2e_report",
        fake_delivery,
    )

    report = visual_slack_conversation_e2e.build_visual_slack_conversation_e2e_report(
        mode="live",
        work_dir=work_dir,
        target="D_TEST",
        upload=False,
        repair_budget=1,
    )

    assert report["success"] is True
    assert len(delivery_calls) == 2
    assert report["repair_attempt"]["policy_written"] is True


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


def test_visual_slack_conversation_e2e_live_records_quality_trend_run(
    monkeypatch,
    tmp_path,
):
    from agent.visual.live_quality_trends import build_live_quality_trend_report_from_dir
    from scripts import visual_slack_conversation_e2e

    runtime_home = tmp_path / "runtime-home"
    monkeypatch.setenv("HERMES_HOME", str(runtime_home))
    monkeypatch.setattr(
        visual_slack_conversation_e2e,
        "_resolve_target",
        lambda *, mode, target: "D_LIVE" if mode == "live" and target is None else target,
    )
    monkeypatch.setattr(
        visual_slack_conversation_e2e,
        "build_visual_slack_delivery_e2e_report",
        _fake_delivery_report,
    )

    report = visual_slack_conversation_e2e.build_visual_slack_conversation_e2e_report(
        mode="live",
        work_dir=tmp_path / "work",
        prompt="幫我做一段 4 秒乾淨產品短片，主體是一支霧黑鋼筆",
        target=None,
        upload=True,
        record_quality_run=True,
    )

    quality_runs_dir = runtime_home / "visual" / "live_quality_burn"
    run_paths = sorted((quality_runs_dir / "runs").glob("*.json"))
    assert report["success"] is True
    assert len(run_paths) == 1

    quality_run = json.loads(run_paths[0].read_text(encoding="utf-8"))
    assert quality_run["source"] == "slack_conversation_e2e"
    assert quality_run["success"] is True
    assert quality_run["summary"]["case_count"] == 1
    assert quality_run["summary"]["min_quality_score"] == 1.0
    assert quality_run["summary"]["provider_failure_count"] == 0
    assert quality_run["summary"]["video_missing_after_image_count"] == 0
    assert quality_run["summary"]["image_first_video_source_failure_count"] == 0
    assert quality_run["summary"]["preference_dimension_failure_count"] == 0
    assert quality_run["privacy"]["raw_prompt_omitted"] is True
    assert "霧黑鋼筆" not in json.dumps(quality_run, ensure_ascii=False)
    assert report["quality_run_record"]["success"] is True
    assert report["quality_run_record"]["run_id"] == quality_run["run_id"]

    trend = build_live_quality_trend_report_from_dir(quality_runs_dir)
    assert trend["run_count"] == 1
    assert trend["summary"]["recent_avg_min_quality_score"] == 1.0


def test_visual_slack_conversation_e2e_live_records_provider_fallback_summary(monkeypatch, tmp_path):
    from scripts import visual_slack_conversation_e2e

    runtime_home = tmp_path / "runtime-home"
    monkeypatch.setenv("HERMES_HOME", str(runtime_home))
    monkeypatch.setattr(
        visual_slack_conversation_e2e,
        "_resolve_target",
        lambda *, mode, target: "D_LIVE" if mode == "live" and target is None else target,
    )

    def fallback_delivery(**kwargs):
        report = _fake_delivery_report(**kwargs)
        report["success"] = False
        report["failures"] = ["visual_generation_failed"]
        report["visual"]["video_count"] = 0
        report["visual"]["recovery_summary"] = {
            "provider_failure_count": 2,
            "provider_failure_classes": {"quota_exceeded": 2},
            "provider_error_codes": {"personal-team-blocked:spending-limit": 2},
            "provider_fallback_attempt_count": 1,
            "provider_fallback_success_count": 1,
            "provider_fallback_recovered_classes": ["quota_exceeded"],
        }
        report["delivery"]["deliverable_count"] = 1
        report["delivery"]["sent_count"] = 1
        report["delivery"]["uploaded_video_file_count"] = 0
        return report

    monkeypatch.setattr(
        visual_slack_conversation_e2e,
        "build_visual_slack_delivery_e2e_report",
        fallback_delivery,
    )

    report = visual_slack_conversation_e2e.build_visual_slack_conversation_e2e_report(
        mode="live",
        work_dir=tmp_path / "work",
        prompt="make an image and video of a matte black pen",
        target=None,
        upload=True,
        record_quality_run=True,
    )

    quality_run_path = runtime_home / "visual" / "live_quality_burn" / "latest.json"
    quality_run = json.loads(quality_run_path.read_text(encoding="utf-8"))
    assert report["success"] is False
    assert quality_run["summary"]["provider_failure_count"] == 2
    assert quality_run["summary"]["provider_fallback_attempt_count"] == 1
    assert quality_run["summary"]["provider_fallback_success_count"] == 1
    assert quality_run["summary"]["provider_fallback_recovered_classes"] == ["quota_exceeded"]


def test_visual_slack_conversation_e2e_live_records_no_video_fallback_summary(monkeypatch, tmp_path):
    from scripts import visual_slack_conversation_e2e

    runtime_home = tmp_path / "runtime-home"
    monkeypatch.setenv("HERMES_HOME", str(runtime_home))
    monkeypatch.setattr(
        visual_slack_conversation_e2e,
        "_resolve_target",
        lambda *, mode, target: "D_LIVE" if mode == "live" and target is None else target,
    )

    def no_fallback_delivery(**kwargs):
        report = _fake_delivery_report(**kwargs)
        report["success"] = False
        report["failures"] = ["visual_generation_failed"]
        report["visual"]["video_count"] = 0
        report["visual"]["recovery_summary"] = {
            "provider_failure_count": 2,
            "provider_failure_classes": {"quota_exceeded": 2},
            "provider_error_codes": {"personal-team-blocked:spending-limit": 2},
            "no_video_fallback_available_count": 1,
            "provider_quarantine_count": 1,
            "provider_quarantine_classes": ["quota_exceeded"],
            "video_fallback_diagnostics": [
                {
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
                            "post_setup": "",
                        }
                    ],
                }
            ],
        }
        return report

    monkeypatch.setattr(
        visual_slack_conversation_e2e,
        "build_visual_slack_delivery_e2e_report",
        no_fallback_delivery,
    )

    report = visual_slack_conversation_e2e.build_visual_slack_conversation_e2e_report(
        mode="live",
        work_dir=tmp_path / "work",
        prompt="make an image and video of a matte black pen",
        target=None,
        upload=True,
        record_quality_run=True,
    )

    quality_run_path = runtime_home / "visual" / "live_quality_burn" / "latest.json"
    quality_run = json.loads(quality_run_path.read_text(encoding="utf-8"))
    assert report["success"] is False
    assert quality_run["summary"]["no_video_fallback_available_count"] == 1
    assert quality_run["summary"]["provider_quarantine_count"] == 1
    assert quality_run["summary"]["provider_quarantine_classes"] == ["quota_exceeded"]
    assert quality_run["summary"]["video_fallback_diagnostics"] == [
        {
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
                    "post_setup": "",
                }
            ],
        }
    ]
    assert {
        "type": "configure_video_fallback_provider",
        "track": "provider",
        "reason": "slack_conversation_no_video_fallback_available",
        "confidence": 0.9,
        "evidence_count": 1,
        "requires_human_feedback": False,
        "activation_status": "next_run",
        "source": "slack_conversation_e2e",
        "provider_failure_classes": {"quota_exceeded": 2},
        "provider_error_codes": {"personal-team-blocked:spending-limit": 2},
        "video_fallback_diagnostics": [
            {
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
                        "post_setup": "",
                    }
                ],
            }
        ],
    } in report["next_actions"]
    assert quality_run["next_actions"] == report["next_actions"]


def test_visual_slack_conversation_e2e_live_records_inline_vision_failure_summary(monkeypatch, tmp_path):
    from scripts import visual_slack_conversation_e2e

    runtime_home = tmp_path / "runtime-home"
    monkeypatch.setenv("HERMES_HOME", str(runtime_home))
    monkeypatch.setattr(
        visual_slack_conversation_e2e,
        "_resolve_target",
        lambda *, mode, target: "D_LIVE" if mode == "live" and target is None else target,
    )

    def vision_failure_delivery(**kwargs):
        report = _fake_delivery_report(**kwargs)
        report["visual"]["inline_vision_failure_count"] = 1
        report["visual"]["inline_vision_failure_classes"] = {"quota_exceeded": 1}
        return report

    monkeypatch.setattr(
        visual_slack_conversation_e2e,
        "build_visual_slack_delivery_e2e_report",
        vision_failure_delivery,
    )

    visual_slack_conversation_e2e.build_visual_slack_conversation_e2e_report(
        mode="live",
        work_dir=tmp_path / "work",
        prompt="make an image and video of a matte black pen",
        target=None,
        upload=True,
        record_quality_run=True,
    )

    quality_run_path = runtime_home / "visual" / "live_quality_burn" / "latest.json"
    quality_run = json.loads(quality_run_path.read_text(encoding="utf-8"))
    assert quality_run["summary"]["inline_vision_failure_count"] == 1
    assert quality_run["summary"]["inline_vision_failure_classes"] == {"quota_exceeded": 1}


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


def test_visual_slack_conversation_e2e_cli_text_includes_self_review(monkeypatch, capsys, tmp_path):
    from scripts import visual_slack_conversation_e2e

    monkeypatch.setattr(
        visual_slack_conversation_e2e,
        "build_visual_slack_delivery_e2e_report",
        _fake_delivery_report,
    )

    code = visual_slack_conversation_e2e.main(
        ["--work-dir", str(tmp_path), "--target", "D_TEST"]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert "visual slack conversation e2e passed" in out
    assert "self_review=accept" in out
