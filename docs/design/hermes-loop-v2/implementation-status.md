# Hermes Loop v2 — Implementation Status

This file is the honest review surface for the current branch state.

It separates:
- what is already landed in code,
- what is only partially covered,
- and what is still target architecture rather than implemented runtime.

## Suggested review order

1. `6beebd64` — gateway durability foundation
2. `b3972405` — persisted loop inspection commands
3. `ef7b9e93` — top-level status visibility
4. `955b1594` — richer control state + anti-stall guards
5. `7f157794` — operator mutation commands

## What is landed now

### Durable gateway loop baseline
- filesystem-backed checkpoint + event persistence via `hermes_loop.store.LoopStore`
- gateway startup hydration of active loop checkpoints
- conservative replay/resume behavior for recovered loops
- fail-closed handling for malformed/missing/diverged checkpoints
- fail-closed handling for critical persistence failures

### Operator inspection
- `hermes loop list`
- `hermes loop status <session_id> [--events N]`
- `hermes status` summary section for autonomous loops

### Operator controls
- `hermes loop pause <session_id>`
- `hermes loop resume <session_id>`
- `hermes loop stop <session_id>`
- typed stop disclosure persisted in checkpoints:
  - `stop_reason`
  - `stop_class`
  - `stop_message`
  - `resumable`

### Anti-stall / conservative recovery slice
- repeated next-prompt suppression
- duplicate-result suppression
- retry budget for invalid verifier/planner payloads
- idle timeout
- ambiguous interrupted-turn recovery -> `recovery_incomplete`
- checkpoint watcher so persisted operator writes can affect live gateway loop state
- deterministic observable-evidence gate for obviously unsupported self-report progress (`missing_observable_evidence`)

### Artifact-boundary metadata
- stable `goal_id` metadata binds same-session review loading to the active goal instead of mixing prior goal reviews
- persisted gateway checkpoints/events now carry `goal_id` + `run_id`
- background review artifacts now carry optional `goal_id` + `run_id` for correlation
- persisted `goal.json` artifact now gives `goal_id` a real immutable contract target instead of metadata-only correlation
- gateway followup/recovery and CLI decision/verifier paths now prefer the persisted goal artifact when present

## Phase coverage against `rollout-plan.md`

### Phase 0: docs and contract agreement
Landed as docs in this directory.

### Phase 1: runtime extraction
Partial only.

Implemented:
- minimal persistence helper
- incremental hardening around current bounded loop code
- minimal persisted LoopGoal artifact contract (`goal.json`) with planner/verifier/followup consultation

Not yet implemented:
- `LoopGoalRegistry`
- `LoopRuntime.tick()`
- shared runtime API used by all surfaces
- typed `LoopGoal` / `LoopRun` / `LoopTurn` runtime layer

### Phase 2: gateway durability
Substantially landed, but still incremental.

Implemented:
- checkpoint-backed persistence
- restart hydration
- conservative recovery behavior
- inspection/status plumbing

Still incomplete:
- live gateway control still uses `_loop_states` as the in-memory runtime mirror
- persistence constrains runtime, but has not fully replaced surface-local runtime state

### Phase 3: operator controls
Partially landed.

Implemented:
- CLI list/status/pause/resume/stop
- typed persisted stop disclosure
- resumable flag + basic operator-facing summaries
- persisted checkpoint/event correlation now includes `goal_id` + `run_id`

Still incomplete:
- no fully unified surface-neutral control plane
- runtime ownership of transitions is still split across CLI/gateway codepaths

### Phase 4: stronger anti-stall controls
Partially landed.

Implemented:
- retry budget for invalid verifier/planner payloads
- idle timeout
- repeated prompt / duplicate result guards
- conservative interrupted-turn recovery policy
- deterministic observable-evidence gate for obviously unsupported self-report progress

Still incomplete:
- no richer `evidence_tier` / `evidence_summary` contract yet
- broader deterministic stop taxonomy wired through a shared runtime service
- more complete retry/recovery semantics beyond narrow payload-retry handling

## Important remaining gaps

These are still real architecture gaps and should not be overclaimed as complete:

1. no revisioned `LoopGoalRegistry` / supersession workflow yet
2. no full `turn_id` / `attempt_id` artifact model
3. no canonical `LoopRuntime.tick()` implementation
4. no event schema with `event_id`, `state_before`, `state_after`
5. no full `evidence_tier` / `evidence_summary` verifier contract yet
6. no truly surface-neutral runtime ownership of transitions

## Practical interpretation

The current branch should be described as:

> a durable loop-v2 thin slice that lands persistence, recovery, inspection, CLI controls, and several conservative anti-stall safeguards

It should **not** yet be described as the full loop-v2 runtime architecture.
