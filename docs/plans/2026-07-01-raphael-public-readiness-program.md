# Raphael Public Readiness Program

> Tracking issue: https://github.com/EndeavorYen/hermes-agent/issues/4

## Goal

Ship Hermes Raphael mode to a public release standard where users can enable it,
summon it, and experience a real control-layer evolution: goal awareness,
mode routing, evidence-gated execution, self-correction, auditable learning,
clean media delivery, and simple install/enable/disable/uninstall flows.

This program is not a persona or prompt refresh. Raphael is the high-level
Sage King control layer for Hermes. It coordinates existing specialist modes
and providers, proves claims before reporting success, and keeps durable
learning behind audit and rollback gates.

## Non-Negotiable Workflow

Every development segment must follow this sequence:

1. Open a remote issue in `EndeavorYen/hermes-agent`.
2. Create one branch from `origin/upgrade/hermes-v2026.6.19-local` or the
   current merged program base.
3. Define acceptance criteria before implementation.
4. Use TDD for behavior changes, or an explicit docs/config verification path
   when TDD is not applicable.
5. Keep the change scoped to the issue.
6. Commit and push that segment.
7. Open a PR against the origin branch, never upstream.
8. Include self-review, verification evidence, and current progress percent.
9. Review before merge.
10. Merge before starting the next dependent segment.

Rules:

- Do not open issues, PRs, or branches against `NousResearch/hermes-agent`
  unless the user explicitly requests an upstream workflow.
- Do not land one large Raphael bundle.
- Do not treat existing local WIP as automatically accepted.
- Do not claim Grok, video, visual, Slack, runtime, or release readiness from
  docs alone.
- Do not publicly claim untested capabilities. For media, claim only the slice
  backed by current evidence.
- If implementation starts drifting from the approved design, stop and update
  the issue or plan before writing more code.

## Approved Source Baseline

The program must preserve these approved requirements:

- Raphael mode is a control layer, not a persona.
- It must maintain goal state: current goal, active artifact, success
  conditions, phase, blockers, next action, and proof state.
- It must route natural language across general chat, tool tasks, visual
  generation, visual edits, follow-ups, prompt disclosure, and clarification.
- It must coordinate visual providers without exposing internal provider
  complexity to users.
- It must separate provider health, moderation, handoff failure, browser
  automation failure, artifact quality failure, and delivery failure.
- It must verify with a proof ladder instead of trusting tool success.
- It must learn from failures and feedback through auditable, reversible
  proposals.
- It must deliver only current selected artifacts and keep private logs,
  raw prompts, base64, rejected candidates, and stale media out of user-facing
  delivery.
- It must be easy to install, enable, disable, and uninstall.

Draft design and plan artifacts discovered in the current local WIP should be
ported only through scoped PRs:

- `docs/superpowers/specs/2026-06-30-raphael-wow-mode-design.md`
- `docs/superpowers/plans/2026-06-30-raphael-wow-mode-implementation.md`
- `docs/superpowers/plans/2026-06-30-raphael-sage-king-mode.md`
- `docs/raphael-mode.md`
- `docs/raphael-llm-public-slice.md`
- `docs/raphael-release-slice-audit.md`

Those files are useful source material, but they are not a license to merge the
whole current WIP. Each future PR must name which parts it ports or replaces.

## Progress Rubric

Progress is counted against the final public Raphael release goal, not against
the easiest passing subset.

| Percent | Phase | Exit Evidence |
| --- | --- | --- |
| 0-5 | Program reset | Root tracking issue, source index, phase backlog, progress rubric, and PR discipline merged. |
| 5-15 | Install lifecycle | Install, enable, disable, status, and uninstall are simple, reversible, package-tested, and documented. |
| 15-30 | Goal-state manager | Mission state tracks goal, artifact, success conditions, phase, blockers, next action, and follow-up continuity. |
| 30-45 | Mode router and handoff | Natural language routes correctly across chat, tools, visual generation/editing, prompt disclosure, and clarification. |
| 45-60 | Evidence gate and self-review | Claims require matching proof; missing proof produces actionable blocked output; self-review changes next action. |
| 60-72 | Active evolution | Failure and feedback create auditable improvement proposals with confidence, promotion gate, and rollback condition. |
| 72-82 | Public LLM slice | Live LLM-only smoke, summon UX, hostile review, and non-visual regression prove the public text/control-layer slice. |
| 82-92 | Media and visual slice | OpenAI image slice first, then Grok Web Imagine and video only after live evidence; stale or wrong media is rejected. |
| 92-100 | Release candidate | Full install smoke, release gate, docs, public claims, PR review, and merge evidence prove release readiness. |

Round-end reporting must include:

- Current percentage and why it changed.
- Issue, branch, PR, and merge state.
- Files changed in the segment.
- Verification commands and results.
- Direction self-review: still aligned or drifting.
- Remaining risks.
- Next issue.

## Phase Backlog

### Phase 0: Program Reset

Tracking issue: `#4`.

Scope:

- Land this program document.
- Freeze workflow rules for future Raphael work.
- Define the phase percentages and reporting format.
- State how to salvage or discard current WIP.

Proof:

- Docs-only diff.
- `git diff --check`.
- Branch status proves no runtime files changed.
- PR body contains direction self-review.

Exit percent: 5%.

### Phase 1: Install, Enable, Disable, Uninstall

Create issue title:

`Raphael lifecycle install enable disable uninstall public smoke`

Acceptance:

- `hermes raphael install` is idempotent.
- `hermes raphael enable` and `disable` are reversible.
- `hermes raphael status` explains active state without leaking internals.
- Uninstall or cleanup removes only Raphael-owned state.
- Package install smoke proves the installed entrypoint, not only source tree
  behavior.

Proof:

- Focused CLI tests.
- Package install smoke report.
- Docs update.
- PR self-review against the simple-promotion requirement.

Progress target when merged: 15%.

### Phase 2: Goal-State Manager

Create issue title:

`Raphael mission state tracks active goal artifact proof and followups`

Acceptance:

- Raphael records mission id, goal, active artifact, success conditions, phase,
  blockers, next action, selected strategy, required proofs, and last evidence.
- Follow-up user requests update the current mission instead of starting over.
- Ambiguous artifact references ask one precise clarification or produce a
  bounded multi-candidate plan when allowed.

Proof:

- TDD unit tests for mission creation and follow-up updates.
- CLI/status smoke showing mission state.
- Regression tests that stale artifacts are not selected.

Progress target when merged: 30%.

### Phase 3: Mode Router And Handoff

Create issue title:

`Raphael routes chat tools visual edits disclosure and clarification`

Acceptance:

- Natural language routes across general chat, tool task, image generation,
  video generation, visual edit, prompt disclosure, and clarification.
- Visual mode handoff preserves provider boundaries.
- OpenAI GPT can cover LLM-only tests; xAI/Grok and video claims remain
  guarded until live evidence exists.

Proof:

- Router fixture matrix.
- Prompt disclosure regression.
- Visual handoff unit tests without live generation quota.

Progress target when merged: 45%.

### Phase 4: Evidence Gate And Self-Review

Create issue title:

`Raphael proof gate blocks unsupported success claims`

Acceptance:

- Tool success alone cannot mark a task complete.
- Missing proof produces user-facing blocked output with the next concrete
  proof command.
- Runtime, LLM, install, media, and artifact claims map to different proof
  requirements.

Proof:

- Proof gate unit tests.
- Turn finalizer tests.
- Non-visual regression.

Progress target when merged: 60%.

### Phase 5: Active Evolution

Create issue title:

`Raphael creates auditable evolution proposals from feedback and failures`

Acceptance:

- User corrections, hostile review, repeated failures, and provider outcomes
  create improvement proposals.
- Proposals include affected skill or strategy, confidence, promotion gate, and
  rollback condition.
- Approval records a decision and surfaces manual rollout steps.
- Approval does not silently mutate durable policy.

Proof:

- Evolution policy tests.
- Status and CLI proposal lifecycle tests.
- Package install smoke includes proposal lifecycle evidence.

Progress target when merged: 72%.

### Phase 6: Public LLM Slice

Create issue title:

`Raphael public LLM slice summon UX live smoke and hostile review`

Acceptance:

- A real LLM-only smoke covers summon, mission follow-up, proof block, and
  evolution proposal behavior.
- Hostile review verifies public wording does not overclaim Sage King,
  "wow", media, video, or Grok readiness.
- The release gate records the slice as LLM-ready only.

Proof:

- LLM smoke transcript.
- Hostile review report.
- Non-visual regression.
- Release gate output.

Progress target when merged: 82%.

### Phase 7: Media And Visual Slice

Create issue title:

`Raphael media readiness proves OpenAI image slice before Grok and video claims`

Acceptance:

- OpenAI image slice is tested first if visual quota is available.
- Grok Web Imagine and video remain not-ready until their own live evidence
  exists.
- Stale, duplicated, rejected, or wrong artifacts are not delivered.
- Geometry and selected artifact evidence are used for packaging decisions.

Proof:

- OpenAI visual live E2E when explicitly allowed.
- Independent visual quality review.
- Provider failure classification tests.
- Release gate keeps full media release blocked until all required live
  evidence exists.

Progress target when merged: 92%.

### Phase 8: Release Candidate

Create issue title:

`Raphael release candidate gate docs claims and merge readiness`

Acceptance:

- All previous phase issues are merged.
- Install lifecycle, LLM slice, media slice, release docs, and public claims
  are verified from current origin state.
- Release notes state tested and untested capabilities exactly.

Proof:

- Full release gate.
- Package install smoke.
- Non-visual regression.
- Required live smoke reports.
- Review and merge evidence.

Progress target when merged: 100%.

## Handling Existing WIP

The current primary checkout contains a large Raphael WIP. It must be treated
as raw material, not as release-ready work.

Before reusing any WIP change:

1. Match it to exactly one phase issue.
2. Confirm it still follows the approved design.
3. Re-run or recreate the TDD red/green evidence for that behavior.
4. Cherry-pick only the minimal scoped files, or reimplement in the clean
   phase branch when that is safer.
5. Re-run the phase verification from the clean branch.
6. Mention the WIP source and the acceptance criterion in the PR body.

If a WIP change cannot be mapped to a phase issue, leave it out.

## Direction Self-Review

Current direction is correct at the product level: Raphael should become a
goal/evidence/routing/evolution control layer that makes Hermes feel upgraded.

Current execution needed correction: the prior approach accumulated too much
unmerged WIP, mixed planning with implementation, and made progress hard to
audit. This program reset fixes the process first, then resumes feature work
through small PRs.

Distance from final target after this document merges: 5%. The goal is still
far from complete because install lifecycle, mission state, routing,
proof-gating, evolution, LLM smoke, media evidence, and release gate work all
remain separate proof-bearing phases.

## PR Body Checklist

Every future Raphael PR must include:

```markdown
Part of: #<issue>

Progress:
- Previous: <percent>
- This PR target: <percent>
- Final target remaining: <percent>

Scope:
- <files or behavior changed>

Acceptance:
- [ ] <issue criterion>

Verification:
- <command> -> <result>

Direction self-review:
- Alignment with approved Raphael control-layer design:
- Drift risk:
- Remaining gap:

Public claim boundary:
- What this PR proves:
- What this PR does not prove:
```
