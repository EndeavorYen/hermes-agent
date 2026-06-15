# Raphael Phase 0 Discovery Report

Date: 2026-06-15
Status: Complete

## Summary

Phase 0 mapped the current Hermes extension and approval surfaces for the Raphael Capability Evolution Layer. The original plugin-first direction still holds, but discovery corrected one important assumption: the codebase does not currently expose a `skills.write_approval` staged-human-approval API. Skill writes are immediate with validation, atomic writes, scan blocking, and rollback for some operations. Therefore staged skill evolution is a real design gap, not a switch Raphael can simply enable.

The strongest ready surfaces are plugin registration, hooks, plugin slash commands, gateway/Slack command routing, skill usage telemetry sidecars, skill bundles, cron runtime safety guards, and profile-aware Hermes home paths. The most important gaps for Raphael are plugin-scoped state, platform-neutral status-card delivery, generic mutation approval, staged skill evolution, and stronger file-safety coverage for a new `raphael/` runtime state directory.

No production code was changed during discovery. Subagents performed read-only inspection and reported intermittent `Too many open files` failures from the command launcher; focused tests were identified but not run in this phase.

Live-state observations in this report are point-in-time checks from Phase 0 discovery and must be rechecked before implementation or operational decisions.

## Tracking

- Design spec: `docs/superpowers/specs/2026-06-15-raphael-capability-evolution-layer-design.md`
- Implementation plan: `docs/superpowers/plans/2026-06-15-raphael-phase-0-discovery.md`
- Tracking issue: unavailable until GitHub Issues are enabled for `EndeavorYen/hermes-agent`

## Findings

### Repository

| Item | Result | Evidence |
| --- | --- | --- |
| Repo | `EndeavorYen/hermes-agent` | `rtk gh repo view EndeavorYen/hermes-agent --json nameWithOwner,defaultBranchRef,url` |
| Default branch | `main` | `defaultBranchRef.name` returned `main` |
| Issues enabled | No | `rtk gh issue list --repo EndeavorYen/hermes-agent --limit 1` returned `the 'EndeavorYen/hermes-agent' repository has disabled issues` |
| Local branch | `live/hermes-v2026.6.5` | `rtk git status --short --branch` |
| Remotes | `origin` is `EndeavorYen/hermes-agent`; `upstream` is `NousResearch/hermes-agent` | Earlier `rtk git remote -v` check during this work; later retries hit command-launcher file descriptor exhaustion |

### Plugin API

| Question | Result | Evidence |
| --- | --- | --- |
| How are local plugins discovered? | Bundled repo plugins, user `$HERMES_HOME/plugins`, opt-in project `./.hermes/plugins`, and pip entry points are supported. Later sources override earlier sources. Standalone/user/entry-point plugins are opt-in through `plugins.enabled`; `plugins.disabled` wins. | `hermes_cli/plugins.py:5`, `hermes_cli/plugins.py:1076`, `hermes_cli/plugins.py:1111`, `hermes_cli/plugins.py:1123`, `hermes_cli/plugins.py:1135`, `hermes_cli/plugins.py:1152`, `hermes_cli/plugins.py:1167`, `hermes_cli/plugins.py:1182`, `hermes_cli/plugins.py:1194` |
| What shape does a plugin manifest have? | `plugin.yaml` or `plugin.yml` is parsed into `PluginManifest` with fields including `name`, `version`, `description`, `author`, `requires_env`, `provides_tools`, `provides_hooks`, `kind`, and `key`. Directory plugins need `__init__.py` with `register(ctx)`. | `hermes_cli/plugins.py:19`, `hermes_cli/plugins.py:260`, `hermes_cli/plugins.py:1307`, `hermes_cli/plugins.py:1501` |
| Can a plugin register tools? | Yes. `ctx.register_tool(...)` delegates to `tools.registry.register(...)`. Toolsets are implicit from each registered tool's `toolset` field; no explicit `register_toolset` was found. | `hermes_cli/plugins.py:343`, `hermes_cli/plugins.py:1844`, `AGENTS.md:305` |
| Can a plugin register hooks? | Yes. `ctx.register_hook(...)` accepts tool, LLM, API, session, gateway dispatch, subagent, and approval lifecycle hooks. Unknown hooks are retained with a warning for forward compatibility. | `hermes_cli/plugins.py:152`, `hermes_cli/plugins.py:962` |
| Can a plugin register slash commands? | Yes. `ctx.register_command(...)` registers in-session `/commands` for CLI and gateway sessions; built-in conflicts are rejected. `ctx.register_cli_command(...)` also wires `hermes <subcommand>` argparse trees. | `hermes_cli/plugins.py:413`, `hermes_cli/plugins.py:438`, `hermes_cli/plugins.py:1765`, `hermes_cli/plugins.py:1820` |
| Can a plugin register provider backends? | Yes for several plugin-backed providers through context methods: context engine, image/video/web/browser/TTS/STT/dashboard auth/platform/auxiliary-task providers. Memory and model providers have category-specific discovery paths. | `hermes_cli/plugins.py:525`, `hermes_cli/plugins.py:557`, `hermes_cli/plugins.py:624`, `hermes_cli/plugins.py:651`, `hermes_cli/plugins.py:793`, `AGENTS.md:553`, `AGENTS.md:589` |
| Can a plugin store profile-scoped state? | No dedicated `ctx.state`, `ctx.state_dir`, or plugin storage API was found. Existing guidance is to use `get_hermes_home()` manually for profile-scoped state. | `hermes_cli/plugins.py:49`, `hermes_cli/plugins.py:330`, `AGENTS.md:343`, `AGENTS.md:345` |
| Can a disabled no-op Raphael plugin load without core changes? | Inferred viable, not verified. Phase 0 did not create or run a dedicated Raphael no-op plugin fixture. Existing loader code and plugin tests indicate the path should work, but Phase 1 must begin with a disabled-by-default no-op plugin contract test before adding behavior. | `hermes_cli/plugins.py:1076`, `hermes_cli/plugins.py:1111`, `hermes_cli/plugins.py:1135`, `tests/plugins/test_disk_cleanup_plugin.py`, `tests/test_transform_tool_result_hook.py` |

Relevant focused tests:

```bash
rtk ./venv/bin/python -m pytest tests/test_transform_tool_result_hook.py tests/plugins/test_disk_cleanup_plugin.py tests/providers/test_plugin_discovery.py
rtk ./venv/bin/python -m pytest tests/plugins/test_security_guidance_plugin.py tests/plugins/test_plugin_dashboard_auth_contract.py tests/gateway/test_plugin_platform_interface.py
```

### Skill Management

| Question | Result | Evidence |
| --- | --- | --- |
| Where is `skill_manage` implemented? | Core CRUD lives in `tools/skill_manager_tool.py`, registered as tool `skill_manage` under toolset `skills`. | `tools/skill_manager_tool.py:816`, `tools/skill_manager_tool.py:900`, `tools/skill_manager_tool.py:1018` |
| Does `skills.write_approval` exist? | No matching code/config API was found. Closest current control is `skills.guard_agent_created`, default false. Code blocks flagged writes; it does not stage for human approval. Docs appear to claim an approval prompt, so docs/code may be mismatched. | `tools/skill_manager_tool.py:59`, `tools/skill_manager_tool.py:93`, `website/docs/user-guide/configuration.md:516` |
| Can skill writes be staged? | No staged skill-write API was found. Existing behavior uses validation, atomic temp writes, scan blocking, backup/restore for edit/patch/write_file, and curator tree backups/rollback. | `tools/skill_manager_tool.py:440`, `hermes_cli/curator.py:372` |
| Can staged skill writes be rejected and rolled back? | There is no staged write to reject. Some immediate write operations roll back when validation/scanning blocks the result. Curator can roll back the entire skills tree from a snapshot. | `tools/skill_manager_tool.py:533`, `tools/skill_manager_tool.py:566`, `tools/skill_manager_tool.py:717`, `hermes_cli/curator.py:391` |
| What skill telemetry exists? | `.usage.json` sidecars track use/view/patch, state, pinning, and `created_by`. Background review creates are marked agent-created; foreground creates are not. | `tools/skill_usage.py:1`, `tools/skill_manager_tool.py:874`, `tools/skill_usage.py:592` |
| How do skill slash commands work? | Skills are scanned from local `SKILLS_DIR` and external dirs; disabled/platform/env-incompatible skills are skipped; names normalize to `/slug`. Invocation loads skill content through `skill_view`, injects setup/supporting-file hints, and bumps usage. | `agent/skill_commands.py:53`, `agent/skill_commands.py:160`, `agent/skill_commands.py:263`, `agent/skill_commands.py:432` |
| Do skill bundles exist? | Yes. Bundles live in `~/.hermes/skill-bundles/*.yaml` with `name`, `description`, `skills`, optional `instruction`; dispatch loads referenced skills, skips missing ones, dedupes, prepends bundle instruction, and bumps use. Bundles take precedence over individual skills in CLI and gateway dispatch. | `agent/skill_bundles.py:1`, `agent/skill_bundles.py:116`, `agent/skill_bundles.py:253`, `cli.py:9174`, `gateway/run.py:8414` |
| How does curator behave? | Curator candidates are agent-created skills, plus built-ins only when `curator.prune_builtins` is enabled; hub-installed skills are excluded. Archive/restore uses `~/.hermes/skills/.archive`; CLI supports status, run, pause, resume, pin, unpin, archive, prune, backup, rollback, list-archived. | `tools/skill_usage.py:308`, `tools/skill_usage.py:405`, `tools/skill_usage.py:642`, `tools/skill_usage.py:692`, `hermes_cli/curator.py:480` |

Relevant focused tests:

```bash
rtk ./venv/bin/python -m pytest tests/tools/test_skill_manager_tool.py tests/tools/test_skill_size_limits.py tests/tools/test_skill_improvements.py tests/tools/test_cross_profile_guard.py
rtk ./venv/bin/python -m pytest tests/tools/test_skill_usage.py tests/agent/test_curator.py tests/agent/test_curator_backup.py tests/hermes_cli/test_curator_status.py
rtk ./venv/bin/python -m pytest tests/agent/test_skill_commands.py tests/agent/test_skill_commands_reload.py tests/agent/test_skill_bundles.py tests/hermes_cli/test_bundles.py tests/gateway/test_bundles_command.py
```

### Gateway And Slack

| Question | Result | Evidence |
| --- | --- | --- |
| Where are gateway slash commands dispatched? | `COMMAND_REGISTRY` in `hermes_cli/commands.py` is the source of truth. Gateway imports command helpers, checks access, fires `command:<canonical>` hooks, then dispatches built-ins. Plugin commands are handled in gateway runtime, and skill/bundle commands have a parallel path. | `hermes_cli/commands.py:64`, `hermes_cli/commands.py:304`, `gateway/run.py:8060`, `gateway/run.py:8388`, `gateway/run.py:8405`, `gateway/run.py:8414` |
| Can plugin commands appear in Slack? | Yes. `slack_subcommand_map()` includes built-ins, aliases, and plugin commands for `/hermes <cmd>` routing. Slack also registers native slashes through `slack_native_slashes()` where available. | `hermes_cli/commands.py:1033`, `hermes_cli/commands.py:1123`, `gateway/platforms/slack.py:3194` |
| Is there a delivery policy or cooldown hook? | Partial. Delivery supports thread-aware targets and filters bare silence narration. Slack has dedupe/threading and ephemeral slash response contexts. No generic named cooldown/status-card delivery API was found. | `gateway/delivery.py:26`, `gateway/delivery.py:95`, `gateway/delivery.py:329`, `gateway/platforms/slack.py:40`, `gateway/platforms/slack.py:332`, `gateway/platforms/slack.py:636`, `gateway/platforms/slack.py:1069`, `gateway/platforms/slack.py:1247` |
| Is approval/status delivery available? | Fragmented. Slack registers approval Block Kit actions and slash-confirm actions; destructive slash commands route through `_maybe_confirm_destructive_slash`. There is not yet a platform-neutral mutation approval primitive. | `gateway/platforms/slack.py:928`, `gateway/platforms/slack.py:937`, `gateway/run.py:14556` |
| Can CLI-only commands become gateway commands through config? | Yes. `gateway_config_gate` is a `CommandDef` field; config-gated CLI-only commands can become gateway-available through `_is_gateway_available`. | `hermes_cli/commands.py:57`, `hermes_cli/commands.py:412` |
| Is slash access source-scoped? | Yes. Slash access uses `gateway.slash_access.policy_for_source` in `_check_slash_access`. | `gateway/run.py:10231` |

Relevant focused tests:

```bash
rtk ./venv/bin/python -m pytest tests/hermes_cli/test_commands.py tests/gateway/test_gateway_command_help.py tests/gateway/test_unknown_command.py tests/gateway/test_command_bypass_active_session.py
rtk ./venv/bin/python -m pytest tests/gateway/test_approve_deny_commands.py tests/gateway/test_config_driven_access_policy.py tests/gateway/test_pre_gateway_dispatch.py
rtk ./venv/bin/python -m pytest tests/gateway/test_delivery.py tests/gateway/test_notice_delivery.py tests/gateway/test_delivery_silence_filter.py tests/gateway/test_restart_redelivery_dedup.py
rtk ./venv/bin/python -m pytest tests/agent/test_skill_commands.py tests/agent/test_skill_commands_reload.py tests/gateway/test_reload_skills_command.py
```

### Cron

| Question | Result | Evidence |
| --- | --- | --- |
| Where are cron jobs stored? | Jobs live at `/Users/simon/.hermes/cron/jobs.json`; the live file exists with mode `0600`, top-level keys `jobs` and `updated_at`, and current `job_count=0`. | `cron/jobs.py:37`, `cron/jobs.py:55`, `cron/jobs.py:176`, live metadata read by cron explorer |
| Where are run outputs stored? | Outputs live under `/Users/simon/.hermes/cron/output/{job_id}/{timestamp}.md`; live output dir exists with 75 job output directories and 120 markdown files. | `cron/jobs.py:1114`, live metadata read by cron explorer |
| Is run outcome metadata available? | Yes. `tick()` writes outputs, advances recurring `next_run_at`, marks `last_run_at`, `status`, and `error`, and may recompute stale schedules. | `cron/jobs.py:910`, `cron/jobs.py:983`, `cron/jobs.py:1012` |
| Are recursive cron protections present? | Yes. Cron-spawned agents disable `cronjob`, `messaging`, and `clarify` toolsets. Tool schema also warns cron sessions must not schedule cron recursively. | `cron/scheduler.py:62`, `cron/scheduler.py:1731`, `tools/cronjob_tools.py:213`, `tools/cronjob_tools.py:381` |
| Who owns cron execution? | Gateway owns live cron execution with a `cron-ticker` thread calling `cron.scheduler.tick(..., sync=False)` every 60 seconds. | `gateway/run.py:19385`, `gateway/run.py:19837` |
| Is no-agent mode available? | Yes. `no_agent=True` skips `AIAgent` and runs a script; stdout is delivered directly, empty stdout or `wakeAgent:false` is silent, failures alert. | `cron/scheduler.py:1303`, `cron/scheduler.py:1338`, `cron/jobs.py:672`, `hermes_cli/main.py:13564` |
| Can Phase 1 avoid cron mutation? | Yes. Phase 1 should parse `jobs.json` and output metadata read-only. Avoid `hermes cron`, `cron.jobs.load_jobs()`, and `tick()` because loader/tick paths can repair or mutate runtime state. | Cron explorer recommendation from code evidence |

Relevant focused tests:

```bash
rtk ./venv/bin/python -m pytest tests/cron/test_jobs.py tests/cron/test_scheduler.py tests/cron/test_parallel_pool.py
rtk ./venv/bin/python -m pytest tests/cron/test_cron_no_agent.py tests/cron/test_cron_script.py tests/cron/test_scheduler_mcp_init.py
rtk ./venv/bin/python -m pytest tests/tools/test_cronjob_tools.py tests/tools/test_cron_prompt_injection.py tests/tools/test_cron_approval_mode.py
rtk ./venv/bin/python -m pytest tests/hermes_cli/test_cron.py tests/hermes_cli/test_gateway_restart_loop.py tests/hermes_cli/test_mcp_reload_confirm_gate.py
```

### Memory And State

| Question | Result | Evidence |
| --- | --- | --- |
| How are memory reads injected? | Built-in memory reads `MEMORY.md` and `USER.md` under `get_hermes_home() / "memories"`; memory and `USER.md` profile blocks enter the volatile prompt snapshot when enabled. | `tools/memory_tool.py:55`, `tools/memory_tool.py:132`, `agent/system_prompt.py:303`, `agent/agent_init.py:1070` |
| How are memory writes gated? | Built-in memory `add`, `replace`, and `remove` mutate memory under a file lock and persist immediately. Existing gates include sanitization, char limits, file locks, threat scanning/drift refusal, and background review nudges; no human approval gate was found. | `tools/memory_tool.py:297`, `tools/memory_tool.py:515` |
| Are external memory providers profile-aware? | Provider contract says use `hermes_home`; `MemoryManager.initialize_all()` passes `hermes_home=str(get_hermes_home())`. Live config has no external provider. | `agent/memory_manager.py:636`, `agent/memory_provider.py:67` |
| What runtime DB exists? | `state.db` defaults to `get_hermes_home() / "state.db"`; `state_meta` provides key/value reads and writes. The live DB exists and is production-sized. | `hermes_state.py:34`, `hermes_state.py:3574` |
| Where should Raphael state live? | Use `get_hermes_home() / "raphael" / "state.json"` for small state, with optional `events.jsonl` or `state.db` for concurrent writes. Do not use `memories/` because it is prompt-injected. Avoid `config.yaml` except for user-editable settings. | Memory explorer recommendation from `get_hermes_home()` and memory injection evidence |
| Is the new `raphael/` state path protected by file safety? | Not yet. Cross-profile guard currently covers `skills`, `plugins`, `cron`, and `memories`, but not a future `raphael/` directory. Add `raphael` to `PROFILE_SCOPED_AREAS` or implement Raphael-specific guard before generic file tools write there. | `agent/file_safety.py:336` |
| Is a context fragment provider available? | Context engines have session lifecycle hooks and receive `hermes_home`; classify ephemeral recall/context as a context engine or context-engine plugin, not as durable memory. | `agent/context_engine.py:144`, `agent/agent_init.py:1526` |

Relevant focused tests:

```bash
rtk ./venv/bin/python -m pytest tests/tools/test_memory_tool.py tests/tools/test_memory_tool_schema.py tests/agent/test_memory_provider.py tests/agent/test_memory_user_id.py tests/run_agent/test_memory_provider_init.py tests/run_agent/test_memory_nudge_counter_hydration.py tests/run_agent/test_commit_memory_session_context_engine.py
rtk ./venv/bin/python -m pytest tests/test_hermes_home_profile_warning.py tests/hermes_cli/test_profiles.py tests/agent/test_file_safety_cross_profile.py tests/tools/test_cross_profile_guard.py tests/tools/test_file_state_registry.py tests/agent/test_context_engine.py tests/run_agent/test_plugin_context_engine_init.py
```

### Required Core Hooks

| Hook | Need | Classification | Evidence |
| --- | --- | --- | --- |
| action policy provider | Useful for mutation policy before risky tool calls; local Raphael policy can initially use config/plugin checks and slash access. | plugin workaround | `gateway/run.py:10231`, `hermes_cli/plugins.py:962` |
| generic approval API | Needed before staged skill evolution or tool forge can be safe across CLI/Slack/other platforms. Existing approval surfaces are fragmented. | upstream PR candidate | `gateway/platforms/slack.py:928`, `gateway/platforms/slack.py:937`, `gateway/run.py:14556` |
| plugin scoped state | Needed for a clean Raphael runtime state API; today plugin must use `get_hermes_home()` manually. | core patch needed | `hermes_cli/plugins.py:330`, `AGENTS.md:345` |
| status card delivery | Needed for portable status cards with dedupe/cooldown/threading. Existing `/status`, Slack assistant status, and delivery router are not typed status-card APIs. | upstream PR candidate | `gateway/delivery.py:95`, `gateway/delivery.py:329`, `gateway/platforms/slack.py:1247` |
| context fragment provider | Mostly available through `pre_llm_call` and context-engine plugin lifecycle. | available today | `hermes_cli/plugins.py:962`, `agent/context_engine.py:144`, `agent/agent_init.py:1526` |
| skill telemetry API | Existing `.usage.json` sidecar is already current-branch runtime data used by curator and skill invocation. Raphael can read it but should not own it. Preserve for Phase 1 if present; do not classify as upgrade-required until an upstream release-tag audit proves this is a local delta with a live-runtime contract. | available today | `tools/skill_usage.py:1`, `tools/skill_usage.py:592`, `agent/skill_commands.py:432` |
| skill provenance metadata | Existing sidecar tracks `created_by`, state, and pinning; enough for MVP scoring and provenance. Preserve for Phase 1 if present; do not classify as upgrade-required until an upstream release-tag audit proves this is a local delta with a live-runtime contract. | available today | `tools/skill_usage.py:592`, `tools/skill_manager_tool.py:874` |
| staged skill evolution API | Needed for safe Raphael evolution. Not present today. | upstream PR candidate | `tools/skill_manager_tool.py:440`, `tools/skill_manager_tool.py:533`, `hermes_cli/curator.py:391` |
| skill graph/dependency API | Useful for future synthesis, but current bundles and support-file hints are enough for MVP. | upstream PR candidate | `agent/skill_bundles.py:116`, `agent/skill_bundles.py:253` |
| tool forge sandbox API | Needed only for future Tool Forge. Not needed in Phase 1. | blocked pending design | Design spec non-goal for MVP; plugin registration exists in `hermes_cli/plugins.py:343` |
| capability manifest | Helpful for future risk classification. Current `plugin.yaml` has `provides_tools` and `provides_hooks`; extend manifest rather than adding runtime hook. | upstream PR candidate | `hermes_cli/plugins.py:260` |
| skill regression replay harness | Useful for mature evolution; not runtime core for MVP. | plugin workaround | Existing focused tests cover skill manager, curator, commands, and bundles |

## Phase 1 Recommendation

Proceed with **Advisor MVP only**, implemented as a disabled-by-default local Raphael plugin plus tests. Phase 1 should not depend on staged skill writes, cron mutation, memory mutation, or tool forge.

Include:

- `raphael.enabled` config defaulting to false.
- A no-op plugin load contract proving local plugin discovery and opt-in behavior.
- A read-only `/raphael-status` or `/raphael_status` command surface. Use `/raphael status` only if Phase 1 implements a single `/raphael` plugin command that parses subcommands, with CLI/gateway/Slack tests.
- Status-card data model with `observed_at`, `expires_at`, `source`, `confidence`, and `evidence_refs`.
- Risk classifier for R0/R1/R1.5/R2/R3 action proposals.
- Action proposal records stored under profile-aware Raphael runtime state.
- Audit events under `get_hermes_home() / "raphael"`.
- File-safety coverage for `raphael/` before generic file tools can write that state.

Exclude:

- Staged skill writes.
- Skill patching or deletion.
- Tool forge.
- Cron creation or mutation.
- Memory writes.
- Public Slack posting by default.
- RPG skill tree, rank, XP, or synthesis UI.

Recommended Phase 1 state path:

```text
get_hermes_home() / "raphael" / "state.json"
get_hermes_home() / "raphael" / "events.jsonl"
```

Recommended Phase 1 implementation split:

1. Config defaults and file-safety protection for `raphael/`.
2. Raphael runtime state helper with atomic writes.
3. Status-card and risk-classifier pure modules.
4. Disabled-by-default plugin that registers read-only command(s).
5. Tests for plugin disabled/enabled behavior, state path profile awareness, risk classes, and stale status expiry.

## Verification Commands

Phase 0 report checks:

```bash
rtk rg -n "T[B]D|TO[D]O|FIX[M]E|p[l]aceholders?|\\?\\?|P[e]nding" docs/superpowers/specs/2026-06-15-raphael-phase-0-discovery-report.md
rtk git diff --check -- docs/superpowers/specs/2026-06-15-raphael-phase-0-discovery-report.md
```

Report verification performed:

- Red-flag marker scan passed after escaping self-referential scan patterns.
- `git diff --check -- docs/superpowers/specs/2026-06-15-raphael-phase-0-discovery-report.md` passed.
- Reviewer agents found required fixes; this report incorporates them.

Focused suites to run before Phase 1 implementation:

```bash
rtk ./venv/bin/python -m pytest tests/test_transform_tool_result_hook.py tests/plugins/test_disk_cleanup_plugin.py tests/providers/test_plugin_discovery.py
rtk ./venv/bin/python -m pytest tests/hermes_cli/test_commands.py tests/gateway/test_gateway_command_help.py tests/gateway/test_unknown_command.py tests/gateway/test_config_driven_access_policy.py tests/gateway/test_pre_gateway_dispatch.py
rtk ./venv/bin/python -m pytest tests/tools/test_skill_manager_tool.py tests/tools/test_skill_usage.py tests/agent/test_skill_commands.py tests/agent/test_skill_bundles.py tests/gateway/test_bundles_command.py
rtk ./venv/bin/python -m pytest tests/cron/test_jobs.py tests/cron/test_scheduler.py tests/tools/test_cronjob_tools.py
rtk ./venv/bin/python -m pytest tests/tools/test_memory_tool.py tests/agent/test_memory_provider.py tests/agent/test_file_safety_cross_profile.py tests/tools/test_cross_profile_guard.py tests/agent/test_context_engine.py
```

These tests were not run in Phase 0 because the phase was read-only discovery and the command launcher intermittently hit file descriptor exhaustion while subagents were active.

## Open Risks

- `skills.write_approval` appears absent in code despite documentation hints. Treat any staged skill evolution work as new design, not existing integration.
- Plugin-scoped state lacks a first-class `PluginContext` API. Phase 1 can use `get_hermes_home() / "raphael"` directly, but a generic state API would be cleaner upstream.
- No dedicated Raphael no-op plugin fixture was created or run in Phase 0. Plugin viability is inferred from loader code and existing tests; Phase 1 must start with a disabled-by-default no-op plugin contract test before adding behavior.
- `raphael/` is not currently in cross-profile file-safety scoped areas.
- Status-card delivery and generic approval are fragmented across gateway, Slack, and command-specific confirmation paths.
- Cron `load_jobs()` and `tick()` can mutate runtime state; Phase 1 status must read cron metadata directly.
- Live GitHub Issues are disabled for `EndeavorYen/hermes-agent`, so local docs remain the tracking surface until repository settings change.
- Subagent read-only discovery hit intermittent `Too many open files` launcher errors; rerun focused tests in a calmer execution window before implementation.
