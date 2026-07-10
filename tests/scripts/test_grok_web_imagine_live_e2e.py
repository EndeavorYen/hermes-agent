from __future__ import annotations

import pytest

from scripts import grok_web_imagine_live_e2e as live_e2e


def _live_env() -> dict[str, str]:
    return {
        "HERMES_VISUAL_LIVE_E2E": "1",
        "HERMES_GROK_WEB_IMAGINE": "1",
    }


def test_live_provider_setup_failure_is_structured(monkeypatch):
    def fail_provider_import():
        raise ImportError("Grok browser provider is not installed")

    monkeypatch.setattr(live_e2e, "_default_provider", fail_provider_import)

    try:
        report = live_e2e.build_grok_web_imagine_live_e2e_report(env=_live_env())
    except ImportError as exc:
        pytest.fail(f"provider setup failure escaped the live harness: {exc}")

    assert report["success"] is False
    assert report["status"] == "setup_required"
    assert report["requires_operator_setup"] is True
    assert report["self_review"]["provider_called"] is False


def test_live_generation_requires_safe_browser_preflight():
    calls: list[str] = []

    class BlockedProvider:
        def preflight(self, **_kwargs):
            calls.append("preflight")
            return {
                "ready": False,
                "safe_to_submit": False,
                "status": "composer_not_ready",
                "message": "submit button disabled",
            }

        def generate(self, *_args, **_kwargs):
            calls.append("generate")
            raise AssertionError("generate must not run after a blocked preflight")

    report = live_e2e.build_grok_web_imagine_live_e2e_report(
        provider_factory=BlockedProvider,
        env=_live_env(),
    )

    assert calls == ["preflight"]
    assert report["success"] is False
    assert report["status"] == "browser_preflight_blocked"
    assert report["self_review"]["provider_called"] is False


def test_live_generation_runs_only_after_safe_browser_preflight(tmp_path):
    calls: list[str] = []
    artifact = tmp_path / "selected.png"
    artifact.write_bytes(b"fixture")

    class ReadyProvider:
        def preflight(self, **_kwargs):
            calls.append("preflight")
            return {
                "ready": True,
                "safe_to_submit": True,
                "status": "ready",
                "message": "composer ready",
                "prompt_probe": {
                    "attempted": True,
                    "prompt_text_present": True,
                    "submit_enabled": True,
                },
            }

        def generate(self, *_args, **_kwargs):
            calls.append("generate")
            return {
                "success": True,
                "image": str(artifact),
                "provider": "grok-web-imagine",
                "history_verified": True,
                "history_entry_id": "history-1",
            }

    report = live_e2e.build_grok_web_imagine_live_e2e_report(
        provider_factory=ReadyProvider,
        env=_live_env(),
    )

    assert calls == ["preflight", "generate"]
    assert report["success"] is True
    assert report["browser_preflight"]["safe_to_submit"] is True


def test_ready_only_preflight_cannot_generate():
    calls: list[str] = []

    class ReadyOnlyProvider:
        def preflight(self, **_kwargs):
            calls.append("preflight")
            return {
                "ready": True,
                "status": "ready",
                "message": "composer claims ready",
            }

        def generate(self, *_args, **_kwargs):
            calls.append("generate")
            raise AssertionError("ready-only preflight must not authorize generation")

    report = live_e2e.build_grok_web_imagine_live_e2e_report(
        provider_factory=ReadyOnlyProvider,
        env=_live_env(),
    )

    assert calls == ["preflight"]
    assert report["success"] is False
    assert report["status"] == "browser_preflight_blocked"


@pytest.mark.parametrize(
    "missing_field",
    ("attempted", "prompt_text_present", "submit_enabled"),
)
def test_incomplete_prompt_probe_contract_cannot_generate(missing_field):
    calls: list[str] = []
    prompt_probe = {
        "attempted": True,
        "prompt_text_present": True,
        "submit_enabled": True,
    }
    prompt_probe.pop(missing_field)

    class IncompleteProbeProvider:
        def preflight(self, **_kwargs):
            calls.append("preflight")
            return {
                "ready": True,
                "safe_to_submit": True,
                "status": "ready",
                "message": "composer claims ready",
                "prompt_probe": prompt_probe,
            }

        def generate(self, *_args, **_kwargs):
            calls.append("generate")
            raise AssertionError("incomplete prompt probe must not authorize generation")

    report = live_e2e.build_grok_web_imagine_live_e2e_report(
        provider_factory=IncompleteProbeProvider,
        env=_live_env(),
    )

    assert calls == ["preflight"]
    assert report["success"] is False
    assert report["status"] == "browser_preflight_blocked"


def test_safe_to_submit_requires_literal_true():
    calls: list[str] = []

    class TruthySafeProvider:
        def preflight(self, **_kwargs):
            calls.append("preflight")
            return {
                "ready": True,
                "safe_to_submit": "true",
                "status": "ready",
                "message": "composer claims ready",
                "prompt_probe": {
                    "attempted": True,
                    "prompt_text_present": True,
                    "submit_enabled": True,
                },
            }

        def generate(self, *_args, **_kwargs):
            calls.append("generate")
            raise AssertionError("truthy strings must not authorize generation")

    report = live_e2e.build_grok_web_imagine_live_e2e_report(
        provider_factory=TruthySafeProvider,
        env=_live_env(),
    )

    assert calls == ["preflight"]
    assert report["success"] is False
    assert report["status"] == "browser_preflight_blocked"
