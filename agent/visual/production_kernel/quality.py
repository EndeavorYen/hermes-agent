from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Iterable


_BLOCKER_ORDER = (
    "stale_contract",
    "vision_evidence_missing",
    "provider_failure",
    "artifact_defect",
    "subject_mismatch",
    "action_or_moment_missing",
    "composition_weak",
    "reference_identity_drift",
    "style_mismatch",
    "truth_or_evidence_risk",
    "other",
)


@dataclass(frozen=True)
class VisualQualityDecision:
    contract_hash: str
    artifact_id: str
    deliverable: bool
    blocker_codes: tuple[str, ...]
    quality_issues: tuple[str, ...]
    reason: str

    def to_record(self) -> dict[str, object]:
        return {
            "contract_hash": self.contract_hash,
            "artifact_id": self.artifact_id,
            "deliverable": self.deliverable,
            "blocker_codes": list(self.blocker_codes),
            "quality_issues": list(self.quality_issues),
            "reason": self.reason,
        }


def evaluate_visual_quality(
    *,
    contract_hash: str,
    artifact_contract_hash: str,
    artifact_id: str,
    quality_issues: Iterable[Any],
    hard_gate_passed: bool,
    provider_failure: Any = None,
    vision_confidence: float | None = None,
) -> VisualQualityDecision:
    contract_hash = str(contract_hash or "").strip()
    artifact_contract_hash = str(artifact_contract_hash or "").strip()
    issues = tuple(str(item).strip() for item in quality_issues if str(item).strip())
    if not contract_hash or artifact_contract_hash != contract_hash:
        return VisualQualityDecision(
            contract_hash=contract_hash,
            artifact_id=str(artifact_id or ""),
            deliverable=False,
            blocker_codes=("stale_contract",),
            quality_issues=issues,
            reason="artifact_contract_mismatch",
        )

    blockers = set(classify_quality_blockers(issues))
    if provider_failure:
        blockers.add("provider_failure")
    if vision_confidence is not None and _confidence(vision_confidence) <= 0.0:
        blockers.add("vision_evidence_missing")
    if not hard_gate_passed and not blockers:
        blockers.add("other")
    ordered = _ordered_blockers(blockers)
    return VisualQualityDecision(
        contract_hash=contract_hash,
        artifact_id=str(artifact_id or ""),
        deliverable=hard_gate_passed and not ordered,
        blocker_codes=ordered,
        quality_issues=issues,
        reason="quality_pass" if hard_gate_passed and not ordered else "quality_blocked",
    )


def classify_quality_blockers(quality_issues: Iterable[Any]) -> tuple[str, ...]:
    blockers: set[str] = set()
    for issue in quality_issues:
        text = str(issue or "").strip().lower()
        if not text:
            continue
        if "reference" in text and any(token in text for token in ("identity", "drift", "role")):
            blockers.add("reference_identity_drift")
        elif any(token in text for token in ("composition", "framing", "focal", "pose_stiff")):
            blockers.add("composition_weak")
        elif any(token in text for token in ("style", "art_style", "aesthetic_mismatch")):
            blockers.add("style_mismatch")
        elif any(token in text for token in ("subject_missing", "subject_mismatch", "wrong_subject")):
            blockers.add("subject_mismatch")
        elif any(token in text for token in ("action_missing", "moment_missing", "static_scene")):
            blockers.add("action_or_moment_missing")
        elif any(token in text for token in ("truth", "evidence", "unsupported", "sensational")):
            blockers.add("truth_or_evidence_risk")
        elif any(
            token in text
            for token in (
                "distort",
                "unnatural",
                "extra_finger",
                "bad_hand",
                "artifact",
                "watermark",
                "blurred_face",
                "not_beautiful",
                "not_glamorous",
            )
        ):
            blockers.add("artifact_defect")
        elif any(token in text for token in ("provider_", "quota", "authentication", "timeout")):
            blockers.add("provider_failure")
        else:
            blockers.add("other")
    return _ordered_blockers(blockers)


def _ordered_blockers(blockers: set[str]) -> tuple[str, ...]:
    return tuple(code for code in _BLOCKER_ORDER if code in blockers)


def _confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
