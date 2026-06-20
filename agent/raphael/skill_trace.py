from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from agent.raphael.models import SkillTrace, SkillTraceSummary
from agent.raphael.redaction import redact_trace_payload
from agent.raphael.state import get_raphael_skill_traces_path, get_raphael_state_dir
from tools.skill_usage import latest_activity_at, load_usage


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    raw = str(value)
    try:
        parsed = datetime.fromisoformat(
            raw.removesuffix("Z") + "+00:00" if raw.endswith("Z") else raw
        )
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _int_record_value(record: dict[str, Any], key: str) -> int:
    try:
        return int(record.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _empty_summary(skill_name: str) -> SkillTraceSummary:
    return SkillTraceSummary(
        skill_name=skill_name,
        use_count=0,
        view_count=0,
        patch_count=0,
        latest_activity_at=None,
        state=None,
        created_by=None,
        outcome_counts={},
    )


def append_skill_trace(
    trace: SkillTrace,
    *,
    max_string_length: int | None = None,
) -> None:
    payload = trace.to_dict()
    redacted = dict(payload)
    redact_kwargs = {} if max_string_length is None else {"max_string_length": max_string_length}
    for key in ("metadata", "user_corrections", "risk_incidents"):
        redacted[key] = redact_trace_payload(payload.get(key), **redact_kwargs)
    state_dir = get_raphael_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    with get_raphael_skill_traces_path().open(
        "a",
        encoding="utf-8",
    ) as trace_file:
        trace_file.write(json.dumps(redacted, sort_keys=True) + "\n")


def read_skill_traces(limit: int | None = None) -> list[SkillTrace]:
    path = get_raphael_skill_traces_path()
    if not path.exists():
        return []

    traces: list[SkillTrace] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            traces.append(SkillTrace.from_dict(json.loads(line)))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue

    if limit is None:
        return traces
    bounded_limit = max(0, int(limit))
    if bounded_limit == 0:
        return []
    return traces[-bounded_limit:]


def _summary_from_usage_record(
    skill_name: str,
    record: dict[str, Any],
) -> SkillTraceSummary:
    return SkillTraceSummary(
        skill_name=skill_name,
        use_count=_int_record_value(record, "use_count"),
        view_count=_int_record_value(record, "view_count"),
        patch_count=_int_record_value(record, "patch_count"),
        latest_activity_at=_parse_iso_datetime(latest_activity_at(record)),
        state=record.get("state"),
        created_by=record.get("created_by"),
        outcome_counts={},
    )


def _with_outcome(summary: SkillTraceSummary, outcome: str) -> SkillTraceSummary:
    outcome_counts = dict(summary.outcome_counts)
    outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
    return SkillTraceSummary(
        skill_name=summary.skill_name,
        use_count=summary.use_count,
        view_count=summary.view_count,
        patch_count=summary.patch_count,
        latest_activity_at=summary.latest_activity_at,
        state=summary.state,
        created_by=summary.created_by,
        outcome_counts=outcome_counts,
    )


def summarize_skill_usage(
    *,
    max_rows: int = 20,
    max_trace_events: int = 500,
) -> list[SkillTraceSummary]:
    usage = load_usage()
    summaries = {
        skill_name: _summary_from_usage_record(skill_name, record)
        for skill_name, record in usage.items()
    }

    for trace in read_skill_traces(limit=max_trace_events):
        for skill_name in trace.skills_used:
            if not skill_name:
                continue
            summary = summaries.get(skill_name) or _empty_summary(skill_name)
            summaries[skill_name] = _with_outcome(summary, trace.outcome)

    def sort_key(summary: SkillTraceSummary) -> tuple[int, int, str]:
        latest = (
            summary.latest_activity_at.timestamp()
            if summary.latest_activity_at
            else 0
        )
        activity_count = summary.use_count + summary.view_count + summary.patch_count
        return (-activity_count, -int(latest), summary.skill_name.lower())

    bounded_rows = max(0, int(max_rows))
    return sorted(summaries.values(), key=sort_key)[:bounded_rows]


def _format_outcomes(outcome_counts: dict[str, int] | Any) -> str:
    if not outcome_counts:
        return "none"
    return ", ".join(
        f"{outcome}={count}"
        for outcome, count in sorted(dict(outcome_counts).items())
    )


def render_skill_summary(summaries: Sequence[SkillTraceSummary]) -> str:
    lines = [
        "Raphael Skill Trace",
        "Mode: read-only skill usage summary",
        "",
        "Skill Usage:",
    ]

    if not summaries:
        lines.append("No skill usage or trace events recorded.")
    else:
        for summary in summaries:
            latest = (
                summary.latest_activity_at.isoformat()
                if summary.latest_activity_at is not None
                else "never"
            )
            state = summary.state or "unknown"
            created_by = summary.created_by or "unknown"
            lines.append(
                f"- {summary.skill_name}: "
                f"use={summary.use_count} "
                f"view={summary.view_count} "
                f"patch={summary.patch_count} "
                f"latest={latest} "
                f"state={state} "
                f"created_by={created_by} "
                f"outcomes={_format_outcomes(summary.outcome_counts)}"
            )

    lines.extend(
        [
            "",
            "Safety: Raphael Skill Trace is read-only and does not propose or modify skills.",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "append_skill_trace",
    "read_skill_traces",
    "render_skill_summary",
    "summarize_skill_usage",
]
