# Hermes Release Adoption Mechanism Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Hermes upgrades into an adoption loop that absorbs useful upstream features, retires local workarounds when upstream has a better architecture, and leaves a verified runtime change rather than a version bump only.

**Architecture:** Treat each upstream release as an input to a local adoption matrix. The matrix compares release features against the local custom delta, then routes each item to keep-local, replace-with-upstream, upstream-pr, pluginize, or configure-and-adopt. Live service changes are gated behind auth/runtime smoke tests and Slack/gateway verification.

**Tech Stack:** Hermes CLI, Git tags/remotes, gateway/cron/Kanban/Curator/checkpoints, local docs, focused pytest suites, Slack live smoke.

---

## Current Baseline

- Runtime branch: `feat/hermes-custom-autonomy`
- Current merge checkpoint: `015183445 chore: merge upstream v2026.5.7`
- Upstream releases in scope:
  - `v2026.5.7 / v0.13.0` - Tenacity release
  - `v2026.4.30 / v0.12.0` - Curator release
- Local delta after the v2026.5.7 merge:
  - `124 files changed, 24402 insertions(+), 297 deletions(-)` against `v2026.5.7`
  - Dominant local surfaces: `gateway/run.py`, `hermes_cli/loop.py`, `hermes_loop/*`, `memory/layer2_*`, `cron/scheduler.py`, image-generation reference-image support, Slack/thread delivery fixes, and local creative skills.
- Live feature state checked on 2026-05-10:
  - Gateway is live on `v0.13.0`.
  - Slack Socket Mode works; channel directory refresh works after `groups:read` was added.
  - `slack.strict_mention` is already `true`.
  - Curator is enabled and has run twice.
  - Checkpoints v2 store is healthy: `10.5 MB`, no projects.
  - Kanban exists but the `default` board is empty.
  - Several Taiwan cron jobs have last-run `token_invalidated (401)` from 2026-05-08, while `hermes auth status openai-codex` now reports logged in. This requires a fresh auth smoke before relying on the next market-day cron run.

## Release Value To Absorb

### v2026.5.7 - Tenacity

High-value features for this local runtime:

- Durable multi-agent Kanban with task heartbeats, reclaim, zombie detection, retries, diagnostics, worker logs, task dependency context, and gateway-embedded dispatcher.
- `/goal` persistent cross-turn target tracking and gateway auto-resume after restart.
- Checkpoints v2 with pruning and disk guardrails.
- `no_agent` cron mode for script-only watchdog jobs.
- ProviderProfile and `plugins/model-providers/` as the long-term home for provider-specific behavior.
- Security hardening: default redaction, platform allowlists, OAuth/auth TOCTOU fixes, MCP OAuth hardening.
- Slack fixes and platform allowlists.
- `image_gen.model` config honoring, MCP media preservation, `video_analyze`, and richer media routing.
- Curator subcommands and safer manual run behavior.

### v2026.4.30 - Curator

High-value features for this local runtime:

- Autonomous Curator and upgraded self-improvement loop for skill-library hygiene.
- Skill ecosystem expansion and `/reload-skills`.
- First-class providers such as LM Studio plus remote model catalog and dashboard model controls.
- Cron `workdir` and script support as a foundation for project-aware Taiwan workflows.
- Native multimodal routing and gateway media parity.
- Observability and achievements plugins.
- TUI performance and prompt-cache TTL.

## Adoption Matrix

| Local surface | Upstream replacement or substrate | Decision | Next action |
| --- | --- | --- | --- |
| Local phrase-triggered learning-skill injection | v0.12 self-improvement loop + Curator | replace-with-upstream | Already retired in prior delta-shrinking slice. Keep it retired. |
| Local bounded `hermes_loop` continuation runtime | v0.13 `/goal`, auto-resume, Checkpoints v2, Kanban | migrate-partially | Use Kanban for multi-task work and `/goal` for single durable objectives. Keep local loop only for evidence-gated continuation until upstream goal/kanban covers the verifier contract. |
| Local loop checkpoint/recovery code in `gateway/run.py` | v0.13 gateway auto-resume + Checkpoints v2 | pluginize-or-reduce | Map local recovery behavior to upstream checkpoints; delete duplicated persistence only after tests prove equivalent recovery. |
| Local Layer-2 evidence memory | v0.12 Curator/self-improvement, v0.13 API session memory and Hindsight append dedupe | keep-local, isolate | Keep evidence-linked recurrence ledger. Move integration toward MemoryProvider/plugin boundaries so future upstream memory changes do not touch `run_agent.py` or `gateway/run.py`. |
| Cron `memory_pipeline` | Curator + Layer-2 ledger | keep-local | Keep as the evidence capture path for high-value cron loops. Do not collapse it into skills. |
| Cron manual run and provider routing patches | v0.13 cron provider fixes + `no_agent` | audit-and-upstream-pr | Retain only if tests show upstream behavior still misses local requirements. Convert script-only jobs to `no_agent` where the agent adds no value. |
| Script-injected cron jobs | v0.13 `--no-agent` | replace-with-upstream | Convert self-contained script jobs after a dry run. Candidate jobs: `taiwan-prediction-ledger-row-sync-local`, `taiwan-prediction-error-accounting-local`. |
| Slack thread target delivery and payload guards | v0.13 Slack fixes + allowlists | audit-and-upstream-pr | Keep until equivalent upstream behavior is proven. Prepare small PRs for generic fixes. |
| Local image reference inputs | v0.12 native multimodal routing, v0.13 image config/model honoring, MCP media tags | keep-local-narrow | Keep safe opt-in `reference_images` support if upstream still lacks explicit reference-image semantics. Prefer upstream media routing for ordinary images/videos. |
| Local story/video skills | v0.13 `video_analyze`, media routing | configure-and-adopt | Update skill workflow to use `video_analyze` for post-render QA and upstream media routing for inputs. |
| Dashboard plugin discovery gate | v0.13 dashboard plugin page and profile management | audit | Confirm upstream dashboard plugin controls cover the need. If equivalent, delete local gate or move to config. |
| Local provider special cases | v0.13 ProviderProfile plugins | pluginize | Move provider-specific behavior into `plugins/model-providers/` when the delta is not generally useful upstream. |
| Upgrade runbook docs | `hermes update --check`, backup flags, checkpoints status | configure-and-adopt | Keep local merge-based runbook for custom branch. Add release adoption audit after each merge. |

## Operating Policy

Every release adoption cycle must produce:

- A rollback branch and runtime backup before merge.
- A release intelligence summary covering the latest two releases, not only the current target.
- A local-delta matrix from `git diff <latest-upstream-tag>..HEAD`.
- A replacement decision for every large local surface.
- A live-service gate: import smoke, version/config check, custom regression pack, gateway restart, Slack smoke.
- A post-merge adoption board in Kanban, with tasks for migrations that should not be hidden inside conflict resolution.

Do not delete local code because upstream has a similar name. Retire local code only when one of these is true:

- Upstream behavior is equivalent and verified by local tests.
- The local behavior can be represented as config, skill, plugin, or provider profile.
- The local behavior is small and generic enough to upstream as a PR.
- The local behavior is obsolete because our workflow has moved to Kanban, Curator, or no-agent cron.

## Task 1: Create The Release Adoption Board

**Files:**
- No repo files modified by this task.
- Runtime state: Hermes Kanban board store under `~/.hermes/kanban/`.

- [ ] **Step 1: Create a dedicated board**

Run:

```bash
rtk venv/bin/hermes kanban boards create release-adoption \
  --name "Release Adoption" \
  --description "Post-release adoption, workaround retirement, and local-delta migration tracking"
```

Expected: board exists. If it already exists, use it.

- [ ] **Step 2: Add initial migration tasks**

Run these with idempotency keys:

```bash
rtk venv/bin/hermes kanban --board release-adoption create "P0 auth and cron health gate before next market run" \
  --priority 0 \
  --workspace dir:/Users/simon/.hermes/hermes-agent \
  --idempotency-key release-adoption-2026-05-10-auth-cron-gate \
  --body "Verify OpenAI Codex auth with a minimal one-shot call, then run/read-only check recent Taiwan cron jobs before the next market-day window. Do not change job schedules in this task."

rtk venv/bin/hermes kanban --board release-adoption create "Migrate script-only cron jobs to no_agent where safe" \
  --priority 1 \
  --workspace dir:/Users/simon/.hermes/hermes-agent \
  --idempotency-key release-adoption-2026-05-10-no-agent-cron \
  --body "Audit jobs with script=true and no_agent=false. Candidate jobs: 5587c816ff1b taiwan-prediction-ledger-row-sync-local, 058d6b4ea1d9 taiwan-prediction-error-accounting-local. Dry-run scripts first; edit jobs only after output contract is confirmed."

rtk venv/bin/hermes kanban --board release-adoption create "Map local loop runtime to upstream goal plus kanban primitives" \
  --priority 1 \
  --workspace dir:/Users/simon/.hermes/hermes-agent \
  --idempotency-key release-adoption-2026-05-10-loop-to-goal-kanban \
  --body "Compare local hermes_loop verifier/evidence gates with upstream /goal, gateway auto-resume, Checkpoints v2, and Kanban. Produce a delete/keep/pluginize list for gateway/run.py and hermes_cli/loop.py."

rtk venv/bin/hermes kanban --board release-adoption create "Curator governance and custom-skill protection" \
  --priority 2 \
  --workspace dir:/Users/simon/.hermes/hermes-agent \
  --idempotency-key release-adoption-2026-05-10-curator-governance \
  --body "Review the two Curator runs, inspect archived/umbrella skills, pin or protect critical custom skills, and decide whether Curator remains mutation-enabled or report-only for custom directories."

rtk venv/bin/hermes kanban --board release-adoption create "Prepare upstream PR or plugin plan for remaining narrow patches" \
  --priority 3 \
  --workspace dir:/Users/simon/.hermes/hermes-agent \
  --idempotency-key release-adoption-2026-05-10-upstream-pr-pluginize \
  --body "Classify Slack payload/thread fixes, cron provider/manual-run patches, dashboard plugin gate, and image reference support as upstream-pr, pluginize, or keep-local."
```

Expected: tasks exist on `release-adoption`.

## Task 2: Run The Auth And Cron Health Gate

**Files:**
- No repo files modified by this task.
- Runtime state: may create a normal Hermes session from the one-shot smoke.

- [ ] **Step 1: Verify auth state**

Run:

```bash
rtk venv/bin/hermes auth status openai-codex
```

Expected: `openai-codex: logged in`.

- [ ] **Step 2: Verify an actual small model call**

Run:

```bash
rtk venv/bin/hermes -z "Reply with exactly: OK"
```

Expected: output contains only `OK` or a simple successful response. If this fails with 401, stop and refresh Hermes OpenAI Codex auth before touching cron jobs.

- [ ] **Step 3: Summarize cron health**

Run:

```bash
rtk venv/bin/hermes cron list
```

Expected: record which jobs still show last-run 401. Do not assume current failure until Step 2 fails.

## Task 3: Convert Safe Script-Only Jobs To `no_agent`

**Files:**
- Runtime state: `~/.hermes/cron/jobs.json`.

- [ ] **Step 1: Inspect candidate scripts**

Run:

```bash
rtk venv/bin/python - <<'PY'
import json
from pathlib import Path
jobs = json.loads(Path('/Users/simon/.hermes/cron/jobs.json').read_text())
items = jobs.get('jobs', jobs)
if isinstance(items, dict):
    items = list(items.values())
for job in items:
    if job.get('script') and not job.get('no_agent'):
        print(job['id'], job.get('name'), job.get('script'), job.get('workdir'))
PY
```

Expected: list only script jobs still using agent mediation.

- [ ] **Step 2: Dry-run scripts from their workdir**

For each candidate, inspect the script path under `~/.hermes/scripts/` and run it from the configured `workdir`. Capture whether stdout is already the desired delivered artifact.

Expected: if stdout is the complete output, the job is safe for `--no-agent`. If stdout is only raw context for an LLM summary, keep agent mode.

- [ ] **Step 3: Edit only safe jobs**

Run one edit per safe job:

```bash
rtk venv/bin/hermes cron edit <job_id> --no-agent
```

Expected: `hermes cron list` shows `Script:` and no-agent behavior is active for the edited job.

## Task 4: Replace Multi-Step Upgrade Work With Kanban

**Files:**
- No repo code files modified unless a Kanban task explicitly scopes a code migration.

- [ ] **Step 1: Use Kanban for future release adoption**

For future releases, create one parent task per release and child tasks for:

- release intelligence
- merge rehearsal
- local-delta matrix
- live rollout
- workaround retirement
- upstream PR candidates

Expected: upgrade work is visible as tasks with logs and run history, not hidden inside a long Slack thread.

- [ ] **Step 2: Keep local `/loop` for evidence-gated single-session work only**

Use `/loop` when the value is the local verifier/evidence contract. Use Kanban when the value is task decomposition, worker retries, shared logs, and multi-profile handoff.

Expected: local autonomy delta shrinks over time instead of competing with upstream Kanban.

## Task 5: Govern Curator Before More Mutation

**Files:**
- May modify custom skills only after explicit task approval.

- [ ] **Step 1: Review current Curator reports**

Run:

```bash
rtk venv/bin/hermes curator status
rtk find /Users/simon/.hermes/logs/curator -maxdepth 2 -type f | sort | tail -20
```

Expected: identify exactly what the two prior runs changed or suggested.

- [ ] **Step 2: Protect critical custom skills**

List critical skills and decide which must be pinned/protected before more Curator mutation:

- `agentic-taiwan-market-committee`
- `nightly-dream-shadow-cron`
- `autonomous-learning-sprint`
- local story/video production skills
- any skill referenced by active cron jobs

Expected: Curator can report and consolidate safely without breaking scheduled workflows.

## Task 6: Produce The Next Delta-Shrinking Patch Set

**Files:**
- Likely modify: `gateway/run.py`, `hermes_cli/loop.py`, `cron/scheduler.py`, `tools/cronjob_tools.py`, `gateway/platforms/slack.py`, `tools/image_generation_tool.py`, plugin/provider files, and targeted tests.

- [ ] **Step 1: Generate the latest local delta**

Run:

```bash
rtk git diff --name-status v2026.5.7..HEAD
rtk git diff --shortstat v2026.5.7..HEAD
rtk git log --oneline --no-merges --cherry-pick --right-only v2026.5.7...HEAD
```

Expected: every surviving local surface is assigned to the adoption matrix.

- [ ] **Step 2: Remove or migrate one category at a time**

Recommended order:

1. Cron script jobs to `no_agent`.
2. Curator governance and skill protection.
3. Slack thread/payload fixes into upstream PR candidates.
4. Local loop-to-goal/Kanban mapping.
5. Provider-specific code to ProviderProfile plugins.
6. Image reference support retained only as narrow opt-in behavior.

Expected: each category lands with focused tests and does not mix unrelated churn.

## Verification Commands

Run after any repo-code migration:

```bash
rtk git diff --check
rtk venv/bin/python -m py_compile \
  gateway/run.py hermes_cli/loop.py cron/scheduler.py tools/cronjob_tools.py \
  tools/image_generation_tool.py gateway/platforms/slack.py
rtk scripts/run_tests.sh \
  tests/cron/test_scheduler.py \
  tests/tools/test_cronjob_tools.py \
  tests/gateway/test_loop_recovery.py \
  tests/hermes_cli/test_loop.py \
  tests/hermes_loop/test_runtime.py \
  tests/gateway/test_slack.py \
  tests/tools/test_image_generation_plugin_dispatch.py \
  -q -o addopts= --tb=short
```

Run after live workflow changes:

```bash
rtk venv/bin/hermes --version
rtk venv/bin/hermes gateway status
rtk venv/bin/hermes cron list
rtk venv/bin/hermes kanban --board release-adoption stats
```

## Completion Criteria

- The `release-adoption` Kanban board exists and contains the initial migration tasks.
- Auth smoke passes after the v2026.5.7 rollout.
- Script-only cron jobs are classified, and safe ones are converted to `no_agent`.
- Local loop, Layer-2, cron, Slack, image, dashboard, and provider patches each have an explicit keep/migrate/delete/pluginize decision.
- Future releases always produce an adoption matrix before live rollout is called complete.
- The local custom delta shrinks or becomes more modular after every release cycle.
