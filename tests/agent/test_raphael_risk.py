import pytest

from agent.raphael.models import RiskLevel
from agent.raphael.risk import classify_action


@pytest.mark.parametrize(
    ("action_type", "expected"),
    [
        (" read-status ", RiskLevel.R0),
        ("LIST_OBSERVATIONS", RiskLevel.R0),
        ("write_raphael_state", RiskLevel.R1),
        (" append-audit-event ", RiskLevel.R1),
        ("create_skill_proposal", RiskLevel.R1_5),
        ("CREATE-TOOL-SPEC", RiskLevel.R1_5),
        ("skill_create", RiskLevel.R2),
        ("skill_patch", RiskLevel.R2),
        ("skill_delete", RiskLevel.R2),
        ("skill_bundle_create", RiskLevel.R2),
        ("tool_draft_write", RiskLevel.R2),
        ("write_file", RiskLevel.R2),
        ("modify_cron", RiskLevel.R2),
        ("send_public_message", RiskLevel.R2),
        ("install_tool", RiskLevel.R2),
        ("bypass_approval", RiskLevel.R3),
        ("permission_change", RiskLevel.R3),
        ("expose_secret", RiskLevel.R3),
        ("silent_tool_install", RiskLevel.R3),
        ("self_replicating_cron", RiskLevel.R3),
    ],
)
def test_classify_action_maps_known_action_types(action_type, expected):
    assert classify_action(action_type) is expected


def test_classify_action_defaults_unknown_actions_to_r2():
    assert classify_action("rebalance_portfolio") is RiskLevel.R2
