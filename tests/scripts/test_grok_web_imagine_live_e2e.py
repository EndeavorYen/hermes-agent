from __future__ import annotations


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
    }
    assert report["provider"] == {
        "name": "grok-web-imagine",
        "model": "grok-web-imagine",
        "quota_source": "consumer_web",
    }


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
