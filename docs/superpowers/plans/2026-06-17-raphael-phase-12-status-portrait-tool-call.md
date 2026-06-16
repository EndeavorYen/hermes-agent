# Raphael Phase 12 Status Portrait Tool Call Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and superpowers:verification-before-completion. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When Phase 11 allows an automatic status portrait, provide an exact `image_generate` tool-call instruction that the existing tool loop can execute once.

**Architecture:** Extend the existing Raphael observer context. Allowed auto portrait turns render a small tool-call block with the tool name, aspect ratio, original non-infringing prompt, and required final marker. Suppressed/casual turns render no tool-call block. No new executor path, storage, cron, or image pipeline.

**Tech Stack:** Python, pytest, existing Hermes tool loop.

---

## Scope Locks

- Use the existing `image_generate` tool only.
- Do not hard-call image generation from `conversation_loop.py`.
- Render tool-call instructions only when `auto_status_portrait: allowed`.
- Suppressed/cooldown/mutation turns must not render a tool-call block.
- Require the final answer marker `狀態：Raphael Status Portrait: <image path or URL>` when an image is generated, so cooldown can see it later.

## Files

- Modify: `agent/raphael/observer.py`
- Modify: `tests/agent/test_raphael_observer.py`
- Create: `docs/superpowers/plans/2026-06-17-raphael-phase-12-status-portrait-tool-call.md`

## Tasks

- [x] Add failing tests for allowed tool-call instructions and suppressed no-call behavior.
- [x] Implement the minimal status portrait tool-call block.
- [x] Run focused and adjacent tests.
- [ ] Commit and push to `origin/live/hermes-v2026.6.5`.
- [ ] Restart gateway and run live smoke.
- [ ] Record execution evidence in this plan.

## Acceptance

- Allowed status portrait turns include `tool: image_generate`.
- The tool-call prompt is original and non-infringing.
- The tool-call block asks for one portrait image.
- Suppressed mutation/cooldown turns do not include `tool: image_generate`.
- The final marker requirement is visible in context.

## Execution Evidence

TDD red:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_observer.py -q
FAILED tests/agent/test_raphael_observer.py::test_observation_context_renders_status_portrait_tool_call_when_allowed
1 failed, 17 passed in 0.09s
```

Focused green:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_observer.py -q
18 passed in 0.08s
```

Fresh verification:

```text
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_observer.py tests/agent/test_raphael_governor.py tests/agent/test_raphael_prompt.py tests/agent/test_system_prompt.py tests/hermes_cli/test_raphael_config.py tests/plugins/test_raphael_plugin.py -q
53 passed, 1 warning in 0.96s

rtk ./venv/bin/python -m pytest tests/agent/test_system_prompt.py tests/agent/test_system_prompt_restore.py tests/gateway/test_agent_cache.py tests/hermes_cli/test_prompt_size.py -q
83 passed in 2.74s

rtk git diff --check
No output
```
