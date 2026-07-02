def test_visual_prompt_disclosure_detects_prior_prompt_request():
    from agent.visual.prompt_disclosure import is_visual_prompt_disclosure_request

    assert is_visual_prompt_disclosure_request("請給我你使用的 prompt") is True
    assert is_visual_prompt_disclosure_request("what prompt did you use?") is True


def test_visual_prompt_disclosure_ignores_prompt_builder_request():
    from agent.visual.prompt_disclosure import is_visual_prompt_disclosure_request

    assert (
        is_visual_prompt_disclosure_request(
            "固定這位角色，替換不同的服裝與構圖，高品質，請給我 prompt 就好，不須產圖"
        )
        is False
    )


def test_visual_prompt_disclosure_ignores_plain_generation_request():
    from agent.visual.prompt_disclosure import is_visual_prompt_disclosure_request

    assert is_visual_prompt_disclosure_request("make a fashion portrait image") is False
