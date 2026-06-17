"""Feature-flagged Image2 adaptive mediation helpers.

This module keeps the first version intentionally small: extract a practical
intent sketch, choose a strategy, optionally use a draft model, repair element
locks, and append one JSONL evidence record per attempt.
"""

from __future__ import annotations

import datetime as _datetime
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from tools.registry import registry

logger = logging.getLogger(__name__)

DraftFn = Callable[[str], Optional[str]]


_LOCK_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "黑色洋桔梗": {
        "canonical": "black lisianthus flowers, also known as eustoma",
        "category": "object",
    },
    "洋桔梗": {
        "canonical": "lisianthus flowers, also known as eustoma",
        "category": "object",
    },
    "旗袍": {"canonical": "qipao / cheongsam", "category": "clothing"},
    "黑色絲絨手套": {"canonical": "black velvet opera gloves", "category": "clothing"},
    "緞面晚禮服": {"canonical": "satin evening gown", "category": "clothing"},
    "祖母綠耳環": {"canonical": "emerald earrings", "category": "object"},
    "銀色手拿包": {"canonical": "silver clutch bag", "category": "object"},
    "舊旅館電梯": {"canonical": "vintage hotel elevator", "category": "scene"},
    "黃銅按鈕": {"canonical": "brass buttons", "category": "object"},
    "鏡面牆": {"canonical": "mirrored walls", "category": "scene"},
    "台北雨夜": {"canonical": "rainy night in Taipei", "category": "scene"},
    "午夜台北花市": {"canonical": "midnight Taipei flower market", "category": "scene"},
    "成熟時尚雜誌感": {
        "canonical": "mature high-fashion magazine editorial style",
        "category": "style",
    },
}
_LOCK_TRANSLATIONS: Dict[str, str] = {
    source: str(definition["canonical"]) for source, definition in _LOCK_DEFINITIONS.items()
}

_SENSITIVE_REWRITES = (
    ("not nude", "polished wardrobe"),
    ("no nudity", "polished wardrobe"),
    ("without nudity", "polished wardrobe"),
    ("non-explicit", "editorial-safe"),
    ("nsfw", "bold editorial"),
    ("explicit", "bold editorial"),
    ("sexual", "magnetic editorial"),
    ("erotic", "mature cinematic tension"),
    ("provocative", "bold editorial styling"),
    ("sexy", "refined glamour"),
    ("性感", "refined glamour"),
)

_AVOID_FINAL_TERMS = (
    "nude",
    "nudity",
    "naked",
    "cleavage",
    "underwear",
    "lingerie",
    "nsfw",
    "explicit",
    "sexual",
    "exposure",
)

_HUMAN_MARKERS = (
    "person",
    "portrait",
    "model",
    "woman",
    "man",
    "character",
    "人物",
    "面容",
    "同一人",
    "reference",
)

_STYLE_MARKERS = (
    "fashion",
    "editorial",
    "cinematic",
    "glamour",
    "magazine",
    "時尚",
    "電影",
    "高級",
)

_SENSUAL_MARKERS = (
    "sexy",
    "sensual",
    "alluring",
    "glamour",
    "性感",
)

_OBJECT_SUBSTITUTIONS = {
    "black roses": "black lisianthus flowers, also known as eustoma",
    "dark roses": "black lisianthus flowers, also known as eustoma",
    "black stock flower (Anemone)": "black lisianthus flowers, also known as eustoma",
    "black stock flower": "black lisianthus flowers, also known as eustoma",
    "stock flower": "lisianthus flowers, also known as eustoma",
    "Anemone": "lisianthus flowers, also known as eustoma",
    "matthiola": "lisianthus flowers, also known as eustoma",
}


@dataclass(frozen=True)
class ConstraintLock:
    category: str
    canonical: str
    source: str
    hard: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "canonical": self.canonical,
            "source": self.source,
            "hard": self.hard,
        }


@dataclass(frozen=True)
class Image2Intent:
    subject: str
    scene: str = ""
    style: str = ""
    mood: str = ""
    must_keep: List[str] = field(default_factory=list)
    must_avoid: List[str] = field(default_factory=list)
    constraint_locks: List[ConstraintLock] = field(default_factory=list)
    soft_preferences: List[str] = field(default_factory=list)
    ambiguities: List[str] = field(default_factory=list)
    risk_level: str = "low"
    success_definition: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subject": self.subject,
            "scene": self.scene,
            "style": self.style,
            "mood": self.mood,
            "must_keep": list(self.must_keep),
            "must_avoid": list(self.must_avoid),
            "constraint_locks": [lock.to_dict() for lock in self.constraint_locks],
            "soft_preferences": list(self.soft_preferences),
            "ambiguities": list(self.ambiguities),
            "risk_level": self.risk_level,
            "success_definition": self.success_definition,
        }


@dataclass(frozen=True)
class MediatedImagePrompt:
    user_concept: str
    final_prompt: str
    intent: Image2Intent
    strategy: str
    strategy_reason: str = ""
    draft_model: str = "codex"
    draft_prompt: str = ""
    object_locks_added: List[str] = field(default_factory=list)
    worked_phrases: List[str] = field(default_factory=list)
    avoid_phrases: List[str] = field(default_factory=list)
    qwen_candidate_id: str = ""
    qwen_validation_status: str = "not_applicable"
    qwen_constraint_report: List[Dict[str, Any]] = field(default_factory=list)

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "strategy_reason": self.strategy_reason,
            "draft_model": self.draft_model,
            "intent": self.intent.to_dict(),
            "object_locks_added": list(self.object_locks_added),
            "worked_phrases": list(self.worked_phrases),
            "avoid_phrases": list(self.avoid_phrases),
            "qwen_candidate_id": self.qwen_candidate_id,
            "qwen_validation_status": self.qwen_validation_status,
            "qwen_constraint_report": list(self.qwen_constraint_report),
        }


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on", "enabled"}:
            return True
        if text in {"0", "false", "no", "off", "disabled"}:
            return False
    return default


def _default_memory_path() -> str:
    try:
        from hermes_constants import get_hermes_home

        return str(get_hermes_home() / "hermes_image2_adaptive_memory.jsonl")
    except Exception:
        return str(Path.home() / ".hermes" / "hermes_image2_adaptive_memory.jsonl")


def _default_memory_dir() -> str:
    try:
        from hermes_constants import get_hermes_home

        return str(get_hermes_home() / "image2_mediator_memory")
    except Exception:
        return str(Path.home() / ".hermes" / "image2_mediator_memory")


def read_image2_adaptive_mediator_config() -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
    except Exception as exc:
        logger.debug("Could not read image2 adaptive mediator config: %s", exc)
        return {"enabled": False}

    section = cfg.get("image_gen") if isinstance(cfg, dict) else None
    mediator = section.get("adaptive_mediator") if isinstance(section, dict) else None
    if not isinstance(mediator, dict):
        return {"enabled": False}

    enabled = _coerce_bool(mediator.get("enabled"), default=False)
    if not enabled:
        return {"enabled": False}

    return {
        "enabled": True,
        "memory_path": str(mediator.get("memory_path") or _default_memory_path()),
        "memory_dir": str(mediator.get("memory_dir") or _default_memory_dir()),
        "log_attempts": _coerce_bool(mediator.get("log_attempts"), default=True),
        "exploration_rate": float(mediator.get("exploration_rate", 0.2)),
        "qwen_json_contract": _coerce_bool(mediator.get("qwen_json_contract"), default=True),
    }


def extract_image2_intent(prompt: str) -> Image2Intent:
    text = (prompt or "").strip()
    lowered = text.lower()
    constraint_locks = _extract_constraint_locks(text)
    if any(marker in lowered for marker in ("reference", "identity", "same person")) or any(
        marker in text for marker in ("固定", "面容", "同一人")
    ):
        constraint_locks.insert(0, ConstraintLock(
            category="identity",
            canonical="reference identity",
            source="reference identity",
            hard=True,
        ))
    if "構圖" in text and any(marker in text for marker in ("保留", "固定", "原本")):
        constraint_locks.append(ConstraintLock(
            category="composition",
            canonical="original composition",
            source="構圖",
            hard=True,
        ))
    if "姿勢" in text and any(marker in text for marker in ("保留", "固定", "原本")):
        constraint_locks.append(ConstraintLock(
            category="pose",
            canonical="original pose",
            source="姿勢",
            hard=True,
        ))
    constraint_locks = _dedupe_constraint_locks(constraint_locks)
    must_keep = _dedupe([lock.canonical for lock in constraint_locks if lock.hard])
    must_keep = _dedupe([item for item in must_keep if item])

    soft_preferences: List[str] = []
    if any(marker in lowered or marker in text for marker in _SENSUAL_MARKERS):
        soft_preferences.append("refined glamour")
    if any(marker in lowered or marker in text for marker in _STYLE_MARKERS):
        soft_preferences.append("high-end editorial style")

    risk_level = "low"
    if any(term in lowered for term in ("nude", "nudity", "naked", "explicit", "nsfw")):
        risk_level = "high"
    elif soft_preferences or any(marker in lowered or marker in text for marker in _HUMAN_MARKERS):
        risk_level = "medium"

    return Image2Intent(
        subject=text,
        scene=_infer_scene(text),
        style=_infer_style(text),
        mood=_infer_mood(text),
        must_keep=must_keep,
        must_avoid=_matched_avoid_terms(text),
        constraint_locks=constraint_locks,
        soft_preferences=_dedupe(soft_preferences),
        ambiguities=[],
        risk_level=risk_level,
        success_definition="Closest feasible Image2 result that preserves user intent.",
    )


def mediate_image2_prompt(
    prompt: str,
    *,
    config: Optional[Dict[str, Any]] = None,
    preprocessor_config: Optional[Dict[str, Any]] = None,
    draft_fn: Optional[DraftFn] = None,
) -> MediatedImagePrompt:
    config = config or {"enabled": False}
    intent = extract_image2_intent(prompt)
    if not config.get("enabled"):
        return MediatedImagePrompt(
            user_concept=prompt,
            final_prompt=prompt,
            intent=intent,
            strategy="codex_direct",
            strategy_reason="adaptive mediator disabled; pass through original prompt",
        )

    exact_prompt = _find_exact_success_prompt(config, prompt)
    if exact_prompt:
        return MediatedImagePrompt(
            user_concept=prompt,
            final_prompt=exact_prompt,
            intent=intent,
            strategy="reuse_exact_success",
            strategy_reason="exact repeat matched a previous successful prompt; reuse without exploration",
            draft_model="memory",
            object_locks_added=list(intent.must_keep),
            worked_phrases=_worked_phrases(exact_prompt),
            qwen_validation_status="not_called_exact_repeat",
        )

    strategy_signal = _recent_strategy_signal(config, prompt)
    if strategy_signal:
        strategy = strategy_signal["strategy"]
        strategy_reason = strategy_signal["reason"]
    else:
        strategy = _choose_strategy(intent, preprocessor_config)
        strategy_reason = _explain_strategy(strategy, intent, preprocessor_config)
    draft_prompt = ""
    draft_model = "codex"
    if strategy in {"qwen36_desire_draft", "hybrid_refine"} and draft_fn:
        try:
            draft_request = build_qwen_image_prompt_draft_request(
                prompt,
                intent,
                memory_hints=_build_compact_memory_hints(config, intent),
            )
            draft_prompt = (draft_fn(draft_request) or "").strip()
            if draft_prompt:
                draft_model = str(
                    (preprocessor_config or {}).get("model") or "qwen36-image-prompt"
                )
        except Exception as exc:
            logger.info("Image2 adaptive mediator draft unavailable: %s", exc)
            draft_prompt = ""

    selected = _select_qwen_candidate(
        draft_prompt,
        intent,
        require_json=_coerce_bool(config.get("qwen_json_contract"), default=True),
    )
    final_prompt = _compose_final_prompt(prompt, intent, strategy, selected["positive_prompt"])
    return MediatedImagePrompt(
        user_concept=prompt,
        final_prompt=final_prompt,
        intent=intent,
        strategy=strategy,
        strategy_reason=strategy_reason,
        draft_model=draft_model,
        draft_prompt=draft_prompt,
        object_locks_added=list(intent.must_keep),
        worked_phrases=_worked_phrases(final_prompt),
        avoid_phrases=_dedupe(_matched_avoid_terms(draft_prompt) + selected["avoid_phrases"]),
        qwen_candidate_id=selected["candidate_id"],
        qwen_validation_status=selected["status"],
        qwen_constraint_report=selected["constraint_report"],
    )


def build_qwen_image_prompt_draft_request(
    prompt: str,
    intent: Image2Intent,
    *,
    memory_hints: Optional[Dict[str, Any]] = None,
) -> str:
    hints = memory_hints or {
        "worked_phrases": [],
        "avoid_phrases": [],
        "hard_lessons": [],
        "user_style_preferences": [],
    }
    payload = {
        "schema_version": "qwen_image_prompt_draft_request.v1",
        "role": "You are a local creative draft model. Hermes/Codex is the final authority.",
        "task": (
            "Create 1 Image2-oriented visual draft candidate. Preserve hard locks exactly. "
            "Do not decide safety policy. Do not add reasoning. Return JSON only."
        ),
        "user_concept": prompt,
        "intent": intent.to_dict(),
        "hard_locks": list(intent.must_keep),
        "constraint_locks": [lock.to_dict() for lock in intent.constraint_locks],
        "compact_memory_hints": hints,
        "output_schema": {
            "schema_version": "qwen_image_prompt_draft.v1",
            "positive_prompt_max_chars": 900,
            "max_constraint_report_items": 4,
            "candidates": [{
                "candidate_id": "q1",
                "positive_prompt": "string",
                "style_tags": ["string"],
                "lighting": ["string"],
                "camera": ["string"],
                "invented_elements": ["string"],
                "risky_or_counterproductive_terms": ["string"],
                "constraint_preservation_report": [{
                    "lock_id": "string",
                    "expected": "string",
                    "status": "preserved | violated | missing",
                    "evidence": "string",
                    "found_problem": "string",
                    "action": "keep_candidate | reject_candidate",
                }],
            }],
        },
        "rules": [
            "Return valid JSON only. No markdown fences.",
            "Keep positive_prompt under 900 characters.",
            "At most 4 constraint_preservation_report items",
            "Use choices[0].message.content only; do not include reasoning in visible output.",
            "Do not substitute hard-locked objects, clothing, location, identity, or reference constraints.",
            "If a hard lock cannot be expressed, mark it violated in constraint_preservation_report.",
            "Avoid final wording such as nude, nudity, naked, NSFW, explicit, sexual, no nudity, non-explicit.",
            "Use positive fashion/editorial language instead.",
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def record_image2_mediator_attempt(
    mediated: MediatedImagePrompt,
    *,
    image2_status: str = "unknown",
    feedback_source: str = "agent_inference",
    failure_class: Optional[List[str]] = None,
    scores: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
    notes: str = "",
) -> None:
    config = config or {}
    if config.get("enabled") is False or not _coerce_bool(config.get("log_attempts"), True):
        return
    path = _memory_write_path(config, "attempt")
    if path is None:
        return

    status = image2_status or "unknown"
    merged_scores = {
        "intent_fidelity": 1,
        "aesthetic": 1,
        "sensuality_or_emotional_force": 1,
        "control": 1,
        "safety_feasibility": 0 if status == "blocked" else 1,
        "user_satisfaction": None,
    }
    if scores:
        merged_scores.update(scores)

    payload = {
        "timestamp": _datetime.datetime.now(_datetime.timezone.utc).isoformat(),
        "record_type": "attempt",
        "user_concept": mediated.user_concept,
        "intent": mediated.intent.to_dict(),
        "strategy": mediated.strategy,
        "strategy_reason": mediated.strategy_reason,
        "draft_model": mediated.draft_model,
        "draft_prompt": mediated.draft_prompt,
        "final_prompt": mediated.final_prompt,
        "image2_status": status,
        "feedback_source": feedback_source,
        "failure_class": failure_class or [],
        "scores": merged_scores,
        "worked_phrases": list(mediated.worked_phrases),
        "avoid_phrases": list(mediated.avoid_phrases),
        "object_locks_added": list(mediated.object_locks_added),
        "qwen_candidate_id": mediated.qwen_candidate_id,
        "qwen_validation_status": mediated.qwen_validation_status,
        "qwen_constraint_report": list(mediated.qwen_constraint_report),
        "notes": notes,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    except Exception as exc:
        logger.info("Could not write Image2 adaptive mediator memory: %s", exc)


def record_qwen_call_health(
    *,
    status: str,
    latency_ms: float,
    model: str,
    base_url: str,
    transport: str,
    config: Optional[Dict[str, Any]] = None,
    response_chars: int = 0,
    error_type: str = "",
    error_message: str = "",
    now: Optional[str] = None,
) -> None:
    config = config or {}
    if config.get("enabled") is False or not _coerce_bool(config.get("log_attempts"), True):
        return
    path = _memory_write_path(config, "qwen_call")
    if path is None:
        return

    payload = {
        "timestamp": now or _datetime.datetime.now(_datetime.timezone.utc).isoformat(),
        "record_type": "qwen_call",
        "status": str(status or "unknown").strip() or "unknown",
        "latency_ms": round(float(latency_ms or 0), 2),
        "model": str(model or "").strip(),
        "base_url": str(base_url or "").strip(),
        "transport": str(transport or "").strip(),
        "response_chars": int(response_chars or 0),
        "error_type": str(error_type or "").strip(),
        "error_message": str(error_message or "").strip()[:120],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    except Exception as exc:
        logger.info("Could not write Qwen call health memory: %s", exc)


def summarize_image2_mediator_memory(
    *,
    config: Optional[Dict[str, Any]] = None,
    limit: int = 10,
    now: Optional[str] = None,
) -> Dict[str, Any]:
    config = config or read_image2_adaptive_mediator_config()
    records = _read_memory_records(config)
    attempts = [record for record in records if record.get("record_type", "attempt") == "attempt"]
    feedback = [record for record in records if record.get("record_type") == "user_feedback"]
    qwen_calls = [record for record in records if record.get("record_type") == "qwen_call"]
    status_counts = _count_values(record.get("image2_status") for record in attempts)
    strategy_counts = _count_values(record.get("strategy") for record in attempts)
    failure_class_counts = _count_values(
        failure
        for record in records
        for failure in _as_list(record.get("failure_class"))
    )
    recent = records[-max(1, int(limit or 10)):]

    return {
        "memory_path": str((config or {}).get("memory_path") or ""),
        "record_count": len(records),
        "attempt_count": len(attempts),
        "feedback_count": len(feedback),
        "status_counts": status_counts,
        "strategy_counts": strategy_counts,
        "failure_class_counts": failure_class_counts,
        "sample_confidence": _sample_confidence(len(attempts), status_counts),
        "qwen_health": _summarize_qwen_health(attempts, qwen_calls=qwen_calls, now=now),
        "learning_summary": _summarize_strategy_learning(attempts, feedback),
        "recent": [_public_memory_record(record) for record in recent],
    }


def record_image2_user_feedback(
    feedback_text: str,
    *,
    config: Optional[Dict[str, Any]] = None,
    target_record: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    config = config or read_image2_adaptive_mediator_config()
    if config.get("enabled") is False or not _coerce_bool(config.get("log_attempts"), True):
        return {
            "recorded": False,
            "error": "Image2 adaptive mediator logging is disabled.",
        }
    path = _memory_write_path(config, "user_feedback")
    if path is None:
        return {
            "recorded": False,
            "error": "Image2 adaptive mediator memory path is not configured.",
        }

    records = _read_memory_records(config)
    target = target_record or _latest_attempt_record(records)
    mapped = _map_user_feedback(feedback_text)
    payload = {
        "timestamp": _datetime.datetime.now(_datetime.timezone.utc).isoformat(),
        "record_type": "user_feedback",
        "user_concept": str((target or {}).get("user_concept") or ""),
        "intent": (target or {}).get("intent") or {},
        "strategy": str((target or {}).get("strategy") or mapped["next_strategy"]),
        "draft_model": str((target or {}).get("draft_model") or ""),
        "draft_prompt": str((target or {}).get("draft_prompt") or ""),
        "final_prompt": str((target or {}).get("final_prompt") or ""),
        "image2_status": "feedback",
        "feedback_source": "user",
        "feedback_text": str(feedback_text or "").strip(),
        "target_timestamp": (target or {}).get("timestamp"),
        "failure_class": mapped["failure_class"],
        "scores": mapped["scores"],
        "worked_phrases": mapped["worked_phrases"],
        "avoid_phrases": mapped["avoid_phrases"],
        "object_locks_added": (target or {}).get("object_locks_added") or [],
        "next_strategy": mapped["next_strategy"],
        "notes": mapped["notes"],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    except Exception as exc:
        logger.info("Could not write Image2 adaptive mediator feedback: %s", exc)
        return {
            "recorded": False,
            "error": str(exc),
            **mapped,
        }
    return {
        "recorded": True,
        "target_timestamp": payload["target_timestamp"],
        **mapped,
    }


def _choose_strategy(
    intent: Image2Intent,
    preprocessor_config: Optional[Dict[str, Any]],
) -> str:
    has_qwen = bool((preprocessor_config or {}).get("enabled"))
    if intent.risk_level == "high":
        return "safe_reframe"
    if any(item != "reference identity" for item in intent.must_keep):
        return "hybrid_refine" if has_qwen else "element_lock"
    if "refined glamour" in intent.soft_preferences:
        return "hybrid_refine" if has_qwen else "codex_direct"
    if has_qwen and any(marker in intent.subject.lower() for marker in _HUMAN_MARKERS):
        return "hybrid_refine"
    return "codex_direct"


def _recent_strategy_signal(config: Dict[str, Any], prompt: str) -> Optional[Dict[str, str]]:
    normalized = str(prompt or "").strip()
    for record in reversed(_read_memory_records(config)):
        record_type = record.get("record_type", "attempt")
        if record_type not in {"attempt", "user_feedback"}:
            continue
        concept = str(record.get("user_concept") or "").strip()
        if concept and normalized and concept != normalized:
            continue
        failures = {item.lower() for item in _as_list(record.get("failure_class"))}
        status = str(record.get("image2_status") or "").strip().lower()
        if status == "blocked" or "blocked" in failures:
            return {
                "strategy": "safe_reframe",
                "reason": "previous Image2 attempt was blocked; route to safe_reframe",
            }
        if "object_drift" in failures:
            return {
                "strategy": "element_lock",
                "reason": "recent feedback reported object_drift; route to element_lock repair",
            }
        if "too_explicit_or_risky" in failures:
            return {
                "strategy": "safe_reframe",
                "reason": "recent feedback found the result too explicit or risky; route to safe_reframe",
            }
        if "too_tame" in failures or "not_sexy_enough" in failures:
            return {
                "strategy": "hybrid_refine",
                "reason": "recent feedback was too_tame; increase mature editorial intensity",
            }
    return None


def _explain_strategy(
    strategy: str,
    intent: Image2Intent,
    preprocessor_config: Optional[Dict[str, Any]],
) -> str:
    has_qwen = bool((preprocessor_config or {}).get("enabled"))
    hard_lock_count = len([lock for lock in intent.constraint_locks if lock.hard])
    if strategy == "safe_reframe":
        return "high-risk prompt terms detected; route to safe_reframe"
    if strategy == "element_lock":
        return "hard locks present and qwen unavailable; route to element_lock"
    if strategy == "hybrid_refine" and hard_lock_count:
        return f"{hard_lock_count} hard locks present; use qwen draft with strict Hermes validation"
    if strategy == "hybrid_refine" and has_qwen:
        return "style or human-subject prompt can benefit from qwen creative drafting"
    if strategy == "codex_direct":
        return "simple or tightly constrained prompt; use Codex/Hermes direct compiler"
    return f"selected {strategy}"


def _select_qwen_candidate(
    draft_prompt: str,
    intent: Image2Intent,
    *,
    require_json: bool = True,
) -> Dict[str, Any]:
    if not draft_prompt:
        return _empty_qwen_selection("unavailable")
    payload = _parse_qwen_json_payload(draft_prompt)
    if payload is None:
        if require_json:
            return _empty_qwen_selection("malformed")
        return {
            "candidate_id": "",
            "positive_prompt": draft_prompt,
            "status": "plain_text",
            "constraint_report": [],
            "avoid_phrases": [],
        }

    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        if isinstance(payload.get("positive_prompt"), str):
            candidates = [payload]
        else:
            return _empty_qwen_selection("malformed")
    rejected_reports: List[Dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        validation = _validate_qwen_candidate(candidate, intent)
        if validation["accepted"]:
            return {
                "candidate_id": str(candidate.get("candidate_id") or ""),
                "positive_prompt": str(candidate.get("positive_prompt") or "").strip(),
                "status": "accepted",
                "constraint_report": validation["constraint_report"],
                "avoid_phrases": validation["avoid_phrases"],
            }
        rejected_reports.extend(validation["constraint_report"])
    result = _empty_qwen_selection("rejected")
    result["constraint_report"] = rejected_reports
    result["avoid_phrases"] = _dedupe(
        str(item.get("found_problem") or "")
        for item in rejected_reports
        if str(item.get("found_problem") or "").strip()
    )
    return result


def _parse_qwen_json_payload(raw: str) -> Optional[Dict[str, Any]]:
    text = str(raw or "").strip()
    if not text:
        return None

    candidates = [text]
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate.startswith("{"):
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _validate_qwen_candidate(candidate: Dict[str, Any], intent: Image2Intent) -> Dict[str, Any]:
    positive_prompt = str(candidate.get("positive_prompt") or "").strip()
    report = _as_constraint_report(candidate.get("constraint_preservation_report"))
    avoid_phrases: List[str] = []
    accepted = bool(positive_prompt)

    for item in report:
        status = str(item.get("status") or "").strip().lower()
        action = str(item.get("action") or "").strip().lower()
        if status not in {"preserved", "ok", "present"} or action == "reject_candidate":
            accepted = False
            problem = str(item.get("found_problem") or item.get("expected") or "").strip()
            if problem:
                avoid_phrases.append(problem)

    invented = _as_list(candidate.get("invented_elements"))
    for item in invented:
        if _conflicts_with_locks(item, intent.must_keep):
            accepted = False
            report.append({
                "lock_id": "invented_element",
                "expected": ", ".join(intent.must_keep),
                "status": "violated",
                "found_problem": item,
                "action": "reject_candidate",
            })
            avoid_phrases.append(item)

    for violation in _detect_typed_lock_violations(
        " ".join([positive_prompt, *invented]),
        intent.constraint_locks,
    ):
        accepted = False
        report.append(violation)
        avoid_phrases.append(str(violation.get("found_problem") or ""))

    if _conflicts_with_locks(positive_prompt, intent.must_keep):
        accepted = False
        report.append({
            "lock_id": "positive_prompt",
            "expected": ", ".join(intent.must_keep),
            "status": "violated",
            "found_problem": "candidate prompt conflicts with locked object",
            "action": "reject_candidate",
        })
        avoid_phrases.append("candidate prompt conflicts with locked object")

    return {
        "accepted": accepted,
        "constraint_report": report,
        "avoid_phrases": _dedupe(avoid_phrases),
    }


def _empty_qwen_selection(status: str) -> Dict[str, Any]:
    return {
        "candidate_id": "",
        "positive_prompt": "",
        "status": status,
        "constraint_report": [],
        "avoid_phrases": [],
    }


def _find_exact_success_prompt(config: Dict[str, Any], prompt: str) -> str:
    normalized = str(prompt or "").strip()
    if not normalized:
        return ""
    for record in reversed(_read_memory_records(config)):
        if record.get("record_type", "attempt") != "attempt":
            continue
        if str(record.get("image2_status") or "").strip().lower() != "success":
            continue
        if str(record.get("user_concept") or "").strip() != normalized:
            continue
        final_prompt = str(record.get("final_prompt") or "").strip()
        if final_prompt:
            return final_prompt
    return ""


def _build_compact_memory_hints(
    config: Dict[str, Any],
    intent: Image2Intent,
    *,
    limit: int = 40,
) -> Dict[str, Any]:
    worked: List[str] = []
    avoid: List[str] = []
    hard_lessons: List[str] = []
    style_preferences: List[str] = []
    target_signature = _intent_bucket_signature(intent)
    source_record_count = 0

    for record in reversed(_read_memory_records(config)[-limit:]):
        if record.get("record_type", "attempt") not in {"attempt", "user_feedback"}:
            continue
        if not _record_matches_bucket(record, target_signature):
            continue

        source_record_count += 1
        worked.extend(_as_list(record.get("worked_phrases")))
        avoid.extend(_as_list(record.get("avoid_phrases")))

        failures = {item.lower() for item in _as_list(record.get("failure_class"))}
        if "object_drift" in failures:
            hard_lessons.extend(
                f"Do not substitute {lock.canonical}."
                for lock in intent.constraint_locks
                if lock.category == "object"
            )
        if "too_tame" in failures or "not_sexy_enough" in failures:
            style_preferences.append(
                "prefers mature, bold, fashion-editorial mood over conservative styling"
            )
        if "too_explicit_or_risky" in failures:
            avoid.append("overly explicit framing")

    return {
        "target_bucket": _bucket_label(target_signature),
        "source_record_count": source_record_count,
        "worked_phrases": _limit_list(_dedupe(worked), 6),
        "avoid_phrases": _limit_list(_dedupe(avoid), 8),
        "hard_lessons": _limit_list(_dedupe(hard_lessons), 6),
        "user_style_preferences": _limit_list(_dedupe(style_preferences), 4),
    }


def _summarize_strategy_learning(
    attempts: List[Dict[str, Any]],
    feedback: List[Dict[str, Any]],
) -> Dict[str, Any]:
    buckets: Dict[str, Dict[str, Any]] = {}

    for record in attempts:
        label = _record_bucket_label(record)
        bucket = _ensure_learning_bucket(buckets, label)
        bucket["attempt_count"] += 1
        status = str(record.get("image2_status") or "unknown").strip() or "unknown"
        _increment_count(bucket["status_counts"], status)
        for failure in _as_list(record.get("failure_class")):
            _increment_count(bucket["failure_class_counts"], failure)

        strategy = str(record.get("strategy") or "unknown").strip() or "unknown"
        strategy_summary = bucket["strategies"].setdefault(strategy, {
            "attempt_count": 0,
            "success_count": 0,
            "blocked_count": 0,
            "status_counts": {},
            "failure_class_counts": {},
            "success_rate": 0.0,
        })
        strategy_summary["attempt_count"] += 1
        _increment_count(strategy_summary["status_counts"], status)
        if status == "success":
            strategy_summary["success_count"] += 1
        if status == "blocked":
            strategy_summary["blocked_count"] += 1
        for failure in _as_list(record.get("failure_class")):
            _increment_count(strategy_summary["failure_class_counts"], failure)

    for record in feedback:
        label = _record_bucket_label(record)
        bucket = _ensure_learning_bucket(buckets, label)
        bucket["user_feedback_count"] += 1
        for failure in _as_list(record.get("failure_class")):
            _increment_count(bucket["user_feedback_failure_counts"], failure)

    strategy_buckets = []
    for bucket in buckets.values():
        attempt_count = int(bucket["attempt_count"])
        bucket["status_counts"] = _sorted_counts(bucket["status_counts"])
        bucket["failure_class_counts"] = _sorted_counts(bucket["failure_class_counts"])
        bucket["user_feedback_failure_counts"] = _sorted_counts(
            bucket["user_feedback_failure_counts"]
        )
        bucket["sample_policy"] = _learning_sample_policy(attempt_count)
        bucket["feedback_weight"] = (
            "user_feedback_strongest_signal"
            if int(bucket["user_feedback_count"]) > 0
            else "automatic_evidence_only"
        )
        for strategy_summary in bucket["strategies"].values():
            strategy_attempts = int(strategy_summary["attempt_count"])
            strategy_summary["status_counts"] = _sorted_counts(strategy_summary["status_counts"])
            strategy_summary["failure_class_counts"] = _sorted_counts(
                strategy_summary["failure_class_counts"]
            )
            strategy_summary["success_rate"] = _round_rate(
                int(strategy_summary["success_count"]),
                strategy_attempts,
            )
        bucket["strategies"] = dict(sorted(bucket["strategies"].items()))
        strategy_buckets.append(bucket)

    strategy_buckets.sort(key=lambda item: (-int(item["attempt_count"]), str(item["bucket"])))
    return {
        "sample_policy": _learning_sample_policy(len(attempts)),
        "feedback_weight": (
            "user_feedback_strongest_signal" if feedback else "automatic_evidence_only"
        ),
        "strategy_buckets": strategy_buckets,
    }


def _ensure_learning_bucket(
    buckets: Dict[str, Dict[str, Any]],
    label: str,
) -> Dict[str, Any]:
    return buckets.setdefault(label, {
        "bucket": label,
        "attempt_count": 0,
        "user_feedback_count": 0,
        "status_counts": {},
        "failure_class_counts": {},
        "user_feedback_failure_counts": {},
        "strategies": {},
        "sample_policy": "rules_only",
        "feedback_weight": "automatic_evidence_only",
    })


def _as_constraint_report(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _conflicts_with_locks(text: str, must_keep: List[str]) -> bool:
    lowered = str(text or "").lower()
    lock_text = " ".join(must_keep).lower()
    if "lisianthus" in lock_text:
        conflict_terms = (
            "black rose",
            "black roses",
            "dark rose",
            "dark roses",
            "anemone",
            "stock flower",
            "matthiola",
            "orchid",
            "black lily",
            "black lilies",
        )
        return any(term in lowered for term in conflict_terms)
    return False


def _detect_typed_lock_violations(
    text: str,
    locks: List[ConstraintLock],
) -> List[Dict[str, Any]]:
    lowered = str(text or "").lower()
    violations: List[Dict[str, Any]] = []
    for lock in locks:
        canonical = lock.canonical.lower()
        problem = ""
        if lock.category == "identity" and _contains_any(
            lowered,
            ("generic model", "different face", "different person", "new face", "unrelated model"),
        ):
            problem = "reference identity weakened or replaced"
        elif lock.category == "clothing":
            if "satin evening gown" in canonical and _contains_any(
                lowered,
                ("leather jacket", "biker jacket", "denim jacket", "business suit", "bodysuit"),
            ):
                problem = "clothing lock changed or contradicted"
            elif "qipao" in canonical and _contains_any(
                lowered,
                ("evening gown", "leather jacket", "business suit", "bodysuit"),
            ):
                problem = "clothing lock changed or contradicted"
        elif lock.category == "scene":
            if "taipei" in canonical and _contains_any(
                lowered,
                ("paris", "ballroom", "new york", "tokyo", "seoul", "london"),
            ):
                problem = "scene lock changed or contradicted"
            elif "hotel elevator" in canonical and _contains_any(
                lowered,
                ("ballroom", "street", "bedroom", "studio"),
            ):
                problem = "scene lock changed or contradicted"
        elif lock.category == "object" and "lisianthus" in canonical:
            if _contains_any(
                lowered,
                (
                    "black rose",
                    "black roses",
                    "dark rose",
                    "anemone",
                    "stock flower",
                    "matthiola",
                    "orchid",
                    "black lily",
                    "black lilies",
                ),
            ):
                problem = "object lock changed or contradicted"

        if problem:
            violations.append({
                "lock_id": f"{lock.category}:{lock.source}",
                "expected": lock.canonical,
                "status": "violated",
                "found_problem": problem,
                "action": "reject_candidate",
            })
    return _dedupe_constraint_reports(violations)


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    return any(needle in text for needle in needles)


def _dedupe_constraint_reports(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    result: List[Dict[str, Any]] = []
    for item in items:
        key = (
            str(item.get("lock_id") or ""),
            str(item.get("found_problem") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


_SPLIT_MEMORY_FILES = {
    "attempt": "attempts.jsonl",
    "qwen_call": "qwen_calls.jsonl",
    "user_feedback": "user_feedback.jsonl",
    "strategy_summary": "strategy_summaries.jsonl",
}


def _memory_write_path(config: Dict[str, Any], record_type: str) -> Optional[Path]:
    memory_dir = str((config or {}).get("memory_dir") or "").strip()
    if memory_dir:
        filename = _SPLIT_MEMORY_FILES.get(record_type)
        if filename:
            return Path(memory_dir).expanduser() / filename
    memory_path = str((config or {}).get("memory_path") or "").strip()
    return Path(memory_path).expanduser() if memory_path else None


def _memory_read_paths(config: Dict[str, Any]) -> List[Path]:
    paths: List[Path] = []
    memory_path = str((config or {}).get("memory_path") or "").strip()
    if memory_path:
        paths.append(Path(memory_path).expanduser())

    memory_dir = str((config or {}).get("memory_dir") or "").strip()
    if memory_dir:
        root = Path(memory_dir).expanduser()
        paths.extend(root / filename for filename in _SPLIT_MEMORY_FILES.values())

    seen: set[str] = set()
    unique: List[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _read_memory_records(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for path in _memory_read_paths(config):
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    records.append(payload)
        except OSError as exc:
            logger.info("Could not read Image2 adaptive mediator memory: %s", exc)
    return sorted(records, key=_record_sort_key)


def _record_sort_key(record: Dict[str, Any]) -> tuple[_datetime.datetime, str]:
    timestamp = _parse_timestamp(record.get("timestamp"))
    if timestamp is None:
        timestamp = _datetime.datetime.min.replace(tzinfo=_datetime.timezone.utc)
    return timestamp, str(record.get("record_type") or "")


def _latest_attempt_record(records: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for record in reversed(records):
        if record.get("record_type", "attempt") == "attempt":
            return record
    return None


def _map_user_feedback(feedback_text: str) -> Dict[str, Any]:
    text = str(feedback_text or "").strip()
    lowered = text.lower()
    failures: List[str] = []
    worked: List[str] = []
    avoid: List[str] = []
    satisfaction = 3
    next_strategy = "hybrid_refine"
    negative_style_feedback = (
        any(token in lowered for token in ("ugly", "bad style", "not my style", "generic"))
        or any(
            token in text
            for token in (
                "好醜",
                "醜",
                "不好看",
                "不喜歡",
                "不是我喜歡",
                "不是我的風格",
                "不對味",
                "很爛",
                "爛",
                "跑偏",
            )
        )
    )
    visual_arsenal_miss = any(
        token in lowered for token in ("visual arsenal", "arsenal")
    ) or "武器庫" in text
    partial_positive_feedback = any(
        token in text
        for token in ("過關", "不錯", "還可以", "算可以", "可用", "能用")
    )
    persona_drift_feedback = (
        "persona drift" in lowered
        or "design drift" in lowered
        or "人設" in text and any(token in text for token in ("差異", "不對", "跑掉", "不像"))
    )
    beauty_insufficient_feedback = any(
        token in lowered for token in ("not pretty enough", "not beautiful enough")
    ) or any(token in text for token in ("不夠漂亮", "不是美女", "臉太醜"))
    glamour_insufficient_feedback = (
        any(token in lowered for token in ("not sexy enough", "not glamorous enough"))
        or "不夠性感" in text
        or ("不夠" in text and "性感" in text)
    )

    if negative_style_feedback:
        failures.append("style_mismatch")
        avoid.append("generic cosplay style")
        avoid.append("off-preference visual direction")
        next_strategy = "post_failure_repair"
        satisfaction = 1
    if visual_arsenal_miss:
        failures.append("visual_arsenal_miss")
        avoid.append("style outside visual arsenal")
        next_strategy = "post_failure_repair"
        satisfaction = 1
    if partial_positive_feedback:
        failures.append("partial_success")
        worked.append("preserve accepted variant direction")
        satisfaction = max(satisfaction, 3)
    if persona_drift_feedback:
        failures.append("persona_drift")
        avoid.append("persona/design drift")
        next_strategy = "post_failure_repair"
        satisfaction = min(satisfaction, 3)
    if beauty_insufficient_feedback:
        failures.append("not_beautiful_enough")
        avoid.append("unattractive face direction")
        next_strategy = "post_failure_repair"
        satisfaction = min(satisfaction, 3)

    if "更接近" in text or "接近" in text:
        satisfaction = max(satisfaction, 4)
        worked.append("preserve current direction")
    positive_feedback = any(token in lowered for token in ("excellent", "great", "good")) or any(
        token in text for token in ("很好", "很棒", "滿意", "可以", "好看", "漂亮", "成功")
    )
    if positive_feedback and not any((
        negative_style_feedback,
        persona_drift_feedback,
        beauty_insufficient_feedback,
    )):
        satisfaction = max(satisfaction, 5)
        worked.append("repeat current strategy")
    if "太保守" in text:
        failures.append("too_tame")
        worked.append("increase sensuality through gaze")
        next_strategy = "hybrid_refine"
        satisfaction = min(satisfaction, 3)
    if glamour_insufficient_feedback:
        failures.append("not_sexy_enough")
        worked.append("increase sensuality through gaze")
        worked.append("stronger fashion editorial silhouette")
        if not (persona_drift_feedback or beauty_insufficient_feedback):
            next_strategy = "hybrid_refine"
        satisfaction = min(satisfaction, 3)
    if "太露骨" in text or "太超過" in text:
        failures.append("too_explicit_or_risky")
        avoid.append("overly explicit framing")
        next_strategy = "safe_reframe"
        satisfaction = min(satisfaction, 2)
    if "跑題" in text or "不相關" in text or "不像" in text:
        failures.append("wrong_subject")
        avoid.append("generic subject substitution")
        next_strategy = "post_failure_repair"
        satisfaction = min(satisfaction, 2)
    if "物件漂移" in text or "物件錯" in text or "花錯" in text:
        failures.append("object_drift")
        worked.append("stricter element lock")
        next_strategy = "element_lock"
        satisfaction = min(satisfaction, 2)
    if "構圖差" in text or "構圖" in text:
        failures.append("bad_composition")
        next_strategy = "post_failure_repair"
        satisfaction = min(satisfaction, 2)
    if "保留這版" in text or "保留" in text:
        failures.append("partial_success")
        worked.append("preserve current direction")
        satisfaction = max(satisfaction, 3)

    if not failures and satisfaction >= 5:
        failures.append("excellent")
    failures = _dedupe(failures)

    return {
        "failure_class": failures,
        "scores": {
            "intent_fidelity": satisfaction,
            "aesthetic": satisfaction,
            "sensuality_or_emotional_force": satisfaction,
            "control": satisfaction,
            "safety_feasibility": 1,
            "user_satisfaction": satisfaction,
        },
        "worked_phrases": _dedupe(worked),
        "avoid_phrases": _dedupe(avoid),
        "next_strategy": next_strategy,
        "notes": text,
    }


def _intent_bucket_signature(intent: Image2Intent) -> Dict[str, List[str]]:
    return _bucket_signature_from_parts(
        locks=[lock.to_dict() for lock in intent.constraint_locks],
        style=intent.style,
        risk_level=intent.risk_level,
        soft_preferences=intent.soft_preferences,
    )


def _record_bucket_signature(record: Dict[str, Any]) -> Dict[str, List[str]]:
    intent = record.get("intent")
    if isinstance(intent, dict):
        locks = _as_lock_dicts(intent.get("constraint_locks"))
        style = str(intent.get("style") or "")
        risk_level = str(intent.get("risk_level") or "")
        soft_preferences = _as_list(intent.get("soft_preferences"))
    else:
        locks = []
        style = ""
        risk_level = ""
        soft_preferences = []

    for item in _as_list(record.get("object_locks_added")):
        locks.append({
            "category": _infer_bucket_category(item),
            "canonical": item,
        })

    if not locks and not style and not risk_level:
        concept = str(record.get("user_concept") or "").strip()
        if concept:
            return _intent_bucket_signature(extract_image2_intent(concept))

    return _bucket_signature_from_parts(
        locks=locks,
        style=style,
        risk_level=risk_level,
        soft_preferences=soft_preferences,
    )


def _bucket_signature_from_parts(
    *,
    locks: List[Dict[str, Any]],
    style: str,
    risk_level: str,
    soft_preferences: List[str],
) -> Dict[str, List[str]]:
    signature: Dict[str, List[str]] = {
        "identity": [],
        "object": [],
        "clothing": [],
        "scene": [],
        "style": [],
        "risk": [],
    }
    for lock in locks:
        category = str(lock.get("category") or "").strip().lower()
        canonical = str(lock.get("canonical") or "").strip()
        if category not in signature or not canonical:
            continue
        signature[category].append(canonical)
    if style:
        signature["style"].append(style)
    signature["style"].extend(soft_preferences)
    if risk_level:
        signature["risk"].append(risk_level)
    return {key: _dedupe(values) for key, values in signature.items()}


def _record_matches_bucket(record: Dict[str, Any], target_signature: Dict[str, List[str]]) -> bool:
    record_signature = _record_bucket_signature(record)
    for category in ("identity", "object", "clothing", "scene"):
        target_values = target_signature.get(category, [])
        if target_values:
            return _values_overlap(target_values, record_signature.get(category, []))
    style_values = target_signature.get("style", [])
    if style_values:
        return _values_overlap(style_values, record_signature.get("style", []))
    return True


def _record_bucket_label(record: Dict[str, Any]) -> str:
    return _bucket_label(_record_bucket_signature(record))


def _bucket_label(signature: Dict[str, List[str]]) -> str:
    parts: List[str] = []
    for category in ("identity", "object", "clothing", "scene", "style", "risk"):
        values = _dedupe(signature.get(category, []))
        if values:
            parts.append(f"{category}:{' + '.join(values)}")
    return "|".join(parts) if parts else "general"


def _values_overlap(left: List[str], right: List[str]) -> bool:
    left_values = [_normalize_bucket_value(value) for value in left]
    right_values = [_normalize_bucket_value(value) for value in right]
    for left_value in left_values:
        for right_value in right_values:
            if not left_value or not right_value:
                continue
            if left_value == right_value or left_value in right_value or right_value in left_value:
                return True
    return False


def _normalize_bucket_value(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _as_lock_dicts(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _infer_bucket_category(value: str) -> str:
    lowered = str(value or "").lower()
    if "identity" in lowered:
        return "identity"
    if any(token in lowered for token in ("qipao", "cheongsam", "gown", "gloves", "wardrobe")):
        return "clothing"
    if any(token in lowered for token in ("taipei", "night", "hotel", "elevator", "market")):
        return "scene"
    if any(token in lowered for token in ("editorial", "style", "glamour", "fashion")):
        return "style"
    return "object"


def _learning_sample_policy(attempt_count: int) -> str:
    if attempt_count >= 300:
        return "bandit_candidate"
    if attempt_count >= 100:
        return "strong_reference"
    if attempt_count >= 30:
        return "moderate_reference"
    if attempt_count >= 10:
        return "weak_reference"
    return "rules_only"


def _increment_count(counts: Dict[str, int], value: str) -> None:
    key = str(value or "").strip()
    if not key:
        return
    counts[key] = counts.get(key, 0) + 1


def _sorted_counts(counts: Dict[str, int]) -> Dict[str, int]:
    return dict(sorted(counts.items()))


def _count_values(values: Any) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for value in values:
        _increment_count(counts, value)
    return _sorted_counts(counts)



def _summarize_qwen_health(
    attempts: List[Dict[str, Any]],
    *,
    qwen_calls: Optional[List[Dict[str, Any]]] = None,
    now: Optional[str] = None,
) -> Dict[str, Any]:
    qwen_calls = qwen_calls or []
    if qwen_calls:
        return _summarize_qwen_call_health(qwen_calls, now=now)

    observed = [
        record
        for record in attempts
        if str(record.get("qwen_validation_status") or "").strip()
        not in {"", "not_applicable", "not_called_exact_repeat"}
    ]
    status_counts = _count_values(record.get("qwen_validation_status") for record in observed)
    total = len(observed)
    fallback_statuses = {"unavailable", "malformed", "rejected"}
    fallback_count = sum(
        1
        for record in observed
        if str(record.get("qwen_validation_status") or "").strip() in fallback_statuses
    )
    malformed_count = int(status_counts.get("malformed", 0))
    violation_count = 0
    for record in observed:
        report = _as_constraint_report(record.get("qwen_constraint_report"))
        if any(str(item.get("status") or "").strip().lower() == "violated" for item in report):
            violation_count += 1

    if not observed:
        health_status = "unknown"
    elif fallback_count:
        health_status = "degraded"
    else:
        health_status = "healthy"

    return {
        "status": health_status,
        "window_hours": 24,
        "call_count_24h": 0,
        "status_counts": status_counts,
        "status_counts_24h": status_counts,
        "last_success_at": _latest_qwen_timestamp(observed, {"accepted", "plain_text"}),
        "last_failure_at": _latest_qwen_timestamp(observed, fallback_statuses),
        "fallback_rate": _round_rate(fallback_count, total),
        "fallback_rate_24h": _round_rate(fallback_count, total),
        "malformed_json_rate": _round_rate(malformed_count, total),
        "malformed_json_rate_24h": _round_rate(malformed_count, total),
        "timeout_rate_24h": 0.0,
        "constraint_violation_rate": _round_rate(violation_count, total),
        "p50_latency_ms": None,
        "p95_latency_ms": None,
    }


def _summarize_qwen_call_health(
    qwen_calls: List[Dict[str, Any]],
    *,
    now: Optional[str] = None,
) -> Dict[str, Any]:
    current_time = _parse_timestamp(now) or _latest_record_time(qwen_calls)
    if current_time is None:
        windowed = qwen_calls
    else:
        start = current_time - _datetime.timedelta(hours=24)
        windowed = [
            record
            for record in qwen_calls
            if (timestamp := _parse_timestamp(record.get("timestamp"))) is not None
            and start <= timestamp <= current_time
        ]

    status_counts = _count_values(record.get("status") for record in windowed)
    total = len(windowed)
    fallback_statuses = {"unavailable", "malformed", "rejected", "offline", "timeout", "error"}
    fallback_count = sum(
        1 for record in windowed if str(record.get("status") or "").strip() in fallback_statuses
    )
    malformed_count = sum(
        1
        for record in windowed
        if str(record.get("status") or "").strip() == "malformed"
        or str(record.get("error_type") or "").strip() == "malformed_json"
    )
    timeout_count = sum(
        1
        for record in windowed
        if str(record.get("status") or "").strip() == "timeout"
        or str(record.get("error_type") or "").strip() == "timeout"
    )
    latencies = sorted(
        float(record.get("latency_ms"))
        for record in windowed
        if isinstance(record.get("latency_ms"), (int, float))
    )

    if not windowed:
        health_status = "unknown"
    elif fallback_count:
        health_status = "degraded"
    else:
        health_status = "healthy"

    return {
        "status": health_status,
        "window_hours": 24,
        "call_count_24h": total,
        "status_counts": status_counts,
        "status_counts_24h": status_counts,
        "last_success_at": _latest_qwen_call_timestamp(windowed, {"accepted", "plain_text"}),
        "last_failure_at": _latest_qwen_call_timestamp(windowed, fallback_statuses),
        "fallback_rate": _round_rate(fallback_count, total),
        "fallback_rate_24h": _round_rate(fallback_count, total),
        "malformed_json_rate": _round_rate(malformed_count, total),
        "malformed_json_rate_24h": _round_rate(malformed_count, total),
        "timeout_rate_24h": _round_rate(timeout_count, total),
        "constraint_violation_rate": _round_rate(int(status_counts.get("rejected", 0)), total),
        "p50_latency_ms": _nearest_rank(latencies, 0.50),
        "p95_latency_ms": _nearest_rank(latencies, 0.95),
    }


def _latest_qwen_timestamp(records: List[Dict[str, Any]], statuses: set[str]) -> Optional[str]:
    for record in reversed(records):
        status = str(record.get("qwen_validation_status") or "").strip()
        if status in statuses:
            return str(record.get("timestamp") or "")
    return None


def _latest_qwen_call_timestamp(records: List[Dict[str, Any]], statuses: set[str]) -> Optional[str]:
    for record in reversed(records):
        status = str(record.get("status") or "").strip()
        if status in statuses:
            return str(record.get("timestamp") or "")
    return None


def _parse_timestamp(value: Any) -> Optional[_datetime.datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = _datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=_datetime.timezone.utc)
    return parsed


def _latest_record_time(records: List[Dict[str, Any]]) -> Optional[_datetime.datetime]:
    timestamps = [
        parsed
        for record in records
        if (parsed := _parse_timestamp(record.get("timestamp"))) is not None
    ]
    return max(timestamps) if timestamps else None


def _nearest_rank(values: List[float], percentile: float) -> Optional[float]:
    if not values:
        return None
    index = max(0, min(len(values) - 1, int(_ceil(len(values) * percentile) - 1)))
    value = values[index]
    return int(value) if value.is_integer() else round(value, 2)


def _ceil(value: float) -> int:
    as_int = int(value)
    return as_int if value == as_int else as_int + 1


def _round_rate(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count / total, 4)


def _as_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if value is None or value == "":
        return []
    return [str(value)]


def _limit_list(items: List[str], limit: int) -> List[str]:
    return items[: max(0, int(limit))]


def _sample_confidence(attempt_count: int, status_counts: Dict[str, int]) -> str:
    if attempt_count < 5:
        return "low"
    if attempt_count < 20:
        return "medium"
    success_count = int(status_counts.get("success", 0))
    return "high" if success_count >= max(5, attempt_count // 2) else "medium"


def _public_memory_record(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "timestamp": record.get("timestamp"),
        "record_type": record.get("record_type", "attempt"),
        "user_concept": record.get("user_concept"),
        "strategy": record.get("strategy"),
        "strategy_reason": record.get("strategy_reason"),
        "image2_status": record.get("image2_status"),
        "qwen_validation_status": record.get("qwen_validation_status"),
        "failure_class": _as_list(record.get("failure_class")),
        "feedback_text": record.get("feedback_text"),
        "target_timestamp": record.get("target_timestamp"),
    }


def _compose_final_prompt(
    prompt: str,
    intent: Image2Intent,
    strategy: str,
    draft_prompt: str,
) -> str:
    base = _sanitize_prompt(draft_prompt or prompt)
    base = _repair_object_substitutions(base, intent.must_keep)
    locks = list(intent.must_keep)

    composition_locks = [
        lock.canonical for lock in intent.constraint_locks if lock.category in {"composition", "pose"}
    ]
    style_bits = _dedupe([
        item
        for item in [
            intent.style,
            intent.mood,
            *intent.soft_preferences,
            "high-end cinematic editorial image",
        ]
        if item
    ])
    parts = [
        f"Hard locks: {', '.join(locks) if locks else 'preserve the user-specified subject exactly'}.",
        f"Subject: {_sanitize_prompt(prompt)}. Draft visual direction: {base}.",
        (
            "Composition: "
            + (
                ", ".join(composition_locks)
                if composition_locks
                else "controlled composition, confident posture, expressive gaze"
            )
            + "."
        ),
        f"Style and mood: {', '.join(style_bits)}.",
        "Lighting and camera: premium lighting, controlled highlights, polished real-camera editorial framing.",
        "Provider-safe framing: tasteful adult editorial styling, polished wardrobe, provider-safe editorial boundaries, focus on fashion composition, lighting, fabric, color, posture, and form.",
    ]
    if intent.scene:
        parts.append(f"Setting anchor: {intent.scene}.")
    parts.append(
        "Preserve all hard locks exactly; do not substitute locked objects, location, clothing, identity, pose, composition, or style."
    )
    if strategy == "safe_reframe":
        parts.append(
            "Keep the emotional force through lighting, fabric, color, gaze, posture, and cinematic distance."
        )
    return _sanitize_prompt(" ".join(parts))


def _sanitize_prompt(text: str) -> str:
    result = str(text or "").strip()
    for source, replacement in _SENSITIVE_REWRITES:
        result = re.sub(re.escape(source), replacement, result, flags=re.IGNORECASE)
    for term in _AVOID_FINAL_TERMS:
        result = re.sub(rf"\b{re.escape(term)}\b", "editorial-safe", result, flags=re.IGNORECASE)
    result = re.sub(r"\s+", " ", result)
    return result.strip()


def _extract_locks(text: str) -> List[str]:
    return _dedupe([lock.canonical for lock in _extract_constraint_locks(text)])


def _extract_constraint_locks(text: str) -> List[ConstraintLock]:
    matched_sources = [source for source in _LOCK_DEFINITIONS if source in text]
    locks: List[ConstraintLock] = []
    for source in matched_sources:
        if any(source != other and source in other for other in matched_sources):
            continue
        definition = _LOCK_DEFINITIONS[source]
        locks.append(ConstraintLock(
            category=str(definition["category"]),
            canonical=str(definition["canonical"]),
            source=source,
            hard=True,
        ))
    return _dedupe_constraint_locks(locks)


def _dedupe_constraint_locks(locks: Iterable[ConstraintLock]) -> List[ConstraintLock]:
    seen: set[tuple[str, str]] = set()
    result: List[ConstraintLock] = []
    for lock in locks:
        key = (lock.category, lock.canonical.lower())
        if key in seen:
            continue
        seen.add(key)
        result.append(lock)
    return result


def _repair_object_substitutions(text: str, must_keep: List[str]) -> str:
    result = text
    lock_text = " ".join(must_keep).lower()
    if "lisianthus" not in lock_text:
        return result
    for source, replacement in _OBJECT_SUBSTITUTIONS.items():
        result = re.sub(re.escape(source), replacement, result, flags=re.IGNORECASE)
    return result


def _infer_scene(text: str) -> str:
    if "台北雨夜" in text:
        return "rainy night in Taipei"
    lowered = text.lower()
    if "taipei" in lowered and "rain" in lowered:
        return "rainy night in Taipei"
    if "night" in lowered or "夜" in text:
        return "night scene"
    return ""


def _infer_style(text: str) -> str:
    lowered = text.lower()
    if any(marker in lowered or marker in text for marker in _STYLE_MARKERS):
        return "high-end fashion editorial"
    return ""


def _infer_mood(text: str) -> str:
    lowered = text.lower()
    if any(marker in lowered or marker in text for marker in _SENSUAL_MARKERS):
        return "refined glamour"
    if "noir" in lowered or "dark" in lowered:
        return "moody cinematic atmosphere"
    return ""


def _matched_avoid_terms(text: str) -> List[str]:
    lowered = str(text or "").lower()
    return [term for term in _AVOID_FINAL_TERMS if term in lowered]


def _worked_phrases(text: str) -> List[str]:
    phrases = []
    lowered = text.lower()
    for phrase in (
        "high-end cinematic editorial",
        "polished wardrobe",
        "premium lighting",
        "confident posture",
        "expressive gaze",
    ):
        if phrase in lowered:
            phrases.append(phrase)
    return phrases


def _dedupe(items: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _handle_image2_mediator_memory(args: Dict[str, Any], **kw: Any) -> str:
    action = str(args.get("action") or "report").strip().lower()
    config = read_image2_adaptive_mediator_config()
    if action == "report":
        limit = int(args.get("limit") or 10)
        return json.dumps({
            "success": True,
            "summary": summarize_image2_mediator_memory(config=config, limit=limit),
        }, indent=2, ensure_ascii=False)
    if action == "feedback":
        feedback = str(args.get("feedback") or "").strip()
        if not feedback:
            return json.dumps({
                "success": False,
                "error": "feedback is required when action='feedback'",
                "error_type": "invalid_argument",
            }, indent=2, ensure_ascii=False)
        recorded = record_image2_user_feedback(feedback, config=config)
        return json.dumps({
            "success": bool(recorded.get("recorded")),
            "feedback": recorded,
            "error": recorded.get("error"),
        }, indent=2, ensure_ascii=False)
    return json.dumps({
        "success": False,
        "error": "action must be 'report' or 'feedback'",
        "error_type": "invalid_argument",
    }, indent=2, ensure_ascii=False)


IMAGE2_MEDIATOR_MEMORY_SCHEMA = {
    "name": "image2_mediator_memory",
    "description": (
        "Inspect Image2 adaptive mediator JSONL evidence or record compact user "
        "feedback after an image result. Use action='report' to summarize recent "
        "attempts, strategies, statuses, and failure classes. Use action='feedback' "
        "when the user says 更接近, 太保守, 太露骨, 不夠性感, 跑題, 物件漂移, "
        "構圖差, or 保留這版但加強... so the mediator can learn from the strongest "
        "user signal without rewriting older records."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["report", "feedback"],
                "description": "Whether to summarize mediator memory or append user feedback.",
            },
            "feedback": {
                "type": "string",
                "description": "Natural-language user feedback to append when action is feedback.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 50,
                "description": "Recent memory records to include in report output.",
            },
        },
        "required": ["action"],
    },
}


registry.register(
    name="image2_mediator_memory",
    toolset="image_gen",
    schema=IMAGE2_MEDIATOR_MEMORY_SCHEMA,
    handler=_handle_image2_mediator_memory,
    check_fn=lambda: True,
    requires_env=[],
    is_async=False,
    emoji="🧭",
)
