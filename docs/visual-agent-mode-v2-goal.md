# Hermes Visual Agent Mode V2 Goal

> **TL;DR** - V2 turns the current Visual Agent Mode MVP into an evidence-driven production loop. The next target is not more prompt wording; it is full source lineage, automatic scoring, bounded repair, and operator-visible learning signals.

## Why V2 Exists

The MVP can route natural image+video requests, produce selected artifacts, avoid stale delivery, and prove Slack delivery. Its main gap is that the system can prove delivery better than it can prove why a request was generated, why an artifact was selected, and how the next run should improve without manual feedback.

V2 closes that gap by making each visual package auditable from inbound request to final Slack delivery, then using artifact evidence to improve future routing and selection.

## Product Promise

Hermes should act closer to an agent-mode visual producer:

- capture platform, channel, thread, message, user, and attachment context for visual requests;
- score generated images and videos before delivery using deterministic and optional vision signals;
- separate provider reliability from aesthetic preference;
- repair or reframe failed generations within bounded budgets;
- learn from weak automatic signals and sparse human feedback without storing raw private prompts;
- report exactly why a package was delivered, repaired, stopped, or escalated.

## Baseline

The current MVP already provides:

- `visual_agent_generate` orchestration for image+video packages;
- asset graph and delivery metadata for selected artifacts;
- Slack delivery proof with image/video join checks and duplicate-delivery detection;
- local-date live proof verification through `scripts/visual_agent_live_proof.py`;
- basic `StrategyAtomStore` for conservative strategy outcomes;
- deterministic artifact ranking primitives.

V2 builds on these pieces and should not replace the existing image mission, video generation, or Slack delivery path.

## Scope

V2 has four workstreams:

| Workstream | Goal | Primary evidence |
| --- | --- | --- |
| Source lineage | Prove request source through ledger rows | `visual_requests` includes platform/channel/thread/message metadata |
| Self-scoring | Rank candidates before delivery without requiring feedback every time | score records, ranked candidates, selected artifact rationale |
| Bounded repair | Retry or reframe provider/QC failures safely | repair attempts, stop reasons, budget trace |
| Operator reporting | Show progress and learning state without reading private prompts | daily report, live proof, strategy summaries |

## Non-Goals

V2 does not train a neural model, bypass provider policy, store raw private prompt corpora in the repo, or implement a full UI dashboard. It should remain a repo-local, provider-agnostic orchestration improvement with runtime data under `~/.hermes`.

## Target Flow

```text
Slack/user request + attachments
  -> VisualSourceContext captured
  -> VisualMission planned with source metadata
  -> image candidates generated
  -> deterministic + optional vision scores recorded
  -> best candidates selected or repaired
  -> video clips generated from selected images
  -> package delivered to Slack
  -> delivery proof links source request, artifacts, and message IDs
  -> strategy/reward signals update compact runtime stores
  -> operator report summarizes what improved and what failed
```

## Autonomy Target

V2 should raise the default from "MVP L2 delivery" toward "bounded L3 repair":

| Level | V2 behavior |
| --- | --- |
| L2 | Auto-select and deliver when hard gates and confidence pass |
| L3 | Retry or reframe failed image/video stages within configured budgets |
| L3 stop | Escalate with clear reason when confidence, policy, provider, or budget gates fail |

V2 should not enable open-ended L4 production loops until scoring and repair evidence are stable.

## Completion Criteria

V2 is complete when Hermes can prove all of the following for a safe Slack visual package:

1. `visual_requests` records source platform, channel, thread, user, and message metadata.
2. Selected image and video artifacts join to attempts, request source metadata, delivery rows, and package metadata.
3. Candidate ranking includes automatic scores and a selected-artifact rationale.
4. Provider failure, QC failure, low confidence, content moderation, and delivery failure are classified separately.
5. Repair attempts are bounded, recorded, and visible in package `stop_reasons` or `repair_trace`.
6. Strategy rewards update compact runtime state without storing raw private prompts.
7. A report command summarizes provider health, delivery health, scoring outcomes, and top strategy atoms.
8. Live proof passes with no stale artifact, duplicate artifact, missing join, or missing source metadata.

## Current Implementation Status

As of 2026-06-20, the repo-local implementation covers the V2 evidence loop in four phases:

| Workstream | Status | Evidence |
| --- | --- | --- |
| Source lineage | Implemented locally | Gateway visual turns set `VisualSourceContext`; new visual request rows persist platform, channel, user, message, thread, and conversation metadata; live proof fails missing source metadata by default. |
| Self-scoring | Implemented locally | `VisualReward` separates provider health, artifact quality, delivery health, and preference score; visual packages include `delivery_metadata.reward_trace` in shadow mode. |
| Bounded repair | Implemented locally | `VisualRepairDecision` gates retries by autonomy level, error type, and budget; `visual_agent_generate` records `repair_trace` and bounded retry attempts at L3+. |
| Operator reporting | Implemented locally | `scripts/visual_agent_report.py` emits aggregate JSON for requests, attempts, artifacts, delivery, provider errors, source metadata, and strategy atoms without raw prompt columns. |

Latest focused verification:

```bash
rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest \
  tests/visual/test_source_context.py \
  tests/visual/test_attempt_ledger.py \
  tests/visual/test_live_proof.py \
  tests/visual/test_live_proof_cli.py \
  tests/gateway/test_visual_source_context.py \
  tests/visual/agent_mode/test_reward.py \
  tests/visual/agent_mode/test_learning.py \
  tests/tools/test_visual_agent_tool.py \
  tests/visual/test_ranker.py \
  tests/visual/agent_mode/test_repair_policy.py \
  tests/visual/test_visual_agent_report.py -q
```

Result: `51 passed`.

Latest full visual suite:

```bash
rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual -q
```

Result: `88 passed`.

Remaining proof boundary: live Slack/Grok package generation still needs a fresh runtime smoke after deployment, then `scripts/visual_agent_live_proof.py` and `scripts/visual_agent_report.py` should be run against the live ledger for the same local date.

## Privacy Rules

Runtime-private material stays under `~/.hermes`:

- raw prompts and references;
- generated image/video files;
- user taste and feedback evidence;
- provider responses;
- local model endpoints;
- strategy statistics tied to private use.

Tracked repo files may contain schemas, generic tests, and generic examples only.

## Recommended Approach

Use an incremental evidence-first approach:

1. Add source context propagation first, because it makes later scoring and repair evidence trustworthy.
2. Add self-scoring as shadow data before changing delivery decisions.
3. Add bounded repair only after score and error taxonomy coverage exists.
4. Add reporting last, aggregating already-recorded evidence rather than inventing a parallel data path.
