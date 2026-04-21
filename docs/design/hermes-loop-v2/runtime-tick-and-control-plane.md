# Loop v2 Runtime Tick and Control Plane

Primary references:
- `runtime-architecture.md`
- `interfaces-and-schemas.md`
- `rollout-plan.md`
- `implementation-status.md`

## Purpose

This document specifies the **next missing thin slice** between the current durable loop-v2 implementation and the target architecture:

> a shared runtime-owned `tick()` contract and surface-neutral control plane.

Today the branch already has durable persistence, restart hydration, inspection, operator controls, and several conservative anti-stall safeguards. But the runtime is still split across surface-local control paths:
- gateway live execution still mirrors state in `_loop_states`
- CLI and gateway still own parts of transition behavior separately
- there is no canonical `LoopRuntime.tick()` that both surfaces call

This spec exists to close that gap without turning Hermes into a heavyweight workflow engine.

## Why this spec exists now

`implementation-status.md` already calls out the main remaining gaps:
1. no revisioned `LoopGoalRegistry` / supersession workflow yet
2. no full `turn_id` / `attempt_id` artifact model
3. no canonical `LoopRuntime.tick()` implementation
4. no event schema with `event_id`, `state_before`, `state_after`
5. no full `evidence_tier` / `evidence_summary` verifier contract yet
6. no truly surface-neutral runtime ownership of transitions

The highest-leverage next spec is **not** a richer artifact schema and **not** a broader verifier framework.
The biggest unresolved seam is:

> who owns transitions, in what order, under what durable contract?

This document answers that question.

## Scope

### In scope
- shared runtime API for loop execution/control
- canonical `tick()` semantics
- surface-neutral ownership of pause/resume/stop/start/status
- transition ordering and durable write obligations
- allocation points for `turn_id` / `attempt_id`
- scheduler boundary and recovery hooks
- minimum implementation acceptance criteria

### Out of scope
- a full `LoopGoalRegistry` design
- rich goal supersession workflows beyond the minimum runtime hook
- analytics/reporting/dashboard surfaces
- retention/compaction policy
- broader verifier scoring or rubric frameworks
- workflow-engine features such as DAGs, multi-run orchestration, or generalized planners

## Non-goals

This spec must **not** be used to justify:
- replacing Hermes session history as primary truth
- introducing a separate database for loop v2
- moving logic into prompt-only skills
- adding a new daemon/controller framework before the shared runtime seam exists
- bundling multiple architecture upgrades into one implementation slice

## Current grounded baseline

Landed now:
- persisted checkpoint + event store in `hermes_loop.store.LoopStore`
- persisted `goal.json` artifact for stable goal correlation
- gateway restart hydration and conservative replay behavior
- CLI `list/status/pause/resume/stop`
- observable-evidence gate and conservative anti-stall controls

Still missing:
- a shared runtime package that owns transitions
- one durable transition cycle contract
- surface-neutral control mutation path
- canonical event/checkpoint write ordering

## Design principle

The key architectural rule is:

> **runtime owns transitions; surfaces trigger and render.**

That means:
- CLI may request a transition, but it does not decide the durable state machine itself
- gateway may schedule followup work, but it does not privately own the continuation lifecycle
- schedulers may wake a run, but they do not mutate run state directly
- planner/verifier helpers may advise a next action, but they do not own persistence

## Proposed package shape

Minimal new internal module surface:

- `hermes_loop/runtime.py`
  - `LoopRuntime`
  - shared transition engine
- `hermes_loop/models.py` or equivalent small typed module
  - thin runtime dataclasses / typed dicts only if needed
- existing `hermes_loop/store.py`
  - remains the durable store helper

Do **not** split into a large framework package.

## Runtime responsibilities

`LoopRuntime` owns:
- loading the canonical persisted run state
- validating whether a requested transition is legal
- allocating identifiers for a new turn/attempt when needed
- calling planner / executor / verifier helpers in the correct order
- writing required event rows and updated checkpoints
- returning a compact result for the caller to render or schedule from

Surfaces own:
- translating user/operator requests into runtime calls
- formatting output for CLI or gateway
- holding short-lived local caches only when safe
- enqueueing future wakeups using runtime-returned hints

Schedulers own:
- invoking `tick()` or `resume()` at the appropriate time
- never mutating checkpoints directly except through runtime APIs

Planner/verifier wrappers own:
- producing normalized decision/verifier payloads
- never directly mutating persisted loop state

## Shared public API

The runtime should expose a small explicit API.

### `start(goal_input, surface_context) -> StartResult`

Purpose:
- create a new run bound to a persisted goal artifact
- initialize the first checkpoint/event pair

Inputs:
- goal text / goal input
- success criteria / constraints if available
- session id
- optional surface routing context
- actor metadata

Must:
- persist or bind `goal.json`
- allocate `run_id`
- create initial checkpoint in `created` or `planning`
- append `run_created` and `goal_bound` events

### `tick(run_id, trigger) -> TickResult`

Purpose:
- execute **exactly one durable transition cycle**

Allowed triggers:
- `operator`
- `scheduler`
- `gateway_followup`
- `recovery`
- `resume`

Must:
- reload canonical persisted state first
- validate trigger against current run state
- perform at most one bounded transition cycle
- persist required events/checkpoint updates
- return the new state, stop information, and next scheduling hint

### `pause(run_id, actor, reason) -> ControlResult`

Purpose:
- move a pausable active run into `paused`

Must:
- validate current state is pausable
- append `paused` event
- persist checkpoint with `state=paused`, `resumable=true`

### `resume(run_id, actor, reason=None) -> ControlResult`

Purpose:
- reactivate a paused/waiting/recovery-blocked run when safe

Must:
- distinguish safe resume from ambiguous interrupted-turn recovery
- persist `resumed` event
- return whether the caller should immediately invoke `tick()`

### `stop(run_id, actor, reason, message=None) -> ControlResult`

Purpose:
- force a terminal stop through the runtime-owned path

Must:
- assign terminal fields explicitly, not with merge-default behavior
- append `stop_requested` and `stopped` (or a single terminal control event if simplified)
- persist `LoopStopRecord`-equivalent metadata on checkpoint

### `status(run_id) -> StatusResult`

Purpose:
- return a surface-neutral summary from persisted state

Must not:
- depend on gateway-local `_loop_states`

## Canonical run states

This spec assumes the state set already proposed in the ADRs, but constrains the minimum implementation to the states needed for extraction:
- `created`
- `planning`
- `executing`
- `verifying`
- `waiting`
- `paused`
- `stopped`
- `failed`
- `recovery_incomplete`

The implementation may continue to use a subset internally at first, but `tick()` must map real behavior onto these canonical labels rather than surface-specific approximations.

## Tick contract

### Core rule

One `tick()` call performs **one bounded durable cycle**.

That means a tick may:
- plan the next turn
- execute the turn
- verify the result
- decide the next steady state

But it must do so as **one explicit runtime-owned cycle** with durable state boundaries, not as scattered surface-local steps.

### Preconditions

`tick()` may run only when the current persisted state is one of:
- `created`
- `planning`
- `waiting`
- `executing` only for tightly-scoped recovery handling
- `verifying` only for tightly-scoped recovery handling
- `recovery_incomplete` only when an explicit recovery trigger allows retry

`tick()` must reject direct execution from:
- `paused`
- `stopped`
- `failed`

### Tick outputs

Minimum `TickResult` fields:
- `run_id`
- `goal_id`
- `starting_state`
- `ending_state`
- `tick_outcome` (`progress|waiting|paused|stopped|failed|no_op`)
- `stop_reason`
- `stop_message`
- `turn_id`
- `attempt_id`
- `should_schedule_followup`
- `pending_wakeup_at`
- `result_preview`
- `evidence_summary` (optional initially)

### Idempotency rule

If the same external trigger is replayed against an already-advanced run state, `tick()` must fail safely to a typed `no_op` or recovery result rather than replaying execution blindly.

## Transition sequence inside one tick

The minimum sequence is:

1. **Load persisted canonical state**
2. **Validate trigger and state**
3. **Allocate identifiers if entering a new turn**
4. **Persist `turn_planned` or equivalent start event**
5. **Run executor path**
6. **Persist execution result metadata**
7. **Run verifier path**
8. **Choose next steady state**
9. **Persist required terminal/nonterminal event(s)**
10. **Write updated checkpoint**
11. **Return scheduling hint / stop info**

## Identifier allocation

### `run_id`
Allocated once in `start()`.

### `turn_id`
Allocated when a new planned turn becomes durable.

### `attempt_id`
Allocated per execution attempt within a turn.
Initial thin implementation may use one attempt per turn, but the allocation point must be explicit now so retries can later be added without redefining ownership.

## Durable write ordering

The runtime must freeze one explicit ordering rule.

Recommended first rule:
1. append event row
2. write updated checkpoint
3. if checkpoint write fails after event append, mark recovery conservatively on next load

Rationale:
- append-only events should remain the factual transition trail
- checkpoint is the latest summarized state view
- partial-write recovery becomes diagnosable because the event trail exists

Required follow-on rule:
- if checkpoint write fails, the runtime must surface a conservative failure/stop path
- no optimistic continuation after persistence failure

## Required event obligations

Minimum event family for the extraction slice:
- `run_created`
- `goal_bound`
- `turn_planned`
- `turn_execution_started`
- `turn_executed`
- `turn_verified`
- `paused`
- `resumed`
- `stop_requested`
- `stopped`
- `failed`
- `recovered`

The full event schema can stay incremental, but the runtime must own **when** these events are emitted.

## Surface-neutral control plane rules

### CLI
CLI subcommands must become thin wrappers over runtime APIs:
- `hermes loop pause` -> `LoopRuntime.pause()`
- `hermes loop resume` -> `LoopRuntime.resume()`
- `hermes loop stop` -> `LoopRuntime.stop()`
- `hermes loop status` -> persisted read path, not gateway-local mirror

### Gateway
Gateway auto-followup must stop owning hidden transition logic.
Gateway should:
1. ask runtime for status/tick/control actions
2. use runtime result to enqueue or message the user
3. keep `_loop_states` only as a short-lived mirror/cache if still needed during migration

### Scheduler / wakeups
Schedulers must never mutate active run state directly.
They may only:
- call `tick(run_id, trigger="scheduler")`
- call `resume()` when an explicit runtime contract says resume is safe

## Recovery semantics

### Interrupted execution
If restart occurs during an in-flight execution and the runtime cannot prove safe replay, the run must enter `recovery_incomplete`.

### Resume after ambiguity
`resume()` may reactivate a run in `recovery_incomplete` only when:
- an operator explicitly requests it, or
- a future deterministic proof of safe retry exists

Do not silently replay.

## Goal supersession hook

This spec does not define the whole `LoopGoalRegistry`, but it must define the minimal hook.

Minimum rule:
- if a new persisted goal revision is bound to an active session/run relationship, runtime must decide one of:
  - stop current run with a typed supersession reason
  - pause current run and require explicit operator resume into a new run
  - create a new run and mark the old run superseded

The first extraction slice may support only one of these, but the hook must be explicit.

## Minimum acceptance criteria for implementation

A runtime extraction slice is considered successful only if all are true:

1. a shared `LoopRuntime` exists and is used by both CLI and gateway for at least one real control/transition path
2. `tick()` reloads persisted state before acting
3. runtime, not surfaces, owns transition legality checks
4. turn/attempt allocation points are explicit
5. required event/checkpoint writes happen through one runtime-owned path
6. pause/resume/stop use the same runtime-owned persistence contract
7. gateway `_loop_states` is no longer the sole truth for any transitioned run
8. persistence failure remains fail-closed

## Required tests for the first implementation slice

### Unit
- `tick()` rejects illegal states
- `tick()` allocates `turn_id` only when entering a new durable turn
- `pause()` / `resume()` / `stop()` produce typed persisted state
- duplicate trigger replay yields safe `no_op` or conservative recovery behavior
- partial-write recovery path is conservative

### Integration
- CLI control commands call runtime-owned control path
- gateway followup path uses `tick()` for at least one bounded transition
- recovery after restart loads persisted state and does not depend solely on `_loop_states`
- explicit operator resume from `recovery_incomplete` works or fails legibly

## Explicit anti-patterns

Do not implement this slice as:
- a wrapper that still lets gateway and CLI privately mutate checkpoints on the side
- a "runtime" class that only forwards to existing surface-local logic without owning transitions
- a giant refactor that rewrites every loop file at once
- a scheduler-first design
- a broader artifact migration coupled to the first shared-runtime extraction

## Recommended implementation order

1. add minimal `LoopRuntime` with shared persisted-state load + legality checks
2. move one bounded control path (`stop` or `pause/resume`) behind runtime ownership
3. move one bounded execution path (`tick`) behind runtime ownership
4. migrate gateway followup to call runtime instead of owning transition logic directly
5. reduce `_loop_states` to a mirror/cache rather than source of truth
6. only after that expand goal-registry or richer verifier/event semantics

## Practical interpretation

If implemented well, this spec should produce:
- a smaller and more honest seam between surfaces and durable loop state
- less duplicated transition logic
- a real place to attach future `LoopGoalRegistry`, richer event schemas, and verifier evidence tiers
- better restart/recovery safety without inventing a new orchestration framework

It should **not** be described as a complete loop-v2 finish line.
It is the next architectural substrate slice that makes the remaining work more governable.