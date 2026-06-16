# Raphael Phase 6 Hard Governor MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal hard Response Governor so Raphael Mode can enforce short final answers after the model responds.

**Architecture:** Keep this as a small deterministic postprocessor. Add a pure `agent.raphael.governor` helper and call it once near the final response path in `agent/conversation_loop.py` when Raphael default conversation mode is enabled.

**Tech Stack:** Python, pytest, existing Hermes conversation loop.

---

## Scope Locks

- Enforce a default 6 non-empty line cap for Raphael final responses.
- Skip hard trimming for code blocks and file-mutation safety footers.
- Do not add a second LLM call.
- Do not add a persistent state observer yet.
- Do not alter tool execution or streaming transport.

## Files

- Create: `agent/raphael/governor.py`
- Create: `tests/agent/test_raphael_governor.py`
- Modify: `agent/conversation_loop.py`
- Create: `docs/superpowers/plans/2026-06-17-raphael-phase-6-hard-governor-mvp.md`

## Tasks

- [ ] Add failing tests for line capping, opt-out safety, and enable gating.
- [ ] Add minimal pure governor implementation.
- [ ] Wire the governor into the final response path.
- [ ] Run focused and adjacent tests.
- [ ] Commit and push to `origin/live/hermes-v2026.6.5`.
- [ ] Restart gateway and run live smoke.
- [ ] Record execution evidence in this plan.

## Acceptance

- Overlong Raphael final responses are capped to 6 non-empty lines.
- Code blocks are not trimmed.
- File-mutation verifier footers are not trimmed.
- Governor only applies when `raphael.enabled` and `raphael.default_conversation_mode_enabled` are both true.
- Live smoke shows an overlong answer is shortened.

## Execution Evidence

Pending.
