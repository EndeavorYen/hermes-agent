from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from typing import Mapping


SCHEMA = "visual_intent_contract_v1"


@dataclass(frozen=True)
class VisualIntentContract:
    original_request: str
    primary_subject: str
    observable_action: str = ""
    decisive_moment: str = ""
    focal_point: str = ""
    composition: str = ""
    style: str = ""
    audience_effect: str = ""
    reference_roles: tuple[tuple[str, str], ...] = ()
    required_details: tuple[str, ...] = ()
    forbidden_details: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()
    aspect_ratio: str = ""
    truth_mode: str = ""

    def to_canonical_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "original_request": self.original_request,
            "primary_subject": self.primary_subject,
            "observable_action": self.observable_action,
            "decisive_moment": self.decisive_moment,
            "focal_point": self.focal_point,
            "composition": self.composition,
            "style": self.style,
            "audience_effect": self.audience_effect,
            "reference_roles": [list(item) for item in self.reference_roles],
            "required_details": list(self.required_details),
            "forbidden_details": list(self.forbidden_details),
            "acceptance_criteria": list(self.acceptance_criteria),
            "aspect_ratio": self.aspect_ratio,
            "truth_mode": self.truth_mode,
        }


def compile_visual_intent_contract(
    prompt: str,
    request_context: Mapping[str, Any] | None = None,
) -> VisualIntentContract:
    context = request_context or {}
    original_request = _text(prompt)
    primary_subject = _text(context.get("primary_subject")) or original_request
    acceptance_criteria = _text_tuple(context.get("acceptance_criteria"))
    if not acceptance_criteria:
        acceptance_criteria = (
            "the primary subject is immediately readable",
            "the composition preserves the requested focal hierarchy",
            "the artifact has no obvious generation defects",
        )
    return VisualIntentContract(
        original_request=original_request,
        primary_subject=primary_subject,
        observable_action=_text(context.get("observable_action") or context.get("action")),
        decisive_moment=_text(context.get("decisive_moment") or context.get("story_moment")),
        focal_point=_text(context.get("focal_point")),
        composition=_text(context.get("composition")),
        style=_text(context.get("style")),
        audience_effect=_text(context.get("audience_effect") or context.get("viewer_emotion")),
        reference_roles=_reference_roles(context.get("reference_roles")),
        required_details=_text_tuple(context.get("required_details")),
        forbidden_details=_text_tuple(context.get("forbidden_details")),
        acceptance_criteria=acceptance_criteria,
        aspect_ratio=_text(context.get("aspect_ratio")),
        truth_mode=_text(context.get("truth_mode") or context.get("visual_truth_mode")),
    )


def visual_contract_hash(contract: VisualIntentContract) -> str:
    encoded = json.dumps(
        contract.to_canonical_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _reference_roles(value: Any) -> tuple[tuple[str, str], ...]:
    if isinstance(value, Mapping):
        return tuple(
            (str(key).strip(), str(role).strip())
            for key, role in sorted(value.items(), key=lambda item: str(item[0]))
            if str(key).strip() and str(role).strip()
        )
    if not isinstance(value, (list, tuple)):
        return ()
    roles: list[tuple[str, str]] = []
    for item in value:
        if isinstance(item, Mapping):
            source = _text(item.get("source") or item.get("uri") or item.get("path"))
            role = _text(item.get("role") or item.get("role_hint"))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            source, role = _text(item[0]), _text(item[1])
        else:
            continue
        if source and role:
            roles.append((source, role))
    return tuple(roles)


def _text_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(text for item in value if (text := _text(item)))


def _text(value: Any) -> str:
    return str(value or "").strip()
