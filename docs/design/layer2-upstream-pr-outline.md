# Layer-2 Memory Upstream PR Outline

## Problem

Built-in memory is intentionally small and directly injected into the prompt.
When every provisional lesson goes directly to durable memory, users either hit
memory budget pressure or lose useful but not-yet-proven lessons.

## Proposal

Add a local Layer-2 memory provider:

- SQLite-backed candidate evidence ledger.
- Candidate writes separate from durable memory writes.
- Source-linked recurrence and contradiction counting.
- Query-scoped bounded recall injected with normal memory context.
- Explicit L1 promotion policy that respects durable memory pressure.
- Operator review and health reporting.

## Non-Goals

- No automatic durable memory flooding.
- No external service dependency.
- No skill synthesis.
- No cron-only coupling.

## Safety

- L2 is profile scoped.
- Direct cron tool writes remain blocked.
- Chat writes cannot promote.
- Promotion path is explicit and reviewable.
- Recall excludes stale, quarantined, pruned, and promoted candidates by default.

## Test Plan

- `rtk pytest tests/memory/test_layer2_schema.py -q`
- `rtk pytest tests/memory/test_layer2_selector.py -q`
- `rtk pytest tests/memory/test_layer2_promotion.py -q`
- `rtk pytest tests/memory/test_layer2_signals.py -q`
- `rtk pytest tests/memory/test_layer2_health.py -q`
- `rtk pytest tests/run_agent/test_run_agent.py::TestLayer2RecallInjection -q`
- `rtk pytest tests/tools/test_layer2_review_tool.py -q`
