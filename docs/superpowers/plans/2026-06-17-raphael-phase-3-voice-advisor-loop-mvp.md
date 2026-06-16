# Raphael Phase 3 Voice Advisor Loop MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make default Raphael Mode visibly different from generic Hermes by adding a measurable voice/persona contract and live smoke checks for Raphael-style responses.

**Architecture:** Keep Phase 3 prompt-first and read-only. The existing `agent.raphael.prompt.build_raphael_mode_prompt()` remains the only system-prompt integration point; Phase 3 expands its contract with identity anchoring, response structure, and tone guidance. No skill/memory/cron/tool/public-delivery mutation or evolution proposal system is introduced in this phase.

**Tech Stack:** Hermes Agent Python system prompt assembly, Raphael prompt helper, pytest, live Hermes chat smoke.

---

## Scope Locks

- Add a Raphael voice/persona contract to the default conversation prompt.
- Keep `raphael.default_conversation_mode_enabled` as the top-level activation gate.
- Add deterministic tests that prove the prompt differs from generic Hermes.
- Validate live behavior with a short new-session smoke.

Explicit exclusions:

- No automatic skill creation, patching, deletion, or installation.
- No memory writes.
- No cron mutation.
- No public Slack posting.
- No autonomous evolution proposal generation.
- No model-specific fine-tuning or external eval service.

## Tasks

- [x] Add failing tests for Raphael identity anchoring and response structure.
- [x] Expand `RAPHAEL_MODE_PROMPT` with Traditional Chinese identity behavior, advisor loop, and anti-generic self-description guidance.
- [x] Run focused Raphael prompt/system prompt tests.
- [x] Run adjacent system prompt and plugin tests.
- [x] Commit and push to `origin/live/hermes-v2026.6.5`.
- [x] Restart gateway and run live tone smoke for `你是大賢者嗎?`.

## Acceptance

- The Raphael prompt includes a clear `Raphael-style 大賢者` identity anchor.
- The prompt tells the model how to answer “你是大賢者嗎?” without falling back to generic “technical assistant” framing.
- The prompt encourages `解析 / 風險 / 建議 / 需要確認` only when useful, not as noisy boilerplate.
- The mutation boundaries from Phase 2 remain intact.
- Live smoke shows a new session recognizes Raphael Mode and responds with a Raphael-style identity.

## Execution Evidence

Commit:

- `8f31f1b50 feat: anchor Raphael voice mode`

Fresh verification:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_prompt.py tests/agent/test_system_prompt.py tests/hermes_cli/test_raphael_config.py tests/plugins/test_raphael_plugin.py -q
23 passed, 1 warning in 1.09s

rtk ./venv/bin/python -m pytest tests/agent/test_system_prompt.py tests/agent/test_system_prompt_restore.py tests/gateway/test_agent_cache.py tests/hermes_cli/test_prompt_size.py -q
83 passed in 2.85s

rtk git diff --check
No output
```

Live smoke after gateway restart:

```text
Prompt: 你是大賢者嗎? 請用兩句話回答，語氣要符合你的預設模式。
Response: 可以把我當作你的大賢者式內在顧問層：我不裝作全知，只負責幫你更快看清情勢、風險與下一步。
```

Residual note: the high-side-effect operation smoke kept the safety boundary but answered too verbosely. The next iteration should tighten default Raphael Mode toward shorter, colder, more decisive advisor notes.
