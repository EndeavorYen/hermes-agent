# Raphael Production Control Kernel Design

**Status:** Implemented on `raphael/control-kernel-hardening`; release gates pending

**Date:** 2026-07-11

## Purpose

Raphael mode is Hermes' high-level control layer. It must preserve the user's
goal, choose the right execution path and provider, require evidence before
completion claims, classify failures, repair or escalate them, and turn repeated
failures into auditable improvement proposals. It is not a persona-only prompt,
a second visual pipeline, or a release-report generator detached from runtime.

This design replaces the current split between production visual control,
detached router/proof simulations, two mission representations, and background
review side effects with one production control kernel.

## Goals

1. Use one canonical foreground mission and state store.
2. Produce one canonical control decision per foreground turn.
3. Route general conversation, tool tasks, visual work, follow-ups, and
   clarification through the same decision contract.
4. Enforce structured proof requirements in the real turn finalizer.
5. Prevent internal turns from mutating foreground goal state.
6. Resolve model and provider contracts from effective runtime configuration.
7. Promote learning only when replay evidence proves a useful improvement.
8. Make operator status reflect the live runtime, not stale or simulated state.
9. Prove release readiness through the production conversation path.
10. Require both Codex self-review and an independent Grok review before a PR.

## Non-Goals

- Replacing the existing visual agent implementation.
- Automatically applying skill, memory, cron, provider, or public-delivery
  mutations without the normal approval gates.
- Claiming Grok, video, Slack delivery, or full media readiness without current
  live evidence for those slices.
- Preserving unused compatibility surfaces indefinitely.
- Deploying an unreviewed feature branch as the live launchd gateway.

## Considered Approaches

### A. Canonical kernel with staged migration — selected

Introduce one canonical decision and mission contract, connect production
adapters to it, migrate existing state, and then remove detached legacy paths.
This keeps the change reviewable while ensuring the end state has one control
plane.

### B. Big-bang rewrite — rejected

Deleting all Raphael modules and replacing them at once would produce a cleaner
diff in theory, but it would combine state migration, routing, proof enforcement,
visual integration, evolution, and release evidence into one high-risk cutover.

### C. Add wiring without consolidation — rejected

Calling the existing proof helper from the finalizer would be fast, but would
leave two mission models, two routers, hard-coded provider contracts, and a
readiness simulator that can diverge from production.

## Canonical Contracts

### Turn origin

Every turn receives a required origin:

```python
class RaphaelTurnOrigin(str, Enum):
    FOREGROUND = "foreground"
    BACKGROUND_REVIEW = "background_review"
    CRON = "cron"
    SUBAGENT = "subagent"
    REPLAY = "replay"
```

Only `FOREGROUND` may create, replace, or advance the foreground mission.
`REPLAY` uses an isolated state store. Other origins may append diagnostic or
learning evidence but cannot write foreground mission or selected-artifact
state.

The turn origin is carried through `build_turn_context`, plugin hooks,
conversation execution, finalization, and evolution records. It must not be
inferred from prompt text.

### Runtime contract

```python
@dataclass(frozen=True)
class RaphaelRuntimeContract:
    base_provider: str
    base_model: str
    base_api_mode: str
    visual_planner_provider: str | None
    visual_planner_model: str | None
    image_provider: str | None
    image_model: str | None
    video_provider: str | None
    video_model: str | None
    source: str
```

The resolver consumes the same effective configuration and fallback selection
used by the running agent. No release or route decision may hard-code
`gpt-5.5`, `grok-4.3`, or another versioned model as current runtime truth.
Release profiles may express capability constraints, such as OpenAI-family
provider or minimum evidence fields, without pinning an obsolete model name.

### Mission

There is one persisted `RaphaelMission` representation:

```python
@dataclass(frozen=True)
class RaphaelMission:
    mission_id: str
    goal: str
    success_conditions: tuple[str, ...]
    phase: str
    blockers: tuple[str, ...]
    next_action: str
    required_proofs: tuple[str, ...]
    proof_status: str
    active_artifact_id: str | None
    artifacts: tuple[MissionArtifact, ...]
    last_evidence: tuple[str, ...]
    last_user_request: str | None
    created_at: datetime
    updated_at: datetime
```

Mission state lives inside the canonical Raphael state document. The existing
standalone mission file is read only by a migration adapter. On first canonical
write, the adapter imports compatible fields, records migration provenance, and
retires the legacy file. New code must not write both stores.

### Turn decision

```python
@dataclass(frozen=True)
class RaphaelTurnDecision:
    turn_id: str
    origin: RaphaelTurnOrigin
    mission_id: str | None
    mode: str
    target_artifact: str
    route: RaphaelRouteDecision
    required_proofs: tuple[str, ...]
    completion_policy: str
    blockers: tuple[str, ...]
    next_action: str
    clarification_question: str | None
    confidence: float
    runtime_contract: RaphaelRuntimeContract
```

The decision is produced once. The conversation loop, direct visual handoff,
tool execution, finalizer, status surface, and release replay all consume this
same decision or its stable serialized form.

## Production Turn Flow

1. `build_turn_context` attaches an explicit origin and effective runtime
   contract.
2. The Raphael pre-LLM hook observes the foreground request without mutating
   state.
3. The canonical kernel resolves or creates the mission and produces the turn
   decision under a state lock.
4. The decision is recorded as a structured event with task, turn, mission,
   runtime-contract, and route provenance.
5. The conversation loop executes the selected adapter:
   - direct response for general conversation;
   - normal tool loop for tool tasks;
   - existing visual-agent handoff for visual work;
   - one precise question for blocked ambiguity.
6. Tool and provider results append structured evidence events.
7. The real finalizer evaluates the required proofs before accepting a
   completion claim.
8. Passed proof advances the mission. Missing proof either schedules the next
   safe verification step or changes the public result to a blocked state.
9. Evolution consumes the completed decision, evidence, and outcome after the
   user response; it cannot rewrite foreground mission state.

The Codex app-server path must run the same decision and finalization hooks. A
separate transport cannot bypass Raphael proof enforcement.

## Proof Enforcement

Proof is represented by structured events, not by finding phrases in terminal
text alone:

```python
@dataclass(frozen=True)
class RaphaelEvidenceEvent:
    evidence_id: str
    mission_id: str | None
    turn_id: str
    proof_type: str
    source: str
    status: str
    command: str | None
    artifact_id: str | None
    provider: str | None
    observed_at: datetime
    payload_digest: str
```

Adapters may parse legacy tool output into evidence events, but finalizer logic
only consumes validated events. Failed commands, stale artifacts, unmatched
session ids, provider-only self-scores, and unassociated screenshots cannot
satisfy proofs.

Completion policies:

- `informational`: no mutation claim; grounded-answer proof is sufficient.
- `mutation`: focused verification and diff hygiene are required.
- `runtime`: focused verification plus runtime smoke are required.
- `visual`: selected-current-artifact, freshness, independent quality, and clean
  delivery proofs are required.
- `release`: profile-specific fresh evidence and claim-boundary validation are
  required.

If the assistant says work is complete while required proofs are missing, the
finalizer changes the result to `blocked_unverified_completion`, includes the
missing proof types and next command, and records an evolution signal. It does
not merely add an audit record after returning an unsupported success claim.

## Visual Integration

The existing `visual_agent_generate` path remains the execution surface.
Raphael owns intent, mission continuity, provider contract, evidence policy, and
delivery authorization.

The visual adapter must:

- consume the canonical decision rather than recomputing it;
- attach current mission and artifact ids;
- preserve semantic reference roles;
- require image-first single-source evidence for video;
- block stale, duplicate, rejected, or unselected artifacts;
- classify failures as setup, quota, provider health, moderation, handoff,
  browser automation, selection, geometry, quality, or delivery;
- return the failure layer to the canonical mission and learning loop.

## Outcome-Driven Learning

Repeated signals do not automatically justify a patch. A promotion candidate
requires:

- a stable failure-cluster id;
- at least two independent foreground occurrences or one explicit user
  correction plus one reproducible failure;
- affected component and owner;
- a concrete minimal proposed change;
- a replay fixture or command;
- baseline and target outcome metrics;
- promotion and rollback conditions;
- approval classification.

Primary metrics are recurrence reduction, successful recovery rate, false
proposal rate, user correction rate, and human interventions per completed
mission. Proposal count is diagnostic only.

Background review uses an isolated origin and state namespace. Approval records
do not apply a change. Durable promotion remains a separate, reviewable action.

## Operator And Documentation Surfaces

`docs/raphael-mode.md` becomes the durable architecture and operator contract.
It describes the control loop, state model, origins, failure model, proof
policies, runtime commands, and recovery procedures. It does not embed mutable
claims that evidence is currently fresh.

Readiness JSON is the authoritative current snapshot. Release-facing Markdown
may link to a generated snapshot but must label timestamps and expiry. Stale
evidence must render as stale rather than remain described as current.

`/raphael-status` and `hermes raphael status` show:

- foreground mission only;
- last canonical decision and proof state;
- current blockers and next action;
- effective provider/model contract;
- live checkout, commit, and gateway service path when available;
- evolution proposals and their promotion state;
- degraded control-layer conditions.

Internal labels, private paths, secrets, rejected media, and raw provider output
remain redacted from user-facing status.

## Runtime Deployment Boundary

Development occurs in the feature worktree. Live feature verification uses an
isolated gateway process and port. The launchd service is repaired separately to
point at the accepted runtime worktree and may be restarted after recording the
pre-change PID, command, commit, and editable-install path.

An unreviewed feature worktree must never replace the supervised live service.
After any accepted promotion, runtime moves one way:

`reviewed feature/upgrade → main checkout → runtime worktree → gateway restart`

Rollback means repointing or fast-forwarding the runtime worktree to the last
accepted commit and restarting the gateway; it does not rewrite the development
branch.

## Migration And Compatibility

1. Add origin and runtime-contract plumbing without changing routing behavior.
2. Add canonical mission serialization and one-time legacy migration.
3. Connect visual handoff and status to the canonical decision.
4. Connect tool-task finalization to structured proof enforcement.
5. Move readiness simulations onto production replay adapters.
6. Convert evolution proposals to the outcome contract.
7. Remove legacy mission writes, detached router paths, unused response governor,
   and other compatibility surfaces after usage searches and tests prove no
   callers remain.

Every temporary compatibility reader records its caller and has the exit
condition: no production writer or test depends on the legacy schema.

## Testing Strategy

### Unit tests

- origin propagation and foreground write policy;
- runtime-contract resolution from config and active fallback;
- canonical mission serialization and migration;
- decision routing for conversation, tool, visual, follow-up, and clarification;
- evidence validation and completion policies;
- failure classification and learning-promotion thresholds.

### Production-path integration tests

- `run_conversation` tool task cannot return an unsupported completion claim;
- valid focused-test and runtime-smoke evidence allows completion;
- direct visual handoff consumes the same persisted decision;
- background review with an empty mission cannot create a foreground mission;
- background review with an active mission cannot alter it;
- Codex app-server turns run the same pre/post Raphael gates;
- status reports canonical mission and effective runtime contract;
- release replay calls production routing and finalization adapters.

### Runtime acceptance

- accepted runtime worktree, editable install, launchd command, process command,
  and commit agree;
- gateway status no longer reports a stale service definition;
- isolated feature gateway passes a text tool-task smoke and a no-quota visual
  routing smoke;
- an approved live visual smoke records current selected-artifact and quality
  evidence when provider quota is intentionally enabled.

## Release And Review Gates

Before PR creation:

1. All requirement-linked tests and the relevant wider suites pass.
2. Ruff/static checks and `git diff --check` pass.
3. Package install, CLI lifecycle, production replay, and runtime acceptance
   artifacts are fresh and privacy-safe.
4. Codex performs a requirement-by-requirement hostile self-review of the final
   diff and evidence.
5. An independent Grok review receives the committed diff, this specification,
   verification output, and residual risks. It must return no unresolved
   critical or important finding.
6. Any review finding is fixed with a failing regression first and both reviews
   are rerun on the new head commit.
7. The target is queried from the live `origin` repository immediately before
   PR creation. The target must be both the remote default branch and not named
   `main`. If those conditions conflict, PR creation stops for an explicit user
   decision.
8. The branch is pushed only to `origin`; no upstream PR or issue is created.

## Acceptance Criteria

The work is complete only when current evidence proves all of the following:

- live gateway routing is truthful and recoverable;
- one canonical mission and decision drive production paths;
- internal turns cannot pollute foreground mission state;
- runtime provider/model reporting matches effective configuration;
- unsupported completion claims are blocked in the real finalizer;
- visual handoff and delivery use canonical evidence policy;
- learning proposals are outcome-backed and approval-gated;
- durable design and operator docs match shipped behavior;
- production-path acceptance artifacts are fresh;
- Codex and independent Grok reviews both pass on the final commit;
- the PR targets the verified non-`main` remote default branch.
