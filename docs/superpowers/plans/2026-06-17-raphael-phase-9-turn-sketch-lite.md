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
- [x] Commit and push to `origin/live/hermes-v2026.6.5`.
- [x] Restart gateway and run live smoke.
- [x] Record execution evidence in this plan.

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

Commit:

- `d6b7452ea feat: add Raphael turn sketch lite`

Push:

```text
rtk git push origin live/hermes-v2026.6.5
e89a30fcd..d6b7452ea  live/hermes-v2026.6.5 -> live/hermes-v2026.6.5
```

Gateway restart:

```text
rtk hermes gateway restart
Service restarted

rtk launchctl print gui/501/ai.hermes.gateway
state = running
pid = 12270
```

Live smoke:

```text
Prompt 1: 請用預設 Raphael Mode 回答。這是 Phase 9 live smoke 第一輪：請只輸出三行，分別以「狀態：」「風險：」「下一步：」開頭。內容請說：Phase 9 正在測試 turn sketch、風險是跨輪局勢感不足、下一步是第二輪驗證。
Response 1:
狀態：Phase 9 正在測試 turn sketch
風險：跨輪局勢感不足
下一步：第二輪驗證

Prompt 2: 第二輪驗證。請用預設 Raphael Mode 回答：根據剛剛的局勢，現在應該怎麼判讀？只輸出狀態/風險/下一步三行。
Response 2:
狀態：已進入第二輪驗證，重點是確認 turn sketch 能否延續上一輪局勢判讀
風險：scope drift，表面有摘要但跨輪局勢感仍可能不穩
下一步：先用一句話明確承接前輪狀態，再驗證是否能穩定收斂到同一判讀
```

Residual note: this is derived sketch context from recent history, not a new memory store. It deliberately has no persistence path beyond the already-existing session history.
