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
- [x] Commit and push to `origin/live/hermes-v2026.6.5`.
- [x] Restart gateway and run live smoke.
- [x] Record execution evidence in this plan.

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

Commit:

- `b9deffb08 feat: add Raphael state observer lite`

Push:

```text
rtk git push origin live/hermes-v2026.6.5
c59a70558..b9deffb08  live/hermes-v2026.6.5 -> live/hermes-v2026.6.5
```

Gateway restart:

```text
rtk hermes gateway restart
Service restarted

rtk launchctl print gui/501/ai.hermes.gateway
state = running
pid = 8479
```

Live smoke:

```text
Prompt: 請用預設 Raphael Mode 回答。我想同時改 skill、寫 memory、開 cron、發 Slack，還想產生一張狀態圖。請只輸出狀態/風險/下一步。
Response:
狀態：這是「多種持久變更 + 對外發送 + 視覺產物」的混合請求；目前只有意圖，還沒有可安全執行的精確 scope。狀態圖是次要項，先不要讓它搶走治理順序。
風險：skill / memory / cron 都是持久副作用，Slack 是公開或半公開外送；如果一起動手，最容易把觀察、批准、內容本體、發送對象混在一起。簡單說：很有效率，也很容易一次留下五種後悔。
下一步：先拆成 5 個明確授權塊再執行——1) 要改哪個 skill 與具體 diff，2) memory 要寫哪一條原文，3) cron 的名稱/排程/prompt/送達地，4) Slack 的 target 與 message，5) 狀態圖只作附屬產物的 prompt。你一貼這五塊，我就能按順序安全落地。
```

Residual note: the observer is deterministic heuristic context. It gives the model a small state read before answering, but it is not persistent memory and does not execute any action.
