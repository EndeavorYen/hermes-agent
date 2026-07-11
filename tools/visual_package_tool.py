from __future__ import annotations

import datetime
import hashlib
import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from urllib.parse import urlparse
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

from agent.visual.active_learning import decide_visual_action
from agent.visual.agent_mode.handoff import is_visual_prompt_disclosure_request
from agent.visual.agent_mode.handoff import normalise_visual_agent_attachment
from agent.visual.arsenal_prompt import build_arsenal_prompt_variants
from agent.visual.artifact_observation import build_artifact_observation
from agent.visual.aspect_policy import select_video_aspect_ratio
from agent.visual.attempt_ledger import VisualAttemptLedger
from agent.visual.autonomous_orchestration import build_post_generation_orchestration
from agent.visual.autonomous_validation import validate_visual_generation_payload
from agent.visual.feedback_policy import resolve_visual_feedback_policy
from agent.visual.feedback import is_visual_feedback_only_text
from agent.visual.intent_signature import build_intent_signature
from agent.visual.judges.deterministic import judge_artifact
from agent.visual.judges.quality import judge_visual_quality
from agent.visual.media_probe import probe_media_reference
from agent.visual.preference_profile import build_preference_profile
from agent.visual.prompt_arsenal import approved_prompt_arsenal_entries
from agent.visual.prompt_text import build_provider_facing_visual_prompt
from agent.visual.prompt_text import strip_visual_prompt_metadata
from agent.visual.provider_failures import classify_visual_provider_failure
from agent.visual.provider_stats import compute_provider_reliability
from agent.visual.ranker import rank_visual_candidates
from agent.visual.reference_similarity import augment_observation_with_reference_similarity
from agent.visual.recovery import plan_visual_recovery
from agent.visual.reward_model import score_visual_candidate
from agent.visual.shadow_learning import record_shadow_update
from agent.visual.strategy_policy import StrategyPlan
from agent.visual.strategy_policy import find_controlled_strategy_plan
from agent.visual.strategy_policy import select_strategy_plan
from agent.visual.tracking import default_visual_ledger_path
from agent.visual.tracking import visual_delivery_metadata
from agent.visual.video_hardening import build_hardened_video_request
from agent.visual.vision_evaluator import build_candidate_vision_observation
from tools.registry import registry
from tools.registry import tool_error
from tools.story_video_provider_guard import normalize_visual_provider
from tools.story_video_provider_guard import resolve_story_video_image_provider
from tools.story_video_provider_guard import story_video_video_block_payload
from tools.url_safety import is_safe_url

logger = logging.getLogger(__name__)

MAX_REMOTE_MEDIA_BYTES = 150 * 1024 * 1024
MAX_REMOTE_MEDIA_REDIRECTS = 5
REMOTE_MEDIA_TIMEOUT_SECONDS = 60.0
MAX_RUNTIME_POLICY_SNAPSHOT_BYTES = 1024 * 1024
MAX_RUNTIME_POLICY_ACTIONS = 32
DEFAULT_VISUAL_EXECUTION_DEADLINE_SECONDS = 300.0
MAX_VISUAL_EXECUTION_DEADLINE_SECONDS = 1800.0
VISUAL_PROVIDER_REFERENCE_SLOT_BUDGET = 3
ALWAYS_BLOCKING_QUALITY_ISSUES = {
    "composition_bad",
    "reference_identity_drift",
    "reference_overcopy",
    "reference_role_evidence_missing",
    "source_frame_grid",
}
VIDEO_BLOCKING_QUALITY_ISSUES = {
    "aspect_integrity_bad",
    "motion_bad",
}
PORTRAIT_BLOCKING_QUALITY_ISSUES = {
    "subject_not_attractive",
    "not_beautiful",
    "stockings_bad",
}
PREFERENCE_DIMENSION_DELIVERY_THRESHOLD = 0.5


_monotonic = time.monotonic


@dataclass
class _VisualExecutionDeadline:
    configured_seconds: float
    started_at: float
    expires_at: float
    completed_provider_calls: list[dict[str, Any]]


class _VisualPackageDeadlineExceeded(RuntimeError):
    def __init__(self, *, stage: str, deadline: _VisualExecutionDeadline, now: float) -> None:
        super().__init__("visual package execution deadline exceeded")
        self.stage = stage
        self.deadline = deadline
        self.now = now

    def deadline_payload(self) -> dict[str, Any]:
        return {
            "expired": True,
            "stage": self.stage,
            "configured_seconds": self.deadline.configured_seconds,
            "elapsed_seconds": max(0.0, self.now - self.deadline.started_at),
        }

    def partial_evidence(self) -> dict[str, Any]:
        calls = [dict(item) for item in self.deadline.completed_provider_calls]
        return {
            "completed_provider_call_count": len(calls),
            "completed_provider_calls": calls,
        }


_ACTIVE_EXECUTION_DEADLINE: ContextVar[_VisualExecutionDeadline | None] = ContextVar(
    "visual_package_execution_deadline",
    default=None,
)


def _configured_execution_deadline_seconds(args: dict[str, Any]) -> float:
    value: Any = args.get("execution_deadline_seconds")
    if value in (None, ""):
        value = os.getenv("HERMES_VISUAL_EXECUTION_DEADLINE_SECONDS")
    if value in (None, ""):
        try:
            from hermes_cli.config import read_raw_config

            config = read_raw_config()
            visual = config.get("visual") if isinstance(config, dict) else None
            if isinstance(visual, dict):
                value = visual.get("execution_deadline_seconds")
        except Exception:
            value = None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        seconds = DEFAULT_VISUAL_EXECUTION_DEADLINE_SECONDS
    if not math.isfinite(seconds) or seconds <= 0:
        seconds = DEFAULT_VISUAL_EXECUTION_DEADLINE_SECONDS
    return max(1.0, min(seconds, MAX_VISUAL_EXECUTION_DEADLINE_SECONDS))


def _new_execution_deadline(args: dict[str, Any]) -> _VisualExecutionDeadline:
    configured_seconds = _configured_execution_deadline_seconds(args)
    started_at = _monotonic()
    return _VisualExecutionDeadline(
        configured_seconds=configured_seconds,
        started_at=started_at,
        expires_at=started_at + configured_seconds,
        completed_provider_calls=[],
    )


def _deadline_checkpoint(stage: str) -> None:
    deadline = _ACTIVE_EXECUTION_DEADLINE.get()
    if deadline is None:
        return
    now = _monotonic()
    if now >= deadline.expires_at:
        raise _VisualPackageDeadlineExceeded(stage=stage, deadline=deadline, now=now)


def _provider_media_count(payload: dict[str, Any], *, kind: str) -> int:
    singular = payload.get(kind)
    plural = payload.get(f"{kind}s")
    if isinstance(singular, str) and singular:
        return 1
    if isinstance(plural, list):
        return len([item for item in plural if isinstance(item, str) and item])
    return 0


def _record_completed_provider_call(*, kind: str, payload: dict[str, Any]) -> None:
    deadline = _ACTIVE_EXECUTION_DEADLINE.get()
    if deadline is None:
        return
    deadline.completed_provider_calls.append(
        {
            "kind": kind,
            "provider": str(payload.get("provider") or ""),
            "model": str(payload.get("model") or ""),
            "success": payload.get("success") is True,
            "media_count": _provider_media_count(payload, kind=kind),
        }
    )


def _call_generation_provider(
    generator,
    *,
    kind: str,
    stage: str,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    _deadline_checkpoint(stage)
    payload = generator(**kwargs)
    _record_completed_provider_call(kind=kind, payload=payload)
    _deadline_checkpoint(f"{stage}:complete")
    return payload
INLINE_VISION_JUDGE_PROMPT = """\
Evaluate this generated visual artifact for automated quality ranking.
Return only a JSON object with numeric values from 0.0 to 1.0:
{
  "reference_adherence": 0.5,
  "character_identity_adherence": 0.5,
  "pose_composition_adherence": 0.5,
  "wardrobe_adherence": 0.5,
  "subject_quality": 0.5,
  "face_quality": 0.5,
  "visual_appeal": 0.5,
  "glamour_impact": 0.5,
  "composition": 0.5,
  "pose_composition": 0.5,
  "pose_novelty": 0.5,
  "fashion_material_quality": 0.5,
  "stocking_quality": 0.5,
  "artifact_defects": []
}
Use character_identity_adherence for whether the output preserves the intended character/person identity from the identity reference.
Use pose_composition_adherence for whether the output follows the intended pose, camera angle, and composition reference.
If the output copies identity, face, hair, wardrobe, or character traits from a pose/composition-only reference, include "reference_identity_drift" in artifact_defects.
If pose/composition is weak, include "pose_composition_weak" in artifact_defects.
If the output visibly inherits contour-map, line-art, silhouette-guide, or edge-guide artifacts, include "guide_artifact_contamination".
If outlines, limbs, fabric, or background look melted, wavy, rubbery, or warped by a guide image, include "melted_or_wavy_contours".
If anatomy, hands, feet, legs, or body proportions are distorted, include "distorted_anatomy".
Do not include names, private prompt text, file paths, or prose.
"""
REFERENCE_AWARE_INLINE_VISION_PROMPT = """\
You are seeing a single contact sheet with labeled panels. The left panels are user-supplied references;
the final panel is the generated candidate output. Evaluate only whether the candidate output satisfies
the requested role transfer.

Return only a JSON object with numeric values from 0.0 to 1.0:
{
  "reference_adherence": 0.5,
  "character_identity_adherence": 0.5,
  "pose_composition_adherence": 0.5,
  "wardrobe_adherence": 0.5,
  "subject_quality": 0.5,
  "face_quality": 0.5,
  "visual_appeal": 0.5,
  "glamour_impact": 0.5,
  "composition": 0.5,
  "pose_composition": 0.5,
  "pose_novelty": 0.5,
  "fashion_material_quality": 0.5,
  "stocking_quality": 0.5,
  "artifact_defects": []
}
For a character_identity reference, compare the candidate's character identity, hair, eye color, face,
signature outfit, silhouette, and distinctive accessories against that reference.
For a pose_composition reference, compare pose, camera angle, framing, body orientation, and scene layout.
Use each reference only for its labeled role. If the candidate copies identity, face, hair, wardrobe,
or character traits from a pose/composition-only reference, include "reference_identity_drift" in
artifact_defects and lower character_identity_adherence / wardrobe_adherence. If the candidate misses
the pose/composition reference, include "pose_composition_weak".
If the candidate visually inherits contour-map, line-art, silhouette-guide, or edge-guide artifacts,
include "guide_artifact_contamination". If outlines, limbs, fabric, or background look melted, wavy,
rubbery, or warped by a guide image, include "melted_or_wavy_contours". If anatomy, hands, feet, legs,
or body proportions are distorted, include "distorted_anatomy".
Do not include names, private prompt text, file paths, or prose.
"""


VISUAL_PACKAGE_SCHEMA: dict[str, Any] = {
    "name": "visual_package_generate",
    "description": (
        "Generate a coordinated visual package when the user naturally asks "
        "for both an image and a video, a set of visual assets, a product photo "
        "plus short clip, a 寫真影片, or similar. Use this instead of separate image_generate "
        "and video_generate calls for requests like '請產出一張圖片和一段影片', "
        "'做一組視覺素材', 'image plus short video', 'fashion portrait video', "
        "or 'product photo and 6 second clip'. For text-only visual video requests, "
        "this tool uses the image-first route: generate image candidates, rank/select "
        "one, then animate the selected image. "
        "The tool generates candidates, records evidence, ranks artifacts, and "
        "returns only selected current media plus delivery metadata."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Natural-language visual package request.",
            },
            "attachments": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional image paths or URLs supplied by the user.",
            },
            "aspect_ratio": {
                "type": "string",
                "description": "Optional shared aspect ratio, e.g. 16:9, 9:16, 1:1, landscape, portrait, square.",
            },
            "duration": {
                "type": "integer",
                "description": "Optional desired video duration in seconds.",
            },
            "candidate_budget": {
                "type": "integer",
                "description": "Optional image candidate budget. Defaults to 2.",
            },
            "include_image": {
                "type": "boolean",
                "description": (
                    "Whether to deliver a selected image. For video-only requests, set false; "
                    "the tool may still generate internal source images for image-first video."
                ),
            },
            "include_video": {
                "type": "boolean",
                "description": "Whether to generate and deliver selected video output.",
            },
            "video_budget": {
                "type": "integer",
                "description": "Optional video candidate budget. Defaults to 1.",
            },
            "execution_deadline_seconds": {
                "type": "number",
                "minimum": 1,
                "maximum": MAX_VISUAL_EXECUTION_DEADLINE_SECONDS,
                "description": (
                    "Operator override for the bounded visual-package execution deadline. "
                    "Natural requests use the configured 300-second default."
                ),
            },
            "image_provider": {
                "type": "string",
                "description": (
                    "Optional image backend override inferred from user intent, "
                    "for example xai/grok-imagine or openai-codex/image2."
                ),
            },
            "image_provider_source": {
                "type": "string",
                "description": "Optional source marker for the image provider decision.",
            },
            "reference_binding": {
                "type": "object",
                "description": "Optional reference role mapping inferred from user-visible upload order.",
            },
            "reference_conditioning_policy": {
                "type": "string",
                "description": "Optional reference conditioning policy such as structure_guide.",
            },
            "character_design_ref_only": {
                "type": "boolean",
                "description": "Generate an OpenAI-safe character design reference for later final composition.",
            },
            "composition_guide_only": {
                "type": "boolean",
                "description": "Generate an abstract pose/composition guide, not final character art.",
            },
            "hybrid_final_combine": {
                "type": "boolean",
                "description": "Generate a final image by combining character-design and pose/composition references.",
            },
            "storyboard": {
                "type": "object",
                "description": (
                    "Optional multi-shot video contract. Each shot must use one ranked source image; "
                    "do not pass a collage or candidate grid as a single video source."
                ),
            },
            "autonomy_level": {
                "type": "integer",
                "description": "Optional advanced autonomy level reserved for learning gates.",
            },
        },
        "required": ["prompt"],
    },
}


def check_visual_package_requirements() -> bool:
    try:
        from tools.image_generation_tool import check_image_generation_requirements

        return bool(check_image_generation_requirements())
    except Exception:
        return False


def generate_image(**kwargs: Any) -> dict[str, Any]:
    from tools.image_generation_tool import _handle_image_generate

    kwargs = {
        **kwargs,
        "_disable_visual_agent_route": True,
        "_disable_visual_tracking": True,
    }
    return json.loads(_handle_image_generate(kwargs))


def generate_video(**kwargs: Any) -> dict[str, Any]:
    from tools.video_generation_tool import _handle_video_generate

    return json.loads(_handle_video_generate(kwargs))


def _image_provider_override(args: dict[str, Any], *, prompt: str | None = None) -> str | None:
    if not isinstance(args, dict):
        return None
    for key in ("_provider", "image_provider", "provider"):
        provider = _normalise_image_provider(args.get(key))
        if provider:
            return provider
    return None


def _normalise_image_provider(value: Any, *, allow_unknown: bool = True) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    lowered = re.sub(r"\s+", " ", raw.lower())
    if lowered in {
        "grok-web-imagine",
        "grok web imagine",
        "grok_web_imagine",
        "grokwebimagine",
        "grok-web",
        "grok web",
        "grok_web",
        "grokweb",
    }:
        return "grok-web-imagine"
    normalized = normalize_visual_provider(raw)
    if allow_unknown:
        return normalized
    if normalized in {"xai", "openai-codex"}:
        return normalized
    return None


def _apply_image_provider_override(kwargs: dict[str, Any], provider: str | None) -> None:
    if provider:
        kwargs["_provider"] = provider


def _story_video_visual_package_block_payload(
    error_payload: dict[str, Any],
) -> dict[str, Any]:
    required_image_provider = error_payload.get("required_image_provider") or error_payload.get(
        "required_provider"
    )
    required_workflow = error_payload.get("required_workflow") or "story-video-production-pipeline"
    return {
        "success": False,
        "package_status": "failed",
        "error": error_payload.get("error"),
        "error_type": error_payload.get("error_type"),
        "images": [],
        "videos": [],
        "provider": error_payload.get("provider"),
        "model": error_payload.get("model"),
        "required_image_provider": required_image_provider,
        "required_workflow": required_workflow,
        "generation_strategy": {
            "story_video_provider_guard": True,
            "required_image_provider": required_image_provider,
            "required_workflow": required_workflow,
        },
    }


def _image_provider_source(args: dict[str, Any]) -> str | None:
    raw = str(args.get("image_provider_source") or "").strip()
    if raw in {"visual_agent_default", "prompt_override", "explicit_override"}:
        return raw
    return None


def _grok_web_imagine_policy(
    args: dict[str, Any],
    *,
    image_provider_override: str | None,
    image_provider_source: str | None,
) -> dict[str, Any] | None:
    if image_provider_override != "grok-web-imagine":
        return None
    source = image_provider_source or "explicit_override"
    return {
        "enabled": True,
        "mode": "controlled_visual_agent_provider",
        "source": source,
        "handoff_mode": str(args.get("visual_agent_handoff_mode") or "").strip() or None,
    }


def _polish_provider_override(args: dict[str, Any], *, prompt: str | None = None) -> str | None:
    for key in ("polish_provider", "quality_polish_provider"):
        provider = _normalise_image_provider(args.get(key))
        if provider:
            return provider
    if _coerce_bool(args.get("grok_web_polish")):
        return "grok-web-imagine"
    provider = _normalise_polish_provider_from_prompt(prompt)
    if provider:
        return provider
    return None


def _normalise_polish_provider_from_prompt(prompt: str | None) -> str | None:
    text = _current_visual_instruction(prompt or "")
    lowered = text.lower()
    compact = re.sub(r"[\s_\-.]+", "", lowered)
    if "prompt" in lowered or "提示詞" in lowered or "提示词" in lowered:
        return None
    has_polish = any(
        token in lowered
        for token in (
            "polish",
            "refine",
            "enhance",
            "quality pass",
            "quality polish",
            "web polish",
        )
    ) or any(
        token in re.sub(r"\s+", "", lowered)
        for token in ("精修", "修圖", "润饰", "潤飾", "美化", "畫質提升", "品质提升", "品質提升")
    )
    if not has_polish:
        return None
    if "grok web" in lowered or "web polish" in lowered or compact == "grokwebpolish":
        return "grok-web-imagine"
    return None


def _current_visual_instruction(prompt: str) -> str:
    text = strip_visual_prompt_metadata(prompt)
    if "[End of thread context]" in text:
        text = text.split("[End of thread context]", 1)[1]
    for marker in (
        "Session visual context:",
        "Reference policy for unassigned uploaded images:",
        "Provider-ready visual prompt:",
    ):
        if marker in text:
            text = text.split(marker, 1)[0]
    return text.strip()


def _direct_polish_source_image(
    *,
    prompt: str,
    args: dict[str, Any],
    attachments: list[str],
    reference_binding: dict[str, Any] | None,
    polish_provider: str | None,
    wants_video: bool,
) -> str | None:
    if not polish_provider or wants_video:
        return None
    if args.get("direct_polish") is False:
        return None
    instruction = _current_visual_instruction(prompt)
    if not _normalise_polish_provider_from_prompt(instruction) and not _coerce_bool(
        args.get("grok_web_polish")
    ):
        if not any(args.get(key) for key in ("polish_provider", "quality_polish_provider")):
            return None
    lowered = instruction.lower()
    compact = re.sub(r"\s+", "", lowered)
    new_generation_markers = (
        "new pose",
        "different pose",
        "new composition",
        "different composition",
        "candidate",
        "candidates",
        "重新生成",
        "重新產生",
        "重新產出",
        "不同姿勢",
        "不同構圖",
        "換個姿勢",
        "換個構圖",
        "候選",
    )
    if any(marker in lowered for marker in new_generation_markers) or any(
        marker in compact for marker in ("不同姿勢", "不同構圖", "換個姿勢", "換個構圖", "候選")
    ):
        return None
    return _reference_role_attachment(
        attachments,
        reference_binding,
        role_hint="edit_anchor",
    )


def _should_run_image_polish_pass(
    *,
    polish_provider: str | None,
    selected_image: dict[str, Any] | None,
) -> bool:
    return bool(
        polish_provider
        and selected_image
        and isinstance(selected_image.get("artifact_path"), str)
        and selected_image.get("artifact_path", "").strip()
    )


def _grok_web_current_result_operation(
    *,
    args: dict[str, Any],
    prompt: str,
    image_provider: str | None,
    polish_provider: str | None,
    direct_polish_mode: bool,
    image_reference_source: str | None,
) -> str | None:
    explicit = str(
        args.get("image_operation")
        or args.get("grok_web_operation")
        or args.get("operation")
        or ""
    ).strip()
    if explicit:
        return explicit
    active_provider = polish_provider if direct_polish_mode else image_provider
    if active_provider != "grok-web-imagine":
        return None
    if not direct_polish_mode and image_reference_source != "session_visual_context":
        return None
    instruction = _current_visual_instruction(prompt)
    if _is_regenerate_only_instruction(instruction):
        return "regenerate_current"
    return "continue_current"


def _is_regenerate_only_instruction(prompt: str) -> bool:
    text = str(prompt or "").strip().lower()
    if not text:
        return False
    compact = re.sub(r"\s+", "", text)
    regen_markers = (
        "regenerate",
        "reroll",
        "retry",
        "redo",
        "try again",
        "重新產生",
        "重新生成",
        "再生成",
        "重試",
        "重试",
        "重做",
        "再抽",
        "重抽",
    )
    if not any(marker in text for marker in regen_markers) and not any(
        marker in compact for marker in regen_markers
    ):
        return False
    change_markers = (
        "different",
        "change",
        "modify",
        "adjust",
        "improve",
        "add",
        "remove",
        "keep",
        "不同",
        "換",
        "改",
        "調整",
        "優化",
        "改善",
        "增加",
        "移除",
        "保持",
        "固定",
        "類似",
    )
    return not any(marker in text for marker in change_markers) and not any(
        marker in compact for marker in change_markers
    )


def _session_visual_reference_attachments(
    prompt: str,
    attachments: list[str],
) -> tuple[list[str], str | None, list[dict[str, Any]]]:
    if attachments:
        return attachments, None, []
    try:
        from agent.visual.session_references import session_visual_reference_entries_for_prompt
    except Exception as exc:  # noqa: BLE001
        logger.debug("Session visual reference lookup unavailable: %s", exc)
        return attachments, None, []
    entries = session_visual_reference_entries_for_prompt(prompt)
    refs = [
        str(entry.get("uri") or "").strip()
        for entry in entries
        if isinstance(entry, dict) and str(entry.get("uri") or "").strip()
    ]
    if not refs:
        return attachments, None, []
    return refs, "session_visual_context", entries


def analyze_candidate_with_vision_tool(candidate: dict[str, Any]) -> dict[str, Any]:
    source = _candidate_visual_source(candidate)
    if not source:
        raise ValueError("candidate has no analyzable image source")
    prompt = INLINE_VISION_JUDGE_PROMPT
    reference_source = _build_reference_aware_contact_sheet(candidate, source)
    if reference_source:
        source = reference_source
        prompt = _reference_aware_inline_vision_prompt(candidate)
    from model_tools import _run_async
    from tools.vision_tools import vision_analyze_tool

    raw = _run_async(vision_analyze_tool(source, prompt))
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"analysis": raw}
    return raw if isinstance(raw, dict) else {"analysis": str(raw)}


def _reference_aware_inline_vision_prompt(candidate: dict[str, Any]) -> str:
    lines = [REFERENCE_AWARE_INLINE_VISION_PROMPT.rstrip(), "", "Reference roles in the contact sheet:"]
    for artifact in _candidate_input_artifacts(candidate):
        index = _coerce_int(artifact.get("index"))
        role_hint = str(artifact.get("role_hint") or "visual_reference").strip() or "visual_reference"
        if index is not None:
            lines.append(f"- ref {index} role: {role_hint}")
    lines.append("- candidate output: generated image to evaluate")
    return "\n".join(lines)


def _build_reference_aware_contact_sheet(candidate: dict[str, Any], candidate_source: str) -> str | None:
    artifacts = _candidate_input_artifacts(candidate)
    if not artifacts:
        return None
    panels: list[tuple[str, str]] = []
    for artifact in artifacts:
        uri = str(artifact.get("uri") or artifact.get("path") or artifact.get("attachment") or "").strip()
        if not uri or not Path(uri).is_file():
            continue
        index = _coerce_int(artifact.get("index"))
        role_hint = str(artifact.get("role_hint") or "visual_reference").strip() or "visual_reference"
        label = f"ref {index or len(panels) + 1}: {role_hint}"
        panels.append((label, uri))
    if not panels or not Path(candidate_source).is_file():
        return None
    panels.append(("candidate output", candidate_source))
    try:
        return str(_write_reference_contact_sheet(panels))
    except Exception as exc:  # noqa: BLE001 - fallback to single-image judge
        logger.debug("reference-aware contact sheet unavailable: %s", exc)
        return None


def _candidate_input_artifacts(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    value = candidate.get("input_artifacts")
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _write_reference_contact_sheet(panels: list[tuple[str, str]]) -> Path:
    from PIL import Image
    from PIL import ImageDraw
    from PIL import ImageOps

    cell_width = 448
    cell_height = 640
    label_height = 34
    padding = 12
    sheet_width = len(panels) * cell_width + (len(panels) + 1) * padding
    sheet_height = cell_height + label_height + padding * 3
    sheet = Image.new("RGB", (sheet_width, sheet_height), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    x = padding
    for label, path in panels:
        with Image.open(path) as image:
            image = ImageOps.contain(image.convert("RGB"), (cell_width, cell_height))
            y = padding + label_height + max(0, (cell_height - image.height) // 2)
            draw.rectangle(
                [x, padding, x + cell_width, padding + label_height + cell_height],
                outline=(180, 180, 180),
                width=2,
            )
            draw.text((x + 8, padding + 9), label[:56], fill=(20, 20, 20))
            sheet.paste(image, (x + max(0, (cell_width - image.width) // 2), y))
        x += cell_width + padding
    digest = hashlib.sha256(
        "|".join(f"{label}:{path}" for label, path in panels).encode("utf-8")
    ).hexdigest()[:16]
    out_dir = default_visual_ledger_path().parent / "reference_contact_sheets"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"reference_contact_sheet_{digest}.jpg"
    sheet.save(out_path, format="JPEG", quality=90)
    return out_path


def _handle_visual_package_generate(args: dict[str, Any], **_kw: Any) -> str:
    prompt = strip_visual_prompt_metadata(args.get("prompt"))
    if not prompt:
        return tool_error("prompt is required for visual package generation")
    if is_visual_prompt_disclosure_request(prompt):
        return tool_error(
            "visual_package_generate is for image/video generation, not prompt disclosure",
            request_type="visual_prompt_disclosure",
        )
    if is_visual_feedback_only_text(prompt) and not _normalise_polish_provider_from_prompt(prompt):
        return tool_error(
            "visual_package_generate is for image/video generation, not visual feedback",
            request_type="visual_feedback",
        )
    deadline_token = _ACTIVE_EXECUTION_DEADLINE.set(_new_execution_deadline(args))
    try:
        _deadline_checkpoint("request_start")
        payload = _visual_package_generate(args, prompt=prompt)
        return json.dumps(payload, ensure_ascii=False)
    except _VisualPackageDeadlineExceeded as exc:
        return json.dumps(
            {
                "success": False,
                "package_status": "partial",
                "error": "visual package execution deadline exceeded",
                "error_type": "visual_package_deadline_exceeded",
                "deadline": exc.deadline_payload(),
                "partial_evidence": exc.partial_evidence(),
            },
            ensure_ascii=False,
        )
    except Exception as exc:  # noqa: BLE001 - tool should surface structured failure
        logger.warning("visual package generation failed: %s", exc)
        failure = _visual_package_exception_failure(exc)
        return json.dumps(
            {
                "success": False,
                "package_status": "failed",
                "error": failure["error"],
                "error_type": failure["error_type"],
                "recovery_hint": failure.get("recovery_hint"),
            },
            ensure_ascii=False,
        )
    finally:
        _ACTIVE_EXECUTION_DEADLINE.reset(deadline_token)


def _visual_package_exception_failure(exc: Exception) -> dict[str, str]:
    message = str(exc)
    lowered = message.lower()
    if (
        "too many open files" in lowered
        or "unable to open database file" in lowered
        or "database is locked" in lowered
    ):
        return {
            "error_type": "visual_package_resource_exhaustion",
            "error": message,
            "recovery_hint": (
                "visual package generation hit local resource/database exhaustion; "
                "restart the gateway and check for recursive visual routing or stale in-flight requests"
            ),
        }
    return {
        "error_type": type(exc).__name__,
        "error": message,
        "recovery_hint": "inspect visual package logs for the first failing provider or routing layer",
    }


def _visual_agent_original_prompt(args: dict[str, Any], fallback_prompt: str) -> str:
    for key in ("visual_agent_original_prompt", "user_prompt", "original_prompt"):
        value = strip_visual_prompt_metadata(args.get(key))
        if value:
            return value
    return strip_visual_prompt_metadata(fallback_prompt)


def _visual_package_generate(args: dict[str, Any], *, prompt: str) -> dict[str, Any]:
    visual_agent_original_prompt = _visual_agent_original_prompt(args, prompt)
    attachments = _normalise_attachments(args.get("attachments"))
    attachments, image_reference_source, session_reference_entries = _session_visual_reference_attachments(
        prompt,
        attachments,
    )
    reference_binding = _normalise_reference_binding(args.get("reference_binding"), attachments)
    reference_binding = _reference_binding_from_session_entries(
        reference_binding,
        session_reference_entries,
        attachments,
    )
    prompt = _apply_reference_binding_prompt(prompt, reference_binding)
    image_provider_override = _image_provider_override(args, prompt=prompt)
    image_provider_source = _image_provider_source(args)
    polish_provider_override = _polish_provider_override(args, prompt=prompt)
    character_design_ref_only = _coerce_bool(args.get("character_design_ref_only"))
    composition_guide_only = _coerce_bool(args.get("composition_guide_only"))
    hybrid_final_combine = _coerce_bool(args.get("hybrid_final_combine"))
    aspect_ratio = _visual_package_aspect_ratio(args, attachments, reference_binding)
    image_aspect_ratio = _image_tool_aspect_ratio(aspect_ratio)
    duration = _coerce_int(args.get("duration")) or 6
    requested_image = _wants_image(prompt, args)
    wants_video = _wants_video(prompt, args)
    if character_design_ref_only or composition_guide_only or hybrid_final_combine:
        requested_image = True
        wants_video = False
    story_video_video_error = story_video_video_block_payload(
        args,
        prompt=prompt,
        provider=image_provider_override,
        model=str(args.get("model") or ""),
    )
    if wants_video and story_video_video_error is not None:
        return _story_video_visual_package_block_payload(story_video_video_error)
    image_provider_override, story_video_image_error = resolve_story_video_image_provider(
        args,
        prompt=prompt,
        provider_override=image_provider_override,
    )
    if story_video_image_error is not None:
        return _story_video_visual_package_block_payload(story_video_image_error)
    grok_web_imagine_policy = _grok_web_imagine_policy(
        args,
        image_provider_override=image_provider_override,
        image_provider_source=image_provider_source,
    )
    explicit_image_url = str(args.get("image_url") or "").strip() or None
    explicit_video_source = explicit_image_url
    needs_generated_video_source = wants_video and not requested_image and not explicit_video_source
    should_generate_image = requested_image or needs_generated_video_source
    image_first_for_video = wants_video and should_generate_image and not explicit_video_source
    storyboard_contract = _normalise_storyboard_contract(args.get("storyboard"))
    storyboard_enabled = bool(storyboard_contract and wants_video)
    if not should_generate_image and not wants_video:
        requested_image = True
        should_generate_image = True
        wants_video = True
    feedback_policy = _visual_feedback_policy(
        args,
        wants_image=should_generate_image,
        wants_video=wants_video,
    )
    policy_image_first_for_video = (
        wants_video
        and not requested_image
        and feedback_policy.get("prefer_image_first_video") is True
    )
    if policy_image_first_for_video:
        image_first_for_video = True
        should_generate_image = True
    provider_retry_budget = _provider_retry_budget(feedback_policy)
    candidate_budget = int(feedback_policy.get("candidate_budget") or 0) if should_generate_image else 0
    candidate_budget_source = (
        str(feedback_policy.get("candidate_budget_source") or "default")
        if should_generate_image
        else "not_requested"
    )
    if hybrid_final_combine and should_generate_image:
        candidate_budget = 1
        candidate_budget_source = "hybrid_final_combine_initial_then_repair"
    video_budget = _video_budget(args, wants_video=wants_video)
    inline_vision_judge = _inline_vision_judge_mode(args)
    if (
        args.get("inline_vision_judge") is None
        and feedback_policy.get("require_preference_dimension_evidence") is True
    ):
        inline_vision_judge = True
    request_category = _visual_request_category(prompt)
    quality_guidance = _quality_guidance_plan(
        feedback_policy,
        request_category=request_category,
        image_provider=image_provider_override,
    )
    normalized_intent = {
        "kind": "visual_package",
        "wants_image": requested_image,
        "wants_video": wants_video,
        "generates_image": should_generate_image,
        "image_first_for_video": image_first_for_video,
        "aspect_ratio": _judge_aspect_ratio(aspect_ratio),
        "category": request_category,
        "storyboard": storyboard_enabled,
        "storyboard_shot_count": storyboard_contract.get("shot_count") if storyboard_enabled else None,
    }
    if image_provider_override:
        normalized_intent["image_provider"] = image_provider_override
    intent_signature = build_intent_signature(
        {
            **normalized_intent,
            "modality": "package",
            "operation": "visual_package_generate",
        }
    )

    ledger = VisualAttemptLedger(default_visual_ledger_path())
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt=visual_agent_original_prompt,
        normalized_intent=normalized_intent,
        modality="package",
        operation="visual_package_generate",
        status="started",
        metadata={
            "intent_signature": intent_signature,
            "visual_agent_prompt_mediated": prompt,
        },
    )

    selected_artifact_ids: list[str] = []
    selected_images: list[str] = []
    selected_videos: list[str] = []
    video_source_image: str | None = None
    video_source_artifact_id: str | None = None
    artifact_roles_by_id: dict[str, str] = {}
    rankings: dict[str, dict[str, Any]] = {}
    generation_payloads: dict[str, Any] = {}
    image_payloads: list[dict[str, Any]] = []
    delivery_gate: dict[str, dict[str, Any]] = {}
    polish_pass_metadata: dict[str, Any] | None = None
    hybrid_quality_gate_metadata: dict[str, Any] | None = None
    image_prompt_variants: list[dict[str, Any]] = []
    reference_conditioning_variants: list[str] | None = None
    primary_reference_conditioning: dict[str, Any] | None = None
    preference_profile = build_preference_profile(ledger, bucket=intent_signature)
    strategy_plan = select_strategy_plan(
        intent_signature,
        provider_stats={},
        preference_profile=preference_profile,
        exploration_rate=0.0,
    )
    controlled_strategy_plan = find_controlled_strategy_plan(
        ledger,
        intent_signature=intent_signature,
    )
    controlled_strategy_plan = _applicable_controlled_strategy_plan(
        controlled_strategy_plan,
        wants_video=wants_video,
    )
    feedback_strategy_plan = None
    if controlled_strategy_plan is not None:
        strategy_plan = controlled_strategy_plan
        feedback_policy = _feedback_policy_with_controlled_strategy(
            feedback_policy,
            controlled_strategy_plan,
            args=args,
            wants_image=should_generate_image,
            wants_video=wants_video,
        )
        policy_image_first_for_video = (
            wants_video
            and not requested_image
            and feedback_policy.get("prefer_image_first_video") is True
        )
        if policy_image_first_for_video:
            image_first_for_video = True
            should_generate_image = True
        provider_retry_budget = _provider_retry_budget(feedback_policy)
        candidate_budget = int(feedback_policy.get("candidate_budget") or 0) if should_generate_image else 0
        candidate_budget_source = (
            str(feedback_policy.get("candidate_budget_source") or "default")
            if should_generate_image
            else "not_requested"
        )
        if hybrid_final_combine and should_generate_image:
            candidate_budget = 1
            candidate_budget_source = "hybrid_final_combine_initial_then_repair"
        if (
            args.get("inline_vision_judge") is None
            and feedback_policy.get("require_preference_dimension_evidence") is True
        ):
            inline_vision_judge = True
        quality_guidance = _quality_guidance_plan(
            feedback_policy,
            request_category=request_category,
            image_provider=image_provider_override,
        )
    else:
        feedback_strategy_plan = _strategy_plan_from_feedback_preference(
            strategy_plan,
            feedback_policy=feedback_policy,
            intent_signature=intent_signature,
        )
        if feedback_strategy_plan is not None:
            strategy_plan = feedback_strategy_plan
    if composition_guide_only:
        inline_vision_judge = False
        provider_retry_budget = 0
    learning: dict[str, Any] = {
        "mode": _learning_mode(
            controlled_strategy_plan=controlled_strategy_plan,
            feedback_strategy_plan=feedback_strategy_plan,
        ),
        "strategy_plan": strategy_plan.to_record(),
        "active_learning": {},
    }

    if storyboard_enabled:
        storyboard_result = _run_storyboard_execution(
            args=args,
            ledger=ledger,
            request_id=request_id,
            intent_signature=intent_signature,
            strategy_plan=strategy_plan,
            prompt=prompt,
            storyboard=storyboard_contract,
            attachments=attachments,
            aspect_ratio=aspect_ratio,
            image_aspect_ratio=image_aspect_ratio,
            duration=duration,
            request_category=request_category,
            quality_guidance=quality_guidance,
            inline_vision_judge=inline_vision_judge,
            learning=learning,
            prompt_original=visual_agent_original_prompt,
        )
        return _finalize_visual_package_payload(
            args,
            request_id=request_id,
            requested_image=requested_image,
            wants_video=wants_video,
            selected_images=[],
            selected_videos=storyboard_result["selected_videos"],
            selected_artifact_ids=storyboard_result["selected_artifact_ids"],
            rankings=storyboard_result["rankings"],
            generation_payloads=storyboard_result["generation_payloads"],
            delivery_gate=storyboard_result["delivery_gate"],
            should_generate_image=should_generate_image,
            image_first_for_video=True,
            video_source_image=storyboard_result.get("first_source_image"),
            video_source_artifact_id=storyboard_result.get("first_source_artifact_id"),
            candidate_budget=storyboard_result["candidate_budget_per_shot"],
            candidate_budget_source=candidate_budget_source,
            video_budget=video_budget,
            feedback_policy=feedback_policy,
            quality_guidance=quality_guidance,
            learning=learning,
            extra_generation_strategy={
                **(_extra_generation_strategy(
                    image_provider_override=image_provider_override,
                    image_provider_source=image_provider_source,
                    grok_web_imagine_policy=grok_web_imagine_policy,
                    polish_pass=polish_pass_metadata,
                    image_reference_source=image_reference_source,
                    storyboard_contract=storyboard_contract,
                    reference_binding=reference_binding,
                    aspect_ratio=aspect_ratio,
                    reference_conditioning=None,
                ) or {}),
                "storyboard_execution": storyboard_result["execution"],
            },
        )

    if should_generate_image:
        image_candidates = []
        image_prompt_base = _image_first_source_frame_prompt(prompt) if image_first_for_video else prompt
        if character_design_ref_only:
            image_prompt_base = _character_design_ref_prompt(prompt)
        elif composition_guide_only:
            image_prompt_base = _composition_guide_prompt(prompt)
        elif hybrid_final_combine:
            image_prompt_base = _hybrid_final_combine_prompt(prompt)
        image_generation_prompt_base = _apply_first_pass_quality_guidance(image_prompt_base, quality_guidance["image"])
        image_artifact_role = (
            "character_design_ref"
            if character_design_ref_only
            else "pose_composition_ref"
            if composition_guide_only
            else None
        )
        direct_polish_source = _direct_polish_source_image(
            prompt=prompt,
            args=args,
            attachments=attachments,
            reference_binding=reference_binding,
            polish_provider=polish_provider_override,
            wants_video=wants_video,
        )
        direct_polish_mode = bool(direct_polish_source)
        grok_web_current_operation = _grok_web_current_result_operation(
            args=args,
            prompt=prompt,
            image_provider=image_provider_override,
            polish_provider=polish_provider_override,
            direct_polish_mode=direct_polish_mode,
            image_reference_source=image_reference_source,
        )
        if grok_web_current_operation in {"continue_current", "regenerate_current"}:
            candidate_budget = 1
            candidate_budget_source = "grok_web_current_result_operation"
        effective_candidate_budget = 1 if direct_polish_mode or grok_web_current_operation else candidate_budget
        if direct_polish_mode:
            image_prompt_variants = []
        elif _should_apply_arsenal_prompt_variants(
            strategy_plan=strategy_plan,
            feedback_policy=feedback_policy,
            candidate_budget=candidate_budget,
        ):
            approved_prompt_entries = approved_prompt_arsenal_entries(
                ledger,
                request_category=request_category,
                limit=max(1, min(2, candidate_budget - 1)),
            )
            image_prompt_variants = build_arsenal_prompt_variants(
                base_prompt=image_generation_prompt_base,
                strategy_plan=strategy_plan.to_record(),
                feedback_policy=feedback_policy,
                request_category=request_category,
                candidate_budget=candidate_budget,
                approved_prompt_entries=approved_prompt_entries,
            )
        else:
            image_prompt_variants = []
        image_input_artifacts = _reference_input_artifacts(attachments, reference_binding)
        if direct_polish_mode and direct_polish_source:
            image_input_artifacts = [
                {
                    "index": 1,
                    "role_hint": "edit_anchor",
                    "uri": direct_polish_source,
                    "source": "direct_edit_anchor_polish",
                }
            ]
        reference_conditioning_policy_override = _reference_conditioning_policy_override(
            args,
            attachments=attachments,
            reference_binding=reference_binding,
        )
        reference_conditioning_variants = _reference_conditioning_variants(
            attachments,
            reference_binding,
            policy_override=reference_conditioning_policy_override,
        )
        primary_reference_policy = _reference_conditioning_policy_for_candidate(
            reference_conditioning_variants,
            candidate_index=0,
        )
        _, primary_reference_conditioning = _provider_reference_image_urls(
            attachments,
            reference_binding,
            conditioning_policy=primary_reference_policy,
        )
        for candidate_index in range(effective_candidate_budget):
            _deadline_checkpoint(f"image_candidate:{candidate_index}")
            if direct_polish_mode and direct_polish_source:
                provider_reference_images = []
                reference_conditioning = None
                reference_attempt_extra = {
                    "direct_polish": True,
                    "polish_pass_of": "edit_anchor",
                    "polish_provider": polish_provider_override,
                }
                prompt_variant: dict[str, Any] = {"prompt": image_generation_prompt_base}
                image_generation_prompt = _image_polish_prompt(image_generation_prompt_base)
            else:
                if composition_guide_only:
                    provider_reference_images = []
                    reference_conditioning = None
                    reference_attempt_extra = {
                        "composition_guide_only": True,
                        "reference_conditioning": "disabled_for_abstract_guide",
                    }
                else:
                    reference_policy = _reference_conditioning_policy_for_candidate(
                        reference_conditioning_variants,
                        candidate_index=candidate_index,
                    )
                    provider_reference_images, reference_conditioning = _provider_reference_image_urls(
                        attachments,
                        reference_binding,
                        conditioning_policy=reference_policy,
                    )
                    reference_attempt_extra = _provider_reference_attempt_extra(
                        provider_reference_images,
                        reference_conditioning,
                    )
                prompt_variant = _prompt_variant_for_candidate(
                    image_prompt_variants,
                    candidate_index=candidate_index,
                    fallback_prompt=image_generation_prompt_base,
                )
                image_generation_prompt = _apply_provider_reference_conditioning_prompt(
                    str(prompt_variant.get("prompt") or image_generation_prompt_base),
                    reference_conditioning,
                )
            provider_image_generation_prompt = build_provider_facing_visual_prompt(
                image_generation_prompt,
                provider=image_provider_override,
                request_category=request_category,
            )
            image_attempt_extra = dict(reference_attempt_extra)
            if image_prompt_variants:
                image_attempt_extra["visual_arsenal_variant"] = _public_prompt_variant(prompt_variant)
            image_attempt_parameters = _image_attempt_parameters(
                aspect_ratio,
                attachments=attachments,
                reference_binding=reference_binding,
                extra=image_attempt_extra,
            )
            image_kwargs = {
                "prompt": provider_image_generation_prompt,
                "aspect_ratio": image_aspect_ratio,
                "reference_image_urls": provider_reference_images or None,
            }
            if str(args.get("image_model") or "").strip():
                image_kwargs["model"] = str(args["image_model"]).strip()
            grok_web_operation = grok_web_current_operation
            if grok_web_operation:
                image_kwargs["operation"] = grok_web_operation
            if direct_polish_mode and direct_polish_source:
                image_kwargs["image_url"] = direct_polish_source
                image_kwargs["reference_image_urls"] = None
                _apply_image_provider_override(image_kwargs, polish_provider_override)
                polish_pass_metadata = {
                    "enabled": True,
                    "provider": polish_provider_override,
                    "selected_source_image": direct_polish_source,
                    "status": "pending",
                    "mode": "direct_edit_anchor_polish",
                }
            else:
                _apply_image_provider_override(image_kwargs, image_provider_override)
            image_request = {
                "prompt": provider_image_generation_prompt,
                "arguments": image_kwargs,
                "source_media": _source_media_from_attachments(
                    [direct_polish_source] if direct_polish_mode and direct_polish_source else attachments
                ),
            }
            if direct_polish_mode and direct_polish_source and polish_pass_metadata:
                image_request["polish_pass"] = {
                    "provider": polish_provider_override,
                    "source_image": direct_polish_source,
                    "source_artifact_id": "edit_anchor",
                    "mode": "direct_edit_anchor_polish",
                }
            image_payload = _call_generation_provider(
                generate_image,
                kind="image",
                stage=f"image_generate:{candidate_index}",
                kwargs=image_kwargs,
            )
            if direct_polish_mode and direct_polish_source and polish_pass_metadata:
                polish_pass_metadata["status"] = "completed" if image_payload.get("success") else "failed"
                image_payload["polish_pass"] = {
                    "provider": polish_provider_override,
                    "source_image": direct_polish_source,
                    "source_artifact_id": "edit_anchor",
                    "mode": "direct_edit_anchor_polish",
                }
            if not image_payload.get("success"):
                _annotate_generation_failure(
                    image_payload,
                    base_kwargs=image_kwargs,
                    request=image_request,
                    retry_budget_remaining=provider_retry_budget,
                )
            image_payloads.append(image_payload)
            image_candidate = _record_payload_candidate(
                ledger,
                request_id=request_id,
                payload=image_payload,
                artifact_key="image",
                expected_kind="image",
                prompt=provider_image_generation_prompt,
                prompt_original=visual_agent_original_prompt,
                provider=str(image_payload.get("provider") or ""),
                model=str(image_payload.get("model") or ""),
                requested_parameters=image_attempt_parameters,
                candidate_index=candidate_index,
                input_artifacts=image_input_artifacts,
                artifact_role=image_artifact_role,
            )
            if image_candidate:
                image_candidates.append(image_candidate)
            elif not image_payload.get("success"):
                fallback_candidate_added = False
                for fallback_offset, fallback_payload in enumerate(_provider_fallback_payloads(
                    generator=generate_image,
                    payload=image_payload,
                    base_kwargs=image_kwargs,
                    request=image_request,
                    modality="image",
                    retry_of=candidate_index,
                )):
                    image_payloads.append(fallback_payload)
                    fallback_candidate = _record_payload_candidate(
                        ledger,
                        request_id=request_id,
                            payload=fallback_payload,
                            artifact_key="image",
                            expected_kind="image",
                            prompt=str(fallback_payload.get("prompt") or provider_image_generation_prompt),
                            prompt_original=visual_agent_original_prompt,
                            provider=str(fallback_payload.get("provider") or ""),
                            model=str(fallback_payload.get("model") or ""),
                        requested_parameters=_image_attempt_parameters(
                            aspect_ratio,
                            attachments=attachments,
                            reference_binding=reference_binding,
                            extra={
                                **reference_attempt_extra,
                                "provider_fallback_of": candidate_index,
                            },
                        ),
                        candidate_index=candidate_index + (candidate_budget * (fallback_offset + 1)),
                        input_artifacts=image_input_artifacts,
                        artifact_role=image_artifact_role,
                    )
                    if fallback_candidate:
                        image_candidates.append(fallback_candidate)
                        fallback_candidate_added = True
                        break
                if fallback_candidate_added:
                    continue
                for retry_offset, retry_payload in enumerate(_retry_generation_payloads(
                    generator=generate_image,
                    modality="image",
                    payload=image_payload,
                    base_kwargs=image_kwargs,
                    request=image_request,
                    retry_budget_remaining=provider_retry_budget,
                    retry_of=candidate_index,
                )):
                    image_payloads.append(retry_payload)
                    retry_candidate = _record_payload_candidate(
                        ledger,
                        request_id=request_id,
                        payload=retry_payload,
                        artifact_key="image",
                        expected_kind="image",
                        prompt=str(retry_payload.get("prompt") or provider_image_generation_prompt),
                        prompt_original=visual_agent_original_prompt,
                        provider=str(retry_payload.get("provider") or ""),
                        model=str(retry_payload.get("model") or ""),
                        requested_parameters=image_attempt_parameters,
                        candidate_index=candidate_index + (candidate_budget * (retry_offset + 1)),
                        input_artifacts=image_input_artifacts,
                        artifact_role=image_artifact_role,
                    )
                    if retry_candidate:
                        image_candidates.append(retry_candidate)
                        break
                if _provider_quota_should_stop_candidate_batch(image_payload):
                    break
        generation_payloads["image"] = image_payloads[0] if len(image_payloads) == 1 else image_payloads
        _score_candidates(
            ledger,
            request_id=request_id,
            intent_signature=intent_signature,
            strategy_signature=strategy_plan.strategy_signature,
            modality="image",
            has_reference_image=bool(attachments),
            request_category=request_category,
            candidates=image_candidates,
            inline_vision_judge=inline_vision_judge,
            vision_analyzer=analyze_candidate_with_vision_tool,
            reference_binding=reference_binding,
        )
        image_decision = rank_visual_candidates(
            request_id=request_id,
            candidates=image_candidates,
            post_threshold=0.0,
            ask_threshold=0.0,
        )
        image_decision = _enforce_non_grid_video_source_decision(
            image_decision,
            candidates=image_candidates,
            prompt=prompt,
            wants_video=wants_video,
            image_first_for_video=image_first_for_video,
        )
        rankings["image"] = image_decision.__dict__
        image_learning = _record_learning_trace(
            ledger,
            request_id=request_id,
            intent_signature=intent_signature,
            strategy_signature=strategy_plan.strategy_signature,
            strategy_plan=strategy_plan.to_record(),
            modality="image",
            rank_decision=image_decision.__dict__,
            candidates=image_candidates,
            has_reference_image=bool(attachments),
        )
        learning["active_learning"]["image"] = image_learning
        selected_image = _selected_candidate(image_candidates, image_decision.selected_artifact_id)
        image_gate = _delivery_gate_decision(image_learning, selected_image, prompt=prompt)
        if composition_guide_only:
            image_gate = _composition_guide_delivery_gate(image_learning, selected_image)
        elif hybrid_final_combine:
            hybrid_quality_gate_metadata = _hybrid_final_combine_quality_gate(selected_image)
            if hybrid_quality_gate_metadata.get("passed") is not True:
                image_gate = _with_hybrid_quality_gate_block(image_gate, hybrid_quality_gate_metadata)
            else:
                image_gate = _with_hybrid_quality_gate_pass(image_gate, hybrid_quality_gate_metadata)
        if direct_polish_mode:
            image_gate["polish_pass_attempted"] = True
        delivery_gate["image"] = image_gate
        if (
            not direct_polish_mode
            and not composition_guide_only
            and _should_run_image_polish_pass(
                polish_provider=polish_provider_override,
                selected_image=selected_image,
            )
        ):
            source_image = str(selected_image.get("artifact_path") or "").strip()
            polish_prompt = build_provider_facing_visual_prompt(
                _image_polish_prompt(image_prompt_base),
                provider=polish_provider_override,
                request_category=request_category,
            )
            polish_kwargs = {
                "prompt": polish_prompt,
                "aspect_ratio": image_aspect_ratio,
                "image_url": source_image,
                "reference_image_urls": None,
            }
            _apply_image_provider_override(polish_kwargs, polish_provider_override)
            polish_payload = _call_generation_provider(
                generate_image,
                kind="image",
                stage="image_polish",
                kwargs=polish_kwargs,
            )
            polish_pass_metadata = {
                "enabled": True,
                "provider": polish_provider_override,
                "selected_source_image": source_image,
                "status": "completed" if polish_payload.get("success") else "failed",
            }
            polish_payload["polish_pass"] = {
                "provider": polish_provider_override,
                "source_image": source_image,
                "source_artifact_id": selected_image.get("artifact_id"),
            }
            image_payloads.append(polish_payload)
            if not polish_payload.get("success"):
                _annotate_generation_failure(
                    polish_payload,
                    base_kwargs=polish_kwargs,
                    request={
                        "prompt": polish_prompt,
                        "arguments": polish_kwargs,
                        "source_media": _source_media_from_attachments([source_image]),
                        "polish_pass": polish_payload["polish_pass"],
                    },
                    retry_budget_remaining=0,
                )
            polish_candidate = _record_payload_candidate(
                ledger,
                request_id=request_id,
                payload=polish_payload,
                artifact_key="image",
                expected_kind="image",
                prompt=polish_prompt,
                prompt_original=visual_agent_original_prompt,
                provider=str(polish_payload.get("provider") or ""),
                model=str(polish_payload.get("model") or ""),
                requested_parameters=_image_attempt_parameters(
                    aspect_ratio,
                    attachments=attachments,
                    reference_binding=reference_binding,
                    extra={
                        "polish_pass_of": selected_image.get("artifact_id"),
                        "polish_provider": polish_provider_override,
                    },
                ),
                candidate_index=len(image_candidates),
                input_artifacts=[
                    {
                        "index": 1,
                        "role_hint": "edit_anchor",
                        "uri": source_image,
                        "source": "selected_candidate_polish",
                    }
                ],
            )
            if polish_candidate:
                image_candidates.append(polish_candidate)
                _score_candidates(
                    ledger,
                    request_id=request_id,
                    intent_signature=intent_signature,
                    strategy_signature=strategy_plan.strategy_signature,
                    modality="image",
                    has_reference_image=True,
                    request_category=request_category,
                    candidates=[polish_candidate],
                    inline_vision_judge=inline_vision_judge,
                    vision_analyzer=analyze_candidate_with_vision_tool,
                    reference_binding=reference_binding,
                )
                polish_decision = rank_visual_candidates(
                    request_id=request_id,
                    candidates=image_candidates,
                    post_threshold=0.0,
                    ask_threshold=0.0,
                )
                rankings["image"] = polish_decision.__dict__
                polish_learning = _record_learning_trace(
                    ledger,
                    request_id=request_id,
                    intent_signature=intent_signature,
                    strategy_signature=strategy_plan.strategy_signature,
                    strategy_plan=strategy_plan.to_record(),
                    modality="image",
                    rank_decision=polish_decision.__dict__,
                    candidates=image_candidates,
                    has_reference_image=bool(attachments),
                )
                learning["active_learning"]["image"] = polish_learning
                selected_image = _selected_candidate(image_candidates, polish_decision.selected_artifact_id)
                image_gate = _delivery_gate_decision(polish_learning, selected_image, prompt=prompt)
                image_gate["polish_pass_attempted"] = True
                delivery_gate["image"] = image_gate
        if (
            selected_image
            and not image_gate["allowed"]
            and not composition_guide_only
            and not hybrid_final_combine
            and _should_escalate_candidate_budget(image_gate)
        ):
            escalation_prompt = _candidate_escalation_prompt(image_prompt_base, image_gate)
            escalation_reference_policy = _reference_conditioning_policy_for_gate(
                image_gate,
                reference_conditioning_variants,
            )
            provider_reference_images, reference_conditioning = _provider_reference_image_urls(
                attachments,
                reference_binding,
                conditioning_policy=escalation_reference_policy,
            )
            reference_attempt_extra = _provider_reference_attempt_extra(
                provider_reference_images,
                reference_conditioning,
            )
            escalation_prompt = _apply_provider_reference_conditioning_prompt(
                escalation_prompt,
                reference_conditioning,
            )
            escalation_prompt = build_provider_facing_visual_prompt(
                escalation_prompt,
                provider=image_provider_override,
                request_category=request_category,
            )
            escalation_kwargs = {
                "prompt": escalation_prompt,
                "aspect_ratio": image_aspect_ratio,
                "reference_image_urls": provider_reference_images or None,
            }
            _apply_image_provider_override(escalation_kwargs, image_provider_override)
            escalation_payload = _call_generation_provider(
                generate_image,
                kind="image",
                stage="image_candidate_escalation",
                kwargs=escalation_kwargs,
            )
            escalation_payload["candidate_escalation"] = {
                "reason": image_gate.get("reason"),
                "quality_issues": image_gate.get("quality_issues", []),
                "preference_dimension_fit": image_gate.get("preference_dimension_fit"),
                "threshold": image_gate.get("threshold"),
            }
            image_payloads.append(escalation_payload)
            if not escalation_payload.get("success"):
                _annotate_generation_failure(
                    escalation_payload,
                    base_kwargs=escalation_kwargs,
                    request={
                        "prompt": escalation_prompt,
                        "arguments": escalation_kwargs,
                        "source_media": _source_media_from_attachments(attachments),
                        "candidate_escalation": escalation_payload["candidate_escalation"],
                    },
                    retry_budget_remaining=0,
                )
            escalation_candidate = _record_payload_candidate(
                ledger,
                request_id=request_id,
                payload=escalation_payload,
                artifact_key="image",
                expected_kind="image",
                prompt=escalation_prompt,
                prompt_original=visual_agent_original_prompt,
                provider=str(escalation_payload.get("provider") or ""),
                model=str(escalation_payload.get("model") or ""),
                requested_parameters=_image_attempt_parameters(
                    aspect_ratio,
                    attachments=attachments,
                    reference_binding=reference_binding,
                    extra={
                        **reference_attempt_extra,
                        "candidate_escalation_of": selected_image.get("artifact_id"),
                    },
                ),
                candidate_index=len(image_candidates),
                input_artifacts=image_input_artifacts,
                artifact_role=image_artifact_role,
            )
            if escalation_candidate:
                image_candidates.append(escalation_candidate)
                _score_candidates(
                    ledger,
                    request_id=request_id,
                    intent_signature=intent_signature,
                    strategy_signature=strategy_plan.strategy_signature,
                    modality="image",
                    has_reference_image=bool(attachments),
                    request_category=request_category,
                    candidates=[escalation_candidate],
                    inline_vision_judge=inline_vision_judge,
                    vision_analyzer=analyze_candidate_with_vision_tool,
                    reference_binding=reference_binding,
                )
                escalation_decision = rank_visual_candidates(
                    request_id=request_id,
                    candidates=image_candidates,
                    post_threshold=0.0,
                    ask_threshold=0.0,
                )
                rankings["image"] = escalation_decision.__dict__
                escalation_learning = _record_learning_trace(
                    ledger,
                    request_id=request_id,
                    intent_signature=intent_signature,
                    strategy_signature=strategy_plan.strategy_signature,
                    strategy_plan=strategy_plan.to_record(),
                    modality="image",
                    rank_decision=escalation_decision.__dict__,
                    candidates=image_candidates,
                    has_reference_image=bool(attachments),
                )
                learning["active_learning"]["image"] = escalation_learning
                escalated_from = image_gate
                selected_image = _selected_candidate(image_candidates, escalation_decision.selected_artifact_id)
                image_gate = _delivery_gate_decision(escalation_learning, selected_image, prompt=prompt)
                image_gate["candidate_budget_escalated"] = True
                image_gate["escalated_from"] = escalated_from
                delivery_gate["image"] = image_gate
        if selected_image and not image_gate["allowed"] and not composition_guide_only:
            image_repair_mode = (
                "hybrid_final_combine"
                if hybrid_final_combine
                else _quality_repair_policy_mode(feedback_policy, "image")
            )
            repair_prompt = _quality_repair_prompt(
                image_prompt_base,
                image_gate,
                mode=image_repair_mode,
                reference_binding=reference_binding,
            )
            repair_reference_policy = _reference_conditioning_policy_for_gate(
                image_gate,
                reference_conditioning_variants,
            )
            provider_reference_images, reference_conditioning = _provider_reference_image_urls(
                attachments,
                reference_binding,
                conditioning_policy=repair_reference_policy,
            )
            reference_attempt_extra = _provider_reference_attempt_extra(
                provider_reference_images,
                reference_conditioning,
            )
            repair_prompt = _apply_provider_reference_conditioning_prompt(
                repair_prompt,
                reference_conditioning,
            )
            repair_prompt = build_provider_facing_visual_prompt(
                repair_prompt,
                provider=image_provider_override,
                request_category=request_category,
            )
            repair_kwargs = {
                "prompt": repair_prompt,
                "aspect_ratio": image_aspect_ratio,
                "reference_image_urls": provider_reference_images or None,
            }
            _apply_image_provider_override(repair_kwargs, image_provider_override)
            repair_payload = _call_generation_provider(
                generate_image,
                kind="image",
                stage="image_quality_repair",
                kwargs=repair_kwargs,
            )
            repair_payload["retry_of"] = selected_image.get("attempt_id")
            repair_payload["quality_repair"] = {
                "reason": image_gate.get("reason"),
                "quality_issues": image_gate.get("quality_issues", []),
                "policy_mode": image_repair_mode,
                "policy_actions": feedback_policy.get("applied_action_types", []),
            }
            image_payloads.append(repair_payload)
            if not repair_payload.get("success"):
                _annotate_generation_failure(
                    repair_payload,
                    base_kwargs=repair_kwargs,
                    request={
                        "prompt": repair_prompt,
                        "arguments": repair_kwargs,
                        "source_media": _source_media_from_attachments(attachments),
                        "quality_repair": repair_payload["quality_repair"],
                    },
                    retry_budget_remaining=0,
                )
            repair_candidate = _record_payload_candidate(
                ledger,
                request_id=request_id,
                payload=repair_payload,
                artifact_key="image",
                expected_kind="image",
                prompt=repair_prompt,
                prompt_original=visual_agent_original_prompt,
                provider=str(repair_payload.get("provider") or ""),
                model=str(repair_payload.get("model") or ""),
                requested_parameters=_image_attempt_parameters(
                    aspect_ratio,
                    attachments=attachments,
                    reference_binding=reference_binding,
                    extra={
                        **reference_attempt_extra,
                        "quality_repair_of": selected_image.get("artifact_id"),
                    },
                ),
                candidate_index=candidate_budget,
                input_artifacts=image_input_artifacts,
                artifact_role=image_artifact_role,
            )
            if repair_candidate:
                image_candidates.append(repair_candidate)
                _score_candidates(
                    ledger,
                    request_id=request_id,
                    intent_signature=intent_signature,
                    strategy_signature=strategy_plan.strategy_signature,
                    modality="image",
                    has_reference_image=bool(attachments),
                    request_category=request_category,
                    candidates=[repair_candidate],
                    inline_vision_judge=inline_vision_judge,
                    vision_analyzer=analyze_candidate_with_vision_tool,
                    reference_binding=reference_binding,
                )
                repair_decision = rank_visual_candidates(
                    request_id=request_id,
                    candidates=[repair_candidate],
                    post_threshold=0.0,
                    ask_threshold=0.0,
                )
                rankings["image"] = repair_decision.__dict__
                repair_learning = _record_learning_trace(
                    ledger,
                    request_id=request_id,
                    intent_signature=intent_signature,
                    strategy_signature=strategy_plan.strategy_signature,
                    strategy_plan=strategy_plan.to_record(),
                    modality="image",
                    rank_decision=repair_decision.__dict__,
                    candidates=[repair_candidate],
                    has_reference_image=bool(attachments),
                )
                learning["active_learning"]["image"] = repair_learning
                selected_image = _selected_candidate([repair_candidate], repair_decision.selected_artifact_id)
                repaired_gate = _delivery_gate_decision(repair_learning, selected_image, prompt=prompt)
                repaired_gate["repair_attempted"] = True
                repaired_gate["repaired_from"] = image_gate
                if hybrid_final_combine:
                    repaired_hybrid_gate = _hybrid_final_combine_quality_gate(selected_image)
                    repaired_hybrid_gate["repair_attempted"] = True
                    repaired_hybrid_gate["repaired_from"] = hybrid_quality_gate_metadata
                    hybrid_quality_gate_metadata = repaired_hybrid_gate
                    if repaired_hybrid_gate.get("passed") is not True:
                        repaired_gate = _with_hybrid_quality_gate_block(
                            repaired_gate,
                            repaired_hybrid_gate,
                        )
                    else:
                        repaired_gate = _with_hybrid_quality_gate_pass(
                            repaired_gate,
                            repaired_hybrid_gate,
                        )
                image_gate = repaired_gate
                delivery_gate["image"] = image_gate
            elif hybrid_final_combine and hybrid_quality_gate_metadata is not None:
                hybrid_quality_gate_metadata["repair_attempted"] = True
        generation_payloads["image"] = image_payloads[0] if len(image_payloads) == 1 else image_payloads
        if selected_image and image_gate["allowed"]:
            video_source_image = selected_image["artifact_path"]
            video_source_artifact_id = selected_image["artifact_id"]
            selected_image_role = str(selected_image.get("artifact_role") or "").strip()
            if selected_image_role:
                artifact_roles_by_id[str(selected_image["artifact_id"])] = selected_image_role
            if requested_image:
                deliverable_images = (
                    _ranked_candidate_options(
                        image_candidates,
                        image_decision.ranked_artifact_ids,
                    )
                    if composition_guide_only
                    else [selected_image]
                )
                for deliverable_image in deliverable_images:
                    artifact_id = str(deliverable_image.get("artifact_id") or "").strip()
                    artifact_path = str(deliverable_image.get("artifact_path") or "").strip()
                    if not artifact_id or not artifact_path:
                        continue
                    selected_artifact_ids.append(artifact_id)
                    selected_images.append(artifact_path)
                    deliverable_role = str(deliverable_image.get("artifact_role") or "").strip()
                    if deliverable_role:
                        artifact_roles_by_id[artifact_id] = deliverable_role

    if wants_video:
        if policy_image_first_for_video and video_source_image:
            video_image_url = video_source_image
        else:
            video_image_url = explicit_video_source or video_source_image
        video_candidates = []
        if not video_image_url:
            video_payload = {
                "success": False,
                "video": None,
                "error": "Image-first video generation requires a selected or supplied source image.",
                "error_type": "missing_video_source_image",
                "prompt": prompt,
                "provider": "",
                "model": "",
            }
            generation_payloads["video"] = video_payload
            _record_payload_candidate(
                ledger,
                request_id=request_id,
                payload=video_payload,
                artifact_key="video",
                expected_kind="video",
                prompt=prompt,
                prompt_original=visual_agent_original_prompt,
                provider="",
                model="",
                requested_parameters={
                    "duration_seconds": duration,
                    "aspect_ratio": _judge_aspect_ratio(aspect_ratio),
                    "motion_mode": None,
                },
            )
        else:
            video_generation_base_prompt = _apply_first_pass_quality_guidance(prompt, quality_guidance["video"])
            video_source_media = _video_source_media(video_image_url)
            hardened_video = build_hardened_video_request(
                prompt=video_generation_base_prompt,
                requested_aspect_ratio=_video_tool_aspect_ratio(
                    requested_aspect_ratio=_judge_aspect_ratio(aspect_ratio),
                    source_ref=video_image_url,
                ),
                source_media=video_source_media,
            )
            video_prompt = build_provider_facing_visual_prompt(hardened_video["prompt"])
            video_aspect_ratio = hardened_video["aspect_ratio"]
            video_payloads = []
            for candidate_index in range(video_budget):
                _deadline_checkpoint(f"video_candidate:{candidate_index}")
                video_kwargs = {
                    "prompt": video_prompt,
                    "image_url": video_image_url,
                    "duration": duration,
                    "aspect_ratio": video_aspect_ratio,
                    "source_media": video_source_media,
                }
                if str(args.get("video_provider") or "").strip():
                    video_kwargs["_provider"] = str(args["video_provider"]).strip()
                if str(args.get("video_model") or "").strip():
                    video_kwargs["model"] = str(args["video_model"]).strip()
                video_request = {
                    "prompt": video_prompt,
                    "arguments": video_kwargs,
                    "source_media": video_source_media,
                    "video_hardening": hardened_video.get("metadata", {}),
                }
                video_payload = _runtime_policy_video_quarantine_payload(
                    feedback_policy,
                    prompt=video_prompt,
                )
                if video_payload is None:
                    video_payload = _video_provider_quarantine_payload(
                        image_payloads=image_payloads,
                        prompt=video_prompt,
                    )
                if video_payload is None:
                    video_payload = _call_generation_provider(
                        generate_video,
                        kind="video",
                        stage=f"video_generate:{candidate_index}",
                        kwargs=video_kwargs,
                    )
                if not video_payload.get("success"):
                    _annotate_generation_failure(
                        video_payload,
                        base_kwargs=video_kwargs,
                        request=video_request,
                        retry_budget_remaining=0
                        if video_payload.get("provider_quarantine")
                        else provider_retry_budget,
                    )
                video_payloads.append(video_payload)
                video_candidate = _record_payload_candidate(
                    ledger,
                    request_id=request_id,
                    payload=video_payload,
                    artifact_key="video",
                    expected_kind="video",
                    prompt=video_prompt,
                    prompt_original=visual_agent_original_prompt,
                    provider=str(video_payload.get("provider") or ""),
                    model=str(video_payload.get("model") or ""),
                    requested_parameters={
                        "duration_seconds": duration,
                        "aspect_ratio": video_aspect_ratio,
                        "motion_mode": hardened_video.get("metadata", {}).get("motion_mode"),
                        "source_image_artifact_id": video_source_artifact_id,
                    },
                    candidate_index=candidate_index,
                )
                if video_candidate:
                    video_candidates.append(video_candidate)
                elif not video_payload.get("success"):
                    fallback_candidate_added = False
                    for fallback_offset, fallback_payload in enumerate(_provider_fallback_payloads(
                        generator=generate_video,
                        payload=video_payload,
                        base_kwargs=video_kwargs,
                        request=video_request,
                        modality="video",
                        retry_of=candidate_index,
                    )):
                        video_payloads.append(fallback_payload)
                        fallback_candidate = _record_payload_candidate(
                            ledger,
                            request_id=request_id,
                            payload=fallback_payload,
                            artifact_key="video",
                            expected_kind="video",
                            prompt=str(fallback_payload.get("prompt") or prompt),
                            prompt_original=visual_agent_original_prompt,
                            provider=str(fallback_payload.get("provider") or ""),
                            model=str(fallback_payload.get("model") or ""),
                            requested_parameters={
                                "duration_seconds": fallback_payload.get("duration", duration),
                                "aspect_ratio": video_aspect_ratio,
                                "motion_mode": hardened_video.get("metadata", {}).get("motion_mode"),
                                "source_image_artifact_id": video_source_artifact_id,
                                "provider_fallback_of": candidate_index,
                            },
                            candidate_index=candidate_index + (video_budget * (fallback_offset + 1)),
                        )
                        if fallback_candidate:
                            video_candidates.append(fallback_candidate)
                            fallback_candidate_added = True
                            break
                    if fallback_candidate_added:
                        continue
                    for retry_offset, retry_payload in enumerate(_retry_generation_payloads(
                        generator=generate_video,
                        modality="video",
                        payload=video_payload,
                        base_kwargs=video_kwargs,
                        request=video_request,
                        retry_budget_remaining=provider_retry_budget,
                        retry_of=candidate_index,
                    )):
                        video_payloads.append(retry_payload)
                        retry_candidate = _record_payload_candidate(
                            ledger,
                            request_id=request_id,
                            payload=retry_payload,
                            artifact_key="video",
                            expected_kind="video",
                            prompt=str(retry_payload.get("prompt") or prompt),
                            prompt_original=visual_agent_original_prompt,
                            provider=str(retry_payload.get("provider") or ""),
                            model=str(retry_payload.get("model") or ""),
                            requested_parameters={
                                "duration_seconds": retry_payload.get("duration", duration),
                                "aspect_ratio": video_aspect_ratio,
                                "motion_mode": hardened_video.get("metadata", {}).get("motion_mode"),
                                "source_image_artifact_id": video_source_artifact_id,
                            },
                            candidate_index=candidate_index + (video_budget * (retry_offset + 1)),
                        )
                        if retry_candidate:
                            video_candidates.append(retry_candidate)
                            break
            generation_payloads["video"] = video_payloads[0] if len(video_payloads) == 1 else video_payloads
        _score_candidates(
            ledger,
            request_id=request_id,
            intent_signature=intent_signature,
            strategy_signature=strategy_plan.strategy_signature,
            modality="video",
            has_reference_image=bool(video_image_url),
            request_category=request_category,
            candidates=video_candidates,
            inline_vision_judge=False,
            vision_analyzer=analyze_candidate_with_vision_tool,
        )
        video_decision = rank_visual_candidates(
            request_id=request_id,
            candidates=video_candidates,
            post_threshold=0.0,
            ask_threshold=0.0,
        )
        rankings["video"] = video_decision.__dict__
        video_learning = _record_learning_trace(
            ledger,
            request_id=request_id,
            intent_signature=intent_signature,
            strategy_signature=strategy_plan.strategy_signature,
            strategy_plan=strategy_plan.to_record(),
            modality="video",
            rank_decision=video_decision.__dict__,
            candidates=video_candidates,
            has_reference_image=bool(video_image_url),
        )
        learning["active_learning"]["video"] = video_learning
        selected_video = _selected_candidate(video_candidates, video_decision.selected_artifact_id)
        video_gate = _delivery_gate_decision(video_learning, selected_video, prompt=prompt)
        delivery_gate["video"] = video_gate
        if selected_video and not video_gate["allowed"] and video_image_url and _string_list(video_gate.get("quality_issues")):
            video_repair_mode = _quality_repair_policy_mode(feedback_policy, "video")
            repair_prompt = build_provider_facing_visual_prompt(
                _video_quality_repair_prompt(video_prompt, video_gate, mode=video_repair_mode)
            )
            repair_kwargs = {
                "prompt": repair_prompt,
                "image_url": video_image_url,
                "duration": duration,
                "aspect_ratio": video_aspect_ratio,
                "source_media": video_source_media,
            }
            repair_payload = _call_generation_provider(
                generate_video,
                kind="video",
                stage="video_quality_repair",
                kwargs=repair_kwargs,
            )
            repair_payload["quality_repair"] = {
                "modality": "video",
                "reason": video_gate.get("reason"),
                "quality_issues": _string_list(video_gate.get("quality_issues")),
                "policy_mode": video_repair_mode,
                "policy_actions": feedback_policy.get("applied_action_types", []),
            }
            if not repair_payload.get("success"):
                _annotate_generation_failure(
                    repair_payload,
                    base_kwargs=repair_kwargs,
                    request={
                        "prompt": prompt,
                        "arguments": repair_kwargs,
                        "source_media": video_source_media,
                        "video_hardening": hardened_video.get("metadata", {}),
                    },
                    retry_budget_remaining=0,
                )
            video_payloads.append(repair_payload)
            repair_candidate = _record_payload_candidate(
                ledger,
                request_id=request_id,
                payload=repair_payload,
                artifact_key="video",
                expected_kind="video",
                prompt=repair_prompt,
                prompt_original=visual_agent_original_prompt,
                provider=str(repair_payload.get("provider") or ""),
                model=str(repair_payload.get("model") or ""),
                requested_parameters={
                    "duration_seconds": duration,
                    "aspect_ratio": video_aspect_ratio,
                    "motion_mode": hardened_video.get("metadata", {}).get("motion_mode"),
                    "source_image_artifact_id": video_source_artifact_id,
                    "quality_repair": True,
                },
                candidate_index=len(video_candidates),
            )
            if repair_candidate:
                video_candidates.append(repair_candidate)
                _score_candidates(
                    ledger,
                    request_id=request_id,
                    intent_signature=intent_signature,
                    strategy_signature=strategy_plan.strategy_signature,
                    modality="video",
                    has_reference_image=bool(video_image_url),
                    request_category=request_category,
                    candidates=[repair_candidate],
                    inline_vision_judge=False,
                    vision_analyzer=analyze_candidate_with_vision_tool,
                )
                repair_decision = rank_visual_candidates(
                    request_id=request_id,
                    candidates=[repair_candidate],
                    post_threshold=0.0,
                    ask_threshold=0.0,
                )
                rankings["video"] = repair_decision.__dict__
                repair_learning = _record_learning_trace(
                    ledger,
                    request_id=request_id,
                    intent_signature=intent_signature,
                    strategy_signature=strategy_plan.strategy_signature,
                    strategy_plan=strategy_plan.to_record(),
                    modality="video",
                    rank_decision=repair_decision.__dict__,
                    candidates=[repair_candidate],
                    has_reference_image=bool(video_image_url),
                )
                learning["active_learning"]["video"] = repair_learning
                selected_video = _selected_candidate([repair_candidate], repair_decision.selected_artifact_id)
                repaired_gate = _delivery_gate_decision(repair_learning, selected_video, prompt=prompt)
                repaired_gate["repair_attempted"] = True
                repaired_gate["repaired_from"] = video_gate
                video_gate = repaired_gate
                delivery_gate["video"] = video_gate
            else:
                video_gate["repair_attempted"] = True
            generation_payloads["video"] = video_payloads[0] if len(video_payloads) == 1 else video_payloads
        if selected_video and video_gate["allowed"]:
            selected_artifact_ids.append(selected_video["artifact_id"])
            selected_videos.append(selected_video["artifact_path"])

    extra_generation_strategy = _extra_generation_strategy(
        image_provider_override=image_provider_override,
        image_provider_source=image_provider_source,
        grok_web_imagine_policy=grok_web_imagine_policy,
        polish_pass=polish_pass_metadata,
        image_reference_source=image_reference_source,
        storyboard_contract=storyboard_contract,
        reference_binding=reference_binding,
        aspect_ratio=aspect_ratio,
        reference_conditioning=primary_reference_conditioning,
        reference_conditioning_variants=reference_conditioning_variants,
        image_prompt_variants=_public_prompt_variants(image_prompt_variants),
    ) or {}
    if character_design_ref_only:
        extra_generation_strategy["character_design_ref_only"] = True
    if composition_guide_only:
        extra_generation_strategy["composition_guide_only"] = True
    if hybrid_final_combine:
        extra_generation_strategy["hybrid_final_combine"] = True
        if hybrid_quality_gate_metadata is not None:
            extra_generation_strategy["hybrid_quality_gate"] = hybrid_quality_gate_metadata

    return _finalize_visual_package_payload(
        args,
        request_id=request_id,
        requested_image=requested_image,
        wants_video=wants_video,
        selected_images=selected_images,
        selected_videos=selected_videos,
        selected_artifact_ids=selected_artifact_ids,
        rankings=rankings,
        generation_payloads=generation_payloads,
        delivery_gate=delivery_gate,
        should_generate_image=should_generate_image,
        image_first_for_video=image_first_for_video,
        video_source_image=video_source_image,
        video_source_artifact_id=video_source_artifact_id,
        candidate_budget=candidate_budget,
        candidate_budget_source=candidate_budget_source,
        video_budget=video_budget,
        feedback_policy=feedback_policy,
        quality_guidance=quality_guidance,
        learning=learning,
        extra_generation_strategy=extra_generation_strategy,
        artifact_roles_by_id=artifact_roles_by_id,
    )


def _finalize_visual_package_payload(
    args: dict[str, Any],
    *,
    request_id: str,
    requested_image: bool,
    wants_video: bool,
    selected_images: list[str],
    selected_videos: list[str],
    selected_artifact_ids: list[str],
    rankings: dict[str, Any],
    generation_payloads: dict[str, Any],
    delivery_gate: dict[str, dict[str, Any]],
    should_generate_image: bool,
    image_first_for_video: bool,
    video_source_image: str | None,
    video_source_artifact_id: str | None,
    candidate_budget: int,
    candidate_budget_source: str,
    video_budget: int,
    feedback_policy: dict[str, Any],
    quality_guidance: dict[str, Any],
    learning: dict[str, Any],
    extra_generation_strategy: dict[str, Any] | None = None,
    artifact_roles_by_id: dict[str, str] | None = None,
) -> dict[str, Any]:
    success = (not requested_image or bool(selected_images)) and (not wants_video or bool(selected_videos))
    package_status = "success" if success else ("partial" if selected_images or selected_videos else "failed")
    package_error = _package_error(success=success, delivery_gate=delivery_gate)
    selected_artifact_paths = selected_images + selected_videos
    delivery_recovery = _delivery_recovery_summary(
        requested_image=requested_image,
        wants_video=wants_video,
        selected_images=selected_images,
        selected_videos=selected_videos,
        generation_payloads=generation_payloads,
        delivery_gate=delivery_gate,
    )
    delivery_metadata = visual_delivery_metadata(
        request_id=request_id,
        attempt_id=None,
        artifact_ids=selected_artifact_ids,
        artifact_paths=selected_artifact_paths,
        selected_artifact_ids=selected_artifact_ids,
        artifact_roles_by_id=artifact_roles_by_id,
    )
    selected_delivery_refs = set(selected_artifact_paths)
    generation_strategy = {
        "requested_image": requested_image,
        "generated_image": should_generate_image,
        "image_first_for_video": image_first_for_video,
        "video_source_image": video_source_image,
        "video_source_artifact_id": video_source_artifact_id,
        "video_source_image_count": _video_source_image_count(video_source_image),
        "video_source_policy": _video_source_policy(
            wants_video=wants_video,
            image_first_for_video=image_first_for_video,
            video_source_artifact_id=video_source_artifact_id,
            video_source_image=video_source_image,
        ),
        "candidate_budget": candidate_budget,
        "candidate_budget_source": candidate_budget_source,
        "video_budget": video_budget,
        "feedback_policy": feedback_policy,
        "quality_guidance": quality_guidance,
    }
    if extra_generation_strategy:
        generation_strategy.update(extra_generation_strategy)

    payload = {
        "success": success,
        "package_status": package_status,
        "error_type": package_error.get("error_type"),
        "error": package_error.get("error"),
        "visual_request_id": request_id,
        "images": selected_images,
        "videos": selected_videos,
        "rankings": rankings,
        "generation_strategy": generation_strategy,
        "delivery_metadata": delivery_metadata,
        "generation_payloads": _delivery_safe_generation_payloads(
            generation_payloads,
            selected_refs=selected_delivery_refs,
        ),
        "learning": learning,
        "delivery_recovery": delivery_recovery,
        "delivery_gate": delivery_gate,
    }
    autonomous_validation = validate_visual_generation_payload(
        payload,
        db_path=default_visual_ledger_path(),
        require_video=wants_video,
    )
    payload["autonomous_validation"] = autonomous_validation
    delivery_metadata["visual_quality_run"] = _visual_quality_run_metadata(
        payload=payload,
        requested_image=requested_image,
        wants_video=wants_video,
        should_generate_image=should_generate_image,
        image_first_for_video=image_first_for_video,
        video_source_artifact_id=video_source_artifact_id,
        rankings=rankings,
        selected_artifact_ids=selected_artifact_ids,
        delivery_gate=delivery_gate,
        validation=autonomous_validation,
        video_source_image_count=_video_source_image_count(video_source_image),
    )
    payload["autonomous_orchestration"] = build_post_generation_orchestration(
        payload,
        db_path=default_visual_ledger_path(),
        require_video=wants_video,
        autonomy_level=_coerce_int(args.get("autonomy_level")) or 2,
        validation=autonomous_validation,
    )
    _mark_visual_package_request_status(request_id, success=success)
    return payload


def _mark_visual_package_request_status(request_id: str, *, success: bool) -> None:
    try:
        ledger = VisualAttemptLedger(default_visual_ledger_path())
        ledger.initialize()
        ledger.update_request_status(request_id, "completed" if success else "failed")
    except Exception as exc:  # noqa: BLE001 - status bookkeeping must not hide artifacts
        logger.warning("Visual package request status update skipped: %s", exc)


def _extra_generation_strategy(
    *,
    image_provider_override: str | None,
    image_provider_source: str | None,
    grok_web_imagine_policy: dict[str, Any] | None = None,
    polish_pass: dict[str, Any] | None = None,
    image_reference_source: str | None,
    storyboard_contract: dict[str, Any] | None,
    reference_binding: dict[str, Any] | None,
    aspect_ratio: str | None,
    reference_conditioning: dict[str, Any] | None,
    reference_conditioning_variants: list[str] | None = None,
    image_prompt_variants: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    extra: dict[str, Any] = {}
    if aspect_ratio:
        extra["aspect_ratio"] = _judge_aspect_ratio(aspect_ratio)
    if image_provider_override:
        extra["image_provider"] = image_provider_override
    if image_provider_source:
        extra["image_provider_source"] = image_provider_source
    if grok_web_imagine_policy:
        extra["grok_web_imagine_policy"] = {
            key: value
            for key, value in grok_web_imagine_policy.items()
            if value not in (None, "")
        }
    if polish_pass:
        extra["polish_pass"] = polish_pass
    if image_reference_source:
        extra["image_reference_source"] = image_reference_source
    if storyboard_contract:
        extra["storyboard"] = storyboard_contract
    if reference_binding:
        sanitized_binding = _sanitized_reference_binding(reference_binding)
        if sanitized_binding:
            extra["reference_binding"] = sanitized_binding
    if reference_conditioning:
        extra["reference_conditioning"] = reference_conditioning
    if reference_conditioning_variants:
        extra["reference_conditioning_variants"] = reference_conditioning_variants
    if image_prompt_variants:
        extra["image_prompt_variants"] = image_prompt_variants
    return extra or None


def _prompt_variant_for_candidate(
    variants: list[dict[str, Any]],
    *,
    candidate_index: int,
    fallback_prompt: str,
) -> dict[str, Any]:
    if variants:
        return variants[candidate_index % len(variants)]
    return {
        "variant_id": "arsenal_fallback",
        "source": "visual_arsenal",
        "prompt": fallback_prompt,
        "applied_dimensions": [],
        "atom_signatures": [],
    }


def _should_apply_arsenal_prompt_variants(
    *,
    strategy_plan: StrategyPlan,
    feedback_policy: dict[str, Any],
    candidate_budget: int,
) -> bool:
    if strategy_plan.activation_status == "controlled" and not strategy_plan.prompt_mutation_allowed:
        return False
    if _feedback_policy_requests_prompt_repair(feedback_policy):
        return True
    return candidate_budget > 1


def _feedback_policy_requests_prompt_repair(feedback_policy: dict[str, Any]) -> bool:
    return bool(
        feedback_policy.get("repair_dimensions")
        or feedback_policy.get("quality_focus_operators")
        or feedback_policy.get("require_preference_dimension_evidence")
    )


def _public_prompt_variants(variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_public_prompt_variant(variant) for variant in variants]


def _public_prompt_variant(variant: dict[str, Any]) -> dict[str, Any]:
    return {
        "variant_id": str(variant.get("variant_id") or ""),
        "source": str(variant.get("source") or ""),
        "applied_dimensions": _string_list(variant.get("applied_dimensions")),
        "atom_signatures": _string_list(variant.get("atom_signatures")),
    }


def _visual_quality_run_metadata(
    *,
    payload: dict[str, Any],
    requested_image: bool,
    wants_video: bool,
    should_generate_image: bool,
    image_first_for_video: bool,
    video_source_artifact_id: str | None,
    rankings: dict[str, Any],
    selected_artifact_ids: list[str],
    delivery_gate: dict[str, dict[str, Any]],
    validation: dict[str, Any],
    video_source_image_count: int,
) -> dict[str, Any]:
    success = payload.get("success") is True and validation.get("success") is True
    quality_issues = _delivery_gate_quality_issues(delivery_gate)
    preference_failures = _delivery_gate_preference_failures(delivery_gate)
    image_first_case_count = 1 if wants_video and image_first_for_video else 0
    image_first_covered = bool(
        wants_video
        and image_first_for_video
        and video_source_artifact_id
        and payload.get("videos")
    )
    video_missing_after_image = bool(
        wants_video
        and should_generate_image
        and payload.get("images")
        and not payload.get("videos")
    )
    summary = {
        "case_count": 1,
        "failed_case_count": 0 if success else 1,
        "failed_case_ids": [] if success else [str(payload.get("visual_request_id") or "visual_package")],
        "min_quality_score": _visual_quality_run_score(
            rankings,
            selected_artifact_ids=selected_artifact_ids,
            validation_success=validation.get("success") is True,
        ),
        "quality_issue_count": len(quality_issues),
        "quality_issues": quality_issues,
        "provider_failure_count": 0 if payload.get("success") is True else 1,
        "video_missing_after_image_count": 1 if video_missing_after_image else 0,
        "video_missing_after_image_case_ids": [str(payload.get("visual_request_id") or "visual_package")]
        if video_missing_after_image
        else [],
        "image_first_video_source_case_count": image_first_case_count,
        "image_first_video_source_covered_count": 1 if image_first_covered else 0,
        "image_first_video_source_failure_count": 1
        if image_first_case_count and not image_first_covered
        else 0,
        "image_first_video_source_failure_case_ids": [
            str(payload.get("visual_request_id") or "visual_package")
        ]
        if image_first_case_count and not image_first_covered
        else [],
        "video_source_image_count": video_source_image_count,
        "preference_dimension_failure_count": len(preference_failures),
        "preference_dimension_failures": preference_failures,
    }
    return {
        "success": success,
        "requires_video": wants_video,
        "summary": summary,
        "next_actions": [],
        "self_review": {
            "image_first_video_source_covered": image_first_covered if wants_video else False,
            "single_video_source_image": (video_source_image_count == 1) if wants_video else False,
            "privacy_safe": True,
            "raw_prompt_omitted": True,
        },
        "privacy": {
            "raw_prompt_omitted": True,
            "stores_prompt_hash_only": True,
        },
    }


def _visual_quality_run_score(
    rankings: dict[str, Any],
    *,
    selected_artifact_ids: list[str],
    validation_success: bool,
) -> float:
    judgment_scores = _selected_artifact_judgment_scores(selected_artifact_ids)
    if judgment_scores:
        return min(judgment_scores)
    scores: list[float] = []
    for value in rankings.values():
        if not isinstance(value, dict):
            continue
        for key in ("top_score", "selected_score", "score"):
            if value.get(key) is not None:
                scores.append(_coerce_float(value.get(key)))
    if scores:
        return min(scores)
    return 1.0 if validation_success else 0.0


def _selected_artifact_judgment_scores(selected_artifact_ids: list[str]) -> list[float]:
    artifact_ids = [str(artifact_id or "").strip() for artifact_id in selected_artifact_ids]
    artifact_ids = [artifact_id for artifact_id in artifact_ids if artifact_id]
    if not artifact_ids:
        return []
    try:
        ledger = VisualAttemptLedger(default_visual_ledger_path())
        rows: list[dict[str, Any]] = []
        for artifact_id in artifact_ids:
            rows.extend(
                ledger._list(
                    "visual_judgments",
                    where="artifact_id = ?",
                    params=(artifact_id,),
                )
            )
    except Exception:
        return []
    scores: list[float] = []
    for row in rows:
        if row.get("judge_name") != "visual_quality_judge":
            continue
        value = row.get("score", row.get("confidence"))
        if value is None:
            continue
        scores.append(_coerce_float(value))
    return scores


def _delivery_gate_quality_issues(delivery_gate: dict[str, dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    for gate in delivery_gate.values():
        if not isinstance(gate, dict):
            continue
        for issue in _string_list(gate.get("quality_issues")):
            if issue and issue not in issues:
                issues.append(issue)
    return issues


def _delivery_recovery_summary(
    *,
    requested_image: bool,
    wants_video: bool,
    selected_images: list[str],
    selected_videos: list[str],
    generation_payloads: dict[str, Any],
    delivery_gate: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    blocked_modalities: list[str] = []
    for modality_key, gate in delivery_gate.items():
        if not isinstance(gate, dict) or gate.get("allowed") is not False:
            continue
        modality = _delivery_gate_modality(modality_key)
        if modality not in blocked_modalities:
            blocked_modalities.append(modality)
        quality_issues = _string_list(gate.get("quality_issues"))
        actions.append(
            {
                "modality": modality,
                "reason": str(gate.get("reason") or ""),
                "quality_issues": quality_issues,
                "repair_attempted": bool(gate.get("repair_attempted")),
                "candidate_budget_escalated": bool(gate.get("candidate_budget_escalated")),
                "polish_pass_attempted": bool(gate.get("polish_pass_attempted")),
                "recommended_action": _delivery_recovery_recommended_action(
                    modality=modality,
                    reason=str(gate.get("reason") or ""),
                    quality_issues=quality_issues,
                ),
            }
        )
    generated_candidate_available = _generated_candidate_available(
        generation_payloads,
        require_image=requested_image and not selected_images,
        require_video=wants_video and not selected_videos,
    )
    status = "blocked" if actions else "delivered"
    if actions and not generated_candidate_available:
        status = "blocked_without_candidate"
    return {
        "status": status,
        "blocked_modalities": blocked_modalities,
        "generated_candidate_available": generated_candidate_available,
        "actions": actions,
        "deliver_rejected_artifact": False,
        "self_review": {
            "preserves_delivery_quality_gate": True,
            "avoids_stale_or_rejected_slack_delivery": True,
            "actionable_after_failure": bool(actions),
        },
    }


def _delivery_gate_modality(modality_key: str) -> str:
    value = str(modality_key or "")
    if "video" in value:
        return "video"
    return "image"


def _delivery_recovery_recommended_action(
    *,
    modality: str,
    reason: str,
    quality_issues: list[str],
) -> str:
    if modality == "video":
        return "rerun_video_repair_with_selected_source"
    if any(issue in {"reference_identity_drift", "reference_role_evidence_missing"} for issue in quality_issues):
        return "rerun_reference_repair_or_grok_web_polish"
    if reason in {"active_learning_fail_closed", "active_learning_review_required", "pre_slack_preference_dimension_low"}:
        return "rerun_quality_repair_or_grok_web_polish"
    return "inspect_delivery_gate_and_retry"


def _generated_candidate_available(
    value: Any,
    *,
    require_image: bool,
    require_video: bool,
) -> bool:
    if not (require_image or require_video):
        return False
    if isinstance(value, list):
        return any(
            _generated_candidate_available(item, require_image=require_image, require_video=require_video)
            for item in value
        )
    if not isinstance(value, dict):
        return False
    if value.get("success") is True:
        if require_image and isinstance(value.get("image"), str) and value.get("image"):
            return True
        if require_video and isinstance(value.get("video"), str) and value.get("video"):
            return True
    return any(
        _generated_candidate_available(item, require_image=require_image, require_video=require_video)
        for item in value.values()
        if isinstance(item, (dict, list))
    )


def _delivery_gate_preference_failures(delivery_gate: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for modality, gate in delivery_gate.items():
        if not isinstance(gate, dict):
            continue
        fit = gate.get("preference_dimension_fit")
        if fit is None:
            continue
        score = _coerce_float(fit)
        if score >= PREFERENCE_DIMENSION_DELIVERY_THRESHOLD:
            continue
        failures.append(
            {
                "dimension": str(modality or "visual"),
                "issue": str(gate.get("reason") or "preference_dimension_low"),
                "score": score,
            }
        )
    return failures


def _run_storyboard_execution(
    *,
    args: dict[str, Any],
    ledger: VisualAttemptLedger,
    request_id: str,
    intent_signature: str,
    strategy_plan,
    prompt: str,
    storyboard: dict[str, Any],
    attachments: list[str],
    aspect_ratio: str,
    image_aspect_ratio: str,
    duration: int,
    request_category: str,
    quality_guidance: dict[str, Any],
    inline_vision_judge: bool | str,
    learning: dict[str, Any],
    prompt_original: str,
) -> dict[str, Any]:
    image_provider_override = _image_provider_override(args, prompt=prompt)
    selected_artifact_ids: list[str] = []
    selected_videos: list[str] = []
    rankings: dict[str, Any] = {"storyboard": {"shots": []}}
    generation_payloads: dict[str, Any] = {"storyboard": []}
    delivery_gate: dict[str, dict[str, Any]] = {}
    execution_shots: list[dict[str, Any]] = []
    first_source_image: str | None = None
    first_source_artifact_id: str | None = None
    candidate_budget_per_shot = _storyboard_candidate_budget(storyboard, fallback=_coerce_int(args.get("candidate_budget")) or 1)
    video_budget_per_shot = 1
    composition_status = "not_required"
    composition_error: dict[str, Any] = {}
    composed_video: str | None = None
    composed_video_artifact_id: str | None = None

    for shot_index, shot in enumerate(_storyboard_shots(storyboard)):
        _deadline_checkpoint(f"storyboard_shot:{shot_index}")
        shot_id = str(shot.get("shot_id") or f"shot_{shot_index + 1}")
        shot_prompt = _storyboard_shot_prompt(prompt, shot, shot_index=shot_index)
        image_payloads: list[dict[str, Any]] = []
        image_candidates: list[dict[str, Any]] = []
        for candidate_index in range(candidate_budget_per_shot):
            _deadline_checkpoint(f"storyboard_image_candidate:{shot_index}:{candidate_index}")
            image_generation_prompt = _apply_first_pass_quality_guidance(shot_prompt, quality_guidance["image"])
            provider_image_generation_prompt = build_provider_facing_visual_prompt(
                image_generation_prompt,
                provider=image_provider_override,
                request_category=request_category,
            )
            image_kwargs = {
                "prompt": provider_image_generation_prompt,
                "aspect_ratio": image_aspect_ratio,
                "reference_image_urls": attachments or None,
            }
            _apply_image_provider_override(image_kwargs, image_provider_override)
            image_payload = _call_generation_provider(
                generate_image,
                kind="image",
                stage=f"storyboard_image_generate:{shot_index}:{candidate_index}",
                kwargs=image_kwargs,
            )
            image_payloads.append(image_payload)
            image_candidate = _record_payload_candidate(
                ledger,
                request_id=request_id,
                payload=image_payload,
                artifact_key="image",
                expected_kind="image",
                prompt=provider_image_generation_prompt,
                prompt_original=prompt_original,
                provider=str(image_payload.get("provider") or ""),
                model=str(image_payload.get("model") or ""),
                requested_parameters={
                    "aspect_ratio": _judge_aspect_ratio(aspect_ratio),
                    "storyboard_shot_id": shot_id,
                },
                candidate_index=(shot_index * candidate_budget_per_shot) + candidate_index,
            )
            if image_candidate:
                image_candidates.append(image_candidate)

        _score_candidates(
            ledger,
            request_id=request_id,
            intent_signature=intent_signature,
            strategy_signature=strategy_plan.strategy_signature,
            modality="image",
            has_reference_image=bool(attachments),
            request_category=request_category,
            candidates=image_candidates,
            inline_vision_judge=inline_vision_judge,
            vision_analyzer=analyze_candidate_with_vision_tool,
        )
        image_decision = rank_visual_candidates(
            request_id=request_id,
            candidates=image_candidates,
            post_threshold=0.0,
            ask_threshold=0.0,
        )
        rankings[f"storyboard_image:{shot_id}"] = image_decision.__dict__
        image_learning = _record_learning_trace(
            ledger,
            request_id=request_id,
            intent_signature=intent_signature,
            strategy_signature=strategy_plan.strategy_signature,
            strategy_plan=strategy_plan.to_record(),
            modality="image",
            rank_decision=image_decision.__dict__,
            candidates=image_candidates,
            has_reference_image=bool(attachments),
        )
        learning["active_learning"][f"storyboard_image:{shot_id}"] = image_learning
        selected_image = _selected_candidate(image_candidates, image_decision.selected_artifact_id)
        image_gate = _delivery_gate_decision(image_learning, selected_image, prompt=prompt)
        delivery_gate[f"storyboard_image:{shot_id}"] = image_gate

        shot_payloads: dict[str, Any] = {
            "shot_id": shot_id,
            "image": image_payloads[0] if len(image_payloads) == 1 else image_payloads,
        }
        shot_summary: dict[str, Any] = {
            "shot_id": shot_id,
            "role": shot.get("role"),
            "candidate_count": len(image_candidates),
            "source_image_artifact_id": selected_image.get("artifact_id") if selected_image else None,
            "video_artifact_id": None,
            "uses_single_ranked_image": bool(selected_image and image_gate.get("allowed")),
            "source_media_reference_count": None,
            "source_media_single_source_image": None,
        }
        if selected_image and image_gate.get("allowed"):
            if first_source_image is None:
                first_source_image = selected_image["artifact_path"]
                first_source_artifact_id = selected_image["artifact_id"]
            video_generation_base_prompt = _apply_first_pass_quality_guidance(shot_prompt, quality_guidance["video"])
            hardened_video = build_hardened_video_request(
                prompt=video_generation_base_prompt,
                requested_aspect_ratio=_video_tool_aspect_ratio(
                    requested_aspect_ratio=_judge_aspect_ratio(aspect_ratio),
                    source_ref=selected_image["artifact_path"],
                ),
                source_media=_source_media_from_attachments([selected_image["artifact_path"]]),
            )
            video_prompt = build_provider_facing_visual_prompt(hardened_video["prompt"])
            video_aspect_ratio = hardened_video["aspect_ratio"]
            video_source_media = _video_source_media(selected_image["artifact_path"])
            shot_summary["source_media_reference_count"] = _coerce_int(
                video_source_media.get("reference_count")
            )
            shot_summary["source_media_single_source_image"] = (
                video_source_media.get("single_source_image") is True
            )
            video_payloads: list[dict[str, Any]] = []
            video_candidates: list[dict[str, Any]] = []
            for video_index in range(video_budget_per_shot):
                _deadline_checkpoint(f"storyboard_video_candidate:{shot_index}:{video_index}")
                video_kwargs = {
                    "prompt": video_prompt,
                    "image_url": selected_image["artifact_path"],
                    "duration": duration,
                    "aspect_ratio": video_aspect_ratio,
                    "source_media": video_source_media,
                }
                video_payload = _call_generation_provider(
                    generate_video,
                    kind="video",
                    stage=f"storyboard_video_generate:{shot_index}:{video_index}",
                    kwargs=video_kwargs,
                )
                video_payloads.append(video_payload)
                video_candidate = _record_payload_candidate(
                    ledger,
                    request_id=request_id,
                    payload=video_payload,
                    artifact_key="video",
                    expected_kind="video",
                    prompt=video_prompt,
                    prompt_original=prompt_original,
                    provider=str(video_payload.get("provider") or ""),
                    model=str(video_payload.get("model") or ""),
                    requested_parameters={
                        "duration_seconds": duration,
                        "aspect_ratio": video_aspect_ratio,
                        "motion_mode": hardened_video.get("metadata", {}).get("motion_mode"),
                        "source_image_artifact_id": selected_image["artifact_id"],
                        "storyboard_shot_id": shot_id,
                    },
                    candidate_index=shot_index + video_index,
                )
                if video_candidate:
                    video_candidates.append(video_candidate)
            shot_payloads["video"] = video_payloads[0] if len(video_payloads) == 1 else video_payloads
            _score_candidates(
                ledger,
                request_id=request_id,
                intent_signature=intent_signature,
                strategy_signature=strategy_plan.strategy_signature,
                modality="video",
                has_reference_image=True,
                request_category=request_category,
                candidates=video_candidates,
                inline_vision_judge=False,
                vision_analyzer=analyze_candidate_with_vision_tool,
            )
            video_decision = rank_visual_candidates(
                request_id=request_id,
                candidates=video_candidates,
                post_threshold=0.0,
                ask_threshold=0.0,
            )
            rankings[f"storyboard_video:{shot_id}"] = video_decision.__dict__
            video_learning = _record_learning_trace(
                ledger,
                request_id=request_id,
                intent_signature=intent_signature,
                strategy_signature=strategy_plan.strategy_signature,
                strategy_plan=strategy_plan.to_record(),
                modality="video",
                rank_decision=video_decision.__dict__,
                candidates=video_candidates,
                has_reference_image=True,
            )
            learning["active_learning"][f"storyboard_video:{shot_id}"] = video_learning
            selected_video = _selected_candidate(video_candidates, video_decision.selected_artifact_id)
            video_gate = _delivery_gate_decision(video_learning, selected_video, prompt=prompt)
            delivery_gate[f"storyboard_video:{shot_id}"] = video_gate
            if selected_video and video_gate.get("allowed"):
                selected_artifact_ids.append(selected_video["artifact_id"])
                selected_videos.append(selected_video["artifact_path"])
                shot_summary["video_artifact_id"] = selected_video["artifact_id"]
                shot_summary["clip_path"] = selected_video["artifact_path"]
        generation_payloads["storyboard"].append(shot_payloads)
        execution_shots.append(shot_summary)

    source_clip_videos = list(selected_videos)
    source_clip_artifact_ids = list(selected_artifact_ids)
    source_clip_count = len(source_clip_videos)
    if storyboard.get("composition_target") == "single_coherent_video" and source_clip_count > 1:
        composition_payload = _compose_storyboard_clips(source_clip_videos, request_id=request_id)
        generation_payloads["composition"] = composition_payload
        if composition_payload.get("success"):
            composed_candidate = _record_payload_candidate(
                ledger,
                request_id=request_id,
                payload=composition_payload,
                artifact_key="video",
                expected_kind="video",
                prompt=prompt,
                prompt_original=prompt_original,
                provider=str(composition_payload.get("provider") or "local"),
                model=str(composition_payload.get("model") or "ffmpeg-concat"),
                requested_parameters={
                    "aspect_ratio": _judge_aspect_ratio(aspect_ratio),
                    "composition": "storyboard_concat",
                    "composition_target": storyboard.get("composition_target"),
                    "duration_seconds": duration * source_clip_count,
                    "source_clip_count": source_clip_count,
                    "source_video_artifact_ids": source_clip_artifact_ids,
                },
                candidate_index=len(_storyboard_shots(storyboard)) * candidate_budget_per_shot + source_clip_count,
            )
            if composed_candidate:
                _score_candidates(
                    ledger,
                    request_id=request_id,
                    intent_signature=intent_signature,
                    strategy_signature=strategy_plan.strategy_signature,
                    modality="video",
                    has_reference_image=bool(attachments),
                    request_category=request_category,
                    candidates=[composed_candidate],
                    inline_vision_judge=False,
                    vision_analyzer=analyze_candidate_with_vision_tool,
                )
                selected_artifact_ids = [composed_candidate["artifact_id"]]
                selected_videos = [composed_candidate["artifact_path"]]
                composed_video = composed_candidate["artifact_path"]
                composed_video_artifact_id = composed_candidate["artifact_id"]
                composition_status = "composed"
            else:
                composition_status = "failed"
                composition_error = {
                    "error_type": "composition_artifact_not_recorded",
                    "error": "composed video payload did not produce a recordable artifact",
                }
        else:
            composition_status = "failed"
            composition_error = {
                "error_type": composition_payload.get("error_type"),
                "error": composition_payload.get("error"),
            }

    clip_count = source_clip_count
    shot_count = len(execution_shots)
    execution = {
        "status": (
            "composed"
            if composition_status == "composed"
            else ("clips_ready" if clip_count == shot_count else ("partial" if clip_count else "failed"))
        ),
        "shot_count": shot_count,
        "clip_count": clip_count,
        "composition_status": composition_status,
        "composition_error": composition_error or None,
        "composed_video": composed_video,
        "composed_video_artifact_id": composed_video_artifact_id,
        "delivery_policy": storyboard.get("delivery_policy") or "deliver_composed_video_when_available_else_selected_clips",
        "source_image_policy": storyboard.get("source_image_policy") or "one_ranked_image_per_shot",
        "candidate_budget_per_shot": candidate_budget_per_shot,
        "shots": execution_shots,
    }
    rankings["storyboard"]["shot_count"] = shot_count
    rankings["storyboard"]["clip_count"] = clip_count
    return {
        "selected_artifact_ids": selected_artifact_ids,
        "selected_videos": selected_videos,
        "rankings": rankings,
        "generation_payloads": generation_payloads,
        "delivery_gate": delivery_gate,
        "first_source_image": first_source_image,
        "first_source_artifact_id": first_source_artifact_id,
        "candidate_budget_per_shot": candidate_budget_per_shot,
        "execution": execution,
    }


def _compose_storyboard_clips(video_paths: list[str], *, request_id: str) -> dict[str, Any]:
    source_paths = [str(Path(path)) for path in video_paths if isinstance(path, str) and path.strip()]
    if len(source_paths) < 2:
        return _composition_error("not_enough_clips", "storyboard composition requires at least two clips")
    missing = [path for path in source_paths if not Path(path).exists()]
    if missing:
        return _composition_error("source_clip_missing", f"storyboard source clip missing: {missing[0]}")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return _composition_error("ffmpeg_unavailable", "ffmpeg is not available for storyboard composition")

    output_path = _storyboard_composed_video_path(request_id)
    with tempfile.NamedTemporaryFile(
        "w",
        suffix=".txt",
        prefix="storyboard-concat-",
        delete=False,
        encoding="utf-8",
    ) as file_list:
        list_path = Path(file_list.name)
        for path in source_paths:
            file_list.write(_ffmpeg_concat_file_line(path) + "\n")
    try:
        copy_result = _run_ffmpeg_concat(
            ffmpeg,
            list_path=list_path,
            output_path=output_path,
            reencode=False,
        )
        if copy_result["success"]:
            return _composition_success(
                output_path,
                source_clip_count=len(source_paths),
                method="ffmpeg_concat_copy",
            )

        reencode_result = _run_ffmpeg_concat(
            ffmpeg,
            list_path=list_path,
            output_path=output_path,
            reencode=True,
        )
        if reencode_result["success"]:
            payload = _composition_success(
                output_path,
                source_clip_count=len(source_paths),
                method="ffmpeg_concat_reencode",
            )
            payload["copy_error"] = copy_result.get("error")
            return payload
        return _composition_error(
            "ffmpeg_concat_failed",
            str(reencode_result.get("error") or copy_result.get("error") or "ffmpeg concat failed"),
        )
    finally:
        list_path.unlink(missing_ok=True)


def _run_ffmpeg_concat(
    ffmpeg: str,
    *,
    list_path: Path,
    output_path: Path,
    reencode: bool,
) -> dict[str, Any]:
    _deadline_checkpoint("ffmpeg_concat_reencode" if reencode else "ffmpeg_concat_copy")
    command = [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
    ]
    if reencode:
        command.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart"])
    else:
        command.extend(["-c", "copy"])
    command.append(str(output_path))
    try:
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "ffmpeg concat timed out"}
    if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
        return {"success": True}
    return {
        "success": False,
        "error": (result.stderr or result.stdout or f"ffmpeg exited with {result.returncode}")[:2000],
    }


def _storyboard_composed_video_path(request_id: str) -> Path:
    from hermes_constants import get_hermes_home

    cache_dir = get_hermes_home() / "cache" / "videos"
    cache_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    short = uuid.uuid4().hex[:8]
    safe_request_id = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in request_id)
    return cache_dir / f"visual-storyboard_{safe_request_id}_{ts}_{short}.mp4"


def _ffmpeg_concat_file_line(path: str) -> str:
    escaped = str(Path(path)).replace("'", "'\\''")
    return f"file '{escaped}'"


def _composition_success(path: Path, *, source_clip_count: int, method: str) -> dict[str, Any]:
    return {
        "success": True,
        "video": str(path),
        "provider": "local",
        "model": "ffmpeg-concat",
        "composition": {
            "method": method,
            "source_clip_count": source_clip_count,
        },
    }


def _composition_error(error_type: str, error: str) -> dict[str, Any]:
    return {
        "success": False,
        "provider": "local",
        "model": "ffmpeg-concat",
        "error_type": error_type,
        "error": error,
    }


def _normalise_storyboard_contract(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("enabled") is not True:
        return {}

    supplied_shots = value.get("shots")
    raw_shots = supplied_shots if isinstance(supplied_shots, list) else []
    requested_count = _coerce_int(value.get("shot_count")) or len(raw_shots) or 1
    shot_count = max(1, min(6, requested_count))
    candidate_budget_per_shot = max(1, min(4, _coerce_int(value.get("candidate_budget_per_shot")) or 2))

    normalised_shots: list[dict[str, Any]] = []
    for index in range(shot_count):
        source = raw_shots[index] if index < len(raw_shots) and isinstance(raw_shots[index], dict) else {}
        shot_id = str(source.get("shot_id") or f"shot_{index + 1}").strip() or f"shot_{index + 1}"
        role = str(source.get("role") or _default_storyboard_role(index)).strip()
        normalised_shots.append(
            {
                **source,
                "shot_id": shot_id,
                "role": role,
                "source_image_policy": "single_ranked_image",
                "clip_target": "one_video_clip",
            }
        )

    return {
        **value,
        "enabled": True,
        "mode": str(value.get("mode") or "multi_shot_video"),
        "shot_count": shot_count,
        "candidate_budget_per_shot": candidate_budget_per_shot,
        "source_image_policy": "one_ranked_image_per_shot",
        "composition_target": str(value.get("composition_target") or "single_coherent_video"),
        "delivery_policy": str(value.get("delivery_policy") or "deliver_composed_video_when_available_else_selected_clips"),
        "shots": normalised_shots,
    }


def _storyboard_candidate_budget(storyboard: dict[str, Any], *, fallback: int) -> int:
    budget = _coerce_int(storyboard.get("candidate_budget_per_shot")) or fallback or 1
    return max(1, min(4, budget))


def _storyboard_shots(storyboard: dict[str, Any]) -> list[dict[str, Any]]:
    shots = storyboard.get("shots")
    if isinstance(shots, list):
        return [shot for shot in shots if isinstance(shot, dict)]
    shot_count = max(1, min(6, _coerce_int(storyboard.get("shot_count")) or 1))
    return [
        {
            "shot_id": f"shot_{index + 1}",
            "role": _default_storyboard_role(index),
            "source_image_policy": "single_ranked_image",
            "clip_target": "one_video_clip",
        }
        for index in range(shot_count)
    ]


def _storyboard_shot_prompt(prompt: str, shot: dict[str, Any], *, shot_index: int) -> str:
    role = str(shot.get("role") or _default_storyboard_role(shot_index)).strip()
    shot_id = str(shot.get("shot_id") or f"shot_{shot_index + 1}").strip()
    return (
        f"{prompt}\n\n"
        f"Storyboard source frame {shot_index + 1} ({shot_id}, {role}): "
        "generate exactly one clean source frame for this shot only. "
        "Do not create a collage, contact sheet, split-screen, grid, or four-panel layout. "
        "Preserve continuity with the overall request while varying framing for this shot."
    )


def _image_first_source_frame_prompt(prompt: str) -> str:
    source_frame_contract = (
        "Image-first video source frame contract: generate exactly one single still source frame "
        "for the requested video, not a video storyboard. Do not create a collage, contact sheet, "
        "split-screen, grid, four-panel layout, timeline preview, or multiple frames in one image. "
        "The output must be one coherent camera frame that can be animated directly."
    )
    if source_frame_contract in prompt:
        return prompt
    return f"{prompt}\n\n{source_frame_contract}"


def _composition_guide_prompt(prompt: str) -> str:
    instruction = _composition_guide_source_instruction(prompt)
    return (
        "Create 1 abstract pose/composition guide image only. This is a non-NSFW structure planning image, "
        "not final character art. Show simplified grayscale body layout, gesture line, camera angle, crop, "
        "limb placement, body orientation, foreground overlap, and negative space. Use readable mannequin "
        "or silhouette-like shapes. No face, no detailed outfit, no identity, no erotic detail, no background "
        "scene, no text, no watermark. Render exactly one single uninterrupted frame: one canvas, one pose, "
        "one composition, one camera angle. no split panels, no contact sheet, no side-by-side comparison, "
        "no grid, no collage, no storyboard sheet, and no multiple poses inside one image. Prioritize dynamic "
        "tension, clear line of action, and a usable final "
        "illustration composition.\n\n"
        "Use only this composition focus; ignore any character identity, face, hair, costume, palette, "
        f"reference-preservation, or final-illustration wording: {instruction}"
    )


def _composition_guide_source_instruction(prompt: str) -> str:
    instruction = _current_visual_instruction(prompt)
    match = re.search(r"\bComposition\s*:\s*(.+)", instruction, flags=re.IGNORECASE | re.DOTALL)
    if match:
        instruction = match.group(1).strip()
    instruction = re.split(
        r"\b(?:Pure\s+2D|Art\s+direction|Style\s*:|Rendering\s*:|Quality\s*:|Negative\s*:|No\s+photorealism)\b",
        instruction,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    instruction = re.sub(r"\s+", " ", instruction).strip(" .;\n\t")
    return instruction or "clear readable pose, camera angle, crop, line of action, and negative space"


def _character_design_ref_prompt(prompt: str) -> str:
    safe_brief = _structured_safe_character_design_brief(prompt)
    return (
        "Structured OpenAI-safe character design brief\n"
        f"Source intent: {safe_brief['source_intent']}\n"
        f"Allowed design focus: {safe_brief['allowed_design_focus']}\n"
        f"Outfit direction: {safe_brief['outfit_direction']}\n"
        "Safety mediator: adult, non-explicit, tasteful fashion/concept-art presentation; avoid sexualized pose, "
        "nudity, transparent private areas, erotic framing, fetish focus, text, logo, or watermark.\n"
        "Forbidden content: explicit sexual content, exposed private anatomy, erotic body-part emphasis, underage "
        "appearance, pornographic framing.\n"
        "Output role: character_design_ref for later use by another provider. Emphasize identity, face design, "
        "hairstyle, palette, silhouette, material notes, and clean high-quality 2D style; do not make the final image."
    )


def _structured_safe_character_design_brief(prompt: str) -> dict[str, str]:
    instruction = _current_visual_instruction(prompt)
    sanitized = _strip_openai_unsafe_visual_terms(instruction)
    return {
        "source_intent": sanitized or "safe character identity and outfit design reference",
        "allowed_design_focus": (
            "recognizable character identity, refined face, hairstyle, palette, silhouette, "
            "ornamental motifs, elegant material design, high-quality 2D concept art"
        ),
        "outfit_direction": (
            "tasteful adult fashion redesign with elegant coverage, refined tailoring, fabric layers, "
            "ornaments, accessories, and clear front-facing design readability"
        ),
    }


def _strip_openai_unsafe_visual_terms(value: str) -> str:
    sanitized = str(value or "")
    replacements = (
        "性感一些",
        "性感",
        "巨乳",
        "豐乳",
        "丰乳",
        "水蛇腰",
        "翹臀",
        "翘臀",
        "蜜大腿",
        "裸",
        "露出",
        "sexier",
        "sexy",
        "erotic",
        "fetish",
        "explicit",
        "nsfw",
    )
    for term in replacements:
        sanitized = re.sub(re.escape(term), "", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"\s+", " ", sanitized)
    return sanitized.strip(" ，,。")


def _hybrid_final_combine_prompt(prompt: str) -> str:
    return (
        f"{_current_visual_instruction(prompt)}\n\n"
        "Manual hybrid final combine contract: character design references control identity, face, hair, "
        "palette, art style, silhouette, and outfit design direction. Pose/composition references control only "
        "pose, camera angle, framing, body orientation, limb placement, and scene layout. The user prompt controls "
        "the final target, mood, styling intensity, and requested changes. Do not lock the final outfit to the safe "
        "character-design outfit if the user asks for changes. Do not copy guide lines, grayscale shapes, contour "
        "maps, construction marks, watermarks, or background cleanup artifacts into the final image. Produce one "
        "coherent final illustration, not a stitched blend or cleanup of any reference."
    )


def _default_storyboard_role(index: int) -> str:
    roles = (
        "establishing_context",
        "subject_focus",
        "detail_closeup",
        "motion_variation",
        "alternate_angle",
        "closing_hero",
    )
    return roles[index] if 0 <= index < len(roles) else "continuity_shot"


def _visual_package_aspect_ratio(
    args: dict[str, Any],
    attachments: list[str],
    reference_binding: dict[str, Any] | None,
) -> str:
    explicit = str(args.get("aspect_ratio") or "").strip()
    if explicit:
        return explicit
    pose_reference = _reference_role_attachment(
        attachments,
        reference_binding,
        role_hint="pose_composition",
    )
    if pose_reference:
        inferred = _image_aspect_ratio_from_reference(pose_reference)
        if inferred:
            return inferred
    edit_anchor = _reference_role_attachment(
        attachments,
        reference_binding,
        role_hint="edit_anchor",
    )
    return _image_aspect_ratio_from_reference(edit_anchor) or "16:9"


def _reference_role_attachment(
    attachments: list[str],
    reference_binding: dict[str, Any] | None,
    *,
    role_hint: str,
) -> str | None:
    if not attachments or not isinstance(reference_binding, dict):
        return None
    for item in reference_binding.get("reference_order") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("role_hint") or "").strip() != role_hint:
            continue
        index = _coerce_int(item.get("index"))
        if index is not None and 1 <= index <= len(attachments):
            return attachments[index - 1]
    return None


def _image_aspect_ratio_from_reference(reference: str | None) -> str | None:
    if not reference:
        return None
    path = Path(reference)
    if not path.is_file():
        return None
    try:
        from PIL import Image
        from PIL import ImageOps

        with Image.open(path) as image:
            width, height = ImageOps.exif_transpose(image).size
    except Exception:
        return None
    if width <= 0 or height <= 0:
        return None
    ratio = width / height
    if ratio > 1.1:
        return "16:9"
    if ratio < 0.9:
        return "9:16"
    return "1:1"


def _provider_reference_image_urls(
    attachments: list[str],
    reference_binding: dict[str, Any] | None,
    *,
    conditioning_policy: str | None = None,
) -> tuple[list[str], dict[str, Any] | None]:
    if not attachments:
        return [], None
    role_by_index = _reference_role_by_index(reference_binding)
    if not role_by_index:
        policy = _normalise_reference_conditioning_policy(conditioning_policy, allow_empty=True)
        if policy != "collective_inspiration":
            return list(attachments), None
        metadata = [
            {
                "provider_index": provider_index,
                "index": provider_index,
                "role_hint": "visual_reference",
                "conditioning": "collective_reference_inspiration",
            }
            for provider_index, _attachment in enumerate(attachments, start=1)
        ]
        return list(attachments), {
            "policy": policy,
            "provider_reference_images": metadata,
        }
    binding_item_by_index = _reference_binding_item_by_index(reference_binding)
    policy = _normalise_reference_conditioning_policy(conditioning_policy)
    max_provider_refs = VISUAL_PROVIDER_REFERENCE_SLOT_BUDGET
    provider_refs: list[str] = []
    metadata: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    optional_guides: list[dict[str, Any]] = []

    def with_reference_metadata(index: int, role_hint: str, conditioning: str, **extra: Any) -> dict[str, Any]:
        item: dict[str, Any] = {
            "index": index,
            "role_hint": role_hint,
            "conditioning": conditioning,
        }
        source_item = binding_item_by_index.get(index) or {}
        if isinstance(source_item, dict) and source_item.get("user_ref_index") not in (None, ""):
            item["user_ref_index"] = source_item.get("user_ref_index")
        item.update(extra)
        return item

    def append_required(reference: str, item: dict[str, Any], *, original_index: int, role_hint: str) -> bool:
        if len(provider_refs) >= max_provider_refs:
            omitted.append(
                {
                    "index": original_index,
                    "role_hint": role_hint,
                    "reason": "provider_reference_slot_budget",
                }
            )
            return False
        provider_refs.append(reference)
        item["provider_index"] = len(provider_refs)
        metadata.append(item)
        return True

    for index, attachment in enumerate(attachments, start=1):
        role_hint = role_by_index.get(index, "visual_reference")
        if role_hint == "edit_anchor":
            source_item = binding_item_by_index.get(index) or {}
            user_ref_index = (
                source_item.get("user_ref_index")
                if isinstance(source_item, dict)
                else None
            ) or "previous_selected_output"
            append_required(
                attachment,
                with_reference_metadata(
                    index,
                    role_hint,
                    "selected_output_edit_anchor",
                    user_ref_index=user_ref_index,
                ),
                original_index=index,
                role_hint=role_hint,
            )
            continue
        if role_hint == "pose_composition":
            if policy in {"structure_guide", "structure_contour"}:
                guide = _pose_composition_guide_image(attachment)
                if guide:
                    appended = append_required(
                        guide,
                        with_reference_metadata(
                            index,
                            role_hint,
                            "pose_composition_guide",
                            derived_from_index=index,
                            original_policy="omitted_to_prevent_identity_drift",
                        ),
                        original_index=index,
                        role_hint=role_hint,
                    )
                    if appended and policy == "structure_contour":
                        edge_guide = _pose_composition_edge_guide_image(attachment)
                        if edge_guide:
                            optional_guides.append(
                                {
                                    "reference": edge_guide,
                                    "metadata": with_reference_metadata(
                                        index,
                                        role_hint,
                                        "pose_composition_edge_guide",
                                        derived_from_index=index,
                                        original_policy="omitted_to_prevent_identity_drift",
                                    ),
                                    "index": index,
                                    "role_hint": role_hint,
                                }
                            )
                    continue
            append_required(
                attachment,
                with_reference_metadata(index, role_hint, "pose_composition_original_role_locked"),
                original_index=index,
                role_hint=role_hint,
            )
            continue
        append_required(
            attachment,
            with_reference_metadata(index, role_hint, "original"),
            original_index=index,
            role_hint=role_hint,
        )
    for optional in optional_guides:
        if len(provider_refs) >= max_provider_refs:
            break
        reference = str(optional.get("reference") or "").strip()
        item = optional.get("metadata")
        if not reference or not isinstance(item, dict):
            continue
        provider_refs.append(reference)
        item = dict(item)
        item["provider_index"] = len(provider_refs)
        metadata.append(item)
    conditioning: dict[str, Any] = {
        "policy": policy,
        "provider_reference_images": metadata,
    }
    if omitted:
        conditioning["omitted_provider_references"] = omitted
    return provider_refs, conditioning


def _reference_conditioning_variants(
    attachments: list[str],
    reference_binding: dict[str, Any] | None,
    *,
    policy_override: Any = None,
) -> list[str]:
    role_by_index = _reference_role_by_index(reference_binding)
    if not attachments:
        return []
    override = _normalise_reference_conditioning_policy(policy_override, allow_empty=True)
    if override:
        return [override]
    if not role_by_index:
        return []
    roles = {str(role or "").strip() for role in role_by_index.values()}
    has_pose = "pose_composition" in roles
    if not has_pose:
        return ["role_locked_originals"]
    has_identity_or_style_source = any(
        role
        and role not in {"pose_composition", "visual_reference"}
        for role in roles
    )
    if has_identity_or_style_source:
        return ["role_locked_originals", "structure_guide"]
    return ["role_locked_originals"]


def _reference_conditioning_policy_for_candidate(
    variants: list[str],
    *,
    candidate_index: int,
) -> str | None:
    if not variants:
        return None
    return variants[candidate_index % len(variants)]


def _reference_conditioning_policy_for_gate(
    gate: dict[str, Any],
    variants: list[str],
) -> str | None:
    if not variants:
        return None
    quality_issues = set(_string_list(gate.get("quality_issues")))
    if "reference_identity_drift" in quality_issues and "structure_guide" in variants:
        return "structure_guide"
    if "composition_bad" in quality_issues and "role_locked_originals" in variants:
        return "role_locked_originals"
    return variants[0]


def _normalise_reference_conditioning_policy(value: Any, *, allow_empty: bool = False) -> str:
    raw = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "raw": "role_locked_originals",
        "raw_originals": "role_locked_originals",
        "role_locked": "role_locked_originals",
        "originals": "role_locked_originals",
        "guide": "structure_guide",
        "pose_guide": "structure_guide",
        "structure": "structure_guide",
        "contour": "structure_contour",
        "edge": "structure_contour",
        "edge_guide": "structure_contour",
        "collective": "collective_inspiration",
        "collective_reference": "collective_inspiration",
        "collective_inspiration": "collective_inspiration",
        "unassigned": "collective_inspiration",
        "unassigned_refs": "collective_inspiration",
    }
    normalized = aliases.get(raw, raw)
    allowed = {"role_locked_originals", "structure_guide", "structure_contour", "collective_inspiration"}
    if normalized in allowed:
        return normalized
    return "" if allow_empty else "role_locked_originals"


def _reference_conditioning_policy_override(
    args: dict[str, Any],
    *,
    attachments: list[str],
    reference_binding: dict[str, Any] | None,
) -> Any:
    explicit = args.get("reference_conditioning_policy")
    if explicit:
        return explicit
    strategy = args.get("reference_strategy")
    if (
        isinstance(strategy, dict)
        and str(strategy.get("mode") or "").strip() == "unassigned_collective_generation"
        and strategy.get("edit_anchor") is not True
        and attachments
        and not reference_binding
    ):
        return "collective_inspiration"
    if not attachments or reference_binding:
        return None
    return None


def _apply_provider_reference_conditioning_prompt(
    prompt: str,
    reference_conditioning: dict[str, Any] | None,
) -> str:
    if not isinstance(reference_conditioning, dict):
        return prompt
    if "Provider reference image ordering for generation:" in prompt:
        return prompt
    references = reference_conditioning.get("provider_reference_images")
    if not isinstance(references, list):
        return prompt
    if references and all(
        isinstance(item, dict)
        and str(item.get("conditioning") or "").strip() == "collective_reference_inspiration"
        for item in references
    ):
        indices = [
            _coerce_int(item.get("provider_index"))
            for item in references
            if isinstance(item, dict) and _coerce_int(item.get("provider_index")) is not None
        ]
        provider_label = _provider_image_range_label(indices)
        block = "\n".join(
            [
                "Provider reference image ordering for generation:",
                f"- provider images {provider_label} form an unassigned collective identity/style reference set, "
                "not an edit anchor or base image to clean up. Use them only as shared evidence for the requested "
                "character identity, visual style, palette, and recurring design cues. Do not reproduce any single "
                "reference image, remove watermarks from it, extend its canvas, or preserve its exact "
                "background/crop/composition; create a single coherent new image with one consistent lighting "
                "direction, one unified design, and a new pose/composition for the requested final image. "
                "The result should be a synthesis, not a stitched blend, collage, average face, or cleanup of any reference.",
                "When provider image ordering and user ref labels differ, user ref labels keep their original visible upload order.",
            ]
        )
        return f"{prompt}\n\n{block}"
    lines: list[str] = []
    for item in references:
        if not isinstance(item, dict):
            continue
        provider_index = _coerce_int(item.get("provider_index"))
        user_index = _coerce_int(item.get("index"))
        role_hint = str(item.get("role_hint") or "visual_reference").strip()
        conditioning = str(item.get("conditioning") or "original").strip()
        if provider_index is None or user_index is None:
            continue
        user_label = _provider_reference_user_label(item, user_index)
        if conditioning == "selected_output_edit_anchor":
            lines.append(
                f"- provider image {provider_index} is the previous selected output / edit anchor; "
                "treat it as the current image to improve. Preserve its character identity, pose, "
                "camera, composition, outfit, colors, and overall image unless the user explicitly "
                "requested a change. Apply only the requested local edit and change only the requested details."
            )
        elif conditioning == "pose_composition_original_role_locked":
            lines.append(
                f"- provider image {provider_index} is {user_label} as a role-locked original pose/composition reference; "
                "use only pose, camera angle, framing, body orientation, limb placement, and scene layout. "
                "Do not copy identity, face, hair, wardrobe, color palette, or character traits from this provider image."
            )
        elif conditioning == "pose_composition_guide":
            original_policy = str(item.get("original_policy") or "").strip()
            policy_note = (
                " The original pose reference is intentionally not sent as a provider image to reduce identity drift."
                if original_policy == "omitted_to_prevent_identity_drift"
                else ""
            )
            lines.append(
                f"- provider image {provider_index} is a derived pose/composition guide from {user_label}; "
                "use it only to reinforce pose, camera angle, framing, body orientation, limb placement, "
                "and composition. It is not a separate user ref and must not change identity, face, hair, "
                f"wardrobe, or color palette.{policy_note}"
            )
        elif conditioning == "pose_composition_edge_guide":
            lines.append(
                f"- provider image {provider_index} is a derived pose/contour guide from {user_label}; "
                "use it to refine body outline, limb placement, foreshortening, camera angle, and framing only. "
                "It is not a separate user ref and must not change identity, face, hair, wardrobe, or color palette."
            )
        elif conditioning == "collective_reference_inspiration":
            lines.append(
                f"- provider image {provider_index} is part of an unassigned collective identity/style reference set, "
                "not an edit anchor or base image to clean up. Use it only as shared evidence for the requested "
                "character identity, visual style, palette, and recurring design cues. Do not reproduce this image, "
                "remove watermarks from it, extend its canvas, or preserve its exact background/crop/composition; "
                "create a single coherent new image with one consistent lighting direction, one unified design, "
                "and a new pose/composition for the requested final image. The result should be a synthesis, "
                "not a stitched blend, collage, average face, or cleanup of any reference."
            )
        else:
            lines.append(
                f"- provider image {provider_index} = {user_label} ({role_hint}, original)"
            )
    if not lines:
        return prompt
    block = "\n".join(
        [
            "Provider reference image ordering for generation:",
            *lines,
            "When provider image ordering and user ref labels differ, user ref labels keep their original visible upload order.",
        ]
    )
    return f"{prompt}\n\n{block}"


def _provider_image_range_label(indices: list[int | None]) -> str:
    values = sorted({index for index in indices if index is not None})
    if not values:
        return "in this request"
    if values == list(range(values[0], values[-1] + 1)):
        return f"{values[0]}-{values[-1]}" if len(values) > 1 else str(values[0])
    return ", ".join(str(value) for value in values)


def _provider_reference_user_label(item: dict[str, Any], fallback_index: int) -> str:
    user_ref_index = item.get("user_ref_index")
    if str(user_ref_index or "").strip() == "previous_selected_output":
        return "previous selected output"
    coerced = _coerce_int(user_ref_index)
    if coerced is not None:
        return f"user ref {coerced}"
    return f"user ref {fallback_index}"


def _reference_role_by_index(reference_binding: dict[str, Any] | None) -> dict[int, str]:
    if not isinstance(reference_binding, dict):
        return {}
    roles: dict[int, str] = {}
    for item in reference_binding.get("reference_order") or []:
        if not isinstance(item, dict):
            continue
        index = _coerce_int(item.get("index"))
        role_hint = str(item.get("role_hint") or "").strip()
        if index is not None and role_hint:
            roles[index] = role_hint
    return roles


def _reference_binding_item_by_index(reference_binding: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    if not isinstance(reference_binding, dict):
        return {}
    items: dict[int, dict[str, Any]] = {}
    for item in reference_binding.get("reference_order") or []:
        if not isinstance(item, dict):
            continue
        index = _coerce_int(item.get("index"))
        if index is not None:
            items[index] = item
    return items


def _pose_composition_guide_image(reference: str) -> str | None:
    source = Path(reference)
    if not source.is_file():
        return None
    try:
        digest = hashlib.sha256(b"pose_composition_guide.v3\0" + source.read_bytes()).hexdigest()[:16]
        out_dir = default_visual_ledger_path().parent / "reference_role_guides"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"pose_composition_guide_{digest}.jpg"
        if out_path.is_file():
            return str(out_path)

        from PIL import Image
        from PIL import ImageFilter
        from PIL import ImageOps

        with Image.open(source) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            blur_radius = max(10, min(image.size) // 18)
            gray = ImageOps.grayscale(image)
            structure = gray.filter(ImageFilter.GaussianBlur(radius=blur_radius))
            structure = ImageOps.autocontrast(structure, cutoff=4)
            # Keep this as a pale layout mask. Dark contour/depth guides are
            # too easy for image models to copy as visible artifacts.
            guide_l = structure.point(
                lambda value: 192
                if value < 92
                else 218
                if value < 164
                else 242
            )
            guide_l = guide_l.filter(ImageFilter.GaussianBlur(radius=max(1, min(image.size) // 120)))
            guide = guide_l.convert("RGB")
            guide.save(out_path, format="JPEG", quality=95)
        return str(out_path)
    except Exception:
        return None


def _pose_composition_edge_guide_image(reference: str) -> str | None:
    source = Path(reference)
    if not source.is_file():
        return None
    try:
        digest = hashlib.sha256(b"pose_composition_edge_guide.v2\0" + source.read_bytes()).hexdigest()[:16]
        out_dir = default_visual_ledger_path().parent / "reference_role_guides"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"pose_composition_edge_guide_{digest}.jpg"
        if out_path.is_file():
            return str(out_path)

        from PIL import Image
        from PIL import ImageFilter
        from PIL import ImageOps

        with Image.open(source) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            gray = ImageOps.grayscale(image)
            blur_radius = max(5, min(image.size) // 45)
            smoothed = gray.filter(ImageFilter.GaussianBlur(radius=blur_radius))
            structure = ImageOps.autocontrast(smoothed, cutoff=2)
            structure = ImageOps.posterize(structure.convert("RGB"), 3).convert("L")
            edges = structure.filter(ImageFilter.FIND_EDGES)
            edges = ImageOps.autocontrast(edges, cutoff=1)
            line_art = edges.point(lambda value: 0 if value > 20 else 255, mode="L")
            line_art = line_art.filter(ImageFilter.MinFilter(size=3))
            guide = line_art.convert("RGB")
            guide.save(out_path, format="JPEG", quality=92)
        return str(out_path)
    except Exception:
        return None


def _image_attempt_parameters(
    aspect_ratio: str,
    *,
    attachments: list[str],
    reference_binding: dict[str, Any] | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parameters: dict[str, Any] = {"aspect_ratio": _judge_aspect_ratio(aspect_ratio)}
    if attachments:
        parameters["reference_image_count"] = len(attachments)
    sanitized_binding = _sanitized_reference_binding(reference_binding)
    if sanitized_binding:
        parameters["reference_binding"] = sanitized_binding
    if extra:
        parameters.update(extra)
    return parameters


def _provider_reference_attempt_extra(
    provider_reference_images: list[str],
    reference_conditioning: dict[str, Any] | None,
) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    if provider_reference_images:
        extra["provider_reference_image_count"] = len(provider_reference_images)
    if reference_conditioning:
        extra["reference_conditioning"] = reference_conditioning
    return extra


def _sanitized_reference_binding(binding: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(binding, dict):
        return None
    sanitized = {
        key: value
        for key, value in binding.items()
        if key not in {"character_reference", "pose_reference"}
    }
    reference_order = []
    for item in binding.get("reference_order") or []:
        if not isinstance(item, dict):
            continue
        entry: dict[str, Any] = {}
        index = _coerce_int(item.get("index"))
        if index is not None:
            entry["index"] = index
        role_hint = str(item.get("role_hint") or "").strip()
        if role_hint:
            entry["role_hint"] = role_hint
        user_ref_index = item.get("user_ref_index")
        if user_ref_index not in (None, "") and isinstance(user_ref_index, (int, float, str)):
            entry["user_ref_index"] = (
                int(user_ref_index)
                if isinstance(user_ref_index, float) and user_ref_index.is_integer()
                else user_ref_index
            )
        if entry:
            reference_order.append(entry)
    if reference_order:
        sanitized["reference_order"] = reference_order
    elif "reference_order" in sanitized:
        sanitized.pop("reference_order", None)
    return sanitized or None


def _reference_input_artifacts(
    attachments: list[str],
    reference_binding: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not attachments:
        return []
    role_by_index: dict[int, str] = {}
    user_ref_by_index: dict[int, Any] = {}
    source = "user_visible_upload_order"
    if isinstance(reference_binding, dict):
        source = str(reference_binding.get("reference_order_source") or source)
        for item in reference_binding.get("reference_order") or []:
            if not isinstance(item, dict):
                continue
            index = _coerce_int(item.get("index"))
            role_hint = str(item.get("role_hint") or "").strip()
            if index is not None and role_hint:
                role_by_index[index] = role_hint
            if index is not None and item.get("user_ref_index") not in (None, ""):
                user_ref_by_index[index] = item.get("user_ref_index")
    artifacts = []
    for index, attachment in enumerate(attachments, start=1):
        artifact = {
            "index": index,
            "role_hint": role_by_index.get(index, "visual_reference"),
            "uri": attachment,
            "source": source,
        }
        if user_ref_by_index.get(index) not in (None, ""):
            artifact["user_ref_index"] = user_ref_by_index[index]
        artifacts.append(artifact)
    return artifacts


def _record_payload_candidate(
    ledger: VisualAttemptLedger,
    *,
    request_id: str,
    payload: dict[str, Any],
    artifact_key: str,
    expected_kind: str,
    prompt: str,
    provider: str,
    model: str,
    requested_parameters: dict[str, Any],
    prompt_original: str | None = None,
    candidate_index: int = 0,
    input_artifacts: list[dict[str, Any]] | None = None,
    artifact_role: str | None = None,
) -> dict[str, Any] | None:
    success = bool(payload.get("success"))
    effective_parameters = _effective_generation_parameters(payload, requested_parameters)
    attempt_id = ledger.record_attempt(
        request_id=request_id,
        candidate_index=candidate_index,
        provider=provider,
        model=model,
        prompt_original=prompt_original or prompt,
        prompt_mediated=prompt,
        parameters_requested=requested_parameters,
        parameters_effective=effective_parameters,
        input_artifacts=input_artifacts or None,
        status="completed" if success else "failed",
        error_type=payload.get("error_type") if not success else None,
        error_message=payload.get("error") if not success else None,
        metadata=_attempt_metadata(payload),
    )
    artifact_ref = payload.get(artifact_key)
    if not success or not isinstance(artifact_ref, str) or not artifact_ref.strip():
        return None

    artifact_id, artifact = _record_artifact_ref(
        ledger,
        request_id=request_id,
        attempt_id=attempt_id,
        kind=expected_kind,
        artifact_ref=artifact_ref.strip(),
        artifact_role=artifact_role,
    )
    score = judge_artifact(
        artifact,
        expected_kind=expected_kind,
        requested_parameters=effective_parameters,
    )
    candidate = {
        "attempt_id": attempt_id,
        "artifact_id": artifact_id,
        "artifact_path": artifact.get("local_path") or artifact.get("uri") or artifact_ref.strip(),
        "kind": expected_kind,
        "provider": provider,
        "model": model,
        "content_hash": artifact.get("content_hash"),
        "width": artifact.get("width"),
        "height": artifact.get("height"),
        "duration_seconds": artifact.get("duration_seconds"),
        "requested_parameters": effective_parameters,
        "user_requested_parameters": requested_parameters,
        "input_artifacts": input_artifacts or [],
        "hard_gate": score["hard_gate"],
        "scores": score["scores"],
        "vision_observation": _payload_vision_observation(payload),
    }
    if artifact_role:
        candidate["artifact_role"] = artifact_role
    return candidate


def _effective_generation_parameters(
    payload: dict[str, Any],
    requested_parameters: dict[str, Any],
) -> dict[str, Any]:
    effective = dict(requested_parameters)
    duration = payload.get("duration_seconds", payload.get("duration"))
    if duration is not None:
        effective["duration_seconds"] = duration
    aspect_ratio = payload.get("aspect_ratio")
    if aspect_ratio:
        effective["aspect_ratio"] = aspect_ratio
    resolution = payload.get("resolution")
    if resolution:
        effective["resolution"] = resolution
    return effective


def _package_error(
    *,
    success: bool,
    delivery_gate: dict[str, dict[str, Any]],
) -> dict[str, str | None]:
    if success:
        return {"error_type": None, "error": None}
    if _delivery_gate_has_reference_role_block(delivery_gate):
        return {
            "error_type": "delivery_gate_blocked",
            "error": "reference role transfer did not pass visual quality validation after repair",
        }
    if any(
        isinstance(gate, dict)
        and gate.get("allowed") is False
        and gate.get("reason")
        in {
            "active_learning_fail_closed",
            "active_learning_review_required",
            "video_quality_issue_blocked",
        }
        for gate in delivery_gate.values()
    ):
        return {
            "error_type": "delivery_gate_blocked",
            "error": "visual candidate blocked by active-learning delivery gate",
        }
    if any(
        isinstance(gate, dict)
        and gate.get("allowed") is False
        and gate.get("reason") == "no_selected_candidate"
        for gate in delivery_gate.values()
    ):
        return {
            "error_type": "no_deliverable_media",
            "error": "visual generation produced no selected deliverable media",
        }
    return {"error_type": None, "error": None}


def _delivery_gate_has_reference_role_block(delivery_gate: dict[str, dict[str, Any]]) -> bool:
    reference_issues = {
        "reference_identity_drift",
        "reference_role_evidence_missing",
    }
    return any(
        isinstance(gate, dict)
        and gate.get("allowed") is False
        and any(issue in reference_issues for issue in _string_list(gate.get("quality_issues")))
        for gate in delivery_gate.values()
    )


def _retry_generation_payloads(
    *,
    generator,
    modality: str | None = None,
    payload: dict[str, Any],
    base_kwargs: dict[str, Any],
    request: dict[str, Any],
    retry_budget_remaining: int,
    retry_of: int,
) -> list[dict[str, Any]]:
    retries: list[dict[str, Any]] = []
    current_payload = payload
    current_kwargs = dict(base_kwargs)
    remaining = max(0, _coerce_int(retry_budget_remaining) or 0)
    current_retry_of = retry_of
    resolved_modality = modality or ("video" if "duration" in base_kwargs else "image")
    while remaining > 0:
        _deadline_checkpoint(f"{resolved_modality}_retry:{len(retries)}")
        _annotate_generation_failure(
            current_payload,
            base_kwargs=current_kwargs,
            request={**request, "arguments": current_kwargs},
            retry_budget_remaining=remaining,
        )
        recovery = current_payload["recovery"]
        if recovery.get("decision") != "retry":
            break
        retry_kwargs = _retry_kwargs_from_recovery(current_kwargs, recovery)
        retry_payload = _call_generation_provider(
            generator,
            kind=resolved_modality,
            stage=f"{resolved_modality}_retry_generate:{len(retries)}",
            kwargs=retry_kwargs,
        )
        retry_payload["retry_of"] = current_retry_of
        retries.append(retry_payload)
        if retry_payload.get("success"):
            retry_payload["recovery"] = recovery
            break
        remaining -= 1
        _annotate_generation_failure(
            retry_payload,
            base_kwargs=retry_kwargs,
            request={**request, "arguments": retry_kwargs},
            retry_budget_remaining=remaining,
        )
        current_payload = retry_payload
        current_kwargs = retry_kwargs
        current_retry_of = current_retry_of + 1
    return retries


def _provider_fallback_payloads(
    *,
    generator,
    payload: dict[str, Any],
    base_kwargs: dict[str, Any],
    request: dict[str, Any],
    modality: str,
    retry_of: int,
) -> list[dict[str, Any]]:
    failure_class = _payload_failure_class(payload)
    if failure_class not in {"quota_exceeded", "provider_unavailable", "rate_limited"}:
        return []
    failed_provider = str(payload.get("provider") or "").strip()
    fallback_providers = (
        _available_image_provider_fallbacks(failed_provider=failed_provider)
        if modality == "image"
        else _available_video_provider_fallbacks(failed_provider=failed_provider)
    )
    fallbacks: list[dict[str, Any]] = []
    for provider_name in fallback_providers:
        _deadline_checkpoint(f"{modality}_provider_fallback:{provider_name}")
        if not provider_name or provider_name == failed_provider:
            continue
        fallback_kwargs = {**base_kwargs, "_provider": provider_name}
        fallback_payload = _call_generation_provider(
            generator,
            kind=modality,
            stage=f"{modality}_provider_fallback_generate:{provider_name}",
            kwargs=fallback_kwargs,
        )
        fallback_payload["retry_of"] = retry_of
        fallback_payload["provider_fallback"] = {
            "from_provider": failed_provider,
            "to_provider": provider_name,
            "failure_class": failure_class,
            "retry_of": retry_of,
        }
        fallbacks.append(fallback_payload)
        if not fallback_payload.get("success"):
            _annotate_generation_failure(
                fallback_payload,
                base_kwargs=fallback_kwargs,
                request={**request, "arguments": fallback_kwargs},
                retry_budget_remaining=0,
            )
            continue
        return fallbacks
    return fallbacks


def _payload_failure_class(payload: dict[str, Any]) -> str:
    failure = payload.get("failure") if isinstance(payload.get("failure"), dict) else {}
    if not failure:
        failure = classify_visual_provider_failure(payload)
        payload["failure"] = failure
    return str(failure.get("failure_class") or "").strip()


def _provider_quota_should_stop_candidate_batch(payload: dict[str, Any]) -> bool:
    return _payload_failure_class(payload) == "quota_exceeded"


def _runtime_policy_video_quarantine_payload(
    feedback_policy: dict[str, Any],
    *,
    prompt: str,
) -> dict[str, Any] | None:
    if feedback_policy.get("provider_recovery_mode") != "video_fallback_unavailable":
        return None

    diagnostic = _runtime_policy_video_fallback_diagnostic(feedback_policy)
    provider, model = _active_video_provider_identity()
    provider_label = (
        provider
        or str(diagnostic.get("failed_provider") or "").strip()
        or str(diagnostic.get("failed_provider_family") or "").strip()
        or "video_provider"
    )
    provider_family = _provider_family(provider_label) or str(
        diagnostic.get("failed_provider_family") or ""
    ).strip()
    failure = _runtime_policy_provider_failure(feedback_policy)
    return {
        "success": False,
        "video": None,
        "error_type": "provider_quarantined",
        "error": (
            "Skipped video generation because runtime policy reports no available "
            "video fallback provider. Configure a video fallback provider before retrying."
        ),
        "prompt": prompt,
        "provider": provider_label,
        "model": model or "",
        "failure": failure,
        "provider_quarantine": {
            "modality": "video",
            "provider": provider_label,
            "provider_family": provider_family,
            "failure_class": failure.get("failure_class") or "quota_exceeded",
            "provider_message_code": failure.get("provider_message_code") or "unknown",
            "no_video_fallback_available": True,
            "video_fallback_diagnostic": diagnostic,
        },
    }


def _runtime_policy_provider_failure(feedback_policy: dict[str, Any]) -> dict[str, Any]:
    context = feedback_policy.get("provider_failure_context")
    context = context if isinstance(context, dict) else {}
    failure_classes = context.get("provider_failure_classes")
    error_codes = context.get("provider_error_codes")
    failure_class = _preferred_failure_key(
        failure_classes,
        preferred=("quota_exceeded", "provider_unavailable", "rate_limited", "content_moderation"),
    )
    provider_message_code = _preferred_failure_key(error_codes)
    return {
        "failure_class": failure_class or "quota_exceeded",
        "retryable": False,
        "safe_reframe_allowed": False,
        "provider_message_code": provider_message_code or "unknown",
        "operator_summary": "no available video fallback provider is configured",
    }


def _preferred_failure_key(value: Any, *, preferred: tuple[str, ...] = ()) -> str:
    if not isinstance(value, dict) or not value:
        return ""
    for key in preferred:
        if key in value:
            return key
    best_key = ""
    best_count = -1
    for raw_key, raw_count in value.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        count = _coerce_int(raw_count) or 0
        if best_key and count <= best_count:
            continue
        best_key = key
        best_count = count
    return best_key


def _runtime_policy_video_fallback_diagnostic(feedback_policy: dict[str, Any]) -> dict[str, Any]:
    diagnostics = feedback_policy.get("video_fallback_diagnostics")
    if isinstance(diagnostics, list):
        for diagnostic in diagnostics:
            if isinstance(diagnostic, dict):
                return dict(diagnostic)

    provider, _model = _active_video_provider_identity()
    provider_label = provider or "video_provider"
    return _video_provider_fallback_diagnostic(failed_provider=provider_label)


def _video_provider_quarantine_payload(
    *,
    image_payloads: list[dict[str, Any]],
    prompt: str,
) -> dict[str, Any] | None:
    blocked = _quota_blocked_provider_families(image_payloads)
    if not blocked:
        return None
    provider, model = _active_video_provider_identity()
    provider_family = _provider_family(provider)
    if not provider_family or provider_family not in blocked:
        return None
    if _available_video_provider_fallbacks(failed_provider=provider):
        return None
    failure = _first_quota_failure(image_payloads)
    provider_label = provider or provider_family
    return {
        "success": False,
        "video": None,
        "error_type": "provider_quarantined",
        "error": (
            f"Skipped {provider_label} video generation because this run already hit "
            "the same provider account quota or subscription limit and no available "
            "video fallback provider was found."
        ),
        "prompt": prompt,
        "provider": provider_label,
        "model": model or "",
        "failure": failure,
        "provider_quarantine": {
            "modality": "video",
            "provider": provider_label,
            "provider_family": provider_family,
            "failure_class": failure.get("failure_class") or "quota_exceeded",
            "provider_message_code": failure.get("provider_message_code") or "unknown",
            "no_video_fallback_available": True,
            "video_fallback_diagnostic": _video_provider_fallback_diagnostic(
                failed_provider=provider_label
            ),
        },
    }


def _quota_blocked_provider_families(payloads: list[dict[str, Any]]) -> set[str]:
    families: set[str] = set()
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        if payload.get("success") is True:
            continue
        if _payload_failure_class(payload) != "quota_exceeded":
            continue
        family = _provider_family(str(payload.get("provider") or ""))
        if family:
            families.add(family)
    return families


def _first_quota_failure(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        failure = payload.get("failure") if isinstance(payload.get("failure"), dict) else {}
        if not failure:
            failure = classify_visual_provider_failure(payload)
        if failure.get("failure_class") == "quota_exceeded":
            return dict(failure)
    return {
        "failure_class": "quota_exceeded",
        "retryable": False,
        "safe_reframe_allowed": False,
        "provider_message_code": "unknown",
        "operator_summary": "provider account quota or subscription limit was hit",
    }


def _provider_family(provider: str) -> str:
    value = str(provider or "").strip().lower()
    if not value:
        return ""
    if value.startswith("xai"):
        return "xai"
    return value


def _active_video_provider_identity() -> tuple[str, str]:
    try:
        from tools.video_generation_tool import _resolve_active_provider

        provider = _resolve_active_provider()
    except Exception as exc:  # noqa: BLE001 - preflight should never break generation
        logger.debug("video provider preflight identity unavailable: %s", exc)
        provider = None
    if provider is None:
        return "", ""
    name = str(getattr(provider, "name", "") or "").strip()
    model = ""
    try:
        model = str(provider.default_model() or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("video provider default model unavailable for %s: %s", name, exc)
    return name, model


def _available_image_provider_fallbacks(*, failed_provider: str | None = None) -> list[str]:
    failed = str(failed_provider or "").strip()
    try:
        from agent.image_gen_registry import list_providers
        from hermes_cli.plugins import _ensure_plugins_discovered

        _ensure_plugins_discovered()
        providers = list_providers()
    except Exception as exc:  # noqa: BLE001 - fallback discovery must not block primary error handling
        logger.debug("image provider fallback discovery unavailable: %s", exc)
        return []

    names: list[str] = []
    for provider in providers:
        name = str(getattr(provider, "name", "") or "").strip()
        if not name or name == failed or name in names:
            continue
        try:
            available = provider.is_available()
        except Exception as exc:  # noqa: BLE001
            logger.debug("image provider fallback %s availability failed: %s", name, exc)
            continue
        if available:
            names.append(name)
    return names


def _available_video_provider_fallbacks(*, failed_provider: str | None = None) -> list[str]:
    failed = str(failed_provider or "").strip()
    try:
        from agent.video_gen_registry import list_providers
        from hermes_cli.plugins import _ensure_plugins_discovered

        _ensure_plugins_discovered()
        providers = list_providers()
    except Exception as exc:  # noqa: BLE001 - fallback discovery must not block primary error handling
        logger.debug("video provider fallback discovery unavailable: %s", exc)
        return []

    names: list[str] = []
    for provider in providers:
        name = str(getattr(provider, "name", "") or "").strip()
        if not name or name == failed or name in names:
            continue
        try:
            available = provider.is_available()
        except Exception as exc:  # noqa: BLE001
            logger.debug("video provider fallback %s availability failed: %s", name, exc)
            continue
        if available:
            names.append(name)
    return names


def _video_provider_fallback_diagnostic(*, failed_provider: str | None = None) -> dict[str, Any]:
    failed = str(failed_provider or "").strip()
    failed_family = _provider_family(failed)
    registered_names: list[str] = []
    available_names: list[str] = []
    unavailable_names: list[str] = []
    fallback_names: list[str] = []
    setup_actions: list[dict[str, Any]] = []

    for provider in _video_provider_registry_snapshot():
        name = str(getattr(provider, "name", "") or "").strip()
        if not name or name in registered_names:
            continue
        registered_names.append(name)
        if name == failed:
            continue
        provider_family = _provider_family(name)
        if failed_family and provider_family == failed_family:
            continue
        if _video_provider_is_available(provider):
            available_names.append(name)
            fallback_names.append(name)
            continue
        unavailable_names.append(name)
        setup_actions.append(_video_provider_setup_action(provider, name=name))

    return {
        "failed_provider": failed,
        "failed_provider_family": failed_family,
        "registered_provider_names": registered_names,
        "available_provider_names": available_names,
        "unavailable_provider_names": unavailable_names,
        "fallback_provider_names": fallback_names,
        "setup_actions": setup_actions,
    }


def _video_provider_registry_snapshot() -> list[Any]:
    try:
        from agent.video_gen_registry import list_providers
        from hermes_cli.plugins import _ensure_plugins_discovered

        _ensure_plugins_discovered()
        return list(list_providers())
    except Exception as exc:  # noqa: BLE001 - diagnostics must not block recovery
        logger.debug("video provider fallback diagnostic unavailable: %s", exc)
        return []


def _video_provider_is_available(provider: Any) -> bool:
    try:
        return bool(provider.is_available())
    except Exception as exc:  # noqa: BLE001 - diagnostics must tolerate provider bugs
        logger.debug(
            "video provider fallback diagnostic availability failed for %s: %s",
            getattr(provider, "name", "?"),
            exc,
        )
        return False


def _video_provider_setup_action(provider: Any, *, name: str) -> dict[str, Any]:
    schema: dict[str, Any] = {}
    try:
        raw = provider.get_setup_schema()
        schema = raw if isinstance(raw, dict) else {}
    except Exception as exc:  # noqa: BLE001 - setup hints are best-effort diagnostics
        logger.debug("video provider setup schema unavailable for %s: %s", name, exc)
    env_vars = []
    for item in schema.get("env_vars") or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if key and key not in env_vars:
            env_vars.append(key)
    configured_env_vars = _configured_env_var_names(env_vars)
    return {
        "provider": name,
        "env_vars": env_vars,
        "configured_env_vars": configured_env_vars,
        "missing_env_vars": [key for key in env_vars if key not in configured_env_vars],
        "post_setup": str(schema.get("post_setup") or "").strip(),
    }


def _configured_env_var_names(env_vars: list[str]) -> list[str]:
    configured: list[str] = []
    for key in env_vars:
        if not key:
            continue
        value = os.getenv(key)
        if value is None:
            try:
                from hermes_cli.config import get_env_value

                value = get_env_value(key)
            except Exception:
                value = None
        if value and str(value).strip() and key not in configured:
            configured.append(key)
    return configured


def _retry_generation_payload(
    *,
    generator,
    payload: dict[str, Any],
    base_kwargs: dict[str, Any],
    request: dict[str, Any],
    retry_budget_remaining: int,
    retry_of: int,
) -> dict[str, Any] | None:
    retries = _retry_generation_payloads(
        generator=generator,
        payload=payload,
        base_kwargs=base_kwargs,
        request=request,
        retry_budget_remaining=retry_budget_remaining,
        retry_of=retry_of,
    )
    return retries[0] if retries else None


def _retry_kwargs_from_recovery(base_kwargs: dict[str, Any], recovery: dict[str, Any]) -> dict[str, Any]:
    retry_kwargs = {**base_kwargs}
    for key in recovery.get("removed_arguments") or []:
        retry_kwargs.pop(str(key), None)
    retry_kwargs.update(_generator_kwargs(recovery.get("modified_arguments")))
    return retry_kwargs


def _annotate_generation_failure(
    payload: dict[str, Any],
    *,
    base_kwargs: dict[str, Any],
    request: dict[str, Any],
    retry_budget_remaining: int,
) -> None:
    if "failure" not in payload:
        payload["failure"] = classify_visual_provider_failure(payload)
    if "recovery" not in payload:
        payload["recovery"] = plan_visual_recovery(
            {**request, "arguments": {**base_kwargs}},
            payload["failure"],
            retry_budget_remaining=retry_budget_remaining,
        )


def _attempt_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in (
        "failure",
        "recovery",
        "retry_of",
        "quality_repair",
        "polish_pass",
        "candidate_escalation",
        "provider_family",
        "quota_source",
        "provider_fallback",
        "fallback_attempted",
        "fallback_from_provider",
        "fallback_reason",
        "primary_failure_class",
        "primary_provider_message_code",
        "primary_error_type",
        "provider_quarantine",
        "artifact_source",
    ):
        if key in payload:
            metadata[key] = payload[key]
    return metadata


def _payload_vision_observation(payload: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("vision_observation", "visual_quality_observation"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return None


def _generator_kwargs(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        key: item
        for key, item in value.items()
        if key in {
            "prompt",
            "aspect_ratio",
            "duration",
            "candidate_budget",
            "reference_image_urls",
            "image_url",
            "_provider",
        }
    }


def _source_media_from_attachments(attachments: list[str]) -> dict[str, Any]:
    for attachment in attachments:
        meta = probe_media_reference(attachment)
        if meta.width and meta.height:
            return {"width": meta.width, "height": meta.height}
    return {}


def _video_source_media(source_image: str) -> dict[str, Any]:
    media = _source_media_from_attachments([source_image])
    media["reference_count"] = 1
    media["references"] = [source_image]
    media["single_source_image"] = True
    return media


def _video_source_image_count(source_image: str | None) -> int:
    return 1 if isinstance(source_image, str) and source_image.strip() else 0


def _video_source_policy(
    *,
    wants_video: bool,
    image_first_for_video: bool,
    video_source_artifact_id: str | None,
    video_source_image: str | None,
) -> str:
    if not wants_video or not video_source_image:
        return "none"
    if image_first_for_video and video_source_artifact_id:
        return "single_ranked_selected_image"
    return "single_source_image"


def _score_candidates(
    ledger: VisualAttemptLedger,
    *,
    request_id: str,
    intent_signature: str,
    strategy_signature: str,
    modality: str,
    has_reference_image: bool,
    candidates: list[dict[str, Any]],
    request_category: str = "portrait",
    inline_vision_judge: bool | str = "auto",
    vision_analyzer=None,
    reference_binding: dict[str, Any] | None = None,
) -> None:
    if not candidates:
        return
    provider_stats = compute_provider_reliability(ledger, request_id=request_id)
    preference_profile = build_preference_profile(ledger, bucket=intent_signature)
    recent_hashes: set[str] = set()
    inline_vision_disabled_for_batch = False
    for candidate in candidates:
        inline_enabled = (
            _should_run_inline_vision_judge(candidate, inline_vision_judge)
            and not inline_vision_disabled_for_batch
        )
        vision_observation = build_candidate_vision_observation(
            candidate,
            fallback_observation=build_artifact_observation(candidate),
            inline_enabled=inline_enabled,
            analyzer=vision_analyzer,
        )
        vision_observation = augment_observation_with_reference_similarity(candidate, vision_observation)
        evidence = vision_observation.get("evidence") if isinstance(vision_observation.get("evidence"), dict) else {}
        candidate["vision_observation_source"] = evidence.get("source")
        vision_failure = (
            vision_observation.get("vision_failure")
            if isinstance(vision_observation.get("vision_failure"), dict)
            else None
        )
        if vision_failure:
            candidate["vision_failure"] = vision_failure
            if _inline_vision_failure_disables_batch(vision_failure):
                inline_vision_disabled_for_batch = True
        quality = judge_visual_quality(
            candidate,
            request_context={
                "has_reference_image": has_reference_image,
                "category": request_category,
                **({"reference_binding": _sanitized_reference_binding(reference_binding)} if reference_binding else {}),
            },
            recent_artifact_hashes=recent_hashes,
            vision_observation=vision_observation,
        )
        if evidence.get("source"):
            quality["evidence"] = {
                "source": evidence.get("source"),
                "summary": evidence.get("summary", ""),
            }
        if vision_failure:
            quality["vision_failure"] = vision_failure
        content_hash = candidate.get("content_hash")
        if isinstance(content_hash, str) and content_hash:
            recent_hashes.add(content_hash)
        candidate["judge_scores"] = quality["scores"]
        candidate["quality_issues"] = quality.get("quality_issues", [])
        candidate["preference_dimensions"] = quality.get("preference_dimensions", {})
        ledger.record_judgment(
            request_id=request_id,
            attempt_id=candidate.get("attempt_id"),
            artifact_id=candidate.get("artifact_id"),
            judge_name="visual_quality_judge",
            score=quality.get("confidence"),
            verdict="pass" if quality.get("confidence", 0.0) >= 0.5 else "review",
            details=quality,
            metadata={
                "intent_signature": intent_signature,
                "strategy_signature": strategy_signature,
                "modality": modality,
                "judge_sources": quality.get("judge_sources", {}),
                "uncertainty_reasons": quality.get("uncertainty_reasons", []),
                "vision_observation_source": candidate.get("vision_observation_source"),
                **({"vision_failure": vision_failure} if vision_failure else {}),
            },
        )
        candidate["reward"] = score_visual_candidate(
            candidate,
            provider_stats=provider_stats,
            preference_profile=preference_profile,
        )


def _inline_vision_judge_mode(args: dict[str, Any]) -> bool | str:
    if args.get("inline_vision_judge") is not None:
        return _coerce_bool(args.get("inline_vision_judge"))
    env_value = os.environ.get("HERMES_VISUAL_INLINE_VISION_JUDGE", "auto").strip().lower()
    if env_value in {"0", "false", "no", "off", "disabled"}:
        return False
    if env_value in {"1", "true", "yes", "on", "enabled"}:
        return True
    return "auto"


def _should_run_inline_vision_judge(candidate: dict[str, Any], mode: bool | str) -> bool:
    if mode is True:
        return candidate.get("kind") == "image"
    if mode is False:
        return False
    if candidate.get("kind") != "image":
        return False
    provider = str(candidate.get("provider") or "").strip().lower()
    model = str(candidate.get("model") or "").strip().lower()
    return bool(provider) and provider not in {"fixture", "mock", "test"} and "fixture" not in model


def _inline_vision_failure_disables_batch(failure: dict[str, Any]) -> bool:
    return str(failure.get("failure_class") or "") in {
        "provider_unavailable",
        "quota_exceeded",
        "rate_limited",
    }


def _record_learning_trace(
    ledger: VisualAttemptLedger,
    *,
    request_id: str,
    intent_signature: str,
    strategy_signature: str,
    strategy_plan: dict[str, Any],
    modality: str,
    rank_decision: dict[str, Any],
    candidates: list[dict[str, Any]],
    has_reference_image: bool,
) -> dict[str, Any]:
    selected = _selected_candidate(candidates, rank_decision.get("selected_artifact_id"))
    top = selected or _top_ranked_candidate(candidates, rank_decision.get("ranked_artifact_ids"))
    reward = top.get("reward", {}) if top else {}
    active_learning = decide_visual_action(
        {
            "decision": rank_decision.get("decision"),
            "top_score": reward.get("final_score", 0.0),
            "top_confidence": reward.get("confidence", 0.0),
            "uncertainty_reasons": reward.get("uncertainty_reasons", []),
        },
        request_context={
            "has_reference_image": has_reference_image,
            "candidate_count": len(candidates),
            "retry_budget_remaining": 0,
            "failure_type": rank_decision.get("reason"),
        },
    )
    ledger.record_ranking(
        request_id=request_id,
        selected_artifact_id=rank_decision.get("selected_artifact_id"),
        decision=rank_decision.get("decision"),
        scores={
            "reward": reward,
            "ranked_artifact_ids": rank_decision.get("ranked_artifact_ids", []),
        },
        metadata={
            "modality": modality,
            "active_learning": active_learning,
            "strategy_signature": strategy_signature,
            "strategy_plan": strategy_plan,
        },
    )
    record_shadow_update(
        ledger,
        request_id=request_id,
        intent_signature=intent_signature,
        strategy_signature=strategy_signature,
        proposed_change={
            "type": "strategy_observation",
            "modality": modality,
            "activation": "shadow_only",
        },
        evidence={
            "candidate_count": len(candidates),
            "selected_artifact_id": rank_decision.get("selected_artifact_id"),
            "rank_decision": rank_decision.get("decision"),
        },
        confidence=active_learning.get("top_confidence"),
    )
    return active_learning


def _selected_candidate(
    candidates: list[dict[str, Any]],
    selected_artifact_id: str | None,
) -> dict[str, Any] | None:
    if selected_artifact_id is None:
        return None
    return next(
        (candidate for candidate in candidates if candidate.get("artifact_id") == selected_artifact_id),
        None,
    )


def _ranked_candidate_options(
    candidates: list[dict[str, Any]],
    ranked_artifact_ids: list[str],
) -> list[dict[str, Any]]:
    by_id = {
        str(candidate.get("artifact_id")): candidate
        for candidate in candidates
        if candidate.get("artifact_id")
    }
    ranked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for artifact_id in ranked_artifact_ids or []:
        key = str(artifact_id)
        candidate = by_id.get(key)
        if candidate and key not in seen:
            ranked.append(candidate)
            seen.add(key)
    return ranked


def _enforce_non_grid_video_source_decision(
    rank_decision: Any,
    *,
    candidates: list[dict[str, Any]],
    prompt: str,
    wants_video: bool,
    image_first_for_video: bool,
) -> Any:
    if not wants_video or not image_first_for_video:
        return rank_decision
    selected = _selected_candidate(candidates, rank_decision.selected_artifact_id)
    if selected is None or not _candidate_has_source_frame_grid_issue(selected, prompt=prompt):
        return rank_decision
    for artifact_id in rank_decision.ranked_artifact_ids:
        candidate = _selected_candidate(candidates, str(artifact_id))
        if candidate is None or candidate is selected:
            continue
        if _candidate_has_blocking_video_source_issue(candidate, prompt=prompt):
            continue
        return replace(
            rank_decision,
            selected_artifact_id=candidate.get("artifact_id"),
            selected_attempt_id=candidate.get("attempt_id"),
            reason="selected_non_grid_video_source",
        )
    return rank_decision


def _candidate_has_source_frame_grid_issue(candidate: dict[str, Any], *, prompt: str) -> bool:
    quality_issues, _ignored = _blocking_quality_issues(
        _string_list(candidate.get("quality_issues")),
        prompt=prompt,
    )
    return "source_frame_grid" in quality_issues


def _candidate_has_blocking_video_source_issue(candidate: dict[str, Any], *, prompt: str) -> bool:
    quality_issues, _ignored = _blocking_quality_issues(
        _string_list(candidate.get("quality_issues")),
        prompt=prompt,
    )
    return bool(quality_issues)


def _delivery_gate_decision(
    active_learning: dict[str, Any],
    candidate: dict[str, Any] | None,
    *,
    prompt: str,
) -> dict[str, Any]:
    if candidate is None:
        return {
            "allowed": False,
            "reason": "no_selected_candidate",
            "active_learning_action": active_learning.get("action"),
            "quality_issues": [],
            "ignored_quality_issues": [],
        }
    quality_issues, ignored_quality_issues = _blocking_quality_issues(
        _string_list(candidate.get("quality_issues")),
        prompt=prompt,
    )
    action = str(active_learning.get("action") or "")
    if "source_frame_grid" in quality_issues:
        return {
            "allowed": False,
            "reason": "invalid_video_source_frame",
            "active_learning_action": action,
            "quality_issues": quality_issues,
            "ignored_quality_issues": ignored_quality_issues,
        }
    if any(issue in VIDEO_BLOCKING_QUALITY_ISSUES for issue in quality_issues):
        return {
            "allowed": False,
            "reason": "video_quality_issue_blocked",
            "active_learning_action": action,
            "quality_issues": quality_issues,
            "ignored_quality_issues": ignored_quality_issues,
        }
    if any(issue in {"reference_role_evidence_missing", "reference_identity_drift"} for issue in quality_issues):
        return {
            "allowed": False,
            "reason": "active_learning_review_required",
            "active_learning_action": action,
            "quality_issues": quality_issues,
            "ignored_quality_issues": ignored_quality_issues,
        }
    if action == "fail_closed" and quality_issues:
        return {
            "allowed": False,
            "reason": "active_learning_fail_closed",
            "active_learning_action": action,
            "quality_issues": quality_issues,
            "ignored_quality_issues": ignored_quality_issues,
        }
    preference_dimension_fit = _candidate_preference_dimension_fit(candidate)
    if (
        preference_dimension_fit is not None
        and preference_dimension_fit < PREFERENCE_DIMENSION_DELIVERY_THRESHOLD
        and quality_issues
    ):
        return {
            "allowed": False,
            "reason": "pre_slack_preference_dimension_low",
            "active_learning_action": action,
            "quality_issues": quality_issues,
            "ignored_quality_issues": ignored_quality_issues,
            "preference_dimension_fit": preference_dimension_fit,
            "threshold": PREFERENCE_DIMENSION_DELIVERY_THRESHOLD,
        }
    if any(issue in ALWAYS_BLOCKING_QUALITY_ISSUES for issue in quality_issues):
        return {
            "allowed": False,
            "reason": "active_learning_review_required",
            "active_learning_action": action,
            "quality_issues": quality_issues,
            "ignored_quality_issues": ignored_quality_issues,
        }
    return {
        "allowed": True,
        "reason": "delivery_allowed",
        "active_learning_action": action,
        "quality_issues": quality_issues,
        "ignored_quality_issues": ignored_quality_issues,
    }


def _composition_guide_delivery_gate(
    active_learning: dict[str, Any],
    candidate: dict[str, Any] | None,
) -> dict[str, Any]:
    if candidate is None:
        return {
            "allowed": False,
            "reason": "no_selected_candidate",
            "active_learning_action": active_learning.get("action"),
            "quality_issues": [],
            "ignored_quality_issues": [],
        }
    return {
        "allowed": True,
        "reason": "composition_guide_delivery",
        "active_learning_action": active_learning.get("action"),
        "quality_issues": [],
        "ignored_quality_issues": [],
    }


def _hybrid_final_combine_quality_gate(candidate: dict[str, Any] | None) -> dict[str, Any]:
    if candidate is None:
        return {
            "passed": False,
            "selected_passed": False,
            "failure_reasons": ["no_selected_candidate"],
        }
    observation = candidate.get("vision_observation")
    if not isinstance(observation, dict):
        observation = {}
    thresholds = {
        "character_identity_adherence": 0.72,
        "pose_composition_adherence": 0.72,
        "wardrobe_adherence": 0.62,
        "visual_appeal": 0.62,
    }
    scores = {
        key: _coerce_gate_float(observation.get(key), default=0.5)
        for key in thresholds
    }
    defects = _string_list(observation.get("artifact_defects"))
    failure_reasons = [
        key
        for key, threshold in thresholds.items()
        if scores.get(key, 0.0) < threshold
    ]
    contamination_defects = [
        defect
        for defect in defects
        if defect
        in {
            "guide_artifact_contamination",
            "melted_or_wavy_contours",
            "reference_identity_drift",
        }
    ]
    failure_reasons.extend(contamination_defects)
    passed = not failure_reasons
    return {
        "passed": passed,
        "selected_passed": passed,
        "scores": scores,
        "thresholds": thresholds,
        "failure_reasons": failure_reasons,
        "artifact_defects": defects,
    }


def _with_hybrid_quality_gate_block(
    gate: dict[str, Any],
    hybrid_gate: dict[str, Any],
) -> dict[str, Any]:
    blocked = dict(gate)
    blocked["allowed"] = False
    blocked["reason"] = "hybrid_quality_gate_failed"
    blocked["hybrid_quality_gate"] = hybrid_gate
    quality_issues = list(blocked.get("quality_issues") or [])
    for reason in _string_list(hybrid_gate.get("failure_reasons")):
        if reason not in quality_issues:
            quality_issues.append(reason)
    blocked["quality_issues"] = quality_issues
    return blocked


def _with_hybrid_quality_gate_pass(
    gate: dict[str, Any],
    hybrid_gate: dict[str, Any],
) -> dict[str, Any]:
    passed = dict(gate)
    quality_issues = [
        issue
        for issue in _string_list(passed.get("quality_issues"))
        if issue != "reference_role_evidence_missing"
    ]
    passed["quality_issues"] = quality_issues
    passed["hybrid_quality_gate"] = hybrid_gate
    if not quality_issues and passed.get("reason") == "active_learning_review_required":
        passed["allowed"] = True
        passed["reason"] = "delivery_allowed"
    return passed


def _coerce_gate_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _should_escalate_candidate_budget(gate: dict[str, Any]) -> bool:
    return str(gate.get("reason") or "") == "pre_slack_preference_dimension_low"


def _blocking_quality_issues(issues: list[str], *, prompt: str) -> tuple[list[str], list[str]]:
    portrait_like = _portrait_like_prompt(prompt)
    blocking: list[str] = []
    ignored: list[str] = []
    for issue in issues:
        if issue in ALWAYS_BLOCKING_QUALITY_ISSUES or issue in VIDEO_BLOCKING_QUALITY_ISSUES:
            blocking.append(issue)
        elif issue in PORTRAIT_BLOCKING_QUALITY_ISSUES:
            if portrait_like:
                blocking.append(issue)
            else:
                ignored.append(issue)
    return blocking, ignored


def _candidate_preference_dimension_fit(candidate: dict[str, Any]) -> float | None:
    reward = candidate.get("reward")
    dimensions = reward.get("dimensions") if isinstance(reward, dict) else None
    if not isinstance(dimensions, dict) or dimensions.get("preference_dimension_fit") is None:
        return None
    try:
        return float(dimensions.get("preference_dimension_fit") or 0.0)
    except (TypeError, ValueError):
        return None


def _candidate_escalation_prompt(prompt: str, gate: dict[str, Any]) -> str:
    issues = _string_list(gate.get("quality_issues"))
    instructions: list[str] = []
    if "subject_not_attractive" in issues or "not_beautiful" in issues:
        instructions.append("choose a clearly more attractive subject rendering with natural facial features")
    if "face_unnatural" in issues:
        instructions.append("use a cleaner, more natural face structure and expression")
    if "stockings_bad" in issues:
        instructions.append("use refined realistic wardrobe and legwear material texture")
    if "composition_bad" in issues:
        instructions.append("try a different stronger editorial pose and framing")
    if not instructions:
        instructions.append("try a distinct higher-quality candidate while preserving the user's intent")
    return (
        f"{prompt}\n\n"
        "Additional candidate pass: generate a new alternative candidate instead of repairing the same draft; "
        + "; ".join(instructions)
        + ". Keep the user's intent, but vary pose, framing, and visual execution enough to escape the failed draft."
    )


def _image_polish_prompt(prompt: str) -> str:
    return (
        f"{prompt}\n\n"
        "Grok Web polish pass: improve the selected image's final visual quality, face/detail polish, "
        "lighting, material texture, and overall appeal while preserving the current composition, "
        "identity, pose, camera angle, outfit, color palette, and user-requested constraints. "
        "Do not redesign the image; treat the supplied image as the edit anchor and make a refined version."
    )


def _quality_repair_prompt(
    prompt: str,
    gate: dict[str, Any],
    *,
    mode: str = "default",
    reference_binding: dict[str, Any] | None = None,
) -> str:
    issues = _string_list(gate.get("quality_issues"))
    instructions: list[str] = []
    reference_repair = _reference_role_repair_instruction(reference_binding, issues)
    if reference_repair:
        instructions.append(reference_repair)
    if "subject_not_attractive" in issues or "not_beautiful" in issues:
        instructions.append("render a naturally beautiful subject with clean facial features")
    if "composition_bad" in issues:
        instructions.append("use a stronger editorial composition with clear framing")
    if "stockings_bad" in issues:
        instructions.append("make wardrobe and legwear texture clean, refined, and realistic")
    if "reference_identity_drift" in issues:
        instructions.append("preserve the reference identity and recognizable facial structure")
    if not instructions:
        instructions.append("improve visual quality while preserving the original intent")
    repair = "; ".join(instructions)
    if mode == "preferred":
        policy_instruction = "Proven quality repair strategy: reuse the historically successful repair pattern. "
    elif mode == "escalated":
        policy_instruction = (
            "Escalated quality repair strategy: change the composition path instead of repeating the failed draft. "
        )
    elif mode == "hybrid_final_combine":
        policy_instruction = (
            "Hybrid repair pass: regenerate once with stricter role separation. Preserve character identity "
            "from character-design refs, preserve pose/camera/framing from pose-composition refs, and remove "
            "any guide lines, contour-map artifacts, stitched-reference blending, or identity drift. "
        )
        return (
            f"{policy_instruction}Quality repair pass: "
            f"{repair}. Avoid distorted anatomy, awkward face rendering, weak composition, "
            "and low-quality surface detail.\n\n"
            f"Original target to preserve: {prompt}"
        )
    else:
        policy_instruction = ""
    return (
        f"{prompt}\n\n"
        f"{policy_instruction}Quality repair pass: "
        f"{repair}. Avoid distorted anatomy, awkward face rendering, weak composition, "
        "and low-quality surface detail."
    )


def _reference_role_repair_instruction(
    binding: dict[str, Any] | None,
    issues: list[str],
) -> str:
    if not isinstance(binding, dict):
        return ""
    if not any(
        issue
        in {
            "reference_identity_drift",
            "reference_role_evidence_missing",
            "composition_bad",
        }
        for issue in issues
    ):
        return ""
    role_instructions: list[str] = []
    saw_pose_reference = False
    for item in binding.get("reference_order") or []:
        if not isinstance(item, dict):
            continue
        index = _coerce_int(item.get("index"))
        role_hint = str(item.get("role_hint") or "").strip()
        if index is None or not role_hint or role_hint == "visual_reference":
            continue
        role_instructions.append(f"Use ref {index} only for {role_hint}")
        if role_hint == "character_identity":
            role_instructions.append(
                f"lock the final subject's identity, face, hair, eye color, silhouette, outfit, "
                f"accessories, and palette to ref {index}"
            )
        elif role_hint == "pose_composition":
            saw_pose_reference = True
            role_instructions.append(
                f"use ref {index} only for pose, camera angle, framing, body orientation, limb placement, "
                "and scene composition"
            )
        elif role_hint == "wardrobe":
            role_instructions.append(f"use ref {index} only for clothing, wardrobe, material, and palette")
        elif role_hint == "style":
            role_instructions.append(f"use ref {index} only for art direction, rendering style, and finish")
        elif role_hint == "background":
            role_instructions.append(f"use ref {index} only for background, environment, and scene context")
    if not role_instructions:
        return ""
    if saw_pose_reference:
        role_instructions.append(
            "Do not copy identity, face, hair, wardrobe, color palette, or character traits "
            "from pose/composition references"
        )
    role_instructions.append("if roles conflict, preserve the user's listed role binding over visual similarity")
    return "Reference role repair pass: " + "; ".join(role_instructions)


def _video_quality_repair_prompt(prompt: str, gate: dict[str, Any], *, mode: str = "default") -> str:
    issues = _string_list(gate.get("quality_issues"))
    instructions: list[str] = []
    if "aspect_integrity_bad" in issues:
        instructions.append("preserve the source image aspect ratio exactly with no horizontal or vertical stretching")
    if "motion_bad" in issues:
        instructions.append("use natural real-time motion, steady subject anatomy, and avoid slow motion or frozen-frame drift")
    if not instructions:
        instructions.append("improve video coherence while preserving the source image and original composition")
    repair = "; ".join(instructions)
    if mode == "preferred":
        policy_instruction = "Proven video quality repair strategy: reuse the historically successful repair pattern. "
    elif mode == "escalated":
        policy_instruction = (
            "Escalated video quality repair strategy: change the motion path instead of repeating the failed clip. "
        )
    else:
        policy_instruction = ""
    return (
        f"{prompt}\n\n"
        f"{policy_instruction}Video quality repair pass: {repair}. "
        "Keep the same subject, framing, lighting, and user intent."
    )


def _quality_repair_policy_mode(feedback_policy: dict[str, Any], modality: str) -> str:
    modes = feedback_policy.get("quality_repair_modes")
    if isinstance(modes, dict):
        mode = str(modes.get(modality) or "default").strip().lower()
        return mode if mode in {"default", "preferred", "escalated"} else "default"
    mode = str(feedback_policy.get("quality_repair_mode") or "default").strip().lower()
    return mode if mode in {"default", "preferred", "escalated"} else "default"


def _quality_guidance_plan(
    feedback_policy: dict[str, Any],
    *,
    request_category: str,
    image_provider: str | None = None,
) -> dict[str, dict[str, Any]]:
    return {
        "image": _quality_guidance_entry(
            feedback_policy,
            "image",
            request_category=request_category,
            image_provider=image_provider,
        ),
        "video": _quality_guidance_entry(feedback_policy, "video", request_category=request_category),
    }


def _quality_guidance_entry(
    feedback_policy: dict[str, Any],
    modality: str,
    *,
    request_category: str,
    image_provider: str | None = None,
) -> dict[str, Any]:
    mode = _quality_repair_policy_mode(feedback_policy, modality)
    if mode == "default":
        return {
            "enabled": False,
            "mode": mode,
            "prompt_suffix": "",
        }
    dimension_guidance = _dimension_quality_guidance(
        feedback_policy,
        modality=modality,
        request_category=request_category,
    )
    if modality == "video":
        suffix = (
            "First-pass video quality guidance: use natural real-time motion, "
            "visible subject, camera, or environmental movement, preserve the source aspect ratio, "
            "avoid slow motion, avoid slow cinematic-only push-in, avoid stretching, "
            "and keep subject anatomy stable."
        )
    elif _anime_like_category(request_category):
        suffix = (
            "First-pass visual quality guidance: anime illustration polish, clean expressive facial features, "
            "appealing stylized anatomy, refined wardrobe and legwear rendering, strong composition, "
            "crisp linework, vibrant color harmony."
        )
        xai_pack = _xai_anime_quality_pack(feedback_policy, image_provider=image_provider)
        if xai_pack:
            suffix = f"{suffix} {xai_pack}"
    elif _portrait_like_category(request_category):
        suffix = (
            "First-pass visual quality guidance: clean facial features, naturally polished subject, "
            "refined wardrobe and legwear texture, strong editorial composition, realistic details."
        )
    else:
        suffix = (
            "First-pass visual quality guidance: clean product detail, strong composition, "
            "realistic material texture, polished commercial lighting."
        )
    if dimension_guidance:
        suffix = f"{suffix} {dimension_guidance}"
    return {
        "enabled": True,
        "mode": mode,
        "prompt_suffix": suffix,
        "source_action_types": list(feedback_policy.get("applied_action_types") or []),
    }


def _dimension_quality_guidance(
    feedback_policy: dict[str, Any],
    *,
    modality: str,
    request_category: str,
) -> str:
    dimensions = feedback_policy.get("repair_dimensions")
    if not isinstance(dimensions, list):
        return ""
    instructions: list[str] = []
    for item in dimensions:
        if not isinstance(item, dict):
            continue
        dimension = str(item.get("dimension") or "").strip()
        if modality == "image" and dimension == "motion_quality":
            continue
        hint = str(item.get("repair_hint") or "").strip()
        instruction = _dimension_quality_instruction(
            dimension,
            hint,
            modality=modality,
            request_category=request_category,
        )
        if instruction and instruction not in instructions:
            instructions.append(instruction)
    if not instructions:
        return ""
    return "Dimension-specific quality guidance: " + "; ".join(instructions) + "."


def _dimension_quality_instruction(
    dimension: str,
    repair_hint: str,
    *,
    modality: str,
    request_category: str,
) -> str:
    if dimension == "subject_beauty" and _anime_like_category(request_category):
        return "subject_beauty: improve stylized attractiveness while preserving anime design intent"
    if dimension == "pose_composition" and _anime_like_category(request_category):
        return (
            "pose_composition: use dynamic contrapposto, torso twist, hip tilt, readable line of action, "
            "and asymmetrical silhouette instead of stiff standing"
        )
    if dimension == "camera_composition" and _anime_like_category(request_category):
        return (
            "camera_composition: use off-axis low-angle three-quarter camera, diagonal S-curve, "
            "foreground overlap, and intentional negative space"
        )
    if dimension == "lighting_depth" and _anime_like_category(request_category):
        return (
            "lighting_depth: use warm key light, cool rim light, layered cast shadows, bounce light, "
            "and controlled bloom"
        )
    if dimension == "linework_finish" and _anime_like_category(request_category):
        return (
            "linework_finish: use variable tapered line weight, confident ink hierarchy, crisp hair strands, "
            "and refined fabric folds"
        )
    if dimension == "sensual_outfit_design" and _anime_like_category(request_category):
        return (
            "sensual_outfit_design: use specific seductive outfit construction, high slit or off-shoulder cut, "
            "corset/bodysuit tension, sheer sleeves or stockings, with tasteful adult coverage"
        )
    return {
        "subject_beauty": "subject_beauty: raise overall subject attractiveness while keeping natural realism",
        "face_naturalness": "face_naturalness: prioritize natural facial structure, clean eyes, and non-distorted expression",
        "glamour_impact": "glamour_impact: increase polished editorial glamour through pose, lighting, and camera angle",
        "fashion_material_quality": "fashion_material_quality: improve wardrobe and legwear material texture without plastic artifacts",
        "pose_composition": "pose_composition: use a more dynamic pose and cleaner framing",
        "motion_quality": "motion_quality: use clear real-time movement with stable anatomy",
    }.get(dimension, f"{dimension}: {repair_hint}" if repair_hint else "")


def _xai_anime_quality_pack(
    feedback_policy: dict[str, Any],
    *,
    image_provider: str | None,
) -> str:
    if not _xai_like_provider(image_provider):
        return ""
    dimensions = feedback_policy.get("repair_dimensions") if isinstance(feedback_policy, dict) else []
    if not isinstance(dimensions, list):
        return ""
    dimension_set = {str(item.get("dimension") or "").strip() for item in dimensions if isinstance(item, dict)}
    if not dimension_set.intersection(
        {
            "pose_composition",
            "camera_composition",
            "lighting_depth",
            "linework_finish",
            "sensual_outfit_design",
        }
    ):
        return ""
    return (
        "XAI anime quality pack: use dynamic contrapposto with torso twist and hip tilt; "
        "off-axis low-angle three-quarter camera with diagonal S-curve and foreground overlap; "
        "warm key light plus cool rim light, layered cast shadows, bounce light, controlled bloom; "
        "variable tapered line weight, confident ink hierarchy, crisp hair strands and refined fabric folds; "
        "specific seductive outfit construction with high slit or off-shoulder cut, corset/bodysuit tension, "
        "sheer sleeves or stockings, tasteful adult coverage."
    )


def _xai_like_provider(value: str | None) -> bool:
    text = str(value or "").strip().lower()
    return text in {"xai", "grok", "grok-web-imagine", "xai-grok"} or "grok" in text


def _apply_first_pass_quality_guidance(prompt: str, guidance: dict[str, Any]) -> str:
    suffix = str(guidance.get("prompt_suffix") or "").strip() if isinstance(guidance, dict) else ""
    if not suffix or suffix in prompt:
        return prompt
    return f"{prompt}\n\n{suffix}"


def _portrait_like_category(category: str) -> bool:
    return any(token in str(category or "").lower() for token in ("portrait", "fashion", "character", "cosplay"))


def _anime_like_category(category: str) -> bool:
    return "anime" in str(category or "").lower()


def _portrait_like_prompt(prompt: str) -> bool:
    text = prompt.lower()
    return any(
        token in text
        for token in (
            "portrait",
            "fashion",
            "cosplay",
            "character",
            "girl",
            "woman",
            "model",
            "person",
            "寫真",
            "人像",
            "人物",
            "角色",
            "美少女",
            "美女",
            "性感",
            "絲襪",
            "腿",
            "臉",
        )
    )


def _visual_request_category(prompt: str) -> str:
    if _composition_guide_like_prompt(prompt):
        return "composition_guide"
    if _anime_like_prompt(prompt):
        return "anime_character"
    if _portrait_like_prompt(prompt):
        return "portrait"
    if _product_like_prompt(prompt):
        return "product"
    return "scene"


def _composition_guide_like_prompt(prompt: str) -> bool:
    text = str(prompt or "").lower()
    compact = re.sub(r"\s+", "", text)
    return any(
        token in text
        for token in (
            "pose guide",
            "composition guide",
            "layout guide",
            "composition candidate",
            "pose candidate",
            "composition study",
        )
    ) or any(
        token in compact
        for token in (
            "先產構圖",
            "先产构图",
            "產出構圖",
            "产出构图",
            "生成構圖",
            "生成构图",
            "給我構圖",
            "给我构图",
            "產畫面構圖",
            "产画面构图",
            "構圖草圖",
            "构图草图",
            "構圖候選",
            "构图候选",
            "動作構圖",
            "动作构图",
            "人物構圖",
            "人物构图",
            "角色構圖",
            "角色构图",
            "人體構圖",
            "人体构图",
        )
    ) or any(token in compact for token in ("構圖草圖", "构图草图", "構圖候選", "构图候选")) or (
        ("構圖" in compact or "构图" in compact)
        and any(token in compact for token in ("先產", "先产", "生成", "給我", "给我"))
        and not any(token in compact for token in ("腿部構圖", "腿部构图", "畫面構圖", "画面构图"))
    )


def _product_like_prompt(prompt: str) -> bool:
    text = str(prompt or "").lower()
    compact = re.sub(r"\s+", "", text)
    if any(token in compact for token in ("鋼筆", "產品", "物品", "商品")):
        return True
    return any(
        re.search(pattern, text)
        for pattern in (
            r"\bproduct\b",
            r"\bobject\b",
            r"\bfountain\s+pen\b",
            r"\bpen\b",
        )
    )


def _anime_like_prompt(prompt: str) -> bool:
    text = str(prompt or "").lower()
    compact = re.sub(r"\s+", "", text)
    return any(
        token in text
        for token in (
            "anime",
            "manga",
            "illustration",
            "anime style",
        )
    ) or any(
        token in compact
        for token in (
            "動漫",
            "動畫風",
            "二次元",
            "漫畫",
            "插畫",
        )
    )


def _top_ranked_candidate(
    candidates: list[dict[str, Any]],
    ranked_artifact_ids: Any,
) -> dict[str, Any] | None:
    if isinstance(ranked_artifact_ids, list) and ranked_artifact_ids:
        return _selected_candidate(candidates, str(ranked_artifact_ids[0]))
    return candidates[0] if candidates else None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _delivery_safe_generation_payloads(value: Any, *, selected_refs: set[str]) -> Any:
    if isinstance(value, list):
        return [
            _delivery_safe_generation_payloads(item, selected_refs=selected_refs)
            for item in value
        ]
    if not isinstance(value, dict):
        return value
    sanitized: dict[str, Any] = {}
    redacted = False
    for key, item in value.items():
        if key in {"image", "video", "source_video_url"} and isinstance(item, str):
            if item in selected_refs:
                sanitized[key] = item
            else:
                sanitized[key] = None
                redacted = True
            continue
        if key in {"images", "videos"} and isinstance(item, list):
            filtered = [ref for ref in item if isinstance(ref, str) and ref in selected_refs]
            if len(filtered) != len([ref for ref in item if isinstance(ref, str)]):
                redacted = True
            sanitized[key] = filtered
            continue
        sanitized[key] = _delivery_safe_generation_payloads(item, selected_refs=selected_refs)
    if redacted:
        sanitized["unselected_media_redacted"] = True
    return sanitized


def _record_artifact_ref(
    ledger: VisualAttemptLedger,
    *,
    request_id: str,
    attempt_id: str,
    kind: str,
    artifact_ref: str,
    artifact_role: str | None = None,
) -> tuple[str, dict[str, Any]]:
    source_ref = artifact_ref
    probe_ref = _materialize_remote_artifact_ref(artifact_ref, kind=kind)
    meta = probe_media_reference(probe_ref)
    content_hash = meta.sha256
    is_stable = meta.is_stable
    freshness_status = meta.freshness_status
    if _is_remote_url(source_ref) and meta.freshness_status == "unknown" and kind != "video":
        content_hash = "refhash:" + hashlib.sha256(artifact_ref.encode("utf-8")).hexdigest()
        is_stable = True
        freshness_status = "fresh"
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind=kind,
        local_path=meta.local_path,
        uri=source_ref,
        content_hash=content_hash,
        mime_type=meta.mime_type,
        bytes=meta.bytes,
        width=meta.width,
        height=meta.height,
        duration_seconds=getattr(meta, "duration_seconds", None),
        is_stable=is_stable,
        freshness_status=freshness_status,
        metadata=(
            {
                "artifact_role": artifact_role,
                "role_ledger_source": "visual_package_generate",
            }
            if artifact_role
            else None
        ),
    )
    return artifact_id, ledger.get_artifact(artifact_id)


def _materialize_remote_artifact_ref(artifact_ref: str, *, kind: str) -> str:
    if not _is_remote_url(artifact_ref) or kind != "video":
        return artifact_ref
    try:
        return download_remote_media(artifact_ref, kind=kind)
    except Exception as exc:
        logger.warning(
            "could not materialize remote %s artifact %s: %s",
            kind,
            _safe_url_for_log(artifact_ref),
            type(exc).__name__,
        )
        return artifact_ref


def download_remote_media(url: str, *, kind: str) -> str:
    if kind != "video":
        raise ValueError(f"unsupported remote media kind: {kind}")
    current_url = str(url or "").strip()
    for redirect_count in range(MAX_REMOTE_MEDIA_REDIRECTS + 1):
        if not is_safe_url(current_url):
            raise ValueError(f"unsafe remote media URL: {_safe_url_for_log(current_url)}")
        status_code, headers, raw = _remote_media_http_get(current_url)
        if status_code in {301, 302, 303, 307, 308}:
            location = str(headers.get("location") or "").strip()
            if not location:
                raise ValueError("remote media redirect omitted Location header")
            if redirect_count >= MAX_REMOTE_MEDIA_REDIRECTS:
                raise ValueError("remote media redirect limit exceeded")
            current_url = urljoin(current_url, location)
            continue
        if status_code >= 400:
            raise ValueError(f"remote media HTTP status {status_code}")
        if len(raw) > MAX_REMOTE_MEDIA_BYTES:
            raise ValueError("remote media exceeds maximum cache size")
        break
    else:  # pragma: no cover - loop terminates via return/break/error
        raise ValueError("remote media redirect limit exceeded")
    extension = _remote_media_extension(current_url, default="mp4")
    from agent.video_gen_provider import save_bytes_video

    return str(save_bytes_video(raw, prefix="visual-package", extension=extension))


def _remote_media_http_get(url: str) -> tuple[int, dict[str, str], bytes]:
    import httpx

    with httpx.Client(timeout=REMOTE_MEDIA_TIMEOUT_SECONDS, follow_redirects=False) as client:
        with client.stream(
            "GET",
            url,
            headers={"User-Agent": "Hermes visual package"},
        ) as response:
            status_code = int(response.status_code)
            headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
            if status_code in {301, 302, 303, 307, 308}:
                return status_code, headers, b""
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > MAX_REMOTE_MEDIA_BYTES:
                    raise ValueError("remote media exceeds maximum cache size")
                chunks.append(chunk)
            return status_code, headers, b"".join(chunks)


def _safe_url_for_log(url: str, *, max_len: int = 160) -> str:
    raw = str(url or "").strip()
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return "<invalid-url>"
    host = parsed.hostname or ""
    if not parsed.scheme or not host:
        return "<invalid-url>"
    try:
        parsed_port = parsed.port
    except ValueError:
        parsed_port = None
    port = f":{parsed_port}" if parsed_port else ""
    safe = urlunsplit((parsed.scheme, f"{host}{port}", parsed.path, "", ""))
    if len(safe) <= max_len:
        return safe
    return f"{safe[: max(0, max_len - 3)]}..."


def _remote_media_extension(url: str, *, default: str) -> str:
    suffix = urlparse(url).path.rsplit(".", 1)[-1].lower()
    if suffix in {"mp4", "mov", "webm", "mkv"}:
        return suffix
    return default


def _normalise_attachments(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    attachments: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        attachment = normalise_visual_agent_attachment(item)
        if attachment:
            attachments.append(attachment)
    return attachments


def _normalise_reference_binding(value: Any, attachments: list[str]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    binding = dict(value)
    character_index = _coerce_int(binding.get("character_reference_index"))
    pose_index = _coerce_int(binding.get("pose_reference_index"))
    if character_index is not None and 1 <= character_index <= len(attachments):
        binding["character_reference"] = attachments[character_index - 1]
    if pose_index is not None and 1 <= pose_index <= len(attachments):
        binding["pose_reference"] = attachments[pose_index - 1]
    binding.setdefault("reference_order_source", "user_visible_upload_order")
    binding.setdefault("role_policy", "derive_from_user_prompt")
    explicit_order = _normalise_reference_order(binding.get("reference_order"), attachments)
    if explicit_order:
        binding["reference_order"] = explicit_order
        return binding
    if attachments:
        binding["reference_order"] = [
            {
                "index": index,
                "role_hint": _explicit_reference_role_hint(
                    index,
                    character_index=character_index,
                    pose_index=pose_index,
                ),
                "attachment": attachment,
            }
            for index, attachment in enumerate(attachments, start=1)
        ]
    return binding


def _reference_binding_from_session_entries(
    existing: dict[str, Any] | None,
    entries: list[dict[str, Any]],
    attachments: list[str],
) -> dict[str, Any] | None:
    if not entries or not attachments:
        return existing
    attachment_index = {str(attachment): index for index, attachment in enumerate(attachments, start=1)}
    reference_order: list[dict[str, Any]] = []
    has_edit_anchor = False
    has_role_metadata = False
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        uri = str(entry.get("uri") or entry.get("path") or entry.get("attachment") or "").strip()
        index = attachment_index.get(uri)
        if index is None:
            continue
        role_hint = str(entry.get("role_hint") or "visual_reference").strip() or "visual_reference"
        if role_hint in {"selected_output", "previous_selected_output", "previous_output"}:
            role_hint = "edit_anchor"
        item: dict[str, Any] = {
            "index": index,
            "role_hint": role_hint,
            "attachment": attachments[index - 1],
        }
        user_ref_index = entry.get("user_ref_index")
        if role_hint == "edit_anchor":
            has_edit_anchor = True
            user_ref_index = user_ref_index or "previous_selected_output"
        if user_ref_index not in (None, ""):
            item["user_ref_index"] = user_ref_index
            has_role_metadata = True
        if role_hint != "visual_reference":
            has_role_metadata = True
        reference_order.append(item)
    if not reference_order:
        return existing
    if existing and not has_edit_anchor:
        return existing
    if not has_edit_anchor and not has_role_metadata:
        return existing
    binding = dict(existing or {})
    binding["mode"] = "session_edit_references" if has_edit_anchor else "session_references"
    binding["reference_order_source"] = "session_visual_context"
    binding["role_policy"] = (
        "session_context_with_edit_anchor" if has_edit_anchor else "session_context_roles"
    )
    binding["reference_order"] = reference_order
    return binding


def _normalise_reference_order(value: Any, attachments: list[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    reference_order: list[dict[str, Any]] = []
    for ordinal, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        index = _coerce_int(item.get("index")) or ordinal
        if index < 1:
            continue
        entry: dict[str, Any] = {"index": index}
        role_hint = str(item.get("role_hint") or item.get("role") or "").strip()
        if role_hint:
            entry["role_hint"] = role_hint
        attachment = attachments[index - 1] if 1 <= index <= len(attachments) else item.get("attachment")
        if isinstance(attachment, str) and attachment.strip():
            entry["attachment"] = attachment
        reference_order.append(entry)
    return reference_order


def _explicit_reference_role_hint(
    index: int,
    *,
    character_index: int | None,
    pose_index: int | None,
) -> str:
    if index == character_index:
        return "character_identity"
    if index == pose_index:
        return "pose_composition"
    return "visual_reference"


def _apply_reference_binding_prompt(prompt: str, binding: dict[str, Any] | None) -> str:
    if not binding:
        return prompt
    if "Reference roles for this request:" in prompt:
        return prompt
    block = _reference_binding_prompt_block(binding)
    if "Reference binding:" in prompt:
        role_block = _reference_role_contract_block(binding)
        return f"{prompt}\n\n{role_block}" if role_block else prompt
    return f"{prompt}\n\n{block}"


def _reference_binding_prompt_block(binding: dict[str, Any]) -> str:
    parts = [
        "Reference binding: reference N/ref N means the Nth uploaded image in the user's "
        "visible attachment order; reference 1 means the first uploaded image in the user's "
        "visible attachment order. Do not assume fixed roles for any reference index. Derive "
        "each reference role from the user's wording, such as character identity/person, "
        "pose/composition, clothing, wardrobe, style, or background. If a role is not explicit, "
        "treat that reference as a neutral visual reference instead of assigning character or "
        "pose by default."
    ]
    role_block = _reference_role_contract_block(binding)
    if role_block:
        parts.append(role_block)
    return "\n\n".join(parts)


def _reference_role_contract_block(binding: dict[str, Any]) -> str:
    role_lines = []
    for item in binding.get("reference_order") or []:
        if not isinstance(item, dict):
            continue
        index = _coerce_int(item.get("index"))
        role_hint = str(item.get("role_hint") or "").strip()
        if index is None or not role_hint:
            continue
        user_ref_index = item.get("user_ref_index")
        if role_hint == "edit_anchor":
            role_lines.append(
                f"- previous selected output / edit anchor: provider ref {index} role: {role_hint}"
            )
        elif user_ref_index not in (None, ""):
            role_lines.append(
                f"- user ref {user_ref_index} role: {role_hint} (provider ref {index})"
            )
        else:
            role_lines.append(f"- ref {index} role: {role_hint}")
    if not role_lines:
        return ""
    return "\n".join(
        [
            "Reference roles for this request:",
            *role_lines,
            "Use each reference only for its listed role. Do not transfer character identity "
            "from a pose/composition reference, and do not transfer pose/composition from a "
            "character identity reference unless the user explicitly asks for that blend.",
            "For edit_anchor references, treat the previous selected output as the current image "
            "to improve. Preserve its identity, pose, composition, camera, outfit, color palette, "
            "and overall image unless the user explicitly asked to change them; change only the requested details.",
            "For character_identity references, preserve the subject identity, face, hair, eye color, "
            "signature outfit, silhouette, accessories, and palette from that reference.",
            "For pose_composition references, use only pose, camera angle, framing, body orientation, "
            "limb placement, and scene layout; do not copy that reference's character, face, hair, "
            "wardrobe, color palette, or identity traits unless explicitly requested.",
        ]
    )


def _wants_image(prompt: str, args: dict[str, Any]) -> bool:
    if args.get("include_image") is not None:
        return bool(args.get("include_image"))
    prompt_lc = prompt.lower()
    return any(token in prompt_lc for token in ("image", "photo", "picture", "圖片", "圖", "照片", "寫真", "素材"))


def _wants_video(prompt: str, args: dict[str, Any]) -> bool:
    if args.get("include_video") is not None:
        return bool(args.get("include_video"))
    prompt_lc = prompt.lower()
    return any(token in prompt_lc for token in ("video", "clip", "motion", "影片", "視頻", "短片", "動畫"))


def _coerce_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float:
    try:
        return round(max(0.0, min(1.0, float(value))), 4)
    except (TypeError, ValueError):
        return 0.0


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _candidate_visual_source(candidate: dict[str, Any]) -> str:
    for key in ("artifact_path", "local_path", "source_url", "uri"):
        value = candidate.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _learning_mode(
    *,
    controlled_strategy_plan: StrategyPlan | None,
    feedback_strategy_plan: StrategyPlan | None,
) -> str:
    if controlled_strategy_plan is not None:
        return "controlled_read_only"
    if feedback_strategy_plan is not None:
        return "feedback_preferred_read_only"
    return "shadow"


def _applicable_controlled_strategy_plan(
    controlled_strategy_plan: StrategyPlan | None,
    *,
    wants_video: bool,
) -> StrategyPlan | None:
    if controlled_strategy_plan is None:
        return None
    if controlled_strategy_plan.strategy_signature == "image_first_rank_then_video" and not wants_video:
        return None
    return controlled_strategy_plan


def _feedback_policy_with_controlled_strategy(
    feedback_policy: dict[str, Any],
    controlled_strategy_plan: StrategyPlan,
    *,
    args: dict[str, Any],
    wants_image: bool,
    wants_video: bool,
) -> dict[str, Any]:
    if controlled_strategy_plan.strategy_signature != "image_first_rank_then_video" or not wants_video:
        return feedback_policy
    patched = dict(feedback_policy)
    preference = {
        "strategy_signature": controlled_strategy_plan.strategy_signature,
        "source": "controlled_strategy",
        "bucket": controlled_strategy_plan.intent_signature,
        "activation_status": controlled_strategy_plan.activation_status,
        "confidence": controlled_strategy_plan.confidence,
        "candidate_budget": 2,
        "activation_id": controlled_strategy_plan.activation_id,
    }
    patched["strategy_preference"] = preference
    patched["prefer_image_first_video"] = True
    patched["rerank_before_delivery"] = True
    current_budget = _coerce_int(patched.get("candidate_budget")) or 0
    if wants_image and not _candidate_budget_locked_by_user(args) and current_budget < 2:
        patched["candidate_budget"] = 2
        patched["candidate_budget_source"] = "controlled_strategy"
    _append_unique_policy_value(patched, "applied_action_types", "prefer_strategy")
    _append_unique_policy_value(patched, "applied_action_sources", "controlled_strategy")
    _append_unique_policy_value(patched, "policy_sources", "controlled_strategy")
    return patched


def _candidate_budget_locked_by_user(args: dict[str, Any]) -> bool:
    if _coerce_int(args.get("candidate_budget")) is None:
        return False
    source = str(args.get("candidate_budget_source") or "").strip().lower()
    return source != "planner_default"


def _append_unique_policy_value(policy: dict[str, Any], key: str, value: str) -> None:
    values = policy.get(key)
    if not isinstance(values, list):
        values = []
    if value not in values:
        values = [*values, value]
    policy[key] = values


def _strategy_plan_from_feedback_preference(
    base_plan: StrategyPlan,
    *,
    feedback_policy: dict[str, Any],
    intent_signature: str,
) -> StrategyPlan | None:
    preference = feedback_policy.get("strategy_preference")
    if not isinstance(preference, dict):
        return None
    strategy_signature = str(preference.get("strategy_signature") or "").strip()
    if not strategy_signature:
        return None
    return StrategyPlan(
        intent_signature=intent_signature,
        mode="feedback_preferred",
        confidence=_coerce_float(preference.get("confidence")),
        strategy_signature=strategy_signature,
        atom_signatures=list(base_plan.atom_signatures),
        activation_status=str(preference.get("activation_status") or "shadow").strip() or "shadow",
        prompt_mutation_allowed=False,
    )


def _visual_feedback_policy(
    args: dict[str, Any],
    *,
    wants_image: bool,
    wants_video: bool,
) -> dict[str, Any]:
    report = _runtime_visual_feedback_report()
    explicit_candidate_budget, default_candidate_budget = _candidate_budget_policy_inputs(args)
    return resolve_visual_feedback_policy(
        report,
        wants_image=wants_image,
        wants_video=wants_video,
        explicit_candidate_budget=explicit_candidate_budget,
        default_candidate_budget=default_candidate_budget,
    )


def _provider_retry_budget(feedback_policy: dict[str, Any]) -> int:
    value = _coerce_int(feedback_policy.get("provider_retry_budget"))
    if value is not None:
        return _clamp_budget(value, minimum=0, maximum=2)
    return 1


def _candidate_budget_policy_inputs(args: dict[str, Any]) -> tuple[int | None, int]:
    value = _coerce_int(args.get("candidate_budget"))
    source = str(args.get("candidate_budget_source") or "").strip().lower()
    if source == "planner_default":
        return None, _clamp_budget(value or 2, minimum=1, maximum=4)
    return value, 2


def _runtime_visual_feedback_report() -> dict[str, Any]:
    actions = _latest_self_validation_next_actions()
    return {
        "next_actions": actions,
        "policy_sources": ["scheduled_self_validation"] if actions else ["runtime_defaults"],
    }


def _latest_self_validation_next_actions() -> list[dict[str, Any]]:
    latest_path = default_visual_ledger_path().parent / "self_validation" / "latest.json"
    try:
        with latest_path.open("r", encoding="utf-8") as handle:
            raw = handle.read(MAX_RUNTIME_POLICY_SNAPSHOT_BYTES + 1)
        if len(raw.encode("utf-8")) > MAX_RUNTIME_POLICY_SNAPSHOT_BYTES:
            logger.warning("visual runtime policy snapshot exceeds size limit")
            return []
        payload = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 - stale/missing reports must not block generation
        logger.debug("visual scheduled self-validation policy unavailable: %s", exc)
        return []
    if not isinstance(payload, dict):
        return []
    return _runtime_policy_next_actions(payload.get("runtime_policy"))


def _runtime_policy_next_actions(value: Any) -> list[dict[str, Any]]:
    policy = value if isinstance(value, dict) else {}
    if policy.get("success") is not True:
        return []
    if policy.get("decision") != "apply_next_run":
        return []
    expires_at = _parse_policy_datetime(policy.get("expires_at"))
    if expires_at is None:
        return []
    now = datetime.datetime.now(datetime.timezone.utc)
    if expires_at <= now:
        return []
    return _action_list(policy.get("next_actions"))[:MAX_RUNTIME_POLICY_ACTIONS]


def _parse_policy_datetime(value: Any) -> datetime.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


def _action_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _video_budget(args: dict[str, Any], *, wants_video: bool) -> int:
    if not wants_video:
        return 0
    value = _coerce_int(args.get("video_budget"))
    return _clamp_budget(value or 1, minimum=1, maximum=2)


def _clamp_budget(value: int, *, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def _image_tool_aspect_ratio(value: str) -> str:
    normalized = _judge_aspect_ratio(value)
    return {
        "16:9": "landscape",
        "9:16": "portrait",
        "1:1": "square",
    }.get(normalized, value)


def _judge_aspect_ratio(value: str) -> str:
    lowered = str(value or "").strip().lower()
    return {
        "landscape": "16:9",
        "portrait": "9:16",
        "square": "1:1",
    }.get(lowered, lowered or "16:9")


def _video_tool_aspect_ratio(*, requested_aspect_ratio: str, source_ref: str | None) -> str:
    supported = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"]
    if source_ref:
        meta = probe_media_reference(source_ref)
        return select_video_aspect_ratio(
            source_width=meta.width,
            source_height=meta.height,
            requested_aspect_ratio=requested_aspect_ratio,
            supported=supported,
            default=requested_aspect_ratio,
        )
    return select_video_aspect_ratio(
        source_width=None,
        source_height=None,
        requested_aspect_ratio=requested_aspect_ratio,
        supported=supported,
        default=requested_aspect_ratio,
    )


def _is_remote_url(value: str) -> bool:
    return urlparse(value).scheme in {"http", "https"}


registry.register(
    name="visual_package_generate",
    toolset="image_gen",
    schema=VISUAL_PACKAGE_SCHEMA,
    handler=_handle_visual_package_generate,
    check_fn=check_visual_package_requirements,
    requires_env=[],
    is_async=False,
    emoji="🎞️",
)
