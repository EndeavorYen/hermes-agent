# Hermes Release Adoption Execution Record - 2026-05-11

## Scope

This record executes the adoption mechanism from
`docs/plans/2026-05-10-hermes-release-adoption-mechanism.md` for the latest two
upstream releases in scope:

- `v2026.5.7 / v0.13.0` - Tenacity
- `v2026.4.30 / v0.12.0` - Curator

The intent is to make the upgrade visible in daily Hermes workflows: use new
upstream primitives where they are better than local workarounds, keep local
behavior only where it still has a verified contract, and route narrow generic
fixes toward upstream PRs.

## Executed Changes

### Kanban as the release-adoption control plane

- The `release-adoption` board is active and tracks post-release migration work.
- Completed items before this record:
  - P0 auth and cron health gate.
  - Script-only cron migration to `no_agent`.
- Remaining adoption work is now represented as visible Kanban tasks instead of
  being hidden inside a long chat thread.

Decision: use Kanban for multi-step upgrade adoption, worker handoff, and
workaround retirement. Keep local `/loop` only for evidence-gated continuation
where its verifier contract still adds value.

### Cron script jobs moved to `no_agent`

Converted these runtime cron jobs:

- `5587c816ff1b` - `taiwan-prediction-ledger-row-sync-local`
- `058d6b4ea1d9` - `taiwan-prediction-error-accounting-local`

Decision: script-only jobs whose stdout is already the final artifact should use
upstream `no_agent` mode. Agent mediation stays only when the script output needs
LLM synthesis.

### Cron jobs.json write race fixed

Observed failure: two concurrent `hermes cron edit ... --no-agent` commands could
clobber each other because `create_job`, `update_job`, and `remove_job` performed
load-modify-save cycles without the existing jobs-file lock.

Change:

- Promote `_jobs_file_lock` to `threading.RLock()`.
- Wrap `create_job`, `update_job`, and `remove_job` load-modify-save cycles in
  the same lock already used by scheduler write paths.
- Add a regression test proving concurrent `update_job` calls serialize their
  file cycle.

Decision: keep this local fix now and prepare it as a narrow upstream PR
candidate because the bug is generic and not custom-workflow-specific.

### Curator governance enabled with pinned workflow entrypoints

Reviewed the two Curator reports:

- `20260502-163613`: umbrella consolidation, 39 skills merged, 0 pruned.
- `20260509-170408`: umbrella consolidation, 13 skills merged, 0 pruned.

Pinned or verified protection for critical daily workflow skills:

- Already pinned: `agentic-taiwan-market-committee`,
  `nightly-dream-shadow-cron`, `directional-probability-decision-engine`,
  stock/Taiwan operator skills.
- Pinned in this execution: `autonomous-learning-sprint`,
  `story-video-production-pipeline`, `reference-photo-social-editorial`,
  `state-safe-operator-packs`, `hermes-cron-and-telemetry-governance`,
  `taiwan-market-workflow-validation`,
  `research-due-diligence-and-opportunity-scouting`.
- `taiwan-childrens-story-writing` was reported by the CLI as not
  curator-managed, so Curator will not auto-transition it.

Decision: keep Curator enabled weekly. It has backups and no deletion behavior;
critical custom workflow entrypoints are now protected.

### Story/video workflow adopted `video_analyze`

Updated `skills/creative/story-video-production-pipeline/SKILL.md` so final
story-video delivery requires a `video/final_qa.md` record and uses
`video_analyze` when the `video` toolset is available.

Decision: story/video work should use upstream multimodal/video QA for
post-render review, while deterministic checks (`ffprobe`, sampled frames,
contact sheets) remain the source of concrete media facts.

## Runtime Error Triage

Current checks distinguish live failures from retained historical job status:

- OpenAI Codex auth is currently healthy: `hermes auth status openai-codex`
  reports logged in.
- Slack `groups:read` missing-scope warnings are stale log lines from before
  the bot reinstall. `channel_directory.json` updated on 2026-05-11 after those
  warnings, so channel directory refresh is now working.
- `hermes cron list` still shows 15 jobs with `token_invalidated (401)` in
  `last_error`, all from 2026-05-08. These are retained last-run records, not
  proof of current auth failure. They should be overwritten by the next
  scheduled 2026-05-11 market runs rather than manually erased.
- The real runtime-state bug found during this triage was the concurrent
  `jobs.json` write race, now covered by a regression test and fixed in code.

## Local Delta Decisions

| Surface | Decision | Why |
| --- | --- | --- |
| Local bounded loop runtime | Keep narrow, migrate usage to `/goal` + Kanban where possible | Upstream `/goal` covers ordinary persistent goals and Kanban covers multi-task work, but local loop still has evidence gates, goal artifacts, conservative recovery, and operator controls that are not fully replaced. |
| `gateway/run.py` loop recovery | Reduce over time | Upstream goal/checkpoint primitives exist, but the local implementation still owns evidence and stop-taxonomy behavior. Delete only after tests prove parity. |
| Layer-2 evidence memory | Keep local, isolate | Curator and session memory do not replace evidence-linked recurrence memory. Keep behind provider/tool boundaries. |
| Cron script jobs | Replace with `no_agent` where stdout is final | Done for two safe runtime jobs. |
| Cron provider/manual-run patches | Upstream PR candidate | Generic behavior; keep local until upstream has equivalent tests. |
| Cron jobs-file lock | Upstream PR candidate | Generic data-loss bug found during adoption. |
| Slack thread delivery / payload guards | Upstream PR candidate | Generic delivery hardening; current local tests protect behavior. |
| Slack channel directory scope | Configure-and-adopt | `groups:read` was added and the directory is refreshing. No local workaround needed. |
| Curator skill hygiene | Configure-and-adopt | Curator remains enabled, with critical custom skills pinned. |
| Story/video production | Configure-and-adopt | `video_analyze` is now part of the normal post-render QA contract. |
| Image reference inputs | Keep local narrow | Upstream media routing is better for ordinary media, but explicit local reference-image semantics remain a narrow opt-in feature. |
| Provider-specific behavior | Pluginize future changes | Prefer `plugins/model-providers/` and ProviderProfile rather than adding more provider branches to core code. |
| Dashboard plugin discovery gate | Audit before deletion | Keep local gate until upstream dashboard config controls are proven equivalent. |

## Next Patch Set

1. Upstream PR candidate: cron jobs-file write lock.
2. Upstream PR candidate: Slack thread target delivery and oversized edit guards.
3. Audit dashboard plugin discovery gate against upstream dashboard controls.
4. Move any remaining provider-specific logic into ProviderProfile plugins.
5. Continue shrinking local loop code only when `/goal`, checkpoints, and Kanban
   cover the same recovery/evidence tests.

## Verification Targets

Required before this execution is considered complete:

- Focused cron race regression test passes.
- Full `tests/cron/test_jobs.py` passes.
- `git diff --check` passes.
- Live runtime checks: auth status, gateway status, cron list, Kanban stats.
- Gateway restart after code changes so the cron lock fix is active in the
  scheduler process.
