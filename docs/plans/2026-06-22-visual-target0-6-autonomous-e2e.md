# Visual Target 0-6 Autonomous E2E Plan

**Goal:** Finish the current visual autonomy loop from runtime validation to self-checking E2E gates, reducing manual user intervention while keeping provider behavior, user preference, and controlled learning separate.

## Target 0: Phase 16-19 Closeout

Status: completed before this plan was authored.

Acceptance:

- Phase 16-19 diff reviewed.
- Visual + Slack targeted tests pass.
- Commit pushed to `origin/upgrade/hermes-v2026.6.19-local`.

Evidence:

- Commit: `67acbcbf7 feat: wire visual runtime autonomy`

## Target 1: Autonomous Health Runner

Objective:

- Make visual health checks callable by post-generation hooks and scheduled jobs without manually stitching together scripts.

Implementation:

- Add a pure health runner that combines regression, learning, and autonomous loop reports.
- Add a CLI wrapper for fixture/live operator use.
- Keep raw prompts, private paths, and generated media out of the report.

Acceptance:

- Health report succeeds on clean fixture ledger.
- Duplicate delivery or unsafe activation fails closed.
- CLI emits JSON and returns nonzero on failed health unless `--allow-failures` is used.

## Target 2: Slack Reaction Feedback

Objective:

- Convert lightweight Slack reactions into visual feedback records without waking the agent loop.

Implementation:

- Map positive and negative reaction emoji to feedback polarity.
- Resolve reactions by Slack delivery `message_id`, then request/thread fallback.
- Keep user ids out of visual feedback metadata.

Acceptance:

- Positive reaction on a delivered artifact records positive feedback.
- Negative reaction records negative feedback.
- Unknown reaction is ignored.
- Reaction does not trigger normal agent processing.

## Target 3: Video Probe

Objective:

- Detect common video defects automatically: wrong aspect, weak duration evidence, and weak motion evidence.

Implementation:

- Add a video probe helper that can consume artifact metadata or optional analyzer output.
- Integrate probe output into artifact observation and quality judgment.
- Fail soft when probe data is missing.

Acceptance:

- Aspect mismatch is flagged.
- Slow/static motion evidence is flagged.
- Probe failure lowers confidence but does not crash generation.

## Target 4: Vision Judge v1

Objective:

- Add a privacy-safe bridge for vision-model or deterministic visual observations to affect ranking.

Implementation:

- Normalize vision observations into reference adherence, face quality, visual appeal, composition, pose novelty, and artifact defects.
- Convert face/reference/composition defects into quality-judge uncertainty reasons.
- Avoid raw prompt and private path leakage.

Acceptance:

- Face defect lowers aesthetic score.
- Reference drift lowers reference adherence.
- Good composition and appeal raise confidence.
- Output is privacy-safe.

## Target 5: Controlled Learning Activation Runner

Objective:

- Allow evidence-qualified shadow proposals to become controlled read-only strategy activations without manual promotion scripts.

Implementation:

- Add an activation runner that evaluates proposals against promotion policy and autonomous rollout checks.
- Record controlled activations only when operator/autonomy policy permits.
- Keep prompt mutation disabled.

Acceptance:

- Evidence-qualified proposal can be recorded as controlled.
- Human veto or unsafe runtime checks block activation.
- Prompt mutation proposals are rejected.
- Rollback path remains available.

## Target 6: Visual E2E Automation Report

Objective:

- Provide one command that runs fixture E2E by default and optionally includes live provider E2E when explicitly enabled.

Implementation:

- Add an E2E automation report script.
- Default mode: fixture only.
- Live mode: opt-in via flag/env and provider availability checks.
- Summarize provider checks, health, learning, and selected artifacts without media leakage.

Acceptance:

- Fixture report passes locally.
- Live report skips/blocks clearly when providers are unavailable.
- Failures are classified, not hidden as green.

## Verification Plan

- Targeted unit tests per target.
- `tests/visual` full slice.
- `tests/gateway/test_slack.py` for Slack hook safety.
- `tests/scripts` visual report tests.
- `ruff check` for touched files.
- `git diff --check`.
- Fixture E2E report.

## Self-Review Standard

Each target must state:

- What was automated.
- What still requires human input.
- Whether it can run safely in runtime/cron.
- Whether prompt mutation remains disabled.
- Whether provider health and user preference are kept separate.

## Execution Summary

Status: implemented and verified.

Implemented:

- Target 1: `scripts/visual_autonomous_healthcheck.py` combines autonomous loop, regression, and learning reports into one cron/post-generation health surface.
- Target 2: Slack `reaction_added` now records visual feedback against delivered artifacts without waking the agent loop.
- Target 3: `agent.visual.video_probe` flags video aspect, duration, and motion defects; artifact observation now feeds probe signals into quality judgment.
- Target 4: `agent.visual.judges.vision` provides a privacy-safe vision observation normalizer for reference, face, appeal, composition, and pose novelty.
- Target 5: `agent.visual.controlled_activation_runner` promotes only evidence-qualified, operator-approved, read-only shadow proposals; human veto blocks promotion.
- Target 6: `scripts/visual_e2e_automation_report.py` runs fixture E2E by default and only attempts live provider E2E when explicitly enabled.

Verification:

- `rtk ./venv/bin/python -m pytest tests/visual tests/scripts/test_visual_autonomous_healthcheck.py tests/scripts/test_visual_e2e_automation_report.py tests/scripts/test_visual_autonomous_loop_report.py tests/scripts/test_visual_live_provider_e2e.py tests/scripts/test_visual_learning_report.py tests/scripts/test_visual_learning_replay.py tests/tools/test_visual_package_tool.py tests/gateway/test_slack.py -q`
  - Result: `370 passed, 35 warnings`.
- `rtk ./venv/bin/python -m ruff check ...`
  - Result: passed.
- `rtk git diff --check`
  - Result: passed.
- `rtk ./venv/bin/python scripts/visual_learning_replay.py --db-path /private/tmp/hermes-visual-target0-6-replay.sqlite3 --json`
  - Result: `success=true`.
- `rtk ./venv/bin/python scripts/visual_autonomous_healthcheck.py --db-path /private/tmp/hermes-visual-target0-6-replay.sqlite3 --autonomy-level 2 --json`
  - Result: `success=true`, `health_status=pass`.
- `rtk ./venv/bin/python scripts/visual_e2e_automation_report.py --work-dir /private/tmp/hermes-visual-target0-6-e2e --json`
  - Result: `success=true`, fixture image+video E2E passed, live E2E `not_requested`.

Self-review:

- Human intervention reduced: yes for health/report/reaction/fixture validation; controlled activation remains intentionally gated until evidence thresholds and operator policy pass.
- Self-verification improved: yes. Hermes can now run a fixture-first E2E plus health report without user-triggered visual inspection.
- Learning autonomy improved: partially. Shadow proposals can be promoted through a controlled runner, but sparse live data still keeps most proposals shadow-only.
- Provider health and preference remain separated: yes. Health/regression/provider checks do not inflate aesthetic preference.
- Prompt mutation remains disabled: yes. Controlled activation rejects prompt mutation and records read-only strategy activations only.
- Runtime/cron suitability: yes for `visual_autonomous_healthcheck.py` and fixture `visual_e2e_automation_report.py`; live E2E requires explicit `HERMES_VISUAL_LIVE_E2E=1`.
- Remaining risk: live provider E2E is not run by default, and visual/aesthetic scoring still depends on available vision observations or metadata. More real samples are needed before higher-autonomy promotion is safe.
