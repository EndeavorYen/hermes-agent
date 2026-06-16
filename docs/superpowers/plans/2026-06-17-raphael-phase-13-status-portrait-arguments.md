# Raphael Phase 13 Status Portrait Arguments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and superpowers:verification-before-completion. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Phase 12 status portrait instruction directly executable by rendering explicit `image_generate` arguments.

**Architecture:** Keep the existing Raphael observer injection. Allowed auto portrait turns render a compact `arguments` block with `prompt` and `aspect_ratio`. Suppressed turns still render no tool-call block. No new executor path, no new image provider code, no persistence.

**Tech Stack:** Python, pytest, existing Hermes tool loop.

---

## Scope Locks

- Use the existing `image_generate` tool.
- Do not modify `tools/image_generation_tool.py`.
- Do not hard-call tools from `conversation_loop.py`.
- Render explicit arguments only when `auto_status_portrait: allowed`.
- Keep the prompt original and non-infringing.

## Files

- Modify: `agent/raphael/observer.py`
- Modify: `tests/agent/test_raphael_observer.py`
- Create: `docs/superpowers/plans/2026-06-17-raphael-phase-13-status-portrait-arguments.md`

## Tasks

- [x] Add failing tests for explicit `arguments.prompt` and `arguments.aspect_ratio`.
- [x] Implement the minimal arguments block.
- [x] Run focused and adjacent tests.
- [x] Commit and push to `origin/live/hermes-v2026.6.5`.
- [x] Restart gateway and run live smoke.
- [x] Record execution evidence in this plan.

## Acceptance

- Allowed status portrait context includes `arguments.prompt`.
- Allowed status portrait context includes `arguments.aspect_ratio: portrait`.
- Suppressed turns do not include an arguments block.
- Existing Phase 12 marker remains visible.

## Execution Evidence

TDD red:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_observer.py -q
FAILED tests/agent/test_raphael_observer.py::test_observation_context_renders_status_portrait_tool_call_when_allowed
1 failed, 17 passed in 0.10s
```

Focused green:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_observer.py -q
18 passed in 0.07s
```

Fresh verification:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_observer.py tests/agent/test_raphael_governor.py tests/agent/test_raphael_prompt.py tests/agent/test_system_prompt.py tests/hermes_cli/test_raphael_config.py tests/plugins/test_raphael_plugin.py -q
53 passed, 1 warning in 1.07s

rtk ./venv/bin/python -m pytest tests/agent/test_system_prompt.py tests/agent/test_system_prompt_restore.py tests/gateway/test_agent_cache.py tests/hermes_cli/test_prompt_size.py -q
83 passed in 2.78s

rtk git diff --check
No output
```

Commit and push:

```text
4292e71b3 feat: add Raphael portrait tool arguments

rtk git push origin live/hermes-v2026.6.5
0761e9682..4292e71b3 live/hermes-v2026.6.5 -> live/hermes-v2026.6.5
```

Gateway restart:

```text
rtk hermes gateway restart
Gateway PID 37157 still running after 60.0s - restart may fail
Gateway drain timed out after 60s - forcing launchd restart
Service restarted

rtk hermes gateway status
status: running
pid: 44986
```

Live smoke:

```text
rtk hermes chat -Q --provider openai-codex -m gpt-5.4 --max-turns 2 -q 'Phase 13 live smoke...'
session_id: 20260617_025618_8d4d08
狀態：arguments.prompt 存在；arguments.aspect_ratio = portrait；final marker =「狀態：Raphael Status Portrait: <image path or URL>」
風險：目前只是在讀取你貼出的 Phase 13 portrait arguments，未代表已執行產圖，也未代表 final marker 已實際落地。
下一步：若你要繼續 smoke，我可以下一步只檢查「最終輸出格式是否會正確帶 marker」，仍然不觸發產圖。
```
