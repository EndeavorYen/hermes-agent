from __future__ import annotations

from hermes_cli.config import cfg_get, load_config, read_raw_config
from hermes_cli.raphael_cmd import (
    disable_raphael_mode,
    enable_raphael_mode,
    raphael_setup_doctor,
)
from agent.raphael.config import raphael_effective_enabled
from agent.raphael.evolution import read_evolution_records
from agent.raphael.observer import build_raphael_observation_context
from agent.raphael.skill_trace import render_skill_summary, summarize_skill_usage
from agent.raphael.state import read_mission_state, read_state
from agent.raphael.status import collect_curator_health, render_status

_DISABLED_MESSAGE = (
    "Raphael mode is disabled. Use /raphael-enable or `hermes raphael enable` "
    "to re-enable /raphael-status."
)
_SKILL_TRACE_DISABLED_MESSAGE = (
    "Raphael Skill Trace is disabled. Use /raphael-enable or "
    "`hermes raphael enable` first, then set raphael.skill_trace.enabled: true "
    "to enable /raphael-skills."
)


def _raphael_enabled() -> bool:
    return raphael_effective_enabled(
        _read_config(),
        require_default_conversation=False,
    )


def _max_status_cards() -> int:
    raw_value = cfg_get(_read_config(), "raphael", "max_status_cards", default=20)
    return _bounded_int(raw_value, default=20, minimum=1)


def _bounded_int(raw_value, *, default: int, minimum: int) -> int:
    if isinstance(raw_value, bool):
        return default
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default
    return max(minimum, value)


def _skill_trace_config() -> dict:
    raw_value = cfg_get(_read_config(), "raphael", "skill_trace", default={})
    return raw_value if isinstance(raw_value, dict) else {}


def _skill_trace_enabled() -> bool:
    if not _raphael_enabled():
        return False
    raw_value = cfg_get(
        _read_config(),
        "raphael",
        "skill_trace",
        "enabled",
        default=True,
    )
    return raw_value is True


def _max_skill_summary_rows() -> int:
    raw_value = _skill_trace_config().get("max_summary_rows", 20)
    return _bounded_int(raw_value, default=20, minimum=0)


def _max_trace_events() -> int:
    raw_value = _skill_trace_config().get("max_trace_events", 500)
    return _bounded_int(raw_value, default=500, minimum=0)


def _read_config() -> dict:
    try:
        return read_raw_config()
    except Exception:
        return load_config()


def handle_status(raw_args: str) -> str:
    if raw_args.strip():
        return "Usage: /raphael-status"
    if not _raphael_enabled():
        return _DISABLED_MESSAGE
    mission = read_mission_state()
    return render_status(
        read_state(),
        max_cards=_max_status_cards(),
        evolution_records=read_evolution_records(limit=5),
        mission_state=mission.to_dict() if mission is not None else None,
        curator_health=collect_curator_health(),
    )


def handle_skills(raw_args: str) -> str:
    if raw_args.strip():
        return "Usage: /raphael-skills"
    if not _skill_trace_enabled():
        return _SKILL_TRACE_DISABLED_MESSAGE
    summaries = summarize_skill_usage(
        max_rows=_max_skill_summary_rows(),
        max_trace_events=_max_trace_events(),
    )
    return render_skill_summary(summaries)


def handle_doctor(raw_args: str) -> str:
    if raw_args.strip():
        return "Usage: /raphael-doctor"
    return raphael_setup_doctor().message


def handle_enable(raw_args: str) -> str:
    if raw_args.strip():
        return "Usage: /raphael-enable"
    return enable_raphael_mode().message


def handle_disable(raw_args: str) -> str:
    if raw_args.strip():
        return "Usage: /raphael-disable"
    return disable_raphael_mode().message


def handle_pre_llm_call(
    *,
    user_message="",
    conversation_history=None,
    turn_origin="foreground",
    runtime_contract=None,
    **_kwargs,
):
    context = build_raphael_observation_context(
        user_message,
        conversation_history=conversation_history,
        turn_origin=turn_origin,
        runtime_contract=runtime_contract,
    )
    if not context:
        return None
    return {"context": context}


def register(ctx) -> None:
    ctx.register_hook("pre_llm_call", handle_pre_llm_call)
    ctx.register_command(
        "raphael-status",
        handle_status,
        description="Show Raphael Sage King status",
        args_hint="",
    )
    ctx.register_command(
        "raphael-skills",
        handle_skills,
        description="Show Raphael skill evolution traces",
        args_hint="",
    )
    ctx.register_command(
        "raphael-doctor",
        handle_doctor,
        description="Check Raphael local setup",
        args_hint="",
    )
    ctx.register_command(
        "raphael-enable",
        handle_enable,
        description="Enable Raphael mode",
        args_hint="",
    )
    ctx.register_command(
        "raphael-disable",
        handle_disable,
        description="Disable Raphael mode",
        args_hint="",
    )
