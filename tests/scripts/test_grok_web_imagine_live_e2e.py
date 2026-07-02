from __future__ import annotations

import json


def test_grok_web_imagine_preflight_disabled_without_opt_in_does_not_construct_provider(
    monkeypatch,
    tmp_path,
):
    from scripts import grok_web_imagine_live_e2e

    constructed = False

    def _provider_factory():
        nonlocal constructed
        constructed = True
        raise AssertionError("provider should not be constructed without opt-in")

    monkeypatch.delenv("HERMES_VISUAL_LIVE_E2E", raising=False)
    monkeypatch.delenv("HERMES_GROK_WEB_IMAGINE", raising=False)

    report = grok_web_imagine_live_e2e.build_grok_web_imagine_preflight_report(
        work_dir=tmp_path,
        provider_factory=_provider_factory,
    )

    assert constructed is False
    assert report["success"] is False
    assert report["status"] == "disabled"
    assert report["requires_operator_setup"] is True
    assert report["quota_used"] is False
    assert report["checks"]["opt_in"] is False
    assert report["checks"]["provider_constructed"] is False
    assert report["missing_opt_in"] == [
        "HERMES_VISUAL_LIVE_E2E=1",
        "HERMES_GROK_WEB_IMAGINE=1",
    ]


def test_grok_web_imagine_preflight_constructs_provider_without_generating(
    monkeypatch,
    tmp_path,
):
    from scripts import grok_web_imagine_live_e2e

    generated = False

    class FakeProvider:
        def generate(self, *_args, **_kwargs):
            nonlocal generated
            generated = True
            raise AssertionError("preflight must not generate media")

    monkeypatch.setenv("HERMES_VISUAL_LIVE_E2E", "1")
    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")

    report = grok_web_imagine_live_e2e.build_grok_web_imagine_preflight_report(
        work_dir=tmp_path,
        provider_factory=lambda: FakeProvider(),
    )

    assert generated is False
    assert report["success"] is False
    assert report["status"] == "provider_preflight_unavailable"
    assert report["requires_operator_setup"] is True
    assert report["quota_used"] is False
    assert report["checks"] == {
        "opt_in": True,
        "provider_constructed": True,
        "provider_preflight": False,
        "generation_called": False,
    }
    assert "preflight" in report["self_review"]["next_action"]


def test_grok_web_imagine_preflight_records_browser_readiness_without_generating(
    monkeypatch,
    tmp_path,
):
    from scripts import grok_web_imagine_live_e2e

    generated = False
    probed = False

    class FakeProvider:
        name = "grok-web-imagine"

        def preflight(self):
            nonlocal probed
            probed = True
            return {
                "status": "imagine_ready",
                "ready": True,
                "safe_to_submit": True,
                "message": "Grok web Imagine appears ready.",
                "url": "https://grok.com/imagine",
                "title": "Imagine - Grok",
                "quota_used": False,
            }

        def generate(self, *_args, **_kwargs):
            nonlocal generated
            generated = True
            raise AssertionError("preflight must not generate media")

    monkeypatch.setenv("HERMES_VISUAL_LIVE_E2E", "1")
    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")

    report = grok_web_imagine_live_e2e.build_grok_web_imagine_preflight_report(
        work_dir=tmp_path,
        provider_factory=lambda: FakeProvider(),
    )

    assert probed is True
    assert generated is False
    assert report["success"] is True
    assert report["status"] == "preflight_ready"
    assert report["checks"]["provider_preflight"] is True
    assert report["checks"]["generation_called"] is False
    assert report["browser_preflight"] == {
        "status": "imagine_ready",
        "ready": True,
        "safe_to_submit": True,
        "message": "Grok web Imagine appears ready.",
        "url": "https://grok.com/imagine",
        "title": "Imagine - Grok",
        "quota_used": False,
    }


def test_grok_web_imagine_preflight_preserves_prompt_probe_without_generating(
    monkeypatch,
    tmp_path,
):
    from scripts import grok_web_imagine_live_e2e

    generated = False

    class FakeProvider:
        name = "grok-web-imagine"

        def preflight(self, probe_prompt=None):
            assert probe_prompt
            return {
                "status": "imagine_ready",
                "ready": True,
                "safe_to_submit": True,
                "message": "Grok web Imagine appears ready.",
                "url": "https://grok.com/imagine",
                "title": "Imagine - Grok",
                "quota_used": False,
                "generation_called": False,
                "prompt_probe": {
                    "attempted": True,
                    "prompt_text_present": True,
                    "submit_enabled": True,
                    "reason": "",
                    "tag": "TEXTAREA",
                    "filled_text_preview": "Hermes Raphael preflight browser readiness probe.",
                },
            }

        def generate(self, *_args, **_kwargs):
            nonlocal generated
            generated = True
            raise AssertionError("preflight must not generate media")

    monkeypatch.setenv("HERMES_VISUAL_LIVE_E2E", "1")
    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")

    report = grok_web_imagine_live_e2e.build_grok_web_imagine_preflight_report(
        work_dir=tmp_path,
        provider_factory=lambda: FakeProvider(),
    )

    assert generated is False
    assert report["success"] is True
    assert report["status"] == "preflight_ready"
    assert report["checks"]["generation_called"] is False
    assert report["browser_preflight"]["prompt_probe"] == {
        "attempted": True,
        "prompt_text_present": True,
        "submit_enabled": True,
        "reason": "",
        "tag": "TEXTAREA",
        "filled_text_preview": "Hermes Raphael preflight browser readiness probe.",
    }


def test_grok_web_imagine_preflight_blocks_ready_but_not_safe_to_submit(
    monkeypatch,
    tmp_path,
):
    from scripts import grok_web_imagine_live_e2e

    generated = False

    class FakeProvider:
        name = "grok-web-imagine"

        def preflight(self):
            return {
                "status": "composer_disabled",
                "ready": True,
                "safe_to_submit": False,
                "message": "Composer visible but submit button is disabled.",
                "url": "https://grok.com/imagine",
                "title": "Imagine - Grok",
                "quota_used": False,
            }

        def generate(self, *_args, **_kwargs):
            nonlocal generated
            generated = True
            raise AssertionError("preflight must not generate media")

    monkeypatch.setenv("HERMES_VISUAL_LIVE_E2E", "1")
    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")

    report = grok_web_imagine_live_e2e.build_grok_web_imagine_preflight_report(
        work_dir=tmp_path,
        provider_factory=lambda: FakeProvider(),
    )

    assert generated is False
    assert report["success"] is False
    assert report["status"] == "browser_preflight_blocked"
    assert report["error_type"] == "composer_disabled"
    assert report["requires_operator_setup"] is True
    assert report["browser_preflight"]["ready"] is True
    assert report["browser_preflight"]["safe_to_submit"] is False
    assert report["checks"]["generation_called"] is False


def test_grok_web_imagine_preflight_reports_browser_readiness_blocker(
    monkeypatch,
    tmp_path,
):
    from scripts import grok_web_imagine_live_e2e

    generated = False

    class FakeProvider:
        def preflight(self):
            return {
                "status": "login_required",
                "ready": False,
                "safe_to_submit": False,
                "message": "Grok web requires manual login in the debug Chrome window.",
                "url": "https://accounts.x.ai/sign-in",
                "title": "Sign in",
                "quota_used": False,
            }

        def generate(self, *_args, **_kwargs):
            nonlocal generated
            generated = True
            raise AssertionError("preflight must not generate media")

    monkeypatch.setenv("HERMES_VISUAL_LIVE_E2E", "1")
    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")

    report = grok_web_imagine_live_e2e.build_grok_web_imagine_preflight_report(
        work_dir=tmp_path,
        provider_factory=lambda: FakeProvider(),
    )

    assert generated is False
    assert report["success"] is False
    assert report["status"] == "browser_preflight_blocked"
    assert report["error_type"] == "login_required"
    assert report["requires_operator_setup"] is True
    assert report["quota_used"] is False
    assert report["checks"]["provider_preflight"] is True
    assert report["checks"]["generation_called"] is False
    assert report["browser_preflight"]["status"] == "login_required"
    assert "manual login" in report["self_review"]["next_action"]


def test_grok_web_imagine_preflight_reports_provider_construction_error(
    monkeypatch,
    tmp_path,
):
    from scripts import grok_web_imagine_live_e2e

    def _provider_factory():
        raise RuntimeError("CDP dependency missing")

    monkeypatch.setenv("HERMES_VISUAL_LIVE_E2E", "1")
    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")

    report = grok_web_imagine_live_e2e.build_grok_web_imagine_preflight_report(
        work_dir=tmp_path,
        provider_factory=_provider_factory,
    )

    assert report["success"] is False
    assert report["status"] == "provider_unavailable"
    assert report["requires_operator_setup"] is True
    assert report["quota_used"] is False
    assert report["error_type"] == "RuntimeError"
    assert "CDP dependency missing" in report["error"]


def test_grok_web_imagine_live_e2e_cli_preflight_only_does_not_generate(
    monkeypatch,
    tmp_path,
    capsys,
):
    from scripts import grok_web_imagine_live_e2e

    class FakeProvider:
        def preflight(self):
            return {
                "status": "imagine_ready",
                "ready": True,
                "safe_to_submit": True,
                "message": "ready",
                "url": "https://grok.com/imagine",
                "title": "Imagine - Grok",
                "quota_used": False,
            }

        def generate(self, *_args, **_kwargs):
            raise AssertionError("preflight must not generate media")

    monkeypatch.setenv("HERMES_VISUAL_LIVE_E2E", "1")
    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")
    monkeypatch.setattr(grok_web_imagine_live_e2e, "_default_provider", lambda: FakeProvider())

    exit_code = grok_web_imagine_live_e2e.main(
        [
            "--preflight-only",
            "--work-dir",
            str(tmp_path),
        ]
    )

    report = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert report["status"] == "preflight_ready"
    assert report["quota_used"] is False
    assert report["checks"]["generation_called"] is False


def test_grok_web_imagine_live_e2e_disabled_without_opt_in(monkeypatch, tmp_path):
    from scripts import grok_web_imagine_live_e2e

    called = False

    class FakeProvider:
        def generate(self, *_args, **_kwargs):
            nonlocal called
            called = True
            return {"success": True}

    monkeypatch.delenv("HERMES_VISUAL_LIVE_E2E", raising=False)
    monkeypatch.delenv("HERMES_GROK_WEB_IMAGINE", raising=False)

    report = grok_web_imagine_live_e2e.build_grok_web_imagine_live_e2e_report(
        work_dir=tmp_path,
        provider_factory=lambda: FakeProvider(),
    )

    assert called is False
    assert report["success"] is False
    assert report["status"] == "disabled"
    assert report["requires_operator_setup"] is True
    assert report["missing_opt_in"] == [
        "HERMES_VISUAL_LIVE_E2E=1",
        "HERMES_GROK_WEB_IMAGINE=1",
    ]


def test_grok_web_imagine_live_e2e_runs_provider_when_opted_in(monkeypatch, tmp_path):
    from scripts import grok_web_imagine_live_e2e

    source = tmp_path / "selected-source.png"
    reference = tmp_path / "pose-reference.png"
    output = tmp_path / "grok-web-output.png"
    source.write_bytes(b"source")
    reference.write_bytes(b"reference")
    output.write_bytes(b"generated")
    calls = []

    class FakeProvider:
        def generate(self, *args, **kwargs):
            calls.append((args, kwargs))
            return {
                "success": True,
                "image": str(output),
                "provider": "grok-web-imagine",
                "model": "grok-web-imagine",
                "artifact_source": "browser_screenshot",
                "artifact_durability": "durable_history_or_post",
                "history_verified": True,
                "page_url": "https://grok.com/imagine/post/abc123",
                "quota_source": "consumer_web",
            }

    monkeypatch.setenv("HERMES_VISUAL_LIVE_E2E", "1")
    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")

    report = grok_web_imagine_live_e2e.build_grok_web_imagine_live_e2e_report(
        work_dir=tmp_path,
        prompt="polish the selected character image",
        aspect_ratio="portrait",
        image_url=str(source),
        reference_image_urls=[str(reference)],
        provider_factory=lambda: FakeProvider(),
    )

    assert report["success"] is True
    assert report["status"] == "completed"
    assert report["run_id"].startswith("grok-web-live-")
    assert report["generated_at"]
    assert calls == [
        (
            ("polish the selected character image",),
                {
                    "aspect_ratio": "portrait",
                    "image_url": str(source),
                    "reference_image_urls": [str(reference)],
                    "operation": "generate",
                    "timeout_seconds": 240,
                },
            )
    ]
    assert report["artifact"] == {
        "path": str(output),
        "exists": True,
        "source": "browser_screenshot",
        "durability": "durable_history_or_post",
        "history_verified": True,
        "page_url": "https://grok.com/imagine/post/abc123",
    }
    assert report["provider"] == {
        "name": "grok-web-imagine",
        "model": "grok-web-imagine",
        "quota_source": "consumer_web",
    }
    assert report["self_review"]["artifact_quality_verdict"] == "unreviewed"
    assert "quality" in report["self_review"]["next_action"]


def test_grok_web_imagine_live_e2e_rejects_unverified_ephemeral_browser_artifact(monkeypatch, tmp_path):
    from scripts import grok_web_imagine_live_e2e

    output = tmp_path / "grok-web-explore-output.jpg"
    output.write_bytes(b"generated")

    class FakeProvider:
        def generate(self, *_args, **_kwargs):
            return {
                "success": True,
                "image": str(output),
                "provider": "grok-web-imagine",
                "model": "grok-web-imagine",
                "artifact_source": "browser_data_url",
                "artifact_durability": "ephemeral_browser_page",
                "history_verified": False,
                "page_url": "https://grok.com/imagine",
                "page_title": "Transient browser result - Grok",
                "quota_source": "consumer_web",
            }

    monkeypatch.setenv("HERMES_VISUAL_LIVE_E2E", "1")
    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")

    report = grok_web_imagine_live_e2e.build_grok_web_imagine_live_e2e_report(
        work_dir=tmp_path,
        prompt="Tiny red cube on a white table, clean product photo, no text.",
        provider_factory=lambda: FakeProvider(),
    )

    assert report["success"] is False
    assert report["status"] == "ephemeral_artifact"
    assert report["artifact"] == {
        "path": str(output),
        "exists": True,
        "source": "browser_data_url",
        "durability": "ephemeral_browser_page",
        "history_verified": False,
        "page_url": "https://grok.com/imagine",
    }
    assert report["self_review"]["artifact_verified"] is True
    assert report["self_review"]["durable_history_verified"] is False
    assert "history" in report["self_review"]["next_action"]


def test_grok_web_imagine_live_e2e_rejects_durable_label_without_result_surface(
    monkeypatch,
    tmp_path,
):
    from scripts import grok_web_imagine_live_e2e

    output = tmp_path / "grok-web-labelled-output.jpg"
    output.write_bytes(b"generated")

    class FakeProvider:
        def generate(self, *_args, **_kwargs):
            return {
                "success": True,
                "image": str(output),
                "provider": "grok-web-imagine",
                "model": "grok-web-imagine",
                "artifact_source": "browser_screenshot",
                "artifact_durability": "durable_history_or_post",
                "history_verified": False,
                "quota_source": "consumer_web",
            }

    monkeypatch.setenv("HERMES_VISUAL_LIVE_E2E", "1")
    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")

    report = grok_web_imagine_live_e2e.build_grok_web_imagine_live_e2e_report(
        work_dir=tmp_path,
        prompt="Tiny red cube on a white table, clean product photo, no text.",
        provider_factory=lambda: FakeProvider(),
    )

    assert report["success"] is False
    assert report["status"] == "ephemeral_artifact"
    assert report["artifact"]["durability"] == "durable_history_or_post"
    assert report["artifact"]["history_verified"] is False
    assert report["self_review"]["durable_history_verified"] is False


def test_grok_web_imagine_live_e2e_forwards_edit_current_operation(monkeypatch, tmp_path):
    from scripts import grok_web_imagine_live_e2e

    output = tmp_path / "grok-web-edit.png"
    output.write_bytes(b"generated")
    calls = []

    class FakeProvider:
        def generate(self, *args, **kwargs):
            calls.append((args, kwargs))
            return {
                "success": True,
                "image": str(output),
                "provider": "grok-web-imagine",
                "model": "grok-web-imagine",
                "artifact_source": "browser_screenshot",
                "artifact_durability": "durable_history_or_post",
                "history_verified": True,
                "page_url": "https://grok.com/imagine/post/abc123",
                "quota_source": "consumer_web",
                "operation": "edit_current",
            }

    monkeypatch.setenv("HERMES_VISUAL_LIVE_E2E", "1")
    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")

    report = grok_web_imagine_live_e2e.build_grok_web_imagine_live_e2e_report(
        work_dir=tmp_path,
        prompt="make the current post warmer",
        aspect_ratio="square",
        operation="edit_current",
        provider_factory=lambda: FakeProvider(),
    )

    assert report["success"] is True
    assert calls == [
        (
            ("make the current post warmer",),
                {
                    "aspect_ratio": "square",
                    "image_url": None,
                    "reference_image_urls": None,
                    "timeout_seconds": 240,
                    "operation": "edit_current",
                },
        )
    ]
    assert report["request"]["operation"] == "edit_current"
    assert report["provider_result"]["operation"] == "edit_current"


def test_grok_web_imagine_live_e2e_forwards_continue_current_operation(monkeypatch, tmp_path):
    from scripts import grok_web_imagine_live_e2e

    output = tmp_path / "grok-web-continue.png"
    output.write_bytes(b"generated")
    calls = []

    class FakeProvider:
        def generate(self, *args, **kwargs):
            calls.append((args, kwargs))
            return {
                "success": True,
                "image": str(output),
                "provider": "grok-web-imagine",
                "model": "grok-web-imagine",
                "artifact_source": "browser_screenshot",
                "artifact_durability": "durable_history_or_post",
                "history_verified": True,
                "page_url": "https://grok.com/imagine/post/abc123",
                "quota_source": "consumer_web",
                "operation": "continue_current",
            }

    monkeypatch.setenv("HERMES_VISUAL_LIVE_E2E", "1")
    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")

    report = grok_web_imagine_live_e2e.build_grok_web_imagine_live_e2e_report(
        work_dir=tmp_path,
        prompt="try a different composition for the current image",
        aspect_ratio="portrait",
        operation="continue_current",
        provider_factory=lambda: FakeProvider(),
    )

    assert report["success"] is True
    assert calls == [
        (
            ("try a different composition for the current image",),
                {
                    "aspect_ratio": "portrait",
                    "image_url": None,
                    "reference_image_urls": None,
                    "timeout_seconds": 240,
                    "operation": "continue_current",
                },
        )
    ]
    assert report["request"]["operation"] == "continue_current"
    assert report["provider_result"]["operation"] == "continue_current"


def test_grok_web_imagine_live_e2e_rejects_weak_result_surface_token(
    monkeypatch,
    tmp_path,
):
    from scripts import grok_web_imagine_live_e2e

    output = tmp_path / "grok-web-current.png"
    output.write_bytes(b"generated")

    class FakeProvider:
        def generate(self, *_args, **_kwargs):
            return {
                "success": True,
                "image": str(output),
                "provider": "grok-web-imagine",
                "model": "grok-web-imagine",
                "artifact_source": "browser_screenshot",
                "artifact_durability": "durable_history_or_post",
                "history_verified": False,
                "result_surface_id": "current",
                "quota_source": "consumer_web",
            }

    monkeypatch.setenv("HERMES_VISUAL_LIVE_E2E", "1")
    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")

    report = grok_web_imagine_live_e2e.build_grok_web_imagine_live_e2e_report(
        work_dir=tmp_path,
        prompt="clean product photo",
        aspect_ratio="portrait",
        provider_factory=lambda: FakeProvider(),
    )

    assert report["success"] is False
    assert report["status"] == "ephemeral_artifact"
    assert report["self_review"]["durable_history_verified"] is False
    assert report["result_surface_id"] == "current"


def test_grok_web_imagine_live_e2e_cli_accepts_regenerate_current_operation(monkeypatch, tmp_path, capsys):
    from scripts import grok_web_imagine_live_e2e

    output = tmp_path / "grok-web-regenerate.png"
    output.write_bytes(b"generated")
    calls = []

    class FakeProvider:
        def generate(self, *args, **kwargs):
            calls.append((args, kwargs))
            return {
                "success": True,
                "image": str(output),
                "provider": "grok-web-imagine",
                "model": "grok-web-imagine",
                "artifact_source": "browser_screenshot",
                "artifact_durability": "durable_history_or_post",
                "history_verified": True,
                "page_url": "https://grok.com/imagine/post/abc123",
                "quota_source": "consumer_web",
                "operation": kwargs["operation"],
            }

    monkeypatch.setenv("HERMES_VISUAL_LIVE_E2E", "1")
    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")
    monkeypatch.setattr(grok_web_imagine_live_e2e, "_default_provider", lambda: FakeProvider())

    exit_code = grok_web_imagine_live_e2e.main(
        [
            "--operation",
            "regenerate_current",
            "--prompt",
            "重新產生",
            "--work-dir",
            str(tmp_path),
        ]
    )

    report = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert report["request"]["operation"] == "regenerate_current"
    assert report["provider_result"]["operation"] == "regenerate_current"
    assert calls == [
        (
            ("重新產生",),
            {
                "aspect_ratio": "portrait",
                "image_url": None,
                "reference_image_urls": None,
                "operation": "regenerate_current",
                "timeout_seconds": 240,
            },
        )
    ]


def test_grok_web_imagine_live_e2e_cli_attaches_quality_review_report(
    monkeypatch,
    tmp_path,
    capsys,
):
    from scripts import grok_web_imagine_live_e2e

    output = tmp_path / "grok-web-reviewed.png"
    output.write_bytes(b"generated")
    review_report = tmp_path / "quality-review.json"
    review_report.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "raphael_visual_quality_review",
                "generated_at": "2026-06-30T13:20:00Z",
                "command": "vision-backed artifact quality review",
                "run_id": "visual-quality-review-1",
                "producer": "hermes-visual-quality-review",
                "reviewer": "vision-backed-artifact-review",
                "artifact_path": str(output),
                "artifact_quality_verdict": "pass",
                "dimensions": {
                    "composition": "pass",
                    "prompt_adherence": "pass",
                    "geometry": "pass",
                    "subject_quality": "pass",
                },
            }
        ),
        encoding="utf-8",
    )

    class FakeProvider:
        def generate(self, *_args, **_kwargs):
            return {
                "success": True,
                "image": str(output),
                "provider": "grok-web-imagine",
                "model": "grok-web-imagine",
                "artifact_source": "browser_screenshot",
                "artifact_durability": "durable_history_or_post",
                "history_verified": True,
                "page_url": "https://grok.com/imagine/post/abc123",
                "quota_source": "consumer_web",
            }

    monkeypatch.setenv("HERMES_VISUAL_LIVE_E2E", "1")
    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")
    monkeypatch.setattr(grok_web_imagine_live_e2e, "_default_provider", lambda: FakeProvider())

    exit_code = grok_web_imagine_live_e2e.main(
        [
            "--prompt",
            "polished final image",
            "--work-dir",
            str(tmp_path),
            "--quality-review-report",
            str(review_report),
        ]
    )

    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert report["quality_review"]["source_report_path"] == str(review_report)
    assert report["quality_review"]["run_id"] == "visual-quality-review-1"
    assert report["quality_review"]["reviewer"] == "vision-backed-artifact-review"
    assert report["quality_review"]["artifact_path"] == str(output)


def test_grok_web_imagine_live_e2e_cli_attaches_quality_review_to_existing_report(
    monkeypatch,
    tmp_path,
    capsys,
):
    from scripts import grok_web_imagine_live_e2e

    output = tmp_path / "grok-web-reviewed.png"
    output.write_bytes(b"generated")
    live_report = tmp_path / "grok-web-live-report.json"
    attached_report = tmp_path / "grok-web-live-report.reviewed.json"
    live_report.write_text(
        json.dumps(
            {
                "run_id": "grok-web-live-1",
                "generated_at": "2026-06-30T13:20:00Z",
                "success": True,
                "status": "completed",
                "provider_mode": "grok-web-imagine-live",
                "artifact": {
                    "path": str(output),
                    "exists": True,
                    "source": "browser_screenshot",
                    "durability": "durable_history_or_post",
                    "history_verified": True,
                    "page_url": "https://grok.com/imagine/post/abc123",
                },
            }
        ),
        encoding="utf-8",
    )
    review_report = tmp_path / "quality-review.json"
    review_report.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "raphael_visual_quality_review",
                "generated_at": "2026-06-30T13:25:00Z",
                "command": "vision-backed artifact quality review",
                "run_id": "visual-quality-review-1",
                "producer": "hermes-visual-quality-review",
                "reviewer": "vision-backed-artifact-review",
                "artifact_path": str(output),
                "artifact_quality_verdict": "pass",
                "dimensions": {
                    "composition": "pass",
                    "prompt_adherence": "pass",
                    "geometry": "pass",
                    "subject_quality": "pass",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        grok_web_imagine_live_e2e,
        "_default_provider",
        lambda: (_ for _ in ()).throw(AssertionError("provider should not run")),
    )

    exit_code = grok_web_imagine_live_e2e.main(
        [
            "--input-report",
            str(live_report),
            "--quality-review-report",
            str(review_report),
            "--output",
            str(attached_report),
        ]
    )

    report = json.loads(capsys.readouterr().out)
    written_report = json.loads(attached_report.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert written_report == report
    assert report["run_id"] == "grok-web-live-1"
    assert report["quality_review"]["source_report_path"] == str(review_report)
    assert report["quality_review"]["run_id"] == "visual-quality-review-1"
    assert report["quality_review"]["reviewer"] == "vision-backed-artifact-review"
    assert report["quality_review"]["artifact_path"] == str(output)


def test_grok_web_imagine_live_e2e_cli_fails_attach_mode_when_quality_report_missing(
    monkeypatch,
    tmp_path,
    capsys,
):
    from scripts import grok_web_imagine_live_e2e

    output = tmp_path / "grok-web-reviewed.png"
    output.write_bytes(b"generated")
    live_report = tmp_path / "grok-web-live-report.json"
    attached_report = tmp_path / "grok-web-live-report.reviewed.json"
    missing_review_report = tmp_path / "missing-quality-review.json"
    live_report.write_text(
        json.dumps(
            {
                "run_id": "grok-web-live-1",
                "generated_at": "2026-06-30T13:20:00Z",
                "success": True,
                "status": "completed",
                "provider_mode": "grok-web-imagine-live",
                "artifact": {
                    "path": str(output),
                    "exists": True,
                    "source": "browser_screenshot",
                    "durability": "durable_history_or_post",
                    "history_verified": True,
                    "page_url": "https://grok.com/imagine/post/abc123",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        grok_web_imagine_live_e2e,
        "_default_provider",
        lambda: (_ for _ in ()).throw(AssertionError("provider should not run")),
    )

    exit_code = grok_web_imagine_live_e2e.main(
        [
            "--input-report",
            str(live_report),
            "--quality-review-report",
            str(missing_review_report),
            "--output",
            str(attached_report),
        ]
    )

    report = json.loads(capsys.readouterr().out)
    written_report = json.loads(attached_report.read_text(encoding="utf-8"))
    assert exit_code == 2
    assert written_report == report
    assert report["success"] is False
    assert report["status"] == "quality_review_attachment_error"
    assert report["quality_review"]["attachment_error"] == "FileNotFoundError"
