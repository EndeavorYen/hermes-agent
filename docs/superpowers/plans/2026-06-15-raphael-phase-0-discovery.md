# Raphael Phase 0 Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discover the exact Hermes extension, approval, gateway, cron, memory, and skill-management surfaces needed to implement the Raphael Capability Evolution Layer without starting with a fork.

**Architecture:** Phase 0 is documentation and verification only. It maps current Hermes APIs, proves whether a disabled no-op Raphael plugin can load, verifies skill write approval behavior, and produces the concrete Phase 1 implementation boundary. It must not add production Raphael behavior, mutate skills, enable cron jobs, or install tools.

**Tech Stack:** Hermes Agent Python codebase, pytest, local Hermes CLI, GitHub CLI for tracking if issues are enabled, Markdown design docs.

---

## Tracking Status

GitHub issue creation was attempted for `EndeavorYen/hermes-agent`, but GitHub returned that issues are disabled for the repository. Until issues are enabled, this local plan is the tracking source of truth.

Suggested issue title when GitHub Issues are enabled:

```text
Build Raphael capability evolution layer
```

Suggested issue body:

```markdown
## Summary

Track the Raphael Capability Evolution Layer for the local Hermes runtime.

Raphael should be a plugin-first, approval-gated capability evolution control plane on top of Hermes. It should observe runtime/workflow state, produce evidence-backed status cards, classify risk, create action proposals, trace skill usage, and later propose skill evolution and tool forge drafts. It must not become a long-lived fork or bypass Hermes approval paths.

## Design Spec

Related local spec:

- `docs/superpowers/specs/2026-06-15-raphael-capability-evolution-layer-design.md`

## Initial Scope

Phase 0 Discovery only:

- Map Hermes plugin and hook APIs.
- Verify whether plugin slash commands can be local-only.
- Verify `skill_manage` and `skills.write_approval` behavior.
- Identify curator and skill-bundle integration points.
- Map cron run metadata and gateway delivery surfaces.
- Map memory write gates and runtime state storage options.
- Prove whether a disabled no-op Raphael plugin can load without core changes.
- Produce the Phase 1 Advisor MVP implementation plan.

## Non-Goals For MVP

- No long-lived fork.
- No automatic skill writes.
- No tool installation.
- No cron mutation.
- No memory mutation.
- No RPG skill tree.
- No self-approved capability evolution.

## Acceptance Criteria

- Phase 0 API map cites real files, functions, commands, and config keys.
- No-op plugin load path is verified or blocked with exact evidence.
- Skill write approval behavior is verified with a harmless staged fixture or documented as blocked.
- Required core hooks are classified as `not needed`, `plugin workaround`, or `upstream PR candidate`.
- Phase 1 plan is ready and remains read-only.

Related: local design commit `1bac3c7c docs: design Raphael capability evolution layer`
```

## File Map

Create:

- `docs/superpowers/plans/2026-06-15-raphael-phase-0-discovery.md` - this implementation plan.
- `docs/superpowers/specs/2026-06-15-raphael-phase-0-discovery-report.md` - the final discovery report produced by Task 8.

Read and inspect:

- `docs/superpowers/specs/2026-06-15-raphael-capability-evolution-layer-design.md` - source design.
- `AGENTS.md` - repo architecture and local development rules.
- `hermes_cli/plugins.py` or the current plugin loader file if the name has changed.
- `plugins/` - examples of plugin manifests, tools, hooks, and optional commands.
- `hermes_cli/commands.py` - slash command registry and gateway command metadata.
- `gateway/run.py` - gateway command dispatch and platform routing.
- `agent/skill_commands.py` - skill command loading.
- `skills/` and `optional-skills/` - built-in skill shape.
- `tools/` and `tools/registry.py` - tool registration and dispatch conventions.
- `model_tools.py` - tool discovery and execution path.
- `run_agent.py` - agent loop and possible task-completion observation points.
- `cron/` - scheduled task schema and run metadata.
- `memory/`, `agent/`, and memory-related config code - memory write/read behavior.
- Curator implementation files found through `rg -n "curator|skill_manage|write_approval|skill bundle|bundle"`.

Do not modify production files in Phase 0 unless a task explicitly says to create a disabled fixture. Any fixture must be test-only or disabled-by-default and must be removed or documented before the final report.

## Task 1: Confirm Repo And Tracking Surfaces

**Files:**
- Read: `docs/superpowers/specs/2026-06-15-raphael-capability-evolution-layer-design.md`
- Read: `.gitignore`
- Create/Modify: `docs/superpowers/specs/2026-06-15-raphael-phase-0-discovery-report.md`

- [ ] **Step 1: Confirm repository and default branch**

Run:

```bash
rtk gh repo view EndeavorYen/hermes-agent --json nameWithOwner,defaultBranchRef,url
rtk git status --short --branch
rtk git remote -v
```

Expected:

```text
nameWithOwner is EndeavorYen/hermes-agent
defaultBranchRef.name is main
origin points to EndeavorYen/hermes-agent
upstream points to NousResearch/hermes-agent
```

- [ ] **Step 2: Check whether GitHub Issues are enabled**

Run:

```bash
rtk gh issue list --repo EndeavorYen/hermes-agent --limit 1
```

Expected:

```text
Either a normal issue list is returned, or GitHub reports that issues are disabled.
```

If issues are enabled, create the issue using the issue body in this plan. If issues are disabled, do not modify repository settings. Record the disabled-issues result in the discovery report.

- [ ] **Step 3: Create the discovery report skeleton**

Create `docs/superpowers/specs/2026-06-15-raphael-phase-0-discovery-report.md` with this exact skeleton:

```markdown
# Raphael Phase 0 Discovery Report

Date: 2026-06-15
Status: Draft

## Summary

Phase 0 maps the current Hermes extension and approval surfaces for the Raphael Capability Evolution Layer.

## Tracking

- Design spec: `docs/superpowers/specs/2026-06-15-raphael-capability-evolution-layer-design.md`
- Tracking issue: unavailable until GitHub Issues are enabled for `EndeavorYen/hermes-agent`

## Findings

### Repository

| Item | Result | Evidence |
| --- | --- | --- |
| Repo |  |  |
| Default branch |  |  |
| Issues enabled |  |  |

### Plugin API

| Question | Result | Evidence |
| --- | --- | --- |
| How are local plugins discovered? |  |  |
| Can a plugin register tools? |  |  |
| Can a plugin register hooks? |  |  |
| Can a plugin register slash commands? |  |  |
| Can a plugin store profile-scoped state? |  |  |

### Skill Management

| Question | Result | Evidence |
| --- | --- | --- |
| Where is `skill_manage` implemented? |  |  |
| Does `skills.write_approval` exist? |  |  |
| Can skill writes be staged? |  |  |
| Can staged skill writes be rejected and rolled back? |  |  |

### Gateway And Slack

| Question | Result | Evidence |
| --- | --- | --- |
| Where are gateway slash commands dispatched? |  |  |
| Can plugin commands appear in Slack? |  |  |
| Is there a delivery policy or cooldown hook? |  |  |

### Cron

| Question | Result | Evidence |
| --- | --- | --- |
| Where are cron jobs stored? |  |  |
| Where are run outputs stored? |  |  |
| Is run outcome metadata available? |  |  |
| Are recursive cron protections present? |  |  |

### Memory And State

| Question | Result | Evidence |
| --- | --- | --- |
| How are memory reads injected? |  |  |
| How are memory writes gated? |  |  |
| Where should Raphael state live? |  |  |

### Required Core Hooks

| Hook | Need | Classification | Evidence |
| --- | --- | --- | --- |
| action policy provider |  |  |  |
| generic approval API |  |  |  |
| plugin scoped state |  |  |  |
| status card delivery |  |  |  |
| context fragment provider |  |  |  |
| skill telemetry API |  |  |  |
| skill provenance metadata |  |  |  |

## Phase 1 Recommendation

## Verification Commands

## Open Risks
```

- [ ] **Step 4: Commit the report skeleton only if Task 1 is a standalone checkpoint**

Run:

```bash
rtk git add docs/superpowers/specs/2026-06-15-raphael-phase-0-discovery-report.md
rtk git commit -m "docs: start Raphael phase 0 discovery report"
```

Expected:

```text
Commit succeeds and includes only the report skeleton.
```

If executing all tasks in one branch before committing, skip this commit step and commit at Task 8.

## Task 2: Map Plugin Loading And Extension Surfaces

**Files:**
- Read: `hermes_cli/plugins.py` or actual plugin loader files found by search
- Read: `plugins/**/plugin.yaml`
- Read: `plugins/**/__init__.py`
- Modify: `docs/superpowers/specs/2026-06-15-raphael-phase-0-discovery-report.md`

- [ ] **Step 1: Locate plugin loader and plugin examples**

Run:

```bash
rtk rg -n "class Plugin|register_tool|register_hook|plugin.yaml|entry_points|plugins" hermes_cli plugins tests -g '*.py' -g '*.yaml' -g '*.yml'
```

Expected:

```text
Output identifies the plugin loader, plugin context API, and at least one local plugin example.
```

- [ ] **Step 2: Record local plugin discovery paths**

Inspect the loader files and record:

```text
- repo plugin paths
- user plugin paths
- project plugin paths
- pip entry point support if present
- disabled-by-default or config gating behavior if present
```

Update the report's Plugin API table with exact file paths and function/class names.

- [ ] **Step 3: Check whether plugins can register tools, hooks, and commands**

Run:

```bash
rtk rg -n "register_tool|register_hook|register_command|slash|CommandDef|toolset" hermes_cli plugins gateway tools tests -g '*.py'
```

Expected:

```text
The output either proves plugin registration support or shows that commands require core registry edits.
```

Update the report with `yes`, `no`, or `partial`, plus evidence.

## Task 3: Map Skill Management And Approval

**Files:**
- Read: files found by `rg -n "skill_manage|write_approval|pending review|staged|curator"`
- Read: `agent/skill_commands.py`
- Read: `skills/`
- Modify: `docs/superpowers/specs/2026-06-15-raphael-phase-0-discovery-report.md`

- [ ] **Step 1: Locate skill management implementation**

Run:

```bash
rtk rg -n "skill_manage|write_approval|skills.write_approval|pending review|approve|reject|curator|bundle" . -g '*.py' -g '*.md' -g '*.yaml' -g '*.yml'
```

Expected:

```text
Output identifies skill management, approval config, curator, and any bundle docs or tests.
```

- [ ] **Step 2: Identify config keys and approval flow**

Inspect the files from Step 1 and record:

```text
- config key names
- create/edit/patch/delete behavior
- where staged writes are stored
- how approval and rejection happen
- whether rollback is automatic or manual
```

Update Skill Management table in the report.

- [ ] **Step 3: Verify with tests or a harmless fixture if available**

Run the focused existing tests first:

```bash
rtk rg -n "write_approval|skill_manage|curator" tests -g '*.py'
```

If focused tests exist, run the smallest relevant set:

```bash
rtk ./venv/bin/python -m pytest <focused-test-file> -q
```

Expected:

```text
Focused tests pass, or the report records why they cannot run in the current environment.
```

Do not create or mutate a real user skill during Phase 0 unless the approval path has an explicit harmless test fixture.

## Task 4: Map Gateway And Slack Command Delivery

**Files:**
- Read: `hermes_cli/commands.py`
- Read: `gateway/run.py`
- Read: `gateway/platforms/slack*` files if present
- Modify: `docs/superpowers/specs/2026-06-15-raphael-phase-0-discovery-report.md`

- [ ] **Step 1: Locate command registry and gateway dispatch**

Run:

```bash
rtk rg -n "COMMAND_REGISTRY|GATEWAY_KNOWN_COMMANDS|slack_subcommand_map|resolve_command|gateway_only|gateway_config_gate|slash" hermes_cli gateway tests -g '*.py'
```

Expected:

```text
Output identifies where CLI and gateway commands are registered and dispatched.
```

- [ ] **Step 2: Determine whether local plugin slash commands are possible**

Inspect command registration and plugin command support. Record one of:

```text
plugin-supported
core-registry-required
skill-command-only
unknown
```

Add evidence to the Gateway And Slack table.

- [ ] **Step 3: Check delivery policy and noise controls**

Run:

```bash
rtk rg -n "cooldown|dedupe|thread|reply|DM|direct|notify|quiet|digest|rate" gateway hermes_cli tests -g '*.py' -g '*.yaml'
```

Expected:

```text
Output identifies existing delivery controls, or the report records that Raphael needs its own plugin-level cooldown state.
```

## Task 5: Map Cron Metadata And Recursion Protections

**Files:**
- Read: `cron/`
- Read: `gateway/run.py` cron-related paths if present
- Read: `config.yaml` cron section
- Modify: `docs/superpowers/specs/2026-06-15-raphael-phase-0-discovery-report.md`

- [ ] **Step 1: Locate cron storage and scheduler implementation**

Run:

```bash
rtk rg -n "cron|jobs.json|output|recursive|recursion|no-agent|dispatch_in_gateway|run output|run_id" cron gateway hermes_cli tests -g '*.py' -g '*.md' -g '*.yaml'
```

Expected:

```text
Output identifies job storage, output directory, scheduler, and recursion protections if they exist.
```

- [ ] **Step 2: Inspect live local cron paths read-only**

Run:

```bash
rtk ls -la /Users/simon/.hermes/cron
rtk find /Users/simon/.hermes/cron -maxdepth 2 -type f
```

Expected:

```text
The report records jobs and output path shapes without modifying any cron file.
```

- [ ] **Step 3: Record whether Phase 1 can avoid cron mutation**

Update the report:

```text
Phase 1 should not create cron jobs. It should expose read-only CLI/Slack status first. Cron-based monitors can be planned after Advisor MVP verification.
```

## Task 6: Map Memory And Raphael State Storage

**Files:**
- Read: memory-related files found by search
- Read: `hermes_constants.py`
- Read: `agent/file_safety.py`
- Modify: `docs/superpowers/specs/2026-06-15-raphael-phase-0-discovery-report.md`

- [ ] **Step 1: Locate memory read/write implementation**

Run:

```bash
rtk rg -n "memory_enabled|user_profile_enabled|write_memory|memory write|memory_path|Memory|memories|remember|forget|get_hermes_home|profile-aware" agent memory hermes_cli tools tests -g '*.py' -g '*.md'
```

Expected:

```text
Output identifies memory injection, write gates, provider behavior, and profile-aware path helpers.
```

- [ ] **Step 2: Identify safe Raphael state location**

Inspect `get_hermes_home()` usage and file-safety rules. Recommend one state path:

```text
<HERMES_HOME>/raphael/state.jsonl
```

or a better existing plugin state store if discovered. The report must include why this path is profile-aware and why it avoids long-term memory staleness.

- [ ] **Step 3: Record freshness rules**

Add this rule to the report:

```text
Every operational fact must include observed_at, expires_at, source, confidence, and evidence_refs. Expired operational facts must not be injected as current context.
```

## Task 7: Classify Required Core Hooks

**Files:**
- Modify: `docs/superpowers/specs/2026-06-15-raphael-phase-0-discovery-report.md`

- [ ] **Step 1: Fill hook classification table**

For each hook from the design spec, classify as:

```text
not needed
available today
plugin workaround
core patch needed
upstream PR candidate
blocked pending design
```

Required rows:

```text
action policy provider
generic approval API
plugin scoped state
status card delivery
context fragment provider
skill telemetry API
skill provenance metadata
staged skill evolution API
skill graph/dependency API
tool forge sandbox API
capability manifest
skill regression replay harness
```

- [ ] **Step 2: Add Phase 1 boundary**

Add a Phase 1 recommendation that includes only:

```text
- disabled-by-default Raphael config
- read-only status command
- status card data model
- risk classifier
- action proposal records
- audit log
```

Explicitly exclude:

```text
- staged skill writes
- tool forge
- cron mutation
- memory mutation
- public Slack posting by default
- RPG skill tree
```

## Task 8: Verify, Self-Review, And Commit Discovery Report

**Files:**
- Modify: `docs/superpowers/specs/2026-06-15-raphael-phase-0-discovery-report.md`

- [ ] **Step 1: Red-flag marker scan**

Run:

```bash
rtk rg -n "T[B]D|TO[D]O|FIX[M]E|p[l]aceholders?|\\?\\?|  \\|" docs/superpowers/specs/2026-06-15-raphael-phase-0-discovery-report.md
```

Expected:

```text
No red-flag markers remain. Empty table cells are allowed only if the row explicitly says blocked or unavailable with evidence.
```

- [ ] **Step 2: Verify whitespace and staged scope**

Run:

```bash
rtk git diff --check -- docs/superpowers/specs/2026-06-15-raphael-phase-0-discovery-report.md
rtk git status --short --branch
```

Expected:

```text
No whitespace errors. Status may include unrelated pre-existing image/visual changes, but the discovery report is the only file staged for this work.
```

- [ ] **Step 3: Commit the completed report**

Run:

```bash
rtk git add -f docs/superpowers/specs/2026-06-15-raphael-phase-0-discovery-report.md
rtk git commit -m "docs: complete Raphael phase 0 discovery"
```

Expected:

```text
Commit includes only the discovery report, unless Task 1 already committed the skeleton.
```

- [ ] **Step 4: Write Phase 1 plan only after report is complete**

Do not write Phase 1 implementation plan until this report is reviewed. Phase 1 must be based on actual discovered Hermes APIs, not assumptions from the design spec.

## Plan Self-Review

Spec coverage:

- The plan covers Phase 0 Discovery from the Raphael design spec.
- It maps plugin APIs, skill write approval, curator, gateway, cron, memory, and required core hooks.
- It keeps MVP behavior read-only and proposal-only.
- It avoids implementation of staged writes, tool forge, RPG UX, and cron mutation.

Red-flag marker scan:

- This plan intentionally includes report skeleton blank cells because Task 1 creates a working report template. The execution task requires replacing those cells with evidence or explicit blocked/unavailable results.

Type and path consistency:

- The design spec path is `docs/superpowers/specs/2026-06-15-raphael-capability-evolution-layer-design.md`.
- The discovery report path is `docs/superpowers/specs/2026-06-15-raphael-phase-0-discovery-report.md`.
- The plan path is `docs/superpowers/plans/2026-06-15-raphael-phase-0-discovery.md`.
