from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_ROOTS = (
    REPO_ROOT / "agent",
    REPO_ROOT / "hermes_cli",
    REPO_ROOT / "plugins",
    REPO_ROOT / "tools",
)


def _python_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _production_importers(prefix: str) -> list[str]:
    importers: list[str] = []
    for root in PRODUCTION_ROOTS:
        for path in root.rglob("*.py"):
            if any(module == prefix or module.startswith(f"{prefix}.") for module in _python_imports(path)):
                importers.append(str(path.relative_to(REPO_ROOT)))
    return sorted(importers)


def test_embedded_raphael_is_not_shipped_or_imported_by_hermes() -> None:
    assert list((REPO_ROOT / "agent" / "raphael").glob("*.py")) == []
    assert list((REPO_ROOT / "plugins" / "raphael").glob("*.py")) == []
    assert _production_importers("agent.raphael") == []


def test_visual_production_kernel_is_owned_by_standalone_engine() -> None:
    assert list(
        (REPO_ROOT / "agent" / "visual" / "production_kernel").glob("*.py")
    ) == []
    assert _production_importers("agent.visual.production_kernel") == []


def test_toonflow_plugin_uses_only_control_contract() -> None:
    root = REPO_ROOT / "plugins" / "toonflow_control"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in root.rglob("*.py")
    )
    assert "/control/v1" in source
    assert "/media/v1" not in source
    assert "chatgpt.com/backend-api" not in source
    assert "api.x.ai" not in source


def test_hermes_does_not_import_toonflow_or_media_bridge() -> None:
    assert _production_importers("toonflow") == []
    assert _production_importers("subscription_media_bridge") == []
