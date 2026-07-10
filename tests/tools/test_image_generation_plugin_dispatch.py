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


class _NamedRecordingProvider(ImageGenProvider):
    def __init__(self, name: str):
        self._name = name
        self.last_kwargs = {}

    @property
    def name(self) -> str:
        return self._name

    def generate(self, prompt, aspect_ratio="landscape", **kwargs):
        self.last_kwargs = {"prompt": prompt, "aspect_ratio": aspect_ratio, **kwargs}
        return {
            "success": True,
            "image": f"/tmp/{self._name}-test.png",
            "model": kwargs.get("model") or "fixture-image-model",
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "provider": self._name,
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

    def test_story_video_image_prompt_forces_openai_when_configured_provider_is_xai(
        self,
        monkeypatch,
        tmp_path,
    ):
        from agent import image_gen_registry as registry_module
        from hermes_cli import plugins as plugins_module
        from tools import image_generation_tool

        xai_provider = _NamedRecordingProvider("xai")
        openai_provider = _NamedRecordingProvider("openai-codex")
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: "xai")
        monkeypatch.setattr(
            image_generation_tool,
            "_read_configured_image_model",
            lambda: "grok-imagine-image-quality",
        )
        monkeypatch.setattr(plugins_module, "_ensure_plugins_discovered", lambda *a, **k: None)
        monkeypatch.setattr(
            registry_module,
            "get_provider",
            lambda name: {"xai": xai_provider, "openai-codex": openai_provider}.get(name),
        )

        prompt = (
            "Scene S03 keyframe concept for a 5-minute Traditional Chinese "
            "science explainer about dinosaur origins. Photoreal natural-history "
            "documentary paleoart. Leave the bottom 20% visually clean for subtitles."
        )
        payload = json.loads(
            image_generation_tool._handle_image_generate(
                {"prompt": prompt, "aspect_ratio": "landscape"}
            )
        )

        assert payload["success"] is True
        assert payload["provider"] == "openai-codex"
        assert openai_provider.last_kwargs["prompt"].startswith("Scene S03")
        assert xai_provider.last_kwargs == {}

    def test_story_video_image_prompt_rejects_explicit_xai_before_provider_call(
        self,
        monkeypatch,
        tmp_path,
    ):
        from agent import image_gen_registry as registry_module
        from hermes_cli import plugins as plugins_module
        from tools import image_generation_tool

        xai_provider = _NamedRecordingProvider("xai")
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: "xai")
        monkeypatch.setattr(plugins_module, "_ensure_plugins_discovered", lambda *a, **k: None)
        monkeypatch.setattr(
            registry_module,
            "get_provider",
            lambda name: xai_provider if name == "xai" else None,
        )

        prompt = "故事影片 scene keyframe，秘密提示詞 privacy-marker-3517，科普影片 5mins"
        payload = json.loads(
            image_generation_tool._handle_image_generate({"prompt": prompt, "_provider": "xai"})
        )

        assert payload["success"] is False
        assert payload["error_type"] == "story_video_provider_blocked"
        assert payload["provider"] == "xai"
        assert "privacy-marker-3517" not in str(payload)
        assert xai_provider.last_kwargs == {}

    def test_agent_mode_image_uses_sync_visual_package_handler(self, monkeypatch, tmp_path):
        from tools import image_generation_tool
        from tools import visual_package_tool

        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        captured = {}

        def fake_visual_package(args, **_kwargs):
            captured.update(args)
            return json.dumps(
                {
                    "success": True,
                    "package_status": "success",
                    "visual_request_id": "vrq_agent_image",
                    "images": ["/tmp/selected-agent-image.png"],
                    "generation_payloads": {
                        "image": [
                            {
                                "success": True,
                                "image": "/tmp/selected-agent-image.png",
                                "provider": "xai",
                                "model": "grok-imagine-image-quality",
                            }
                        ]
                    },
                    "delivery_metadata": {"selected_artifact_paths": ["/tmp/selected-agent-image.png"]},
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
        assert payload["visual_package_request_id"] == "vrq_agent_image"
        assert captured["attachments"] == ["/tmp/ref.png"]
        assert captured["image_provider"] == "xai"
