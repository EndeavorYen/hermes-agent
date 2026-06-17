"""Integration tests for the xAI video gen plugin's simplified surface.

xAI exposes only text-to-video and image-to-video through the unified
``video_generate`` tool. We assert the endpoint hit and the payload shape
because routing is the part most likely to break silently.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

import pytest
from PIL import Image

from agent import video_gen_registry


@pytest.fixture(autouse=True)
def _reset_registry():
    video_gen_registry._reset_for_tests()
    yield
    video_gen_registry._reset_for_tests()


class _FakeResponse:
    def __init__(
        self,
        status: int = 200,
        payload: Optional[Dict[str, Any]] = None,
        content: bytes = b"",
    ):
        self.status_code = status
        self._payload = payload or {}
        self.text = json.dumps(self._payload)
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("err", request=None, response=self)  # type: ignore

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self):
        self.posts: List[Dict[str, Any]] = []
        self.gets: List[Dict[str, Any]] = []
        self.closed = False

    async def __aenter__(self):
        self.closed = False
        return self

    async def __aexit__(self, *args):
        self.closed = True
        return None

    async def post(self, url, headers=None, json=None, timeout=None):
        if self.closed:
            raise RuntimeError("Cannot send a request, as the client has been closed.")
        self.posts.append({"url": url, "json": json})
        return _FakeResponse(200, {"request_id": "req-123"})

    async def get(self, url, headers=None, timeout=None):
        if self.closed:
            raise RuntimeError("Cannot send a request, as the client has been closed.")
        self.gets.append({"url": url})
        if url == "https://xai-cdn/out.mp4":
            return _FakeResponse(200, content=b"video-bytes")
        return _FakeResponse(200, {
            "status": "done",
            "video": {"url": "https://xai-cdn/out.mp4", "duration": 8},
            "model": self.posts[-1]["json"]["model"],
        })


@pytest.fixture
def xai_provider(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key")

    import plugins.video_gen.xai as xai_plugin

    captured: Dict[str, _FakeAsyncClient] = {}

    def _client_factory():
        captured["client"] = _FakeAsyncClient()
        return captured["client"]

    monkeypatch.setattr(xai_plugin.httpx, "AsyncClient", _client_factory)

    async def _no_sleep(*a, **k):
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    provider = xai_plugin.XAIVideoGenProvider()
    return provider, captured


def _last_post(captured) -> Dict[str, Any]:
    return captured["client"].posts[-1]


class TestXAIEndpoint:
    """xAI uses one endpoint — ``/videos/generations`` — for both modes."""

    def test_text_to_video_hits_generations(self, xai_provider):
        provider, captured = xai_provider
        result = provider.generate("a dog on a skateboard")
        assert result["success"] is True
        assert _last_post(captured)["url"].endswith("/videos/generations")
        assert result["modality"] == "text"

    def test_uses_configured_timeout_seconds(self, xai_provider, monkeypatch):
        provider, captured = xai_provider

        import plugins.video_gen.xai as xai_plugin

        monkeypatch.setattr(
            xai_plugin,
            "_read_xai_video_config",
            lambda: {"timeout_seconds": 600},
        )

        seen = {}

        async def fake_poll(*_args, **kwargs):
            seen["timeout_seconds"] = kwargs["timeout_seconds"]
            return {
                "status": "done",
                "body": {
                    "video": {"url": "https://xai-cdn/out.mp4", "duration": 8},
                    "model": "grok-imagine-video",
                },
            }

        monkeypatch.setattr(xai_plugin, "_poll", fake_poll)

        result = provider.generate("a dog on a skateboard")

        assert result["success"] is True
        assert _last_post(captured)["url"].endswith("/videos/generations")
        assert seen["timeout_seconds"] == 600

    def test_submit_http_error_exposes_status_and_error_code(
        self, xai_provider, monkeypatch
    ):
        provider, captured = xai_provider

        class SubmitErrorClient(_FakeAsyncClient):
            async def post(self, url, headers=None, json=None, timeout=None):
                self.posts.append({"url": url, "json": json})
                return _FakeResponse(
                    400,
                    {
                        "code": "Client specified an invalid argument",
                        "error": "Generated video rejected by content moderation.",
                    },
                )

        import plugins.video_gen.xai as xai_plugin

        def _client_factory():
            captured["client"] = SubmitErrorClient()
            return captured["client"]

        monkeypatch.setattr(xai_plugin.httpx, "AsyncClient", _client_factory)

        result = provider.generate("make this unsafe")

        assert result["success"] is False
        assert result["error_type"] == "content_moderation"
        assert result["error_phase"] == "submit"
        assert result["http_status"] == 400
        assert result["error_code"] == "Client specified an invalid argument"
        assert "content moderation" in result["error"]

    def test_poll_http_error_exposes_request_id_and_error_code(
        self, xai_provider, monkeypatch
    ):
        provider, captured = xai_provider

        class PollErrorClient(_FakeAsyncClient):
            async def get(self, url, headers=None, timeout=None):
                self.gets.append({"url": url})
                return _FakeResponse(
                    429,
                    {"code": "rate_limit_exceeded", "error": "try later"},
                )

        import plugins.video_gen.xai as xai_plugin

        def _client_factory():
            captured["client"] = PollErrorClient()
            return captured["client"]

        monkeypatch.setattr(xai_plugin.httpx, "AsyncClient", _client_factory)

        result = provider.generate("a dog on a skateboard")

        assert result["success"] is False
        assert result["error_type"] == "rate_limited"
        assert result["error_phase"] == "poll"
        assert result["http_status"] == 429
        assert result["error_code"] == "rate_limit_exceeded"
        assert result["request_id"] == "req-123"

    def test_poll_connect_timeout_exposes_request_id_and_error_code(
        self, xai_provider, monkeypatch
    ):
        provider, _captured = xai_provider

        import httpx
        import plugins.video_gen.xai as xai_plugin

        async def fake_poll(*_args, **_kwargs):
            raise httpx.ConnectTimeout("connect timed out")

        monkeypatch.setattr(xai_plugin, "_poll", fake_poll)

        result = provider.generate("a dog on a skateboard")

        assert result["success"] is False
        assert result["error_type"] == "timeout"
        assert result["error_phase"] == "poll"
        assert result["error_code"] == "connect_timeout"
        assert result["request_id"] == "req-123"
        assert "connect timed out" in result["error"]

    def test_timeout_exposes_request_id_last_status_and_error_code(
        self, xai_provider, monkeypatch
    ):
        provider, captured = xai_provider

        import plugins.video_gen.xai as xai_plugin

        monkeypatch.setattr(
            xai_plugin,
            "_read_xai_video_config",
            lambda: {"timeout_seconds": 600},
        )

        async def fake_poll(*_args, **_kwargs):
            return {"status": "timeout", "body": {"status": "queued"}}

        monkeypatch.setattr(xai_plugin, "_poll", fake_poll)

        result = provider.generate("a dog on a skateboard")

        assert result["success"] is False
        assert result["error_type"] == "timeout"
        assert result["error_code"] == "hermes_poll_timeout"
        assert result["request_id"] == "req-123"
        assert result["xai_status"] == "queued"
        assert result["timeout_seconds"] == 600

    def test_image_to_video_hits_generations(self, xai_provider):
        provider, captured = xai_provider
        result = provider.generate(
            "animate this",
            image_url="https://example.com/cat.png",
        )
        assert result["success"] is True
        assert _last_post(captured)["url"].endswith("/videos/generations")
        assert result["modality"] == "image"

    def test_done_video_is_cached_locally_with_remote_url_metadata(
        self, xai_provider, monkeypatch, tmp_path
    ):
        provider, _captured = xai_provider

        import plugins.video_gen.xai as xai_plugin

        saved = {}

        def fake_save_bytes_video(raw, *, prefix, extension):
            saved["raw"] = raw
            saved["prefix"] = prefix
            saved["extension"] = extension
            path = tmp_path / f"{prefix}.{extension}"
            path.write_bytes(raw)
            return path

        monkeypatch.setattr(
            xai_plugin,
            "save_bytes_video",
            fake_save_bytes_video,
            raising=False,
        )

        result = provider.generate("animate this", image_url="https://example.com/cat.png")

        assert result["success"] is True
        assert result["video"] == str(tmp_path / "xai_grok-imagine-video-1.5.mp4")
        assert result["remote_video_url"] == "https://xai-cdn/out.mp4"
        assert saved == {
            "raw": b"video-bytes",
            "prefix": "xai_grok-imagine-video-1.5",
            "extension": "mp4",
        }


class TestXAIPayload:
    def test_text_payload_has_no_image_field(self, xai_provider):
        provider, captured = xai_provider
        provider.generate("a dog at sunset")
        payload = _last_post(captured)["json"]
        assert payload["model"] == "grok-imagine-video"
        assert payload["prompt"] == "a dog at sunset"
        assert payload["aspect_ratio"] == "16:9"
        assert "image" not in payload
        assert "reference_images" not in payload

    def test_image_payload_has_image_field(self, xai_provider):
        provider, captured = xai_provider
        provider.generate("animate this", image_url="https://example.com/cat.png")
        payload = _last_post(captured)["json"]
        assert payload["model"] == "grok-imagine-video-1.5"
        assert payload["image"] == {"url": "https://example.com/cat.png"}
        assert "aspect_ratio" not in payload

    def test_local_image_path_is_sent_as_data_uri(self, xai_provider, tmp_path):
        provider, captured = xai_provider
        image_path = tmp_path / "frame.png"
        image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

        provider.generate("animate this", image_url=str(image_path))

        payload = _last_post(captured)["json"]
        assert payload["model"] == "grok-imagine-video-1.5"
        assert payload["image"]["url"].startswith("data:image/png;base64,")
        assert "aspect_ratio" not in payload

    def test_local_image_to_video_infers_portrait_aspect_ratio(
        self, xai_provider, tmp_path
    ):
        provider, captured = xai_provider
        image_path = tmp_path / "portrait.png"
        Image.new("RGB", (800, 1200), (30, 30, 30)).save(image_path)

        result = provider.generate("animate this", image_url=str(image_path))
        payload = _last_post(captured)["json"]
        assert "aspect_ratio" not in payload
        assert result["aspect_ratio"] == "2:3"

    def test_explicit_aspect_ratio_override_is_not_sent_for_xai_image_to_video(
        self, xai_provider, tmp_path
    ):
        provider, captured = xai_provider
        image_path = tmp_path / "portrait.png"
        Image.new("RGB", (800, 1200), (30, 30, 30)).save(image_path)

        provider.generate(
            "animate this",
            image_url=str(image_path),
            aspect_ratio="16:9",
            _aspect_ratio_override_explicit=True,
        )

        payload = _last_post(captured)["json"]
        assert "aspect_ratio" not in payload

    def test_text_model_override_routes_to_current_image_model(self, xai_provider):
        provider, captured = xai_provider
        provider.generate(
            "animate this",
            image_url="https://example.com/cat.png",
            model="grok-imagine-video",
            _model_override_explicit=True,
        )
        payload = _last_post(captured)["json"]
        assert payload["model"] == "grok-imagine-video-1.5"

    def test_non_default_explicit_model_override_is_honored_for_image(self, xai_provider):
        provider, captured = xai_provider
        provider.generate(
            "animate this",
            image_url="https://example.com/cat.png",
            model="custom-image-video-model",
            _model_override_explicit=True,
        )
        payload = _last_post(captured)["json"]
        assert payload["model"] == "custom-image-video-model"

    def test_reference_images_payload(self, xai_provider):
        provider, captured = xai_provider
        provider.generate(
            "keep this character",
            reference_image_urls=[
                "https://example.com/a.png",
                "https://example.com/b.png",
            ],
        )
        payload = _last_post(captured)["json"]
        assert payload["reference_images"] == [
            {"url": "https://example.com/a.png"},
            {"url": "https://example.com/b.png"},
        ]


class TestXAIValidation:
    def test_missing_prompt_rejects(self, xai_provider):
        provider, captured = xai_provider
        result = provider.generate("")
        assert result["success"] is False
        assert result["error_type"] == "missing_prompt"
        # Never hit the network
        assert "client" not in captured or not captured["client"].posts

    def test_image_plus_refs_rejects(self, xai_provider):
        provider, captured = xai_provider
        result = provider.generate(
            "x",
            image_url="https://example.com/i.png",
            reference_image_urls=["https://example.com/r.png"],
        )
        assert result["success"] is False
        assert result["error_type"] == "conflicting_inputs"
        assert "client" not in captured or not captured["client"].posts

    def test_too_many_references_rejects(self, xai_provider):
        provider, captured = xai_provider
        result = provider.generate(
            "x",
            reference_image_urls=[f"https://example.com/r{i}.png" for i in range(8)],
        )
        assert result["success"] is False
        assert result["error_type"] == "too_many_references"


class TestXAIClamping:
    def test_duration_clamped_to_15(self, xai_provider):
        provider, captured = xai_provider
        provider.generate("x", duration=30)
        assert _last_post(captured)["json"]["duration"] == 15

    def test_duration_clamped_when_refs_present(self, xai_provider):
        provider, captured = xai_provider
        provider.generate(
            "x",
            duration=15,
            reference_image_urls=["https://example.com/r.png"],
        )
        # refs present caps to 10
        assert _last_post(captured)["json"]["duration"] == 10

    def test_invalid_aspect_ratio_soft_clamps(self, xai_provider):
        provider, captured = xai_provider
        provider.generate("x", aspect_ratio="21:9")
        assert _last_post(captured)["json"]["aspect_ratio"] == "16:9"
