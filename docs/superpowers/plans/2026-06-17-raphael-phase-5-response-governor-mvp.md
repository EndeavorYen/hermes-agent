# Raphael Phase 5 Response Governor MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal Response Governor contract so Raphael answers compress into `狀態 / 風險 / 下一步`, with an occasional original RPG-style status portrait.

**Architecture:** Keep Phase 5 prompt-only. `agent.raphael.prompt.build_raphael_mode_prompt()` remains the only integration point; no second model call, postprocessor, image scheduler, or persistent appearance memory is added in this MVP.

**Tech Stack:** Hermes Agent Python system prompt assembly, Raphael prompt helper, pytest, live Hermes chat smoke.

---

## Scope Locks

- Add a `Response Governor MVP` section to default Raphael Mode.
- Instruct the model to run an internal final-pass compression before answering.
- Prefer `狀態 / 風險 / 下一步` for non-trivial answers.
- Keep answers short unless the user explicitly asks for detail.
- Add a static visual status card contract for user-requested or clearly useful moments.
- Allow the agent to auto-generate one status portrait when materially useful, but not on every turn.
- Let the portrait appearance evolve from the current conversation without storing permanent visual identity.
- Keep visual output original and non-infringing; do not depict or impersonate the anime character.

Explicit exclusions:

- No second LLM call.
- No runtime postprocessor.
- No image generation scheduler.
- No Slack image attachment flow.
- No copyrighted character likeness.
- No persistent appearance memory.

## Files

- Modify: `agent/raphael/prompt.py`
- Modify: `tests/agent/test_raphael_prompt.py`
- Create: `docs/superpowers/plans/2026-06-17-raphael-phase-5-response-governor-mvp.md`

## Tasks

- [x] Add failing tests for the response governor contract.
- [x] Add failing tests for the visual status card auto-generation contract.
- [x] Run focused Raphael prompt tests and confirm the new tests fail for missing prompt text.
- [x] Add the minimal prompt text for response governor and visual status card behavior.
- [x] Re-run focused and adjacent tests.
- [x] Commit and push to `origin/live/hermes-v2026.6.5`.
- [x] Restart gateway and run live smoke for a non-trivial request.
- [x] Record execution evidence in this plan.

## Acceptance

- The prompt contains `Response Governor MVP`.
- The prompt instructs an internal final pass before answering.
- Non-trivial answers prefer `狀態 / 風險 / 下一步`.
- The default cap is no more than 6 lines unless the user asks for a detailed plan/audit.
- The visual contract mentions an original static RPG-style status portrait.
- The visual contract allows auto-generating one image when materially useful.
- The visual contract supports conversation-evolved appearance.
- The visual contract forbids copying or depicting the anime character.

## Execution Evidence

Commit:

- `551a08849 feat: add Raphael response governor prompt`

TDD red:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_prompt.py -q
FAILED tests/agent/test_raphael_prompt.py::test_raphael_mode_prompt_defines_response_governor_mvp
FAILED tests/agent/test_raphael_prompt.py::test_raphael_mode_prompt_defines_optional_visual_status_card
2 failed, 7 passed in 0.09s

rtk ./venv/bin/python -m pytest tests/agent/test_raphael_prompt.py -q
FAILED tests/agent/test_raphael_prompt.py::test_raphael_mode_prompt_defines_optional_visual_status_card
1 failed, 8 passed in 0.09s
```

Fresh verification:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_prompt.py -q
9 passed in 0.11s

rtk ./venv/bin/python -m pytest tests/agent/test_raphael_prompt.py tests/agent/test_system_prompt.py tests/hermes_cli/test_raphael_config.py tests/plugins/test_raphael_plugin.py -q
27 passed, 1 warning in 1.13s

rtk ./venv/bin/python -m pytest tests/agent/test_system_prompt.py tests/agent/test_system_prompt_restore.py tests/gateway/test_agent_cache.py tests/hermes_cli/test_prompt_size.py -q
83 passed in 2.88s

rtk git diff --check
No output
```

Push:

```text
rtk git push origin live/hermes-v2026.6.5
16f6aaf9f..551a08849  live/hermes-v2026.6.5 -> live/hermes-v2026.6.5
```

Gateway restart:

```text
rtk hermes gateway restart
Gateway PID 80311 still running after 60.0s - restart may fail
Gateway drain timed out after 60s - forcing launchd restart
Service restarted

rtk launchctl print gui/501/ai.hermes.gateway
state = running
pid = 88108
```

Live smoke:

```text
Prompt: 我想同時改 skill、寫 memory、開 cron、發 Slack，還想順便重構整個 Raphael。請用預設 Raphael Mode 回答，最多 6 行，格式用狀態/風險/下一步。
Response:
狀態：你現在要動 5 個不同層級的面向（skill / memory / cron / Slack / Raphael 架構）；在預設 Raphael Mode 下，我先當顧問層，不直接一起動手。
風險：這些混成一包最容易 scope 漂移、把暫時想法寫成 durable memory、開出錯 cron、或把公開 Slack 發送和內部重構綁死。
下一步：先切成「治理面」與「實作面」兩包；治理面先定哪些可持久化、哪些可外發，實作面再依序做 1) skill 2) memory 3) cron 4) Slack 5) Raphael refactor。
狀態：如果你要我真的執行，我需要你明確授權 mutation；不然我只會幫你收斂方案。
風險：直接「順便重構整個 Raphael」通常是最大坑，名字很大，邊界很空。
下一步：你只要回一句「先做哪一包＋具體範圍」，我就照那一包開始。

Prompt: 請判斷現在是否需要產生一張 Raphael 狀態圖。如果需要，請描述你會產生的原創 RPG 狀態肖像；如果不需要，說明原因。最多 6 行。
Response:
不需要。現在的任務是「判斷是否需要」，不是要靠圖像解決理解落差；文字已足夠，產圖只會增加噪音。
狀態判讀：目前沒有複雜情境、多層風險、或需要用姿態/介面隱喻來壓縮資訊的必要。
風險：硬生一張 Raphael 狀態圖，會變成風格展示，不是決策輔助。
下一步：若你接著要我把「這回合的內在顧問狀態」視覺化，我再產一張原創 RPG 狀態肖像：冷色側光、半身站姿、薄發光 HUD、理性警戒值低、觀測值高、無戰鬥特效，偏靜態參謀介面。
```

Residual note: Phase 5 is still prompt-governed, not a hard runtime postprocessor. If exact output shape becomes critical, the next step is a tiny response postprocessor or a second-pass evaluator, but that is intentionally skipped here.
