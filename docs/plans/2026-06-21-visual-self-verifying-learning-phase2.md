# Visual Self-Verifying Learning Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a self-verifying visual learning loop that can generate candidates, score them, rank them, decide whether to post/retry/ask, and improve strategy selection in shadow mode with minimal human intervention.

**Architecture:** Keep Phase 1 evidence primitives as the source of truth: Visual Attempt Ledger, stable artifacts, deterministic judgments, ranking, delivery records, feedback attribution, and self-smoke. Phase 2 adds a separate learning layer that reads evidence and writes versioned strategy/preference/provider summaries; it must not overwrite prompts or mutate runtime behavior until shadow-mode gates pass. Human feedback remains the strongest signal, but the default loop should rely on automatic checks, weak labels, and confidence gates so the user only intervenes when uncertainty is high.

**Tech Stack:** Python 3.11, SQLite, existing `agent.visual` primitives, Hermes image/video providers, optional Hermes vision tools, pytest, ruff, `scripts/visual_evidence_self_smoke.py`, `scripts/visual_evidence_report.py`.

## Global Constraints

- Base branch: `upgrade/hermes-v2026.6.19-local`.
- Push local integration work to `origin` only unless an explicit upstream PR workflow is requested.
- Use TDD for every behavior change; write the failing test first, run it, implement the smallest fix, then re-run.
- Runtime-private data stays under `/Users/simon/.hermes`; do not commit raw prompts, generated media, user preference corpora, local network endpoints, tokens, or provider responses.
- Phase 2 must not train a new generative model. Providers remain black-box samplers.
- Phase 2 must not automatically mutate prompts in production until shadow-mode reports show stable improvement across real requests.
- Separate provider reliability, delivery health, reference adherence, aesthetic preference, and user feedback. Do not let one track inflate another.
- Every autonomous decision must be auditable from ledger rows: candidate set, judges, score components, confidence, strategy version, and final action.
- The default user experience must stay natural-language friendly. Users should not need to specify `autonomy_level`, `candidate_budget`, or `video_budget` unless they choose advanced control.
- Slack must only receive current selected artifacts, never stale or duplicate candidates.

---

## Current Phase 1 Foundation

Phase 1 is complete enough to support Phase 2:

- `agent/visual/attempt_ledger.py` records requests, attempts, artifacts, judgments, rankings, deliveries, and feedback.
- `agent/visual/judges/deterministic.py` provides hard gates and basic artifact scores.
- `agent/visual/ranker.py` chooses `post`, `ask_user`, `retry`, or `fail` from scored candidates.
- `agent/visual/feedback.py` parses sparse human feedback into selection hints, polarity, signals, and issues.
- `tools/visual_package_tool.py` generates coordinated image/video packages and returns selected media.
- `scripts/visual_evidence_self_smoke.py` and `scripts/visual_evidence_report.py` provide headless proof.

Phase 2 must build on these contracts instead of replacing them.

## Phase 2 Non-Goals

- Do not restore old Visual Agent Mode code wholesale.
- Do not require human scoring after every generation.
- Do not store raw private prompts in tracked docs or committed fixtures.
- Do not treat Qwen, Grok, Image2, or any single provider as the ground truth.
- Do not optimize for bypassing platform detection or content policy. The learning system should optimize quality, relevance, reliability, and delivery correctness within configured provider capabilities.

## File Structure

Create:

- `agent/visual/intent_signature.py`
  - Converts normalized intent, modality, locks, and style hints into stable bucket signatures.
- `agent/visual/eval_dimensions.py`
  - Defines score dimensions and typed score aggregation helpers.
- `agent/visual/provider_stats.py`
  - Computes provider/model reliability priors from ledger evidence.
- `agent/visual/preference_profile.py`
  - Maintains EWMA preference summaries from explicit feedback and weak labels.
- `agent/visual/strategy_atoms.py`
  - Defines reusable prompt/composition/motion strategy atoms and strategy signatures.
- `agent/visual/strategy_policy.py`
  - Chooses candidate strategies using confidence-gated exploitation/exploration.
- `agent/visual/reward_model.py`
  - Combines deterministic judges, provider priors, weak labels, and feedback into a candidate reward.
- `agent/visual/active_learning.py`
  - Decides `auto_post`, `auto_retry`, `ask_user`, `shadow_only`, or `fail_closed`.
- `agent/visual/shadow_learning.py`
  - Records proposed strategy updates without changing production behavior.
- `agent/visual/self_validation.py`
  - Runs self-validation checks over fixture and runtime-scoped evidence.
- `scripts/visual_phase2_self_check.py`
  - CLI gate for development and rollout verification.
- `scripts/visual_shadow_learning_report.py`
  - Privacy-safe report showing proposed learning changes and confidence.

Modify:

- `agent/visual/attempt_ledger.py`
  - Add schema/helpers for strategy decisions, reward scores, self-check runs, and shadow updates.
- `agent/visual/judges/deterministic.py`
  - Keep as hard gate; expose dimension-compatible scores.
- `agent/visual/ranker.py`
  - Accept reward-model scores and confidence when available.
- `tools/visual_package_tool.py`
  - Add internal candidate-budget support, strategy selection, self-scoring, and active-learning decisions while keeping simple user prompts.
- `scripts/visual_evidence_report.py`
  - Include Phase 2 fields without leaking private prompt text.
- `scripts/visual_evidence_self_smoke.py`
  - Exercise one shadow-learning pass with fixture artifacts.

Tests:

- `tests/visual/test_intent_signature.py`
- `tests/visual/test_eval_dimensions.py`
- `tests/visual/test_provider_stats.py`
- `tests/visual/test_preference_profile.py`
- `tests/visual/test_strategy_atoms.py`
- `tests/visual/test_strategy_policy.py`
- `tests/visual/test_reward_model.py`
- `tests/visual/test_active_learning.py`
- `tests/visual/test_shadow_learning.py`
- `tests/visual/test_self_validation.py`
- `tests/tools/test_visual_package_tool.py`
- `tests/scripts/test_visual_phase2_self_check.py`
- `tests/scripts/test_visual_shadow_learning_report.py`

## Self-Validation Contract

Every Phase 2 implementation milestone must end with three validation layers:

1. **Unit tests:** deterministic, no live providers, no Slack, no network.
2. **Headless self-check:** fixture artifacts and temporary `HERMES_HOME`; must prove no duplicate delivery, no missing source metadata, valid reward traces, and stable active-learning decisions.
3. **Runtime-scoped proof:** run against a specific request id when live providers are used; report must be scoped and privacy-safe.

Required commands after each implementation milestone:

```bash
rtk ./venv/bin/python -m pytest tests/visual tests/tools/test_visual_package_tool.py tests/scripts/test_visual_evidence_self_smoke.py -q
rtk ./venv/bin/python scripts/visual_evidence_self_smoke.py --json
rtk ./venv/bin/python scripts/visual_phase2_self_check.py --json
rtk ./venv/bin/python -m ruff check agent/visual tools/visual_package_tool.py scripts/visual_phase2_self_check.py scripts/visual_shadow_learning_report.py
rtk git diff --check
```

Expected:

- pytest passes;
- self-smoke returns `success: true`;
- Phase 2 self-check returns `success: true`;
- duplicate delivery count is `0`;
- missing source metadata count is `0`;
- every ranked candidate has score components and confidence;
- shadow updates are recorded but production strategy is unchanged unless the milestone explicitly enables a gated rollout.

## Human-Intervention Reduction Targets

Phase 2 is successful only if normal use requires substantially less manual review:

- Candidate ranking happens before Slack delivery.
- Hermes posts the best current artifact set automatically when confidence is high.
- Hermes retries internally when failure reason is actionable and retry budget remains.
- Hermes asks the user only when confidence is low, reference identity is uncertain, provider failure is ambiguous, or style preference conflicts are detected.
- User feedback can be sparse: "A good, B bad, face wrong" should be enough to update preference summaries.
- No manual intervention is required for routine stale/duplicate/media-metadata validation.

## Milestone 1: Intent Buckets and Score Dimensions

**Purpose:** Make learning context-specific instead of global.

**Files:**

- Create: `agent/visual/intent_signature.py`
- Create: `agent/visual/eval_dimensions.py`
- Test: `tests/visual/test_intent_signature.py`
- Test: `tests/visual/test_eval_dimensions.py`

**Interfaces:**

- Produces: `build_intent_signature(intent: dict[str, Any]) -> str`
- Produces: `VisualScoreBreakdown`
- Produces: `combine_weighted_scores(scores: dict[str, float], weights: dict[str, float]) -> float`

- [ ] **Step 1: Write failing intent signature tests**

```python
def test_intent_signature_is_stable_and_omits_raw_prompt():
    from agent.visual.intent_signature import build_intent_signature

    sig1 = build_intent_signature(
        {
            "modality": "package",
            "subject_type": "product",
            "style": "clean product photography",
            "aspect_ratio": "16:9",
            "raw_prompt": "private prompt should not leak",
        }
    )
    sig2 = build_intent_signature(
        {
            "aspect_ratio": "16:9",
            "style": "clean product photography",
            "subject_type": "product",
            "modality": "package",
            "raw_prompt": "different private text",
        }
    )

    assert sig1 == sig2
    assert sig1.startswith("visig_")
    assert "private" not in sig1
```

- [ ] **Step 2: Write failing score dimension tests**

```python
def test_combine_weighted_scores_clamps_and_normalizes():
    from agent.visual.eval_dimensions import combine_weighted_scores

    score = combine_weighted_scores(
        scores={"artifact_validity": 1.0, "provider_reliability": 0.5, "aesthetic_fit": 2.0},
        weights={"artifact_validity": 2.0, "provider_reliability": 1.0, "aesthetic_fit": 1.0},
    )

    assert score == 0.875
```

- [ ] **Step 3: Run red tests**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_intent_signature.py tests/visual/test_eval_dimensions.py -q
```

Expected: FAIL because modules are missing.

- [ ] **Step 4: Implement minimal modules**

`build_intent_signature()` must whitelist stable non-private keys and hash the canonical JSON payload. `combine_weighted_scores()` must clamp every dimension to `[0.0, 1.0]`, ignore zero/negative weights, and round to four decimals.

- [ ] **Step 5: Verify and commit**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_intent_signature.py tests/visual/test_eval_dimensions.py -q
rtk ./venv/bin/python -m ruff check agent/visual/intent_signature.py agent/visual/eval_dimensions.py tests/visual/test_intent_signature.py tests/visual/test_eval_dimensions.py
rtk git diff --check
rtk git add agent/visual/intent_signature.py agent/visual/eval_dimensions.py tests/visual/test_intent_signature.py tests/visual/test_eval_dimensions.py
rtk git commit -m "feat: add visual intent buckets"
```

## Milestone 2: Provider Reliability Priors

**Purpose:** Let Hermes learn which provider/model paths are reliable without confusing reliability with taste.

**Files:**

- Create: `agent/visual/provider_stats.py`
- Modify: `scripts/visual_evidence_report.py`
- Test: `tests/visual/test_provider_stats.py`

**Interfaces:**

- Consumes: `VisualAttemptLedger`
- Produces: `ProviderReliability`
- Produces: `compute_provider_reliability(ledger: VisualAttemptLedger, *, bucket: str | None = None) -> dict[str, Any]`

- [ ] **Step 1: Write failing provider stats tests**

```python
def test_provider_reliability_counts_success_policy_and_delivery_separately(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.provider_stats import compute_provider_reliability

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed", metadata={"intent_signature": "visig_demo"})
    good_attempt = ledger.record_attempt(request_id=request_id, provider="xai", model="image", status="completed")
    bad_attempt = ledger.record_attempt(
        request_id=request_id,
        provider="xai",
        model="image",
        status="failed",
        error_type="content_moderation",
    )
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=good_attempt,
        kind="image",
        content_hash="abc",
        mime_type="image/png",
        freshness_status="fresh",
        is_stable=True,
    )
    ledger.record_delivery(request_id=request_id, attempt_id=good_attempt, artifact_id=artifact_id, delivery_status="sent")

    stats = compute_provider_reliability(ledger, bucket="visig_demo")

    assert stats["xai:image"]["attempt_count"] == 2
    assert stats["xai:image"]["generation_success_rate"] == 0.5
    assert stats["xai:image"]["delivery_success_rate"] == 1.0
    assert stats["xai:image"]["policy_failure_rate"] == 0.5
```

- [ ] **Step 2: Run red test**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_provider_stats.py -q
```

Expected: FAIL because `provider_stats` is missing.

- [ ] **Step 3: Implement provider stats**

Implementation must read only structured ledger fields. It must never inspect or store raw prompt text.

- [ ] **Step 4: Add report summary**

Extend `build_visual_evidence_report()` with:

```python
"provider_reliability": {
    "top": [
        {
            "provider_model": "xai:image",
            "attempt_count": 2,
            "generation_success_rate": 0.5,
            "delivery_success_rate": 1.0,
            "policy_failure_rate": 0.5,
        }
    ]
}
```

- [ ] **Step 5: Verify and commit**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_provider_stats.py tests/scripts/test_visual_evidence_self_smoke.py -q
rtk ./venv/bin/python -m ruff check agent/visual/provider_stats.py scripts/visual_evidence_report.py tests/visual/test_provider_stats.py
rtk git diff --check
rtk git add agent/visual/provider_stats.py scripts/visual_evidence_report.py tests/visual/test_provider_stats.py
rtk git commit -m "feat: track visual provider reliability"
```

## Milestone 3: Preference Profile From Sparse Feedback

**Purpose:** Turn sparse user feedback into preference priors without requiring per-round manual ratings.

**Files:**

- Create: `agent/visual/preference_profile.py`
- Test: `tests/visual/test_preference_profile.py`

**Interfaces:**

- Consumes: rows from `visual_feedback`
- Produces: `PreferenceProfile`
- Produces: `build_preference_profile(ledger: VisualAttemptLedger, *, bucket: str | None = None) -> dict[str, Any]`

- [ ] **Step 1: Write failing preference profile tests**

```python
def test_preference_profile_uses_feedback_ewma_by_issue_and_signal(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.preference_profile import build_preference_profile

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed", metadata={"intent_signature": "visig_demo"})
    artifact_id = ledger.record_artifact(request_id=request_id, kind="image", content_hash="abc")
    ledger.record_feedback(
        request_id=request_id,
        artifact_id=artifact_id,
        feedback_text="A 不錯，有美腿，但臉不自然",
        polarity=0.4,
        parsed={"signals": ["legs_positive"], "issues": ["face_unnatural"]},
    )

    profile = build_preference_profile(ledger, bucket="visig_demo")

    assert profile["bucket"] == "visig_demo"
    assert profile["signals"]["legs_positive"]["weight"] > 0
    assert profile["issues"]["face_unnatural"]["penalty"] > 0
    assert profile["sample_count"] == 1
```

- [ ] **Step 2: Run red test**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_preference_profile.py -q
```

Expected: FAIL because module is missing.

- [ ] **Step 3: Implement EWMA profile**

Use conservative defaults:

- explicit user feedback weight: `1.0`;
- weak automatic labels weight: `0.25`;
- minimum confidence sample count: `5`;
- no production prompt mutation from profile data.

- [ ] **Step 4: Verify and commit**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_preference_profile.py tests/visual/test_feedback_parser.py -q
rtk ./venv/bin/python -m ruff check agent/visual/preference_profile.py tests/visual/test_preference_profile.py
rtk git diff --check
rtk git add agent/visual/preference_profile.py tests/visual/test_preference_profile.py
rtk git commit -m "feat: summarize visual preferences from feedback"
```

## Milestone 4: Strategy Atoms and Shadow Policy

**Purpose:** Make prompt/composition/video improvements reusable and testable instead of ad hoc.

**Files:**

- Create: `agent/visual/strategy_atoms.py`
- Create: `agent/visual/strategy_policy.py`
- Test: `tests/visual/test_strategy_atoms.py`
- Test: `tests/visual/test_strategy_policy.py`

**Interfaces:**

- Produces: `StrategyAtom`
- Produces: `StrategyPlan`
- Produces: `select_strategy_plan(intent_signature: str, *, provider_stats: dict[str, Any], preference_profile: dict[str, Any], exploration_rate: float = 0.2) -> StrategyPlan`

- [ ] **Step 1: Write failing strategy atom tests**

```python
def test_strategy_atom_signature_is_versioned_and_private_safe():
    from agent.visual.strategy_atoms import StrategyAtom

    atom = StrategyAtom(
        atom_id="composition.full_body_product",
        version="v1",
        kind="composition",
        public_summary="full subject visible with clean background",
        prompt_delta="full subject visible, clean background",
        negative_delta="cropped subject",
    )

    assert atom.signature == "composition.full_body_product@v1"
    assert "private" not in atom.to_record()
```

- [ ] **Step 2: Write failing policy tests**

```python
def test_strategy_policy_prefers_reliable_high_confidence_atoms():
    from agent.visual.strategy_policy import select_strategy_plan

    plan = select_strategy_plan(
        "visig_demo",
        provider_stats={"xai:image": {"generation_success_rate": 0.9, "attempt_count": 20}},
        preference_profile={"signals": {"legs_positive": {"weight": 0.8}}, "sample_count": 8},
        exploration_rate=0.0,
    )

    assert plan.mode == "exploit"
    assert plan.confidence >= 0.7
    assert plan.strategy_signature
```

- [ ] **Step 3: Run red tests**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_strategy_atoms.py tests/visual/test_strategy_policy.py -q
```

Expected: FAIL because modules are missing.

- [ ] **Step 4: Implement strategy atoms and policy**

Start with a small built-in registry:

- `composition.full_subject_visible@v1`
- `composition.leg_emphasis_editorial@v1`
- `motion.camera_push_in@v1`
- `motion.subject_turn_subtle@v1`
- `safety.professional_editorial@v1`
- `product.clean_window_light@v1`

Policy must return a plan but not directly rewrite prompts in this milestone.

- [ ] **Step 5: Verify and commit**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_strategy_atoms.py tests/visual/test_strategy_policy.py -q
rtk ./venv/bin/python -m ruff check agent/visual/strategy_atoms.py agent/visual/strategy_policy.py tests/visual/test_strategy_atoms.py tests/visual/test_strategy_policy.py
rtk git diff --check
rtk git add agent/visual/strategy_atoms.py agent/visual/strategy_policy.py tests/visual/test_strategy_atoms.py tests/visual/test_strategy_policy.py
rtk git commit -m "feat: add visual strategy policy"
```

## Milestone 5: Reward Model and Confidence

**Purpose:** Score candidates before Slack delivery using multiple evidence tracks.

**Files:**

- Create: `agent/visual/reward_model.py`
- Modify: `agent/visual/ranker.py`
- Test: `tests/visual/test_reward_model.py`
- Test: `tests/visual/test_ranker.py`

**Interfaces:**

- Produces: `score_visual_candidate(candidate: dict[str, Any], *, provider_stats: dict[str, Any], preference_profile: dict[str, Any]) -> dict[str, Any]`
- Produces score dimensions:
  - `artifact_validity`
  - `provider_reliability`
  - `delivery_health`
  - `reference_adherence`
  - `aesthetic_fit`
  - `novelty`
  - `motion_quality`
  - `user_preference_fit`

- [ ] **Step 1: Write failing reward model test**

```python
def test_reward_model_keeps_provider_and_aesthetic_tracks_separate():
    from agent.visual.reward_model import score_visual_candidate

    result = score_visual_candidate(
        {
            "artifact_id": "var_1",
            "kind": "image",
            "hard_gate": {"passed": True},
            "scores": {"final_score": 0.8},
            "judge_scores": {"aesthetic_fit": 0.4},
        },
        provider_stats={"fixture:image": {"generation_success_rate": 1.0, "delivery_success_rate": 1.0}},
        preference_profile={"signals": {}, "issues": {}, "sample_count": 0},
    )

    assert result["dimensions"]["provider_reliability"] == 1.0
    assert result["dimensions"]["aesthetic_fit"] == 0.4
    assert result["final_score"] < 1.0
    assert result["confidence"] < 0.8
```

- [ ] **Step 2: Run red test**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_reward_model.py -q
```

Expected: FAIL because module is missing.

- [ ] **Step 3: Implement reward model**

Use explicit weights:

```python
DEFAULT_WEIGHTS = {
    "artifact_validity": 0.20,
    "provider_reliability": 0.15,
    "delivery_health": 0.10,
    "reference_adherence": 0.15,
    "aesthetic_fit": 0.15,
    "novelty": 0.05,
    "motion_quality": 0.10,
    "user_preference_fit": 0.10,
}
```

Confidence must decrease when sample count is low, judge coverage is missing, or provider failures are recent.

- [ ] **Step 4: Wire ranker to reward fields**

`rank_visual_candidates()` should continue to work with old `scores.final_score`, but prefer `reward.final_score` and `reward.confidence` when present.

- [ ] **Step 5: Verify and commit**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_reward_model.py tests/visual/test_ranker.py -q
rtk ./venv/bin/python -m ruff check agent/visual/reward_model.py agent/visual/ranker.py tests/visual/test_reward_model.py tests/visual/test_ranker.py
rtk git diff --check
rtk git add agent/visual/reward_model.py agent/visual/ranker.py tests/visual/test_reward_model.py tests/visual/test_ranker.py
rtk git commit -m "feat: score visual candidates with rewards"
```

## Milestone 6: Active Learning Gate

**Purpose:** Decide when Hermes can act without asking the user.

**Files:**

- Create: `agent/visual/active_learning.py`
- Test: `tests/visual/test_active_learning.py`

**Interfaces:**

- Produces: `decide_visual_action(ranking: dict[str, Any], *, request_context: dict[str, Any]) -> dict[str, Any]`

- [ ] **Step 1: Write failing active learning tests**

```python
def test_active_learning_auto_posts_high_score_high_confidence():
    from agent.visual.active_learning import decide_visual_action

    decision = decide_visual_action(
        {"decision": "post", "top_score": 0.86, "top_confidence": 0.82, "uncertainty_reasons": []},
        request_context={"has_reference_image": False, "candidate_count": 3},
    )

    assert decision["action"] == "auto_post"
    assert decision["requires_user"] is False
```

```python
def test_active_learning_asks_on_reference_uncertainty():
    from agent.visual.active_learning import decide_visual_action

    decision = decide_visual_action(
        {
            "decision": "post",
            "top_score": 0.78,
            "top_confidence": 0.62,
            "uncertainty_reasons": ["reference_adherence_missing"],
        },
        request_context={"has_reference_image": True, "candidate_count": 2},
    )

    assert decision["action"] == "ask_user"
    assert decision["requires_user"] is True
```

- [ ] **Step 2: Run red test**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_active_learning.py -q
```

Expected: FAIL because module is missing.

- [ ] **Step 3: Implement gate**

Use conservative thresholds:

- `auto_post`: score >= `0.80`, confidence >= `0.75`, no high-risk uncertainty.
- `auto_retry`: no passing candidate and retry budget remains with actionable provider or artifact reason.
- `ask_user`: confidence between `0.45` and `0.75`, reference uncertainty, conflicting preferences, or repeated aesthetic misses.
- `fail_closed`: provider/policy failures with no safe retry path.
- `shadow_only`: any proposed learning mutation before rollout approval.

- [ ] **Step 4: Verify and commit**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_active_learning.py -q
rtk ./venv/bin/python -m ruff check agent/visual/active_learning.py tests/visual/test_active_learning.py
rtk git diff --check
rtk git add agent/visual/active_learning.py tests/visual/test_active_learning.py
rtk git commit -m "feat: gate visual autonomy decisions"
```

## Milestone 7: Candidate Sets in Visual Package Tool

**Purpose:** Generate and evaluate multiple candidates internally while keeping user prompts simple.

**Files:**

- Modify: `tools/visual_package_tool.py`
- Modify: `agent/visual/attempt_ledger.py`
- Test: `tests/tools/test_visual_package_tool.py`
- Test: `tests/visual/test_attempt_ledger.py`

**Interfaces:**

- `visual_package_generate` keeps only required `prompt` for normal use.
- Optional advanced args:
  - `candidate_budget: int`
  - `video_budget: int`
  - `autonomy_level: int`
- Defaults:
  - simple image-only: `candidate_budget=2`
  - image+video package: `candidate_budget=2`, `video_budget=1`
  - explicit quick request: `candidate_budget=1`

- [ ] **Step 1: Write failing package tests**

```python
@pytest.mark.asyncio
async def test_visual_package_generates_multiple_image_candidates_and_posts_only_winner(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    paths = []
    for index in range(2):
        path = tmp_path / f"image-{index}.png"
        path.write_bytes(_ONE_PIXEL_PNG)
        paths.append(path)
    calls = []

    def fake_generate_image(**kwargs):
        calls.append(kwargs)
        return {"success": True, "image": str(paths[len(calls) - 1]), "provider": "fixture", "model": "image"}

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(
        visual_package_tool,
        "generate_video",
        lambda **kwargs: {"success": False, "error": "not requested", "provider": "fixture", "model": "video"},
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {"prompt": "請產出一張圖片：霧黑鋼筆。", "candidate_budget": 2, "include_video": False}
        )
    )

    assert len(calls) == 2
    assert len(payload["images"]) == 1
    assert len(payload["delivery_metadata"]["selected_visual_artifact_ids"]) == 1
```

- [ ] **Step 2: Run red test**

```bash
rtk ./venv/bin/python -m pytest tests/tools/test_visual_package_tool.py::test_visual_package_generates_multiple_image_candidates_and_posts_only_winner -q
```

Expected: FAIL because the tool currently generates one image candidate.

- [ ] **Step 3: Implement candidate loop**

Implementation rules:

- generate all candidates before ranking;
- record every candidate attempt and artifact;
- run deterministic and reward scoring for each candidate;
- return only selected media;
- delivery metadata must include all artifact ids and selected artifact ids;
- no candidate is sent to Slack unless selected.

- [ ] **Step 4: Verify and commit**

```bash
rtk ./venv/bin/python -m pytest tests/tools/test_visual_package_tool.py tests/visual/test_attempt_ledger.py -q
rtk ./venv/bin/python -m ruff check tools/visual_package_tool.py agent/visual/attempt_ledger.py tests/tools/test_visual_package_tool.py tests/visual/test_attempt_ledger.py
rtk git diff --check
rtk git add tools/visual_package_tool.py agent/visual/attempt_ledger.py tests/tools/test_visual_package_tool.py tests/visual/test_attempt_ledger.py
rtk git commit -m "feat: rank visual package candidate sets"
```

## Milestone 8: Shadow Learning Records

**Purpose:** Let Hermes propose improvements without silently changing behavior.

**Files:**

- Create: `agent/visual/shadow_learning.py`
- Modify: `agent/visual/attempt_ledger.py`
- Create: `scripts/visual_shadow_learning_report.py`
- Test: `tests/visual/test_shadow_learning.py`
- Test: `tests/scripts/test_visual_shadow_learning_report.py`

**Interfaces:**

- Produces: `record_shadow_update(...) -> str`
- Produces: `build_shadow_learning_report(db_path: str | Path, *, request_id: str | None = None) -> dict[str, Any]`

- [ ] **Step 1: Write failing shadow learning tests**

```python
def test_shadow_learning_records_proposed_update_without_activation(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.shadow_learning import record_shadow_update

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed")

    update_id = record_shadow_update(
        ledger,
        request_id=request_id,
        intent_signature="visig_demo",
        strategy_signature="composition.full_subject_visible@v1",
        proposed_change={"increase_weight": 0.05},
        evidence={"sample_count": 3, "expected_delta": 0.04},
    )

    row = ledger.get_shadow_update(update_id)
    assert row["activation_status"] == "shadow"
    assert row["proposed_change"]["increase_weight"] == 0.05
```

- [ ] **Step 2: Run red tests**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_shadow_learning.py -q
```

Expected: FAIL because shadow learning storage is missing.

- [ ] **Step 3: Add ledger table and helpers**

Create table:

```sql
CREATE TABLE IF NOT EXISTS visual_shadow_updates (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    intent_signature TEXT,
    strategy_signature TEXT,
    proposed_change_json TEXT,
    evidence_json TEXT,
    confidence REAL,
    activation_status TEXT
);
```

- [ ] **Step 4: Implement report**

Report must include counts, top proposed changes, confidence, and reasons. It must not include raw prompt text.

- [ ] **Step 5: Verify and commit**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_shadow_learning.py tests/scripts/test_visual_shadow_learning_report.py -q
rtk ./venv/bin/python -m ruff check agent/visual/shadow_learning.py scripts/visual_shadow_learning_report.py tests/visual/test_shadow_learning.py tests/scripts/test_visual_shadow_learning_report.py
rtk git diff --check
rtk git add agent/visual/shadow_learning.py agent/visual/attempt_ledger.py scripts/visual_shadow_learning_report.py tests/visual/test_shadow_learning.py tests/scripts/test_visual_shadow_learning_report.py
rtk git commit -m "feat: record visual shadow learning"
```

## Milestone 9: Phase 2 Self-Check CLI

**Purpose:** Give development and rollout a one-command self-validation gate.

**Files:**

- Create: `agent/visual/self_validation.py`
- Create: `scripts/visual_phase2_self_check.py`
- Test: `tests/visual/test_self_validation.py`
- Test: `tests/scripts/test_visual_phase2_self_check.py`

**Interfaces:**

- Produces: `run_visual_self_validation(db_path: str | Path | None = None, *, request_id: str | None = None) -> dict[str, Any]`

- [ ] **Step 1: Write failing self-validation tests**

```python
def test_self_validation_fails_when_reward_trace_missing(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.self_validation import run_visual_self_validation

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed")
    attempt_id = ledger.record_attempt(request_id=request_id, status="completed", provider="fixture", model="image")
    ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        content_hash="abc",
        mime_type="image/png",
        freshness_status="fresh",
        is_stable=True,
    )

    result = run_visual_self_validation(tmp_path / "visual.sqlite3", request_id=request_id)

    assert result["success"] is False
    assert "missing_reward_trace" in result["failures"]
```

- [ ] **Step 2: Write failing CLI test**

```python
def test_phase2_self_check_json_reports_success_for_fixture(capsys, tmp_path, monkeypatch):
    from scripts.visual_phase2_self_check import main

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    code = main(["--fixture", "--json"])
    out = capsys.readouterr().out

    assert code == 0
    assert '"success": true' in out
```

- [ ] **Step 3: Run red tests**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_self_validation.py tests/scripts/test_visual_phase2_self_check.py -q
```

Expected: FAIL because self-validation is missing.

- [ ] **Step 4: Implement self-validation**

Checks:

- ledger schema includes Phase 1 and Phase 2 tables;
- every selected artifact is fresh, stable, and has source metadata;
- sent deliveries have no duplicate artifact hash per destination/request;
- every ranked candidate has deterministic score, reward score, and confidence;
- active-learning decision exists for package requests;
- shadow updates are not active unless activation gate is explicitly enabled;
- reports are request-scoped when `request_id` is provided.

- [ ] **Step 5: Verify and commit**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_self_validation.py tests/scripts/test_visual_phase2_self_check.py -q
rtk ./venv/bin/python scripts/visual_phase2_self_check.py --fixture --json
rtk ./venv/bin/python -m ruff check agent/visual/self_validation.py scripts/visual_phase2_self_check.py tests/visual/test_self_validation.py tests/scripts/test_visual_phase2_self_check.py
rtk git diff --check
rtk git add agent/visual/self_validation.py scripts/visual_phase2_self_check.py tests/visual/test_self_validation.py tests/scripts/test_visual_phase2_self_check.py
rtk git commit -m "feat: add visual phase2 self check"
```

## Milestone 10: Shadow-Mode Runtime Rollout

**Purpose:** Run learning in production evidence mode while keeping behavior conservative.

**Files:**

- Modify: `tools/visual_package_tool.py`
- Modify: `scripts/visual_evidence_report.py`
- Modify: `scripts/visual_evidence_self_smoke.py`
- Test: `tests/tools/test_visual_package_tool.py`
- Test: `tests/scripts/test_visual_evidence_self_smoke.py`

**Interfaces:**

- `visual_package_generate` writes:
  - strategy plan metadata;
  - reward scores;
  - active-learning decision;
  - shadow update proposals.

- [ ] **Step 1: Write failing runtime shadow test**

```python
@pytest.mark.asyncio
async def test_visual_package_records_shadow_learning_but_keeps_delivery_selected_only(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "image.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    monkeypatch.setattr(
        visual_package_tool,
        "generate_image",
        lambda **kwargs: {"success": True, "image": str(image), "provider": "fixture", "model": "image"},
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {"prompt": "請產出一張圖片：霧黑鋼筆。", "include_video": False}
        )
    )

    assert payload["success"] is True
    assert payload["rankings"]["image"]["decision"] in {"post", "ask_user"}
    assert payload["delivery_metadata"]["selected_visual_artifact_ids"]
    assert payload["learning"]["mode"] == "shadow"
```

- [ ] **Step 2: Run red test**

```bash
rtk ./venv/bin/python -m pytest tests/tools/test_visual_package_tool.py::test_visual_package_records_shadow_learning_but_keeps_delivery_selected_only -q
```

Expected: FAIL because package tool does not yet write learning metadata.

- [ ] **Step 3: Wire package tool shadow mode**

Default behavior:

- production delivery remains selected-only;
- strategy plan and reward traces are recorded;
- active-learning action may decide `auto_post`, `auto_retry`, `ask_user`, or `fail_closed`;
- learning mode remains `shadow`;
- no prompt mutation is activated.

- [ ] **Step 4: Verify and commit**

```bash
rtk ./venv/bin/python -m pytest tests/visual tests/tools/test_visual_package_tool.py tests/scripts/test_visual_evidence_self_smoke.py -q
rtk ./venv/bin/python scripts/visual_evidence_self_smoke.py --json
rtk ./venv/bin/python scripts/visual_phase2_self_check.py --fixture --json
rtk ./venv/bin/python -m ruff check agent/visual tools/visual_package_tool.py scripts/visual_evidence_self_smoke.py scripts/visual_evidence_report.py
rtk git diff --check
rtk git add tools/visual_package_tool.py scripts/visual_evidence_report.py scripts/visual_evidence_self_smoke.py tests/tools/test_visual_package_tool.py tests/scripts/test_visual_evidence_self_smoke.py
rtk git commit -m "feat: run visual learning in shadow mode"
```

## Milestone 11: Live Runtime Proof Without Routine Human Review

**Purpose:** Prove Phase 2 can self-check a live request and reduce manual intervention.

**Files:**

- No production code expected.
- Update: `docs/plans/2026-06-21-visual-self-verifying-learning-phase2.md`

**Steps:**

- [ ] **Step 1: Restart gateway**

```bash
rtk hermes gateway restart
rtk hermes gateway status
rtk hermes cron status
```

Expected: gateway running and Slack connected.

- [ ] **Step 2: Run provider smoke**

```bash
rtk hermes chat -Q --max-turns 1 -q "Reply exactly: OK"
```

Expected: `OK`.

- [ ] **Step 3: Run low-risk live visual package request**

Use Slack or direct tool path with a low-risk product prompt:

```text
請產出一張圖片和一段影片：一支霧黑鋼筆放在白紙上，柔和窗光，乾淨產品攝影。完成後直接貼在 Slack。
```

Expected:

- one selected image and one selected video;
- no old media repost;
- no duplicate delivery;
- active-learning decision recorded;
- shadow learning proposal recorded;
- no user review required if confidence passes threshold.

- [ ] **Step 4: Run request-scoped self-check**

```bash
rtk ./venv/bin/python scripts/visual_evidence_report.py --request-id <visual_request_id> --json
rtk ./venv/bin/python scripts/visual_phase2_self_check.py --request-id <visual_request_id> --json
rtk ./venv/bin/python scripts/visual_shadow_learning_report.py --request-id <visual_request_id> --json
```

Expected:

- all reports return `success: true`;
- duplicate delivery count `0`;
- missing source metadata count `0`;
- reward trace present for selected candidates;
- learning mode remains `shadow`.

- [ ] **Step 5: Commit closeout and push**

```bash
rtk git add docs/plans/2026-06-21-visual-self-verifying-learning-phase2.md
rtk git commit -m "docs: close visual self-verifying phase2 rollout"
rtk git push origin upgrade/hermes-v2026.6.19-local
```

## Promotion Gate From Shadow to Controlled Autonomy

Do not enable production prompt mutation until all gates pass:

- At least `20` real visual requests with Phase 2 traces.
- At least `5` requests in the target intent bucket.
- Request-scoped self-check success rate >= `95%`.
- Duplicate/stale delivery incidents = `0`.
- Provider failure classification coverage >= `90%`.
- Shadow policy expected improvement positive for at least `3` consecutive reports.
- No high-confidence regression in user feedback.
- User explicitly approves moving one strategy bucket from `shadow` to `controlled`.

Controlled autonomy still requires rollback:

- feature flag can disable Phase 2 learning immediately;
- active strategy version is recorded per request;
- previous strategy version can be restored without data migration.

## Final Acceptance Criteria

- Phase 2 has a documented, tested self-validation gate.
- Normal users can trigger visual package mode with natural language.
- Candidate sets are generated and ranked before delivery.
- Hermes can auto-post high-confidence selected artifacts without asking the user.
- Hermes asks the user only on low confidence, reference uncertainty, ambiguous failure, or conflicting preferences.
- Reward traces keep provider reliability separate from aesthetic preference.
- Preference profiles update from sparse feedback but do not mutate production prompts by default.
- Shadow learning proposes strategy changes with evidence and confidence.
- Request-scoped reports prove no stale/duplicate delivery and no missing source metadata.
- Runtime-private data remains untracked.
- All milestones are committed and pushed to `origin`.

## Self-Review

- Spec coverage: this plan covers Phase 2 learning, self-validation, automatic scoring, candidate ranking, active-learning gates, shadow-mode safety, and reduced human intervention.
- Placeholder scan: no unresolved placeholder markers or unspecified acceptance gate is intentionally left.
- Type consistency: Phase 2 modules consume existing Phase 1 ledger/ranker/tool contracts and add versioned interfaces for scores, policies, rewards, and self-checks.
