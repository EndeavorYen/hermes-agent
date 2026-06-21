# Visual Phase 11-15 Autonomous Loop Implementation Plan

**Goal:** Make Hermes visual generation self-validating and self-improving so real image/video runs can be assessed, learned from, and repaired with minimal user-triggered verification.

**Architecture:** Keep providers as black-box generators. Add a post-generation validation layer that inspects the real ledger, enriches quality judgments with automated artifact observations, attributes sparse Slack-style feedback to artifacts, proposes controlled read-only rollout decisions, and hardens video prompts/aspect handling. Prompt mutation remains disallowed for strategy learning; provider-facing video motion hints are logged as generation parameters, not learned raw-prompt rewrites.

**Tech Stack:** Python 3.11, SQLite visual ledger, existing `agent.visual` modules, `visual_package_generate`, pytest, ruff.

## Global Constraints

- Use TDD for behavior changes.
- Do not require the user to manually inspect Slack output for validation.
- Do not push generated media, private prompts, provider tokens, or runtime cache artifacts.
- Keep autonomous learning evidence-led and shadow-first unless a controlled read-only gate passes.
- Do not allow uncontrolled prompt mutation.

## Phase 11: Post-Generation Autonomous Validation

**Objective:** Every visual package result should carry a machine-readable validation summary that says whether the run is acceptable, retryable, or needs user feedback.

**Files:**

- Create: `agent/visual/autonomous_validation.py`
- Modify: `tools/visual_package_tool.py`
- Test: `tests/visual/test_autonomous_validation.py`
- Test: `tests/tools/test_visual_package_tool.py`

**Acceptance:**

- Valid package with image/video, judgments, rankings, and learning traces returns `decision=accept`.
- Missing judgments or learning traces returns `decision=retry_or_rejudge`.
- Missing selected media returns `decision=retry_generation`.
- Validation is included in `visual_package_generate` output.

## Phase 12: Automated Artifact Observation for Quality Judging

**Objective:** Quality judging should use artifact-derived observation signals automatically, not wait for a human to describe visible defects.

**Files:**

- Create: `agent/visual/artifact_observation.py`
- Modify: `tools/visual_package_tool.py`
- Test: `tests/visual/test_artifact_observation.py`
- Test: `tests/tools/test_visual_package_tool.py`

**Acceptance:**

- Fresh high-resolution image yields positive composition/aspect/delivery observation.
- Duplicate or low-metadata video yields uncertainty reasons.
- `visual_quality_judge` receives `vision_observation` from package scoring.
- Judgments record `judge_sources` with vision-derived dimensions when available.

## Phase 13: Feedback Attribution v2

**Objective:** Sparse user feedback like `K2 face weird, legs good` should be attributed to the correct artifact without a bespoke manual step.

**Files:**

- Create: `agent/visual/feedback_attribution.py`
- Test: `tests/visual/test_feedback_attribution.py`

**Acceptance:**

- Feedback can bind by 1-based index, artifact label, or latest selected artifacts.
- Parsed polarity and issues are written to `visual_feedback`.
- Attribution metadata records the method and remains privacy-safe.

## Phase 14: Autonomous Controlled Rollout Candidates

**Objective:** Hermes should be able to decide which shadow proposals are eligible for controlled read-only rollout without asking the user to trigger each evaluation.

**Files:**

- Create: `agent/visual/autonomous_rollout.py`
- Create: `scripts/visual_autonomous_loop_report.py`
- Test: `tests/visual/test_autonomous_rollout.py`
- Test: `tests/scripts/test_visual_autonomous_loop_report.py`

**Acceptance:**

- Low-risk proposals may become `controlled_candidate` only with high evidence, zero vetoes, zero duplicate deliveries, and no prompt mutation.
- Risky proposals stay `shadow_only`.
- Report combines validation, learning, rollout candidates, and regression failures.
- Report fails closed on duplicate delivery, missing source metadata, unsafe activation, or prompt mutation reads.

## Phase 15: Video Hardening

**Objective:** Video generation should reduce stretched or slow-motion outputs by default using source aspect and motion hints.

**Files:**

- Create: `agent/visual/video_hardening.py`
- Modify: `tools/visual_package_tool.py`
- Test: `tests/visual/test_video_hardening.py`
- Test: `tests/tools/test_visual_package_tool.py`

**Acceptance:**

- Video aspect ratio follows the selected source image dimensions.
- Motion prompt adds natural real-time motion guidance unless already present.
- Slow/static video feedback maps to a retry recommendation.
- Video generation records enough validation metadata for the autonomous report.

## Verification Gates

- `rtk ./venv/bin/python -m pytest tests/visual/test_autonomous_validation.py tests/visual/test_artifact_observation.py tests/visual/test_feedback_attribution.py tests/visual/test_autonomous_rollout.py tests/visual/test_video_hardening.py -q`
- `rtk ./venv/bin/python -m pytest tests/tools/test_visual_package_tool.py tests/scripts/test_visual_autonomous_loop_report.py tests/scripts/test_visual_live_provider_e2e.py -q`
- Full visual slice from the Phase 7-10 plan.
- `rtk ./venv/bin/python -m ruff check agent/visual tools/visual_package_tool.py scripts/visual_autonomous_loop_report.py tests/visual tests/scripts/test_visual_autonomous_loop_report.py`
- `rtk git diff --check`

## Self-Review Standard

Each phase must report:

- What was proven by tests.
- What was proven against fixture/runtime ledger evidence.
- Whether the change reduces user intervention.
- What remains shadow-only.
- What failure would still require user input.
- Rollback path.

## Execution Status: 2026-06-21

Implemented:

- Phase 11:
  - `agent/visual/autonomous_validation.py`
  - `visual_package_generate` now returns `autonomous_validation`.
  - Validation checks selected media, attempts, artifacts, judgments, rankings, shadow updates, and active-learning traces.
- Phase 12:
  - `agent/visual/artifact_observation.py`
  - Package quality scoring now passes artifact-derived observations into `visual_quality_judge`.
  - Judgments can use vision-style sources for composition/aspect/aesthetic dimensions without exposing prompts or local paths.
- Phase 13:
  - `agent/visual/feedback_attribution.py`
  - Sparse feedback can be bound to request artifacts by selection index and written to `visual_feedback`.
- Phase 14:
  - `agent/visual/autonomous_rollout.py`
  - `scripts/visual_autonomous_loop_report.py`
  - Autonomous loop report combines regression checks, learning proposals, rollout candidates, and self-review.
- Phase 15:
  - `agent/visual/video_hardening.py`
  - Package video generation now adds natural real-time motion guidance and preserves source-image aspect ratio to avoid stretch.

Verification:

- `rtk ./venv/bin/python -m pytest tests/visual/test_autonomous_validation.py tests/visual/test_artifact_observation.py tests/visual/test_feedback_attribution.py tests/visual/test_autonomous_rollout.py tests/visual/test_video_hardening.py tests/scripts/test_visual_autonomous_loop_report.py -q`: `17 passed`.
- `rtk ./venv/bin/python -m pytest tests/tools/test_visual_package_tool.py tests/scripts/test_visual_live_provider_e2e.py -q`: `17 passed`.
- Full visual slice: `178 passed`.
- `rtk ./venv/bin/python -m ruff check agent/visual tools/visual_package_tool.py scripts/visual_autonomous_loop_report.py tests/visual tests/scripts/test_visual_autonomous_loop_report.py tests/tools/test_visual_package_tool.py`: passed.
- `rtk git diff --check`: passed.
- Fixture live E2E: passed with image/video/judgment/ranking/learning evidence.
- Real provider E2E: passed with provider `xai`, `image_count=1`, `video_count=1`, `judgment_count=2`, `ranking_count=2`, `learning_trace_count=2`.
- Runtime autonomous loop report: passed; no controlled candidates yet because real feedback/proposal volume is still insufficient.
- Replay autonomous loop report: passed with `controlled_candidate_count=2`, proving controlled rollout can activate when evidence is high and risk checks are clean.

Self-review:

- `proven`: post-generation validation now runs inside `visual_package_generate`, so each package can self-report whether the run is acceptable or needs retry/rejudge.
- `proven`: quality judgments no longer depend only on raw deterministic metadata; artifact observations enrich the judge path automatically.
- `proven`: sparse feedback attribution can write learnable feedback without a custom manual script per review.
- `proven`: controlled rollout remains evidence-gated and prompt mutation remains disabled.
- `proven`: video generation now uses source aspect and explicit natural-motion guidance to reduce stretched/slow-motion outputs.
- `reduces_human_intervention`: agent can run `visual_autonomous_loop_report.py`, `visual_live_provider_e2e.py`, and replay gates without asking the user to inspect Slack manually.
- `still_limited`: runtime data has too few real feedback-backed proposals, so the live autonomous loop correctly produces no controlled candidates yet.
- `next_improvement`: wire `visual_autonomous_loop_report.py` into a scheduled Hermes health check or post-generation hook so it runs automatically after visual package activity.
- `rollback_path`: remove `autonomous_validation` from package payloads and keep rollout decisions shadow-only; provider routing and prompt mutation policy remain unchanged.
