# Hermes Loop v2 Design Docs

This directory is the implementation-oriented design set for Hermes long-running autonomous continuation.

It is intentionally **thin and upstream-friendly**:
- extend the existing `hermes_cli.loop` + `gateway.run` slice
- keep session history as the primary source of truth
- add only the minimum durable state and artifacts needed for safe continuation
- avoid introducing a new workflow framework or heavyweight orchestration layer

## Current grounded baseline

Today Hermes already has a durable thin slice for bounded continuation:
- `hermes_cli/loop.py`
  - `decide_continuation_for_session()`
  - `verify_progress_for_session()`
  - `record_background_review()` to `background_reviews.jsonl`
  - `format_loop_stop_notice()`
  - bounded CLI loop runner
  - observable-evidence gating for obviously unsupported progress claims
  - persisted `goal.json` consultation during decision / verifier followup
- `gateway/run.py`
  - `_loop_states` in-memory gateway state
  - `_maybe_schedule_loop_followup()`
  - `_apply_loop_stop_notice()`
  - gateway auto-followup and semantic progress verification
  - checkpoint hydration / conservative replay of active loops
  - checkpoint watcher so persisted operator writes affect live loop state
  - observable-evidence gating for unsupported self-report progress
  - persisted `goal.json` consultation during recovery / followup
- `hermes_loop/store.py`
  - checkpoint + event persistence via `LoopStore`
  - `goal.json` artifact read/write helpers for immutable goal correlation
- `agent/skill_commands.py`
  - continuation skill routing / fallback path
- tests
  - `tests/hermes_cli/test_loop.py`
  - `tests/gateway/test_loop_recovery.py`
  - `tests/gateway/test_unknown_command.py`
  - `tests/hermes_loop/test_store.py`

Loop v2 should evolve this slice into a durable long-running runtime without replacing Hermes with a separate agent framework.

## Current implementation status

See `implementation-status.md` for the current landed scope, review order, and honest remaining gaps versus the target v2 architecture.

## Recommended doc set

These docs are the proposed long-term structure for implementation work.

### 1. `runtime-architecture.md`
The primary spec. Covers:
- goals / non-goals
- core principles
- runtime components
- state machine
- sequencing
- durable state and artifact contracts
- stop / failure handling
- implementation roadmap

### 2. `adr-001-loop-goal-contract.md`
Decision record for the immutable loop goal contract:
- why a goal must be explicit and stable
- what fields are mutable vs immutable
- how user edits create revisions
- compatibility with existing sessions

### 3. `adr-002-loop-artifact-model.md`
Decision record for append-only artifacts:
- event log vs checkpoint snapshot split
- what belongs in session history vs loop artifacts
- file layout under Hermes home
- retention and replay expectations

### 4. `adr-003-loop-state-machine.md`
Decision record for the runtime state machine:
- canonical states and allowed transitions
- pause / resume / interrupt semantics
- stop reason taxonomy ownership
- surface-neutral behavior across CLI and gateway

### 5. `interfaces-and-schemas.md`
Concrete data contracts for implementation:
- `LoopGoal`
- `LoopRun`
- `LoopTurn`
- `LoopDecision`
- `LoopVerification`
- `LoopStopRecord`
- artifact JSONL row schemas
- versioning rules

### 6. `guardrails-and-non-goals.md`
Skeptical constraints that keep loop v2 honest:
- fake-progress failure mode
- evidence hierarchy
- bounded next-step quality bar
- fail-closed verifier behavior
- explicit non-goals for initial rollout

### 7. `runtime-tick-and-control-plane.md`
Focused extraction spec for the next missing substrate seam:
- canonical `LoopRuntime.tick()` contract
- surface-neutral transition ownership
- control-plane API for pause/resume/stop/start/status
- durable write ordering and scheduler boundary

### 8. `rollout-plan.md`
Execution plan for implementation:
- phase-by-phase milestones
- migration from current bounded loop
- test strategy
- operator visibility / debugging additions

## Design constraints

Loop v2 should preserve these constraints:
1. **No giant framework**: plain Python modules + small data contracts.
2. **No split-brain history**: conversation/session history remains primary; loop artifacts supplement it.
3. **Durable enough, not overbuilt**: append-only JSONL + small checkpoint files is preferred over a new database.
4. **Interruptible by design**: every turn should be resumable or safely stoppable.
5. **Verifier-mediated continuation**: raw model self-confidence is not enough.
6. **Surface-neutral runtime**: same loop semantics for CLI, gateway, and future entry points.
7. **Bounded resource defaults**: explicit limits for turns, retries, idle time, and repeated prompts.

## Proposed repository placement

Recommended permanent path:
- `docs/design/hermes-loop-v2/`

This keeps the design easy to review in PRs and lets implementation land incrementally beside the code it evolves.

## Reading order

1. `runtime-architecture.md`
2. `guardrails-and-non-goals.md`
3. `runtime-tick-and-control-plane.md`
4. ADRs 001-003
5. `interfaces-and-schemas.md`
6. `rollout-plan.md`

For now, the concrete architecture is captured in `runtime-architecture.md`.
