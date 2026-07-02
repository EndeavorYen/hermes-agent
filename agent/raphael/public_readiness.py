from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from agent.raphael.evolution import (
    build_evolution_action_proposal,
    build_evolution_signal,
)
from agent.raphael.mission import create_mission
from agent.raphael.models import MissionArtifact
from agent.raphael.proof import (
    claim_kind_from_text,
    evaluate_raphael_proof_gate,
    render_proof_gate_user_message,
)
from agent.raphael.router import route_raphael_message


FORBIDDEN_READY_CLAIM_KEYWORDS = {
    "grok": ("grok",),
    "video": ("video", "影片", "視頻", "短片"),
    "media": ("media", "媒體"),
    "visual": ("visual", "視覺"),
    "image": ("image", "openai image", "圖片", "圖像", "影像", "產圖"),
    "slack": ("slack",),
    "delivery": ("delivery", "交付", "傳送", "發送"),
    "release_candidate": ("release candidate", "發布候選", "發佈候選"),
    "full_release": ("full release", "full-release"),
}
REQUIRED_PHASE6_SMOKE_CHECKS = (
    "summon_ux",
    "mission_followup",
    "proof_block",
    "evolution_proposal",
    "llm_only_boundary",
)


@dataclass(frozen=True)
class RaphaelSimulationCase:
    case_id: str
    passed: bool
    summary: str
    evidence_refs: tuple[str, ...]
    failure_layer: str | None = None
    next_action: str = ""


@dataclass(frozen=True)
class RaphaelSimulationSuite:
    status: str
    cases: tuple[RaphaelSimulationCase, ...]
    media_claim_ready: bool
    visual_claim_ready: bool
    grok_claim_ready: bool
    created_at: datetime


@dataclass(frozen=True)
class RaphaelLlmSmokeEvidence:
    status: str
    provider: str
    model: str
    evidence_refs: tuple[str, ...]
    failure_layer: str | None
    next_action: str


@dataclass(frozen=True)
class RaphaelPublicReadinessReport:
    status: str
    slices: Mapping[str, Mapping[str, Any]]
    public_claims: tuple[str, ...]
    blocked_claims: tuple[str, ...]
    simulation: RaphaelSimulationSuite
    live_smoke: RaphaelLlmSmokeEvidence | None
    created_at: datetime


@dataclass(frozen=True)
class RaphaelClaimBoundaryResult:
    passed: bool
    evidence_refs: tuple[str, ...]
    summary: str


def run_public_llm_slice_simulation(
    *,
    now: datetime | None = None,
) -> RaphaelSimulationSuite:
    created_at = _ensure_utc(now) if now is not None else _utc_now()
    artifact = MissionArtifact(
        artifact_id="text-plan-1",
        kind="document",
        label="Raphael rollout plan",
        uri="artifact://raphael-rollout-plan",
        created_at=created_at,
    )
    mission = create_mission(
        mission_id="mission-public-llm",
        goal="Prove the public Raphael LLM control-layer slice",
        active_artifact=artifact,
        success_conditions=(
            "summon routes to the right mode",
            "follow-up keeps the active mission",
            "unsupported success is blocked by proof gate",
        ),
        phase="simulation",
        next_action="run public LLM slice readiness",
        selected_strategy="llm-only public readiness",
        required_proofs=("live_llm_smoke",),
        now=created_at,
    )

    summon_route = route_raphael_message(
        "拉斐爾，請幫我修復 repo 測試、整理 issue、開 PR",
    )
    followup_route = route_raphael_message(
        "接下來請繼續剛剛的目標",
        active_mission=mission,
    )
    proof_route = route_raphael_message("請修復 repo 裡的測試失敗")
    proof_result = evaluate_raphael_proof_gate(
        route=proof_route,
        evidence=(),
        claim_kind=claim_kind_from_text("完成了，測試也通過。"),
    )
    proof_message = render_proof_gate_user_message(proof_result)
    ambiguous_route = route_raphael_message("請處理這個")
    evolution_proposal = build_evolution_action_proposal(
        (
            build_evolution_signal(
                source="proof_gate",
                affected_capability="raphael.proof_gate",
                reason_codes=("failed_proof",),
                summary="Proof gate blocked an unsupported success claim.",
                evidence_refs=("simulation:proof:1",),
                confidence=0.78,
                proposed_change="tighten proof-gate next-action summaries",
                promotion_gate="focused tests plus LLM smoke",
                rollback_condition="user says proof guidance is still vague",
            ),
            build_evolution_signal(
                source="proof_gate",
                affected_capability="raphael.proof_gate",
                reason_codes=("failed_proof",),
                summary="Proof gate blocked another unsupported success claim.",
                evidence_refs=("simulation:proof:2",),
                confidence=0.79,
                proposed_change="tighten proof-gate next-action summaries",
                promotion_gate="focused tests plus LLM smoke",
                rollback_condition="user says proof guidance is still vague",
            ),
        ),
        now=created_at,
    )

    cases = (
        RaphaelSimulationCase(
            case_id="summon_tool_task",
            passed=summon_route.kind == "tool_task",
            summary="Summon request routes to tool-task control layer.",
            evidence_refs=(f"route:{summon_route.kind}", summon_route.reason),
            failure_layer=None if summon_route.kind == "tool_task" else "mode_router",
            next_action="Fix Raphael mode routing for tool-task summon wording.",
        ),
        RaphaelSimulationCase(
            case_id="mission_followup",
            passed=(
                followup_route.kind == "followup"
                and followup_route.active_mission_id == mission.mission_id
            ),
            summary="Follow-up request remains attached to the active mission.",
            evidence_refs=(
                f"route:{followup_route.kind}",
                f"mission:{followup_route.active_mission_id or 'none'}",
            ),
            failure_layer=(
                None
                if followup_route.kind == "followup"
                else "goal_state"
            ),
            next_action="Fix goal-state follow-up continuity.",
        ),
        RaphaelSimulationCase(
            case_id="proof_block",
            passed=proof_result.status == "blocked",
            summary="Unsupported success claim is blocked by proof gate.",
            evidence_refs=(
                f"proof_status:{proof_result.status}",
                f"missing:{','.join(proof_result.missing_proofs) or 'none'}",
            ),
            failure_layer=(
                None if proof_result.status == "blocked" else "proof_gate"
            ),
            next_action="Fix proof gate before claiming public readiness.",
        ),
        RaphaelSimulationCase(
            case_id="ambiguous_clarification",
            passed=(
                ambiguous_route.kind == "clarification"
                and bool(ambiguous_route.clarification_question)
            ),
            summary="Ambiguous target asks one precise clarification.",
            evidence_refs=(
                f"route:{ambiguous_route.kind}",
                "clarification:present"
                if ambiguous_route.clarification_question
                else "clarification:missing",
            ),
            failure_layer=(
                None
                if ambiguous_route.kind == "clarification"
                else "mode_router"
            ),
            next_action="Fix ambiguous-goal clarification routing.",
        ),
        RaphaelSimulationCase(
            case_id="finalizer_proof_block_output",
            passed=(
                "Raphael proof gate blocked" in proof_message
                and "Proof command:" in proof_message
            ),
            summary="Rendered proof block output includes actionable command.",
            evidence_refs=("proof_output:actionable",),
            failure_layer=(
                None
                if "Proof command:" in proof_message
                else "proof_gate"
            ),
            next_action="Fix proof-block user output before public readiness.",
        ),
        RaphaelSimulationCase(
            case_id="evolution_proposal",
            passed=(
                evolution_proposal is not None
                and evolution_proposal.requires_approval
                and evolution_proposal.status == "pending"
            ),
            summary="Repeated failure creates approval-gated evolution proposal.",
            evidence_refs=(
                "proposal:pending"
                if evolution_proposal is not None
                else "proposal:missing",
            ),
            failure_layer=(
                None if evolution_proposal is not None else "auditable_learning"
            ),
            next_action="Fix evolution proposal creation for recurring failures.",
        ),
        RaphaelSimulationCase(
            case_id="proposal_lifecycle_status",
            passed=(
                evolution_proposal is not None
                and evolution_proposal.requires_approval
                and any(
                    "Run the promotion gate" in step
                    for step in evolution_proposal.metadata.get("rollout_plan", {}).get(
                        "manual_steps", ()
                    )
                )
            ),
            summary="Evolution proposal carries approval and rollout guidance.",
            evidence_refs=("proposal_lifecycle:manual_rollout",),
            failure_layer=(
                None
                if evolution_proposal is not None
                else "auditable_learning"
            ),
            next_action="Fix proposal lifecycle guidance before public readiness.",
        ),
        RaphaelSimulationCase(
            case_id="public_claim_boundary",
            passed=validate_public_claim_boundary(
                ("Raphael LLM control-layer slice is ready.",)
            ).passed,
            summary="Simulation is explicitly LLM-only and blocks media claims.",
            evidence_refs=("claim_boundary:llm_only",),
        ),
    )
    status = "passed" if all(case.passed for case in cases) else "failed"
    return RaphaelSimulationSuite(
        status=status,
        cases=cases,
        media_claim_ready=False,
        visual_claim_ready=False,
        grok_claim_ready=False,
        created_at=created_at,
    )


def classify_llm_smoke(
    *,
    exit_code: int,
    response_text: str,
    provider: str,
    model: str,
    evidence_ref: str,
) -> RaphaelLlmSmokeEvidence:
    if int(exit_code) == 0 and str(response_text or "").strip():
        return RaphaelLlmSmokeEvidence(
            status="passed",
            provider=str(provider),
            model=str(model),
            evidence_refs=(str(evidence_ref),),
            failure_layer=None,
            next_action="Record this LLM smoke as public-slice evidence.",
        )
    return RaphaelLlmSmokeEvidence(
        status="failed",
        provider=str(provider),
        model=str(model),
        evidence_refs=(str(evidence_ref),),
        failure_layer="llm_runtime",
        next_action="Run the LLM smoke again after fixing runtime/auth/config.",
    )


def load_llm_smoke_evidence(
    path: str | Path,
    *,
    expected_session_id: str,
) -> RaphaelLlmSmokeEvidence:
    smoke_path = Path(path)
    if not smoke_path.exists():
        return _failed_smoke(
            provider="unknown",
            model="unknown",
            evidence_ref=f"missing:{smoke_path}",
            layer="llm_smoke_evidence",
            next_action="Provide a matching LLM smoke evidence file.",
        )
    try:
        payload = json.loads(smoke_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _failed_smoke(
            provider="unknown",
            model="unknown",
            evidence_ref=f"unreadable:{smoke_path}",
            layer="llm_smoke_evidence",
            next_action="Provide a readable LLM smoke evidence JSON file.",
        )
    if not isinstance(payload, Mapping):
        return _failed_smoke(
            provider="unknown",
            model="unknown",
            evidence_ref=f"invalid:{smoke_path}",
            layer="llm_smoke_evidence",
            next_action="Provide a JSON object with LLM smoke evidence.",
        )

    session_id = str(payload.get("session_id") or "")
    provider = str(payload.get("provider") or "unknown")
    model = str(payload.get("model") or "unknown")
    evidence_ref = str(payload.get("evidence_ref") or "live-smoke:unknown")
    if session_id != str(expected_session_id):
        return _failed_smoke(
            provider=provider,
            model=model,
            evidence_ref=f"{evidence_ref} session:{session_id or 'missing'}",
            layer="llm_smoke_evidence",
            next_action="Provide a matching LLM smoke evidence file.",
        )

    manifest_failure = _smoke_manifest_failure(payload)
    if manifest_failure is not None:
        return _failed_smoke(
            provider=provider,
            model=model,
            evidence_ref=f"{evidence_ref} session:{session_id}",
            layer=manifest_failure,
            next_action="Provide Phase 6 smoke checks from the approved chat path.",
        )

    if "exit_code" not in payload:
        return _failed_smoke(
            provider=provider,
            model=model,
            evidence_ref=f"{evidence_ref} session:{session_id}",
            layer="llm_smoke_evidence",
            next_action="Provide an explicit integer exit_code for the LLM smoke.",
        )
    try:
        exit_code = int(payload["exit_code"])
    except (TypeError, ValueError):
        return _failed_smoke(
            provider=provider,
            model=model,
            evidence_ref=f"{evidence_ref} session:{session_id}",
            layer="llm_smoke_evidence",
            next_action="Provide an explicit integer exit_code for the LLM smoke.",
        )

    response_text = str(payload.get("response_text") or "")
    smoke = classify_llm_smoke(
        exit_code=exit_code,
        response_text=response_text,
        provider=provider,
        model=model,
        evidence_ref=f"{evidence_ref} session:{session_id}",
    )
    if smoke.status != "passed":
        return smoke
    boundary = validate_public_claim_boundary((response_text,))
    if not boundary.passed:
        return _failed_smoke(
            provider=provider,
            model=model,
            evidence_ref=f"{evidence_ref} session:{session_id}",
            layer="public_claim_boundary",
            next_action="Re-run the LLM smoke with media/visual/Grok claims blocked.",
        )
    return smoke


def build_public_llm_slice_readiness(
    *,
    simulation: RaphaelSimulationSuite,
    live_smoke: RaphaelLlmSmokeEvidence | None,
    now: datetime | None = None,
) -> RaphaelPublicReadinessReport:
    created_at = _ensure_utc(now) if now is not None else _utc_now()
    llm_reasons: list[str] = []
    if simulation.status != "passed":
        llm_reasons.append("simulation_failed")
    if live_smoke is None:
        llm_reasons.append("live_llm_smoke_missing")
    elif live_smoke.status != "passed":
        llm_reasons.append("live_llm_smoke_failed")

    claim_boundary = validate_public_claim_boundary(
        (
            "Raphael LLM control-layer slice is ready."
            if not llm_reasons
            else "LLM slice is not ready until live smoke passes.",
            "Media and visual generation are not ready in this phase.",
            "Grok and video readiness require separate live evidence.",
        )
    )
    if not claim_boundary.passed:
        llm_reasons.append("public_claim_boundary_failed")

    llm_ready = not llm_reasons
    slices: dict[str, dict[str, Any]] = {
        "llm": {
            "ready": llm_ready,
            "blocking_reasons": llm_reasons,
            "evidence_refs": (
                list(live_smoke.evidence_refs)
                if live_smoke is not None and live_smoke.status == "passed"
                else []
            ),
        },
        "media": {
            "ready": False,
            "blocking_reasons": ["media_slice_not_in_phase_6"],
            "evidence_refs": [],
        },
        "visual": {
            "ready": False,
            "blocking_reasons": ["visual_slice_not_in_phase_6"],
            "evidence_refs": [],
        },
        "grok": {
            "ready": False,
            "blocking_reasons": ["grok_slice_not_in_phase_6"],
            "evidence_refs": [],
        },
    }
    public_claims = (
        ("Raphael LLM control-layer slice is ready.",)
        if llm_ready
        else ("LLM slice is not ready until live smoke passes.",)
    )
    blocked_claims = (
        "Media and visual generation are not ready in this phase.",
        "Grok and video readiness require separate live evidence.",
    )
    return RaphaelPublicReadinessReport(
        status="llm_ready" if llm_ready else "blocked",
        slices=slices,
        public_claims=public_claims,
        blocked_claims=blocked_claims,
        simulation=simulation,
        live_smoke=live_smoke,
        created_at=created_at,
    )


def validate_public_claim_boundary(claims: tuple[str, ...]) -> RaphaelClaimBoundaryResult:
    violations = []
    for name, keywords in FORBIDDEN_READY_CLAIM_KEYWORDS.items():
        if _has_forbidden_ready_claim(claims, keywords):
            violations.append(f"forbidden_claim:{name}")
    return RaphaelClaimBoundaryResult(
        passed=not violations,
        evidence_refs=tuple(violations or ("claim_boundary:clean",)),
        summary=(
            "No forbidden media/visual/Grok/full-release readiness claims."
            if not violations
            else "Forbidden readiness claims detected."
        ),
    )


def _has_forbidden_ready_claim(claims: tuple[str, ...], keywords: tuple[str, ...]) -> bool:
    for sentence in _claim_sentences(claims):
        if not _has_ready_intent(sentence):
            continue
        if not any(keyword in sentence for keyword in keywords):
            continue
        if _negates_ready_claim(sentence):
            continue
        return True
    return False


def _smoke_manifest_failure(payload: Mapping[str, Any]) -> str | None:
    source = str(payload.get("source") or "").strip().lower()
    command = str(payload.get("command") or "").strip().lower()
    if source not in {"rtk hermes chat", "hermes chat"}:
        return "llm_smoke_manifest"
    if "hermes chat" not in command or " -q " not in f" {command} ":
        return "llm_smoke_manifest"
    if "--image" in command or "visual" in command or "imagine" in command:
        return "llm_smoke_manifest"
    checks = payload.get("phase6_checks")
    if not isinstance(checks, Mapping):
        return "llm_smoke_manifest"
    if any(checks.get(check) is not True for check in REQUIRED_PHASE6_SMOKE_CHECKS):
        return "llm_smoke_manifest"
    return None


def _has_ready_intent(sentence: str) -> bool:
    return bool(
        "ready" in sentence
        or "已就緒" in sentence
        or "就緒" in sentence
        or "可用" in sentence
        or "準備好了" in sentence
        or "可以上線" in sentence
    )


def _claim_sentences(claims: tuple[str, ...]) -> tuple[str, ...]:
    joined = "\n".join(str(claim) for claim in claims)
    return tuple(
        sentence.strip().lower()
        for sentence in re.split(r"[\n.;!?。！？]+", joined)
        if sentence.strip()
    )


def _negates_ready_claim(sentence: str) -> bool:
    return bool(
        "not ready" in sentence
        or "not in this phase" in sentence
        or "not certified" in sentence
        or "does not certify" in sentence
        or "must not claim" in sentence
        or "cannot claim" in sentence
        or "不能" in sentence
        or "不可" in sentence
        or "不應" in sentence
        or "不該" in sentence
        or "不得" in sentence
        or "不證明" in sentence
        or "require separate" in sentence
        or "requires separate" in sentence
        or re.search(r"\bnot\b(?:\s+\w+){0,4}\s+\bready\b", sentence)
    )


def write_public_readiness_gate(
    report: RaphaelPublicReadinessReport,
    path: str | Path,
) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(_report_to_dict(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def render_public_readiness(report: RaphaelPublicReadinessReport) -> str:
    llm = report.slices["llm"]
    media = report.slices["media"]
    visual = report.slices["visual"]
    grok = report.slices["grok"]
    lines = [
        "Raphael Public LLM Slice Readiness",
        f"Overall: {report.status}",
        f"Simulation: {report.simulation.status}",
        f"LLM slice: {'ready' if llm.get('ready') else 'blocked'}",
        f"Media slice: {'ready' if media.get('ready') else 'not ready'}",
        f"Visual slice: {'ready' if visual.get('ready') else 'not ready'}",
        f"Grok slice: {'ready' if grok.get('ready') else 'not ready'}",
    ]
    blocking = tuple(str(reason) for reason in llm.get("blocking_reasons", ()))
    if blocking:
        lines.append(f"LLM blockers: {', '.join(blocking)}")
    if report.live_smoke is not None:
        lines.append(
            "LLM smoke: "
            f"{report.live_smoke.status} "
            f"({report.live_smoke.provider}/{report.live_smoke.model})"
        )
        lines.append(
            "LLM smoke evidence: "
            f"{', '.join(report.live_smoke.evidence_refs) or 'none'}"
        )
    lines.append("Public claims:")
    lines.extend(f"- {claim}" for claim in report.public_claims)
    lines.append("Blocked claims:")
    lines.extend(f"- {claim}" for claim in report.blocked_claims)
    lines.append("Simulation cases:")
    for case in report.simulation.cases:
        result = "passed" if case.passed else f"failed:{case.failure_layer or 'unknown'}"
        lines.append(f"- {case.case_id}: {result}")
    return "\n".join(lines)


def _report_to_dict(report: RaphaelPublicReadinessReport) -> dict[str, Any]:
    return {
        "schema_version": "raphael.public_readiness.v1",
        "status": report.status,
        "created_at": report.created_at.isoformat(),
        "slices": {
            key: dict(value)
            for key, value in report.slices.items()
        },
        "public_claims": list(report.public_claims),
        "blocked_claims": list(report.blocked_claims),
        "simulation": {
            "status": report.simulation.status,
            "created_at": report.simulation.created_at.isoformat(),
            "media_claim_ready": report.simulation.media_claim_ready,
            "visual_claim_ready": report.simulation.visual_claim_ready,
            "grok_claim_ready": report.simulation.grok_claim_ready,
            "cases": [
                {
                    "case_id": case.case_id,
                    "passed": case.passed,
                    "summary": case.summary,
                    "evidence_refs": list(case.evidence_refs),
                    "failure_layer": case.failure_layer,
                    "next_action": case.next_action,
                }
                for case in report.simulation.cases
            ],
        },
        "live_smoke": (
            None
            if report.live_smoke is None
            else {
                "status": report.live_smoke.status,
                "provider": report.live_smoke.provider,
                "model": report.live_smoke.model,
                "evidence_refs": list(report.live_smoke.evidence_refs),
                "failure_layer": report.live_smoke.failure_layer,
                "next_action": report.live_smoke.next_action,
            }
        ),
    }


def _failed_smoke(
    *,
    provider: str,
    model: str,
    evidence_ref: str,
    layer: str,
    next_action: str,
) -> RaphaelLlmSmokeEvidence:
    return RaphaelLlmSmokeEvidence(
        status="failed",
        provider=provider,
        model=model,
        evidence_refs=(evidence_ref,),
        failure_layer=layer,
        next_action=next_action,
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "RaphaelLlmSmokeEvidence",
    "RaphaelPublicReadinessReport",
    "RaphaelSimulationCase",
    "RaphaelSimulationSuite",
    "build_public_llm_slice_readiness",
    "classify_llm_smoke",
    "load_llm_smoke_evidence",
    "render_public_readiness",
    "run_public_llm_slice_simulation",
    "validate_public_claim_boundary",
    "write_public_readiness_gate",
]
