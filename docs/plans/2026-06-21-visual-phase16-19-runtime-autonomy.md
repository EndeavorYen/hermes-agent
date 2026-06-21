# Visual Phase 16-19 Runtime Autonomy Implementation

**Goal:** Move Hermes visual generation from offline reports toward runtime self-validation, automatic Slack feedback ingestion, stronger artifact quality judging, and bounded provider negotiation.

**Scope:** This phase does not enable uncontrolled prompt mutation or full controlled learning activation. It adds the runtime hooks and evidence plumbing needed before Phase 20 can safely promote strategies.

## Phase 16: Post-Generation Orchestration

Implemented:

- `agent/visual/autonomous_orchestration.py`
- `visual_package_generate` now returns `autonomous_orchestration` next to `autonomous_validation`.

Behavior:

- Converts validation decisions into runtime actions:
  - `accept` -> `accept_and_monitor`
  - `retry_generation` -> `retry_generation`
  - `retry_or_rejudge` -> `rejudge_before_delivery`
  - `provider_blocked` -> `provider_blocked`
- Returns privacy-safe health counters only; raw prompts and local private context are not included.

Proof:

- `tests/visual/test_autonomous_orchestration.py`
- `tests/tools/test_visual_package_tool.py`

Self-review:

- This reduces manual inspection because every package now carries a machine-readable post-generation action.
- It is not yet a scheduled cron job. A later phase can wire this same helper into cron or gateway health checks without changing the validation contract.

## Phase 17: Slack Feedback Ingestion

Implemented:

- `agent/visual/slack_feedback_ingestion.py`
- `gateway/platforms/slack.py` now calls the ingestion helper before normal mention/thread routing can drop a visual feedback reply.

Behavior:

- Resolves Slack feedback to the latest visual request by `platform=slack`, `channel_id`, and `thread_id`.
- Binds labels like `G2` or `第 2 張` to the correct artifact through the existing feedback attribution path.
- Handles broad feedback such as `全部退貨` by recording feedback against all current artifacts.
- Ignores generic thread chat that does not look like visual feedback.
- Stores only safe Slack metadata: platform, channel, thread, message id, and source.

Proof:

- `tests/visual/test_slack_feedback_ingestion.py`
- `tests/gateway/test_slack.py::TestSlackVisualFeedbackIngestion`

Self-review:

- Slack thread comments can now become learning signals without manual scripts or waking the agent.
- Reaction-based feedback is still not ingested; only text feedback is wired in this phase.

## Phase 18: Quality Judge Strengthening

Implemented:

- Candidate records now carry artifact `content_hash`, `width`, `height`, and `duration_seconds`.
- Package scoring passes prior candidate hashes into `visual_quality_judge`.
- `visual_quality_judge` surfaces artifact observation defects such as weak aspect integrity and weak motion evidence.

Behavior:

- Duplicate candidate media can be detected within the same generation batch.
- Video artifact observations can lower confidence and expose actionable uncertainty reasons.
- The judge remains privacy-safe and does not expose prompts.

Proof:

- `tests/tools/test_visual_package_tool.py`
- `tests/visual/test_quality_judges.py`

Self-review:

- This improves pre-delivery ranking and reduces repeated stale-looking outputs.
- It is still metadata/observation-driven, not a full external vision-model judge. Actual face beauty and reference identity scoring require a later vision analyzer integration.

## Phase 19: Provider Negotiation v2

Implemented:

- `agent/visual/provider_failures.py` now extracts nested provider error codes.
- Unsupported reference-conditioning failures are retryable.
- `agent/visual/recovery.py` can downgrade unsupported reference requests to text-only fallback.
- `visual_package_generate` honors recovery `removed_arguments` so retry calls can remove reference/image arguments instead of accidentally keeping them.

Behavior:

- xAI/Grok-style nested errors with `{code, message}` produce readable `provider_message_code`.
- `reference_images conditioning not supported` is classified as `unsupported_reference`.
- The retry path can remove `reference_image_urls` and `image_url` when a provider cannot accept reference conditioning.

Proof:

- `tests/visual/test_provider_failures.py`
- `tests/visual/test_recovery.py`
- `tests/tools/test_visual_package_tool.py`

Self-review:

- This makes provider failure handling more autonomous: Hermes can negotiate a bounded fallback before asking the user.
- Provider switching itself remains outside this phase; the current behavior is retry-with-modified-arguments, not cross-provider orchestration.

## Verification

Fresh verification run on 2026-06-21:

- `rtk ./venv/bin/python -m pytest tests/visual/test_autonomous_orchestration.py tests/visual/test_slack_feedback_ingestion.py tests/tools/test_visual_package_tool.py tests/visual/test_quality_judges.py tests/visual/test_provider_failures.py tests/visual/test_recovery.py -q`
  - `34 passed`
- `rtk ./venv/bin/python -m pytest tests/visual/test_slack_feedback_ingestion.py tests/gateway/test_slack.py::TestSlackVisualFeedbackIngestion -q`
  - `4 passed`
- `rtk ./venv/bin/python -m pytest tests/visual tests/scripts/test_visual_autonomous_loop_report.py tests/scripts/test_visual_live_provider_e2e.py tests/tools/test_visual_package_tool.py -q`
  - `153 passed`

## Remaining Gaps

- Slack reaction events are still no-op and are not converted into visual feedback.
- Cron or gateway health checks should call the autonomous report helper on a schedule.
- Video MP4 probe and frame sampling are still needed for stronger stretch/slow-motion detection.
- Full vision-model judging is still needed for face quality, reference identity, and composition novelty.
- Controlled learning activation remains Phase 20+ and should stay evidence-gated.
