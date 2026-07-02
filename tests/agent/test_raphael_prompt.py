from agent.raphael.prompt import build_raphael_mode_prompt


def _enabled_config(mode: str = "sage_king"):
    return {
        "plugins": {"enabled": ["raphael"], "disabled": []},
        "raphael": {
            "enabled": True,
            "default_conversation_mode_enabled": True,
            "mode": mode,
        }
    }


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


def test_raphael_mode_prompt_disabled_when_plugin_is_disabled():
    config = _enabled_config()
    config["plugins"] = {"enabled": ["raphael"], "disabled": ["raphael"]}

    assert build_raphael_mode_prompt(config) == ""


def test_raphael_mode_prompt_describes_sage_king_evolution_contract():
    prompt = build_raphael_mode_prompt(_enabled_config())

    assert "Raphael Mode" in prompt
    assert "Sage King" in prompt
    assert "not a passive advisor" in prompt
    assert "proactive skill evolution" in prompt
    assert "auditable" in prompt
    assert "rollback" in prompt
    assert "memory, cron, tools, or public delivery" in prompt
    assert "explicit user request" in prompt


def test_raphael_mode_prompt_accepts_legacy_advisor_mode_as_alias():
    prompt = build_raphael_mode_prompt(_enabled_config(mode="advisor"))

    assert "Sage King" in prompt
    assert "not a passive advisor" in prompt


def test_raphael_mode_prompt_anchors_identity_for_great_sage_questions():
    prompt = build_raphael_mode_prompt(_enabled_config())

    assert "Raphael-style 大賢者" in prompt
    assert "你是大賢者嗎" in prompt
    assert "不要只用 generic technical assistant framing" in prompt
    assert "內在顧問層" in prompt


def test_raphael_mode_prompt_defines_advisor_loop_without_noisy_boilerplate():
    prompt = build_raphael_mode_prompt(_enabled_config())

    assert "解析 / 風險 / 建議 / 需要確認" in prompt
    assert "只有在有助於判斷時才使用" in prompt
    assert "不用每次都套模板" in prompt


def test_raphael_mode_prompt_enforces_concise_cold_precision():
    prompt = build_raphael_mode_prompt(_enabled_config())

    assert "Concision / cold precision" in prompt
    assert "Default length: 1-3 short paragraphs" in prompt
    assert "結論先行" in prompt
    assert "狀態判讀" in prompt
    assert "avoid long taxonomies unless the user asks" in prompt
    assert "only expand when asked" in prompt
    assert "Do not turn safety boundaries into a lecture" in prompt


def test_raphael_mode_prompt_allows_rare_deadpan_asides():
    prompt = build_raphael_mode_prompt(_enabled_config())

    assert "rare dry aside" in prompt
    assert "偶爾吐槽" in prompt
    assert "one short line" in prompt
    assert "never overdo the bit" in prompt
    assert "Do not quote or impersonate the anime character" in prompt


def test_raphael_mode_prompt_defines_response_governor_mvp():
    prompt = build_raphael_mode_prompt(_enabled_config())

    assert "Response Governor MVP" in prompt
    assert "Before final answer, run an internal response governor" in prompt
    assert "狀態 / 風險 / 下一步" in prompt
    assert "max 6 lines" in prompt
    assert "Compress first; expand only when the user asks" in prompt


def test_raphael_mode_prompt_forbids_public_internal_orchestration_labels():
    prompt = build_raphael_mode_prompt(_enabled_config())

    assert "Do not expose internal orchestration labels" in prompt
    assert "call_visual_agent_generate" in prompt
    assert "visual_generation_requested" in prompt
    assert "chosen_route" in prompt
    assert "natural user-facing language" in prompt


def test_raphael_mode_prompt_does_not_auto_generate_visual_status_card():
    prompt = build_raphael_mode_prompt(_enabled_config())

    assert "Static visual status card" in prompt
    assert "RPG status portrait" in prompt
    assert "Do not auto-generate" in prompt
    assert "Raphael auto status portrait output is currently disabled" in prompt
    assert "textual status read" in prompt
    assert "does not disable explicit user-requested image generation" in prompt
    assert "conversation-evolved appearance" in prompt
    assert "Do not depict copyrighted character designs" in prompt


def test_raphael_mode_prompt_defines_original_cool_anime_girl_visual_persona():
    prompt = build_raphael_mode_prompt(_enabled_config())

    assert "adult anime-style cool beautiful girl" in prompt
    assert "do not copy any named anime character" in prompt
    assert "avoid exact costume, color layout, hairstyle, or accessory matches" in prompt
