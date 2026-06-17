"""Tests for the bundled ``openai-codex`` image_gen plugin.

Mirrors ``test_openai_provider.py`` but targets the standalone
Codex/ChatGPT-OAuth-backed provider that uses the Responses
``image_generation`` tool path instead of the ``images.generate`` REST
endpoint.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import httpx
import pytest

# The plugin directory uses a hyphen, which is not a valid Python identifier
# for the dotted-import form. Load it via importlib so tests don't need to
# touch sys.path or rename the directory.
codex_plugin = importlib.import_module("plugins.image_gen.openai-codex")


# 1×1 transparent PNG — valid bytes for save_b64_image()
_PNG_HEX = (
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c6300010000000500010d0a2db40000000049454e44"
    "ae426082"
)


def _b64_png() -> str:
    import base64
    return base64.b64encode(bytes.fromhex(_PNG_HEX)).decode()


@pytest.fixture(autouse=True)
def _tmp_hermes_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    yield tmp_path


@pytest.fixture
def provider(monkeypatch):
    # Codex plugin is API-key-independent; clear it to make the test honest.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return codex_plugin.OpenAICodexImageGenProvider()


# ── Metadata ────────────────────────────────────────────────────────────────


class TestMetadata:
    def test_name(self, provider):
        assert provider.name == "openai-codex"

    def test_display_name(self, provider):
        assert provider.display_name == "OpenAI (Codex auth)"

    def test_default_model(self, provider):
        assert provider.default_model() == "gpt-image-2-medium"

    def test_list_models_three_tiers(self, provider):
        ids = [m["id"] for m in provider.list_models()]
        assert ids == ["gpt-image-2-low", "gpt-image-2-medium", "gpt-image-2-high"]

    def test_setup_schema_has_no_required_env_vars(self, provider):
        schema = provider.get_setup_schema()
        assert schema["env_vars"] == []
        assert schema["badge"] == "free"


# ── Availability ────────────────────────────────────────────────────────────


class TestAvailability:
    def test_unavailable_without_codex_token(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setattr(codex_plugin, "_read_codex_access_token", lambda: None)
        assert codex_plugin.OpenAICodexImageGenProvider().is_available() is False

    def test_available_with_codex_token(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setattr(codex_plugin, "_read_codex_access_token", lambda: "codex-token")
        assert codex_plugin.OpenAICodexImageGenProvider().is_available() is True

    def test_openai_api_key_alone_is_not_enough(self, monkeypatch):
        # Codex plugin is intentionally orthogonal to the API-key plugin —
        # the API key alone must NOT make it appear available.
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setattr(codex_plugin, "_read_codex_access_token", lambda: None)
        assert codex_plugin.OpenAICodexImageGenProvider().is_available() is False


# ── Generate ────────────────────────────────────────────────────────────────


class TestGenerate:
    def test_returns_auth_error_without_codex_token(self, provider, monkeypatch):
        monkeypatch.setattr(codex_plugin, "_read_codex_access_token", lambda: None)
        result = provider.generate("a cat")
        assert result["success"] is False
        assert result["error_type"] == "auth_required"

    def test_direct_generate_blocked_when_zimage_remote_is_active(self, provider, monkeypatch):
        monkeypatch.setattr(codex_plugin, "_load_image_gen_config", lambda: {"provider": "zimage_remote"})
        monkeypatch.setattr(
            codex_plugin,
            "_read_codex_access_token",
            lambda: (_ for _ in ()).throw(AssertionError("auth should not be read")),
        )

        result = provider.generate("a cat")

        assert result["success"] is False
        assert result["error_type"] == "provider_disabled"
        assert "zimage_remote" in result["error"]

    def test_direct_generate_override_allows_codex_when_zimage_remote_is_active(self, provider, monkeypatch):
        monkeypatch.setenv("OPENAI_CODEX_IMAGE_ALLOW_WHEN_ZIMAGE_ACTIVE", "1")
        monkeypatch.setattr(codex_plugin, "_load_image_gen_config", lambda: {"provider": "zimage_remote"})
        monkeypatch.setattr(codex_plugin, "_read_codex_access_token", lambda: "codex-token")
        monkeypatch.setattr(codex_plugin, "_collect_image_b64", lambda *a, **kw: _b64_png())

        result = provider.generate("a cat")

        assert result["success"] is True
        assert result["provider"] == "openai-codex"

    def test_returns_invalid_argument_for_empty_prompt(self, provider, monkeypatch):
        monkeypatch.setattr(codex_plugin, "_read_codex_access_token", lambda: "codex-token")
        result = provider.generate("   ")
        assert result["success"] is False
        assert result["error_type"] == "invalid_argument"

    def test_generate_uses_codex_stream_path(self, provider, monkeypatch, tmp_path):
        monkeypatch.setattr(codex_plugin, "_read_codex_access_token", lambda: "codex-token")
        monkeypatch.setattr(codex_plugin, "_collect_image_b64", lambda *a, **kw: _b64_png())

        result = provider.generate("a cat", aspect_ratio="landscape")

        assert result["success"] is True
        assert result["model"] == "gpt-image-2-medium"
        assert result["provider"] == "openai-codex"
        assert result["quality"] == "medium"

        saved = Path(result["image"])
        assert saved.exists()
        assert saved.parent == tmp_path / "cache" / "images"
        # Filename prefix differs from the API-key plugin so cache audits can
        # tell the two backends apart.
        assert saved.name.startswith("openai_codex_")

    def test_generate_classifies_policy_refusal_for_prompt_rewrite(self, provider, monkeypatch):
        monkeypatch.setattr(codex_plugin, "_read_codex_access_token", lambda: "codex-token")

        def blocked(*args, **kwargs):
            request = httpx.Request("POST", "https://chatgpt.com/backend-api/codex/responses")
            response = httpx.Response(
                400,
                request=request,
                content=json.dumps({
                    "error": {
                        "message": "Request was rejected by the safety policy.",
                    },
                }).encode("utf-8"),
            )
            raise httpx.HTTPStatusError("bad request", request=request, response=response)

        monkeypatch.setattr(codex_plugin, "_collect_image_b64", blocked)

        result = provider.generate("glamorous beach portrait")

        assert result["success"] is False
        assert result["error_type"] == "policy_refusal"
        assert result["rewrite_prompt"] is True
        assert result["retryable"] is False

    def test_generate_classifies_wrapped_http_policy_refusal_for_prompt_rewrite(self, provider, monkeypatch):
        monkeypatch.setattr(codex_plugin, "_read_codex_access_token", lambda: "codex-token")

        def blocked(*args, **kwargs):
            request = httpx.Request("POST", "https://chatgpt.com/backend-api/codex/responses")
            response = httpx.Response(
                400,
                request=request,
                content=json.dumps({
                    "error": {
                        "message": "Request was rejected by the safety policy.",
                    },
                }).encode("utf-8"),
            )
            exc = httpx.HTTPStatusError("bad request", request=request, response=response)
            raise RuntimeError(
                "Codex Responses API returned HTTP 400: "
                '{"error":{"message":"Request was rejected by the safety policy."}}'
            ) from exc

        monkeypatch.setattr(codex_plugin, "_collect_image_b64", blocked)

        result = provider.generate("glamorous beach portrait")

        assert result["success"] is False
        assert result["error_type"] == "policy_refusal"
        assert result["rewrite_prompt"] is True
        assert result["retryable"] is False

    def test_generate_classifies_wrapped_http_rate_limit(self, provider, monkeypatch):
        monkeypatch.setattr(codex_plugin, "_read_codex_access_token", lambda: "codex-token")

        def rate_limited(*args, **kwargs):
            request = httpx.Request("POST", "https://chatgpt.com/backend-api/codex/responses")
            response = httpx.Response(
                429,
                request=request,
                headers={"retry-after": "30"},
                content=b"rate limit exceeded",
            )
            exc = httpx.HTTPStatusError("rate limited", request=request, response=response)
            raise RuntimeError("Codex Responses API returned HTTP 429: rate limit exceeded") from exc

        monkeypatch.setattr(codex_plugin, "_collect_image_b64", rate_limited)

        result = provider.generate("a cat")

        assert result["success"] is False
        assert result["error_type"] == "rate_limit"
        assert result["retryable"] is False
        assert result["retry_after_seconds"] == 30

    def test_generate_classifies_timeout_as_retryable(self, provider, monkeypatch):
        monkeypatch.setattr(codex_plugin, "_read_codex_access_token", lambda: "codex-token")
        monkeypatch.setattr(
            codex_plugin,
            "_collect_image_b64",
            lambda *a, **kw: (_ for _ in ()).throw(httpx.ReadTimeout("timed out")),
        )

        result = provider.generate("a cat")

        assert result["success"] is False
        assert result["error_type"] == "timeout"
        assert result["retryable"] is True

    def test_generate_classifies_transient_network_as_retryable(self, provider, monkeypatch):
        monkeypatch.setattr(codex_plugin, "_read_codex_access_token", lambda: "codex-token")

        def network_down(*args, **kwargs):
            request = httpx.Request("POST", "https://chatgpt.com/backend-api/codex/responses")
            raise httpx.ConnectError("network down", request=request)

        monkeypatch.setattr(codex_plugin, "_collect_image_b64", network_down)

        result = provider.generate("a cat")

        assert result["success"] is False
        assert result["error_type"] == "transient_network"
        assert result["retryable"] is True

    def test_generate_classifies_stream_parse_errors_as_retryable(self, provider, monkeypatch):
        monkeypatch.setattr(codex_plugin, "_read_codex_access_token", lambda: "codex-token")
        monkeypatch.setattr(
            codex_plugin,
            "_collect_image_b64",
            lambda *a, **kw: (_ for _ in ()).throw(json.JSONDecodeError("bad sse", "not-json", 0)),
        )

        result = provider.generate("a cat")

        assert result["success"] is False
        assert result["error_type"] == "stream_parse_error"
        assert result["retryable"] is True

    def test_generate_classifies_rate_limit_without_same_turn_retry(self, provider, monkeypatch):
        monkeypatch.setattr(codex_plugin, "_read_codex_access_token", lambda: "codex-token")

        def rate_limited(*args, **kwargs):
            request = httpx.Request("POST", "https://chatgpt.com/backend-api/codex/responses")
            response = httpx.Response(
                429,
                request=request,
                headers={"retry-after": "30"},
                content=b"rate limit exceeded",
            )
            raise httpx.HTTPStatusError("rate limited", request=request, response=response)

        monkeypatch.setattr(codex_plugin, "_collect_image_b64", rate_limited)

        result = provider.generate("a cat")

        assert result["success"] is False
        assert result["error_type"] == "rate_limit"
        assert result["retryable"] is False
        assert result["retry_after_seconds"] == 30

    def test_generate_classifies_bad_request_without_retry(self, provider, monkeypatch):
        monkeypatch.setattr(codex_plugin, "_read_codex_access_token", lambda: "codex-token")

        def bad_request(*args, **kwargs):
            request = httpx.Request("POST", "https://chatgpt.com/backend-api/codex/responses")
            response = httpx.Response(
                400,
                request=request,
                content=b"invalid image request",
            )
            raise httpx.HTTPStatusError("bad request", request=request, response=response)

        monkeypatch.setattr(codex_plugin, "_collect_image_b64", bad_request)

        result = provider.generate("a cat")

        assert result["success"] is False
        assert result["error_type"] == "bad_request"
        assert result["retryable"] is False
        assert "rewrite_prompt" not in result

    def test_generate_save_failure_is_image_save_error(self, provider, monkeypatch):
        monkeypatch.setattr(codex_plugin, "_read_codex_access_token", lambda: "codex-token")
        monkeypatch.setattr(codex_plugin, "_collect_image_b64", lambda *a, **kw: _b64_png())
        monkeypatch.setattr(
            codex_plugin,
            "save_b64_image",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )

        result = provider.generate("a cat")

        assert result["success"] is False
        assert result["error_type"] == "image_save_error"

    def test_codex_stream_request_shape(self, provider, monkeypatch):
        monkeypatch.setattr(codex_plugin, "_read_codex_access_token", lambda: "codex-token")

        captured = {}

        def _collect(token, *, prompt, size, quality, reference_images=None):
            captured.update(codex_plugin._build_responses_payload(
                prompt=prompt,
                size=size,
                quality=quality,
                reference_images=reference_images,
            ))
            return _b64_png()

        monkeypatch.setattr(codex_plugin, "_collect_image_b64", _collect)

        result = provider.generate("a cat", aspect_ratio="portrait")
        assert result["success"] is True

        assert captured["model"] == "gpt-5.4"
        assert captured["store"] is False
        assert captured["input"][0]["type"] == "message"
        assert captured["input"][0]["role"] == "user"
        assert captured["input"][0]["content"][0]["type"] == "input_text"
        assert captured["tool_choice"]["type"] == "allowed_tools"
        assert captured["tool_choice"]["mode"] == "required"
        assert captured["tool_choice"]["tools"] == [{"type": "image_generation"}]

        tool = captured["tools"][0]
        assert tool["type"] == "image_generation"
        assert tool["model"] == "gpt-image-2"
        assert tool["quality"] == "medium"
        assert tool["size"] == "1024x1536"
        assert tool["output_format"] == "png"
        assert tool["background"] == "opaque"
        assert tool["partial_images"] == 1

    def test_reference_inputs_are_attached_to_responses_payload(self, provider, monkeypatch):
        monkeypatch.setattr(codex_plugin, "_read_codex_access_token", lambda: "codex-token")

        captured = {}

        def _collect(token, *, prompt, size, quality, reference_images=None):
            captured["reference_images"] = reference_images
            captured["payload"] = codex_plugin._build_responses_payload(
                prompt=prompt,
                size=size,
                quality=quality,
                reference_images=reference_images,
            )
            return _b64_png()

        monkeypatch.setattr(codex_plugin, "_collect_image_b64", _collect)

        result = provider.generate(
            "keep identity",
            input_image="https://example.com/ref.png",
        )

        assert result["success"] is True
        assert captured["reference_images"] == ["https://example.com/ref.png"]
        content = captured["payload"]["input"][0]["content"]
        assert content[1] == {
            "type": "input_image",
            "image_url": "https://example.com/ref.png",
            "detail": "high",
        }
        assert result["reference_image_count"] == 1

    def test_partial_image_event_is_not_final_image(self):
        """Partial previews are not deliverable final images by themselves."""
        payload = {
            "type": "response.image_generation_call.partial_image",
            "partial_image_b64": _b64_png(),
        }
        assert codex_plugin._extract_image_b64(payload) is None

    def test_invalid_reference_path_rejected_before_generation(self, provider, monkeypatch, tmp_path):
        monkeypatch.setattr(codex_plugin, "_read_codex_access_token", lambda: "codex-token")

        def _should_not_collect(*args, **kwargs):
            raise AssertionError("generation should not start with an invalid reference image")

        monkeypatch.setattr(codex_plugin, "_collect_image_b64", _should_not_collect)

        result = provider.generate(
            "keep identity",
            input_image=str(tmp_path / "missing-reference.png"),
        )

        assert result["success"] is False
        assert result["error_type"] == "invalid_reference_image"
        assert "missing-reference.png" in result["error"]

    def test_sse_parser_handles_event_and_data_lines(self):
        class _Response:
            def iter_lines(self):
                return iter([
                    "event: response.output_item.done",
                    'data: {"item": {"type": "image_generation_call", "result": "abc"}}',
                    "",
                ])

        events = list(codex_plugin._iter_sse_json(_Response()))
        assert events == [{
            "type": "response.output_item.done",
            "item": {"type": "image_generation_call", "result": "abc"},
        }]

    def test_final_response_sweep_recovers_image(self):
        """Completed response output is found by recursive payload scanning."""
        payload = {
            "type": "response.completed",
            "response": {
                "output": [{
                    "type": "image_generation_call",
                    "status": "completed",
                    "id": "ig_final",
                    "result": _b64_png(),
                }],
            },
        }
        assert codex_plugin._extract_image_b64(payload) == _b64_png()

    def test_empty_response_returns_error(self, provider, monkeypatch):
        monkeypatch.setattr(codex_plugin, "_read_codex_access_token", lambda: "codex-token")
        monkeypatch.setattr(codex_plugin, "_collect_image_b64", lambda *a, **kw: None)

        result = provider.generate("a cat")
        assert result["success"] is False
        assert result["error_type"] == "empty_response"
        assert result["retryable"] is True

    def test_stream_exception_returns_unknown_api_error(self, provider, monkeypatch):
        monkeypatch.setattr(codex_plugin, "_read_codex_access_token", lambda: "codex-token")

        def _boom(*args, **kwargs):
            raise RuntimeError("cloudflare 403")

        monkeypatch.setattr(codex_plugin, "_collect_image_b64", _boom)

        result = provider.generate("a cat")
        assert result["success"] is False
        assert result["error_type"] == "unknown_api_error"
        assert "cloudflare 403" in result["error"]


# ── Plugin entry point ──────────────────────────────────────────────────────


class TestRegistration:
    def test_register_calls_register_image_gen_provider(self):
        registered = []

        class _Ctx:
            def register_image_gen_provider(self, prov):
                registered.append(prov)

        codex_plugin.register(_Ctx())
        assert len(registered) == 1
        assert registered[0].name == "openai-codex"
