from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Callable


POSE_GEOMETRY_PROMPT = """Analyze only pose and shot geometry. Ignore identity, appearance, hair,
wardrobe, colors, visual style, attractiveness, and background. Return JSON only in this schema:
{"torso":{"lean_direction":"none|left|right|forward|back","lean_degrees":0,
"facing":"front|three_quarter_left|three_quarter_right|profile_left|profile_right|back"},
"head":{"tilt_direction":"none|left|right|forward|back","tilt_degrees":0,
"chin":"up|level|down"},"camera":{"view":"front|near_frontal_three_quarter|three_quarter_left|
three_quarter_right|profile_left|profile_right|back","elevation":"low|eye_level|high",
"distance":"close|medium|wide"},"framing":{"shot":"face_closeup|tight_upper_body|upper_body|
three_quarter|full_body"},"limbs":[{"limb":"subject_left_arm|subject_right_arm|subject_left_leg|
subject_right_leg","direction":"up|down|left|right|diagonal_up_left|diagonal_up_right|
diagonal_down_left|diagonal_down_right|forward|back","bend":"straight|slight|bent|right_angle|
folded","visibility":"full|partial|out_of_frame","foreground":false}],"crop":{"top":"none|
clips_head|clips_arm","bottom":"none|clips_torso|clips_waist|clips_leg","left":"none|
clips_head|clips_arm|clips_shoulder|clips_torso|clips_leg","right":"none|clips_head|clips_arm|
clips_shoulder|clips_torso|clips_leg"}}. Use only listed enum values and numbers."""

POSE_GEOMETRY_SCHEMA = "pose_geometry_v3"
POSE_INSTRUCTION_MAX_CHARS = 680
POSE_MAX_LIMBS = 6

_ENUMS = {
    "lean_direction": {"none", "left", "right", "forward", "back"},
    "facing": {"front", "three_quarter_left", "three_quarter_right", "profile_left", "profile_right", "back"},
    "tilt_direction": {"none", "left", "right", "forward", "back"},
    "chin": {"up", "level", "down"},
    "view": {"front", "near_frontal_three_quarter", "three_quarter_left", "three_quarter_right", "profile_left", "profile_right", "back"},
    "elevation": {"low", "eye_level", "high"},
    "distance": {"close", "medium", "wide"},
    "shot": {"face_closeup", "tight_upper_body", "upper_body", "three_quarter", "full_body"},
    "limb": {"subject_left_arm", "subject_right_arm", "subject_left_leg", "subject_right_leg"},
    "direction": {"up", "down", "left", "right", "diagonal_up_left", "diagonal_up_right", "diagonal_down_left", "diagonal_down_right", "forward", "back"},
    "bend": {"straight", "slight", "bent", "right_angle", "folded"},
    "visibility": {"full", "partial", "out_of_frame"},
}
_CROP_ENUMS = {
    "top": {"none", "clips_head", "clips_arm"},
    "bottom": {"none", "clips_torso", "clips_waist", "clips_leg"},
    "left": {"none", "clips_head", "clips_arm", "clips_shoulder", "clips_torso", "clips_leg"},
    "right": {"none", "clips_head", "clips_arm", "clips_shoulder", "clips_torso", "clips_leg"},
}


def extract_pose_transfer_instruction(
    reference: str,
    *,
    analyzer: Callable[[str, str], Any] | None = None,
    cache_dir: str | Path | None = None,
) -> dict[str, Any]:
    path = Path(reference).expanduser()
    if not path.is_file():
        return _failure("pose_reference_unavailable")
    reference_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    provenance = _analyzer_provenance(injected=analyzer is not None)
    prompt_hash = hashlib.sha256(POSE_GEOMETRY_PROMPT.encode("utf-8")).hexdigest()
    cache_identity = hashlib.sha256(
        json.dumps(
            {
                "schema": POSE_GEOMETRY_SCHEMA,
                "reference_hash": reference_hash,
                "prompt_hash": prompt_hash,
                "analyzer": provenance,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    cache_root = Path(cache_dir) if cache_dir is not None else _default_cache_dir()
    cache_path = cache_root / f"{POSE_GEOMETRY_SCHEMA}_{cache_identity[:20]}.json"
    cache_allowed = provenance.get("provider") != "auto" or provenance.get("route") == "injected"
    cached = (
        _read_cached(
            cache_path,
            reference_hash=reference_hash,
            prompt_hash=prompt_hash,
            provenance=provenance,
        )
        if cache_allowed
        else None
    )
    if cached:
        cached["cache_hit"] = True
        return cached

    analyze = analyzer or _default_analyzer
    try:
        raw = analyze(str(path.resolve()), POSE_GEOMETRY_PROMPT)
    except Exception as exc:  # noqa: BLE001 - provider errors are evidence, not crashes
        return _failure("pose_geometry_analyzer_failed", detail=str(exc))
    geometry = _parse_geometry(raw)
    instruction = _geometry_instruction(geometry)
    if not instruction:
        return _failure("pose_geometry_unavailable")
    result = {
        "success": True,
        "instruction": instruction,
        "source": "vision_pose_geometry",
        "cache_hit": False,
        "reference_hash": reference_hash,
        "schema": POSE_GEOMETRY_SCHEMA,
        "prompt_hash": prompt_hash,
        "analyzer": provenance,
        "cache_policy": "content_addressed" if cache_allowed else "disabled_for_dynamic_route",
    }
    if cache_allowed:
        cache_root.mkdir(parents=True, exist_ok=True)
        temporary = cache_path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
        temporary.replace(cache_path)
    return result


def _default_cache_dir() -> Path:
    home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
    return home / "visual" / "reference_role_guides"


def _default_analyzer(path: str, prompt: str) -> Any:
    from model_tools import _run_async
    from tools.vision_tools import vision_analyze_tool

    return _run_async(vision_analyze_tool(path, prompt))


def _read_cached(
    path: Path,
    *,
    reference_hash: str,
    prompt_hash: str,
    provenance: dict[str, str],
) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("success") is not True:
        return None
    if (
        value.get("schema") != POSE_GEOMETRY_SCHEMA
        or value.get("reference_hash") != reference_hash
        or value.get("prompt_hash") != prompt_hash
        or value.get("analyzer") != provenance
        or not str(value.get("instruction") or "").strip()
    ):
        return None
    return value


def _parse_geometry(raw: Any) -> dict[str, Any]:
    value = raw
    for _depth in range(5):
        if isinstance(value, dict):
            if value.get("success") is False:
                return {}
            if "analysis" in value:
                value = value.get("analysis")
                continue
            return value
        if isinstance(value, str):
            text = value.strip()
            fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
            if fenced:
                text = fenced.group(1)
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                return {}
            continue
        return {}
    return {}


def _geometry_instruction(geometry: dict[str, Any]) -> str:
    torso = geometry.get("torso") if isinstance(geometry.get("torso"), dict) else {}
    head = geometry.get("head") if isinstance(geometry.get("head"), dict) else {}
    camera = geometry.get("camera") if isinstance(geometry.get("camera"), dict) else {}
    framing = geometry.get("framing") if isinstance(geometry.get("framing"), dict) else {}
    crop = geometry.get("crop") if isinstance(geometry.get("crop"), dict) else {}
    parts: list[str] = []

    shot = _enum(framing.get("shot"), "shot")
    if shot:
        parts.append(f"framing {shot.replace('_', ' ')}")
    view = _enum(camera.get("view"), "view")
    elevation = _enum(camera.get("elevation"), "elevation")
    distance = _enum(camera.get("distance"), "distance")
    if any((view, elevation, distance)):
        parts.append("camera " + ", ".join(value.replace("_", " ") for value in (view, elevation, distance) if value))
    lean = _enum(torso.get("lean_direction"), "lean_direction")
    facing = _enum(torso.get("facing"), "facing")
    lean_degrees = _degrees(torso.get("lean_degrees"))
    if any((lean, facing)):
        parts.append(f"torso lean {lean or 'none'} {lean_degrees} degrees, facing {(facing or 'front').replace('_', ' ')}")
    tilt = _enum(head.get("tilt_direction"), "tilt_direction")
    chin = _enum(head.get("chin"), "chin")
    tilt_degrees = _degrees(head.get("tilt_degrees"))
    if any((tilt, chin)):
        parts.append(f"head tilt {tilt or 'none'} {tilt_degrees} degrees, chin {chin or 'level'}")

    limbs = geometry.get("limbs")
    if isinstance(limbs, list):
        seen_limbs: set[str] = set()
        for item in limbs[:POSE_MAX_LIMBS]:
            if not isinstance(item, dict):
                continue
            limb = _enum(item.get("limb"), "limb")
            if not limb or limb in seen_limbs:
                continue
            seen_limbs.add(limb)
            direction = _enum(item.get("direction"), "direction")
            bend = _enum(item.get("bend"), "bend")
            visibility = _enum(item.get("visibility"), "visibility")
            details = [value.replace("_", " ") for value in (direction, bend, visibility) if value]
            if item.get("foreground") is True:
                details.append("foreground")
            if details:
                parts.append(f"{limb.replace('_', ' ')} " + ", ".join(details))
    crop_values = [
        f"{edge} {value.replace('_', ' ')}"
        for edge in ("top", "bottom", "left", "right")
        if (value := _crop_enum(crop.get(edge), edge)) and value != "none"
    ]
    if crop_values:
        parts.append("crop " + ", ".join(crop_values))
    instruction = "; ".join(parts)
    if not shot or not view or not any(part.startswith("subject ") for part in parts):
        return ""
    return instruction[:POSE_INSTRUCTION_MAX_CHARS].rstrip(" ,;.")


def _enum(value: Any, key: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in _ENUMS[key] else ""


def _crop_enum(value: Any, edge: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in _CROP_ENUMS[edge] else ""


def _degrees(value: Any) -> int:
    try:
        return max(0, min(90, round(float(value))))
    except (TypeError, ValueError):
        return 0


def _analyzer_provenance(*, injected: bool) -> dict[str, str]:
    if injected:
        return {"route": "injected", "provider": "injected", "model": "injected"}
    provider = "auto"
    model = "auto"
    try:
        from hermes_cli.config import load_config

        config = load_config()
        auxiliary = config.get("auxiliary") if isinstance(config, dict) else None
        vision = auxiliary.get("vision") if isinstance(auxiliary, dict) else None
        configured_provider = str(vision.get("provider") or "auto") if isinstance(vision, dict) else "auto"
        configured_model = str(vision.get("model") or "") if isinstance(vision, dict) else ""
        provider = configured_provider
        model = configured_model or "auto"
    except Exception:
        pass
    return {"route": "auxiliary.vision", "provider": provider, "model": model}


def _failure(error_type: str, *, detail: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {"success": False, "error_type": error_type}
    if detail:
        result["error"] = detail[:500]
    return result
