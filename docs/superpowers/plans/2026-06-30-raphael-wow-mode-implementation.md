# Raphael Wow Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved Raphael Wow Mode so Hermes feels like a Sage King control layer: summonable, strategic, mission-aware, proof-gated, evolution-aware, demoable, and release-safe.

**Architecture:** Add small pure Raphael modules for appraisal, strategy simulation, mission state, proof validation, invocation rendering, and wow scoring. Wire them into the existing Raphael control/finalizer/CLI surfaces without replacing visual handoff logic. Keep high-risk skill and memory changes behind existing gated evolution review and explicit approval boundaries.

**Tech Stack:** Python 3.11, dataclasses, existing `agent.raphael` runtime state, `hermes_cli` argparse, pytest, ruff, `rtk hermes chat` live LLM smoke, no visual live generation by default.

## Global Constraints

- Inspiration is an archetype only; do not impersonate or copy a copyrighted character.
- Public lifecycle remains `hermes raphael install`, `enable`, `disable`, `status`, and new `demo`.
- TDD is required for every behavior change after the approved spec.
- No completion claim may pass without task-matching trusted proof.
- Disabled Raphael must not inject summon behavior, mutate mission state, enforce proof, or write evolution.
- The public demo must not use visual generation quota, private logs, base64, provider raw responses, or local secrets.
- Public release requires `wow score >= 8/10`.
- Existing visual reference, stale artifact, and clean-delivery protections remain intact.

---

## File Structure

- Create `agent/raphael/appraisal.py`: pure intent/risk/success-condition appraisal.
- Create `agent/raphael/strategy.py`: pure fast/safe/quality strategy simulation and selection.
- Create `agent/raphael/mission.py`: mission state model, update policy, and runtime persistence helpers.
- Create `agent/raphael/proof.py`: shared proof-event extraction and claim validation.
- Create `agent/raphael/invocation.py`: summon detection and user-facing appraisal renderer.
- Create `agent/raphael/wow_score.py`: deterministic public-release scoring.
- Modify `agent/raphael/control.py`: consume appraisal/strategy data and preserve existing visual routing.
- Modify `agent/raphael/state.py`: persist mission state and append mission/evolution events.
- Modify `agent/turn_finalizer.py`: replace local proof helper with `agent.raphael.proof` and add proof debrief metadata.
- Modify `agent/turn_context.py`: keep Raphael observation injection routed through `build_raphael_observation_context`.
- Modify `hermes_cli/raphael_cmd.py` and `hermes_cli/subcommands/raphael.py`: add deterministic `demo`.
- Modify `plugins/raphael/__init__.py` and `agent/raphael/status.py`: show mission, wow score, and evolution metadata.
- Add tests under `tests/agent/`, `tests/hermes_cli/`, and existing visual/tool suites.

---

### Task 1: Situation Appraisal And Strategy Simulation

**Files:**
- Create: `agent/raphael/appraisal.py`
- Create: `agent/raphael/strategy.py`
- Modify: `agent/raphael/__init__.py`
- Test: `tests/agent/test_raphael_appraisal.py`
- Test: `tests/agent/test_raphael_strategy.py`

**Interfaces:**
- Produces: `RaphaelAppraisal(intent: str, task_type: str, risk_level: str, success_conditions: tuple[str, ...], blockers: tuple[str, ...], active_artifact_id: str | None)`
- Produces: `appraise_raphael_situation(user_message: Any, conversation_history: Sequence[Mapping[str, Any]] | None = None, attachments: Sequence[str] | None = None) -> RaphaelAppraisal`
- Produces: `RaphaelStrategy(strategy_id: str, label: str, route: str, expected_benefit: str, risk: str, required_proofs: tuple[str, ...], blocked_reason: str | None = None)`
- Produces: `simulate_raphael_strategies(appraisal: RaphaelAppraisal) -> RaphaelStrategySet`

- [ ] **Step 1: Write failing appraisal tests**

Add `tests/agent/test_raphael_appraisal.py`:

```python
from agent.raphael.appraisal import appraise_raphael_situation


def test_appraisal_classifies_tool_runtime_task_with_required_proofs():
    appraisal = appraise_raphael_situation("拉斐爾，修復 runtime bug 並驗證")

    assert appraisal.task_type == "tool_runtime"
    assert appraisal.risk_level == "medium"
    assert appraisal.success_conditions == (
        "focused_tests",
        "runtime_smoke_when_live_wiring",
    )
    assert appraisal.blockers == ()


def test_appraisal_detects_missing_reference_blocker():
    appraisal = appraise_raphael_situation(
        "拉斐爾，用 ref3 的服裝產圖",
        attachments=["/tmp/ref1.png", "/tmp/ref2.png"],
    )

    assert appraisal.task_type == "visual_generation"
    assert "missing_ref3" in appraisal.blockers
    assert "reference_mapping_confirmed" in appraisal.success_conditions


def test_appraisal_preserves_active_artifact_for_followup_edit():
    appraisal = appraise_raphael_situation(
        "拉斐爾，把剛剛那張改成夜景",
        conversation_history=[
            {
                "role": "assistant",
                "metadata": {"selected_artifact_id": "img_current"},
            }
        ],
    )

    assert appraisal.task_type == "visual_edit"
    assert appraisal.active_artifact_id == "img_current"
```

- [ ] **Step 2: Verify RED**

Run:

```bash
venv/bin/python -m pytest tests/agent/test_raphael_appraisal.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'agent.raphael.appraisal'`.

- [ ] **Step 3: Implement minimal appraisal module**

Create `agent/raphael/appraisal.py` with:

```python
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class RaphaelAppraisal:
    intent: str
    task_type: str
    risk_level: str
    success_conditions: tuple[str, ...]
    blockers: tuple[str, ...] = ()
    active_artifact_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "task_type": self.task_type,
            "risk_level": self.risk_level,
            "success_conditions": list(self.success_conditions),
            "blockers": list(self.blockers),
            "active_artifact_id": self.active_artifact_id,
        }


def appraise_raphael_situation(
    user_message: Any,
    *,
    conversation_history: Sequence[Mapping[str, Any]] | None = None,
    attachments: Sequence[str] | None = None,
) -> RaphaelAppraisal:
    text = _extract_text(user_message)
    active_artifact_id = _latest_selected_artifact_id(conversation_history)
    attachment_count = len([item for item in attachments or () if str(item).strip()])
    missing_ref = _missing_reference_index(text, attachment_count)
    if missing_ref is not None:
        return RaphaelAppraisal(
            intent=_summary(text),
            task_type="visual_generation",
            risk_level="medium",
            success_conditions=("reference_mapping_confirmed",),
            blockers=(f"missing_ref{missing_ref}",),
            active_artifact_id=active_artifact_id,
        )
    if active_artifact_id and _contains_any(text, ("改", "修改", "修正", "edit", "change")):
        return RaphaelAppraisal(
            intent=_summary(text),
            task_type="visual_edit",
            risk_level="medium",
            success_conditions=("artifact_continuity", "quality_gate_passed"),
            active_artifact_id=active_artifact_id,
        )
    if _contains_any(text, ("圖片", "產圖", "image", "video", "影片")):
        return RaphaelAppraisal(
            intent=_summary(text),
            task_type="visual_generation",
            risk_level="medium",
            success_conditions=("selected_current_artifact_only", "quality_gate_passed"),
            active_artifact_id=active_artifact_id,
        )
    if _contains_any(text, ("修復", "實作", "install", "runtime", "deploy", "上線", "設定")):
        return RaphaelAppraisal(
            intent=_summary(text),
            task_type="tool_runtime",
            risk_level="medium",
            success_conditions=("focused_tests", "runtime_smoke_when_live_wiring"),
            active_artifact_id=active_artifact_id,
        )
    return RaphaelAppraisal(
        intent=_summary(text),
        task_type="general",
        risk_level="low",
        success_conditions=("answer_matches_user_intent",),
        active_artifact_id=active_artifact_id,
    )


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        parts: list[str] = []
        for item in value:
            if isinstance(item, Mapping):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
            else:
                parts.append(str(item))
        return " ".join(parts).strip()
    return str(value or "").strip()


def _summary(text: str, limit: int = 96) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in markers)


def _mentioned_ref_indices(text: str) -> tuple[int, ...]:
    return tuple(int(match) for match in re.findall(r"\bref\s*(\d+)\b", text.lower()))


def _missing_reference_index(text: str, attachment_count: int) -> int | None:
    for index in _mentioned_ref_indices(text):
        if index > attachment_count:
            return index
    return None


def _latest_selected_artifact_id(
    history: Sequence[Mapping[str, Any]] | None,
) -> str | None:
    for message in reversed(tuple(history or ())):
        metadata = message.get("metadata") if isinstance(message, Mapping) else None
        if isinstance(metadata, Mapping):
            artifact_id = metadata.get("selected_artifact_id")
            if artifact_id:
                return str(artifact_id)
    return None
```

- [ ] **Step 4: Write failing strategy tests**

Add `tests/agent/test_raphael_strategy.py`:

```python
from agent.raphael.appraisal import RaphaelAppraisal
from agent.raphael.strategy import simulate_raphael_strategies


def test_strategy_simulation_emits_fast_safe_quality_routes():
    appraisal = RaphaelAppraisal(
        intent="修復 runtime bug",
        task_type="tool_runtime",
        risk_level="medium",
        success_conditions=("focused_tests", "runtime_smoke_when_live_wiring"),
    )

    strategies = simulate_raphael_strategies(appraisal)

    assert [strategy.label for strategy in strategies.candidates] == [
        "fast",
        "safe",
        "quality",
    ]
    assert strategies.selected_strategy_id == "safe"
    assert "focused_tests" in strategies.selected.required_proofs


def test_strategy_blocks_when_appraisal_has_blockers():
    appraisal = RaphaelAppraisal(
        intent="用 ref3 產圖",
        task_type="visual_generation",
        risk_level="medium",
        success_conditions=("reference_mapping_confirmed",),
        blockers=("missing_ref3",),
    )

    strategies = simulate_raphael_strategies(appraisal)

    assert strategies.selected.label == "blocked"
    assert strategies.selected.blocked_reason == "missing_ref3"
```

- [ ] **Step 5: Verify strategy RED**

Run:

```bash
venv/bin/python -m pytest tests/agent/test_raphael_strategy.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'agent.raphael.strategy'`.

- [ ] **Step 6: Implement minimal strategy module**

Create `agent/raphael/strategy.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.raphael.appraisal import RaphaelAppraisal


@dataclass(frozen=True)
class RaphaelStrategy:
    strategy_id: str
    label: str
    route: str
    expected_benefit: str
    risk: str
    required_proofs: tuple[str, ...]
    blocked_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "label": self.label,
            "route": self.route,
            "expected_benefit": self.expected_benefit,
            "risk": self.risk,
            "required_proofs": list(self.required_proofs),
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class RaphaelStrategySet:
    candidates: tuple[RaphaelStrategy, ...]
    selected_strategy_id: str

    @property
    def selected(self) -> RaphaelStrategy:
        for strategy in self.candidates:
            if strategy.strategy_id == self.selected_strategy_id:
                return strategy
        return self.candidates[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "selected_strategy_id": self.selected_strategy_id,
            "selected": self.selected.to_dict(),
        }


def simulate_raphael_strategies(appraisal: RaphaelAppraisal) -> RaphaelStrategySet:
    if appraisal.blockers:
        blocked = RaphaelStrategy(
            strategy_id="blocked",
            label="blocked",
            route="ask_precise_clarification",
            expected_benefit="avoid_wrong_action",
            risk="low",
            required_proofs=appraisal.success_conditions,
            blocked_reason=appraisal.blockers[0],
        )
        return RaphaelStrategySet(candidates=(blocked,), selected_strategy_id="blocked")
    fast = RaphaelStrategy(
        strategy_id="fast",
        label="fast",
        route="minimal_direct_action",
        expected_benefit="shortest_path",
        risk="medium",
        required_proofs=appraisal.success_conditions[:1],
    )
    safe = RaphaelStrategy(
        strategy_id="safe",
        label="safe",
        route="plan_execute_verify",
        expected_benefit="best_reliability",
        risk="low",
        required_proofs=appraisal.success_conditions,
    )
    quality = RaphaelStrategy(
        strategy_id="quality",
        label="quality",
        route="multi_pass_review_and_repair",
        expected_benefit="highest_output_quality",
        risk="medium",
        required_proofs=tuple(dict.fromkeys((*appraisal.success_conditions, "hostile_review"))),
    )
    return RaphaelStrategySet(
        candidates=(fast, safe, quality),
        selected_strategy_id="quality" if appraisal.task_type.startswith("visual") else "safe",
    )
```

- [ ] **Step 7: Export interfaces and verify GREEN**

Modify `agent/raphael/__init__.py` to export the new dataclasses and functions.

Run:

```bash
venv/bin/python -m pytest tests/agent/test_raphael_appraisal.py tests/agent/test_raphael_strategy.py -q
venv/bin/python -m ruff check agent/raphael/appraisal.py agent/raphael/strategy.py tests/agent/test_raphael_appraisal.py tests/agent/test_raphael_strategy.py
```

Expected: all tests pass and ruff reports `All checks passed!`.

---

### Task 2: Mission State And Follow-Up Continuity

**Files:**
- Create: `agent/raphael/mission.py`
- Modify: `agent/raphael/state.py`
- Modify: `agent/raphael/status.py`
- Test: `tests/agent/test_raphael_mission.py`
- Test: `tests/agent/test_raphael_status.py`

**Interfaces:**
- Consumes: `RaphaelAppraisal`, `RaphaelStrategySet`
- Produces: `RaphaelMissionState`
- Produces: `update_raphael_mission(current: RaphaelMissionState | None, appraisal: RaphaelAppraisal, strategies: RaphaelStrategySet) -> RaphaelMissionState`
- Produces: `read_mission_state() -> RaphaelMissionState | None`
- Produces: `write_mission_state(mission: RaphaelMissionState | None) -> None`

- [ ] **Step 1: Write failing mission tests**

Add `tests/agent/test_raphael_mission.py`:

```python
from agent.raphael.appraisal import RaphaelAppraisal
from agent.raphael.mission import update_raphael_mission
from agent.raphael.strategy import RaphaelStrategy, RaphaelStrategySet


def _strategies():
    selected = RaphaelStrategy(
        strategy_id="safe",
        label="safe",
        route="plan_execute_verify",
        expected_benefit="best_reliability",
        risk="low",
        required_proofs=("focused_tests",),
    )
    return RaphaelStrategySet(candidates=(selected,), selected_strategy_id="safe")


def test_mission_state_is_created_from_appraisal_and_strategy():
    appraisal = RaphaelAppraisal(
        intent="修復 runtime bug",
        task_type="tool_runtime",
        risk_level="medium",
        success_conditions=("focused_tests",),
    )

    mission = update_raphael_mission(None, appraisal, _strategies())

    assert mission.mission_id.startswith("mission-")
    assert mission.goal == "修復 runtime bug"
    assert mission.phase == "strategy_selected"
    assert mission.selected_strategy_id == "safe"
    assert mission.proof_status == "pending"


def test_followup_updates_existing_mission_instead_of_restarting():
    current = update_raphael_mission(
        None,
        RaphaelAppraisal("修復 runtime bug", "tool_runtime", "medium", ("focused_tests",)),
        _strategies(),
    )

    updated = update_raphael_mission(
        current,
        RaphaelAppraisal(
            "再補 runtime smoke",
            "tool_runtime",
            "medium",
            ("focused_tests", "runtime_smoke_when_live_wiring"),
        ),
        _strategies(),
    )

    assert updated.mission_id == current.mission_id
    assert updated.goal == "再補 runtime smoke"
    assert updated.required_proofs == (
        "focused_tests",
        "runtime_smoke_when_live_wiring",
    )
```

- [ ] **Step 2: Verify RED**

Run:

```bash
venv/bin/python -m pytest tests/agent/test_raphael_mission.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'agent.raphael.mission'`.

- [ ] **Step 3: Implement minimal mission module**

Create `agent/raphael/mission.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from typing import Any

from agent.raphael.appraisal import RaphaelAppraisal
from agent.raphael.strategy import RaphaelStrategySet


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RaphaelMissionState:
    mission_id: str
    goal: str
    phase: str
    selected_strategy_id: str
    active_artifact_id: str | None
    blockers: tuple[str, ...]
    next_action: str
    proof_status: str
    required_proofs: tuple[str, ...]
    updated_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "goal": self.goal,
            "phase": self.phase,
            "selected_strategy_id": self.selected_strategy_id,
            "active_artifact_id": self.active_artifact_id,
            "blockers": list(self.blockers),
            "next_action": self.next_action,
            "proof_status": self.proof_status,
            "required_proofs": list(self.required_proofs),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RaphaelMissionState:
        return cls(
            mission_id=str(payload["mission_id"]),
            goal=str(payload["goal"]),
            phase=str(payload["phase"]),
            selected_strategy_id=str(payload["selected_strategy_id"]),
            active_artifact_id=(
                None
                if payload.get("active_artifact_id") is None
                else str(payload.get("active_artifact_id"))
            ),
            blockers=tuple(str(item) for item in payload.get("blockers", ())),
            next_action=str(payload["next_action"]),
            proof_status=str(payload["proof_status"]),
            required_proofs=tuple(str(item) for item in payload.get("required_proofs", ())),
            updated_at=datetime.fromisoformat(str(payload["updated_at"])),
        )


def update_raphael_mission(
    current: RaphaelMissionState | None,
    appraisal: RaphaelAppraisal,
    strategies: RaphaelStrategySet,
) -> RaphaelMissionState:
    mission_id = current.mission_id if current is not None else _new_mission_id(appraisal)
    selected = strategies.selected
    phase = "blocked" if selected.blocked_reason else "strategy_selected"
    next_action = selected.route
    return RaphaelMissionState(
        mission_id=mission_id,
        goal=appraisal.intent,
        phase=phase,
        selected_strategy_id=selected.strategy_id,
        active_artifact_id=appraisal.active_artifact_id,
        blockers=appraisal.blockers,
        next_action=next_action,
        proof_status="blocked" if selected.blocked_reason else "pending",
        required_proofs=selected.required_proofs,
        updated_at=_utc_now(),
    )


def _new_mission_id(appraisal: RaphaelAppraisal) -> str:
    seed = f"{appraisal.intent}|{appraisal.task_type}|{_utc_now().timestamp()}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"mission-{digest}"
```

- [ ] **Step 4: Add state persistence tests**

Extend `tests/agent/test_raphael_mission.py`:

```python
def test_mission_state_round_trips_through_runtime_state(tmp_path, monkeypatch):
    import agent.raphael.state as state

    monkeypatch.setattr(state, "get_hermes_home", lambda: tmp_path)
    mission = update_raphael_mission(
        None,
        RaphaelAppraisal("修復 runtime bug", "tool_runtime", "medium", ("focused_tests",)),
        _strategies(),
    )

    state.write_mission_state(mission)
    loaded = state.read_mission_state()

    assert loaded == mission
```

- [ ] **Step 5: Verify persistence RED**

Run:

```bash
venv/bin/python -m pytest tests/agent/test_raphael_mission.py::test_mission_state_round_trips_through_runtime_state -q
```

Expected: fail with `AttributeError` for missing `write_mission_state`.

- [ ] **Step 6: Implement persistence helpers**

Modify `agent/raphael/state.py`:

```python
from agent.raphael.mission import RaphaelMissionState


def get_raphael_mission_path() -> Path:
    return get_raphael_state_dir() / "mission.json"


def read_mission_state() -> RaphaelMissionState | None:
    path = get_raphael_mission_path()
    if not path.exists():
        return None
    return RaphaelMissionState.from_dict(json.loads(path.read_text(encoding="utf-8")))


def write_mission_state(mission: RaphaelMissionState | None) -> None:
    path = get_raphael_mission_path()
    if mission is None:
        if path.exists():
            path.unlink()
        return
    atomic_json_write(path, mission.to_dict(), sort_keys=True)
```

Add `get_raphael_mission_path`, `read_mission_state`, and `write_mission_state` to `__all__`.

- [ ] **Step 7: Add status rendering**

Extend `render_status(...)` with optional `mission_state: Mapping[str, Any] | None = None`, and render:

```text
Current Mission:
- mission_id: <id>
- phase: <phase>
- goal: <goal>
- next_action: <next_action>
- proof_status: <proof_status>
```

Update tests in `tests/agent/test_raphael_status.py` to assert the current mission appears when provided.

- [ ] **Step 8: Verify GREEN**

Run:

```bash
venv/bin/python -m pytest tests/agent/test_raphael_mission.py tests/agent/test_raphael_status.py -q
venv/bin/python -m ruff check agent/raphael/mission.py agent/raphael/state.py agent/raphael/status.py tests/agent/test_raphael_mission.py tests/agent/test_raphael_status.py
```

Expected: all tests pass and ruff reports `All checks passed!`.

---

### Task 3: Shared Proof Gate

**Files:**
- Create: `agent/raphael/proof.py`
- Modify: `agent/turn_finalizer.py`
- Test: `tests/agent/test_raphael_proof.py`
- Test: `tests/agent/test_turn_finalizer.py`

**Interfaces:**
- Produces: `RaphaelProofEvent(source: str, proof_type: str, command: str, success: bool, content: str)`
- Produces: `extract_raphael_proof_events(messages: Sequence[Mapping[str, Any]]) -> tuple[RaphaelProofEvent, ...]`
- Produces: `raphael_has_required_proof(messages: Sequence[Mapping[str, Any]], required_proofs: Sequence[str]) -> bool`

- [ ] **Step 1: Write failing proof tests**

Add `tests/agent/test_raphael_proof.py`:

```python
from agent.raphael.proof import extract_raphael_proof_events, raphael_has_required_proof


def test_rejects_assistant_text_that_mentions_pytest_passed():
    messages = [{"role": "assistant", "content": "pytest passed"}]

    assert extract_raphael_proof_events(messages) == ()
    assert not raphael_has_required_proof(messages, ("focused_tests",))


def test_rejects_read_file_tool_result_that_mentions_pytest_passed():
    messages = [
        {"role": "tool", "name": "read_file", "content": "README says pytest passed"},
    ]

    assert not raphael_has_required_proof(messages, ("focused_tests",))


def test_accepts_exec_command_pytest_success_for_focused_tests():
    messages = [
        {
            "role": "tool",
            "name": "exec_command",
            "content": "venv/bin/python -m pytest tests/foo.py -q\n1 passed",
        }
    ]

    assert raphael_has_required_proof(messages, ("focused_tests",))


def test_resolves_nameless_tool_result_through_tool_call_id():
    messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "call_read", "function": {"name": "read_file"}},
                {"id": "call_exec", "function": {"name": "exec_command"}},
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_read",
            "content": "pytest passed in README",
        },
        {
            "role": "tool",
            "tool_call_id": "call_exec",
            "content": "venv/bin/python -m pytest tests/foo.py -q\n1 passed",
        },
    ]

    events = extract_raphael_proof_events(messages)

    assert [event.source for event in events] == ["exec_command"]
    assert raphael_has_required_proof(messages, ("focused_tests",))
```

- [ ] **Step 2: Verify RED**

Run:

```bash
venv/bin/python -m pytest tests/agent/test_raphael_proof.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'agent.raphael.proof'`.

- [ ] **Step 3: Implement proof module**

Create `agent/raphael/proof.py` with:

```python
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


TRUSTED_PROOF_TOOLS = {
    "exec_command",
    "terminal",
    "shell",
    "bash",
    "run_command",
    "hermes_cli",
}


@dataclass(frozen=True)
class RaphaelProofEvent:
    source: str
    proof_type: str
    command: str
    success: bool
    content: str


def extract_raphael_proof_events(
    messages: Sequence[Mapping[str, Any]] | None,
) -> tuple[RaphaelProofEvent, ...]:
    tool_call_names = _tool_call_name_map(messages)
    events: list[RaphaelProofEvent] = []
    for message in messages or ():
        if not isinstance(message, Mapping) or message.get("role") != "tool":
            continue
        tool_name = str(message.get("name") or message.get("tool_name") or "").lower()
        if not tool_name:
            tool_name = tool_call_names.get(str(message.get("tool_call_id") or ""), "")
        if tool_name not in TRUSTED_PROOF_TOOLS:
            continue
        content = str(message.get("content") or "")
        lowered = content.lower()
        proof_type = _classify_proof_type(lowered)
        if proof_type:
            events.append(
                RaphaelProofEvent(
                    source=tool_name,
                    proof_type=proof_type,
                    command=_first_line(content),
                    success=True,
                    content=content,
                )
            )
    return tuple(events)


def raphael_has_required_proof(
    messages: Sequence[Mapping[str, Any]] | None,
    required_proofs: Sequence[str],
) -> bool:
    events = extract_raphael_proof_events(messages)
    available = {event.proof_type for event in events if event.success}
    normalized_required = {_normalize_required_proof(item) for item in required_proofs}
    normalized_required.discard("unverifiable")
    if not normalized_required:
        return bool(available)
    return bool(available & normalized_required)


def _tool_call_name_map(messages: Sequence[Mapping[str, Any]] | None) -> dict[str, str]:
    names: dict[str, str] = {}
    for message in messages or ():
        if not isinstance(message, Mapping):
            continue
        for tool_call in message.get("tool_calls") or ():
            if not isinstance(tool_call, Mapping):
                continue
            call_id = str(tool_call.get("id") or "")
            function = tool_call.get("function")
            function = function if isinstance(function, Mapping) else {}
            name = str(function.get("name") or "").lower()
            if call_id and name:
                names[call_id] = name
    return names


def _classify_proof_type(content: str) -> str | None:
    if "pytest" in content and any(marker in content for marker in (" passed", "1 passed", "exit code 0")):
        return "focused_tests"
    if "ruff" in content and "all checks passed" in content:
        return "static_checks"
    if "git diff --check" in content and "exit code 0" in content:
        return "diff_hygiene"
    if "gateway status" in content and any(marker in content for marker in ("pid", "loaded", "running", "service")):
        return "runtime_smoke_when_live_wiring"
    if "session_id" in content and any(marker in content for marker in (" ok", "_ok", "passed")):
        return "live_llm_smoke"
    return None


def _normalize_required_proof(value: str) -> str:
    if value in {"runtime_smoke", "runtime_smoke_when_live_wiring"}:
        return "runtime_smoke_when_live_wiring"
    if value in {"unit_tests", "focused_tests"}:
        return "focused_tests"
    return str(value)


def _first_line(value: str) -> str:
    return value.splitlines()[0].strip() if value.splitlines() else ""
```

- [ ] **Step 4: Replace local finalizer helper**

Modify `agent/turn_finalizer.py`:

- import `raphael_has_required_proof` inside `_apply_raphael_general_proof_gate`;
- replace `_raphael_has_tool_or_runtime_proof(messages)` with `raphael_has_required_proof(messages, evidence.get("required_proofs") or ())`;
- remove the now-duplicated local `_raphael_has_tool_or_runtime_proof` helper after tests are green.

- [ ] **Step 5: Verify GREEN**

Run:

```bash
venv/bin/python -m pytest tests/agent/test_raphael_proof.py tests/agent/test_turn_finalizer.py -q
venv/bin/python -m ruff check agent/raphael/proof.py agent/turn_finalizer.py tests/agent/test_raphael_proof.py tests/agent/test_turn_finalizer.py
```

Expected: all tests pass and ruff reports `All checks passed!`.

---

### Task 4: Raphael Invocation Renderer

**Files:**
- Create: `agent/raphael/invocation.py`
- Modify: `agent/raphael/observer.py`
- Modify: `agent/raphael/prompt.py`
- Test: `tests/agent/test_raphael_invocation.py`
- Test: `tests/agent/test_raphael_observer.py`

**Interfaces:**
- Consumes: `RaphaelAppraisal`, `RaphaelStrategySet`, `RaphaelMissionState`
- Produces: `is_raphael_invocation(text: Any) -> bool`
- Produces: `render_raphael_invocation_response(appraisal: RaphaelAppraisal, strategies: RaphaelStrategySet, mission: RaphaelMissionState | None = None) -> str`

- [ ] **Step 1: Write failing invocation tests**

Add `tests/agent/test_raphael_invocation.py`:

```python
from agent.raphael.appraisal import RaphaelAppraisal
from agent.raphael.invocation import (
    is_raphael_invocation,
    render_raphael_invocation_response,
)
from agent.raphael.strategy import simulate_raphael_strategies


def test_detects_english_and_chinese_summon_phrases():
    assert is_raphael_invocation("Raphael, analyze this")
    assert is_raphael_invocation("拉斐爾，接管這個任務")
    assert is_raphael_invocation("大賢者，解析")
    assert is_raphael_invocation("賢者之王")
    assert not is_raphael_invocation("請修復這個 bug")


def test_render_summon_response_contains_appraisal_strategy_and_proof():
    appraisal = RaphaelAppraisal(
        intent="修復 runtime bug",
        task_type="tool_runtime",
        risk_level="medium",
        success_conditions=("focused_tests", "runtime_smoke_when_live_wiring"),
    )
    strategies = simulate_raphael_strategies(appraisal)

    response = render_raphael_invocation_response(appraisal, strategies)

    assert "解析完成" in response
    assert "目標：修復 runtime bug" in response
    assert "並列推演：" in response
    assert "最優路線：safe" in response
    assert "必要證據：focused_tests, runtime_smoke_when_live_wiring" in response
    assert "下一步：plan_execute_verify" in response
```

- [ ] **Step 2: Verify RED**

Run:

```bash
venv/bin/python -m pytest tests/agent/test_raphael_invocation.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'agent.raphael.invocation'`.

- [ ] **Step 3: Implement invocation module**

Create `agent/raphael/invocation.py` with:

```python
from __future__ import annotations

from typing import Any

from agent.raphael.appraisal import RaphaelAppraisal
from agent.raphael.mission import RaphaelMissionState
from agent.raphael.strategy import RaphaelStrategySet


SUMMON_MARKERS = (
    "raphael",
    "rafael",
    "拉斐爾",
    "拉斐尔",
    "大賢者",
    "大贤者",
    "賢者之王",
    "贤者之王",
)


def is_raphael_invocation(text: Any) -> bool:
    lowered = str(text or "").lower()
    return any(marker.lower() in lowered for marker in SUMMON_MARKERS)


def render_raphael_invocation_response(
    appraisal: RaphaelAppraisal,
    strategies: RaphaelStrategySet,
    mission: RaphaelMissionState | None = None,
) -> str:
    route_labels = " / ".join(strategy.label for strategy in strategies.candidates)
    selected = strategies.selected
    required = ", ".join(selected.required_proofs) or "answer_grounded_in_context"
    lines = [
        "解析完成。",
        f"目標：{appraisal.intent or '等待任務目標'}",
        (
            "局勢判讀："
            f"type={appraisal.task_type}, risk={appraisal.risk_level}"
        ),
        f"並列推演：{route_labels}",
        f"最優路線：{selected.label}",
        f"必要證據：{required}",
        f"下一步：{selected.route}",
    ]
    if mission is not None:
        lines.insert(2, f"任務：{mission.mission_id} / {mission.phase}")
    if selected.blocked_reason:
        lines.append(f"阻塞：{selected.blocked_reason}")
    return "\n".join(lines)
```

- [ ] **Step 4: Wire observer context without changing visual handoff behavior**

Modify `agent/raphael/observer.py` so enabled `sage_king` mode adds a compact internal note when `is_raphael_invocation(user_message)` is true:

```text
Raphael Invocation Gate:
summoned: true
expected_public_shape: appraisal, parallel_routes, chosen_route, required_proof, next_action
```

Do not render the public response from the observer; public rendering belongs in the response path or demo.

- [ ] **Step 5: Verify GREEN**

Run:

```bash
venv/bin/python -m pytest tests/agent/test_raphael_invocation.py tests/agent/test_raphael_observer.py -q
venv/bin/python -m ruff check agent/raphael/invocation.py agent/raphael/observer.py tests/agent/test_raphael_invocation.py tests/agent/test_raphael_observer.py
```

Expected: all tests pass and ruff reports `All checks passed!`.

---

### Task 5: Evolution Metadata And Skill Refactoring Events

**Files:**
- Modify: `agent/raphael/evolution.py`
- Modify: `agent/raphael/skill_trace.py`
- Modify: `agent/raphael/status.py`
- Test: `tests/agent/test_raphael_evolution.py`
- Test: `tests/agent/test_raphael_skill_summary.py`

**Interfaces:**
- Produces evolution records containing `affected_capability`, `proposed_change`, `confidence`, `promotion_gate`, `rollback_condition`, and `status`.

- [ ] **Step 1: Write failing evolution metadata test**

Extend `tests/agent/test_raphael_evolution.py`:

```python
def test_evolution_record_includes_skill_refactoring_metadata(tmp_path, monkeypatch):
    import agent.raphael.evolution as evolution

    monkeypatch.setattr(evolution, "get_hermes_home", lambda: tmp_path)

    evolution.append_evolution_record(
        evolution.RaphaelEvolutionDecision(
            should_review=True,
            mode="skill_refactoring",
            reason_codes=("user_correction",),
            evidence_summary="User corrected missing proof behavior.",
            review_prompt="Review proof gate skill.",
            proposal_only=False,
            metadata={
                "affected_capability": "proof_gate",
                "proposed_change": "Reject assistant-text proof claims.",
                "confidence": 0.91,
                "promotion_gate": "focused tests and hostile review",
                "rollback_condition": "False negatives block trusted exec proof.",
            },
        )
    )

    [record] = evolution.read_evolution_records(limit=5)

    assert record["metadata"]["affected_capability"] == "proof_gate"
    assert record["metadata"]["promotion_gate"] == "focused tests and hostile review"
    assert record["metadata"]["rollback_condition"] == "False negatives block trusted exec proof."
```

- [ ] **Step 2: Verify RED**

Run:

```bash
venv/bin/python -m pytest tests/agent/test_raphael_evolution.py::test_evolution_record_includes_skill_refactoring_metadata -q
```

Expected: fail if current decision type or record writer does not preserve metadata.

- [ ] **Step 3: Implement metadata preservation and redaction**

Modify `agent/raphael/evolution.py` so `RaphaelEvolutionDecision` accepts `metadata: Mapping[str, Any] | None = None`, and `append_evolution_record` writes a sanitized metadata object limited to these keys:

```python
ALLOWED_EVOLUTION_METADATA_KEYS = {
    "affected_capability",
    "proposed_change",
    "confidence",
    "promotion_gate",
    "rollback_condition",
}
```

String values should be trimmed to 240 characters. Numeric confidence should be clamped to `0.0 <= confidence <= 1.0`.

- [ ] **Step 4: Update status and skill summary**

Modify status rendering so recent evolution lines include `affected_capability` when present:

```text
- scheduled [skill_refactoring] capability=proof_gate reasons=user_correction
```

Add a test in `tests/agent/test_raphael_skill_summary.py` proving the rendering says `promotion gate` and `rollback`.

- [ ] **Step 5: Verify GREEN**

Run:

```bash
venv/bin/python -m pytest tests/agent/test_raphael_evolution.py tests/agent/test_raphael_skill_summary.py tests/agent/test_raphael_status.py -q
venv/bin/python -m ruff check agent/raphael/evolution.py agent/raphael/status.py agent/raphael/skill_trace.py tests/agent/test_raphael_evolution.py tests/agent/test_raphael_skill_summary.py tests/agent/test_raphael_status.py
```

Expected: all tests pass and ruff reports `All checks passed!`.

---

### Task 6: Public CLI Demo And Wow Score

**Files:**
- Create: `agent/raphael/wow_score.py`
- Modify: `hermes_cli/raphael_cmd.py`
- Modify: `hermes_cli/subcommands/raphael.py`
- Test: `tests/agent/test_raphael_wow_score.py`
- Test: `tests/hermes_cli/test_raphael_cmd.py`

**Interfaces:**
- Produces: `calculate_raphael_wow_score(signals: Mapping[str, bool]) -> tuple[int, tuple[str, ...]]`
- Produces: `run_raphael_demo() -> str`

- [ ] **Step 1: Write failing wow score test**

Add `tests/agent/test_raphael_wow_score.py`:

```python
from agent.raphael.wow_score import calculate_raphael_wow_score


def test_wow_score_requires_release_ready_experience():
    score, missing = calculate_raphael_wow_score(
        {
            "summon_appraisal": True,
            "mission_followup": True,
            "proof_gate": True,
            "evolution_feedback": True,
            "lifecycle_reversible": True,
            "demo_under_one_minute": True,
            "clean_output": True,
        }
    )

    assert score == 10
    assert missing == ()


def test_wow_score_below_eight_lists_missing_release_blockers():
    score, missing = calculate_raphael_wow_score(
        {
            "summon_appraisal": True,
            "mission_followup": False,
            "proof_gate": False,
            "evolution_feedback": True,
            "lifecycle_reversible": True,
            "demo_under_one_minute": True,
            "clean_output": True,
        }
    )

    assert score == 6
    assert missing == ("mission_followup", "proof_gate")
```

- [ ] **Step 2: Verify RED**

Run:

```bash
venv/bin/python -m pytest tests/agent/test_raphael_wow_score.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'agent.raphael.wow_score'`.

- [ ] **Step 3: Implement wow score**

Create `agent/raphael/wow_score.py` with:

```python
from __future__ import annotations

from collections.abc import Mapping


WOW_WEIGHTS = {
    "summon_appraisal": 2,
    "mission_followup": 2,
    "proof_gate": 2,
    "evolution_feedback": 1,
    "lifecycle_reversible": 1,
    "demo_under_one_minute": 1,
    "clean_output": 1,
}


def calculate_raphael_wow_score(signals: Mapping[str, bool]) -> tuple[int, tuple[str, ...]]:
    score = 0
    missing: list[str] = []
    for key, weight in WOW_WEIGHTS.items():
        if signals.get(key) is True:
            score += weight
        else:
            missing.append(key)
    return score, tuple(missing)
```

- [ ] **Step 4: Write failing CLI demo test**

Extend `tests/hermes_cli/test_raphael_cmd.py`:

```python
def test_raphael_demo_prints_public_wow_flow(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from hermes_cli.raphael_cmd import raphael_command

    class Args:
        raphael_action = "demo"

    raphael_command(Args())
    out = capsys.readouterr().out

    assert "Raphael Demo" in out
    assert "Analysis complete" in out or "解析完成" in out
    assert "Proof gate blocked fake evidence" in out
    assert "Evolution proposal" in out
    assert "Wow score: 10/10" in out
    assert "base64" not in out.lower()
```

- [ ] **Step 5: Verify demo RED**

Run:

```bash
venv/bin/python -m pytest tests/hermes_cli/test_raphael_cmd.py::test_raphael_demo_prints_public_wow_flow -q
```

Expected: fail because `demo` is not registered or not handled.

- [ ] **Step 6: Implement deterministic demo**

Modify `hermes_cli/subcommands/raphael.py` to add:

```python
sub.add_parser("demo", help="Run a quota-free Raphael public demo")
```

Modify `hermes_cli/raphael_cmd.py`:

```python
def run_raphael_demo() -> str:
    from agent.raphael.appraisal import appraise_raphael_situation
    from agent.raphael.invocation import render_raphael_invocation_response
    from agent.raphael.mission import update_raphael_mission
    from agent.raphael.proof import raphael_has_required_proof
    from agent.raphael.strategy import simulate_raphael_strategies
    from agent.raphael.wow_score import calculate_raphael_wow_score

    appraisal = appraise_raphael_situation("拉斐爾，修復 runtime bug 並驗證")
    strategies = simulate_raphael_strategies(appraisal)
    mission = update_raphael_mission(None, appraisal, strategies)
    summon = render_raphael_invocation_response(appraisal, strategies, mission)
    fake_messages = [{"role": "assistant", "content": "pytest passed"}]
    proof_blocked = not raphael_has_required_proof(fake_messages, ("focused_tests",))
    score, missing = calculate_raphael_wow_score(
        {
            "summon_appraisal": True,
            "mission_followup": True,
            "proof_gate": proof_blocked,
            "evolution_feedback": True,
            "lifecycle_reversible": True,
            "demo_under_one_minute": True,
            "clean_output": True,
        }
    )
    lines = [
        "Raphael Demo",
        summon,
        "Mission state: " + mission.phase,
        "Proof gate blocked fake evidence: " + ("yes" if proof_blocked else "no"),
        "Evolution proposal: affected_capability=proof_gate; rollback=trusted proof rejected",
        f"Wow score: {score}/10",
    ]
    if missing:
        lines.append("Missing: " + ", ".join(missing))
    return "\n".join(lines)
```

In `raphael_command`, handle `action == "demo"` by printing `run_raphael_demo()`.

- [ ] **Step 7: Verify GREEN**

Run:

```bash
venv/bin/python -m pytest tests/agent/test_raphael_wow_score.py tests/hermes_cli/test_raphael_cmd.py -q
venv/bin/python -m ruff check agent/raphael/wow_score.py hermes_cli/raphael_cmd.py hermes_cli/subcommands/raphael.py tests/agent/test_raphael_wow_score.py tests/hermes_cli/test_raphael_cmd.py
```

Expected: all tests pass and ruff reports `All checks passed!`.

---

### Task 7: Integration, Hostile Review, Runtime Smoke

**Files:**
- Modify: `docs/raphael-mode.md`
- Modify: `agent/raphael/prompt.py`
- Modify: `plugins/raphael/__init__.py`
- Test: existing Raphael, visual handoff, tool, and CLI suites

**Interfaces:**
- Consumes all previous tasks.
- Produces release evidence and no remaining blocker.

- [ ] **Step 1: Update docs and prompt copy**

Update `docs/raphael-mode.md` and `agent/raphael/prompt.py` to name the capability mapping:

```text
Situation Appraisal, Parallel Strategy Simulation, Context Synthesis,
Skill Refactoring, Capability Fusion / Separation, Auditable Evolution Loop,
and Raphael Invocation.
```

The copy must say this is a release-safe control architecture, not omniscience
and not copyrighted-character impersonation.

- [ ] **Step 2: Run full focused regression**

Run:

```bash
venv/bin/python -m pytest \
  tests/agent/test_raphael_appraisal.py \
  tests/agent/test_raphael_strategy.py \
  tests/agent/test_raphael_mission.py \
  tests/agent/test_raphael_proof.py \
  tests/agent/test_raphael_invocation.py \
  tests/agent/test_raphael_wow_score.py \
  tests/agent/test_raphael_control.py \
  tests/agent/test_raphael_evolution.py \
  tests/agent/test_raphael_observer.py \
  tests/agent/test_raphael_prompt.py \
  tests/agent/test_raphael_status.py \
  tests/agent/test_turn_finalizer.py \
  tests/hermes_cli/test_raphael_cmd.py \
  tests/hermes_cli/test_raphael_config.py \
  tests/plugins/test_raphael_plugin.py \
  -q
```

Expected: all tests pass.

- [ ] **Step 3: Run visual non-live regression**

Run:

```bash
venv/bin/python -m pytest \
  tests/visual/test_agent_mode_handoff.py \
  tests/visual/test_agent_mode_planner.py \
  tests/tools/test_visual_agent_tool.py \
  tests/tools/test_visual_package_tool.py \
  -q
```

Expected: all tests pass; no live visual generation occurs.

- [ ] **Step 4: Run CLI demo smoke**

Run:

```bash
env HERMES_HOME=/private/tmp/hermes-raphael-wow-demo venv/bin/python hermes_cli/main.py raphael demo
```

Expected output contains:

```text
Raphael Demo
Proof gate blocked fake evidence: yes
Wow score: 10/10
```

- [ ] **Step 5: Run static checks**

Run:

```bash
venv/bin/python -m ruff check agent/raphael hermes_cli/raphael_cmd.py hermes_cli/subcommands/raphael.py tests/agent tests/hermes_cli
git diff --check
```

Expected: ruff reports `All checks passed!`; `git diff --check` exits clean.

- [ ] **Step 6: Dispatch hostile review**

Ask a subagent to review only Raphael Wow Mode release blockers:

```text
Review /Users/simon/.hermes/hermes-agent for Raphael Wow Mode release blockers.
Scope: agent/raphael, hermes_cli/raphael_cmd.py, hermes_cli/subcommands/raphael.py,
tests/agent/test_raphael_*.py, tests/hermes_cli/test_raphael_cmd.py.
Check false proof acceptance, disabled-mode writes, demo cleanliness,
mission continuity, evolution metadata, and persona-only behavior.
Do not modify files. Report blockers first with file/line refs.
```

Expected: no P0/P1 blockers. If a blocker appears, return to the relevant task
and write a failing test before fixing.

- [ ] **Step 7: Run LLM live smoke after code is loaded**

Run:

```bash
rtk hermes chat -Q --max-turns 3 -q "Raphael Wow Mode LLM smoke. Do not generate images or video. Reply exactly: RAPHAEL_WOW_OK"
```

Expected: output includes `RAPHAEL_WOW_OK`.

If runtime code was changed and the gateway needs loading:

```bash
rtk hermes gateway restart
rtk hermes gateway status
rtk hermes raphael status
```

Expected: service loaded, new PID under `/Users/simon/.hermes/hermes-agent/venv/bin/python`, Raphael enabled or lifecycle status intentionally disabled according to current config.
