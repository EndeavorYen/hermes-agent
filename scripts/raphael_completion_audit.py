from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REQUIRED_LLM_SCOPED_CHECKS: tuple[str, ...] = (
    "install_disable_uninstall",
    "package_install_smoke",
    "slash_command_surface",
    "mode_router_contract",
    "goal_state_contract",
    "evolution_contract",
    "llm_live_smoke",
    "hostile_review",
    "non_visual_regression",
    "release_docs_audit",
    "wow_experience",
)

REQUIRED_ULTIMATE_MEDIA_CAPABILITIES: tuple[str, ...] = (
    "xai_grok_generation",
    "video_generation",
)

ULTIMATE_CLAIM_FLAGS: tuple[tuple[str, str], ...] = (
    ("sage_king_claim_allowed", "ultimate_claim:sage_king_denied"),
    ("wow_claim_allowed", "ultimate_claim:wow_denied"),
    ("big_evolution_claim_allowed", "ultimate_claim:big_evolution_denied"),
)

REQUIRED_WOW_USER_SIMULATION_CASES: tuple[str, ...] = (
    "standby_summon",
    "vague_takeover_preserves_mission",
    "runtime_log_attachment_routes_tool_task",
    "blank_screen_repair_routes_tool_task",
    "prompt_builder_question_not_prompt_disclosure",
    "negated_media_summon_stays_text_only",
)


@dataclass(frozen=True)
class CompletionAuditResult:
    status: str
    scoped_release_ready: bool
    ultimate_ready: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    progress_percent: int = 0
    progress_layers: tuple[dict[str, Any], ...] = ()


def audit_completion(
    *,
    llm_readiness: Mapping[str, Any],
    media_readiness: Mapping[str, Any],
    boundary_summary: Mapping[str, Any] | None = None,
) -> CompletionAuditResult:
    blockers: list[str] = []
    warnings: list[str] = []
    boundary_summary = boundary_summary or {}

    for check_name in REQUIRED_LLM_SCOPED_CHECKS:
        if not _check_passed(llm_readiness, check_name):
            blockers.append(f"llm:{check_name}_missing_or_not_pass")

    if _sequence(boundary_summary.get("unclassified_paths")):
        blockers.append("boundary:unclassified_paths")
    if _sequence(boundary_summary.get("content_violations")):
        blockers.append("boundary:content_violations")
    if _sequence(boundary_summary.get("deferred_media_paths")):
        warnings.append("boundary:deferred_media_paths_present")

    llm_scope_ready = (
        _text(llm_readiness.get("release_state")) == "ready_for_llm_only_release"
        and _text(llm_readiness.get("public_claim_scope")) == "llm_only"
        and bool(llm_readiness.get("public_release_ready")) is True
    )
    if not llm_scope_ready:
        blockers.append("llm:scoped_release_not_ready")

    scoped_release_ready = not any(
        blocker.startswith("llm:") or blocker.startswith("boundary:")
        for blocker in blockers
    )

    hostile_claims = _merged_hostile_claims(llm_readiness, media_readiness)
    for flag, blocker in ULTIMATE_CLAIM_FLAGS:
        if hostile_claims.get(flag) is not True:
            blockers.append(blocker)

    verified_capabilities = set(
        _verified_capability_ids(media_readiness.get("verified_media_capabilities"))
    )
    remaining_media_gaps = set(_string_list(media_readiness.get("remaining_media_gaps")))
    for capability in REQUIRED_ULTIMATE_MEDIA_CAPABILITIES:
        if capability in remaining_media_gaps or capability not in verified_capabilities:
            blockers.append(f"full_media:{capability}_missing")

    full_media_ready = (
        media_readiness.get("full_media_release_ready") is True
        and media_readiness.get("public_release_ready") is True
        and _text(media_readiness.get("media_release_scope"))
        in {"full_media", "full_sage_king"}
    )
    if not full_media_ready:
        blockers.append("full_media:release_not_ready")

    blockers_tuple = tuple(dict.fromkeys(blockers))
    ultimate_ready = scoped_release_ready and not blockers_tuple
    status = "ready" if ultimate_ready else "partial" if scoped_release_ready else "blocked"
    progress_layers = _estimate_progress_layers(
        llm_readiness=llm_readiness,
        media_readiness=media_readiness,
        hostile_claims=hostile_claims,
        scoped_release_ready=scoped_release_ready,
        full_media_ready=full_media_ready,
        verified_capabilities=verified_capabilities,
        remaining_media_gaps=remaining_media_gaps,
    )
    return CompletionAuditResult(
        status=status,
        scoped_release_ready=scoped_release_ready,
        ultimate_ready=ultimate_ready,
        blockers=blockers_tuple,
        warnings=tuple(dict.fromkeys(warnings)),
        progress_percent=_weighted_progress_percent(progress_layers),
        progress_layers=progress_layers,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit Raphael scoped release and ultimate Sage King readiness."
    )
    parser.add_argument(
        "--llm-readiness",
        default="/Users/simon/.hermes/raphael/release_readiness.llm.json",
    )
    parser.add_argument(
        "--media-readiness",
        default="/Users/simon/.hermes/raphael/release_readiness.media.json",
    )
    parser.add_argument(
        "--boundary-json",
        help="Optional JSON file with unclassified_paths/content_violations/deferred_media_paths.",
    )
    parser.add_argument(
        "--target",
        choices=("scoped", "ultimate"),
        default="ultimate",
        help="Use scoped for LLM/OpenAI-image release automation; ultimate keeps full Sage King semantics.",
    )
    args = parser.parse_args(argv)

    result = audit_completion(
        llm_readiness=_read_json(Path(args.llm_readiness)),
        media_readiness=_read_json(Path(args.media_readiness)),
        boundary_summary=_read_json(Path(args.boundary_json)) if args.boundary_json else {},
    )
    print(f"Raphael completion audit: {result.status}")
    print(f"Scoped release ready: {'yes' if result.scoped_release_ready else 'no'}")
    print(f"Ultimate Sage King ready: {'yes' if result.ultimate_ready else 'no'}")
    print(
        f"Progress estimate: {result.progress_percent}% "
        "(not release evidence)"
    )
    print("Progress layers:")
    for layer in result.progress_layers:
        gaps = _string_list(layer.get("gaps"))
        gap_text = ", ".join(gaps) if gaps else "none"
        print(f"- {layer['id']}: {layer['percent']}% (gaps: {gap_text})")
    if result.blockers:
        print("Blockers:")
        for blocker in result.blockers:
            print(f"- {blocker}")
    if result.warnings:
        print("Warnings:")
        for warning in result.warnings:
            print(f"- {warning}")
    if args.target == "scoped":
        return 0 if result.scoped_release_ready else 1
    return 0 if result.ultimate_ready else 1


def _read_json(path: Path) -> Mapping[str, Any]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    return parsed if isinstance(parsed, Mapping) else {}


def _check_passed(readiness: Mapping[str, Any], check_name: str) -> bool:
    check = _nested(readiness, "checks", check_name)
    return isinstance(check, Mapping) and _text(check.get("status")) == "pass"


def _estimate_progress_layers(
    *,
    llm_readiness: Mapping[str, Any],
    media_readiness: Mapping[str, Any],
    hostile_claims: Mapping[str, Any],
    scoped_release_ready: bool,
    full_media_ready: bool,
    verified_capabilities: set[str],
    remaining_media_gaps: set[str],
) -> tuple[dict[str, Any], ...]:
    """Return an operator-facing progress estimate, not release evidence."""

    mode_router = _check_passed(llm_readiness, "mode_router_contract")
    goal_state = _check_passed(llm_readiness, "goal_state_contract")
    evolution = _check_passed(llm_readiness, "evolution_contract")
    install = _check_passed(llm_readiness, "install_disable_uninstall")
    package = _check_passed(llm_readiness, "package_install_smoke")
    slash = _check_passed(llm_readiness, "slash_command_surface")
    llm_smoke = _check_passed(llm_readiness, "llm_live_smoke")
    hostile = _check_passed(llm_readiness, "hostile_review")
    non_visual = _check_passed(llm_readiness, "non_visual_regression")
    docs = _check_passed(llm_readiness, "release_docs_audit")
    completion = _check_passed(llm_readiness, "completion_audit") or scoped_release_ready
    wow = _check_passed(llm_readiness, "wow_experience")
    reviewable_wow_matrix = _reviewable_wow_user_simulation_matrix(
        _nested(llm_readiness, "checks", "wow_experience", "user_simulation_cases")
    )
    visual = _check_passed(media_readiness, "visual_live_e2e")

    sage_claim = hostile_claims.get("sage_king_claim_allowed") is True
    wow_claim = hostile_claims.get("wow_claim_allowed") is True
    evolution_claim = hostile_claims.get("big_evolution_claim_allowed") is True
    has_grok = "xai_grok_generation" in verified_capabilities
    has_video = "video_generation" in verified_capabilities
    has_openai_image = "openai_image_generation" in verified_capabilities

    return (
        _progress_layer(
            "intent_mode_routing",
            100 if mode_router and has_grok and has_video else 80 if mode_router else 0,
            evidence=["mode_router_contract"] if mode_router else [],
            gaps=[
                gap
                for gap, missing in (
                    ("mode_router_contract", not mode_router),
                    ("xai_grok_generation", not has_grok),
                    ("video_generation", not has_video),
                )
                if missing
            ],
            weight=1.0,
        ),
        _progress_layer(
            "goal_state_management",
            100 if goal_state and scoped_release_ready and sage_claim else 90 if goal_state else 0,
            evidence=["goal_state_contract"] if goal_state else [],
            gaps=[
                gap
                for gap, missing in (
                    ("goal_state_contract", not goal_state),
                    ("sage_king_claim_not_allowed", not sage_claim),
                )
                if missing
            ],
            weight=1.0,
        ),
        _progress_layer(
            "autonomous_planning_execution",
            100
            if goal_state and wow and llm_smoke and evolution_claim
            else 55
            if goal_state and wow and llm_smoke
            else 0,
            evidence=[
                name
                for name, present in (
                    ("goal_state_contract", goal_state),
                    ("wow_experience", wow),
                    ("llm_live_smoke", llm_smoke),
                )
                if present
            ],
            gaps=[
                gap
                for gap, missing in (
                    ("goal_state_contract", not goal_state),
                    ("wow_experience", not wow),
                    ("llm_live_smoke", not llm_smoke),
                    ("big_evolution_claim_not_allowed", not evolution_claim),
                )
                if missing
            ],
            weight=1.2,
        ),
        _progress_layer(
            "evidence_self_validation",
            100
            if hostile and non_visual and docs and completion and full_media_ready
            else 80
            if hostile and non_visual and docs and completion
            else 0,
            evidence=[
                name
                for name, present in (
                    ("hostile_review", hostile),
                    ("non_visual_regression", non_visual),
                    ("release_docs_audit", docs),
                    ("completion_audit", completion),
                )
                if present
            ],
            gaps=[
                gap
                for gap, missing in (
                    ("hostile_review", not hostile),
                    ("non_visual_regression", not non_visual),
                    ("release_docs_audit", not docs),
                    ("completion_audit", not completion),
                    ("full_media_release_not_ready", not full_media_ready),
                )
                if missing
            ],
            weight=1.2,
        ),
        _progress_layer(
            "visual_coordination",
            100
            if full_media_ready and has_grok and has_video
            else min(65, (25 if visual else 0) + (20 if has_openai_image else 0) + 10),
            evidence=[
                name
                for name, present in (
                    ("visual_live_e2e", visual),
                    ("openai_image_generation", has_openai_image),
                )
                if present
            ],
            gaps=sorted(remaining_media_gaps),
            weight=1.5,
        ),
        _progress_layer(
            "provider_runtime_health",
            100
            if install and package and full_media_ready
            else 70
            if install and package
            else 0,
            evidence=[
                name
                for name, present in (
                    ("install_disable_uninstall", install),
                    ("package_install_smoke", package),
                )
                if present
            ],
            gaps=sorted(remaining_media_gaps) if not full_media_ready else [],
            weight=1.0,
        ),
        _progress_layer(
            "learning_feedback_evolution",
            100 if evolution and evolution_claim else 60 if evolution else 0,
            evidence=["evolution_contract"] if evolution else [],
            gaps=[
                gap
                for gap, missing in (
                    ("evolution_contract", not evolution),
                    ("big_evolution_claim_not_allowed", not evolution_claim),
                )
                if missing
            ],
            weight=1.4,
        ),
        _progress_layer(
            "install_enable_disable",
            (40 if install else 0) + (35 if package else 0) + (25 if slash else 0),
            evidence=[
                name
                for name, present in (
                    ("install_disable_uninstall", install),
                    ("package_install_smoke", package),
                    ("slash_command_surface", slash),
                )
                if present
            ],
            gaps=[
                gap
                for gap, missing in (
                    ("install_disable_uninstall", not install),
                    ("package_install_smoke", not package),
                    ("slash_command_surface", not slash),
                )
                if missing
            ],
            weight=0.8,
        ),
        _progress_layer(
            "summon_wow_ux",
            100 if wow and wow_claim else 80 if wow and reviewable_wow_matrix else 50 if wow else 0,
            evidence=[
                name
                for name, present in (
                    ("wow_experience", wow),
                    (
                        "reviewable_user_simulation_matrix",
                        reviewable_wow_matrix,
                    ),
                )
                if present
            ],
            gaps=[
                gap
                for gap, missing in (
                    ("wow_experience", not wow),
                    (
                        "reviewable_user_simulation_matrix_missing",
                        wow and not reviewable_wow_matrix,
                    ),
                    ("full_wow_claim_not_allowed", not wow_claim),
                )
                if missing
            ],
            weight=1.5,
        ),
    )


def _reviewable_wow_user_simulation_matrix(value: Any) -> bool:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return False
    by_case: dict[str, Mapping[str, Any]] = {}
    for item in value:
        if not isinstance(item, Mapping):
            return False
        case = _text(item.get("case"))
        if not case or case in by_case:
            return False
        by_case[case] = item
    if set(by_case) != set(REQUIRED_WOW_USER_SIMULATION_CASES):
        return False
    for item in by_case.values():
        if (
            _text(item.get("status")) != "pass"
            or item.get("visual_quota_used") is not False
            or not _text(item.get("user_prompt"))
            or not _text(item.get("expected_visible_behavior"))
            or not _nonempty_text_sequence(item.get("critical_assertions"))
            or not _text(item.get("evidence"))
            or not _text(item.get("next_action"))
            or not _text(item.get("proof_layer"))
        ):
            return False
    return True


def _nonempty_text_sequence(value: Any) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, str)
        and bool(value)
        and all(bool(_text(item)) for item in value)
    )


def _progress_layer(
    layer_id: str,
    percent: int,
    *,
    evidence: Sequence[str],
    gaps: Sequence[str],
    weight: float,
) -> dict[str, Any]:
    bounded = max(0, min(100, int(percent)))
    if bounded == 100:
        status = "pass"
    elif bounded > 0:
        status = "partial"
    else:
        status = "blocked"
    return {
        "id": layer_id,
        "percent": bounded,
        "status": status,
        "evidence": tuple(evidence),
        "gaps": tuple(gaps),
        "weight": weight,
    }


def _weighted_progress_percent(layers: Sequence[Mapping[str, Any]]) -> int:
    if not layers:
        return 0
    weighted_sum = 0.0
    total_weight = 0.0
    for layer in layers:
        weight = float(layer.get("weight") or 1.0)
        weighted_sum += int(layer.get("percent") or 0) * weight
        total_weight += weight
    if total_weight <= 0:
        return 0
    return int(round(weighted_sum / total_weight))


def _merged_hostile_claims(
    llm_readiness: Mapping[str, Any],
    media_readiness: Mapping[str, Any],
) -> Mapping[str, Any]:
    merged: dict[str, Any] = {}
    for readiness in (llm_readiness, media_readiness):
        claims = _nested(readiness, "checks", "hostile_review", "llm_ux_claims")
        if isinstance(claims, Mapping):
            merged.update(claims)
    return merged


def _nested(mapping: Mapping[str, Any], *path: str) -> Any:
    current: Any = mapping
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _text(value: Any) -> str:
    return str(value or "").strip()


def _string_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _verified_capability_ids(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return ()
    capabilities: list[str] = []
    for item in value:
        if isinstance(item, Mapping):
            status = _text(item.get("status"))
            capability_id = _text(item.get("capability_id"))
            if capability_id and status in {"", "verified"}:
                capabilities.append(capability_id)
            continue
        text = _text(item)
        if text:
            capabilities.append(text)
    return tuple(capabilities)


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, str) else ()


if __name__ == "__main__":
    raise SystemExit(main())
