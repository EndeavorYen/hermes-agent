from __future__ import annotations

import argparse

from typing import Callable


def build_raphael_parser(subparsers, *, cmd_raphael: Callable) -> None:
    parser = subparsers.add_parser(
        "raphael",
        help="Install, enable, disable, or inspect Raphael mode",
        description=(
            "Manage Raphael mode as a first-class Hermes control layer. "
            "`enable` and `install` both enable the bundled plugin and turn on "
            "default conversation-mode injection."
        ),
    )
    sub = parser.add_subparsers(dest="raphael_action")
    sub.add_parser("status", help="Show Raphael lifecycle state")
    doctor = sub.add_parser("doctor", help="Run a quota-free Raphael local setup check")
    doctor.add_argument(
        "--check",
        action="store_true",
        help="Exit nonzero when local setup is not ready",
    )
    install = sub.add_parser("install", help="Install/enable the bundled Raphael mode")
    install.add_argument(
        "--evolve",
        action="store_true",
        help="Enable durable skill/memory evolution writes instead of audit-only mode",
    )
    enable = sub.add_parser("enable", help="Enable Raphael mode")
    enable.add_argument(
        "--evolve",
        action="store_true",
        help="Enable durable skill/memory evolution writes instead of audit-only mode",
    )
    sub.add_parser("disable", help="Disable Raphael mode but keep commands available")
    sub.add_parser("uninstall", help="Disable Raphael mode and disable the plugin")
    sub.add_parser("reset", help="Alias for uninstall")
    proposal = sub.add_parser(
        "proposal",
        help="Approve or reject a pending Raphael evolution proposal",
    )
    proposal_sub = proposal.add_subparsers(dest="proposal_action", required=True)
    for action, help_text in (
        ("approve", "Approve a pending proposal for manual rollout"),
        ("reject", "Reject a pending proposal and keep an audit trail"),
    ):
        proposal_action = proposal_sub.add_parser(action, help=help_text)
        proposal_action.add_argument("proposal_id")
        proposal_action.add_argument("--reason", default="")
        proposal_action.add_argument("--reviewer", default="operator")
    readiness = sub.add_parser("readiness", help="Show public-release readiness gates")
    readiness.add_argument(
        "--readiness-profile",
        choices=("media", "llm", "llm-only"),
        default="media",
        dest="profile",
        help="Readiness profile to evaluate; media requires visual live E2E",
    )
    readiness.add_argument(
        "--check",
        action="store_true",
        help="Exit nonzero when the selected readiness profile is blocked",
    )
    readiness.add_argument(
        "--llm-smoke-session-id",
        default="",
        help="Session id for an operator-recorded passing LLM-only live smoke",
    )
    readiness.add_argument(
        "--llm-smoke-evidence-file",
        default="",
        help="JSON evidence file produced from the reviewed LLM-only live smoke",
    )
    readiness.add_argument(
        "--gate-output",
        default="",
        help="Optional JSON output path for the public readiness gate report",
    )
    media_readiness = sub.add_parser(
        "media-readiness",
        help=(
            "Show OpenAI image media-slice readiness without claiming Grok "
            "or video readiness"
        ),
    )
    media_readiness.add_argument(
        "--openai-image-evidence-file",
        default="",
        help="JSON evidence file for the current selected OpenAI image artifact",
    )
    media_readiness.add_argument(
        "--openai-image-session-id",
        default="",
        help="Expected session id for the current OpenAI image evidence file",
    )
    media_readiness.add_argument(
        "--current-selected-artifact-id",
        default="",
        help="Artifact id currently selected for public delivery",
    )
    media_readiness.add_argument(
        "--max-evidence-age-seconds",
        type=int,
        default=86400,
        help="Maximum allowed age for OpenAI image evidence before it is stale",
    )
    media_readiness.add_argument(
        "--gate-output",
        default="",
        help="Optional JSON output path for the media readiness gate report",
    )
    release_gate = sub.add_parser(
        "release-gate",
        help="Write trusted Raphael release-gate evidence after audited smokes",
    )
    release_gate.add_argument(
        "--readiness-profile",
        choices=("media", "llm", "llm-only"),
        default="media",
        dest="profile",
        help="Readiness profile to write/evaluate",
    )
    release_gate.add_argument(
        "--lifecycle-evidence-file",
        default="",
        help="JSON evidence file for install, enable, disable, and uninstall smoke",
    )
    release_gate.add_argument(
        "--llm-readiness-file",
        default="",
        help="JSON output produced by hermes raphael readiness",
    )
    release_gate.add_argument(
        "--media-readiness-file",
        default="",
        help="JSON output produced by hermes raphael media-readiness",
    )
    release_gate.add_argument(
        "--docs-file",
        action="append",
        dest="docs_files",
        default=[],
        help="Public docs or release notes file to scan for overclaiming",
    )
    release_gate.add_argument(
        "--gate-output",
        default="",
        help="Optional JSON output path for the release-candidate gate report",
    )
    release_gate.add_argument("--llm-smoke-session-id", default=None)
    release_gate.add_argument("--llm-smoke-command", default="rtk hermes chat")
    release_gate.add_argument(
        "--llm-tool-call-count",
        type=int,
        default=None,
        help=argparse.SUPPRESS,
    )
    release_gate.add_argument(
        "--llm-smoke-transcript",
        "--llm-transcript-report",
        dest="llm_transcript_report_path",
        default=None,
    )
    release_gate.add_argument(
        "--llm-summon-sections-verified",
        action="store_true",
        default=None,
        help=argparse.SUPPRESS,
    )
    release_gate.add_argument(
        "--llm-full-body-preserved",
        action="store_true",
        default=None,
        help=argparse.SUPPRESS,
    )
    release_gate.add_argument(
        "--llm-no-visual-failure-trace",
        action="store_true",
        default=None,
        help=argparse.SUPPRESS,
    )
    release_gate.add_argument(
        "--package-install-report",
        dest="package_install_report_path",
        default=None,
    )
    release_gate.add_argument("--hostile-review-command", default=None)
    release_gate.add_argument("--hostile-review-run-id", default=None)
    release_gate.add_argument(
        "--hostile-review-verdict",
        default=None,
        help=argparse.SUPPRESS,
    )
    release_gate.add_argument(
        "--hostile-review-blockers",
        type=int,
        default=None,
        help=argparse.SUPPRESS,
    )
    release_gate.add_argument("--hostile-review-report", dest="hostile_review_report_path", default=None)
    release_gate.add_argument("--non-visual-regression-command", default=None)
    release_gate.add_argument("--non-visual-regression-run-id", default=None)
    release_gate.add_argument(
        "--non-visual-regression-passed-count",
        type=int,
        default=None,
        help=argparse.SUPPRESS,
    )
    release_gate.add_argument(
        "--non-visual-regression-visual-quota-used",
        action="store_true",
        default=None,
        help=argparse.SUPPRESS,
    )
    release_gate.add_argument(
        "--non-visual-regression-report",
        dest="non_visual_regression_report_path",
        default=None,
    )
    release_gate.add_argument("--visual-run-id", default=None)
    release_gate.add_argument("--visual-command", default=None)
    release_gate.add_argument("--visual-preflight-report", dest="visual_preflight_report_path", default=None)
    release_gate.add_argument("--visual-e2e-report", dest="visual_e2e_report_path", default=None)
    release_gate.add_argument(
        "--visual-selected-artifact-id",
        default=None,
        help=argparse.SUPPRESS,
    )
    release_gate.add_argument(
        "--visual-artifact-quality-verdict",
        default=None,
        help=argparse.SUPPRESS,
    )
    release_gate.add_argument(
        "--visual-fresh-artifact",
        action="store_true",
        default=None,
        help=argparse.SUPPRESS,
    )
    demo = sub.add_parser("demo", help="Render an offline Raphael capability demo")
    demo.add_argument(
        "prompt",
        nargs="*",
        help="Optional sample user request to route through the Raphael demo",
    )
    parser.set_defaults(func=cmd_raphael)


__all__ = ["build_raphael_parser"]
