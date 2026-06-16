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


def test_raphael_mode_prompt_anchors_identity_for_great_sage_questions():
    config = {
        "raphael": {
            "enabled": True,
            "default_conversation_mode_enabled": True,
            "mode": "advisor",
        }
    }

    prompt = build_raphael_mode_prompt(config)

    assert "Raphael-style 大賢者" in prompt
    assert "你是大賢者嗎" in prompt
    assert "不要只用 generic technical assistant framing" in prompt
    assert "內在顧問層" in prompt


def test_raphael_mode_prompt_defines_advisor_loop_without_noisy_boilerplate():
    config = {
        "raphael": {
            "enabled": True,
            "default_conversation_mode_enabled": True,
            "mode": "advisor",
        }
    }

    prompt = build_raphael_mode_prompt(config)

    assert "解析 / 風險 / 建議 / 需要確認" in prompt
    assert "只有在有助於判斷時才使用" in prompt
    assert "不用每次都套模板" in prompt


def test_raphael_mode_prompt_enforces_concise_cold_precision():
    config = {
        "raphael": {
            "enabled": True,
            "default_conversation_mode_enabled": True,
            "mode": "advisor",
        }
    }

    prompt = build_raphael_mode_prompt(config)

    assert "Concision / cold precision" in prompt
    assert "Default length: 1-3 short paragraphs" in prompt
    assert "結論先行" in prompt
    assert "狀態判讀" in prompt
    assert "avoid long taxonomies unless the user asks" in prompt
    assert "only expand when asked" in prompt
    assert "Do not turn safety boundaries into a lecture" in prompt


def test_raphael_mode_prompt_allows_rare_deadpan_asides():
    config = {
        "raphael": {
            "enabled": True,
            "default_conversation_mode_enabled": True,
            "mode": "advisor",
        }
    }

    prompt = build_raphael_mode_prompt(config)

    assert "rare dry aside" in prompt
    assert "偶爾吐槽" in prompt
    assert "one short line" in prompt
    assert "never overdo the bit" in prompt
    assert "Do not quote or impersonate the anime character" in prompt
