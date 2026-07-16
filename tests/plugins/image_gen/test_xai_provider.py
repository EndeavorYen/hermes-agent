#!/usr/bin/env python3
"""Tests for xAI image generation provider."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fake_api_key(monkeypatch, tmp_path):
    """Ensure XAI_API_KEY is set for all tests."""
    monkeypatch.setenv("XAI_API_KEY", "test-key-12345")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    try:
        import hermes_cli.config as cfg_mod

        if hasattr(cfg_mod, "_invalidate_load_config_cache"):
            cfg_mod._invalidate_load_config_cache()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Provider class tests
# ---------------------------------------------------------------------------


class TestXAIImageGenProvider:
    def test_name(self):
        from plugins.image_gen.xai import XAIImageGenProvider

        provider = XAIImageGenProvider()
        assert provider.name == "xai"

    def test_display_name(self):
        from plugins.image_gen.xai import XAIImageGenProvider

        provider = XAIImageGenProvider()
        assert provider.display_name == "xAI (Grok)"

    def test_is_available_with_key(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "sk-xxx")
        from plugins.image_gen.xai import XAIImageGenProvider

        provider = XAIImageGenProvider()
        assert provider.is_available() is True

    def test_is_available_without_key(self, monkeypatch):
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        from plugins.image_gen.xai import XAIImageGenProvider

        provider = XAIImageGenProvider()
        assert provider.is_available() is False

    def test_list_models(self):
        from plugins.image_gen.xai import XAIImageGenProvider

        provider = XAIImageGenProvider()
        models = provider.list_models()
        assert len(models) >= 1
        assert models[0]["id"] == "grok-imagine-image"

    def test_default_model(self):
        from plugins.image_gen.xai import XAIImageGenProvider

        provider = XAIImageGenProvider()
        assert provider.default_model() == "grok-imagine-image"

    def test_get_setup_schema(self):
        from plugins.image_gen.xai import XAIImageGenProvider

        provider = XAIImageGenProvider()
        schema = provider.get_setup_schema()
        assert schema["name"] == "xAI Grok Imagine (image)"
        assert schema["badge"] == "paid"
        # Auth resolution is delegated to the shared "xai_grok" post_setup
        # hook so the picker doesn't blindly prompt for XAI_API_KEY when the
        # user is already signed in via xAI Grok OAuth.
        assert schema["env_vars"] == []
        assert schema["post_setup"] == "xai_grok"

    def test_capabilities_expose_total_source_image_limit(self):
        from plugins.image_gen.xai import XAIImageGenProvider

        caps = XAIImageGenProvider().capabilities()
        assert caps["max_reference_images"] == 2
        assert caps["max_source_images"] == 3


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestConfig:
    def test_default_model(self):
        from plugins.image_gen.xai import _resolve_model

        model_id, meta = _resolve_model()
        assert model_id == "grok-imagine-image"

    def test_default_resolution(self):
        from plugins.image_gen.xai import _resolve_resolution

        assert _resolve_resolution() == "1k"

    def test_custom_model(self, monkeypatch):
        monkeypatch.setenv("XAI_IMAGE_MODEL", "grok-imagine-image")
        from plugins.image_gen.xai import _resolve_model

        model_id, _ = _resolve_model()
        assert model_id == "grok-imagine-image"


# ---------------------------------------------------------------------------
# Generate tests
# ---------------------------------------------------------------------------


class TestGenerate:
    def test_grok_build_extracts_markdown_wrapped_absolute_image_path(self, tmp_path):
        from plugins.image_gen.xai import _extract_grok_build_image

        image = tmp_path / "generated.jpg"
        image.write_bytes(b"image")
        stdout = json.dumps({"text": f"`{image}`"})

        assert _extract_grok_build_image(stdout) == str(image.resolve())

    def test_grok_build_resolves_session_relative_image_path(self, tmp_path):
        from plugins.image_gen.xai import _extract_grok_build_image

        workdir = tmp_path / "work"
        workdir.mkdir()
        grok_home = tmp_path / ".grok"
        session_id = "019f671d-6a86-7ee3-a189-24235146c063"
        from urllib.parse import quote

        image = (
            grok_home
            / "sessions"
            / quote(str(workdir.resolve()), safe="")
            / session_id
            / "images"
            / "1.jpg"
        )
        image.parent.mkdir(parents=True)
        image.write_bytes(b"image")
        stdout = json.dumps(
            {
                "sessionId": session_id,
                "structuredOutput": {"image_path": "images/1.jpg"},
            }
        )

        assert _extract_grok_build_image(
            stdout,
            workdir=workdir,
            config={"grok_home": str(grok_home)},
        ) == str(image.resolve())

    def test_grok_build_resolves_workdir_session_relative_image_path(self, tmp_path):
        from plugins.image_gen.xai import _extract_grok_build_image

        workdir = tmp_path / "work"
        session_id = "019f6c47-6ffd-7a70-8acf-b14c53822113"
        image = workdir / session_id / "images" / "1.jpg"
        image.parent.mkdir(parents=True)
        image.write_bytes(b"image")
        stdout = json.dumps(
            {
                "sessionId": session_id,
                "structuredOutput": {"image_path": "images/1.jpg"},
            }
        )

        assert _extract_grok_build_image(
            stdout,
            workdir=workdir,
        ) == str(image.resolve())

    def test_grok_build_resolves_url_encoded_vscode_file_link(self, tmp_path):
        from urllib.parse import quote

        from plugins.image_gen.xai import _extract_grok_build_image

        image = tmp_path / "generated image.jpg"
        image.write_bytes(b"image")
        encoded_path = quote(str(image.resolve()), safe="")
        stdout = json.dumps(
            {
                "text": (
                    "Generated file: "
                    f"[Open](vscode-file://vscode-app/{encoded_path})"
                )
            }
        )

        assert _extract_grok_build_image(stdout) == str(image.resolve())

    def test_grok_build_transport_uses_native_image_tools_without_web(
        self, monkeypatch, tmp_path
    ):
        from plugins.image_gen import xai as xai_module

        image = tmp_path / "generated.jpg"
        image.write_bytes(b"image")
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps({"result": {"image_path": str(image)}}),
                stderr="",
            )

        monkeypatch.setattr(
            xai_module,
            "_load_xai_config",
            lambda: {
                "transport": "grok-build",
                "grok_binary": "/Users/simon/.local/bin/grok",
            },
        )
        monkeypatch.setattr(xai_module, "_grok_build_available", lambda _cfg=None: True)
        monkeypatch.setattr(xai_module.subprocess, "run", fake_run)

        result = xai_module.XAIImageGenProvider().generate(
            prompt="A dramatic studio portrait",
            aspect_ratio="portrait",
        )

        assert result["success"] is True
        assert result["provider"] == "xai"
        assert result["transport"] == "grok-build"
        assert result["image"] == str(image)
        command = captured["command"]
        assert "--disable-web-search" in command
        assert "--tools" not in command
        assert "--json-schema" not in command
        denied = command[command.index("--disallowed-tools") + 1]
        assert "run_terminal_cmd" in denied
        assert "web_search" in denied
        assert "web_fetch" in denied
        assert "Agent" in denied
        assert "--no-subagents" in command
        assert "--no-memory" in command
        assert captured["kwargs"]["shell"] is False

    def test_grok_build_transport_instructs_native_edit_for_reference(
        self, monkeypatch, tmp_path
    ):
        from plugins.image_gen import xai as xai_module

        source = tmp_path / "source.png"
        source.write_bytes(b"source")
        image = tmp_path / "edited.jpg"
        image.write_bytes(b"image")
        captured = {}

        def fake_run(command, **_kwargs):
            captured["command"] = command
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps({"image_path": str(image)}),
                stderr="",
            )

        monkeypatch.setattr(
            xai_module,
            "_load_xai_config",
            lambda: {"transport": "grok-build", "grok_binary": "grok"},
        )
        monkeypatch.setattr(xai_module, "_grok_build_available", lambda _cfg=None: True)
        monkeypatch.setattr(xai_module.subprocess, "run", fake_run)

        result = xai_module.XAIImageGenProvider().generate(
            prompt="Keep identity and change the pose",
            aspect_ratio="portrait",
            image_url=str(source),
        )

        assert result["success"] is True
        single_prompt = captured["command"][captured["command"].index("--single") + 1]
        assert "image_edit" in single_prompt
        assert str(source) in single_prompt

    def test_missing_api_key(self, monkeypatch):
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        from plugins.image_gen.xai import XAIImageGenProvider

        provider = XAIImageGenProvider()
        result = provider.generate(prompt="test")
        assert result["success"] is False
        assert "XAI_API_KEY" in result["error"]

    def test_successful_generation(self):
        from plugins.image_gen.xai import XAIImageGenProvider

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "data": [{"b64_json": "dGVzdC1pbWFnZS1kYXRh"}],  # base64 "test-image-data"
        }

        with patch("plugins.image_gen.xai.requests.post", return_value=mock_resp):
            with patch("plugins.image_gen.xai.save_b64_image", return_value="/tmp/test.png"):
                provider = XAIImageGenProvider()
                result = provider.generate(prompt="A cat playing piano")

        assert result["success"] is True
        assert result["image"] == "/tmp/test.png"
        assert result["provider"] == "xai"
        assert result["model"] == "grok-imagine-image"

    def test_successful_url_response(self):
        """xAI URL response is cached locally — #26942 contract.

        Pre-fix this asserted ``result["image"] == "<the bare URL>"``, which
        was exactly the bug: xAI's ``imgen.x.ai/xai-tmp-*`` URLs expire fast
        and the gateway 404'd by ``send_photo`` time.  Post-fix the URL
        bytes are downloaded at tool-completion and the result carries an
        absolute filesystem path the gateway can upload from.
        """
        from plugins.image_gen.xai import XAIImageGenProvider

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "data": [{"url": "https://imgen.x.ai/xai-tmp-imgen-test.jpeg"}],
        }

        with patch("plugins.image_gen.xai.requests.post", return_value=mock_resp), \
             patch(
                 "plugins.image_gen.xai.save_url_image",
                 return_value=Path("/tmp/xai_grok-imagine-image_20260524_000000_deadbeef.jpg"),
             ) as mock_save_url:
            provider = XAIImageGenProvider()
            result = provider.generate(prompt="A cat playing piano")

        assert result["success"] is True
        assert result["image"].startswith("/"), (
            f"URL response must be cached to an absolute path, got {result['image']!r}"
        )
        assert "imgen.x.ai" not in result["image"], (
            "ephemeral xAI URL must not leak into result.image — caller will 404"
        )
        # The downloader should have been called exactly once with the URL
        # and an xai-prefixed cache filename.
        mock_save_url.assert_called_once()
        call_args, call_kwargs = mock_save_url.call_args
        assert call_args[0] == "https://imgen.x.ai/xai-tmp-imgen-test.jpeg"
        assert call_kwargs.get("prefix", "").startswith("xai_")

    def test_url_response_fails_closed_when_safe_cache_fails(self):
        """A provider URL must never bypass the guarded local cache path."""
        import requests as req_lib
        from plugins.image_gen.xai import XAIImageGenProvider

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "data": [{"url": "https://imgen.x.ai/xai-tmp-imgen-already-404.jpeg"}],
        }

        with patch("plugins.image_gen.xai.requests.post", return_value=mock_resp), \
             patch(
                 "plugins.image_gen.xai.save_url_image",
                 side_effect=req_lib.HTTPError("404 from CDN"),
             ):
            provider = XAIImageGenProvider()
            result = provider.generate(prompt="A cat playing piano")

        assert result["success"] is False
        assert result["error_type"] == "io_error"
        assert result["image"] is None
        assert "imgen.x.ai" not in str(result)

    def test_api_error(self):
        import requests as req_lib
        from plugins.image_gen.xai import XAIImageGenProvider

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        mock_resp.json.return_value = {"error": {"message": "Invalid API key"}}
        mock_resp.raise_for_status.side_effect = req_lib.HTTPError(response=mock_resp)

        with patch("plugins.image_gen.xai.requests.post", return_value=mock_resp):
            provider = XAIImageGenProvider()
            result = provider.generate(prompt="test")

        assert result["success"] is False
        assert result["error_type"] == "api_error"

    def test_api_error_preserves_real_response_status(self):
        import requests as req_lib
        from plugins.image_gen.xai import XAIImageGenProvider

        response = req_lib.Response()
        response.status_code = 401
        response._content = json.dumps({"error": {"message": "Invalid API key"}}).encode()
        response.headers["Content-Type"] = "application/json"

        response.raise_for_status = MagicMock(
            side_effect=req_lib.HTTPError(response=response)
        )

        with patch("plugins.image_gen.xai.requests.post", return_value=response):
            provider = XAIImageGenProvider()
            result = provider.generate(prompt="test")

        assert result["success"] is False
        assert result["error_type"] == "api_error"
        assert "xAI image generation failed (401): Invalid API key" in result["error"]

    def test_timeout(self):
        import requests as req_lib

        from plugins.image_gen.xai import XAIImageGenProvider

        with patch("plugins.image_gen.xai.requests.post", side_effect=req_lib.Timeout()):
            provider = XAIImageGenProvider()
            result = provider.generate(prompt="test")

        assert result["success"] is False
        assert result["error_type"] == "timeout"

    def test_empty_response(self):
        from plugins.image_gen.xai import XAIImageGenProvider

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"data": []}

        with patch("plugins.image_gen.xai.requests.post", return_value=mock_resp):
            provider = XAIImageGenProvider()
            result = provider.generate(prompt="test")

        assert result["success"] is False
        assert result["error_type"] == "empty_response"

    def test_auth_header(self):
        from plugins.image_gen.xai import XAIImageGenProvider

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "data": [{"url": "https://xai.image/test.png"}],
        }

        with patch("plugins.image_gen.xai.requests.post", return_value=mock_resp) as mock_post:
            provider = XAIImageGenProvider()
            provider.generate(prompt="test")

        call_args = mock_post.call_args
        headers = call_args.kwargs.get("headers") or call_args[1].get("headers")
        assert "Bearer test-key-12345" in headers["Authorization"]
        assert "Hermes-Agent" in headers["User-Agent"]

    def test_payload_resolution_is_literal_1k_or_2k(self):
        """Regression: xAI API rejects numeric resolutions ("1024"/"2048") with 422.

        The endpoint expects the literal strings "1k" or "2k". Ensure the wire
        payload carries that literal — not a numeric mapping. See PR #18678.
        """
        from plugins.image_gen.xai import XAIImageGenProvider

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"data": [{"url": "https://xai.image/test.png"}]}

        with patch("plugins.image_gen.xai.requests.post", return_value=mock_resp) as mock_post:
            provider = XAIImageGenProvider()
            provider.generate(prompt="test")

        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        assert payload["resolution"] in {"1k", "2k"}, (
            f"resolution must be the literal '1k' or '2k', got {payload['resolution']!r}"
        )

    def test_image_edit_rejects_bare_file_id_input(self):
        from plugins.image_gen.xai import XAIImageGenProvider

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"data": [{"url": "https://xai.image/edited.png"}]}

        with patch("plugins.image_gen.xai.requests.post", return_value=mock_resp) as mock_post, \
             patch("plugins.image_gen.xai.save_url_image", return_value="/tmp/edited.png"):
            provider = XAIImageGenProvider()
            result = provider.generate(
                prompt="make the robot red",
                image_url="file_03eb65b1-aa97-482f-9ef0-b04f9172ea00",
            )

        assert result["success"] is False
        assert result["error_type"] == "invalid_image_url"
        mock_post.assert_not_called()

    def test_image_edit_accepts_public_https_url(self):
        from plugins.image_gen.xai import XAIImageGenProvider

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"data": [{"url": "https://xai.image/edited.png"}]}

        public_url = "https://files-cdn.x.ai/token/file_abc.png"
        with patch("plugins.image_gen.xai.requests.post", return_value=mock_resp) as mock_post, \
             patch("plugins.image_gen.xai.save_url_image", return_value="/tmp/edited.png"):
            provider = XAIImageGenProvider()
            result = provider.generate(
                prompt="make the robot red",
                image_url=public_url,
            )

        assert result["success"] is True
        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        assert payload["image"] == {"url": public_url, "type": "image_url"}

    def test_multi_image_edit_rejects_bare_file_id_inputs(self):
        from plugins.image_gen.xai import XAIImageGenProvider

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"data": [{"url": "https://xai.image/edited.png"}]}

        with patch("plugins.image_gen.xai.requests.post", return_value=mock_resp) as mock_post, \
             patch("plugins.image_gen.xai.save_url_image", return_value="/tmp/edited.png"):
            provider = XAIImageGenProvider()
            result = provider.generate(
                prompt="combine these robots into one product shot",
                image_url="file_03eb65b1-aa97-482f-9ef0-b04f9172ea00",
                reference_image_urls=[
                    "file_54b48d6d-28ad-4982-9d72-bd3ac677c9bc",
                    "file_aa11bb22-cc33-44dd-88ee-ff0011223344",
                ],
            )

        assert result["success"] is False
        assert result["error_type"] == "invalid_image_url"
        mock_post.assert_not_called()

    def test_multi_image_edit_rejects_more_than_three_sources(self):
        from plugins.image_gen.xai import XAIImageGenProvider

        provider = XAIImageGenProvider()
        result = provider.generate(
            prompt="combine too many references",
            image_url="file_1",
            reference_image_urls=["file_2", "file_3", "file_4"],
        )

        assert result["success"] is False
        assert result["error_type"] == "too_many_references"

    def test_storage_options_are_sent_by_default(self):
        from plugins.image_gen.xai import XAIImageGenProvider

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"data": [{"b64_json": "dGVzdA=="}]}

        with patch("plugins.image_gen.xai.requests.post", return_value=mock_resp) as mock_post, \
             patch("plugins.image_gen.xai.save_b64_image", return_value="/tmp/test.png"):
            provider = XAIImageGenProvider()
            provider.generate(prompt="test")

        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        assert payload["storage_options"]["public_url"] is True
        assert "expires_after" not in payload["storage_options"]
        assert payload["storage_options"]["filename"].endswith(".png")

    def test_public_url_file_output_is_cached_and_preserved(self, tmp_path):
        from plugins.image_gen.xai import XAIImageGenProvider

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "data": [{
                "url": "https://imgen.x.ai/xai-tmp-imgen-test.jpeg",
                "file_output": {
                    "file_id": "file-123",
                    "filename": "stored.png",
                    "public_url": "https://xai-files.example/stored.png",
                    "public_url_expires_at": 1234567890,
                },
            }],
        }

        cached_path = tmp_path / "xai_grok-imagine-image_20260708_014800_deadbeef.png"
        with patch("plugins.image_gen.xai.requests.post", return_value=mock_resp), \
             patch(
                 "plugins.image_gen.xai.save_url_image",
                 return_value=cached_path,
             ) as mock_save_url:
            provider = XAIImageGenProvider()
            result = provider.generate(prompt="A cat playing piano")

        assert result["success"] is True
        assert result["image"] == str(cached_path)
        assert result["public_url"] == "https://xai-files.example/stored.png"
        assert "file_id" not in result
        mock_save_url.assert_called_once_with(
            "https://xai-files.example/stored.png",
            prefix="xai_grok-imagine-image",
        )

    def test_public_url_cache_failure_does_not_return_bare_url(self):
        from plugins.image_gen.xai import XAIImageGenProvider

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {
                    "file_output": {
                        "public_url": "http://127.0.0.1/internal.png",
                    }
                }
            ]
        }

        with patch("plugins.image_gen.xai.requests.post", return_value=mock_resp), \
             patch(
                 "plugins.image_gen.xai.save_url_image",
                 side_effect=ValueError("unsafe image URL"),
             ):
            result = XAIImageGenProvider().generate(prompt="A cat")

        assert result["success"] is False
        assert result["error_type"] == "io_error"
        assert result["image"] is None
        assert "127.0.0.1" not in str(result)


# ---------------------------------------------------------------------------
# Registration test
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_register(self):
        from plugins.image_gen.xai import XAIImageGenProvider, register

        mock_ctx = MagicMock()
        register(mock_ctx)
        mock_ctx.register_image_gen_provider.assert_called_once()
        provider = mock_ctx.register_image_gen_provider.call_args[0][0]
        assert isinstance(provider, XAIImageGenProvider)
        assert provider.name == "xai"


def test_xai_image_field_expands_user_home(tmp_path, monkeypatch):
    """A ~-prefixed local image path must load (expanduser), not raise io_error.

    Pre-flight validation uses ``Path(source).expanduser()`` so a ``~/...`` path
    passes; ``_xai_image_field`` must expand it too or the load fails spuriously.
    """
    from plugins.image_gen.xai import _xai_image_field

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    img = tmp_path / "pic.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")

    field = _xai_image_field("~/pic.png")
    assert field["type"] == "image_url"
    assert field["url"].startswith("data:image/png;base64,")


class TestXAIImageFieldReadGuard:
    """#57698: local image inputs must not read Hermes credential stores."""

    def test_xai_image_field_blocks_credential_store(self, tmp_path, monkeypatch):
        from plugins.image_gen.xai import _xai_image_field

        hermes_home = tmp_path / ".hermes"
        hermes_home.mkdir()
        auth_json = hermes_home / "auth.json"
        auth_json.write_text('{"api_key":"sk-secret"}', encoding="utf-8")
        monkeypatch.setenv("HERMES_HOME", str(hermes_home))

        with pytest.raises(ValueError, match="credential store"):
            _xai_image_field(str(auth_json))

    def test_xai_image_field_never_opens_blocked_credential(self, tmp_path, monkeypatch):
        """Guard fires before open() — credential store never read into memory."""
        import builtins

        from plugins.image_gen.xai import _xai_image_field

        hermes_home = tmp_path / ".hermes"
        hermes_home.mkdir()
        auth_json = hermes_home / "auth.json"
        auth_json.write_text('{"api_key":"sk-secret"}', encoding="utf-8")
        monkeypatch.setenv("HERMES_HOME", str(hermes_home))

        real_open = builtins.open
        opened: list = []

        def _spy_open(file, *a, **k):
            opened.append(str(file))
            return real_open(file, *a, **k)

        monkeypatch.setattr(builtins, "open", _spy_open)
        with pytest.raises(ValueError, match="credential store"):
            _xai_image_field(str(auth_json))
        assert str(auth_json) not in opened, "blocked credential must never be opened"

    def test_xai_image_field_passthrough_url_not_blocked(self, monkeypatch):
        """Negative control: remote URLs and data: URIs pass through unguarded."""
        from plugins.image_gen.xai import _xai_image_field

        assert _xai_image_field("https://example.com/pic.png")["url"] == "https://example.com/pic.png"
        assert _xai_image_field("data:image/png;base64,eHl6")["url"].startswith("data:image/png")
