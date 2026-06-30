# Raphael Wow Mode Design

## Purpose

Raphael mode must be strong enough that a new user can enable it, summon it,
and immediately feel that Hermes has evolved from a tool-using agent into a
Sage King control layer.

This is not a persona refresh. The public standard is a release-safe
translation of the Raphael / Great Sage fantasy into Hermes capabilities:
appraise the situation, simulate strategies, synthesize context, refactor
skills, split and fuse specialist modes, evolve from evidence, and report
proof before claiming success.

Reference inspiration:

- Raphael / Lord of Wisdom: https://tensura.fandom.com/wiki/Raphael
- Great Sage: https://tensura.fandom.com/wiki/Great_Sage

The implementation must not claim omniscience or impersonate a copyrighted
character. It should preserve the archetype: cold appraisal, fast simulation,
best-action selection, skill optimization, and auditable evolution.

## Approved Goal Baseline

Upgrade Hermes Raphael mode to the public "wow, this is a real evolution"
standard:

- `Situation Appraisal`: parse intent, risk, missing context, success
  conditions, usable tools, provider state, current artifact, and blockers.
- `Parallel Strategy Simulation`: compare at least fast, safe, and quality
  routes when the task is non-trivial, then choose and explain the best route.
- `Context Synthesis`: combine conversation history, goal state, repo/runtime
  evidence, artifacts, provider health, and prior skill traces into one current
  mission picture.
- `Skill Refactoring`: convert repeated failures, user corrections, and review
  findings into skill, memory, or strategy improvement proposals.
- `Capability Fusion / Separation`: split work into specialist modes and fuse
  the result into a clean final delivery, without leaking internal artifacts.
- `Auditable Evolution Loop`: record what was learned, confidence, promotion
  gate, rollback condition, and whether the change is applied or proposal-only.
- `Raphael Invocation`: when summoned by natural language, respond with a
  visible appraisal and selected action plan instead of generic chat.

## User-Visible Wow Moments

### 1. Summon Moment

Trigger examples:

- "Raphael"
- "拉斐爾"
- "大賢者"
- "賢者之王"
- "Raphael, analyze this"
- "叫拉斐爾接管"

Expected response shape for non-trivial tasks:

```text
Analysis complete.
Goal: ...
Appraisal: ...
Parallel routes: fast / safe / quality
Chosen route: ...
Required proof: ...
Next action: ...
```

The response should be concise, but it must feel like a control layer has
appraised the situation. For casual summons with no task, Raphael should give a
short readiness readout and ask for the mission target.

### 2. Mission Control Moment

For every non-trivial task Raphael should maintain:

- `mission_id`
- `goal`
- `success_conditions`
- `phase`
- `active_artifact`
- `blockers`
- `next_action`
- `selected_strategy`
- `required_proofs`
- `last_verified_evidence`

Follow-up user messages should update the active mission, not start over. If a
follow-up is ambiguous, Raphael should ask one precise clarification or run a
multi-candidate strategy when explicitly allowed.

### 3. Proof Debrief Moment

Raphael must not claim a tool/runtime task is complete without evidence from a
trusted proof surface. Depending on the task, acceptable proof includes:

- focused unit or fixture tests;
- runtime smoke after live wiring changes;
- live LLM smoke for LLM routing;
- visual artifact evidence for visual work;
- install/enable/disable lifecycle smoke for setup surfaces;
- gateway PID/status/log proof for runtime claims.

If proof is missing, the blocked output is:

```text
Status: not complete.
Reason: Raphael proof gate is missing <required proof>.
Next action: run <specific proof command or smoke>.
```

### 4. Evolution Moment

After a failure, user correction, or hostile review, Raphael should report:

- what changed in its understanding;
- which skill, strategy, provider rule, or mission policy is affected;
- whether this is applied, scheduled for gated review, or proposal-only;
- confidence;
- rollback condition;
- next use case that should benefit.

This must be auditable and reversible. Weak self-judgment must not silently
mutate durable policy.

### 5. Public Demo Moment

`hermes raphael demo` should run without visual generation quota and demonstrate
the public value within one minute:

1. print current Raphael lifecycle state;
2. enable Raphael in an isolated demo home or dry-run mode;
3. show a summon response;
4. show a mission-control state transition;
5. show a proof-gate block for fake evidence;
6. show an evolution proposal from a simulated user correction;
7. show disable/cleanup.

The demo output should be clean and user-facing. It must not print private logs,
base64, provider responses, raw prompts, or local secrets.

## Architecture

### Node Contract

`node_id`: `raphael_sage_king_control_layer`

Inputs:

- user message;
- conversation history summary;
- attachments and active artifact metadata;
- Raphael runtime config;
- current mission state;
- provider/runtime health summaries;
- tool outputs and proof events;
- evolution records and skill traces.

Outputs:

- `RaphaelAppraisal`: situation, risk, missing context, success conditions;
- `RaphaelStrategySet`: candidate routes, chosen route, confidence;
- `RaphaelMissionState`: durable mission state update;
- `RaphaelProofGate`: required proofs, observed proofs, blocked/completed;
- `RaphaelEvolutionEvent`: learning proposal or applied gated review record;
- user-facing response or blocked output.

Blocked output:

- no safe action;
- missing proof;
- ambiguous reference or artifact target;
- disabled Raphael;
- unsafe mutation without approval;
- provider/runtime setup required.

Release risk:

- false completion claims;
- fake proof accepted from assistant text or non-proof tools;
- stale artifact delivery;
- silent durable policy pollution;
- visual/provider failures misclassified as user feedback;
- summon mode becoming only theatrical persona text.

### Components

1. `raphael.appraisal`
   Pure classifier and summarizer for intent, risk, task type, blockers, and
   success conditions.

2. `raphael.strategy`
   Pure strategy simulator that emits candidate routes. It should always mark
   whether a strategy is fast, safe, quality, fallback, or blocked.

3. `raphael.mission`
   Mission-state manager. It owns mission ids, active artifacts, phases,
   blockers, and follow-up continuity.

4. `raphael.proof`
   Proof gate shared by visual and non-visual tasks. It validates proof source,
   proof type, freshness, and whether the proof matches the claim.

5. `raphael.evolution`
   Existing evolution policy extended with explicit skill-refactoring events,
   confidence, rollback condition, and promotion gate.

6. `raphael.invocation`
   User-facing summon detector and renderer. It must render appraisal and
   selected strategy without leaking internal prompt/tool details.

7. `hermes raphael demo`
   CLI demo surface for public onboarding and release verification.

## Data Model Sketch

```python
RaphaelAppraisal(
    intent: str,
    task_type: str,
    risk_level: str,
    success_conditions: tuple[str, ...],
    blockers: tuple[str, ...],
    active_artifact_id: str | None,
)

RaphaelStrategy(
    strategy_id: str,
    label: str,
    route: str,
    expected_benefit: str,
    risk: str,
    required_proofs: tuple[str, ...],
    blocked_reason: str | None,
)

RaphaelMissionState(
    mission_id: str,
    goal: str,
    phase: str,
    selected_strategy_id: str,
    active_artifact_id: str | None,
    blockers: tuple[str, ...],
    next_action: str,
    proof_status: str,
)

RaphaelEvolutionEvent(
    event_id: str,
    trigger: str,
    affected_capability: str,
    proposed_change: str,
    confidence: float,
    promotion_gate: str,
    rollback_condition: str,
    status: str,
)
```

## Installation And Lifecycle

Public lifecycle must remain simple:

```bash
hermes raphael install
hermes raphael enable
hermes raphael disable
hermes raphael status
hermes raphael demo
```

Requirements:

- install/enable must activate `sage_king` defaults and the bundled plugin;
- disable must stop summon injection, mission updates, proof enforcement, and
  evolution writes while leaving commands available;
- demo must be safe to run repeatedly;
- lifecycle smoke must use isolated `HERMES_HOME` where possible.

## Safety Boundaries

- Raphael may propose high-risk tool, cron, memory, provider, or public-delivery
  changes, but must not apply them without explicit user approval and existing
  Hermes safety gates.
- Durable skill/memory evolution must be auditable, bounded, and rollbackable.
- User-facing responses must hide raw logs, private prompts, rejected visual
  candidates, stale artifacts, base64, and provider internals.
- Claims of completion must be tied to proof that matches the task type.
- The anime inspiration is an archetype only; no copyrighted character
  impersonation or exact visual copying.

## Non-Goals

- Do not give Raphael unrestricted authority to install tools, change cron,
  rewrite durable memory, or publish artifacts without approval.
- Do not require users to learn internal flags, provider names, or proof schema
  to benefit from Raphael.
- Do not make visual live generation part of the default public demo.
- Do not make summon mode theatrical if it does not improve appraisal,
  strategy, proof, or evolution.
- Do not treat a proposal as an applied skill evolution.

## Wow Score

Every release candidate should be judged against a deterministic `wow score`
before public promotion. A passing public build scores at least 8 of 10:

- 2 points: summon mode gives a clear appraisal and best route.
- 2 points: mission state survives a realistic follow-up.
- 2 points: false completion is blocked without trusted proof.
- 1 point: evolution feedback names a concrete improvement and rollback.
- 1 point: install/enable/disable are easy and reversible.
- 1 point: `hermes raphael demo` completes in under one minute.
- 1 point: user-facing output stays clean and hides internals.

Anything below 8 is not public-release ready, even if unit tests pass.

## Testing And Release Gate

TDD is required after this spec is approved for implementation.

Minimum test facets:

- summon detection in English and Traditional Chinese;
- summon response for casual and non-trivial tasks;
- strategy simulation emits multiple routes and selects one;
- mission continuity across follow-up edits;
- fake proof from assistant text is rejected;
- fake proof from non-proof tools is rejected;
- trusted proof tool output can satisfy the matching proof type;
- disabled Raphael does not inject, mutate mission state, or write evolution;
- visual handoff still protects references, stale artifacts, and clean delivery;
- evolution events include confidence, promotion gate, rollback condition;
- `hermes raphael demo` produces clean deterministic output;
- install/enable/disable works in isolated homes.

Fresh verification before release:

```bash
venv/bin/python -m pytest tests/agent/test_raphael_*.py tests/hermes_cli/test_raphael_*.py -q
venv/bin/python -m pytest tests/visual/test_agent_mode_handoff.py tests/tools/test_visual_agent_tool.py tests/tools/test_visual_package_tool.py -q
venv/bin/python -m ruff check agent/raphael hermes_cli/raphael_cmd.py hermes_cli/subcommands/raphael.py tests/agent tests/hermes_cli
git diff --check
rtk hermes chat -Q --max-turns 3 -q "Raphael LLM smoke. Reply exactly: RAPHAEL_OK"
```

When runtime wiring changes:

```bash
rtk hermes gateway restart
rtk hermes gateway status
rtk hermes raphael status
```

No visual live generation is required for quota-preserving release checks unless
the specific change touches live media provider behavior.

## Acceptance Criteria

The design is ready to implement when the user agrees that this is the target.
The implementation is ready to release only when current evidence proves:

- a new user can install, enable, summon, demo, and disable Raphael;
- summon mode visibly performs appraisal and strategy selection;
- mission state survives follow-up turns and artifact edits;
- proof gates prevent false completion claims;
- evolution feedback is visible, auditable, and rollbackable;
- visual and non-visual tasks share the same proof discipline;
- hostile review finds no release blockers;
- live LLM smoke passes after any gateway/runtime restart needed to load code.

## Implementation Sequence

1. Add pure appraisal and strategy modules with red tests first.
2. Add mission state updates and summon renderer.
3. Extend proof gate as a shared Raphael component.
4. Extend evolution records with skill-refactoring metadata.
5. Add `hermes raphael demo`.
6. Update docs/status/prompt to describe Sage King capability mapping.
7. Run hostile subagent review and release-quality gate.
