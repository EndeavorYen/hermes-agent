#!/usr/bin/env python3
"""Enforce Hermes's local branch names and safe push routing.

Installed through ``core.hooksPath=.githooks``.  This guard intentionally
blocks accidental pushes; documented promotion commands remain responsible for
review and runtime evidence.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Iterable


CANONICAL_BRANCHES = {"main", "local/main", "runtime/current"}
PROTECTED_BRANCHES = CANONICAL_BRANCHES
LEGACY_PREFIXES = (
    "backup/",
    "cleanup/",
    "codex/",
    "integration/",
    "live/",
    "main-",
    "raphael/",
    "runtime/",
    "upstream-pr/",
    "wip/",
)
TOPIC_RE = re.compile(
    r"^(?:feat|fix|docs|test|refactor|chore|hotfix)/"
    r"[a-z0-9]+(?:-[a-z0-9]+)*/[a-z0-9]+(?:-[a-z0-9]+)*$"
)
UPSTREAM_RE = re.compile(
    r"^upstream/(?:feat|fix|docs|test|refactor)/"
    r"[a-z0-9]+(?:-[a-z0-9]+)*/[a-z0-9]+(?:-[a-z0-9]+)*$"
)
UPGRADE_RE = re.compile(r"^upgrade/v\d{4}\.\d{1,2}\.\d{1,2}(?:\.\d+)*$")
ZERO_SHA = "0" * 40


def branch_from_ref(ref: str) -> str | None:
    """Return a branch name from a full heads ref, if it is one."""
    prefix = "refs/heads/"
    return ref[len(prefix) :] if ref.startswith(prefix) else None


def validate_branch_name(branch: str) -> str | None:
    """Return an error for an invalid branch name, otherwise ``None``."""
    if branch in CANONICAL_BRANCHES:
        return None
    if branch.startswith(LEGACY_PREFIXES):
        return f"{branch!r} uses a forbidden legacy or ambiguous namespace"
    if UPGRADE_RE.fullmatch(branch) or TOPIC_RE.fullmatch(branch) or UPSTREAM_RE.fullmatch(branch):
        return None
    return (
        f"{branch!r} is not a canonical role or a permitted scoped branch "
        "(use upgrade/v..., feat|fix|docs|test|refactor|chore|hotfix/<area>/<slug>, "
        "or upstream/<type>/<area>/<slug>)"
    )


def is_fast_forward(remote_sha: str, local_sha: str) -> bool:
    """Return whether pushing ``local_sha`` would fast-forward ``remote_sha``."""
    if remote_sha == ZERO_SHA:
        return True
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", remote_sha, local_sha],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def validate_push(
    remote_name: str,
    local_sha: str,
    local_ref: str,
    remote_sha: str,
    remote_ref: str,
) -> str | None:
    """Return an error for one pre-push update, otherwise ``None``."""
    local_branch = branch_from_ref(local_ref)
    remote_branch = branch_from_ref(remote_ref)

    if remote_branch is None:
        return f"ref {remote_ref!r} is not a branch ref"

    if local_sha == ZERO_SHA:
        if remote_branch in PROTECTED_BRANCHES:
            return f"refusing to delete protected branch {remote_branch!r}"
        if remote_branch.startswith(LEGACY_PREFIXES) and not os.getenv(
            "HERMES_GOVERNANCE_ALLOW_LEGACY_CLEANUP"
        ):
            return (
                f"refusing to delete legacy branch {remote_branch!r} without "
                "HERMES_GOVERNANCE_ALLOW_LEGACY_CLEANUP=1"
            )
        return None

    if remote_name == "upstream":
        return "direct pushes to upstream are forbidden; push an upstream/* branch to origin instead"
    if remote_name != "origin":
        return f"push remote {remote_name!r} is not approved; use origin"
    if local_branch is None:
        return f"local ref {local_ref!r} is not a branch ref"

    name_error = validate_branch_name(local_branch)
    if name_error:
        return name_error
    if local_branch != remote_branch:
        return (
            f"refusing to publish {local_branch!r} as {remote_branch!r}; "
            "origin branch names must exactly match local branch names"
        )
    if local_branch == "main" and not os.getenv("HERMES_GOVERNANCE_ALLOW_MIRROR_SYNC"):
        return "origin/main is an upstream mirror; use the documented mirror command with explicit authorization"
    if local_branch in PROTECTED_BRANCHES and not is_fast_forward(remote_sha, local_sha):
        return f"refusing non-fast-forward update to protected branch {local_branch!r}"
    return None


def validate_push_stream(remote_name: str, lines: Iterable[str]) -> list[str]:
    """Validate all pre-push protocol lines and return actionable errors."""
    errors: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        fields = line.split()
        if len(fields) != 4:
            errors.append(f"invalid pre-push input line: {raw_line.rstrip()!r}")
            continue
        error = validate_push(remote_name, *fields)
        if error:
            errors.append(error)
    return errors


def command_validate_branch(branch: str) -> int:
    error = validate_branch_name(branch)
    if error:
        print(f"branch governance: {error}", file=sys.stderr)
        return 1
    return 0


def command_pre_push(remote_name: str) -> int:
    errors = validate_push_stream(remote_name, sys.stdin)
    if errors:
        for error in errors:
            print(f"branch governance: {error}", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate-branch")
    validate.add_argument("branch")
    pre_push = subparsers.add_parser("pre-push")
    pre_push.add_argument("remote_name")
    pre_push.add_argument("remote_url")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate-branch":
        return command_validate_branch(args.branch)
    if args.command == "pre-push":
        return command_pre_push(args.remote_name)
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
