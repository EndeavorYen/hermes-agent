# Raphael Release Slice Audit

> **TL;DR** — Raphael mode is moving in the right architectural direction, and
> the scoped LLM-only slice can pass the release gate. That is not a full
> Raphael launch: public wow/Sage King/big-evolution claims remain denied, and
> media readiness is currently limited to OpenAI image-only evidence while full
> Grok/video media readiness remains blocked.

## Current Verdict

| Scope | Status | Evidence | Release decision |
| --- | --- | --- | --- |
| LLM-only Raphael | Scoped public slice ready | Fresh `hermes raphael readiness --readiness-profile llm --check` passes as `ready_for_llm_only_release` and prints `Release scope: llm_only` | Can release only as LLM-only control layer; not as full wow/Sage King |
| OpenAI visual Raphael | Limited public media slice ready | Current `hermes raphael readiness --readiness-profile media --check` passes as `ready_for_limited_media_public_release`, scope `media_openai_image_only`, with verified `openai_image_generation` | Can publish only with OpenAI image-only wording and explicit remaining Grok/video gaps |
| Full media Raphael | Blocked | Media readiness still reports remaining gaps for `xai_grok_generation` and `video_generation` | Do not release as full media |
| Install/enable/disable | Healthy | Fresh package smoke `package-install-20260701-fresh-home-fail-closed-v1` verifies wheel install, install/disable/enable/uninstall, audit-only default, installed media and LLM readiness fail-closed behavior in a fresh home, and approval-gated proposal lifecycle commands | Keep in LLM slice |
| Evolution writes | Managed local override | Local status labels durable writes as a local override; fresh install smoke shows `audit-only` | Public default remains audit-only unless `--evolve` is explicit |
| Worktree hygiene | Controlled boundary, unsplit worktree | Current local boundary command `scripts/raphael_release_slice_boundary.py --from-git-status` classifies changed paths into LLM slice vs deferred media with `0` unclassified paths and `0` Raphael core deferred-media import violations; this is local boundary evidence, not a readiness JSON field | Still not reviewable as one release; use the boundary command to split review |
| Release slice manifest | Reviewable scoped split | `scripts/raphael_release_slice_manifest.py --from-git-status` emits `review_strategy: split_required`, separates `llm_scoped_release` from `deferred_media`, and keeps full-Sage blockers under completion evidence | Use the manifest as reviewer handoff for the scoped LLM slice |
| Ultimate completion | Partial | `scripts/raphael_completion_audit.py` currently prints `Raphael completion audit: partial` and `Ultimate Sage King ready: no` | Treat full Sage King as incomplete until the listed blockers clear |

## Release Slices

| Slice | Candidate files | Why it matters | Gate |
| --- | --- | --- | --- |
| Core control layer | `agent/raphael/appraisal.py`, `control.py`, `mission.py`, `proof.py`, `strategy.py`, `state.py` | Keeps goals, routing, blockers, evidence, and follow-up continuity out of persona prompts | Focused `tests/agent/test_raphael_*.py` |
| LLM summon UX | `agent/raphael/observer.py`, `prompt.py`, `governor.py`, `wow_score.py`, `agent/prompt_builder.py`, `agent/conversation_loop.py` | Makes `拉斐爾？` feel like a controlled Sage King summon, not a one-off answer | LLM live smoke plus wow-score checks |
| Lifecycle and readiness CLI | `hermes_cli/raphael_cmd.py`, `hermes_cli/subcommands/raphael.py`, `plugins/raphael/*`, `docs/raphael-mode.md` | Gives users install, enable, disable, uninstall, doctor, and release-gate surfaces | `tests/hermes_cli/test_raphael_cmd.py` and package install smoke |
| Evolution audit | `agent/raphael/evolution.py`, `skill_trace.py`, `status.py`, `agent/background_review.py` | Converts corrections and failed proof gates into auditable improvement proposals, prioritizes repeated patterns in Active Self-Correction, and creates approval-gated skill-patch proposals with rollout plans | Audit-only default, rollout-plan enforcement, rollback metadata, hostile review |
| Completion audit | `scripts/raphael_completion_audit.py`, `tests/scripts/test_raphael_completion_audit.py` | Prevents scoped LLM/OpenAI-image readiness from being reported as ultimate Sage King completion | `scripts/raphael_completion_audit.py` exits non-zero while ultimate blockers remain |
| Release slice manifest | `scripts/raphael_release_slice_manifest.py`, `tests/scripts/test_raphael_release_slice_manifest.py` | Turns the large worktree into a machine-readable reviewer handoff with LLM paths, deferred media paths, allowed claims, blocked claims, and required evidence commands | `scripts/raphael_release_slice_manifest.py --from-git-status` |
| Visual routing | `agent/visual/agent_mode/*`, `tools/visual_agent_tool.py`, `agent/visual/session_references.py` | Routes image/video tasks to the visual-agent path and preserves reference semantics; this does not prove Grok generation readiness | Quota-free visual handoff tests |
| Media provider evidence | `plugins/image_gen/grok_web_imagine/*`, `scripts/grok_web_imagine_live_e2e.py`, `scripts/openai_visual_live_e2e.py` | Current public media evidence is OpenAI image-only; Grok preflight/live E2E, stale-artifact rejection, and video proof remain pending | OpenAI image-only report now; Grok/video live E2E only when quota is approved |
| Delivery privacy | `tools/visual_package_tool.py`, `gateway/platforms/base.py`, `gateway/run.py` | Prevents rejected, stale, duplicate, or diagnostic media from being delivered | Gateway and visual package regression |

## Alignment Check

Aligned:

- Raphael is implemented as a control layer with goal, route, evidence, mission, proof, and evolution surfaces.
- LLM-only control mechanics are currently supported by release-gate evidence and scoped public readiness.
- The LLM boundary now detects both path drift and `agent/raphael/*` imports of deferred media modules.
- Raphael summon detection no longer treats file paths or broad topic mentions like `docs/raphael-mode.md` as explicit summons.
- Negated media language such as `不要產圖` in an LLM-only summon smoke now stays on the text-only route instead of being misclassified as visual generation.
- Fresh LLM live smoke `20260701_131600_93f518` proves same-session summon continuity with `gpt-5.5`, zero tool calls, and text-only output.
- Fresh hostile-shaped smoke `20260701_130957_137750` proves public Raphael wording with negated media language stays text-only.
- Fresh LLM readiness evidence now records the quota-free six-case user simulation matrix with required `user_prompt`, `expected_visible_behavior`, `critical_assertions`, `next_action`, `proof_layer`, and `visual_quota_used=false` fields. Stale wow evidence without those fields is rejected as `wow_experience_score_unverified`.
- Fresh non-visual regression report `non-visual-regression-20260701-openai-quality-attachment-gate` records `1529` passing tests, zero failures, zero visual quota, and broad Raphael/media regression coverage.
- Fresh package install smoke `package-install-20260701-fresh-home-fail-closed-v1` verifies wheel install, install/disable/enable/uninstall, audit-only default, installed media and LLM readiness fail closed without release evidence in a fresh home, and approval-gated proposal approve/reject lifecycle commands.
- Hostile review `hostile-review-20260701-fresh-home-fail-closed-v1` allows only the scoped LLM-only and OpenAI image-only media releases while explicitly denying Sage King, wow, big-evolution, Grok, video, full-media, and full-Sage-King claims.
- Raphael completion audit currently reports `Raphael completion audit: partial`, `Scoped release ready: yes`, and `Ultimate Sage King ready: no`.
- Raphael release slice manifest records `review_strategy: split_required`, keeps `allowed_public_claims` to `llm_only`, and separates `llm_scoped_release` paths from `deferred_media` paths for reviewer handoff.
- Active Self-Correction now prioritizes repeated evolution patterns, so two proof-gate failures outrank one later unrelated lesson as the next skill focus.
- Repeated active evolution patterns now create one deduplicated pending `skill_patch` action proposal with `R2` approval required, evidence refs, pending-approval status, verification commands, promotion gate, and rollback condition. Release readiness rejects legacy evolution evidence that proves only "a proposal exists" without proving the rollout plan.
- `/raphael-status` now renders pending skill-patch rollout plans as pending approval with Verify/Promote/Rollback steps, refuses stale `applied` rollout status on pending proposals, and redacts secrets and private paths from rollout metadata.
- Media readiness currently allows only the OpenAI image-only slice; full media remains refused until Grok and video evidence pass.
- Repair plans and proof requirements now expose the next machine-readable live proof steps.

Current media-profile evidence:

- Fresh media-profile LLM smoke `20260701_163247_d9b87d` proves `gpt-5.5`, zero tool calls, summon sections, same-mission continuity, and no visual failure trace for the media readiness bundle.
- Fresh media-profile non-visual regression report `non-visual-regression-20260701-wow-user-simulation-proof-v1` records `1541` passing tests, zero failures, zero visual quota, no OpenAI live generation, and no xAI/Grok live generation.
- OpenAI image-only visual report `openai-visual-live-20260701-openai-gpt-strict-review.reviewed.json` proves only `openai_image_generation`; it explicitly does not prove Grok, xAI, video, or full media readiness.

Weak or incomplete:

- Public wow/Sage King/big-evolution claims remain denied by current hostile UX evidence.
- Completion audit hard-blocks ultimate readiness on denied Sage King/wow/big-evolution claims plus missing xAI/Grok and video evidence.
- Evolution is gated, auditable, can prioritize repeated self-correction patterns, and can create approval-gated skill-patch proposals with rollout-plan enforcement; it is still not full autonomous skill publication like the final Sage King target.
- Full media release lacks Grok live generation and image-first video proof.
- The deterministic demo score is now displayed as `Offline demo shape`; it remains useful shape evidence, not human delight evidence.
- Some mixed core surfaces remain in the broader worktree; the LLM boundary and release slice manifest pass, but final publication still needs slice review discipline.
- The worktree is too large for review as a single public release, though changed paths, Raphael core imports, and reviewer handoff slices are now machine-classified.

## Next Gate

1. Keep feature additions frozen for the scoped LLM and limited OpenAI image-only slices; publish them only with the current explicit claim boundaries.
2. Preserve the current no-visual hostile review evidence when publishing the LLM-only slice and the limited OpenAI image scope.
3. Split or document the LLM-only slice first: core control, lifecycle CLI, summon UX, evolution audit, release gate.
4. Defer full media release until Grok and image-first video live evidence are available.
5. Run `scripts/raphael_completion_audit.py` before any full Sage King or wow launch wording.
6. Attach `scripts/raphael_release_slice_manifest.py --from-git-status` output to reviewer handoff for the scoped LLM slice.

## Gate State Summary

LLM-only public slice: `ready_for_llm_only_release`.

OpenAI image-only media slice: `ready_for_limited_media_public_release` with scope `media_openai_image_only`.

Full media Raphael: not ready. Current hard gaps are `xai_grok_generation` and `video_generation`.

Public promotion readiness: scoped only. Public wording must stay limited to the current gate state, scope, and explicit exclusions; do not use percentage estimates as release evidence.
