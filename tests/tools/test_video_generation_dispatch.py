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

    def __init__(self, name: str = "fake", default_model: str = "model-a"):
        self._name = name
        self._default_model = default_model
        self.last_kwargs: Dict[str, Any] = {}

    @property
    def name(self) -> str:
        return self._name

    def list_models(self) -> List[Dict[str, Any]]:
        return [{"id": self._default_model}]

    def default_model(self) -> Optional[str]:
        return self._default_model

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


class _RaisingProvider(VideoGenProvider):
    @property
    def name(self) -> str:
        return "raises"

    def generate(self, prompt, **kwargs):
        raise RuntimeError("boom")


class TestUnifiedDispatch:
    def _run(self, args: Dict[str, Any], *, configured: Optional[str] = None) -> Dict[str, Any]:
        from tools import video_generation_tool
        import hermes_cli.plugins as plugins_module

        saved = video_generation_tool._read_configured_video_provider
        video_generation_tool._read_configured_video_provider = lambda: configured  # type: ignore
        saved_discover = plugins_module._ensure_plugins_discovered
        plugins_module._ensure_plugins_discovered = lambda *_a, **_k: None  # type: ignore
        try:
            raw = video_generation_tool._handle_video_generate(args)
        finally:
            video_generation_tool._read_configured_video_provider = saved  # type: ignore
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

    def test_xai_text_visual_video_routes_to_visual_package(self, monkeypatch):
        from tools import visual_package_tool

        async def fake_visual_package(args, **_kwargs):
            return json.dumps(
                {
                    "success": True,
                    "package_status": "success",
                    "videos": ["/tmp/grok-video.mp4"],
                    "images": [],
                    "visual_request_id": "vrq_grok_video",
                    "generation_payloads": {
                        "video": {
                            "success": True,
                            "video": "/tmp/grok-video.mp4",
                            "provider": "xai",
                            "model": "grok-imagine-video-1.5",
                        },
                    },
                    "generation_strategy": {"image_first_for_video": True},
                }
            )

        monkeypatch.setattr(
            visual_package_tool,
            "_handle_visual_package_generate",
            fake_visual_package,
        )
        provider = _RecordingProvider("xai", default_model="grok-imagine-video")
        video_gen_registry.register_provider(provider)

        result = self._run(
            {"prompt": "make a high quality fashion portrait video"},
            configured="xai",
        )

        assert result["success"] is True
        assert result["video"] == "/tmp/grok-video.mp4"
        assert result["provider"] == "xai"
        assert result["model"] == "grok-imagine-video-1.5"
        assert result["route"] == "image_first_visual_package"
        assert result["recommended_tool"] == "visual_package_generate"
        assert result["recommended_arguments"]["candidate_budget"] == 2
        assert provider.last_kwargs == {}

    def test_xai_text_visual_video_auto_routes_to_visual_package(self, monkeypatch):
        from tools import visual_package_tool

        captured: Dict[str, Any] = {}

        async def fake_visual_package(args, **_kwargs):
            captured.update(args)
            return json.dumps(
                {
                    "success": True,
                    "package_status": "success",
                    "videos": ["/tmp/current-video.mp4"],
                    "images": [],
                    "visual_request_id": "vrq_auto_video",
                    "delivery_metadata": {
                        "selected_visual_artifact_ids": ["art_video"],
                    },
                    "generation_strategy": {
                        "image_first_for_video": True,
                        "candidate_budget": 4,
                        "candidate_budget_source": "feedback_loop",
                    },
                }
            )

        monkeypatch.setattr(
            visual_package_tool,
            "_handle_visual_package_generate",
            fake_visual_package,
        )
        provider = _RecordingProvider("xai", default_model="grok-imagine-video-1.5")
        video_gen_registry.register_provider(provider)

        result = self._run(
            {
                "prompt": "make a high quality fashion portrait video",
                "duration": 4,
                "aspect_ratio": "9:16",
            },
            configured="xai",
        )

        assert result["success"] is True
        assert result["video"] == "/tmp/current-video.mp4"
        assert result["route"] == "image_first_visual_package"
        assert result["source_tool"] == "video_generate"
        assert result["visual_request_id"] == "vrq_auto_video"
        assert result["generation_strategy"]["image_first_for_video"] is True
        assert captured["prompt"] == "make a high quality fashion portrait video"
        assert captured["include_image"] is False
        assert captured["include_video"] is True
        assert captured["candidate_budget"] == 2
        assert captured["candidate_budget_source"] == "planner_default"
        assert captured["video_budget"] == 1
        assert captured["duration"] == 4
        assert captured["aspect_ratio"] == "9:16"
        assert provider.last_kwargs == {}

    def test_xai_visual_video_with_multiple_reference_images_routes_to_visual_package(self, monkeypatch):
        from tools import visual_package_tool

        captured: Dict[str, Any] = {}

        async def fake_visual_package(args, **_kwargs):
            captured.update(args)
            return json.dumps(
                {
                    "success": True,
                    "package_status": "success",
                    "videos": ["/tmp/current-reference-video.mp4"],
                    "images": [],
                    "visual_request_id": "vrq_reference_video",
                    "generation_strategy": {
                        "image_first_for_video": True,
                        "video_source_image": "/tmp/selected-source.png",
                        "video_source_artifact_id": "var_selected_source",
                    },
                }
            )

        monkeypatch.setattr(
            visual_package_tool,
            "_handle_visual_package_generate",
            fake_visual_package,
        )
        provider = _RecordingProvider("xai", default_model="grok-imagine-video-1.5")
        video_gen_registry.register_provider(provider)

        refs = [
            "https://example.com/candidate-1.png",
            "https://example.com/candidate-2.png",
            "https://example.com/candidate-3.png",
            "https://example.com/candidate-4.png",
        ]
        result = self._run(
            {
                "prompt": "make a high quality fashion portrait video",
                "reference_image_urls": refs,
                "duration": 6,
                "aspect_ratio": "9:16",
            },
            configured="xai",
        )

        assert result["success"] is True
        assert result["video"] == "/tmp/current-reference-video.mp4"
        assert result["route"] == "image_first_visual_package"
        assert result["recommended_tool"] == "visual_package_generate"
        assert captured["attachments"] == refs
        assert captured["include_image"] is False
        assert captured["include_video"] is True
        assert captured["candidate_budget"] == 2
        assert captured["video_budget"] == 1
        assert provider.last_kwargs == {}

    def test_xai_15_text_visual_video_routes_to_visual_package(self, monkeypatch):
        from tools import visual_package_tool

        async def fake_visual_package(args, **_kwargs):
            return json.dumps(
                {
                    "success": True,
                    "package_status": "success",
                    "videos": ["/tmp/grok-15-video.mp4"],
                    "images": [],
                    "visual_request_id": "vrq_grok_15_video",
                    "generation_strategy": {"image_first_for_video": True},
                }
            )

        monkeypatch.setattr(
            visual_package_tool,
            "_handle_visual_package_generate",
            fake_visual_package,
        )
        provider = _RecordingProvider("xai", default_model="grok-imagine-video-1.5")
        video_gen_registry.register_provider(provider)

        result = self._run(
            {"prompt": "make a high quality fashion portrait video"},
            configured="xai",
        )

        assert result["success"] is True
        assert result["video"] == "/tmp/grok-15-video.mp4"
        assert result["route"] == "image_first_visual_package"
        assert result["source_tool"] == "video_generate"
        assert result["recommended_tool"] == "visual_package_generate"
        assert provider.last_kwargs == {}

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

    def test_xai_image_to_video_materializes_remote_video_for_upload(self, monkeypatch, tmp_path):
        from tools import video_generation_tool

        cached = tmp_path / "cached.mp4"

        def fake_download_remote_video(url):
            assert url == "https://example.com/v.mp4"
            cached.write_bytes(b"video")
            return str(cached)

        monkeypatch.setattr(
            video_generation_tool,
            "download_remote_video",
            fake_download_remote_video,
            raising=False,
        )
        provider = _RecordingProvider("xai", default_model="grok-imagine-video-1.5")
        video_gen_registry.register_provider(provider)

        result = self._run(
            {
                "prompt": "animate this",
                "image_url": "https://example.com/img.png",
            },
            configured="xai",
        )

        assert result["success"] is True
        assert result["video"] == str(cached)
        assert result["source_video_url"] == "https://example.com/v.mp4"

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

    def test_operation_field_not_in_schema(self):
        """Make sure we removed the operation field from the schema."""
        from tools.video_generation_tool import VIDEO_GENERATE_SCHEMA
        assert "operation" not in VIDEO_GENERATE_SCHEMA["parameters"]["properties"]
        assert "video_url" not in VIDEO_GENERATE_SCHEMA["parameters"]["properties"]
