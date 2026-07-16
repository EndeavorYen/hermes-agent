# Story Video Batch Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce a five-minute, 18-shot story-video image phase from an unbounded multi-hour agent loop to a bounded, resumable native chunked run while preserving OpenAI-only provenance and visual quality.

**Architecture:** Replace the LLM-driven per-shot scheduler with a native `StoryVideoBatchExecutor`. Each tool call processes up to three images so it remains below the Codex turn deadline; the executor deterministically finishes all fresh shots before a bounded repair wave, records one QC result per candidate, and resolves exhausted ordinary shots through an auditable continuity hold instead of resetting budgets through repeated contract replans. The LLM no longer schedules individual shot transitions.

**Tech Stack:** Python, Hermes plugin tools/hooks, OpenAI Codex image provider, OpenAI vision QC, `ThreadPoolExecutor`, JSON manifests, pytest.

## Global Constraints

- Story-video LLM, image generation, and vision QC remain `openai-codex`; xAI/Grok remain forbidden.
- Do not lower `QUALITY_THRESHOLD = 80.0` to gain speed.
- Generate one initial candidate per shot; ordinary body shots may receive at most one generated repair across all contract revisions.
- Critical opening, style-anchor, and release-art shots may receive one additional repair only while the run-wide candidate cap remains intact.
- A five-minute 18-shot run may generate at most 22 body candidates: 18 initial candidates plus a global repair reserve of 4.
- Fresh-shot generation must not wait behind a failed earlier shot.
- Default image concurrency is 3 and must be proven by overlapping provider timestamps.
- Operator stop must cancel pending work and prevent new provider dispatches.
- Existing selected current artifacts remain resumable and are never regenerated without a superseding shot-contract hash.

---

## Baseline And Root Cause

The July 16 live production evidence established the failure:

- 18 required shots, but only 7 selected after about 90 minutes.
- 39 orchestration API calls and 13 session rotations.
- 27 candidate-history rows for only 9 attempted shots.
- `S06_SH00` consumed 8 attempts; `S07_SH00` consumed 5.
- `MAX_REPAIR_ROUNDS = 3` is scoped to the current shot-contract hash. Each automatic contract replan creates a new local budget, so the end-to-end shot budget is not actually bounded.
- `_next_batch_work()` prioritizes `repair_required` and `quality_budget_exhausted` before untouched shots, causing head-of-line blocking.
- `_next_batch_work_group()` can batch only untouched shots. Every repair, rejudge, and replan is forced through a singleton LLM turn.
- Autopilot rotates after three continuations, so a long image phase repeatedly starts fresh Codex app-server sessions.

The correct fix is a native scheduler plus an end-to-end run budget, not a looser QC threshold or shorter prompts.

### Acceptance Targets

- Fixture: 18 shots, 6 initial failures, 3 successful repairs.
- Body candidates dispatched: `<= 22`.
- Ordinary candidates per shot: `<= 2` across every contract hash and replan.
- Batch orchestration turns: `<= 9`; batch session rotations: `0` for the 18-shot fixture.
- Provider concurrency: 3 overlapping fresh generations.
- No hard-blocked image is selected.
- Bounded best effort is allowed only at score `>= 75`, with no hard blocker and explicit audit evidence.
- Live 18-shot batch wall time: `<= 45 minutes` and at least 40% faster than the July 16 baseline at comparable provider health.
- Full five-minute review artifact target: `<= 70 minutes`, reported separately from provider queue time.

---

### Task 1: Add End-To-End Production Budgets And Metrics

**Files:**
- Create: `plugins/story_video/batch_policy.py`
- Modify: `plugins/story_video/state.py`
- Modify: `plugins/story_video/audit.py`
- Test: `tests/plugins/story_video/test_batch_policy.py`
- Test: `tests/plugins/story_video/test_state.py`

**Interfaces:**
- Produces: `BatchPolicy.for_run(shot_count: int) -> BatchPolicy`
- Produces: `BatchBudget.can_generate(shot_id: str, critical: bool) -> bool`
- Produces: `BatchBudget.record_generation(shot_id: str, contract_hash: str) -> None`
- Produces: `BatchMetrics.record(stage: str, shot_id: str, started_at: str, completed_at: str, status: str) -> None`

- [ ] **Step 1: Write failing budget tests**

Cover these exact behaviors:

```python
def test_replan_does_not_reset_end_to_end_shot_budget():
    budget = BatchBudget(BatchPolicy(max_candidates_per_shot=2, max_total_candidates=22))
    budget.record_generation("S06_SH00", "contract-a")
    budget.record_generation("S06_SH00", "contract-b")
    assert budget.can_generate("S06_SH00", critical=False) is False


def test_eighteen_shot_run_caps_repairs_at_four():
    policy = BatchPolicy.for_run(18)
    assert policy.initial_candidate_cap == 18
    assert policy.repair_candidate_cap == 4
    assert policy.max_total_candidates == 22
```

- [ ] **Step 2: Run tests and verify the new module is missing**

Run: `pytest -q tests/plugins/story_video/test_batch_policy.py`

Expected: FAIL because `plugins.story_video.batch_policy` does not exist.

- [ ] **Step 3: Implement immutable policy and persisted budget state**

Persist counts in `manifests/batch_run_manifest.json`, keyed by `shot_id`, not by candidate or contract hash. Record `purpose` values separately as `orchestration`, `image_generation`, and `vision_qc` so quota analysis no longer conflates them.

- [ ] **Step 4: Verify budget and state tests**

Run: `pytest -q tests/plugins/story_video/test_batch_policy.py tests/plugins/story_video/test_state.py`

Expected: PASS.

---

### Task 2: Make Exhausted Shots Terminal Without Blocking Fresh Work

**Files:**
- Modify: `plugins/story_video/visual_judge.py`
- Modify: `plugins/story_video/repair_planner.py`
- Test: `tests/plugins/story_video/test_visual_judge.py`
- Test: `tests/plugins/story_video/test_repair_planner.py`

**Interfaces:**
- Consumes: `BatchBudget` from Task 1.
- Produces: `_resolve_exhausted_shot(context, shot_id, budget) -> dict[str, Any]`
- Produces terminal statuses: `selected_current`, `continuity_hold`, or `human_review_required` only for mandatory unique evidence.

- [ ] **Step 1: Write regression tests for the July 16 loop**

Create a fixture where a shot has three old-contract attempts and two new-contract attempts. Assert that `next_batch_work` does not return another generation or replan after the end-to-end cap is reached.

```python
assert result["operation"] != "repair"
assert result["operation"] != "replan_shot_contract"
assert result["status"] in {"continuity_hold", "human_review_required"}
```

- [ ] **Step 2: Write a head-of-line regression test**

With `S02` exhausted and `S03` untouched, assert that the next fresh-wave group contains `S03` instead of repeatedly returning `S02`.

- [ ] **Step 3: Run the focused tests and confirm both fail**

Run: `pytest -q tests/plugins/story_video/test_visual_judge.py tests/plugins/story_video/test_repair_planner.py -k 'end_to_end_budget or head_of_line'`

Expected: FAIL under the current per-contract budget and repair-first ordering.

- [ ] **Step 4: Implement terminal resolution**

Reuse the existing terminal fallback and continuity-hold machinery. A continuity hold must point to a compatible adjacent selected image, retain the failed shot's narration interval, and record why no extra image was generated. Never copy a score from the adjacent shot as if it were a fresh visual judgment.

- [ ] **Step 5: Verify repair planning and quality behavior**

Run: `pytest -q tests/plugins/story_video/test_visual_judge.py tests/plugins/story_video/test_repair_planner.py`

Expected: PASS.

---

### Task 3: Build The Native Two-Wave Batch Executor

**Files:**
- Create: `plugins/story_video/batch_executor.py`
- Modify: `tools/image_generation_tool.py`
- Modify: `plugins/story_video/visual_judge.py`
- Test: `tests/plugins/story_video/test_batch_executor.py`
- Test: `tests/tools/test_image_generation.py`

**Interfaces:**
- Produces: `generate_image(args: dict[str, Any], *, task_id: str = "") -> dict[str, Any]` as the public provider-safe wrapper around the current image handler.
- Produces: `StoryVideoBatchExecutor.run_chunk(context, cancel_check) -> BatchRunSummary`.
- `BatchRunSummary` includes `selected`, `continuity_holds`, `failed`, `generated_candidates`, `vision_qc_calls`, `elapsed_sec`, and `provider_wait_sec`.

- [ ] **Step 1: Write a failing concurrency test**

Inject a fake generator that records start/end times. With six untouched shots and concurrency 3, assert that the first three calls overlap and that no more than three run simultaneously.

- [ ] **Step 2: Write a failing two-wave test**

Initial wave: six candidates, two QC failures. Repair wave: exactly those two shots, one candidate each. Assert eight total generations and no third wave.

- [ ] **Step 3: Write provider and partial-failure tests**

Every generation request must include `provider="openai-codex"`. A transient provider failure may retry once without consuming semantic repair budget; successful siblings remain committed and are not regenerated.

- [ ] **Step 4: Run tests and confirm executor absence**

Run: `pytest -q tests/plugins/story_video/test_batch_executor.py tests/tools/test_image_generation.py`

Expected: FAIL because the executor and public wrapper do not exist.

- [ ] **Step 5: Implement the initial wave**

Compile every untouched prompt deterministically, submit groups through `ThreadPoolExecutor(max_workers=3)`, and atomically persist each completed provider result before QC. Do not wait for an earlier shot's repair before generating later untouched shots.

- [ ] **Step 6: Implement the repair wave**

Use one semantic repair directive derived from the first QC result. Spend the run-wide repair reserve only on shots with hard blockers or score below 75. Accept clean `75-79.99` candidates as explicit bounded best effort; otherwise use terminal resolution from Task 2.

- [ ] **Step 7: Verify executor and image-provider tests**

Run: `pytest -q tests/plugins/story_video/test_batch_executor.py tests/tools/test_image_generation.py tests/tools/test_image_generation_plugin_dispatch.py`

Expected: PASS.

---

### Task 4: Move Auto Mode Off The LLM Scheduler

**Files:**
- Modify: `plugins/story_video/schemas.py`
- Modify: `plugins/story_video/visual_judge.py`
- Modify: `plugins/story_video/hooks.py`
- Modify: `plugins/story_video/__init__.py`
- Test: `tests/plugins/story_video/test_hooks.py`
- Test: `tests/plugins/story_video/test_tools.py`

**Interfaces:**
- Adds: `story_video_quality_control(action="run_batch_chunk")`.
- Auto continuation emits bounded `run_batch_chunk` actions for the image phase, then one `story_video_control(action="validate")` action.
- Manual `compile_prompt`, `judge_candidates`, and `next_batch_work` remain available for diagnostics and one release of rollback compatibility.

- [ ] **Step 1: Write failing autopilot tests**

Assert that batch auto continuation requests `run_batch_chunk`, does not enumerate shot IDs in natural-language scheduling instructions, and does not rotate every three shots.

- [ ] **Step 2: Add stop and resume tests**

Stop during a three-call provider group: running calls may finish and persist, queued calls must be cancelled, and no repair wave may start. Resume must skip selected and already persisted successful candidates.

- [ ] **Step 3: Run focused tests and confirm current behavior fails**

Run: `pytest -q tests/plugins/story_video/test_hooks.py tests/plugins/story_video/test_tools.py -k 'run_batch or stop or resume'`

Expected: FAIL because current auto mode emits per-group natural-language continuations.

- [ ] **Step 4: Wire the native executor**

Add `run_batch_chunk` to the schema and handler. Keep individual shot scheduling inside the native executor rather than Codex turns.

- [ ] **Step 5: Verify story-video plugin tests**

Run: `pytest -q tests/plugins/story_video/test_hooks.py tests/plugins/story_video/test_tools.py tests/plugins/story_video/test_state.py`

Expected: PASS.

---

### Task 5: Add Release-Grade Performance Evidence

**Files:**
- Create: `scripts/story_video_batch_benchmark.py`
- Create: `tests/plugins/story_video/fixtures/batch_performance_18_shots.json`
- Modify: `tests/plugins/story_video/test_tools.py`
- Modify: `docs/story-video-operator-guide.md` if present; otherwise create it.

**Interfaces:**
- Produces: `manifests/batch_performance_report.json`.
- Report fields: `wall_time_sec`, `provider_wait_sec`, `orchestration_api_calls`, `vision_qc_calls`, `image_generations`, `repair_generations`, `session_rotations`, `selected_count`, `continuity_hold_count`, `hard_blocker_count`, and `quality_summary`.

- [ ] **Step 1: Add a deterministic benchmark fixture**

The fixture must reproduce six first-pass failures, three repair successes, two clean bounded-best-effort selections, and one continuity hold without network access.

- [ ] **Step 2: Implement benchmark assertions**

Fail the command if candidates exceed 22, a shot exceeds its end-to-end cap, concurrency does not overlap, any hard blocker is selected, or orchestration turns exceed 9.

- [ ] **Step 3: Run the offline release gate**

Run:

```bash
pytest -q tests/plugins/story_video tests/run_agent/test_image_generate_parallel.py
python scripts/story_video_batch_benchmark.py --fixture tests/plugins/story_video/fixtures/batch_performance_18_shots.json
git diff --check
```

Expected: all tests pass and the report says `status=PASS`.

- [ ] **Step 4: Run a bounded live smoke**

Use a three-shot scheduler/provider smoke first. Require OpenAI-only provenance, three-way overlapping dispatch, exactly three candidates, and no operator interaction. This smoke does not claim visual QC quality.

- [ ] **Step 5: Run the final five-minute live benchmark**

Run one 18-shot project only after the three-shot smoke passes. Require batch wall time `<= 45 minutes`, full review artifact `<= 70 minutes`, candidates `<= 22`, and quality evidence meeting the constraints above.

---

### Task 6: Deploy With A Measured Rollback Gate

**Files:**
- Modify: `config.example.yaml`
- Modify: `docs/story-video-operator-guide.md`
- Test: `tests/plugins/story_video/test_hooks.py`

**Interfaces:**
- Native batch becomes the auto-mode default only after Task 5 live gates pass.
- Legacy diagnostic actions remain callable for one release but are not the auto scheduler.
- Rollback is a reviewed revert or hotfix promoted through `local/main`, never a protected-branch rewind.

- [x] **Step 1: Prove native auto routing and legacy diagnostic compatibility**

Assert that production auto mode routes only through `run_batch_chunk` while manual diagnostic actions remain schema-compatible.

- [ ] **Step 2: Deploy through the governed Hermes runtime flow**

Read `docs/hermes-branch-governance.md` and `docs/hermes-release-upgrade-guideline.md` before branch or runtime mutations. Merge only after focused and wider tests pass.

- [ ] **Step 3: Verify runtime truth**

Confirm `local/main`, `runtime/current`, and the launchd gateway all point to the accepted SHA. Run a live schema probe proving `run_batch_chunk` is exposed and image generation remains explicitly `openai-codex`.

- [ ] **Step 4: Verify rollback**

Toggle the flag to legacy in a non-production smoke, confirm no state corruption, then restore native mode. Record both results in the release evidence.

---

## Self-Review

- Spec coverage: provider lock, quality preservation, quota cap, parallel generation, bounded repairs, stop/resume, telemetry, live test, deployment, and rollback are covered.
- Placeholder scan: no TBD/TODO placeholders remain.
- Type consistency: `BatchPolicy`, `BatchBudget`, `BatchMetrics`, `BatchRunSummary`, and `StoryVideoBatchExecutor` are introduced once and reused consistently.
- Deliberate non-goals: TTS, pronunciation, subtitle composition, camera motion, and YouTube upload behavior are unchanged by this plan.
