from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.raphael_completion_audit import audit_completion
from scripts.raphael_release_slice_boundary import (
    classify_paths,
    git_status_paths,
    inspect_content_boundaries,
)


REQUIRED_COMMANDS: list[str] = [
    "venv/bin/python scripts/raphael_completion_audit.py --target scoped",
    "venv/bin/python scripts/raphael_release_docs_audit.py",
    "venv/bin/python scripts/raphael_release_slice_boundary.py --profile llm --from-git-status",
    "venv/bin/python -m pytest tests/scripts/test_raphael_release_slice_manifest.py tests/scripts/test_raphael_completion_audit.py tests/scripts/test_raphael_release_slice_boundary.py -q",
    "venv/bin/ruff check scripts/raphael_release_slice_manifest.py tests/scripts/test_raphael_release_slice_manifest.py",
    "git diff --check",
]

FULL_MEDIA_BLOCKED_CLAIMS: list[str] = [
    "sage_king",
    "wow",
    "big_evolution",
    "full_media",
    "xai_grok_generation",
    "video_generation",
]


def build_release_slice_manifest(
    paths: Iterable[str],
    *,
    llm_readiness: Mapping[str, Any],
    media_readiness: Mapping[str, Any],
    root: str | Path = ".",
) -> dict[str, Any]:
    boundary = classify_paths(paths, profile="llm")
    content = inspect_content_boundaries(boundary.included, root=root, profile="llm")
    completion = audit_completion(
        llm_readiness=llm_readiness,
        media_readiness=media_readiness,
        boundary_summary={
            "unclassified_paths": list(boundary.unclassified),
            "content_violations": list(content.violations),
            "deferred_media_paths": list(boundary.deferred_media),
        },
    )

    blockers = [
        blocker
        for blocker in completion.blockers
        if blocker.startswith("llm:") or blocker.startswith("boundary:")
    ]
    if boundary.unclassified and "boundary:unclassified_paths" not in blockers:
        blockers.append("boundary:unclassified_paths")
    if content.violations and "boundary:content_violations" not in blockers:
        blockers.append("boundary:content_violations")

    scoped_release_ready = completion.scoped_release_ready and not any(
        blocker.startswith("boundary:") for blocker in blockers
    )
    status = "reviewable" if scoped_release_ready else "blocked"
    review_strategy = (
        "classify_or_remove_unknown_paths"
        if boundary.unclassified or content.violations
        else "split_required"
        if boundary.deferred_media
        else "single_llm_slice"
    )
    return {
        "schema_version": 1,
        "status": status,
        "review_strategy": review_strategy,
        "allowed_public_claims": ["llm_only"] if scoped_release_ready else [],
        "blocked_public_claims": FULL_MEDIA_BLOCKED_CLAIMS,
        "blockers": blockers,
        "counts": {
            "llm_slice_paths": len(boundary.included),
            "deferred_media_paths": len(boundary.deferred_media),
            "unclassified_paths": len(boundary.unclassified),
            "content_violations": len(content.violations),
        },
        "slices": [
            {
                "id": "llm_scoped_release",
                "release_ready": scoped_release_ready,
                "paths": list(boundary.included),
            },
            {
                "id": "deferred_media",
                "release_ready": False,
                "paths": list(boundary.deferred_media),
            },
        ],
        "unclassified_paths": list(boundary.unclassified),
        "content_violations": list(content.violations),
        "completion": {
            "status": completion.status,
            "scoped_release_ready": completion.scoped_release_ready,
            "ultimate_ready": completion.ultimate_ready,
            "blockers": list(completion.blockers),
            "warnings": list(completion.warnings),
        },
        "required_commands": REQUIRED_COMMANDS,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render a reviewable Raphael release-slice manifest."
    )
    parser.add_argument(
        "--from-git-status",
        action="store_true",
        help="Read paths from git status --short in the current checkout.",
    )
    parser.add_argument(
        "--llm-readiness",
        default=None,
    )
    parser.add_argument(
        "--media-readiness",
        default=None,
    )
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)
    llm_readiness = (
        Path(args.llm_readiness)
        if args.llm_readiness
        else _default_readiness_path("llm")
    )
    media_readiness = (
        Path(args.media_readiness)
        if args.media_readiness
        else _default_readiness_path("media")
    )

    paths = git_status_paths() if args.from_git_status else tuple(args.paths)
    manifest = build_release_slice_manifest(
        paths,
        llm_readiness=_read_json(llm_readiness),
        media_readiness=_read_json(media_readiness),
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if manifest["status"] == "reviewable" else 1


def _read_json(path: Path) -> Mapping[str, Any]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    return parsed if isinstance(parsed, Mapping) else {}


def _default_readiness_path(profile: str) -> Path:
    home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
    return home / "raphael" / f"release_readiness.{profile}.json"


if __name__ == "__main__":
    raise SystemExit(main())
