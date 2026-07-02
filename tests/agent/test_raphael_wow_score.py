from agent.raphael.wow_score import calculate_raphael_wow_score


def test_wow_score_requires_release_ready_experience():
    score, missing = calculate_raphael_wow_score(
        {
            "summon_appraisal": True,
            "standby_summon": True,
            "mission_followup": True,
            "proof_gate": True,
            "evolution_feedback": True,
            "lifecycle_reversible": True,
            "demo_under_one_minute": True,
            "clean_output": True,
        }
    )

    assert score == 10
    assert missing == ()


def test_wow_score_requires_standby_summon_as_release_signal():
    score, missing = calculate_raphael_wow_score(
        {
            "summon_appraisal": True,
            "standby_summon": False,
            "mission_followup": True,
            "proof_gate": True,
            "evolution_feedback": True,
            "lifecycle_reversible": True,
            "demo_under_one_minute": True,
            "clean_output": True,
        }
    )

    assert score == 9
    assert missing == ("standby_summon",)


def test_wow_score_below_eight_lists_missing_release_blockers():
    score, missing = calculate_raphael_wow_score(
        {
            "summon_appraisal": True,
            "standby_summon": True,
            "mission_followup": False,
            "proof_gate": False,
            "evolution_feedback": True,
            "lifecycle_reversible": True,
            "demo_under_one_minute": True,
            "clean_output": True,
        }
    )

    assert score == 6
    assert missing == ("mission_followup", "proof_gate")
