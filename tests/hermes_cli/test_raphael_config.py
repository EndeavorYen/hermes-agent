from unittest.mock import patch

from hermes_cli.config import DEFAULT_CONFIG, _KNOWN_ROOT_KEYS, load_config


def test_raphael_defaults_disabled_and_guarded():
    raphael = DEFAULT_CONFIG["raphael"]

    assert raphael["enabled"] is False
    assert raphael["mode"] == "advisor"
    assert raphael["status_card_ttl_seconds"] == 900
    assert raphael["max_status_cards"] == 20
    assert raphael["public_delivery_enabled"] is False
    assert raphael["skill_writes_enabled"] is False
    assert raphael["cron_mutation_enabled"] is False
    assert raphael["memory_writes_enabled"] is False
    assert raphael["tool_install_enabled"] is False


def test_raphael_skill_trace_defaults_enabled_and_bounded():
    skill_trace = DEFAULT_CONFIG["raphael"]["skill_trace"]

    assert skill_trace == {
        "enabled": True,
        "max_summary_rows": 20,
        "max_trace_events": 500,
    }


def test_load_config_deep_merges_raphael_defaults(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "raphael:\n"
        "  enabled: true\n",
        encoding="utf-8",
    )

    with patch.dict("os.environ", {"HERMES_HOME": str(tmp_path)}):
        config = load_config()

    assert config["raphael"]["enabled"] is True
    assert config["raphael"]["mode"] == "advisor"
    assert config["raphael"]["status_card_ttl_seconds"] == 900
    assert config["raphael"]["public_delivery_enabled"] is False


def test_load_config_deep_merges_raphael_skill_trace_defaults(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "raphael:\n"
        "  skill_trace:\n"
        "    max_summary_rows: 5\n",
        encoding="utf-8",
    )

    with patch.dict("os.environ", {"HERMES_HOME": str(tmp_path)}):
        config = load_config()

    assert config["raphael"]["skill_trace"]["enabled"] is True
    assert config["raphael"]["skill_trace"]["max_summary_rows"] == 5
    assert config["raphael"]["skill_trace"]["max_trace_events"] == 500


def test_raphael_is_known_root_config_key():
    assert "raphael" in _KNOWN_ROOT_KEYS
