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


class _NamedRecordingProvider(ImageGenProvider):
    def __init__(self, name: str):
        self._name = name
        self.last_kwargs = {}

    @property
    def name(self) -> str:
        return self._name

    def generate(self, prompt, aspect_ratio="landscape", **kwargs):
        self.last_kwargs = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            **kwargs,
        }
        return {
            "success": True,
            "image": f"/tmp/{self._name}.png",
            "model": kwargs.get("model") or f"{self._name}-model",
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "provider": self._name,
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
    def test_handle_agent_mode_image_routes_to_visual_package(self, monkeypatch, tmp_path):
        from tools import image_generation_tool
        from tools import visual_package_tool

        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        captured: Dict[str, Any] = {}

        async def fake_visual_package(args, **_kwargs):
            captured.update(args)
            return json.dumps(
                {
                    "success": True,
                    "package_status": "success",
                    "images": ["/tmp/selected-agent-image.png"],
                    "visual_request_id": "vrq_agent_image",
                    "generation_payloads": {
                        "image": [
                            {
                                "success": True,
                                "image": "/tmp/selected-agent-image.png",
                                "provider": "xai",
                                "model": "grok-imagine-image-quality",
                            }
                        ],
                    },
                    "generation_strategy": {"candidate_budget": 2},
                }
            )

        monkeypatch.setattr(
            visual_package_tool,
            "_handle_visual_package_generate",
            fake_visual_package,
        )

        payload = json.loads(
            image_generation_tool._handle_image_generate(
                {
                    "prompt": "請用 Agent mode 固定這位角色，產出精緻圖片",
                    "aspect_ratio": "9:16",
                    "reference_image_urls": ["/tmp/ref.png"],
                    "agent_mode": True,
                    "_provider": "xai",
                }
            )
        )

        assert payload["success"] is True
        assert payload["image"] == "/tmp/selected-agent-image.png"
        assert payload["provider"] == "xai"
        assert payload["model"] == "grok-imagine-image-quality"
        assert payload["route"] == "image_visual_package"
        assert payload["source_tool"] == "image_generate"
        assert payload["recommended_tool"] == "visual_package_generate"
        assert payload["visual_package_request_id"] == "vrq_agent_image"
        assert captured["prompt"] == "請用 Agent mode 固定這位角色，產出精緻圖片"
        assert captured["include_image"] is True
        assert captured["include_video"] is False
        assert captured["candidate_budget"] == 2
        assert captured["candidate_budget_source"] == "agent_mode"
        assert captured["attachments"] == ["/tmp/ref.png"]
        assert captured["image_provider"] == "xai"

    def test_handle_agent_mode_grok_prompt_routes_visual_package_to_xai(self, monkeypatch, tmp_path):
        from tools import image_generation_tool
        from tools import visual_package_tool

        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: "openai-codex")
        captured: Dict[str, Any] = {}

        async def fake_visual_package(args, **_kwargs):
            captured.update(args)
            return json.dumps(
                {
                    "success": True,
                    "package_status": "success",
                    "images": ["/tmp/grok-agent-image.png"],
                    "generation_payloads": {
                        "image": [
                            {
                                "success": True,
                                "image": "/tmp/grok-agent-image.png",
                                "provider": "xai",
                                "model": "grok-imagine-image-quality",
                            }
                        ],
                    },
                }
            )

        monkeypatch.setattr(
            visual_package_tool,
            "_handle_visual_package_generate",
            fake_visual_package,
        )

        payload = json.loads(
            image_generation_tool._handle_image_generate(
                {
                    "prompt": "請用 Grok Imagine 生成純 2D 動漫角色",
                    "agent_mode": True,
                    "candidate_budget": 2,
                }
            )
        )

        assert payload["success"] is True
        assert payload["provider"] == "xai"
        assert payload["route"] == "image_visual_package"
        assert captured["image_provider"] == "xai"
        assert captured["candidate_budget"] == 2

    def test_handle_image_generate_can_disable_visual_tracking(self, monkeypatch, tmp_path):
        from tools import image_generation_tool

        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setattr(
            image_generation_tool,
            "_dispatch_to_plugin_provider",
            lambda *args, **kwargs: json.dumps(
                {
                    "success": True,
                    "image": "/tmp/internal.png",
                    "provider": "fixture",
                    "model": "fixture-image",
                }
            ),
        )
        monkeypatch.setattr(
            image_generation_tool,
            "_postprocess_image_generate_result",
            lambda raw, task_id=None: raw,
        )

        def fail_tracking(raw, **kwargs):
            raise AssertionError("internal visual package image calls must not create visual requests")

        monkeypatch.setattr(image_generation_tool, "_track_image_generate_result", fail_tracking)

        payload = json.loads(
            image_generation_tool._handle_image_generate(
                {
                    "prompt": "internal candidate",
                    "_disable_visual_tracking": True,
                }
            )
        )

        assert payload["success"] is True
        assert payload["image"] == "/tmp/internal.png"

    def test_handle_grok_prompt_overrides_configured_openai_provider(self, monkeypatch, tmp_path):
        from tools import image_generation_tool
        from agent import image_gen_registry as registry_module
        from hermes_cli import plugins as plugins_module

        xai = _NamedRecordingProvider("xai")
        openai = _NamedRecordingProvider("openai-codex")
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: "openai-codex")
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_model", lambda: "gpt-image-2-high")
        monkeypatch.setattr(plugins_module, "_ensure_plugins_discovered", lambda *a, **k: None)
        monkeypatch.setattr(
            registry_module,
            "get_provider",
            lambda name: {"xai": xai, "openai-codex": openai}.get(name),
        )

        payload = json.loads(
            image_generation_tool._handle_image_generate(
                {
                    "prompt": "請用 Grok Imagine 生成純 2D 動漫角色",
                    "aspect_ratio": "portrait",
                }
            )
        )

        assert payload["success"] is True
        assert payload["provider"] == "xai"
        assert xai.last_kwargs["prompt"] == "請用 Grok Imagine 生成純 2D 動漫角色"
        assert openai.last_kwargs == {}

    def test_handle_grok_web_imagine_provider_arg_is_not_collapsed_to_xai(self, monkeypatch, tmp_path):
        from tools import image_generation_tool
        from agent import image_gen_registry as registry_module
        from hermes_cli import plugins as plugins_module

        xai = _NamedRecordingProvider("xai")
        grok_web = _NamedRecordingProvider("grok-web-imagine")
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: "xai")
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_model", lambda: "grok-imagine-image-quality")
        monkeypatch.setattr(plugins_module, "_ensure_plugins_discovered", lambda *a, **k: None)
        monkeypatch.setattr(
            registry_module,
            "get_provider",
            lambda name: {"xai": xai, "grok-web-imagine": grok_web}.get(name),
        )

        payload = json.loads(
            image_generation_tool._handle_image_generate(
                {
                    "prompt": "請產出一張高品質動漫圖",
                    "provider": "Grok Web Imagine",
                }
            )
        )

        assert payload["success"] is True
        assert payload["provider"] == "grok-web-imagine"
        assert grok_web.last_kwargs["prompt"] == "請產出一張高品質動漫圖"
        assert xai.last_kwargs == {}

    def test_handle_provider_arg_preserves_grok_intent_after_prompt_rewrite(self, monkeypatch, tmp_path):
        from tools import image_generation_tool
        from agent import image_gen_registry as registry_module
        from hermes_cli import plugins as plugins_module

        xai = _NamedRecordingProvider("xai")
        openai = _NamedRecordingProvider("openai-codex")
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: "openai-codex")
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_model", lambda: "gpt-image-2-high")
        monkeypatch.setattr(plugins_module, "_ensure_plugins_discovered", lambda *a, **k: None)
        monkeypatch.setattr(
            registry_module,
            "get_provider",
            lambda name: {"xai": xai, "openai-codex": openai}.get(name),
        )

        payload = json.loads(
            image_generation_tool._handle_image_generate(
                {
                    "prompt": "Use the attached reference images to create the best selected 2D anime portrait.",
                    "aspect_ratio": "portrait",
                    "provider": "Grok Imagine",
                }
            )
        )

        assert payload["success"] is True
        assert payload["provider"] == "xai"
        assert xai.last_kwargs["prompt"].startswith("Use the attached reference images")
        assert openai.last_kwargs == {}

    def test_handle_followup_image_reuses_session_visual_references(self, monkeypatch, tmp_path):
        from tools import image_generation_tool
        from agent import image_gen_registry as registry_module
        from gateway.session_context import (
            clear_session_vars,
            reset_visual_reference_context,
            set_session_vars,
            set_visual_reference_context,
        )
        from hermes_cli import plugins as plugins_module

        provider = _NamedRecordingProvider("xai")
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: "xai")
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_model", lambda: "grok-imagine-image-quality")
        monkeypatch.setattr(plugins_module, "_ensure_plugins_discovered", lambda *a, **k: None)
        monkeypatch.setattr(registry_module, "get_provider", lambda name: provider if name == "xai" else None)

        tokens = set_session_vars(session_key="slack:D123")
        ref_token = set_visual_reference_context(["/tmp/previous-selected.png", "/tmp/original-ref.png"])
        try:
            payload = json.loads(
                image_generation_tool._handle_image_generate(
                    {
                        "prompt": "把上一張改成夜景，角色外貌保持一致",
                        "aspect_ratio": "portrait",
                    }
                )
            )
        finally:
            clear_session_vars(tokens)
            reset_visual_reference_context(ref_token)

        assert payload["success"] is True
        assert provider.last_kwargs["reference_image_urls"] == [
            "/tmp/previous-selected.png",
            "/tmp/original-ref.png",
        ]

    def test_handle_prompt_agent_mode_image_routes_to_visual_package(self, monkeypatch, tmp_path):
        from tools import image_generation_tool
        from tools import visual_package_tool

        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        captured: Dict[str, Any] = {}

        async def fake_visual_package(args, **_kwargs):
            captured.update(args)
            return json.dumps(
                {
                    "success": True,
                    "package_status": "success",
                    "images": ["/tmp/prompt-agent-image.png"],
                    "visual_request_id": "vrq_prompt_agent_image",
                }
            )

        monkeypatch.setattr(
            visual_package_tool,
            "_handle_visual_package_generate",
            fake_visual_package,
        )

        payload = json.loads(
            image_generation_tool._handle_image_generate(
                {
                    "prompt": "請用 visual agent mode 產出一張乾淨產品攝影圖",
                    "aspect_ratio": "square",
                }
            )
        )

        assert payload["success"] is True
        assert payload["image"] == "/tmp/prompt-agent-image.png"
        assert payload["route"] == "image_visual_package"
        assert captured["include_image"] is True
        assert captured["include_video"] is False

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

    def test_handle_forwards_grok_web_edit_current_operation_to_provider(self, monkeypatch, tmp_path):
        from tools import image_generation_tool
        from agent import image_gen_registry as registry_module
        from hermes_cli import plugins as plugins_module

        provider = _RecordingProvider()
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: "recording")
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_model", lambda: None)
        monkeypatch.setattr(image_generation_tool, "_postprocess_image_generate_result", lambda raw, task_id=None: raw)
        monkeypatch.setattr(image_generation_tool, "_track_image_generate_result", lambda raw, **kwargs: raw)
        monkeypatch.setattr(plugins_module, "_ensure_plugins_discovered", lambda *a, **k: None)
        monkeypatch.setattr(registry_module, "get_provider", lambda name: provider if name == "recording" else None)

        payload = json.loads(
            image_generation_tool._handle_image_generate(
                {
                    "prompt": "make the current post warmer",
                    "aspect_ratio": "square",
                    "operation": "edit_current",
                    "_provider": "recording",
                }
            )
        )

        assert payload["success"] is True
        assert provider.last_kwargs["operation"] == "edit_current"

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

    def test_xai_quota_fallback_skips_remote_reference_conditioning(self, monkeypatch, tmp_path):
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

    def test_xai_quota_fallback_preserves_local_reference_conditioning(self, monkeypatch, tmp_path):
        from tools import image_generation_tool
        from agent import image_gen_registry as registry_module
        from hermes_cli import plugins as plugins_module

        reference_path = tmp_path / "reference.png"
        reference_path.write_bytes(b"fake image")
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
                    "reference_image_urls": [str(reference_path)],
                }
            )
        )

        assert xai.calls == 1
        assert grok_web.calls == 1
        assert payload["success"] is True
        assert payload["provider"] == "grok-web-imagine"
        assert grok_web.last_kwargs["reference_image_urls"] == [str(reference_path)]
