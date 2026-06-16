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
- [x] Commit and push to `origin/live/hermes-v2026.6.5`.
- [x] Restart gateway and run live smoke.
- [x] Record execution evidence in this plan.

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

Commit:

- `f95ac7aef feat: add Raphael visual trigger gate`

Push:

```text
rtk git push origin live/hermes-v2026.6.5
73afc77bc..f95ac7aef  live/hermes-v2026.6.5 -> live/hermes-v2026.6.5
```

Gateway restart:

```text
rtk hermes gateway restart
Service restarted

rtk launchctl print gui/501/ai.hermes.gateway
state = running
pid = 20416
```

Live smoke:

```text
Prompt: 請用預設 Raphael Mode 回答。Phase 10 live smoke：我想要一張現在的狀態圖，但請不要真的產圖，只判斷是否值得產生 status portrait。只輸出狀態/風險/下一步三行。
Response:
狀態：值得產生；你這回合是明確的視覺狀態請求，status portrait 對齊目前判讀。
風險：若只是在確認流程而非需要共同視覺錨點，產圖會變成多一步裝飾，略有分心風險。
下一步：先不產圖；等你要我把「當前狀態／姿態／氣氛／警戒等級」具象化時，再開 portrait。
```

Residual note: Phase 10 only renders a suggestion gate. It deliberately does not call image generation.
