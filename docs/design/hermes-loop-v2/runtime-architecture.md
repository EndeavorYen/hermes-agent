# Hermes Loop v2 Runtime Architecture

## 1. Summary

Hermes loop v2 should be a **durable, interruptible, surface-neutral continuation runtime** built as a thin extension of the current bounded loop controller.

The right design is **not** a new workflow framework. It is a small runtime layer that standardizes:
- an immutable goal contract
- a canonical loop state machine
- append-only turn artifacts plus compact checkpoints
- explicit stop/failure semantics
- resume/replay behavior across CLI and gateway
- independent progress verification before further continuation

The existing slice in `hermes_cli.loop` and `gateway.run` is the correct seed. Loop v2 should formalize and harden it rather than replace it.

---

## 2. Problem statement

Current Hermes loop behavior is useful but intentionally bounded:
- continuation decisions exist
- semantic progress verification exists
- gateway auto-followup exists
- stop notices and some stall suppression exist
- state is still partly in-memory and partly implicit in session history / JSONL logs

That is enough for short autonomous bursts, but not for reliable long-running continuation where Hermes may need to:
- survive process restarts
- pause and resume safely
- expose operator-visible loop status
- distinguish transient failure from true stop
- avoid repeated low-signal work across many turns
- carry a stable objective across surfaces

Loop v2 should solve those runtime engineering problems with the minimum added machinery.

---

## 3. Goals

### 3.1 Primary goals

1. **Durable continuation**  
   A loop can survive gateway restarts or CLI relaunches.

2. **Single canonical state model**  
   CLI and gateway follow the same loop lifecycle semantics.

3. **Interrupt/resume safety**  
   Every continuation turn can be paused, stopped, retried, or resumed without undefined behavior.

4. **Verifier-gated autonomy**  
   A loop only continues after explicit progress verification and stop checks.

5. **Thin implementation surface**  
   Use plain Python modules, append-only JSONL, and small snapshot files instead of introducing an orchestration framework.

6. **Upstream-friendly evolution**  
   Preserve current entry points and incrementally refactor internals.

### 3.2 Non-goals

1. Building a general DAG/workflow engine.
2. Replacing Hermes session storage with a new database.
3. Introducing a complex memory subsystem specific to loop v2.
4. Moving core execution logic into prompt-only skills.
5. Adding speculative parallel branches in v2 initial rollout.

---

## 4. Core principles

### 4.1 Session history remains primary

The existing Hermes session transcript remains the source of truth for what the agent actually saw and did. Loop artifacts are supplementary runtime records, not a second conversation system.

### 4.2 Goal contract is explicit and stable

Long-running continuation only works when the runtime has a stable objective. The loop must run against a concrete `LoopGoal` contract rather than an implicit "keep going" instruction.

### 4.3 State machine over ad hoc booleans

The runtime should expose a small, canonical set of states and transitions. Avoid scattered flags like `remaining_auto_turns` as the main control model.

### 4.4 Append-only events + compact checkpoints

Durability should come from:
- append-only event JSONL for auditability and replay
- a small checkpoint snapshot for fast recovery

This is simpler and more robust than mutable in-memory-only state.

### 4.5 Verification is separate from execution

Execution produces candidate progress. Verification determines whether that progress is meaningful enough to justify another turn.

### 4.6 Stop reasons are first-class

Stopping is not an error path. It is a structured outcome with a typed reason, human-readable explanation, and final disclosure.

### 4.7 Evidence beats narration

The loop must prefer externally checkable progress over self-report.

Evidence hierarchy:
- external state evidence — file changes, tool outputs, test results, API responses, persisted artifacts
- session delta evidence — new concrete deliverables or decisions visible in the transcript
- self-report only — the assistant claims it progressed

The verifier and stop evaluator must not let self-report override the absence of stronger evidence.

### 4.7 Surface-neutral runtime

CLI, gateway, and future surfaces should all call the same loop runtime API. Surface-specific code should only handle triggering and delivery.

### 4.8 Bounded by default

Long-running does not mean unbounded. The runtime should always have configurable limits for turns, retries, idle time, and repeated/no-progress behavior.

---

## 5. Architecture choice

## Chosen approach

A **thin loop runtime module** with:
- one canonical state machine
- one durable checkpoint per active loop run
- one append-only event log per loop run
- one scheduler interface used by CLI/gateway surfaces
- reuse of existing Hermes execution/session infrastructure

### Why this is the best fit

It captures the useful lessons from LangGraph/Open SWE/SWE-agent style systems:
- explicit workflow states
- durable checkpoints
- interrupt/resume
- external verification
- reusable skills/tools/session memory

But it avoids importing their framework shape into Hermes. Hermes already has:
- sessions
- agent execution
- tools
- gateway event routing
- bounded continuation logic

So the missing piece is a **runtime protocol**, not a new platform.

---

## 6. Proposed runtime components

## 6.1 `LoopGoalRegistry`

Responsible for creating and loading the loop goal contract.

Responsibilities:
- create a `LoopGoal` from `/loop` or CLI invocation
- assign a stable `goal_id`
- support goal revisions when the user materially changes direction
- expose the latest active goal for a session

Notes:
- the goal is immutable once a run begins; edits create a new revision
- old revisions remain readable for auditability

## 6.2 `LoopRuntime`

The orchestrator for loop execution.

Responsibilities:
- load checkpoint
- determine current state
- execute one state transition at a time
- persist events/checkpoint after each transition
- expose `start`, `resume`, `pause`, `stop`, `tick`

Design note:
- this should be a plain Python service module, not a background framework
- `tick()` should do one durable step and return; surfaces/schedulers can call it repeatedly

## 6.3 `LoopStateStore`

Persistence for active loop run state.

Responsibilities:
- read/write current checkpoint
- append events
- list active runs
- recover incomplete turns after restart

Implementation preference:
- filesystem-backed JSON + JSONL under Hermes home
- no new DB in initial v2

## 6.4 `TurnPlanner`

Wraps current continuation decision logic.

Responsibilities:
- call the existing decision path (evolved from `decide_continuation_for_session()`)
- produce `LoopDecision`
- enforce schema validation
- normalize next-step prompts / structured actions

## 6.5 `TurnExecutor`

Runs the actual next continuation step using the session.

Responsibilities:
- execute one bounded agent turn
- bind execution to `session_id` and `turn_id`
- capture output summary/artifacts
- emit execution result event

## 6.6 `ProgressVerifier`

Wraps current semantic verification logic.

Responsibilities:
- evaluate latest turn output against goal + recent history + prior artifacts
- classify as `progress`, `stalled`, or `done`
- recommend continue/stop/retry eligibility

## 6.7 `StopEvaluator`

Applies deterministic runtime stop rules.

Responsibilities:
- repeated prompt detection
- duplicate result detection
- max turn budget
- retry exhaustion
- idle timeout
- user stop / operator stop
- policy stop from planner/verifier

Important split:
- planner/verifier produce semantic judgments
- stop evaluator owns deterministic runtime rules and stop taxonomy

## 6.8 `FollowupScheduler`

Schedules the next `tick()`.

Responsibilities:
- gateway: queue internal follow-up event
- CLI: run immediate next cycle or spawn resumable background launcher
- future: cron/daemon polling if desired

Constraint:
- scheduler must be replaceable; runtime semantics cannot depend on one surface

## 6.9 `LoopStatusView`

Human/operator-facing state summary.

Responsibilities:
- show active state, last progress, stop reason, next wakeup, remaining budget
- generate stop notices and resumable summaries

This formalizes what `format_loop_stop_notice()` started.

---

## 7. State model

## 7.1 Canonical run states

A loop run should have one of these states:

- `created` — goal exists, run created, no planning yet
- `planning` — runtime is deciding whether/how to continue
- `executing` — one bounded continuation turn is in flight
- `verifying` — latest turn is being evaluated for real progress
- `waiting` — run is healthy and waiting for scheduled next tick
- `paused` — run intentionally suspended, resumable without semantic reset
- `stopped` — normal terminal state
- `failed` — abnormal terminal state after unrecoverable runtime failure

### Derived flags

These should be derived, not primary state:
- `is_terminal`
- `is_resumable`
- `needs_operator_attention`
- `has_inflight_turn`

## 7.2 Transition model

```text
created -> planning
planning -> stopped      (planner says stop / invalid goal / no next step)
planning -> executing    (planner returns bounded next action)
executing -> verifying   (turn completed and artifacts captured)
executing -> waiting     (execution delegated async and still running)
executing -> failed      (unrecoverable executor error)
verifying -> planning    (verified progress, continue allowed)
verifying -> stopped     (done/stalled/stop rule triggered)
waiting -> executing     (async execution resumes/completes under scheduler)
waiting -> planning      (wake up for next turn)
paused -> planning       (resume)
any active -> paused     (user/operator pause)
any active -> stopped    (user/operator stop)
any active -> failed     (checkpoint corruption / unrecoverable recovery error)
```

## 7.3 Why this state machine

It is intentionally smaller than a generic workflow graph, but it captures the important operational distinctions:
- planning and verification are separate
- waiting is not executing
- paused is not stopped
- failed is explicit and diagnosable

---

## 8. Execution sequence

## 8.1 Start sequence

1. Surface receives `/loop` or CLI loop invocation.
2. Runtime creates or resolves `LoopGoal`.
3. Runtime creates `LoopRun` with `state=created`.
4. Runtime writes checkpoint + `run_created` event.
5. Runtime enters `planning` on first `tick()`.

## 8.2 One loop turn

1. Load checkpoint.
2. Check for terminal/pause conditions.
3. Run planner.
4. If planner returns stop or pause, emit the corresponding event and finalize/suspend.
5. If planner returns continue, persist `turn_planned`.
6. Execute one bounded turn against the session.
7. Persist `turn_executed` with execution summary.
8. Apply a hard observable-evidence gate.
9. Run progress verifier.
10. Persist `turn_verified`.
11. Apply deterministic stop evaluator.
11. Either:
   - finalize `stopped`, or
   - transition to `planning`/`waiting` and schedule next tick.

### 8.2.1 Observable-evidence gate

Before semantic verification may classify a turn as strong `progress` or `done`, at least one of these should be true:
- the turn produced a persistent artifact or changed an existing one
- a tool returned new information that concretely changes the next bounded step
- the transcript contains a concrete deliverable, decision, or resolved blocker that was not present before

If none of those are true, the runtime should classify the turn conservatively as `stalled` or `inconclusive`, not progress.

## 8.3 Resume after restart

1. Runtime lists non-terminal checkpoints.
2. For each run, load latest checkpoint.
3. If state was `executing` with no completion record:
   - mark as `waiting_recovery` internally during recovery logic, or map directly to `planning` with a `recovery_needed` event
   - determine whether the in-flight turn completed, is unknown, or must be retried
4. Re-enter canonical state (`planning`, `waiting`, or `failed`) and continue.

Implementation note:
- no special permanent state is needed for `waiting_recovery`; this can be represented as a recovery event plus a new canonical state

---

## 9. Data contracts

These are conceptual contracts for v2. Exact field names can evolve, but the shapes should remain stable.

## 9.1 `LoopGoal`

```json
{
  "version": 1,
  "goal_id": "goal_...",
  "session_id": "sess_...",
  "created_at": "2026-04-21T01:25:00Z",
  "created_by": "cli|gateway",
  "goal_text": "Continue autonomously until a real stop condition is reached.",
  "success_criteria": [
    "Make concrete progress toward the stated objective",
    "Stop on ambiguity, convergence, or user-level tradeoff"
  ],
  "constraints": {
    "max_turns": 50,
    "max_retries_per_turn": 2,
    "idle_timeout_seconds": 900,
    "require_verification": true
  },
  "revision": 1,
  "supersedes_goal_id": null,
  "metadata": {
    "surface": "gateway",
    "channel_id": "..."
  }
}
```

### Rules
- `goal_text` is immutable within a run
- user changes produce a new goal revision
- run checkpoints reference a specific `goal_id`

## 9.2 `LoopRun`

```json
{
  "version": 1,
  "run_id": "run_...",
  "goal_id": "goal_...",
  "session_id": "sess_...",
  "state": "planning",
  "started_at": "2026-04-21T01:26:00Z",
  "updated_at": "2026-04-21T01:26:10Z",
  "surface": "gateway",
  "turn_index": 3,
  "retry_index": 0,
  "last_turn_id": "turn_...",
  "stop_reason": null,
  "stop_message": null
}
```

## 9.3 `LoopDecision`

```json
{
  "version": 1,
  "turn_id": "turn_...",
  "action": "continue|pause|stop",
  "reason": "short factual reason",
  "next_prompt": "bounded next step",
  "pause_reason": null,
  "planner": {
    "source": "hermes_self_planner",
    "model": "..."
  }
}
```

## 9.4 `LoopExecutionResult`

```json
{
  "version": 1,
  "turn_id": "turn_...",
  "session_id": "sess_...",
  "started_at": "...",
  "completed_at": "...",
  "final_response_preview": "...",
  "message_count_delta": 2,
  "tool_activity": {
    "used_tools": true,
    "tool_names": ["terminal", "read_file"]
  },
  "artifacts": [
    {
      "type": "file",
      "path": "docs/design/hermes-loop-v2/runtime-architecture.md"
    }
  ]
}
```

## 9.5 `LoopVerification`

```json
{
  "version": 1,
  "turn_id": "turn_...",
  "verdict": "progress|stalled|done|inconclusive",
  "reason": "short factual reason",
  "should_continue": true,
  "evidence_summary": [
    "wrote docs/design/hermes-loop-v2/runtime-architecture.md"
  ],
  "verifier": {
    "source": "hermes_progress_verifier",
    "model": "..."
  }
}
```

## 9.6 `LoopStopRecord`

```json
{
  "version": 1,
  "run_id": "run_...",
  "turn_id": "turn_...",
  "stop_reason": "repeated_next_prompt",
  "stop_class": "normal|user|resource|verification|runtime_error",
  "message": "Loop stopped: repeated next prompt.",
  "final": true,
  "stopped_at": "..."
}
```

---

## 10. Artifact model

## 10.1 File layout

Recommended layout under `get_hermes_home()` / `HERMES_HOME`:

```text
<HERMES_HOME>/
  state/
    loops/
      goals/
        <goal_id>.json
      runs/
        <run_id>/
          checkpoint.json
          events.jsonl
          turns/
            <turn_id>.json
```

This should coexist with current logs like `logs/background_reviews.jsonl` during migration.

## 10.2 Why per-run directories

Benefits:
- easy replay/debugging
- small isolated artifacts
- simple cleanup/retention
- avoids one forever-growing global file for all loop runtime concerns

## 10.3 Event schema ideas

`events.jsonl` rows should be append-only and minimal:

```json
{
  "ts": "2026-04-21T01:26:10Z",
  "run_id": "run_...",
  "turn_id": "turn_...",
  "event": "turn_verified",
  "state_before": "verifying",
  "state_after": "planning",
  "payload": {
    "verdict": "progress",
    "reason": "Created a concrete design-doc set in repo"
  }
}
```

Core event types:
- `run_created`
- `goal_bound`
- `turn_planned`
- `turn_execution_started`
- `turn_executed`
- `turn_verified`
- `retry_scheduled`
- `paused`
- `resumed`
- `stop_requested`
- `stopped`
- `failed`
- `recovered`

## 10.4 Checkpoint schema ideas

`checkpoint.json` should be the current materialized state, not a copy of the whole event log:

```json
{
  "version": 1,
  "run_id": "run_...",
  "goal_id": "goal_...",
  "session_id": "sess_...",
  "state": "planning",
  "turn_index": 3,
  "retry_index": 0,
  "last_prompt_norm": "implement the next thin slice",
  "last_result_preview": "Added runtime-architecture.md and README design index",
  "last_verifier_verdict": "progress",
  "remaining_budget": {
    "turns": 47,
    "retries_this_turn": 2
  },
  "pending_wakeup_at": null,
  "updated_at": "..."
}
```

## 10.5 Relation to current artifacts

Current artifacts should map forward as follows:
- `background_reviews.jsonl` -> transitional verifier/stop audit stream
- future per-run `events.jsonl` -> canonical runtime event log
- session transcript -> still canonical execution history

Migration rule:
- do not break existing log readers in phase 1
- dual-write if needed until v2 runtime artifacts stabilize

---

## 11. Stop and failure taxonomy

## 11.1 Stop classes

Every terminal outcome should be assigned to one of these classes:

- `normal` — expected semantic completion or planner stop
- `user` — user explicitly paused/stopped or changed goal
- `resource` — turn/idle/retry budget exhausted
- `verification` — verifier judged done/stalled or deterministic stall suppression fired
- `trust` — progress/completion could not be credibly established from available evidence
- `runtime_error` — unrecoverable runtime/storage/execution failure

## 11.2 Proposed stop reasons

### Semantic / planner stops
- `model_stop`
- `missing_goal`
- `missing_next_prompt`
- `goal_revised`
- `no_bounded_next_step`

### Verification / anti-stall stops
- `progress_verifier_done`
- `progress_verifier_stalled`
- `progress_verifier_inconclusive`
- `repeated_next_prompt`
- `duplicate_result_preview`
- `empty_continuation_result`
- `no_new_artifacts`
- `no_observable_delta`

### Resource stops
- `max_turns_reached`
- `max_retries_reached`
- `idle_timeout`
- `max_runtime_reached`

### User/operator stops
- `user_stop`
- `user_pause`
- `operator_stop`
- `session_superseded`

### Runtime failures
- `invalid_decision_payload`
- `invalid_progress_verifier_payload`
- `session_not_found`
- `checkpoint_corruption`
- `artifact_write_failed`
- `executor_crash`
- `recovery_incomplete`

## 11.3 Stop disclosure contract

Every visible stop should provide:
- stop reason code
- concise human message
- whether the run is resumable
- last meaningful progress summary

Example:

```text
Loop stopped: latest continuation did not materially advance the goal. (progress_verifier_stalled)
Resumable: yes
Last progress: Added runtime-architecture.md and README design index.
```

---

## 12. Failure handling and recovery

## 12.1 Failure categories

1. **Planner/verifier payload failure**  
   Invalid model JSON or missing fields.

2. **Execution failure**  
   Agent turn crashes, timeout, or transport failure.

3. **Storage failure**  
   Checkpoint or event write fails.

4. **Recovery ambiguity**  
   After restart, runtime cannot determine whether an in-flight turn completed.

## 12.2 Recovery policy

### Planner/verifier payload failure
- fail closed to `pause` or typed stop depending on context
- do not silently continue forever on malformed outputs
- persist failure event

### Execution failure
- retry if below retry budget and no side-effect ambiguity
- otherwise stop with `executor_crash` or `max_retries_reached`

### Storage failure
- fail closed
- if event/checkpoint cannot be persisted, do not advance the run optimistically

### Recovery ambiguity
- create `recovered` event with ambiguity metadata
- default to safe stop or explicit retry depending on surface and side-effect risk

## 12.3 Idempotency guidance

To keep resume/retry safe:
- planner outputs should be deterministic enough to compare/normalize
- turn execution should record previews and artifact paths
- recovery should detect whether the same turn likely already completed
- external side-effectful actions should prefer human confirmation or stronger replay markers

---

## 13. Surface integration

## 13.1 CLI

CLI should use `LoopRuntime.tick()` directly for:
- `loop once`
- `loop run`
- future `loop resume`, `loop pause`, `loop status`, `loop stop`

CLI should not duplicate planner/verifier logic.

## 13.2 Gateway

Gateway should stop owning autonomous logic directly.

Current gateway pieces map to v2 as:
- `_loop_states` -> replaced by `LoopStateStore` checkpoint lookup
- `_maybe_schedule_loop_followup()` -> adapter over `LoopRuntime.tick()` + scheduler
- `_apply_loop_stop_notice()` -> `LoopStatusView.format_stop_notice()` or equivalent

Gateway remains responsible for:
- converting platform events into loop commands
- delivering follow-up prompts/results
- surfacing pause/stop/status to users

## 13.3 Skills / fallback

`agent/skill_commands.py` remains a compatibility/fallback path, but core loop runtime behavior should live in code, not depend on bundled skill prompts for correctness.

Skills may still help with:
- planning style
- domain-specific work modes
- operator guidance

But not with core runtime durability.

---

## 14. Minimal module shape

Recommended new modules:

```text
hermes_loop/
  __init__.py
  models.py          # dataclasses / typed dicts for contracts
  runtime.py         # LoopRuntime orchestration
  store.py           # checkpoint + event persistence
  planner.py         # wraps decide_continuation_for_session logic
  verifier.py        # wraps verify_progress_for_session logic
  stop.py            # deterministic stop evaluation
  status.py          # human-facing summaries / notices
```

Migration-friendly rule:
- initial implementation can keep `hermes_cli.loop` as the facade and move internals underneath incrementally

---

## 15. Implementation roadmap

## Phase 0 — codify the contract

Deliverables:
- design docs committed
- stop taxonomy agreed
- canonical state machine agreed
- data contract names agreed

Code impact:
- none required beyond docs

## Phase 1 — extract runtime internals without behavior expansion

Deliverables:
- factor current planner/verifier logic behind thin runtime interfaces
- introduce `LoopGoal`, `LoopRun`, checkpoint, and event append helpers
- keep current CLI/gateway behavior mostly unchanged

Acceptance criteria:
- existing tests still pass
- gateway and CLI still behave as today
- runtime can emit checkpoint + events for bounded runs

## Phase 2 — durable active-run recovery

Deliverables:
- persist active run state to filesystem
- add CLI/gateway resume support after restart
- replace gateway `_loop_states` in-memory dependency with checkpoint-backed lookup

Acceptance criteria:
- active loop survives process restart
- stop notices and status are reconstructable from checkpoint + events
- test coverage for restart recovery exists

## Phase 3 — explicit controls and operator visibility

Deliverables:
- `loop status`
- `loop pause`
- `loop resume`
- `loop stop`
- clearer stop disclosure and run summaries

Acceptance criteria:
- users can inspect and control long-running loops
- paused runs do not lose state
- stop reasons are typed and visible

## Phase 4 — stronger anti-stall and retry policies

Deliverables:
- retry budget per turn
- idle timeout support
- no-new-artifact / no-new-evidence rules
- better recovery for ambiguous interrupted turns

Acceptance criteria:
- loop avoids repeated low-signal continuation
- retries are bounded and observable
- resource stop reasons are explicit

## Phase 5 — optional advanced capabilities

Possible follow-ons, not required for initial v2:
- scheduled wakeups/backoff
- richer artifact indexing
- per-goal success criteria editors
- delegated subtask runs
- external evaluator hooks

These should only land if phase 1-4 stays simple.

---

## 16. Testing strategy

## 16.1 Unit tests

Add focused coverage for:
- state transitions
- checkpoint read/write
- event append/replay
- stop evaluator decisions
- planner/verifier payload validation

## 16.2 Integration tests

Add end-to-end tests for:
- CLI start -> continue -> stop
- gateway start -> auto-followup -> stop
- restart recovery mid-run
- pause/resume flows
- malformed planner/verifier payloads

## 16.3 Property-style invariants

Important invariants:
- terminal runs never schedule another turn
- every state transition produces an event
- every non-terminal checkpoint is resumable or diagnosably failed
- stop notices always include a typed reason

---

## 17. Open decisions to settle early

1. Exact filesystem path under `get_hermes_home()` / `HERMES_HOME` for loop artifacts.
2. Whether goal revisions create a new run automatically or require explicit user confirmation.
3. How conservative recovery should be for interrupted side-effectful turns.
4. Whether CLI `loop run` should remain synchronous by default or shift to a resumable background launcher.
5. Whether legacy `background_reviews.jsonl` remains dual-written through the full migration.

---

## 18. Recommended next implementation step

The best next code step is:

**Extract a small internal `LoopRuntime` + `LoopStateStore` layer while keeping current `hermes_cli.loop` and `gateway.run` call sites intact.**

That gives Hermes the core v2 shape immediately without destabilizing current behavior.

Concretely, implement in this order:
1. typed models for goal/run/checkpoint/events
2. filesystem-backed store
3. planner/verifier wrappers around current functions
4. runtime `tick()` state transition engine
5. adapt CLI and gateway to call the runtime

This is the lowest-risk path from the current bounded slice to true long-running autonomous continuation.
