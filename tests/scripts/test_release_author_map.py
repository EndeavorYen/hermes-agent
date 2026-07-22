"""Regression coverage for contributor-attribution CI mappings."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_SCRIPT = REPO_ROOT / "scripts" / "release.py"


def author_map() -> dict[str, str]:
    tree = ast.parse(RELEASE_SCRIPT.read_text(encoding="utf-8"))
    legacy_map: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        target_names = {
            target.id for target in node.targets if isinstance(target, ast.Name)
        }
        if "LEGACY_AUTHOR_MAP" in target_names:
            legacy_map = ast.literal_eval(node.value)
        if "AUTHOR_MAP" in target_names:
            try:
                return ast.literal_eval(node.value)
            except (TypeError, ValueError):
                # v0.19 builds AUTHOR_MAP by overlaying directory-backed
                # contributor records on the frozen literal legacy map.
                # The governance identity asserted below remains in that
                # literal, so parse it without importing the release script.
                return legacy_map
    raise AssertionError("scripts/release.py must define AUTHOR_MAP")


class ReleaseAuthorMapTests(unittest.TestCase):
    def test_local_governance_author_email_is_mapped(self) -> None:
        self.assertEqual(
            author_map()["endeavorisforever@gmail.com"],
            "EndeavorYen",
        )


if __name__ == "__main__":
    unittest.main()
