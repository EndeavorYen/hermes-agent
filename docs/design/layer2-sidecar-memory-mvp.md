# Layer-2 Sidecar Memory MVP Spec and Rollout

> Status note: this remains the authoritative spec for the current cron-specific Layer-2 MVP implementation on this branch. For the broader future Hermes memory architecture, see `docs/design/hermes-memory-architecture/README.md` and the doc set under that directory.

## Status

Implemented locally as an MVP on `feat/hermes-custom-autonomy`.

Primary implementation files:
- `memory/layer2_store.py` — shared Layer-2 store and payload application logic
- `agent/layer2_memory_provider.py` — built-in MemoryManager provider for runtime Layer-2 recall/write routing
- `agent/layer2_recall.py` — query/scope-aware runtime recall packet formatting
- `tools/layer2_memory_tool.py` — chat-side candidate-only L2 write tool
- `tools/layer2_review_tool.py` — operator review/prune/promote tooling
- `cron/layer2_memory.py` — compatibility facade for older imports
- `cron/scheduler.py` — cron producer/consumer integration
- `cron/jobs.py`
- `tools/cronjob_tools.py`
- `tests/memory/test_layer2_store.py`
- `tests/cron/test_layer2_memory.py`
- `tests/tools/test_cronjob_tools.py`
- `tests/cron/test_scheduler.py`

## Problem statement

The old pattern of inferring recurrence directly from non-durable analysis is not good enough because it collapses three different things into one step:
1. raw evidence observed by a job,
2. a candidate belief that may or may not recur,
3. a durable memory write.

That makes audit hard, allows derived summaries to masquerade as recurrence, and leaves no durable candidate ledger to inspect before promotion. In practice, a cron job could repeatedly restate its own previous conclusion and appear to have found recurrence even when no new underlying evidence was observed.

The MVP fixes that by introducing an explicit sidecar ledger for candidate-memory events between job output and durable memory.

## Three-layer model

### L1: raw evidence
The underlying source material for a run: transcripts, artifacts, tool output, review notes, or other concrete inputs observed during that run.

### L2: candidate ledger
A separate SQLite-backed ledger of candidate facts and candidate events.

Current implementation:
- DB path: `~/.hermes/cron/layer2_memory.sqlite3`
- candidate row tracks `canonical_text`, `kind`, `proposed_target`, `status`, `support_count`, `contradict_count`, timestamps, and optional `promoted_ref`
- event row tracks `event_type`, provenance, recurrence-count flag, deltas, and optional durable-write metadata

L2 is the audit layer. It is where recurrence evidence accumulates before durable writes.

### L3: durable memory
The built-in memory store (`MEMORY.md` / `USER.md`) written via `MemoryStore`.

In this MVP, L3 writes are guarded and job-scoped. They only happen when a job explicitly opts in and the requested target is allowlisted.

## MVP scope

Included in the MVP:
- opt-in `memory_pipeline` metadata on cron jobs
- scheduler prompt hint for opted-in jobs
- parsing exactly one fenced ````hermes-layer2```` JSON payload from final cron output
- SQLite-backed Layer-2 candidate/event ledger
- audit section appended to saved cron output
- guarded durable promotion to `memory` and/or `user` when explicitly allowlisted
- duplicate-event suppression via `source_event_id`
- recurrence counting control via `counts_for_recurrence`
- tests for parsing, ledger behavior, scheduler integration, and guarded promotion

## Explicit non-goals

Not included in this MVP:
- automatic promotion thresholds or auto-promotion policy
- a full operator review UI over Layer-2 candidates
- any new user-facing moderation or approval workflow
- migration of historical recurrence analyses into Layer-2
- skill promotion or skill synthesis from memory candidates
- schema validation beyond the lightweight parser/application rules now in code
- any guarantee that all current learning jobs already emit valid Layer-2 payloads

## Job opt-in contract

A cron job participates only when `memory_pipeline.enabled` is true.

Example job metadata:

```json
{
  "memory_pipeline": {
    "enabled": true,
    "allow_durable_promotion_targets": ["user"]
  }
}
```

Current behavior:
- `enabled: true` allows Layer-2 payload parsing/application
- `allow_durable_promotion_targets` may be `[]`, a string, a list, or `true`
- `true` means both `memory` and `user`
- if a job is not opted in, Layer-2 payloads are ignored

## Layer-2 payload contract

Opted-in jobs may append exactly one fenced block to the final response:

```hermes-layer2
{
  "candidate_events": [
    {
      "action": "create",
      "canonical_text": "User prefers concise answers",
      "kind": "preference",
      "proposed_target": "user",
      "counts_for_recurrence": true,
      "source_ref": "optional explicit provenance",
      "source_event_id": "optional explicit event id",
      "notes": "optional"
    },
    {
      "action": "contradict",
      "canonical_text": "User prefers concise answers",
      "counts_for_recurrence": true
    }
  ],
  "promotions": [
    {
      "canonical_text": "User prefers concise answers",
      "target": "user",
      "content": "User prefers concise answers",
      "kind": "preference",
      "source_ref": "optional explicit provenance",
      "source_event_id": "optional explicit event id",
      "notes": "optional"
    }
  ]
}
```

Current parser/application rules:
- fence label must be `hermes-layer2`
- payload must parse as a single JSON object
- invalid JSON is ignored and left in the visible response
- supported candidate actions: `create`, `strengthen`, `contradict`, `prune`
- supported promotion targets: `memory`, `user`
- unsupported items are skipped
- if the visible response is empty after stripping the fenced block, nothing is applied

## Recurrence evidence rules

### Counts as recurrence evidence
- a new raw-evidence-grounded observation recorded as `create` or `strengthen`
- a contradiction grounded in new evidence recorded as `contradict`
- distinct supporting events with distinct provenance / `source_event_id`
- evidence explicitly marked `counts_for_recurrence: true` (default)

### Does not count as recurrence evidence
- derived summaries that only restate a prior conclusion
- repeated emission of the same `source_event_id`
- `prune` and `promote` events
- any item with `counts_for_recurrence: false`
- payloads from jobs that are not opted in
- payloads attached to runs with no human-visible response after the fence is removed

### Important MVP discipline
Recurrence is evidence-based, not summary-based. The scheduler prompt already states: derived summaries do not count as recurrence by themselves.

## Live rollout recommendation for current learning jobs

Recommended rollout is intentionally conservative.

| Job | Recommendation | Durable promotion? | Rationale |
|---|---|---:|---|
| `daily-autonomous-learning-short` | Enable Layer-2 candidate capture | No | Frequent, high-volume synthesis job; good for seeding L2 but too easy to overfit on lightly-processed findings. |
| `weekly-autonomous-learning-review` | Enable Layer-2 candidate capture | Yes, `user` and narrow `memory` only after review of emitted payload quality | Best place to summarize cross-run recurrence because it sees broader evidence and lower cadence. |
| `nightly-dream-shadow-review` | Enable Layer-2 candidate capture | No | Shadow review should accumulate candidates and contradictions, not write durable memory yet. |
| `nightly-dream-sandbox-shadow-validation` | Enable Layer-2 candidate capture | No | Validation/sandbox job is useful as corroboration input, but should stay candidate-only in MVP. |
| `nightly-professor-question-distillation` | Enable Layer-2 candidate capture | Yes, `user` only if outputs are consistently concrete and evidence-linked | Distillation may identify stable user interests/preferences, but should not broadly write repo/global memory in MVP. |

Recommended order:
1. candidate-only on all five jobs,
2. inspect saved Layer-2 audit output for at least several runs,
3. then allow narrow durable promotion on `weekly-autonomous-learning-review`,
4. consider `nightly-professor-question-distillation` `user`-only promotion after audit quality is stable.

## Audit UX and emoji semantics

What landed now:
- saved cron output gets a `## Layer-2 Audit` section
- audit lines are plain text labels such as `candidate_created`, `candidate_strengthened`, `candidate_contradicted`, `candidate_pruned`, `candidate_promoted`, `durable_write`, `durable_write_failed`, and `duplicate_ignored`

Recommended emoji semantics for future operator-facing surfaces:
- 🟢 strengthen / promote / durable write
- 🟡 create / candidate pending review
- ⚪ duplicate ignored / no-op
- 🟠 contradict / mixed evidence
- 🔴 durable write failed / invalid candidate / blocked action
- ✂️ prune

This emoji mapping is a UX recommendation only. It is not yet implemented in the current audit formatter.

## Safety notes

- Layer-2 is opt-in per job; non-opted-in jobs do not mutate the ledger.
- Durable writes are target-allowlisted per job.
- Promotion writes currently flow only to `MEMORY.md` / `USER.md` through `MemoryStore`.
- Promotions do not increment recurrence counts.
- Duplicate `source_event_id` values are ignored for counting.
- Invalid or malformed payload entries are skipped rather than partially coerced.
- Empty-visible-output runs do not mutate Layer-2.

## Deferred items

Deferred beyond this MVP:
- automatic promotion thresholds and recency windows
- migration of historical recurrence analyses into Layer-2
- richer provenance linking back to exact artifacts/messages
- conflict-resolution policy beyond simple contradict counts
- automatic skill creation from Layer-2 candidates; operator review may draft or inspect, but should not auto-install skills
- broader rollout to non-learning jobs

## Bottom line

This MVP introduces a real Layer-2 sidecar ledger between cron analysis and durable memory. It is intentionally small: candidate capture is the default win, durable promotion is narrow and guarded, and skill promotion remains explicitly deferred.
