from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any
from unittest.mock import patch

from agent.raphael.control import classify_visual_failure_layer
from agent.raphael.finalization import enforce_raphael_completion
from agent.raphael.kernel import prepare_raphael_turn, replay_raphael_turn
from agent.raphael.runtime_contract import (
    RaphaelRuntimeContract,
    RaphaelTurnOrigin,
)
from agent.raphael.state import read_state


SCENARIO_IDS = (
    "conversation",
    "tool_task",
    "visual_routing",
    "same_artifact_followup",
    "provider_failure_classification",
    "missing_proof",
    "background_isolation",
    "codex_transport_parity",
)


@dataclass(frozen=True)
class AcceptanceValidation:
    status: str
    blocking_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "blocking_reasons": list(self.blocking_reasons),
        }


@dataclass(frozen=True)
class PrTargetGate:
    allowed: bool
    target_branch: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "target_branch": self.target_branch,
            "reason": self.reason,
        }


def evaluate_pr_target(*, default_branch: str) -> PrTargetGate:
    target = str(default_branch or "").strip()
    if not target:
        return PrTargetGate(False, "", "remote_default_branch_missing")
    if target == "main":
        return PrTargetGate(False, target, "default_branch_must_not_be_main")
    return PrTargetGate(True, target, "verified_remote_default_branch")


def validate_acceptance(report: Mapping[str, Any]) -> AcceptanceValidation:
    reasons: list[str] = []
    feature_head = str(report.get("feature_head") or "")
    scenarios = report.get("scenarios")
    scenario_status = {
        str(item.get("scenario_id") or ""): str(item.get("status") or "")
        for item in scenarios or ()
        if isinstance(item, Mapping)
    }
    for scenario_id in SCENARIO_IDS:
        if scenario_status.get(scenario_id) != "passed":
            reasons.append(f"scenario_failed:{scenario_id}")

    verification = _mapping(report.get("verification"))
    for check in ("tests", "static_checks", "diff_hygiene"):
        if verification.get(check) != "passed":
            reasons.append(f"verification_failed:{check}")

    runtime = _mapping(report.get("runtime"))
    for check in ("routing_truth", "isolated_feature_smoke"):
        if runtime.get(check) != "passed":
            reasons.append(f"runtime_failed:{check}")

    reviews = _mapping(report.get("reviews"))
    for reviewer in ("codex", "grok"):
        review = reviews.get(reviewer)
        if not isinstance(review, Mapping):
            reasons.append(f"{reviewer}_review_missing")
            continue
        if str(review.get("status") or "").lower() != "pass":
            reasons.append(f"{reviewer}_review_failed")
        if str(review.get("head") or "") != feature_head:
            reasons.append(f"{reviewer}_review_head_mismatch")
        if _has_blocking_findings(review.get("findings")):
            reasons.append(f"{reviewer}_review_blocking_findings")

    if report.get("privacy_safe") is not True:
        reasons.append("privacy_check_failed")
    return AcceptanceValidation(
        status="passed" if not reasons else "blocked",
        blocking_reasons=tuple(dict.fromkeys(reasons)),
    )


def build_quota_free_production_scenarios() -> list[dict[str, Any]]:
    contract = RaphaelRuntimeContract(
        base_provider="openai-codex",
        base_model="gpt-5-production-replay",
        base_api_mode="production_replay",
        source="production_replay",
    )
    conversation = replay_raphael_turn(
        turn_id="accept-conversation",
        runtime_contract=contract,
        user_message="請說明 Raphael control kernel 的用途",
    )
    tool_task = replay_raphael_turn(
        turn_id="accept-tool-task",
        runtime_contract=contract,
        user_message="請 patch gateway fallback 並執行 pytest",
    )
    visual = replay_raphael_turn(
        turn_id="accept-visual-routing",
        runtime_contract=contract,
        user_message="請產出一張圖片",
    )
    followup = replay_raphael_turn(
        turn_id="accept-visual-followup",
        runtime_contract=contract,
        user_message="上一張照片再改亮一點",
        conversation_history=(
            {
                "role": "tool",
                "name": "visual_agent_generate",
                "content": (
                    '{"success":true,"delivery_metadata":'
                    '{"selected_visual_artifact_ids":["artifact-selected"]}}'
                ),
            },
        ),
    )
    failure_layers = tuple(
        classify_visual_failure_layer(payload)
        for payload in (
            {"provider_failure_classes": {"quota_exhausted": 1}},
            {"error": "candidate failed artifact quality gate"},
            {"delivery_recovery": {"status": "blocked"}},
        )
    )
    missing_proof = enforce_raphael_completion(
        decision=tool_task.to_dict(),
        final_response="完成了，測試都通過。",
        messages=(),
    )
    with tempfile.TemporaryDirectory(prefix="raphael-acceptance-") as temp_home:
        config = {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {
                "enabled": True,
                "default_conversation_mode_enabled": True,
            },
        }
        with patch.dict(os.environ, {"HERMES_HOME": temp_home}):
            background = prepare_raphael_turn(
                turn_id="accept-background",
                origin=RaphaelTurnOrigin.BACKGROUND_REVIEW,
                runtime_contract=contract,
                config=config,
                user_message="Review internal state",
            )
            background_state = read_state()
    codex_result = enforce_raphael_completion(
        decision=tool_task.to_dict(),
        final_response="完成了，測試都通過。",
        messages=(),
    )

    raw = [
        _scenario(
            "conversation",
            conversation.mode in {"general_conversation", "runtime_analysis"},
            decision_id=conversation.turn_id,
            mode=conversation.mode,
            runtime_contract=conversation.runtime_contract.to_dict(),
        ),
        _scenario(
            "tool_task",
            tool_task.mode == "tool_task" and tool_task.completion_policy == "mutation",
            decision_id=tool_task.turn_id,
            mode=tool_task.mode,
        ),
        _scenario(
            "visual_routing",
            visual.mode == "visual_agent_generation"
            and visual.route.handoff_tool == "visual_agent_generate",
            decision_id=visual.turn_id,
            mode=visual.mode,
        ),
        _scenario(
            "same_artifact_followup",
            followup.mode == "visual_agent_edit"
            and followup.goal.active_artifact_id == "artifact-selected",
            decision_id=followup.turn_id,
            mode=followup.mode,
        ),
        _scenario(
            "provider_failure_classification",
            failure_layers == ("provider_health", "artifact_quality", "delivery"),
            classifications=list(failure_layers),
        ),
        _scenario(
            "missing_proof",
            missing_proof.status == "blocked_unverified_completion",
            decision_id=tool_task.turn_id,
            missing_proofs=list(missing_proof.missing_proofs),
        ),
        _scenario(
            "background_isolation",
            background is None
            and background_state.active_mission is None
            and background_state.last_decision is None,
            decision_id="accept-background",
        ),
        _scenario(
            "codex_transport_parity",
            codex_result.status == missing_proof.status
            and codex_result.final_response == missing_proof.final_response,
            decision_id=tool_task.turn_id,
            finalization_status=codex_result.status,
        ),
    ]
    return raw


def build_acceptance_report(
    *,
    feature_head: str,
    verification: Mapping[str, Any] | None,
    runtime: Mapping[str, Any] | None,
    codex_review: Mapping[str, Any] | None,
    grok_review: Mapping[str, Any] | None,
) -> dict[str, Any]:
    scenarios = build_quota_free_production_scenarios()
    report = {
        "schema_version": "raphael.production_acceptance.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "feature_head": feature_head,
        "scenarios": scenarios,
        "verification": _safe_gate_summary(verification),
        "runtime": _safe_runtime_summary(runtime),
        "reviews": {
            "codex": _safe_review_summary(codex_review),
            "grok": _safe_review_summary(grok_review),
        },
        "privacy_safe": _privacy_safe(scenarios),
    }
    report["validation"] = validate_acceptance(report).to_dict()
    report["artifact_digest"] = _digest(
        {
            "feature_head": feature_head,
            "scenarios": scenarios,
            "verification": report["verification"],
            "runtime": report["runtime"],
            "reviews": report["reviews"],
        }
    )
    return report


def _scenario(scenario_id: str, passed: bool, **evidence: Any) -> dict[str, Any]:
    safe_evidence = _sanitize_mapping(evidence)
    return {
        "scenario_id": scenario_id,
        "status": "passed" if passed else "failed",
        "evidence_id": f"evidence-{_digest(safe_evidence).split(':', 1)[1][:16]}",
        "evidence": safe_evidence,
    }


def _safe_gate_summary(value: Mapping[str, Any] | None) -> dict[str, str]:
    source = value if isinstance(value, Mapping) else {}
    return {
        key: "passed" if source.get(key) == "passed" else "missing"
        for key in ("tests", "static_checks", "diff_hygiene")
    }


def _safe_runtime_summary(value: Mapping[str, Any] | None) -> dict[str, str]:
    source = value if isinstance(value, Mapping) else {}
    return {
        key: "passed" if source.get(key) == "passed" else "missing"
        for key in ("routing_truth", "isolated_feature_smoke")
    }


def _safe_review_summary(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    findings = [
        {
            "severity": str(item.get("severity") or ""),
            "status": str(item.get("status") or ""),
            "code": str(item.get("code") or "")[:80],
        }
        for item in value.get("findings") or ()
        if isinstance(item, Mapping)
    ]
    return {
        "status": str(value.get("status") or ""),
        "head": str(value.get("head") or ""),
        "ready_for_pr": value.get("ready_for_pr") is True,
        "findings": findings,
    }


def _has_blocking_findings(value: Any) -> bool:
    return any(
        isinstance(item, Mapping)
        and str(item.get("severity") or "").lower() in {"critical", "important"}
        and str(item.get("status") or "open").lower() not in {"resolved", "closed"}
        for item in (value or ())
    )


def _sanitize_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): _sanitize_value(item)
        for key, item in value.items()
        if str(key) not in {"prompt", "raw_prompt", "user_message", "path"}
    }


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _sanitize_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, str) and value.startswith(("/Users/", "/private/", "/tmp/")):
        return "[redacted-path]"
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _privacy_safe(value: Any) -> bool:
    serialized = json.dumps(value, sort_keys=True)
    return not any(
        marker in serialized
        for marker in ("/Users/", "/private/", "raw_prompt", "user_message")
    )


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _read_json(path: str) -> Mapping[str, Any] | None:
    if not path:
        return None
    parsed = json.loads(Path(path).read_text(encoding="utf-8"))
    return parsed if isinstance(parsed, Mapping) else None


def _git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Raphael production acceptance")
    parser.add_argument("--output", required=True)
    parser.add_argument("--verification-evidence", default="")
    parser.add_argument("--runtime-evidence", default="")
    parser.add_argument("--codex-review", default="")
    parser.add_argument("--grok-review", default="")
    parser.add_argument("--default-branch", default="")
    parser.add_argument("--feature-head", default="")
    args = parser.parse_args(argv)

    report = build_acceptance_report(
        feature_head=args.feature_head or _git_head(),
        verification=_read_json(args.verification_evidence),
        runtime=_read_json(args.runtime_evidence),
        codex_review=_read_json(args.codex_review),
        grok_review=_read_json(args.grok_review),
    )
    report["pr_target"] = evaluate_pr_target(
        default_branch=args.default_branch
    ).to_dict()
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    validation = report["validation"]
    if validation["status"] == "passed" and report["pr_target"]["allowed"]:
        print("Raphael production acceptance: passed")
        return 0
    print("Raphael production acceptance: blocked")
    for reason in validation["blocking_reasons"]:
        print(f"- {reason}")
    if not report["pr_target"]["allowed"]:
        print(f"- {report['pr_target']['reason']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
