from agent.raphael.prompt import build_raphael_mode_prompt


def test_raphael_mode_prompt_disabled_by_default():
    assert build_raphael_mode_prompt({"raphael": {"enabled": True}}) == ""


def test_raphael_mode_prompt_requires_raphael_enabled():
    config = {
        "raphael": {
            "enabled": False,
            "default_conversation_mode_enabled": True,
            "mode": "advisor",
        }
    }

    assert build_raphael_mode_prompt(config) == ""


def test_raphael_mode_prompt_describes_read_only_default_contract():
    config = {
        "raphael": {
            "enabled": True,
            "default_conversation_mode_enabled": True,
            "mode": "advisor",
        }
    }

    prompt = build_raphael_mode_prompt(config)

    assert "Raphael Mode" in prompt
    assert "read-only advisor layer" in prompt
    assert "Do not create, patch, delete, install, or enable skills" in prompt
    assert "memory, cron, tools, or public delivery" in prompt
    assert "explicit user request" in prompt
