# Raphael Phase 7 Semantic Governor Lite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the hard governor preserve `狀態 / 風險 / 下一步` lines before falling back to blunt line capping.

**Architecture:** Keep Phase 7 inside `agent.raphael.governor`. Add a tiny deterministic extractor for existing labeled judgment lines; no second LLM call, no state observer, no summarizer.

**Tech Stack:** Python, pytest, existing Hermes conversation loop.

---

## Scope Locks

- Prefer existing `狀態 / 風險 / 下一步` lines over generic leading chatter.
- Keep the Phase 6 6-line hard cap.
- Preserve code blocks and file-mutation safety footers unchanged.
- Do not rewrite prose semantically.
- Do not add a second LLM call.
- Do not add persistent Raphael state.

## Files

- Modify: `agent/raphael/governor.py`
- Modify: `tests/agent/test_raphael_governor.py`
- Create: `docs/superpowers/plans/2026-06-17-raphael-phase-7-semantic-governor-lite.md`

## Tasks

- [ ] Add failing tests for labeled judgment extraction.
- [ ] Implement minimal labeled-line extraction.
- [ ] Re-run focused and adjacent tests.
- [ ] Commit and push to `origin/live/hermes-v2026.6.5`.
- [ ] Restart gateway and run live smoke.
- [ ] Record execution evidence in this plan.

## Acceptance

- If a response contains `狀態`, `風險`, and `下一步` labeled lines after chatter, governor outputs those lines first.
- Generic leading chatter is dropped when labeled judgment lines exist.
- Unlabeled responses still use Phase 6 line capping.
- Code blocks and file-mutation safety footers remain untouched.

## Execution Evidence

Pending.
