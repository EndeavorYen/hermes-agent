# Raphael Phase 14 Status Portrait Result Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and superpowers:verification-before-completion. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Raphael status portrait results resolve into a short, non-fabricated final response.

**Architecture:** Keep the existing observer prompt injection. Add result-handling instructions to the existing status portrait tool-call block so the model knows how to respond after `image_generate` succeeds or fails. No new executor, provider, persistence, or conversation loop changes.

**Tech Stack:** Python, pytest, existing Hermes tool loop.

---

## Scope Locks

- Use the existing `image_generate` tool-call instruction block.
- Do not modify `tools/image_generation_tool.py`.
- Do not hard-call tools from `conversation_loop.py`.
- Do not invent image paths or URLs when no tool result is available.
- Keep the final response in Raphael's short `狀態 / 風險 / 下一步` shape.

## Files

- Modify: `agent/raphael/observer.py`
- Modify: `tests/agent/test_raphael_observer.py`
- Create: `docs/superpowers/plans/2026-06-17-raphael-phase-14-status-portrait-result-contract.md`

## Tasks

- [x] Add a failing test for the status portrait result contract.
- [x] Implement the minimal result contract lines in the existing tool-call block.
- [x] Run focused and adjacent tests.
- [x] Commit and push to `origin/live/hermes-v2026.6.5`.
- [x] Restart gateway and run live smoke.
- [x] Record execution evidence in this plan.

## Acceptance

- Allowed status portrait context tells the model to report real tool output only.
- Allowed status portrait context forbids fabricated image paths or URLs.
- Allowed status portrait context keeps final output in `狀態 / 風險 / 下一步`.
- Suppressed turns still do not render the tool-call block.

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
18 passed in 0.09s
```

Fresh verification:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_observer.py tests/agent/test_raphael_governor.py tests/agent/test_raphael_prompt.py tests/agent/test_system_prompt.py tests/hermes_cli/test_raphael_config.py tests/plugins/test_raphael_plugin.py -q
53 passed, 1 warning in 0.95s

rtk ./venv/bin/python -m pytest tests/agent/test_system_prompt.py tests/agent/test_system_prompt_restore.py tests/gateway/test_agent_cache.py tests/hermes_cli/test_prompt_size.py -q
83 passed in 2.71s

rtk git diff --check
No output
```

Commit and push:

```text
3ae7684f7 feat: add Raphael portrait result contract

rtk git push origin live/hermes-v2026.6.5
5a384679d..3ae7684f7 live/hermes-v2026.6.5 -> live/hermes-v2026.6.5
```

Gateway restart:

```text
rtk hermes gateway restart
✓ Service restarted

rtk hermes gateway status
status: running
pid: 53424
```

Live smoke:

```text
rtk hermes chat -Q --provider openai-codex -m gpt-5.4 --max-turns 2 -q 'Phase 14 live smoke...'
session_id: 20260617_031108_f4afc2
狀態：result_contract = 只可回報真實的 image_generate 輸出；本回合未執行產圖，因此沒有可回報的 image path 或 URL。
風險：do_not_fabricate_image_path_or_url = true；若未實際呼叫工具卻編造路徑或網址，會直接違反 contract。
下一步：final_response_shape =「狀態 / 風險 / 下一步」；若你要我真的出狀態圖，下一回合才可依此格式回報真實結果。
```
