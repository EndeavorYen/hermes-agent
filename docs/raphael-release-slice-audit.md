# Raphael Release Slice Audit

> **TL;DR** — Raphael mode is moving in the right architectural direction, and
> the scoped LLM-only slice can pass the release gate. That is not a full
> Raphael launch: public wow/Sage King/big-evolution claims remain denied, and
> the archived media evidence was limited to OpenAI image-only proof while full
> Grok/video media readiness remains blocked.

## Archived Verdict Snapshot

| Scope | Status | Evidence | Release decision |
| --- | --- | --- | --- |
| LLM-only Raphael | Historical scoped result | Archived gate output reported `ready_for_llm_only_release` and `Release scope: llm_only`; rerun the gate for a current verdict | Can release only from fresh evidence and only as LLM control layer |
| OpenAI visual Raphael | Historical limited result | Archived gate output reported `ready_for_limited_media_public_release`, scope `media_openai_image_only`, with `openai_image_generation`; rerun the gate for a current verdict | Can publish only from fresh evidence with explicit Grok/video gaps |
| Full media Raphael | Blocked | Media readiness still reports remaining gaps for `xai_grok_generation` and `video_generation` | Do not release as full media |
| Install/enable/disable | Historical pass | Archived package smoke `package-install-20260701-fresh-home-fail-closed-v1` verified wheel install, lifecycle, audit-only default, fail-closed readiness, and proposal lifecycle commands | Rerun before release |
| Evolution writes | Managed local override | Local status labels durable writes as a local override; fresh install smoke shows `audit-only` | Public default remains audit-only unless `--evolve` is explicit |
| Worktree hygiene | Canonical fail-closed boundary | The packaged boundary policy is the source of truth; unrelated CI, old plans, generic release automation, and generic tests/utilities remain unclassified | Classify or remove unknown paths before review |
| Release slice manifest | Reviewable scoped split | `scripts/raphael_release_slice_manifest.py --from-git-status` emits `review_strategy: split_required`, separates `llm_scoped_release` from `deferred_media`, and keeps full-Sage blockers under completion evidence | Use the manifest as reviewer handoff for the scoped LLM slice |
| Ultimate completion | Historical partial result | The archived completion audit reported `Raphael completion audit: partial` and `Ultimate Sage King ready: no` | Treat full Sage King as incomplete until a fresh gate clears every blocker |

## Release Slices

| Slice | Candidate files | Why it matters | Gate |
| --- | --- | --- | --- |
| Core control layer | `agent/raphael/appraisal.py`, `control.py`, `mission.py`, `proof.py`, `strategy.py`, `state.py` | Keeps goals, routing, blockers, evidence, and follow-up continuity out of persona prompts | Focused `tests/agent/test_raphael_*.py` |
| LLM summon UX | `agent/raphael/observer.py`, `prompt.py`, `governor.py`, `wow_score.py`, `plugins/raphael/__init__.py` | Makes `拉斐爾？` feel like a controlled Sage King summon through the plugin context hook | LLM live smoke plus wow-score checks |
| Lifecycle and readiness CLI | `hermes_cli/raphael_cmd.py`, `hermes_cli/raphael_lifecycle.py`, `hermes_cli/subcommands/raphael.py`, `plugins/raphael/*` | Gives users install, enable, disable, uninstall, doctor, and release-gate surfaces | `tests/hermes_cli/test_raphael_cmd.py` and package install smoke |
| Evolution audit | `agent/raphael/evolution.py`, `skill_trace.py`, `status.py`, `agent/background_review.py` | Converts corrections and failed proof gates into auditable improvement proposals, prioritizes repeated patterns in Active Self-Correction, and creates approval-gated skill-patch proposals with rollout plans | Audit-only default, rollout-plan enforcement, rollback metadata, hostile review |
| Completion audit | `scripts/raphael_completion_audit.py`, `tests/scripts/test_raphael_completion_audit.py` | Prevents scoped LLM/OpenAI-image readiness from being reported as ultimate Sage King completion | `scripts/raphael_completion_audit.py` exits non-zero while ultimate blockers remain |
| Release slice manifest | `scripts/raphael_release_slice_manifest.py`, `tests/scripts/test_raphael_release_slice_manifest.py` | Turns the large worktree into a machine-readable reviewer handoff with LLM paths, deferred media paths, allowed claims, blocked claims, and required evidence commands | `scripts/raphael_release_slice_manifest.py --from-git-status` |
| Visual routing | `agent/visual/agent_mode/*`, `tools/visual_agent_tool.py`, `agent/visual/session_references.py` | Routes image/video tasks to the visual-agent path and preserves reference semantics; this does not prove Grok generation readiness | Quota-free visual handoff tests |
| Media provider evidence | `plugins/image_gen/grok_web_imagine/*`, `scripts/grok_web_imagine_live_e2e.py`, `scripts/openai_visual_live_e2e.py` | The archived public media evidence was OpenAI image-only; Grok preflight/live E2E, stale-artifact rejection, and video proof were pending | Require fresh provider evidence for any publication |
| Delivery privacy | `tools/visual_package_tool.py`, `gateway/platforms/base.py`, `gateway/run.py` | Prevents rejected, stale, duplicate, or diagnostic media from being delivered | Gateway and visual package regression |

## Alignment Check

Aligned:

- Raphael is implemented as a control layer with goal, route, evidence, mission, proof, and evolution surfaces.
- Archived release-gate evidence supported the LLM-only control mechanics at
  its recorded time; it is not a current release verdict.
- The LLM boundary now detects both path drift and `agent/raphael/*` imports of deferred media modules.
- Raphael summon detection no longer treats file paths or broad topic mentions like `docs/raphael-mode.md` as explicit summons.
- Negated media language such as `不要產圖` in an LLM-only summon smoke now stays on the text-only route instead of being misclassified as visual generation.
- Historical LLM live smoke `20260701_131600_93f518` recorded same-session
  summon continuity with the then-current `gpt-5.5`, zero tool calls, and
  text-only output. The current gate accepts the effective supported OpenAI
  GPT-5-family model only when log and transcript identities agree.
- Archived hostile-shaped smoke `20260701_130957_137750` recorded that public Raphael wording with negated media language stayed text-only.
- The LLM readiness implementation uses quota-free `production_replay` through the
  canonical kernel and shared finalizer; detached deterministic-router evidence
  is rejected. The separate six-case user matrix still requires `user_prompt`,
  `expected_visible_behavior`, `critical_assertions`, `next_action`,
  `proof_layer`, and `visual_quota_used=false` fields.
- Archived non-visual regression report `non-visual-regression-20260701-openai-quality-attachment-gate` recorded `1529` passing tests, zero failures, zero visual quota, and broad Raphael/media regression coverage.
- Archived package install smoke `package-install-20260701-fresh-home-fail-closed-v1` verified wheel install, lifecycle, audit-only default, fail-closed readiness, and approval-gated proposal commands.
- Hostile review `hostile-review-20260701-fresh-home-fail-closed-v1` allows only the scoped LLM-only and OpenAI image-only media releases while explicitly denying Sage King, wow, big-evolution, Grok, video, full-media, and full-Sage-King claims.
- The archived Raphael completion audit reported `Raphael completion audit:
  partial`, `Scoped release ready: yes`, and `Ultimate Sage King ready: no`.
- Raphael release slice manifest records `review_strategy: split_required`, keeps `allowed_public_claims` to `llm_only`, and separates `llm_scoped_release` paths from `deferred_media` paths for reviewer handoff.
- Active Self-Correction now prioritizes repeated evolution patterns, so two proof-gate failures outrank one later unrelated lesson as the next skill focus.
- Repeated active evolution patterns now create one deduplicated pending `skill_patch` action proposal with `R2` approval required, evidence refs, pending-approval status, verification commands, promotion gate, and rollback condition. Release readiness rejects legacy evolution evidence that proves only "a proposal exists" without proving the rollout plan.
- `/raphael-status` now renders pending skill-patch rollout plans as pending approval with Verify/Promote/Rollback steps, refuses stale `applied` rollout status on pending proposals, and redacts secrets and private paths from rollout metadata.
- The archived media gate allowed only the OpenAI image-only slice; a fresh
  gate must still refuse full media until Grok and video evidence pass.
- Repair plans and proof requirements now expose the next machine-readable live proof steps.

Archived media-profile evidence:

- Historical media-profile LLM smoke `20260701_163247_d9b87d` recorded
  `gpt-5.5`, zero tool calls, summon sections, same-mission continuity, and no
  visual failure trace. It is not a version pin for current readiness.
- Archived media-profile non-visual regression report `non-visual-regression-20260701-wow-user-simulation-proof-v1` recorded `1541` passing tests, zero failures, zero visual quota, no OpenAI live generation, and no xAI/Grok live generation.
- OpenAI image-only visual report `openai-visual-live-20260701-openai-gpt-strict-review.reviewed.json` proves only `openai_image_generation`; it explicitly does not prove Grok, xAI, video, or full media readiness.

Weak or incomplete:

- The archived hostile UX review denied public wow/Sage King/big-evolution claims; rerun it before publication.
- Completion audit hard-blocks ultimate readiness on denied Sage King/wow/big-evolution claims plus missing xAI/Grok and video evidence.
- Evolution is gated, auditable, can prioritize repeated self-correction patterns, and can create approval-gated skill-patch proposals with rollout-plan enforcement; it is still not full autonomous skill publication like the final Sage King target.
- Full media release lacks Grok live generation and image-first video proof.
- The deterministic demo score is now displayed as `Offline demo shape`; it remains useful shape evidence, not human delight evidence.
- Some mixed core surfaces remain in the broader worktree; the LLM boundary and release slice manifest pass, but final publication still needs slice review discipline.
- The worktree is too large for review as a single public release, though changed paths, Raphael core imports, and reviewer handoff slices are now machine-classified.

## Next Gate

1. Keep publication scoped to the explicit boundaries returned by a fresh gate.
2. Regenerate no-visual hostile review evidence before publishing either slice.
3. Split or document the LLM-only slice first: core control, lifecycle CLI, summon UX, evolution audit, release gate.
4. Defer full media release until Grok and image-first video live evidence are available.
5. Run `scripts/raphael_completion_audit.py` before any full Sage King or wow launch wording.
6. Attach `scripts/raphael_release_slice_manifest.py --from-git-status` output to reviewer handoff for the scoped LLM slice.

## Gate State Summary

LLM-only public slice: `ready_for_llm_only_release`.

OpenAI image-only media slice: `ready_for_limited_media_public_release` with scope `media_openai_image_only`.

Full media Raphael was not ready in the archived snapshot; recorded gaps were `xai_grok_generation` and `video_generation`.

Public wording must stay limited to the fresh gate state, scope, and explicit exclusions; do not use percentage estimates or this Markdown as release evidence.
