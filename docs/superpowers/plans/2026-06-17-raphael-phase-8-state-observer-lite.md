# Raphael Phase 8 State Observer Lite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development for behavior changes and superpowers:verification-before-completion before claiming completion.

**Goal:** Add a deterministic per-turn Raphael observation so default Raphael Mode can notice task state, risk signal, next move, and visual status need before the model answers.

**Architecture:** Keep this as an ephemeral user-message context injection. Add a pure `agent.raphael.observer` helper and call it once per turn from `agent/conversation_loop.py`. No persistent state, no second LLM call, no tool execution changes.

**Tech Stack:** Python, pytest, existing Hermes conversation loop.

---

## Scope Locks

- Emit one compact internal observation per turn when default Raphael Mode is enabled.
- Track only `task_state`, `risk_signal`, `suggested_next_move`, and `visual_status_needed`.
- Keep heuristics deterministic and local.
- Do not persist the observation to session DB.
- Do not mutate memory, cron, tools, Slack, images, or public delivery from this observer.
- Do not add a second LLM call or a state machine.

## Files

- Create: `agent/raphael/observer.py`
- Create: `tests/agent/test_raphael_observer.py`
- Modify: `agent/conversation_loop.py`
- Create: `docs/superpowers/plans/2026-06-17-raphael-phase-8-state-observer-lite.md`

## Tasks

- [x] Add failing tests for observer defaults, mutation risk, visual status, rendering, and config gate.
- [x] Implement minimal pure observer.
- [x] Inject observation into current-turn ephemeral user context.
- [x] Run focused and adjacent tests.
- [ ] Commit and push to `origin/live/hermes-v2026.6.5`.
- [ ] Restart gateway and run live smoke.
- [ ] Record execution evidence in this plan.

## Acceptance

- Default Raphael Mode injects a compact internal observation for the current turn.
- Casual/direct messages are marked low risk.
- Persistent or public side-effect requests are marked as mutation/delivery risk.
- Visual/status portrait requests set `visual_status_needed: true`.
- The injected observation is ephemeral and does not alter persisted conversation history.

## Execution Evidence

TDD red:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_observer.py -q
ModuleNotFoundError: No module named 'agent.raphael.observer'
1 error in 0.07s
```

Focused green:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_observer.py -q
5 passed in 0.06s
```

Fresh verification:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_observer.py tests/agent/test_raphael_governor.py tests/agent/test_raphael_prompt.py tests/agent/test_system_prompt.py tests/hermes_cli/test_raphael_config.py tests/plugins/test_raphael_plugin.py -q
40 passed, 1 warning in 0.99s

rtk ./venv/bin/python -m pytest tests/agent/test_system_prompt.py tests/agent/test_system_prompt_restore.py tests/gateway/test_agent_cache.py tests/hermes_cli/test_prompt_size.py -q
83 passed in 2.79s

rtk git diff --check
No output
```
