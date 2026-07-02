from __future__ import annotations

from pathlib import Path
from typing import Any


HASH_SIZE = 16
OVERCOPY_SIMILARITY_THRESHOLD = 0.985


def augment_observation_with_reference_similarity(
    candidate: dict[str, Any],
    observation: dict[str, Any],
) -> dict[str, Any]:
    """Add a conservative reference-overcopy defect for near-identical local images."""

    candidate_hash = _average_hash(_local_path(candidate.get("artifact_path")))
    if candidate_hash is None:
        return observation

    best: dict[str, Any] | None = None
    for reference in _reference_artifacts(candidate):
        reference_hash = _average_hash(_local_path(reference.get("uri")))
        if reference_hash is None:
            continue
        similarity = _hash_similarity(candidate_hash, reference_hash)
        if best is None or similarity > best["similarity"]:
            best = {
                "similarity": similarity,
                "reference_index": reference.get("index"),
                "role_hint": reference.get("role_hint"),
            }

    if best is None or best["similarity"] < OVERCOPY_SIMILARITY_THRESHOLD:
        return observation

    augmented = dict(observation)
    defects = list(augmented.get("artifact_defects") or [])
    if "reference_overcopy" not in defects:
        defects.append("reference_overcopy")
    augmented["artifact_defects"] = defects
    augmented["reference_similarity"] = {
        "max_similarity": round(float(best["similarity"]), 4),
        "reference_index": best.get("reference_index"),
        "role_hint": best.get("role_hint"),
        "threshold": OVERCOPY_SIMILARITY_THRESHOLD,
    }
    evidence = dict(augmented.get("evidence") or {})
    source = str(evidence.get("source") or "artifact_observation").strip()
    if "reference_similarity" not in source:
        source = f"{source}+reference_similarity"
    evidence["source"] = source
    evidence["summary"] = "artifact metadata plus local reference similarity check"
    augmented["evidence"] = evidence
    augmented["confidence"] = max(_coerce_float(augmented.get("confidence")), 0.8)
    return augmented


def _reference_artifacts(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    values = candidate.get("input_artifacts")
    if not isinstance(values, list):
        return []
    return [item for item in values if isinstance(item, dict) and item.get("uri")]


def _average_hash(path: Path | None) -> tuple[bool, ...] | None:
    if path is None:
        return None
    try:
        from PIL import Image

        with Image.open(path) as image:
            pixels = list(
                image.convert("L")
                .resize((HASH_SIZE, HASH_SIZE), Image.Resampling.LANCZOS)
                .tobytes()
            )
    except Exception:
        return None
    if not pixels:
        return None
    average = sum(pixels) / len(pixels)
    bits = tuple(pixel > average for pixel in pixels)
    on_count = sum(1 for bit in bits if bit)
    if on_count == 0 or on_count == len(bits):
        return None
    return bits


def _hash_similarity(left: tuple[bool, ...], right: tuple[bool, ...]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    matches = sum(1 for left_bit, right_bit in zip(left, right) if left_bit == right_bit)
    return matches / len(left)


def _local_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    if value.startswith(("http://", "https://", "data:")):
        return None
    path = Path(value).expanduser()
    return path if path.is_file() else None


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
