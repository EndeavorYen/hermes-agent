from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
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

    def __post_init__(self) -> None:
        object.__setattr__(self, "blockers", tuple(self.blockers))
        object.__setattr__(self, "required_proofs", tuple(self.required_proofs))
        if self.updated_at.tzinfo is None:
            object.__setattr__(
                self, "updated_at", self.updated_at.replace(tzinfo=timezone.utc)
            )

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
            required_proofs=tuple(
                str(item) for item in payload.get("required_proofs", ())
            ),
            updated_at=datetime.fromisoformat(str(payload["updated_at"])),
        )


def update_raphael_mission(
    current: RaphaelMissionState | None,
    appraisal: RaphaelAppraisal,
    strategies: RaphaelStrategySet,
) -> RaphaelMissionState:
    mission_id = (
        current.mission_id
        if current is not None and _should_continue_mission(current, appraisal)
        else _new_mission_id(appraisal)
    )
    selected = strategies.selected
    phase = "blocked" if selected.blocked_reason else "strategy_selected"
    return RaphaelMissionState(
        mission_id=mission_id,
        goal=appraisal.intent,
        phase=phase,
        selected_strategy_id=selected.strategy_id,
        active_artifact_id=appraisal.active_artifact_id,
        blockers=appraisal.blockers,
        next_action=selected.route,
        proof_status="blocked" if selected.blocked_reason else "pending",
        required_proofs=selected.required_proofs,
        updated_at=_utc_now(),
    )


def _new_mission_id(appraisal: RaphaelAppraisal) -> str:
    seed = f"{appraisal.intent}|{appraisal.task_type}|{_utc_now().timestamp()}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"mission-{digest}"


def _should_continue_mission(
    current: RaphaelMissionState,
    appraisal: RaphaelAppraisal,
) -> bool:
    if appraisal.active_artifact_id and appraisal.active_artifact_id == current.active_artifact_id:
        return True
    if _looks_like_followup(appraisal.intent):
        return True
    if appraisal.task_type not in current.required_proofs and not _task_type_matches_current(
        current,
        appraisal,
    ):
        return False
    return _goal_overlap(current.goal, appraisal.intent) >= 0.34


def _task_type_matches_current(
    current: RaphaelMissionState,
    appraisal: RaphaelAppraisal,
) -> bool:
    if "visual" in appraisal.task_type:
        return current.active_artifact_id is not None
    if appraisal.task_type in {"general_conversation", "chitchat"}:
        return False
    if any(proof in current.required_proofs for proof in appraisal.success_conditions):
        return True
    if appraisal.task_type == "tool_runtime" and any(
        proof in current.required_proofs
        for proof in ("focused_tests", "runtime_smoke_when_live_wiring", "diff_hygiene")
    ):
        return True
    return False


def _looks_like_followup(value: str) -> bool:
    compact = re.sub(r"\s+", "", str(value or "").lower())
    markers = (
        "再",
        "繼續",
        "继续",
        "補",
        "补",
        "同一",
        "上一",
        "剛剛",
        "刚刚",
        "current",
        "followup",
        "follow-up",
        "same task",
    )
    return any(marker in compact for marker in markers)


def _goal_overlap(left: str, right: str) -> float:
    left_tokens = _goal_tokens(left)
    right_tokens = _goal_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _goal_tokens(value: str) -> set[str]:
    text = str(value or "").lower()
    ascii_tokens = set(re.findall(r"[a-z0-9_]{3,}", text))
    cjk_chars = set(re.findall(r"[\u4e00-\u9fff]", text))
    return ascii_tokens | cjk_chars


__all__ = ["RaphaelMissionState", "update_raphael_mission"]
