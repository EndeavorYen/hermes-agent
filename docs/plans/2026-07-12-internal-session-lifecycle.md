# Internal Session Lifecycle Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep Hermes-owned background work out of Codex Remote, bound cron-generated state growth, prevent accidental unbounded high-frequency agent schedules, report manual one-shot outcomes correctly, and hide internal sessions from the public session-list API by default.

**Architecture:** Centralize Codex thread visibility in the Codex runtime with an explicit per-agent override for CLI flows that share the `cli` platform label. Add cron-specific session maintenance beside the existing generic session maintenance, using ended-session-only deletion, per-job limits, age limits, independent cadence metadata, FTS optimization, and VACUUM. Enforce recurring-agent safety in the shared cron job store so every creation/update surface receives the same fail-closed behavior.

**Tech Stack:** Python 3.11, SQLite/FTS5, pytest, aiohttp test client, Hermes gateway and cron runtime.

## Global Constraints

- Use TDD: every behavior change starts with a focused failing regression test.
- Preserve active sessions and non-cron history during cron maintenance.
- Preserve current interactive Codex task visibility; internal/unknown execution paths default to ephemeral.
- Do not add dependencies.
- PR base is `local/main`; runtime deploy pointer must end at the identical accepted SHA.
- The live database cleanup requires a timestamped backup, `PRAGMA integrity_check`, stopped gateway writers, post-cleanup integrity/search checks, and fresh runtime smoke.

---

### Task 1: Codex Thread Visibility Policy

**Files:**
- Modify: `agent/agent_init.py`
- Modify: `agent/codex_runtime.py`
- Modify: `hermes_cli/oneshot.py`
- Modify: `hermes_cli/cli_commands_mixin.py`
- Test: `tests/agent/test_codex_app_server_persist.py`

**Interfaces:**
- Consumes: `AIAgent.platform` and optional `codex_thread_ephemeral` constructor policy.
- Produces: `resolve_codex_thread_ephemeral(agent) -> bool` used exactly once when constructing `CodexAppServerSession`.

- [ ] Add failing tests proving cron, curator, subagent, unknown, one-shot, and CLI background agents are ephemeral while normal interactive CLI remains visible.
- [ ] Run the focused tests and confirm failure because only `platform == "cron"` is currently ephemeral.
- [ ] Add the optional agent field, centralized resolver, and explicit one-shot/background overrides.
- [ ] Re-run the focused tests and related Codex transport/runtime tests.

### Task 2: Cron Session Retention and Database Maintenance

**Files:**
- Modify: `hermes_state.py`
- Modify: `gateway/run.py`
- Modify: `hermes_cli/config.py`
- Modify: `website/docs/user-guide/sessions.md`
- Test: `tests/test_hermes_state.py`

**Interfaces:**
- Consumes: cron session IDs shaped as `cron_<job-id>_<YYYYMMDD_HHMMSS>` and ended rows only.
- Produces: `prune_cron_sessions(retention_days, keep_per_job, sessions_dir) -> int` and `maybe_auto_prune_cron_sessions(...) -> maintenance result` with a cadence marker independent from generic session pruning.

- [ ] Add failing tests for active-session preservation, non-cron preservation, per-job cap, age cutoff, transcript cleanup, cadence, FTS search integrity, and optional VACUUM.
- [ ] Run the focused tests and confirm the cron-specific methods are absent.
- [ ] Implement bounded ended-cron deletion using both age and per-job rank, then add independent startup maintenance defaults.
- [ ] Document why cron history is shorter than user conversations and re-run state/gateway tests.

### Task 3: Infinite High-Frequency Agent Cron Guard

**Files:**
- Modify: `cron/jobs.py`
- Modify: `hermes_cli/config.py`
- Modify: `website/docs/user-guide/sessions.md`
- Test: `tests/cron/test_jobs.py`

**Interfaces:**
- Consumes: parsed schedule, repeat count, `no_agent`, and operator config `cron.allow_high_frequency_agent_jobs` / `cron.min_agent_interval_minutes`.
- Produces: a shared create/update validation that rejects only unbounded recurring agent jobs below the configured minimum; one-shot, finite-repeat, no-agent, and explicitly enabled jobs remain valid.

- [ ] Add failing create and update tests covering interval and cron-expression schedules plus every allowed boundary.
- [ ] Run the focused tests and confirm unsafe schedules are currently accepted.
- [ ] Implement one shared schedule-period resolver and validation in both create and update paths.
- [ ] Re-run cron store, tool, CLI, API, and scheduler tests.

### Task 4: Manual One-Shot Outcome Contract

**Files:**
- Modify: `cron/scheduler.py`
- Modify: `tools/cronjob_tools.py`
- Test: `tests/tools/test_cronjob_run_immediate.py`
- Test: `tests/cron/test_run_one_job.py`

**Interfaces:**
- Consumes: `run_one_job(job, outcome=...)` with optional mutable outcome sink.
- Produces: exact `success` / `error` result even when a finite job is removed before `_execute_job_now` re-reads it.

- [ ] Add a failing regression reproducing a successful removed one-shot and a failed removed one-shot.
- [ ] Run the focused tests and confirm the success case is misreported.
- [ ] Populate the optional outcome sink on all processed/error paths and use it only when the post-run job row no longer exists.
- [ ] Re-run immediate-run and scheduler tests.

### Task 5: Session Listing Privacy Contract

**Files:**
- Modify: `gateway/platforms/api_server.py`
- Test: `tests/gateway/test_session_api.py`

**Interfaces:**
- Consumes: optional explicit `source` query.
- Produces: default list excludes `cron`, `subagent`, `tool`, `curator`, and background-review sources; an explicit source query remains an admin/debug opt-in.

- [ ] Add a failing API regression with interactive and internal sessions.
- [ ] Run it and confirm the default endpoint leaks internal rows.
- [ ] Pass the centralized internal-source exclusion to `list_sessions_rich` only when no explicit source was requested.
- [ ] Re-run the complete session API suite.

### Task 6: Release and Live Database Cleanup

**Files:**
- Modify only if review finds defects; live artifacts remain outside git.

**Interfaces:**
- Consumes: accepted topic SHA and live `state.db`.
- Produces: green local/full tests, self-review, Grok Build approval, fork-local PR/CI merge, identical `local/main` and `runtime/current`, and a smaller integrity-checked live DB with a timestamped backup.

- [ ] Run focused suites, relevant wider suites, static compilation, `git diff --check`, and privacy/diff audit.
- [ ] Perform requirement-by-requirement self-review and repair findings.
- [ ] Send the unpublished diff and design plan to Grok Build; repair and repeat until approved.
- [ ] Push the exact named topic ref, open PR to `local/main`, wait for required CI, and merge only when green.
- [ ] Fast-forward local `local/main`, deploy the identical SHA to `runtime/current`, restart the supervised gateway, and run live cron/session smokes.
- [ ] Stop gateway writers, checkpoint WAL, create a timestamped backup, run integrity check, execute cron maintenance plus FTS optimize/VACUUM, verify row/source counts and search, restart, and retain the backup until post-cleanup runtime verification is green.

## Self-Review

- Spec coverage: all five diagnosed product defects and one-time/live database cleanup have explicit tasks and proof steps.
- Placeholder scan: no deferred implementation placeholders remain.
- Type consistency: visibility resolver returns `bool`; maintenance and outcome contracts have stable return shapes; existing callers remain backward-compatible through optional arguments.

