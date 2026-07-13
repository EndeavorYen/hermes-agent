from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


BLOCKER_CODES = frozenset({
    "subtitle_collision",
    "anatomy_geometry",
    "scientific_identity",
    "text_artifact",
    "focus_clarity",
    "continuity_redundancy",
    "other",
})


@dataclass(frozen=True)
class RepairPlan:
    strategy: str
    candidate_suffix: str
    directive: str
    blocker_codes: tuple[str, ...] = ()
    exhausted: bool = False


_KEYWORDS = {
    "subtitle_collision": (
        "subtitle", "safe area", "safe-area", "字幕", "安全區",
    ),
    "anatomy_geometry": (
        "anatom", "geometry", "geometr", "malformed", "解剖", "幾何",
        "失真", "熔融", "黏連", "粘連", "分叉", "畸形",
    ),
    "scientific_identity": (
        "scientific", "contradiction", "taxon", "identity", "科學",
        "辨識", "可信", "食性", "物種", "分類",
    ),
    "text_artifact": (
        "generated text", "watermark", "label", "文字", "浮水印", "標籤",
    ),
    "focus_clarity": (
        "focus", "unclear", "readable", "焦點", "模糊", "不清楚",
    ),
    "continuity_redundancy": (
        "continuity", "redundan", "adjacent", "連續性", "重複", "相鄰",
    ),
}


_DIRECTIVES = {
    "initial": "Generate the declared shot contract with no prior candidate reuse.",
    "targeted_repair": (
        "Correct every listed QC blocker. Change the failing visual evidence, not "
        "only color, crop, lighting, or camera polish."
    ),
    "layout_reset": (
        "Use a materially different offset or wider composition. Keep the declared "
        "subtitle-safe region completely empty of subject, evidence, hands, and supports."
    ),
    "evidence_reframe": (
        "Reframe as credible fragmentary evidence in a professional museum or research "
        "context. Do not invent a complete specimen or unsupported taxon-specific anatomy. "
        "Reduce extreme macro magnification, show neutral broken boundaries, and keep only "
        "visibly coherent teeth or bone geometry. The image may support uncertainty; it "
        "must not pretend the fragmentary evidence proves more than is visible."
    ),
    "contextual_replan": (
        "Replace the unreliable exact-morphology view with a semantically equivalent "
        "research-process shot: a small fragmentary specimen handled or examined in a "
        "credible lab or museum setting. Preserve the narration's evidence relationship "
        "without requiring the generated image to establish exact taxonomic identity."
    ),
    "documentary_context": (
        "Use honest documentary context B-roll for the scientific claim, such as the "
        "fragmentary specimen's research setting or discovery context. Avoid fabricated "
        "diagnostic anatomy and make uncertainty visually explicit through partial, "
        "non-complete evidence. Do not add text, labels, diagrams, or a complete skull."
    ),
}


def classify_blockers(
    blockers: Iterable[Any],
    explicit_codes: Iterable[Any] = (),
) -> set[str]:
    codes = {
        str(code).strip()
        for code in explicit_codes
        if str(code).strip() in BLOCKER_CODES
    }
    if codes:
        return codes
    text = " ".join(str(item) for item in blockers).lower()
    for code, keywords in _KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            codes.add(code)
    return codes or {"other"}


def _strategy(row: dict[str, Any]) -> str:
    explicit = str(row.get("repair_strategy") or "").strip()
    if explicit:
        return explicit
    if row.get("strategy_reset") is True:
        return "layout_reset"
    return "targeted_repair"


def apply_repair_strategy(
    shot: dict[str, Any],
    strategy: str,
    *,
    blocker_codes: Iterable[Any] = (),
) -> dict[str, Any]:
    effective = dict(shot)
    evidence = str(shot.get("evidence_detail") or "the narrated evidence").strip()
    acceptance = [
        str(item).strip()
        for item in shot.get("acceptance_criteria") or []
        if str(item).strip()
    ]
    if strategy == "evidence_reframe":
        effective.update({
            "subject": f"fragmentary research specimen showing {evidence}",
            "action": "resting in a neutral museum specimen tray under soft side light",
            "evidence_detail": (
                f"partial, non-complete preservation of {evidence} with coherent geometry"
            ),
            "shot_scale": "close_up",
            "focal_point": "fragment boundaries and limited preserved evidence",
            "acceptance_criteria": [
                *acceptance,
                "no invented complete specimen",
                "no unsupported taxon-specific anatomy",
                "broken and missing regions remain visibly neutral",
            ],
            "risk_class": "high",
        })
    elif strategy == "contextual_replan":
        effective.update({
            "subject": "researcher examining fragmentary evidence relevant to the narration",
            "action": "carefully examining a small partial specimen in a neutral lab tray",
            "evidence_detail": "fragmentary preservation and evidence-review process",
            "shot_scale": "medium",
            "focal_point": "small partial specimen and careful examination",
            "acceptance_criteria": [
                *acceptance,
                "the image does not claim exact visual taxonomic identification",
                "no complete reconstructed anatomy",
                "no generated labels or text",
            ],
            "risk_class": "high",
        })
    elif strategy == "documentary_context":
        effective.update({
            "subject": "professional natural-history research context for the narrated discovery",
            "action": "documenting small fragmentary evidence without reconstruction",
            "evidence_detail": "credible discovery or museum-research context",
            "shot_scale": "medium",
            "focal_point": "documentary research activity and partial evidence",
            "acceptance_criteria": [
                *acceptance,
                "context supports the narration without fabricating diagnostic anatomy",
                "no complete specimen, generated text, or taxonomic label",
            ],
            "risk_class": "high",
        })
    codes = {str(code).strip() for code in blocker_codes}
    safe_area = str(shot.get("subtitle_safe_area") or "").strip().lower()
    if "subtitle_collision" in codes:
        if "right" in safe_area:
            action_lock = "confined entirely to the left 60 percent of the frame"
            empty_lock = (
                "right 35 percent is empty low-detail background with no people, "
                "hands, tools, and specimens"
            )
        elif "left" in safe_area:
            action_lock = "confined entirely to the right 60 percent of the frame"
            empty_lock = (
                "left 35 percent is empty low-detail background with no people, "
                "hands, tools, and specimens"
            )
        elif "bottom" in safe_area:
            action_lock = "confined entirely above the bottom 25 percent of the frame"
            empty_lock = (
                "bottom 20 percent is empty low-detail background with no people, "
                "hands, tools, and specimens"
            )
        else:
            action_lock = "confined entirely outside the declared subtitle-safe region"
            empty_lock = (
                "declared subtitle-safe region is empty low-detail background with no "
                "people, hands, tools, and specimens"
            )
        effective["action"] = (
            f"{effective.get('action') or 'documenting the evidence'}, {action_lock}"
        )
        effective["acceptance_criteria"] = [
            *effective.get("acceptance_criteria", []),
            empty_lock,
        ]
    return effective


def plan_repair(attempts: Iterable[dict[str, Any]]) -> RepairPlan:
    rows = [row for row in attempts if isinstance(row, dict)]
    if not rows:
        return RepairPlan("initial", "C01", _DIRECTIVES["initial"])

    latest = rows[-1]
    codes = classify_blockers(
        latest.get("hard_blockers") or (),
        latest.get("blocker_codes") or (),
    )
    used = {_strategy(row) for row in rows}
    status = str(latest.get("status") or "")

    if status == "repair_required":
        normal_round = max(
            (int(row.get("repair_round") or 0) for row in rows),
            default=0,
        ) + 1
        return RepairPlan(
            "targeted_repair",
            f"C{normal_round:02d}",
            _DIRECTIVES["targeted_repair"],
            tuple(sorted(codes)),
        )

    if codes & {"anatomy_geometry", "scientific_identity"}:
        preferred = ["evidence_reframe", "contextual_replan", "documentary_context"]
    elif "subtitle_collision" in codes:
        preferred = ["layout_reset", "contextual_replan", "documentary_context"]
    else:
        preferred = ["contextual_replan", "documentary_context"]

    suffixes = {
        "layout_reset": "LAYOUT_C01",
        "evidence_reframe": "EVIDENCE_C01",
        "contextual_replan": "CONTEXT_C01",
        "documentary_context": "DOC_C01",
    }
    for strategy in preferred:
        if strategy not in used:
            return RepairPlan(
                strategy,
                suffixes[strategy],
                _DIRECTIVES[strategy],
                tuple(sorted(codes)),
            )
    return RepairPlan(
        "human_review_required",
        "",
        "All semantically equivalent visual repair strategies failed QC.",
        tuple(sorted(codes)),
        exhausted=True,
    )


__all__ = [
    "BLOCKER_CODES",
    "RepairPlan",
    "apply_repair_strategy",
    "classify_blockers",
    "plan_repair",
]
