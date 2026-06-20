"""Compatibility tests for Simon's local runtime config contract."""

from __future__ import annotations

from unittest.mock import patch

import yaml


def test_grok_primary_and_codex_fallback_survive_config_migration(tmp_path):
    from hermes_cli.config import DEFAULT_CONFIG, load_config, migrate_config
    from hermes_cli.fallback_config import get_fallback_chain

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "_config_version": DEFAULT_CONFIG["_config_version"],
                "model": {
                    "default": "grok-4.3",
                    "provider": "xai-oauth",
                    "base_url": "https://api.x.ai/v1",
                    "context_length": 128000,
                    "reasoning_effort": "high",
                },
                "fallback_providers": [
                    {
                        "provider": "openai-codex",
                        "model": "gpt-5.4",
                        "base_url": "https://chatgpt.com/backend-api/codex",
                    }
                ],
                "plugins": {
                    "enabled": [
                        "rtk-rewrite",
                        "image-reference-library",
                        "visual-arsenal",
                    ],
                    "disabled": [],
                },
            }
        ),
        encoding="utf-8",
    )

    with patch.dict("os.environ", {"HERMES_HOME": str(tmp_path)}):
        migrate_config(interactive=False, quiet=True)
        config = load_config()

    assert config["model"]["default"] == "grok-4.3"
    assert config["model"]["provider"] == "xai-oauth"
    assert config["model"]["base_url"] == "https://api.x.ai/v1"
    assert get_fallback_chain(config) == [
        {
            "provider": "openai-codex",
            "model": "gpt-5.4",
            "base_url": "https://chatgpt.com/backend-api/codex",
        }
    ]
    assert config["plugins"]["enabled"] == [
        "rtk-rewrite",
        "image-reference-library",
        "visual-arsenal",
    ]
