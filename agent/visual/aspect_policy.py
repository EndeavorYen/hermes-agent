"""Aspect-ratio selection and no-stretch crop planning."""

from __future__ import annotations

from typing import Any, Iterable, Optional


def parse_aspect_ratio(value: str) -> Optional[float]:
    raw = str(value or "").strip()
    if ":" not in raw:
        return None
    left, right = raw.split(":", 1)
    try:
        width = float(left)
        height = float(right)
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return None
    return width / height


def nearest_aspect_ratio(
    width: int,
    height: int,
    supported: Iterable[str],
) -> Optional[str]:
    if width <= 0 or height <= 0:
        return None
    ratios = {
        str(label): parsed
        for label in supported
        if (parsed := parse_aspect_ratio(str(label))) is not None
    }
    if not ratios:
        return None
    actual = width / height
    return min(ratios, key=lambda label: abs(actual - ratios[label]))


def plan_center_crop(
    *,
    width: int,
    height: int,
    target_aspect_ratio: str,
    tolerance: float = 0.02,
) -> dict[str, Any]:
    target = parse_aspect_ratio(target_aspect_ratio)
    if width <= 0 or height <= 0 or target is None:
        return {"action": "copy", "reason": "missing_dimensions_or_target"}

    actual = width / height
    if abs(actual - target) / target <= tolerance:
        return {
            "action": "copy",
            "reason": "aspect_ratio_within_tolerance",
            "width": width,
            "height": height,
            "target_aspect_ratio": target_aspect_ratio,
        }

    if actual > target:
        crop_height = _even_floor(height)
        crop_width = _even_floor(crop_height * target)
    else:
        crop_width = _even_floor(width)
        crop_height = _even_floor(crop_width / target)

    crop_width = min(crop_width, _even_floor(width))
    crop_height = min(crop_height, _even_floor(height))
    x = _even_offset((width - crop_width) / 2)
    y = _even_offset((height - crop_height) / 2)

    return {
        "action": "crop",
        "width": crop_width,
        "height": crop_height,
        "x": x,
        "y": y,
        "source_width": width,
        "source_height": height,
        "target_aspect_ratio": target_aspect_ratio,
        "filter": f"crop={crop_width}:{crop_height}:{x}:{y}",
    }


def _even_floor(value: float) -> int:
    return max(2, int(value) // 2 * 2)


def _even_offset(value: float) -> int:
    return max(0, int(value) // 2 * 2)
