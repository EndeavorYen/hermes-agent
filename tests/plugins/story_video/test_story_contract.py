from plugins.story_video.story_contract import validate_story_engine


def _ledger(**overrides):
    ledger = {
        "quality_contract_version": 4,
        "audience_profile": {
            "age_band": "school_age",
            "minimum_age_years": 5,
            "knowledge_level": "newcomer",
            "attention_style": "curious_explorer",
            "safety_intensity": "gentle",
        },
        "story_engine": {
            "audience_promise": "把艱深知識變成一場孩子想追到底的發現",
            "opening_question": "如果恐龍不是突然出現，第一隻恐龍到底躲在哪裡？",
            "dramatic_question": "弱小的早期恐龍，怎麼在巨獸旁邊活下來？",
            "curiosity_gap": "先看腳印與骨頭，再逐步拼出答案",
            "escalation": [
                "先發現一枚不尋常腳印",
                "再看見競爭者與惡劣環境",
                "最後揭曉敏捷身體帶來的優勢",
            ],
            "knowledge_payoff": "恐龍的興起不是魔法，而是身體特徵與環境共同作用",
            "ending_echo": "原來，改變世界的第一步，可能只是一枚小腳印。",
            "humor_strategy": "用輕巧比喻與一次溫和反差，不拿角色受苦開玩笑",
        },
        "scenes": [
            {"scene_id": "S00", "narrative_role": "hook", "shots": []},
            {"scene_id": "S01", "narrative_role": "context", "shots": []},
            {"scene_id": "S02", "narrative_role": "turn", "shots": []},
            {"scene_id": "S03", "narrative_role": "payoff", "shots": []},
            {"scene_id": "S04", "narrative_role": "close", "shots": []},
        ],
    }
    ledger.update(overrides)
    return ledger


def test_v4_story_engine_requires_child_curiosity_and_dramatic_payoff() -> None:
    ledger = _ledger()
    ledger.pop("story_engine")

    report = validate_story_engine(ledger)

    assert report.ok is False
    assert "story_engine" in report.violations


def test_story_engine_rejects_flat_arc_without_turn_payoff_or_close() -> None:
    ledger = _ledger(
        scenes=[
            {"scene_id": "S00", "narrative_role": "context", "shots": []},
            {"scene_id": "S01", "narrative_role": "evidence", "shots": []},
        ]
    )

    report = validate_story_engine(ledger)

    assert "story_arc.missing_role:hook" in report.violations
    assert "story_arc.missing_role:turn" in report.violations
    assert "story_arc.missing_role:payoff" in report.violations
    assert "story_arc.missing_role:close" in report.violations


def test_story_engine_requires_three_step_escalation_and_age_floor() -> None:
    ledger = _ledger()
    ledger["story_engine"]["escalation"] = ["只有一個平鋪直述的說明"]
    ledger["audience_profile"].pop("minimum_age_years")

    report = validate_story_engine(ledger)

    assert "story_engine.escalation" in report.violations
    assert "audience_profile.minimum_age_years" in report.violations

    underage = _ledger()
    underage["audience_profile"]["minimum_age_years"] = 4

    assert (
        "audience_profile.minimum_age_years"
        in validate_story_engine(underage).violations
    )


def test_complete_child_story_engine_passes() -> None:
    report = validate_story_engine(_ledger())

    assert report.ok is True
    assert report.metrics["arc_roles"] == ["close", "context", "hook", "payoff", "turn"]
