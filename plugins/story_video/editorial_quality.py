from __future__ import annotations

import math
import re
from typing import Any


EDITORIAL_PROFILE_ID = "family-review-board-v2"
EDITORIAL_METRICS_SCHEMA = "story_video_editorial_metrics_v1"
LONG_SENTENCE_CHAR_LIMIT = 46
MAX_LONG_SENTENCE_RATIO = 0.25
MIN_CONCRETE_SCENE_RATIO = 0.80

_SEGMENT_HEADING_RE = re.compile(r"^###\s+(S\d+)\b.*$", re.MULTILINE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?])")


def _text(value: Any) -> str:
    return str(value or "").strip()


def parse_script_segments(script_text: str) -> dict[str, str]:
    matches = list(_SEGMENT_HEADING_RE.finditer(script_text))
    segments: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(script_text)
        segments[match.group(1)] = script_text[start:end].strip()
    return segments


def compute_read_aloud_metrics(script_text: str) -> dict[str, float | int]:
    segments = parse_script_segments(script_text)
    sentences: list[str] = []
    for body in segments.values():
        sentences.extend(
            sentence.strip()
            for sentence in _SENTENCE_SPLIT_RE.split(body)
            if sentence.strip()
        )
    long_sentences = [
        sentence
        for sentence in sentences
        if len(re.sub(r"\s+", "", sentence)) > LONG_SENTENCE_CHAR_LIMIT
    ]
    ratio = len(long_sentences) / len(sentences) if sentences else 1.0
    return {
        "sentence_count": len(sentences),
        "long_sentence_count": len(long_sentences),
        "long_sentence_ratio": round(ratio, 4),
    }


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _collect_segment_references(report: dict[str, Any]) -> set[str]:
    references: set[str] = set()
    for field_name in (
        "concrete_scene_evidence",
        "delight_beat_evidence",
        "emotional_turn_evidence",
    ):
        for row in _list(report.get(field_name)):
            if isinstance(row, dict) and _text(row.get("segment_id")):
                references.add(_text(row.get("segment_id")))
    references.update(_text(value) for value in _list(report.get("abstract_only_segment_ids")))
    for row in _list(report.get("curiosity_loop_evidence")):
        if not isinstance(row, dict):
            continue
        references.update(
            _text(row.get(field_name))
            for field_name in ("opening_segment_id", "payoff_segment_id")
            if _text(row.get(field_name))
        )
    for row in _list(report.get("rhetorical_template_evidence")):
        if isinstance(row, dict):
            references.update(_text(value) for value in _list(row.get("segment_ids")))
    return {value for value in references if value}


def _complete_rows(rows: list[Any], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if isinstance(row, dict) and all(_text(row.get(field_name)) for field_name in fields)
    ]


def validate_editorial_profile_v2(
    script_text: str,
    report: dict[str, Any],
    target_duration_sec: int | float,
) -> tuple[str, ...]:
    violations: list[str] = []
    if _text(report.get("schema")) != EDITORIAL_METRICS_SCHEMA:
        violations.append("editorial_metrics schema is invalid")

    segments = parse_script_segments(script_text)
    if not segments:
        return tuple(violations + ["editorial_metrics script has no Sxx segments"])
    segment_ids = set(segments)

    for reference in sorted(_collect_segment_references(report) - segment_ids):
        violations.append(
            f"editorial_metrics evidence references unknown segment: {reference}"
        )

    concrete_rows = _complete_rows(
        _list(report.get("concrete_scene_evidence")),
        ("segment_id", "subject", "action", "sensory_detail", "stakes_or_question"),
    )
    concrete_ids = {
        _text(row.get("segment_id"))
        for row in concrete_rows
        if _text(row.get("segment_id")) in segment_ids
    }
    concrete_ratio = len(concrete_ids) / len(segment_ids)
    if concrete_ratio < MIN_CONCRETE_SCENE_RATIO:
        violations.append("editorial_metrics.concrete_scene_ratio<0.80")

    abstract_ids = {
        _text(value)
        for value in _list(report.get("abstract_only_segment_ids"))
        if _text(value)
    }
    if abstract_ids:
        violations.append("editorial_metrics.abstract_only_segment_count>0")

    try:
        duration = float(target_duration_sec or 0)
    except (TypeError, ValueError):
        duration = 0.0
    if not math.isfinite(duration) or duration <= 0:
        violations.append("editorial_metrics target_duration_sec is invalid")
        duration = 0.0
    runtime_minutes = duration / 60.0
    required_loops = max(2, math.ceil(runtime_minutes))
    loop_rows = _complete_rows(
        _list(report.get("curiosity_loop_evidence")),
        (
            "loop_id",
            "opening_segment_id",
            "payoff_segment_id",
            "question",
            "payoff",
            "status",
        ),
    )
    unique_loop_ids = {_text(row.get("loop_id")) for row in loop_rows}
    resolved_loop_ids = {
        _text(row.get("loop_id"))
        for row in loop_rows
        if _text(row.get("status")).lower() == "resolved"
    }
    if len(unique_loop_ids) < required_loops:
        violations.append(f"editorial_metrics.curiosity_loop_count<{required_loops}")
    if len(resolved_loop_ids) < required_loops:
        violations.append(
            f"editorial_metrics.resolved_curiosity_loop_count<{required_loops}"
        )

    required_delight_beats = max(1, math.floor(runtime_minutes / 2))
    delight_rows = _complete_rows(
        _list(report.get("delight_beat_evidence")),
        ("segment_id", "beat_type", "text"),
    )
    if len(delight_rows) < required_delight_beats:
        violations.append(
            f"editorial_metrics.delight_beat_count<{required_delight_beats}"
        )

    required_turns = 3 if duration >= 120 else 1
    turn_rows = _complete_rows(
        _list(report.get("emotional_turn_evidence")),
        ("segment_id", "from_state", "to_state", "cause"),
    )
    if len(turn_rows) < required_turns:
        violations.append(f"editorial_metrics.emotional_turn_count<{required_turns}")

    for row in _list(report.get("rhetorical_template_evidence")):
        if not isinstance(row, dict):
            continue
        template = _text(row.get("template")) or "<missing>"
        used_in = {_text(value) for value in _list(row.get("segment_ids")) if _text(value)}
        if len(used_in) > 2:
            violations.append(
                f"editorial_metrics rhetorical template {template} used>2"
            )

    computed = compute_read_aloud_metrics(script_text)
    reported = report.get("reported_read_aloud_metrics")
    if not isinstance(reported, dict):
        violations.append("editorial_metrics reported_read_aloud_metrics is missing")
    else:
        if reported.get("sentence_count") != computed["sentence_count"]:
            violations.append("editorial_metrics.sentence_count report mismatch")
        reported_ratio = reported.get("long_sentence_ratio")
        if not isinstance(reported_ratio, (int, float)) or abs(
            float(reported_ratio) - float(computed["long_sentence_ratio"])
        ) > 0.001:
            violations.append("editorial_metrics.long_sentence_ratio report mismatch")
    if float(computed["long_sentence_ratio"]) > MAX_LONG_SENTENCE_RATIO:
        violations.append("editorial_metrics.long_sentence_ratio>0.25")

    return tuple(violations)


__all__ = [
    "EDITORIAL_METRICS_SCHEMA",
    "EDITORIAL_PROFILE_ID",
    "LONG_SENTENCE_CHAR_LIMIT",
    "MAX_LONG_SENTENCE_RATIO",
    "MIN_CONCRETE_SCENE_RATIO",
    "compute_read_aloud_metrics",
    "parse_script_segments",
    "validate_editorial_profile_v2",
]
