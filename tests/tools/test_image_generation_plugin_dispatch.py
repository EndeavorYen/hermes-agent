from __future__ import annotations

import json
import pytest

from agent import image_gen_registry
from agent.image_gen_provider import ImageGenProvider


@pytest.fixture(autouse=True)
def _reset_registry():
    image_gen_registry._reset_for_tests()
    yield
    image_gen_registry._reset_for_tests()


class _FakeCodexProvider(ImageGenProvider):
    @property
    def name(self) -> str:
        return "codex"

    def generate(self, prompt, aspect_ratio="landscape", **kwargs):
        return {
            "success": True,
            "image": "/tmp/codex-test.png",
            "model": "gpt-5.2-codex",
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "provider": "codex",
        }


class _RecordingProvider(ImageGenProvider):
    def __init__(self):
        self.last_kwargs = {}

    @property
    def name(self) -> str:
        return "recording"

    def generate(self, prompt, aspect_ratio="landscape", **kwargs):
        self.last_kwargs = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            **kwargs,
        }
        return {
            "success": True,
            "image": "/tmp/recording.png",
            "model": kwargs.get("model") or "recording-model",
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "provider": "recording",
        }


class _FailingProvider(ImageGenProvider):
    def __init__(self, name: str, error: str, error_type: str = "api_error"):
        self._name = name
        self.error = error
        self.error_type = error_type
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    def generate(self, prompt, aspect_ratio="landscape", **kwargs):
        self.calls += 1
        return {
            "success": False,
            "image": None,
            "error": self.error,
            "error_type": self.error_type,
            "model": f"{self._name}-model",
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "provider": self._name,
        }


class _GrokWebFallbackProvider(ImageGenProvider):
    def __init__(self):
        self.calls = 0
        self.last_kwargs = {}

    @property
    def name(self) -> str:
        return "grok-web-imagine"

    def generate(self, prompt, aspect_ratio="landscape", **kwargs):
        self.calls += 1
        self.last_kwargs = {"prompt": prompt, "aspect_ratio": aspect_ratio, **kwargs}
        return {
            "success": True,
            "image": "/tmp/grok-web.png",
            "model": "grok-web-imagine",
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "provider": "grok-web-imagine",
            "provider_family": "grok_web",
            "quota_source": "consumer_web",
        }


class TestPluginDispatch:
    def test_dispatch_routes_to_codex_provider(self, monkeypatch, tmp_path):
        from tools import image_generation_tool
        from agent import image_gen_registry as registry_module
        from hermes_cli import plugins as plugins_module

        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        (tmp_path / "config.yaml").write_text("image_gen:\n  provider: codex\n")
        image_gen_registry.register_provider(_FakeCodexProvider())

        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: "codex")
        monkeypatch.setattr(plugins_module, "_ensure_plugins_discovered", lambda: None)
        monkeypatch.setattr(registry_module, "get_provider", lambda name: _FakeCodexProvider() if name == "codex" else None)

        dispatched = image_generation_tool._dispatch_to_plugin_provider("draw cat", "square")
        payload = json.loads(dispatched)

        assert payload["success"] is True
        assert payload["provider"] == "codex"
        assert payload["image"] == "/tmp/codex-test.png"
        assert payload["aspect_ratio"] == "square"

    def test_dispatch_reports_missing_registered_provider(self, monkeypatch, tmp_path):
        from tools import image_generation_tool
        from hermes_cli import plugins as plugins_module

        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        (tmp_path / "config.yaml").write_text("image_gen:\n  provider: missing-codex\n")

        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: "missing-codex")
        monkeypatch.setattr(plugins_module, "_ensure_plugins_discovered", lambda: None)

        dispatched = image_generation_tool._dispatch_to_plugin_provider("draw cat", "landscape")
        payload = json.loads(dispatched)

        assert payload["success"] is False
        assert payload["error_type"] == "provider_not_registered"
        assert "image_gen.provider='missing-codex'" in payload["error"]

    def test_dispatch_force_refreshes_plugins_when_provider_initially_missing(self, monkeypatch, tmp_path):
        from tools import image_generation_tool
        from hermes_cli import plugins as plugins_module
        from agent import image_gen_registry as registry_module

        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        (tmp_path / "config.yaml").write_text("image_gen:\n  provider: codex\n")

        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: "codex")

        calls = []
        provider_state = {"provider": None}

        def fake_ensure_plugins_discovered(force=False):
            calls.append(force)
            if force:
                provider_state["provider"] = _FakeCodexProvider()

        monkeypatch.setattr(plugins_module, "_ensure_plugins_discovered", fake_ensure_plugins_discovered)
        monkeypatch.setattr(registry_module, "get_provider", lambda name: provider_state["provider"])

        dispatched = image_generation_tool._dispatch_to_plugin_provider("draw hammy", "portrait")
        payload = json.loads(dispatched)

        assert calls == [False, True]
        assert payload["success"] is True
        assert payload["provider"] == "codex"
        assert payload["aspect_ratio"] == "portrait"

    def test_handle_internal_provider_override_routes_to_fallback_provider(self, monkeypatch, tmp_path):
        from tools import image_generation_tool
        from agent import image_gen_registry as registry_module
        from hermes_cli import plugins as plugins_module

        primary = _RecordingProvider()
        fallback = _FakeCodexProvider()
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: "recording")
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_model", lambda: "primary-model")
        monkeypatch.setattr(plugins_module, "_ensure_plugins_discovered", lambda *a, **k: None)
        monkeypatch.setattr(
            registry_module,
            "get_provider",
            lambda name: {"recording": primary, "codex": fallback}.get(name),
        )

        payload = json.loads(
            image_generation_tool._handle_image_generate(
                {
                    "prompt": "draw cat",
                    "aspect_ratio": "square",
                    "_provider": "codex",
                }
            )
        )

        assert payload["success"] is True
        assert payload["provider"] == "codex"
        assert payload["image"] == "/tmp/codex-test.png"
        assert primary.last_kwargs == {}

    def test_handle_accepts_reference_images_alias_for_runtime_plugins(self, monkeypatch, tmp_path):
        """Machine-local plugins still call image_generate with reference_images.

        The upstream schema uses reference_image_urls, but runtime plugins such
        as Visual Arsenal predate that rename. Keep the handler compatible by
        normalizing reference_images into the provider-facing field.
        """
        from tools import image_generation_tool
        from agent import image_gen_registry as registry_module
        from hermes_cli import plugins as plugins_module

        provider = _RecordingProvider()
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        (tmp_path / "config.yaml").write_text("image_gen:\n  provider: recording\n")
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: "recording")
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_model", lambda: None)
        monkeypatch.setattr(plugins_module, "_ensure_plugins_discovered", lambda *a, **k: None)
        monkeypatch.setattr(registry_module, "get_provider", lambda name: provider if name == "recording" else None)

        payload = json.loads(
            image_generation_tool._handle_image_generate(
                {
                    "prompt": "draw from refs",
                    "reference_images": ["https://example.com/ref.png"],
                }
            )
        )

        assert payload["success"] is True
        assert provider.last_kwargs["reference_image_urls"] == [
            "https://example.com/ref.png"
        ]

    def test_xai_quota_failure_falls_back_to_grok_web_when_opted_in(self, monkeypatch, tmp_path):
        from tools import image_generation_tool
        from agent import image_gen_registry as registry_module
        from hermes_cli import plugins as plugins_module

        xai = _FailingProvider(
            "xai",
            "xAI image generation failed (403): "
            '{"code":"personal-team-blocked:spending-limit","error":"run out of credits"}',
        )
        grok_web = _GrokWebFallbackProvider()
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE_FALLBACK", "1")
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: "xai")
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_model", lambda: None)
        monkeypatch.setattr(image_generation_tool, "_postprocess_image_generate_result", lambda raw, task_id=None: raw)
        monkeypatch.setattr(
            image_generation_tool,
            "_track_image_generate_result",
            lambda raw, **kwargs: raw,
        )
        monkeypatch.setattr(plugins_module, "_ensure_plugins_discovered", lambda *a, **k: None)
        monkeypatch.setattr(
            registry_module,
            "get_provider",
            lambda name: {"xai": xai, "grok-web-imagine": grok_web}.get(name),
        )

        payload = json.loads(
            image_generation_tool._handle_image_generate(
                {
                    "prompt": "draw a clean product photo",
                    "aspect_ratio": "square",
                }
            )
        )

        assert xai.calls == 1
        assert grok_web.calls == 1
        assert payload["success"] is True
        assert payload["provider"] == "grok-web-imagine"
        assert payload["provider_family"] == "grok_web"
        assert payload["quota_source"] == "consumer_web"
        assert payload["fallback_from_provider"] == "xai"
        assert payload["fallback_reason"] == "xai_api_quota_exceeded"
        assert payload["primary_failure_class"] == "quota_exceeded"
        assert grok_web.last_kwargs["prompt"] == "draw a clean product photo"

    def test_xai_quota_failure_does_not_fallback_without_explicit_opt_in(self, monkeypatch, tmp_path):
        from tools import image_generation_tool
        from agent import image_gen_registry as registry_module
        from hermes_cli import plugins as plugins_module

        xai = _FailingProvider(
            "xai",
            "xAI image generation failed (403): personal-team-blocked:spending-limit",
        )
        grok_web = _GrokWebFallbackProvider()
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.delenv("HERMES_GROK_WEB_IMAGINE_FALLBACK", raising=False)
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: "xai")
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_model", lambda: None)
        monkeypatch.setattr(image_generation_tool, "_postprocess_image_generate_result", lambda raw, task_id=None: raw)
        monkeypatch.setattr(image_generation_tool, "_track_image_generate_result", lambda raw, **kwargs: raw)
        monkeypatch.setattr(plugins_module, "_ensure_plugins_discovered", lambda *a, **k: None)
        monkeypatch.setattr(
            registry_module,
            "get_provider",
            lambda name: {"xai": xai, "grok-web-imagine": grok_web}.get(name),
        )

        payload = json.loads(image_generation_tool._handle_image_generate({"prompt": "draw cat"}))

        assert xai.calls == 1
        assert grok_web.calls == 0
        assert payload["success"] is False
        assert payload["provider"] == "xai"

    def test_xai_content_moderation_does_not_fallback_to_web_quota(self, monkeypatch, tmp_path):
        from tools import image_generation_tool
        from agent import image_gen_registry as registry_module
        from hermes_cli import plugins as plugins_module

        xai = _FailingProvider("xai", "Generated image rejected by content moderation.")
        grok_web = _GrokWebFallbackProvider()
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE_FALLBACK", "1")
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: "xai")
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_model", lambda: None)
        monkeypatch.setattr(image_generation_tool, "_postprocess_image_generate_result", lambda raw, task_id=None: raw)
        monkeypatch.setattr(image_generation_tool, "_track_image_generate_result", lambda raw, **kwargs: raw)
        monkeypatch.setattr(plugins_module, "_ensure_plugins_discovered", lambda *a, **k: None)
        monkeypatch.setattr(
            registry_module,
            "get_provider",
            lambda name: {"xai": xai, "grok-web-imagine": grok_web}.get(name),
        )

        payload = json.loads(image_generation_tool._handle_image_generate({"prompt": "draw cat"}))

        assert xai.calls == 1
        assert grok_web.calls == 0
        assert payload["success"] is False
        assert payload["provider"] == "xai"

    def test_xai_quota_fallback_skips_reference_conditioning(self, monkeypatch, tmp_path):
        from tools import image_generation_tool
        from agent import image_gen_registry as registry_module
        from hermes_cli import plugins as plugins_module

        xai = _FailingProvider(
            "xai",
            "xAI image generation failed (403): personal-team-blocked:spending-limit",
        )
        grok_web = _GrokWebFallbackProvider()
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE_FALLBACK", "1")
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: "xai")
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_model", lambda: None)
        monkeypatch.setattr(image_generation_tool, "_postprocess_image_generate_result", lambda raw, task_id=None: raw)
        monkeypatch.setattr(image_generation_tool, "_track_image_generate_result", lambda raw, **kwargs: raw)
        monkeypatch.setattr(plugins_module, "_ensure_plugins_discovered", lambda *a, **k: None)
        monkeypatch.setattr(
            registry_module,
            "get_provider",
            lambda name: {"xai": xai, "grok-web-imagine": grok_web}.get(name),
        )

        payload = json.loads(
            image_generation_tool._handle_image_generate(
                {
                    "prompt": "edit this",
                    "reference_image_urls": ["https://example.com/ref.png"],
                }
            )
        )

        assert xai.calls == 1
        assert grok_web.calls == 0
        assert payload["success"] is False
        assert payload["provider"] == "xai"
