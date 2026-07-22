from __future__ import annotations

import hashlib
import json
from typing import Any


SHOT_CONTRACT_FIELDS = (
    "narration_text",
    "narrative_role",
    "viewer_takeaway",
    "subject",
    "action",
    "evidence_detail",
    "shot_scale",
    "camera_angle",
    "camera_movement",
    "focal_point",
    "subtitle_safe_area",
    "acceptance_criteria",
    "risk_class",
    "engagement_role",
    "attention_hook",
    "story_moment",
    "action_consequence",
    "composition_energy",
    "viewer_emotion",
    "engagement_criteria",
    "visual_truth_mode",
    "evidence_bridge",
    "calm_reason",
    "continuity_anchors",
)


def shot_contract_hash(shot: dict[str, Any]) -> str:
    contract = {field: shot.get(field) for field in SHOT_CONTRACT_FIELDS}
    encoded = json.dumps(
        contract,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def manifest_row_matches_shot_contract(
    row: dict[str, Any],
    shot: dict[str, Any],
    fallback_prompt: str = "",
) -> bool:
    current_hash = shot_contract_hash(shot)
    stored_hash = str(row.get("shot_contract_hash") or "").strip()
    if stored_hash:
        return stored_hash == current_hash
    stored_scale = str(row.get("shot_scale") or "").strip()
    current_scale = str(shot.get("shot_scale") or "").strip()
    if stored_scale and current_scale and stored_scale != current_scale:
        return False
    prompt = str(row.get("generation_prompt") or fallback_prompt or "").strip()
    identifies_contract = any(
        marker in prompt
        for marker in ("Primary subject:", "Observable action:", "場景：", "動作：")
    )
    if identifies_contract:
        for field in ("subject", "action"):
            value = str(shot.get(field) or "").strip()
            if value and value not in prompt:
                return False
    return True


__all__ = [
    "SHOT_CONTRACT_FIELDS",
    "manifest_row_matches_shot_contract",
    "shot_contract_hash",
]
