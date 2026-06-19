"""In-memory asset graph for Visual Agent Mode missions."""

from __future__ import annotations

from dataclasses import replace
import uuid
from typing import Any, Dict, List, Optional

from agent.visual.agent_mode.types import VisualArtifactRole, VisualAssetNode


class VisualAssetGraph:
    """Track visual asset lineage within one mission."""

    def __init__(self, mission_id: str) -> None:
        self.mission_id = mission_id
        self._assets: Dict[str, VisualAssetNode] = {}

    def add_asset(
        self,
        *,
        role: VisualArtifactRole,
        artifact_id: Optional[str] = None,
        local_path: Optional[str] = None,
        source_url: Optional[str] = None,
        parent_asset_ids: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> VisualAssetNode:
        asset = VisualAssetNode(
            asset_id=_new_asset_id(),
            role=role,
            artifact_id=artifact_id,
            local_path=local_path,
            source_url=source_url,
            parent_asset_ids=list(parent_asset_ids or []),
            metadata=dict(metadata or {}),
        )
        self._assets[asset.asset_id] = asset
        return asset

    def link(self, parent_asset_id: str, child_asset_id: str) -> None:
        if parent_asset_id not in self._assets:
            raise KeyError(parent_asset_id)
        child = self._assets[child_asset_id]
        parents = list(child.parent_asset_ids)
        if parent_asset_id not in parents:
            parents.append(parent_asset_id)
        self._assets[child_asset_id] = replace(child, parent_asset_ids=parents)

    def parents(self, asset_id: str) -> List[str]:
        return list(self._assets[asset_id].parent_asset_ids)

    def selected_artifact_ids(self, role: VisualArtifactRole) -> List[str]:
        return [
            asset.artifact_id
            for asset in self._assets.values()
            if asset.role == role and asset.artifact_id
        ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "assets": [
                {
                    "asset_id": asset.asset_id,
                    "role": asset.role.value,
                    "artifact_id": asset.artifact_id,
                    "local_path": asset.local_path,
                    "source_url": asset.source_url,
                    "parent_asset_ids": list(asset.parent_asset_ids),
                    "metadata": dict(asset.metadata),
                }
                for asset in self._assets.values()
            ],
        }


def _new_asset_id() -> str:
    return f"vas_{uuid.uuid4().hex}"
