# ADR-003: Loop State Machine

- Status: Proposed
- Owner: Hermes loop v2
- Related: `runtime-architecture.md`

## Context

Current loop control uses a mix of explicit decisions and surface-local state, especially in gateway `_loop_states`. For durable continuation, Hermes needs one canonical runtime state machine.

## Decision

Hermes loop v2 will standardize on these run states:
- `created`
- `planning`
- `executing`
- `verifying`
- `waiting`
- `paused`
- `stopped`
- `failed`

## State ownership

- Runtime owns state transitions.
- Surfaces trigger actions and display status.
- Stop evaluator owns deterministic stop transitions.
- Planner/verifier contribute semantic inputs but do not directly mutate runtime state.

## Allowed transitions

```text
created -> planning
planning -> executing | stopped
executing -> verifying | waiting | failed
verifying -> planning | stopped
waiting -> planning | executing
paused -> planning
any active -> paused | stopped | failed
```

## Why this machine

It is intentionally small, but captures the distinctions that matter:
- plan vs execute vs verify
- wait vs pause
- stop vs fail

## Consequences

Benefits:
- simpler reasoning across CLI and gateway
- better restart semantics
- cleaner testing of transitions

Costs:
- some existing surface-local flags must be migrated
- runtime transition logic becomes more explicit

## Open questions

1. Should delayed wakeups be represented only as `waiting` + timestamp?
2. Does interrupted execution need any additional transient recovery marker?
3. What should the default resume target be after ambiguous in-flight interruption?
