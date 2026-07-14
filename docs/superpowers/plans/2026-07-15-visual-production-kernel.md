# Visual Production Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Visual Agent a shared versioned intent contract, one-candidate default, artifact-specific QC repair, and evidence-based provider coordination without importing story-video phase machinery.

**Architecture:** Add small pure modules under `agent/visual/production_kernel`, then wire their outputs into the existing Visual Agent planner and Visual Package execution path. Existing providers, ledger, vision judge, ranker, and delivery gate remain the execution and evidence surfaces.

**Tech Stack:** Python 3.11+, dataclasses, SHA-256 canonical JSON, pytest, existing Visual Agent ledger and provider tools.

## Global Constraints

- Natural language remains the primary user interface.
- Default image candidate budget is exactly `1`.
- Default repair generation budget is exactly `1`.
- Explicit provider choice always wins.
- OpenAI Image2 and xAI Imagine do not run as a default parallel ensemble.
- Contract hash mismatch invalidates stale artifact reuse.
- Story-video phases, narration, subtitles, and rendering remain outside the kernel.

---

### Task 1: Versioned Visual Intent Contract

**Files:**
- Create: `agent/visual/production_kernel/__init__.py`
- Create: `agent/visual/production_kernel/contract.py`
- Create: `tests/visual/production_kernel/test_contract.py`

**Interfaces:**
- Produces: `VisualIntentContract`, `compile_visual_intent_contract(prompt, request_context)`, and `visual_contract_hash(contract)`.
- Consumes: plain prompt text and existing planner arguments only.

- [ ] **Step 1: Write failing contract tests**

```python
def test_contract_hash_changes_when_acceptance_criteria_change():
    first = compile_visual_intent_contract("A red bicycle in rain", {})
    second = replace(first, acceptance_criteria=("bicycle is red",))
    assert visual_contract_hash(first) != visual_contract_hash(second)

def test_contract_hash_ignores_provider_prompt_text():
    contract = compile_visual_intent_contract("A red bicycle in rain", {})
    assert "provider" not in contract.to_canonical_dict()
```

- [ ] **Step 2: Run the tests and confirm missing-module failure**

Run: `.venv/bin/pytest -q tests/visual/production_kernel/test_contract.py`

Expected: collection fails because `agent.visual.production_kernel` does not exist.

- [ ] **Step 3: Implement the immutable contract and canonical hash**

```python
@dataclass(frozen=True)
class VisualIntentContract:
    original_request: str
    primary_subject: str
    observable_action: str = ""
    focal_point: str = ""
    acceptance_criteria: tuple[str, ...] = ()
    required_details: tuple[str, ...] = ()
    forbidden_details: tuple[str, ...] = ()
    reference_roles: tuple[tuple[str, str], ...] = ()
    aspect_ratio: str = ""
    truth_mode: str = ""

    def to_canonical_dict(self) -> dict[str, object]:
        return {
            "original_request": self.original_request,
            "primary_subject": self.primary_subject,
            "observable_action": self.observable_action,
            "focal_point": self.focal_point,
            "acceptance_criteria": list(self.acceptance_criteria),
            "required_details": list(self.required_details),
            "forbidden_details": list(self.forbidden_details),
            "reference_roles": [list(item) for item in self.reference_roles],
            "aspect_ratio": self.aspect_ratio,
            "truth_mode": self.truth_mode,
        }
```

- [ ] **Step 4: Run contract tests**

Run: `.venv/bin/pytest -q tests/visual/production_kernel/test_contract.py`

Expected: all pass.

### Task 2: Blocker Classification And Bounded Repair

**Files:**
- Create: `agent/visual/production_kernel/quality.py`
- Create: `agent/visual/production_kernel/repair.py`
- Create: `tests/visual/production_kernel/test_quality.py`
- Create: `tests/visual/production_kernel/test_repair.py`

**Interfaces:**
- Consumes: current contract hash, artifact id, Visual Agent quality issues, provider failure data, and prior repair history.
- Produces: `VisualQualityDecision` and `VisualRepairPlan` with one stable strategy and `should_generate`.

- [ ] **Step 1: Write failing blocker and stale-contract tests**

```python
def test_stale_contract_blocks_delivery():
    decision = evaluate_visual_quality(contract_hash="new", artifact_contract_hash="old", quality_issues=[])
    assert decision.deliverable is False
    assert decision.blocker_codes == ("stale_contract",)

def test_reference_drift_maps_to_identity_recovery():
    plan = plan_visual_repair(("reference_identity_drift",), prior_repairs=())
    assert plan.strategy == "identity_recovery"
    assert plan.should_generate is True
```

- [ ] **Step 2: Confirm tests fail for missing interfaces**

Run: `.venv/bin/pytest -q tests/visual/production_kernel/test_quality.py tests/visual/production_kernel/test_repair.py`

- [ ] **Step 3: Implement taxonomy, stale guard, and repair ladder**

The planner must return no generation after one prior generated repair and must recommend `provider_switch` only for provider failure, explicit capability mismatch, or the same blocker repeated after targeted repair.

- [ ] **Step 4: Run quality and repair tests**

Run: `.venv/bin/pytest -q tests/visual/production_kernel/test_quality.py tests/visual/production_kernel/test_repair.py`

Expected: all pass.

### Task 3: Evidence-Based Provider Coordinator

**Files:**
- Create: `agent/visual/production_kernel/providers.py`
- Create: `tests/visual/production_kernel/test_providers.py`

**Interfaces:**
- Consumes: explicit provider, configured default, authorized providers, optional category-scoped provider profiles, and failure evidence.
- Produces: `ProviderDecision(provider, reason, evidence)`.

- [ ] **Step 1: Write failing provider-policy tests**

```python
def test_explicit_provider_always_wins():
    result = choose_visual_provider(explicit_provider="openai-codex", default_provider="xai", authorized=("xai", "openai-codex"), profiles={})
    assert result.provider == "openai-codex"
    assert result.reason == "explicit_override"

def test_sparse_profile_does_not_override_default():
    result = choose_visual_provider(explicit_provider=None, default_provider="xai", authorized=("xai", "openai-codex"), profiles={"openai-codex": {"sample_count": 1, "first_pass_rate": 1.0}})
    assert result.provider == "xai"
```

- [ ] **Step 2: Confirm missing-interface failure**

Run: `.venv/bin/pytest -q tests/visual/production_kernel/test_providers.py`

- [ ] **Step 3: Implement deterministic provider selection**

Require at least five measured samples before profile evidence can override the configured default. Never select an unauthorized provider.

- [ ] **Step 4: Run provider tests**

Run: `.venv/bin/pytest -q tests/visual/production_kernel/test_providers.py`

Expected: all pass.

### Task 4: Visual Agent Planner Integration

**Files:**
- Modify: `agent/visual/agent_mode/planner.py`
- Modify: `tools/visual_agent_tool.py`
- Modify: `tests/visual/test_agent_mode_planner.py`
- Modify: `tests/tools/test_visual_agent_tool.py`

**Interfaces:**
- Consumes: `compile_visual_intent_contract` and `choose_visual_provider`.
- Produces: `arguments.visual_intent_contract`, `arguments.visual_contract_hash`, `arguments.provider_decision`, candidate budget `1`, and recovery budget `1`.

- [ ] **Step 1: Write planner tests for contract propagation and one-candidate default**

```python
def test_image_plan_contains_versioned_contract_and_one_candidate():
    plan = plan_visual_agent_request("Create an image of a red bicycle in rain")
    assert plan["arguments"]["candidate_budget"] == 1
    assert plan["arguments"]["visual_contract_hash"]
    assert plan["arguments"]["visual_intent_contract"]["primary_subject"]
```

- [ ] **Step 2: Confirm the tests fail on the old planner output**

Run: `.venv/bin/pytest -q tests/visual/test_agent_mode_planner.py tests/tools/test_visual_agent_tool.py`

- [ ] **Step 3: Wire the kernel into planner output and direct overrides**

Add the contract keys to the internal direct-override allowlist without exposing them as required user syntax. Preserve explicit provider overrides.

- [ ] **Step 4: Run planner and tool tests**

Run: `.venv/bin/pytest -q tests/visual/test_agent_mode_planner.py tests/tools/test_visual_agent_tool.py`

Expected: all pass.

### Task 5: Visual Package QC And Repair Integration

**Files:**
- Modify: `tools/visual_package_tool.py`
- Modify: `tests/tools/test_visual_package_tool.py`

**Interfaces:**
- Consumes: current contract/hash, quality issues, artifact metadata, provider decision, and the existing delivery gate.
- Produces: ledger metadata with contract provenance, blocker-specific repair prompts, one bounded repair attempt, and structured review-required evidence.

- [ ] **Step 1: Write failing execution tests**

```python
def test_visual_package_generates_one_initial_candidate_by_default(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(visual_package_tool, "generate_image", lambda **kwargs: calls.append(kwargs) or successful_image(tmp_path))
    payload = run_image_package(tmp_path, candidate_budget=1)
    assert payload["success"] is True
    assert len(calls) == 1

def test_visual_package_repair_prompt_names_classified_blocker(monkeypatch, tmp_path):
    calls = install_low_composition_then_pass_provider(monkeypatch, tmp_path)
    payload = run_image_package(tmp_path, candidate_budget=1)
    assert payload["delivery_gate"]["image"]["allowed"] is True
    assert "composition_weak" in calls[1]["prompt"]

def test_visual_package_rejects_artifact_from_stale_contract(monkeypatch, tmp_path):
    payload = run_image_package(tmp_path, artifact_contract_hash="old", visual_contract_hash="new")
    assert payload["delivery_gate"]["image"]["allowed"] is False
    assert "stale_contract" in payload["delivery_gate"]["image"]["blocker_codes"]

def test_visual_package_does_not_call_both_providers_without_fallback_reason(monkeypatch, tmp_path):
    providers = install_provider_capture(monkeypatch, tmp_path)
    run_image_package(tmp_path, image_provider="openai-codex")
    assert providers == ["openai-codex"]
```

- [ ] **Step 2: Run focused tests and confirm behavioral failures**

Run: `.venv/bin/pytest -q tests/tools/test_visual_package_tool.py -k 'contract or candidate_budget or repair or provider'`

- [ ] **Step 3: Record contract provenance and apply bounded repair decisions**

The existing provider call functions remain unchanged. The integration must use the current artifact only for repair and delivery, append blocker codes to repair metadata, and stop after one generated repair.

- [ ] **Step 4: Run the complete Visual Package tests**

Run: `.venv/bin/pytest -q tests/tools/test_visual_package_tool.py`

Expected: all pass.

### Task 6: Regression, Review, And Runtime Proof

**Files:**
- Modify only files identified by review findings.

**Interfaces:**
- Consumes: completed implementation and test evidence.
- Produces: green CI-ready branch and a no-cost runtime planner smoke.

- [ ] **Step 1: Run the production-kernel and complete visual suites**

Run: `.venv/bin/pytest -q tests/visual tests/tools/test_visual_agent_tool.py tests/tools/test_visual_package_tool.py`

- [ ] **Step 2: Run formatting and diff checks**

Run: `.venv/bin/ruff check agent/visual/production_kernel agent/visual/agent_mode/planner.py tools/visual_agent_tool.py tools/visual_package_tool.py tests/visual/production_kernel`

Run: `git diff --check`

- [ ] **Step 3: Perform independent code review**

Review for unbounded calls, hidden dual-provider generation, stale artifact acceptance, provider override regressions, private evidence leakage, and story-video coupling. Fix every validated finding and rerun the focused tests.

- [ ] **Step 4: Run no-cost runtime planner smoke**

Execute `plan_visual_agent_request` against the installed runtime with a temporary image request and assert the emitted candidate budget is one, the contract hash is present, and no media provider is called.

- [ ] **Step 5: Commit, open the fork-local PR, pass CI, merge, and deploy**

Push `feat/visual/production-kernel` to the matching origin branch, target `local/main`, merge only after CI and review pass, fast-forward `local/main`, then fast-forward `runtime/current` to the identical SHA and restart the supervised gateway.
