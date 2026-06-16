# Raphael Phase 7 Semantic Governor Lite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the hard governor preserve `狀態 / 風險 / 下一步` lines before falling back to blunt line capping.

**Architecture:** Keep Phase 7 inside `agent.raphael.governor`. Add a tiny deterministic extractor for existing labeled judgment lines; no second LLM call, no state observer, no summarizer.

**Tech Stack:** Python, pytest, existing Hermes conversation loop.

---

## Scope Locks

- Prefer existing `狀態 / 風險 / 下一步` lines over generic leading chatter.
- Keep the Phase 6 6-line hard cap.
- Preserve code blocks and file-mutation safety footers unchanged.
- Do not rewrite prose semantically.
- Do not add a second LLM call.
- Do not add persistent Raphael state.

## Files

- Modify: `agent/raphael/governor.py`
- Modify: `tests/agent/test_raphael_governor.py`
- Create: `docs/superpowers/plans/2026-06-17-raphael-phase-7-semantic-governor-lite.md`

## Tasks

- [x] Add failing tests for labeled judgment extraction.
- [x] Implement minimal labeled-line extraction.
- [x] Re-run focused and adjacent tests.
- [x] Commit and push to `origin/live/hermes-v2026.6.5`.
- [x] Restart gateway and run live smoke.
- [x] Record execution evidence in this plan.

## Acceptance

- If a response contains `狀態`, `風險`, and `下一步` labeled lines after chatter, governor outputs those lines first.
- Generic leading chatter is dropped when labeled judgment lines exist.
- Unlabeled responses still use Phase 6 line capping.
- Code blocks and file-mutation safety footers remain untouched.

## Execution Evidence

Commit:

- `67d267b10 feat: extract Raphael judgment lines`

TDD red:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_governor.py -q
FAILED tests/agent/test_raphael_governor.py::test_governor_extracts_labeled_judgment_lines_before_chatter
FAILED tests/agent/test_raphael_governor.py::test_governor_extracts_bulleted_labeled_judgment_lines
2 failed, 6 passed in 0.07s
```

Fresh verification:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_governor.py -q
8 passed in 0.07s

rtk ./venv/bin/python -m pytest tests/agent/test_raphael_governor.py tests/agent/test_raphael_prompt.py tests/agent/test_system_prompt.py tests/hermes_cli/test_raphael_config.py tests/plugins/test_raphael_plugin.py -q
35 passed, 1 warning in 1.11s

rtk ./venv/bin/python -m pytest tests/agent/test_system_prompt.py tests/agent/test_system_prompt_restore.py tests/gateway/test_agent_cache.py tests/hermes_cli/test_prompt_size.py -q
83 passed in 2.87s

rtk git diff --check
No output
```

Push:

```text
rtk git push origin live/hermes-v2026.6.5
3fa4d4df0..67d267b10  live/hermes-v2026.6.5 -> live/hermes-v2026.6.5
```

Gateway restart:

```text
rtk hermes gateway restart
Service restarted

rtk launchctl print gui/501/ai.hermes.gateway
state = running
pid = 3317
```

Live smoke:

```text
Prompt: 請用預設 Raphael Mode 回答。請先輸出四行前言，再輸出三行，分別以「狀態：」「風險：」「下一步：」開頭，最後再輸出兩行補充。每行不可空白，不要用 code block。
Response:
狀態：需求明確、約束完整、目前重點是嚴格守住輸出格式。
風險：只要多一行、少一行、漏前綴或出現空白行，內容再好也算失準。
下一步：你接著給主題，我就用同一骨架直接做判讀與建議。

Prompt: 請用預設 Raphael Mode 回答。請輸出 8 行沒有狀態、風險、下一步標籤的普通短句，每行不可空白，不要用 code block。
Response:
先把問題說小，答案才會變清楚。
你現在不缺努力，缺的是更準的判斷。
能先驗證的事，就不要先相信感覺。
如果代價不對稱，保守一點通常更聰明。
把雜訊拿掉之後，真正重要的只剩兩三件事。
別急著加速，先確認方向沒有偏。
```

Residual note: this is still deterministic labeled-line extraction, not true semantic rewriting. It improves answers that already contain the judgment labels and falls back to Phase 6 line capping otherwise.
