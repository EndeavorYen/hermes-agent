# Visual Phase 7-10 Self-Improving Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Phase 4-6 foundation into a practical self-improving visual agent loop that can judge real artifacts, select only the best current outputs, repair provider failures, deliver correctly to Slack, and learn from evidence with much less human intervention.

**Architecture:** Phase 7 upgrades quality judging from metadata-only scoring to artifact-aware scoring with calibrated vision observations. Phase 8 moves ranking and negotiation before delivery so weak, stale, duplicate, or policy-failed candidates are repaired or suppressed before the user sees them. Phase 9 proves the real Slack delivery contract end-to-end. Phase 10 closes the loop by extracting reusable strategy signals from ledger evidence while keeping autonomous prompt mutation disabled until controlled gates prove enough confidence.

**Tech Stack:** Python 3.11, SQLite, existing `agent.visual` modules, `tools/visual_package_tool.py`, gateway/Slack delivery surfaces, pytest, ruff, `scripts/visual_regression_report.py`, `scripts/visual_evidence_self_smoke.py`, runtime-private Visual Attempt Ledger.

## Phase 7-10 Completion Objective

Phase 7-10 are complete only when Hermes can run the visual package path with materially less manual intervention:

- It can judge generated image/video artifacts with evidence beyond metadata-only checks.
- It can suppress weak, stale, duplicate, failed, or unselected candidates before Slack delivery.
- It can negotiate one bounded provider repair attempt when a provider rejects, times out, returns empty output, or cannot honor reference/aspect settings.
- It can post selected current images/videos to Slack automatically without requiring a second user prompt.
- It can derive video aspect settings from the actual source media when available.
- It can produce privacy-safe learning proposals from ledger evidence while keeping prompt mutation disabled.
- It can explain what was selected, what was suppressed, what was retried, and what remains shadow-only.

The target is not to make every generated image excellent. The target is to make Hermes measurably better at avoiding known failure modes, choosing the best current candidate, recovering from provider failures, and learning from evidence without relying on the user to review every round.

## Self-Assessment and Improvement Contract

Every phase must end with a written self-assessment and at least one concrete improvement decision.

The self-assessment must include:

- `proven`: exact tests, reports, or runtime ledger checks that passed.
- `not_proven`: user-facing behavior that is still unverified.
- `quality_delta`: whether the phase should reduce human intervention, and why.
- `regression_risks`: stale media, duplicate delivery, wrong aspect ratio, prompt mutation, provider-policy confusion, or privacy leakage risks still present.
- `improvement_action`: one of `fix_now`, `carry_to_next_phase`, or `documented_defer`, with a concrete reason.
- `rollback_path`: how to disable or revert the behavior if live output regresses.

If self-assessment finds a failed acceptance gate, the phase is not complete. The worker must either fix it immediately or explicitly move the incomplete item into the next phase with a testable follow-up task. Reporting a weakness without an action is not accepted.

## Global Constraints

- Base branch: `upgrade/hermes-v2026.6.19-local`.
- Push local integration work to `origin` only unless an explicit upstream PR workflow is requested.
- Use TDD for every behavior change; write the failing test first, run it, implement the smallest fix, then re-run.
- Runtime-private data stays under `/Users/simon/.hermes`; do not commit raw prompts, generated media, local network endpoints, tokens, provider responses, or user preference corpora.
- User intent is the target; prompts are negotiable interfaces; provider output is evidence.
- Provider reliability, delivery correctness, safety status, and aesthetic preference remain separate tracks.
- No stale prior-round media may be delivered.
- No duplicate artifact may be delivered even when a provider returns different filenames or URLs for the same content.
- Normal users must not need `autonomy_level`, `candidate_budget`, or `video_budget`.
- Prompt mutation remains disabled unless a later controlled activation explicitly enables it.
- Metadata hygiene may strip local filesystem, camera, GPS, cache, and private provenance metadata from deliverables; it must not remove required compliance or license information.
- Remote Qwen and zimage remain optional/pass-through; these phases must work when they are off.

---

## Phase 7 Goal: Artifact-Aware Quality Judges

Replace the current metadata-only judge with an artifact-aware scoring layer that can consume bounded vision observations for images and videos. This phase does not train a model. It creates a strict adapter boundary so Hermes can use local or routed vision analysis later without leaking raw prompts or committing private media.

### Task 7.1: Vision Observation Contract

**Files:**

- Create: `agent/visual/judges/vision_observation.py`
- Modify: `agent/visual/judges/__init__.py`
- Test: `tests/visual/test_vision_observation.py`

**Interfaces:**

- Produces:
  - `normalize_vision_observation(observation: dict[str, Any]) -> dict[str, Any]`
  - `empty_vision_observation(reason: str) -> dict[str, Any]`

**Implementation Requirements:**

- Accepted normalized keys:
  - `subject_quality`
  - `reference_adherence`
  - `composition`
  - `visual_appeal`
  - `glamour_impact`
  - `product_appeal`
  - `aspect_integrity`
  - `motion_quality`
  - `artifact_defects`
  - `confidence`
  - `evidence`
- Clamp all numeric dimensions to `0.0..1.0`.
- Drop unknown keys.
- Never store raw prompt text, private file paths, or provider response bodies in `evidence`.

- [ ] **Step 1: Write failing normalization tests**

```python
def test_normalize_vision_observation_clamps_scores_and_drops_unknowns():
    result = normalize_vision_observation(
        {
            "subject_quality": 1.7,
            "composition": -0.2,
            "artifact_defects": ["blurred_face", "extra_fingers"],
            "raw_prompt": "private prompt text",
            "unknown": "drop me",
            "confidence": 0.8,
            "evidence": {"summary": "clear subject, no stretch"},
        }
    )

    assert result["subject_quality"] == 1.0
    assert result["composition"] == 0.0
    assert result["artifact_defects"] == ["blurred_face", "extra_fingers"]
    assert result["confidence"] == 0.8
    assert result["evidence"] == {"summary": "clear subject, no stretch"}
    assert "raw_prompt" not in result
    assert "unknown" not in result
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_vision_observation.py -q
```

Expected: fail because `agent.visual.judges.vision_observation` does not exist.

- [ ] **Step 3: Implement the normalization module**

Implement the exact public functions listed above. Keep it pure: no filesystem reads, no provider calls, no ledger writes.

- [ ] **Step 4: Re-run targeted tests**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_vision_observation.py -q
rtk ./venv/bin/python -m ruff check agent/visual/judges/vision_observation.py tests/visual/test_vision_observation.py
```

- [ ] **Step 5: Commit**

```bash
rtk git add agent/visual/judges/vision_observation.py agent/visual/judges/__init__.py tests/visual/test_vision_observation.py
rtk git commit -m "feat: add visual observation contract"
```

### Task 7.2: Artifact-Aware Quality Merge

**Files:**

- Modify: `agent/visual/judges/quality.py`
- Test: `tests/visual/test_quality_judges.py`

**Interfaces:**

- Modifies:
  - `judge_visual_quality(candidate, *, request_context=None, recent_artifact_hashes=None, vision_observation=None) -> dict[str, Any]`

**Implementation Requirements:**

- Merge deterministic metadata and normalized vision observations.
- Use vision observations only when present and confidence is non-zero.
- Keep hard gates dominant: failed hard gate keeps `delivery_readiness` low and verdict review/fail.
- Penalize:
  - stretched video or image aspect mismatch;
  - blurred/distorted faces when the request is portrait/character/fashion;
  - duplicate hash or duplicate source URL;
  - missing reference evidence when the request has reference images.
- Return `judge_sources` showing which dimensions came from `deterministic`, `vision`, or `fallback`.

- [ ] **Step 1: Write failing tests for vision merge**

```python
def test_quality_judge_uses_vision_observation_without_leaking_prompt():
    candidate = {
        "artifact_id": "var_1",
        "kind": "image",
        "hard_gate": {"passed": True, "delivery_possible": True},
        "scores": {"resolution": 0.6, "aspect_match": 0.7, "final_score": 0.6},
    }

    result = judge_visual_quality(
        candidate,
        request_context={"has_reference_image": True, "category": "fashion"},
        vision_observation={
            "reference_adherence": 0.9,
            "visual_appeal": 0.8,
            "composition": 0.85,
            "aspect_integrity": 0.95,
            "confidence": 0.75,
            "evidence": {"summary": "same subject, clean pose"},
            "raw_prompt": "must not appear",
        },
    )

    assert result["scores"]["reference_adherence"] == 0.9
    assert result["scores"]["aesthetic_fit"] >= 0.75
    assert result["scores"]["composition"] == 0.85
    assert result["judge_sources"]["reference_adherence"] == "vision"
    assert "raw_prompt" not in str(result)
```

- [ ] **Step 2: Run failing tests**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_quality_judges.py -q
```

Expected: fail because `vision_observation` is not accepted.

- [ ] **Step 3: Implement merge logic**

Keep `judge_visual_quality()` backward-compatible for existing callers. Add only the new keyword argument.

- [ ] **Step 4: Re-run tests**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_quality_judges.py tests/visual/test_reward_model.py -q
rtk ./venv/bin/python -m ruff check agent/visual/judges/quality.py tests/visual/test_quality_judges.py
```

- [ ] **Step 5: Commit**

```bash
rtk git add agent/visual/judges/quality.py tests/visual/test_quality_judges.py
rtk git commit -m "feat: merge vision observations into visual quality"
```

### Task 7.3: Calibration Report

**Files:**

- Create: `agent/visual/calibration.py`
- Create: `scripts/visual_quality_calibration_report.py`
- Test: `tests/visual/test_calibration.py`
- Test: `tests/scripts/test_visual_quality_calibration_report.py`

**Interfaces:**

- Produces:
  - `build_quality_calibration_report(db_path: str | Path) -> dict[str, Any]`

**Implementation Requirements:**

- Read `visual_judgments`, `visual_feedback`, `visual_artifacts`, and `visual_rankings` when present.
- Report privacy-safe aggregates:
  - total judged artifacts;
  - average judge confidence;
  - low-confidence count;
  - human-positive count;
  - human-negative count;
  - judge/human agreement count;
  - disagreement count;
  - top uncertainty reasons.
- Missing tables return zero-count success, not a crash.
- No raw prompts or media paths in output.

**Verification:**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_calibration.py tests/scripts/test_visual_quality_calibration_report.py -q
rtk ./venv/bin/python scripts/visual_quality_calibration_report.py --json
rtk ./venv/bin/python -m ruff check agent/visual/calibration.py scripts/visual_quality_calibration_report.py tests/visual/test_calibration.py tests/scripts/test_visual_quality_calibration_report.py
rtk git diff --check
```

**Phase 7 Self-Review Gate:**

- Did artifact-aware scoring improve quality evidence beyond metadata?
- Are judge scores explainable without raw prompt leakage?
- Does disagreement lower confidence instead of hiding uncertainty?
- Can the report show judge/human alignment without exposing private media?
- Does this phase reduce human review load only when confidence is high?

### Phase 7 Execution Status: 2026-06-21

Implemented:

- `agent/visual/judges/vision_observation.py`
  - Normalizes bounded vision observations.
  - Clamps numeric dimensions.
  - Drops unknown fields and private evidence keys.
  - Exposes `normalize_vision_observation()` and `empty_vision_observation()` from `agent.visual.judges`.
- `agent/visual/judges/quality.py`
  - Accepts optional `vision_observation`.
  - Merges vision dimensions into existing quality scores.
  - Adds `judge_sources` so score provenance is explicit.
  - Penalizes portrait/fashion/character defects such as blurred faces.
- `agent/visual/calibration.py`
  - Builds a privacy-safe calibration report over judgments and human feedback.
  - Reports agreement, disagreement, low-confidence counts, and uncertainty reasons.
- `scripts/visual_quality_calibration_report.py`
  - Adds CLI report support for local/runtime ledger checks.

Self-assessment:

- `proven`: `tests/visual/test_vision_observation.py`, `tests/visual/test_quality_judges.py`, `tests/visual/test_calibration.py`, `tests/visual/test_reward_model.py`, `tests/tools/test_visual_package_tool.py`, `tests/scripts/test_visual_quality_calibration_report.py`, and `tests/scripts/test_visual_regression_report.py` passed.
- `proven`: `scripts/visual_quality_calibration_report.py --json` and `scripts/visual_regression_report.py --json` passed against the runtime ledger.
- `not_proven`: live provider vision analysis is not wired yet; Phase 7 accepts artifact-aware observations but does not call a vision provider by itself.
- `quality_delta`: should reduce human review only after a caller supplies vision observations; without observations it remains backward-compatible metadata scoring.
- `regression_risks`: low risk for prompt leakage because tests assert raw prompt removal; remaining risk is under-scoring when no vision observations are present.
- `improvement_action`: `carry_to_next_phase`; Phase 8 should consume these richer judge scores before pre-delivery retry/suppression decisions.
- `rollback_path`: callers can omit `vision_observation`; quality judge then falls back to prior deterministic behavior.

---

## Phase 8 Goal: Pre-Delivery Ranking and Negotiated Repair

Move selection, repair, and retry decisions before Slack delivery. The user should see fewer weak outputs, fewer duplicate/stale files, and more useful retry behavior when providers reject or distort a request.

### Task 8.1: Provider Failure Classifier

**Files:**

- Create: `agent/visual/provider_failures.py`
- Test: `tests/visual/test_provider_failures.py`

**Interfaces:**

- Produces:
  - `classify_visual_provider_failure(payload: dict[str, Any] | Exception) -> dict[str, Any]`

**Failure Classes:**

- `content_moderation`
- `timeout`
- `empty_response`
- `unsupported_reference`
- `unsupported_aspect_ratio`
- `rate_limited`
- `provider_unavailable`
- `unknown`

**Implementation Requirements:**

- Preserve provider-vs-aesthetic separation.
- Extract safe fields only:
  - `failure_class`
  - `retryable`
  - `safe_reframe_allowed`
  - `provider_message_code`
  - `operator_summary`
- Do not store full provider error bodies.

**Verification:**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_provider_failures.py -q
rtk ./venv/bin/python -m ruff check agent/visual/provider_failures.py tests/visual/test_provider_failures.py
```

### Task 8.2: Negotiated Retry Planner

**Files:**

- Create: `agent/visual/recovery.py`
- Test: `tests/visual/test_recovery.py`

**Interfaces:**

- Produces:
  - `plan_visual_recovery(request: dict[str, Any], failure: dict[str, Any], *, retry_budget_remaining: int) -> dict[str, Any]`

**Implementation Requirements:**

- For `content_moderation`, propose safer framing only when `safe_reframe_allowed` is true.
- For `unsupported_reference`, switch to text-only or alternate provider only when the request allows losing reference conditioning.
- For `unsupported_aspect_ratio`, recompute aspect from source media through `agent.visual.aspect_policy`.
- For `timeout`, reduce budget or duration before retrying.
- For `empty_response`, retry once with simpler prompt and same intent.
- Never bypass provider policy or generate disallowed content.

**Expected Recovery Decision Shape:**

```python
{
    "decision": "retry" | "ask_user" | "fail",
    "reason": "content_moderation_safe_reframe",
    "modified_arguments": {"duration": 5},
    "user_visible_summary": "Provider rejected the first attempt; retrying a safer feasible variant.",
    "audit": {"failure_class": "content_moderation", "retry_budget_remaining": 1},
}
```

**Verification:**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_recovery.py tests/visual/test_aspect_policy.py -q
rtk ./venv/bin/python -m ruff check agent/visual/recovery.py tests/visual/test_recovery.py
```

### Task 8.3: Package Tool Repair Loop

**Files:**

- Modify: `tools/visual_package_tool.py`
- Test: `tests/tools/test_visual_package_tool.py`

**Implementation Requirements:**

- Record failed image/video attempts with classified failure details.
- Apply one negotiated retry per modality when planner returns `decision="retry"`.
- Keep retry evidence in `generation_payloads` and ledger metadata.
- If retry succeeds, rank the retry candidate normally.
- If retry fails, return `package_status="partial"` or `failed` with a clear structured reason.
- Do not deliver failed or unselected artifacts.

**Verification:**

```bash
rtk ./venv/bin/python -m pytest tests/tools/test_visual_package_tool.py tests/visual/test_provider_failures.py tests/visual/test_recovery.py -q
rtk ./venv/bin/python scripts/visual_regression_report.py --json
rtk ./venv/bin/python -m ruff check tools/visual_package_tool.py agent/visual/provider_failures.py agent/visual/recovery.py tests/tools/test_visual_package_tool.py
rtk git diff --check
```

### Task 8.4: Pre-Delivery Selection Report

**Files:**

- Create: `agent/visual/selection_report.py`
- Create: `scripts/visual_selection_report.py`
- Test: `tests/visual/test_selection_report.py`
- Test: `tests/scripts/test_visual_selection_report.py`

**Implementation Requirements:**

- For the latest or specified request, report:
  - generated candidate count;
  - selected artifact ids;
  - suppressed stale artifact count;
  - suppressed duplicate count;
  - retry count;
  - failure classes;
  - top rank reasons;
  - ask-user reason when not auto-delivered.
- Privacy-safe output only.

**Phase 8 Self-Review Gate:**

- Are provider failures classified separately from aesthetic failures?
- Does retry negotiation preserve user intent while respecting provider policy?
- Are stale/duplicate/failed candidates suppressed before delivery?
- Does retry improve success without hiding compromise?
- Can the user understand what changed when Hermes returns a compromised version?

### Phase 8 Execution Status: 2026-06-21

Implemented:

- `agent/visual/provider_failures.py`
  - Classifies provider failures into content moderation, timeout, empty response, unsupported reference, unsupported aspect ratio, rate limited, provider unavailable, and unknown.
  - Emits safe operator summaries without raw provider bodies.
- `agent/visual/recovery.py`
  - Plans bounded recovery decisions.
  - Supports content-moderation safe reframing, timeout work reduction, unsupported aspect-ratio repair from source dimensions, and empty-response simplification.
  - Fails closed when retry budget is exhausted or the failure is not retryable.
- `tools/visual_package_tool.py`
  - Annotates failed generation attempts with `failure` and `recovery` metadata before writing the ledger.
  - Performs one bounded retry per failed image/video candidate when recovery returns `decision="retry"`.
  - Ranks only successful retry candidates.
- `agent/visual/selection_report.py`
  - Reports selected artifacts, generated candidates, stale suppression, duplicate suppression, retry count, failure classes, and rank decisions.
- `scripts/visual_selection_report.py`
  - Adds CLI support for runtime selection-report inspection.

Self-assessment:

- `proven`: `tests/visual/test_provider_failures.py`, `tests/visual/test_recovery.py`, `tests/visual/test_selection_report.py`, `tests/tools/test_visual_package_tool.py`, `tests/scripts/test_visual_selection_report.py`, and `tests/scripts/test_visual_regression_report.py` passed.
- `proven`: `scripts/visual_selection_report.py --json` and `scripts/visual_regression_report.py --json` passed against the runtime ledger.
- `not_proven`: live provider retry quality is not yet proven; the retry loop is fixture-proven and ledger-visible.
- `quality_delta`: should reduce manual intervention for empty responses, timeouts, and aspect mismatch because Hermes can retry or report compromise without user input.
- `regression_risks`: safe reframing may still be too conservative or too generic; Phase 9 must prove delivery does not expose failed/unselected attempts.
- `improvement_action`: `carry_to_next_phase`; Phase 9 must use selected-artifact manifests so repaired candidates are delivered while failed attempts remain suppressed.
- `rollback_path`: disable retry by setting `retry_budget_remaining=0` in the package tool recovery call; failures will record metadata but no automatic retry will run.

---

## Phase 9 Goal: Slack Delivery End-to-End Contract

Prove the real user-facing contract: when Hermes generates visual media from Slack, it posts only the current selected image/video artifacts automatically, with correct aspect handling and without repeating prior-round outputs.

### Task 9.1: Delivery Manifest

**Files:**

- Create: `agent/visual/delivery_manifest.py`
- Modify: `agent/visual/tracking.py`
- Test: `tests/visual/test_delivery_manifest.py`
- Test: `tests/visual/test_tracking.py`

**Interfaces:**

- Produces:
  - `build_visual_delivery_manifest(package_payload: dict[str, Any]) -> dict[str, Any]`
  - `select_deliverable_artifacts(manifest: dict[str, Any]) -> list[dict[str, Any]]`

**Implementation Requirements:**

- Manifest includes selected image/video artifacts only.
- Manifest excludes artifacts not in `selected_visual_artifact_ids`.
- Manifest includes stable identity:
  - artifact id;
  - kind;
  - content hash or remote source identity;
  - local path or URL;
  - request id;
  - media dimensions when available.
- Local files are preferred for packaged delivery when available.
- Remote URL fallback remains allowed for provider-hosted videos.

**Verification:**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_delivery_manifest.py tests/visual/test_tracking.py -q
rtk ./venv/bin/python -m ruff check agent/visual/delivery_manifest.py agent/visual/tracking.py tests/visual/test_delivery_manifest.py tests/visual/test_tracking.py
```

### Task 9.2: Gateway/Slack Auto-Delivery Hook

**Files:**

- Modify: `gateway/run.py`
  - `_deliver_media_from_response()`
  - background-task media extraction path near the `# Extract media files from the response` comment
- Modify: `gateway/platforms/base.py`
  - final response media extraction and send flow near `extract_media(response)`
  - native media batching through `send_multiple_images()` / `send_video()`
- Modify: `gateway/platforms/slack.py`
  - `SlackAdapter.send_multiple_images()`
  - `SlackAdapter.send_video()`
- Test: `tests/gateway/test_media_extraction.py`
- Test: `tests/gateway/test_run_tool_media_re.py`
- Test: `tests/gateway/test_run_progress_topics.py`
- Test: `tests/gateway/test_send_multiple_images.py`
- Test: `tests/gateway/test_slack.py`

**Implementation Requirements:**

- When a tool result contains a visual delivery manifest, the gateway sends those media files/URLs automatically.
- The final text may summarize status, but media should not require a second user prompt.
- If both local file and remote URL exist, local file is selected for images; remote URL remains acceptable for provider-hosted video when no local file exists.
- Delivery records are written through `record_visual_delivery_status()`.
- Duplicate suppression uses artifact identity, not filename.

**Required Tests:**

- Slack image-only package sends one selected current image.
- Slack image-plus-video package sends one selected image and one selected video when both are selected.
- Prior-round artifacts present in payload metadata are not sent.
- Two video URLs with the same source identity are sent once.
- A failed video with successful image returns partial success and sends only the image.

**Verification:**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_delivery_manifest.py tests/gateway -q
rtk ./venv/bin/python scripts/visual_regression_report.py --json
rtk ./venv/bin/python -m ruff check agent/visual gateway tests/visual tests/gateway
rtk git diff --check
```

### Task 9.3: Aspect-Ratio and Metadata Hygiene Gate

**Files:**

- Modify: `agent/visual/aspect_policy.py`
- Create: `agent/visual/metadata_hygiene.py`
- Test: `tests/visual/test_aspect_policy.py`
- Test: `tests/visual/test_metadata_hygiene.py`

**Implementation Requirements:**

- Derive video aspect settings from source image dimensions when an image is supplied.
- If source dimensions are unknown, use user-requested aspect when present.
- If neither exists, use provider default without hard-coding a stretched transform.
- Metadata hygiene removes local path, GPS, camera, filesystem, and cache metadata from deliverable copies when copies are created.
- Metadata hygiene does not alter pixel aspect ratio.
- Metadata hygiene does not remove required compliance/license information.

**Verification:**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_aspect_policy.py tests/visual/test_metadata_hygiene.py -q
rtk ./venv/bin/python -m ruff check agent/visual/aspect_policy.py agent/visual/metadata_hygiene.py tests/visual/test_metadata_hygiene.py
```

**Phase 9 Self-Review Gate:**

- Does Slack receive media automatically after visual generation?
- Are only current selected artifacts delivered?
- Are duplicates suppressed by content/source identity?
- Is aspect ratio derived from actual source media when possible?
- Does metadata hygiene protect privacy without corrupting media or removing required compliance data?

### Phase 9 Execution Status: 2026-06-21

Implemented:

- `agent/visual/delivery_manifest.py`
  - Builds a selected-artifact delivery manifest from `visual_package_generate` payloads.
  - Deduplicates deliverables by content/source identity.
  - Excludes unselected prior-round artifacts.
- `gateway/run.py`
  - Adds `visual_package_generate` to the current-turn tool-result auto-append allowlist.
  - Converts selected local package deliverables into `MEDIA:` tags for existing gateway native media delivery.
- `agent/visual/aspect_policy.py`
  - Adds `select_video_aspect_ratio()`.
  - Prefers source media dimensions over requested aspect ratio when generating video from an image.
- `tools/visual_package_tool.py`
  - Uses selected source-image dimensions to choose video aspect ratio.
- `agent/visual/metadata_hygiene.py`
  - Sanitizes private local/GPS/camera/cache metadata while preserving dimensions, content hash, license, and compliance data.

Self-assessment:

- `proven`: `tests/visual/test_delivery_manifest.py`, `tests/gateway/test_media_extraction.py`, `tests/visual/test_aspect_policy.py`, `tests/visual/test_metadata_hygiene.py`, `tests/tools/test_visual_package_tool.py`, and `tests/scripts/test_visual_regression_report.py` passed.
- `proven`: `scripts/visual_regression_report.py --json` passed against the runtime ledger.
- `not_proven`: live Slack upload was not executed in this phase; the gateway extraction path is unit-proven and uses the existing media delivery pipeline.
- `quality_delta`: should reduce stale/duplicate delivery because only selected manifest deliverables are converted to `MEDIA:` tags.
- `regression_risks`: provider-hosted remote video URLs are preserved in payloads but not yet downloaded/packaged for Slack native upload.
- `improvement_action`: `carry_to_next_phase`; Phase 10 learning should observe delivery outcomes, and a later refinement should add optional remote-video download/package support.
- `rollback_path`: remove `visual_package_generate` from `_AUTO_APPEND_MEDIA_TOOL_NAMES`; package payloads will still return selected artifacts but gateway will stop auto-appending media tags.

---

## Phase 10 Goal: Self-Reinforcing Learning Loop v1

Use ledger evidence, judge scores, provider outcomes, and sparse human feedback to improve strategy selection automatically. Phase 10 still does not train a generative model and still does not allow uncontrolled prompt mutation.

### Task 10.1: Strategy Outcome Aggregator

**Files:**

- Create: `agent/visual/learning/outcomes.py`
- Create: `agent/visual/learning/__init__.py`
- Test: `tests/visual/test_learning_outcomes.py`

**Interfaces:**

- Produces:
  - `aggregate_visual_strategy_outcomes(db_path: str | Path, *, bucket: str | None = None) -> dict[str, Any]`

**Implementation Requirements:**

- Aggregate by intent signature and strategy signature.
- Separate tracks:
  - provider health;
  - delivery correctness;
  - quality judge performance;
  - human feedback;
  - retry effectiveness;
  - ask-user rate.
- Output confidence from sample size and disagreement.
- Do not combine provider success with aesthetic preference into one untraceable score.

**Verification:**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_learning_outcomes.py -q
rtk ./venv/bin/python -m ruff check agent/visual/learning tests/visual/test_learning_outcomes.py
```

### Task 10.2: Policy Update Proposer

**Files:**

- Create: `agent/visual/learning/proposals.py`
- Test: `tests/visual/test_learning_proposals.py`

**Interfaces:**

- Produces:
  - `propose_visual_policy_updates(outcomes: dict[str, Any]) -> list[dict[str, Any]]`

**Implementation Requirements:**

- Allowed proposal types:
  - `prefer_strategy`
  - `avoid_strategy`
  - `prefer_provider_for_bucket`
  - `avoid_provider_for_bucket`
  - `increase_candidate_budget`
  - `reduce_video_duration`
  - `ask_user_sooner`
- Disallowed proposal types:
  - raw prompt rewriting;
  - policy bypass;
  - hidden content-rule weakening;
  - unbounded budget increases.
- Every proposal includes:
  - `bucket`
  - `strategy_signature`
  - `confidence`
  - `evidence_counts`
  - `reason`
  - `activation_status="shadow"`

**Verification:**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_learning_proposals.py tests/visual/test_strategy_policy.py -q
rtk ./venv/bin/python -m ruff check agent/visual/learning/proposals.py tests/visual/test_learning_proposals.py
```

### Task 10.3: Controlled Activation Bridge

**Files:**

- Modify: `agent/visual/strategy_activation.py`
- Modify: `agent/visual/promotion_policy.py`
- Test: `tests/visual/test_strategy_activation.py`
- Test: `tests/visual/test_promotion_policy.py`

**Implementation Requirements:**

- Promotion from shadow proposal to controlled read-only strategy requires:
  - minimum request count;
  - minimum successful delivery count;
  - zero duplicate delivery failures in scope;
  - zero missing source metadata failures in scope;
  - no recent human veto;
  - judge/human disagreement below threshold;
  - explicit local config or operator approval.
- Controlled read-only may choose strategy/provider/budget within safe bounds.
- Controlled read-only must not mutate raw prompt text.
- Rollback disables strategy reads without deleting evidence.

**Verification:**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_strategy_activation.py tests/visual/test_promotion_policy.py tests/visual/test_strategy_policy.py -q
rtk ./venv/bin/python scripts/visual_strategy_activation_report.py --json
rtk ./venv/bin/python scripts/visual_regression_report.py --json
rtk ./venv/bin/python -m ruff check agent/visual/strategy_activation.py agent/visual/promotion_policy.py tests/visual/test_strategy_activation.py tests/visual/test_promotion_policy.py
```

### Task 10.4: Continuous Learning Report

**Files:**

- Create: `scripts/visual_learning_report.py`
- Test: `tests/scripts/test_visual_learning_report.py`

**Implementation Requirements:**

- Report:
  - bucket count;
  - strategy count;
  - top shadow proposals;
  - controlled strategy reads;
  - blocked promotions and reasons;
  - rollback count;
  - prompt mutation reads;
  - human-veto count;
  - ask-user rate.
- Exit code is `0` only when:
  - unsafe activation count is zero;
  - prompt mutation read count is zero;
  - duplicate delivery count is zero;
  - missing source metadata count is zero.
- Output is privacy-safe.

**Verification:**

```bash
rtk ./venv/bin/python -m pytest tests/scripts/test_visual_learning_report.py tests/visual/test_learning_outcomes.py tests/visual/test_learning_proposals.py -q
rtk ./venv/bin/python scripts/visual_learning_report.py --json
rtk ./venv/bin/python scripts/visual_regression_report.py --json
rtk ./venv/bin/python -m ruff check scripts/visual_learning_report.py tests/scripts/test_visual_learning_report.py
rtk git diff --check
```

**Phase 10 Self-Review Gate:**

- Does learning rely on evidence instead of self-delusion?
- Are provider health, delivery correctness, and aesthetic preference separated?
- Are proposals shadow-only until gates approve them?
- Is controlled activation reversible?
- Does the system reduce user review burden without silently changing prompts?

### Phase 10 Execution Status: 2026-06-21

Implemented:

- `agent/visual/learning/outcomes.py`
  - Aggregates strategy outcomes by intent bucket and strategy signature.
  - Separates provider health, delivery correctness, quality judge scores, human feedback, retry effectiveness, and ask-user rate.
  - Computes confidence from sample size, judge-human disagreement, and human veto pressure.
- `agent/visual/learning/proposals.py`
  - Emits shadow-only safe proposal types: prefer/avoid strategy, prefer/avoid provider, candidate-budget increase, duration reduction, and ask-user-sooner.
  - Rejects raw prompt rewriting and policy-bypass style mutations by construction.
- `agent/visual/promotion_policy.py`
  - Promotion gates now require successful delivery evidence.
  - Blocks judge-human disagreement, human vetoes, prompt mutation requests, duplicate delivery, missing source metadata, and failed self-validation.
- `agent/visual/strategy_activation.py`
  - Controlled activation rejects prompt mutation metadata and remains read-only.
- `scripts/visual_learning_report.py`
  - Reports bucket/strategy counts, shadow proposals, controlled reads, blocked promotions, rollback count, prompt mutation reads, human veto count, and ask-user rate.
  - Fails closed on unsafe activations, prompt mutation reads, duplicate deliveries, or missing source metadata.

Self-assessment:

- `proven`: Phase 10 tests passed for outcome aggregation, proposal generation, promotion gates, read-only activation, and privacy-safe learning report.
- `proven`: runtime ledger reports passed: `visual_learning_report.py --json`, `visual_strategy_activation_report.py --json`, `visual_regression_report.py --json`, `visual_evidence_self_smoke.py --json`, and `visual_quality_calibration_report.py --json`.
- `not_proven`: live provider-generated artifacts still have sparse judge rows in the runtime ledger (`judgments=0` in the current regression report), so the learning loop is operational but cannot yet create high-confidence aesthetic proposals from live history.
- `quality_delta`: Hermes can now reduce user review burden when enough evidence accumulates, without silently rewriting prompts or merging provider reliability into aesthetic preference.
- `regression_risks`: proposal thresholds are intentionally conservative; early usage may produce no proposals until more judged artifacts and feedback are recorded.
- `improvement_action`: next phase should wire provider/vision judging into live package generation so `judgments` are populated consistently, then calibrate proposal thresholds against actual Slack feedback.
- `rollback_path`: stop reading controlled strategies by disabling/removing controlled activations; shadow proposals remain evidence records and do not mutate prompts.

---

## Phase 7-10 Completion Criteria

- Phase 7 artifact-aware quality judging exists, is tested, and reports calibration against human feedback when available.
- Phase 8 provider failures are classified, negotiated retries are planned, and package generation can recover or fail clearly before delivery.
- Phase 9 Slack/gateway delivery posts only current selected media automatically and suppresses stale/duplicate outputs.
- Phase 10 self-reinforcing learning creates shadow proposals from evidence and can promote only safe controlled read-only strategy changes.
- All new outputs are privacy-safe and do not expose raw prompts, generated media, private endpoints, provider responses, tokens, or user preference corpora.
- Prompt mutation remains disabled by default and is detected by regression reports.
- `scripts/visual_regression_report.py --json`, `scripts/visual_evidence_self_smoke.py --json`, `scripts/visual_strategy_activation_report.py --json`, and the new Phase 7-10 reports all pass.
- Full visual test slice passes before push.
- Work is committed in phase-sized commits and pushed to `origin/upgrade/hermes-v2026.6.19-local`.

## Recommended Execution Order

1. Phase 7 first: improve scoring evidence before changing delivery behavior.
2. Phase 8 second: add repair and pre-delivery suppression while still using offline fixtures.
3. Phase 9 third: wire real Slack delivery after ranking/repair is stable.
4. Phase 10 last: learn from the improved evidence stream and keep activation shadow-first.

## Final Self-Assessment Standard

At the end of each phase, report:

- What was proven by tests.
- What was proven against the runtime ledger.
- What remains shadow-only.
- Whether human intervention should decrease in that phase.
- What rollback path exists if live behavior regresses.
- Whether the next phase can start without live provider access.

---

## Follow-Up Execution: Self-Verification and Learning Evidence Hardening

Date: 2026-06-21

Implemented:

- `scripts/visual_test_coverage_report.py`
  - Adds a runnable targeted line-coverage gate using Python stdlib `trace`.
  - Runs the relevant visual tests quietly, then executes deterministic probes for critical learning and validation modules.
  - Requires each target file to meet `min_line_coverage=0.70`.
- `scripts/visual_learning_replay.py`
  - Builds a privacy-safe fixture ledger with enough request, delivery, judgment, and feedback evidence to produce safe shadow proposals.
  - Verifies self-reinforcement can produce `prefer_strategy` and `prefer_provider_for_bucket` without prompt mutation or unsafe activation.
- `tools/visual_package_tool.py`
  - Quality judgments now carry learning metadata: intent signature, strategy signature, modality, judge sources, and uncertainty reasons.
- `scripts/visual_evidence_report.py`
  - Evidence reports now include `judgments.count`.
  - Missing optional tables are handled schema-tolerantly.
- `scripts/visual_evidence_self_smoke.py`
  - Fixture now records image and video judgments, proving the self-smoke path has learnable quality evidence.

Verification:

- `rtk ./venv/bin/python -m pytest ...` visual slice: `153 passed`.
- `rtk ./venv/bin/python -m ruff check ...`: passed.
- `rtk ./venv/bin/python scripts/visual_test_coverage_report.py --json`: passed.
  - `agent/visual/learning/outcomes.py`: `0.8611`
  - `agent/visual/learning/proposals.py`: `0.8272`
  - `agent/visual/promotion_policy.py`: `0.7436`
  - `agent/visual/strategy_activation.py`: `0.8824`
  - `agent/visual/judges/quality.py`: `0.9118`
  - `scripts/visual_learning_report.py`: `0.9167`
- `rtk ./venv/bin/python scripts/visual_learning_replay.py --json`: passed and produced safe shadow proposals.
- `rtk ./venv/bin/python scripts/visual_evidence_self_smoke.py --json`: passed with `judgments.count=2`.
- `rtk ./venv/bin/python scripts/visual_learning_report.py --json`: passed.
- `rtk ./venv/bin/python scripts/visual_regression_report.py --json`: passed.

Self-assessment:

- `improved`: self-verification now has a runnable targeted coverage gate without adding dependencies.
- `improved`: learning replay proves the self-reinforcement proposal path can work without live provider access or human intervention.
- `improved`: visual package candidate judgments now preserve enough metadata for later replay, calibration, and proposal attribution.
- `still_limited`: the current live runtime ledger still reports `judgments=0`; this means old/live history has not yet accumulated judged provider outputs, not that the new fixture path cannot write judgments.
- `next_improvement`: run real Slack visual-package tasks through the new path, then verify the runtime ledger `judgments` count rises and learning proposals appear from actual usage.
