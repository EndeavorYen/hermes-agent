"""Behavioral coverage for the local Hermes branch-governance guard."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hermes_branch_governance.py"
PRE_PUSH_HOOK = REPO_ROOT / ".githooks" / "pre-push"
ZERO_SHA = "0" * 40
LOCAL_SHA = "a" * 40


def pre_push_line(local_ref: str, local_sha: str, remote_ref: str, remote_sha: str) -> str:
    """Build Git's documented pre-push protocol line."""
    return f"{local_ref} {local_sha} {remote_ref} {remote_sha}\n"


def run_guard(
    *args: str,
    stdin: str = "",
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command_env = os.environ.copy()
    if env:
        command_env.update(env)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
        env=command_env,
    )


class BranchGrammarTests(unittest.TestCase):
    def test_accepts_canonical_branch_names(self) -> None:
        for branch in (
            "main",
            "local/main",
            "runtime/current",
            "upgrade/v2026.7.7.2",
            "feat/raphael/control-kernel-hardening",
            "fix/story-video/azure-voice-contract",
            "docs/repo/branch-governance",
            "upstream/fix/xai/error-classification",
        ):
            with self.subTest(branch=branch):
                result = run_guard("validate-branch", branch)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_legacy_or_ambiguous_branch_names(self) -> None:
        for branch in (
            "main-hermes-v2026.7.7.2-local",
            "wip/story-video",
            "integration/hermes-v2026.7.7.2-local",
            "raphael/release-candidate",
            "runtime/hermes-v2026.7.7.2-local",
            "upstream-pr/xai-video-error-classification",
        ):
            with self.subTest(branch=branch):
                result = run_guard("validate-branch", branch)
                self.assertNotEqual(result.returncode, 0)


class PrePushPolicyTests(unittest.TestCase):
    def test_hook_resolves_guard_from_the_shared_repository_root(self) -> None:
        hook = PRE_PUSH_HOOK.read_text(encoding="utf-8")

        self.assertIn("git rev-parse --git-common-dir", hook)
        self.assertIn("hermes_branch_governance.py", hook)

    def test_allows_canonical_local_main_checkpoint_to_origin(self) -> None:
        result = run_guard(
            "pre-push",
            "origin",
            "https://github.com/EndeavorYen/hermes-agent.git",
            stdin=pre_push_line(
                "refs/heads/local/main", LOCAL_SHA, "refs/heads/local/main", ZERO_SHA
            ),
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_allows_only_explicit_main_mirror_sync_to_rewrite_origin_main(self) -> None:
        result = run_guard(
            "pre-push",
            "origin",
            "https://github.com/EndeavorYen/hermes-agent.git",
            stdin=pre_push_line("refs/heads/main", LOCAL_SHA, "refs/heads/main", "b" * 40),
            env={"HERMES_GOVERNANCE_ALLOW_MIRROR_SYNC": "1"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_main_rewrite_without_explicit_mirror_sync(self) -> None:
        result = run_guard(
            "pre-push",
            "origin",
            "https://github.com/EndeavorYen/hermes-agent.git",
            stdin=pre_push_line("refs/heads/main", LOCAL_SHA, "refs/heads/main", "b" * 40),
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mirror", result.stderr)

    def test_allows_new_canonical_archive_tag_to_origin(self) -> None:
        tag_ref = "refs/tags/archive/2026-07-11/runtime/pre-canonical-cutover"
        result = run_guard(
            "pre-push",
            "origin",
            "https://github.com/EndeavorYen/hermes-agent.git",
            stdin=pre_push_line(tag_ref, LOCAL_SHA, tag_ref, ZERO_SHA),
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_archive_tag_rewrite_or_deletion(self) -> None:
        tag_ref = "refs/tags/archive/2026-07-11/runtime/pre-canonical-cutover"
        rewrite = run_guard(
            "pre-push",
            "origin",
            "https://github.com/EndeavorYen/hermes-agent.git",
            stdin=pre_push_line(tag_ref, LOCAL_SHA, tag_ref, "b" * 40),
        )
        deletion = run_guard(
            "pre-push",
            "origin",
            "https://github.com/EndeavorYen/hermes-agent.git",
            stdin=pre_push_line("(delete)", ZERO_SHA, tag_ref, LOCAL_SHA),
        )

        self.assertNotEqual(rewrite.returncode, 0)
        self.assertIn("immutable", rewrite.stderr)
        self.assertNotEqual(deletion.returncode, 0)
        self.assertIn("delete", deletion.stderr)

    def test_rejects_noncanonical_or_upstream_tag_push(self) -> None:
        release_tag_ref = "refs/tags/v2026.7.7.2"
        archive_tag_ref = "refs/tags/archive/2026-07-11/runtime/pre-canonical-cutover"
        invalid_name = run_guard(
            "pre-push",
            "origin",
            "https://github.com/EndeavorYen/hermes-agent.git",
            stdin=pre_push_line(release_tag_ref, LOCAL_SHA, release_tag_ref, ZERO_SHA),
        )
        upstream = run_guard(
            "pre-push",
            "upstream",
            "https://github.com/NousResearch/hermes-agent.git",
            stdin=pre_push_line(archive_tag_ref, LOCAL_SHA, archive_tag_ref, ZERO_SHA),
        )

        self.assertNotEqual(invalid_name.returncode, 0)
        self.assertIn("archive", invalid_name.stderr)
        self.assertNotEqual(upstream.returncode, 0)
        self.assertIn("upstream", upstream.stderr.lower())

    def test_rejects_direct_push_to_upstream(self) -> None:
        result = run_guard(
            "pre-push",
            "upstream",
            "https://github.com/NousResearch/hermes-agent.git",
            stdin=pre_push_line(
                "refs/heads/upstream/fix/xai/error-classification",
                LOCAL_SHA,
                "refs/heads/main",
                ZERO_SHA,
            ),
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("upstream", result.stderr.lower())

    def test_rejects_legacy_wip_push_even_to_origin(self) -> None:
        result = run_guard(
            "pre-push",
            "origin",
            "https://github.com/EndeavorYen/hermes-agent.git",
            stdin=pre_push_line(
                "refs/heads/wip/story-video", LOCAL_SHA, "refs/heads/wip/story-video", ZERO_SHA
            ),
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("wip", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
