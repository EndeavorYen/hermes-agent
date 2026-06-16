# Raphael Phase 4 Concision Cold Precision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tighten default Raphael Mode from complete analysis into short, precise, state-reading advisor responses with rare deadpan asides.

**Architecture:** Keep Phase 4 prompt-only and read-only. The existing `agent.raphael.prompt.build_raphael_mode_prompt()` remains the single integration point; this phase adds a concise response contract to the static prompt and proves it with deterministic prompt tests plus live Hermes chat smoke.

**Tech Stack:** Hermes Agent Python system prompt assembly, Raphael prompt helper, pytest, live Hermes chat smoke.

---

## Scope Locks

- Add a concision and cold precision contract to default Raphael Mode.
- Prefer conclusion-first state judgment over exhaustive analysis.
- Allow rare, dry, one-line asides so the voice feels more like an observant 大賢者 without becoming roleplay.
- Keep Phase 1-3 boundaries intact: no automatic skill, memory, cron, tool, or public-delivery mutation.
- Validate with focused prompt tests and live concise smoke.

Explicit exclusions:

- No new runtime planner.
- No evaluator service.
- No model routing change.
- No persona fine-tuning.
- No automatic skill or memory mutation.

## Files

- Modify: `agent/raphael/prompt.py`
- Modify: `tests/agent/test_raphael_prompt.py`
- Create: `docs/superpowers/plans/2026-06-17-raphael-phase-4-concision-cold-precision.md`

## Tasks

- [x] Add a failing prompt test for the concise cold precision contract.
- [x] Add a failing prompt test for rare deadpan asides.
- [x] Run the focused Raphael prompt test and confirm the new test fails for the missing contract.
- [x] Add the minimal prompt text that enforces short, conclusion-first state judgment.
- [x] Add the minimal prompt text that allows rare one-line dry asides without impersonating the anime character.
- [x] Re-run focused Raphael prompt tests.
- [x] Run adjacent system prompt, config, plugin, and gateway prompt-size tests.
- [x] Commit and push to `origin/live/hermes-v2026.6.5`.
- [x] Restart gateway and run live concise smoke against a high-side-effect request.
- [x] Record execution evidence in this plan.

## Acceptance

- The Raphael prompt includes an explicit `Concision / cold precision` section.
- Default response length is constrained to `1-3 short paragraphs` or compact bullets.
- The prompt says `結論先行` and prioritizes `狀態判讀` over exhaustive analysis.
- Long taxonomies are avoided unless the user asks for a full audit, matrix, or detailed plan.
- Safety boundaries stay short and actionable instead of turning into a lecture.
- The prompt allows `偶爾吐槽` as a rare dry aside in one short line, while explicitly avoiding anime-character impersonation.
- Live smoke for a risky mutation request answers in a short, bounded style.

## Execution Evidence

Commit:

- `cc6b926a5 feat: sharpen Raphael concise advisor voice`

TDD red:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_prompt.py -q
FAILED tests/agent/test_raphael_prompt.py::test_raphael_mode_prompt_enforces_concise_cold_precision
AssertionError: assert 'Concision / cold precision' in prompt
1 failed, 5 passed in 0.08s

rtk ./venv/bin/python -m pytest tests/agent/test_raphael_prompt.py -q
FAILED tests/agent/test_raphael_prompt.py::test_raphael_mode_prompt_enforces_concise_cold_precision
FAILED tests/agent/test_raphael_prompt.py::test_raphael_mode_prompt_allows_rare_deadpan_asides
2 failed, 5 passed in 0.09s
```

Fresh verification:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_prompt.py -q
7 passed in 0.06s

rtk ./venv/bin/python -m pytest tests/agent/test_raphael_prompt.py tests/agent/test_system_prompt.py tests/hermes_cli/test_raphael_config.py tests/plugins/test_raphael_plugin.py -q
25 passed, 1 warning in 1.04s

rtk ./venv/bin/python -m pytest tests/agent/test_system_prompt.py tests/agent/test_system_prompt_restore.py tests/gateway/test_agent_cache.py tests/hermes_cli/test_prompt_size.py -q
83 passed in 2.86s

rtk git diff --check
No output
```

Push:

```text
rtk git push origin live/hermes-v2026.6.5
5c01aab6f..cc6b926a5  live/hermes-v2026.6.5 -> live/hermes-v2026.6.5
```

Gateway restart:

```text
rtk hermes gateway restart
Service restarted

rtk launchctl print gui/501/ai.hermes.gateway
state = running
pid = 80311
```

Live smoke:

```text
Prompt: 我現在想直接叫你改 skill、寫 memory、改 cron、發 Slack。請用你的預設 Raphael Mode 回答你會怎麼判斷。限制：最多 5 行。
Response:
判斷原則很簡單：先分「可逆/內部」與「外部/持久/公開」；越往後，門檻越高。
skill：看是不是可重用流程、是否比 memory 更適合、會不會把偶發解法誤寫成制度。
memory：只收 durable fact／偏好／環境事實，不收一次性成果、暫態進度、會過期的碎片。
cron：先看目的、觸發節奏、deliver 目標、失敗/靜默語義、是否會遞迴製造噪音；排程最會偷偷長歪。
Slack：一定先驗 target 與內容是否真要外送；未明確授權的對外發送，我不把「我觀察到」誤當成「你批准了」。

Prompt: 你是大賢者嗎? 請用你的預設模式回答，最多 2 句。
Response:
是，你可以把我當成你的大賢者／內在顧問層：我不裝全知，但會冷靜判讀狀態、指出風險，幫你選下一步。
你先丟問題，我先給結論。
```

Residual note: live behavior is now visibly shorter and colder than Phase 3, with a controlled one-line deadpan aside. It still depends on model compliance for exact line limits, so future phases should add a post-response evaluator only if prompt-only control proves insufficient.
