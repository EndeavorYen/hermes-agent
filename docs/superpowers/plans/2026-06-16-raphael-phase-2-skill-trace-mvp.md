# Raphael Phase 2 Skill Trace MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-first Skill Trace MVP that lets Raphael summarize skill usage, record explicit skill/tool/outcome traces under Raphael state, redact trace payloads, and expose a read-only `/raphael-skills` command.

**Architecture:** Phase 2 remains plugin-first and profile-scoped. It reads Hermes skill telemetry from `~/.hermes/skills/.usage.json` through `tools.skill_usage.load_usage()`, stores only Raphael-owned trace JSONL under `get_hermes_home() / "raphael"`, and renders a read-only summary command. It does not create, patch, delete, rank-up, or evolve skills.

**Tech Stack:** Hermes Agent Python codebase, bundled Raphael plugin, `tools.skill_usage`, profile-scoped JSONL state, pytest, Markdown slash-command output.

---

## Execution Evidence

Status: implemented on `live/hermes-v2026.6.5` as Phase 2 only. No Phase 1 status behavior was mixed into the Skill Trace work.

Commits:

- `8d18ae4e6 feat: add Raphael skill trace config defaults`
- `789f1ebe4 feat: add Raphael skill trace models`
- `2705eeb1b feat: redact Raphael skill trace payloads`
- `cf095c5ae feat: summarize Raphael skill traces`
- `373b54afe feat: render Raphael skill trace summary`
- `13d055b5a feat: add Raphael skills command`

Fresh verification run after implementation:

```text
rtk ./venv/bin/python -m pytest tests/hermes_cli/test_raphael_config.py tests/agent/test_raphael_skill_trace_models.py tests/agent/test_raphael_redaction.py tests/agent/test_raphael_skill_trace.py tests/agent/test_raphael_skill_summary.py tests/plugins/test_raphael_plugin.py -q
30 passed, 1 warning in 0.64s

rtk ./venv/bin/python -m pytest tests/tools/test_skill_usage.py tests/agent/test_skill_commands.py tests/hermes_cli/test_plugins.py tests/test_transform_tool_result_hook.py -q
168 passed, 1 warning in 9.72s

rtk rg -n "skill_manage|skill_patch|skill_delete|create_skill_proposal|evolution|cronjob|memory_add|memory_tool|send_public|post_message|install_tool|approve|write_approval|tool_forge" agent/raphael plugins/raphael tests/agent/test_raphael_*.py tests/plugins/test_raphael_plugin.py
Only existing Phase 1 risk-classifier constants/tests matched.

rtk ./venv/bin/python -c <isolated /raphael-skills smoke>
Raphael Skill Trace
['config.yaml']

rtk git diff --check
No output
```

Read-only scaffold smoke used `/private/tmp/hermes-raphael-phase2-smoke` and confirmed invoking `/raphael-skills` in an otherwise clean `HERMES_HOME` left only `config.yaml`.

## Scope Locks

Build only Skill Trace MVP:

- Add `skill_trace` defaults under `DEFAULT_CONFIG["raphael"]`.
- Add pure `SkillTrace` and `SkillTraceSummary` data contracts.
- Add redaction helpers for trace metadata and user corrections.
- Add trace JSONL writer/reader under `get_hermes_home() / "raphael"`.
- Add `.usage.json` read integration through `tools.skill_usage.load_usage()`.
- Add `/raphael-skills` read-only summary command.
- Add tests for model validation, redaction, trace writes, usage summary, command disabled/enabled behavior, and no runtime scaffold mutation.

Explicit exclusions:

- No skill create, patch, delete, bundle mutation, or `skill_manage` calls.
- No evolution proposal generation.
- No `/raphael-evolutions`, `/raphael-explain`, or `/raphael-reject`.
- No cron mutation.
- No memory writes.
- No public Slack posting.
- No tool forge.
- No automatic install or enable flow.
- No RPG rank, XP, or skill tree.
- No new core hook unless a test proves the plugin API cannot support the read-only command.

## File Map

Create:

- `agent/raphael/redaction.py` - deterministic recursive redaction for trace payloads.
- `agent/raphael/skill_trace.py` - trace JSONL helpers and `.usage.json` summary integration.
- `tests/agent/test_raphael_skill_trace_models.py` - trace model serialization and validation tests.
- `tests/agent/test_raphael_redaction.py` - trace redaction tests.
- `tests/agent/test_raphael_skill_trace.py` - trace store and skill usage summary tests.

Modify:

- `hermes_cli/config.py` - add `raphael.skill_trace` defaults.
- `tests/hermes_cli/test_raphael_config.py` - cover new defaults and deep merge.
- `agent/raphael/models.py` - add `SKILL_TRACE_SCHEMA_VERSION`, `SkillTrace`, and `SkillTraceSummary`.
- `agent/raphael/state.py` - add `get_raphael_skill_traces_path()`.
- `agent/raphael/__init__.py` - export trace model names alongside Phase 1 primitives.
- `plugins/raphael/__init__.py` - register `/raphael-skills` and implement a read-only handler.
- `tests/plugins/test_raphael_plugin.py` - cover `/raphael-skills` command behavior and no-scaffold smoke.

Do not modify existing image/image2 dirty files.

## Data Contracts

### Config

Extend the existing `DEFAULT_CONFIG["raphael"]` block:

```python
"skill_trace": {
    "enabled": True,
    "max_summary_rows": 20,
    "max_trace_events": 500,
},
```

`raphael.enabled` and `plugins.enabled` still gate command availability. `raphael.skill_trace.enabled` gates `/raphael-skills` content after the plugin is loaded.

### Skill Trace JSONL

Store explicit Raphael traces here:

```text
get_hermes_home() / "raphael" / "skill_traces.jsonl"
```

Trace line shape:

```json
{
  "schema_version": "raphael.skill_trace.v1",
  "trace_id": "trace_001",
  "task_id": "task_001",
  "created_at": "2026-06-16T00:00:00+00:00",
  "source": "manual",
  "skills_used": ["superpowers:writing-plans"],
  "tools_used": ["exec_command"],
  "outcome": "success",
  "user_corrections": [],
  "risk_incidents": [],
  "metadata": {"phase": "phase-2"}
}
```

Phase 2 trace records may store observed outcomes, but they must not store an evolution proposal field. Phase 3 owns evolution proposal generation.

### Skill Summary

`/raphael-skills` should render:

- top skills by `use_count`;
- recent activity from `latest_activity_at(record)`;
- `view_count`, `patch_count`, lifecycle state, and `created_by` when available;
- outcome counts derived from Raphael `SkillTrace` JSONL;
- a clear line when no usage records or no traces exist.

## Task 1: Config Defaults For Skill Trace

**Files:**
- Modify: `hermes_cli/config.py`
- Modify: `tests/hermes_cli/test_raphael_config.py`

- [ ] **Step 1: Write failing config tests**

Add this to `tests/hermes_cli/test_raphael_config.py`:

```python
def test_raphael_skill_trace_defaults_enabled_and_bounded():
    skill_trace = DEFAULT_CONFIG["raphael"]["skill_trace"]

    assert skill_trace == {
        "enabled": True,
        "max_summary_rows": 20,
        "max_trace_events": 500,
    }


def test_load_config_deep_merges_raphael_skill_trace_defaults(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "raphael:\n"
        "  skill_trace:\n"
        "    max_summary_rows: 5\n",
        encoding="utf-8",
    )

    with patch.dict("os.environ", {"HERMES_HOME": str(tmp_path)}):
        config = load_config()

    assert config["raphael"]["skill_trace"]["enabled"] is True
    assert config["raphael"]["skill_trace"]["max_summary_rows"] == 5
    assert config["raphael"]["skill_trace"]["max_trace_events"] == 500
```

- [ ] **Step 2: Run RED**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/hermes_cli/test_raphael_config.py::test_raphael_skill_trace_defaults_enabled_and_bounded tests/hermes_cli/test_raphael_config.py::test_load_config_deep_merges_raphael_skill_trace_defaults -q
```

Expected:

```text
FAILED ... KeyError: 'skill_trace'
```

- [ ] **Step 3: Add config defaults**

In `hermes_cli/config.py`, extend the existing `DEFAULT_CONFIG["raphael"]` block:

```python
        "skill_trace": {
            "enabled": True,
            "max_summary_rows": 20,
            "max_trace_events": 500,
        },
```

- [ ] **Step 4: Run GREEN**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/hermes_cli/test_raphael_config.py -q
```

Expected:

```text
All selected tests pass
```

- [ ] **Step 5: Commit**

Run:

```bash
rtk git add hermes_cli/config.py tests/hermes_cli/test_raphael_config.py
rtk git commit -m "feat: add Raphael skill trace config defaults"
```

## Task 2: Skill Trace Data Models

**Files:**
- Modify: `agent/raphael/models.py`
- Modify: `agent/raphael/__init__.py`
- Create: `tests/agent/test_raphael_skill_trace_models.py`

- [ ] **Step 1: Write failing model tests**

Create `tests/agent/test_raphael_skill_trace_models.py`:

```python
from datetime import datetime, timezone

import pytest

from agent.raphael.models import (
    SKILL_TRACE_SCHEMA_VERSION,
    SkillTrace,
    SkillTraceSummary,
)


def _at(second: int) -> datetime:
    return datetime(2026, 6, 16, 0, 0, second, tzinfo=timezone.utc)


def test_skill_trace_round_trips_schema_and_tuples():
    trace = SkillTrace(
        trace_id="trace_001",
        task_id="task_001",
        created_at=_at(1),
        source="manual",
        skills_used=["superpowers:writing-plans"],
        tools_used=["exec_command"],
        outcome="success",
        user_corrections=["use Traditional Chinese"],
        risk_incidents=[],
        metadata={"phase": "phase-2"},
    )

    data = trace.to_dict()

    assert data["schema_version"] == SKILL_TRACE_SCHEMA_VERSION
    assert data["skills_used"] == ["superpowers:writing-plans"]
    assert SkillTrace.from_dict(data) == trace


def test_skill_trace_rejects_wrong_schema():
    payload = {
        "schema_version": "wrong",
        "trace_id": "trace_001",
        "task_id": "task_001",
        "created_at": _at(1).isoformat(),
        "source": "manual",
        "skills_used": [],
        "tools_used": [],
        "outcome": "success",
        "user_corrections": [],
        "risk_incidents": [],
        "metadata": {},
    }

    with pytest.raises(ValueError, match="Unsupported Raphael skill trace schema"):
        SkillTrace.from_dict(payload)


def test_skill_trace_summary_round_trips_usage_and_outcomes():
    summary = SkillTraceSummary(
        skill_name="superpowers:writing-plans",
        use_count=3,
        view_count=2,
        patch_count=1,
        latest_activity_at="2026-06-16T00:00:00+00:00",
        state="active",
        created_by="agent",
        outcome_counts={"success": 2, "failure": 1},
    )

    assert SkillTraceSummary.from_dict(summary.to_dict()) == summary
```

- [ ] **Step 2: Run RED**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_skill_trace_models.py -q
```

Expected:

```text
ImportError: cannot import name 'SkillTrace'
```

- [ ] **Step 3: Add model classes**

Add these definitions to `agent/raphael/models.py` after `EVENT_SCHEMA_VERSION`:

```python
SKILL_TRACE_SCHEMA_VERSION = "raphael.skill_trace.v1"
```

Add these dataclasses before `RaphaelState`:

```python
@dataclass(frozen=True)
class SkillTrace:
    trace_id: str
    task_id: str
    created_at: datetime
    source: str
    skills_used: tuple[str, ...]
    tools_used: tuple[str, ...]
    outcome: str
    user_corrections: tuple[str, ...] = ()
    risk_incidents: tuple[str, ...] = ()
    metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", _ensure_utc(self.created_at))
        object.__setattr__(self, "skills_used", tuple(self.skills_used))
        object.__setattr__(self, "tools_used", tuple(self.tools_used))
        object.__setattr__(self, "user_corrections", tuple(self.user_corrections))
        object.__setattr__(self, "risk_incidents", tuple(self.risk_incidents))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SKILL_TRACE_SCHEMA_VERSION,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "created_at": _datetime_to_iso(self.created_at),
            "source": self.source,
            "skills_used": list(self.skills_used),
            "tools_used": list(self.tools_used),
            "outcome": self.outcome,
            "user_corrections": list(self.user_corrections),
            "risk_incidents": list(self.risk_incidents),
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SkillTrace":
        _require_schema(payload, SKILL_TRACE_SCHEMA_VERSION, "skill trace")
        return cls(
            trace_id=str(payload["trace_id"]),
            task_id=str(payload["task_id"]),
            created_at=_datetime_from_iso(str(payload["created_at"])),
            source=str(payload.get("source", "unknown")),
            skills_used=tuple(str(item) for item in payload.get("skills_used", ())),
            tools_used=tuple(str(item) for item in payload.get("tools_used", ())),
            outcome=str(payload.get("outcome", "unknown")),
            user_corrections=tuple(
                str(item) for item in payload.get("user_corrections", ())
            ),
            risk_incidents=tuple(
                str(item) for item in payload.get("risk_incidents", ())
            ),
            metadata=payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {},
        )


@dataclass(frozen=True)
class SkillTraceSummary:
    skill_name: str
    use_count: int
    view_count: int
    patch_count: int
    latest_activity_at: str | None
    state: str
    created_by: str | None
    outcome_counts: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "use_count", int(self.use_count))
        object.__setattr__(self, "view_count", int(self.view_count))
        object.__setattr__(self, "patch_count", int(self.patch_count))
        object.__setattr__(self, "outcome_counts", dict(self.outcome_counts))

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "use_count": self.use_count,
            "view_count": self.view_count,
            "patch_count": self.patch_count,
            "latest_activity_at": self.latest_activity_at,
            "state": self.state,
            "created_by": self.created_by,
            "outcome_counts": dict(self.outcome_counts),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SkillTraceSummary":
        outcome_counts = payload.get("outcome_counts", {})
        if not isinstance(outcome_counts, Mapping):
            outcome_counts = {}
        return cls(
            skill_name=str(payload["skill_name"]),
            use_count=int(payload.get("use_count") or 0),
            view_count=int(payload.get("view_count") or 0),
            patch_count=int(payload.get("patch_count") or 0),
            latest_activity_at=(
                str(payload["latest_activity_at"])
                if payload.get("latest_activity_at") is not None
                else None
            ),
            state=str(payload.get("state") or "active"),
            created_by=(
                str(payload["created_by"])
                if payload.get("created_by") is not None
                else None
            ),
            outcome_counts={
                str(key): int(value)
                for key, value in outcome_counts.items()
            },
        )
```

Update `__all__` to include:

```python
    "SKILL_TRACE_SCHEMA_VERSION",
    "SkillTrace",
    "SkillTraceSummary",
```

Update `agent/raphael/__init__.py` imports:

```python
from agent.raphael.models import (
    ActionProposal,
    RaphaelEvent,
    RaphaelState,
    RiskLevel,
    SKILL_TRACE_SCHEMA_VERSION,
    SkillTrace,
    SkillTraceSummary,
    StatusCard,
)
```

Update `agent/raphael/__init__.py` `__all__`:

```python
__all__ = [
    "ActionProposal",
    "RaphaelEvent",
    "RaphaelState",
    "RiskLevel",
    "SKILL_TRACE_SCHEMA_VERSION",
    "SkillTrace",
    "SkillTraceSummary",
    "StatusCard",
]
```

- [ ] **Step 4: Run GREEN**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_skill_trace_models.py tests/agent/test_raphael_models.py -q
```

Expected:

```text
All selected tests pass
```

- [ ] **Step 5: Commit**

Run:

```bash
rtk git add agent/raphael/models.py agent/raphael/__init__.py tests/agent/test_raphael_skill_trace_models.py
rtk git commit -m "feat: add Raphael skill trace models"
```

## Task 3: Trace Redaction

**Files:**
- Create: `agent/raphael/redaction.py`
- Create: `tests/agent/test_raphael_redaction.py`

- [ ] **Step 1: Write failing redaction tests**

Create `tests/agent/test_raphael_redaction.py`:

```python
from agent.raphael.redaction import redact_trace_payload


def test_redacts_secret_like_keys_recursively():
    payload = {
        "api_key": "sk-secret",
        "nested": {
            "token": "tok-secret",
            "safe": "visible",
        },
    }

    assert redact_trace_payload(payload) == {
        "api_key": "[redacted]",
        "nested": {
            "token": "[redacted]",
            "safe": "visible",
        },
    }


def test_redacts_long_strings_without_changing_short_values():
    payload = {
        "short": "ok",
        "long": "x" * 300,
    }

    redacted = redact_trace_payload(payload, max_string_length=32)

    assert redacted["short"] == "ok"
    assert redacted["long"].startswith("x" * 32)
    assert redacted["long"].endswith("[truncated]")


def test_lists_are_redacted_recursively():
    payload = {"items": [{"password": "secret"}, "plain"]}

    assert redact_trace_payload(payload)["items"] == [
        {"password": "[redacted]"},
        "plain",
    ]
```

- [ ] **Step 2: Run RED**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_redaction.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'agent.raphael.redaction'
```

- [ ] **Step 3: Add redaction helper**

Create `agent/raphael/redaction.py`:

```python
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "refresh_token",
    "secret",
    "token",
)


def _is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in _SECRET_KEY_PARTS)


def redact_trace_payload(
    payload: Any, *, max_string_length: int = 240
) -> Any:
    if isinstance(payload, Mapping):
        redacted: dict[str, Any] = {}
        for key, value in payload.items():
            str_key = str(key)
            if _is_secret_key(str_key):
                redacted[str_key] = "[redacted]"
            else:
                redacted[str_key] = redact_trace_payload(
                    value, max_string_length=max_string_length
                )
        return redacted
    if isinstance(payload, list):
        return [
            redact_trace_payload(item, max_string_length=max_string_length)
            for item in payload
        ]
    if isinstance(payload, tuple):
        return [
            redact_trace_payload(item, max_string_length=max_string_length)
            for item in payload
        ]
    if isinstance(payload, str) and len(payload) > max_string_length:
        return payload[:max_string_length] + "[truncated]"
    return payload
```

- [ ] **Step 4: Run GREEN**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_redaction.py -q
```

Expected:

```text
3 passed
```

- [ ] **Step 5: Commit**

Run:

```bash
rtk git add agent/raphael/redaction.py tests/agent/test_raphael_redaction.py
rtk git commit -m "feat: redact Raphael skill trace payloads"
```

## Task 4: Trace Store And Usage Summary

**Files:**
- Modify: `agent/raphael/state.py`
- Create: `agent/raphael/skill_trace.py`
- Create: `tests/agent/test_raphael_skill_trace.py`

- [ ] **Step 1: Write failing trace store tests**

Create `tests/agent/test_raphael_skill_trace.py`:

```python
import json
from datetime import datetime, timezone

from agent.raphael.models import SkillTrace
from agent.raphael.skill_trace import (
    append_skill_trace,
    read_skill_traces,
    summarize_skill_usage,
)
from agent.raphael.state import get_raphael_skill_traces_path


def _at(second: int) -> datetime:
    return datetime(2026, 6, 16, 0, 0, second, tzinfo=timezone.utc)


def _trace(trace_id: str, outcome: str = "success") -> SkillTrace:
    return SkillTrace(
        trace_id=trace_id,
        task_id="task_001",
        created_at=_at(1),
        source="manual",
        skills_used=("superpowers:writing-plans",),
        tools_used=("exec_command",),
        outcome=outcome,
        user_corrections=("keep it separate",),
        risk_incidents=(),
        metadata={"api_key": "secret", "phase": "phase-2"},
    )


def test_get_skill_traces_path_is_profile_scoped(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    assert get_raphael_skill_traces_path() == tmp_path / "raphael" / "skill_traces.jsonl"


def test_append_skill_trace_redacts_metadata_and_writes_jsonl(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    append_skill_trace(_trace("trace_001"))

    lines = get_raphael_skill_traces_path().read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["metadata"]["api_key"] == "[redacted]"
    traces = read_skill_traces()
    assert [trace.trace_id for trace in traces] == ["trace_001"]
    assert traces[0].metadata["api_key"] == "[redacted]"


def test_read_skill_traces_limit_returns_newest_records(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    append_skill_trace(_trace("trace_001", outcome="failure"))
    append_skill_trace(_trace("trace_002", outcome="success"))

    traces = read_skill_traces(limit=1)

    assert [trace.trace_id for trace in traces] == ["trace_002"]


def test_summarize_skill_usage_combines_usage_json_and_trace_outcomes(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    usage_dir = tmp_path / "skills"
    usage_dir.mkdir(parents=True)
    (usage_dir / ".usage.json").write_text(
        json.dumps(
            {
                "superpowers:writing-plans": {
                    "use_count": 4,
                    "view_count": 2,
                    "patch_count": 1,
                    "last_used_at": "2026-06-16T00:00:00+00:00",
                    "state": "active",
                    "created_by": "agent",
                }
            }
        ),
        encoding="utf-8",
    )
    append_skill_trace(_trace("trace_001", outcome="failure"))
    append_skill_trace(_trace("trace_002", outcome="success"))

    summaries = summarize_skill_usage(max_rows=5)

    assert len(summaries) == 1
    assert summaries[0].skill_name == "superpowers:writing-plans"
    assert summaries[0].use_count == 4
    assert summaries[0].outcome_counts == {"failure": 1, "success": 1}
```

- [ ] **Step 2: Run RED**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_skill_trace.py -q
```

Expected:

```text
ImportError: cannot import name 'get_raphael_skill_traces_path'
```

- [ ] **Step 3: Add state path helper**

In `agent/raphael/state.py`, add:

```python
def get_raphael_skill_traces_path() -> Path:
    return get_raphael_state_dir() / "skill_traces.jsonl"
```

Update `__all__`:

```python
    "get_raphael_skill_traces_path",
```

- [ ] **Step 4: Add trace store and summary module**

Create `agent/raphael/skill_trace.py`:

```python
from __future__ import annotations

import json
from collections import Counter
from typing import Iterable

from agent.raphael.models import SkillTrace, SkillTraceSummary
from agent.raphael.redaction import redact_trace_payload
from agent.raphael.state import get_raphael_skill_traces_path
from tools.skill_usage import latest_activity_at, load_usage


def append_skill_trace(trace: SkillTrace) -> None:
    path = get_raphael_skill_traces_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = trace.to_dict()
    payload["metadata"] = redact_trace_payload(payload.get("metadata", {}))
    payload["user_corrections"] = redact_trace_payload(
        payload.get("user_corrections", [])
    )
    with path.open("a", encoding="utf-8") as traces_file:
        traces_file.write(json.dumps(payload, sort_keys=True) + "\n")


def read_skill_traces(*, limit: int | None = None) -> list[SkillTrace]:
    path = get_raphael_skill_traces_path()
    if not path.exists():
        return []
    traces: list[SkillTrace] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            traces.append(SkillTrace.from_dict(json.loads(line)))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    if limit is None:
        return traces
    bounded_limit = max(0, int(limit))
    if bounded_limit == 0:
        return []
    return traces[-bounded_limit:]


def _outcome_counts_by_skill(traces: Iterable[SkillTrace]) -> dict[str, Counter]:
    counts: dict[str, Counter] = {}
    for trace in traces:
        for skill_name in trace.skills_used:
            counts.setdefault(skill_name, Counter())[trace.outcome] += 1
    return counts


def summarize_skill_usage(
    *, max_rows: int = 20, max_trace_events: int = 500
) -> list[SkillTraceSummary]:
    usage = load_usage()
    traces = read_skill_traces(limit=max_trace_events)
    outcome_counts = _outcome_counts_by_skill(traces)
    skill_names = set(usage) | set(outcome_counts)

    summaries: list[SkillTraceSummary] = []
    for skill_name in skill_names:
        record = usage.get(skill_name, {})
        outcomes = outcome_counts.get(skill_name, Counter())
        summaries.append(
            SkillTraceSummary(
                skill_name=skill_name,
                use_count=int(record.get("use_count") or 0),
                view_count=int(record.get("view_count") or 0),
                patch_count=int(record.get("patch_count") or 0),
                latest_activity_at=latest_activity_at(record),
                state=str(record.get("state") or "active"),
                created_by=(
                    str(record["created_by"])
                    if record.get("created_by") is not None
                    else None
                ),
                outcome_counts=dict(sorted(outcomes.items())),
            )
        )

    summaries.sort(
        key=lambda item: (
            item.use_count,
            item.view_count,
            item.patch_count,
            item.latest_activity_at or "",
            item.skill_name,
        ),
        reverse=True,
    )
    return summaries[: max(0, int(max_rows))]
```

- [ ] **Step 5: Run GREEN**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_skill_trace.py tests/agent/test_raphael_state.py -q
```

Expected:

```text
All selected tests pass
```

- [ ] **Step 6: Commit**

Run:

```bash
rtk git add agent/raphael/state.py agent/raphael/skill_trace.py tests/agent/test_raphael_skill_trace.py
rtk git commit -m "feat: store Raphael skill traces"
```

## Task 5: Read-Only Skill Summary Renderer

**Files:**
- Create: `tests/agent/test_raphael_skill_summary.py`
- Modify: `agent/raphael/skill_trace.py`

- [ ] **Step 1: Write failing renderer tests**

Create `tests/agent/test_raphael_skill_summary.py`:

```python
from agent.raphael.models import SkillTraceSummary
from agent.raphael.skill_trace import render_skill_summary


def test_render_skill_summary_empty_state():
    output = render_skill_summary([])

    assert "Raphael Skill Trace" in output
    assert "No skill usage records found." in output
    assert "does not propose or modify skills" in output


def test_render_skill_summary_includes_usage_and_failures():
    output = render_skill_summary(
        [
            SkillTraceSummary(
                skill_name="superpowers:writing-plans",
                use_count=4,
                view_count=2,
                patch_count=1,
                latest_activity_at="2026-06-16T00:00:00+00:00",
                state="active",
                created_by="agent",
                outcome_counts={"failure": 1, "success": 3},
            )
        ]
    )

    assert "- superpowers:writing-plans" in output
    assert "use=4 view=2 patch=1" in output
    assert "outcomes: failure=1, success=3" in output
```

- [ ] **Step 2: Run RED**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_skill_summary.py -q
```

Expected:

```text
ImportError: cannot import name 'render_skill_summary'
```

- [ ] **Step 3: Add renderer**

Add to `agent/raphael/skill_trace.py`:

```python
def _format_outcomes(outcome_counts: dict[str, int]) -> str:
    if not outcome_counts:
        return "outcomes: none recorded"
    return "outcomes: " + ", ".join(
        f"{name}={count}" for name, count in sorted(outcome_counts.items())
    )


def render_skill_summary(summaries: list[SkillTraceSummary]) -> str:
    lines = [
        "Raphael Skill Trace",
        "Mode: read-only Skill Trace MVP.",
        "",
        "Skill Usage:",
    ]
    if not summaries:
        lines.append("No skill usage records found.")
    else:
        for summary in summaries:
            latest = summary.latest_activity_at or "no activity timestamp"
            created_by = summary.created_by or "unknown"
            lines.append(
                f"- {summary.skill_name} "
                f"(use={summary.use_count} view={summary.view_count} "
                f"patch={summary.patch_count}; state={summary.state}; "
                f"created_by={created_by}; latest={latest}; "
                f"{_format_outcomes(dict(summary.outcome_counts))})"
            )
    lines.extend(
        [
            "",
            "Read-only safety: Raphael Skill Trace reads skill usage and "
            "Raphael traces only; it does not propose or modify skills.",
        ]
    )
    return "\n".join(lines)
```

- [ ] **Step 4: Run GREEN**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_skill_summary.py tests/agent/test_raphael_skill_trace.py -q
```

Expected:

```text
All selected tests pass
```

- [ ] **Step 5: Commit**

Run:

```bash
rtk git add agent/raphael/skill_trace.py tests/agent/test_raphael_skill_summary.py
rtk git commit -m "feat: render Raphael skill usage summary"
```

## Task 6: `/raphael-skills` Plugin Command

**Files:**
- Modify: `plugins/raphael/__init__.py`
- Modify: `tests/plugins/test_raphael_plugin.py`

- [ ] **Step 1: Write failing plugin tests**

Add to `tests/plugins/test_raphael_plugin.py`:

```python
def test_enabled_plugin_registers_raphael_skills_command(monkeypatch, tmp_path):
    import hermes_cli.plugins as plugins_mod

    hermes_home = tmp_path / "hermes_home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    _write_config(
        hermes_home,
        {
            "plugins": {"enabled": ["raphael"]},
            "raphael": {"enabled": True},
        },
    )

    plugins_mod._plugin_manager = plugins_mod.PluginManager()
    plugins_mod.discover_plugins()

    handler = plugins_mod.get_plugin_command_handler("raphael-skills")
    assert handler is not None
    assert "Raphael Skill Trace" in handler("")


def test_raphael_skills_disabled_when_raphael_disabled(monkeypatch, tmp_path):
    import hermes_cli.plugins as plugins_mod

    hermes_home = tmp_path / "hermes_home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    _write_config(
        hermes_home,
        {
            "plugins": {"enabled": ["raphael"]},
            "raphael": {"enabled": False},
        },
    )

    plugins_mod._plugin_manager = plugins_mod.PluginManager()
    plugins_mod.discover_plugins()
    handler = plugins_mod.get_plugin_command_handler("raphael-skills")

    assert handler is not None
    assert "Raphael Advisor is disabled" in handler("")


def test_raphael_skills_rejects_args(monkeypatch, tmp_path):
    plugin = _load_plugin_init()
    monkeypatch.setattr(plugin, "_raphael_enabled", lambda: True)

    assert plugin.handle_skills("extra") == "Usage: /raphael-skills"


def test_raphael_skills_does_not_initialize_runtime_scaffold(
    monkeypatch, tmp_path
):
    import hermes_cli.plugins as plugins_mod

    hermes_home = tmp_path / "hermes_home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    _write_config(
        hermes_home,
        {
            "plugins": {"enabled": ["raphael"]},
            "raphael": {"enabled": True},
        },
    )

    plugins_mod._plugin_manager = plugins_mod.PluginManager()
    plugins_mod.discover_plugins()
    handler = plugins_mod.get_plugin_command_handler("raphael-skills")

    assert handler is not None
    assert "Raphael Skill Trace" in handler("")
    assert sorted(path.name for path in hermes_home.iterdir()) == ["config.yaml"]
```

- [ ] **Step 2: Run RED**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/plugins/test_raphael_plugin.py::test_enabled_plugin_registers_raphael_skills_command tests/plugins/test_raphael_plugin.py::test_raphael_skills_disabled_when_raphael_disabled tests/plugins/test_raphael_plugin.py::test_raphael_skills_rejects_args tests/plugins/test_raphael_plugin.py::test_raphael_skills_does_not_initialize_runtime_scaffold -q
```

Expected:

```text
FAILED ... assert None is not None
```

- [ ] **Step 3: Add command handler**

Modify `plugins/raphael/__init__.py`:

```python
from agent.raphael.skill_trace import render_skill_summary, summarize_skill_usage
```

Add helpers:

```python
def _skill_trace_config() -> dict:
    config = cfg_get(_read_config(), "raphael", "skill_trace", default={})
    return config if isinstance(config, dict) else {}


def _skill_trace_enabled() -> bool:
    return cfg_get(_skill_trace_config(), "enabled", default=True) is not False


def _max_skill_summary_rows() -> int:
    raw_value = cfg_get(_skill_trace_config(), "max_summary_rows", default=20)
    if isinstance(raw_value, bool):
        return 20
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return 20
    return max(1, value)


def _max_trace_events() -> int:
    raw_value = cfg_get(_skill_trace_config(), "max_trace_events", default=500)
    if isinstance(raw_value, bool):
        return 500
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return 500
    return max(0, value)
```

Add handler:

```python
def handle_skills(raw_args: str) -> str:
    if raw_args.strip():
        return "Usage: /raphael-skills"
    if not _raphael_enabled():
        return _DISABLED_MESSAGE
    if not _skill_trace_enabled():
        return "Raphael Skill Trace is disabled. Set raphael.skill_trace.enabled: true."
    summaries = summarize_skill_usage(
        max_rows=_max_skill_summary_rows(),
        max_trace_events=_max_trace_events(),
    )
    return render_skill_summary(summaries)
```

Update `register(ctx)`:

```python
    ctx.register_command(
        "raphael-skills",
        handle_skills,
        description="Show read-only Raphael skill usage trace summary",
        args_hint="",
    )
```

- [ ] **Step 4: Run GREEN**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/plugins/test_raphael_plugin.py -q
```

Expected:

```text
All selected tests pass
```

- [ ] **Step 5: Commit**

Run:

```bash
rtk git add plugins/raphael/__init__.py tests/plugins/test_raphael_plugin.py
rtk git commit -m "feat: add Raphael skills summary command"
```

## Task 7: Integration Verification And Safety Gates

**Files:**
- Read: all Phase 2 files.
- Runtime-only: temporary `HERMES_HOME` under `/private/tmp`.

- [ ] **Step 1: Run focused Phase 2 suite**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/hermes_cli/test_raphael_config.py tests/agent/test_raphael_skill_trace_models.py tests/agent/test_raphael_redaction.py tests/agent/test_raphael_skill_trace.py tests/agent/test_raphael_skill_summary.py tests/plugins/test_raphael_plugin.py -q
```

Expected:

```text
All selected tests pass
```

- [ ] **Step 2: Run adjacent skill telemetry and plugin suites**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/tools/test_skill_usage.py tests/agent/test_skill_commands.py tests/hermes_cli/test_plugins.py tests/test_transform_tool_result_hook.py -q
```

Expected:

```text
All selected tests pass
```

- [ ] **Step 3: Scan for forbidden Phase 2 behavior**

Run:

```bash
rtk rg -n "skill_manage|skill_patch|skill_delete|create_skill_proposal|evolution|cronjob|memory_add|memory_tool|send_public|post_message|install_tool|approve|write_approval|tool_forge" agent/raphael plugins/raphael tests/agent/test_raphael_*.py tests/plugins/test_raphael_plugin.py
```

Expected:

```text
Only Phase 1 risk-classifier constants/tests and scope-lock documentation may mention forbidden action names. Plugin runtime code must not call mutation tools, memory APIs, cron APIs, public messaging APIs, approval APIs, or tool install APIs.
```

- [ ] **Step 4: Run isolated `/raphael-skills` smoke**

Create `/private/tmp/hermes-raphael-phase2-smoke/config.yaml`:

```yaml
plugins:
  enabled:
    - raphael
raphael:
  enabled: true
```

Run:

```bash
rtk env HERMES_HOME=/private/tmp/hermes-raphael-phase2-smoke ./venv/bin/python -c "import hermes_cli.plugins as p; p._plugin_manager=p.PluginManager(); p.discover_plugins(); h=p.get_plugin_command_handler('raphael-skills'); print(h(''))"
rtk rg --files /private/tmp/hermes-raphael-phase2-smoke
```

Expected output contains:

```text
Raphael Skill Trace
Read-only safety
```

Expected file listing:

```text
/private/tmp/hermes-raphael-phase2-smoke/config.yaml
```

The command must not create `SOUL.md`, `memories/`, `cron/`, `skills/`, or `raphael/` when no trace write happens.

- [ ] **Step 5: Check whitespace**

Run:

```bash
rtk git diff --check
```

Expected:

```text
No output
```

- [ ] **Step 6: Commit verification adjustments if needed**

If verification required small test or doc fixes, commit them:

```bash
rtk git add agent/raphael plugins/raphael tests/hermes_cli/test_raphael_config.py tests/agent/test_raphael_*.py tests/plugins/test_raphael_plugin.py hermes_cli/config.py
rtk git commit -m "test: verify Raphael skill trace MVP integration"
```

If no fixes were needed after Task 6, skip this commit.

## Self-Review Checklist

- [ ] Phase 2 remains separate from Phase 1.
- [ ] `raphael.skill_trace` defaults are explicit and disabled only through config.
- [ ] `/raphael-skills` is read-only.
- [ ] `/raphael-skills` does not write trace state, memory, skills, cron, Slack, approvals, or tool installs.
- [ ] Trace writer writes only to `get_hermes_home() / "raphael" / "skill_traces.jsonl"`.
- [ ] `.usage.json` integration uses `tools.skill_usage.load_usage()` and does not call usage mutators.
- [ ] Redaction runs before JSONL persistence.
- [ ] Summary can show failure outcomes when trace records contain failures.
- [ ] No evolution proposal, skill patch proposal, or tool forge behavior exists in this phase.
- [ ] Final smoke proves read-only command discovery does not initialize runtime scaffold.
- [ ] Existing image/image2 dirty files stay untouched and unstaged.

Run this red-flag scan before execution:

```bash
rtk rg -n "T[B]D|TO[D]O|FIX[M]E|p[l]aceholders?|implement l[a]ter|fill in d[e]tails|Similar to T[a]sk|\\?\\?" docs/superpowers/plans/2026-06-16-raphael-phase-2-skill-trace-mvp.md
```

Expected:

```text
No output
```

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-16-raphael-phase-2-skill-trace-mvp.md`. Two execution options:

**1. Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, run spec review and code quality review between tasks, and keep commits small.

**2. Inline Execution** - Execute tasks in this session using `superpowers:executing-plans`, with checkpoints after each commit.

Choose one execution mode before starting Task 1.
