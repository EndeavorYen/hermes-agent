from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StrategyAtom:
    atom_id: str
    version: str
    kind: str
    public_summary: str
    prompt_delta: str
    negative_delta: str = ""

    @property
    def signature(self) -> str:
        return f"{self.atom_id}@{self.version}"

    def to_record(self) -> dict[str, Any]:
        return {
            "signature": self.signature,
            "atom_id": self.atom_id,
            "version": self.version,
            "kind": self.kind,
            "public_summary": self.public_summary,
            "prompt_delta": self.prompt_delta,
            "negative_delta": self.negative_delta,
        }


def builtin_strategy_atoms() -> list[StrategyAtom]:
    return [
        StrategyAtom(
            atom_id="composition.full_subject_visible",
            version="v1",
            kind="composition",
            public_summary="keep the full subject visible with a clean readable frame",
            prompt_delta="full subject visible, clean readable frame, no accidental cropping",
            negative_delta="cropped subject, cut off head, cut off feet",
        ),
        StrategyAtom(
            atom_id="composition.leg_emphasis_editorial",
            version="v1",
            kind="composition",
            public_summary="editorial composition that emphasizes long leg lines",
            prompt_delta="editorial full-body composition, elegant long leg line emphasis",
            negative_delta="shortened legs, awkward limb proportions",
        ),
        StrategyAtom(
            atom_id="motion.camera_push_in",
            version="v1",
            kind="motion",
            public_summary="subtle camera push-in for short video packages",
            prompt_delta="subtle cinematic camera push-in, natural motion",
            negative_delta="frozen frame, slow motion only, stretched video",
        ),
        StrategyAtom(
            atom_id="motion.subject_turn_subtle",
            version="v1",
            kind="motion",
            public_summary="small subject turn with stable identity",
            prompt_delta="small natural subject turn, stable identity, controlled movement",
            negative_delta="face morphing, identity drift, excessive movement",
        ),
        StrategyAtom(
            atom_id="safety.professional_editorial",
            version="v1",
            kind="safety",
            public_summary="professional editorial framing",
            prompt_delta="professional editorial photography, polished but natural",
            negative_delta="explicit content, unsafe framing",
        ),
        StrategyAtom(
            atom_id="product.clean_window_light",
            version="v1",
            kind="product",
            public_summary="clean product photography with soft window light",
            prompt_delta="clean product photography, soft window light, minimal background",
            negative_delta="cluttered background, harsh flash",
        ),
    ]


def builtin_strategy_atom_map() -> dict[str, StrategyAtom]:
    return {atom.signature: atom for atom in builtin_strategy_atoms()}
