from __future__ import annotations

from hermes_cli.config import cfg_get, load_config, read_raw_config
from agent.raphael.skill_trace import render_skill_summary, summarize_skill_usage
from agent.raphael.state import read_state
from agent.raphael.status import render_status

_DISABLED_MESSAGE = (
    "Raphael Advisor is disabled. Set raphael.enabled: true to enable "
    "/raphael-status."
)
_SKILL_TRACE_DISABLED_MESSAGE = (
    "Raphael Skill Trace is disabled. Set raphael.skill_trace.enabled: true "
    "to enable /raphael-skills."
)


def _raphael_enabled() -> bool:
    return cfg_get(_read_config(), "raphael", "enabled", default=False) is True


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
    return render_status(read_state(), max_cards=_max_status_cards())


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


def register(ctx) -> None:
    ctx.register_command(
        "raphael-status",
        handle_status,
        description="Show read-only Raphael advisor status",
        args_hint="",
    )
    ctx.register_command(
        "raphael-skills",
        handle_skills,
        description="Show read-only Raphael skill usage traces",
        args_hint="",
    )
