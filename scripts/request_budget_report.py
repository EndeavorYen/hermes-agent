#!/usr/bin/env python3
"""Render a human-readable report from Hermes request budget logs.

The report is intentionally log-only: it reads existing agent/gateway logs and
does not touch the runtime hot path. It is useful after enabling
``request_budget.v1`` and ``request_budget.gateway_delivery.v1`` logs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Iterable


TURN_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}).*?"
    r"request_budget\.v1 (?P<payload>\{.*\})"
)
DELIVERY_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}).*?"
    r"request_budget\.gateway_delivery\.v1 (?P<payload>\{.*\})"
)


class BudgetTurn:
    def __init__(self, timestamp: str, payload: dict[str, Any]) -> None:
        self.timestamp = timestamp
        self.payload = payload

    @property
    def session_id(self) -> str:
        return str(self.payload.get("session_id") or "")

    @property
    def turn_id(self) -> str:
        return str(self.payload.get("turn_id") or "")

    @property
    def platform(self) -> str:
        return str(self.payload.get("platform") or "")

    @property
    def model(self) -> str:
        return str(self.payload.get("model") or "")

    @property
    def provider(self) -> str:
        return str(self.payload.get("provider") or "")

    @property
    def total_ms(self) -> int:
        return _int_value(self.payload.get("total_ms"))

    @property
    def total_s(self) -> float:
        return round(self.total_ms / 1000, 1)

    @property
    def model_ms(self) -> int:
        return _int_value(self.payload.get("model_request_ms"))

    @property
    def model_s(self) -> float:
        return round(self.model_ms / 1000, 1)

    @property
    def tool_ms(self) -> int:
        return _int_value(self.payload.get("tool_execution_ms"))

    @property
    def tool_s(self) -> float:
        return round(self.tool_ms / 1000, 1)

    @property
    def ttfb_ms(self) -> int:
        return _int_value(self.payload.get("model_ttfb_ms"))

    @property
    def ttfb_s(self) -> float:
        return round(self.ttfb_ms / 1000, 1)

    @property
    def api_calls(self) -> int:
        return _int_value(self.payload.get("api_calls"))

    @property
    def tool_call_count(self) -> int:
        return _int_value(self.payload.get("tool_call_count"))

    @property
    def tool_schema_tokens(self) -> int:
        return _int_value(self.payload.get("tool_schema_tokens"))

    @property
    def skill_index_tokens(self) -> int:
        return _int_value(self.payload.get("skill_index_tokens"))

    @property
    def tool_names_split(self) -> list[str]:
        names: list[str] = []
        for raw in self.payload.get("tool_names") or []:
            for name in str(raw).split(","):
                name = name.strip()
                if name:
                    names.append(name)
        return names

    @property
    def bottleneck(self) -> str:
        if self.tool_ms >= 1000 and self.tool_ms >= self.model_ms:
            return "tool"
        if self.model_ms >= 1000 and self.model_ms >= self.tool_ms:
            return "model"
        if self.total_ms >= 1000:
            return "overhead"
        return "none"


class DeliveryBudget:
    def __init__(self, timestamp: str, payload: dict[str, Any]) -> None:
        self.timestamp = timestamp
        self.payload = payload

    @property
    def platform(self) -> str:
        return str(self.payload.get("platform") or "")

    @property
    def gateway_delivery_ms(self) -> int:
        return _int_value(self.payload.get("gateway_delivery_ms"))

    @property
    def delivery_succeeded(self) -> bool:
        return bool(self.payload.get("delivery_succeeded"))

    @property
    def response_chars(self) -> int:
        return _int_value(self.payload.get("response_chars"))


class ParsedBudgets:
    def __init__(self, turns: list[BudgetTurn], deliveries: list[DeliveryBudget]) -> None:
        self.turns = turns
        self.deliveries = deliveries


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _json_payload(match: re.Match[str]) -> dict[str, Any] | None:
    try:
        payload = json.loads(match.group("payload"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _entry_key(kind: str, timestamp: str, payload: dict[str, Any]) -> tuple[str, str, str]:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return kind, timestamp, encoded


def parse_logs(paths: Iterable[Path], *, since: str | None = None) -> ParsedBudgets:
    turns: list[BudgetTurn] = []
    deliveries: list[DeliveryBudget] = []
    seen_entries: set[tuple[str, str, str]] = set()
    since_prefix = (since or "").strip()

    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            turn_match = TURN_RE.search(line)
            if turn_match:
                timestamp = turn_match.group("ts")
                if since_prefix and timestamp < since_prefix:
                    continue
                payload = _json_payload(turn_match)
                if payload is not None:
                    key = _entry_key("turn", timestamp, payload)
                    if key in seen_entries:
                        continue
                    seen_entries.add(key)
                    turns.append(BudgetTurn(timestamp, payload))
                continue

            delivery_match = DELIVERY_RE.search(line)
            if delivery_match:
                timestamp = delivery_match.group("ts")
                if since_prefix and timestamp < since_prefix:
                    continue
                payload = _json_payload(delivery_match)
                if payload is not None:
                    key = _entry_key("delivery", timestamp, payload)
                    if key in seen_entries:
                        continue
                    seen_entries.add(key)
                    deliveries.append(DeliveryBudget(timestamp, payload))

    return ParsedBudgets(turns=turns, deliveries=deliveries)


def _fmt_seconds(value: float) -> str:
    return f"{value:.1f}s"


def _fmt_ms(value: int) -> str:
    return f"{value}ms"


def _fmt_int(value: float | int) -> str:
    return f"{int(float(value) + 0.5):,}"


def _median(values: Iterable[int]) -> float:
    vals = [v for v in values if v is not None]
    if not vals:
        return 0
    return float(median(vals))


def _percentile(values: Iterable[int], pct: float) -> int:
    vals = sorted(values)
    if not vals:
        return 0
    idx = round((len(vals) - 1) * pct)
    return vals[int(idx)]


def _time_only(timestamp: str) -> str:
    # "2026-05-28 02:16:08,288" -> "02:16:08"
    try:
        return timestamp.split(" ", 1)[1].split(",", 1)[0]
    except IndexError:
        return timestamp


def _tool_summary(turn: BudgetTurn, *, limit: int = 3) -> str:
    counts = Counter(turn.tool_names_split)
    if not counts:
        return "-"
    parts: list[str] = []
    for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]:
        parts.append(f"{name} x{count}" if count > 1 else name)
    remaining = len(counts) - limit
    if remaining > 0:
        parts.append(f"+{remaining} more")
    return ", ".join(parts)


def _group_summary(turns: list[BudgetTurn], key_name: str) -> str:
    groups: dict[str, list[BudgetTurn]] = defaultdict(list)
    for turn in turns:
        groups[str(getattr(turn, key_name) or "unknown")].append(turn)
    if not groups:
        return "_No turns._\n"

    lines = [
        "| Group | Turns | Total p50 | Total p90 | Model p50 | Tool p50 | Tool schema p50 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, items in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
        total_values = [turn.total_ms for turn in items]
        model_values = [turn.model_ms for turn in items]
        tool_values = [turn.tool_ms for turn in items]
        schema_values = [turn.tool_schema_tokens for turn in items]
        lines.append(
            "| {name} | {count} | {total_p50} | {total_p90} | {model_p50} | {tool_p50} | {schema_p50} |".format(
                name=name,
                count=len(items),
                total_p50=_fmt_seconds(_median(total_values) / 1000),
                total_p90=_fmt_seconds(_percentile(total_values, 0.9) / 1000),
                model_p50=_fmt_seconds(_median(model_values) / 1000),
                tool_p50=_fmt_seconds(_median(tool_values) / 1000),
                schema_p50=_fmt_int(_median(schema_values)),
            )
        )
    return "\n".join(lines) + "\n"


def render_markdown(parsed: ParsedBudgets, *, limit: int = 10) -> str:
    turns = sorted(parsed.turns, key=lambda turn: turn.total_ms, reverse=True)
    deliveries = parsed.deliveries

    lines: list[str] = ["# Request Budget Report", ""]
    lines.append(
        f"Turns parsed: {len(parsed.turns)} | Gateway deliveries parsed: {len(deliveries)}"
    )
    lines.append("")

    if not turns:
        lines.append("_No `request_budget.v1` entries found._")
        return "\n".join(lines) + "\n"

    total_values = [turn.total_ms for turn in turns]
    model_values = [turn.model_ms for turn in turns]
    tool_values = [turn.tool_ms for turn in turns]
    ttfb_values = [turn.ttfb_ms for turn in turns]
    schema_values = [turn.tool_schema_tokens for turn in turns]
    skill_values = [turn.skill_index_tokens for turn in turns]
    delivery_values = [d.gateway_delivery_ms for d in deliveries]

    lines.extend(
        [
            "## Summary",
            "",
            f"- total p50: {_fmt_seconds(_median(total_values) / 1000)}; p90: {_fmt_seconds(_percentile(total_values, 0.9) / 1000)}; max: {_fmt_seconds(max(total_values) / 1000)}",
            f"- model p50: {_fmt_seconds(_median(model_values) / 1000)}; p90: {_fmt_seconds(_percentile(model_values, 0.9) / 1000)}; max: {_fmt_seconds(max(model_values) / 1000)}",
            f"- tool p50: {_fmt_seconds(_median(tool_values) / 1000)}; p90: {_fmt_seconds(_percentile(tool_values, 0.9) / 1000)}; max: {_fmt_seconds(max(tool_values) / 1000)}",
            f"- TTFB p50: {_fmt_seconds(_median(ttfb_values) / 1000)}; p90: {_fmt_seconds(_percentile(ttfb_values, 0.9) / 1000)}; max: {_fmt_seconds(max(ttfb_values) / 1000)}",
            f"- tool schema p50: {_fmt_int(_median(schema_values))} tokens; skill index p50: {_fmt_int(_median(skill_values))} tokens",
        ]
    )
    if delivery_values:
        lines.append(
            f"- gateway delivery p50: {_fmt_ms(int(_median(delivery_values)))}; gateway delivery max: {_fmt_ms(max(delivery_values))}"
        )
    lines.append("")

    lines.extend(
        [
            "## Slowest Turns",
            "",
            "| Time | Platform | Model | Total | Model | Tool | TTFB | Calls | Bottleneck | Tools |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for turn in turns[:limit]:
        lines.append(
            "| {time} | {platform} | {model} | {total} | {model_s} | {tool_s} | {ttfb} | {calls} | {bottleneck} | {tools} |".format(
                time=_time_only(turn.timestamp),
                platform=turn.platform or "-",
                model=turn.model or "-",
                total=_fmt_seconds(turn.total_s),
                model_s=_fmt_seconds(turn.model_s),
                tool_s=_fmt_seconds(turn.tool_s),
                ttfb=_fmt_seconds(turn.ttfb_s),
                calls=f"{turn.api_calls}/{turn.tool_call_count}",
                bottleneck=turn.bottleneck,
                tools=_tool_summary(turn),
            )
        )
    lines.append("")

    lines.extend(["## By Platform", "", _group_summary(turns, "platform"), ""])
    lines.extend(["## By Model", "", _group_summary(turns, "model"), ""])

    if deliveries:
        lines.extend(
            [
                "## Gateway Delivery",
                "",
                "| Time | Platform | Delivery | Chars | Success |",
                "| --- | --- | ---: | ---: | --- |",
            ]
        )
        for delivery in sorted(
            deliveries, key=lambda item: item.gateway_delivery_ms, reverse=True
        )[:limit]:
            lines.append(
                "| {time} | {platform} | {delivery} | {chars} | {success} |".format(
                    time=_time_only(delivery.timestamp),
                    platform=delivery.platform or "-",
                    delivery=_fmt_ms(delivery.gateway_delivery_ms),
                    chars=delivery.response_chars,
                    success="yes" if delivery.delivery_succeeded else "no",
                )
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _default_logs() -> list[Path]:
    log_dir = Path.home() / ".hermes" / "logs"
    return [p for p in (log_dir / "agent.log", log_dir / "gateway.log") if p.exists()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render a readable report from Hermes request_budget logs."
    )
    parser.add_argument(
        "--log",
        action="append",
        type=Path,
        dest="logs",
        help="Log file to read. May be passed more than once. Defaults to ~/.hermes/logs/agent.log and gateway.log.",
    )
    parser.add_argument("--since", help="Only include log lines at or after this timestamp/date prefix.")
    parser.add_argument("--limit", type=int, default=10, help="Rows to show in top tables.")
    parser.add_argument("--output", type=Path, help="Write Markdown report to this file.")
    args = parser.parse_args(argv)

    logs = args.logs or _default_logs()
    if not logs:
        print("No log files found. Pass --log PATH.", file=sys.stderr)
        return 1

    parsed = parse_logs(logs, since=args.since)
    report = render_markdown(parsed, limit=max(1, args.limit))
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
