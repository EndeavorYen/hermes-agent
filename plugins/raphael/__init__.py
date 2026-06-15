from __future__ import annotations

from hermes_cli.config import cfg_get, load_config, read_raw_config
from agent.raphael.state import read_state
from agent.raphael.status import render_status

_DISABLED_MESSAGE = (
    "Raphael Advisor is disabled. Set raphael.enabled: true to enable "
    "/raphael-status."
)


def _raphael_enabled() -> bool:
    return cfg_get(_read_config(), "raphael", "enabled", default=False) is True


def _max_status_cards() -> int:
    raw_value = cfg_get(_read_config(), "raphael", "max_status_cards", default=20)
    if isinstance(raw_value, bool):
        return 20
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return 20
    return max(1, value)


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


def register(ctx) -> None:
    ctx.register_command(
        "raphael-status",
        handle_status,
        description="Show read-only Raphael advisor status",
        args_hint="",
    )
