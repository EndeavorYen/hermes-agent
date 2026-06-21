# Visual Phase 3 Controlled Autonomy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a controlled autonomy layer that can evaluate, promote, report, and roll back visual shadow-learning updates without allowing unproven prompt or strategy mutations into production.

**Architecture:** Phase 3 reads Phase 1/2 evidence from the Visual Attempt Ledger and writes explicit strategy activation decisions. Shadow observations remain immutable evidence. Promotion is a separate policy decision with thresholds, operator approval, bucket scope, self-validation proof, and rollback metadata.

**Tech Stack:** Python 3.11, SQLite, existing `agent.visual` modules, pytest, ruff, `scripts/visual_phase2_self_check.py`, `scripts/visual_shadow_learning_report.py`, `scripts/visual_evidence_report.py`.

## Global Constraints

- Base branch: `upgrade/hermes-v2026.6.19-local`.
- Push local integration work to `origin` only unless an explicit upstream PR workflow is requested.
- Use TDD for every behavior change; write the failing test first, run it, implement the smallest fix, then re-run.
- Runtime-private data stays under `/Users/simon/.hermes`; do not commit raw prompts, generated media, local network endpoints, tokens, provider responses, or user preference corpora.
- Promotion must be scoped by intent signature and strategy signature.
- Under-sampled evidence must stay `shadow_only`.
- Missing operator approval must block activation even when metrics look good.
- Rollback must disable a strategy without deleting evidence.
- Reports must be privacy-safe and must not expose raw prompt text.

---

## File Structure

Create:

- `agent/visual/promotion_policy.py`
  - Pure promotion gate for shadow updates.
  - Produces `PromotionDecision`.
- `agent/visual/strategy_activation.py`
  - Records strategy activation and rollback decisions in the ledger.
- `scripts/visual_strategy_activation_report.py`
  - Privacy-safe CLI report for controlled/active/disabled visual strategies.
- `tests/visual/test_promotion_policy.py`
- `tests/visual/test_strategy_activation.py`
- `tests/scripts/test_visual_strategy_activation_report.py`

Modify:

- `agent/visual/attempt_ledger.py`
  - Add `visual_strategy_activations` table and record/get/list helpers.
- `agent/visual/self_validation.py`
  - Fail when active strategy activations exist without promotion gate evidence.
- `scripts/visual_phase2_self_check.py`
  - Keep Phase 2 default shadow check passing while allowing explicit Phase 3 activation checks when scoped.
- `scripts/visual_shadow_learning_report.py`
  - Link shadow updates to activation state when present.
- `tools/visual_package_tool.py`
  - Later Phase 3 milestone only: read controlled strategies but keep prompt mutation disabled unless activation says it is allowed.

## Milestone 1: Promotion Gate

**Purpose:** Decide whether a shadow update is eligible for controlled activation without mutating runtime behavior.

**Files:**

- Create: `agent/visual/promotion_policy.py`
- Test: `tests/visual/test_promotion_policy.py`

**Interfaces:**

- Produces:

```python
@dataclass(frozen=True)
class PromotionDecision:
    decision: str
    allowed: bool
    reasons: list[str]
    confidence: float
    required: dict[str, float | int | bool]
    observed: dict[str, float | int | bool]

    def to_record(self) -> dict[str, Any]: ...

def evaluate_shadow_promotion(
    evidence: dict[str, Any],
    *,
    operator_approved: bool = False,
    thresholds: PromotionThresholds | None = None,
) -> PromotionDecision: ...
```

- `decision` values:
  - `promote_controlled`
  - `shadow_only`
  - `blocked`

- Required thresholds:
  - `min_bucket_requests = 20`
  - `min_successful_artifacts = 10`
  - `min_provider_confidence = 0.80`
  - `min_shadow_confidence = 0.75`
  - `max_duplicate_deliveries = 0`
  - `max_missing_source_metadata = 0`
  - `max_recent_negative_feedback = 0`
  - `operator_approved = True`
  - `self_validation_success = True`

- [ ] **Step 1: Write failing tests**

Add `tests/visual/test_promotion_policy.py`:

```python
def test_promotion_policy_blocks_under_sampled_bucket():
    from agent.visual.promotion_policy import evaluate_shadow_promotion

    decision = evaluate_shadow_promotion(
        {
            "bucket_request_count": 3,
            "successful_artifact_count": 2,
            "provider_confidence": 0.95,
            "shadow_confidence": 0.90,
            "duplicate_delivery_count": 0,
            "missing_source_metadata_count": 0,
            "recent_negative_feedback_count": 0,
            "self_validation_success": True,
        },
        operator_approved=True,
    )

    assert decision.allowed is False
    assert decision.decision == "shadow_only"
    assert "insufficient_bucket_requests" in decision.reasons
```

```python
def test_promotion_policy_requires_operator_approval():
    from agent.visual.promotion_policy import evaluate_shadow_promotion

    decision = evaluate_shadow_promotion(
        {
            "bucket_request_count": 25,
            "successful_artifact_count": 12,
            "provider_confidence": 0.95,
            "shadow_confidence": 0.90,
            "duplicate_delivery_count": 0,
            "missing_source_metadata_count": 0,
            "recent_negative_feedback_count": 0,
            "self_validation_success": True,
        },
        operator_approved=False,
    )

    assert decision.allowed is False
    assert decision.decision == "blocked"
    assert "operator_approval_required" in decision.reasons
```

```python
def test_promotion_policy_allows_controlled_when_all_gates_pass():
    from agent.visual.promotion_policy import evaluate_shadow_promotion

    decision = evaluate_shadow_promotion(
        {
            "bucket_request_count": 25,
            "successful_artifact_count": 12,
            "provider_confidence": 0.95,
            "shadow_confidence": 0.90,
            "duplicate_delivery_count": 0,
            "missing_source_metadata_count": 0,
            "recent_negative_feedback_count": 0,
            "self_validation_success": True,
        },
        operator_approved=True,
    )

    assert decision.allowed is True
    assert decision.decision == "promote_controlled"
    assert decision.confidence == 0.9
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_promotion_policy.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agent.visual.promotion_policy'`.

- [ ] **Step 3: Implement the promotion policy**

Create `agent/visual/promotion_policy.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PromotionThresholds:
    min_bucket_requests: int = 20
    min_successful_artifacts: int = 10
    min_provider_confidence: float = 0.80
    min_shadow_confidence: float = 0.75
    max_duplicate_deliveries: int = 0
    max_missing_source_metadata: int = 0
    max_recent_negative_feedback: int = 0

    def to_record(self) -> dict[str, float | int | bool]:
        return {
            "min_bucket_requests": self.min_bucket_requests,
            "min_successful_artifacts": self.min_successful_artifacts,
            "min_provider_confidence": self.min_provider_confidence,
            "min_shadow_confidence": self.min_shadow_confidence,
            "max_duplicate_deliveries": self.max_duplicate_deliveries,
            "max_missing_source_metadata": self.max_missing_source_metadata,
            "max_recent_negative_feedback": self.max_recent_negative_feedback,
            "operator_approved": True,
            "self_validation_success": True,
        }


@dataclass(frozen=True)
class PromotionDecision:
    decision: str
    allowed: bool
    reasons: list[str]
    confidence: float
    required: dict[str, float | int | bool]
    observed: dict[str, float | int | bool]

    def to_record(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "allowed": self.allowed,
            "reasons": self.reasons,
            "confidence": self.confidence,
            "required": self.required,
            "observed": self.observed,
        }


def evaluate_shadow_promotion(
    evidence: dict[str, Any],
    *,
    operator_approved: bool = False,
    thresholds: PromotionThresholds | None = None,
) -> PromotionDecision:
    thresholds = thresholds or PromotionThresholds()
    observed = _observed(evidence, operator_approved=operator_approved)
    reasons = _gate_failures(observed, thresholds)
    confidence = min(
        _float(observed["provider_confidence"]),
        _float(observed["shadow_confidence"]),
    )
    if not reasons:
        decision = "promote_controlled"
        allowed = True
    elif "operator_approval_required" in reasons:
        decision = "blocked"
        allowed = False
    else:
        decision = "shadow_only"
        allowed = False
    return PromotionDecision(
        decision=decision,
        allowed=allowed,
        reasons=reasons,
        confidence=round(confidence, 4),
        required=thresholds.to_record(),
        observed=observed,
    )
```

The helper functions must normalize missing or malformed values to conservative defaults:

```python
def _observed(
    evidence: dict[str, Any],
    *,
    operator_approved: bool,
) -> dict[str, float | int | bool]:
    return {
        "bucket_request_count": _int(evidence.get("bucket_request_count")),
        "successful_artifact_count": _int(evidence.get("successful_artifact_count")),
        "provider_confidence": _float(evidence.get("provider_confidence")),
        "shadow_confidence": _float(evidence.get("shadow_confidence")),
        "duplicate_delivery_count": _int(evidence.get("duplicate_delivery_count")),
        "missing_source_metadata_count": _int(evidence.get("missing_source_metadata_count")),
        "recent_negative_feedback_count": _int(evidence.get("recent_negative_feedback_count")),
        "self_validation_success": evidence.get("self_validation_success") is True,
        "operator_approved": operator_approved is True,
    }
```

- [ ] **Step 4: Run tests**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_promotion_policy.py -q
```

Expected: PASS.

- [ ] **Step 5: Self-review Milestone 1**

Check:

- under-sampled evidence stays `shadow_only`;
- missing approval returns `blocked`;
- fully qualified evidence returns `promote_controlled`;
- no ledger schema or runtime behavior has changed yet;
- no prompt text or private runtime data is introduced.

- [ ] **Step 6: Commit Milestone 1**

Run:

```bash
rtk git add agent/visual/promotion_policy.py tests/visual/test_promotion_policy.py
rtk git commit -m "feat: gate visual strategy promotion"
```

## Milestone 2: Strategy Activation Ledger

**Purpose:** Persist promotion decisions and rollback state separately from shadow observations.

**Files:**

- Modify: `agent/visual/attempt_ledger.py`
- Create: `agent/visual/strategy_activation.py`
- Test: `tests/visual/test_strategy_activation.py`

**Interfaces:**

- Produces:

```python
def record_strategy_activation(
    ledger: VisualAttemptLedger,
    *,
    shadow_update_id: str,
    intent_signature: str,
    strategy_signature: str,
    activation_status: str,
    promotion_decision: dict[str, Any],
    rollback_of: str | None = None,
) -> str: ...
```

- Activation statuses:
  - `controlled`
  - `disabled`
  - `rolled_back`

**Verification:**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_strategy_activation.py tests/visual/test_attempt_ledger.py -q
rtk ./venv/bin/python -m ruff check agent/visual/attempt_ledger.py agent/visual/strategy_activation.py tests/visual/test_strategy_activation.py
rtk git diff --check
```

## Milestone 3: Activation Reports and Self-Validation

**Purpose:** Make controlled strategies auditable and fail closed when activation evidence is missing.

**Files:**

- Create: `scripts/visual_strategy_activation_report.py`
- Modify: `agent/visual/self_validation.py`
- Modify: `scripts/visual_shadow_learning_report.py`
- Test: `tests/scripts/test_visual_strategy_activation_report.py`
- Test: `tests/visual/test_self_validation.py`

**Verification:**

```bash
rtk ./venv/bin/python -m pytest tests/scripts/test_visual_strategy_activation_report.py tests/visual/test_self_validation.py tests/scripts/test_visual_shadow_learning_report.py -q
rtk ./venv/bin/python scripts/visual_phase2_self_check.py --fixture --json
rtk ./venv/bin/python -m ruff check agent/visual scripts/visual_strategy_activation_report.py scripts/visual_shadow_learning_report.py
rtk git diff --check
```

## Milestone 4: Controlled Strategy Read Path

**Purpose:** Let `visual_package_generate` read controlled strategy state while keeping prompt mutation disabled unless the activation explicitly allows it.

**Files:**

- Modify: `tools/visual_package_tool.py`
- Modify: `agent/visual/strategy_policy.py`
- Test: `tests/tools/test_visual_package_tool.py`
- Test: `tests/visual/test_strategy_policy.py`

**Verification:**

```bash
rtk ./venv/bin/python -m pytest tests/tools/test_visual_package_tool.py tests/visual/test_strategy_policy.py tests/visual/test_promotion_policy.py -q
rtk ./venv/bin/python scripts/visual_evidence_self_smoke.py --json
rtk ./venv/bin/python scripts/visual_phase2_self_check.py --fixture --json
rtk ./venv/bin/python -m ruff check agent/visual tools/visual_package_tool.py scripts
rtk git diff --check
```

## Milestone 5: Live Controlled Rollout Readiness

**Purpose:** Prepare a live proof path without enabling production mutation by default.

**Requirements:**

- Run fixture proof first.
- Run one direct `visual_package_generate` smoke with `learning_mode=shadow`.
- Run activation report and confirm no controlled activations exist unless explicitly configured.
- If controlled activation is enabled later, scope it to a single bucket and one strategy signature.

**Verification:**

```bash
rtk ./venv/bin/python -m pytest tests/visual tests/tools/test_visual_package_tool.py tests/scripts/test_visual_evidence_self_smoke.py tests/scripts/test_visual_phase2_self_check.py tests/scripts/test_visual_shadow_learning_report.py -q
rtk ./venv/bin/python scripts/visual_evidence_self_smoke.py --json
rtk ./venv/bin/python scripts/visual_phase2_self_check.py --fixture --json
rtk ./venv/bin/python scripts/visual_shadow_learning_report.py --json
rtk git status --short --branch
```

## Phase 3 Completion Criteria

- Promotion policy is implemented and tested.
- Strategy activation ledger exists and is privacy-safe.
- Reports explain active, controlled, disabled, and rolled-back strategies.
- Self-validation catches unsafe activation.
- Package tool can read controlled strategy state without forcing mutation.
- Default production behavior remains shadow unless gates and config allow controlled mode.
- All milestone commits are pushed to `origin/upgrade/hermes-v2026.6.19-local`.

## Self-Review Checklist

After each milestone:

- Does this reduce future human intervention without hiding uncertainty?
- Can the behavior be proven offline?
- Can the behavior be explained from ledger evidence?
- Is provider reliability separate from aesthetic preference?
- Is rollback possible without deleting evidence?
- Did the change avoid committing private prompts, media, provider responses, or local endpoints?
- Are stale/duplicate Slack delivery protections preserved?
