# ADR-001: Loop Goal Contract

- Status: Proposed
- Owner: Hermes loop v2
- Related: `runtime-architecture.md`

## Context

Hermes currently supports bounded continuation decisions, but long-running continuation needs a stable objective that survives restarts, retries, and surface changes.

Without an explicit contract, the runtime can drift between:
- user intent from old transcript messages
- transient planner prompts
- gateway-local state

## Decision

Hermes loop v2 will use an explicit immutable `LoopGoal` contract.

Key rules:
1. Each active autonomous run binds to exactly one `goal_id`.
2. `goal_text` and baseline success criteria are immutable within a run.
3. Material user direction changes create a new goal revision.
4. A new goal revision may supersede an existing active run.
5. Session transcript remains primary conversational history; `LoopGoal` is the runtime contract layered on top.

## Fields to stabilize

Required fields:
- `goal_id`
- `session_id`
- `goal_text`
- `success_criteria`
- `constraints`
- `revision`
- `created_at`
- `created_by`

## Consequences

Benefits:
- stable continuation target
- cleaner pause/resume semantics
- easier stop explanations
- less ambiguity during recovery

Costs:
- a new persisted artifact type
- revision logic for user redirection

## Open questions

1. Does a goal revision automatically stop the old run?
2. Should success criteria be user-visible/editable in early v2?
3. How much default constraint data should be implicit vs stored?
