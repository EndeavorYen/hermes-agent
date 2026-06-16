# Raphael Phase 10 Visual Trigger Gate Lite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and superpowers:verification-before-completion. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach Raphael Mode when a status portrait would be useful without auto-calling image generation every turn.

**Architecture:** Add a deterministic visual trigger decision to the existing Raphael observer. Render the decision as ephemeral internal context alongside the Phase 8 observation and Phase 9 turn sketch. No image tool call, no new persistence, no scheduler.

**Tech Stack:** Python, pytest, existing Hermes conversation loop.

---

## Scope Locks

- Suggest a status portrait only for explicit visual requests or meaningful state transitions.
- Do not auto-call image generation in this phase.
- Keep the trigger decision deterministic and local.
- Keep the context ephemeral and derived from current turn/history only.
- Do not add a new plugin, DB table, cron, or background job.

## Files

- Modify: `agent/raphael/observer.py`
- Modify: `tests/agent/test_raphael_observer.py`
- Create: `docs/superpowers/plans/2026-06-17-raphael-phase-10-visual-trigger-gate-lite.md`

## Tasks

- [x] Add failing tests for explicit visual requests, milestone transitions, and quiet/default turns.
- [x] Implement minimal visual trigger decision.
- [x] Render the visual gate in observation context.
- [x] Run focused and adjacent tests.
- [ ] Commit and push to `origin/live/hermes-v2026.6.5`.
- [ ] Restart gateway and run live smoke.
- [ ] Record execution evidence in this plan.

## Acceptance

- Explicit status image requests produce `visual_trigger: suggest_status_portrait`.
- Milestone or blocked/error transitions from recent sketch can produce a status portrait suggestion.
- Casual turns produce `visual_trigger: none`.
- The rendered context says this is a suggestion, not an image tool call.

## Execution Evidence

TDD red:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_observer.py -q
ImportError: cannot import name 'decide_raphael_visual_trigger' from 'agent.raphael.observer'
1 error in 0.07s
```

Quiet-context red:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_observer.py -q
FAILED tests/agent/test_raphael_observer.py::test_observation_context_omits_visual_gate_when_not_needed
1 failed, 11 passed in 0.09s
```

Focused green:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_observer.py -q
12 passed in 0.08s
```

Fresh verification:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_observer.py tests/agent/test_raphael_governor.py tests/agent/test_raphael_prompt.py tests/agent/test_system_prompt.py tests/hermes_cli/test_raphael_config.py tests/plugins/test_raphael_plugin.py -q
47 passed, 1 warning in 0.95s

rtk ./venv/bin/python -m pytest tests/agent/test_system_prompt.py tests/agent/test_system_prompt_restore.py tests/gateway/test_agent_cache.py tests/hermes_cli/test_prompt_size.py -q
83 passed in 2.72s

rtk git diff --check
No output
```
