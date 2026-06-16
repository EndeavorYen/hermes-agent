# Raphael Phase 11 Auto Status Portrait MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and superpowers:verification-before-completion. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Raphael Mode allow one automatic status portrait when Phase 10 says a portrait is useful and cooldown/risk checks pass.

**Architecture:** Extend the existing Raphael observer with an auto portrait gate derived from current observation, visual trigger, and existing conversation history. The gate is rendered as ephemeral internal context. Cooldown is inferred from recent assistant messages containing a `Raphael Status Portrait` marker; no new persistence, no scheduler, no hardcoded tool execution path.

**Tech Stack:** Python, pytest, existing Hermes conversation loop.

---

## Scope Locks

- Allow auto portrait only when visual trigger suggests a status portrait.
- Suppress auto portrait for mutation/public-delivery turns.
- Suppress auto portrait during cooldown when recent assistant history contains `Raphael Status Portrait`.
- Do not add a new DB table, file store, cron, or plugin state.
- Do not hard-call image generation from `conversation_loop.py`; emit a gate the model/tool loop can honor.

## Files

- Modify: `agent/raphael/observer.py`
- Modify: `tests/agent/test_raphael_observer.py`
- Create: `docs/superpowers/plans/2026-06-17-raphael-phase-11-auto-status-portrait-mvp.md`

## Tasks

- [x] Add failing tests for auto allowed, mutation suppression, cooldown suppression, and context rendering.
- [x] Implement minimal auto portrait gate.
- [x] Render the auto portrait gate only when Phase 10 suggests a portrait.
- [x] Run focused and adjacent tests.
- [ ] Commit and push to `origin/live/hermes-v2026.6.5`.
- [ ] Restart gateway and run live smoke.
- [ ] Record execution evidence in this plan.

## Acceptance

- Explicit status portrait requests can render `auto_status_portrait: allowed`.
- High-risk mutation/public-delivery requests render `auto_status_portrait: suppressed`.
- Recent `Raphael Status Portrait` history suppresses auto portrait with a cooldown reason.
- Casual turns do not render the auto portrait gate.

## Execution Evidence

TDD red:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_observer.py -q
ImportError: cannot import name 'decide_raphael_auto_status_portrait' from 'agent.raphael.observer'
1 error in 0.09s
```

Focused green:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_observer.py -q
16 passed in 0.08s
```

Fresh verification:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_observer.py tests/agent/test_raphael_governor.py tests/agent/test_raphael_prompt.py tests/agent/test_system_prompt.py tests/hermes_cli/test_raphael_config.py tests/plugins/test_raphael_plugin.py -q
51 passed, 1 warning in 1.02s

rtk ./venv/bin/python -m pytest tests/agent/test_system_prompt.py tests/agent/test_system_prompt_restore.py tests/gateway/test_agent_cache.py tests/hermes_cli/test_prompt_size.py -q
83 passed in 2.74s

rtk git diff --check
No output
```
