"""Operator-facing health report for the Layer-2 memory ledger."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from memory.layer2_store import Layer2Store


@dataclass(frozen=True)
class Layer2HealthReport:
    counts_by_status: dict[str, int]
    promotion_candidates: list[dict[str, Any]]
    contradiction_candidates: list[dict[str, Any]]
    markdown: str


def _markdown(report: Layer2HealthReport) -> str:
    lines = ["## Layer-2 Health", ""]
    lines.append("### Counts")
    for status, count in sorted(report.counts_by_status.items()):
        lines.append(f"- {status}: {count}")
    lines.append("")
    lines.append("### Promotion Candidates")
    for item in report.promotion_candidates:
        target = item.get("routing_destination") or item.get("proposed_target") or "-"
        lines.append(
            f"- {item['canonical_text']} "
            f"(support={item['support_count']}, target={target})"
        )
    lines.append("")
    lines.append("### Contradiction Candidates")
    for item in report.contradiction_candidates:
        lines.append(
            f"- {item['canonical_text']} "
            f"(support={item['support_count']}, contradict={item['contradict_count']})"
        )
    return "\n".join(lines)


def build_layer2_health_report(*, store: Optional[Layer2Store] = None, max_items: int = 10) -> Layer2HealthReport:
    ledger = store or Layer2Store()
    bounded_max = max(1, int(max_items))
    with ledger._connect() as conn:  # noqa: SLF001 - health report is ledger maintenance.
        counts = {
            row["status"]: int(row["n"] or 0)
            for row in conn.execute(
                "SELECT status, COUNT(*) AS n FROM candidates GROUP BY status"
            ).fetchall()
        }
        promotion_candidates = [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM candidates
                WHERE status = 'active'
                  AND support_count - contradict_count >= 3
                ORDER BY support_count - contradict_count DESC, updated_at DESC
                LIMIT ?
                """,
                (bounded_max,),
            ).fetchall()
        ]
        contradiction_candidates = [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM candidates
                WHERE contradict_count > 0
                ORDER BY contradict_count DESC, support_count DESC
                LIMIT ?
                """,
                (bounded_max,),
            ).fetchall()
        ]

    report = Layer2HealthReport(
        counts_by_status=counts,
        promotion_candidates=promotion_candidates,
        contradiction_candidates=contradiction_candidates,
        markdown="",
    )
    return Layer2HealthReport(
        counts_by_status=report.counts_by_status,
        promotion_candidates=report.promotion_candidates,
        contradiction_candidates=report.contradiction_candidates,
        markdown=_markdown(report),
    )
