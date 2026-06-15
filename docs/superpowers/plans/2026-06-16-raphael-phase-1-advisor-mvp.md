# Raphael Phase 1 Advisor MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first read-only Raphael Advisor MVP as an opt-in Hermes plugin with profile-scoped state, risk classification, status-card rendering, and a `/raphael-status` command.

**Architecture:** Raphael Phase 1 stays plugin-first and disabled by default. Core changes are limited to generic config defaults and cross-profile file-safety coverage for the new `raphael/` state directory; all Raphael behavior lives in focused `agent/raphael/` modules and `plugins/raphael/`. The MVP can read and render its own state, classify proposed actions, and write Raphael audit/state files only through explicit helper APIs; it cannot mutate skills, memory, cron jobs, tools, approvals, or public Slack delivery.

**Tech Stack:** Hermes Agent Python codebase, bundled plugin system, `hermes_cli.config.DEFAULT_CONFIG`, `hermes_constants.get_hermes_home()`, pytest, JSON/JSONL runtime state, Markdown command output.

---

## Scope Locks

Build only the Advisor MVP:

- Add `raphael` config defaults with `enabled: false`.
- Add `raphael` to profile-scoped file-safety areas.
- Add pure Raphael models, risk classifier, status helpers, and state helpers.
- Add a bundled `raphael` plugin that registers `/raphael-status` only when the plugin is enabled through `plugins.enabled`.
- Keep `/raphael-status` read-only from the user's perspective: it may read Raphael state and render output, but it must not collect fresh live evidence, write memory, edit skills, edit cron, install tools, or send public messages.

Explicit exclusions:

- No staged skill evolution implementation.
- No skill create, patch, delete, or bundle mutation.
- No memory writes.
- No cron creation, cron edits, or scheduler calls.
- No public Slack posting by default.
- No `/raphael status` parser in Phase 1; use `/raphael-status`.
- No RPG ranks, XP, skill tree, tool forge, or self-evolution UI.
- No long-lived Raphael-specific fork behavior.

## File Map

Create:

- `agent/raphael/__init__.py` - package marker and public exports.
- `agent/raphael/models.py` - dataclasses/enums for risk, status cards, proposals, events, and state.
- `agent/raphael/risk.py` - pure action-risk classifier.
- `agent/raphael/state.py` - profile-aware `get_hermes_home() / "raphael"` state and event helpers.
- `agent/raphael/status.py` - status-card freshness and command rendering helpers.
- `plugins/raphael/plugin.yaml` - bundled plugin manifest.
- `plugins/raphael/__init__.py` - plugin registration and `/raphael-status` handler.
- `tests/hermes_cli/test_raphael_config.py` - config default and deep-merge tests.
- `tests/agent/test_raphael_models.py` - model serialization and validation tests.
- `tests/agent/test_raphael_risk.py` - risk classifier tests.
- `tests/agent/test_raphael_state.py` - state path, atomic write, and event append tests.
- `tests/agent/test_raphael_status.py` - freshness and rendering tests.
- `tests/plugins/test_raphael_plugin.py` - plugin opt-in and command behavior tests.

Modify:

- `hermes_cli/config.py` - add `DEFAULT_CONFIG["raphael"]`.
- `agent/file_safety.py` - add `"raphael"` to `PROFILE_SCOPED_AREAS`.
- `tests/agent/test_file_safety_cross_profile.py` - include `raphael` in the profile-scoped area fixture and parametrized coverage.
- `tests/tools/test_cross_profile_guard.py` - add an end-to-end file-tool guard case for another profile's `raphael/` directory.

Do not touch current image/image2 worktree changes.

## Data Contracts

### Config

Add this exact default shape in `hermes_cli/config.py`:

```python
"raphael": {
    "enabled": False,
    "mode": "advisor",
    "status_card_ttl_seconds": 900,
    "max_status_cards": 20,
    "public_delivery_enabled": False,
    "skill_writes_enabled": False,
    "cron_mutation_enabled": False,
    "memory_writes_enabled": False,
    "tool_install_enabled": False,
},
```

Phase 1 code may read `raphael.enabled`, `status_card_ttl_seconds`, and `max_status_cards`. The mutation flags exist as explicit safety defaults and must remain false unless a future plan adds approval-gated behavior.

### Runtime State

Store Raphael state only under the active profile:

```text
get_hermes_home() / "raphael" / "state.json"
get_hermes_home() / "raphael" / "events.jsonl"
```

State JSON shape:

```json
{
  "schema_version": "raphael.state.v1",
  "status_cards": [],
  "action_proposals": [],
  "updated_at": "2026-06-16T00:00:00+00:00"
}
```

Event JSONL shape:

```json
{"schema_version":"raphael.event.v1","event_id":"evt_001","kind":"status_rendered","created_at":"2026-06-16T00:00:00+00:00","details":{"command":"raphael-status"}}
```

The `/raphael-status` command must not append an event in Phase 1. Event append helpers are for later explicit calls and direct tests only.

## Task 1: Config Defaults

**Files:**
- Create: `tests/hermes_cli/test_raphael_config.py`
- Modify: `hermes_cli/config.py`

- [ ] **Step 1: Write failing config tests**

Create `tests/hermes_cli/test_raphael_config.py`:

```python
from unittest.mock import patch

from hermes_cli.config import DEFAULT_CONFIG, load_config


def test_raphael_defaults_disabled_and_guarded():
    raphael = DEFAULT_CONFIG["raphael"]

    assert raphael["enabled"] is False
    assert raphael["mode"] == "advisor"
    assert raphael["status_card_ttl_seconds"] == 900
    assert raphael["max_status_cards"] == 20
    assert raphael["public_delivery_enabled"] is False
    assert raphael["skill_writes_enabled"] is False
    assert raphael["cron_mutation_enabled"] is False
    assert raphael["memory_writes_enabled"] is False
    assert raphael["tool_install_enabled"] is False


def test_load_config_deep_merges_raphael_defaults(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "raphael:\n"
        "  enabled: true\n",
        encoding="utf-8",
    )

    with patch.dict("os.environ", {"HERMES_HOME": str(tmp_path)}):
        config = load_config()

    assert config["raphael"]["enabled"] is True
    assert config["raphael"]["mode"] == "advisor"
    assert config["raphael"]["status_card_ttl_seconds"] == 900
    assert config["raphael"]["public_delivery_enabled"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/hermes_cli/test_raphael_config.py -q
```

Expected:

```text
FAIL test_raphael_defaults_disabled_and_guarded
KeyError: 'raphael'
```

- [ ] **Step 3: Add `DEFAULT_CONFIG["raphael"]`**

Modify `hermes_cli/config.py` near the other top-level default sections:

```python
    "raphael": {
        "enabled": False,
        "mode": "advisor",
        "status_card_ttl_seconds": 900,
        "max_status_cards": 20,
        "public_delivery_enabled": False,
        "skill_writes_enabled": False,
        "cron_mutation_enabled": False,
        "memory_writes_enabled": False,
        "tool_install_enabled": False,
    },
```

- [ ] **Step 4: Run config tests**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/hermes_cli/test_raphael_config.py tests/hermes_cli/test_config.py::TestLoadConfigDefaults::test_returns_defaults_when_no_file -q
```

Expected:

```text
3 passed
```

- [ ] **Step 5: Commit**

Run:

```bash
rtk git add hermes_cli/config.py tests/hermes_cli/test_raphael_config.py
rtk git commit -m "feat: add Raphael advisor config defaults"
```

## Task 2: Cross-Profile File Safety For `raphael/`

**Files:**
- Modify: `agent/file_safety.py`
- Modify: `tests/agent/test_file_safety_cross_profile.py`
- Modify: `tests/tools/test_cross_profile_guard.py`

- [ ] **Step 1: Write failing classifier coverage**

Modify the fake Hermes fixture in `tests/agent/test_file_safety_cross_profile.py` so each profile includes `raphael/`:

```python
    (root / "raphael").mkdir(parents=True)
    (root / "raphael" / "state.json").write_text("{}")

    (sec_home / "raphael").mkdir(parents=True)
    (sec_home / "raphael" / "state.json").write_text("{}")

    (coder_home / "raphael").mkdir(parents=True)
    (coder_home / "raphael" / "state.json").write_text("{}")
```

Update the existing parametrized test:

```python
    @pytest.mark.parametrize("area", ["skills", "plugins", "cron", "memories", "raphael"])
    def test_all_profile_scoped_areas_classified(self, fake_hermes, monkeypatch, area):
        _set_active_home(monkeypatch, fake_hermes["security_home"])
        from agent.file_safety import classify_cross_profile_target
        target = fake_hermes["default_home"] / area / "foo.txt"
        result = classify_cross_profile_target(str(target))
        assert result is not None
        assert result["area"] == area
```

- [ ] **Step 2: Write failing file-tool guard coverage**

Add this test in `tests/tools/test_cross_profile_guard.py` near the existing cross-profile write tests:

```python
def test_cross_profile_raphael_write_blocked_by_default(fake_hermes):
    from tools.file_tools import write_file

    target = fake_hermes["default_home"] / "raphael" / "state.json"
    result = write_file(str(target), '{"schema_version":"raphael.state.v1"}')

    assert result.get("error") is True
    assert "cross-profile" in result.get("message", "").lower()
    assert "raphael" in result.get("message", "")
    assert "cross_profile=True" in result.get("message", "")
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/agent/test_file_safety_cross_profile.py::TestClassifyCrossProfileTarget::test_all_profile_scoped_areas_classified tests/tools/test_cross_profile_guard.py::test_cross_profile_raphael_write_blocked_by_default -q
```

Expected:

```text
FAIL tests/agent/test_file_safety_cross_profile.py
AssertionError: assert None is not None
```

- [ ] **Step 4: Add `raphael` to scoped areas**

Modify `agent/file_safety.py`:

```python
PROFILE_SCOPED_AREAS = ("skills", "plugins", "cron", "memories", "raphael")
```

Update nearby comments and docstrings that enumerate scoped areas so they include `raphael`.

- [ ] **Step 5: Run file-safety tests**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/agent/test_file_safety_cross_profile.py tests/tools/test_cross_profile_guard.py -q
```

Expected:

```text
All selected tests pass
```

- [ ] **Step 6: Commit**

Run:

```bash
rtk git add agent/file_safety.py tests/agent/test_file_safety_cross_profile.py tests/tools/test_cross_profile_guard.py
rtk git commit -m "feat: guard Raphael state across profiles"
```

## Task 3: Raphael Models

**Files:**
- Create: `agent/raphael/__init__.py`
- Create: `agent/raphael/models.py`
- Create: `tests/agent/test_raphael_models.py`

- [ ] **Step 1: Write failing model tests**

Create `tests/agent/test_raphael_models.py`:

```python
from datetime import datetime, timezone

from agent.raphael.models import (
    ActionProposal,
    RaphaelState,
    RiskLevel,
    StatusCard,
)


def _now():
    return datetime(2026, 6, 16, 0, 0, tzinfo=timezone.utc)


def test_status_card_round_trips_to_dict():
    card = StatusCard(
        card_id="card_001",
        severity="warning",
        title="Gateway delivery may be degraded",
        summary="Slack socket errors were observed.",
        observed_at=_now(),
        expires_at=_now(),
        source="raphael-test",
        confidence=0.84,
        evidence_refs=["gateway.log:latest"],
    )

    data = card.to_dict()
    assert data == {
        "card_id": "card_001",
        "severity": "warning",
        "title": "Gateway delivery may be degraded",
        "summary": "Slack socket errors were observed.",
        "observed_at": "2026-06-16T00:00:00+00:00",
        "expires_at": "2026-06-16T00:00:00+00:00",
        "source": "raphael-test",
        "confidence": 0.84,
        "evidence_refs": ["gateway.log:latest"],
    }
    assert StatusCard.from_dict(data) == card


def test_action_proposal_requires_approval_from_risk():
    proposal = ActionProposal(
        proposal_id="act_001",
        action_type="skill_patch",
        risk=RiskLevel.R2,
        summary="Patch a skill after review",
        evidence_refs=["trace_001"],
        created_at=_now(),
    )

    assert proposal.requires_approval is True
    assert proposal.to_dict()["risk"] == "R2"


def test_state_round_trips_with_defaults():
    state = RaphaelState(
        status_cards=[],
        action_proposals=[],
        updated_at=_now(),
    )

    data = state.to_dict()
    assert data["schema_version"] == "raphael.state.v1"
    assert data["status_cards"] == []
    assert data["action_proposals"] == []
    assert RaphaelState.from_dict(data) == state
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_models.py -q
```

Expected:

```text
ERROR ModuleNotFoundError: No module named 'agent.raphael'
```

- [ ] **Step 3: Create package exports**

Create `agent/raphael/__init__.py`:

```python
"""Raphael advisor primitives.

Phase 1 keeps these helpers pure and profile-aware. Runtime integration lives
in the bundled raphael plugin.
"""

from .models import ActionProposal, RaphaelEvent, RaphaelState, RiskLevel, StatusCard

__all__ = [
    "ActionProposal",
    "RaphaelEvent",
    "RaphaelState",
    "RiskLevel",
    "StatusCard",
]
```

- [ ] **Step 4: Implement models**

Create `agent/raphael/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


STATE_SCHEMA_VERSION = "raphael.state.v1"
EVENT_SCHEMA_VERSION = "raphael.event.v1"


class RiskLevel(str, Enum):
    R0 = "R0"
    R1 = "R1"
    R1_5 = "R1.5"
    R2 = "R2"
    R3 = "R3"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _dt_to_str(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _dt_from_str(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class StatusCard:
    card_id: str
    severity: str
    title: str
    summary: str
    observed_at: datetime
    expires_at: datetime
    source: str
    confidence: float
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "severity": self.severity,
            "title": self.title,
            "summary": self.summary,
            "observed_at": _dt_to_str(self.observed_at),
            "expires_at": _dt_to_str(self.expires_at),
            "source": self.source,
            "confidence": self.confidence,
            "evidence_refs": list(self.evidence_refs),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StatusCard":
        return cls(
            card_id=str(data["card_id"]),
            severity=str(data["severity"]),
            title=str(data["title"]),
            summary=str(data["summary"]),
            observed_at=_dt_from_str(str(data["observed_at"])),
            expires_at=_dt_from_str(str(data["expires_at"])),
            source=str(data["source"]),
            confidence=float(data["confidence"]),
            evidence_refs=[str(v) for v in data.get("evidence_refs", [])],
        )


@dataclass(frozen=True)
class ActionProposal:
    proposal_id: str
    action_type: str
    risk: RiskLevel
    summary: str
    evidence_refs: list[str]
    created_at: datetime
    status: str = "pending"

    @property
    def requires_approval(self) -> bool:
        return self.risk in {RiskLevel.R2, RiskLevel.R3}

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "action_type": self.action_type,
            "risk": self.risk.value,
            "summary": self.summary,
            "evidence_refs": list(self.evidence_refs),
            "created_at": _dt_to_str(self.created_at),
            "status": self.status,
            "requires_approval": self.requires_approval,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActionProposal":
        return cls(
            proposal_id=str(data["proposal_id"]),
            action_type=str(data["action_type"]),
            risk=RiskLevel(str(data["risk"])),
            summary=str(data["summary"]),
            evidence_refs=[str(v) for v in data.get("evidence_refs", [])],
            created_at=_dt_from_str(str(data["created_at"])),
            status=str(data.get("status", "pending")),
        )


@dataclass(frozen=True)
class RaphaelEvent:
    event_id: str
    kind: str
    created_at: datetime
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": EVENT_SCHEMA_VERSION,
            "event_id": self.event_id,
            "kind": self.kind,
            "created_at": _dt_to_str(self.created_at),
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class RaphaelState:
    status_cards: list[StatusCard]
    action_proposals: list[ActionProposal]
    updated_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "status_cards": [card.to_dict() for card in self.status_cards],
            "action_proposals": [
                proposal.to_dict() for proposal in self.action_proposals
            ],
            "updated_at": _dt_to_str(self.updated_at),
        }

    @classmethod
    def empty(cls) -> "RaphaelState":
        return cls(status_cards=[], action_proposals=[], updated_at=utc_now())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RaphaelState":
        return cls(
            status_cards=[
                StatusCard.from_dict(card)
                for card in data.get("status_cards", [])
            ],
            action_proposals=[
                ActionProposal.from_dict(proposal)
                for proposal in data.get("action_proposals", [])
            ],
            updated_at=_dt_from_str(str(data["updated_at"])),
        )
```

- [ ] **Step 5: Run model tests**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_models.py -q
```

Expected:

```text
3 passed
```

- [ ] **Step 6: Commit**

Run:

```bash
rtk git add agent/raphael/__init__.py agent/raphael/models.py tests/agent/test_raphael_models.py
rtk git commit -m "feat: add Raphael advisor data models"
```

## Task 4: Risk Classifier

**Files:**
- Create: `agent/raphael/risk.py`
- Create: `tests/agent/test_raphael_risk.py`

- [ ] **Step 1: Write failing risk tests**

Create `tests/agent/test_raphael_risk.py`:

```python
import pytest

from agent.raphael.models import RiskLevel
from agent.raphael.risk import classify_action


@pytest.mark.parametrize("action_type", ["read_status", "list_observations"])
def test_read_only_actions_are_r0(action_type):
    assert classify_action(action_type) == RiskLevel.R0


@pytest.mark.parametrize("action_type", ["write_raphael_state", "append_audit_event"])
def test_raphael_local_state_actions_are_r1(action_type):
    assert classify_action(action_type) == RiskLevel.R1


@pytest.mark.parametrize("action_type", ["create_skill_proposal", "create_tool_spec"])
def test_design_only_evolution_actions_are_r1_5(action_type):
    assert classify_action(action_type) == RiskLevel.R1_5


@pytest.mark.parametrize(
    "action_type",
    ["skill_create", "skill_patch", "skill_delete", "write_file", "modify_cron", "send_public_message"],
)
def test_mutations_require_approval(action_type):
    assert classify_action(action_type) == RiskLevel.R2


@pytest.mark.parametrize(
    "action_type",
    ["bypass_approval", "permission_change", "expose_secret", "silent_tool_install", "self_replicating_cron"],
)
def test_forbidden_actions_are_r3(action_type):
    assert classify_action(action_type) == RiskLevel.R3


def test_unknown_actions_default_to_approval_required():
    assert classify_action("restart_gateway") == RiskLevel.R2
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_risk.py -q
```

Expected:

```text
ERROR ModuleNotFoundError: No module named 'agent.raphael.risk'
```

- [ ] **Step 3: Implement classifier**

Create `agent/raphael/risk.py`:

```python
from __future__ import annotations

from agent.raphael.models import RiskLevel


R0_ACTIONS = frozenset({
    "read_status",
    "list_observations",
})

R1_ACTIONS = frozenset({
    "write_raphael_state",
    "append_audit_event",
})

R1_5_ACTIONS = frozenset({
    "create_skill_proposal",
    "create_tool_spec",
})

R2_ACTIONS = frozenset({
    "skill_create",
    "skill_patch",
    "skill_delete",
    "skill_bundle_create",
    "tool_draft_write",
    "write_file",
    "modify_cron",
    "send_public_message",
    "install_tool",
})

R3_ACTIONS = frozenset({
    "bypass_approval",
    "permission_change",
    "expose_secret",
    "silent_tool_install",
    "self_replicating_cron",
})


def classify_action(action_type: str) -> RiskLevel:
    normalized = action_type.strip().lower().replace("-", "_")

    if normalized in R3_ACTIONS:
        return RiskLevel.R3
    if normalized in R2_ACTIONS:
        return RiskLevel.R2
    if normalized in R1_5_ACTIONS:
        return RiskLevel.R1_5
    if normalized in R1_ACTIONS:
        return RiskLevel.R1
    if normalized in R0_ACTIONS:
        return RiskLevel.R0

    return RiskLevel.R2
```

- [ ] **Step 4: Run risk tests**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_risk.py -q
```

Expected:

```text
All selected tests pass
```

- [ ] **Step 5: Commit**

Run:

```bash
rtk git add agent/raphael/risk.py tests/agent/test_raphael_risk.py
rtk git commit -m "feat: classify Raphael advisor action risk"
```

## Task 5: Profile-Aware State Helpers

**Files:**
- Create: `agent/raphael/state.py`
- Create: `tests/agent/test_raphael_state.py`

- [ ] **Step 1: Write failing state tests**

Create `tests/agent/test_raphael_state.py`:

```python
import json
from datetime import datetime, timezone
from unittest.mock import patch

from agent.raphael.models import RaphaelEvent, RaphaelState, StatusCard
from agent.raphael.state import (
    append_event,
    get_raphael_events_path,
    get_raphael_state_dir,
    get_raphael_state_path,
    read_state,
    write_state,
)


def _now():
    return datetime(2026, 6, 16, 0, 0, tzinfo=timezone.utc)


def test_state_paths_use_active_hermes_home(tmp_path):
    with patch.dict("os.environ", {"HERMES_HOME": str(tmp_path)}):
        assert get_raphael_state_dir() == tmp_path / "raphael"
        assert get_raphael_state_path() == tmp_path / "raphael" / "state.json"
        assert get_raphael_events_path() == tmp_path / "raphael" / "events.jsonl"


def test_read_state_returns_empty_when_missing(tmp_path):
    with patch.dict("os.environ", {"HERMES_HOME": str(tmp_path)}):
        state = read_state()

    assert state.status_cards == []
    assert state.action_proposals == []


def test_write_state_uses_atomic_json_file(tmp_path):
    card = StatusCard(
        card_id="card_001",
        severity="info",
        title="All quiet",
        summary="No active observations.",
        observed_at=_now(),
        expires_at=_now(),
        source="test",
        confidence=1.0,
        evidence_refs=[],
    )
    state = RaphaelState(status_cards=[card], action_proposals=[], updated_at=_now())

    with patch.dict("os.environ", {"HERMES_HOME": str(tmp_path)}):
        write_state(state)
        loaded = read_state()
        raw = json.loads(get_raphael_state_path().read_text(encoding="utf-8"))

    assert loaded == state
    assert raw["schema_version"] == "raphael.state.v1"
    assert raw["status_cards"][0]["card_id"] == "card_001"
    assert not list((tmp_path / "raphael").glob("*.tmp"))


def test_append_event_writes_jsonl(tmp_path):
    event = RaphaelEvent(
        event_id="evt_001",
        kind="state_written",
        created_at=_now(),
        details={"path": "state.json"},
    )

    with patch.dict("os.environ", {"HERMES_HOME": str(tmp_path)}):
        append_event(event)
        line = get_raphael_events_path().read_text(encoding="utf-8").strip()

    assert json.loads(line) == {
        "schema_version": "raphael.event.v1",
        "event_id": "evt_001",
        "kind": "state_written",
        "created_at": "2026-06-16T00:00:00+00:00",
        "details": {"path": "state.json"},
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_state.py -q
```

Expected:

```text
ERROR ModuleNotFoundError: No module named 'agent.raphael.state'
```

- [ ] **Step 3: Implement state helpers**

Create `agent/raphael/state.py`:

```python
from __future__ import annotations

import json
import os
from pathlib import Path

from hermes_constants import get_hermes_home

from agent.raphael.models import RaphaelEvent, RaphaelState


def get_raphael_state_dir() -> Path:
    return get_hermes_home() / "raphael"


def get_raphael_state_path() -> Path:
    return get_raphael_state_dir() / "state.json"


def get_raphael_events_path() -> Path:
    return get_raphael_state_dir() / "events.jsonl"


def read_state() -> RaphaelState:
    path = get_raphael_state_path()
    if not path.exists():
        return RaphaelState.empty()
    data = json.loads(path.read_text(encoding="utf-8"))
    return RaphaelState.from_dict(data)


def write_state(state: RaphaelState) -> None:
    state_dir = get_raphael_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    path = get_raphael_state_path()
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(
        json.dumps(state.to_dict(), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp_path, path)


def append_event(event: RaphaelEvent) -> None:
    events_path = get_raphael_events_path()
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with events_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
```

- [ ] **Step 4: Run state tests**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_state.py -q
```

Expected:

```text
4 passed
```

- [ ] **Step 5: Commit**

Run:

```bash
rtk git add agent/raphael/state.py tests/agent/test_raphael_state.py
rtk git commit -m "feat: add Raphael profile state helpers"
```

## Task 6: Status Freshness And Rendering

**Files:**
- Create: `agent/raphael/status.py`
- Create: `tests/agent/test_raphael_status.py`

- [ ] **Step 1: Write failing status tests**

Create `tests/agent/test_raphael_status.py`:

```python
from datetime import datetime, timedelta, timezone

from agent.raphael.models import ActionProposal, RaphaelState, RiskLevel, StatusCard
from agent.raphael.status import active_cards, render_status


def _at(minute: int):
    return datetime(2026, 6, 16, 0, minute, tzinfo=timezone.utc)


def _card(card_id, title, expires_minute):
    return StatusCard(
        card_id=card_id,
        severity="warning",
        title=title,
        summary=f"{title} summary",
        observed_at=_at(0),
        expires_at=_at(expires_minute),
        source="test",
        confidence=0.9,
        evidence_refs=["evidence:1"],
    )


def test_active_cards_filters_expired_cards():
    state = RaphaelState(
        status_cards=[
            _card("expired", "Expired", 5),
            _card("active", "Active", 20),
        ],
        action_proposals=[],
        updated_at=_at(10),
    )

    cards = active_cards(state, now=_at(10))

    assert [card.card_id for card in cards] == ["active"]


def test_render_status_when_no_cards_or_proposals():
    state = RaphaelState(status_cards=[], action_proposals=[], updated_at=_at(0))

    output = render_status(state, now=_at(1))

    assert "Raphael Advisor" in output
    assert "No active status cards" in output
    assert "No pending action proposals" in output
    assert "read-only" in output


def test_render_status_includes_cards_and_approval_required_proposals():
    proposal = ActionProposal(
        proposal_id="act_001",
        action_type="skill_patch",
        risk=RiskLevel.R2,
        summary="Patch a skill after human review",
        evidence_refs=["trace_001"],
        created_at=_at(1),
    )
    state = RaphaelState(
        status_cards=[_card("card_001", "Gateway warning", 20)],
        action_proposals=[proposal],
        updated_at=_at(2),
    )

    output = render_status(state, now=_at(3))

    assert "Gateway warning" in output
    assert "act_001" in output
    assert "R2" in output
    assert "requires approval" in output
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_status.py -q
```

Expected:

```text
ERROR ModuleNotFoundError: No module named 'agent.raphael.status'
```

- [ ] **Step 3: Implement status helpers**

Create `agent/raphael/status.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone

from agent.raphael.models import ActionProposal, RaphaelState, StatusCard


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def active_cards(state: RaphaelState, *, now: datetime | None = None) -> list[StatusCard]:
    moment = now or _now_utc()
    return [card for card in state.status_cards if card.expires_at > moment]


def _proposal_line(proposal: ActionProposal) -> str:
    approval = "requires approval" if proposal.requires_approval else "auto-allow"
    return (
        f"- `{proposal.proposal_id}` [{proposal.risk.value}] "
        f"{proposal.summary} ({approval})"
    )


def render_status(
    state: RaphaelState,
    *,
    now: datetime | None = None,
    max_cards: int = 20,
) -> str:
    moment = now or _now_utc()
    cards = active_cards(state, now=moment)[:max_cards]
    proposals = [
        proposal
        for proposal in state.action_proposals
        if proposal.status == "pending"
    ]

    lines = [
        "# Raphael Advisor",
        "",
        "Mode: read-only Advisor MVP.",
        f"State updated: {state.updated_at.isoformat()}",
        "",
        "## Status Cards",
    ]

    if not cards:
        lines.append("No active status cards.")
    else:
        for card in cards:
            lines.append(
                f"- [{card.severity}] {card.title}: {card.summary} "
                f"(source: {card.source}, confidence: {card.confidence:.2f})"
            )

    lines.extend(["", "## Action Proposals"])

    if not proposals:
        lines.append("No pending action proposals.")
    else:
        lines.extend(_proposal_line(proposal) for proposal in proposals)

    lines.extend([
        "",
        "This command does not write memory, edit skills, change cron, install tools, or send public messages.",
    ])
    return "\n".join(lines)
```

- [ ] **Step 4: Run status tests**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/agent/test_raphael_status.py -q
```

Expected:

```text
3 passed
```

- [ ] **Step 5: Commit**

Run:

```bash
rtk git add agent/raphael/status.py tests/agent/test_raphael_status.py
rtk git commit -m "feat: render Raphael advisor status"
```

## Task 7: Bundled Raphael Plugin And `/raphael-status`

**Files:**
- Create: `plugins/raphael/plugin.yaml`
- Create: `plugins/raphael/__init__.py`
- Create: `tests/plugins/test_raphael_plugin.py`

- [ ] **Step 1: Write failing plugin tests**

Create `tests/plugins/test_raphael_plugin.py`:

```python
import importlib.util
import sys
import types
from pathlib import Path

import yaml

import hermes_cli.plugins as plugins_mod


def _write_config(home: Path, *, enabled_plugins: list[str], raphael_enabled: bool):
    (home / "config.yaml").write_text(
        yaml.safe_dump({
            "plugins": {"enabled": enabled_plugins},
            "raphael": {"enabled": raphael_enabled},
        }),
        encoding="utf-8",
    )


def _reset_plugins():
    plugins_mod._plugin_manager = plugins_mod.PluginManager()


def _load_plugin_init():
    repo_root = Path(__file__).resolve().parents[2]
    plugin_dir = repo_root / "plugins" / "raphael"
    spec = importlib.util.spec_from_file_location(
        "hermes_plugins.raphael",
        plugin_dir / "__init__.py",
        submodule_search_locations=[str(plugin_dir)],
    )
    if "hermes_plugins" not in sys.modules:
        ns = types.ModuleType("hermes_plugins")
        ns.__path__ = []
        sys.modules["hermes_plugins"] = ns
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "hermes_plugins.raphael"
    mod.__path__ = [str(plugin_dir)]
    sys.modules["hermes_plugins.raphael"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_raphael_plugin_not_loaded_without_plugin_allow_list(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(tmp_path, enabled_plugins=[], raphael_enabled=True)

    _reset_plugins()
    plugins_mod.discover_plugins()

    assert "raphael-status" not in plugins_mod.get_plugin_commands()


def test_enabled_plugin_registers_status_command(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(tmp_path, enabled_plugins=["raphael"], raphael_enabled=True)

    _reset_plugins()
    plugins_mod.discover_plugins()

    commands = plugins_mod.get_plugin_commands()
    assert "raphael-status" in commands
    assert commands["raphael-status"]["plugin"] == "raphael"


def test_status_command_reports_disabled_without_creating_state(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(tmp_path, enabled_plugins=["raphael"], raphael_enabled=False)
    plugin = _load_plugin_init()

    output = plugin.handle_status("")

    assert "disabled" in output.lower()
    assert not (tmp_path / "raphael").exists()


def test_status_command_renders_state_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(tmp_path, enabled_plugins=["raphael"], raphael_enabled=True)
    plugin = _load_plugin_init()

    output = plugin.handle_status("")

    assert "Raphael Advisor" in output
    assert "No active status cards" in output
    assert "No pending action proposals" in output
    assert not (tmp_path / "memories").exists()
    assert not (tmp_path / "cron" / "jobs.json").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/plugins/test_raphael_plugin.py -q
```

Expected:

```text
ERROR FileNotFoundError
```

or:

```text
FAIL test_enabled_plugin_registers_status_command
AssertionError: assert 'raphael-status' in ...
```

- [ ] **Step 3: Add plugin manifest**

Create `plugins/raphael/plugin.yaml`:

```yaml
name: raphael
version: 0.1.0
description: Read-only Raphael Advisor MVP status command.
author: local
kind: standalone
provides_hooks: []
provides_tools: []
```

- [ ] **Step 4: Implement plugin registration**

Create `plugins/raphael/__init__.py`:

```python
from __future__ import annotations

from hermes_cli.config import cfg_get, load_config

from agent.raphael.state import read_state
from agent.raphael.status import render_status


def _raphael_enabled() -> bool:
    config = load_config()
    return bool(cfg_get(config, "raphael", "enabled", default=False))


def _max_status_cards() -> int:
    config = load_config()
    value = cfg_get(config, "raphael", "max_status_cards", default=20)
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 20


def handle_status(raw_args: str) -> str:
    args = (raw_args or "").strip()
    if args:
        return "Usage: /raphael-status"

    if not _raphael_enabled():
        return (
            "Raphael Advisor is disabled. Enable `raphael.enabled: true` "
            "and keep the `raphael` plugin in `plugins.enabled` to use it."
        )

    return render_status(read_state(), max_cards=_max_status_cards())


def register(ctx):
    ctx.register_command(
        "raphael-status",
        handle_status,
        description="Show read-only Raphael advisor status",
        args_hint="",
    )
```

- [ ] **Step 5: Run plugin tests**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/plugins/test_raphael_plugin.py tests/test_transform_tool_result_hook.py::test_transform_tool_result_integration_with_real_plugin -q
```

Expected:

```text
All selected tests pass
```

- [ ] **Step 6: Commit**

Run:

```bash
rtk git add plugins/raphael/plugin.yaml plugins/raphael/__init__.py tests/plugins/test_raphael_plugin.py
rtk git commit -m "feat: add read-only Raphael advisor plugin"
```

## Task 8: Focused Integration Verification

**Files:**
- Read: all files changed by Tasks 1-7.

- [ ] **Step 1: Run focused Raphael suite**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/hermes_cli/test_raphael_config.py tests/agent/test_file_safety_cross_profile.py tests/tools/test_cross_profile_guard.py tests/agent/test_raphael_models.py tests/agent/test_raphael_risk.py tests/agent/test_raphael_state.py tests/agent/test_raphael_status.py tests/plugins/test_raphael_plugin.py -q
```

Expected:

```text
All selected tests pass
```

- [ ] **Step 2: Run adjacent plugin/config/gateway suites**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/test_transform_tool_result_hook.py tests/plugins/test_disk_cleanup_plugin.py tests/hermes_cli/test_commands.py::TestTelegramMenuCommands::test_includes_plugin_commands_via_lazy_discovery tests/gateway/test_config_driven_access_policy.py -q
```

Expected:

```text
All selected tests pass
```

- [ ] **Step 3: Scan for forbidden Phase 1 behavior**

Run:

```bash
rtk rg -n "skill_manage|memory_add|cronjob|send_public|post_message|install_tool|approve|write_approval|skill_patch|skill_delete" agent/raphael plugins/raphael tests/agent/test_raphael_*.py tests/plugins/test_raphael_plugin.py
```

Expected:

```text
Only risk-classifier constants/tests may mention mutation action names. Plugin runtime code must not call mutation tools, memory APIs, cron APIs, messaging APIs, or approval APIs.
```

- [ ] **Step 4: Check whitespace**

Run:

```bash
rtk git diff --check
```

Expected:

```text
No output
```

- [ ] **Step 5: Commit verification adjustments if needed**

If verification required small fixes, commit them:

```bash
rtk git add agent/raphael plugins/raphael tests/hermes_cli/test_raphael_config.py tests/agent/test_file_safety_cross_profile.py tests/tools/test_cross_profile_guard.py tests/agent/test_raphael_*.py tests/plugins/test_raphael_plugin.py hermes_cli/config.py agent/file_safety.py
rtk git commit -m "test: verify Raphael advisor MVP integration"
```

If no fixes were needed after Task 7, skip this commit.

## Task 9: Local Runtime Smoke Test

**Files:**
- Runtime-only: temporary `HERMES_HOME` under `/private/tmp`
- No repository file changes expected.

- [ ] **Step 1: Create an isolated smoke config**

Run:

```bash
rtk mkdir -p /private/tmp/hermes-raphael-smoke
```

Create `/private/tmp/hermes-raphael-smoke/config.yaml` with:

```yaml
plugins:
  enabled:
    - raphael
raphael:
  enabled: true
```

Use `apply_patch` only for repository files. For this temporary smoke file, use a shell editor or Python one-liner only if the environment allows temporary writes safely.

- [ ] **Step 2: Call the plugin handler directly**

Run:

```bash
rtk env HERMES_HOME=/private/tmp/hermes-raphael-smoke ./venv/bin/python -c "import hermes_cli.plugins as p; p._plugin_manager=p.PluginManager(); p.discover_plugins(); h=p.get_plugin_command_handler('raphael-status'); print(h(''))"
```

Expected output contains:

```text
Raphael Advisor
No active status cards
No pending action proposals
read-only
```

- [ ] **Step 3: Confirm smoke did not mutate unrelated runtime areas**

Run:

```bash
rtk find /private/tmp/hermes-raphael-smoke -maxdepth 2 -type f -print
```

Expected:

```text
/private/tmp/hermes-raphael-smoke/config.yaml
```

`state.json` should not be created by a read-only status render when no state exists.

## Task 10: Final Review And Branch Hygiene

**Files:**
- Read: `git status`, `git log`, changed files.

- [ ] **Step 1: Review final diff**

Run:

```bash
rtk git status --short --branch
rtk git log --oneline -8
rtk git diff --stat HEAD~7..HEAD
```

Expected:

```text
Only Raphael/config/file-safety/test files from this plan are included in the new commits.
Existing image/image2 worktree changes remain untouched and unstaged unless they predated this work.
```

- [ ] **Step 2: Re-run final verification bundle**

Run:

```bash
rtk ./venv/bin/python -m pytest tests/hermes_cli/test_raphael_config.py tests/agent/test_file_safety_cross_profile.py tests/tools/test_cross_profile_guard.py tests/agent/test_raphael_models.py tests/agent/test_raphael_risk.py tests/agent/test_raphael_state.py tests/agent/test_raphael_status.py tests/plugins/test_raphael_plugin.py tests/test_transform_tool_result_hook.py tests/plugins/test_disk_cleanup_plugin.py -q
rtk git diff --check
```

Expected:

```text
All selected tests pass
git diff --check has no output
```

- [ ] **Step 3: Prepare reviewer summary**

Use this summary shape:

```markdown
## Summary

- Added disabled-by-default Raphael advisor config and profile-scoped file-safety coverage.
- Added pure Raphael models, risk classification, state helpers, and status rendering.
- Added bundled opt-in `raphael` plugin with read-only `/raphael-status`.

## Safety

- No skill writes.
- No memory writes.
- No cron mutation.
- No public Slack posting.
- No tool installation.
- Runtime state is profile-scoped under `get_hermes_home() / "raphael"`.

## Tests

- `rtk ./venv/bin/python -m pytest ... -q`
- `rtk git diff --check`
```

## Self-Review Checklist

- [ ] Every design requirement from the Phase 0 report maps to a task above.
- [ ] `raphael.enabled` defaults to false.
- [ ] `plugins.enabled` remains required for plugin loading.
- [ ] `/raphael-status` is the only command in Phase 1.
- [ ] The status command does not write state or events.
- [ ] Raphael state helpers use `get_hermes_home() / "raphael"`.
- [ ] `raphael/` is covered by cross-profile file-safety tests.
- [ ] Mutation action names appear only in risk classification or tests.
- [ ] The final diff excludes unrelated image/image2 files.
- [ ] Verification commands and expected results are concrete.

Run this red-flag scan against the plan before executing it:

```bash
rtk rg -n "T[B]D|TO[D]O|FIX[M]E|p[l]aceholders?|implement l[a]ter|fill in d[e]tails|Similar to T[a]sk|\\?\\?" docs/superpowers/plans/2026-06-16-raphael-phase-1-advisor-mvp.md
```

Expected:

```text
No output
```

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-16-raphael-phase-1-advisor-mvp.md`. Two execution options:

**1. Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, and keep each commit small.

**2. Inline Execution** - Execute tasks in this session using `superpowers:executing-plans`, with checkpoints after each commit.

Choose one execution mode before starting Task 1.

## Execution Status - 2026-06-16

Status: Phase 1 Advisor MVP implemented and reviewed.

Implementation commits:

- `02ab3aad1` `feat: add Raphael advisor config defaults`
- `390ede8f5` `feat: guard Raphael state across profiles`
- `9af28cdda` `feat: add Raphael advisor data models`
- `869450f84` `fix: validate Raphael model schemas`
- `6930c684f` `fix: align Raphael status card serialization`
- `5c344420a` `feat: classify Raphael advisor action risk`
- `6c113b7cf` `feat: add Raphael profile state helpers`
- `2942daad6` `fix: use shared atomic write for Raphael state`
- `c74e7e3f4` `feat: render Raphael advisor status`
- `b1d84616a` `feat: add read-only Raphael advisor plugin`
- `18636034d` `fix: recognize Raphael config root key`
- `8a19cfbb7` `fix: keep plugin allowlist reads side-effect free`
- `ff7ca5df0` `fix: keep dashboard auth discovery side-effect free`
- `508f83deb` `test: align dashboard auth config reader tests`
- `63ae1f70b` `docs: mention Raphael in cross-profile tool schemas`

Review:

- First final review requested changes for stale dashboard auth tests that patched `load_config()` after production moved to `read_raw_config()`.
- Follow-up commit `508f83deb` aligned the tests with the new side-effect-free config reader.
- Second final review approved the implementation and confirmed the Phase 1 scope, read-only behavior, no forbidden mutation surface, and no unrelated image/image2 worktree changes.

Verification evidence:

- Focused Raphael suite: `77 passed, 1 warning`.
- Plugin/dashboard auth suite: `263 passed, 1 warning`.
- Adjacent plugin/config/gateway suite: `105 passed`.
- Dashboard auth provider suite: `142 passed`.
- Cross-profile guard focused suite: `13 passed`.
- Mutation scan only found risk-classifier constants and tests for forbidden action names.
- Isolated `/raphael-status` smoke under `/private/tmp/hermes-raphael-final-smoke-508f83d` rendered the expected advisor output and left only `config.yaml`; it did not create `SOUL.md`, `memories/`, `cron/`, or `raphael/state.json`.
- Phase commit-range whitespace check: `rtk git diff --check 419fbe617^..HEAD` produced no output.

Remaining notes:

- Existing image/image2 dirty files are unrelated and intentionally untouched.
- Phase 2 should start with a new plan for Skill Trace MVP; do not fold it into this Phase 1 implementation.
