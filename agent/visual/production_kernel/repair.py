from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class VisualRepairPlan:
    strategy: str
    should_generate: bool
    should_switch_provider: bool
    blocker_codes: tuple[str, ...]
    directive: str
    reason: str

    def to_record(self) -> dict[str, object]:
        return {
            "strategy": self.strategy,
            "should_generate": self.should_generate,
            "should_switch_provider": self.should_switch_provider,
            "blocker_codes": list(self.blocker_codes),
            "directive": self.directive,
            "reason": self.reason,
        }


def plan_visual_repair(
    blocker_codes: Iterable[str],
    *,
    prior_generated_repairs: Iterable[str],
    repeated_blockers: Iterable[str] = (),
    capability_mismatch: bool = False,
    max_generated_repairs: int = 1,
) -> VisualRepairPlan:
    blockers = tuple(dict.fromkeys(str(code).strip() for code in blocker_codes if str(code).strip()))
    prior = tuple(str(item).strip() for item in prior_generated_repairs if str(item).strip())
    prior_set = set(prior)
    repeated = {str(item).strip() for item in repeated_blockers if str(item).strip()}
    if "stale_contract" in blockers:
        return _plan(
            "recompile_contract",
            blockers,
            should_generate=False,
            directive="Recompile the current visual contract before judging or generating another artifact.",
            reason="stale_contract_requires_recompile",
        )
    if "vision_evidence_missing" in blockers:
        return _plan(
            "rejudge_artifact",
            blockers,
            should_generate=False,
            directive="Acquire artifact-level vision evidence for the current image before generation.",
            reason="vision_evidence_required",
        )
    if len(prior) >= max(0, int(max_generated_repairs)):
        return _plan(
            "review_required",
            blockers,
            should_generate=False,
            directive="Stop generation and surface the current blocker evidence for review.",
            reason="generated_repair_budget_exhausted",
        )
    if (
        prior
        and prior[-1] == "targeted_repair"
        and {"artifact_defect", "subject_mismatch", "other"}.intersection(blockers)
    ):
        return _plan(
            "constraint_rebuild",
            blockers,
            should_generate=True,
            directive=(
                "Rebuild from the bound reference and audit each explicit user requirement as a visible "
                "constraint. Preserve details that already pass while correcting every missing or defective "
                "detail; do not repeat the prior targeted repair composition."
            ),
        )
    provider_or_capability_failure = (
        "provider_failure" in blockers
        or capability_mismatch
        or bool(repeated.intersection(blockers))
    )
    if provider_or_capability_failure and "provider_switch" in prior_set:
        return _plan(
            "review_required",
            blockers,
            should_generate=False,
            directive="Stop generation because the authorized provider recovery did not clear the failure.",
            reason="persistent_provider_failure",
        )
    if provider_or_capability_failure:
        return _plan(
            "provider_switch",
            blockers,
            should_generate=True,
            should_switch_provider=True,
            directive=(
                "Preserve the exact visual contract and retry once with one authorized fallback provider; "
                "do not generate a cross-provider candidate ensemble."
            ),
            reason="provider_or_capability_failure",
        )
    if "reference_identity_drift" in blockers and "identity_recovery" not in prior_set:
        return _plan(
            "identity_recovery",
            blockers,
            should_generate=True,
            directive=(
                "Correct blocker reference_identity_drift: restore the bound reference identity and role "
                "while changing only the failed composition or rendering details."
            ),
        )
    if "reference_overcopy" in blockers and "reference_resynthesis" not in prior_set:
        return _plan(
            "reference_resynthesis",
            blockers,
            should_generate=True,
            directive=(
                "Create a genuinely new role-locked synthesis: preserve character identity only from the "
                "identity reference and use the pose reference only for pose, camera, framing, and limb layout. "
                "Do not reproduce either reference verbatim or reuse the pose reference as the final image."
            ),
        )
    if "composition_weak" in blockers and "composition_reset" not in prior_set:
        return _plan(
            "composition_reset",
            blockers,
            should_generate=True,
            directive=(
                "Correct blocker composition_weak with a materially different composition, focal hierarchy, "
                "and subject placement; do not merely adjust color or lighting."
            ),
        )
    if "action_or_moment_missing" in blockers and "story_moment_reframe" not in prior_set:
        return _plan(
            "story_moment_reframe",
            blockers,
            should_generate=True,
            directive=(
                "Show one decisive visible action and its immediate consequence so the requested moment reads "
                "without explanatory text."
            ),
        )
    if "style_mismatch" in blockers and "style_correction" not in prior_set:
        return _plan(
            "style_correction",
            blockers,
            should_generate=True,
            directive="Correct the requested visual language while preserving subject, action, and composition.",
        )
    if "truth_or_evidence_risk" in blockers and "truth_reframe" not in prior_set:
        return _plan(
            "truth_reframe",
            blockers,
            should_generate=True,
            directive=(
                "Remove unsupported certainty, danger, or fabricated evidence and show only a truthful visual "
                "claim supported by the contract."
            ),
        )
    return _plan(
        "targeted_repair",
        blockers,
        should_generate=True,
        directive=(
            "Correct every listed blocker in the visible artifact. Change the failed visual content, not only "
            "camera polish, color, or lighting."
        ),
    )


def _plan(
    strategy: str,
    blockers: tuple[str, ...],
    *,
    should_generate: bool,
    directive: str,
    reason: str = "classified_quality_repair",
    should_switch_provider: bool = False,
) -> VisualRepairPlan:
    return VisualRepairPlan(
        strategy=strategy,
        should_generate=should_generate,
        should_switch_provider=should_switch_provider,
        blocker_codes=blockers,
        directive=directive,
        reason=reason,
    )
