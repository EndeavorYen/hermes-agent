from __future__ import annotations

import json
import logging
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

    def test_handle_image_generate_forwards_reproducible_generation_tunables(self, monkeypatch):
        from tools import image_generation_tool
        from hermes_cli import plugins as plugins_module
        from agent import image_gen_registry as registry_module

        captured = {}

        class TunableProvider(_FakeCodexProvider):
            def generate(self, prompt, aspect_ratio="landscape", **kwargs):
                captured.update(kwargs)
                result = super().generate(prompt, aspect_ratio, **kwargs)
                result["seed"] = kwargs.get("seed")
                result["num_inference_steps"] = kwargs.get("num_inference_steps")
                result["guidance_scale"] = kwargs.get("guidance_scale")
                return result

        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: "codex")
        monkeypatch.setattr(plugins_module, "_ensure_plugins_discovered", lambda: None)
        monkeypatch.setattr(registry_module, "get_provider", lambda name: TunableProvider())
        monkeypatch.setattr(
            image_generation_tool,
            "_read_image_prompt_preprocessor_config",
            lambda: {"enabled": False},
            raising=False,
        )

        result = image_generation_tool._handle_image_generate({
            "prompt": "remote zimage benchmark",
            "aspect_ratio": "square",
            "seed": 12345,
            "num_inference_steps": 9,
            "guidance_scale": 0.0,
        })
        payload = json.loads(result)

        assert payload["success"] is True
        assert captured["seed"] == 12345
        assert captured["num_inference_steps"] == 9
        assert captured["guidance_scale"] == 0.0

    def test_handle_image_generate_uses_configured_prompt_preprocessor(self, monkeypatch):
        from tools import image_generation_tool
        from hermes_cli import plugins as plugins_module
        from agent import image_gen_registry as registry_module

        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: "codex")
        monkeypatch.setattr(plugins_module, "_ensure_plugins_discovered", lambda: None)
        monkeypatch.setattr(registry_module, "get_provider", lambda name: _FakeCodexProvider())
        monkeypatch.setattr(
            image_generation_tool,
            "_read_image_prompt_preprocessor_config",
            lambda: {"enabled": True, "model": "qwen36-image-prompt"},
            raising=False,
        )
        monkeypatch.setattr(
            image_generation_tool,
            "_call_image_prompt_preprocessor",
            lambda prompt, config: "qwen polished prompt",
            raising=False,
        )

        result = image_generation_tool._handle_image_generate({
            "prompt": "rough user concept",
            "aspect_ratio": "portrait",
        })
        payload = json.loads(result)

        assert payload["success"] is True
        assert payload["prompt"] == "qwen polished prompt"

    def test_handle_image_generate_uses_adaptive_mediator_when_enabled(self, monkeypatch):
        from tools import image_generation_tool
        from hermes_cli import plugins as plugins_module
        from agent import image_gen_registry as registry_module

        def should_not_call_legacy_preprocessor(prompt, config):
            raise AssertionError("adaptive mediator owns qwen drafting when enabled")

        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: "codex")
        monkeypatch.setattr(plugins_module, "_ensure_plugins_discovered", lambda: None)
        monkeypatch.setattr(registry_module, "get_provider", lambda name: _FakeCodexProvider())
        monkeypatch.setattr(
            image_generation_tool,
            "_read_image2_adaptive_mediator_config",
            lambda: {"enabled": True, "memory_path": ""},
            raising=False,
        )
        monkeypatch.setattr(
            image_generation_tool,
            "_read_image_prompt_preprocessor_config",
            lambda: {"enabled": True, "model": "qwen36-image-prompt"},
            raising=False,
        )
        monkeypatch.setattr(
            image_generation_tool,
            "_call_image_prompt_preprocessor",
            should_not_call_legacy_preprocessor,
            raising=False,
        )
        monkeypatch.setattr(
            image_generation_tool,
            "_mediate_image2_prompt",
            lambda prompt, **kwargs: type("Mediated", (), {
                "final_prompt": "mediated final prompt",
                "strategy": "hybrid_refine",
                "to_public_dict": lambda self: {"strategy": "hybrid_refine"},
            })(),
            raising=False,
        )
        monkeypatch.setattr(
            image_generation_tool,
            "_record_image2_mediator_attempt",
            lambda *args, **kwargs: None,
            raising=False,
        )

        result = image_generation_tool._handle_image_generate({
            "prompt": "rough user concept",
            "aspect_ratio": "portrait",
        })
        payload = json.loads(result)

        assert payload["success"] is True
        assert payload["prompt"] == "mediated final prompt"
        assert payload["adaptive_mediator"] == {"strategy": "hybrid_refine"}

    def test_handle_image_generate_can_skip_preprocessor_for_mission_prompts(self, monkeypatch):
        from tools import image_generation_tool
        from hermes_cli import plugins as plugins_module
        from agent import image_gen_registry as registry_module

        def should_not_preprocess(prompt, config):
            raise AssertionError("mission prompt should not be preprocessed again")

        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: "codex")
        monkeypatch.setattr(plugins_module, "_ensure_plugins_discovered", lambda: None)
        monkeypatch.setattr(registry_module, "get_provider", lambda name: _FakeCodexProvider())
        monkeypatch.setattr(
            image_generation_tool,
            "_read_image_prompt_preprocessor_config",
            lambda: {"enabled": True, "model": "qwen36-image-prompt"},
            raising=False,
        )
        monkeypatch.setattr(
            image_generation_tool,
            "_call_image_prompt_preprocessor",
            should_not_preprocess,
            raising=False,
        )

        result = image_generation_tool._handle_image_generate({
            "prompt": "Create a polished Image2 result.\n\nUser intent anchors: exact product on white.",
            "aspect_ratio": "portrait",
            "skip_prompt_preprocessor": True,
        })
        payload = json.loads(result)

        assert payload["success"] is True
        assert payload["prompt"].startswith("Create a polished Image2 result")
        assert "User intent anchors: exact product on white" in payload["prompt"]

    def test_handle_image_generate_falls_back_when_preprocessor_unavailable(self, monkeypatch):
        from tools import image_generation_tool
        from hermes_cli import plugins as plugins_module
        from agent import image_gen_registry as registry_module

        calls = []

        def unavailable(prompt, config):
            calls.append(prompt)
            raise TimeoutError("local qwen is offline")

        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: "codex")
        monkeypatch.setattr(plugins_module, "_ensure_plugins_discovered", lambda: None)
        monkeypatch.setattr(registry_module, "get_provider", lambda name: _FakeCodexProvider())
        monkeypatch.setattr(
            image_generation_tool,
            "_read_image_prompt_preprocessor_config",
            lambda: {"enabled": True, "model": "qwen36-image-prompt"},
            raising=False,
        )
        monkeypatch.setattr(
            image_generation_tool,
            "_call_image_prompt_preprocessor",
            unavailable,
            raising=False,
        )

        result = image_generation_tool._handle_image_generate({
            "prompt": "rough user concept",
            "aspect_ratio": "portrait",
        })
        payload = json.loads(result)

        assert calls == ["rough user concept"]
        assert payload["success"] is True
        assert payload["prompt"] == "rough user concept"

    def test_prompt_preprocessor_success_is_logged(self, monkeypatch, caplog):
        from tools import image_generation_tool

        monkeypatch.setattr(
            image_generation_tool,
            "_read_image_prompt_preprocessor_config",
            lambda: {"enabled": True, "model": "qwen36-image-prompt"},
            raising=False,
        )
        monkeypatch.setattr(
            image_generation_tool,
            "_call_image_prompt_preprocessor",
            lambda prompt, config: "qwen polished prompt",
            raising=False,
        )

        with caplog.at_level(logging.INFO, logger="tools.image_generation_tool"):
            result = image_generation_tool._maybe_preprocess_image_prompt("rough user concept")

        assert result == "qwen polished prompt"
        assert "Image prompt preprocessor applied via qwen36-image-prompt" in caplog.text

    def test_adaptive_mediator_requests_qwen_json_schema(self, monkeypatch):
        from tools import image_generation_tool

        captured = {}
        qwen_json = json.dumps({
            "schema_version": "qwen_image_prompt_draft.v1",
            "candidates": [{
                "candidate_id": "q1",
                "positive_prompt": (
                    "A fashion editorial scene holding black lisianthus flowers, "
                    "also known as eustoma."
                ),
                "style_tags": [],
                "lighting": [],
                "camera": [],
                "invented_elements": [],
                "risky_or_counterproductive_terms": [],
                "constraint_preservation_report": [{
                    "lock_id": "flower",
                    "expected": "black lisianthus flowers, also known as eustoma",
                    "status": "preserved",
                    "evidence": "uses black lisianthus/eustoma",
                }],
            }],
        })

        monkeypatch.setattr(
            image_generation_tool,
            "_read_image2_adaptive_mediator_config",
            lambda: {"enabled": True, "memory_path": ""},
            raising=False,
        )
        monkeypatch.setattr(
            image_generation_tool,
            "_read_image_prompt_preprocessor_config",
            lambda: {"enabled": True, "model": "qwen36-image-prompt"},
            raising=False,
        )

        def fake_qwen_content(content, config):
            captured["content"] = content
            return qwen_json

        monkeypatch.setattr(
            image_generation_tool,
            "_call_image_prompt_preprocessor_content",
            fake_qwen_content,
            raising=False,
        )

        final_prompt, mediated, _config = image_generation_tool._maybe_mediate_image2_prompt(
            "手拿黑色洋桔梗，成熟時尚雜誌感"
        )

        assert '"schema_version": "qwen_image_prompt_draft.v1"' in captured["content"]
        assert "black lisianthus flowers, also known as eustoma" in captured["content"]
        assert mediated.qwen_validation_status == "accepted"
        assert mediated.qwen_candidate_id == "q1"
        assert "black lisianthus flowers, also known as eustoma" in final_prompt

    def test_adaptive_mediator_records_successful_qwen_call_health(self, monkeypatch):
        from tools import image_generation_tool

        recorded = {}
        qwen_json = json.dumps({
            "schema_version": "qwen_image_prompt_draft.v1",
            "candidates": [{
                "candidate_id": "q1",
                "positive_prompt": "A fashion editorial scene with black lisianthus flowers, also known as eustoma.",
                "style_tags": [],
                "lighting": [],
                "camera": [],
                "invented_elements": [],
                "risky_or_counterproductive_terms": [],
                "constraint_preservation_report": [{
                    "lock_id": "flower",
                    "expected": "black lisianthus flowers, also known as eustoma",
                    "status": "preserved",
                    "evidence": "uses black lisianthus/eustoma",
                }],
            }],
        })

        monkeypatch.setattr(
            image_generation_tool,
            "_read_image2_adaptive_mediator_config",
            lambda: {"enabled": True, "memory_path": "/tmp/adaptive.jsonl", "log_attempts": True},
            raising=False,
        )
        monkeypatch.setattr(
            image_generation_tool,
            "_read_image_prompt_preprocessor_config",
            lambda: {
                "enabled": True,
                "model": "qwen36-image-prompt",
                "base_url": "http://192.168.50.178:11434/v1",
                "transport": "curl",
            },
            raising=False,
        )
        monkeypatch.setattr(
            image_generation_tool,
            "_call_image_prompt_preprocessor_content",
            lambda content, config: qwen_json,
            raising=False,
        )
        monkeypatch.setattr(
            image_generation_tool,
            "_record_qwen_call_health",
            lambda **kwargs: recorded.update(kwargs),
            raising=False,
        )

        _final_prompt, mediated, _config = image_generation_tool._maybe_mediate_image2_prompt(
            "手拿黑色洋桔梗，成熟時尚雜誌感"
        )

        assert mediated.qwen_validation_status == "accepted"
        assert recorded["status"] == "accepted"
        assert recorded["model"] == "qwen36-image-prompt"
        assert recorded["base_url"] == "http://192.168.50.178:11434/v1"
        assert recorded["transport"] == "curl"
        assert recorded["response_chars"] == len(qwen_json)
        assert recorded["config"]["memory_path"] == "/tmp/adaptive.jsonl"

    def test_adaptive_mediator_records_failed_qwen_call_and_falls_back(self, monkeypatch):
        from tools import image_generation_tool

        recorded = {}

        monkeypatch.setattr(
            image_generation_tool,
            "_read_image2_adaptive_mediator_config",
            lambda: {"enabled": True, "memory_path": "/tmp/adaptive.jsonl", "log_attempts": True},
            raising=False,
        )
        monkeypatch.setattr(
            image_generation_tool,
            "_read_image_prompt_preprocessor_config",
            lambda: {
                "enabled": True,
                "model": "qwen36-image-prompt",
                "base_url": "http://192.168.50.178:11434/v1",
                "transport": "curl",
            },
            raising=False,
        )

        def failing_qwen(content, config):
            raise RuntimeError("No route to host")

        monkeypatch.setattr(
            image_generation_tool,
            "_call_image_prompt_preprocessor_content",
            failing_qwen,
            raising=False,
        )
        monkeypatch.setattr(
            image_generation_tool,
            "_record_qwen_call_health",
            lambda **kwargs: recorded.update(kwargs),
            raising=False,
        )

        final_prompt, mediated, _config = image_generation_tool._maybe_mediate_image2_prompt(
            "手拿黑色洋桔梗，成熟時尚雜誌感"
        )

        assert mediated.qwen_validation_status == "unavailable"
        assert recorded["status"] == "offline"
        assert recorded["error_type"] == "connection_failed"
        assert "No route to host" in recorded["error_message"]
        assert "black lisianthus flowers, also known as eustoma" in final_prompt


class TestPromptPreprocessorParsing:
    def test_extracts_positive_prompt_and_ignores_reasoning(self):
        from tools import image_generation_tool

        response = {
            "choices": [{
                "message": {
                    "content": (
                        "[Positive Prompt]\n"
                        "A polished editorial image prompt.\n\n"
                        "[Negative Prompt]\n"
                        "bad hands, watermark"
                    ),
                    "reasoning": "Do not leak this into the image generator.",
                },
            }],
        }

        assert (
            image_generation_tool._extract_prompt_preprocessor_prompt(response)
            == "A polished editorial image prompt."
        )

    def test_returns_none_for_malformed_preprocessor_response(self):
        from tools import image_generation_tool

        response = {
            "choices": [{
                "message": {
                    "content": "A paragraph without the required section marker.",
                    "reasoning": "irrelevant",
                },
            }],
        }

        assert image_generation_tool._extract_prompt_preprocessor_prompt(response) is None

    def test_curl_transport_honors_source_interface(self, monkeypatch):
        from tools import image_generation_tool
        import subprocess as subprocess_module

        captured = {}

        class Result:
            returncode = 0
            stdout = b'{"choices":[{"message":{"content":"[Positive Prompt]\\nA"}}]}'
            stderr = b""

        def fake_run(cmd, *, input, capture_output, timeout, check):
            captured["cmd"] = cmd
            captured["input"] = input
            captured["timeout"] = timeout
            return Result()

        monkeypatch.setattr(subprocess_module, "run", fake_run)

        response = image_generation_tool._post_image_prompt_preprocessor_request(
            {
                "base_url": "http://192.168.50.178:11434/v1",
                "api_key": "ollama",
                "timeout_seconds": 6,
                "transport": "curl",
                "source_interface": "en1",
            },
            {"model": "qwen36-image-prompt"},
        )

        assert response["choices"][0]["message"]["content"] == "[Positive Prompt]\nA"
        assert captured["cmd"][:3] == ["/usr/bin/curl", "--interface", "en1"]
        assert captured["timeout"] == 8.0
