"""Behavioral coverage for the local Hermes branch-governance guard."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hermes_branch_governance.py"
PRE_PUSH_HOOK = REPO_ROOT / ".githooks" / "pre-push"
ZERO_SHA = "0" * 40
LOCAL_SHA = "a" * 40


def run_guard(*args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
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
            stdin=f"{LOCAL_SHA} refs/heads/local/main {ZERO_SHA} refs/heads/local/main\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_direct_push_to_upstream(self) -> None:
        result = run_guard(
            "pre-push",
            "upstream",
            "https://github.com/NousResearch/hermes-agent.git",
            stdin=f"{LOCAL_SHA} refs/heads/upstream/fix/xai/error-classification {ZERO_SHA} refs/heads/main\n",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("upstream", result.stderr.lower())

    def test_rejects_legacy_wip_push_even_to_origin(self) -> None:
        result = run_guard(
            "pre-push",
            "origin",
            "https://github.com/EndeavorYen/hermes-agent.git",
            stdin=f"{LOCAL_SHA} refs/heads/wip/story-video {ZERO_SHA} refs/heads/wip/story-video\n",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("wip", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
