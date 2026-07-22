# Hermes v0.19 Local Port Manifest

Date: 2026-07-22

## Upgrade Boundary

- Upstream release: `v2026.7.20` / Hermes Agent 0.19.0 (Quicksilver)
- Upstream release commit: `3ef6bbd201263d354fd83ec55b3c306ded2eb72a`
- Accepted local baseline: `local/main` at `1d412e03bb248f71d9757c5053c4c2aa12c389b3`
- Live baseline: `runtime/current` at the same `1d412e03bb248f71d9757c5053c4c2aa12c389b3`
- Integration branch: `upgrade/v2026.7.20`, based directly on the peeled upstream release tag
- Integration topology: merge the accepted local baseline into the release branch. This preserves the full local history while making the release commit the upgrade base. Conflicts are resolved semantically rather than by mechanically keeping both sides.

The local delta from the previous upstream base contains 246 non-merge commits and a final net delta of 497 paths (374 added, 123 modified; 179,137 insertions and 512 deletions). The commits are highly iterative: many successive commits refine the same visual, story-video, Raphael, Codex, and runtime contracts. Classification is therefore performed on the final net behavior and path groups, while merge ancestry preserves the individual commit audit trail.

## Upstream Baseline Evidence

The pristine release was installed with the supported non-Matrix extras:

```bash
uv sync --extra dev --extra all --frozen
scripts/run_tests.sh -j 8
```

Result: 43,561 tests passed and 27 failed across 13 files. The failures were recorded before any local port and are the comparison baseline, not accepted regressions:

| Baseline file | Failures | Classification |
|---|---:|---|
| `tests/agent/test_anthropic_adapter.py` | 3 | macOS keychain subprocess leaks through incomplete mocks |
| `tests/agent/test_credential_pool_oat_authtype.py` | 1 | profile credential fallback side effect |
| `tests/gateway/test_background_command.py` | 1 | macOS `/tmp` canonicalizes to `/private/tmp` |
| `tests/gateway/test_shutdown_forensics.py` | 1 | Linux/systemd assumption on macOS |
| `tests/gateway/test_systemd_notify.py` | 1 | Linux/systemd assumption on macOS |
| `tests/hermes_cli/test_gateway_wsl.py` | 2 | WSL-only assumption on macOS |
| `tests/hermes_cli/test_gateway_service.py` | 4 | service-manager platform assumptions |
| `tests/hermes_cli/test_service_manager.py` | 2 | service-manager platform assumptions |
| `tests/hermes_cli/test_signal_handler_kanban_worker.py` | 1 | SIGTERM timing sensitivity |
| `tests/test_live_system_guard_self_test.py` | 4 | `systemctl` unavailable on macOS |
| `tests/tools/test_approval.py` | 1 | macOS `/tmp` canonicalization |
| `tests/tools/test_file_tools.py` | 3 | GNU-versus-BSD tool/flag semantics |
| `tests/tools/test_execution_flag_detection.py` | 3 | GNU-versus-BSD tool/flag semantics |

Any new failing test is a release blocker. A pre-existing failure may remain only if it is reproduced unchanged and is unrelated to an upgrade contract. Local macOS baseline fixes are expected to reduce this set.

## Final Delta Classification

| Net path group | Paths | Classification | Decision and exit condition |
|---|---:|---|---|
| Visual agent and image/video tooling | 158 | `port-core-required` plus `port-as-config/plugin/skill` | Keep the natural-language visual workflow, image-first video, artifact ranking, geometry preservation, provider failure attribution, and current-only delivery contracts. Prefer upstream 0.19 extension points wherever available. Core portions exit when upstream has tested equivalent routing and live wiring. |
| Story-video pipeline | 100 | `port-as-config/plugin/skill`, with narrow core adapters only where unavoidable | Keep because it is an active user-facing production path with manifests, narration, render QC, and delivery evidence. Generated media, provider responses, and private runtime traces remain uncommitted. Core adapters exit once the plugin surface covers the same contract. |
| Raphael control/evidence layer | 38 | `port-core-required` and `port-as-config/plugin/skill` | Keep the goal, evidence, routing, review, and bounded self-correction contracts. Discard edition-only or prompt-only duplication when upstream 0.19 already provides the mechanism. Every retained core seam needs a focused test and an upstream-equivalent search. |
| Core runtime and focused tests | 132 | Per-file `upstream-equivalent`, `port-core-required`, or `upstream-pr-candidate` | Audit conflict by conflict. Keep state durability, gateway restart/redelivery, session continuity, Codex app-server, turn finalization, cron evidence, and safety contracts only where current live callers exist. Generic platform fixes are upstream PR candidates; no upstream publication is authorized in this upgrade. |
| Governance and CI | 9 | `port-as-config` | Keep local branch/runtime governance and privacy gates. Rebase CI and test runner changes on the 0.19 workflow. Local policy must not be pushed to upstream. |
| Durable skills | 3 | `port-as-skill` | Keep versionable operator and goal contracts. Runtime prompts, ledgers, caches, and private preference traces remain local. |
| Slack platform integration | 3 | `port-core-required` | Port current selected native media delivery and visual-reference intake onto the upstream 0.19 delivery ledger/dedup path. Exit when upstream covers both behavior and live wiring. |
| Other additive docs/tests/fixtures | 57 | `discard`, `port-as-config/plugin/skill`, or sanitized test fixture | Keep only versionable documentation, schemas, and deterministic fixtures. Discard caches, media, provider logs, platform metadata, private prompts, and obsolete rehearsal artifacts. |

Totals: 497 classified net paths. The manifest describes the final effective delta; the full 246-commit history remains reachable through the merge parent.

## Conflict Resolution Ledger

The read-only merge simulation identified 28 conflicting paths. The initial resolution rule is recorded here and must be updated if implementation evidence changes the decision.

| Path | Initial decision |
|---|---|
| `.github/workflows/ci.yml` | Upstream 0.19 workflow base; port only hermetic macOS and local quality gates that remain relevant. |
| `agent/auxiliary_client.py` | Upstream client lifecycle base; retain proven local provider/evidence contracts. |
| `agent/codex_runtime.py` | Integrate local app-server/session durability into upstream 0.19 Codex runtime. |
| `agent/conversation_loop.py` | Upstream loop base; retain live Raphael/visual routing through explicit extension seams. |
| `agent/file_safety.py` | Keep stricter safe-path behavior unless upstream is equivalent; normalize macOS paths in tests, not by weakening checks. |
| `agent/skill_commands.py` | Upstream command registry base; port durable local skill exposure without private runtime state. |
| `agent/transports/hermes_tools_mcp_server.py` | Preserve upstream MCP surface and port tested local Codex/app/visual tool contracts. |
| `agent/turn_context.py` | Combine upstream context lifecycle with local goal/evidence and finalization state. |
| `agent/turn_finalizer.py` | Preserve upstream finalization semantics plus tested local durable-goal and artifact delivery guarantees. |
| `cron/scheduler.py` | Upstream scheduler base; retain execution ledger, heartbeat, and recovery evidence used by live jobs. |
| `gateway/run.py` | Upstream 0.19 gateway base; retain restart/resume, dedup, Slack, state, and live recovery contracts. |
| `hermes_cli/config.py` | Upstream configuration schema base; port only current local settings and compatibility shims with callers. |
| `hermes_cli/oneshot.py` | Upstream oneshot behavior plus tested Codex/session finalization compatibility. |
| `plugins/platforms/slack/adapter.py` | Upstream adapter and delivery ledger base; retain native selected-media upload and visual-reference intake. |
| `scripts/run_tests.sh` | Upstream runner base plus portable macOS isolation and parallel-test fixes. |
| `tests/agent/test_credential_pool.py` | Combine upstream cases with local hermetic macOS regressions. |
| `tests/agent/test_turn_context.py` | Combine upstream lifecycle cases with local goal/evidence contracts. |
| `tests/agent/transports/test_codex_app_server_session.py` | Combine both; retained implementation must satisfy session continuity. |
| `tests/agent/transports/test_hermes_tools_mcp_server.py` | Combine both tool-surface contracts and remove duplicate assertions only. |
| `tests/gateway/test_restart_resume_pending.py` | Combine both restart/redelivery cases. |
| `tests/hermes_cli/test_ignore_user_config_flags.py` | Combine both and keep hermetic config isolation. |
| `tests/run_agent/test_codex_app_server_integration.py` | Combine upstream integration coverage with local app-server behavior. |
| `tests/test_run_tests_parallel.py` | Use upstream runner expectations plus portable local parallelism checks. |
| `tests/test_tui_gateway_server.py` | Combine lifecycle and shutdown coverage. |
| `tests/tools/test_delegate.py` | Combine upstream delegation behavior with bounded local evidence/recovery cases. |
| `tests/tools/test_image_generation_plugin_dispatch.py` | Preserve upstream plugin dispatch and local visual-agent routing cases. |
| `tools/environments/base.py` | Upstream environment abstraction base; retain portable execution and evidence seams only. |
| `tools/image_generation_tool.py` | Integrate local candidate/ranking/repair behavior through upstream 0.19 provider and plugin interfaces. |

## Required Live Contracts Before Promotion

Promotion is blocked until current evidence proves all of the following:

1. Targeted tests cover every retained core conflict and pass.
2. The wider supported test suite introduces no failure beyond the pristine 0.19 baseline.
3. A copied production `state.db` passes schema/open/read checks without mutating the live database.
4. Gateway startup, auth/config loading, Codex app-server, session continuity, and controlled restart/resume pass.
5. Cron execution ledger and heartbeat remain readable and a non-destructive job smoke succeeds.
6. Slack mention/reply, deduplication, current selected media delivery, and visual-reference intake pass with no stale or duplicate artifact delivery.
7. Configured providers pass the smallest practical non-destructive smoke; unavailable credentials are reported as setup blockers, not hidden as product failures.
8. The visual and story-video paths pass artifact-level fixture/runtime evidence gates without committing generated media or private logs.
9. `local/main`, `origin/local/main`, `runtime/current`, `origin/runtime/current`, the editable install, and the running launchd gateway all resolve to the promoted commit.
10. Protected branch and remote push restrictions are restored and verified after cutover.

## Privacy and Publication Boundary

This upgrade is local integration work. Integration branches and protected role branches are pushed to `origin` only. No upstream issue or pull request is created. Generic fixes discovered during the port may be recorded as future upstream PR candidates, but publication requires a separate explicit user request and duplicate search.
