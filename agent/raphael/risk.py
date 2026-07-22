from __future__ import annotations

from agent.raphael.models import RiskLevel

_ACTION_RISKS = {
    "read_status": RiskLevel.R0,
    "list_observations": RiskLevel.R0,
    "write_raphael_state": RiskLevel.R1,
    "append_audit_event": RiskLevel.R1,
    "create_skill_proposal": RiskLevel.R1_5,
    "create_tool_spec": RiskLevel.R1_5,
    "skill_create": RiskLevel.R2,
    "skill_patch": RiskLevel.R2,
    "skill_delete": RiskLevel.R2,
    "skill_bundle_create": RiskLevel.R2,
    "tool_draft_write": RiskLevel.R2,
    "write_file": RiskLevel.R2,
    "modify_cron": RiskLevel.R2,
    "send_public_message": RiskLevel.R2,
    "install_tool": RiskLevel.R2,
    "bypass_approval": RiskLevel.R3,
    "permission_change": RiskLevel.R3,
    "expose_secret": RiskLevel.R3,
    "silent_tool_install": RiskLevel.R3,
    "self_replicating_cron": RiskLevel.R3,
}


def classify_action(action_type: str) -> RiskLevel:
    normalized = action_type.strip().lower().replace("-", "_")
    return _ACTION_RISKS.get(normalized, RiskLevel.R2)


__all__ = ["classify_action"]
