# Raphael Phase 5 Response Governor MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal Response Governor contract so Raphael answers compress into `狀態 / 風險 / 下一步`, with an occasional original RPG-style status portrait.

**Architecture:** Keep Phase 5 prompt-only. `agent.raphael.prompt.build_raphael_mode_prompt()` remains the only integration point; no second model call, postprocessor, image scheduler, or persistent appearance memory is added in this MVP.

**Tech Stack:** Hermes Agent Python system prompt assembly, Raphael prompt helper, pytest, live Hermes chat smoke.

---

## Scope Locks

- Add a `Response Governor MVP` section to default Raphael Mode.
- Instruct the model to run an internal final-pass compression before answering.
- Prefer `狀態 / 風險 / 下一步` for non-trivial answers.
- Keep answers short unless the user explicitly asks for detail.
- Add a static visual status card contract for user-requested or clearly useful moments.
- Allow the agent to auto-generate one status portrait when materially useful, but not on every turn.
- Let the portrait appearance evolve from the current conversation without storing permanent visual identity.
- Keep visual output original and non-infringing; do not depict or impersonate the anime character.

Explicit exclusions:

- No second LLM call.
- No runtime postprocessor.
- No image generation scheduler.
- No Slack image attachment flow.
- No copyrighted character likeness.
- No persistent appearance memory.

## Files

- Modify: `agent/raphael/prompt.py`
- Modify: `tests/agent/test_raphael_prompt.py`
- Create: `docs/superpowers/plans/2026-06-17-raphael-phase-5-response-governor-mvp.md`

## Tasks

- [ ] Add failing tests for the response governor contract.
- [ ] Add failing tests for the visual status card auto-generation contract.
- [ ] Run focused Raphael prompt tests and confirm the new tests fail for missing prompt text.
- [ ] Add the minimal prompt text for response governor and visual status card behavior.
- [ ] Re-run focused and adjacent tests.
- [ ] Commit and push to `origin/live/hermes-v2026.6.5`.
- [ ] Restart gateway and run live smoke for a non-trivial request.
- [ ] Record execution evidence in this plan.

## Acceptance

- The prompt contains `Response Governor MVP`.
- The prompt instructs an internal final pass before answering.
- Non-trivial answers prefer `狀態 / 風險 / 下一步`.
- The default cap is no more than 6 lines unless the user asks for a detailed plan/audit.
- The visual contract mentions an original static RPG-style status portrait.
- The visual contract allows auto-generating one image when materially useful.
- The visual contract supports conversation-evolved appearance.
- The visual contract forbids copying or depicting the anime character.

## Execution Evidence

Pending.
