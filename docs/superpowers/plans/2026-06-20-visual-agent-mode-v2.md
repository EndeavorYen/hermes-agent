# Visual Agent Mode V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade Visual Agent Mode from MVP delivery proof to an evidence-driven production loop with source lineage, self-scoring, bounded repair, and operator reporting.

**Architecture:** Extend the existing `agent.visual` ledger and `agent.visual.agent_mode` modules. Keep runtime-private evidence under `~/.hermes`; add compact, typed source context and scoring records that can be joined from inbound request through artifact delivery. Do not replace `image_generate_mission`, `video_generate`, or Slack media delivery.

**Tech Stack:** Python stdlib (`contextvars`, `dataclasses`, `json`, `sqlite3`, `pathlib`, `typing`), existing Hermes gateway/session/tool stack, `pytest`, current `agent.visual` ledger/artifact/ranker modules, current Slack delivery adapters.

## Global Constraints

- Use TDD for implementation tasks.
- Runtime data stays under `~/.hermes`, not the repo checkout.
- Public tests and docs use generic examples such as `product showcase`, `reference portrait`, and `clean product video`.
- Push integration branches to `origin` only unless an explicit upstream PR workflow is requested.
- Do not store raw private prompts, generated media, local model endpoints, or user preference corpora in tracked files.
- Keep `image_generate_mission` as the image QC path.
- Keep provider failures, aesthetic preference, and delivery failures as separate evidence tracks.
- Any repair loop must be bounded by explicit attempt budgets.

## Execution Strategy

Implement V2 in four phases:

| Phase | Status | Gate |
| --- | --- | --- |
| A. Source lineage | Implemented locally | Source metadata appears in `visual_requests` and live proof |
| B. Self-scoring | Implemented locally | Candidates have automatic score records and selected rationale |
| C. Bounded repair | Implemented locally | Repair attempts are recorded and budget-limited |
| D. Operator reporting | Implemented locally | CLI report summarizes health and strategy outcomes |

Each phase ends with a self-evaluation note in this plan before continuing.

## File Structure

Create:

```text
agent/visual/source_context.py
agent/visual/agent_mode/reward.py
agent/visual/agent_mode/repair_policy.py
scripts/visual_agent_report.py
tests/visual/test_source_context.py
tests/visual/agent_mode/test_reward.py
tests/visual/agent_mode/test_repair_policy.py
tests/visual/test_visual_agent_report.py
```

Modify:

```text
agent/visual/tracking.py
agent/visual/attempt_ledger.py
agent/visual/live_proof.py
agent/visual/ranker.py
tools/visual_agent_tool.py
gateway/run.py
gateway/platforms/base.py
gateway/platforms/slack.py
scripts/visual_agent_live_proof.py
tests/visual/test_attempt_ledger.py
tests/visual/test_live_proof.py
tests/tools/test_visual_agent_tool.py
tests/gateway/platforms/test_slack_visual_delivery.py
```

---

## Phase A: Source Lineage

Goal: every visual request created during a gateway turn should carry source platform, channel, thread, user, and message metadata.

### Task A1: Source Context Carrier

**Files:**
- Create: `agent/visual/source_context.py`
- Test: `tests/visual/test_source_context.py`

**Interfaces:**
- Produces: `VisualSourceContext`, `set_visual_source_context(context)`, `get_visual_source_context()`, `clear_visual_source_context()`
- Consumes: no prior V2 task

- [x] **Step 1: Write failing tests**

```python
from agent.visual.source_context import (
    VisualSourceContext,
    clear_visual_source_context,
    get_visual_source_context,
    set_visual_source_context,
)


def test_source_context_round_trips_gateway_fields():
    clear_visual_source_context()
    context = VisualSourceContext(
        platform="slack",
        channel_id="D123",
        thread_id="1710000000.000100",
        user_id="U123",
        message_id="1710000000.000200",
        conversation_id="slack:D123",
    )

    token = set_visual_source_context(context)
    try:
        assert get_visual_source_context() == context
    finally:
        clear_visual_source_context(token)

    assert get_visual_source_context() is None
```

- [x] **Step 2: Run red test**

Run:

```bash
/Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/test_source_context.py -q
```

Expected: import or attribute failure.

- [x] **Step 3: Implement context carrier**

Add a frozen dataclass and a `contextvars.ContextVar` in `agent/visual/source_context.py`.

Required behavior:

- empty strings normalize to `None`;
- `platform` lowercases;
- `clear_visual_source_context(token)` resets with token;
- `clear_visual_source_context()` clears unconditionally.

- [x] **Step 4: Run green test**

Run the same pytest command. Expected: pass.

- [x] **Step 5: Self-evaluate**

Add a short note under `## Phase A Self-Evaluation` in this plan:

```markdown
- A1 evidence: source context round-trip test passes.
- Risk: context only exists in-process until gateway wiring lands.
```

### Task A2: Ledger Request Source Metadata

**Files:**
- Modify: `agent/visual/tracking.py`
- Modify: `agent/visual/attempt_ledger.py`
- Test: `tests/visual/test_attempt_ledger.py`
- Test: `tests/visual/test_source_context.py`

**Interfaces:**
- Consumes: `get_visual_source_context()`
- Produces: request rows populated with `platform`, `channel_id`, `thread_id`, `user_id`, and `conversation_id`

- [x] **Step 1: Write failing test**

Add a test that sets `VisualSourceContext`, calls `record_visual_generation_attempt()` with a successful fake payload, then reads the request row and asserts source fields are populated.

Expected assertions:

```python
assert request["platform"] == "slack"
assert request["channel_id"] == "D123"
assert request["thread_id"] == "1710000000.000100"
assert request["user_id"] == "U123"
assert request["conversation_id"] == "slack:D123"
```

- [x] **Step 2: Run red test**

Expected: fields are `None`.

- [x] **Step 3: Implement tracking integration**

In `agent/visual/tracking.py`, when recording a new request, read `get_visual_source_context()` and pass source fields into `ledger.record_request()`.

Do not mutate existing explicit `request_id` behavior; if a request already exists, update status only.

- [x] **Step 4: Run green tests**

Run:

```bash
/Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/test_source_context.py tests/visual/test_attempt_ledger.py -q
```

- [x] **Step 5: Self-evaluate**

Add:

```markdown
- A2 evidence: request rows created under visual tracking include source metadata.
- Risk: gateway still needs to set the context around real turns.
```

### Task A3: Gateway Source Context Wiring

**Files:**
- Modify: `gateway/run.py`
- Test: `tests/gateway/test_media_extraction.py` or a focused gateway source-context test

**Interfaces:**
- Consumes: `set_visual_source_context()`
- Produces: source context active while the agent/tool turn processes a platform event

- [x] **Step 1: Write failing gateway test**

Create a fake Slack message event with `platform="slack"`, `chat_id="D123"`, `thread_id`, `user_id`, and `message_id`. Patch `record_visual_generation_attempt()` or a small hook to assert `get_visual_source_context()` returns those values during the turn.

- [x] **Step 2: Run red test**

Expected: context is `None`.

- [x] **Step 3: Implement gateway context scope**

Wrap the message handling section that invokes the agent with:

```python
token = set_visual_source_context(VisualSourceContext.from_gateway_event(event))
try:
    ...
finally:
    clear_visual_source_context(token)
```

Do not leak context across concurrent sessions.

- [x] **Step 4: Run green tests**

Run:

```bash
/Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/gateway/test_media_extraction.py tests/visual/test_source_context.py -q
```

- [x] **Step 5: Self-evaluate**

Add:

```markdown
- A3 evidence: gateway turn sets and clears source context.
- Risk: live proof still needs source metadata enforcement.
```

### Task A4: Live Proof Requires Source Metadata

**Files:**
- Modify: `agent/visual/live_proof.py`
- Modify: `scripts/visual_agent_live_proof.py`
- Test: `tests/visual/test_live_proof.py`

**Interfaces:**
- Consumes: `visual_requests` source metadata
- Produces: missing key `missing_request_source_metadata`

- [x] **Step 1: Write failing tests**

Add one passing fixture with Slack source metadata and one failing fixture where deliveries join artifacts but request source fields are empty.

Expected failure:

```python
assert proof.success is False
assert "missing_request_source_metadata" in proof.missing
```

- [x] **Step 2: Run red tests**

Expected: current proof passes without source metadata.

- [x] **Step 3: Implement proof check**

Join `visual_requests` in `_fetch_sent_delivery_rows()` and expose:

- `request_platform`;
- `request_channel_id`;
- `request_thread_id`;
- `request_user_id`;
- `request_conversation_id`.

Fail when `require_source_metadata=True` and required fields are missing.

- [x] **Step 4: Preserve compatibility**

Add CLI option:

```text
--no-require-source-metadata
```

Default should require source metadata after Task A3 is merged.

- [x] **Step 5: Run green tests**

Run:

```bash
/Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/test_live_proof.py tests/visual/test_live_proof_cli.py -q
```

- [x] **Step 6: Self-evaluate**

Add:

```markdown
- A4 evidence: live proof fails when delivery exists but request source metadata is missing.
- Risk: existing historical rows need compatibility flag for audits before A3.
```

## Phase A Self-Evaluation

- A1 evidence: source context round-trip and normalization tests pass with `rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/test_source_context.py -q`.
- Risk: context only exists in-process until ledger and gateway wiring land.
- A2 evidence: source metadata and `message_id` are written to request rows; focused tests pass with `rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/test_source_context.py tests/visual/test_attempt_ledger.py -q`.
- Risk: gateway still needs to set the context around real turns.
- A3 evidence: gateway handler sets source context during `_run_agent` and clears it afterward; focused tests pass with `rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/gateway/test_visual_source_context.py tests/visual/test_source_context.py -q`.
- Risk: live proof still needs source metadata enforcement.
- A4 evidence: live proof joins request source metadata, fails missing source metadata by default, and supports `--no-require-source-metadata` for historical rows; focused tests pass with `rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/test_live_proof.py tests/visual/test_live_proof_cli.py -q`.
- Risk: historical deliveries before A3 need the compatibility flag when audited.
- Gate A evidence: `rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/test_source_context.py tests/visual/test_attempt_ledger.py tests/visual/test_live_proof.py tests/visual/test_live_proof_cli.py tests/gateway/test_visual_source_context.py -q` passes; full `tests/visual` also passes.
- Self-review: A3 relies on gateway `_run_agent` preserving contextvars into its executor; current implementation uses `_run_in_executor_with_context`, so visual tools should read the source context during real agent turns.

---

## Phase B: Self-Scoring

Goal: produce automatic reward signals before changing delivery behavior.

### Task B1: Reward Signal Model

**Files:**
- Create: `agent/visual/agent_mode/reward.py`
- Test: `tests/visual/agent_mode/test_reward.py`

**Interfaces:**
- Produces: `VisualReward`, `score_visual_outcome(evidence: dict) -> VisualReward`
- Consumes: artifact validity, delivery status, score components, feedback polarity

- [x] **Step 1: Write failing tests**

```python
from agent.visual.agent_mode.reward import score_visual_outcome


def test_reward_separates_provider_and_preference_tracks():
    reward = score_visual_outcome({
        "artifact_valid": True,
        "delivered": True,
        "provider_error_type": None,
        "feedback_polarity": -1.0,
        "composition_score": 0.8,
    })

    assert reward.provider_health == 1.0
    assert reward.preference_score < 0.5
    assert reward.overall_score < 1.0
```

- [x] **Step 2: Run red test**

Expected: module missing.

- [x] **Step 3: Implement reward model**

Reward fields:

- `provider_health: float`
- `artifact_quality: float`
- `delivery_health: float`
- `preference_score: float`
- `overall_score: float`
- `confidence: float`
- `components: dict[str, float]`

Clamp all scores to `[0.0, 1.0]`.

- [x] **Step 4: Run green tests**

Run:

```bash
/Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/agent_mode/test_reward.py -q
```

- [x] **Step 5: Self-evaluate**

Add:

```markdown
- B1 evidence: reward model separates provider health from user preference.
- Risk: no behavior changes until rewards are recorded and calibrated.
```

### Task B2: Record Reward To Strategy Store

**Files:**
- Modify: `agent/visual/agent_mode/learning.py`
- Test: `tests/visual/agent_mode/test_learning.py`

**Interfaces:**
- Consumes: `VisualReward`
- Produces: safe evidence keys for provider, strategy, and reward components

- [x] **Step 1: Write failing test**

Record an outcome with reward components and assert `top_strategies()` returns safe evidence without raw prompt text.

- [x] **Step 2: Run red test**

Expected: reward components are dropped or unavailable.

- [x] **Step 3: Implement safe reward evidence**

Allow compact keys:

- `provider_health`
- `artifact_quality`
- `delivery_health`
- `preference_score`
- `overall_score`
- `confidence`

Do not allow `prompt`, `raw_text`, `reference_image`, or provider raw output.

- [x] **Step 4: Run green tests**

Run:

```bash
/Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/agent_mode/test_learning.py -q
```

- [x] **Step 5: Self-evaluate**

Add:

```markdown
- B2 evidence: strategy store records compact reward evidence only.
- Risk: reward aggregation still needs runtime hook.
```

### Task B3: Shadow Score Visual Packages

**Files:**
- Modify: `tools/visual_agent_tool.py`
- Modify: `agent/visual/ranker.py`
- Test: `tests/tools/test_visual_agent_tool.py`
- Test: `tests/visual/test_ranker.py`

**Interfaces:**
- Consumes: `score_visual_outcome()`
- Produces: package `delivery_metadata["reward_trace"]`

- [x] **Step 1: Write failing test**

Patch image/video generation to return selected artifacts and assert returned package includes:

```python
assert "reward_trace" in payload["delivery_metadata"]
assert payload["delivery_metadata"]["reward_trace"]["mode"] == "shadow"
```

- [x] **Step 2: Run red test**

Expected: key missing.

- [x] **Step 3: Implement shadow scoring**

After assembling the package, compute reward trace from:

- image stage success;
- video stage success;
- selected artifacts;
- delivery readiness;
- confidence/ranking info already available.

Do not change delivery decisions in this task.

- [x] **Step 4: Run green tests**

Run:

```bash
/Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/tools/test_visual_agent_tool.py tests/visual/test_ranker.py -q
```

- [x] **Step 5: Self-evaluate**

Add:

```markdown
- B3 evidence: package metadata includes shadow reward trace.
- Risk: reward values need calibration before driving autonomy.
```

## Phase B Self-Evaluation

- B1 evidence: reward model separates provider health, artifact quality, delivery health, and preference score; focused tests pass with `rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/agent_mode/test_reward.py -q`.
- Risk: reward values are deterministic heuristics, not calibrated aesthetic truth.
- B2 evidence: strategy store records compact reward evidence and drops prompt/raw/reference fields; focused tests pass with `rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/agent_mode/test_learning.py -q`.
- Risk: strategy aggregation still uses EWMA on one scalar plus latest safe evidence.
- B3 evidence: visual package metadata includes `delivery_metadata.reward_trace` in shadow mode; focused tests pass with `rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/tools/test_visual_agent_tool.py tests/visual/test_ranker.py -q`.
- Risk: reward trace is recorded but does not yet change selection or repair behavior by design.
- Gate B evidence: `rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/agent_mode/test_reward.py tests/visual/agent_mode/test_learning.py tests/tools/test_visual_agent_tool.py tests/visual/test_ranker.py -q` passes; full `tests/visual` also passes.
- Self-review: B3 stores reward trace in package metadata only. It does not alter selection, delivery, or repair policy until calibration and bounded repair gates exist.

---

## Phase C: Bounded Repair

Goal: retry or reframe failed visual stages within explicit budgets and record why the loop stopped.

### Task C1: Repair Policy

**Files:**
- Create: `agent/visual/agent_mode/repair_policy.py`
- Test: `tests/visual/agent_mode/test_repair_policy.py`

**Interfaces:**
- Produces: `VisualRepairDecision`, `decide_visual_repair(mission, stage_result, reward_trace) -> VisualRepairDecision`
- Consumes: mission autonomy level, failure type, confidence, attempt budget

- [x] **Step 1: Write failing tests**

```python
def test_repair_policy_retries_retryable_qc_failure_with_budget():
    decision = decide_visual_repair(
        mission={"autonomy_level": 3, "repair_budget": 1},
        stage_result={"success": False, "error_type": "qc_failed"},
        reward_trace={"confidence": 0.4},
    )

    assert decision.action == "retry"
    assert decision.reason == "retryable_qc_failure"
```

Also test content moderation and exhausted budget:

```python
assert decision.action == "stop"
assert decision.reason in {"content_moderation", "repair_budget_exhausted"}
```

- [x] **Step 2: Run red tests**

Expected: module missing.

- [x] **Step 3: Implement policy**

Allowed actions:

- `retry`
- `reframe`
- `ask_user`
- `stop`

Hard stop on content moderation unless a safe reframe is explicitly allowed.

- [x] **Step 4: Run green tests**

Run:

```bash
/Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/agent_mode/test_repair_policy.py -q
```

- [x] **Step 5: Self-evaluate**

Add:

```markdown
- C1 evidence: repair policy is bounded and classifies stop reasons.
- Risk: policy is not wired to generation loop yet.
```

### Task C2: Wire Repair Trace Into Visual Agent Tool

**Files:**
- Modify: `tools/visual_agent_tool.py`
- Test: `tests/tools/test_visual_agent_tool.py`

**Interfaces:**
- Consumes: `decide_visual_repair()`
- Produces: package keys `repair_trace`, `repair_attempt_count`, `stop_reasons`

- [x] **Step 1: Write failing test**

Patch first image stage to fail with `qc_failed`, second stage to succeed, and assert:

```python
assert payload["package_status"] == "success"
assert payload["delivery_metadata"]["repair_trace"][0]["action"] == "retry"
assert payload["delivery_metadata"]["repair_attempt_count"] == 1
```

- [x] **Step 2: Run red test**

Expected: no retry or no trace.

- [x] **Step 3: Implement bounded retry**

Only enable repair when `mission.autonomy_level >= 3`. Respect `repair_budget` default `1`, max `2`.

Do not retry content moderation failures in this task.

- [x] **Step 4: Run green tests**

Run:

```bash
/Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/tools/test_visual_agent_tool.py tests/visual/agent_mode/test_repair_policy.py -q
```

- [x] **Step 5: Self-evaluate**

Add:

```markdown
- C2 evidence: visual agent records repair trace and bounded retries.
- Risk: live provider retries may need conservative defaults after smoke.
```

## Phase C Self-Evaluation

- C1 evidence: repair policy classifies retry, content moderation stop, exhausted budget, and autonomy-too-low cases; focused tests pass with `rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/agent_mode/test_repair_policy.py -q`.
- Risk: policy reasons are intentionally conservative and may need more provider-specific categories after live data.
- C2 evidence: visual agent retries one `qc_failed` image stage when `autonomy_level >= 3`, records `delivery_metadata.repair_trace`, and exposes `repair_attempt_count`; focused tests pass with `rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/tools/test_visual_agent_tool.py tests/visual/agent_mode/test_repair_policy.py -q`.
- Risk: live provider retry smoke is still needed before raising default autonomy beyond L2.
- Gate C evidence: `rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/agent_mode/test_repair_policy.py tests/tools/test_visual_agent_tool.py -q` passes; full `tests/visual` also passes.
- Self-review: repair remains bounded by policy and only auto-runs at L3+, so existing L2 natural visual package requests keep their prior no-retry behavior.

---

## Phase D: Operator Reporting

Goal: provide a compact report without exposing private prompts or media.

### Task D1: Visual Agent Report Script

**Files:**
- Create: `scripts/visual_agent_report.py`
- Test: `tests/visual/test_visual_agent_report.py`

**Interfaces:**
- Consumes: `visual_requests`, `visual_attempts`, `visual_artifacts`, `visual_deliveries`, strategy store
- Produces: JSON summary with health counts and top compact strategy outcomes

- [x] **Step 1: Write failing test**

Create a temp ledger with:

- one successful image;
- one successful video;
- one provider error;
- one delivery;
- one duplicate delivery fixture.

Assert report output includes:

```python
assert payload["delivery"]["sent"] == 1
assert payload["artifacts"]["image"] == 1
assert payload["provider_errors"]["content_moderation"] == 1
assert "raw_prompts" not in payload
```

- [x] **Step 2: Run red test**

Expected: script missing.

- [x] **Step 3: Implement report**

Support:

```bash
scripts/visual_agent_report.py --ledger-path <path> --since-local-date 2026-06-20 --timezone Asia/Taipei --json
```

Report sections:

- `requests`
- `attempts`
- `artifacts`
- `delivery`
- `provider_errors`
- `source_metadata`
- `strategy_atoms`

- [x] **Step 4: Run green tests**

Run:

```bash
/Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/test_visual_agent_report.py -q
```

- [x] **Step 5: Self-evaluate**

Add:

```markdown
- D1 evidence: report summarizes visual health without raw prompts.
- Risk: report is JSON-first; UI can come later.
```

## Phase D Self-Evaluation

- D1 evidence: `scripts/visual_agent_report.py` summarizes request, attempt, artifact, delivery, provider error, source metadata, and strategy atom counts without selecting raw prompt columns; focused tests pass with `rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/test_visual_agent_report.py -q`.
- Risk: report is JSON-first and aggregate-only; richer operator UI can come later.
- Gate D evidence: focused report tests pass. Live runtime report should be run after the next visual package so the current ledger schema has source metadata populated.

---

## Verification Gates

### Gate A: Source Lineage

Run:

```bash
/Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/test_source_context.py tests/visual/test_attempt_ledger.py tests/visual/test_live_proof.py -q
```

Required evidence:

- source context round-trips;
- visual request rows contain source metadata;
- live proof fails when source metadata is required but absent.

### Gate B: Self-Scoring

Run:

```bash
/Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/agent_mode/test_reward.py tests/visual/agent_mode/test_learning.py tests/tools/test_visual_agent_tool.py -q
```

Required evidence:

- provider health and user preference are separate;
- compact reward evidence is recorded;
- package metadata contains shadow reward trace.

### Gate C: Bounded Repair

Run:

```bash
/Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/agent_mode/test_repair_policy.py tests/tools/test_visual_agent_tool.py -q
```

Required evidence:

- retryable QC failures can be retried under L3;
- moderation and exhausted budgets stop with explicit reasons;
- repair trace is returned in package metadata.

### Gate D: Operator Report

Run:

```bash
/Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/test_visual_agent_report.py -q
/Users/simon/.hermes/hermes-agent/venv/bin/python scripts/visual_agent_report.py --since-local-date 2026-06-20 --timezone Asia/Taipei --json
```

Required evidence:

- report emits provider, artifact, delivery, source metadata, and strategy summaries;
- report does not include raw prompts or generated media contents.

### Gate E: Live V2 Proof

Run after a safe Slack visual package request:

```bash
/Users/simon/.hermes/hermes-agent/venv/bin/python scripts/visual_agent_live_proof.py \
  --ledger-path /Users/simon/.hermes/visual/attempt_ledger.sqlite3 \
  --since-local-date <YYYY-MM-DD> \
  --timezone Asia/Taipei \
  --platform slack \
  --destination-id <slack_chat_id> \
  --json
```

Required evidence:

- `success: true`;
- at least one image and one video delivery;
- no missing artifact join;
- no duplicate artifact delivery;
- no missing request source metadata;
- source metadata matches Slack destination and thread where available.

## Post-Implementation Live Validation

2026-06-20 local-date runtime ledger check:

```bash
/Users/simon/.hermes/hermes-agent/venv/bin/python scripts/visual_agent_report.py \
  --ledger-path /Users/simon/.hermes/visual/attempt_ledger.sqlite3 \
  --since-local-date 2026-06-20 \
  --timezone Asia/Taipei \
  --json
```

Observed aggregate result:

- requests: 52 total, 50 completed, 2 failed;
- artifacts: 41 images, 9 videos;
- deliveries: 2 sent, 0 duplicate artifact delivery;
- provider errors: 1 connection error, 1 provider error;
- source metadata: 52 of 52 current-day requests missing full request source metadata.

Historical-delivery proof command:

```bash
/Users/simon/.hermes/hermes-agent/venv/bin/python scripts/visual_agent_live_proof.py \
  --ledger-path /Users/simon/.hermes/visual/attempt_ledger.sqlite3 \
  --since-local-date 2026-06-20 \
  --timezone Asia/Taipei \
  --platform slack \
  --no-require-source-metadata \
  --json
```

Observed result:

- `success: true` for historical delivery mode;
- artifact kind counts: 1 image, 1 video;
- missing artifact join: 0;
- duplicate artifact delivery: 0;
- missing request source metadata count: 2.

Strict source-metadata proof correctly fails on the same historical rows with
`missing_request_source_metadata`. This is expected until the deployed runtime
records new Phase A source metadata for fresh Slack visual requests.

## Documentation Updates

After all gates pass:

- update `docs/visual-agent-mode-v2-goal.md` with current implementation status;
- update this plan's execution status table;
- record live proof command and result;
- record known evidence boundaries honestly.

## Final Self-Review Checklist

- [x] Every V2 completion criterion maps to a task and gate.
- [x] No task requires raw private prompt storage.
- [x] Provider health, preference, and delivery health remain separate.
- [x] Repair loops are bounded.
- [x] Live proof can be rerun using local date and timezone.
- [x] Documentation states evidence boundaries instead of overstating proof.
