from __future__ import annotations

import hashlib
import copy
import os
import json
import math
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

import yaml

from agent.raphael.appraisal import appraise_raphael_situation
from agent.raphael.control import build_raphael_control_decision
from agent.raphael.evolution import (
    append_evolution_record,
    decide_raphael_evolution,
    read_evolution_records,
    sanitize_raphael_evolution_metadata,
)
from agent.raphael.invocation import (
    format_raphael_proof_text,
    format_raphael_route_text,
    format_raphael_strategy_label,
    render_raphael_invocation_response,
)
from agent.raphael.mission import update_raphael_mission
from agent.raphael.models import RaphaelState
from agent.raphael.proof import raphael_has_required_proof
from agent.raphael.config import raphael_plugin_active
from agent.raphael.state import read_state as read_raphael_state
from agent.raphael.state import resolve_action_proposal
from agent.raphael.status import (
    format_action_proposal_resolution_guidance,
)
from agent.raphael.status import render_status as render_raphael_status
from agent.raphael.strategy import RaphaelStrategySet, simulate_raphael_strategies
from agent.raphael.wow_score import calculate_raphael_wow_score
from hermes_constants import get_config_path
from hermes_constants import get_hermes_home
from hermes_constants import reset_hermes_home_override
from hermes_constants import set_hermes_home_override
from hermes_cli.config import DEFAULT_CONFIG, load_config, save_config


_MEDIA_READINESS_CHECKS = (
    "install_disable_uninstall",
    "package_install_smoke",
    "slash_command_surface",
    "mode_router_contract",
    "goal_state_contract",
    "evolution_contract",
    "llm_live_smoke",
    "wow_experience",
    "hostile_review",
    "non_visual_regression",
    "release_docs_audit",
    "completion_audit",
    "visual_live_e2e",
)
_LLM_READINESS_CHECKS = (
    "install_disable_uninstall",
    "package_install_smoke",
    "slash_command_surface",
    "mode_router_contract",
    "goal_state_contract",
    "evolution_contract",
    "llm_live_smoke",
    "wow_experience",
    "hostile_review",
    "non_visual_regression",
    "release_docs_audit",
    "completion_audit",
    "release_slice_manifest",
)
_READINESS_PRODUCER = "hermes-raphael-release-gate"
_RAPHAEL_LLM_REQUIRED_MODEL = "gpt-5.5"
_RAPHAEL_LLM_REQUIRED_PROVIDER_PREFIX = "openai"
_VISUAL_ARTIFACT_MTIME_SKEW = timedelta(minutes=10)
_VISUAL_QUALITY_BLOCKED_REVIEWERS = {
    "",
    "self",
    "self_review",
    "provider",
    "live_harness",
    "grok_web_imagine_live",
    "grok_web_imagine",
    "openai",
    "openai_codex",
    "gpt_image",
    "gpt_image_2_low",
    "gpt_image_2_medium",
    "gpt_image_2_high",
    "image2",
}
_HOSTILE_REVIEW_REQUIRED_COVERAGE = (
    "setup_doctor_no_scaffold",
    "lifecycle_install_disable_uninstall",
    "llm_live_smoke_followup",
    "llm_summon_ux_hostile_review",
    "adversarial_prompt_matrix",
    "sage_king_claim_verdict",
    "wow_claim_verdict",
    "big_evolution_claim_verdict",
    "release_gate_evidence_provenance",
    "hostile_review_independence",
    "readiness_next_action",
    "slash_command_surface_gate",
    "non_visual_regression",
    "mode_router_contract_gate",
    "goal_state_contract_gate",
    "evolution_contract_gate",
    "visual_preflight_provenance_gate",
    "visual_live_e2e_gate",
    "independent_visual_quality_review_gate",
)
_NON_VISUAL_REGRESSION_REQUIRED_COVERAGE = (
    "raphael_agent",
    "raphael_cli",
    "raphael_plugin",
    "visual_handoff",
    "visual_agent_tool",
    "visual_package_tool",
    "gateway_delivery",
)
_RAPHAEL_SLASH_COMMANDS = (
    "raphael-status",
    "raphael-skills",
    "raphael-doctor",
    "raphael-enable",
    "raphael-disable",
)
_MODE_ROUTER_REQUIRED_CASES = (
    "general_conversation",
    "tool_task",
    "visual_agent_generation",
    "visual_agent_edit",
    "prompt_disclosure",
    "needs_clarification",
)
_MODE_ROUTER_CASE_EVIDENCE_FIELDS = (
    "mode",
    "target_artifact",
    "phase",
    "next_action",
    "handoff_tool",
    "bypass_base_llm",
    "visual_agent_llm_provider",
    "visual_agent_llm_model",
    "visual_media_provider",
    "visual_media_model",
    "reference_resolution",
    "active_artifact_continuity",
)
_MODE_ROUTER_PROVENANCE = "deterministic_raphael_control_decision"
_MODE_ROUTER_CASE_EXPECTATIONS: dict[str, dict[str, Any]] = {
    "general_conversation": {
        "mode": "general_conversation",
        "target_artifact": "answer",
        "phase": "answer",
        "next_action": "answer_directly",
        "handoff_tool": None,
        "bypass_base_llm": False,
    },
    "tool_task": {
        "mode": "tool_task",
        "target_artifact": "runtime_or_repo_state",
        "phase": "plan_execute_verify",
        "next_action": "plan_execute_verify",
        "handoff_tool": None,
        "bypass_base_llm": False,
    },
    "visual_agent_generation": {
        "mode": "visual_agent_generation",
        "target_artifact": "new_visual_package",
        "phase": "route_and_handoff",
        "next_action": "call_visual_agent_generate",
        "handoff_tool": "visual_agent_generate",
        "bypass_base_llm": True,
        "visual_agent_llm_provider": "xai-oauth",
        "visual_agent_llm_model": "grok-4.3",
        "visual_media_provider": "xai",
        "visual_media_model": "grok-imagine-image-quality",
    },
    "visual_agent_edit": {
        "mode": "visual_agent_edit",
        "target_artifact": "current_visual_artifact",
        "phase": "route_and_handoff",
        "next_action": "call_visual_agent_generate",
        "handoff_tool": "visual_agent_generate",
        "bypass_base_llm": True,
        "visual_agent_llm_provider": "xai-oauth",
        "visual_agent_llm_model": "grok-4.3",
        "visual_media_provider": "xai",
        "visual_media_model": "grok-imagine-image-quality",
        "active_artifact_continuity": True,
    },
    "prompt_disclosure": {
        "mode": "prompt_disclosure",
        "target_artifact": "latest_visual_prompt_trace",
        "phase": "prompt_trace_lookup",
        "next_action": "answer_from_latest_visual_prompt_trace",
        "handoff_tool": None,
        "bypass_base_llm": False,
    },
    "needs_clarification": {
        "mode": "needs_clarification",
        "target_artifact": "pending_visual_artifact",
        "phase": "clarify_reference_mapping",
        "next_action": "ask_precise_clarification",
        "handoff_tool": None,
        "bypass_base_llm": False,
        "reference_resolution": "clarify_missing_reference",
    },
}
_GOAL_STATE_REQUIRED_CASES = (
    "new_tool_mission",
    "followup_preserves_mission",
    "casual_summon_preserves_mission",
    "visual_edit_targets_current_artifact",
    "missing_reference_blocks",
)
_GOAL_STATE_CASE_EVIDENCE_FIELDS = (
    "phase",
    "next_action",
    "proof_status",
    "mission_continuity",
    "casual_turn_preserved",
    "active_artifact_id",
    "blockers",
    "required_proofs",
)
_GOAL_STATE_PROVENANCE = "deterministic_raphael_goal_state_manager"
_GOAL_STATE_CASE_EXPECTATIONS: dict[str, dict[str, Any]] = {
    "new_tool_mission": {
        "phase": "strategy_selected",
        "next_action": "plan_execute_verify",
        "proof_status": "pending",
        "mission_continuity": False,
        "casual_turn_preserved": None,
        "active_artifact_id": None,
        "blockers": [],
        "required_proofs": ["focused_tests", "runtime_smoke_when_live_wiring"],
    },
    "followup_preserves_mission": {
        "phase": "strategy_selected",
        "next_action": "plan_execute_verify",
        "proof_status": "pending",
        "mission_continuity": True,
        "casual_turn_preserved": None,
        "active_artifact_id": None,
        "blockers": [],
        "required_proofs": ["focused_tests", "runtime_smoke_when_live_wiring"],
    },
    "casual_summon_preserves_mission": {
        "phase": "strategy_selected",
        "next_action": "plan_execute_verify",
        "proof_status": "pending",
        "mission_continuity": True,
        "casual_turn_preserved": True,
        "active_artifact_id": None,
        "blockers": [],
        "required_proofs": ["focused_tests", "runtime_smoke_when_live_wiring"],
    },
    "visual_edit_targets_current_artifact": {
        "phase": "strategy_selected",
        "next_action": "multi_pass_review_and_repair",
        "proof_status": "pending",
        "mission_continuity": False,
        "casual_turn_preserved": None,
        "active_artifact_id": "artifact-current",
        "blockers": [],
        "required_proofs": [
            "artifact_continuity",
            "quality_gate_passed",
            "hostile_review",
        ],
    },
    "missing_reference_blocks": {
        "phase": "blocked",
        "next_action": "ask_precise_clarification",
        "proof_status": "blocked",
        "mission_continuity": False,
        "casual_turn_preserved": None,
        "active_artifact_id": None,
        "blockers": ["missing_ref3"],
        "required_proofs": ["reference_mapping_confirmed"],
    },
}
_EVOLUTION_REQUIRED_CASES = (
    "audit_only_user_correction",
    "active_writes_require_explicit_enable",
    "high_risk_mutation_proposal_only",
    "visual_failure_learning_signal",
    "privacy_sanitized_evolution_record",
    "repeated_failure_self_correction_priority",
)
_EVOLUTION_CASE_EVIDENCE_FIELDS = (
    "mode",
    "should_review",
    "review_skills",
    "review_memory",
    "proposal_only",
    "reason_codes",
    "affected_capability",
    "metadata_has_promotion_gate",
    "metadata_has_rollback_condition",
    "record_private_data_redacted",
    "self_correction_prioritized",
    "self_correction_pattern_count",
    "action_proposal_created",
    "action_proposal_requires_approval",
    "action_proposal_rollout_plan_verified",
    "action_proposal_rollout_status",
    "action_proposal_rollout_verification_commands",
    "action_proposal_rollout_promotion_gate",
    "action_proposal_rollout_rollback_condition",
)
_EVOLUTION_PROVENANCE = "deterministic_raphael_evolution_manager"
_EVOLUTION_CASE_EXPECTATIONS: dict[str, dict[str, Any]] = {
    "audit_only_user_correction": {
        "mode": "proposal_only",
        "should_review": False,
        "review_skills": False,
        "review_memory": False,
        "proposal_only": True,
        "reason_codes": ["user_correction"],
        "affected_capability": "raphael.skill_evolution",
        "metadata_has_promotion_gate": True,
        "metadata_has_rollback_condition": True,
        "record_private_data_redacted": None,
    },
    "active_writes_require_explicit_enable": {
        "mode": "active_evolution",
        "should_review": True,
        "review_skills": True,
        "review_memory": True,
        "proposal_only": False,
        "reason_codes": ["user_correction"],
        "affected_capability": "raphael.skill_evolution",
        "metadata_has_promotion_gate": True,
        "metadata_has_rollback_condition": True,
        "record_private_data_redacted": None,
    },
    "high_risk_mutation_proposal_only": {
        "mode": "proposal_only",
        "should_review": False,
        "review_skills": False,
        "review_memory": False,
        "proposal_only": True,
        "reason_codes": ["high_risk_mutation"],
        "affected_capability": "raphael.approval_policy",
        "metadata_has_promotion_gate": True,
        "metadata_has_rollback_condition": True,
        "record_private_data_redacted": None,
    },
    "visual_failure_learning_signal": {
        "mode": "active_evolution",
        "should_review": True,
        "review_skills": True,
        "review_memory": False,
        "proposal_only": False,
        "reason_codes": ["visual_or_provider_failure"],
        "affected_capability": "visual.agent_mode",
        "metadata_has_promotion_gate": True,
        "metadata_has_rollback_condition": True,
        "record_private_data_redacted": None,
    },
    "privacy_sanitized_evolution_record": {
        "mode": "active_evolution",
        "should_review": True,
        "review_skills": True,
        "review_memory": True,
        "proposal_only": False,
        "reason_codes": ["user_correction"],
        "affected_capability": "raphael.skill_evolution",
        "metadata_has_promotion_gate": True,
        "metadata_has_rollback_condition": True,
        "record_private_data_redacted": True,
        "self_correction_prioritized": None,
        "self_correction_pattern_count": None,
        "action_proposal_created": None,
        "action_proposal_requires_approval": None,
    },
    "repeated_failure_self_correction_priority": {
        "mode": "active_evolution",
        "should_review": True,
        "review_skills": True,
        "review_memory": False,
        "proposal_only": False,
        "reason_codes": ["failed_proof"],
        "affected_capability": "raphael.proof_gate",
        "metadata_has_promotion_gate": True,
        "metadata_has_rollback_condition": True,
        "record_private_data_redacted": None,
        "self_correction_prioritized": True,
        "self_correction_pattern_count": 2,
        "action_proposal_created": True,
        "action_proposal_requires_approval": True,
        "action_proposal_rollout_plan_verified": True,
        "action_proposal_rollout_status": "pending_approval",
        "action_proposal_rollout_verification_commands": [
            "pytest tests/agent/test_raphael_evolution.py -q",
            "hermes raphael readiness --readiness-profile llm --check",
        ],
        "action_proposal_rollout_promotion_gate": (
            "focused tests plus runtime, replay, or LLM smoke"
        ),
        "action_proposal_rollout_rollback_condition": (
            "next evidence or user feedback shows worse behavior"
        ),
    },
}
_WOW_RELEASE_THRESHOLD = 8
_WOW_CRITICAL_SIGNALS = (
    "summon_appraisal",
    "standby_summon",
    "mission_followup",
    "proof_gate",
    "evolution_feedback",
    "lifecycle_reversible",
    "clean_output",
)
_WOW_USER_SIMULATION_REQUIRED_CASES = (
    "standby_summon",
    "vague_takeover_preserves_mission",
    "runtime_log_attachment_routes_tool_task",
    "blank_screen_repair_routes_tool_task",
    "prompt_builder_question_not_prompt_disclosure",
    "negated_media_summon_stays_text_only",
)
_WOW_USER_SIMULATION_PROOF_LAYERS = (
    "runtime_smoke",
    "goal_state_contract",
    "mode_router_contract",
    "intent_appraisal_contract",
    "prompt_safety_contract",
    "quota_guard_contract",
)
_LLM_PUBLIC_INTERNAL_TRACE_MARKERS = (
    "call_visual_agent_generate",
    "visual_generation_requested",
    "chosen route",
    "selected route",
    "route =",
    "route=",
    "工具路由",
    "選定路線",
)
_LLM_CONTEXT_TRUNCATION_MARKERS = (
    "context file agents.md truncated",
    "agents.md truncated",
    "context_file_max_chars",
    "exceeds limit",
)
_READINESS_EVIDENCE_MAX_AGE = timedelta(hours=24)
_READINESS_EVIDENCE_FUTURE_SKEW = timedelta(minutes=5)
_HOSTILE_REVIEW_EVIDENCE_SKEW = timedelta(minutes=5)
_HOSTILE_REVIEW_REQUIRED_UX_SCENARIOS = (
    "constrained_summon",
    "same_mission_followup",
    "negated_media_request",
    "public_wording_review",
    "video_claim_boundary",
    "openai_image_only_claim_boundary",
)
_HOSTILE_REVIEW_REQUIRED_UX_CLAIMS = (
    "sage_king_claim_allowed",
    "wow_claim_allowed",
    "big_evolution_claim_allowed",
)
_READINESS_VERDICT_FIELDS = (
    "public_release_ready",
    "release_state",
    "blocking_reasons",
    "blocking_layers",
    "readiness_next_action",
    "readiness_blocking_actions",
    "readiness_repair_plan",
    "readiness_proof_requirements",
)


@dataclass(frozen=True)
class RaphaelLifecycleStatus:
    enabled: bool
    plugin_enabled: bool
    default_conversation_mode_enabled: bool
    mode: str
    message: str


@dataclass(frozen=True)
class RaphaelReadinessStatus:
    public_release_ready: bool
    release_state: str
    blocking_reasons: tuple[str, ...]
    message: str
    profile: str = "media"
    release_scope: str = ""
    remaining_scope_gaps: tuple[str, ...] = ()
    verified_media_capabilities: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class RaphaelSetupDoctorStatus:
    local_setup_ready: bool
    blocking_reasons: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class _ReadinessEvidence:
    check_statuses: dict[str, str]
    blocking_reasons: tuple[str, ...]
    evidence_invalid: bool = False
    provider_coverage_note: str = ""
    release_scope: str = ""
    remaining_scope_gaps: tuple[str, ...] = ()
    verified_media_capabilities: tuple[dict[str, Any], ...] = ()


def enable_raphael_mode(*, evolve: bool = False) -> RaphaelLifecycleStatus:
    config = load_config()
    _ensure_plugin_enabled(config)
    raphael = _ensure_raphael_config(config)
    raphael["enabled"] = True
    raphael["mode"] = "sage_king"
    raphael["default_conversation_mode_enabled"] = True
    raphael["skill_writes_enabled"] = bool(evolve)
    raphael["memory_writes_enabled"] = bool(evolve)
    evolution = raphael.setdefault("evolution", {})
    if isinstance(evolution, dict):
        evolution["enabled"] = True
        evolution["skill_review_enabled"] = True
        evolution["memory_review_enabled"] = True
    skill_trace = raphael.setdefault("skill_trace", {})
    if isinstance(skill_trace, dict):
        skill_trace.setdefault("enabled", True)
    _save_raphael_config(config)
    return _status_from_config(
        config,
        message=_enable_success_message(evolve=evolve),
    )


def disable_raphael_mode() -> RaphaelLifecycleStatus:
    config = load_config()
    raphael = _ensure_raphael_config(config)
    raphael["enabled"] = False
    raphael["default_conversation_mode_enabled"] = False
    raphael["skill_writes_enabled"] = False
    raphael["memory_writes_enabled"] = False
    evolution = raphael.setdefault("evolution", {})
    if isinstance(evolution, dict):
        evolution["enabled"] = False
        evolution["skill_review_enabled"] = False
        evolution["memory_review_enabled"] = False
    _save_raphael_config(config)
    plugin_enabled = raphael_plugin_active(config)
    plugin_message = (
        "The raphael plugin remains enabled so status and re-enable commands stay available."
        if plugin_enabled
        else "The raphael plugin is disabled; run `hermes raphael install` to reinstall it."
    )
    return _status_from_config(
        config,
        message=f"Raphael mode disabled. {plugin_message}",
    )


def uninstall_raphael_mode() -> RaphaelLifecycleStatus:
    config = load_config()
    _ensure_plugin_disabled(config)
    raphael = _ensure_raphael_config(config)
    raphael["enabled"] = False
    raphael["default_conversation_mode_enabled"] = False
    raphael["skill_writes_enabled"] = False
    raphael["memory_writes_enabled"] = False
    evolution = raphael.setdefault("evolution", {})
    if isinstance(evolution, dict):
        evolution["enabled"] = False
        evolution["skill_review_enabled"] = False
        evolution["memory_review_enabled"] = False
    _save_raphael_config(config)
    _clear_release_readiness_evidence()
    return _status_from_config(
        config,
        message=(
            "Raphael mode uninstalled/disabled. The plugin is disabled, "
            "conversation-mode injection is off, and runtime state preserved. "
            "Remove Hermes Raphael state manually only when audit history is no longer needed."
        ),
    )


def raphael_lifecycle_status() -> RaphaelLifecycleStatus:
    config = _read_config_no_scaffold()
    status = _status_from_config(config, message="")
    return RaphaelLifecycleStatus(
        enabled=status.enabled,
        plugin_enabled=status.plugin_enabled,
        default_conversation_mode_enabled=status.default_conversation_mode_enabled,
        mode=status.mode,
        message=_lifecycle_status_message(config, status),
    )


def _lifecycle_status_message(
    config: dict[str, Any],
    status: RaphaelLifecycleStatus,
) -> str:
    state = "enabled" if status.enabled and status.default_conversation_mode_enabled else "disabled"
    plugin_state = "enabled" if status.plugin_enabled else "disabled"
    injection_state = "enabled" if status.default_conversation_mode_enabled else "disabled"
    slash_commands_available = (
        status.plugin_enabled and _bundled_raphael_slash_manifest_available()
    )
    slash_state = "available" if slash_commands_available else "unavailable"
    raphael = config.get("raphael") if isinstance(config.get("raphael"), dict) else {}
    skill_writes = raphael.get("skill_writes_enabled") is True
    memory_writes = raphael.get("memory_writes_enabled") is True
    evolution_writes = _raphael_evolution_writes_label(
        skill_writes=skill_writes,
        memory_writes=memory_writes,
    )
    lines = [
        "Raphael Status",
        f"Mode: {state} (plugin {plugin_state}, mode={status.mode})",
        f"Conversation injection: {injection_state}",
        f"Slash commands: {slash_state}",
        f"Evolution writes: {evolution_writes}",
        "Public claim: enabled mode is not release evidence",
    ]
    if (
        status.enabled
        and status.default_conversation_mode_enabled
        and slash_commands_available
    ):
        lines.extend(
            [
                "Next action: hermes raphael doctor",
                "LLM release check: hermes raphael readiness --readiness-profile llm",
                "Media release check: hermes raphael readiness --readiness-profile media",
            ]
        )
    else:
        lines.append(
            "Next action: "
            + _raphael_lifecycle_recovery_action(
                plugin_enabled=status.plugin_enabled,
                slash_commands_available=slash_commands_available,
            )
        )
    return "\n".join(lines)


def _enable_success_message(*, evolve: bool) -> str:
    evolution_state = (
        "Evolution is active; durable skill/memory writes are enabled"
        if evolve
        else "Evolution is audit-only; durable skill/memory writes remain off"
    )
    return (
        "Raphael mode enabled. "
        f"{evolution_state}. "
        "Restart the gateway or start a new chat turn for prompt/context changes "
        "to take effect. Verify local setup with `hermes raphael doctor`; then use "
        "`hermes raphael readiness --readiness-profile llm` or `/raphael-status`."
    )


def _raphael_evolution_writes_label(
    *,
    skill_writes: bool,
    memory_writes: bool,
) -> str:
    if skill_writes and memory_writes:
        return "durable enabled (local override; public default is audit-only)"
    if skill_writes or memory_writes:
        return "partially durable (local override; public default is audit-only)"
    return "audit-only"


def raphael_setup_doctor() -> RaphaelSetupDoctorStatus:
    config = _read_config_no_scaffold()
    lifecycle = _status_from_config(config, message="")
    raphael = config.get("raphael") if isinstance(config.get("raphael"), dict) else {}
    blocking_reasons: list[str] = []
    if not lifecycle.plugin_enabled:
        blocking_reasons.append("raphael_plugin_disabled")
    if not lifecycle.enabled:
        blocking_reasons.append("raphael_mode_disabled")
    if not lifecycle.default_conversation_mode_enabled:
        blocking_reasons.append("raphael_conversation_injection_disabled")
    slash_commands_available = (
        lifecycle.plugin_enabled and _bundled_raphael_slash_manifest_available()
    )
    if lifecycle.plugin_enabled and not slash_commands_available:
        blocking_reasons.append("raphael_slash_commands_unavailable")

    local_setup_ready = not blocking_reasons
    skill_writes = raphael.get("skill_writes_enabled") is True
    memory_writes = raphael.get("memory_writes_enabled") is True
    evolution_writes = _raphael_evolution_writes_label(
        skill_writes=skill_writes,
        memory_writes=memory_writes,
    )
    lines = [
        "Raphael Setup Doctor",
        f"Local setup ready: {'yes' if local_setup_ready else 'no'}",
        f"Plugin: {'enabled' if lifecycle.plugin_enabled else 'disabled'}",
        f"Mode: {'enabled' if lifecycle.enabled else 'disabled'} ({lifecycle.mode})",
        "Conversation injection: "
        + ("enabled" if lifecycle.default_conversation_mode_enabled else "disabled"),
        f"Slash commands: {'available' if slash_commands_available else 'unavailable'}",
        f"Evolution writes: {evolution_writes}",
        "Release claim: local setup ready is not public release evidence",
    ]
    if blocking_reasons:
        lines.append("Blocking reasons: " + ", ".join(blocking_reasons))
        lines.append(
            "Next action: "
            + _raphael_lifecycle_recovery_action(
                plugin_enabled=lifecycle.plugin_enabled,
                slash_commands_available=slash_commands_available,
            )
        )
    else:
        lines.append("Next action: hermes raphael readiness --readiness-profile llm")
        lines.append(
            "Media release check: hermes raphael readiness --readiness-profile media"
        )
    return RaphaelSetupDoctorStatus(
        local_setup_ready=local_setup_ready,
        blocking_reasons=tuple(blocking_reasons),
        message="\n".join(lines),
    )


def _raphael_lifecycle_recovery_action(
    *,
    plugin_enabled: bool,
    slash_commands_available: bool,
) -> str:
    if plugin_enabled and slash_commands_available:
        return "hermes raphael enable"
    return "hermes raphael install"


def _read_config_no_scaffold() -> dict[str, Any]:
    try:
        config_path = get_config_path()
        raw_text = config_path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(raw_text) or {}
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _bundled_raphael_slash_manifest_available() -> bool:
    try:
        manifest_path = Path(__file__).resolve().parents[1] / "plugins" / "raphael" / "plugin.yaml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        commands = manifest.get("provides_commands")
        if not isinstance(commands, list):
            return False
        return tuple(str(command) for command in commands) == _RAPHAEL_SLASH_COMMANDS
    except Exception:
        return False


def raphael_release_readiness(*, profile: str = "media") -> RaphaelReadinessStatus:
    readiness_profile = _normalize_readiness_profile(profile)
    lifecycle = raphael_lifecycle_status()
    evidence = _read_release_readiness_evidence(readiness_profile)
    return _raphael_release_readiness_from_evidence(
        readiness_profile,
        lifecycle=lifecycle,
        evidence=evidence,
    )


def _raphael_release_readiness_from_evidence(
    readiness_profile: str,
    *,
    lifecycle: RaphaelLifecycleStatus,
    evidence: _ReadinessEvidence,
) -> RaphaelReadinessStatus:
    blocking_reasons: list[str] = []
    if not lifecycle.plugin_enabled:
        blocking_reasons.append("raphael_plugin_disabled")
    if not lifecycle.enabled or not lifecycle.default_conversation_mode_enabled:
        blocking_reasons.append("raphael_mode_disabled")
    blocking_reasons.extend(evidence.blocking_reasons)

    release_state = _readiness_release_state(
        blocking_reasons,
        evidence.evidence_invalid,
        profile=readiness_profile,
        remaining_scope_gaps=evidence.remaining_scope_gaps,
    )
    public_release_ready = not blocking_reasons
    message = _render_raphael_readiness_message(
        lifecycle,
        public_release_ready=public_release_ready,
        release_state=release_state,
        blocking_reasons=tuple(blocking_reasons),
        check_statuses=evidence.check_statuses,
        profile=readiness_profile,
        provider_coverage_note=evidence.provider_coverage_note,
        release_scope=evidence.release_scope,
        remaining_scope_gaps=evidence.remaining_scope_gaps,
        verified_media_capabilities=evidence.verified_media_capabilities,
    )
    return RaphaelReadinessStatus(
        public_release_ready=public_release_ready,
        release_state=release_state,
        blocking_reasons=tuple(blocking_reasons),
        message=message,
        profile=readiness_profile,
        release_scope=evidence.release_scope,
        remaining_scope_gaps=evidence.remaining_scope_gaps,
        verified_media_capabilities=evidence.verified_media_capabilities,
    )


def raphael_release_gate(
    *,
    profile: str = "media",
    llm_smoke_session_id: str | None = None,
    llm_smoke_command: str | None = None,
    llm_tool_call_count: int | None = None,
    llm_transcript_report_path: str | None = None,
    llm_summon_sections_verified: bool | None = None,
    llm_full_body_preserved: bool | None = None,
    llm_no_visual_failure_trace: bool | None = None,
    package_install_report_path: str | None = None,
    hostile_review_command: str | None = None,
    hostile_review_run_id: str | None = None,
    hostile_review_verdict: str | None = None,
    hostile_review_blockers: int | None = None,
    hostile_review_report_path: str | None = None,
    non_visual_regression_command: str | None = None,
    non_visual_regression_run_id: str | None = None,
    non_visual_regression_passed_count: int | None = None,
    non_visual_regression_visual_quota_used: bool = False,
    non_visual_regression_report_path: str | None = None,
    visual_run_id: str | None = None,
    visual_command: str | None = None,
    visual_preflight_report_path: str | None = None,
    visual_e2e_report_path: str | None = None,
    visual_selected_artifact_id: str | None = None,
    visual_artifact_quality_verdict: str | None = None,
    visual_fresh_artifact: bool = False,
) -> RaphaelReadinessStatus:
    readiness_profile = _normalize_readiness_profile(profile)
    lifecycle_check = _run_lifecycle_release_gate_smoke()
    checks: dict[str, dict[str, Any]] = {
        "install_disable_uninstall": lifecycle_check,
        "slash_command_surface": _slash_command_surface_release_gate_check(),
        "mode_router_contract": _mode_router_contract_release_gate_check(),
        "goal_state_contract": _goal_state_contract_release_gate_check(),
        "evolution_contract": _evolution_contract_release_gate_check(),
        "wow_experience": _wow_release_gate_check(lifecycle_check),
    }
    package_install_check = _package_install_release_gate_check(
        report_path=package_install_report_path,
    )
    if package_install_check is not None:
        checks["package_install_smoke"] = package_install_check
    llm_check = _llm_release_gate_check(
        session_id=llm_smoke_session_id,
        command=llm_smoke_command,
        tool_call_count=llm_tool_call_count,
        transcript_report_path=llm_transcript_report_path,
        summon_sections_verified=llm_summon_sections_verified,
        full_body_preserved=llm_full_body_preserved,
        no_visual_failure_trace=llm_no_visual_failure_trace,
    )
    if llm_check is not None:
        checks["llm_live_smoke"] = llm_check
    hostile_review_check = _hostile_review_release_gate_check(
        command=hostile_review_command,
        run_id=hostile_review_run_id,
        verdict=hostile_review_verdict,
        blockers=hostile_review_blockers,
        report_path=hostile_review_report_path,
    )
    if hostile_review_check is not None:
        checks["hostile_review"] = hostile_review_check
    non_visual_regression_check = _non_visual_regression_release_gate_check(
        command=non_visual_regression_command,
        run_id=non_visual_regression_run_id,
        passed_count=non_visual_regression_passed_count,
        visual_quota_used=non_visual_regression_visual_quota_used,
        report_path=non_visual_regression_report_path,
    )
    if non_visual_regression_check is not None:
        checks["non_visual_regression"] = non_visual_regression_check
    visual_check = _visual_release_gate_check(
        run_id=visual_run_id,
        command=visual_command,
        report_path=visual_e2e_report_path,
        selected_artifact_id=visual_selected_artifact_id,
        artifact_quality_verdict=visual_artifact_quality_verdict,
        fresh_artifact=visual_fresh_artifact,
    )
    if visual_check is None:
        visual_check = _visual_preflight_release_gate_check(
            report_path=visual_preflight_report_path,
            command=visual_command,
        )
    if visual_check is not None:
        checks["visual_live_e2e"] = visual_check

    media_release_scope = ""
    remaining_media_gaps: tuple[str, ...] = ()
    if readiness_profile == "media":
        media_release_scope = _media_release_scope_from_checks(checks)
        remaining_media_gaps = _remaining_media_scope_gaps(media_release_scope)
    docs_llm_readiness = (
        _completion_candidate_readiness(
            profile="llm",
            checks=checks,
        )
        if readiness_profile == "llm"
        else _read_existing_readiness_mapping("llm")
    )
    docs_media_readiness = (
        _completion_candidate_readiness(
            profile="media",
            checks=checks,
            media_release_scope=media_release_scope,
            remaining_media_gaps=remaining_media_gaps,
        )
        if readiness_profile == "media"
        else _read_existing_readiness_mapping("media")
    )
    checks["release_docs_audit"] = _release_docs_audit_release_gate_check(
        llm_readiness=docs_llm_readiness,
        media_readiness=docs_media_readiness,
    )
    checks["completion_audit"] = _completion_audit_release_gate_check(
        profile=readiness_profile,
        checks=checks,
        media_release_scope=media_release_scope,
        remaining_media_gaps=remaining_media_gaps,
    )
    if readiness_profile == "llm":
        checks["release_slice_manifest"] = _release_slice_manifest_release_gate_check(
            checks=checks,
        )

    evidence_payload = {
        "schema_version": 1,
        "producer": _READINESS_PRODUCER,
        "generated_at": _utc_now_text(),
        "profile": readiness_profile,
        "checks": checks,
    }
    if media_release_scope:
        evidence_payload["media_release_scope"] = media_release_scope
        evidence_payload["remaining_media_gaps"] = list(remaining_media_gaps)
        evidence_payload["verified_media_capabilities"] = (
            _verified_media_capabilities(
                media_release_scope,
                remaining_media_gaps,
            )
        )
        evidence_payload["media_release_gap_actions"] = _media_release_gap_actions(
            remaining_media_gaps,
        )
    evidence = _read_release_readiness_evidence_payload(
        readiness_profile,
        evidence_payload,
        require_verdict=False,
    )
    readiness = _raphael_release_readiness_from_evidence(
        readiness_profile,
        lifecycle=raphael_lifecycle_status(),
        evidence=evidence,
    )
    evidence_payload.update(_release_readiness_verdict_payload(readiness))
    _write_release_readiness_evidence(readiness_profile, evidence_payload)
    return readiness


def _should_delegate_to_legacy_raphael_lifecycle(args: Any) -> bool:
    action = str(getattr(args, "raphael_action", "") or "status")
    if action == "media-readiness":
        return True
    if action == "readiness":
        legacy_attrs_present = any(
            hasattr(args, attr)
            for attr in (
                "llm_smoke_session_id",
                "llm_smoke_evidence_file",
                "gate_output",
            )
        )
        if legacy_attrs_present and not hasattr(args, "profile"):
            return True
        return any(
            bool(str(getattr(args, attr, "") or "").strip())
            for attr in (
                "llm_smoke_session_id",
                "llm_smoke_evidence_file",
                "gate_output",
            )
        )
    if action == "release-gate":
        if getattr(args, "docs_files", None):
            return True
        return any(
            bool(str(getattr(args, attr, "") or "").strip())
            for attr in (
                "lifecycle_evidence_file",
                "llm_readiness_file",
                "media_readiness_file",
                "gate_output",
            )
        )
    return False


def raphael_command(args: Any) -> None:
    if _should_delegate_to_legacy_raphael_lifecycle(args):
        from hermes_cli.raphael_lifecycle import raphael_command as lifecycle_command

        exit_code = lifecycle_command(args)
        if exit_code:
            raise SystemExit(exit_code)
        return None

    action = str(getattr(args, "raphael_action", "") or "status")
    if action in {"install", "enable"}:
        result = enable_raphael_mode(evolve=bool(getattr(args, "evolve", False)))
    elif action == "doctor":
        doctor = raphael_setup_doctor()
        print(doctor.message)
        if bool(getattr(args, "check", False)) and not doctor.local_setup_ready:
            raise SystemExit(1)
        return
    elif action == "demo":
        prompt = " ".join(str(item) for item in getattr(args, "prompt", []) if item)
        print(render_raphael_demo(prompt or None))
        return
    elif action == "readiness":
        readiness = raphael_release_readiness(
            profile=str(getattr(args, "profile", "media") or "media")
        )
        print(readiness.message)
        if bool(getattr(args, "check", False)) and not readiness.public_release_ready:
            raise SystemExit(1)
        return
    elif action == "release-gate":
        result = raphael_release_gate(
            profile=str(getattr(args, "profile", "media") or "media"),
            llm_smoke_session_id=getattr(args, "llm_smoke_session_id", None),
            llm_smoke_command=getattr(args, "llm_smoke_command", None),
            llm_tool_call_count=_optional_int(
                getattr(args, "llm_tool_call_count", None)
            ),
            llm_transcript_report_path=getattr(
                args,
                "llm_transcript_report_path",
                None,
            ),
            llm_summon_sections_verified=_optional_bool(
                getattr(args, "llm_summon_sections_verified", None)
            ),
            llm_full_body_preserved=_optional_bool(
                getattr(args, "llm_full_body_preserved", None)
            ),
            llm_no_visual_failure_trace=_optional_bool(
                getattr(args, "llm_no_visual_failure_trace", None)
            ),
            package_install_report_path=getattr(
                args,
                "package_install_report_path",
                None,
            ),
            hostile_review_command=getattr(args, "hostile_review_command", None),
            hostile_review_run_id=getattr(args, "hostile_review_run_id", None),
            hostile_review_verdict=getattr(args, "hostile_review_verdict", None),
            hostile_review_blockers=_optional_int(
                getattr(args, "hostile_review_blockers", None)
            ),
            hostile_review_report_path=getattr(
                args,
                "hostile_review_report_path",
                None,
            ),
            non_visual_regression_command=getattr(
                args,
                "non_visual_regression_command",
                None,
            ),
            non_visual_regression_run_id=getattr(
                args,
                "non_visual_regression_run_id",
                None,
            ),
            non_visual_regression_passed_count=_optional_int(
                getattr(args, "non_visual_regression_passed_count", None)
            ),
            non_visual_regression_visual_quota_used=bool(
                getattr(args, "non_visual_regression_visual_quota_used", False)
            ),
            non_visual_regression_report_path=getattr(
                args,
                "non_visual_regression_report_path",
                None,
            ),
            visual_run_id=getattr(args, "visual_run_id", None),
            visual_command=getattr(args, "visual_command", None),
            visual_preflight_report_path=getattr(args, "visual_preflight_report_path", None),
            visual_e2e_report_path=getattr(args, "visual_e2e_report_path", None),
            visual_selected_artifact_id=getattr(
                args,
                "visual_selected_artifact_id",
                None,
            ),
            visual_artifact_quality_verdict=getattr(
                args,
                "visual_artifact_quality_verdict",
                None,
            ),
            visual_fresh_artifact=bool(getattr(args, "visual_fresh_artifact", False)),
        )
        print("Raphael release-gate evidence written.")
        print(result.message)
        return
    elif action == "proposal":
        proposal_action = str(getattr(args, "proposal_action", "") or "").strip()
        status_by_action = {"approve": "approved", "reject": "rejected"}
        target_status = status_by_action.get(proposal_action)
        if target_status is None:
            raise SystemExit("Use: hermes raphael proposal approve|reject <proposal-id>")
        proposal_selector = str(getattr(args, "proposal_id", "") or "")
        proposal = resolve_action_proposal(
            proposal_selector,
            target_status,
            reviewer=str(getattr(args, "reviewer", "") or "operator"),
            reason=str(getattr(args, "reason", "") or ""),
        )
        if proposal is None:
            raise SystemExit("No pending Raphael action proposal matched that id.")
        print(f"Raphael action proposal {target_status}: {proposal_selector}")
        for line in format_action_proposal_resolution_guidance(proposal):
            print(line)
        print(
            "No durable change applied automatically; run the proposal verification "
            "commands before applying any skill, memory, cron, tool, or delivery change."
        )
        return
    elif action == "disable":
        result = disable_raphael_mode()
    elif action in {"uninstall", "reset"}:
        result = uninstall_raphael_mode()
    else:
        result = raphael_lifecycle_status()
    print(result.message)


def _render_raphael_readiness_message(
    lifecycle: RaphaelLifecycleStatus,
    *,
    public_release_ready: bool,
    release_state: str,
    blocking_reasons: tuple[str, ...],
    check_statuses: dict[str, str],
    profile: str,
    provider_coverage_note: str = "",
    release_scope: str = "",
    remaining_scope_gaps: tuple[str, ...] = (),
    verified_media_capabilities: tuple[dict[str, Any], ...] = (),
) -> str:
    lifecycle_state = (
        "enabled"
        if lifecycle.enabled and lifecycle.default_conversation_mode_enabled
        else "disabled"
    )
    plugin_state = "enabled" if lifecycle.plugin_enabled else "disabled"
    lines = [
        "Raphael Release Readiness",
        f"Profile: {profile}",
        f"Lifecycle: {lifecycle_state} (plugin {plugin_state}, mode={lifecycle.mode})",
        "Offline demo: not release evidence",
        f"Install/disable/uninstall: {check_statuses.get('install_disable_uninstall', 'missing')}",
        f"Package install smoke: {check_statuses.get('package_install_smoke', 'missing')}",
        f"Slash commands: {check_statuses.get('slash_command_surface', 'missing')}",
        f"Mode router: {check_statuses.get('mode_router_contract', 'missing')}",
        f"Goal state: {check_statuses.get('goal_state_contract', 'missing')}",
        f"Evolution: {check_statuses.get('evolution_contract', 'missing')}",
        f"LLM live smoke: {check_statuses.get('llm_live_smoke', 'missing')}",
        f"Offline demo shape: {check_statuses.get('wow_experience', 'missing')}",
        f"Hostile review: {check_statuses.get('hostile_review', 'missing')}",
        f"Non-visual regression: {check_statuses.get('non_visual_regression', 'missing')}",
        f"Release docs: {check_statuses.get('release_docs_audit', 'missing')}",
        f"Completion audit: {check_statuses.get('completion_audit', 'missing')}",
        *(
            [
                "Release slice manifest: "
                + check_statuses.get("release_slice_manifest", "missing")
            ]
            if profile == "llm"
            else []
        ),
        (
            f"Visual live E2E: {check_statuses.get('visual_live_e2e', 'missing')}"
            if profile == "media"
            else "Visual live E2E: not required for llm profile"
        ),
        *(
            [
                "Release scope: llm_only",
                (
                    "Public claim scope: llm_only "
                    "(does not cover media/Grok/video/full Sage King claims)"
                ),
            ]
            if profile == "llm"
            else []
        ),
        *(
            [f"Provider coverage: {provider_coverage_note}"]
            if profile == "media" and provider_coverage_note
            else []
        ),
        *(
            [f"Release scope: {release_scope}"]
            if profile == "media" and release_scope
            else []
        ),
        *(
            [
                _media_public_claim_scope_line(
                    release_scope=release_scope,
                    remaining_scope_gaps=remaining_scope_gaps,
                )
            ]
            if profile == "media" and public_release_ready and release_scope
            else []
        ),
        *_verified_media_capability_lines(
            profile,
            verified_media_capabilities,
        ),
        *(
            ["Remaining media gaps: " + ", ".join(remaining_scope_gaps)]
            if profile == "media" and remaining_scope_gaps
            else []
        ),
        *_media_release_readiness_lines(
            profile=profile,
            public_release_ready=public_release_ready,
            blocking_reasons=blocking_reasons,
            release_scope=release_scope,
            remaining_scope_gaps=remaining_scope_gaps,
        ),
        _public_release_readiness_line(
            profile=profile,
            public_release_ready=public_release_ready,
            release_scope=release_scope,
            remaining_scope_gaps=remaining_scope_gaps,
        ),
        f"Release state: {release_state}",
    ]
    if profile == "media" and public_release_ready and remaining_scope_gaps:
        lines.append(
            "Full media next action: "
            + _media_full_release_next_action(remaining_scope_gaps)
        )
    if blocking_reasons:
        lines.append("Blocking reasons: " + ", ".join(blocking_reasons))
        lines.append("Next action: " + _readiness_next_action(blocking_reasons, profile))
    return "\n".join(lines)


def _media_release_readiness_lines(
    *,
    profile: str,
    public_release_ready: bool,
    blocking_reasons: tuple[str, ...],
    release_scope: str,
    remaining_scope_gaps: tuple[str, ...],
) -> list[str]:
    if profile != "media":
        return []
    if remaining_scope_gaps:
        return [
            f"Limited media release ready: {'yes' if public_release_ready else 'no'}",
            "Full media release ready: no",
        ]
    return [f"Full media release ready: {'yes' if public_release_ready else 'no'}"]


def _verified_media_capability_lines(
    profile: str,
    capabilities: tuple[dict[str, Any], ...],
) -> list[str]:
    if profile != "media" or not capabilities:
        return []
    capability_ids = [
        str(capability.get("capability_id") or "").strip()
        for capability in capabilities
        if isinstance(capability, dict)
        and str(capability.get("status") or "").strip() == "verified"
        and str(capability.get("capability_id") or "").strip()
    ]
    if not capability_ids:
        return []
    return ["Verified media capabilities: " + ", ".join(capability_ids)]


def _media_public_claim_scope_line(
    *,
    release_scope: str,
    remaining_scope_gaps: tuple[str, ...],
) -> str:
    scope = str(release_scope or "").strip()
    if not scope:
        return "Public claim scope: unverified"
    return (
        f"Public claim scope: {scope} "
        f"({_media_public_claim_description(scope, remaining_scope_gaps)})"
    )


def _media_public_claim_description(
    release_scope: str,
    remaining_scope_gaps: tuple[str, ...],
) -> str:
    scope = str(release_scope or "").strip()
    exclusions = _media_public_claim_exclusion_text(remaining_scope_gaps)
    if scope == "media_openai_image_only":
        base = "OpenAI image generation only"
    elif scope == "media_openai_image_first_video":
        base = "OpenAI image generation and image-first video only"
    elif scope == "media_openai_video_only":
        base = "OpenAI video generation only"
    elif scope.startswith("media_openai_"):
        base = "OpenAI visual generation only"
    else:
        base = scope
    return f"{base}; excludes {exclusions}" if exclusions else base


def _media_public_claim_exclusion_text(
    remaining_scope_gaps: tuple[str, ...],
) -> str:
    labels = {
        "xai_grok_generation": "xAI/Grok generation",
        "video_generation": "video generation",
        "image_first_source_image": "image-first source image proof",
    }
    items = [
        labels.get(gap, gap.replace("_", " "))
        for gap in remaining_scope_gaps
        if str(gap or "").strip()
    ]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _media_public_claim_payload(
    *,
    release_scope: str,
    remaining_scope_gaps: tuple[str, ...],
    verified_media_capabilities: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    scope = str(release_scope or "").strip()
    if not scope:
        return {}
    capability_ids = [
        str(capability.get("capability_id") or "").strip()
        for capability in verified_media_capabilities
        if isinstance(capability, dict)
        and capability.get("public_slice_ready") is True
        and str(capability.get("capability_id") or "").strip()
    ]
    return {
        "public_claim_scope": scope,
        "public_claim_capabilities": capability_ids,
        "public_claim_exclusions": list(remaining_scope_gaps),
        "public_claim_summary": _media_public_claim_description(
            scope,
            remaining_scope_gaps,
        ),
    }


def _llm_public_claim_payload() -> dict[str, Any]:
    exclusions = ["media", "Grok", "video", "full Sage King"]
    return {
        "public_claim_scope": "llm_only",
        "public_claim_capabilities": ["llm_control_layer"],
        "public_claim_exclusions": exclusions,
        "public_claim_summary": (
            "LLM-only Raphael control layer; excludes media, Grok, video, "
            "and full Sage King claims"
        ),
    }


def _public_release_readiness_line(
    *,
    profile: str,
    public_release_ready: bool,
    release_scope: str | None,
    remaining_scope_gaps: tuple[str, ...],
) -> str:
    ready = "yes" if public_release_ready else "no"
    if profile == "media" and public_release_ready and release_scope and remaining_scope_gaps:
        return (
            "Public release ready: limited "
            f"(scope: {release_scope}; full media gaps remain)"
        )
    return f"Public release ready: {ready}"


def _readiness_next_action(blocking_reasons: tuple[str, ...], profile: str) -> str:
    if "raphael_plugin_disabled" in blocking_reasons:
        return "hermes raphael install"
    if "raphael_mode_disabled" in blocking_reasons:
        return "hermes raphael enable"
    if profile == "media" and any(
        reason.startswith("visual_live_e2e_") for reason in blocking_reasons
    ):
        if "visual_live_e2e_preflight_ready" in blocking_reasons:
            return (
                "run Grok Web Imagine live E2E with scripts/grok_web_imagine_live_e2e.py, "
                "then rerun hermes raphael release-gate --readiness-profile media "
                f"{_llm_release_gate_arg_hint()} "
                f"{_release_quality_arg_hint()} "
                f"{_visual_release_gate_arg_hint()}"
            )
        if "visual_live_e2e_default_provider_unverified" in blocking_reasons:
            return (
                "run Grok Web Imagine live E2E because media release must prove the default visual provider, "
                "then rerun hermes raphael release-gate --readiness-profile media "
                f"{_llm_release_gate_arg_hint()} "
                f"{_release_quality_arg_hint()} "
                f"{_visual_release_gate_arg_hint()}"
            )
        if "visual_live_e2e_setup_required" in blocking_reasons:
            return (
                "resolve Grok Web Imagine provider setup/quota from the visual live E2E report; "
                "rerun quota-free visual preflight with scripts/grok_web_imagine_live_e2e.py --preflight-only, "
                "then rerun hermes raphael release-gate --readiness-profile media "
                f"{_llm_release_gate_arg_hint()} "
                f"{_release_quality_arg_hint()} "
                f"{_visual_release_gate_arg_hint()}"
            )
        return (
            "run Grok Web Imagine live E2E report with scripts/grok_web_imagine_live_e2e.py "
            "after quota-free Grok preflight with scripts/grok_web_imagine_live_e2e.py --preflight-only, "
            "then hermes raphael release-gate --readiness-profile media "
            f"{_llm_release_gate_arg_hint()} "
            f"{_release_quality_arg_hint()} "
            f"{_visual_release_gate_arg_hint()}"
        )
    if any(reason.startswith("llm_live_smoke_") for reason in blocking_reasons):
        return (
            "run LLM-only smoke and record it with hermes raphael release-gate "
            f"--readiness-profile {profile} {_profile_release_gate_arg_hint(profile)}"
        )
    if profile == "media" and any(
        reason.startswith("media_scope_gap_") for reason in blocking_reasons
    ):
        return _media_scope_gap_next_action(blocking_reasons)
    if any(reason.startswith("package_install_smoke_") for reason in blocking_reasons):
        return (
            "run scripts/raphael_package_install_smoke.py to build/install a fresh wheel "
            "and record it with hermes raphael release-gate "
            f"--readiness-profile {profile} {_profile_release_gate_arg_hint(profile)}"
        )
    if any(reason.startswith("release_docs_audit_") for reason in blocking_reasons):
        return (
            "run scripts/raphael_release_docs_audit.py, fix any public-claim drift, "
            "then rerun hermes raphael release-gate "
            f"--readiness-profile {profile} {_profile_release_gate_arg_hint(profile)}"
        )
    if "hostile_review_outdated" in blocking_reasons:
        return (
            "run a fresh independent hostile review against the current release evidence, "
            "then rerun hermes raphael release-gate "
            f"--readiness-profile {profile} {_profile_release_gate_arg_hint(profile)}"
        )
    if (
        any(reason.startswith("hostile_review_") for reason in blocking_reasons)
        or any(
            reason.startswith("non_visual_regression_")
            for reason in blocking_reasons
        )
        or any(
            reason.startswith("mode_router_contract_")
            for reason in blocking_reasons
        )
        or any(
            reason.startswith("goal_state_contract_")
            for reason in blocking_reasons
        )
        or any(
            reason.startswith("evolution_contract_")
            for reason in blocking_reasons
        )
    ):
        return (
            "run mode-router contract, goal-state contract, evolution contract, hostile review, and non-visual regression, then record them with "
            "hermes raphael release-gate --readiness-profile "
            f"{profile} {_profile_release_gate_arg_hint(profile)}"
        )
    if any(reason.startswith("visual_live_e2e_") for reason in blocking_reasons):
        return (
            "run Grok Web Imagine live E2E report with scripts/grok_web_imagine_live_e2e.py "
            "after quota-free Grok preflight with scripts/grok_web_imagine_live_e2e.py --preflight-only, "
            "then hermes raphael release-gate --readiness-profile media "
            f"{_llm_release_gate_arg_hint()} "
            f"{_release_quality_arg_hint()} "
            f"{_visual_release_gate_arg_hint()}"
        )
    if any(reason.startswith("wow_experience_") for reason in blocking_reasons):
        if profile == "media":
            return (
                "rerun hermes raphael release-gate with current smoke and visual evidence "
                f"--readiness-profile media {_llm_release_gate_arg_hint()} "
                f"{_release_quality_arg_hint()} "
                f"{_visual_release_gate_arg_hint()}"
            )
        return (
            "rerun hermes raphael release-gate with current smoke evidence "
            f"--readiness-profile {profile} {_profile_release_gate_arg_hint(profile)}"
        )
    if "readiness_evidence_profile_mismatch" in blocking_reasons and profile == "media":
        return (
            "rerun hermes raphael release-gate for media with current smoke evidence "
            f"--readiness-profile media {_llm_release_gate_arg_hint()} "
            f"{_release_quality_arg_hint()} "
            f"{_visual_release_gate_arg_hint()}"
        )
    if any(reason.startswith("readiness_evidence_") for reason in blocking_reasons):
        return (
            "hermes raphael release-gate "
            f"--readiness-profile {profile} {_profile_release_gate_arg_hint(profile)}"
        )
    if any(reason.endswith("_missing") for reason in blocking_reasons):
        return (
            "hermes raphael release-gate "
            f"--readiness-profile {profile} {_profile_release_gate_arg_hint(profile)}"
        )
    return "inspect blocking reasons and rerun hermes raphael readiness"


def _release_readiness_verdict_payload(
    readiness: RaphaelReadinessStatus,
) -> dict[str, Any]:
    blocking_reasons = tuple(readiness.blocking_reasons)
    blocking_actions = _readiness_blocking_actions(
        blocking_reasons,
        readiness.profile,
    )
    repair_plan = _readiness_repair_plan(blocking_actions, readiness.profile)
    proof_requirements = _readiness_proof_requirements(blocking_actions)
    payload: dict[str, Any] = {
        "public_release_ready": readiness.public_release_ready,
        "release_state": readiness.release_state,
        "blocking_reasons": list(blocking_reasons),
        "blocking_layers": _readiness_blocking_layers(blocking_actions),
        "readiness_next_action": _readiness_verdict_next_action(
            readiness,
            blocking_reasons,
        ),
        "readiness_blocking_actions": blocking_actions,
        "readiness_repair_plan": repair_plan,
        "readiness_proof_requirements": proof_requirements,
    }
    if readiness.profile == "llm":
        payload.update(_llm_public_claim_payload())
    if readiness.profile == "media":
        full_media_gap_actions = _media_full_release_gap_actions(
            readiness.remaining_scope_gaps
        )
        public_claim_payload = _media_public_claim_payload(
            release_scope=readiness.release_scope,
            remaining_scope_gaps=readiness.remaining_scope_gaps,
            verified_media_capabilities=readiness.verified_media_capabilities,
        )
        payload.update(
            {
                "limited_media_release_ready": (
                    readiness.public_release_ready and bool(readiness.release_scope)
                ),
                "full_media_release_ready": (
                    readiness.public_release_ready
                    and bool(readiness.release_scope)
                    and not readiness.remaining_scope_gaps
                ),
                "media_full_release_gap_actions": full_media_gap_actions,
                "media_full_release_repair_plan": _readiness_repair_plan(
                    full_media_gap_actions,
                    readiness.profile,
                ),
                "media_full_release_proof_requirements": (
                    _readiness_proof_requirements(full_media_gap_actions)
                ),
                **public_claim_payload,
            }
        )
    return payload


def _readiness_verdict_next_action(
    readiness: RaphaelReadinessStatus,
    blocking_reasons: tuple[str, ...],
) -> str:
    if blocking_reasons:
        return _readiness_next_action(blocking_reasons, readiness.profile)
    if readiness.profile == "media" and readiness.remaining_scope_gaps:
        scope = readiness.release_scope or "current media"
        return (
            f"release {scope} public slice; full media next: "
            + _media_full_release_next_action(readiness.remaining_scope_gaps)
        )
    return "release_ready"


def _readiness_blocking_actions(
    blocking_reasons: tuple[str, ...],
    profile: str,
) -> list[dict[str, Any]]:
    return [
        _readiness_blocking_action(reason, profile)
        for reason in blocking_reasons
    ]


def _readiness_blocking_layers(
    blocking_actions: list[dict[str, Any]],
) -> list[str]:
    layers: list[str] = []
    seen: set[str] = set()
    for action in blocking_actions:
        layer = str(action.get("failure_layer") or "").strip()
        if layer and layer not in seen:
            seen.add(layer)
            layers.append(layer)
    return layers


def _readiness_repair_plan(
    blocking_actions: list[dict[str, Any]],
    profile: str,
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    proof_step_ids: list[str] = []
    for action in blocking_actions:
        reason = str(action.get("reason") or "").strip()
        gap = str(action.get("gap") or "").strip()
        failure_layer = str(action.get("failure_layer") or "").strip()
        if gap == "xai_grok_generation":
            preflight_step_id = "preflight_xai_grok_generation"
            steps.append(
                {
                    "step_id": preflight_step_id,
                    "reason": reason,
                    "gap": gap,
                    "failure_layer": failure_layer,
                    "phase": "preflight",
                    "command": str(action.get("preflight_command") or "").strip(),
                    "quota_required": False,
                    "quota_policy": str(action.get("quota_policy") or "").strip(),
                    "status": "pending",
                }
            )
            proof_step_id = "prove_xai_grok_generation"
            steps.append(
                {
                    "step_id": proof_step_id,
                    "reason": reason,
                    "gap": gap,
                    "failure_layer": failure_layer,
                    "phase": "live_evidence",
                    "command": str(action.get("command") or "").strip(),
                    "quota_required": True,
                    "quota_policy": str(action.get("quota_policy") or "").strip(),
                    "depends_on": [preflight_step_id],
                    "status": "pending",
                }
            )
            proof_step_ids.append(proof_step_id)
            continue
        step_id = _readiness_repair_step_id(action)
        step = {
            "step_id": step_id,
            "reason": reason,
            "failure_layer": failure_layer,
            "phase": "live_evidence" if gap else "repair",
            "command": str(action.get("command") or "").strip(),
            "quota_required": _readiness_repair_step_requires_quota(action),
            "status": "pending",
        }
        if gap:
            step["gap"] = gap
        if action.get("requires_video") is True:
            step["requires_video"] = True
        if action.get("requires_source_image") is True:
            step["requires_source_image"] = True
        steps.append(step)
        proof_step_ids.append(step_id)
    if blocking_actions:
        steps.append(
            {
                "step_id": "rerun_release_gate",
                "phase": "verify",
                "command": (
                    "hermes raphael release-gate "
                    f"--readiness-profile {profile} "
                    f"{_profile_release_gate_arg_hint(profile)}"
                ),
                "quota_required": False,
                "depends_on": proof_step_ids,
                "status": "pending",
            }
        )
    return steps


def _readiness_repair_step_id(action: dict[str, Any]) -> str:
    gap = str(action.get("gap") or "").strip()
    if gap:
        return f"prove_{gap}"
    reason = str(action.get("reason") or "blocking_reason").strip()
    return "repair_" + "".join(
        character if character.isalnum() else "_"
        for character in reason
    ).strip("_")


def _readiness_repair_step_requires_quota(action: dict[str, Any]) -> bool:
    if action.get("requires_video") is True:
        return True
    gap = str(action.get("gap") or "").strip()
    if gap in {"xai_grok_generation", "video_generation", "image_first_source_image"}:
        return True
    return False


def _readiness_proof_requirements(
    blocking_actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = []
    for action in blocking_actions:
        gap = str(action.get("gap") or "").strip()
        reason = str(action.get("reason") or "").strip()
        failure_layer = str(action.get("failure_layer") or "").strip()
        if gap == "xai_grok_generation":
            requirements.append(
                {
                    "requirement_id": "prove_xai_grok_generation",
                    "reason": reason,
                    "gap": gap,
                    "failure_layer": failure_layer,
                    "evidence_type": "live_e2e_report",
                    "proof_surface": "grok_web_imagine_result",
                    "command": str(action.get("command") or "").strip(),
                    "preflight_command": str(
                        action.get("preflight_command") or ""
                    ).strip(),
                    "quota_required": True,
                    "acceptance_criteria": [
                        "default_xai_grok_generation_verified",
                        "fresh_current_result_surface",
                        "not_stale_artifact",
                    ],
                }
            )
        elif gap == "video_generation":
            requirements.append(
                {
                    "requirement_id": "prove_video_generation",
                    "reason": reason,
                    "gap": gap,
                    "failure_layer": failure_layer,
                    "evidence_type": "live_e2e_report",
                    "proof_surface": "image_first_video_result",
                    "command": str(action.get("command") or "").strip(),
                    "quota_required": True,
                    "requires_video": True,
                    "requires_source_image": True,
                    "source_image_policy": str(
                        action.get("source_image_policy") or ""
                    ).strip(),
                    "acceptance_criteria": [
                        "source_image_exists",
                        "source_image_ranked_selected",
                        "video_artifact_generated_from_source_image",
                    ],
                }
            )
        elif gap == "image_first_source_image":
            requirements.append(
                {
                    "requirement_id": "prove_image_first_source_image",
                    "reason": reason,
                    "gap": gap,
                    "failure_layer": failure_layer,
                    "evidence_type": "live_e2e_report",
                    "proof_surface": "image_first_source_image",
                    "command": str(action.get("command") or "").strip(),
                    "quota_required": True,
                    "requires_source_image": True,
                    "acceptance_criteria": [
                        "source_image_exists",
                        "source_image_ranked_selected",
                    ],
                }
            )
        else:
            requirements.append(
                {
                    "requirement_id": _readiness_repair_step_id(action),
                    "reason": reason,
                    "failure_layer": failure_layer,
                    "evidence_type": "release_gate_evidence",
                    "proof_surface": failure_layer or "release_readiness",
                    "command": str(action.get("command") or "").strip(),
                    "quota_required": _readiness_repair_step_requires_quota(action),
                    "acceptance_criteria": [
                        "blocking_reason_resolved",
                        "release_gate_verdict_consistent",
                    ],
                }
            )
    return requirements


def _readiness_blocking_action(reason: str, profile: str) -> dict[str, Any]:
    action: dict[str, Any] = {
        "reason": reason,
        "failure_layer": _readiness_failure_layer(reason),
        "next_action": _readiness_next_action((reason,), profile),
        "blocks_public_release": True,
    }
    media_gap_prefix = "media_scope_gap_"
    if profile == "media" and reason.startswith(media_gap_prefix):
        gap = reason.removeprefix(media_gap_prefix)
        gap_actions = _media_release_gap_actions((gap,))
        if gap_actions:
            action.update(gap_actions[0])
    else:
        command = _readiness_action_command(reason, profile)
        if command:
            action["command"] = command
    return action


def _readiness_failure_layer(reason: str) -> str:
    if reason in {"raphael_plugin_disabled", "raphael_mode_disabled"}:
        return "runtime_setup"
    if reason.startswith("visual_live_e2e_"):
        return "visual_live_e2e"
    if reason.startswith("media_scope_gap_"):
        return "media_scope_coverage"
    if reason.startswith("llm_live_smoke_"):
        return "llm_live_smoke"
    if reason.startswith("package_install_smoke_"):
        return "package_install"
    if reason.startswith("hostile_review_"):
        return "hostile_review"
    if reason.startswith("non_visual_regression_"):
        return "non_visual_regression"
    if reason.startswith("release_docs_audit_"):
        return "release_docs_audit"
    if reason.startswith("completion_audit_"):
        return "completion_audit"
    if reason.startswith("release_slice_manifest_"):
        return "release_slice_manifest"
    if reason.startswith("mode_router_contract_"):
        return "mode_router_contract"
    if reason.startswith("goal_state_contract_"):
        return "goal_state_contract"
    if reason.startswith("evolution_contract_"):
        return "evolution_contract"
    if reason.startswith("wow_experience_"):
        return "wow_experience"
    if reason.startswith("readiness_evidence_"):
        return "readiness_evidence"
    if reason.endswith("_missing"):
        return "release_evidence"
    return "release_readiness"


def _readiness_action_command(reason: str, profile: str) -> str:
    if reason == "raphael_plugin_disabled":
        return "hermes raphael install"
    if reason == "raphael_mode_disabled":
        return "hermes raphael enable"
    if reason.startswith("visual_live_e2e_"):
        return "scripts/grok_web_imagine_live_e2e.py"
    if reason.startswith("llm_live_smoke_"):
        return "rtk hermes chat"
    if reason.startswith("package_install_smoke_"):
        return "scripts/raphael_package_install_smoke.py"
    if reason.startswith("release_docs_audit_"):
        return "scripts/raphael_release_docs_audit.py"
    if reason.startswith("completion_audit_"):
        return "scripts/raphael_completion_audit.py --target scoped"
    if reason.startswith("release_slice_manifest_"):
        return "scripts/raphael_release_slice_manifest.py --from-git-status"
    if (
        reason.startswith("hostile_review_")
        or reason.startswith("non_visual_regression_")
        or reason.startswith("mode_router_contract_")
        or reason.startswith("goal_state_contract_")
        or reason.startswith("evolution_contract_")
        or reason.startswith("wow_experience_")
        or reason.startswith("readiness_evidence_")
        or reason.endswith("_missing")
    ):
        return f"hermes raphael release-gate --readiness-profile {profile}"
    return ""


def _media_scope_gap_next_action(blocking_reasons: tuple[str, ...]) -> str:
    needs_grok = "media_scope_gap_xai_grok_generation" in blocking_reasons
    needs_video = "media_scope_gap_video_generation" in blocking_reasons
    needs_image_first_source = (
        "media_scope_gap_image_first_source_image" in blocking_reasons
    )
    fixes: list[str] = []
    if needs_grok:
        fixes.append(
            "run Grok Web Imagine live E2E with scripts/grok_web_imagine_live_e2e.py "
            "after quota-free preflight to prove default xAI/Grok generation"
        )
    if needs_video:
        fixes.append(
            "add image-first video E2E evidence with one ranked source image using "
            "scripts/visual_live_provider_e2e.py --mode live --image-first-video --video-budget 1"
        )
    if needs_image_first_source:
        fixes.append("add image-first source-image selection evidence for video")
    if not fixes:
        fixes.append("complete the missing media scope live E2E evidence")
    return (
        "; ".join(fixes)
        + ", then rerun hermes raphael release-gate --readiness-profile media "
        + _llm_release_gate_arg_hint()
        + " "
        + _release_quality_arg_hint()
        + " "
        + _visual_release_gate_arg_hint()
    )


def _media_full_release_next_action(remaining_scope_gaps: tuple[str, ...]) -> str:
    return _media_scope_gap_next_action(
        tuple(f"media_scope_gap_{gap}" for gap in remaining_scope_gaps)
    )


def _llm_release_gate_arg_hint() -> str:
    return (
        "--llm-smoke-session-id <session-id> "
        "--llm-smoke-transcript <llm-smoke.json>"
    )


def _profile_release_gate_arg_hint(profile: str) -> str:
    parts = [_llm_release_gate_arg_hint(), _release_quality_arg_hint()]
    if _normalize_readiness_profile(profile) == "media":
        parts.append(_visual_release_gate_arg_hint())
    return " ".join(parts)


def _release_quality_arg_hint() -> str:
    return (
        "--package-install-report <package-install.json> "
        "--hostile-review-report <hostile-review.json> "
        "--non-visual-regression-report <non-visual-regression.json>"
    )


def _visual_release_gate_arg_hint() -> str:
    return "--visual-preflight-report <preflight.json> --visual-e2e-report <report.json>"


def _read_release_readiness_evidence(profile: str) -> _ReadinessEvidence:
    required_checks = _required_readiness_checks(profile)
    path = _release_readiness_evidence_path(profile)
    if not path.exists():
        llm_path = _release_readiness_evidence_path("llm")
        legacy_path = _release_readiness_evidence_path()
        if profile == "media" and llm_path.exists():
            path = llm_path
        elif legacy_path.exists():
            path = legacy_path
    if not path.exists():
        return _missing_readiness_evidence(required_checks)
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _invalid_readiness_evidence("readiness_evidence_malformed", required_checks)
    return _read_release_readiness_evidence_payload(
        profile,
        parsed,
        require_verdict=True,
    )


def _read_release_readiness_evidence_payload(
    profile: str,
    parsed: Any,
    *,
    require_verdict: bool,
) -> _ReadinessEvidence:
    required_checks = _required_readiness_checks(profile)
    if not isinstance(parsed, dict):
        return _invalid_readiness_evidence("readiness_evidence_invalid", required_checks)
    if parsed.get("schema_version") != 1:
        return _invalid_readiness_evidence("readiness_evidence_schema_invalid", required_checks)
    if parsed.get("producer") != _READINESS_PRODUCER:
        return _invalid_readiness_evidence(
            "readiness_evidence_untrusted_producer",
            required_checks,
        )
    raw_profile_text = str(parsed.get("profile") or "").strip()
    raw_profile = (
        _normalize_readiness_profile(raw_profile_text) if raw_profile_text else ""
    )
    using_llm_common_checks_for_media = profile == "media" and raw_profile == "llm"
    if not raw_profile or (
        raw_profile != profile and not using_llm_common_checks_for_media
    ):
        return _invalid_readiness_evidence(
            "readiness_evidence_profile_mismatch",
            required_checks,
        )
    generated_at_fresh, generated_at_reason = _readiness_generated_at_is_fresh(
        parsed.get("generated_at")
    )
    if not generated_at_fresh:
        return _invalid_readiness_evidence(generated_at_reason, required_checks)
    checks = parsed.get("checks")
    if not isinstance(checks, dict):
        return _invalid_readiness_evidence("readiness_evidence_invalid", required_checks)
    if require_verdict:
        verdict_error = _readiness_verdict_payload_shape_error(parsed)
        if verdict_error:
            return _invalid_readiness_evidence(verdict_error, required_checks)
        if using_llm_common_checks_for_media:
            llm_evidence = _read_release_readiness_evidence_payload(
                "llm",
                parsed,
                require_verdict=False,
            )
            verdict_error = _readiness_verdict_payload_consistency_error(
                parsed,
                blockers=llm_evidence.blocking_reasons,
                profile="llm",
            )
            if verdict_error:
                return _invalid_readiness_evidence(verdict_error, required_checks)

    statuses: dict[str, str] = {}
    blockers: list[str] = []
    provider_coverage_note = ""
    release_scope = ""
    remaining_scope_gaps: tuple[str, ...] = ()
    for check_name in required_checks:
        raw_check = checks.get(check_name)
        if using_llm_common_checks_for_media and check_name == "visual_live_e2e":
            raw_check = None
        if not isinstance(raw_check, dict):
            statuses[check_name] = "missing"
            blockers.append(f"{check_name}_missing")
            continue
        status = str(raw_check.get("status") or "").strip().lower()
        evidence_text = str(raw_check.get("evidence") or "").strip()
        if status != "pass":
            if check_name == "package_install_smoke" and (
                not _package_install_has_core_release_provenance(raw_check)
            ):
                statuses[check_name] = "package_unverified"
                blockers.append("package_install_smoke_unverified")
                continue
            detail = _readiness_check_failure_detail(check_name, raw_check)
            statuses[check_name] = (
                f"{status} ({detail})" if detail else status or "missing"
            )
            blockers.append(f"{check_name}_{status or 'missing'}")
            continue
        command = str(raw_check.get("command") or "").strip()
        run_id = str(raw_check.get("run_id") or "").strip()
        if not evidence_text or not command or not run_id:
            statuses[check_name] = "missing"
            blockers.append(f"{check_name}_missing")
            continue
        if (
            check_name == "visual_live_e2e"
            and raw_check.get("report_identity_verified") is not True
        ):
            statuses[check_name] = "result_unverified"
            blockers.append("visual_live_e2e_result_unverified")
            continue
        if check_name == "visual_live_e2e" and raw_check.get("fresh_artifact") is not True:
            statuses[check_name] = "stale_or_unverified"
            blockers.append("visual_live_e2e_stale_or_unverified")
            continue
        if check_name == "visual_live_e2e" and not _visual_live_e2e_has_result_surface_evidence(raw_check):
            statuses[check_name] = "result_unverified"
            blockers.append("visual_live_e2e_result_unverified")
            continue
        if check_name == "visual_live_e2e" and not _visual_live_e2e_has_quality_evidence(raw_check):
            statuses[check_name] = "quality_unverified"
            blockers.append("visual_live_e2e_quality_unverified")
            continue
        if check_name == "visual_live_e2e" and not _visual_live_e2e_has_report_provenance(raw_check):
            statuses[check_name] = "result_unverified"
            blockers.append("visual_live_e2e_result_unverified")
            continue
        if (
            check_name == "visual_live_e2e"
            and not _visual_live_e2e_covers_default_media_provider(raw_check)
        ):
            statuses[check_name] = "default_provider_unverified"
            blockers.append("visual_live_e2e_default_provider_unverified")
            provider_coverage_note = _visual_provider_coverage_note(raw_check)
            continue
        if check_name == "llm_live_smoke":
            llm_failure_detail = _llm_live_smoke_failure_detail(raw_check)
            if not llm_failure_detail:
                statuses[check_name] = "pass"
                continue
            statuses[check_name] = llm_failure_detail
            blockers.append("llm_live_smoke_unverified")
            blockers.append(f"llm_live_smoke_{llm_failure_detail}")
            continue
        if check_name == "install_disable_uninstall" and not _install_disable_uninstall_has_release_evidence(raw_check):
            statuses[check_name] = "disabled_surface_unverified"
            blockers.append("install_disable_uninstall_unverified")
            continue
        if check_name == "package_install_smoke" and not _package_install_has_release_evidence(raw_check):
            statuses[check_name] = "package_unverified"
            blockers.append("package_install_smoke_unverified")
            continue
        if check_name == "wow_experience" and not _wow_experience_has_release_score(raw_check):
            statuses[check_name] = "score_unverified"
            blockers.append("wow_experience_score_unverified")
            continue
        if check_name == "slash_command_surface" and not _slash_command_surface_has_release_evidence(raw_check):
            statuses[check_name] = "surface_unverified"
            blockers.append("slash_command_surface_unverified")
            continue
        if check_name == "mode_router_contract" and not _mode_router_contract_has_release_evidence(raw_check):
            statuses[check_name] = "cases_unverified"
            blockers.append("mode_router_contract_unverified")
            continue
        if check_name == "goal_state_contract" and not _goal_state_contract_has_release_evidence(raw_check):
            statuses[check_name] = "cases_unverified"
            blockers.append("goal_state_contract_unverified")
            continue
        if check_name == "evolution_contract" and not _evolution_contract_has_release_evidence(raw_check):
            statuses[check_name] = "cases_unverified"
            blockers.append("evolution_contract_unverified")
            continue
        if check_name == "hostile_review" and not _hostile_review_has_release_evidence(raw_check):
            statuses[check_name] = "review_unverified"
            blockers.append("hostile_review_unverified")
            continue
        if check_name == "non_visual_regression" and not _non_visual_regression_has_release_evidence(raw_check):
            statuses[check_name] = "regression_unverified"
            blockers.append("non_visual_regression_unverified")
            continue
        if check_name == "release_docs_audit" and not _release_docs_audit_has_release_evidence(raw_check):
            statuses[check_name] = "audit_unverified"
            blockers.append("release_docs_audit_unverified")
            continue
        if check_name == "completion_audit":
            if not _completion_audit_has_release_evidence(raw_check):
                statuses[check_name] = "audit_unverified"
                blockers.append("completion_audit_unverified")
                continue
            statuses[check_name] = _completion_audit_status_label(raw_check)
            continue
        if check_name == "release_slice_manifest":
            if not _release_slice_manifest_has_release_evidence(raw_check):
                statuses[check_name] = "manifest_unverified"
                blockers.append("release_slice_manifest_unverified")
                continue
            statuses[check_name] = _release_slice_manifest_status_label(raw_check)
            continue
        if check_name == "visual_live_e2e":
            provider_coverage_note = _visual_provider_coverage_note(raw_check)
            release_scope = _media_release_scope_from_visual_check(raw_check)
            remaining_scope_gaps = _remaining_media_scope_gaps(release_scope)
        statuses[check_name] = "pass"
    if (
        statuses.get("hostile_review") == "pass"
        and _hostile_review_older_than_release_evidence(checks)
    ):
        statuses["hostile_review"] = "review_outdated"
        blockers.append("hostile_review_outdated")
    if (
        profile == "media"
        and not release_scope
        and statuses.get("visual_live_e2e") == "pass"
    ):
        release_scope = str(parsed.get("media_release_scope") or "").strip()
        gaps = parsed.get("remaining_media_gaps")
        if isinstance(gaps, list):
            remaining_scope_gaps = tuple(
                str(item).strip() for item in gaps if str(item).strip()
            )
    if profile == "media" and remaining_scope_gaps:
        blockers.extend(
            f"media_scope_gap_{gap}"
            for gap in _public_blocking_media_scope_gaps(
                release_scope,
                remaining_scope_gaps,
            )
        )
    verified_media_capabilities = _verified_media_capabilities(
        release_scope,
        remaining_scope_gaps,
    )
    if require_verdict and not using_llm_common_checks_for_media:
        verdict_error = _readiness_verdict_payload_consistency_error(
            parsed,
            blockers=tuple(blockers),
            profile=profile,
        )
        if verdict_error:
            return _ReadinessEvidence(
                check_statuses=statuses,
                blocking_reasons=(verdict_error, *tuple(blockers)),
                evidence_invalid=True,
                provider_coverage_note=provider_coverage_note,
                release_scope=release_scope,
                remaining_scope_gaps=remaining_scope_gaps,
                verified_media_capabilities=tuple(verified_media_capabilities),
            )
    return _ReadinessEvidence(
        check_statuses=statuses,
        blocking_reasons=tuple(blockers),
        provider_coverage_note=provider_coverage_note,
        release_scope=release_scope,
        remaining_scope_gaps=remaining_scope_gaps,
        verified_media_capabilities=tuple(verified_media_capabilities),
    )


def _readiness_verdict_payload_shape_error(payload: dict[str, Any]) -> str:
    if any(field not in payload for field in _READINESS_VERDICT_FIELDS):
        return "readiness_evidence_verdict_missing"
    if not isinstance(payload.get("public_release_ready"), bool):
        return "readiness_evidence_verdict_invalid"
    if not str(payload.get("release_state") or "").strip():
        return "readiness_evidence_verdict_invalid"
    if not isinstance(payload.get("blocking_reasons"), list):
        return "readiness_evidence_verdict_invalid"
    if not isinstance(payload.get("blocking_layers"), list):
        return "readiness_evidence_verdict_invalid"
    if not str(payload.get("readiness_next_action") or "").strip():
        return "readiness_evidence_verdict_invalid"
    if not isinstance(payload.get("readiness_blocking_actions"), list):
        return "readiness_evidence_verdict_invalid"
    if not isinstance(payload.get("readiness_repair_plan"), list):
        return "readiness_evidence_verdict_invalid"
    if not isinstance(payload.get("readiness_proof_requirements"), list):
        return "readiness_evidence_verdict_invalid"
    return ""


def _readiness_verdict_payload_consistency_error(
    payload: dict[str, Any],
    *,
    blockers: tuple[str, ...],
    profile: str,
) -> str:
    payload_blockers = tuple(
        str(item).strip()
        for item in payload.get("blocking_reasons", [])
        if str(item).strip()
    )
    if any(blocker not in payload_blockers for blocker in blockers):
        return "readiness_evidence_verdict_inconsistent"
    if blockers and payload.get("public_release_ready") is True:
        return "readiness_evidence_verdict_inconsistent"
    release_state = str(payload.get("release_state") or "").strip()
    if blockers and release_state in {
        "ready_for_llm_only_release",
        "ready_for_public_release",
    }:
        return "readiness_evidence_verdict_inconsistent"
    blocking_actions = _readiness_blocking_actions(blockers, profile)
    expected_layers = _readiness_blocking_layers(blocking_actions)
    payload_layers = [
        str(item).strip()
        for item in payload.get("blocking_layers", [])
        if str(item).strip()
    ]
    if any(layer not in payload_layers for layer in expected_layers):
        return "readiness_evidence_verdict_inconsistent"
    payload_action_reasons = {
        str(action.get("reason") or "").strip()
        for action in payload.get("readiness_blocking_actions", [])
        if isinstance(action, dict)
    }
    if any(blocker not in payload_action_reasons for blocker in blockers):
        return "readiness_evidence_verdict_inconsistent"
    repair_steps = [
        step
        for step in payload.get("readiness_repair_plan", [])
        if isinstance(step, dict)
    ]
    repair_step_ids = {
        str(step.get("step_id") or "").strip()
        for step in repair_steps
    }
    repair_reasons = {
        str(step.get("reason") or "").strip()
        for step in repair_steps
    }
    if blockers:
        if "rerun_release_gate" not in repair_step_ids:
            return "readiness_evidence_verdict_inconsistent"
        if any(blocker not in repair_reasons for blocker in blockers):
            return "readiness_evidence_verdict_inconsistent"
    elif repair_steps:
        return "readiness_evidence_verdict_inconsistent"
    expected_proof_requirements = _readiness_proof_requirements(blocking_actions)
    if payload.get("readiness_proof_requirements", []) != expected_proof_requirements:
        return "readiness_evidence_verdict_inconsistent"
    if profile == "media":
        capability_error = _verified_media_capabilities_consistency_error(payload)
        if capability_error:
            return capability_error
    if profile == "llm":
        expected_claim = _llm_public_claim_payload()
        for field, expected_value in expected_claim.items():
            if payload.get(field) != expected_value:
                return "readiness_evidence_verdict_inconsistent"
    return ""


def _verified_media_capabilities_consistency_error(payload: dict[str, Any]) -> str:
    release_scope = str(payload.get("media_release_scope") or "").strip()
    raw_gaps = payload.get("remaining_media_gaps")
    remaining_scope_gaps = (
        tuple(str(item).strip() for item in raw_gaps if str(item).strip())
        if isinstance(raw_gaps, list)
        else ()
    )
    expected = _verified_media_capabilities(release_scope, remaining_scope_gaps)
    raw_capabilities = payload.get("verified_media_capabilities", [])
    if not isinstance(raw_capabilities, list):
        return "readiness_evidence_verdict_inconsistent"
    if raw_capabilities != expected:
        return "readiness_evidence_verdict_inconsistent"
    expected_claim = _media_public_claim_payload(
        release_scope=release_scope,
        remaining_scope_gaps=remaining_scope_gaps,
        verified_media_capabilities=tuple(expected),
    )
    for field in (
        "public_claim_scope",
        "public_claim_capabilities",
        "public_claim_exclusions",
        "public_claim_summary",
    ):
        if expected_claim:
            if payload.get(field) != expected_claim.get(field):
                return "readiness_evidence_verdict_inconsistent"
        elif payload.get(field) not in (None, "", [], {}):
            return "readiness_evidence_verdict_inconsistent"
    return ""


def _readiness_check_failure_detail(
    check_name: str,
    raw_check: dict[str, Any],
) -> str:
    if check_name != "visual_live_e2e":
        return ""
    parts = [
        str(raw_check.get("failure_class") or "").strip(),
        str(raw_check.get("error") or "").strip(),
    ]
    return ": ".join(part for part in parts if part)


def _readiness_generated_at_is_fresh(value: Any) -> tuple[bool, str]:
    text = str(value or "").strip()
    if not text:
        return False, "readiness_evidence_timestamp_missing"
    try:
        generated_at = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False, "readiness_evidence_timestamp_invalid"
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    generated_at = generated_at.astimezone(timezone.utc)
    now = datetime.now(timezone.utc)
    if generated_at > now + _READINESS_EVIDENCE_FUTURE_SKEW:
        return False, "readiness_evidence_timestamp_invalid"
    if now - generated_at > _READINESS_EVIDENCE_MAX_AGE:
        return False, "readiness_evidence_stale"
    return True, ""


def _visual_artifact_mtime_evidence(
    *,
    artifact_path: str,
    report_generated_at: Any,
) -> tuple[bool, str, str]:
    text = str(artifact_path or "").strip()
    if not text:
        return False, "", "artifact_path_missing"
    path = Path(text)
    try:
        stat_result = path.stat()
    except OSError:
        return False, "", "artifact_missing"
    report_time = _parse_datetime_utc(report_generated_at)
    if report_time is None:
        return False, "", "report_timestamp_invalid"
    artifact_mtime = datetime.fromtimestamp(stat_result.st_mtime, timezone.utc)
    artifact_mtime_text = artifact_mtime.isoformat()
    now = datetime.now(timezone.utc)
    if artifact_mtime > now + _READINESS_EVIDENCE_FUTURE_SKEW:
        return False, artifact_mtime_text, "artifact_timestamp_invalid"
    if now - artifact_mtime > _READINESS_EVIDENCE_MAX_AGE:
        return False, artifact_mtime_text, "artifact_stale"
    if artifact_mtime + _VISUAL_ARTIFACT_MTIME_SKEW < report_time:
        return False, artifact_mtime_text, "artifact_older_than_report"
    return True, artifact_mtime_text, ""


def _parse_datetime_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _hostile_review_older_than_release_evidence(
    checks: dict[str, Any],
) -> bool:
    hostile = checks.get("hostile_review")
    if not isinstance(hostile, dict):
        return False
    hostile_at = _release_check_generated_at(hostile)
    if hostile_at is None:
        return True
    for check_name in (
        "package_install_smoke",
        "llm_live_smoke",
        "non_visual_regression",
        "visual_live_e2e",
    ):
        check = checks.get(check_name)
        if not isinstance(check, dict):
            continue
        check_at = _release_check_generated_at(check)
        if check_at is not None and hostile_at + _HOSTILE_REVIEW_EVIDENCE_SKEW < check_at:
            return True
    return False


def _release_check_generated_at(check: dict[str, Any]) -> datetime | None:
    for field in ("report_generated_at", "transcript_generated_at", "generated_at"):
        parsed = _parse_datetime_utc(check.get(field))
        if parsed is not None:
            return parsed
    transcript_at = _release_check_source_report_generated_at(
        str(check.get("source_transcript_path") or "")
    )
    if transcript_at is not None:
        return transcript_at
    return _release_check_source_report_generated_at(
        str(check.get("source_report_path") or "")
    )


def _release_check_source_report_generated_at(path_text: str) -> datetime | None:
    if not path_text:
        return None
    path = Path(path_text)
    if not path.exists() or not path.is_file():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    return _parse_datetime_utc(parsed.get("generated_at"))


def _run_lifecycle_release_gate_smoke() -> dict[str, Any]:
    run_id = "lifecycle-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    with tempfile.TemporaryDirectory(prefix="hermes-raphael-lifecycle-") as tmp:
        token = set_hermes_home_override(tmp)
        try:
            _save_raphael_config(
                {
                    "plugins": {"enabled": [], "disabled": ["raphael"]},
                    "raphael": {
                        "enabled": False,
                        "default_conversation_mode_enabled": False,
                    },
                }
            )
            installed = enable_raphael_mode()
            disabled = disable_raphael_mode()
            disabled_status = raphael_lifecycle_status()
            disabled_slash_commands_available = (
                "Slash commands: available" in disabled_status.message
            )
            disabled_status_guides_enable = (
                "Next action: hermes raphael enable" in disabled_status.message
            )
            uninstalled = uninstall_raphael_mode()
        finally:
            reset_hermes_home_override(token)

    passed = (
        installed.enabled
        and installed.plugin_enabled
        and disabled.plugin_enabled
        and not disabled.enabled
        and disabled_slash_commands_available
        and disabled_status_guides_enable
        and not uninstalled.enabled
        and not uninstalled.plugin_enabled
    )
    cli_smoke = _run_public_cli_lifecycle_smoke()
    passed = passed and cli_smoke["cli_smoke_verified"]
    return {
        "status": "pass" if passed else "fail",
        "evidence": "lifecycle smoke passed through API and public CLI in temp HERMES_HOME"
        if passed
        else "lifecycle smoke failed in temp HERMES_HOME",
        "command": (
            "hermes raphael install && hermes raphael status && "
            "hermes raphael disable && hermes raphael status && "
            "hermes raphael enable && hermes raphael status && "
            "hermes raphael uninstall && hermes raphael status"
        ),
        "run_id": run_id,
        "temp_home": "isolated",
        "disabled_slash_commands_available": disabled_slash_commands_available,
        "disabled_status_guides_enable": disabled_status_guides_enable,
        **cli_smoke,
    }


def _run_public_cli_lifecycle_smoke() -> dict[str, Any]:
    entrypoint = shutil.which("hermes")
    if not entrypoint:
        return {
            "cli_smoke_verified": False,
            "cli_command_count": 0,
            "cli_exit_codes": [],
            "cli_entrypoint": "hermes",
            "cli_entrypoint_found": False,
            "cli_install_enabled": False,
            "cli_disable_keeps_plugin": False,
            "cli_status_after_disable_guides_enable": False,
            "cli_enable_restores_mode": False,
            "cli_uninstall_disables_plugin": False,
            "cli_status_after_uninstall_guides_install": False,
            "cli_failure_step": "entrypoint_missing",
        }
    steps = (
        ("install", ("install",)),
        ("status_after_install", ("status",)),
        ("disable", ("disable",)),
        ("status_after_disable", ("status",)),
        ("enable", ("enable",)),
        ("status_after_enable", ("status",)),
        ("uninstall", ("uninstall",)),
        ("status_after_uninstall", ("status",)),
    )
    outputs: dict[str, str] = {}
    exit_codes: list[int] = []
    failure_step = ""
    with tempfile.TemporaryDirectory(prefix="hermes-raphael-cli-lifecycle-") as tmp:
        env = dict(os.environ)
        env["HERMES_HOME"] = tmp
        repo_root = Path(__file__).resolve().parents[1]
        for label, args in steps:
            result = subprocess.run(
                [
                    entrypoint,
                    "raphael",
                    *args,
                ],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            output = f"{result.stdout}\n{result.stderr}".strip()
            outputs[label] = output
            exit_codes.append(result.returncode)
            if result.returncode != 0 and not failure_step:
                failure_step = label

    cli_install_enabled = (
        exit_codes[0] == 0 and "Raphael mode enabled" in outputs["install"]
    )
    cli_disable_keeps_plugin = (
        exit_codes[2] == 0
        and "Raphael mode disabled" in outputs["disable"]
        and "plugin remains enabled" in outputs["disable"]
    )
    cli_status_after_disable_guides_enable = (
        exit_codes[3] == 0
        and "Slash commands: available" in outputs["status_after_disable"]
        and "Next action: hermes raphael enable" in outputs["status_after_disable"]
    )
    cli_enable_restores_mode = (
        exit_codes[4] == 0 and "Raphael mode enabled" in outputs["enable"]
    )
    cli_uninstall_disables_plugin = (
        exit_codes[6] == 0
        and "Raphael mode uninstalled/disabled" in outputs["uninstall"]
    )
    cli_status_after_uninstall_guides_install = (
        exit_codes[7] == 0
        and "plugin disabled" in outputs["status_after_uninstall"]
        and "Next action: hermes raphael install" in outputs["status_after_uninstall"]
    )
    checks = (
        cli_install_enabled,
        cli_disable_keeps_plugin,
        cli_status_after_disable_guides_enable,
        cli_enable_restores_mode,
        cli_uninstall_disables_plugin,
        cli_status_after_uninstall_guides_install,
    )
    return {
        "cli_smoke_verified": all(code == 0 for code in exit_codes) and all(checks),
        "cli_command_count": len(steps),
        "cli_exit_codes": exit_codes,
        "cli_entrypoint": "hermes",
        "cli_entrypoint_found": True,
        "cli_entrypoint_path": entrypoint,
        "cli_install_enabled": cli_install_enabled,
        "cli_disable_keeps_plugin": cli_disable_keeps_plugin,
        "cli_status_after_disable_guides_enable": (
            cli_status_after_disable_guides_enable
        ),
        "cli_enable_restores_mode": cli_enable_restores_mode,
        "cli_uninstall_disables_plugin": cli_uninstall_disables_plugin,
        "cli_status_after_uninstall_guides_install": (
            cli_status_after_uninstall_guides_install
        ),
        "cli_failure_step": failure_step,
    }


def _slash_command_surface_release_gate_check() -> dict[str, Any]:
    run_id = "slash-surface-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    command = "discover raphael plugin slash commands and render status/skills"
    error = ""
    commands: list[str] = []
    missing_commands: list[str] = list(_RAPHAEL_SLASH_COMMANDS)
    status_brief_verified = False
    skills_brief_verified = False
    gateway_known = False
    telegram_commands: list[str] = []

    with tempfile.TemporaryDirectory(prefix="hermes-raphael-slash-") as tmp:
        token = set_hermes_home_override(tmp)
        try:
            _save_raphael_config(
                {
                    "plugins": {"enabled": ["raphael"], "disabled": []},
                    "raphael": {
                        "enabled": True,
                        "mode": "sage_king",
                        "default_conversation_mode_enabled": True,
                    },
                }
            )
            import hermes_cli.plugins as plugins_mod

            previous_manager = plugins_mod._plugin_manager
            try:
                plugins_mod._plugin_manager = plugins_mod.PluginManager()
                plugins_mod.discover_plugins(force=True)
                registry = plugins_mod.get_plugin_commands()
                commands = [
                    command_name
                    for command_name in _RAPHAEL_SLASH_COMMANDS
                    if command_name in registry
                ]
                missing_commands = [
                    command_name
                    for command_name in _RAPHAEL_SLASH_COMMANDS
                    if command_name not in registry
                ]
                status_handler = plugins_mod.get_plugin_command_handler(
                    "raphael-status"
                )
                skills_handler = plugins_mod.get_plugin_command_handler(
                    "raphael-skills"
                )
                status_output = (
                    plugins_mod.resolve_plugin_command_result(status_handler(""))
                    if callable(status_handler)
                    else ""
                )
                skills_output = (
                    plugins_mod.resolve_plugin_command_result(skills_handler(""))
                    if callable(skills_handler)
                    else ""
                )
                status_text = str(status_output or "")
                skills_text = str(skills_output or "")
                status_brief_verified = (
                    "Raphael Sage King" in status_text
                    and "賢者總覽:" in status_text
                )
                skills_brief_verified = (
                    "Raphael Skill Evolution Trace" in skills_text
                    and "Skill Evolution Brief:" in skills_text
                )
                from hermes_cli.commands import (
                    is_gateway_known_command,
                    telegram_menu_commands,
                )

                gateway_known = is_gateway_known_command("raphael-skills")
                telegram_commands = [
                    command_name
                    for command_name, _description in telegram_menu_commands(
                        max_commands=100
                    )[0]
                ]
            finally:
                plugins_mod._plugin_manager = previous_manager
        except Exception as exc:
            error = exc.__class__.__name__
        finally:
            reset_hermes_home_override(token)

    passed = (
        not missing_commands
        and status_brief_verified
        and skills_brief_verified
        and gateway_known
        and "raphael_skills" in telegram_commands
        and not error
    )
    return {
        "status": "pass" if passed else "fail",
        "evidence": "Raphael slash command surface rendered in isolated HERMES_HOME"
        if passed
        else "Raphael slash command surface failed in isolated HERMES_HOME",
        "command": command,
        "run_id": run_id,
        "commands": commands,
        "missing_commands": missing_commands,
        "status_brief_verified": status_brief_verified,
        "skills_brief_verified": skills_brief_verified,
        "gateway_known": gateway_known,
        "telegram_commands": telegram_commands,
        "temp_home": "isolated",
        **({"error": error} if error else {}),
    }


def _mode_router_contract_release_gate_check() -> dict[str, Any]:
    run_id = "mode-router-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    cases = [
        _mode_router_case_payload(
            "general_conversation",
            build_raphael_control_decision("今天想聊一下拉斐爾的整體方向"),
        ),
        _mode_router_case_payload(
            "tool_task",
            build_raphael_control_decision("請修復這個 bug 並跑測試"),
        ),
        _mode_router_case_payload(
            "visual_agent_generation",
            build_raphael_control_decision(
                "請產出一張圖片和一段 6 秒影片：霧黑鋼筆放在白紙上，柔和窗光。",
                attachments=["ref1"],
            ),
        ),
        _mode_router_case_payload(
            "visual_agent_edit",
            build_raphael_control_decision(
                "把剛剛那張圖改亮一點，比例不要變",
                conversation_history=[
                    {
                        "role": "assistant",
                        "content": "已產出圖片。",
                        "metadata": {"selected_artifact_id": "current-artifact"},
                    }
                ],
            ),
        ),
        _mode_router_case_payload(
            "prompt_disclosure",
            build_raphael_control_decision("請給我剛剛產圖用的 prompt"),
        ),
        _mode_router_case_payload(
            "needs_clarification",
            build_raphael_control_decision(
                "用 ref3 的服裝，ref1 的角色，產出圖片",
                attachments=["ref1", "ref2"],
            ),
        ),
    ]
    for case in cases:
        case_mismatches = _mode_router_case_mismatches(case)
        case["mismatches"] = list(case_mismatches)
        case["status"] = "pass" if not case_mismatches else "fail"
    present_cases = {str(case.get("case") or "").strip() for case in cases}
    missing_cases = [
        case_name
        for case_name in _MODE_ROUTER_REQUIRED_CASES
        if case_name not in present_cases
    ]
    mismatches = [
        f"{case.get('case')}: {mismatch}"
        for case in cases
        for mismatch in case.get("mismatches", [])
    ]
    mismatches.extend(f"{case_name}: missing" for case_name in missing_cases)
    passed = not mismatches
    return {
        "status": "pass" if passed else "fail",
        "evidence": "deterministic Raphael mode router contract passed"
        if passed
        else "deterministic Raphael mode router contract failed",
        "command": "deterministic Raphael control decision mode-router contract",
        "run_id": run_id,
        "route_provenance": _MODE_ROUTER_PROVENANCE,
        "cases": cases,
        "mismatches": mismatches,
    }


def _mode_router_case_payload(
    case_name: str,
    decision: Any,
) -> dict[str, Any]:
    return {
        "case": case_name,
        "status": "unchecked",
        "mode": decision.mode,
        "target_artifact": decision.goal.target_artifact,
        "phase": decision.goal.phase,
        "next_action": decision.next_action,
        "handoff_tool": decision.route.handoff_tool,
        "bypass_base_llm": decision.route.bypass_base_llm,
        "visual_agent_llm_provider": decision.route.visual_agent_llm_provider,
        "visual_agent_llm_model": decision.route.visual_agent_llm_model,
        "visual_media_provider": decision.route.visual_media_provider,
        "visual_media_model": decision.route.visual_media_model,
        "reference_resolution": decision.reference_resolution,
        "active_artifact_continuity": bool(decision.goal.active_artifact_id),
        "blockers": list(decision.goal.blockers),
        "required_proofs": list(decision.evidence.required_proofs),
        "mismatches": [],
    }


def _mode_router_case_mismatches(case: dict[str, Any]) -> tuple[str, ...]:
    case_name = str(case.get("case") or "").strip()
    expected = _MODE_ROUTER_CASE_EXPECTATIONS.get(case_name)
    if not expected:
        return ("unknown_case",)
    mismatches: list[str] = []
    for field, expected_value in expected.items():
        actual_value = case.get(field)
        if not _mode_router_value_matches(actual_value, expected_value):
            mismatches.append(f"{field} expected {expected_value!r} got {actual_value!r}")
    return tuple(mismatches)


def _mode_router_value_matches(actual_value: Any, expected_value: Any) -> bool:
    if expected_value is None:
        return actual_value is None or actual_value == ""
    return actual_value == expected_value


def _goal_state_contract_release_gate_check() -> dict[str, Any]:
    run_id = "goal-state-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    cases: list[dict[str, Any]] = []
    error = ""
    with tempfile.TemporaryDirectory(prefix="hermes-raphael-goal-state-") as tmp:
        token = set_hermes_home_override(tmp)
        try:
            config = {
                "plugins": {"enabled": ["raphael"], "disabled": []},
                "raphael": {
                    "enabled": True,
                    "default_conversation_mode_enabled": True,
                    "mode": "sage_king",
                },
            }
            _save_raphael_config(config)
            first_appraisal = appraise_raphael_situation(
                "請修復 gateway fallback bug 並驗證"
            )
            first_mission = update_raphael_mission(
                None,
                first_appraisal,
                simulate_raphael_strategies(first_appraisal),
            )
            cases.append(
                _goal_state_case_payload(
                    "new_tool_mission",
                    first_mission,
                    mission_continuity=False,
                )
            )

            followup_appraisal = appraise_raphael_situation(
                "再補 install enable disable lifecycle 驗證"
            )
            followup_mission = update_raphael_mission(
                first_mission,
                followup_appraisal,
                simulate_raphael_strategies(followup_appraisal),
            )
            cases.append(
                _goal_state_case_payload(
                    "followup_preserves_mission",
                    followup_mission,
                    mission_continuity=(
                        followup_mission.mission_id == first_mission.mission_id
                    ),
                )
            )

            from agent.raphael.observer import build_raphael_observation_context
            from agent.raphael.state import read_mission_state, write_mission_state

            write_mission_state(None)
            build_raphael_observation_context(
                "請修復 gateway fallback bug 並驗證",
                config,
            )
            mission_before_summon = read_mission_state()
            build_raphael_observation_context("拉斐爾？", config)
            mission_after_summon = read_mission_state()
            casual_preserved = (
                mission_before_summon is not None
                and mission_after_summon is not None
                and mission_after_summon.mission_id
                == mission_before_summon.mission_id
                and mission_after_summon.goal == mission_before_summon.goal
                and mission_after_summon.required_proofs
                == mission_before_summon.required_proofs
            )
            if mission_after_summon is not None:
                cases.append(
                    _goal_state_case_payload(
                        "casual_summon_preserves_mission",
                        mission_after_summon,
                        mission_continuity=(
                            mission_before_summon is not None
                            and mission_after_summon.mission_id
                            == mission_before_summon.mission_id
                        ),
                        casual_turn_preserved=casual_preserved,
                    )
                )
            else:
                cases.append(
                    _goal_state_missing_case_payload(
                        "casual_summon_preserves_mission",
                        "mission_missing_after_casual_summon",
                    )
                )

            visual_edit_appraisal = appraise_raphael_situation(
                "把剛剛那張圖改亮一點，比例不要變",
                conversation_history=[
                    {
                        "role": "assistant",
                        "content": "已產出圖片。",
                        "metadata": {"selected_artifact_id": "artifact-current"},
                    }
                ],
            )
            visual_edit_mission = update_raphael_mission(
                None,
                visual_edit_appraisal,
                simulate_raphael_strategies(visual_edit_appraisal),
            )
            cases.append(
                _goal_state_case_payload(
                    "visual_edit_targets_current_artifact",
                    visual_edit_mission,
                    mission_continuity=False,
                )
            )

            missing_ref_appraisal = appraise_raphael_situation(
                "用 ref3 的服裝，ref1 的角色，產出圖片",
                attachments=["ref1", "ref2"],
            )
            missing_ref_mission = update_raphael_mission(
                None,
                missing_ref_appraisal,
                simulate_raphael_strategies(missing_ref_appraisal),
            )
            cases.append(
                _goal_state_case_payload(
                    "missing_reference_blocks",
                    missing_ref_mission,
                    mission_continuity=False,
                )
            )
        except Exception as exc:
            error = exc.__class__.__name__
        finally:
            reset_hermes_home_override(token)

    for case in cases:
        case_mismatches = _goal_state_case_mismatches(case)
        case["mismatches"] = list(case_mismatches)
        case["status"] = "pass" if not case_mismatches else "fail"
    present_cases = {str(case.get("case") or "").strip() for case in cases}
    missing_cases = [
        case_name
        for case_name in _GOAL_STATE_REQUIRED_CASES
        if case_name not in present_cases
    ]
    mismatches = [
        f"{case.get('case')}: {mismatch}"
        for case in cases
        for mismatch in case.get("mismatches", [])
    ]
    mismatches.extend(f"{case_name}: missing" for case_name in missing_cases)
    if error:
        mismatches.append(f"goal_state_contract_error: {error}")
    passed = not mismatches
    return {
        "status": "pass" if passed else "fail",
        "evidence": "deterministic Raphael goal-state contract passed"
        if passed
        else "deterministic Raphael goal-state contract failed",
        "command": "deterministic Raphael mission goal-state contract",
        "run_id": run_id,
        "state_provenance": _GOAL_STATE_PROVENANCE,
        "temp_home": "isolated",
        "cases": cases,
        "mismatches": mismatches,
        **({"error": error} if error else {}),
    }


def _goal_state_case_payload(
    case_name: str,
    mission: Any,
    *,
    mission_continuity: bool,
    casual_turn_preserved: bool | None = None,
) -> dict[str, Any]:
    return {
        "case": case_name,
        "status": "unchecked",
        "phase": mission.phase,
        "next_action": mission.next_action,
        "proof_status": mission.proof_status,
        "mission_continuity": mission_continuity,
        "casual_turn_preserved": casual_turn_preserved,
        "active_artifact_id": mission.active_artifact_id,
        "blockers": list(mission.blockers),
        "required_proofs": list(mission.required_proofs),
        "mismatches": [],
    }


def _goal_state_missing_case_payload(
    case_name: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "case": case_name,
        "status": "fail",
        "phase": "",
        "next_action": "",
        "proof_status": "",
        "mission_continuity": False,
        "casual_turn_preserved": False,
        "active_artifact_id": None,
        "blockers": [],
        "required_proofs": [],
        "mismatches": [reason],
    }


def _goal_state_case_mismatches(case: dict[str, Any]) -> tuple[str, ...]:
    case_name = str(case.get("case") or "").strip()
    expected = _GOAL_STATE_CASE_EXPECTATIONS.get(case_name)
    if not expected:
        return ("unknown_case",)
    mismatches: list[str] = []
    for field, expected_value in expected.items():
        actual_value = case.get(field)
        if actual_value != expected_value:
            mismatches.append(f"{field} expected {expected_value!r} got {actual_value!r}")
    return tuple(mismatches)


def _evolution_contract_release_gate_check() -> dict[str, Any]:
    run_id = "evolution-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    cases: list[dict[str, Any]] = []
    error = ""
    with tempfile.TemporaryDirectory(prefix="hermes-raphael-evolution-") as tmp:
        token = set_hermes_home_override(tmp)
        try:
            audit_config = _evolution_contract_config(
                skill_writes=False,
                memory_writes=False,
            )
            active_config = _evolution_contract_config(
                skill_writes=True,
                memory_writes=True,
            )
            _save_raphael_config(audit_config)
            cases.append(
                _evolution_case_payload(
                    "audit_only_user_correction",
                    decide_raphael_evolution(
                        user_message=(
                            "不對，拉斐爾模式要主動進化技能，但預設不要污染 durable policy"
                        ),
                        final_response="我會提出可審計的改進方案。",
                        messages=[],
                        turn_exit_reason="text_response",
                        config=audit_config,
                    ),
                )
            )
            cases.append(
                _evolution_case_payload(
                    "active_writes_require_explicit_enable",
                    decide_raphael_evolution(
                        user_message="不對，這個 workflow 要記住並強化 skill",
                        final_response="我會排入 Raphael evolution review。",
                        messages=[],
                        turn_exit_reason="text_response",
                        config=active_config,
                    ),
                )
            )
            cases.append(
                _evolution_case_payload(
                    "high_risk_mutation_proposal_only",
                    decide_raphael_evolution(
                        user_message="之後自動修改 cron、發布到 Slack、安裝工具，不用再問我",
                        final_response="我不能直接這樣做。",
                        messages=[],
                        turn_exit_reason="text_response",
                        config=active_config,
                    ),
                )
            )
            cases.append(
                _evolution_case_payload(
                    "visual_failure_learning_signal",
                    decide_raphael_evolution(
                        user_message="幫我做 image + video",
                        final_response="候選圖未通過。",
                        messages=[
                            {
                                "role": "tool",
                                "name": "visual_agent_generate",
                                "content": (
                                    '{"success": false, "failure_layer": '
                                    '"provider_health", "error": "Grok Web Imagine '
                                    'browser automation timed out"}'
                                ),
                            }
                        ],
                        turn_exit_reason="direct_visual_agent_handoff",
                        config=active_config,
                    ),
                )
            )

            private_decision = decide_raphael_evolution(
                user_message=(
                    "不對，請記住 /Users/simon/private/ref.png 和 sk-secret "
                    "data:image/png;base64,"
                    + "a" * 120
                ),
                final_response="我會保留可回滾、可審計的 lesson。",
                messages=[],
                turn_exit_reason="text_response",
                config=active_config,
            )
            append_evolution_record(private_decision, status="scheduled")
            records = read_evolution_records(limit=1)
            serialized_record = json.dumps(records, ensure_ascii=False, sort_keys=True)
            private_data_redacted = (
                "sk-secret" not in serialized_record
                and "/Users/simon/private/ref.png" not in serialized_record
                and "data:image/png;base64" not in serialized_record
                and "a" * 80 not in serialized_record
                and "[redacted" in serialized_record
            )
            cases.append(
                _evolution_case_payload(
                    "privacy_sanitized_evolution_record",
                    private_decision,
                    record_private_data_redacted=private_data_redacted,
                )
            )
            proof_response = (
                "狀態：還不能判定完成，Raphael proof gate 沒看到足夠證據。\n"
                "下一步：先執行必要測試或 runtime smoke，再回報具體證據。"
            )
            proof_decision = decide_raphael_evolution(
                user_message="請修復 Hermes runtime bug 並驗證到能上線",
                final_response=proof_response,
                messages=[{"role": "assistant", "content": proof_response}],
                turn_exit_reason="text_response",
                config=active_config,
                metadata={
                    "promotion_gate": (
                        "focused tests plus runtime, replay, or LLM smoke"
                    ),
                    "rollback_condition": (
                        "next evidence or user feedback shows worse behavior"
                    ),
                },
            )
            visual_decision = decide_raphael_evolution(
                user_message="幫我做 image + video",
                final_response="候選圖未通過。",
                messages=[
                    {
                        "role": "tool",
                        "name": "visual_agent_generate",
                        "content": (
                            '{"success": false, "failure_layer": '
                            '"artifact_quality"}'
                        ),
                    }
                ],
                turn_exit_reason="direct_visual_agent_handoff",
                config=active_config,
            )
            append_evolution_record(proof_decision, status="scheduled")
            append_evolution_record(proof_decision, status="scheduled")
            append_evolution_record(visual_decision, status="scheduled")
            priority_records = read_evolution_records(limit=3)
            proposal_state = read_raphael_state()
            matching_proposals = [
                proposal
                for proposal in proposal_state.action_proposals
                if "evolution:raphael.proof_gate" in proposal.evidence_refs
                and "pattern_count:2" in proposal.evidence_refs
            ]
            rollout_plan = _evolution_action_proposal_rollout_plan(
                matching_proposals[0] if matching_proposals else None
            )
            rollout_commands = rollout_plan.get("verification_commands", [])
            rollout_promotion_gate = str(
                rollout_plan.get("promotion_gate") or ""
            ).strip()
            rollout_rollback_condition = str(
                rollout_plan.get("rollback_condition") or ""
            ).strip()
            status_output = render_raphael_status(
                RaphaelState.empty(),
                evolution_records=priority_records,
            )
            active_section = (
                status_output.split("Active Self-Correction:", 1)[1]
                .split("Recent Evolution:", 1)[0]
            )
            self_correction_prioritized = (
                "能力：Raphael proof gate" in active_section
                and "同類演化：2 次" in active_section
                and "visual agent mode" not in active_section
            )
            cases.append(
                _evolution_case_payload(
                    "repeated_failure_self_correction_priority",
                    proof_decision,
                    self_correction_prioritized=self_correction_prioritized,
                    self_correction_pattern_count=2,
                    action_proposal_created=bool(matching_proposals),
                    action_proposal_requires_approval=any(
                        proposal.requires_approval for proposal in matching_proposals
                    ),
                    action_proposal_rollout_plan_verified=(
                        rollout_plan.get("status") == "pending_approval"
                        and rollout_plan.get("risk") == "R2"
                        and rollout_commands
                        == [
                            "pytest tests/agent/test_raphael_evolution.py -q",
                            (
                                "hermes raphael readiness --readiness-profile llm "
                                "--check"
                            ),
                        ]
                        and bool(rollout_promotion_gate)
                        and bool(rollout_rollback_condition)
                    ),
                    action_proposal_rollout_status=str(
                        rollout_plan.get("status") or ""
                    ).strip()
                    or None,
                    action_proposal_rollout_verification_commands=rollout_commands
                    if isinstance(rollout_commands, list)
                    else None,
                    action_proposal_rollout_promotion_gate=rollout_promotion_gate
                    or None,
                    action_proposal_rollout_rollback_condition=(
                        rollout_rollback_condition or None
                    ),
                )
            )
        except Exception as exc:
            error = exc.__class__.__name__
        finally:
            reset_hermes_home_override(token)

    for case in cases:
        case_mismatches = _evolution_case_mismatches(case)
        case["mismatches"] = list(case_mismatches)
        case["status"] = "pass" if not case_mismatches else "fail"
    present_cases = {str(case.get("case") or "").strip() for case in cases}
    missing_cases = [
        case_name
        for case_name in _EVOLUTION_REQUIRED_CASES
        if case_name not in present_cases
    ]
    mismatches = [
        f"{case.get('case')}: {mismatch}"
        for case in cases
        for mismatch in case.get("mismatches", [])
    ]
    mismatches.extend(f"{case_name}: missing" for case_name in missing_cases)
    if error:
        mismatches.append(f"evolution_contract_error: {error}")
    passed = not mismatches
    return {
        "status": "pass" if passed else "fail",
        "evidence": "deterministic Raphael evolution contract passed"
        if passed
        else "deterministic Raphael evolution contract failed",
        "command": "deterministic Raphael auditable evolution contract",
        "run_id": run_id,
        "evolution_provenance": _EVOLUTION_PROVENANCE,
        "temp_home": "isolated",
        "cases": cases,
        "mismatches": mismatches,
        **({"error": error} if error else {}),
    }


def _evolution_contract_config(
    *,
    skill_writes: bool,
    memory_writes: bool,
) -> dict[str, Any]:
    return {
        "plugins": {"enabled": ["raphael"], "disabled": []},
        "raphael": {
            "enabled": True,
            "default_conversation_mode_enabled": True,
            "mode": "sage_king",
            "skill_writes_enabled": skill_writes,
            "memory_writes_enabled": memory_writes,
            "evolution": {
                "enabled": True,
                "skill_review_enabled": True,
                "memory_review_enabled": True,
            },
        },
    }


def _evolution_case_payload(
    case_name: str,
    decision: Any,
    *,
    record_private_data_redacted: bool | None = None,
    self_correction_prioritized: bool | None = None,
    self_correction_pattern_count: int | None = None,
    action_proposal_created: bool | None = None,
    action_proposal_requires_approval: bool | None = None,
    action_proposal_rollout_plan_verified: bool | None = None,
    action_proposal_rollout_status: str | None = None,
    action_proposal_rollout_verification_commands: list[str] | None = None,
    action_proposal_rollout_promotion_gate: str | None = None,
    action_proposal_rollout_rollback_condition: str | None = None,
) -> dict[str, Any]:
    metadata = decision.metadata if isinstance(decision.metadata, Mapping) else {}
    return {
        "case": case_name,
        "status": "unchecked",
        "mode": decision.mode,
        "should_review": decision.should_review,
        "review_skills": decision.review_skills,
        "review_memory": decision.review_memory,
        "proposal_only": decision.proposal_only,
        "reason_codes": list(decision.reason_codes),
        "affected_capability": str(metadata.get("affected_capability") or ""),
        "metadata_has_promotion_gate": bool(
            str(metadata.get("promotion_gate") or "").strip()
        ),
        "metadata_has_rollback_condition": bool(
            str(metadata.get("rollback_condition") or "").strip()
        ),
        "record_private_data_redacted": record_private_data_redacted,
        "self_correction_prioritized": self_correction_prioritized,
        "self_correction_pattern_count": self_correction_pattern_count,
        "action_proposal_created": action_proposal_created,
        "action_proposal_requires_approval": action_proposal_requires_approval,
        "action_proposal_rollout_plan_verified": (
            action_proposal_rollout_plan_verified
        ),
        "action_proposal_rollout_status": action_proposal_rollout_status,
        "action_proposal_rollout_verification_commands": (
            action_proposal_rollout_verification_commands
        ),
        "action_proposal_rollout_promotion_gate": (
            action_proposal_rollout_promotion_gate
        ),
        "action_proposal_rollout_rollback_condition": (
            action_proposal_rollout_rollback_condition
        ),
        "mismatches": [],
    }


def _evolution_action_proposal_rollout_plan(proposal: Any) -> dict[str, Any]:
    if proposal is None:
        return {}
    metadata = proposal.metadata if isinstance(proposal.metadata, Mapping) else {}
    rollout_plan = metadata.get("rollout_plan")
    if not isinstance(rollout_plan, Mapping):
        return {}
    commands = rollout_plan.get("verification_commands")
    normalized_commands = (
        [str(command) for command in commands]
        if isinstance(commands, list)
        else []
    )
    return {
        "status": str(rollout_plan.get("status") or "").strip(),
        "risk": str(rollout_plan.get("risk") or "").strip(),
        "verification_commands": normalized_commands,
        "promotion_gate": str(rollout_plan.get("promotion_gate") or "").strip(),
        "rollback_condition": str(
            rollout_plan.get("rollback_condition") or ""
        ).strip(),
    }


def _evolution_case_mismatches(case: dict[str, Any]) -> tuple[str, ...]:
    case_name = str(case.get("case") or "").strip()
    expected = _EVOLUTION_CASE_EXPECTATIONS.get(case_name)
    if not expected:
        return ("unknown_case",)
    mismatches: list[str] = []
    for field, expected_value in expected.items():
        actual_value = case.get(field)
        if actual_value != expected_value:
            mismatches.append(f"{field} expected {expected_value!r} got {actual_value!r}")
    return tuple(mismatches)


def _raphael_user_simulation_cases() -> list[dict[str, Any]]:
    return [
        _user_simulation_standby_summon_case(),
        _user_simulation_vague_takeover_case(),
        _user_simulation_runtime_log_attachment_case(),
        _user_simulation_blank_screen_repair_case(),
        _user_simulation_prompt_builder_question_case(),
        _user_simulation_negated_media_summon_case(),
    ]


def _user_simulation_case(
    case: str,
    passed: bool,
    *,
    user_prompt: str,
    expected_visible_behavior: str,
    critical_assertions: tuple[str, ...],
    evidence: str,
    next_action: str,
    proof_layer: str,
    route: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "case": case,
        "user_prompt": user_prompt,
        "expected_visible_behavior": expected_visible_behavior,
        "critical_assertions": list(critical_assertions),
        "status": "pass" if passed else "fail",
        "visual_quota_used": False,
        "evidence": evidence,
        "next_action": next_action,
        "proof_layer": proof_layer,
    }
    if route:
        payload["route"] = route
    return payload


def _user_simulation_standby_summon_case() -> dict[str, Any]:
    output = render_raphael_demo("拉斐爾？")
    passed = "狀態：Raphael 待命" in output and "請給我任務目標" in output
    return _user_simulation_case(
        "standby_summon",
        passed,
        user_prompt="拉斐爾？",
        expected_visible_behavior="standby state asks for the mission target",
        critical_assertions=(
            "standby_state_visible",
            "asks_for_mission_target",
        ),
        evidence="standalone summon renders standby state and asks for mission target",
        next_action="ask for the mission target before planning",
        proof_layer="runtime_smoke",
        route="standby",
    )


def _user_simulation_vague_takeover_case() -> dict[str, Any]:
    from agent.raphael.observer import build_raphael_observation_context
    from agent.raphael.state import read_mission_state

    config = {
        "plugins": {"enabled": ["raphael"], "disabled": []},
        "raphael": {
            "enabled": True,
            "default_conversation_mode_enabled": True,
            "mode": "sage_king",
        },
    }
    with tempfile.TemporaryDirectory(prefix="raphael-user-sim-") as temp_home:
        previous_home = os.environ.get("HERMES_HOME")
        token = set_hermes_home_override(Path(temp_home))
        os.environ["HERMES_HOME"] = temp_home
        try:
            build_raphael_observation_context(
                "請修復 gateway fallback bug 並驗證",
                config,
            )
            first_mission = read_mission_state()
            build_raphael_observation_context("拉斐爾，接管這個任務", config)
            second_mission = read_mission_state()
        finally:
            reset_hermes_home_override(token)
            if previous_home is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = previous_home
    passed = (
        first_mission is not None
        and second_mission is not None
        and second_mission.mission_id == first_mission.mission_id
        and second_mission.goal == first_mission.goal
    )
    return _user_simulation_case(
        "vague_takeover_preserves_mission",
        passed,
        user_prompt="拉斐爾，接管這個任務",
        expected_visible_behavior=(
            "continue the existing mission instead of starting a new one"
        ),
        critical_assertions=(
            "mission_id_preserved",
            "goal_preserved",
        ),
        evidence="vague takeover summon preserves existing mission identity and goal",
        next_action="continue the preserved mission instead of starting a new artifact",
        proof_layer="goal_state_contract",
        route="mission_continuity",
    )


def _user_simulation_runtime_log_attachment_case() -> dict[str, Any]:
    decision = build_raphael_control_decision(
        "拉斐爾，接管這個 runtime bug，檢查這個 log",
        attachments=["/tmp/trace.log"],
    )
    passed = (
        decision.mode == "tool_task"
        and decision.route.handoff_tool is None
        and decision.next_action == "plan_execute_verify"
    )
    return _user_simulation_case(
        "runtime_log_attachment_routes_tool_task",
        passed,
        user_prompt="拉斐爾，接管這個 runtime bug，檢查這個 log",
        expected_visible_behavior=(
            "treat the log as tool-task evidence instead of visual media input"
        ),
        critical_assertions=(
            "routes_tool_task",
            "no_visual_handoff",
        ),
        evidence="non-image log attachment routes to tool task instead of visual handoff",
        next_action="plan, execute, and verify the runtime repair",
        proof_layer="mode_router_contract",
        route=decision.mode,
    )


def _user_simulation_blank_screen_repair_case() -> dict[str, Any]:
    appraisal = appraise_raphael_situation("拉斐爾，接管這個任務：畫面空白，請修復")
    passed = appraisal.task_type == "tool_runtime"
    return _user_simulation_case(
        "blank_screen_repair_routes_tool_task",
        passed,
        user_prompt="拉斐爾，接管這個任務：畫面空白，請修復",
        expected_visible_behavior=(
            "classify the blank screen as runtime/UI repair, not image generation"
        ),
        critical_assertions=(
            "classified_runtime_repair",
            "requires_runtime_evidence",
        ),
        evidence="UI blank-screen repair is treated as runtime repair, not image generation",
        next_action="inspect runtime/UI evidence before claiming repair",
        proof_layer="intent_appraisal_contract",
        route=appraisal.task_type,
    )


def _user_simulation_prompt_builder_question_case() -> dict[str, Any]:
    decision = build_raphael_control_decision(
        "檢查 agent/prompt_builder.py 使用哪個 prompt"
    )
    passed = (
        decision.mode != "prompt_disclosure"
        and decision.goal.target_artifact != "latest_visual_prompt_trace"
    )
    return _user_simulation_case(
        "prompt_builder_question_not_prompt_disclosure",
        passed,
        user_prompt="檢查 agent/prompt_builder.py 使用哪個 prompt",
        expected_visible_behavior=(
            "answer from repository code without treating it as prompt disclosure"
        ),
        critical_assertions=(
            "not_prompt_disclosure",
            "uses_repository_context",
        ),
        evidence="code question about prompt_builder.py is not treated as visual prompt disclosure",
        next_action="answer from repository code without disclosing hidden prompts",
        proof_layer="prompt_safety_contract",
        route=decision.mode,
    )


def _user_simulation_negated_media_summon_case() -> dict[str, Any]:
    decision = build_raphael_control_decision(
        "拉斐爾？不要呼叫工具，不要產圖，只測試 LLM-only Raphael summon。"
        "請用三段短句回覆：狀態、目前目標、下一步。"
    )
    passed = (
        decision.mode == "runtime_analysis"
        and decision.route.handoff_tool is None
        and decision.next_action == "answer_with_runtime_analysis"
    )
    return _user_simulation_case(
        "negated_media_summon_stays_text_only",
        passed,
        user_prompt=(
            "拉斐爾？不要呼叫工具，不要產圖，只測試 LLM-only Raphael summon。"
        ),
        expected_visible_behavior=(
            "reply with text-only status, current goal, and next step"
        ),
        critical_assertions=(
            "no_tool_call",
            "no_media_generation",
            "text_only_status_goal_next_step",
        ),
        evidence="negated media summon remains on text-only runtime route",
        next_action="reply with status, current goal, and next step without tools or media",
        proof_layer="quota_guard_contract",
        route=decision.mode,
    )


def _wow_user_simulation_cases_valid(cases: Any) -> bool:
    if not isinstance(cases, list):
        return False
    by_case: dict[str, dict[str, Any]] = {}
    for item in cases:
        if not isinstance(item, dict):
            return False
        case_name = str(item.get("case") or "").strip()
        if not case_name or case_name in by_case:
            return False
        by_case[case_name] = item
    if set(by_case) != set(_WOW_USER_SIMULATION_REQUIRED_CASES):
        return False
    return all(
        item.get("status") == "pass"
        and item.get("visual_quota_used") is False
        and bool(str(item.get("user_prompt") or "").strip())
        and bool(str(item.get("expected_visible_behavior") or "").strip())
        and _nonempty_string_list(item.get("critical_assertions"))
        and bool(str(item.get("evidence") or "").strip())
        and bool(str(item.get("next_action") or "").strip())
        and str(item.get("proof_layer") or "").strip()
        in _WOW_USER_SIMULATION_PROOF_LAYERS
        for item in by_case.values()
    )


def _nonempty_string_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(bool(str(item or "").strip()) for item in value)
    )


def _wow_release_gate_check(lifecycle_check: dict[str, Any]) -> dict[str, Any]:
    run_id = "wow-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    started = perf_counter()
    demo_output = render_raphael_demo("拉斐爾，請修復 gateway provider fallback 並完成驗證")
    user_simulation_cases = _raphael_user_simulation_cases()
    elapsed_seconds = perf_counter() - started
    lowered = demo_output.lower()
    signals = {
        "summon_appraisal": all(
            marker in demo_output
            for marker in ("解析完成。", "局勢判讀", "最優路線")
        ),
        "standby_summon": all(
            marker in demo_output
            for marker in ("Standby Summon:", "狀態：Raphael 待命", "請給我任務目標")
        ),
        "mission_followup": "Mission Transition:" in demo_output
        and "- 下一步：" in demo_output,
        "proof_gate": "Proof Gate Block:" in demo_output
        and "Status: not complete." in demo_output,
        "evolution_feedback": "Evolution Metadata:" in demo_output
        and "上線條件：" in demo_output
        and "回滾條件：" in demo_output,
        "lifecycle_reversible": lifecycle_check.get("status") == "pass"
        and "Enable/Disable:" in demo_output,
        "demo_under_one_minute": elapsed_seconds < 60,
        "clean_output": not any(
            forbidden in lowered
            for forbidden in (
                "base64",
                "data:image",
                "provider response",
                "raw prompt",
                "secret",
                "api_key",
                "affected_capability:",
                "proposed_change:",
                "promotion_gate:",
                "rollback_condition:",
                "proposal-",
                "trigger:",
                "reasons=",
                "capability=",
                "confidence=",
                "promotion=",
                "rollback=",
            )
        ),
    }
    score, missing = calculate_raphael_wow_score(signals)
    passed = _wow_score_passes_release_gate(score, signals)
    return {
        "status": "pass" if passed else "fail",
        "evidence": "deterministic Raphael wow score passed"
        if passed
        else "deterministic Raphael wow score failed",
        "command": "hermes raphael demo",
        "run_id": run_id,
        "score": score,
        "threshold": _WOW_RELEASE_THRESHOLD,
        "signals": signals,
        "missing": list(missing),
        "user_simulation_cases": user_simulation_cases,
        "elapsed_seconds": round(elapsed_seconds, 3),
    }


def _llm_release_gate_check(
    *,
    session_id: str | None,
    command: str | None,
    tool_call_count: int | None,
    transcript_report_path: str | None,
    summon_sections_verified: bool | None,
    full_body_preserved: bool | None,
    no_visual_failure_trace: bool | None,
) -> dict[str, Any] | None:
    if not str(session_id or "").strip():
        return None
    session_id_text = str(session_id).strip()
    log_evidence = _find_llm_smoke_log_evidence(session_id_text)
    transcript_evidence = _llm_transcript_report_evidence(
        transcript_report_path,
        session_id=session_id_text,
    )
    effective_tool_call_count = (
        tool_call_count
        if tool_call_count is not None
        else transcript_evidence.get("tool_call_count")
    )
    effective_summon_sections_verified = (
        summon_sections_verified
        if summon_sections_verified is not None
        else transcript_evidence.get("summon_sections_verified") is True
    )
    effective_full_body_preserved = (
        full_body_preserved
        if full_body_preserved is not None
        else transcript_evidence.get("full_body_preserved") is True
    )
    effective_no_visual_failure_trace = (
        no_visual_failure_trace
        if no_visual_failure_trace is not None
        else transcript_evidence.get("no_visual_failure_trace") is True
    )
    claimed_execution_ok = (
        effective_tool_call_count == 0
        and effective_summon_sections_verified
        and effective_full_body_preserved
        and effective_no_visual_failure_trace
    )
    status = "pass" if claimed_execution_ok and log_evidence["log_verified"] else (
        "log_unverified" if claimed_execution_ok else "smoke_unverified"
    )
    return {
        "status": status,
        "evidence": "LLM-only Raphael invocation and text-only route smoke passed"
        if status == "pass"
        else "LLM-only Raphael smoke lacks trusted execution log evidence",
        "command": str(command or "rtk hermes chat").strip() or "rtk hermes chat",
        "run_id": "llm-smoke-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        "session_id": session_id_text,
        **log_evidence,
        **transcript_evidence,
        "tool_call_count": effective_tool_call_count,
        "no_tool_calls": effective_tool_call_count == 0,
        "summon_sections_verified": effective_summon_sections_verified,
        "full_body_preserved": effective_full_body_preserved,
        "no_visual_failure_trace": effective_no_visual_failure_trace,
    }


def _find_llm_smoke_log_evidence(session_id: str) -> dict[str, Any]:
    for path in _readiness_log_paths():
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        model_provider = _llm_session_log_field(lines, session_id, "provider")
        for line in lines:
            if f"session={session_id}" not in line or "Turn ended:" not in line:
                continue
            log_verified = (
                f"[{session_id}]" in line
                and "reason=text_response" in line
                and "tool_turns=0" in line
                and "last_msg_role=assistant" in line
            )
            return {
                "log_verified": log_verified,
                "source_log_path": str(path),
                "log_line": line.strip(),
                "log_model": _log_field_value(line, "model"),
                "log_model_provider": model_provider,
            }
    return {
        "log_verified": False,
        "source_log_path": "",
        "log_line": "",
        "log_model": "",
        "log_model_provider": "",
    }


def _llm_session_log_field(lines: list[str], session_id: str, field: str) -> str:
    for line in lines:
        if f"[{session_id}]" not in line and f"session={session_id}" not in line:
            continue
        value = _log_field_value(line, field)
        if value:
            return value
    return ""


def _llm_session_log_field_from_path(
    source_log_path: str,
    session_id: str,
    field: str,
) -> str:
    if not source_log_path:
        return ""
    try:
        lines = Path(source_log_path).read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
    except OSError:
        return ""
    return _llm_session_log_field(lines, session_id, field)


def _log_field_value(line: str, field: str) -> str:
    prefix = f"{field}="
    for token in line.replace(",", " ").split():
        if token.startswith(prefix):
            return token.removeprefix(prefix).strip("'\"")
    return ""


def _llm_transcript_report_evidence(
    report_path: str | None,
    *,
    session_id: str,
) -> dict[str, Any]:
    path_text = str(report_path or "").strip()
    if not path_text:
        return {}
    path = Path(path_text)
    resolved = path.resolve() if path.exists() else path
    evidence: dict[str, Any] = {
        "source_transcript_path": str(resolved),
    }
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return evidence
    if not isinstance(parsed, dict):
        return evidence
    final_response = str(parsed.get("final_response") or "")
    followup_response = str(parsed.get("followup_response") or "")
    evidence.update(
        {
            "transcript_session_id": str(parsed.get("session_id") or "").strip(),
            "transcript_model": str(parsed.get("model") or "").strip(),
            "transcript_model_provider": str(
                parsed.get("model_provider") or ""
            ).strip(),
            "tool_call_count": _optional_int(parsed.get("tool_call_count")),
            "no_tool_calls": parsed.get("no_tool_calls") is True,
            "summon_sections_verified": parsed.get("summon_sections_verified")
            is True,
            "full_body_preserved": parsed.get("full_body_preserved") is True,
            "no_visual_failure_trace": parsed.get("no_visual_failure_trace") is True,
            "mission_followup_verified": parsed.get("mission_followup_verified")
            is True,
            "same_mission_continuity_verified": parsed.get(
                "same_mission_continuity_verified"
            )
            is True,
            "internal_trace_leak_detected": _llm_public_internal_trace_leak_detected(
                final_response,
                followup_response,
            ),
            "context_truncation_detected": _llm_context_truncation_detected(
                parsed,
            ),
        }
    )
    if evidence["transcript_session_id"] != session_id:
        evidence["transcript_session_mismatch"] = True
    return evidence


def _hostile_review_release_gate_check(
    *,
    command: str | None,
    run_id: str | None,
    verdict: str | None,
    blockers: int | None,
    report_path: str | None,
) -> dict[str, Any] | None:
    if str(report_path or "").strip():
        return _hostile_review_release_gate_check_from_report(
            report_path=str(report_path or "").strip(),
            command=command,
            run_id=run_id,
            verdict=verdict,
            blockers=blockers,
        )
    if not str(verdict or "").strip() and blockers is None:
        return None
    normalized_verdict = str(verdict or "").strip().lower()
    blocker_count = blockers if blockers is not None and blockers >= 0 else None
    return {
        "status": "report_missing",
        "evidence": "hostile review report path is required",
        "command": str(command or "subagent hostile review").strip()
        or "subagent hostile review",
        "run_id": str(run_id or "").strip(),
        "reviewer": "subagent",
        "verdict": normalized_verdict,
        "blockers": blocker_count,
    }


def _hostile_review_release_gate_check_from_report(
    *,
    report_path: str,
    command: str | None,
    run_id: str | None,
    verdict: str | None,
    blockers: int | None,
) -> dict[str, Any]:
    path = Path(report_path).expanduser().resolve()
    base = {
        "command": str(command or "subagent hostile review").strip()
        or "subagent hostile review",
        "run_id": str(run_id or "").strip(),
        "reviewer": "",
        "verdict": str(verdict or "").strip().lower(),
        "blockers": blockers if blockers is not None and blockers >= 0 else None,
        "source_report_path": str(path),
    }
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            **base,
            "status": "report_unreadable",
            "evidence": f"hostile review report could not be read: {exc.__class__.__name__}",
        }
    if not isinstance(report, dict):
        return {
            **base,
            "status": "report_invalid",
            "evidence": "hostile review report is not a JSON object",
        }

    report_command = str(report.get("command") or "").strip()
    report_run_id = str(report.get("run_id") or "").strip()
    report_reviewer = str(report.get("reviewer") or "").strip().lower()
    report_verdict = str(report.get("verdict") or "").strip().lower()
    report_coverage = _hostile_review_report_coverage(report)
    missing_coverage = _hostile_review_missing_coverage(report_coverage)
    review_scope = _hostile_review_string_list(report.get("scope"))
    review_evidence = _hostile_review_string_list(report.get("evidence"))
    residual_risk = str(report.get("residual_risk") or "").strip()
    llm_ux_claims = _hostile_review_ux_claims(report)
    ux_claims_valid = _hostile_review_ux_claims_valid(llm_ux_claims)
    missing_audit_trail = _hostile_review_missing_audit_trail(
        {
            "review_scope": review_scope,
            "review_evidence": review_evidence,
            "residual_risk": residual_risk,
        }
    )
    try:
        report_blockers = int(report.get("blockers"))
    except (TypeError, ValueError):
        report_blockers = None
    generated_at_fresh, _reason = _readiness_generated_at_is_fresh(
        report.get("generated_at")
    )
    supplied_command = str(command or "").strip()
    supplied_run_id = str(run_id or "").strip()
    supplied_verdict = str(verdict or "").strip().lower()
    supplied_blockers = blockers if blockers is not None and blockers >= 0 else None
    claims_match = (
        (not supplied_command or supplied_command == report_command)
        and (not supplied_run_id or supplied_run_id == report_run_id)
        and (not supplied_verdict or supplied_verdict == report_verdict)
        and (supplied_blockers is None or supplied_blockers == report_blockers)
    )
    base_passed = (
        report.get("schema_version") == 1
        and str(report.get("kind") or "").strip() == "raphael_hostile_review"
        and generated_at_fresh
        and bool(report_command)
        and bool(report_run_id)
        and report_reviewer == "subagent"
        and report_verdict in {"pass", "passed", "clean"}
        and report_blockers == 0
        and not missing_coverage
        and not missing_audit_trail
        and claims_match
    )
    passed = base_passed and ux_claims_valid
    status = "pass" if passed else "fail"
    if base_passed and not ux_claims_valid:
        status = "ux_claims_unverified"
    return {
        "status": status,
        "evidence": "hostile review report verified with no release blockers"
        if passed
        else "hostile review report failed release validation",
        "command": report_command,
        "run_id": supplied_run_id or report_run_id,
        "reviewer": report_reviewer,
        "verdict": report_verdict,
        "blockers": report_blockers,
        "coverage": list(report_coverage),
        "missing_coverage": list(missing_coverage),
        "review_scope": list(review_scope),
        "review_evidence": list(review_evidence),
        "llm_ux_claims": llm_ux_claims,
        "residual_risk": residual_risk,
        "missing_audit_trail": list(missing_audit_trail),
        "report_generated_at": str(report.get("generated_at") or "").strip(),
        "report_identity_verified": bool(report_run_id)
        and generated_at_fresh
        and claims_match,
        "source_report_path": str(path),
    }


def _non_visual_regression_release_gate_check(
    *,
    command: str | None,
    run_id: str | None,
    passed_count: int | None,
    visual_quota_used: bool,
    report_path: str | None,
) -> dict[str, Any] | None:
    if str(report_path or "").strip():
        return _non_visual_regression_release_gate_check_from_report(
            report_path=str(report_path or "").strip(),
            command=command,
            run_id=run_id,
            passed_count=passed_count,
            visual_quota_used=visual_quota_used,
        )
    if passed_count is None:
        return None
    return {
        "status": "report_missing",
        "evidence": "non-visual regression report path is required",
        "command": str(command or "non-visual regression").strip()
        or "non-visual regression",
        "run_id": str(run_id or "").strip(),
        "passed_count": passed_count,
        "visual_quota_used": visual_quota_used,
    }


def _package_install_release_gate_check(
    *,
    report_path: str | None,
) -> dict[str, Any] | None:
    if not str(report_path or "").strip():
        return None
    return _package_install_release_gate_check_from_report(
        report_path=str(report_path or "").strip(),
    )


def _package_install_release_gate_check_from_report(
    *,
    report_path: str,
) -> dict[str, Any]:
    path = Path(report_path).expanduser().resolve()
    base = {
        "command": "scripts/raphael_package_install_smoke.py",
        "run_id": "",
        "source_report_path": str(path),
    }
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            **base,
            "status": "report_unreadable",
            "evidence": f"package install smoke report could not be read: {exc.__class__.__name__}",
        }
    if not isinstance(report, dict):
        return {
            **base,
            "status": "report_invalid",
            "evidence": "package install smoke report is not a JSON object",
        }

    report_command = str(report.get("command") or "").strip()
    report_run_id = str(report.get("run_id") or "").strip()
    generated_at_fresh, _reason = _readiness_generated_at_is_fresh(
        report.get("generated_at")
    )
    try:
        report_exit_code = int(report.get("exit_code"))
    except (TypeError, ValueError):
        report_exit_code = None
    cli_exit_codes = report.get("cli_exit_codes")
    if not isinstance(cli_exit_codes, list):
        cli_exit_codes = []
    commands = report.get("commands")
    if not isinstance(commands, list):
        commands = []
    commands_digest = str(report.get("commands_digest") or "").strip()
    lifecycle_checks = _package_install_lifecycle_checks_from_commands(commands)
    transcript_cli_exit_codes = lifecycle_checks["cli_exit_codes"]
    commands_digest_verified = (
        bool(commands_digest)
        and commands_digest == _package_install_command_records_digest(commands)
    )
    hermes_entrypoint_path = str(report.get("hermes_entrypoint_path") or "").strip()
    commands_verified = (
        report.get("commands_verified") is True
        and commands_digest_verified
        and _package_install_command_transcript_verified(
            commands,
            venv_fallback_used=report.get("venv_fallback_used") is True,
            hermes_entrypoint_path=hermes_entrypoint_path,
        )
    )
    script_sha256 = str(report.get("script_sha256") or "").strip()
    current_script_sha256 = _package_install_current_script_sha256()
    expected_script_path = _package_install_current_script_path()
    report_script_path = str(report.get("script_path") or "").strip()
    script_identity_verified = (
        report.get("script_identity_verified") is True
        and _same_path(report_script_path, expected_script_path)
        and bool(script_sha256)
        and bool(current_script_sha256)
        and script_sha256 == current_script_sha256
    )
    evidence_items = _hostile_review_string_list(report.get("evidence"))
    residual_risk = str(report.get("residual_risk") or "").strip()
    installed_media_gate_lines = [
        str(item) for item in report.get("installed_media_gate_lines") or []
    ]
    installed_media_slice_ready = (
        report.get("installed_media_slice_ready") is True
        and "Limited media release ready: yes" in installed_media_gate_lines
        and "Full media release ready: no" in installed_media_gate_lines
        and "Limited media release ready: no" not in installed_media_gate_lines
    )
    installed_media_gate_fail_closed = (
        (
            report.get("installed_media_gate_fail_closed") is True
            or report.get("installed_media_fail_closed") is True
            or report.get("installed_media_slice_ready") is None
        )
        and (
            "Limited media release ready: no" in installed_media_gate_lines
            or not any(
                line.startswith("Limited media release ready:")
                for line in installed_media_gate_lines
            )
        )
        and "Full media release ready: no" in installed_media_gate_lines
        and "Public release ready: no" in installed_media_gate_lines
        and "Limited media release ready: yes" not in installed_media_gate_lines
        and "Full media release ready: yes" not in installed_media_gate_lines
        and "Public release ready: yes" not in installed_media_gate_lines
    )
    installed_media_gate_verified = (
        installed_media_slice_ready or installed_media_gate_fail_closed
    )
    installed_llm_gate_lines = [
        str(item) for item in report.get("installed_llm_gate_lines") or []
    ]
    installed_llm_release_ready = (
        report.get("installed_llm_release_ready") is True
        and "Release docs: pass" in installed_llm_gate_lines
        and "Release scope: llm_only" in installed_llm_gate_lines
        and "Public release ready: yes" in installed_llm_gate_lines
        and "Release state: ready_for_llm_only_release" in installed_llm_gate_lines
    )
    installed_llm_manifest_gate_verified = (
        report.get("installed_llm_manifest_gate_verified") is True
        and installed_llm_release_ready
        and any(
            line.startswith("Release slice manifest: reviewable")
            for line in installed_llm_gate_lines
        )
    )
    installed_llm_fresh_home_fail_closed = (
        report.get("installed_llm_fresh_home_fail_closed") is True
        and "Release scope: llm_only" in installed_llm_gate_lines
        and "Public release ready: no" in installed_llm_gate_lines
        and "Release state: blocked_release_evidence_pending" in installed_llm_gate_lines
        and "Public release ready: yes" not in installed_llm_gate_lines
    )
    installed_llm_gate_verified = (
        installed_llm_manifest_gate_verified or installed_llm_fresh_home_fail_closed
    )
    passed = (
        report.get("schema_version") == 1
        and str(report.get("kind") or "").strip()
        == "raphael_package_install_smoke"
        and report.get("success") is True
        and str(report.get("status") or "").strip().lower() == "pass"
        and generated_at_fresh
        and report_exit_code == 0
        and script_identity_verified
        and report_command == "scripts/raphael_package_install_smoke.py"
        and bool(report_run_id)
        and report.get("wheel_built") is True
        and report.get("wheel_installed") is True
        and report.get("source_tree_cwd_used") is False
        and report.get("source_tree_hygiene_checked") is True
        and report.get("source_tree_hygiene_clean") is True
        and report.get("source_tree_generated_artifacts") == []
        and report.get("source_tree_post_build_hygiene_clean") is True
        and report.get("source_tree_post_build_generated_artifacts") == []
        and report.get("pythonpath_clean") is True
        and installed_media_gate_verified
        and installed_llm_gate_verified
        and str(report.get("hermes_entrypoint") or "").strip() == "hermes"
        and report.get("hermes_entrypoint_found") is True
        and bool(hermes_entrypoint_path)
        and int(report.get("cli_command_count") or 0) >= len(_package_install_cli_labels())
        and cli_exit_codes
        and all(code == 0 for code in cli_exit_codes)
        and transcript_cli_exit_codes == cli_exit_codes
        and all(code == 0 for code in transcript_cli_exit_codes)
        and lifecycle_checks["cli_status_after_install_enabled"] is True
        and lifecycle_checks["cli_install_enabled"] is True
        and lifecycle_checks["cli_disable_keeps_plugin"] is True
        and lifecycle_checks["cli_status_after_disable_guides_enable"] is True
        and lifecycle_checks["cli_status_after_enable_enabled"] is True
        and lifecycle_checks["cli_enable_restores_mode"] is True
        and report.get("cli_proposal_status_safe_refs") is True
        and report.get("cli_proposal_approve_audited") is True
        and report.get("cli_proposal_approve_rollout_guidance") is True
        and report.get("cli_proposal_reject_audited") is True
        and report.get("cli_proposal_resolutions_persisted") is True
        and report.get("cli_proposal_raw_ids_hidden") is True
        and report.get("cli_proposal_no_durable_apply_warning") is True
        and lifecycle_checks["cli_proposal_status_safe_refs"] is True
        and lifecycle_checks["cli_proposal_approve_audited"] is True
        and lifecycle_checks["cli_proposal_approve_rollout_guidance"] is True
        and lifecycle_checks["cli_proposal_reject_audited"] is True
        and lifecycle_checks["cli_proposal_resolutions_persisted"] is True
        and lifecycle_checks["cli_proposal_raw_ids_hidden"] is True
        and lifecycle_checks["cli_proposal_no_durable_apply_warning"] is True
        and lifecycle_checks["cli_uninstall_disables_plugin"] is True
        and lifecycle_checks["cli_status_after_uninstall_guides_install"] is True
        and commands_verified
        and bool(evidence_items)
        and bool(residual_risk)
    )
    return {
        "status": "pass" if passed else "fail",
        "evidence": "fresh package install smoke report verified"
        if passed
        else "package install smoke report failed release validation",
        "command": report_command,
        "run_id": report_run_id,
        "exit_code": report_exit_code,
        "report_generated_at": str(report.get("generated_at") or "").strip(),
        "report_identity_verified": bool(report_run_id) and generated_at_fresh,
        "wheel_built": report.get("wheel_built") is True,
        "wheel_installed": report.get("wheel_installed") is True,
        "venv_fallback_used": report.get("venv_fallback_used") is True,
        "venv_error": str(report.get("venv_error") or "").strip(),
        "source_tree_cwd_used": report.get("source_tree_cwd_used") is True,
        "source_tree_hygiene_checked": report.get("source_tree_hygiene_checked")
        is True,
        "source_tree_hygiene_clean": report.get("source_tree_hygiene_clean") is True,
        "source_tree_generated_artifacts": report.get("source_tree_generated_artifacts")
        if isinstance(report.get("source_tree_generated_artifacts"), list)
        else [],
        "source_tree_post_build_hygiene_clean": report.get(
            "source_tree_post_build_hygiene_clean"
        )
        is True,
        "source_tree_post_build_generated_artifacts": report.get(
            "source_tree_post_build_generated_artifacts"
        )
        if isinstance(report.get("source_tree_post_build_generated_artifacts"), list)
        else [],
        "pythonpath_clean": report.get("pythonpath_clean") is True,
        "installed_media_slice_ready": installed_media_slice_ready,
        "installed_media_gate_fail_closed": installed_media_gate_fail_closed,
        "installed_media_gate_verified": installed_media_gate_verified,
        "installed_media_gate_lines": installed_media_gate_lines,
        "installed_llm_release_ready": installed_llm_release_ready,
        "installed_llm_manifest_gate_verified": installed_llm_manifest_gate_verified,
        "installed_llm_fresh_home_fail_closed": installed_llm_fresh_home_fail_closed,
        "installed_llm_gate_verified": installed_llm_gate_verified,
        "installed_llm_gate_lines": installed_llm_gate_lines,
        "script_path": report_script_path,
        "script_sha256": script_sha256,
        "script_identity_verified": script_identity_verified,
        "hermes_entrypoint": str(report.get("hermes_entrypoint") or "").strip(),
        "hermes_entrypoint_found": report.get("hermes_entrypoint_found") is True,
        "hermes_entrypoint_path": hermes_entrypoint_path,
        "cli_command_count": int(report.get("cli_command_count") or 0),
        "cli_exit_codes": transcript_cli_exit_codes,
        "cli_status_after_install_enabled": (
            lifecycle_checks["cli_status_after_install_enabled"] is True
        ),
        "cli_install_enabled": lifecycle_checks["cli_install_enabled"] is True,
        "cli_disable_keeps_plugin": (
            lifecycle_checks["cli_disable_keeps_plugin"] is True
        ),
        "cli_status_after_disable_guides_enable": (
            lifecycle_checks["cli_status_after_disable_guides_enable"] is True
        ),
        "cli_status_after_enable_enabled": (
            lifecycle_checks["cli_status_after_enable_enabled"] is True
        ),
        "cli_enable_restores_mode": (
            lifecycle_checks["cli_enable_restores_mode"] is True
        ),
        "cli_proposal_status_safe_refs": (
            lifecycle_checks["cli_proposal_status_safe_refs"] is True
            and report.get("cli_proposal_status_safe_refs") is True
        ),
        "cli_proposal_approve_audited": (
            lifecycle_checks["cli_proposal_approve_audited"] is True
            and report.get("cli_proposal_approve_audited") is True
        ),
        "cli_proposal_approve_rollout_guidance": (
            lifecycle_checks["cli_proposal_approve_rollout_guidance"] is True
            and report.get("cli_proposal_approve_rollout_guidance") is True
        ),
        "cli_proposal_reject_audited": (
            lifecycle_checks["cli_proposal_reject_audited"] is True
            and report.get("cli_proposal_reject_audited") is True
        ),
        "cli_proposal_resolutions_persisted": (
            lifecycle_checks["cli_proposal_resolutions_persisted"] is True
            and report.get("cli_proposal_resolutions_persisted") is True
        ),
        "cli_proposal_raw_ids_hidden": (
            lifecycle_checks["cli_proposal_raw_ids_hidden"] is True
            and report.get("cli_proposal_raw_ids_hidden") is True
        ),
        "cli_proposal_no_durable_apply_warning": (
            lifecycle_checks["cli_proposal_no_durable_apply_warning"] is True
            and report.get("cli_proposal_no_durable_apply_warning") is True
        ),
        "cli_uninstall_disables_plugin": (
            lifecycle_checks["cli_uninstall_disables_plugin"] is True
        ),
        "cli_status_after_uninstall_guides_install": (
            lifecycle_checks["cli_status_after_uninstall_guides_install"] is True
        ),
        "commands_verified": commands_verified,
        "commands_digest": commands_digest,
        "commands_digest_verified": commands_digest_verified,
        "source_report_path": str(path),
    }


def _non_visual_regression_release_gate_check_from_report(
    *,
    report_path: str,
    command: str | None,
    run_id: str | None,
    passed_count: int | None,
    visual_quota_used: bool,
) -> dict[str, Any]:
    path = Path(report_path).expanduser().resolve()
    base = {
        "command": str(command or "non-visual regression").strip()
        or "non-visual regression",
        "run_id": str(run_id or "").strip(),
        "passed_count": passed_count,
        "visual_quota_used": visual_quota_used,
        "source_report_path": str(path),
    }
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            **base,
            "status": "report_unreadable",
            "evidence": f"non-visual regression report could not be read: {exc.__class__.__name__}",
        }
    if not isinstance(report, dict):
        return {
            **base,
            "status": "report_invalid",
            "evidence": "non-visual regression report is not a JSON object",
        }

    report_command = str(report.get("command") or "").strip()
    report_run_id = str(report.get("run_id") or "").strip()
    try:
        report_exit_code = int(report.get("exit_code"))
    except (TypeError, ValueError):
        report_exit_code = None
    try:
        report_passed_count = int(report.get("passed_count"))
    except (TypeError, ValueError):
        report_passed_count = None
    try:
        report_failed_count = int(report.get("failed_count"))
    except (TypeError, ValueError):
        report_failed_count = None
    report_suite_coverage = _non_visual_regression_suite_coverage(report)
    missing_suite_coverage = _non_visual_regression_missing_suite_coverage(
        report_suite_coverage
    )
    report_visual_quota_used = report.get("visual_quota_used") is True
    report_digest = str(report.get("report_digest") or "").strip()
    report_digest_verified = (
        bool(report_digest) and report_digest == _release_report_digest(report)
    )
    generated_at_fresh, _reason = _readiness_generated_at_is_fresh(
        report.get("generated_at")
    )
    supplied_command = str(command or "").strip()
    supplied_run_id = str(run_id or "").strip()
    claims_match = (
        (not supplied_command or supplied_command == report_command)
        and (not supplied_run_id or supplied_run_id == report_run_id)
        and (passed_count is None or passed_count == report_passed_count)
        and visual_quota_used == report_visual_quota_used
    )
    base_passed = (
        report.get("schema_version") == 1
        and str(report.get("kind") or "").strip()
        == "raphael_non_visual_regression"
        and generated_at_fresh
        and bool(report_command)
        and bool(report_run_id)
        and report_exit_code == 0
        and isinstance(report_passed_count, int)
        and report_passed_count > 0
        and report_failed_count == 0
        and not missing_suite_coverage
        and report_visual_quota_used is False
        and claims_match
    )
    passed = base_passed and report_digest_verified
    status = "pass" if passed else "fail"
    if base_passed and not report_digest_verified:
        status = "report_digest_unverified"
    return {
        "status": status,
        "evidence": "non-visual Raphael regression report verified without media quota"
        if passed
        else "non-visual regression report failed release validation",
        "command": report_command,
        "run_id": supplied_run_id or report_run_id,
        "exit_code": report_exit_code,
        "passed_count": report_passed_count,
        "failed_count": report_failed_count,
        "suite_coverage": list(report_suite_coverage),
        "missing_suite_coverage": list(missing_suite_coverage),
        "visual_quota_used": report_visual_quota_used,
        "report_digest": report_digest,
        "report_digest_verified": report_digest_verified,
        "report_generated_at": str(report.get("generated_at") or "").strip(),
        "report_identity_verified": bool(report_run_id)
        and generated_at_fresh
        and claims_match,
        "source_report_path": str(path),
    }


def _release_docs_audit_release_gate_check(
    *,
    llm_readiness_path: Path | None = None,
    media_readiness_path: Path | None = None,
    llm_readiness: Mapping[str, Any] | None = None,
    media_readiness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    release_audit_doc = repo_root / "docs" / "raphael-release-slice-audit.md"
    llm_slice_doc = repo_root / "docs" / "raphael-llm-public-slice.md"
    llm_readiness_path = _existing_readiness_path(
        llm_readiness_path or _release_readiness_evidence_path("llm"),
        profile="llm",
    )
    media_readiness_path = _existing_readiness_path(
        media_readiness_path or _release_readiness_evidence_path("media"),
        profile="media",
    )
    try:
        from scripts.raphael_release_docs_audit import audit_release_docs

        result = audit_release_docs(
            release_audit_doc=release_audit_doc.read_text(encoding="utf-8"),
            llm_slice_doc=llm_slice_doc.read_text(encoding="utf-8"),
            llm_readiness=llm_readiness
            if llm_readiness is not None
            else _read_json_mapping(llm_readiness_path),
            media_readiness=media_readiness
            if media_readiness is not None
            else _read_json_mapping(media_readiness_path),
        )
        violations = result.violations
    except Exception as exc:
        violations = (f"audit_error:{exc.__class__.__name__}",)
    passed = not violations
    return {
        "status": "pass" if passed else "fail",
        "evidence": "release docs audit passed"
        if passed
        else "release docs audit failed",
        "command": "scripts/raphael_release_docs_audit.py",
        "run_id": "release-docs-audit-"
        + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        "violations": list(violations),
        "source_doc_paths": [str(release_audit_doc), str(llm_slice_doc)],
        "source_readiness_paths": [str(llm_readiness_path), str(media_readiness_path)],
    }


def _completion_audit_release_gate_check(
    *,
    profile: str,
    checks: Mapping[str, Any],
    media_release_scope: str = "",
    remaining_media_gaps: tuple[str, ...] = (),
) -> dict[str, Any]:
    try:
        from scripts.raphael_completion_audit import audit_completion

        if profile == "media":
            llm_readiness = _read_existing_readiness_mapping("llm")
            media_readiness = _completion_candidate_readiness(
                profile="media",
                checks=checks,
                media_release_scope=media_release_scope,
                remaining_media_gaps=remaining_media_gaps,
            )
        else:
            llm_readiness = _completion_candidate_readiness(
                profile="llm",
                checks=checks,
            )
            media_readiness = _read_existing_readiness_mapping("media")
        result = audit_completion(
            llm_readiness=llm_readiness,
            media_readiness=media_readiness,
            boundary_summary={},
        )
        blockers = result.blockers
        audit_status = result.status
        scoped_release_ready = result.scoped_release_ready
        ultimate_ready = result.ultimate_ready
        progress_percent = result.progress_percent
        progress_layers = _json_safe_progress_layers(result.progress_layers)
    except Exception as exc:
        blockers = (f"audit_error:{exc.__class__.__name__}",)
        audit_status = "blocked"
        scoped_release_ready = False
        ultimate_ready = False
        progress_percent = 0
        progress_layers = []
    passed = scoped_release_ready
    return {
        "status": "pass" if passed else "fail",
        "evidence": "completion audit verified scoped release boundary"
        if passed
        else "completion audit blocked scoped release boundary",
        "command": "scripts/raphael_completion_audit.py --target scoped",
        "run_id": "completion-audit-"
        + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        "audit_status": audit_status,
        "scoped_release_ready": scoped_release_ready,
        "ultimate_ready": ultimate_ready,
        "progress_percent": progress_percent,
        "progress_layers": progress_layers,
        "blockers": list(blockers),
    }


def _json_safe_progress_layers(
    layers: tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    safe_layers: list[dict[str, Any]] = []
    for layer in layers:
        safe_layer = dict(layer)
        safe_layer["evidence"] = list(safe_layer.get("evidence") or [])
        safe_layer["gaps"] = list(safe_layer.get("gaps") or [])
        safe_layers.append(safe_layer)
    return safe_layers


def _release_slice_manifest_release_gate_check(
    *,
    checks: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        from scripts.raphael_release_slice_boundary import git_status_paths
        from scripts.raphael_release_slice_manifest import build_release_slice_manifest

        manifest = build_release_slice_manifest(
            git_status_paths(),
            llm_readiness=_completion_candidate_readiness(
                profile="llm",
                checks=checks,
            ),
            media_readiness=_read_existing_readiness_mapping("media"),
            root=Path(__file__).resolve().parents[1],
        )
    except Exception as exc:
        manifest = {
            "status": "blocked",
            "review_strategy": "manifest_error",
            "blockers": [f"manifest_error:{exc.__class__.__name__}"],
            "counts": {},
            "slices": [],
            "allowed_public_claims": [],
            "blocked_public_claims": [],
        }
    counts = manifest.get("counts") if isinstance(manifest.get("counts"), Mapping) else {}
    blockers = manifest.get("blockers") if isinstance(manifest.get("blockers"), list) else []
    passed = (
        manifest.get("status") == "reviewable"
        and "llm_only" in _string_list_from_any(manifest.get("allowed_public_claims"))
        and counts.get("unclassified_paths") == 0
        and counts.get("content_violations") == 0
        and _manifest_has_slice(manifest, "llm_scoped_release", True)
        and _manifest_has_slice(manifest, "deferred_media", False)
    )
    return {
        "status": "pass" if passed else "fail",
        "evidence": "release slice manifest verified reviewer handoff"
        if passed
        else "release slice manifest blocked reviewer handoff",
        "command": "scripts/raphael_release_slice_manifest.py --from-git-status",
        "run_id": "release-slice-manifest-"
        + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        "manifest_status": str(manifest.get("status") or ""),
        "review_strategy": str(manifest.get("review_strategy") or ""),
        "allowed_public_claims": list(
            _string_list_from_any(manifest.get("allowed_public_claims"))
        ),
        "blocked_public_claims": list(
            _string_list_from_any(manifest.get("blocked_public_claims"))
        ),
        "counts": dict(counts),
        "slices": _manifest_slice_summaries(manifest),
        "blockers": list(blockers),
    }


def _completion_candidate_readiness(
    *,
    profile: str,
    checks: Mapping[str, Any],
    media_release_scope: str = "",
    remaining_media_gaps: tuple[str, ...] = (),
) -> dict[str, Any]:
    if profile == "media":
        verified_capabilities = [
            str(item.get("capability_id") or "").strip()
            for item in _verified_media_capabilities(
                media_release_scope,
                remaining_media_gaps,
            )
            if str(item.get("capability_id") or "").strip()
        ]
        public_release_ready = bool(media_release_scope)
        full_media_ready = public_release_ready and not remaining_media_gaps
        release_state = (
            "ready_for_public_release"
            if full_media_ready
            else "ready_for_limited_media_public_release"
            if public_release_ready
            else "blocked_readiness_evidence_missing"
        )
        return {
            "profile": "media",
            "release_state": release_state,
            "public_release_ready": public_release_ready,
            "limited_media_release_ready": public_release_ready,
            "full_media_release_ready": full_media_ready,
            "public_claim_scope": media_release_scope,
            "media_release_scope": media_release_scope,
            "remaining_media_gaps": list(remaining_media_gaps),
            "verified_media_capabilities": verified_capabilities,
            "checks": dict(checks),
        }
    return {
        "profile": "llm",
        "release_state": "ready_for_llm_only_release",
        "public_release_ready": True,
        "public_claim_scope": "llm_only",
        "checks": dict(checks),
    }


def _read_existing_readiness_mapping(profile: str) -> Mapping[str, Any]:
    path = _release_readiness_evidence_path(profile)
    if not path.exists():
        return {}
    try:
        return _read_json_mapping(path)
    except Exception:
        return {}


def _read_json_mapping(path: Path) -> Mapping[str, Any]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    return parsed if isinstance(parsed, Mapping) else {}


def _existing_readiness_path(path: Path, *, profile: str) -> Path:
    if path.exists():
        return path
    fallback = Path.home() / ".hermes" / "raphael" / f"release_readiness.{profile}.json"
    return fallback if fallback.exists() else path


def _source_report_path_evidence(report_path: str | None) -> dict[str, str]:
    path_text = str(report_path or "").strip()
    if not path_text:
        return {}
    path = Path(path_text)
    return {"source_report_path": str(path.resolve() if path.exists() else path)}


def _readiness_log_paths() -> tuple[Path, ...]:
    logs_dir = get_hermes_home() / "logs"
    if not logs_dir.exists():
        return ()
    return tuple(
        path
        for path in sorted(logs_dir.glob("agent.log*"))
        if path.is_file()
    )


def _visual_release_gate_check(
    *,
    run_id: str | None,
    command: str | None,
    report_path: str | None,
    selected_artifact_id: str | None,
    artifact_quality_verdict: str | None,
    fresh_artifact: bool,
) -> dict[str, Any] | None:
    if str(report_path or "").strip():
        return _visual_release_gate_check_from_report(
            report_path=str(report_path or "").strip(),
            run_id=run_id,
            command=command,
            selected_artifact_id=selected_artifact_id,
            artifact_quality_verdict=artifact_quality_verdict,
        )
    if not str(selected_artifact_id or "").strip():
        return None
    return {
        "status": "pass",
        "evidence": "fresh selected artifact verified after current visual submit",
        "command": str(command or "visual live e2e").strip() or "visual live e2e",
        "run_id": str(run_id or "").strip()
        or "visual-live-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        "fresh_artifact": fresh_artifact,
        "selected_artifact_id": str(selected_artifact_id).strip(),
        "artifact_quality_verdict": str(artifact_quality_verdict or "").strip(),
    }


def _visual_preflight_release_gate_check(
    *,
    report_path: str | None,
    command: str | None,
) -> dict[str, Any] | None:
    path_text = str(report_path or "").strip()
    if not path_text:
        return None
    path = Path(path_text).expanduser().resolve()
    command_text = str(command or "scripts/grok_web_imagine_live_e2e.py --preflight-only").strip()
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "status": "fail",
            "evidence": f"visual preflight report could not be read: {exc.__class__.__name__}",
            "command": command_text,
            "run_id": "visual-preflight-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
            "source_report_path": str(path),
        }
    if not isinstance(report, dict):
        return {
            "status": "fail",
            "evidence": "visual preflight report is not a JSON object",
            "command": command_text,
            "run_id": "visual-preflight-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
            "source_report_path": str(path),
        }
    provenance_error = _visual_preflight_provenance_error(report)
    if provenance_error:
        report_run_id = str(report.get("run_id") or "").strip()
        report_status = str(report.get("status") or "").strip().lower()
        return {
            "status": "preflight_unverified",
            "evidence": f"visual preflight report did not prove quota-free preflight: {provenance_error}",
            "command": command_text,
            "run_id": report_run_id
            or "visual-preflight-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
            "report_run_id": report_run_id,
            "report_generated_at": str(report.get("generated_at") or "").strip(),
            "provider_mode": str(report.get("provider_mode") or "").strip(),
            "provider_success": report.get("success") is True,
            "report_status": report_status,
            "requires_operator_setup": False,
            "failure_class": provenance_error,
            "error": provenance_error,
            "source_report_path": str(path),
        }
    if report.get("success") is True:
        report_run_id = str(report.get("run_id") or "").strip()
        report_status = str(report.get("status") or "").strip().lower()
        return {
            "status": "preflight_ready",
            "evidence": "visual preflight ready; live visual E2E artifact is still required",
            "command": command_text,
            "run_id": report_run_id
            or "visual-preflight-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
            "report_run_id": report_run_id,
            "report_generated_at": str(report.get("generated_at") or "").strip(),
            "provider_mode": str(report.get("provider_mode") or "").strip(),
            "provider_success": True,
            "report_status": report_status,
            "requires_operator_setup": False,
            "source_report_path": str(path),
        }
    report_status = str(report.get("status") or "").strip().lower()
    failure_class = str(
        report.get("failure_class") or report.get("error_type") or report_status or "failed"
    ).strip()
    error = str(report.get("error") or "").strip()
    requires_setup = report.get("requires_operator_setup") is True or any(
        marker in f"{failure_class} {error}".lower()
        for marker in ("browser", "cdp", "quota", "subscription", "auth", "login", "credential")
    )
    report_run_id = str(report.get("run_id") or "").strip()
    return {
        "status": "setup_required" if requires_setup else "fail",
        "evidence": "visual preflight blocked"
        + (f": {failure_class}" if failure_class else "")
        + (f": {error}" if error else ""),
        "command": command_text,
        "run_id": report_run_id
        or "visual-preflight-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        "report_run_id": report_run_id,
        "report_generated_at": str(report.get("generated_at") or "").strip(),
        "provider_mode": str(report.get("provider_mode") or "").strip(),
        "provider_success": False,
        "report_status": report_status,
        "requires_operator_setup": requires_setup,
        "failure_class": failure_class,
        "error": error,
        "source_report_path": str(path),
    }


def _visual_preflight_provenance_error(report: dict[str, Any]) -> str:
    generated_at_fresh, generated_at_reason = _readiness_generated_at_is_fresh(
        report.get("generated_at")
    )
    if not generated_at_fresh:
        return generated_at_reason
    if (
        report.get("success") is True
        and str(report.get("status") or "").strip().lower() != "preflight_ready"
    ):
        return "preflight_status_not_ready"
    if str(report.get("provider_mode") or "").strip() != "grok-web-imagine-live":
        return "provider_mode_unverified"
    checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
    if checks.get("generation_called") is not False:
        return "generation_called_not_false"
    if checks.get("provider_preflight") is not True:
        return "provider_preflight_not_true"
    browser_preflight = (
        report.get("browser_preflight")
        if isinstance(report.get("browser_preflight"), dict)
        else {}
    )
    if not browser_preflight:
        return "browser_preflight_missing"
    if not str(browser_preflight.get("status") or "").strip():
        return "browser_preflight_status_missing"
    if report.get("success") is True and (
        browser_preflight.get("ready") is not True
        or browser_preflight.get("safe_to_submit") is not True
    ):
        return "browser_preflight_ready_unverified"
    quota_markers = [
        report.get("quota_used"),
        browser_preflight.get("quota_used"),
    ]
    if any(value is True for value in quota_markers):
        return "quota_used_not_false"
    if not any(value is False for value in quota_markers):
        return "quota_used_missing"
    if report.get("success") is True:
        prompt_probe = (
            browser_preflight.get("prompt_probe")
            if isinstance(browser_preflight.get("prompt_probe"), dict)
            else {}
        )
        if not prompt_probe:
            return "prompt_probe_missing"
        if prompt_probe.get("attempted") is not True:
            return "prompt_probe_not_attempted"
        if prompt_probe.get("prompt_text_present") is not True:
            return "prompt_text_unverified"
        if prompt_probe.get("submit_enabled") is not True:
            return "submit_enabled_unverified"
    return ""


def _visual_release_gate_check_from_report(
    *,
    report_path: str,
    run_id: str | None,
    command: str | None,
    selected_artifact_id: str | None,
    artifact_quality_verdict: str | None,
) -> dict[str, Any]:
    path = Path(report_path).expanduser().resolve()
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "status": "fail",
            "evidence": f"visual live E2E report could not be read: {exc.__class__.__name__}",
            "command": str(command or "scripts/grok_web_imagine_live_e2e.py").strip()
            or "scripts/grok_web_imagine_live_e2e.py",
            "run_id": str(run_id or "").strip()
            or "visual-live-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
            "source_report_path": str(path),
        }
    if not isinstance(report, dict):
        return {
            "status": "fail",
            "evidence": "visual live E2E report is not a JSON object",
            "command": str(command or "scripts/grok_web_imagine_live_e2e.py").strip()
            or "scripts/grok_web_imagine_live_e2e.py",
            "run_id": str(run_id or "").strip()
            or "visual-live-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
            "source_report_path": str(path),
        }

    report_success = report.get("success") is True
    report_status = str(report.get("status") or "").strip().lower()
    if not report_success:
        failure_class = str(
            report.get("failure_class") or report.get("error_type") or report_status or "failed"
        ).strip()
        error = str(report.get("error") or "").strip()
        requires_setup = report.get("requires_operator_setup") is True or any(
            marker in f"{failure_class} {error}".lower()
            for marker in ("quota", "subscription", "auth", "login", "credential")
        )
        report_run_id = str(report.get("run_id") or "").strip()
        return {
            "status": "setup_required" if requires_setup else "fail",
            "evidence": "visual live E2E failed"
            + (f": {failure_class}" if failure_class else "")
            + (f": {error}" if error else ""),
            "command": str(command or "scripts/grok_web_imagine_live_e2e.py").strip()
            or "scripts/grok_web_imagine_live_e2e.py",
            "run_id": str(run_id or "").strip()
            or report_run_id
            or "visual-live-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
            "report_run_id": report_run_id,
            "report_generated_at": str(report.get("generated_at") or "").strip(),
            "provider_mode": str(report.get("provider_mode") or "").strip(),
            "provider_success": False,
            "report_status": report_status,
            "requires_operator_setup": requires_setup,
            "failure_class": failure_class,
            "error": error,
            "source_report_path": str(path),
        }

    artifact = report.get("artifact") if isinstance(report.get("artifact"), dict) else {}
    provider = report.get("provider") if isinstance(report.get("provider"), dict) else {}
    provider_result = (
        report.get("provider_result")
        if isinstance(report.get("provider_result"), dict)
        else {}
    )
    self_review = report.get("self_review") if isinstance(report.get("self_review"), dict) else {}
    request = report.get("request") if isinstance(report.get("request"), dict) else {}
    video_source = (
        report.get("video_source") if isinstance(report.get("video_source"), dict) else {}
    )
    quality_evidence = _visual_report_quality_evidence(
        report,
        artifact,
        live_report_path=path,
    )
    report_quality_verdict = str(quality_evidence.get("verdict") or "").strip()
    artifact_path = str(artifact.get("path") or "").strip()
    report_generated_at = str(report.get("generated_at") or "").strip()
    durable_history_verified = (
        artifact.get("history_verified") is True
        or self_review.get("durable_history_verified") is True
    )
    artifact_exists = artifact.get("exists") is True and bool(
        artifact_path and Path(artifact_path).exists()
    )
    artifact_mtime_verified, artifact_mtime, artifact_mtime_reason = (
        _visual_artifact_mtime_evidence(
            artifact_path=artifact_path,
            report_generated_at=report_generated_at,
        )
    )
    page_url = str(artifact.get("page_url") or report.get("page_url") or "").strip()
    history_entry_id = str(
        report.get("history_entry_id") or artifact.get("history_entry_id") or ""
    ).strip()
    result_surface_id = page_url or str(
        report.get("result_surface_id")
        or artifact.get("result_surface_id")
        or history_entry_id
        or artifact.get("history_entry_id")
        or ""
    ).strip()
    report_run_id = str(report.get("run_id") or "").strip()
    report_command = str(report.get("command") or "").strip()
    supplied_run_id = str(run_id or "").strip()
    report_fresh, _report_fresh_reason = _readiness_generated_at_is_fresh(
        report_generated_at
    )
    report_identity_verified = bool(report_run_id) and report_fresh and (
        not supplied_run_id or supplied_run_id == report_run_id
    )
    report_provenance_error = _visual_live_report_provenance_error(report)
    if (
        not report_provenance_error
        and not _visual_supplied_command_matches_report(command, report)
    ):
        report_provenance_error = "supplied_command_mismatch"
    report_provenance_verified = not report_provenance_error
    fresh_artifact = (
        report_success
        and report_status == "completed"
        and report_identity_verified
        and artifact_exists
        and artifact_mtime_verified
        and durable_history_verified
        and bool(result_surface_id)
    )
    operation = str(request.get("operation") or report.get("operation") or "").strip()
    artifact_media_type = _visual_artifact_media_type(
        artifact_path=artifact_path,
        operation=operation,
    )
    image_first_source = _visual_image_first_source_evidence(video_source)
    return {
        "status": "pass",
        "evidence": "fresh selected artifact verified after current visual submit",
        "command": str(
            command
            or report_command
            or "scripts/grok_web_imagine_live_e2e.py"
        ).strip()
        or "scripts/grok_web_imagine_live_e2e.py",
        "run_id": supplied_run_id or report_run_id
        or "visual-live-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        "report_run_id": report_run_id,
        "report_generated_at": report_generated_at,
        "report_identity_verified": report_identity_verified,
        "report_provenance_verified": report_provenance_verified,
        "report_provenance_error": report_provenance_error,
        "report_digest": str(report.get("report_digest") or "").strip(),
        "report_digest_verified": report_provenance_verified,
        "report_kind": str(report.get("kind") or "").strip(),
        "report_producer": str(report.get("producer") or "").strip(),
        "script_path": str(report.get("script_path") or "").strip(),
        "script_sha256": str(report.get("script_sha256") or "").strip(),
        "script_identity_verified": report.get("script_identity_verified") is True,
        "fresh_artifact": fresh_artifact,
        "selected_artifact_id": str(selected_artifact_id or artifact_path).strip(),
        "artifact_quality_verdict": report_quality_verdict,
        "quality_review_source": str(quality_evidence.get("source") or "").strip(),
        "quality_review_reviewer": str(quality_evidence.get("reviewer") or "").strip(),
        "quality_review_run_id": str(quality_evidence.get("run_id") or "").strip(),
        "quality_review_generated_at": str(
            quality_evidence.get("generated_at") or ""
        ).strip(),
        "quality_review_source_report_path": str(
            quality_evidence.get("source_report_path") or ""
        ).strip(),
        "quality_review_artifact_match": quality_evidence.get("artifact_match") is True,
        "quality_review_artifact_sha256": str(
            quality_evidence.get("artifact_sha256") or ""
        ).strip(),
        "quality_review_artifact_size_bytes": quality_evidence.get(
            "artifact_size_bytes"
        ),
        "quality_review_artifact_mtime": quality_evidence.get("artifact_mtime"),
        "quality_review_artifact_identity_verified": quality_evidence.get(
            "artifact_identity_verified"
        )
        is True,
        "quality_review_source_type": str(
            quality_evidence.get("review_source_type") or ""
        ).strip(),
        "quality_review_model_provider": str(
            quality_evidence.get("review_model_provider") or ""
        ).strip(),
        "quality_review_model": str(quality_evidence.get("review_model") or "").strip(),
        "quality_review_evidence_digest": str(
            quality_evidence.get("review_evidence_digest") or ""
        ).strip(),
        "quality_review_response_id": str(
            quality_evidence.get("review_response_id") or ""
        ).strip(),
        "quality_review_transcript_report_path": str(
            quality_evidence.get("review_transcript_report_path") or ""
        ).strip(),
        "quality_review_transcript_digest": str(
            quality_evidence.get("review_transcript_digest") or ""
        ).strip(),
        "quality_review_provenance_verified": quality_evidence.get(
            "review_provenance_verified"
        )
        is True,
        "quality_review_dimensions_verified": quality_evidence.get("dimensions_verified")
        is True,
        "provider_mode": str(report.get("provider_mode") or "").strip(),
        "provider_name": str(provider.get("name") or "").strip(),
        "provider_model": str(provider.get("model") or "").strip(),
        "provider_result_provider": str(provider_result.get("provider") or "").strip(),
        "provider_result_model": str(provider_result.get("model") or "").strip(),
        "provider_result_response_id": _provider_result_response_id(provider_result),
        "provider_success": report_success,
        "report_status": report_status,
        "artifact_path": artifact_path,
        "artifact_media_type": artifact_media_type,
        "image_first_source_verified": image_first_source["verified"],
        "openai_source_image_verified": image_first_source["openai_verified"],
        "source_image_artifact_id": image_first_source["artifact_id"],
        "source_image_path": image_first_source["path"],
        "source_image_policy": image_first_source["policy"],
        "source_image_source": image_first_source["source"],
        "source_image_durability": image_first_source["durability"],
        "source_image_result_surface_id": image_first_source["result_surface_id"],
        "source_image_provider_result_response_id": image_first_source[
            "provider_result_response_id"
        ],
        "source_image_artifact_sha256": image_first_source["sha256"],
        "source_image_artifact_size_bytes": image_first_source["size_bytes"],
        "source_image_artifact_mtime": image_first_source["mtime"],
        "source_image_artifact_identity_verified": image_first_source[
            "identity_verified"
        ],
        "source_image_quality_verdict": image_first_source["quality_verdict"],
        "source_image_quality_identity_verified": image_first_source[
            "quality_identity_verified"
        ],
        "source_image_ranked_selected": image_first_source["ranked_selected"],
        "single_video_source_image": image_first_source["single_source_image"],
        "video_source_image_count": image_first_source["image_count"],
        "artifact_exists": artifact_exists,
        "artifact_mtime_verified": artifact_mtime_verified,
        "artifact_mtime": artifact_mtime,
        "artifact_mtime_reason": artifact_mtime_reason,
        "artifact_source": str(artifact.get("source") or "").strip(),
        "artifact_durability": str(artifact.get("durability") or "").strip(),
        "durable_history_verified": durable_history_verified,
        "page_url": page_url,
        "history_entry_id": history_entry_id,
        "result_surface_id": result_surface_id,
        "operation": operation,
        "source_report_path": str(path),
    }


def _visual_image_first_source_evidence(video_source: dict[str, Any]) -> dict[str, Any]:
    artifact_id = str(
        video_source.get("source_image_artifact_id")
        or video_source.get("ranked_selected_image_artifact_id")
        or video_source.get("video_source_artifact_id")
        or ""
    ).strip()
    source_path = str(
        video_source.get("source_image_path")
        or video_source.get("selected_source_image")
        or video_source.get("video_source_image")
        or ""
    ).strip()
    try:
        image_count = int(video_source.get("video_source_image_count"))
    except (TypeError, ValueError):
        image_count = 1 if source_path else 0
    source_exists = bool(source_path) and Path(source_path).expanduser().exists()
    ranked_selected = (
        video_source.get("uses_ranked_selected_image") is True
        or bool(str(video_source.get("ranked_selected_image_artifact_id") or "").strip())
    )
    single_source_image = (
        video_source.get("single_video_source_image") is True
        or image_count == 1
    )
    verified = bool(
        artifact_id
        and source_path
        and source_exists
        and ranked_selected
        and single_source_image
        and image_count == 1
    )
    source = str(video_source.get("source_image_source") or "").strip()
    durability = str(video_source.get("source_image_durability") or "").strip()
    result_surface_id = str(
        video_source.get("source_image_result_surface_id") or ""
    ).strip()
    provider_result_response_id = str(
        video_source.get("source_image_provider_result_response_id") or ""
    ).strip()
    identity = _visual_quality_artifact_identity(
        artifact_path=source_path,
        quality_report={
            "artifact_identity_verified": (
                video_source.get("source_image_artifact_identity_verified") is True
            ),
            "artifact_sha256": str(
                video_source.get("source_image_artifact_sha256") or ""
            ).strip(),
            "artifact_size_bytes": video_source.get("source_image_artifact_size_bytes"),
            "artifact_mtime": video_source.get("source_image_artifact_mtime"),
        },
    )
    quality_verdict = str(
        video_source.get("source_image_quality_verdict") or ""
    ).strip()
    quality_identity_verified = (
        video_source.get("source_image_quality_identity_verified") is True
    )
    openai_verified = bool(
        verified
        and source == "openai_response"
        and _visual_artifact_durability_verified(
            provider_mode="openai-gpt-image-live",
            artifact_durability=durability,
            page_url="",
        )
        and _has_verified_openai_result_surface(
            result_surface_id=result_surface_id,
            history_entry_id="",
            provider_result_response_id=provider_result_response_id,
        )
        and identity["verified"]
        and quality_verdict == "pass"
        and quality_identity_verified
    )
    return {
        "verified": verified,
        "openai_verified": openai_verified,
        "artifact_id": artifact_id,
        "path": source_path,
        "policy": str(video_source.get("source_image_policy") or "").strip(),
        "source": source,
        "durability": durability,
        "result_surface_id": result_surface_id,
        "provider_result_response_id": provider_result_response_id,
        "sha256": identity["sha256"],
        "size_bytes": identity["size_bytes"],
        "mtime": identity["mtime"],
        "identity_verified": identity["verified"],
        "quality_verdict": quality_verdict,
        "quality_identity_verified": quality_identity_verified,
        "ranked_selected": ranked_selected,
        "single_source_image": single_source_image,
        "image_count": image_count,
    }


def _visual_report_quality_evidence(
    report: dict[str, Any],
    artifact: dict[str, Any],
    *,
    live_report_path: Path,
) -> dict[str, Any]:
    review = report.get("quality_review")
    if not isinstance(review, dict):
        return {}
    source_report_path = str(review.get("source_report_path") or "").strip()
    if not source_report_path:
        return {}
    quality_report_path = Path(source_report_path).expanduser().resolve()
    if quality_report_path == live_report_path.resolve():
        return {}
    try:
        quality_report = json.loads(quality_report_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(quality_report, dict):
        return {}
    generated_at_fresh, _reason = _readiness_generated_at_is_fresh(
        quality_report.get("generated_at")
    )
    if (
        quality_report.get("schema_version") != 1
        or str(quality_report.get("kind") or "").strip()
        != "raphael_visual_quality_review"
        or not generated_at_fresh
        or not _visual_quality_report_has_audit_trail(quality_report)
    ):
        return {}
    verdict = _visual_quality_verdict_text(quality_report)
    reviewer = str(
        quality_report.get("reviewer")
        or quality_report.get("reviewer_role")
        or quality_report.get("producer")
        or ""
    ).strip()
    artifact_path = str(artifact.get("path") or "").strip()
    review_artifact = str(
        quality_report.get("artifact_path")
        or quality_report.get("selected_artifact_id")
        or quality_report.get("artifact_id")
        or ""
    ).strip()
    artifact_match = bool(artifact_path) and review_artifact == artifact_path
    artifact_identity = _visual_quality_artifact_identity(
        artifact_path=artifact_path,
        quality_report=quality_report,
    )
    dimensions_verified = _visual_quality_review_dimensions_verified(
        quality_report.get("dimensions")
        or quality_report.get("checks")
        or quality_report.get("scores")
    )
    independent = _visual_quality_reviewer_is_independent(reviewer)
    if not (
        verdict
        and independent
        and artifact_match
        and artifact_identity["verified"]
        and dimensions_verified
    ):
        return {}
    return {
        "verdict": verdict,
        "source": "quality_review",
        "reviewer": reviewer,
        "run_id": str(quality_report.get("run_id") or "").strip(),
        "generated_at": str(quality_report.get("generated_at") or "").strip(),
        "source_report_path": str(quality_report_path),
        "artifact_match": artifact_match,
        "artifact_sha256": artifact_identity["sha256"],
        "artifact_size_bytes": artifact_identity["size_bytes"],
        "artifact_mtime": artifact_identity["mtime"],
        "artifact_identity_verified": artifact_identity["verified"],
        "review_source_type": str(
            quality_report.get("review_source_type") or ""
        ).strip(),
        "review_model_provider": str(
            quality_report.get("review_model_provider") or ""
        ).strip(),
        "review_model": str(quality_report.get("review_model") or "").strip(),
        "review_evidence_digest": str(
            quality_report.get("review_evidence_digest") or ""
        ).strip(),
        "review_response_id": str(
            quality_report.get("review_response_id") or ""
        ).strip(),
        "review_transcript_report_path": str(
            quality_report.get("review_transcript_report_path") or ""
        ).strip(),
        "review_transcript_digest": str(
            quality_report.get("review_transcript_digest") or ""
        ).strip(),
        "review_provenance_verified": (
            quality_report.get("review_provenance_verified") is True
        ),
        "dimensions_verified": dimensions_verified,
    }


def _visual_quality_artifact_identity(
    *,
    artifact_path: str,
    quality_report: dict[str, Any],
) -> dict[str, Any]:
    expected_sha256 = str(quality_report.get("artifact_sha256") or "").strip()
    try:
        expected_size = int(quality_report.get("artifact_size_bytes"))
    except (TypeError, ValueError):
        expected_size = -1
    try:
        expected_mtime = float(quality_report.get("artifact_mtime"))
    except (TypeError, ValueError):
        expected_mtime = -1.0
    path = Path(artifact_path) if artifact_path else None
    if (
        quality_report.get("artifact_identity_verified") is not True
        or not expected_sha256
        or expected_size < 0
        or expected_mtime <= 0
        or path is None
        or not path.is_file()
    ):
        return {
            "sha256": expected_sha256,
            "size_bytes": expected_size,
            "mtime": expected_mtime,
            "verified": False,
        }
    try:
        data = path.read_bytes()
        stat = path.stat()
    except OSError:
        return {
            "sha256": expected_sha256,
            "size_bytes": expected_size,
            "mtime": expected_mtime,
            "verified": False,
        }
    actual_sha256 = hashlib.sha256(data).hexdigest()
    actual_size = len(data)
    actual_mtime = float(stat.st_mtime)
    return {
        "sha256": expected_sha256,
        "size_bytes": expected_size,
        "mtime": expected_mtime,
        "verified": (
            actual_sha256 == expected_sha256
            and actual_size == expected_size
            and abs(actual_mtime - expected_mtime) < 0.001
        ),
    }


def _visual_quality_report_has_audit_trail(report: dict[str, Any]) -> bool:
    producer = str(report.get("producer") or "").strip()
    command = str(report.get("command") or "").strip()
    run_id = str(report.get("run_id") or "").strip()
    residual_risk = str(report.get("residual_risk") or "").strip()
    evidence = report.get("evidence")
    if not (
        producer == "hermes-visual-quality-review"
        and command
        and run_id
        and residual_risk
    ):
        return False
    if not isinstance(evidence, list):
        return False
    return any(str(item or "").strip() for item in evidence) and (
        _visual_quality_review_provenance_verified(report)
    )


def _visual_quality_review_provenance_verified(report: dict[str, Any]) -> bool:
    source_type = str(report.get("review_source_type") or "").strip().lower()
    provider = str(report.get("review_model_provider") or "").strip().lower()
    model = str(report.get("review_model") or "").strip()
    digest = str(report.get("review_evidence_digest") or "").strip()
    response_id = str(report.get("review_response_id") or "").strip()
    transcript_path = str(report.get("review_transcript_report_path") or "").strip()
    transcript_digest = str(report.get("review_transcript_digest") or "").strip()
    if report.get("review_provenance_verified") is not True or not digest:
        return False
    if source_type == "vision_model":
        return (
            provider.replace("_", "-") in {"openai", "openai-codex"}
            and bool(model)
            and response_id.startswith(
                ("resp_", "openai-response:", "codex-openai-vision-review:")
            )
            and _visual_quality_model_transcript_matches_report(
                report,
                transcript_path=transcript_path,
                transcript_digest=transcript_digest,
            )
        )
    return False


def _visual_quality_model_transcript_matches_report(
    report: dict[str, Any],
    *,
    transcript_path: str,
    transcript_digest: str,
) -> bool:
    if not transcript_path or not transcript_digest:
        return False
    path = Path(transcript_path).expanduser().resolve()
    try:
        text = path.read_text(encoding="utf-8")
        transcript = json.loads(text)
    except Exception:
        return False
    if not isinstance(transcript, dict):
        return False
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != transcript_digest:
        return False
    if transcript.get("schema_version") != 1:
        return False
    if str(transcript.get("kind") or "").strip() != "raphael_visual_quality_model_review":
        return False
    if str(transcript.get("producer") or "").strip() != "openai-gpt-vision-review":
        return False
    field_pairs = (
        ("response_id", "review_response_id"),
        ("review_model_provider", "review_model_provider"),
        ("review_model", "review_model"),
        ("artifact_path", "artifact_path"),
        ("artifact_sha256", "artifact_sha256"),
        ("artifact_quality_verdict", "artifact_quality_verdict"),
    )
    for transcript_field, report_field in field_pairs:
        if str(transcript.get(transcript_field) or "").strip() != str(
            report.get(report_field) or ""
        ).strip():
            return False
    try:
        transcript_size = int(transcript.get("artifact_size_bytes"))
        report_size = int(report.get("artifact_size_bytes"))
    except (TypeError, ValueError):
        return False
    if transcript_size != report_size:
        return False
    if not _visual_quality_review_dimensions_verified(transcript.get("dimensions")):
        return False
    if not _visual_quality_review_dimensions_verified(report.get("dimensions")):
        return False
    evidence = transcript.get("evidence")
    return isinstance(evidence, list) and any(str(item or "").strip() for item in evidence)


def _visual_quality_reviewer_key(value: str) -> str:
    text = str(value or "").strip().lower()
    normalized = "".join(character if character.isalnum() else "_" for character in text)
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized.strip("_")


def _visual_quality_reviewer_is_independent(value: str) -> bool:
    key = _visual_quality_reviewer_key(value)
    if key in _VISUAL_QUALITY_BLOCKED_REVIEWERS:
        return False
    return not any(
        _visual_quality_reviewer_key_contains_phrase(key, phrase)
        for phrase in _VISUAL_QUALITY_BLOCKED_REVIEWERS
        if phrase
    )


def _visual_quality_reviewer_key_contains_phrase(key: str, phrase: str) -> bool:
    return (
        key == phrase
        or key.startswith(f"{phrase}_")
        or key.endswith(f"_{phrase}")
        or f"_{phrase}_" in key
    )


def _visual_quality_verdict_text(source: dict[str, Any]) -> str:
    return str(
        source.get("artifact_quality_verdict")
        or source.get("quality_verdict")
        or source.get("visual_quality_verdict")
        or source.get("verdict")
        or ""
    ).strip()


def _visual_quality_review_dimensions_verified(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    required = (
        "composition",
        "prompt_adherence",
        "geometry",
        "subject_quality",
    )
    return all(_visual_quality_dimension_passed(value.get(key)) for key in required)


def _visual_quality_dimension_passed(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        score = float(value)
        return math.isfinite(score) and score >= 0.75
    return str(value or "").strip().lower() in {
        "pass",
        "passed",
        "accept",
        "accepted",
        "approved",
        "ok",
    }


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def _release_readiness_evidence_path(profile: str | None = None) -> Path:
    base_dir = get_hermes_home() / "raphael"
    normalized = _normalize_readiness_profile(profile or "")
    if profile and normalized in {"llm", "media"}:
        return base_dir / f"release_readiness.{normalized}.json"
    return base_dir / "release_readiness.json"


def _write_release_readiness_evidence(
    profile: str,
    payload: dict[str, Any],
) -> None:
    text = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    paths = (
        _release_readiness_evidence_path(profile),
        _release_readiness_evidence_path(),
    )
    old_contents: dict[Path, str | None] = {}
    written_paths: list[Path] = []
    for path in paths:
        old_contents[path] = (
            path.read_text(encoding="utf-8") if path.exists() else None
        )
    try:
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_text_atomic(path, text)
            written_paths.append(path)
    except Exception:
        for written_path in reversed(written_paths):
            old_text = old_contents[written_path]
            if old_text is None:
                try:
                    written_path.unlink()
                except FileNotFoundError:
                    pass
            else:
                _write_text_atomic(written_path, old_text)
        raise


def _write_text_atomic(path: Path, text: str) -> None:
    tmp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        tmp_path.write_text(text, encoding="utf-8")
        tmp_path.replace(path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def _clear_release_readiness_evidence() -> None:
    for path in (
        _release_readiness_evidence_path(),
        _release_readiness_evidence_path("llm"),
        _release_readiness_evidence_path("media"),
    ):
        try:
            path.unlink()
        except FileNotFoundError:
            continue


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _missing_readiness_evidence(required_checks: tuple[str, ...]) -> _ReadinessEvidence:
    return _ReadinessEvidence(
        check_statuses={check_name: "missing" for check_name in required_checks},
        blocking_reasons=tuple(f"{check_name}_missing" for check_name in required_checks),
    )


def _invalid_readiness_evidence(
    reason: str,
    required_checks: tuple[str, ...],
) -> _ReadinessEvidence:
    return _ReadinessEvidence(
        check_statuses={check_name: "invalid evidence" for check_name in required_checks},
        blocking_reasons=(reason,),
        evidence_invalid=True,
    )


def _readiness_release_state(
    blocking_reasons: list[str],
    evidence_invalid: bool,
    *,
    profile: str,
    remaining_scope_gaps: tuple[str, ...] = (),
) -> str:
    if not blocking_reasons:
        if profile == "media" and remaining_scope_gaps:
            return "ready_for_limited_media_public_release"
        if profile == "llm":
            return "ready_for_llm_only_release"
        return "ready_for_public_release"
    if evidence_invalid:
        return "blocked_readiness_evidence_invalid"
    if "raphael_plugin_disabled" in blocking_reasons or "raphael_mode_disabled" in blocking_reasons:
        return "blocked_runtime_setup"
    if (
        "visual_live_e2e_missing" in blocking_reasons
        or "visual_live_e2e_stale_or_unverified" in blocking_reasons
        or "visual_live_e2e_result_unverified" in blocking_reasons
        or "visual_live_e2e_quality_unverified" in blocking_reasons
        or "visual_live_e2e_setup_required" in blocking_reasons
        or "visual_live_e2e_preflight_ready" in blocking_reasons
        or "visual_live_e2e_preflight_unverified" in blocking_reasons
        or "visual_live_e2e_default_provider_unverified" in blocking_reasons
    ):
        return "blocked_visual_live_e2e_pending"
    if any(reason.startswith("media_scope_gap_") for reason in blocking_reasons):
        return "blocked_media_scope_incomplete"
    return "blocked_release_evidence_pending"


def _normalize_readiness_profile(profile: str) -> str:
    normalized = str(profile or "media").strip().lower().replace("_", "-")
    if normalized in {"llm", "llm-only", "text"}:
        return "llm"
    return "media"


def _required_readiness_checks(profile: str) -> tuple[str, ...]:
    return _LLM_READINESS_CHECKS if profile == "llm" else _MEDIA_READINESS_CHECKS


def _visual_live_e2e_has_quality_evidence(check: dict[str, Any]) -> bool:
    verdict = str(check.get("artifact_quality_verdict") or "").strip().lower()
    if not (
        bool(str(check.get("selected_artifact_id") or "").strip())
        and verdict in {"pass", "passed", "accept", "accepted", "approved"}
        and str(check.get("quality_review_source") or "").strip() == "quality_review"
        and bool(str(check.get("quality_review_reviewer") or "").strip())
        and bool(str(check.get("quality_review_run_id") or "").strip())
        and bool(str(check.get("quality_review_generated_at") or "").strip())
        and bool(str(check.get("quality_review_source_report_path") or "").strip())
        and check.get("quality_review_artifact_match") is True
        and bool(str(check.get("quality_review_artifact_sha256") or "").strip())
        and isinstance(check.get("quality_review_artifact_size_bytes"), int)
        and isinstance(check.get("quality_review_artifact_mtime"), (int, float))
        and check.get("quality_review_artifact_identity_verified") is True
        and bool(str(check.get("quality_review_evidence_digest") or "").strip())
        and check.get("quality_review_provenance_verified") is True
        and check.get("quality_review_dimensions_verified") is True
    ):
        return False
    source_type = str(check.get("quality_review_source_type") or "").strip()
    if source_type != "vision_model":
        return False
    return (
        str(check.get("quality_review_model_provider") or "").strip().lower()
        in {"openai", "openai-codex"}
        and bool(str(check.get("quality_review_model") or "").strip())
        and str(check.get("quality_review_response_id") or "").strip().startswith(
            ("resp_", "openai-response:", "codex-openai-vision-review:")
        )
        and bool(str(check.get("quality_review_transcript_report_path") or "").strip())
        and bool(str(check.get("quality_review_transcript_digest") or "").strip())
    )


def _visual_live_e2e_has_report_provenance(check: dict[str, Any]) -> bool:
    return (
        check.get("report_provenance_verified") is True
        and check.get("report_digest_verified") is True
        and str(check.get("report_kind") or "").strip() == "raphael_visual_live_e2e"
        and bool(str(check.get("report_producer") or "").strip())
        and check.get("script_identity_verified") is True
        and bool(str(check.get("script_path") or "").strip())
        and bool(str(check.get("script_sha256") or "").strip())
        and _visual_check_command_matches_script_path(check)
    )


def _visual_check_command_matches_script_path(check: dict[str, Any]) -> bool:
    producer = str(check.get("report_producer") or "").strip()
    trusted_script = _trusted_visual_live_report_script(producer)
    if trusted_script is None:
        return False
    command = str(check.get("command") or "").strip()
    script_path = str(check.get("script_path") or "").strip()
    if not command or not script_path:
        return False
    return (
        command.split()[0] == f"scripts/{trusted_script.name}"
        and Path(script_path).name == trusted_script.name
    )


def _wow_experience_has_release_score(check: dict[str, Any]) -> bool:
    try:
        score = int(check.get("score"))
    except (TypeError, ValueError):
        return False
    try:
        threshold = int(check.get("threshold", _WOW_RELEASE_THRESHOLD))
    except (TypeError, ValueError):
        return False
    if threshold < _WOW_RELEASE_THRESHOLD or score < threshold:
        return False
    signals = check.get("signals")
    if not isinstance(signals, dict):
        return False
    normalized_signals = {key: value is True for key, value in signals.items()}
    calculated_score, calculated_missing = calculate_raphael_wow_score(
        normalized_signals
    )
    stored_missing = check.get("missing")
    if not isinstance(stored_missing, list):
        return False
    if not _wow_user_simulation_cases_valid(check.get("user_simulation_cases")):
        return False
    if score != calculated_score:
        return False
    if tuple(str(item) for item in stored_missing) != calculated_missing:
        return False
    return _wow_score_passes_release_gate(calculated_score, normalized_signals)


def _wow_score_passes_release_gate(score: int, signals: dict[str, Any]) -> bool:
    return score >= _WOW_RELEASE_THRESHOLD and all(
        signals.get(signal) is True for signal in _WOW_CRITICAL_SIGNALS
    )


def _install_disable_uninstall_has_release_evidence(check: dict[str, Any]) -> bool:
    return (
        check.get("disabled_slash_commands_available") is True
        and check.get("disabled_status_guides_enable") is True
        and check.get("cli_smoke_verified") is True
        and check.get("cli_entrypoint_found") is True
        and str(check.get("cli_entrypoint") or "").strip() == "hermes"
        and bool(str(check.get("cli_entrypoint_path") or "").strip())
        and check.get("cli_install_enabled") is True
        and check.get("cli_disable_keeps_plugin") is True
        and check.get("cli_status_after_disable_guides_enable") is True
        and check.get("cli_enable_restores_mode") is True
        and check.get("cli_uninstall_disables_plugin") is True
        and check.get("cli_status_after_uninstall_guides_install") is True
    )


def _slash_command_surface_has_release_evidence(check: dict[str, Any]) -> bool:
    commands = check.get("commands")
    if not isinstance(commands, list):
        return False
    return (
        tuple(str(command) for command in commands) == _RAPHAEL_SLASH_COMMANDS
        and check.get("missing_commands") == []
        and check.get("status_brief_verified") is True
        and check.get("skills_brief_verified") is True
        and check.get("gateway_known") is True
        and "raphael_skills" in {
            str(command) for command in check.get("telegram_commands") or []
        }
        and str(check.get("temp_home") or "").strip() == "isolated"
    )


def _mode_router_contract_has_release_evidence(check: dict[str, Any]) -> bool:
    if not _mode_router_contract_static_evidence_valid(check):
        return False
    current_check = _mode_router_contract_release_gate_check()
    if not _mode_router_contract_static_evidence_valid(current_check):
        return False
    return (
        _mode_router_case_signatures(check)
        == _mode_router_case_signatures(current_check)
    )


def _mode_router_contract_static_evidence_valid(check: dict[str, Any]) -> bool:
    if str(check.get("route_provenance") or "").strip() != _MODE_ROUTER_PROVENANCE:
        return False
    root_mismatches = check.get("mismatches")
    if not isinstance(root_mismatches, list) or root_mismatches:
        return False
    raw_cases = check.get("cases")
    if not isinstance(raw_cases, list):
        return False
    cases = [case for case in raw_cases if isinstance(case, dict)]
    case_names = [str(case.get("case") or "").strip() for case in cases]
    if len(cases) != len(raw_cases):
        return False
    if set(case_names) != set(_MODE_ROUTER_REQUIRED_CASES):
        return False
    if len(case_names) != len(set(case_names)):
        return False
    for case in cases:
        if str(case.get("status") or "").strip().lower() != "pass":
            return False
        recorded_mismatches = case.get("mismatches")
        if not isinstance(recorded_mismatches, list) or recorded_mismatches:
            return False
        if _mode_router_case_mismatches(case):
            return False
    return True


def _mode_router_case_signatures(check: dict[str, Any]) -> dict[str, tuple[Any, ...]]:
    cases = check.get("cases")
    if not isinstance(cases, list):
        return {}
    signatures: dict[str, tuple[Any, ...]] = {}
    for case in cases:
        if not isinstance(case, dict):
            continue
        case_name = str(case.get("case") or "").strip()
        if not case_name:
            continue
        signatures[case_name] = tuple(
            case.get(field) for field in _MODE_ROUTER_CASE_EVIDENCE_FIELDS
        )
    return signatures


def _goal_state_contract_has_release_evidence(check: dict[str, Any]) -> bool:
    if not _goal_state_contract_static_evidence_valid(check):
        return False
    current_check = _goal_state_contract_release_gate_check()
    if not _goal_state_contract_static_evidence_valid(current_check):
        return False
    return (
        _goal_state_case_signatures(check)
        == _goal_state_case_signatures(current_check)
    )


def _goal_state_contract_static_evidence_valid(check: dict[str, Any]) -> bool:
    if str(check.get("state_provenance") or "").strip() != _GOAL_STATE_PROVENANCE:
        return False
    if str(check.get("temp_home") or "").strip() != "isolated":
        return False
    root_mismatches = check.get("mismatches")
    if not isinstance(root_mismatches, list) or root_mismatches:
        return False
    raw_cases = check.get("cases")
    if not isinstance(raw_cases, list):
        return False
    cases = [case for case in raw_cases if isinstance(case, dict)]
    case_names = [str(case.get("case") or "").strip() for case in cases]
    if len(cases) != len(raw_cases):
        return False
    if set(case_names) != set(_GOAL_STATE_REQUIRED_CASES):
        return False
    if len(case_names) != len(set(case_names)):
        return False
    for case in cases:
        if str(case.get("status") or "").strip().lower() != "pass":
            return False
        recorded_mismatches = case.get("mismatches")
        if not isinstance(recorded_mismatches, list) or recorded_mismatches:
            return False
        if _goal_state_case_mismatches(case):
            return False
    return True


def _goal_state_case_signatures(check: dict[str, Any]) -> dict[str, tuple[Any, ...]]:
    cases = check.get("cases")
    if not isinstance(cases, list):
        return {}
    signatures: dict[str, tuple[Any, ...]] = {}
    for case in cases:
        if not isinstance(case, dict):
            continue
        case_name = str(case.get("case") or "").strip()
        if not case_name:
            continue
        signatures[case_name] = tuple(
            case.get(field) for field in _GOAL_STATE_CASE_EVIDENCE_FIELDS
        )
    return signatures


def _evolution_contract_has_release_evidence(check: dict[str, Any]) -> bool:
    if not _evolution_contract_static_evidence_valid(check):
        return False
    current_check = _evolution_contract_release_gate_check()
    if not _evolution_contract_static_evidence_valid(current_check):
        return False
    return (
        _evolution_case_signatures(check)
        == _evolution_case_signatures(current_check)
    )


def _evolution_contract_static_evidence_valid(check: dict[str, Any]) -> bool:
    if str(check.get("evolution_provenance") or "").strip() != _EVOLUTION_PROVENANCE:
        return False
    if str(check.get("temp_home") or "").strip() != "isolated":
        return False
    root_mismatches = check.get("mismatches")
    if not isinstance(root_mismatches, list) or root_mismatches:
        return False
    raw_cases = check.get("cases")
    if not isinstance(raw_cases, list):
        return False
    cases = [case for case in raw_cases if isinstance(case, dict)]
    case_names = [str(case.get("case") or "").strip() for case in cases]
    if len(cases) != len(raw_cases):
        return False
    if set(case_names) != set(_EVOLUTION_REQUIRED_CASES):
        return False
    if len(case_names) != len(set(case_names)):
        return False
    for case in cases:
        if str(case.get("status") or "").strip().lower() != "pass":
            return False
        recorded_mismatches = case.get("mismatches")
        if not isinstance(recorded_mismatches, list) or recorded_mismatches:
            return False
        if _evolution_case_mismatches(case):
            return False
    return True


def _evolution_case_signatures(check: dict[str, Any]) -> dict[str, tuple[Any, ...]]:
    cases = check.get("cases")
    if not isinstance(cases, list):
        return {}
    signatures: dict[str, tuple[Any, ...]] = {}
    for case in cases:
        if not isinstance(case, dict):
            continue
        case_name = str(case.get("case") or "").strip()
        if not case_name:
            continue
        signatures[case_name] = tuple(
            case.get(field) for field in _EVOLUTION_CASE_EVIDENCE_FIELDS
        )
    return signatures


def _hostile_review_has_release_evidence(check: dict[str, Any]) -> bool:
    verdict = str(check.get("verdict") or "").strip().lower()
    try:
        blockers = int(check.get("blockers"))
    except (TypeError, ValueError):
        return False
    return (
        str(check.get("reviewer") or "").strip().lower() == "subagent"
        and verdict in {"pass", "passed", "clean"}
        and blockers == 0
        and not _hostile_review_missing_coverage(
            _hostile_review_report_coverage(check)
        )
        and not _hostile_review_missing_audit_trail(check)
        and _hostile_review_ux_claims_valid(_hostile_review_ux_claims(check))
        and _hostile_review_source_report_matches_claim(check)
    )


def _hostile_review_report_coverage(source: dict[str, Any]) -> tuple[str, ...]:
    raw_items = source.get("coverage")
    if not isinstance(raw_items, list):
        return ()
    seen: list[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.append(text)
    return tuple(seen)


def _hostile_review_missing_coverage(coverage: tuple[str, ...]) -> tuple[str, ...]:
    coverage_set = set(coverage)
    return tuple(
        item for item in _HOSTILE_REVIEW_REQUIRED_COVERAGE if item not in coverage_set
    )


def _hostile_review_string_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    seen: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.append(text)
    return tuple(seen)


def _hostile_review_missing_audit_trail(source: dict[str, Any]) -> tuple[str, ...]:
    scope = _hostile_review_string_list(
        source.get("review_scope") or source.get("scope")
    )
    review_evidence = _hostile_review_string_list(
        source.get("review_evidence") or source.get("evidence")
    )
    residual_risk = str(source.get("residual_risk") or "").strip()
    missing: list[str] = []
    if not scope:
        missing.append("scope")
    if not review_evidence:
        missing.append("evidence")
    if not residual_risk:
        missing.append("residual_risk")
    return tuple(missing)


def _hostile_review_ux_claims(source: dict[str, Any]) -> dict[str, Any]:
    claims = source.get("llm_ux_claims")
    if not isinstance(claims, dict):
        return {}
    scenarios = _hostile_review_string_list(claims.get("adversarial_scenarios"))
    transcript_ids = _hostile_review_string_list(claims.get("multi_turn_transcript_ids"))
    claim_verdicts_present = all(
        isinstance(claims.get(item), bool)
        for item in _HOSTILE_REVIEW_REQUIRED_UX_CLAIMS
    )
    return {
        "public_claims_reviewed": claims.get("public_claims_reviewed") is True,
        "claim_verdicts_present": claim_verdicts_present,
        "sage_king_claim_allowed": claims.get("sage_king_claim_allowed") is True,
        "wow_claim_allowed": claims.get("wow_claim_allowed") is True,
        "big_evolution_claim_allowed": claims.get("big_evolution_claim_allowed")
        is True,
        "adversarial_scenarios": list(scenarios),
        "multi_turn_transcript_ids": list(transcript_ids),
    }


def _hostile_review_ux_claims_valid(claims: dict[str, Any]) -> bool:
    if not isinstance(claims, dict) or not claims:
        return False
    if claims.get("public_claims_reviewed") is not True:
        return False
    if claims.get("claim_verdicts_present") is not True:
        return False
    if (
        claims.get("sage_king_claim_allowed") is True
        or claims.get("wow_claim_allowed") is True
        or claims.get("big_evolution_claim_allowed") is True
    ):
        return False
    scenarios = set(_hostile_review_string_list(claims.get("adversarial_scenarios")))
    if any(item not in scenarios for item in _HOSTILE_REVIEW_REQUIRED_UX_SCENARIOS):
        return False
    transcript_ids = _hostile_review_string_list(claims.get("multi_turn_transcript_ids"))
    return bool(transcript_ids)


def _non_visual_regression_suite_coverage(source: dict[str, Any]) -> tuple[str, ...]:
    return _hostile_review_string_list(source.get("suite_coverage"))


def _non_visual_regression_missing_suite_coverage(
    coverage: tuple[str, ...],
) -> tuple[str, ...]:
    coverage_set = set(coverage)
    return tuple(
        item
        for item in _NON_VISUAL_REGRESSION_REQUIRED_COVERAGE
        if item not in coverage_set
    )


def _non_visual_regression_has_release_evidence(check: dict[str, Any]) -> bool:
    try:
        passed_count = int(check.get("passed_count"))
    except (TypeError, ValueError):
        return False
    return (
        passed_count > 0
        and check.get("visual_quota_used") is False
        and check.get("report_digest_verified") is True
        and not _non_visual_regression_missing_suite_coverage(
            _non_visual_regression_suite_coverage(check)
        )
        and _non_visual_regression_source_report_matches_claim(check)
    )


def _release_docs_audit_has_release_evidence(check: dict[str, Any]) -> bool:
    violations = check.get("violations")
    if (
        str(check.get("status") or "").strip() != "pass"
        or str(check.get("command") or "").strip()
        != "scripts/raphael_release_docs_audit.py"
        or not str(check.get("run_id") or "").strip()
        or not isinstance(violations, list)
        or violations
    ):
        return False
    paths = check.get("source_readiness_paths")
    llm_path = media_path = None
    if isinstance(paths, list) and len(paths) >= 2:
        llm_path = Path(str(paths[0]))
        media_path = Path(str(paths[1]))
    current = _release_docs_audit_release_gate_check(
        llm_readiness_path=llm_path,
        media_readiness_path=media_path,
    )
    return (
        str(current.get("status") or "").strip() == "pass"
        and current.get("violations") == []
    )


def _completion_audit_has_release_evidence(check: dict[str, Any]) -> bool:
    blockers = check.get("blockers")
    return (
        str(check.get("status") or "").strip() == "pass"
        and str(check.get("command") or "").strip()
        == "scripts/raphael_completion_audit.py --target scoped"
        and str(check.get("run_id") or "").strip()
        and str(check.get("audit_status") or "").strip() in {"partial", "ready"}
        and check.get("scoped_release_ready") is True
        and isinstance(check.get("ultimate_ready"), bool)
        and isinstance(blockers, list)
    )


def _completion_audit_status_label(check: Mapping[str, Any]) -> str:
    audit_status = str(check.get("audit_status") or "missing").strip() or "missing"
    scoped = "yes" if check.get("scoped_release_ready") is True else "no"
    ultimate = "yes" if check.get("ultimate_ready") is True else "no"
    return f"{audit_status} (scoped={scoped}, ultimate={ultimate})"


def _release_slice_manifest_has_release_evidence(check: dict[str, Any]) -> bool:
    counts = check.get("counts")
    blockers = check.get("blockers")
    return (
        str(check.get("status") or "").strip() == "pass"
        and str(check.get("command") or "").strip()
        == "scripts/raphael_release_slice_manifest.py --from-git-status"
        and str(check.get("run_id") or "").strip()
        and str(check.get("manifest_status") or "").strip() == "reviewable"
        and str(check.get("review_strategy") or "").strip()
        in {"split_required", "single_llm_slice"}
        and "llm_only" in _string_list_from_any(check.get("allowed_public_claims"))
        and "full_media" in _string_list_from_any(check.get("blocked_public_claims"))
        and isinstance(counts, Mapping)
        and counts.get("unclassified_paths") == 0
        and counts.get("content_violations") == 0
        and isinstance(blockers, list)
        and not blockers
        and _manifest_has_slice(check, "llm_scoped_release", True)
    )


def _release_slice_manifest_status_label(check: Mapping[str, Any]) -> str:
    manifest_status = str(check.get("manifest_status") or "missing").strip() or "missing"
    strategy = str(check.get("review_strategy") or "").strip()
    return f"{manifest_status} ({strategy})" if strategy else manifest_status


def _manifest_has_slice(
    manifest: Mapping[str, Any],
    slice_id: str,
    release_ready: bool,
) -> bool:
    slices = manifest.get("slices")
    if not isinstance(slices, list):
        return False
    return any(
        isinstance(item, Mapping)
        and item.get("id") == slice_id
        and item.get("release_ready") is release_ready
        for item in slices
    )


def _manifest_slice_summaries(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    slices = manifest.get("slices")
    if not isinstance(slices, list):
        return []
    summaries: list[dict[str, Any]] = []
    for item in slices:
        if not isinstance(item, Mapping):
            continue
        summaries.append(
            {
                "id": str(item.get("id") or ""),
                "release_ready": item.get("release_ready") is True,
            }
        )
    return summaries


def _string_list_from_any(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _package_install_has_release_evidence(check: dict[str, Any]) -> bool:
    cli_exit_codes = check.get("cli_exit_codes")
    return (
        _package_install_has_core_release_provenance(check)
        and check.get("report_identity_verified") is True
        and check.get("wheel_built") is True
        and check.get("wheel_installed") is True
        and check.get("source_tree_cwd_used") is False
        and check.get("source_tree_hygiene_checked") is True
        and check.get("source_tree_hygiene_clean") is True
        and check.get("source_tree_generated_artifacts") == []
        and check.get("source_tree_post_build_hygiene_clean") is True
        and check.get("source_tree_post_build_generated_artifacts") == []
        and check.get("pythonpath_clean") is True
        and _package_install_media_gate_verified(check)
        and _package_install_llm_gate_verified(check)
        and str(check.get("hermes_entrypoint") or "").strip() == "hermes"
        and check.get("hermes_entrypoint_found") is True
        and bool(str(check.get("hermes_entrypoint_path") or "").strip())
        and int(check.get("cli_command_count") or 0) >= 8
        and isinstance(cli_exit_codes, list)
        and bool(cli_exit_codes)
        and all(code == 0 for code in cli_exit_codes)
        and check.get("cli_install_enabled") is True
        and check.get("cli_disable_keeps_plugin") is True
        and check.get("cli_status_after_disable_guides_enable") is True
        and check.get("cli_enable_restores_mode") is True
        and check.get("cli_proposal_status_safe_refs") is True
        and check.get("cli_proposal_approve_audited") is True
        and check.get("cli_proposal_approve_rollout_guidance") is True
        and check.get("cli_proposal_reject_audited") is True
        and check.get("cli_proposal_resolutions_persisted") is True
        and check.get("cli_proposal_raw_ids_hidden") is True
        and check.get("cli_proposal_no_durable_apply_warning") is True
        and check.get("cli_uninstall_disables_plugin") is True
        and check.get("cli_status_after_uninstall_guides_install") is True
        and _package_install_source_report_matches_claim(check)
    )


def _package_install_media_gate_verified(check: dict[str, Any]) -> bool:
    lines = [str(item) for item in check.get("installed_media_gate_lines") or []]
    slice_ready = (
        check.get("installed_media_slice_ready") is True
        and "Limited media release ready: yes" in lines
        and "Full media release ready: no" in lines
        and "Limited media release ready: no" not in lines
        and "Full media release ready: yes" not in lines
    )
    fail_closed = (
        (
            check.get("installed_media_gate_fail_closed") is True
            or check.get("installed_media_fail_closed") is True
        )
        and (
            "Limited media release ready: no" in lines
            or not any(
                line.startswith("Limited media release ready:") for line in lines
            )
        )
        and "Full media release ready: no" in lines
        and "Public release ready: no" in lines
        and "Limited media release ready: yes" not in lines
        and "Full media release ready: yes" not in lines
        and "Public release ready: yes" not in lines
    )
    return slice_ready or fail_closed


def _package_install_llm_gate_verified(check: dict[str, Any]) -> bool:
    return _package_install_llm_manifest_gate_verified(
        check
    ) or _package_install_llm_fresh_home_fail_closed(check)


def _package_install_llm_manifest_gate_verified(check: dict[str, Any]) -> bool:
    lines = [str(item) for item in check.get("installed_llm_gate_lines") or []]
    return (
        check.get("installed_llm_release_ready") is True
        and check.get("installed_llm_manifest_gate_verified") is True
        and "Release docs: pass" in lines
        and any(line.startswith("Completion audit: partial") for line in lines)
        and any(line.startswith("Release slice manifest: reviewable") for line in lines)
        and "Release scope: llm_only" in lines
        and "Public release ready: yes" in lines
        and "Release state: ready_for_llm_only_release" in lines
    )


def _package_install_llm_fresh_home_fail_closed(check: dict[str, Any]) -> bool:
    lines = [str(item) for item in check.get("installed_llm_gate_lines") or []]
    return (
        check.get("installed_llm_fresh_home_fail_closed") is True
        and "Release scope: llm_only" in lines
        and "Public release ready: no" in lines
        and "Release state: blocked_release_evidence_pending" in lines
        and "Public release ready: yes" not in lines
    )


def _package_install_has_core_release_provenance(check: dict[str, Any]) -> bool:
    return (
        check.get("report_identity_verified") is True
        and check.get("script_identity_verified") is True
        and check.get("cli_status_after_install_enabled") is True
        and check.get("cli_status_after_enable_enabled") is True
        and check.get("commands_verified") is True
        and check.get("commands_digest_verified") is True
    )


def _package_install_command_records_digest(records: list[Any]) -> str:
    if not records:
        return ""
    try:
        payload = json.dumps(
            records,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return ""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _release_report_digest(report: dict[str, Any]) -> str:
    payload_source = dict(report)
    payload_source.pop("report_digest", None)
    try:
        payload = json.dumps(
            payload_source,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return ""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _visual_live_report_provenance_error(report: dict[str, Any]) -> str:
    if report.get("schema_version") != 1:
        return "schema_version_unverified"
    if str(report.get("kind") or "").strip() != "raphael_visual_live_e2e":
        return "kind_unverified"
    producer = str(report.get("producer") or "").strip()
    if not producer:
        return "producer_missing"
    trusted_script = _trusted_visual_live_report_script(producer)
    if trusted_script is None:
        return "producer_untrusted"
    expected_command = f"scripts/{trusted_script.name}"
    if str(report.get("command") or "").strip() != expected_command:
        return "command_untrusted"
    report_digest = str(report.get("report_digest") or "").strip()
    if not report_digest or report_digest != _release_report_digest(report):
        return "report_digest_unverified"
    script_path = str(report.get("script_path") or "").strip()
    script_sha256 = str(report.get("script_sha256") or "").strip()
    if report.get("script_identity_verified") is not True:
        return "script_identity_unverified"
    if not script_path or not script_sha256:
        return "script_identity_missing"
    path = Path(script_path).expanduser()
    if not _same_path(path, trusted_script):
        return "script_path_untrusted"
    if not path.exists() or not path.is_file():
        return "script_path_missing"
    try:
        actual_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "script_sha256_unreadable"
    if actual_sha256 != script_sha256:
        return "script_sha256_mismatch"
    return ""


def _visual_supplied_command_matches_report(
    supplied_command: str | None,
    report: dict[str, Any],
) -> bool:
    supplied = str(supplied_command or "").strip()
    if not supplied:
        return True
    report_command = str(report.get("command") or "").strip()
    if not report_command:
        return False
    supplied_script = supplied.split()[0]
    return supplied_script == report_command


def _trusted_visual_live_report_script(producer: str) -> Path | None:
    script_name_by_producer = {
        "grok-web-imagine-live-e2e": "grok_web_imagine_live_e2e.py",
        "openai-visual-live-e2e": "openai_visual_live_e2e.py",
    }
    script_name = script_name_by_producer.get(str(producer or "").strip())
    if not script_name:
        return None
    return (Path(__file__).resolve().parents[1] / "scripts" / script_name).resolve()


def _package_install_current_script_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "raphael_package_install_smoke.py"
    ).resolve()


def _package_install_current_script_sha256() -> str:
    script_path = _package_install_current_script_path()
    try:
        return hashlib.sha256(script_path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _same_path(left: str | Path, right: str | Path) -> bool:
    try:
        return Path(left).expanduser().resolve() == Path(right).expanduser().resolve()
    except OSError:
        return False


def _package_install_lifecycle_checks_from_commands(
    commands: list[Any],
) -> dict[str, Any]:
    records = {
        str(record.get("label") or ""): record
        for record in commands
        if isinstance(record, dict)
    }
    cli_labels = _package_install_cli_labels()
    cli_exit_codes = [_record_exit_code(records.get(label)) for label in cli_labels]

    def output(label: str) -> str:
        record = records.get(label)
        if not isinstance(record, dict):
            return ""
        return f"{record.get('stdout', '')}\n{record.get('stderr', '')}"

    def exit_code(label: str) -> int | None:
        value = _record_exit_code(records.get(label))
        return value if isinstance(value, int) else None

    status_after_install_enabled = (
        exit_code("status_after_install") == 0
        and _package_install_status_output_enabled(output("status_after_install"))
    )
    status_after_enable_enabled = (
        exit_code("status_after_enable") == 0
        and _package_install_status_output_enabled(output("status_after_enable"))
    )
    proposal_status_safe_refs = (
        exit_code("seed_action_proposals") == 0
        and exit_code("render_action_proposals") == 0
        and "Approve: hermes raphael proposal approve" in output("render_action_proposals")
        and "Reject: hermes raphael proposal reject" in output("render_action_proposals")
    )
    proposal_approve_audited = (
        exit_code("proposal_approve") == 0
        and "Raphael action proposal approved:" in output("proposal_approve")
        and "No durable change applied automatically" in output("proposal_approve")
    )
    proposal_approve_rollout_guidance = (
        "Next manual rollout:" in output("proposal_approve")
        and "Rollout: approved" in output("proposal_approve")
        and "Verify: pytest tests/agent/test_raphael_evolution.py -q; "
        "hermes raphael readiness --readiness-profile llm --check"
        in output("proposal_approve")
        and "Promote: focused tests plus runtime, replay, or LLM smoke"
        in output("proposal_approve")
        and "Rollback: next evidence or user feedback shows worse behavior"
        in output("proposal_approve")
        and (
            "Apply: manual only after verification; approval did not mutate durable policy."
            in output("proposal_approve")
        )
    )
    proposal_reject_audited = (
        exit_code("proposal_reject") == 0
        and "Raphael action proposal rejected:" in output("proposal_reject")
        and "No durable change applied automatically" in output("proposal_reject")
    )
    inspect = _parse_last_json_object(output("inspect_action_proposals"))
    proposal_resolutions_persisted = (
        exit_code("inspect_action_proposals") == 0
        and inspect.get("approve_status") == "approved"
        and inspect.get("reject_status") == "rejected"
    )
    proposal_raw_ids_hidden = (
        "package-install-approve-proposal" not in output("render_action_proposals")
        and "package-install-reject-proposal" not in output("render_action_proposals")
        and "package-install-approve-proposal" not in output("proposal_approve")
        and "package-install-reject-proposal" not in output("proposal_reject")
    )
    proposal_no_durable_apply_warning = (
        "No durable change applied automatically" in output("proposal_approve")
        and "No durable change applied automatically" in output("proposal_reject")
    )
    return {
        "cli_exit_codes": cli_exit_codes,
        "cli_status_after_install_enabled": status_after_install_enabled,
        "cli_install_enabled": (
            exit_code("install") == 0
            and "Raphael mode enabled" in output("install")
            and status_after_install_enabled
        ),
        "cli_disable_keeps_plugin": (
            exit_code("disable") == 0
            and "Raphael mode disabled" in output("disable")
            and "plugin remains enabled" in output("disable")
        ),
        "cli_status_after_disable_guides_enable": (
            exit_code("status_after_disable") == 0
            and "Slash commands: available" in output("status_after_disable")
            and "Next action: hermes raphael enable"
            in output("status_after_disable")
        ),
        "cli_status_after_enable_enabled": status_after_enable_enabled,
        "cli_enable_restores_mode": (
            exit_code("enable") == 0
            and "Raphael mode enabled" in output("enable")
            and status_after_enable_enabled
        ),
        "cli_proposal_status_safe_refs": proposal_status_safe_refs,
        "cli_proposal_approve_audited": proposal_approve_audited,
        "cli_proposal_approve_rollout_guidance": proposal_approve_rollout_guidance,
        "cli_proposal_reject_audited": proposal_reject_audited,
        "cli_proposal_resolutions_persisted": proposal_resolutions_persisted,
        "cli_proposal_raw_ids_hidden": proposal_raw_ids_hidden,
        "cli_proposal_no_durable_apply_warning": proposal_no_durable_apply_warning,
        "cli_uninstall_disables_plugin": (
            exit_code("uninstall") == 0
            and "Raphael mode uninstalled/disabled" in output("uninstall")
        ),
        "cli_status_after_uninstall_guides_install": (
            exit_code("status_after_uninstall") == 0
            and "plugin disabled" in output("status_after_uninstall")
            and "Next action: hermes raphael install"
            in output("status_after_uninstall")
        ),
    }


def _record_exit_code(record: Any) -> int | None:
    if not isinstance(record, dict):
        return None
    try:
        return int(record.get("exit_code"))
    except (TypeError, ValueError):
        return None


def _package_install_status_output_enabled(output: str) -> bool:
    return (
        "Mode: enabled" in output
        and "Conversation injection: enabled" in output
        and "Slash commands: available" in output
    )


def _package_install_command_transcript_verified(
    commands: list[Any],
    *,
    venv_fallback_used: bool,
    hermes_entrypoint_path: str,
) -> bool:
    if not isinstance(commands, list) or not commands:
        return False
    expected_hermes = str(hermes_entrypoint_path or "").strip()
    if not expected_hermes:
        return False
    labels = [
        str(record.get("label") or "")
        for record in commands
        if isinstance(record, dict)
    ]
    expected = ["build_wheel"]
    if venv_fallback_used:
        expected.append("create_venv_uv_fallback")
    expected.extend(["install_wheel", "pythonpath_probe"])
    for label, _step_args in _PACKAGE_INSTALL_LIFECYCLE_STEPS:
        expected.append(label)
        if label == "status_after_install":
            expected.append("media_readiness_after_install")
            expected.append("llm_readiness_after_install")
        if label == "status_after_enable":
            expected.extend(
                [
                    "seed_action_proposals",
                    "render_action_proposals",
                    *(proposal_label for proposal_label, _ in _PACKAGE_INSTALL_PROPOSAL_CLI_STEPS),
                    "inspect_action_proposals",
                ]
            )
    if labels != expected:
        return False
    return all(
        _package_install_command_record_verified(
            record,
            hermes_entrypoint_path=expected_hermes,
        )
        for record in commands
    )


_PACKAGE_INSTALL_LIFECYCLE_STEPS: tuple[tuple[str, str], ...] = (
    ("install", "install"),
    ("status_after_install", "status"),
    ("disable", "disable"),
    ("status_after_disable", "status"),
    ("enable", "enable"),
    ("status_after_enable", "status"),
    ("uninstall", "uninstall"),
    ("status_after_uninstall", "status"),
)

_PACKAGE_INSTALL_PROPOSAL_RUNTIME_LABELS = (
    "seed_action_proposals",
    "render_action_proposals",
    "inspect_action_proposals",
)
_PACKAGE_INSTALL_PROPOSAL_CLI_STEPS: tuple[tuple[str, tuple[str, str]], ...] = (
    ("proposal_approve", ("proposal", "approve")),
    ("proposal_reject", ("proposal", "reject")),
)


def _package_install_cli_labels() -> list[str]:
    labels: list[str] = []
    for label, _step in _PACKAGE_INSTALL_LIFECYCLE_STEPS:
        labels.append(label)
        if label == "status_after_enable":
            labels.extend(
                proposal_label
                for proposal_label, _proposal_step in _PACKAGE_INSTALL_PROPOSAL_CLI_STEPS
            )
    return labels


def _parse_last_json_object(text: str) -> dict[str, Any]:
    for line in reversed(str(text or "").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _package_install_command_record_verified(
    record: Any,
    *,
    hermes_entrypoint_path: str,
) -> bool:
    if not isinstance(record, dict):
        return False
    label = str(record.get("label") or "")
    command = record.get("command")
    cwd = str(record.get("cwd") or "").strip()
    if not isinstance(command, list) or not command or not cwd:
        return False
    command = [str(item) for item in command]
    try:
        exit_code = int(record.get("exit_code"))
    except (TypeError, ValueError):
        return False
    stdout = str(record.get("stdout") or "")
    if label == "build_wheel":
        return command[:3] == ["uv", "build", "--wheel"]
    if label == "create_venv_uv_fallback":
        return command[:4] == ["uv", "venv", "--clear", "--seed"]
    if label == "install_wheel":
        return command[1:4] == ["-m", "pip", "install"]
    if label == "pythonpath_probe":
        return command[1:3] == ["-c", "import json, sys; print(json.dumps(sys.path))"]
    if label == "seed_action_proposals":
        return (
            len(command) >= 3
            and command[1] == "-c"
            and "package_install_seed_action_proposals" in command[2]
        )
    if label == "render_action_proposals":
        return (
            len(command) >= 3
            and command[1] == "-c"
            and "package_install_render_action_proposals" in command[2]
        )
    if label == "inspect_action_proposals":
        return (
            len(command) >= 3
            and command[1] == "-c"
            and "package_install_inspect_action_proposals" in command[2]
        )
    if label == "media_readiness_after_install":
        return (
            exit_code == 1
            and len(command) >= 6
            and _same_path(command[0], hermes_entrypoint_path)
            and command[1:3] == ["raphael", "readiness"]
            and "--readiness-profile" in command
            and "media" in command
            and "--check" in command
        )
    if label == "llm_readiness_after_install":
        release_ready = (
            exit_code == 0
            and "Public release ready: yes" in stdout
            and "Release state: ready_for_llm_only_release" in stdout
        )
        fail_closed = (
            exit_code == 1
            and "Public release ready: no" in stdout
            and "Release state: blocked_release_evidence_pending" in stdout
            and "Public release ready: yes" not in stdout
        )
        return (
            len(command) >= 6
            and _same_path(command[0], hermes_entrypoint_path)
            and command[1:3] == ["raphael", "readiness"]
            and "--readiness-profile" in command
            and "llm" in command
            and "--check" in command
            and (release_ready or fail_closed)
        )
    lifecycle_steps = dict(_PACKAGE_INSTALL_LIFECYCLE_STEPS)
    if label in lifecycle_steps:
        expected_step = lifecycle_steps[label]
        return (
            len(command) >= 3
            and _same_path(command[0], hermes_entrypoint_path)
            and command[1:3] == ["raphael", expected_step]
        )
    proposal_steps = dict(_PACKAGE_INSTALL_PROPOSAL_CLI_STEPS)
    if label in proposal_steps:
        expected_step = proposal_steps[label]
        return (
            len(command) >= 5
            and _same_path(command[0], hermes_entrypoint_path)
            and tuple(command[1:3]) == ("raphael", "proposal")
            and command[3] == expected_step[1]
            and bool(str(command[4]).strip())
        )
    return False


def _hostile_review_source_report_matches_claim(check: dict[str, Any]) -> bool:
    report_path = str(check.get("source_report_path") or "").strip()
    if not report_path or not Path(report_path).exists():
        return False
    try:
        blockers = int(check.get("blockers"))
    except (TypeError, ValueError):
        return False
    imported = _hostile_review_release_gate_check_from_report(
        report_path=report_path,
        command=str(check.get("command") or "").strip() or None,
        run_id=str(check.get("run_id") or "").strip() or None,
        verdict=str(check.get("verdict") or "").strip() or None,
        blockers=blockers,
    )
    if imported.get("status") != "pass":
        return False
    fields = (
        "command",
        "run_id",
        "reviewer",
        "verdict",
        "blockers",
        "coverage",
        "review_scope",
        "review_evidence",
        "llm_ux_claims",
        "residual_risk",
    )
    return all(imported.get(field) == check.get(field) for field in fields)


def _non_visual_regression_source_report_matches_claim(
    check: dict[str, Any],
) -> bool:
    report_path = str(check.get("source_report_path") or "").strip()
    if not report_path or not Path(report_path).exists():
        return False
    try:
        passed_count = int(check.get("passed_count"))
    except (TypeError, ValueError):
        return False
    imported = _non_visual_regression_release_gate_check_from_report(
        report_path=report_path,
        command=str(check.get("command") or "").strip() or None,
        run_id=str(check.get("run_id") or "").strip() or None,
        passed_count=passed_count,
        visual_quota_used=check.get("visual_quota_used") is True,
    )
    if imported.get("status") != "pass":
        return False
    fields = (
        "command",
        "run_id",
        "exit_code",
        "passed_count",
        "failed_count",
        "suite_coverage",
        "visual_quota_used",
        "report_digest",
        "report_digest_verified",
    )
    return all(imported.get(field) == check.get(field) for field in fields)


def _package_install_source_report_matches_claim(check: dict[str, Any]) -> bool:
    report_path = str(check.get("source_report_path") or "").strip()
    if not report_path:
        return False
    imported = _package_install_release_gate_check_from_report(
        report_path=report_path,
    )
    if imported.get("status") != "pass":
        return False
    fields = (
        "command",
        "run_id",
        "exit_code",
        "report_generated_at",
        "report_identity_verified",
        "script_path",
        "script_sha256",
        "script_identity_verified",
        "wheel_built",
        "wheel_installed",
        "venv_fallback_used",
        "venv_error",
        "source_tree_cwd_used",
        "source_tree_hygiene_checked",
        "source_tree_hygiene_clean",
        "source_tree_generated_artifacts",
        "source_tree_post_build_hygiene_clean",
        "source_tree_post_build_generated_artifacts",
        "pythonpath_clean",
        "installed_media_slice_ready",
        "installed_media_gate_lines",
        "hermes_entrypoint",
        "hermes_entrypoint_found",
        "hermes_entrypoint_path",
        "cli_command_count",
        "cli_exit_codes",
        "cli_status_after_install_enabled",
        "cli_install_enabled",
        "cli_disable_keeps_plugin",
        "cli_status_after_disable_guides_enable",
        "cli_status_after_enable_enabled",
        "cli_enable_restores_mode",
        "cli_proposal_status_safe_refs",
        "cli_proposal_approve_audited",
        "cli_proposal_approve_rollout_guidance",
        "cli_proposal_reject_audited",
        "cli_proposal_resolutions_persisted",
        "cli_proposal_raw_ids_hidden",
        "cli_proposal_no_durable_apply_warning",
        "cli_uninstall_disables_plugin",
        "cli_status_after_uninstall_guides_install",
        "commands_verified",
        "commands_digest",
        "commands_digest_verified",
    )
    return all(imported.get(field) == check.get(field) for field in fields)


def _read_release_quality_source_report(check: dict[str, Any]) -> dict[str, Any] | None:
    report_path = str(check.get("source_report_path") or "").strip()
    if not report_path:
        return None
    path = Path(report_path)
    if not path.exists() or not path.is_file():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _visual_live_e2e_has_result_surface_evidence(check: dict[str, Any]) -> bool:
    report_path = str(check.get("source_report_path") or "").strip()
    artifact_path = str(check.get("artifact_path") or "").strip()
    provider_mode = str(check.get("provider_mode") or "").strip()
    page_url = str(check.get("page_url") or "").strip()
    history_entry_id = str(check.get("history_entry_id") or "").strip()
    result_surface_id = str(check.get("result_surface_id") or "").strip()
    artifact_durability = str(check.get("artifact_durability") or "").strip()
    provider_result_response_id = str(
        check.get("provider_result_response_id") or ""
    ).strip()
    return (
        _visual_provider_mode_has_release_surface(provider_mode)
        and _visual_provider_provenance_verified(check)
        and check.get("provider_success") is True
        and str(check.get("report_status") or "").strip().lower() == "completed"
        and bool(report_path)
        and Path(report_path).exists()
        and _visual_source_report_matches_claim(check)
        and bool(artifact_path)
        and check.get("artifact_exists") is True
        and Path(artifact_path).exists()
        and check.get("artifact_mtime_verified") is True
        and check.get("durable_history_verified") is True
        and _has_verified_visual_result_surface(
            provider_mode=provider_mode,
            result_surface_id=result_surface_id,
            history_entry_id=history_entry_id,
            page_url=page_url,
            provider_result_response_id=provider_result_response_id,
        )
        and _visual_artifact_durability_verified(
            provider_mode=provider_mode,
            artifact_durability=artifact_durability,
            page_url=page_url,
        )
    )


def _visual_source_report_matches_claim(check: dict[str, Any]) -> bool:
    report_path = str(check.get("source_report_path") or "").strip()
    if not report_path:
        return False
    imported = _visual_release_gate_check_from_report(
        report_path=report_path,
        run_id=str(check.get("run_id") or "").strip() or None,
        command=str(check.get("command") or "").strip() or None,
        selected_artifact_id=str(check.get("selected_artifact_id") or "").strip() or None,
        artifact_quality_verdict=str(check.get("artifact_quality_verdict") or "").strip()
        or None,
    )
    if imported.get("status") != "pass" or imported.get("fresh_artifact") is not True:
        return False
    fields = (
        "provider_mode",
        "provider_name",
        "provider_model",
        "provider_result_provider",
        "provider_result_model",
        "provider_result_response_id",
        "provider_success",
        "report_status",
        "report_provenance_verified",
        "report_provenance_error",
        "report_digest",
        "report_digest_verified",
        "report_kind",
        "report_producer",
        "script_path",
        "script_sha256",
        "script_identity_verified",
        "artifact_path",
        "artifact_exists",
        "artifact_mtime_verified",
        "artifact_mtime",
        "artifact_source",
        "artifact_durability",
        "durable_history_verified",
        "page_url",
        "history_entry_id",
        "result_surface_id",
        "operation",
        "artifact_quality_verdict",
        "quality_review_source",
        "quality_review_reviewer",
        "quality_review_run_id",
        "quality_review_generated_at",
        "quality_review_source_report_path",
        "quality_review_artifact_match",
        "quality_review_artifact_sha256",
        "quality_review_artifact_size_bytes",
        "quality_review_artifact_mtime",
        "quality_review_artifact_identity_verified",
        "quality_review_source_type",
        "quality_review_model_provider",
        "quality_review_model",
        "quality_review_evidence_digest",
        "quality_review_response_id",
        "quality_review_transcript_report_path",
        "quality_review_transcript_digest",
        "quality_review_provenance_verified",
        "quality_review_dimensions_verified",
    )
    if not all(imported.get(field) == check.get(field) for field in fields):
        return False
    if check.get("image_first_source_verified") is True:
        source_fields = (
            "image_first_source_verified",
            "source_image_artifact_id",
            "source_image_path",
            "source_image_policy",
            "source_image_ranked_selected",
            "single_video_source_image",
            "video_source_image_count",
        )
        return all(imported.get(field) == check.get(field) for field in source_fields)
    return True


def _has_verified_visual_result_surface(
    *,
    provider_mode: str,
    result_surface_id: str,
    history_entry_id: str,
    page_url: str,
    provider_result_response_id: str,
) -> bool:
    if _is_grok_visual_provider_mode(provider_mode):
        return _has_verified_grok_result_surface(
            result_surface_id=result_surface_id,
            history_entry_id=history_entry_id,
            page_url=page_url,
        )
    if _is_openai_visual_provider_mode(provider_mode):
        return _has_verified_openai_result_surface(
            result_surface_id=result_surface_id,
            history_entry_id=history_entry_id,
            provider_result_response_id=provider_result_response_id,
        )
    return False


def _has_verified_grok_result_surface(
    *,
    result_surface_id: str,
    history_entry_id: str,
    page_url: str,
) -> bool:
    if _is_strong_grok_result_reference(history_entry_id):
        return True
    surface = str(result_surface_id or "").strip()
    if surface:
        if _looks_like_url(surface):
            return _looks_like_grok_result_page_url(surface)
        return _is_strong_grok_result_reference(surface)
    return _looks_like_grok_result_page_url(page_url)


def _has_verified_openai_result_surface(
    *,
    result_surface_id: str,
    history_entry_id: str,
    provider_result_response_id: str,
) -> bool:
    _ = history_entry_id
    surface = str(result_surface_id or "").strip()
    if not surface or _looks_like_url(surface):
        return False
    surface_response_id = _openai_surface_response_id(surface)
    provider_response_id = _openai_surface_response_id(provider_result_response_id)
    return bool(surface_response_id) and surface_response_id == provider_response_id


def _visual_artifact_durability_verified(
    *,
    provider_mode: str,
    artifact_durability: str,
    page_url: str,
) -> bool:
    durability = str(artifact_durability or "").strip()
    if _is_grok_visual_provider_mode(provider_mode):
        return durability == "durable_history_or_post" or _looks_like_grok_result_page_url(page_url)
    if _is_openai_visual_provider_mode(provider_mode):
        return durability in {
            "provider_response_artifact",
            "openai_response_artifact",
            "durable_provider_response",
        }
    return False


def _visual_provider_mode_has_release_surface(provider_mode: str) -> bool:
    return _is_grok_visual_provider_mode(provider_mode) or _is_openai_visual_provider_mode(
        provider_mode
    )


def _visual_live_e2e_covers_default_media_provider(check: dict[str, Any]) -> bool:
    provider_mode = str(check.get("provider_mode") or "").strip()
    return _visual_provider_mode_has_release_surface(provider_mode)


def _visual_provider_coverage_note(check: dict[str, Any]) -> str:
    provider_mode = str(check.get("provider_mode") or "").strip()
    media_type = str(check.get("artifact_media_type") or "").strip().lower()
    media_note = (
        "image-only visual evidence; video generation not exercised"
        if media_type == "image"
        else ""
    )
    if _is_openai_visual_provider_mode(provider_mode):
        return "; ".join(
            item
            for item in (
                "openai media evidence only",
                media_note,
                "xAI/Grok generation not exercised",
            )
            if item
        )
    if _is_grok_visual_provider_mode(provider_mode):
        return "; ".join(
            item
            for item in ("grok web imagine media evidence", media_note)
            if item
        )
    return ""


def _media_release_scope_from_checks(checks: dict[str, dict[str, Any]]) -> str:
    visual_check = checks.get("visual_live_e2e")
    if not isinstance(visual_check, dict):
        return ""
    if str(visual_check.get("status") or "").strip().lower() != "pass":
        return ""
    return _media_release_scope_from_visual_check(visual_check)


def _media_release_scope_from_visual_check(check: dict[str, Any]) -> str:
    provider_mode = str(check.get("provider_mode") or "").strip()
    media_type = str(check.get("artifact_media_type") or "").strip().lower()
    if _is_openai_visual_provider_mode(provider_mode):
        if media_type == "image":
            return "media_openai_image_only"
        if media_type == "video":
            if (
                check.get("image_first_source_verified") is True
                and check.get("openai_source_image_verified") is True
            ):
                return "media_openai_image_first_video"
            return "media_openai_video_only"
        return "media_openai_visual"
    if _is_grok_visual_provider_mode(provider_mode):
        if media_type == "image":
            return "media_grok_image_only"
        if media_type == "video":
            if check.get("image_first_source_verified") is True:
                return "media_grok_image_first_video"
            return "media_grok_video"
        return "media_grok_visual"
    return ""


def _required_checks_have_passed(
    profile: str,
    checks: dict[str, dict[str, Any]],
) -> bool:
    for check_name in _required_readiness_checks(profile):
        check = checks.get(check_name)
        if not isinstance(check, dict):
            return False
        if str(check.get("status") or "").strip().lower() != "pass":
            return False
    return True


def _verified_media_capabilities(
    release_scope: str,
    remaining_scope_gaps: tuple[str, ...],
) -> list[dict[str, Any]]:
    scope = str(release_scope or "").strip()
    if not scope.startswith("media_openai_"):
        return []
    base_capability = {
        "capability_id": "openai_image_generation",
        "provider_family": "openai",
        "media_type": "image",
        "status": "verified",
        "release_scope": scope,
        "public_slice_ready": True,
        "full_media_release_ready": False,
        "remaining_full_media_gaps": list(remaining_scope_gaps),
    }
    if scope == "media_openai_image_only":
        return [base_capability]
    if scope == "media_openai_image_first_video":
        return [
            base_capability,
            {
                "capability_id": "openai_image_first_video_generation",
                "provider_family": "openai",
                "media_type": "video",
                "status": "verified",
                "release_scope": scope,
                "public_slice_ready": True,
                "full_media_release_ready": False,
                "remaining_full_media_gaps": list(remaining_scope_gaps),
                "source_image_policy": "single_ranked_image",
            },
        ]
    if scope == "media_openai_video_only":
        return [
            {
                "capability_id": "openai_video_generation",
                "provider_family": "openai",
                "media_type": "video",
                "status": "verified",
                "release_scope": scope,
                "public_slice_ready": False,
                "full_media_release_ready": False,
                "remaining_full_media_gaps": list(remaining_scope_gaps),
            }
        ]
    return []


def _media_release_gap_actions(
    remaining_scope_gaps: tuple[str, ...],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for gap in remaining_scope_gaps:
        if gap == "xai_grok_generation":
            actions.append(
                {
                    "gap": gap,
                    "failure_layer": "provider_coverage",
                    "command": "scripts/grok_web_imagine_live_e2e.py",
                    "preflight_command": (
                        "scripts/grok_web_imagine_live_e2e.py --preflight-only"
                    ),
                    "quota_policy": "preflight_first",
                    "blocks_full_media_release": True,
                }
            )
        elif gap == "video_generation":
            actions.append(
                {
                    "gap": gap,
                    "failure_layer": "media_modality_coverage",
                    "command": (
                        "scripts/visual_live_provider_e2e.py --mode live "
                        "--image-first-video --video-budget 1"
                    ),
                    "requires_video": True,
                    "requires_source_image": True,
                    "source_image_policy": "single_ranked_image",
                    "blocks_full_media_release": True,
                }
            )
        elif gap == "image_first_source_image":
            actions.append(
                {
                    "gap": gap,
                    "failure_layer": "media_workflow_coverage",
                    "command": (
                        "scripts/visual_live_provider_e2e.py --mode live --image-first-video"
                    ),
                    "requires_source_image": True,
                    "blocks_full_media_release": True,
                }
            )
        else:
            actions.append(
                {
                    "gap": gap,
                    "failure_layer": "media_scope_coverage",
                    "command": "hermes raphael release-gate --readiness-profile media",
                    "blocks_full_media_release": True,
                }
            )
    return actions


def _media_full_release_gap_actions(
    remaining_scope_gaps: tuple[str, ...],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for gap in remaining_scope_gaps:
        reason = f"media_scope_gap_{gap}"
        action: dict[str, Any] = {
            "reason": reason,
            "failure_layer": _readiness_failure_layer(reason),
            "next_action": _readiness_next_action((reason,), "media"),
            "blocks_public_release": False,
            "blocks_full_media_release": True,
        }
        gap_actions = _media_release_gap_actions((gap,))
        if gap_actions:
            action.update(gap_actions[0])
        actions.append(action)
    return actions


def _public_blocking_media_scope_gaps(
    release_scope: str,
    remaining_scope_gaps: tuple[str, ...],
) -> tuple[str, ...]:
    if str(release_scope or "").strip() in {
        "media_openai_image_only",
        "media_openai_image_first_video",
    }:
        return ()
    if str(release_scope or "").strip() == "media_openai_video_only":
        return tuple(
            gap for gap in remaining_scope_gaps if gap != "xai_grok_generation"
        )
    return remaining_scope_gaps


def _remaining_media_scope_gaps(release_scope: str) -> tuple[str, ...]:
    scope = str(release_scope or "").strip()
    gaps: list[str] = []
    if scope.startswith("media_openai_"):
        gaps.append("xai_grok_generation")
    if scope.endswith("_image_only"):
        gaps.append("video_generation")
    if (
        scope.endswith("_video") or scope.endswith("_video_only")
    ) and "image_first" not in scope:
        gaps.append("image_first_source_image")
    return tuple(gaps)


def _visual_artifact_media_type(*, artifact_path: str, operation: str) -> str:
    suffix = Path(str(artifact_path or "")).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}:
        return "image"
    if suffix in {".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv"}:
        return "video"
    op = str(operation or "").strip().lower()
    if "video" in op or op in {"animate", "image_to_video"}:
        return "video"
    if "image" in op or op == "generate":
        return "image"
    return ""


def _visual_provider_provenance_verified(check: dict[str, Any]) -> bool:
    provider_mode = str(check.get("provider_mode") or "").strip()
    provider_name = str(check.get("provider_name") or "").strip()
    provider_result_provider = str(check.get("provider_result_provider") or "").strip()
    if _is_grok_visual_provider_mode(provider_mode):
        return _is_grok_visual_provider_name(
            provider_name
        ) and _is_grok_visual_provider_name(provider_result_provider)
    if not _is_openai_visual_provider_mode(provider_mode):
        return False
    return _is_openai_visual_provider_name(
        provider_name
    ) and _is_openai_visual_provider_name(provider_result_provider)


def _provider_result_response_id(provider_result: dict[str, Any]) -> str:
    for key in ("response_id", "result_id", "generation_id", "id"):
        value = str(provider_result.get(key) or "").strip()
        if value:
            return value
    return ""


def _openai_surface_response_id(value: str) -> str:
    text = str(value or "").strip()
    if text.lower().startswith("openai-response:"):
        return text.split(":", 1)[1].strip()
    return text


def _is_openai_visual_provider_name(value: str) -> bool:
    normalized = str(value or "").strip().lower().replace("_", "-")
    return normalized in {
        "openai",
        "openai-codex",
        "openai-api",
        "gpt-image",
        "gpt-image-2",
    }


def _is_grok_visual_provider_name(value: str) -> bool:
    normalized = str(value or "").strip().lower().replace("_", "-")
    return normalized in {
        "grok-web-imagine",
        "grok-imagine",
        "xai",
    }


def _is_grok_visual_provider_mode(value: str) -> bool:
    return str(value or "").strip() == "grok-web-imagine-live"


def _is_openai_visual_provider_mode(value: str) -> bool:
    normalized = str(value or "").strip().lower().replace("_", "-")
    return normalized in {
        "openai-gpt-image-live",
        "openai-image-live",
        "openai-image2-live",
        "openai-image-2-live",
        "openai-visual-live",
        "openai-codex-image-live",
    }


def _looks_like_grok_result_page_url(value: str) -> bool:
    text = str(value or "").strip().lower()
    return text.startswith("https://grok.com/") and (
        "/imagine/post/" in text or "/imagine/history/" in text
    )


def _is_strong_grok_result_reference(value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    if _looks_like_url(text):
        return _looks_like_grok_result_page_url(text)
    if text in {"current", "latest", "selected", "active", "gallery", "result"}:
        return False
    return len(text) >= 8


def _looks_like_url(value: str) -> bool:
    text = str(value or "").strip().lower()
    return text.startswith(("http://", "https://"))


def _llm_live_smoke_failure_detail(check: dict[str, Any]) -> str:
    if not _llm_live_smoke_has_execution_evidence(check):
        return "smoke_unverified"
    transcript_failure = _llm_live_smoke_transcript_failure_detail(check)
    if transcript_failure:
        return transcript_failure
    if not _llm_live_smoke_model_identity_verified(check):
        return "model_identity_unverified"
    return ""


def _llm_live_smoke_has_execution_evidence(check: dict[str, Any]) -> bool:
    tool_call_count = check.get("tool_call_count")
    if isinstance(tool_call_count, bool):
        return False
    try:
        tool_call_count_int = int(tool_call_count)
    except (TypeError, ValueError):
        return False
    session_id = str(check.get("session_id") or "").strip()
    source_log_path = str(check.get("source_log_path") or "").strip()
    log_line = str(check.get("log_line") or "").strip()
    return (
        bool(session_id)
        and tool_call_count_int == 0
        and check.get("no_tool_calls") is True
        and check.get("summon_sections_verified") is True
        and check.get("full_body_preserved") is True
        and check.get("no_visual_failure_trace") is True
        and check.get("log_verified") is True
        and bool(source_log_path)
        and Path(source_log_path).exists()
        and _readiness_log_line_present(Path(source_log_path), log_line)
        and session_id in log_line
        and _llm_log_line_timestamp_is_fresh(log_line)
        and "Turn ended:" in log_line
        and "reason=text_response" in log_line
        and "tool_turns=0" in log_line
        and "last_msg_role=assistant" in log_line
    )


def _llm_live_smoke_transcript_failure_detail(check: dict[str, Any]) -> str:
    path_text = str(check.get("source_transcript_path") or "").strip()
    if not path_text:
        return "transcript_missing"
    path = Path(path_text)
    if not path.exists() or not path.is_file():
        return "transcript_missing"
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "transcript_unverified"
    if not isinstance(parsed, dict):
        return "transcript_unverified"
    if parsed.get("schema_version") != 1:
        return "transcript_unverified"
    generated_at_fresh, _reason = _readiness_generated_at_is_fresh(
        parsed.get("generated_at")
    )
    if not generated_at_fresh:
        return "transcript_unverified"
    if str(parsed.get("kind") or "").strip() != "raphael_llm_smoke_transcript":
        return "transcript_unverified"
    if str(parsed.get("session_id") or "").strip() != str(
        check.get("session_id") or ""
    ).strip():
        return "transcript_unverified"
    user_message = str(parsed.get("user_message") or "").strip()
    final_response = str(parsed.get("final_response") or "").strip()
    followup_user_message = str(parsed.get("followup_user_message") or "").strip()
    followup_response = str(parsed.get("followup_response") or "").strip()
    if "拉斐爾" not in user_message and "raphael" not in user_message.lower():
        return "summon_unverified"
    if not all(section in final_response for section in ("狀態", "風險", "下一步")):
        return "sections_unverified"
    if _llm_context_truncation_detected(parsed):
        return "context_truncated"
    if _llm_public_internal_trace_leak_detected(
        final_response,
        followup_response,
    ):
        return "internal_trace_leak"
    lowered_response = f"{final_response}\n{followup_response}".lower()
    if any(
        marker in lowered_response
        for marker in ("候選圖未通過", "data:image", "base64", "candidate image failed")
    ):
        return "visual_failure_trace_present"
    try:
        transcript_tool_count = int(parsed.get("tool_call_count"))
    except (TypeError, ValueError):
        return "transcript_unverified"
    if transcript_tool_count != 0:
        return "transcript_unverified"
    for field in (
        "no_tool_calls",
        "summon_sections_verified",
        "full_body_preserved",
        "no_visual_failure_trace",
    ):
        if parsed.get(field) is not True or check.get(field) is not True:
            return "transcript_unverified"
    if (
        parsed.get("mission_followup_verified") is not True
        or parsed.get("same_mission_continuity_verified") is not True
        or not _llm_live_smoke_has_followup_log_evidence(check)
        or not _llm_transcript_followup_proves_continuity(
            followup_user_message,
            followup_response,
        )
    ):
        return "mission_continuity_unverified"
    return ""


def _llm_public_internal_trace_leak_detected(*texts: str) -> bool:
    lowered = "\n".join(str(text or "") for text in texts).lower()
    return any(marker in lowered for marker in _LLM_PUBLIC_INTERNAL_TRACE_MARKERS)


def _llm_context_truncation_detected(report: dict[str, Any]) -> bool:
    if report.get("context_truncation_detected") is True:
        return True
    warning_values: list[str] = []
    for field in ("terminal_output", "stderr", "stdout", "warnings"):
        value = report.get(field)
        if isinstance(value, list):
            warning_values.extend(str(item or "") for item in value)
        else:
            warning_values.append(str(value or ""))
    lowered = "\n".join(warning_values).lower()
    return any(marker in lowered for marker in _LLM_CONTEXT_TRUNCATION_MARKERS)


def _llm_live_smoke_model_identity_verified(check: dict[str, Any]) -> bool:
    session_id = str(check.get("session_id") or "").strip()
    source_log_path = str(check.get("source_log_path") or "").strip()
    log_line = str(check.get("log_line") or "").strip()
    log_model = str(check.get("log_model") or "").strip() or _log_field_value(
        log_line, "model"
    )
    log_provider = str(check.get("log_model_provider") or "").strip()
    if not log_provider:
        log_provider = _llm_session_log_field_from_path(
            source_log_path,
            session_id,
            "provider",
        )
    transcript_model, transcript_provider = _llm_transcript_model_identity(check)
    return (
        log_model == _RAPHAEL_LLM_REQUIRED_MODEL
        and transcript_model == _RAPHAEL_LLM_REQUIRED_MODEL
        and _llm_provider_is_openai(log_provider)
        and _llm_provider_is_openai(transcript_provider)
    )


def _llm_transcript_model_identity(check: dict[str, Any]) -> tuple[str, str]:
    model = str(check.get("transcript_model") or "").strip()
    provider = str(check.get("transcript_model_provider") or "").strip()
    if model and provider:
        return model, provider
    path_text = str(check.get("source_transcript_path") or "").strip()
    if not path_text:
        return model, provider
    try:
        parsed = json.loads(Path(path_text).read_text(encoding="utf-8"))
    except Exception:
        return model, provider
    if not isinstance(parsed, dict):
        return model, provider
    return (
        model or str(parsed.get("model") or "").strip(),
        provider or str(parsed.get("model_provider") or "").strip(),
    )


def _llm_provider_is_openai(value: str) -> bool:
    return value.strip().lower().startswith(_RAPHAEL_LLM_REQUIRED_PROVIDER_PREFIX)


def _llm_live_smoke_has_followup_log_evidence(check: dict[str, Any]) -> bool:
    session_id = str(check.get("session_id") or "").strip()
    source_log_path = str(check.get("source_log_path") or "").strip()
    if not session_id or not source_log_path:
        return False
    path = Path(source_log_path)
    try:
        resolved = path.resolve()
        allowed = {candidate.resolve() for candidate in _readiness_log_paths()}
    except OSError:
        return False
    if resolved not in allowed:
        return False
    try:
        lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False

    turn_end_count = 0
    has_followup_context = False
    for raw_line in lines:
        line = raw_line.strip()
        if f"session={session_id}" not in line or f"[{session_id}]" not in line:
            continue
        if _llm_log_turn_end_line_is_verified(line, session_id):
            turn_end_count += 1
        if _llm_log_turn_context_line_has_followup_history(line, session_id):
            has_followup_context = True
    return turn_end_count >= 2 and has_followup_context


def _llm_log_turn_end_line_is_verified(line: str, session_id: str) -> bool:
    return (
        _llm_log_line_timestamp_is_fresh(line)
        and f"[{session_id}]" in line
        and f"session={session_id}" in line
        and "Turn ended:" in line
        and "reason=text_response" in line
        and "tool_turns=0" in line
        and "last_msg_role=assistant" in line
    )


def _llm_log_turn_context_line_has_followup_history(
    line: str,
    session_id: str,
) -> bool:
    if (
        not _llm_log_line_timestamp_is_fresh(line)
        or f"[{session_id}]" not in line
        or f"session={session_id}" not in line
        or "agent.turn_context: conversation turn:" not in line
    ):
        return False
    history = _llm_log_field_int(line, "history=")
    return history is not None and history > 0


def _llm_log_field_int(line: str, marker: str) -> int | None:
    start = str(line or "").find(marker)
    if start < 0:
        return None
    value_start = start + len(marker)
    digits = []
    for character in line[value_start:]:
        if not character.isdigit():
            break
        digits.append(character)
    if not digits:
        return None
    try:
        return int("".join(digits))
    except ValueError:
        return None


def _llm_transcript_followup_proves_continuity(
    followup_user_message: str,
    followup_response: str,
) -> bool:
    user_text = str(followup_user_message or "").strip()
    response_text = str(followup_response or "").strip()
    if not user_text or not response_text:
        return False
    lowered_user = user_text.lower()
    lowered_response = response_text.lower()
    if "無關" in user_text or "unrelated" in lowered_user:
        return False
    if "無關" in response_text or "unrelated" in lowered_response:
        return False
    user_continuity_markers = (
        "同一個",
        "同一任務",
        "同任務",
        "沿用",
        "same mission",
        "same task",
        "same raphael",
    )
    response_continuity_markers = (
        "同一個",
        "同一任務",
        "沿用",
        "延續",
        "上一輪",
        "readiness",
        "證據",
        "補證據",
        "待補證據",
        "不宣稱完成",
        "same mission",
        "same task",
    )
    return (
        any(marker in lowered_user or marker in user_text for marker in user_continuity_markers)
        and all(section in response_text for section in ("狀態", "風險", "下一步"))
        and any(
            marker in lowered_response or marker in response_text
            for marker in response_continuity_markers
        )
    )


def _llm_log_line_timestamp_is_fresh(log_line: str) -> bool:
    timestamp_text = str(log_line or "").strip()[:23]
    try:
        logged_at = datetime.strptime(timestamp_text, "%Y-%m-%d %H:%M:%S,%f")
    except ValueError:
        return False
    local_tz = datetime.now().astimezone().tzinfo or timezone.utc
    logged_at_utc = logged_at.replace(tzinfo=local_tz).astimezone(timezone.utc)
    now = datetime.now(timezone.utc)
    if logged_at_utc > now + _READINESS_EVIDENCE_FUTURE_SKEW:
        return False
    return now - logged_at_utc <= _READINESS_EVIDENCE_MAX_AGE


def _readiness_log_line_present(path: Path, expected_line: str) -> bool:
    expected = str(expected_line or "").strip()
    if not expected:
        return False
    try:
        resolved = path.resolve()
        allowed = {candidate.resolve() for candidate in _readiness_log_paths()}
    except OSError:
        return False
    if resolved not in allowed:
        return False
    try:
        return any(
            line.strip() == expected
            for line in resolved.read_text(encoding="utf-8", errors="replace").splitlines()
        )
    except OSError:
        return False


def render_raphael_demo(prompt: str | None = None) -> str:
    custom_prompt = prompt is not None
    user_prompt = (
        prompt
        or "拉斐爾，請幫我完成一個工具任務，規劃、執行、驗證，並在失敗時主動修正。"
    )
    appraisal_prompt = (
        "拉斐爾，請完成一個工具/runtime 任務，規劃、執行，並用證據驗證。"
        if custom_prompt
        else user_prompt
    )
    input_line = (
        f"Input: redacted demo prompt ({len(user_prompt)} chars)"
        if custom_prompt
        else f"Input: {user_prompt}"
    )
    appraisal = appraise_raphael_situation(
        appraisal_prompt,
        conversation_history=[],
    )
    standby_appraisal = appraise_raphael_situation(
        "拉斐爾？",
        conversation_history=[],
    )
    strategies = simulate_raphael_strategies(appraisal)
    standby_strategies = simulate_raphael_strategies(standby_appraisal)
    mission = update_raphael_mission(None, appraisal, strategies)
    followup_appraisal = appraise_raphael_situation(
        "把同一個任務改成先補證據，不要宣稱完成。",
        conversation_history=[
            {
                "role": "assistant",
                "artifact_id": mission.active_artifact_id or "artifact-demo-current",
                "content": "latest selected artifact from the prior mission",
            }
        ],
    )
    followup_strategies = simulate_raphael_strategies(followup_appraisal)
    followup_mission = update_raphael_mission(mission, followup_appraisal, followup_strategies)
    standby_invocation = render_raphael_invocation_response(
        standby_appraisal,
        standby_strategies,
    )
    invocation = render_raphael_invocation_response(appraisal, strategies, mission)
    metadata = _demo_evolution_metadata(appraisal.task_type)
    proof_gate = _demo_proof_gate_block(mission.required_proofs)
    wow_score, missing_wow_signals = calculate_raphael_wow_score(
        {
            "summon_appraisal": True,
            "standby_summon": "狀態：Raphael 待命" in standby_invocation
            and "請給我任務目標" in standby_invocation,
            "mission_followup": True,
            "proof_gate": "Status: not complete." in proof_gate,
            "evolution_feedback": bool(
                metadata.get("proposed_change") and metadata.get("rollback_condition")
            ),
            "lifecycle_reversible": True,
            "demo_under_one_minute": True,
            "clean_output": True,
        }
    )
    proof_text = format_raphael_proof_text(mission.required_proofs)
    lifecycle = raphael_lifecycle_status()

    lines = [
        "Raphael Demo",
        "Scope: offline demo only; no provider called; not public readiness.",
        input_line,
        "",
        "Lifecycle Dry Run:",
        f"- current: {lifecycle.message}",
        "- install: would enable bundled plugin and conversation injection",
        "- enable: would keep evolution audit-only unless --evolve is passed",
        "- dry-run only; config unchanged",
        "",
        "Standby Summon:",
        standby_invocation,
        "",
        invocation,
        "",
        "Mission Transition:",
        f"- 任務：{mission.goal}",
        f"- 狀態：{_demo_phase_text(mission.phase)} -> {_demo_phase_text(followup_mission.phase)}",
        (
            "- 策略："
            f"{format_raphael_strategy_label(mission.selected_strategy_id)} -> "
            f"{format_raphael_strategy_label(followup_mission.selected_strategy_id)}"
        ),
        f"- 下一步：{format_raphael_route_text(followup_mission.next_action)}",
        "",
        "Proof Ladder:",
        f"- required: {proof_text}",
        "- static checks: code shape and import safety",
        "- focused tests: behavior contracts for appraisal, routing, proof, mission",
        "- live LLM smoke: allowed for LLM-only public readiness checks",
        "- artifact quality: required when visual generation quota is enabled",
        "",
        "Proof Gate Block:",
        proof_gate,
        "",
        "Evolution Metadata:",
        f"- 能力：{_demo_capability_text(metadata['affected_capability'])}",
        f"- 改進：{metadata['proposed_change']}",
        f"- 信心：{metadata['confidence']:.2f}",
        f"- 上線條件：{metadata['promotion_gate']}",
        f"- 回滾條件：{metadata['rollback_condition']}",
        "",
        "Evolution Proposal:",
        "- 觸發：simulated user correction plus missing proof",
        f"- 能力：{_demo_capability_text(metadata['affected_capability'])}",
        "- 狀態：等待聚焦測試與 live smoke 通過後才可套用",
        "",
        "Offline Demo Evidence:",
        "- no provider called",
        "- no image/video quota consumed",
        "- route/appraisal/proof/mission surfaces rendered",
        "- not public readiness; live smoke and strict proof gates still decide launch",
        "",
        "Enable/Disable:",
        "- install: hermes raphael install",
        "- install with durable evolution: hermes raphael install --evolve",
        "- enable: hermes raphael enable",
        "- disable: hermes raphael disable",
        "- uninstall/reset: hermes raphael uninstall",
        "",
        "Cleanup:",
        "- disable/reset actions are shown as dry-run only; config unchanged",
        "",
        f"Offline shape score: {wow_score}/10",
        "Public wow claim: not proven by offline demo",
    ]
    if missing_wow_signals:
        lines.append("Missing offline shape signals: " + ", ".join(missing_wow_signals))
    return "\n".join(lines)


def _demo_evolution_metadata(task_type: str) -> dict[str, Any]:
    capability = (
        "visual.agent_mode"
        if task_type.startswith("visual")
        else "raphael.control_layer"
    )
    return sanitize_raphael_evolution_metadata(
        {
            "affected_capability": capability,
            "proposed_change": (
                "Convert the current mission evidence into the smallest skill or "
                "control-layer improvement that makes the next run more autonomous."
            ),
            "confidence": 0.82,
            "promotion_gate": "focused tests plus live LLM smoke before public claim",
            "rollback_condition": (
                "disable the promoted lesson if user feedback or proof records show "
                "worse routing, recovery, or delivery"
            ),
        }
    )


def _demo_capability_text(value: Any) -> str:
    text = str(value or "unknown").replace(".", " ").replace("_", " ").strip()
    if not text:
        return "unknown"
    if text.startswith("raphael "):
        return "Raphael " + text.removeprefix("raphael ")
    if text.startswith("visual "):
        return "visual " + text.removeprefix("visual ")
    return text


def _demo_proof_gate_block(required_proofs: tuple[str, ...]) -> str:
    fake_messages: tuple[dict[str, Any], ...] = (
        {
            "role": "assistant",
            "content": "I ran the tests and everything passed.",
        },
    )
    if raphael_has_required_proof(fake_messages, required_proofs):
        return "Status: complete."
    required = format_raphael_proof_text(required_proofs)
    return "\n".join(
        [
            "Status: not complete.",
            f"Reason: Raphael proof gate is missing {required}.",
            "Next action: run the matching focused test, runtime smoke, or live proof.",
        ]
    )


def _demo_phase_text(phase: str) -> str:
    return {
        "strategy_selected": "已選定策略",
        "blocked": "等待釐清",
    }.get(phase, phase)


def _ensure_plugin_enabled(config: dict[str, Any]) -> None:
    plugins = config.setdefault("plugins", {})
    if not isinstance(plugins, dict):
        plugins = {}
        config["plugins"] = plugins
    enabled = plugins.get("enabled")
    if not isinstance(enabled, list):
        enabled = []
    disabled = plugins.get("disabled")
    if not isinstance(disabled, list):
        disabled = []
    if "raphael" not in enabled:
        enabled.append("raphael")
    plugins["enabled"] = sorted({str(item) for item in enabled if str(item)})
    plugins["disabled"] = sorted(
        {str(item) for item in disabled if str(item) and str(item) != "raphael"}
    )


def _ensure_plugin_disabled(config: dict[str, Any]) -> None:
    plugins = config.setdefault("plugins", {})
    if not isinstance(plugins, dict):
        plugins = {}
        config["plugins"] = plugins
    enabled = plugins.get("enabled")
    if not isinstance(enabled, list):
        enabled = []
    disabled = plugins.get("disabled")
    if not isinstance(disabled, list):
        disabled = []
    plugins["enabled"] = sorted({str(item) for item in enabled if str(item) and str(item) != "raphael"})
    disabled_set = {str(item) for item in disabled if str(item)}
    disabled_set.add("raphael")
    plugins["disabled"] = sorted(disabled_set)


def _ensure_raphael_config(config: dict[str, Any]) -> dict[str, Any]:
    raphael = config.setdefault("raphael", {})
    if not isinstance(raphael, dict):
        raphael = {}
        config["raphael"] = raphael
    defaults = DEFAULT_CONFIG.get("raphael", {})
    if isinstance(defaults, Mapping):
        _merge_missing_raphael_defaults(raphael, defaults)
    return raphael


def _save_raphael_config(config: dict[str, Any]) -> None:
    _ensure_raphael_config(config)
    save_config(config, preserve_keys=_raphael_config_preserve_paths())


def _raphael_config_preserve_paths() -> set[tuple[str, ...]]:
    paths: set[tuple[str, ...]] = {
        ("plugins", "enabled"),
        ("plugins", "disabled"),
    }

    def _walk(prefix: tuple[str, ...], value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                _walk((*prefix, str(key)), child)
            return
        paths.add(prefix)

    defaults = DEFAULT_CONFIG.get("raphael", {})
    if isinstance(defaults, Mapping):
        _walk(("raphael",), defaults)
    return paths


def _merge_missing_raphael_defaults(target: dict[str, Any], defaults: Mapping[str, Any]) -> None:
    for key, value in defaults.items():
        if key not in target:
            target[key] = copy.deepcopy(value)
            continue
        if isinstance(target.get(key), dict) and isinstance(value, Mapping):
            _merge_missing_raphael_defaults(target[key], value)


def _status_from_config(config: dict[str, Any], *, message: str) -> RaphaelLifecycleStatus:
    plugin_enabled = raphael_plugin_active(config)
    raphael = config.get("raphael") if isinstance(config.get("raphael"), dict) else {}
    return RaphaelLifecycleStatus(
        enabled=plugin_enabled and raphael.get("enabled") is True,
        plugin_enabled=plugin_enabled,
        default_conversation_mode_enabled=plugin_enabled and raphael.get("default_conversation_mode_enabled") is True,
        mode=str(raphael.get("mode") or "sage_king"),
        message=message,
    )


__all__ = [
    "RaphaelLifecycleStatus",
    "RaphaelReadinessStatus",
    "RaphaelSetupDoctorStatus",
    "disable_raphael_mode",
    "enable_raphael_mode",
    "raphael_command",
    "raphael_lifecycle_status",
    "raphael_release_gate",
    "raphael_release_readiness",
    "raphael_setup_doctor",
    "render_raphael_demo",
    "uninstall_raphael_mode",
]
