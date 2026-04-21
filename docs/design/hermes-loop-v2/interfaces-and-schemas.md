# Loop Interfaces and Schemas

This document is the implementation checklist for loop v2 data contracts.

Primary reference: `runtime-architecture.md`

## Versioning rules

1. Every persisted loop artifact includes a top-level `version`.
2. Additive fields are preferred over breaking changes.
3. Unknown fields must be ignored by readers when safe.
4. Checkpoint and event schemas can evolve independently.

## Core contracts

### `LoopGoal`

Required:
- `version`
- `goal_id`
- `session_id`
- `goal_text`
- `success_criteria`
- `constraints`
- `revision`
- `created_at`
- `created_by`

### `LoopRun`

Required:
- `version`
- `run_id`
- `goal_id`
- `session_id`
- `session_key` (when a gateway surface needs local routing identity)
- `state`
- `turn_index`
- `retry_index`
- `started_at`
- `updated_at`

Optional:
- `stop_reason`
- `stop_message`
- `last_turn_id`
- `pending_wakeup_at`

### `LoopTurn`

Required:
- `version`
- `turn_id`
- `run_id`
- `attempt_id`
- `turn_index`
- `planned_prompt`
- `planned_at`

Optional:
- `execution_result`
- `verification`
- `artifacts`

### `LoopDecision`

Required:
- `version`
- `turn_id`
- `action` (`continue|pause|stop`)
- `reason`

Conditional:
- `next_prompt` when `action=continue`
- `pause_reason` when `action=pause`
- `stop_reason` when `action=stop`

### `LoopVerification`

Required:
- `version`
- `turn_id`
- `verdict` (`progress|stalled|done|inconclusive`)
- `reason`
- `should_continue`

Recommended:
- `evidence_summary`
- `evidence_tier` (`external|session_delta|self_report_only|none`)

### `LoopStopRecord`

Required:
- `version`
- `run_id`
- `stop_reason`
- `stop_class`
- `message`
- `stopped_at`

## Event log rows

Required:
- `event_id`
- `ts`
- `run_id`
- `attempt_id`
- `event`
- `state_before`
- `state_after`
- `payload`

Recommended events:
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

## Checkpoint fields

Recommended minimum checkpoint shape:
- `version`
- `run_id`
- `goal_id`
- `session_id`
- `state`
- `turn_index`
- `retry_index`
- `last_prompt_norm`
- `last_result_preview`
- `last_verifier_verdict`
- `last_evidence_tier`
- `remaining_budget`
- `pending_wakeup_at`
- `updated_at`

## Validation requirements

1. Planner output must be normalized into valid `LoopDecision`.
2. Verifier output must be normalized into valid `LoopVerification`.
3. Terminal runs must include a `LoopStopRecord`.
4. Every persisted transition should have both an event row and updated checkpoint.
5. Invalid verifier payloads must fail closed to `inconclusive` or a typed pause/stop path, not optimistic progress.
