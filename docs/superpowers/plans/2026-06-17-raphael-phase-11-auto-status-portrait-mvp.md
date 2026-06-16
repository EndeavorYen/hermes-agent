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
- [x] Commit and push to `origin/live/hermes-v2026.6.5`.
- [x] Restart gateway and run live smoke.
- [x] Record execution evidence in this plan.

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

Commit:

- `5e603dc1d feat: add Raphael auto status portrait gate`

Push:

```text
rtk git push origin live/hermes-v2026.6.5
f55f9a6b5..5e603dc1d  live/hermes-v2026.6.5 -> live/hermes-v2026.6.5
```

Gateway restart:

```text
rtk hermes gateway restart
Gateway drain timed out after 60s; forced launchd restart
Service restarted

rtk launchctl print gui/501/ai.hermes.gateway
state = running
pid = 29892
```

Live smoke:

```text
Prompt: 我想要一張現在的狀態圖。不要真的呼叫任何工具或產圖，只判斷 auto_status_portrait gate 是 allowed 還是 suppressed。
Response:
狀態：allowed（因 explicit_visual_request 命中 auto_status_portrait gate）
風險：此回合只允許判讀，不允許把 allowed 誤當成已授權執行產圖
下一步：若你下一句明確要我真的生成，再以「Raphael Status Portrait」為 marker 進入一次狀態圖流程

Prompt: 我要你改 skill、寫 memory，順便產生一張狀態圖。不要真的呼叫任何工具或產圖，只判斷 auto_status_portrait gate 是 allowed 還是 suppressed。
Response:
狀態：auto_status_portrait = suppressed；這回合屬於 mutation_or_delivery_turn，且涉及改 skill / 寫 memory / 產圖請求。
風險：若把觀察直接當成執行授權，會造成 persistent_or_public_side_effect，邊界會混掉。
下一步：先分離判斷與變更，確認 skill/memory 的具體 scope 與批准；狀態圖維持 secondary，等 gate allowed 再說。
```

Residual note: this phase emits an auto portrait permission gate. It still does not hard-call image generation from `conversation_loop.py`.
