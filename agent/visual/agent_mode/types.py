"""Shared types for Visual Agent Mode."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class VisualMissionType(str, Enum):
    IMAGE_SET = "image_set"
    IMAGE_TO_VIDEO = "image_to_video"
    VISUAL_PACKAGE = "visual_package"
    REPAIR_EXISTING = "repair_existing"


class VisualArtifactRole(str, Enum):
    UPLOADED_REFERENCE = "uploaded_reference"
    GENERATED_IMAGE = "generated_image"
    SELECTED_IMAGE = "selected_image"
    GENERATED_VIDEO = "generated_video"
    FINAL_DELIVERY = "final_delivery"


@dataclass(frozen=True)
class VisualMission:
    mission_id: str
    mission_type: VisualMissionType
    user_prompt: str
    output_goal: str
    requested_outputs: List[str]
    constraints: Dict[str, Any] = field(default_factory=dict)
    preferences: Dict[str, Any] = field(default_factory=dict)
    input_assets: List[str] = field(default_factory=list)
    candidate_budget: int = 3
    video_budget: int = 1
    autonomy_level: int = 1


@dataclass(frozen=True)
class VisualAssetNode:
    asset_id: str
    role: VisualArtifactRole
    artifact_id: Optional[str] = None
    local_path: Optional[str] = None
    source_url: Optional[str] = None
    parent_asset_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VisualMissionResult:
    success: bool
    mission_id: str
    selected_image_artifact_ids: List[str]
    selected_video_artifact_ids: List[str]
    delivery_metadata: Dict[str, Any]
    summary: str
    stop_reason: Optional[str] = None

