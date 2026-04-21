# ADR-002: Loop Artifact Model

- Status: Proposed
- Owner: Hermes loop v2
- Related: `runtime-architecture.md`

## Context

Current loop behavior already emits useful JSONL records such as `background_reviews.jsonl`, but long-running continuation needs a clearer artifact model for:
- replay
- restart recovery
- operator inspection
- stop diagnosis

We want durability without introducing a new database or framework.

## Decision

Hermes loop v2 will use a split artifact model:

1. **Append-only event log** per run for auditability and replay
2. **Compact checkpoint** per run for fast recovery
3. **Optional turn detail records** for richer debugging and summaries

Recommended layout:

```text
<HERMES_HOME>/state/loops/
  goals/
  runs/<run_id>/
    checkpoint.json
    events.jsonl
    turns/<turn_id>.json
```

## Rationale

Why not only events?
- recovery would require replaying full logs every time

Why not only snapshots?
- auditability and transition history would be weak

Why filesystem JSON/JSONL?
- easy to inspect
- easy to migrate incrementally
- no DB dependency for initial v2

## Rules

1. Event log is append-only.
2. Checkpoint is the latest materialized state.
3. Session transcript remains the source of truth for conversation history.
4. Runtime artifacts supplement, not replace, session data.
5. Existing global logs may be dual-written during migration.

## Consequences

Benefits:
- straightforward recovery path
- operator-debuggable runtime
- minimal implementation complexity

Costs:
- more files on disk
- retention/cleanup policy needed later

## Open questions

1. How long should completed run artifacts be retained?
2. Should global `background_reviews.jsonl` remain after migration?
3. Do turn detail records need full tool traces or just summaries?
