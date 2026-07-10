from __future__ import annotations

from typing import Any

from agent.visual.strategy_atoms import builtin_strategy_atom_map


MAX_VARIANTS = 4


def build_arsenal_prompt_variants(
    *,
    base_prompt: str,
    strategy_plan: dict[str, Any],
    feedback_policy: dict[str, Any],
    request_category: str,
    candidate_budget: int,
    approved_prompt_entries: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build provider-ready prompt variants from learned visual strategy inputs."""

    base = str(base_prompt or "").strip()
    budget = _clamp_int(candidate_budget, minimum=1, maximum=MAX_VARIANTS)
    category = str(request_category or "general").strip().lower() or "general"
    atom_variants = _atom_variants(strategy_plan, request_category=category)
    composition_delta = _preferred_composition_delta(atom_variants)
    repair_variants = _repair_variants(feedback_policy, request_category=category)
    lanes = _style_lanes(category)

    variants: list[dict[str, Any]] = []
    variants.append(
            _variant(
                base_prompt=base,
                variant_id="arsenal_baseline",
                prompt_delta="",
                applied_dimensions=[],
                atom_signatures=[],
                request_category=category,
            )
    )

    if len(repair_variants) > 1:
        variants.append(
            _variant(
                base_prompt=base,
                variant_id="arsenal_repair_combined",
                prompt_delta=_join_deltas(
                    *(repair["prompt_delta"] for repair in repair_variants),
                    composition_delta,
                ),
                applied_dimensions=[repair["dimension"] for repair in repair_variants],
                atom_signatures=[],
                request_category=category,
            )
        )
    for index, entry in enumerate(approved_prompt_entries or [], start=1):
        approved_prompt = _safe_prompt_excerpt(str(entry.get("prompt_mediated") or ""))
        if not approved_prompt:
            continue
        variants.append(
            _variant(
                base_prompt=base,
                variant_id=f"arsenal_approved_prompt_{index}",
                prompt_delta=(
                    "use this user-approved prior prompt pattern as a quality/style scaffold: "
                    f"{approved_prompt}. Adapt the pattern to the current request; preserve current user intent "
                    "and references, and do not copy obsolete subject details unless they are requested again"
                ),
                applied_dimensions=[],
                atom_signatures=[],
                request_category=category,
                approved_prompt_entry=True,
            )
        )
    for repair in repair_variants:
        variants.append(
            _variant(
                base_prompt=base,
                variant_id=f"arsenal_repair_{repair['dimension']}",
                prompt_delta=_join_deltas(repair["prompt_delta"], composition_delta),
                applied_dimensions=[repair["dimension"]],
                atom_signatures=[],
                request_category=category,
            )
        )

    for atom in atom_variants:
        variants.append(
            _variant(
                base_prompt=base,
                variant_id=f"arsenal_atom_{_slug(atom['signature'])}",
                prompt_delta=atom["prompt_delta"],
                applied_dimensions=[],
                atom_signatures=[atom["signature"]],
                request_category=category,
            )
        )

    lane_index = 0
    while len(_dedupe_variants(variants, limit=budget)) < budget:
        lane = lanes[lane_index % len(lanes)]
        if any(_clean(str(variant.get("prompt_delta") or "")) == _clean(lane) for variant in variants):
            lane = f"{lane}; alternate exploration route {lane_index + 1}"
        variants.append(
            _variant(
                base_prompt=base,
                variant_id=f"arsenal_lane_{len(variants) + 1}",
                prompt_delta=lane,
                applied_dimensions=[],
                atom_signatures=[],
                request_category=category,
            )
        )
        lane_index += 1

    return _dedupe_variants(variants, limit=budget)


def _variant(
    *,
    base_prompt: str,
    variant_id: str,
    prompt_delta: str,
    applied_dimensions: list[str],
    atom_signatures: list[str],
    request_category: str,
    approved_prompt_entry: bool = False,
) -> dict[str, Any]:
    delta = _clean(prompt_delta)
    prompt = base_prompt
    if delta:
        prompt = f"{base_prompt}\n\nVisual Arsenal candidate strategy: {delta}"
    return {
        "variant_id": variant_id,
        "source": "visual_arsenal",
        "request_category": request_category,
        "prompt": prompt,
        "prompt_delta": delta,
        "applied_dimensions": applied_dimensions,
        "atom_signatures": atom_signatures,
        "approved_prompt_entry": approved_prompt_entry,
    }


def _repair_variants(
    feedback_policy: dict[str, Any],
    *,
    request_category: str,
) -> list[dict[str, str]]:
    values = feedback_policy.get("repair_dimensions") if isinstance(feedback_policy, dict) else []
    if not isinstance(values, list):
        return []
    variants = []
    seen: set[str] = set()
    for item in values:
        if not isinstance(item, dict):
            continue
        dimension = str(item.get("dimension") or "").strip()
        if not dimension or dimension in seen:
            continue
        delta = _dimension_delta(dimension, request_category=request_category)
        if not delta:
            continue
        variants.append({"dimension": dimension, "prompt_delta": delta})
        seen.add(dimension)
    return variants


def _dimension_delta(dimension: str, *, request_category: str) -> str:
    anime = _anime_like_category(request_category)
    if dimension == "subject_beauty":
        return (
            "raise subject attractiveness with a clean expressive anime face, appealing stylized "
            "proportions, confident expression"
            if anime
            else "raise subject attractiveness with clean facial features, flattering proportions, confident expression"
        )
    if dimension == "face_naturalness":
        return (
            "clean expressive anime face, symmetrical eyes, stable identity, polished facial details"
            if anime
            else "clean natural face, balanced eyes, stable identity, polished facial details"
        )
    if dimension == "glamour_impact":
        return (
            "strong glamorous anime silhouette, tasteful alluring styling, confident pose"
            if anime
            else "strong glamorous silhouette, tasteful alluring styling, confident pose"
        )
    if dimension == "fashion_material_quality":
        return (
            "refine wardrobe and legwear material texture, coherent fabric coverage, crisp highlights "
            "without plastic artifacts"
        )
    if dimension == "pose_composition":
        return (
            "dynamic contrapposto pose with clear line of action, torso twist, hip tilt, "
            "asymmetrical silhouette, alive gesture rhythm"
            if anime
            else "strong intentional pose, readable line of action, clean silhouette, balanced crop"
        )
    if dimension == "camera_composition":
        return (
            "off-axis low-angle three-quarter camera, diagonal S-curve composition, foreground overlap, "
            "intentional negative space, avoid centered static framing"
            if anime
            else "off-axis editorial camera, layered foreground depth, intentional negative space, avoid static framing"
        )
    if dimension == "lighting_depth":
        return (
            "warm key light, cool rim light, layered cast shadows, bounce light, controlled bloom, "
            "hand-painted lighting depth"
            if anime
            else "clear key light, rim light, cast shadows, bounce light, controlled highlights"
        )
    if dimension == "linework_finish":
        return (
            "variable tapered line weight, confident clean ink hierarchy, crisp hair strands, refined folds, "
            "no rough amateur outlines"
            if anime
            else "clean edge hierarchy, refined contours, crisp detail separation"
        )
    if dimension == "sensual_outfit_design":
        return (
            "specific seductive outfit construction: off-shoulder cut, high slit, corset or bodysuit tension, "
            "sheer sleeves or stockings, tasteful adult coverage"
            if anime
            else "specific tasteful sensual outfit construction with flattering tailoring and premium materials"
        )
    if dimension == "motion_quality" and not _anime_like_category(request_category):
        return "clear natural movement cue, stable anatomy, coherent frame-to-frame direction"
    return ""


def _atom_variants(strategy_plan: dict[str, Any], *, request_category: str) -> list[dict[str, str]]:
    signatures = strategy_plan.get("atom_signatures") if isinstance(strategy_plan, dict) else []
    if not isinstance(signatures, list):
        return []
    atoms = builtin_strategy_atom_map()
    variants = []
    for signature in signatures:
        if not isinstance(signature, str):
            continue
        atom = atoms.get(signature)
        if atom is None:
            continue
        delta = _style_bounded_atom_delta(signature, atom.prompt_delta, request_category=request_category)
        if not delta:
            continue
        variants.append({"signature": signature, "prompt_delta": delta})
    return variants


def _preferred_composition_delta(atom_variants: list[dict[str, str]]) -> str:
    for variant in atom_variants:
        signature = variant.get("signature", "")
        if signature == "composition.leg_emphasis_editorial@v1":
            return variant.get("prompt_delta", "")
    for variant in atom_variants:
        signature = variant.get("signature", "")
        if signature.startswith("composition."):
            return variant.get("prompt_delta", "")
    return ""


def _style_bounded_atom_delta(signature: str, prompt_delta: str, *, request_category: str) -> str:
    if signature.startswith("motion."):
        return ""
    if _anime_like_category(request_category):
        if signature == "composition.leg_emphasis_editorial@v1":
            return "dynamic full-body anime composition with elegant long leg line emphasis"
        if signature == "composition.full_subject_visible@v1":
            return "full character visible, clean readable anime frame, no accidental cropping"
        if signature == "safety.professional_editorial@v1":
            return "polished anime illustration finish, tasteful camera framing, no explicit content"
    if request_category == "product":
        if signature == "composition.full_subject_visible@v1":
            return "full product visible, clean readable product frame, no accidental cropping"
        if signature == "safety.professional_editorial@v1":
            return "premium product presentation, polished but faithful material rendering"
    return _clean(prompt_delta)


def _style_lanes(request_category: str) -> list[str]:
    if _anime_like_category(request_category):
        return [
            "high-quality anime illustration polish, crisp linework, vibrant color harmony",
            "strong character readability, stable identity, refined silhouette, clean hands and feet",
            "dynamic composition, appealing body rhythm, intentional crop, cinematic lighting",
        ]
    if request_category == "product":
        return [
            "faithful product shape, clean edges, readable material finish",
            "clean product photography, soft window light, minimal background",
        ]
    return [
        "polished final image, clear focal point, coherent anatomy or object geometry",
        "strong composition, refined lighting, clean details, no clutter",
    ]


def _anime_like_category(category: str) -> bool:
    return "anime" in str(category or "").lower()


def _safe_prompt_excerpt(prompt: str, *, limit: int = 900) -> str:
    lines = []
    for raw_line in str(prompt or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "image_path:" in line or "source images" in line.lower() or "visual arsenal source images" in line.lower():
            continue
        lines.append(line)
    text = _clean(" ".join(lines))
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].strip()


def _dedupe_variants(variants: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen_prompts: set[str] = set()
    for variant in variants:
        prompt = str(variant.get("prompt") or "")
        if prompt in seen_prompts:
            continue
        seen_prompts.add(prompt)
        deduped.append(variant)
        if len(deduped) >= limit:
            return deduped
    return deduped


def _clamp_int(value: Any, *, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = minimum
    return max(minimum, min(maximum, number))


def _clean(value: str) -> str:
    return " ".join(str(value or "").split())


def _join_deltas(*values: str) -> str:
    return "; ".join(value for value in (_clean(item) for item in values) if value)


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value).strip("_")
