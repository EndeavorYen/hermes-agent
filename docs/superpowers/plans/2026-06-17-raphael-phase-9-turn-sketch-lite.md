# Raphael Phase 9 Turn Sketch Lite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and superpowers:verification-before-completion. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Raphael Mode a tiny short-term sketch of recent judged turns without adding a new memory store.

**Architecture:** Derive up to 3 sketch lines from recent assistant messages already present in `conversation_history`. Render those lines inside the existing Phase 8 observation context and inject them as ephemeral user-message context. No new persistence, no second LLM call, no state machine.

**Tech Stack:** Python, pytest, existing Hermes conversation loop.

---

## Scope Locks

- Extract only recent `狀態 / 風險 / 下一步` assistant judgment lines.
- Keep at most 3 sketch lines.
- Derive from existing conversation history only.
- Do not write a new DB table, memory item, file, cron job, or plugin state.
- Do not summarize with an LLM.

## Files

- Modify: `agent/raphael/observer.py`
- Modify: `tests/agent/test_raphael_observer.py`
- Modify: `agent/conversation_loop.py`
- Create: `docs/superpowers/plans/2026-06-17-raphael-phase-9-turn-sketch-lite.md`

## Tasks

- [x] Add failing tests for extracting recent sketch lines and rendering them in observation context.
- [x] Implement minimal sketch extraction/rendering in `agent/raphael/observer.py`.
- [x] Pass conversation history into Phase 8 observation injection.
- [x] Run focused and adjacent tests.
- [ ] Commit and push to `origin/live/hermes-v2026.6.5`.
- [ ] Restart gateway and run live smoke.
- [ ] Record execution evidence in this plan.

## Acceptance

- Recent assistant `狀態 / 風險 / 下一步` lines appear in the internal Raphael context on the next turn.
- Sketch context remains capped at 3 lines.
- No new persistence path is added.
- Existing observer behavior still works when no prior sketch exists.

## Execution Evidence

TDD red:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_observer.py -q
ImportError: cannot import name 'extract_raphael_turn_sketches' from 'agent.raphael.observer'
1 error in 0.06s
```

Focused green:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_observer.py -q
7 passed in 0.07s
```

Fresh verification:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_observer.py tests/agent/test_raphael_governor.py tests/agent/test_raphael_prompt.py tests/agent/test_system_prompt.py tests/hermes_cli/test_raphael_config.py tests/plugins/test_raphael_plugin.py -q
42 passed, 1 warning in 0.99s

rtk ./venv/bin/python -m pytest tests/agent/test_system_prompt.py tests/agent/test_system_prompt_restore.py tests/gateway/test_agent_cache.py tests/hermes_cli/test_prompt_size.py -q
83 passed in 2.78s

rtk git diff --check
No output
```
