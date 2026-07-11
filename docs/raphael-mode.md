# Raphael Mode

Raphael mode is Hermes's goal, evidence, routing, and self-correction control
layer. It is not a persona prompt. Its job is to keep a foreground request
attached to one mission, route the request through one canonical decision,
require proof before completion claims, and make recovery visible to the
operator.

## Control Kernel

Every enabled foreground turn creates one `RaphaelTurnDecision`. That decision
contains the turn and mission identity, route, completion policy, required
proofs, next action, and effective runtime contract. Conversation, direct visual
handoff, finalization, status, and production replay consume this same shape.

The canonical state is `RaphaelState`. `active_mission` is the sole durable
foreground mission and `last_decision` is the latest foreground decision
snapshot. Legacy mission JSON is read only for one-time migration; new writes
go to canonical state.

## Turn Origins

Raphael distinguishes `foreground`, `background_review`, `cron`, `subagent`,
and `replay` turns. Only foreground turns may create or update the active
mission. Background and replay work can emit local evidence, but cannot replace
the user's mission or appear as the current mission in operator status.

## Proof Enforcement

Mutation and visual completion claims are checked by the shared production
finalizer before output transforms and persistence. Required proof is collected
from trusted tool results and structured evidence events. Missing proof changes
the result to `blocked_unverified_completion` with the missing proof and next
action; informational replies remain unchanged.

Visual evidence is turn-scoped and records proof type, status, source,
mission/turn identity, provider, selected artifact identity, observation time,
and a sanitized payload digest. Raw prompts, provider bodies, private paths,
and generated media are not stored in the event.

## Outcome-Driven Learning

Learning proposals require a stable failure cluster, foreground origin,
independent occurrence identity, component and owner, replay command, baseline
and target metrics, rollback condition, promotion gate, and approval class.
Two independent foreground occurrences, or a user correction plus a reproduced
failure, are required. Provider health, setup, artifact quality, preference,
and delivery failures stay in separate clusters. Durable policy changes remain
manual and R2/R3 changes require explicit approval.

## Runtime Truth And Recovery

The effective provider/model contract is resolved from live agent values over
configured defaults and is captured on the canonical decision. Status displays
that snapshot, but does not treat it as process proof. If gateway process
evidence is unavailable, status says so and directs the operator to
`hermes gateway status`.

The accepted promotion flow is one-way:

`reviewed feature or upgrade -> main checkout -> runtime worktree -> gateway restart`

An unreviewed feature worktree must never become the supervised service.
Rollback repoints the runtime worktree to the last accepted commit and restarts
the gateway; it does not rewrite the development branch.

If launchd cannot keep the installed service loaded, Hermes may use its explicit
detached gateway fallback. That state is degraded, not supervised production:
automatic start and automatic restart are unavailable until launchd management
is restored. `hermes gateway status` must report the fallback and the missing
restart guarantee instead of presenting the process as service-managed.

## Operator Commands

- `/raphael-status` or `hermes raphael status`: canonical mission, decision,
  proof, learning, and runtime snapshot.
- `/raphael-doctor`: local setup checks.
- `hermes raphael readiness --readiness-profile llm --check`: current LLM gate.
- `hermes raphael readiness --readiness-profile media --check`: current media
  gate.
- `hermes gateway status`: live gateway and service truth.
- `hermes raphael proposal approve|reject <ref>`: resolve an approval-gated
  proposal; approval does not itself mutate durable policy.

## Release Boundary

Markdown describes contracts, not freshness. Release claims come only from a
fresh machine-readable readiness or acceptance artifact. Production readiness
uses `producer=production_replay`, current effective provider/model identity,
focused tests, runtime smoke where wiring is live, and dual review when required
by the release plan. Generated media, provider logs, private prompts, caches,
and runtime ledgers stay local unless intentionally sanitized as fixtures.
