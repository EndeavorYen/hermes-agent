"""Guard baoyu-comic docs against stale prompt-only image_generate guidance."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

BAOYU_COMIC_DOCS = [
    Path("skills/creative/baoyu-comic/SKILL.md"),
    Path("skills/creative/baoyu-comic/references/workflow.md"),
    Path("skills/creative/baoyu-comic/PORT_NOTES.md"),
    Path("website/docs/user-guide/skills/bundled/creative/creative-baoyu-comic.md"),
]

STALE_PROMPT_ONLY_CLAIMS = [
    "prompt-only",
    "does not accept reference images",
    "cannot accept images as visual input",
    "never sees the png as a visual input",
    "sole vehicle for character consistency",
    "sole consistency mechanism",
]


def test_baoyu_comic_docs_do_not_downgrade_reference_images():
    """Comic guidance must not steer image2 away from real reference images."""
    for rel_path in BAOYU_COMIC_DOCS:
        content = (REPO_ROOT / rel_path).read_text(encoding="utf-8").lower()
        for stale_claim in STALE_PROMPT_ONLY_CLAIMS:
            assert stale_claim not in content, f"{rel_path} still says {stale_claim!r}"
