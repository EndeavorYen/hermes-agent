# Raphael Learning Absorption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for completed evidence.

> **TL;DR** — Raphael should absorb the new Hermes learning stack as a control-layer capability, not as a persona flourish. The first implementation target is `/learn` execution bridging; the Greedy King backlog adds memory, curator, journey, sessions, goal/queue/steer/background, approval, skills reload, and cron suggestion surfaces behind evidence gates.

**Goal:** Make Raphael route explicit and inferred learning opportunities into audited skill, memory, and workflow improvements without silently mutating durable policy.

**Architecture:** Keep `agent/raphael/control.py` responsible for intent classification and add a small execution bridge that turns `learn_skill` decisions into the same prompt used by `/learn`. Keep durable writes behind existing Raphael evolution gates, memory/skill approval controls, and curator safeguards. Expose learning state through status/readiness surfaces so Raphael can say what it learned, what it refused to store, and how to roll it back.

**Tech Stack:** Python, pytest, Hermes slash command registry, TUI gateway `command.dispatch`, `agent.learn_prompt.build_learn_prompt`, `agent.raphael.evolution`, `agent.background_review`, `agent.curator`, `agent.learning_graph`.

**Status (2026-07-05):** Completed on `codex/raphael-learning-absorption` as an LLM/control-layer upgrade for Raphael. The implementation includes the learning bridge, learning outcome evidence, read-only skill curator health, post-learning reload recommendations, release-slice classification, and merge-gate support fixes for clean-env config writes and browser-connect test determinism.

**Verification Evidence (2026-07-05):**
- `scripts/run_tests.sh --file-timeout 1200 tests/agent/test_raphael_control.py tests/agent/test_raphael_evolution.py tests/agent/test_raphael_status.py tests/agent/test_raphael_learning.py tests/tui_gateway/test_protocol.py tests/test_tui_gateway_server.py tests/cli/test_cli_save_config_value.py tests/scripts/test_raphael_release_slice_boundary.py` -> 464 passed.
- `/Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/hermes_cli/test_raphael_cmd.py tests/plugins/test_raphael_plugin.py tests/tui_gateway/test_protocol.py -q` -> 284 passed.
- `/Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/agent/test_curator.py -q` -> 66 passed.
- `/Users/simon/.hermes/hermes-agent/venv/bin/python -m ruff check ...` -> all checks passed.
- `rtk git diff --check` -> clean.
- `/Users/simon/.hermes/hermes-agent/venv/bin/python scripts/raphael_release_slice_boundary.py --from-git-status` -> 15 LLM slice paths, 0 deferred media paths, 0 unclassified paths, 0 violations.

---

## Absorbable Greedy King Skills

| Capability | Existing surface | Raphael absorption | Safety gate |
| --- | --- | --- | --- |
| Skill distillation | `/learn`, `agent.learn_prompt.build_learn_prompt` | Natural language such as "learn this workflow" becomes a real skill-authoring turn. | Require `skill_manage` evidence and report saved skill name. |
| Memory preferences | `/memory`, memory approval gate, background review | Save durable user preferences only when the user corrects behavior or asks to remember. | Prefer pending approval for public defaults; redact private paths and prompts. |
| Background skill review | `agent.background_review` | Trigger targeted post-turn review after Raphael proof failures, repeated corrections, or provider recovery lessons. | Tool whitelist: memory and skill tools only. |
| Curator | `hermes curator status/run/pin/restore`, `agent.curator` | Let Raphael summarize skill-library health and suggest dry-runs, pinning, or consolidation. | No automatic destructive archive/consolidation without explicit operator action. |
| Journey graph | `hermes journey`, `agent.learning_graph` | Let Raphael answer "what have you learned?" and point to editable learned nodes. | Edit/delete through journey mutation commands, not raw file edits. |
| Session recall | `sessions`, `session_search`-style memory surfaces | Retrieve prior workflows as evidence before creating or patching a skill. | Cite source sessions and avoid storing raw private artifacts. |
| Goal continuity | `/goal` | Attach learning tasks to active goals so improvement is not lost between turns. | Completion requires current evidence, not intent. |
| Queue and steer | `/queue`, `/steer` | Schedule non-interrupting follow-up learning or correction prompts after the current tool call. | Must not hide active user-facing work or override user steering. |
| Background execution | `/background`, `/agents` | Run longer learning distillation or audit tasks without blocking the main conversation. | Report task id, status, output artifact, and cancellation path. |
| Skills reload | `/reload-skills`, `skills.reload` | After a skill is created or installed, refresh the gateway process so Raphael can use it immediately. | Verify total skill count or added skill name. |
| Skills hub and bundles | `/skills`, `/bundles` | Install or group reusable capabilities when a workflow recurs. | Require user approval for installs and avoid upstream/private leakage. |
| Automation suggestions | `/suggestions`, `/blueprint`, `/cron` | Convert repeated Raphael workflows into suggested automations. | Suggest first; cron mutation stays explicit and gated. |
| Approval controls | `/approve`, `/deny`, memory/skills approval | Make risky learning and mutation steps auditable. | Never auto-approve dangerous commands, cron mutation, provider setup, or public delivery. |

## Task 1: Bridge Raphael Learn Decisions To `/learn`

**Files:**
- Modify: `agent/raphael/control.py`
- Create: `agent/raphael/learning.py`
- Test: `tests/agent/test_raphael_learning.py`

- [x] **Step 1: Write the failing bridge test**

```python
from agent.learn_prompt import build_learn_prompt
from agent.raphael.control import build_raphael_control_decision
from agent.raphael.learning import build_raphael_learning_dispatch


def test_raphael_learning_dispatch_uses_shared_learn_prompt():
    request = "拉斐爾，把剛剛 Hermes upgrade 的排查流程學起來，整理成可重用 skill"
    decision = build_raphael_control_decision(request)

    dispatch = build_raphael_learning_dispatch(decision, request)

    assert dispatch["type"] == "send"
    assert dispatch["message"] == build_learn_prompt(request)
    assert dispatch["required_proofs"] == [
        "learn_request_preserved",
        "skill_authoring_standards_applied",
        "skill_manage_write_evidence",
    ]
```

- [x] **Step 2: Run the failing test**

Run:

```bash
/Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/agent/test_raphael_learning.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agent.raphael.learning'`.

- [x] **Step 3: Add the minimal bridge**

Create `agent/raphael/learning.py`:

```python
"""Raphael learning dispatch helpers."""

from __future__ import annotations

from typing import Any, Mapping

from agent.learn_prompt import build_learn_prompt


def build_raphael_learning_dispatch(decision: Any, user_request: str) -> Mapping[str, object]:
    if getattr(decision, "mode", "") != "learn_skill":
        raise ValueError("Raphael learning dispatch requires mode='learn_skill'")
    required = list(getattr(getattr(decision, "evidence", None), "required_proofs", ()) or ())
    return {
        "type": "send",
        "message": build_learn_prompt(user_request),
        "required_proofs": required,
    }
```

- [x] **Step 4: Run the bridge test**

Run:

```bash
/Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/agent/test_raphael_control.py::test_control_routes_explicit_learning_requests_to_learn_skill_handoff tests/agent/test_raphael_learning.py -q
```

Expected: PASS.

- [x] **Step 5: Package in final feature commit**

```bash
rtk git add agent/raphael/learning.py tests/agent/test_raphael_learning.py
rtk git commit -m "feat: bridge raphael learning requests to learn prompt"
```

## Task 2: Add Learning Outcome Evidence

**Files:**
- Modify: `agent/raphael/evolution.py`
- Modify: `hermes_cli/raphael_cmd.py`
- Test: `tests/agent/test_raphael_evolution.py`
- Test: `tests/hermes_cli/test_raphael_cmd.py`

- [x] **Step 1: Write the failing evidence test**

```python
from agent.raphael.evolution import summarize_learning_outcome


def test_learning_outcome_summary_requires_artifact_and_rollback():
    summary = summarize_learning_outcome(
        {
            "skill_name": "hermes-upgrade-operations",
            "source": "current conversation",
            "saved": True,
            "rollback": "archive the skill with hermes curator restore or delete the pending proposal",
        }
    )

    assert "hermes-upgrade-operations" in summary
    assert "current conversation" in summary
    assert "rollback" in summary.lower()
```

- [x] **Step 2: Run the failing test**

Run:

```bash
/Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/agent/test_raphael_evolution.py::test_learning_outcome_summary_requires_artifact_and_rollback -q
```

Expected: FAIL with missing `summarize_learning_outcome`.

- [x] **Step 3: Implement the summary helper**

Add a pure helper near the other Raphael evolution formatters:

```python
def summarize_learning_outcome(record: Mapping[str, Any]) -> str:
    skill_name = _text(record.get("skill_name")) or "unknown-skill"
    source = _text(record.get("source")) or "unspecified source"
    rollback = _text(record.get("rollback")) or "remove or archive the saved learning artifact"
    status = "saved" if record.get("saved") is True else "not saved"
    return (
        f"Learning outcome: {status}; skill={skill_name}; "
        f"source={source}; rollback={rollback}"
    )
```

- [x] **Step 4: Surface the outcome in Raphael status text**

Add a compact status line in the Raphael CLI/status path when a learning outcome record is present:

```python
lines.append(f"Learning outcome: {learning_outcome_summary}")
```

- [x] **Step 5: Run focused tests**

Run:

```bash
/Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/agent/test_raphael_evolution.py tests/hermes_cli/test_raphael_cmd.py -q
```

Expected: PASS.

## Task 3: Make Raphael Skill Health Greedy But Safe

**Files:**
- Modify: `hermes_cli/raphael_cmd.py`
- Modify: `agent/raphael/status.py`
- Test: `tests/hermes_cli/test_raphael_cmd.py`
- Test: `tests/agent/test_raphael_status.py`

- [x] **Step 1: Write the failing status test**

```python
def test_raphael_status_includes_curator_health_without_mutation():
    output = render_raphael_status_card(
        {
            "curator": {
                "enabled": True,
                "consolidate": False,
                "agent_created_skills": 9,
                "stale": 0,
            }
        }
    )

    assert "curator: enabled" in output.lower()
    assert "agent-created skills: 9" in output
    assert "consolidation: off" in output.lower()
    assert "run --dry-run" in output
```

- [x] **Step 2: Run the failing test**

Run:

```bash
/Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/agent/test_raphael_status.py::test_raphael_status_includes_curator_health_without_mutation -q
```

Expected: FAIL until the status renderer includes curator health.

- [x] **Step 3: Add read-only curator health collection**

Call the existing curator status/read-only helpers. Do not call `run_curator_review`, archive, consolidate, or restore from Raphael status.

- [x] **Step 4: Run status and curator tests**

Run:

```bash
/Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/agent/test_raphael_status.py tests/agent/test_curator.py -q
```

Expected: PASS.

## Task 4: Add Learning Recall And Reload Hooks

**Files:**
- Modify: `agent/raphael/learning.py`
- Modify: `tui_gateway/server.py`
- Test: `tests/agent/test_raphael_learning.py`
- Test: `tests/tui_gateway/test_protocol.py`

- [x] **Step 1: Write the failing reload recommendation test**

```python
from agent.raphael.learning import recommend_post_learning_actions


def test_post_learning_actions_reload_skills_after_skill_create():
    actions = recommend_post_learning_actions({"skill_name": "hermes-upgrade-operations"})

    assert actions == [
        {
            "command": "skills.reload",
            "reason": "new skill should be visible in the gateway process",
        }
    ]
```

- [x] **Step 2: Run the failing test**

Run:

```bash
/Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/agent/test_raphael_learning.py::test_post_learning_actions_reload_skills_after_skill_create -q
```

Expected: FAIL until `recommend_post_learning_actions` exists.

- [x] **Step 3: Implement the recommendation helper**

```python
def recommend_post_learning_actions(record: Mapping[str, object]) -> list[dict[str, str]]:
    if str(record.get("skill_name") or "").strip():
        return [
            {
                "command": "skills.reload",
                "reason": "new skill should be visible in the gateway process",
            }
        ]
    return []
```

- [x] **Step 4: Verify gateway reload still works**

Run:

```bash
/Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/tui_gateway/test_protocol.py::test_command_dispatch_learn_sends_built_prompt tests/test_tui_gateway_server.py::test_skills_reload_runs_in_gateway_process -q
```

Expected: PASS.

## Task 5: Release Gate And Review

**Files:**
- Modify: `scripts/raphael_release_slice_boundary.py`
- Modify: `tests/scripts/test_raphael_release_slice_boundary.py`
- Test: existing Raphael release slice tests

- [x] **Step 1: Add the new learning paths to the Raphael LLM slice**

Update the boundary allowlist for:

```text
agent/raphael/learning.py
tests/agent/test_raphael_learning.py
docs/plans/2026-07-05-raphael-learning-absorption-plan.md
```

- [x] **Step 2: Run focused release checks**

Run:

```bash
/Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/scripts/test_raphael_release_slice_boundary.py tests/scripts/test_raphael_release_slice_manifest.py -q
```

Expected: PASS.

- [x] **Step 3: Run the merge gate slice**

Run:

```bash
scripts/run_tests.sh --file-timeout 1200 tests/agent/test_raphael_control.py tests/agent/test_raphael_evolution.py tests/agent/test_raphael_status.py tests/agent/test_raphael_learning.py tests/tui_gateway/test_protocol.py tests/test_tui_gateway_server.py tests/cli/test_cli_save_config_value.py tests/scripts/test_raphael_release_slice_boundary.py
```

Expected: 464 selected tests pass before MR.

## Non-Goals

- Do not make Raphael auto-install skills from the hub.
- Do not turn curator consolidation on automatically.
- Do not make cron mutations automatic.
- Do not store raw prompts, private paths, media artifacts, provider responses, or API outputs in durable skills.
- Do not claim full Sage King or full media readiness from learning improvements alone.

## Review Checklist

- [x] Explicit learning requests route to the shared `/learn` prompt builder.
- [x] Raphael can report learning outcomes with source and rollback path.
- [x] Curator health is visible but read-only by default.
- [x] Newly created skills can be reloaded into the gateway process.
- [x] Memory and skill writes remain auditable and reversible.
- [x] Release slice boundary treats learning absorption as LLM/control-layer work, not media readiness.
