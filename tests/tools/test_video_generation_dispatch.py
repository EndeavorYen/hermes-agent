"""Tests for the unified ``video_generate`` tool dispatch surface."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

from agent import video_gen_registry
from agent.video_gen_provider import VideoGenProvider


@pytest.fixture(autouse=True)
def _reset_registry():
    video_gen_registry._reset_for_tests()
    yield
    video_gen_registry._reset_for_tests()


class _RecordingProvider(VideoGenProvider):
    """Captures the kwargs the tool layer hands it."""

    def __init__(self, name: str = "fake"):
        self._name = name
        self.last_kwargs: Dict[str, Any] = {}

    @property
    def name(self) -> str:
        return self._name

    def list_models(self) -> List[Dict[str, Any]]:
        return [{"id": "model-a"}]

    def default_model(self) -> Optional[str]:
        return "model-a"

    def generate(self, prompt, **kwargs):
        self.last_kwargs = {"prompt": prompt, **kwargs}
        modality = "image" if kwargs.get("image_url") else "text"
        return {
            "success": True,
            "video": "https://example.com/v.mp4",
            "model": kwargs.get("model") or "model-a",
            "prompt": prompt,
            "modality": modality,
            "aspect_ratio": kwargs.get("aspect_ratio", ""),
            "duration": kwargs.get("duration") or 0,
            "provider": self._name,
        }


class _ImageOnlyProvider(_RecordingProvider):
    """Provider catalog entry that cannot service text-only calls."""

    def __init__(self):
        super().__init__("image-only")
        self.calls: List[Dict[str, Any]] = []

    def list_models(self) -> List[Dict[str, Any]]:
        return [{"id": "image-only-model", "modalities": ["image"]}]

    def default_model(self) -> Optional[str]:
        return "image-only-model"

    def capabilities(self) -> Dict[str, Any]:
        return {"modalities": ["image"], "min_duration": 1, "max_duration": 10}

    def generate(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        return super().generate(prompt, **kwargs)


class _RaisingProvider(VideoGenProvider):
    @property
    def name(self) -> str:
        return "raises"

    def generate(self, prompt, **kwargs):
        raise RuntimeError("boom")


class _ModerationThenSuccessProvider(VideoGenProvider):
    @property
    def name(self) -> str:
        return "moderated"

    def __init__(self):
        self.calls: List[Dict[str, Any]] = []

    def default_model(self) -> Optional[str]:
        return "model-a"

    def generate(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        if len(self.calls) == 1:
            return {
                "success": False,
                "video": None,
                "error": "Generated video rejected by content moderation.",
                "error_type": "content_moderation",
                "error_code": "Client specified an invalid argument",
                "provider": self.name,
                "model": kwargs.get("model") or "model-a",
                "prompt": prompt,
            }
        return {
            "success": True,
            "video": "https://example.com/compromise.mp4",
            "model": kwargs.get("model") or "model-a",
            "prompt": prompt,
            "modality": "image" if kwargs.get("image_url") else "text",
            "aspect_ratio": kwargs.get("aspect_ratio", ""),
            "duration": kwargs.get("duration") or 0,
            "provider": self.name,
        }


class TestUnifiedDispatch:
    def _run(
        self,
        args: Dict[str, Any],
        *,
        configured: Optional[str] = None,
        configured_model: Optional[str] = None,
    ) -> Dict[str, Any]:
        from tools import video_generation_tool
        import hermes_cli.plugins as plugins_module

        saved = video_generation_tool._read_configured_video_provider
        video_generation_tool._read_configured_video_provider = lambda: configured  # type: ignore
        saved_model = video_generation_tool._read_configured_video_model
        video_generation_tool._read_configured_video_model = lambda: configured_model  # type: ignore
        saved_discover = plugins_module._ensure_plugins_discovered
        plugins_module._ensure_plugins_discovered = lambda *_a, **_k: None  # type: ignore
        try:
            raw = video_generation_tool._handle_video_generate(args)
        finally:
            video_generation_tool._read_configured_video_provider = saved  # type: ignore
            video_generation_tool._read_configured_video_model = saved_model  # type: ignore
            plugins_module._ensure_plugins_discovered = saved_discover  # type: ignore
        return json.loads(raw)

    def test_no_provider_returns_clear_error(self):
        result = self._run({"prompt": "a dog"})
        assert result["success"] is False
        assert result["error_type"] == "no_provider_configured"

    def test_unknown_provider_returns_clear_error(self):
        result = self._run({"prompt": "a dog"}, configured="ghost")
        assert result["success"] is False
        assert result["error_type"] == "provider_not_registered"

    def test_text_to_video_routes_without_image_url(self):
        provider = _RecordingProvider("rec")
        video_gen_registry.register_provider(provider)
        result = self._run({"prompt": "a happy dog"})
        assert result["success"] is True
        assert result["modality"] == "text"
        assert "image_url" not in provider.last_kwargs
        assert provider.last_kwargs["aspect_ratio"] == "16:9"
        assert provider.last_kwargs["resolution"] == "720p"

    def test_image_to_video_routes_with_image_url(self):
        provider = _RecordingProvider("rec")
        video_gen_registry.register_provider(provider)
        result = self._run({
            "prompt": "animate this",
            "image_url": "https://example.com/img.png",
        })
        assert result["success"] is True
        assert result["modality"] == "image"
        assert provider.last_kwargs["image_url"] == "https://example.com/img.png"
        assert provider.last_kwargs["_aspect_ratio_override_explicit"] is False

    def test_image_only_model_requires_image_url_before_provider_call(self):
        provider = _ImageOnlyProvider()
        video_gen_registry.register_provider(provider)

        result = self._run(
            {"prompt": "animate this generated frame"},
            configured="image-only",
            configured_model="image-only-model",
        )

        assert result["success"] is False
        assert result["error_type"] == "missing_image_url"
        assert "image_url" in result["error"]
        assert provider.calls == []

    def test_video_prompt_mediator_defaults_to_medium_editorial_motion(self):
        provider = _RecordingProvider("rec")
        video_gen_registry.register_provider(provider)
        result = self._run({
            "prompt": "fashion editorial portrait, refined glamour styling",
            "image_url": "https://example.com/img.png",
        })

        assert result["success"] is True
        prompt = provider.last_kwargs["prompt"]
        assert "Video prompt mediator v1" in prompt
        assert "Motion intensity: medium" in prompt
        assert "static slideshow" in prompt
        assert "slow cinematic pan" not in prompt
        assert result["video_prompt_mediation"]["motion_intensity"] == "medium"

    def test_video_prompt_mediator_honors_dynamic_motion_controls(self):
        provider = _RecordingProvider("rec")
        video_gen_registry.register_provider(provider)
        result = self._run({
            "prompt": "glamour editorial beach photoshoot",
            "image_url": "https://example.com/img.png",
            "motion_intensity": "dynamic",
            "camera_motion": "low-angle tracking shot",
            "body_action": "confident walking turn with hair movement",
        })

        assert result["success"] is True
        prompt = provider.last_kwargs["prompt"]
        assert "Motion intensity: dynamic" in prompt
        assert "low-angle tracking shot" in prompt
        assert "confident walking turn with hair movement" in prompt
        assert result["video_prompt_mediation"]["motion_intensity"] == "dynamic"
        assert result["video_prompt_mediation"]["camera_motion"] == "low-angle tracking shot"
        assert result["video_prompt_mediation"]["body_action"] == "confident walking turn with hair movement"

    def test_video_prompt_mediator_preserves_long_core_brief_details(self):
        provider = _RecordingProvider("rec")
        video_gen_registry.register_provider(provider)
        important_late_detail = "final detail: barefoot leg-forward composition"
        long_prompt = (
            "professional glamour editorial image-to-video, same reference identity, "
            "mountain ridge background, black fitted dress, natural skin texture, "
            "beautiful face, elegant body line, cinematic daylight, "
            "avoid plastic texture, keep anatomy stable, "
            f"{important_late_detail}"
        )

        result = self._run({
            "prompt": long_prompt,
            "image_url": "https://example.com/img.png",
        })

        assert result["success"] is True
        assert important_late_detail in provider.last_kwargs["prompt"]

    def test_explicit_aspect_ratio_is_marked_for_provider(self):
        provider = _RecordingProvider("rec")
        video_gen_registry.register_provider(provider)
        result = self._run({
            "prompt": "animate this",
            "image_url": "https://example.com/img.png",
            "aspect_ratio": "9:16",
        })
        assert result["success"] is True
        assert provider.last_kwargs["aspect_ratio"] == "9:16"
        assert provider.last_kwargs["_aspect_ratio_override_explicit"] is True

    def test_prompt_required(self):
        provider = _RecordingProvider("rec")
        video_gen_registry.register_provider(provider)
        result = self._run({"prompt": "", "image_url": "https://example.com/i.png"})
        assert "error" in result
        assert "prompt" in result["error"].lower()

    def test_provider_exception_caught(self):
        video_gen_registry.register_provider(_RaisingProvider())
        result = self._run({"prompt": "x"})
        assert result["success"] is False
        assert result["error_type"] == "provider_exception"

    def test_content_moderation_retries_with_safe_compromise_prompt(self):
        provider = _ModerationThenSuccessProvider()
        video_gen_registry.register_provider(provider)

        result = self._run({
            "prompt": "性感寫真姿勢，sexy back pose, cinematic pan",
            "image_url": "https://example.com/ref.png",
            "duration": 8,
        })

        assert result["success"] is True
        assert result["video"] == "https://example.com/compromise.mp4"
        assert len(provider.calls) == 2
        retry_prompt = provider.calls[1]["prompt"]
        assert "safe compromise" in retry_prompt
        assert "refined glamour" in retry_prompt
        assert "Motion intensity: medium" in retry_prompt
        assert "slow cinematic pan" not in retry_prompt
        assert "性感" not in retry_prompt
        assert "sexy" not in retry_prompt.lower()
        assert provider.calls[1]["image_url"] == "https://example.com/ref.png"
        assert result["video_mediation"]["applied"] is True
        assert result["video_mediation"]["strategy"] == "safe_reframe_retry"
        assert result["video_mediation"]["first_error_type"] == "content_moderation"
        assert result["video_mediation"]["original_prompt"].startswith("性感寫真姿勢")
        assert result["video_prompt_mediation"]["safe_compromise"] is True

    def test_operation_field_not_in_schema(self):
        """Make sure we removed the operation field from the schema."""
        from tools.video_generation_tool import VIDEO_GENERATE_SCHEMA
        assert "operation" not in VIDEO_GENERATE_SCHEMA["parameters"]["properties"]
        assert "video_url" not in VIDEO_GENERATE_SCHEMA["parameters"]["properties"]
