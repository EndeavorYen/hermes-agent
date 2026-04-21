# Loop v2 Rollout Plan

Primary reference: `runtime-architecture.md`

## Phase 0: docs and contract agreement

Deliver:
- architecture spec
- ADRs
- schema checklist
- stop taxonomy agreement

Exit criteria:
- implementation can proceed without re-litigating core runtime shape

## Phase 1: runtime extraction

Deliver:
- internal typed models
- filesystem-backed checkpoint/event helpers
- planner/verifier wrappers around current `hermes_cli.loop` logic
- `LoopRuntime.tick()` for one durable transition cycle

Exit criteria:
- bounded CLI/gateway behavior still works
- no user-facing regression

## Phase 2: gateway durability

Deliver:
- replace in-memory `_loop_states` dependence with checkpoint-backed runtime state
- restart recovery for active runs
- run listing/status plumbing

Exit criteria:
- gateway auto-followup survives restart
- active loop status can be reconstructed from artifacts

## Phase 3: operator controls

Deliver:
- pause/resume/stop/status commands
- typed stop disclosure
- resumability summary

Exit criteria:
- users/operators can inspect and control active runs safely

## Phase 4: stronger anti-stall controls

Deliver:
- retry budgets
- idle timeout
- additional deterministic stop rules
- ambiguous interrupted-turn recovery policy

Exit criteria:
- repeated low-signal continuation is bounded and diagnosable

## Test plan by phase

### Unit
- transition rules
- store read/write behavior
- schema validation
- stop evaluator logic

### Integration
- CLI continue/stop
- gateway auto-followup
- restart recovery
- pause/resume/stop flows
- malformed planner/verifier output

## Migration notes

1. Keep current CLI and gateway entry points stable.
2. Move internals behind the runtime incrementally.
3. Dual-write legacy logs if needed during transition.
4. Remove surface-local loop logic only after parity is verified.
