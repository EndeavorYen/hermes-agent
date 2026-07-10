from __future__ import annotations

import argparse
import ast
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


LLM_INCLUDE_PREFIXES: tuple[str, ...] = (
    "MANIFEST.in",
    "agent/background_review.py",
    "agent/raphael/",
    "agent/turn_finalizer.py",
    "docs/raphael-llm-public-slice.md",
    "docs/raphael-media-readiness.md",
    "docs/raphael-release-candidate.md",
    "docs/raphael-release-slice-audit.md",
    "hermes_cli/config.py",
    "hermes_cli/main.py",
    "hermes_cli/plugins.py",
    "hermes_cli/raphael_lifecycle.py",
    "hermes_cli/release_evidence/raphael/",
    "hermes_cli/raphael_cmd.py",
    "hermes_cli/subcommands/raphael.py",
    "plugins/raphael/",
    "pyproject.toml",
    "run_agent.py",
    "scripts/raphael_completion_audit.py",
    "scripts/raphael_release_docs_audit.py",
    "scripts/raphael_package_install_smoke.py",
    "scripts/raphael_release_slice_boundary.py",
    "scripts/raphael_release_slice_manifest.py",
    "tests/agent/test_raphael_",
    "tests/hermes_cli/test_raphael_",
    "tests/plugins/test_raphael_plugin.py",
    "tests/run_agent/test_background_review.py",
    "tests/scripts/test_raphael_completion_audit.py",
    "tests/scripts/test_raphael_package_install_smoke.py",
    "tests/scripts/test_raphael_release_docs_audit.py",
    "tests/scripts/test_raphael_release_slice_boundary.py",
    "tests/scripts/test_raphael_release_slice_manifest.py",
)

LLM_DEFERRED_MEDIA_PREFIXES: tuple[str, ...] = (
    "agent/visual/",
    "gateway/",
    "plugins/image_gen/",
    "scripts/grok_web_imagine_live_e2e.py",
    "scripts/openai_visual_live_e2e.py",
    "scripts/raphael_visual_quality_review.py",
    "scripts/visual_live_provider_e2e.py",
    "tests/gateway/",
    "tests/plugins/image_gen/",
    "tests/scripts/test_grok_web_imagine_live_e2e.py",
    "tests/scripts/test_openai_visual_live_e2e.py",
    "tests/scripts/test_raphael_visual_quality_review.py",
    "tests/scripts/test_visual_live_provider_e2e.py",
    "tests/tools/test_visual_",
    "tests/visual/",
    "tools/visual_",
)

DEFERRED_IMPORT_PREFIXES: tuple[str, ...] = (
    "agent.visual",
    "gateway.run",
    "gateway.platforms.base",
    "plugins.image_gen",
    "tools.visual_agent_tool",
    "tools.visual_package_tool",
)

STRICT_CONTENT_BOUNDARY_PREFIXES: tuple[str, ...] = (
    "agent/background_review.py",
    "agent/raphael/",
    "agent/turn_finalizer.py",
    "hermes_cli/raphael_lifecycle.py",
    "hermes_cli/raphael_cmd.py",
    "hermes_cli/release_evidence/raphael/raphael_release_slice_boundary.py",
    "hermes_cli/subcommands/raphael.py",
    "plugins/raphael/",
    "scripts/raphael_completion_audit.py",
    "scripts/raphael_package_install_smoke.py",
    "scripts/raphael_release_slice_boundary.py",
    "scripts/raphael_release_slice_manifest.py",
)


@dataclass(frozen=True)
class BoundaryClassification:
    profile: str
    included: tuple[str, ...]
    deferred_media: tuple[str, ...]
    unclassified: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.unclassified


@dataclass(frozen=True)
class ContentBoundaryInspection:
    profile: str
    violations: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.violations


def classify_paths(
    paths: Iterable[str],
    *,
    profile: str = "llm",
) -> BoundaryClassification:
    normalized = tuple(_normalize_path(path) for path in paths if _normalize_path(path))
    if profile != "llm":
        return BoundaryClassification(
            profile=profile,
            included=(),
            deferred_media=(),
            unclassified=tuple(sorted(set(normalized))),
        )
    included: list[str] = []
    deferred_media: list[str] = []
    unclassified: list[str] = []
    for path in sorted(set(normalized)):
        if _matches(path, LLM_INCLUDE_PREFIXES):
            included.append(path)
        elif _matches(path, LLM_DEFERRED_MEDIA_PREFIXES):
            deferred_media.append(path)
        else:
            unclassified.append(path)
    return BoundaryClassification(
        profile=profile,
        included=tuple(included),
        deferred_media=tuple(deferred_media),
        unclassified=tuple(unclassified),
    )


def inspect_content_boundaries(
    paths: Iterable[str],
    *,
    root: str | Path = ".",
    profile: str = "llm",
) -> ContentBoundaryInspection:
    if profile != "llm":
        return ContentBoundaryInspection(profile=profile, violations=())
    root_path = Path(root)
    violations: list[str] = []
    for path in sorted({_normalize_path(item) for item in paths if _normalize_path(item)}):
        if not path.endswith(".py") or not _strict_content_boundary_applies(path):
            continue
        file_path = root_path / path
        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as exc:
            violations.append(f"{path} could not be inspected: {exc.__class__.__name__}")
            continue
        for module in _imported_modules(tree):
            if _matches_import(module, DEFERRED_IMPORT_PREFIXES):
                violations.append(f"{path} imports deferred media module {module}")
    return ContentBoundaryInspection(profile=profile, violations=tuple(violations))


def git_status_paths() -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "status", "--short"],
        check=True,
        text=True,
        capture_output=True,
    )
    return tuple(_path_from_status_line(line) for line in result.stdout.splitlines())


def render_summary(result: BoundaryClassification) -> str:
    lines = [
        f"Raphael release slice boundary: {result.profile}",
        f"LLM slice paths: {len(result.included)}",
        f"Deferred media paths: {len(result.deferred_media)}",
        f"Unclassified paths: {len(result.unclassified)}",
    ]
    if result.unclassified:
        lines.append("Unclassified:")
        lines.extend(f"- {path}" for path in result.unclassified)
    return "\n".join(lines)


def render_content_summary(result: ContentBoundaryInspection) -> str:
    lines = [
        f"Raphael content boundary: {result.profile}",
        f"Violations: {len(result.violations)}",
    ]
    if result.violations:
        lines.append("Boundary violations:")
        lines.extend(f"- {violation}" for violation in result.violations)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Classify changed files against the Raphael release slice boundary."
    )
    parser.add_argument("--profile", default="llm", choices=("llm",))
    parser.add_argument(
        "--from-git-status",
        action="store_true",
        help="Read paths from git status --short in the current checkout.",
    )
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)

    paths = git_status_paths() if args.from_git_status else tuple(args.paths)
    result = classify_paths(paths, profile=args.profile)
    print(render_summary(result))
    content = inspect_content_boundaries(result.included, profile=args.profile)
    print(render_content_summary(content))
    return 0 if result.ready and content.ready else 1


def _normalize_path(path: str) -> str:
    text = str(path or "").strip()
    if not text:
        return ""
    return text[2:] if text.startswith("./") else text


def _path_from_status_line(line: str) -> str:
    raw = str(line or "").rstrip()
    if not raw.strip():
        return ""
    path = raw[3:] if len(raw) > 3 else raw.strip()
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    return _normalize_path(path)


def _matches(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path == prefix or path.startswith(prefix) for prefix in prefixes)


def _matches_import(module: str, prefixes: tuple[str, ...]) -> bool:
    return any(module == prefix or module.startswith(f"{prefix}.") for prefix in prefixes)


def _strict_content_boundary_applies(path: str) -> bool:
    return _matches(path, STRICT_CONTENT_BOUNDARY_PREFIXES)


def _imported_modules(tree: ast.AST) -> tuple[str, ...]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return tuple(modules)


if __name__ == "__main__":
    raise SystemExit(main())
