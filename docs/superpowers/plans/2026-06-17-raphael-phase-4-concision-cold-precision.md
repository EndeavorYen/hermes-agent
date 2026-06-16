# Raphael Phase 4 Concision Cold Precision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tighten default Raphael Mode from complete analysis into short, precise, state-reading advisor responses with rare deadpan asides.

**Architecture:** Keep Phase 4 prompt-only and read-only. The existing `agent.raphael.prompt.build_raphael_mode_prompt()` remains the single integration point; this phase adds a concise response contract to the static prompt and proves it with deterministic prompt tests plus live Hermes chat smoke.

**Tech Stack:** Hermes Agent Python system prompt assembly, Raphael prompt helper, pytest, live Hermes chat smoke.

---

## Scope Locks

- Add a concision and cold precision contract to default Raphael Mode.
- Prefer conclusion-first state judgment over exhaustive analysis.
- Allow rare, dry, one-line asides so the voice feels more like an observant 大賢者 without becoming roleplay.
- Keep Phase 1-3 boundaries intact: no automatic skill, memory, cron, tool, or public-delivery mutation.
- Validate with focused prompt tests and live concise smoke.

Explicit exclusions:

- No new runtime planner.
- No evaluator service.
- No model routing change.
- No persona fine-tuning.
- No automatic skill or memory mutation.

## Files

- Modify: `agent/raphael/prompt.py`
- Modify: `tests/agent/test_raphael_prompt.py`
- Create: `docs/superpowers/plans/2026-06-17-raphael-phase-4-concision-cold-precision.md`

## Tasks

- [ ] Add a failing prompt test for the concise cold precision contract.
- [ ] Add a failing prompt test for rare deadpan asides.
- [ ] Run the focused Raphael prompt test and confirm the new test fails for the missing contract.
- [ ] Add the minimal prompt text that enforces short, conclusion-first state judgment.
- [ ] Add the minimal prompt text that allows rare one-line dry asides without impersonating the anime character.
- [ ] Re-run focused Raphael prompt tests.
- [ ] Run adjacent system prompt, config, plugin, and gateway prompt-size tests.
- [ ] Commit and push to `origin/live/hermes-v2026.6.5`.
- [ ] Restart gateway and run live concise smoke against a high-side-effect request.
- [ ] Record execution evidence in this plan.

## Acceptance

- The Raphael prompt includes an explicit `Concision / cold precision` section.
- Default response length is constrained to `1-3 short paragraphs` or compact bullets.
- The prompt says `結論先行` and prioritizes `狀態判讀` over exhaustive analysis.
- Long taxonomies are avoided unless the user asks for a full audit, matrix, or detailed plan.
- Safety boundaries stay short and actionable instead of turning into a lecture.
- The prompt allows `偶爾吐槽` as a rare dry aside in one short line, while explicitly avoiding anime-character impersonation.
- Live smoke for a risky mutation request answers in a short, bounded style.

## Execution Evidence

Pending.
