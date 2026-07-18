from __future__ import annotations

import math
import re
from typing import Any


EDITORIAL_PROFILE_ID = "family-review-board-v2"
NARRATIVE_EDITORIAL_PROFILE_ID = "story-video-review-board-v3"
EDITORIAL_METRICS_SCHEMA = "story_video_editorial_metrics_v1"
NARRATIVE_DYNAMICS_SCHEMA = "story_video_narrative_dynamics_v1"
LONG_SENTENCE_CHAR_LIMIT = 46
MAX_LONG_SENTENCE_RATIO = 0.25
MIN_CONCRETE_SCENE_RATIO = 0.80
MIN_CAUSAL_HANDOFF_RATIO = 0.70

NARRATIVE_MODES = frozenset(
    {
        "guided_mystery",
        "discovery_quest",
        "transformation",
        "choice_and_consequence",
        "character_lens",
        "pattern_reveal",
        "calm_wonder",
    }
)
RETENTION_ROLES = frozenset(
    {"cold_open", "expectation", "reversal", "payoff", "ending_echo"}
)

_SEGMENT_HEADING_RE = re.compile(r"^###\s+(S\d+)\b.*$", re.MULTILINE)
_SENTENCE_RE = re.compile(r'.+?(?:[。！？!?]+[」』”’"]*|$)', re.DOTALL)


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
            for sentence in _SENTENCE_RE.findall(body)
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


def _script_quote_exists(segments: dict[str, str], segment_id: str, quote: str) -> bool:
    return bool(segment_id in segments and quote and quote in segments[segment_id])


def _positive_duration_minutes(
    target_duration_sec: int | float,
    violations: list[str],
    prefix: str,
) -> float:
    try:
        duration = float(target_duration_sec or 0)
    except (TypeError, ValueError):
        duration = 0.0
    if not math.isfinite(duration) or duration <= 0:
        violations.append(f"{prefix} target_duration_sec is invalid")
        return 0.0
    return duration / 60.0


def validate_narrative_dynamics_v3(
    script_text: str,
    dynamics: dict[str, Any],
    target_duration_sec: int | float,
) -> tuple[str, ...]:
    """Validate that declared story momentum is bound to the spoken script.

    The contract intentionally checks evidence and sequence rather than trying
    to score literary quality from keywords. Model judgment still owns taste;
    this gate prevents a metadata-only PASS from bypassing that judgment.
    """
    violations: list[str] = []
    if _text(dynamics.get("schema")) != NARRATIVE_DYNAMICS_SCHEMA:
        violations.append("narrative_dynamics schema is invalid")

    segments = parse_script_segments(script_text)
    if not segments:
        return tuple(violations + ["narrative_dynamics script has no Sxx segments"])
    segment_ids = list(segments)
    segment_order = {segment_id: index for index, segment_id in enumerate(segment_ids)}

    narrative_mode = _text(dynamics.get("narrative_mode"))
    if narrative_mode not in NARRATIVE_MODES:
        violations.append(
            f"narrative_dynamics narrative_mode is invalid: {narrative_mode or '<missing>'}"
        )
    if not _text(dynamics.get("central_lens")):
        violations.append("narrative_dynamics central_lens is missing")

    beat_rows = _list(dynamics.get("retention_beats"))
    seen_beat_ids: set[str] = set()
    present_roles: set[str] = set()
    for index, row in enumerate(beat_rows):
        if not isinstance(row, dict):
            violations.append(f"narrative_dynamics beat[{index}] is not an object")
            continue
        beat_id = _text(row.get("beat_id")) or f"beat[{index}]"
        role = _text(row.get("role"))
        segment_id = _text(row.get("segment_id"))
        quote = _text(row.get("quote"))
        for field_name in ("beat_id", "role", "segment_id", "quote", "change"):
            if not _text(row.get(field_name)):
                violations.append(f"narrative_dynamics beat {beat_id} {field_name} is missing")
        if beat_id in seen_beat_ids:
            violations.append(f"narrative_dynamics duplicate beat_id: {beat_id}")
        seen_beat_ids.add(beat_id)
        if role and role not in RETENTION_ROLES:
            violations.append(f"narrative_dynamics beat {beat_id} role is invalid: {role}")
        if role in RETENTION_ROLES:
            present_roles.add(role)
        if segment_id not in segments:
            violations.append(
                f"narrative_dynamics beat {beat_id} references unknown segment: {segment_id or '<missing>'}"
            )
        elif quote and not _script_quote_exists(segments, segment_id, quote):
            violations.append(
                f"narrative_dynamics beat {beat_id} quote is not in {segment_id}"
            )
    for role in sorted(RETENTION_ROLES - present_roles):
        violations.append(f"narrative_dynamics missing retention role: {role}")

    runtime_minutes = _positive_duration_minutes(
        target_duration_sec, violations, "narrative_dynamics"
    )
    required_loops = max(1, min(2, math.ceil(runtime_minutes / 2)))
    loop_rows = _list(dynamics.get("cross_segment_loops"))
    valid_loop_ids: set[str] = set()
    for index, row in enumerate(loop_rows):
        if not isinstance(row, dict):
            violations.append(f"narrative_dynamics loop[{index}] is not an object")
            continue
        loop_id = _text(row.get("loop_id")) or f"loop[{index}]"
        opening_id = _text(row.get("opening_segment_id"))
        payoff_id = _text(row.get("payoff_segment_id"))
        opening_quote = _text(row.get("opening_quote"))
        payoff_quote = _text(row.get("payoff_quote"))
        complete = all(
            _text(row.get(field_name))
            for field_name in (
                "loop_id",
                "opening_segment_id",
                "opening_quote",
                "payoff_segment_id",
                "payoff_quote",
            )
        )
        if not complete:
            violations.append(f"narrative_dynamics loop {loop_id} is incomplete")
            continue
        if loop_id in valid_loop_ids:
            violations.append(f"narrative_dynamics duplicate loop_id: {loop_id}")
        if opening_id == payoff_id:
            violations.append(
                f"narrative_dynamics loop {loop_id} is resolved in the opening segment"
            )
        elif opening_id not in segment_order or payoff_id not in segment_order:
            violations.append(f"narrative_dynamics loop {loop_id} references unknown segment")
        elif segment_order[payoff_id] <= segment_order[opening_id]:
            violations.append(f"narrative_dynamics loop {loop_id} payoff is not later")
        else:
            valid_loop_ids.add(loop_id)
        if opening_id in segments and not _script_quote_exists(
            segments, opening_id, opening_quote
        ):
            violations.append(
                f"narrative_dynamics loop {loop_id} opening_quote is not in {opening_id}"
            )
        if payoff_id in segments and not _script_quote_exists(
            segments, payoff_id, payoff_quote
        ):
            violations.append(
                f"narrative_dynamics loop {loop_id} payoff_quote is not in {payoff_id}"
            )
    if len(valid_loop_ids) < required_loops:
        violations.append(
            f"narrative_dynamics.cross_segment_loop_count<{required_loops}"
        )

    valid_handoffs: set[tuple[str, str]] = set()
    for index, row in enumerate(_list(dynamics.get("causal_handoffs"))):
        if not isinstance(row, dict):
            violations.append(f"narrative_dynamics handoff[{index}] is not an object")
            continue
        from_id = _text(row.get("from_segment_id"))
        to_id = _text(row.get("to_segment_id"))
        from_quote = _text(row.get("from_quote"))
        to_quote = _text(row.get("to_quote"))
        if not all((from_id, to_id, from_quote, to_quote)):
            violations.append(f"narrative_dynamics handoff[{index}] is incomplete")
            continue
        adjacent = (
            from_id in segment_order
            and to_id in segment_order
            and segment_order[to_id] == segment_order[from_id] + 1
        )
        if not adjacent:
            violations.append(
                f"narrative_dynamics handoff {from_id}->{to_id} is not adjacent"
            )
            continue
        if not _script_quote_exists(segments, from_id, from_quote):
            violations.append(
                f"narrative_dynamics handoff {from_id}->{to_id} from_quote is not in {from_id}"
            )
            continue
        if not _script_quote_exists(segments, to_id, to_quote):
            violations.append(
                f"narrative_dynamics handoff {from_id}->{to_id} to_quote is not in {to_id}"
            )
            continue
        valid_handoffs.add((from_id, to_id))
    transition_count = max(1, len(segment_ids) - 1)
    handoff_ratio = len(valid_handoffs) / transition_count
    if handoff_ratio < MIN_CAUSAL_HANDOFF_RATIO:
        violations.append("narrative_dynamics.causal_handoff_ratio<0.70")

    exposition_only_ids = {
        _text(value)
        for value in _list(dynamics.get("exposition_only_segment_ids"))
        if _text(value)
    }
    for segment_id in sorted(exposition_only_ids - set(segments)):
        violations.append(
            f"narrative_dynamics exposition evidence references unknown segment: {segment_id}"
        )
    if exposition_only_ids:
        violations.append("narrative_dynamics.exposition_only_segment_count>0")
    return tuple(violations)


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
    "NARRATIVE_DYNAMICS_SCHEMA",
    "NARRATIVE_EDITORIAL_PROFILE_ID",
    "NARRATIVE_MODES",
    "compute_read_aloud_metrics",
    "parse_script_segments",
    "validate_editorial_profile_v2",
    "validate_narrative_dynamics_v3",
]
