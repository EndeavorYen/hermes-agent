from agent.raphael.config import raphael_effective_enabled, raphael_plugin_active


def test_raphael_plugin_active_requires_explicit_plugin_enablement():
    assert raphael_plugin_active({"raphael": {"enabled": True}}) is False


def test_raphael_plugin_disabled_wins_over_enabled_list():
    config = {"plugins": {"enabled": ["raphael"], "disabled": ["raphael"]}}

    assert raphael_plugin_active(config) is False


def test_raphael_effective_enabled_requires_plugin_mode_and_default_gate():
    config = {
        "plugins": {"enabled": ["raphael"], "disabled": []},
        "raphael": {
            "enabled": True,
            "default_conversation_mode_enabled": True,
            "mode": "sage_king",
        },
    }

    assert raphael_effective_enabled(config) is True
    assert (
        raphael_effective_enabled(
            {
                **config,
                "raphael": {
                    **config["raphael"],
                    "default_conversation_mode_enabled": False,
                },
            }
        )
        is False
    )
    assert (
        raphael_effective_enabled(
            {
                **config,
                "raphael": {**config["raphael"], "mode": "planner"},
            },
            require_default_conversation=False,
        )
        is False
    )


def test_raphael_evolution_gate_can_skip_default_conversation_gate():
    config = {
        "plugins": {"enabled": ["raphael"], "disabled": []},
        "raphael": {
            "enabled": True,
            "default_conversation_mode_enabled": False,
            "mode": "sage_king",
        },
    }

    assert raphael_effective_enabled(config) is False
    assert raphael_effective_enabled(config, require_default_conversation=False) is True
