"""``hermes raphael`` lifecycle subcommand parser."""

from __future__ import annotations

from typing import Callable


def build_raphael_parser(subparsers, *, cmd_raphael: Callable) -> None:
    """Attach the ``raphael`` lifecycle subcommand to ``subparsers``."""
    raphael_parser = subparsers.add_parser(
        "raphael",
        help="Install, enable, disable, inspect, or uninstall Raphael mode",
        description=(
            "Manage the Raphael control-layer lifecycle. This command only "
            "controls setup state; it does not prove final release readiness."
        ),
    )
    raphael_subparsers = raphael_parser.add_subparsers(dest="raphael_action")

    raphael_subparsers.add_parser(
        "install",
        help="Install Raphael lifecycle configuration without enabling injection",
    )
    raphael_subparsers.add_parser(
        "enable",
        help="Enable Raphael control-layer prompt, observation, and response surfaces",
    )
    raphael_subparsers.add_parser(
        "disable",
        help="Disable Raphael control-layer injection while keeping it installed",
    )
    raphael_subparsers.add_parser(
        "status",
        help="Show Raphael lifecycle status and the next setup action",
    )
    raphael_subparsers.add_parser(
        "uninstall",
        help="Disable Raphael and remove Raphael-owned runtime state",
    )

    raphael_parser.set_defaults(func=cmd_raphael)
