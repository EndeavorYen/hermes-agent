from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MUSIC_LIBRARY_SCHEMA_V2 = "story_video_music_library_v2"
MUSIC_CUE_PLAN_SCHEMA = "story_video_music_cue_plan_v1"
MIN_CUE_VARIANTS = 3
_ENERGY_LEVELS = frozenset({"gentle", "balanced", "high"})


def _text(value: Any) -> str:
    return str(value or "").strip()


def _tags(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {
        "_".join(_text(item).lower().replace("-", " ").split())
        for item in value
        if _text(item)
    }


def _duration(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if parsed > 0 else 0.0


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_music_direction(direction: dict[str, Any]) -> tuple[str, ...]:
    violations: list[str] = []
    if _text(direction.get("schema")) != "story_video_music_direction_v1":
        violations.append("music_direction schema is invalid")
    for field_name in ("moods", "instruments", "excluded_styles"):
        if not _tags(direction.get(field_name)):
            violations.append(f"music_direction {field_name} is empty")
    energy_curve = direction.get("energy_curve")
    if not isinstance(energy_curve, dict):
        energy_curve = {}
    for phase in ("opening", "body", "payoff", "ending"):
        if _text(energy_curve.get(phase)).lower() not in _ENERGY_LEVELS:
            violations.append(f"music_direction energy_curve.{phase} is invalid")
    if direction.get("narration_priority") is not True:
        violations.append("music_direction narration_priority must be true")
    try:
        min_variants = int(direction.get("min_cue_variants"))
    except (TypeError, ValueError):
        min_variants = 0
    if min_variants < MIN_CUE_VARIANTS:
        violations.append("music_direction min_cue_variants<3")
    return tuple(violations)


def _eligible_tracks(ledger: dict[str, Any], library: dict[str, Any]) -> list[dict[str, Any]]:
    production_type = _text(ledger.get("production_type")).lower()
    engagement = ledger.get("engagement_profile")
    engagement = engagement if isinstance(engagement, dict) else {}
    audience_mode = _text(engagement.get("mode") or "young_explorer").lower()
    direction = ledger.get("music_direction")
    direction = direction if isinstance(direction, dict) else {}
    desired_instruments = _tags(direction.get("instruments"))
    excluded_styles = _tags(direction.get("excluded_styles"))
    eligible: list[dict[str, Any]] = []
    for track in library.get("tracks") or []:
        if not isinstance(track, dict) or track.get("enabled") is not True:
            continue
        rights = track.get("rights")
        if (
            not isinstance(rights, dict)
            or _text(rights.get("status")).lower() != "approved"
            or not _text(rights.get("license"))
            or not _text(rights.get("provenance"))
        ):
            continue
        production_types = _tags(track.get("production_types"))
        audience_modes = _tags(track.get("audience_modes"))
        if production_types and not ({production_type, "*"} & production_types):
            continue
        if audience_modes and not ({audience_mode, "*", "general"} & audience_modes):
            continue
        track_exclusions = _tags(track.get("excluded_styles"))
        if excluded_styles and not excluded_styles.issubset(track_exclusions):
            continue
        track_instruments = _tags(track.get("instruments"))
        if desired_instruments and not desired_instruments.intersection(track_instruments):
            continue
        sections = [
            section
            for section in track.get("sections") or []
            if isinstance(section, dict)
            and _text(section.get("cue_id"))
            and _duration(section.get("end_sec")) > _duration(section.get("start_sec"))
        ]
        if len({str(section["cue_id"]) for section in sections}) < MIN_CUE_VARIANTS:
            continue
        eligible.append({**track, "sections": sections})
    return eligible


def _timeline_segments(
    ledger: dict[str, Any], timeline: list[dict[str, Any]], variant_count: int
) -> list[dict[str, Any]]:
    normalized = [
        {
            "scene_id": _text(row.get("scene_id")) or f"timeline_{index:02d}",
            "duration_sec": _duration(row.get("duration_sec")),
            "narrative_role": _text(row.get("narrative_role")).lower(),
        }
        for index, row in enumerate(timeline)
        if isinstance(row, dict) and _duration(row.get("duration_sec")) > 0
    ]
    scenes = {
        _text(scene.get("scene_id")): scene
        for scene in ledger.get("scenes") or []
        if isinstance(scene, dict) and _text(scene.get("scene_id"))
    }
    for row in normalized:
        if not row["narrative_role"]:
            row["narrative_role"] = _text(
                (scenes.get(row["scene_id"]) or {}).get("narrative_role")
            ).lower()
    target_duration = _duration(ledger.get("target_duration_sec"))
    if not normalized and target_duration > 0:
        normalized = [
            {"scene_id": "timeline", "duration_sec": target_duration, "narrative_role": ""}
        ]
    if len(normalized) >= MIN_CUE_VARIANTS or not normalized:
        return normalized

    total = sum(row["duration_sec"] for row in normalized)
    split_count = min(MIN_CUE_VARIANTS, variant_count)
    roles = ("hook", "reveal", "close")
    return [
        {
            "scene_id": f"music_phase_{index + 1:02d}",
            "duration_sec": total / split_count,
            "narrative_role": roles[min(index, len(roles) - 1)],
        }
        for index in range(split_count)
    ]


def _section_score(
    section: dict[str, Any],
    *,
    role: str,
    index: int,
    last_index: int,
    desired_tags: set[str],
) -> tuple[int, str]:
    tags = _tags(section.get("tags"))
    score = len(tags & desired_tags) * 2
    if role and role in tags:
        score += 8
    if index == 0 and tags & {"hook", "curious", "discovery", "opening"}:
        score += 6
    if index == last_index and tags & {"close", "resolution", "warm", "calm"}:
        score += 8
    if role in {"turn", "conflict"} and tags & {"tense", "mystery"}:
        score += 5
    if role in {"payoff", "reveal"} and tags & {"awe", "wonder", "reveal"}:
        score += 5
    return score, _text(section.get("cue_id"))


def plan_music_cues(
    ledger: dict[str, Any],
    library: dict[str, Any],
    timeline: list[dict[str, Any]],
) -> dict[str, Any]:
    if _text(library.get("schema")) != MUSIC_LIBRARY_SCHEMA_V2:
        return {"schema": MUSIC_CUE_PLAN_SCHEMA, "status": "INVALID_LIBRARY", "cues": []}
    eligible = _eligible_tracks(ledger, library)
    if not eligible:
        return {
            "schema": MUSIC_CUE_PLAN_SCHEMA,
            "status": "INSUFFICIENT_VARIANTS",
            "cues": [],
        }
    engagement = ledger.get("engagement_profile")
    engagement = engagement if isinstance(engagement, dict) else {}
    direction = ledger.get("music_direction")
    direction = direction if isinstance(direction, dict) else {}
    desired_tags = {
        _text(engagement.get("mode")).lower(),
        _text(engagement.get("energy")).lower(),
        *_tags(direction.get("moods")),
    }
    desired_tags.discard("")
    track = max(
        eligible,
        key=lambda item: (
            len(_tags(item.get("moods")) & desired_tags),
            _text(item.get("track_id")),
        ),
    )
    sections = list(track["sections"])
    segments = _timeline_segments(ledger, timeline, len(sections))
    used: set[str] = set()
    cues: list[dict[str, Any]] = []
    for index, segment in enumerate(segments):
        ranked = sorted(
            sections,
            key=lambda section: _section_score(
                section,
                role=segment["narrative_role"],
                index=index,
                last_index=len(segments) - 1,
                desired_tags=desired_tags,
            ),
            reverse=True,
        )
        unused = [section for section in ranked if _text(section.get("cue_id")) not in used]
        section = unused[0] if len(used) < MIN_CUE_VARIANTS and unused else ranked[0]
        cue_id = _text(section.get("cue_id"))
        used.add(cue_id)
        cues.append(
            {
                "timeline_id": segment["scene_id"],
                "narrative_role": segment["narrative_role"],
                "cue_id": cue_id,
                "source_path": _text(track.get("path")),
                "source_start_sec": _duration(section.get("start_sec")),
                "source_end_sec": _duration(section.get("end_sec")),
                "duration_sec": round(segment["duration_sec"], 4),
                "tags": sorted(_tags(section.get("tags"))),
            }
        )
    if len({cue["cue_id"] for cue in cues}) < MIN_CUE_VARIANTS:
        return {
            "schema": MUSIC_CUE_PLAN_SCHEMA,
            "status": "INSUFFICIENT_VARIANTS",
            "cues": [],
        }
    rights = track["rights"]
    return {
        "schema": MUSIC_CUE_PLAN_SCHEMA,
        "status": "SELECTED",
        "track_id": _text(track.get("track_id")),
        "rights_status": "approved",
        "license": _text(rights.get("license")),
        "provenance": _text(rights.get("provenance")),
        "production_type": _text(ledger.get("production_type")),
        "audience_mode": _text(engagement.get("mode")),
        "moods": sorted(_tags(direction.get("moods"))),
        "instruments": sorted(_tags(track.get("instruments"))),
        "excluded_styles": sorted(_tags(direction.get("excluded_styles"))),
        "volume_db": float(track.get("volume_db", -22.0)),
        "fade_in_sec": float(track.get("fade_in_sec", 2.0)),
        "fade_out_sec": float(track.get("fade_out_sec", 4.0)),
        "ducking": track.get("ducking") or {},
        "total_duration_sec": round(sum(cue["duration_sec"] for cue in cues), 4),
        "cues": cues,
    }


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True, text=True)


def compile_music_bed(project_dir: str | Path, plan: dict[str, Any]) -> dict[str, Any]:
    if _text(plan.get("status")) != "SELECTED":
        raise ValueError("music cue plan must be SELECTED before compilation")
    project = Path(project_dir)
    plan_sha256 = hashlib.sha256(
        json.dumps(
            plan,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    manifest_path = project / "manifests" / "music_cue_plan.json"
    try:
        cached_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cached_payload = {}
    cached = (
        cached_payload.get("compiled_bed")
        if isinstance(cached_payload, dict)
        else None
    )
    if isinstance(cached, dict) and cached.get("plan_sha256") == plan_sha256:
        cached_path = project / _text(cached.get("path"))
        expected_sha = _text(cached.get("sha256"))
        if (
            cached_path.is_file()
            and expected_sha
            and _file_sha256(cached_path) == expected_sha
        ):
            return {**cached, "cache_hit": True}

    cue_dir = project / "audio" / "music" / "cues"
    cue_dir.mkdir(parents=True, exist_ok=True)
    cue_paths: list[Path] = []
    for index, cue in enumerate(plan.get("cues") or []):
        source = Path(_text(cue.get("source_path"))).expanduser().resolve()
        if not source.is_file():
            raise ValueError(f"music source is missing: {source}")
        start = _duration(cue.get("source_start_sec"))
        end = _duration(cue.get("source_end_sec"))
        duration = _duration(cue.get("duration_sec"))
        if end <= start or duration <= 0:
            raise ValueError(f"music cue {_text(cue.get('cue_id'))} timing is invalid")
        section_samples = max(1, round((end - start) * 48000))
        fade = min(0.25, duration / 4)
        fade_out_start = max(0.0, duration - fade)
        output = cue_dir / f"{index:03d}_{_text(cue.get('cue_id'))}.wav"
        audio_filter = (
            f"atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS,"
            f"aresample=48000,aloop=loop=-1:size={section_samples},"
            f"atrim=duration={duration:.6f},"
            f"afade=t=in:st=0:d={fade:.6f},"
            f"afade=t=out:st={fade_out_start:.6f}:d={fade:.6f}"
        )
        _run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(source),
                "-af",
                audio_filter,
                "-ar",
                "48000",
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                str(output),
            ]
        )
        cue_paths.append(output)

    concat_path = cue_dir / "concat.txt"
    concat_path.write_text(
        "".join(f"file '{path.as_posix()}'\n" for path in cue_paths),
        encoding="utf-8",
    )
    output_path = project / "audio" / "music" / "story_music_bed.wav"
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
    )
    result = {
        "schema": "story_video_music_bed_v1",
        "status": "PASS",
        "track_id": _text(plan.get("track_id")),
        "path": str(output_path.relative_to(project)),
        "sha256": _file_sha256(output_path),
        "cue_count": len(cue_paths),
        "cue_ids": [_text(cue.get("cue_id")) for cue in plan.get("cues") or []],
        "total_duration_sec": _duration(plan.get("total_duration_sec")),
        "rights_status": _text(plan.get("rights_status")),
        "license": _text(plan.get("license")),
        "provenance": _text(plan.get("provenance")),
        "plan_sha256": plan_sha256,
        "cache_hit": False,
        "compiled_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({**plan, "compiled_bed": result}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return result


__all__ = [
    "MIN_CUE_VARIANTS",
    "MUSIC_CUE_PLAN_SCHEMA",
    "MUSIC_LIBRARY_SCHEMA_V2",
    "compile_music_bed",
    "plan_music_cues",
    "validate_music_direction",
]
