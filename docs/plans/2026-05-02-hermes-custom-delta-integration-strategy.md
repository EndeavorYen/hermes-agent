# Hermes Custom Delta Integration Strategy

Date: 2026-05-02
Branch: `feat/hermes-custom-autonomy`
Current upstream baseline: `v2026.4.30`

## Goal

Keep the local Hermes runtime easy to upgrade by shrinking long-lived forks into
small, intentional deltas. Future upgrades should be merge checkpoints plus a
short audit, not repeated semantic surgery across gateway, cron, skill loading,
and runtime files.

## Operating Rule

Do not delete custom code just because upstream added something nearby. Retire a
local patch only when the upstream feature is behaviorally equivalent for the
local workflow, or when the remaining local behavior can move to config, skills,
plugins, or a narrow upstream PR.

## Delta Triage

Use this classification after every upstream release merge:

- `keep-local`: upstream does not provide the behavior yet, or the local code is
  deliberately stricter for this runtime.
- `replace-with-upstream`: upstream now provides equivalent behavior through core
  code or configuration.
- `upstream-pr`: the local patch is generally useful and small enough to propose
  upstream.
- `pluginize`: the local behavior should move out of patched core files into a
  plugin, hook, skill, or config surface.

## Current Keep-Local Set

- Bounded autonomy runtime: `hermes_loop/*`, `hermes_cli/loop.py`, gateway
  `/loop` recovery, persisted loop checkpoints, evidence-gated progress review.
  Upstream has stuck-loop protection and restart hygiene, but not this governed
  continuation runtime.
- Layer-2 evidence memory: `memory/layer2_*`, `agent/layer2_*`, Layer-2 tools,
  and cron `memory_pipeline`. Upstream improved memory/session search and
  self-improvement, but does not provide evidence-linked durable recurrence.
- `/plan` workspace save target: upstream dropped the explicit `/plan` handler;
  local behavior pins plan artifacts under the active workspace's
  `.hermes/plans/`.
- Cron manual-run execution under scheduler lock: upstream can trigger jobs, but
  local `execute_job_now` actually runs immediately and avoids ticker races.

## Current Replace-With-Upstream Set

- Explicit phrase based learning-skill injection:
  `maybe_build_runtime_learning_skill_message()` and its `run_agent.py` hook.
  Upstream v0.12 has a substantially upgraded background self-improvement loop
  that is class-first, active-update biased, handles skill sub-files, inherits
  runtime credentials, and is restricted to memory + skills toolsets. Curator
  then maintains agent-created skills. This supersedes the local natural-language
  trigger glue and removes a fragile custom path from every agent turn.
- Local scratch visibility:
  `.omc/`, `.plans/`, `.tmp_claude_prompt.txt`, and workspace `.hermes/plans/`
  are runtime artifacts. They should stay untracked unless deliberately promoted
  into a repo plan.

## Current Upstream-PR Candidates

- Slack edit payload length guard: local `msg_too_long` avoidance in
  `gateway/platforms/slack.py` is small, generally useful, and already justified
  by live runtime logs.
- Cron configured provider/base URL inheritance: local cron provider routing
  honors configured model provider/base URL when a job does not override them.
  Upstream already has fallback-provider plumbing, so this is a narrow
  compatibility improvement.
- Skill command aliases: metadata-driven aliases are useful for clean
  high-level commands, but should be reviewed against upstream slash registry
  expectations before proposing.

## Pluginize Candidates

- Channel/workflow specific autonomy launch surfaces should move toward skills
  and plugin hooks. The gateway should only keep the runtime controller and
  minimal command parser.
- Layer-2 memory can remain local for now, but its storage/provider/tool surfaces
  should be isolated enough that future Hermes memory changes do not require
  conflict resolution in `run_agent.py` and `gateway/run.py`.

## Release Merge Runbook

1. Fetch upstream tags and confirm target release notes.
2. Create and push a rollback branch from the current local HEAD.
3. Merge the upstream tag with `--no-ff`; do not rebase this branch.
4. Resolve conflicts by semantic union only. Do not refactor during conflict
   resolution.
5. Run import smoke checks, CLI version/config checks, and the custom regression
   pack for Layer-2, loop, cron, skill commands, gateway, and Slack.
6. Commit the merge checkpoint before restarting live services.
7. Restart gateway and run Slack live thread smoke.
8. Push only after Slack thread reply is confirmed.
9. Open a post-merge delta audit: classify new `upstream-tag..HEAD` diff into
   `keep-local`, `replace-with-upstream`, `upstream-pr`, and `pluginize`.

## First Delta-Shrinking Slice

Implemented in the post-v2026.4.30 follow-up:

- Ignore local runtime scratch in `.gitignore`.
- Retire explicit phrase based learning-skill auto-injection and rely on the
  upstream self-improvement/Curator path for skill and memory maintenance.

Next recommended slice:

- Convert Slack edit payload guard into a small upstream PR.
- Decide whether `docs/plans/2026-05-01-hermes-v2026.4.30-upgrade-plan.md`
  should be committed as the permanent release-upgrade runbook.
- Pin critical local skills before enabling Curator mutation beyond status.
