# Raphael Production Control Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Raphael's split simulated and production paths with one origin-aware, runtime-configured, evidence-enforcing control kernel and prove it through production-path acceptance before review and PR.

**Architecture:** Add small origin/runtime, kernel, and finalization modules around the existing Raphael data types. Migrate the standalone mission state into `RaphaelState`, make conversation and visual adapters consume one serialized turn decision, and make readiness replay the same production adapters. Keep the visual agent as the execution surface and preserve approval gates for durable learning.

**Tech Stack:** Python 3.11, dataclasses, JSON state, pytest, Ruff, Hermes plugin hooks, launchd runtime, GitHub CLI, Hermes CLI.

## Global Constraints

- Use TDD for every behavior change: observe a focused failure before production edits.
- Only foreground turns may mutate the foreground mission.
- Provider/model truth comes from effective runtime configuration, never a versioned hard-coded default.
- Do not deploy the feature branch as the supervised live gateway.
- Keep generated evidence and private runtime traces out of Git.
- Push only to `origin`; do not create upstream issues or PRs.
- Do not create a PR until Codex self-review and independent Grok review both pass.
- The final PR base must be the live `origin` default branch and must not be named `main`; conflicting evidence blocks PR creation.

---

### Task 1: Turn Origin And Runtime Contract

**Files:**
- Create: `agent/raphael/runtime_contract.py`
- Modify: `agent/turn_context.py:93-116,119-520`
- Modify: `plugins/raphael/__init__.py:129-142`
- Test: `tests/agent/test_raphael_runtime_contract.py`
- Test: `tests/agent/test_raphael_turn_origin.py`

**Interfaces:**
- Consumes: effective config mappings and live agent provider/model/api-mode attributes.
- Produces: `RaphaelTurnOrigin`, `RaphaelRuntimeContract`, `resolve_raphael_turn_origin()`, `resolve_raphael_runtime_contract()`, plus `TurnContext.raphael_origin` and `TurnContext.raphael_runtime_contract`.

- [ ] **Step 1: Write failing origin and runtime-resolution tests**

```python
def test_background_write_origin_maps_to_background_review():
    assert resolve_raphael_turn_origin(write_origin="background_review") is RaphaelTurnOrigin.BACKGROUND_REVIEW

def test_live_agent_values_override_stale_config_model():
    contract = resolve_raphael_runtime_contract(
        {"model": {"default": "gpt-5.5", "provider": "openai-codex"}},
        live_provider="openai-codex",
        live_model="gpt-5.6-terra",
        live_api_mode="codex_app_server",
    )
    assert contract.base_model == "gpt-5.6-terra"
    assert contract.source == "live_agent"
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest tests/agent/test_raphael_runtime_contract.py tests/agent/test_raphael_turn_origin.py -q`

Expected: collection fails because `agent.raphael.runtime_contract` does not exist.

- [ ] **Step 3: Implement the pure contracts and propagate hook fields**

```python
class RaphaelTurnOrigin(str, Enum):
    FOREGROUND = "foreground"
    BACKGROUND_REVIEW = "background_review"
    CRON = "cron"
    SUBAGENT = "subagent"
    REPLAY = "replay"

@dataclass(frozen=True)
class RaphaelRuntimeContract:
    base_provider: str
    base_model: str
    base_api_mode: str
    visual_planner_provider: str | None = None
    visual_planner_model: str | None = None
    image_provider: str | None = None
    image_model: str | None = None
    video_provider: str | None = None
    video_model: str | None = None
    source: str = "effective_config"
```

Add the serialized origin and runtime contract to `pre_llm_call` hook kwargs. The Raphael plugin forwards them to observation without inferring origin from text.

- [ ] **Step 4: Verify GREEN and regression scope**

Run: `python -m pytest tests/agent/test_raphael_runtime_contract.py tests/agent/test_raphael_turn_origin.py tests/plugins/test_raphael_plugin.py tests/run_agent/test_background_review.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add agent/raphael/runtime_contract.py agent/turn_context.py plugins/raphael/__init__.py tests/agent/test_raphael_runtime_contract.py tests/agent/test_raphael_turn_origin.py
git commit -m "feat: propagate Raphael turn origin and runtime contract"
```

### Task 2: Canonical Mission State And Legacy Migration

**Files:**
- Modify: `agent/raphael/models.py:314-521`
- Modify: `agent/raphael/state.py:99-421`
- Modify: `agent/raphael/mission.py:52-316`
- Modify: `agent/raphael/observer.py:401-480`
- Test: `tests/agent/test_raphael_mission.py`
- Test: `tests/agent/test_raphael_state.py`
- Test: `tests/agent/test_raphael_observer.py`

**Interfaces:**
- Consumes: `RaphaelTurnOrigin`, current `RaphaelState`, and optional legacy `RaphaelMissionState` JSON.
- Produces: canonical `read_active_mission()`, `write_active_mission()`, and `migrate_legacy_mission_state()`; no new production writes to the legacy file.

- [ ] **Step 1: Add failing state-isolation and migration tests**

```python
def test_background_turn_cannot_create_foreground_mission(tmp_path):
    result = update_active_mission_for_turn(
        origin=RaphaelTurnOrigin.BACKGROUND_REVIEW,
        appraisal=_appraisal("Review the conversation above"),
        strategies=_strategies(),
    )
    assert result is None
    assert read_state().active_mission is None

def test_legacy_mission_is_imported_once_then_not_rewritten(tmp_path):
    write_legacy_fixture(_legacy_mission("repair gateway"))
    migrated = read_active_mission()
    assert migrated.goal == "repair gateway"
    assert latest_migration_event().details["source"] == "raphael_mission_v1"
    assert not legacy_mission_path().exists()
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/agent/test_raphael_mission.py tests/agent/test_raphael_state.py tests/agent/test_raphael_observer.py -q`

Expected: new APIs are missing and background observation still creates an empty-state mission.

- [ ] **Step 3: Implement canonical state and one-time migration**

Extend `RaphaelMission` with backward-compatible defaults for `proof_status`, `last_user_request`, `created_at`, and migration metadata. Perform state read-modify-write under `raphael_state_lock()`. Restrict mutation to `FOREGROUND`; observation becomes read-only for every other origin.

- [ ] **Step 4: Verify GREEN and prove the reported live bug**

Run: `python -m pytest tests/agent/test_raphael_mission.py tests/agent/test_raphael_state.py tests/agent/test_raphael_observer.py tests/plugins/test_raphael_plugin.py -q`

Expected: background empty-state and active-state isolation tests pass; legacy round-trip tests pass.

- [ ] **Step 5: Commit**

```bash
git add agent/raphael/models.py agent/raphael/state.py agent/raphael/mission.py agent/raphael/observer.py tests/agent/test_raphael_mission.py tests/agent/test_raphael_state.py tests/agent/test_raphael_observer.py tests/plugins/test_raphael_plugin.py
git commit -m "fix: unify Raphael foreground mission state"
```

### Task 3: Canonical Turn Decision Kernel

**Files:**
- Create: `agent/raphael/kernel.py`
- Modify: `agent/raphael/models.py:458-521`
- Modify: `agent/raphael/control.py:1-1053`
- Modify: `agent/raphael/router.py:1-514`
- Modify: `agent/raphael/state.py:304-421`
- Modify: `agent/turn_context.py:93-520`
- Modify: `agent/conversation_loop.py:523-810`
- Test: `tests/agent/test_raphael_kernel.py`
- Test: `tests/agent/test_raphael_control.py`
- Test: `tests/agent/test_raphael_router.py`
- Test: `tests/agent/test_direct_visual_handoff_runtime.py`

**Interfaces:**
- Consumes: canonical mission, runtime contract, user message, attachments, and conversation history.
- Produces: `RaphaelTurnDecision`, `prepare_raphael_turn()`, `serialize_raphael_turn_decision()`, and compatibility facades for existing control/router callers.

- [ ] **Step 1: Write failing single-decision production tests**

```python
def test_prepare_turn_records_one_decision_consumed_by_conversation_loop():
    context = build_turn_context_for("請修復 bug 並跑測試")
    assert context.raphael_decision.mode == "tool_task"
    assert read_state().last_decision.turn_id == context.turn_id

def test_router_and_control_facades_return_same_route():
    decision = decide_raphael_turn(_context("請產一張圖"))
    assert build_raphael_control_decision("請產一張圖").mode == decision.mode
    assert route_raphael_message("請產一張圖").kind == decision.route.kind
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/agent/test_raphael_kernel.py tests/agent/test_raphael_control.py tests/agent/test_raphael_router.py tests/agent/test_direct_visual_handoff_runtime.py -q`

Expected: kernel APIs and `TurnContext.raphael_decision` are absent.

- [ ] **Step 3: Implement kernel and turn-context integration**

```python
@dataclass(frozen=True)
class RaphaelTurnDecision:
    turn_id: str
    origin: RaphaelTurnOrigin
    mission_id: str | None
    mode: str
    target_artifact: str
    route: RaphaelRouteDecision
    required_proofs: tuple[str, ...]
    completion_policy: str
    blockers: tuple[str, ...]
    next_action: str
    clarification_question: str | None
    confidence: float
    runtime_contract: RaphaelRuntimeContract
```

Move classification ownership into `kernel.py`. Keep `control.py` and `router.py` as temporary compatibility facades with usage counters and an explicit removal comment. `conversation_loop` receives the decision from `TurnContext`; it does not recompute it.

- [ ] **Step 4: Verify GREEN and run routing regressions**

Run: `python -m pytest tests/agent/test_raphael_kernel.py tests/agent/test_raphael_control.py tests/agent/test_raphael_router.py tests/agent/test_direct_visual_handoff_runtime.py tests/visual/test_agent_mode_handoff.py -q`

Expected: one decision id is visible across context, state, and direct-handoff metadata.

- [ ] **Step 5: Commit**

```bash
git add agent/raphael/kernel.py agent/raphael/models.py agent/raphael/control.py agent/raphael/router.py agent/raphael/state.py agent/turn_context.py agent/conversation_loop.py tests/agent/test_raphael_kernel.py tests/agent/test_raphael_control.py tests/agent/test_raphael_router.py tests/agent/test_direct_visual_handoff_runtime.py tests/visual/test_agent_mode_handoff.py
git commit -m "feat: add canonical Raphael turn decision kernel"
```

### Task 4: Visual Adapter And Structured Evidence

**Files:**
- Modify: `agent/raphael/proof.py:1-434`
- Modify: `agent/visual/agent_mode/handoff.py:38-1160`
- Modify: `agent/conversation_loop.py:523-670`
- Test: `tests/agent/test_raphael_proof.py`
- Test: `tests/visual/test_agent_mode_handoff.py`
- Test: `tests/agent/test_direct_visual_handoff_runtime.py`

**Interfaces:**
- Consumes: the canonical `RaphaelTurnDecision` and visual tool payload.
- Produces: `RaphaelEvidenceEvent`, `evidence_events_from_visual_payload()`, and decision-linked visual gate results.

- [ ] **Step 1: Write failing evidence provenance tests**

```python
def test_visual_handoff_reuses_turn_decision_instead_of_recomputing():
    handoff = build_direct_visual_agent_handoff(agent, request, decision=decision)
    assert handoff["raphael_decision"]["turn_id"] == decision.turn_id
    assert kernel_call_count == 0

def test_stale_selected_artifact_cannot_create_passing_evidence_event():
    events = evidence_events_from_visual_payload(_stale_payload(), decision)
    assert "stale_artifact_guard" not in {event.proof_type for event in events if event.status == "passed"}
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/agent/test_raphael_proof.py tests/visual/test_agent_mode_handoff.py tests/agent/test_direct_visual_handoff_runtime.py -q`

Expected: handoff has no decision parameter and proof events are not structured.

- [ ] **Step 3: Implement the visual adapter and evidence conversion**

```python
@dataclass(frozen=True)
class RaphaelEvidenceEvent:
    evidence_id: str
    mission_id: str | None
    turn_id: str
    proof_type: str
    source: str
    status: str
    command: str | None
    artifact_id: str | None
    provider: str | None
    observed_at: datetime
    payload_digest: str
```

Replace `_evaluate_raphael_evidence_gate()`'s ad-hoc booleans with validated events while preserving the existing blocked-delivery behavior and privacy redaction.

- [ ] **Step 4: Verify GREEN and visual regression scope**

Run: `python -m pytest tests/agent/test_raphael_proof.py tests/visual/test_agent_mode_handoff.py tests/agent/test_direct_visual_handoff_runtime.py tests/tools/test_visual_agent_tool.py -q`

Expected: selected, fresh, independently reviewed artifacts pass; stale, duplicate, rejected, and unselected artifacts fail closed.

- [ ] **Step 5: Commit**

```bash
git add agent/raphael/proof.py agent/visual/agent_mode/handoff.py agent/conversation_loop.py tests/agent/test_raphael_proof.py tests/visual/test_agent_mode_handoff.py tests/agent/test_direct_visual_handoff_runtime.py
git commit -m "feat: attach structured evidence to Raphael visual handoff"
```

### Task 5: Real Finalizer Proof Enforcement

**Files:**
- Create: `agent/raphael/finalization.py`
- Modify: `agent/turn_finalizer.py:58-690`
- Modify: `agent/codex_runtime.py:315-620`
- Modify: `agent/raphael/proof.py:122-434`
- Create: `tests/agent/test_raphael_finalization.py`
- Test: `tests/agent/test_raphael_turn_finalizer.py`
- Create: `tests/agent/test_codex_raphael_finalization.py`

**Interfaces:**
- Consumes: canonical decision, final response, tool messages, and evidence events.
- Produces: `RaphaelFinalizationResult` and `enforce_raphael_completion()` used by normal and Codex app-server finalizers.

- [ ] **Step 1: Write failing production finalizer tests**

```python
def test_tool_task_completion_is_blocked_without_focused_test_evidence():
    result = enforce_raphael_completion(
        decision=_tool_task_decision(required=("focused_tests",)),
        final_response="完成了，測試都通過。",
        messages=(),
    )
    assert result.status == "blocked_unverified_completion"
    assert "focused_tests" in result.missing_proofs

def test_codex_runtime_uses_same_completion_gate():
    result = run_codex_turn_with_unverified_completion()
    assert "尚缺驗證" in result["final_response"]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/agent/test_raphael_finalization.py tests/agent/test_raphael_turn_finalizer.py tests/agent/test_codex_raphael_finalization.py -q`

Expected: unsupported completion is currently returned unchanged and Codex path bypasses the gate.

- [ ] **Step 3: Implement shared finalization enforcement**

```python
@dataclass(frozen=True)
class RaphaelFinalizationResult:
    status: str
    final_response: str
    required_proofs: tuple[str, ...]
    available_proofs: tuple[str, ...]
    missing_proofs: tuple[str, ...]
    next_action: str
```

Invoke the gate before output transforms and persistence in both normal and Codex paths. Informational responses remain unchanged. Mutation/runtime/release completion language is blocked only when its canonical decision requires missing proofs.

- [ ] **Step 4: Verify GREEN and finalizer regressions**

Run: `python -m pytest tests/agent/test_raphael_finalization.py tests/agent/test_raphael_turn_finalizer.py tests/agent/test_codex_raphael_finalization.py tests/agent/test_raphael_proof.py tests/agent/test_turn_finalizer.py -q`

Expected: both transports enforce the same proof policy and existing non-Raphael output transforms remain green.

- [ ] **Step 5: Commit**

```bash
git add agent/raphael/finalization.py agent/turn_finalizer.py agent/codex_runtime.py agent/raphael/proof.py tests/agent/test_raphael_finalization.py tests/agent/test_raphael_turn_finalizer.py tests/agent/test_codex_raphael_finalization.py tests/agent/test_turn_finalizer.py
git commit -m "fix: enforce Raphael proof gate in real finalizers"
```

### Task 6: Production Replay Readiness And Dynamic Model Boundary

**Files:**
- Modify: `agent/raphael/public_readiness.py:1-715`
- Modify: `agent/raphael/release_candidate.py:1-651`
- Modify: `hermes_cli/raphael_cmd.py:80-3730`
- Modify: `docs/raphael-llm-public-slice.md`
- Modify: `docs/raphael-release-slice-audit.md`
- Test: `tests/agent/test_raphael_public_readiness.py`
- Test: `tests/agent/test_raphael_release_candidate.py`
- Test: `tests/hermes_cli/test_raphael_cmd.py`

**Interfaces:**
- Consumes: production kernel/finalizer replay output and effective runtime contract.
- Produces: readiness cases with `producer=production_replay`, capability-based provider constraints, and no exact stale model pin.

- [ ] **Step 1: Write failing readiness provenance tests**

```python
def test_readiness_rejects_detached_simulator_provenance():
    report = build_public_llm_slice_readiness(_evidence(producer="deterministic_router"))
    assert report.status == "blocked_readiness_evidence_invalid"

def test_current_openai_family_model_is_not_forced_to_gpt_5_5():
    report = build_public_llm_slice_readiness(_live_smoke(model="gpt-5.6-terra", provider="openai-codex"))
    assert "llm_model_mismatch" not in report.blocking_reasons
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/agent/test_raphael_public_readiness.py tests/agent/test_raphael_release_candidate.py tests/hermes_cli/test_raphael_cmd.py -q -x`

Expected: detached simulator remains accepted and `gpt-5.6-terra` is rejected by the exact-model gate.

- [ ] **Step 3: Replace detached cases with production replay**

Run quota-free replay through the canonical kernel and shared finalizer. Rename the misleading finalizer case and require matching decision/evidence ids. Validate provider family and declared capability rather than exact versioned model.

- [ ] **Step 4: Verify GREEN and docs alignment**

Run: `python -m pytest tests/agent/test_raphael_public_readiness.py tests/agent/test_raphael_release_candidate.py tests/hermes_cli/test_raphael_cmd.py tests/scripts/test_raphael_release_docs_audit.py -q`

Expected: readiness accepts fresh production replay for the effective OpenAI-family model and still rejects stale or overbroad media claims.

- [ ] **Step 5: Commit**

```bash
git add agent/raphael/public_readiness.py agent/raphael/release_candidate.py hermes_cli/raphael_cmd.py docs/raphael-llm-public-slice.md docs/raphael-release-slice-audit.md tests/agent/test_raphael_public_readiness.py tests/agent/test_raphael_release_candidate.py tests/hermes_cli/test_raphael_cmd.py tests/scripts/test_raphael_release_docs_audit.py
git commit -m "fix: make Raphael readiness replay production control"
```

### Task 7: Outcome-Driven Learning Proposals

**Files:**
- Modify: `agent/raphael/evolution.py:305-969`
- Modify: `agent/raphael/learning.py:1-34`
- Modify: `agent/raphael/status.py:304-676`
- Modify: `agent/turn_finalizer.py:490-660`
- Test: `tests/agent/test_raphael_evolution.py`
- Test: `tests/agent/test_raphael_learning.py`
- Test: `tests/agent/test_raphael_status.py`

**Interfaces:**
- Consumes: foreground decision/evidence/outcome records grouped by stable failure-cluster id.
- Produces: outcome-backed proposal metadata with component, owner, replay, baseline, target, promotion gate, rollback condition, and approval class.

- [ ] **Step 1: Write failing proposal-quality tests**

```python
def test_repeated_signal_without_replay_does_not_create_patch_proposal():
    proposal = build_evolution_action_proposal((_signal(), _signal()))
    assert proposal is None

def test_user_correction_plus_repro_creates_outcome_contract():
    proposal = build_evolution_action_proposal((_user_correction(), _reproduced_failure()))
    assert proposal.metadata["replay_command"]
    assert proposal.metadata["baseline_metric"]
    assert proposal.metadata["target_metric"]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/agent/test_raphael_evolution.py tests/agent/test_raphael_learning.py tests/agent/test_raphael_status.py -q -x`

Expected: vague repeated signals currently create proposals without the outcome contract.

- [ ] **Step 3: Implement cluster and promotion requirements**

Require two independent foreground occurrences or one correction plus one reproducible failure. Keep provider health, setup, aesthetic preference, and delivery clusters separate. Render baseline/target/replay information in redacted operator status.

- [ ] **Step 4: Verify GREEN and background isolation**

Run: `python -m pytest tests/agent/test_raphael_evolution.py tests/agent/test_raphael_learning.py tests/agent/test_raphael_status.py tests/agent/test_raphael_turn_finalizer.py tests/run_agent/test_background_review.py -q`

Expected: vague live proposals are suppressed; actionable proposals remain approval-gated and background turns do not change foreground state.

- [ ] **Step 5: Commit**

```bash
git add agent/raphael/evolution.py agent/raphael/learning.py agent/raphael/status.py agent/turn_finalizer.py tests/agent/test_raphael_evolution.py tests/agent/test_raphael_learning.py tests/agent/test_raphael_status.py tests/agent/test_raphael_turn_finalizer.py
git commit -m "feat: require outcome evidence for Raphael learning"
```

### Task 8: Durable Architecture Docs And Truthful Operator Status

**Files:**
- Create: `docs/raphael-mode.md`
- Modify: `docs/raphael-release-candidate.md`
- Modify: `docs/raphael-media-readiness.md`
- Modify: `docs/raphael-llm-public-slice.md`
- Modify: `docs/raphael-release-slice-audit.md`
- Modify: `plugins/raphael/__init__.py:84-127`
- Modify: `agent/raphael/status.py:49-230`
- Modify: `hermes_cli/raphael_lifecycle.py:155-305`
- Test: `tests/plugins/test_raphael_plugin.py`
- Test: `tests/agent/test_raphael_status.py`
- Test: `tests/hermes_cli/test_raphael_lifecycle.py`
- Test: `tests/scripts/test_raphael_release_docs_audit.py`

**Interfaces:**
- Consumes: canonical status snapshot, runtime contract, gateway truth snapshot, and readiness expiry.
- Produces: durable `docs/raphael-mode.md` and status output containing foreground mission, decision, proof, runtime, and degraded-state truth.

- [ ] **Step 1: Write failing status and docs tests**

```python
def test_status_never_displays_background_review_as_current_mission():
    output = render_status(_state_with_background_record_only())
    assert "Review the conversation above" not in output

def test_docs_do_not_describe_expired_evidence_as_current():
    result = audit_release_docs(now=FRESHNESS_CUTOFF)
    assert result.passed
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/plugins/test_raphael_plugin.py tests/agent/test_raphael_status.py tests/hermes_cli/test_raphael_lifecycle.py tests/scripts/test_raphael_release_docs_audit.py -q -x`

Expected: missing architecture doc and stale/current wording fail the new assertions.

- [ ] **Step 3: Implement docs and operator status**

Write the durable architecture from the approved spec in operator language. Status reads the canonical state and effective runtime snapshot, clearly labels unavailable process evidence, and never claims release freshness from Markdown prose.

- [ ] **Step 4: Verify GREEN and package inclusion**

Run: `python -m pytest tests/plugins/test_raphael_plugin.py tests/agent/test_raphael_status.py tests/hermes_cli/test_raphael_lifecycle.py tests/scripts/test_raphael_release_docs_audit.py tests/test_packaging_metadata.py -q`

Expected: architecture docs ship in the package and release docs remain claim-safe.

- [ ] **Step 5: Commit**

```bash
git add docs/raphael-mode.md docs/raphael-release-candidate.md docs/raphael-media-readiness.md docs/raphael-llm-public-slice.md docs/raphael-release-slice-audit.md plugins/raphael/__init__.py agent/raphael/status.py hermes_cli/raphael_lifecycle.py tests/plugins/test_raphael_plugin.py tests/agent/test_raphael_status.py tests/hermes_cli/test_raphael_lifecycle.py tests/scripts/test_raphael_release_docs_audit.py tests/test_packaging_metadata.py
git commit -m "docs: publish Raphael control and recovery contract"
```

### Task 9: Production Acceptance, Runtime Repair, Dual Review, And PR Gate

**Files:**
- Create: `scripts/raphael_production_path_acceptance.py`
- Create: `tests/scripts/test_raphael_production_path_acceptance.py`
- Modify: `docs/raphael-release-slice-audit.md`
- Runtime evidence only: `~/.hermes/raphael/release/` JSON artifacts, not committed.

**Interfaces:**
- Consumes: committed feature head, canonical production adapters, accepted runtime worktree, isolated gateway endpoint, and review reports.
- Produces: privacy-safe acceptance report, Codex review report, Grok review report, repaired live runtime routing, and a PR only if every gate passes.

- [ ] **Step 1: Write failing acceptance-validator tests**

```python
def test_acceptance_rejects_missing_dual_review():
    report = validate_acceptance(_report(codex_review="pass", grok_review=None))
    assert report.status == "blocked"
    assert "grok_review_missing" in report.blocking_reasons

def test_pr_gate_rejects_main_even_when_remote_reports_main_default():
    gate = evaluate_pr_target(default_branch="main")
    assert gate.allowed is False
    assert gate.reason == "default_branch_must_not_be_main"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/scripts/test_raphael_production_path_acceptance.py -q`

Expected: acceptance script and PR target gate do not exist.

- [ ] **Step 3: Implement acceptance CLI and deterministic validators**

The script runs quota-free production scenarios for conversation, tool task,
visual routing, same-artifact follow-up, provider failure classification,
missing proof, background isolation, and Codex transport parity. It records
commands, exit codes, decision ids, evidence ids, runtime contract, commits,
and artifact digests without private prompts or paths.

- [ ] **Step 4: Repair launchd routing and run isolated feature smoke**

Record current `pip show`, gateway PID/command, runtime worktree commit, and
service definition. Restart launchd from the accepted runtime worktree, then
verify the process command and stale-service warning. Start the feature gateway
on an isolated port, run text and no-quota visual-routing smokes, and stop only
the isolated process afterward.

- [ ] **Step 5: Commit acceptance tooling before review**

```bash
git add scripts/raphael_production_path_acceptance.py tests/scripts/test_raphael_production_path_acceptance.py docs/raphael-release-slice-audit.md
git commit -m "test: add Raphael production acceptance gate"
```

- [ ] **Step 6: Run full verification and Codex hostile self-review**

Run:

```bash
python -m pytest tests/agent/test_raphael_*.py tests/plugins/test_raphael_plugin.py tests/visual/test_agent_mode_handoff.py tests/run_agent/test_background_review.py tests/scripts/test_raphael_production_path_acceptance.py -q
python -m ruff check agent/raphael agent/turn_context.py agent/turn_finalizer.py agent/codex_runtime.py agent/visual/agent_mode/handoff.py plugins/raphael hermes_cli/raphael_cmd.py hermes_cli/raphael_lifecycle.py scripts/raphael_production_path_acceptance.py tests/agent/test_raphael_*.py tests/scripts/test_raphael_production_path_acceptance.py
git diff --check
python scripts/raphael_production_path_acceptance.py --output ~/.hermes/raphael/release/production-acceptance.json
```

Read the spec requirement by requirement, inspect the final diff and fresh
acceptance JSON, and write a privacy-safe Codex review report. Any critical or
important finding returns to a failing regression before proceeding.

- [ ] **Step 7: Run independent Grok review and close findings**

Send Grok the committed diff, spec, test summary, acceptance report, and
residual risks through `rtk hermes chat` using the configured Grok provider.
Require structured verdict, severity-ranked findings, requirement coverage,
and `ready_for_pr`. Fix every critical or important finding with TDD, rerun all
verification, and rerun both reviews on the new head.

- [ ] **Step 8: Verify PR target, push to origin, and create PR**

Query the live repository default branch through GitHub immediately before
publication. Continue only when the branch equals the remote default and its
name is not `main`. Push `raphael/control-kernel-hardening` to `origin`, create
the PR against that verified base, and preserve the worktree for review fixes.
