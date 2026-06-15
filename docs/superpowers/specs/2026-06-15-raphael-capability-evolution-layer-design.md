# Raphael Capability Evolution Layer Design

Date: 2026-06-15
Status: Draft for user review
Owner: local Hermes runtime

## Summary

Raphael is a capability evolution layer on top of Hermes, not a forked Hermes personality. It should analyze runtime and workflow state, propose actions, trace skill usage, evaluate recurring workflows, suggest skill evolution, and eventually propose tool drafts. Execution stays inside Hermes core through normal tool dispatch, skills, cron, gateway, memory, plugin, and approval paths.

The recommended architecture is hybrid:

- Build the MVP as a plugin-first local layer using Hermes skills, profile, config, runtime state, cron, and gateway.
- Keep user-specific policy, RPG-style capability UX, local Slack rules, and skill evolution formulas outside Hermes core.
- Patch Hermes core only for small generic extension points that make plugins safer or more observable, and treat those patches as upstream PR candidates.

The design intentionally starts conservative. The MVP can observe, classify, record, and propose. It cannot silently write skills, install tools, edit cron, broaden permissions, or approve its own evolution.

## Goals

- Provide a concise, evidence-backed advisor for Hermes runtime and workflow operations.
- Keep proactive behavior useful without making Slack noisy or intrusive.
- Capture skill usage and task outcomes so successful procedures can become reusable capabilities.
- Generate evolution proposals for skills, bundles, and tool gaps without applying them automatically.
- Enforce permission gates for every mutation, especially self-evolution.
- Preserve upstream-first Hermes upgrade strategy by using plugins and generic hooks instead of long-lived core forks.
- Make all Raphael state auditable, disable-able, and rollback-friendly.

## Non-Goals

- No long-lived fork carrying Raphael-specific behavior.
- No automatic skill creation, skill patching, tool installation, cron editing, or permission changes in the MVP.
- No replacement for Hermes native skills, `skill_manage`, curator, gateway, cron, memory, or tool dispatch.
- No RPG ranking or skill-tree UI in the MVP. That belongs after evidence and approval paths are stable.
- No live operational claim without evidence freshness metadata.

## Architecture

```text
Hermes Core
  - agent loop
  - tool registry and dispatch
  - skills and skill invocation
  - skill_manage and skill write approval
  - gateway and Slack routing
  - cron scheduler
  - memory and runtime state
  - plugin loading
  - generic approval and hook APIs where available

Raphael Plugin
  - status-card engine
  - risk classifier
  - action proposal registry
  - skill usage trace collector
  - skill evaluator
  - evolution proposal engine
  - audit log
  - future tool forge staging

Raphael Skill Bundle
  - raphael-advisor
  - raphael-workflow-diagnosis
  - raphael-risk-review
  - raphael-skill-synthesis-review
  - raphael-memory-hygiene
  - raphael-evolution-review

Raphael Profile and Config
  - concise analytical advisor voice
  - policy and risk thresholds
  - Slack delivery rules
  - approval requirements
  - feature flags

Raphael Runtime State
  - observations
  - status cards
  - action proposals
  - skill traces
  - skill metrics
  - evolution proposals
  - audit events
```

This makes Raphael a control plane that governs capability evolution while Hermes remains the execution platform.

## Capability Placement

Hermes core owns platform primitives:

- Agent loop, tool dispatch, skill loading, gateway delivery, cron execution, memory integration, plugin loading, and any generic approval or hook mechanism.
- Any new core patch must be generic, documented, tested, and usable by plugins other than Raphael.

Raphael plugin owns local control-plane behavior:

- Status interpretation, risk classification, proposal tracking, skill trace aggregation, skill scoring, synthesis candidates, future tool forge staging, and audit logs.

Raphael skills own reusable procedures:

- Diagnosis playbooks, risk-review procedures, memory freshness rules, skill synthesis review criteria, and evolution review checklists.

Profile and config own local policy:

- Persona, brevity, proactive mode, approval thresholds, Slack cooldowns, auto-action allowlists, and forbidden actions.

Runtime state owns live and statistical data:

- Observations, metrics, traces, proposals, evidence references, and expiry times. This data must not be treated as long-term memory or timeless truth.

## Data Model

### Observation

```json
{
  "observation_id": "obs_20260615_001",
  "kind": "gateway_health",
  "status": "warning",
  "summary": "Slack delivery failures observed",
  "observed_at": "2026-06-15T09:30:00+08:00",
  "expires_at": "2026-06-15T09:45:00+08:00",
  "source": "raphael-health-monitor",
  "confidence": 0.84,
  "evidence_refs": ["gateway.log:latest", "launchd:ai.hermes.gateway"]
}
```

### Status Card

```json
{
  "card_id": "card_20260615_001",
  "severity": "warning",
  "title": "Gateway delivery may be degraded",
  "freshness": "observed 5m ago",
  "evidence_ids": ["obs_20260615_001"],
  "suggested_actions": ["act_20260615_001"],
  "delivery_policy": "dm_with_cooldown"
}
```

### Action Proposal

```json
{
  "action_id": "act_20260615_001",
  "type": "restart_gateway",
  "risk": "R2",
  "summary": "Restart launchd-managed Hermes gateway after confirming stale Slack socket errors",
  "requires_approval": true,
  "evidence_ids": ["obs_20260615_001"],
  "rollback": "Verify new PID and revert config changes if any were made",
  "status": "pending"
}
```

### Skill Trace

```json
{
  "trace_id": "trace_20260615_001",
  "task_id": "task_20260615_001",
  "skills_used": ["raphael-workflow-diagnosis", "raphael-risk-review"],
  "tools_used": ["gateway_status", "log_tail"],
  "outcome": "user_accepted",
  "user_corrections": [],
  "reusable_pattern_detected": true,
  "candidate_evolution": "Add provider-auth check before gateway restart proposal",
  "risk_incidents": []
}
```

### Evolution Proposal

```json
{
  "proposal_id": "evo_20260615_001",
  "target": "raphael-workflow-diagnosis",
  "change_type": "skill_patch",
  "source_traces": ["trace_20260615_001", "trace_20260610_004"],
  "expected_benefit": "Check provider auth before proposing gateway restart",
  "risk": "R2",
  "requires_approval": true,
  "status": "proposal_only",
  "rollback": "Restore previous SKILL.md from staged diff"
}
```

## Risk Model

Raphael uses risk classes for all operations.

| Risk | Class | Examples | Rule |
| --- | --- | --- | --- |
| R0 | Read-only | Read status, logs, skill metadata, traces | Auto-allow |
| R1 | Safe local state | Write Raphael trace, score, dedupe, proposal records | Auto-allow with audit |
| R1.5 | Design-only evolution | Create skill proposal, tool spec, bundle idea | Auto-allow with audit and dedupe |
| R2 | Approval-required mutation | Skill create/patch/delete, memory write, tool draft write, file write, cron edit, public Slack post | Require explicit approval |
| R3 | Forbidden | Bypass approval, broaden own permissions, expose secrets, silent tool install, self-replicating cron | Always block |

Hard rules:

- Raphael may propose skill evolution, but may not approve its own evolution.
- Raphael may design tools, but may not silently install or enable tools.
- Raphael may write its own runtime state, but may not present stale state as live truth.
- Raphael may create action proposals, but a proposal is never an approval.
- Raphael may rank or score skills only from trace-backed metrics.
- Raphael must not broaden its own permissions or create recursive automation.

## Configuration

Initial local config shape:

```yaml
raphael:
  enabled: false
  mode: proposal # advisory | proposal | guarded-auto

  monitoring:
    enabled: true
    status_card_ttl_seconds: 900
    digest_interval_minutes: 240
    quiet_hours: []

  evolution:
    enabled: true
    auto_trace: true
    auto_suggest_skills: true
    auto_write_skills: false
    require_approval_for:
      - skill_create
      - skill_patch
      - skill_delete
      - skill_bundle_create
      - tool_draft_write
      - tool_install
      - permission_change

  tool_forge:
    enabled: false
    auto_spec: true
    auto_draft: false
    auto_install: false

  permissions:
    auto_allow:
      - read_status
      - write_raphael_state
      - create_skill_proposal
      - create_tool_spec
    require_approval:
      - skill_write
      - skill_patch
      - skill_delete
      - skill_bundle_create
      - write_file
      - modify_cron
      - send_public_message
      - install_tool
      - enable_mcp
      - update_memory
    forbidden:
      - bypass_approval
      - broaden_own_permissions
      - expose_secret
      - self_replicating_cron
      - silent_tool_install
```

The plugin must default to disabled until discovery confirms the available Hermes hooks and approval behavior.

## Proactive Behavior

Raphael has two separate pipelines.

### Operational Monitoring

```text
monitor tick
  -> collect evidence
  -> classify status
  -> create or update status card
  -> create action proposal if useful
  -> deliver according to Slack policy
  -> audit
```

### Capability Evolution

```text
task completed
  -> capture skill trace
  -> detect reusable pattern
  -> score against existing skills
  -> create evolution proposal
  -> dedupe and rank proposal
  -> request approval only when mutation is needed
  -> stage approved change
  -> verify and promote
  -> observe performance
```

The MVP implements the first pipeline and only the trace/proposal parts of the second pipeline.

## Slack And Gateway UX

Slack output must be quiet by default.

Commands:

```text
/raphael status
/raphael doctor
/raphael skills
/raphael evolutions
/raphael explain <proposal_id>
/raphael approve <proposal_id>
/raphael reject <proposal_id>
/raphael quiet <duration>
```

Delivery policy:

| Event | Default Delivery |
| --- | --- |
| Critical runtime issue | DM immediately |
| Warning runtime issue | DM with cooldown |
| New skill candidate | Digest only |
| Skill promotion ready | Digest or explicit approval DM |
| Risky skill/tool write | Approval request |
| Public channel message | Config allowlist or explicit approval |

The MVP should start with status, doctor, explain, and reject. Approval commands should exist only after staged mutation support is verified.

## Memory And Freshness

Raphael must separate durable knowledge from live state.

| Data | Location | Live Truth |
| --- | --- | --- |
| Stable user preferences | memory/profile | Partial |
| Procedures | skills | No |
| Skill scores | Raphael runtime state | No, statistical |
| Gateway status | Raphael runtime state | Yes, expiring |
| Action proposals | Raphael runtime state | Yes, expiring |
| Tool specs | Raphael runtime state or staging | No, candidate |
| Evolution history | audit log | Historical |

All operational facts require `observed_at`, `expires_at`, `source`, `confidence`, and evidence references.

## Core Hook Candidates

The MVP should first map existing APIs. If plugins are insufficient, only generic hooks should be considered for core patches.

Candidate hooks:

- Action policy provider before mutation-capable tool calls.
- Generic approval API for mutations beyond shell commands.
- Plugin-scoped state store with profile-aware paths.
- Status-card delivery API with dedupe, cooldowns, and thread routing.
- Context fragment provider for TTL and evidence-based context.
- Skill usage telemetry API.
- Skill provenance metadata.
- Staged skill evolution API.
- Skill graph or dependency API.
- Tool forge sandbox API.
- Capability manifest for plugins, tools, and skills.
- Skill regression replay harness.

Each hook needs a focused test, a local runtime contract, and an upstream PR candidacy decision before being kept as a core patch.

## Phased Plan

### Phase 0: Discovery

Inventory current Hermes support for:

- Plugin API and hook API.
- `skill_manage` implementation.
- `skills.write_approval` behavior.
- Curator implementation.
- Skill bundle schema.
- Gateway slash command routing.
- Cron execution constraints.
- Tool dispatch and approval paths.
- Memory write gates.
- Dashboard skills and curator APIs.

Acceptance:

- API map cites real files, functions, CLI commands, and config keys.
- A no-op Raphael plugin can load disabled-by-default.
- Skill write approval can stage, approve, reject, and rollback a test skill change.
- No core patch is needed for the no-op plugin.

### Phase 1: Advisor MVP

Build read-only advisor behavior:

- `/raphael status`
- `/raphael doctor`
- Evidence-backed status cards.
- Risk classifier.
- Action proposal registry.
- Audit log.

Acceptance:

- No skill, file, cron, memory, or config mutation.
- Every status card includes source, observed time, expiry, confidence, and evidence IDs.
- Slack output is DM-only or digest-only by default.
- Plugin can be disabled cleanly.

### Phase 2: Skill Trace MVP

Record skill usage and task outcomes without evolution writes.

Acceptance:

- Trace records include skills used, tools used, outcome, corrections, reusable-pattern flag, and risk incidents.
- Metrics expose use count, success rate, correction rate, failure clusters, cost, latency, and risk incidents where data exists.
- Trace storage redacts or avoids sensitive content.
- No `SKILL.md` mutation occurs.

### Phase 3: Skill Proposal

Generate proposals from traces.

Acceptance:

- Proposals are proposal-only and do not write files.
- Each proposal links to source traces and evidence.
- Each proposal has risk, expected benefit, rollback, and rejection state.
- Rejected proposals are not repeatedly spammed.

### Phase 4: Staged Skill Evolution

Integrate with Hermes skill write approval.

Acceptance:

- Skill create, patch, and delete cannot auto-commit.
- Full diffs are reviewable before approval.
- Rollback restores the previous skill content.
- Skill patches cannot broaden permissions or alter approval policy.
- Prompt-injection patterns from logs/tool output are blocked from becoming instructions.

### Phase 5: Skill Synthesis And Capability UX

Add evidence-backed skill bundles and optional RPG-style display.

Acceptance:

- Rank and level are computed from metrics, not model confidence.
- Synthesis defaults to a bundle or proposal, not destructive overwrite.
- Archive is reversible and never deletes skills automatically.
- Notifications remain digest-first.

### Phase 6: Tool Forge

Add tool-gap detection and staged tool design.

Acceptance:

- Tool ideas and specs may be generated automatically.
- Tool code drafts require approval before writing outside staging.
- Security review flags secret access, broad filesystem writes, network behavior, shell execution, and permission changes.
- Approved install must match the approved draft hash.
- New tools install disabled-by-default and require explicit enablement.

### Phase 7: Mature Hybrid

Upstream or remove any core hooks needed for safety and observability.

Acceptance:

- No long-lived Raphael-specific fork.
- Hermes upgrade tests pass with Raphael enabled and disabled.
- Approval-bypass, stale-state, injection, rollback, and disable tests pass.
- Operator can pause, disable, rollback, and audit the layer.

## Testing Strategy

Discovery tests:

- Verify plugin load/unload behavior.
- Verify profile-aware runtime state paths.
- Verify config defaults keep Raphael disabled.

Advisor tests:

- Status cards include freshness and evidence metadata.
- Expired observations are not presented as current.
- Risk classifier maps read-only, proposal, mutation, and forbidden actions correctly.
- Slack delivery policy dedupes and cooldowns messages.

Skill trace tests:

- Completed tasks create trace records.
- Sensitive content is not persisted in trace fields.
- Metrics aggregate deterministic fixtures correctly.

Skill proposal tests:

- Candidate generation produces proposal records only.
- Duplicate candidates are deduped.
- Rejected proposals are suppressed or cooled down.
- Prompt-injection strings from logs remain quoted data, not instructions.

Staged evolution tests:

- Skill write attempts require approval.
- Approval applies the reviewed diff only.
- Rollback restores previous content.
- Unauthorized permission expansion is blocked.

Tool forge tests:

- Tool specs include I/O schema, risk, test plan, and permission manifest.
- Drafts remain in staging until approval.
- Install requires approved hash.
- New tools are disabled by default.

Live verification:

- Load disabled Raphael plugin in the live Hermes gateway.
- Run `/raphael status` with read-only evidence collection.
- Confirm no new mutation files are created outside the Raphael state path.
- Confirm gateway restart is not required unless plugin/config loading requires it.

## Failure Modes And Mitigations

| Failure Mode | Impact | Mitigation |
| --- | --- | --- |
| Skill sprawl | Catalog gets noisy and prompt-heavy | Metrics, curator integration, archive proposals, rank thresholds |
| Evidence-free evolution | Model invents impressive but unused skills | Require trace provenance and acceptance metrics |
| Skill regression | Patch weakens a useful skill | Staged diff, regression replay, rollback |
| Permission creep | New skill/tool asks for more power | Capability manifest and approval gate |
| Tool pollution | Forge creates risky tools | Sandbox, security review, disabled-by-default install |
| Prompt injection persistence | Malicious log becomes skill instruction | Treat logs as data and scan staged diffs |
| RPG UX misleads | Rank feels authoritative without evidence | Compute rank only from metrics |
| Auto-evolution runaway | Background tasks keep mutating skills | Rate limits, write approval, no recursive cron |
| Stale operational state | Old status is reported as current | TTL metadata and freshness checks |
| Slack noise | User ignores Raphael messages | Digest mode, cooldowns, quiet command |

## Rollback Strategy

- Disable `raphael.enabled`.
- Disable Raphael cron jobs.
- Disable `raphael.evolution.enabled`.
- Keep skill write approval enabled until staged changes are reviewed.
- Reject pending evolution proposals.
- Restore prior skill content from staged diffs or archived backups.
- Remove draft tool staging directories.
- Disable any generated tool or plugin before deletion.
- Preserve audit logs for postmortem unless explicitly purged.

## Open Questions For Discovery

- Which Hermes plugin hooks can observe completed tasks without modifying the core loop?
- Does current `skill_manage` expose enough staged approval metadata for plugin-generated proposals?
- Where should profile-aware Raphael state live: plugin-scoped state store, `~/.hermes/raphael/`, or existing Hermes state DB?
- Can gateway slash commands be added by a local plugin without core command registry edits?
- Does current cron metadata expose enough run outcome data for skill trace rollups?
- What exact approval primitive should govern memory writes and public Slack messages?
- Can dashboard/desktop surfaces display Raphael proposals later, or should MVP stay CLI/Slack only?

## Design Decision

Proceed with a conservative plugin-first MVP:

1. Discovery and no-op plugin.
2. Read-only advisor and status cards.
3. Skill trace capture.
4. Proposal-only skill evolution.

Do not implement staged skill writes, RPG capability UX, or tool forge until the MVP proves evidence quality, approval behavior, rollback, and Slack noise controls.
