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

- [ ] Add failing tests for Raphael identity anchoring and response structure.
- [ ] Expand `RAPHAEL_MODE_PROMPT` with Traditional Chinese identity behavior, advisor loop, and anti-generic self-description guidance.
- [ ] Run focused Raphael prompt/system prompt tests.
- [ ] Run adjacent system prompt and plugin tests.
- [ ] Commit and push to `origin/live/hermes-v2026.6.5`.
- [ ] Restart gateway and run live tone smoke for `你是大賢者嗎?`.

## Acceptance

- The Raphael prompt includes a clear `Raphael-style 大賢者` identity anchor.
- The prompt tells the model how to answer “你是大賢者嗎?” without falling back to generic “technical assistant” framing.
- The prompt encourages `解析 / 風險 / 建議 / 需要確認` only when useful, not as noisy boilerplate.
- The mutation boundaries from Phase 2 remain intact.
- Live smoke shows a new session recognizes Raphael Mode and responds with a Raphael-style identity.
