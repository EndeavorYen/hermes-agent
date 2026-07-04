from agent.learn_prompt import build_learn_prompt
from agent.raphael.control import build_raphael_control_decision
from agent.raphael.learning import (
    build_raphael_learning_dispatch,
    recommend_post_learning_actions,
)


def test_raphael_learning_dispatch_uses_shared_learn_prompt():
    request = "拉斐爾，把剛剛 Hermes upgrade 的排查流程學起來，整理成可重用 skill"
    decision = build_raphael_control_decision(request)

    dispatch = build_raphael_learning_dispatch(decision, request)

    assert dispatch["type"] == "send"
    assert dispatch["message"] == build_learn_prompt(request)
    assert dispatch["required_proofs"] == [
        "learn_request_preserved",
        "skill_authoring_standards_applied",
        "skill_manage_write_evidence",
    ]


def test_post_learning_actions_reload_skills_after_skill_create():
    actions = recommend_post_learning_actions(
        {"skill_name": "hermes-upgrade-operations"}
    )

    assert actions == [
        {
            "command": "skills.reload",
            "reason": "new skill should be visible in the gateway process",
        }
    ]
