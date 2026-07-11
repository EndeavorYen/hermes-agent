"""Regression coverage for contributor-attribution CI mappings."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_SCRIPT = REPO_ROOT / "scripts" / "release.py"


def author_map() -> dict[str, str]:
    tree = ast.parse(RELEASE_SCRIPT.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "AUTHOR_MAP"
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("scripts/release.py must define AUTHOR_MAP")


class ReleaseAuthorMapTests(unittest.TestCase):
    def test_local_governance_author_email_is_mapped(self) -> None:
        self.assertEqual(
            author_map()["endeavorisforever@gmail.com"],
            "EndeavorYen",
        )


if __name__ == "__main__":
    unittest.main()
