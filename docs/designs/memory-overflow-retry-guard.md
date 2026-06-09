# Memory Overflow Retry Guard

> **TL;DR** - Memory quota overflow is deterministic only while the relevant store state is unchanged. PR 1 should add typed quota overflow results and a per-turn guardrail that blocks identical same-state retries by canonical request fingerprint and opaque store-state token, not by error text. Reliable consolidation should follow with live list/read, stable entry IDs, ID-based mutation, and eventually atomic batch repair.

## Problem

Hermes memory is a bounded persistent store injected into the system prompt as a frozen snapshot at session start. Mid-session writes update disk but do not refresh the prompt snapshot, which preserves prefix-cache stability.

When `memory(action=add)` or `memory(action=replace)` exceeds the configured character limit, retrying the same write against the same store state cannot succeed. Today that failure is exposed mostly through human-readable error text, so the agent can repeat an identical call and waste tool iterations or loop.

Recent overflow guidance improvements help the model understand what to do, but guidance alone does not enforce progress. The runtime should enforce the quota math and retry boundary.

## Goals

- Stop identical same-state memory overflow retries before the tool executes again.
- Cover both `add` overflow and the real `replace` overflow path.
- Avoid brittle string matching by using structured error fields.
- Preserve legitimate recovery: shorter content, space-making mutations, and retry after the store changes.
- Preserve concurrent-session recovery by allowing a cheap state check before blocking.
- Keep automatic deletion or compaction out of the core loop.
- Ship the production firebreak as a small first PR, with reliable consolidation as follow-up work.

## Non-Goals

- Do not add a synchronous LLM self-review cleanup loop in PR 1.
- Do not silently remove, summarize, or compact user memory.
- Do not require a full memory file format migration for the first fix.
- Do not solve every memory consolidation issue in the deterministic retry PR.

## Proposed Design

Use a phased memory transaction protocol:

1. **PR 1: typed overflow and same-state retry guard.**
   The memory tool returns `error.code = "memory_quota_exceeded"` for quota failures, including `operation`, usage, attempted total, and overage. The guardrail records the normalized request fingerprint against the observed store state and blocks the exact same request while that state is unchanged.
2. **PR 2: live list/read and stable identity.**
   The memory tool exposes live entries with stable IDs, entry versions, char counts, and previews/full content. ID-based `replace` and `remove` become preferred, with `old_text` kept as a compatibility fallback.
3. **PR 3: atomic single-store batch.**
   The model can submit remove/replace/add operations in one all-or-nothing transaction guarded by an expected store version.

This design gives the runtime ownership of deterministic mechanics and leaves semantic memory decisions to the model.

## PR 1 Scope

PR 1 should be the smallest fix for the production loop:

- Add a structured quota overflow result for `add` and `replace`.
- Add an opaque `store_state_token` to overflow results.
  - In PR 1 this token is only a retry-guard equivalence token.
  - It is not a durable concurrency-control API.
  - It may be implemented as a canonical serialized-store fingerprint or HMAC.
  - A monotonic `store_version` should be introduced before batch or compare-and-swap semantics.
- Include the current store-state token in successful memory mutation results too, so the guardrail can tell when a previous quota failure is no longer deterministic.
- Add a normalized request fingerprint for memory writes.
- Record quota failures as `(store, operation, request_fingerprint, store_state_token)`.
- Return a synthetic `deterministic_retry_blocked` result before executing a repeated identical write against the same store state.
- Before blocking, optionally perform a cheap store-state check. If another session changed the store, allow the write to re-evaluate against the new state.
- Allow the same original write after a successful space-making mutation changes the store state.
- Fix `replace` quota calculation so it resolves the target first and checks the final projected store size.

The key behavior:

```text
add(new fact) -> memory_quota_exceeded at state A
add(new fact) -> deterministic_retry_blocked at state A
remove(old entry) -> success, state B
add(new fact) -> allowed at state B
```

## Structured Overflow Result

The memory tool should return a machine-readable envelope on quota failure:

```json
{
  "success": false,
  "store": "memory",
  "store_state_token": "opaque:...",
  "error": {
    "code": "memory_quota_exceeded",
    "operation": "add",
    "request_fingerprint": "sha256:..."
  },
  "usage": {
    "current_chars": 2196,
    "limit_chars": 2200,
    "remaining_chars": 4,
    "new_entry_chars": 164,
    "max_add_chars": 4,
    "attempted_total_chars": 2360,
    "over_by_chars": 160,
    "min_chars_to_free": 160,
    "quota_unit": "serialized_chars"
  }
}
```

For `replace`, the tool should include target and delta details after resolving exactly one entry:

```json
{
  "success": false,
  "store": "memory",
  "store_state_token": "opaque:...",
  "error": {
    "code": "memory_quota_exceeded",
    "operation": "replace",
    "request_fingerprint": "sha256:..."
  },
  "replacement": {
    "old_entry_chars": 120,
    "new_entry_chars": 500,
    "delta_chars": 380,
    "max_replacement_chars": 124
  },
  "usage": {
    "current_chars": 2196,
    "limit_chars": 2200,
    "attempted_total_chars": 2576,
    "over_by_chars": 376,
    "quota_unit": "serialized_chars"
  }
}
```

Human-readable `error.message` can exist, but the guardrail must key off `error.code`.

The `store_state_token` should not be documented as a durable version. It only answers: "does the store look equivalent to the state that produced this overflow?" A later monotonic `store_version` should own concurrency control for ID-based mutation and batch.

## Request Fingerprint

The guardrail should compute `request_fingerprint` before tool execution with one canonical helper. The memory tool may echo the fingerprint in error results for logging, but there must be one definition.

The fingerprint should include:

- `store`
- `action`
- normalized content hash and character count
- `old_text` hash or `entry_id`, depending on the target resolver
- quota-relevant options

The fingerprint should normalize or exclude:

- JSON key order
- omitted defaults versus explicit defaults
- trailing whitespace according to memory-tool storage rules
- Unicode form, preferably NFC
- request IDs, timestamps, tracing metadata, and unrelated unknown fields

Logs should store hashes and lengths, not raw memory content.

## Guardrail State Machine

The guardrail is per assistant turn.

It tracks quota failures by:

```text
(store, operation, request_fingerprint, store_state_token)
```

State transitions:

| Event | Result |
| --- | --- |
| First quota overflow | Record the failure and return guidance. |
| Same write under same store state | Block before executing the tool. |
| Candidate block but a cheap state check sees a newer token | Allow the write to re-evaluate. |
| Same write after store state changes | Allow. |
| Changed content or target | Allow. |
| Shorter replacement or remove | Allow, even if the store is full. |
| Successful memory mutation returns a new store-state token | Update the observed state and stop treating older failures as current. |
| Too many quota failures in one turn | Suppress further space-increasing writes for that store unless its state changes. |

Before returning a synthetic block, the runtime should use the latest observed token. To fully support concurrent background mutations, it may run a cheap `memory_stat(store)` check that returns only:

```json
{
  "success": true,
  "store": "memory",
  "store_state_token": "opaque:...",
  "usage": {
    "current_chars": 1980,
    "limit_chars": 2200,
    "remaining_chars": 220
  }
}
```

If the current token differs from the failed token, the write should be allowed.

The synthetic block result should be structured:

```json
{
  "success": false,
  "store": "memory",
  "error": {
    "code": "deterministic_retry_blocked",
    "previous_error_code": "memory_quota_exceeded",
    "reason": "The same memory write already exceeded quota under the current store state.",
    "allowed_next_actions": [
      "shorten_content",
      "remove_existing_entry",
      "replace_with_shorter_content",
      "skip_memory_write"
    ]
  }
}
```

The first synthetic block should only block that exact write. After a small budget of quota failures for the same store, for example two or three failures in one assistant turn, the guardrail should suppress further space-increasing writes for that store unless the store-state token changes. It should still allow stat/read/list, remove, and strictly shrinking replace.

Space-increasing operations are:

| Operation | Space-increasing when |
| --- | --- |
| `add` | Always. |
| `replace` | `new_entry_chars > old_entry_chars`. |
| `remove` | Never. |
| `batch` | Final projected total is greater than current total. |

## Replace Semantics

`replace` must resolve its target before quota checking:

1. Resolve `entry_id` if available, otherwise resolve `old_text`.
2. Return `target_not_found` when no entry matches.
3. Return `ambiguous_target` when `old_text` matches multiple distinct entries.
4. Compute final projected size:

```text
projected_total = current_total - old_entry_serialized_size + new_entry_serialized_size
```

A shorter replacement should be allowed even when the store is at or above quota. `remove` should never fail because of quota.

If full `old_text` ambiguity handling is cheap in PR 1, return structured `ambiguous_target` when `old_text` matches multiple entries. If that change broadens PR 1 too much, defer the complete ambiguity fix to stable IDs, but still resolve the replace target according to the current implementation before quota math.

## Follow-Up: Stable Identity

Reliable consolidation needs live identity, not substring guessing.

Add a `list` or `read` action that returns:

- `store_version`
- usage and remaining chars
- entries with stable `id`
- entry `version`
- char counts
- previews by default
- full content only when requested

Then prefer:

```json
{
  "action": "replace",
  "store": "memory",
  "entry_id": "mem_01J...",
  "expected_entry_version": "ev_7",
  "content": "Shorter replacement"
}
```

Keep `old_text` as a compatibility fallback, but return `ambiguous_target` with candidate IDs/previews instead of mutating when it matches multiple entries.

## Follow-Up: Atomic Batch

After live IDs exist, add a single-store `batch` action:

```json
{
  "action": "batch",
  "store": "memory",
  "expected_store_version": "sv_123",
  "operations": [
    {"op": "remove", "entry_id": "mem_03", "expected_entry_version": "ev_2"},
    {"op": "replace", "entry_id": "mem_04", "expected_entry_version": "ev_5", "content": "Merged shorter memory"},
    {"op": "add", "content": "New durable fact"}
  ]
}
```

Batch semantics:

- Validate all operations against one locked snapshot.
- Apply nothing if any ID/version check fails.
- Check quota only on the final projected store.
- Echo all applied changes in the result.

This makes overflow recovery efficient without silent compaction.

## Tests

PR 1 must cover:

- `add` overflow returns `memory_quota_exceeded`.
- Real `replace` overflow returns `memory_quota_exceeded`.
- Exact same overflowing `add` is blocked under the same store state.
- Exact same overflowing `replace` is blocked under the same store state.
- Same JSON arguments with different key order still block.
- Shorter changed retry is allowed.
- Same original `add` is allowed after a successful `remove`.
- Same original `add` is allowed after a successful shorter `replace`.
- Same original `add` is allowed when a cheap state check sees a concurrent store mutation.
- Smaller `replace` succeeds at full quota.
- `replace` computes final projected size, not append-before-delete size.
- Repeated blocked retries do not execute the memory tool repeatedly.
- Repeated changed overflowing writes hit the quota-failure budget.

Follow-up tests should cover:

- stale entry version conflicts
- `old_text` ambiguity
- list/read pagination or previews
- atomic batch success
- batch quota failure with no partial mutation
- concurrent mutation conflict

## Issue Comment Draft

```md
I think #41755 improves the model-facing overflow guidance, but it does not by itself enforce progress. Once a memory write is known to exceed quota under the current store state, replaying the identical write in the same turn is deterministic non-progress.

A small runtime guard could address this without adding automatic memory compaction or a synchronous cleanup loop:

1. Have the memory tool return a structured overflow result, e.g. `error.code = "memory_quota_exceeded"`, with `operation = "add" | "replace"`, quota usage, attempted total, and overage.
2. Have the guardrail compute a canonical request fingerprint from normalized memory-write arguments.
3. Record quota failures against the observed store state, e.g. `(store, operation, request_fingerprint, store_state_token)`.
4. If the same request is repeated against the same store state, return a synthetic `deterministic_retry_blocked` result before executing the tool again.
5. If the model changes arguments, shortens content, removes/replaces another entry, or the store state changes, allow the retry.

The important nuance is that the block should be scoped to store state, not the whole turn globally. This sequence must remain valid:

`add(new fact) -> quota overflow -> remove(old entry) -> add(same new fact) -> allowed`

For concurrency, a candidate block can optionally perform a cheap state-token check before blocking; if another session has changed the store, the write should be allowed to re-evaluate against the new state.

Separately, reliable consolidation should be follow-up work: `list/read`, stable entry IDs, ID-based remove/replace, and eventually an atomic single-store `batch` operation. Those can be separate from the immediate production firebreak.
```

## PR Sequence

1. Post the issue comment to confirm the refined direction.
2. Open PR 1 for typed overflow and same-store-state retry blocking.
3. Link the PR from #35121 and state that stable IDs and batch are follow-ups.
4. After maintainer feedback, open PR 2 for live list/read and stable IDs.
5. Open PR 3 for atomic batch once ID-based operations are accepted.

## Design Decisions

- PR 1 may use `store_state_token`; it should not call that token a durable `store_version`.
- If monotonic `store_version` is cheap and does not require migration, PR 1 may introduce it. Otherwise defer it to ID/batch work.
- The first synthetic block should not halt all memory writes for the store.
- Entry previews belong in list/read follow-up work, not PR 1 overflow results.
- `old_text` ambiguity can be included in PR 1 only if it stays local to existing replace target resolution.
