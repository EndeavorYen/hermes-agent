from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


STYLE_BIBLE_FIELDS = (
    "style_id",
    "anchor_shot_id",
    "medium",
    "palette",
    "lighting",
    "lens_language",
    "texture",
    "atmosphere",
    "subject_treatment",
)


@dataclass(frozen=True)
class StyleBibleReport:
    ok: bool
    violations: tuple[str, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _version(ledger: dict[str, Any]) -> int:
    try:
        return int(ledger.get("quality_contract_version") or 0)
    except (TypeError, ValueError):
        return 0


def style_contract_enabled(ledger: dict[str, Any]) -> bool:
    return _version(ledger) >= 4 or "style_bible" in ledger


def _shot_ids(ledger: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for scene in ledger.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        for shot in scene.get("shots") or []:
            if not isinstance(shot, dict):
                continue
            shot_id = _text(shot.get("shot_id"))
            if shot_id:
                ids.add(shot_id)
    return ids


def validate_style_bible(ledger: dict[str, Any]) -> StyleBibleReport:
    if not style_contract_enabled(ledger):
        return StyleBibleReport(True)

    bible = ledger.get("style_bible")
    if not isinstance(bible, dict):
        return StyleBibleReport(False, ("style_bible",), {})

    violations: list[str] = []
    for field_name in STYLE_BIBLE_FIELDS:
        if not _text(bible.get(field_name)):
            violations.append(f"style_bible.{field_name}")
    forbidden = bible.get("forbidden_drift")
    if not isinstance(forbidden, list) or not any(_text(item) for item in forbidden):
        violations.append("style_bible.forbidden_drift")

    anchor_shot_id = _text(bible.get("anchor_shot_id"))
    if anchor_shot_id and anchor_shot_id not in _shot_ids(ledger):
        violations.append(f"style_bible.anchor_shot_id:unknown:{anchor_shot_id}")

    return StyleBibleReport(
        not violations,
        tuple(violations),
        {
            "style_id": _text(bible.get("style_id")),
            "anchor_shot_id": anchor_shot_id,
            "forbidden_drift_count": len(forbidden) if isinstance(forbidden, list) else 0,
        },
    )


def compile_style_directive(ledger: dict[str, Any]) -> str:
    bible = ledger.get("style_bible")
    if not isinstance(bible, dict):
        return ""
    forbidden = "; ".join(
        _text(item) for item in bible.get("forbidden_drift") or [] if _text(item)
    )
    return " ".join(
        part
        for part in (
            f"Style bible lock: {_text(bible.get('style_id'))}.",
            f"Medium: {_text(bible.get('medium'))}.",
            f"Palette: {_text(bible.get('palette'))}.",
            f"Lighting: {_text(bible.get('lighting'))}.",
            f"Lens language: {_text(bible.get('lens_language'))}.",
            f"Texture: {_text(bible.get('texture'))}.",
            f"Atmosphere: {_text(bible.get('atmosphere'))}.",
            f"Subject treatment: {_text(bible.get('subject_treatment'))}.",
            f"Forbidden style drift: {forbidden}." if forbidden else "",
            "Do not reinterpret the medium, palette, lighting, lens language, texture, or subject treatment from shot to shot.",
        )
        if part
    )


__all__ = [
    "STYLE_BIBLE_FIELDS",
    "StyleBibleReport",
    "compile_style_directive",
    "style_contract_enabled",
    "validate_style_bible",
]
