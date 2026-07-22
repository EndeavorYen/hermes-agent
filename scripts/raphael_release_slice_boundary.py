"""CLI wrapper for the packaged Raphael release-boundary policy."""

from __future__ import annotations

from hermes_cli.release_evidence.raphael.raphael_release_slice_boundary import (
    DEFERRED_IMPORT_PREFIXES,
    LLM_DEFERRED_MEDIA_PREFIXES,
    LLM_INCLUDE_PREFIXES,
    STRICT_CONTENT_BOUNDARY_PREFIXES,
    BoundaryClassification,
    ContentBoundaryInspection,
    _path_from_status_line,
    classify_paths,
    git_diff_paths,
    git_status_paths,
    inspect_content_boundaries,
    main,
    render_content_summary,
    render_summary,
)

__all__ = [
    "DEFERRED_IMPORT_PREFIXES",
    "LLM_DEFERRED_MEDIA_PREFIXES",
    "LLM_INCLUDE_PREFIXES",
    "STRICT_CONTENT_BOUNDARY_PREFIXES",
    "BoundaryClassification",
    "ContentBoundaryInspection",
    "_path_from_status_line",
    "classify_paths",
    "git_diff_paths",
    "git_status_paths",
    "inspect_content_boundaries",
    "main",
    "render_content_summary",
    "render_summary",
]


if __name__ == "__main__":
    raise SystemExit(main())
