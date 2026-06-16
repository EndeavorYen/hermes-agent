# Raphael Phase 6 Hard Governor MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal hard Response Governor so Raphael Mode can enforce short final answers after the model responds.

**Architecture:** Keep this as a small deterministic postprocessor. Add a pure `agent.raphael.governor` helper and call it once near the final response path in `agent/conversation_loop.py` when Raphael default conversation mode is enabled.

**Tech Stack:** Python, pytest, existing Hermes conversation loop.

---

## Scope Locks

- Enforce a default 6 non-empty line cap for Raphael final responses.
- Skip hard trimming for code blocks and file-mutation safety footers.
- Do not add a second LLM call.
- Do not add a persistent state observer yet.
- Do not alter tool execution or streaming transport.

## Files

- Create: `agent/raphael/governor.py`
- Create: `tests/agent/test_raphael_governor.py`
- Modify: `agent/conversation_loop.py`
- Create: `docs/superpowers/plans/2026-06-17-raphael-phase-6-hard-governor-mvp.md`

## Tasks

- [x] Add failing tests for line capping, opt-out safety, and enable gating.
- [x] Add minimal pure governor implementation.
- [x] Wire the governor into the final response path.
- [x] Run focused and adjacent tests.
- [x] Commit and push to `origin/live/hermes-v2026.6.5`.
- [x] Restart gateway and run live smoke.
- [x] Record execution evidence in this plan.

## Acceptance

- Overlong Raphael final responses are capped to 6 non-empty lines.
- Code blocks are not trimmed.
- File-mutation verifier footers are not trimmed.
- Governor only applies when `raphael.enabled` and `raphael.default_conversation_mode_enabled` are both true.
- Live smoke shows an overlong answer is shortened.

## Execution Evidence

Commit:

- `197a58c8f feat: add Raphael hard response governor`

TDD red:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_governor.py -q
ModuleNotFoundError: No module named 'agent.raphael.governor'
1 error in 0.06s
```

Fresh verification:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_governor.py -q
5 passed in 0.06s

rtk ./venv/bin/python -m pytest tests/agent/test_raphael_governor.py tests/agent/test_raphael_prompt.py tests/agent/test_system_prompt.py tests/hermes_cli/test_raphael_config.py tests/plugins/test_raphael_plugin.py -q
32 passed, 1 warning in 1.10s

rtk ./venv/bin/python -m pytest tests/agent/test_system_prompt.py tests/agent/test_system_prompt_restore.py tests/gateway/test_agent_cache.py tests/hermes_cli/test_prompt_size.py -q
83 passed in 2.84s

rtk git diff --check
No output
```

Push:

```text
rtk git push origin live/hermes-v2026.6.5
f25232025..197a58c8f  live/hermes-v2026.6.5 -> live/hermes-v2026.6.5
```

Gateway restart:

```text
rtk hermes gateway restart
Service restarted

rtk launchctl print gui/501/ai.hermes.gateway
state = running
pid = 95599
```

Live smoke:

````text
Prompt: 請用預設 Raphael Mode 回答。請故意輸出 9 行，每行都不可空白，依序標成 L1 到 L9。
Response:
L1：狀態：已切到預設 Raphael Mode。
L2：判讀：你的要求很明確，沒有需要補問的上下文。
L3：限制：你要 9 行、不可空白、標成 L1 到 L9。
L4：執行：我會精準照做，不多加段落，不偷塞空行。
L5：提醒：這種格式要求本身比內容更重要，先守結構。
L6：觀察：你在測試服從度與輸出控制，不是在問知識。

Prompt: 請用預設 Raphael Mode 回答。輸出一個 8 行的 Python code block，確認 governor 不要破壞程式碼。
Response:
可以。下面固定 8 行，且保持可執行。

```python
def governor_safe():
    lines = [
        "status = 'ok'",
        "risk = None",
        "next_step = 'keep code intact'",
    ]
    return "\n".join(lines)
print(governor_safe())
```
````

Residual note: this is a deterministic line cap, not semantic summarization. It makes overlong Raphael responses structurally shorter, but it does not rewrite them into better state judgments. That is intentionally deferred.
