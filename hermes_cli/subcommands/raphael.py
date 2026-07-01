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
    readiness_parser = raphael_subparsers.add_parser(
        "readiness",
        help="Show public LLM-slice readiness without claiming media readiness",
    )
    readiness_parser.add_argument(
        "--llm-smoke-session-id",
        default="",
        help="Session id for an operator-recorded passing LLM-only live smoke",
    )
    readiness_parser.add_argument(
        "--llm-smoke-evidence-file",
        default="",
        help="JSON evidence file produced from the reviewed LLM-only live smoke",
    )
    readiness_parser.add_argument(
        "--gate-output",
        default="",
        help="Optional JSON output path for the public readiness gate report",
    )
    media_readiness_parser = raphael_subparsers.add_parser(
        "media-readiness",
        help="Show OpenAI image media-slice readiness without claiming Grok or video readiness",
    )
    media_readiness_parser.add_argument(
        "--openai-image-evidence-file",
        default="",
        help="JSON evidence file for the current selected OpenAI image artifact",
    )
    media_readiness_parser.add_argument(
        "--openai-image-session-id",
        default="",
        help="Expected session id for the current OpenAI image evidence file",
    )
    media_readiness_parser.add_argument(
        "--current-selected-artifact-id",
        default="",
        help="Artifact id currently selected for public delivery",
    )
    media_readiness_parser.add_argument(
        "--max-evidence-age-seconds",
        type=int,
        default=86400,
        help="Maximum allowed age for OpenAI image evidence before it is stale",
    )
    media_readiness_parser.add_argument(
        "--gate-output",
        default="",
        help="Optional JSON output path for the media readiness gate report",
    )
    release_gate_parser = raphael_subparsers.add_parser(
        "release-gate",
        help="Verify Raphael release-candidate readiness without overclaiming",
    )
    release_gate_parser.add_argument(
        "--lifecycle-evidence-file",
        default="",
        help="JSON evidence file for install, enable, disable, and uninstall smoke",
    )
    release_gate_parser.add_argument(
        "--llm-readiness-file",
        default="",
        help="JSON output produced by hermes raphael readiness",
    )
    release_gate_parser.add_argument(
        "--media-readiness-file",
        default="",
        help="JSON output produced by hermes raphael media-readiness",
    )
    release_gate_parser.add_argument(
        "--docs-file",
        action="append",
        dest="docs_files",
        default=[],
        help="Public docs or release notes file to scan for overclaiming",
    )
    release_gate_parser.add_argument(
        "--gate-output",
        default="",
        help="Optional JSON output path for the release-candidate gate report",
    )
    raphael_subparsers.add_parser(
        "uninstall",
        help="Disable Raphael and remove Raphael-owned runtime state",
    )
    proposal_parser = raphael_subparsers.add_parser(
        "proposal",
        help="Approve or reject auditable Raphael evolution proposals",
    )
    proposal_subparsers = proposal_parser.add_subparsers(dest="proposal_action")
    approve_parser = proposal_subparsers.add_parser(
        "approve",
        help="Record approval for a Raphael proposal without mutating durable policy",
    )
    approve_parser.add_argument("proposal_id")
    reject_parser = proposal_subparsers.add_parser(
        "reject",
        help="Reject a Raphael proposal and keep durable policy unchanged",
    )
    reject_parser.add_argument("proposal_id")

    raphael_parser.set_defaults(func=cmd_raphael)
