"""Feature-flagged Image2 prompt mediation and memory helpers.

This is the local-runtime compatibility surface for the Image2 adaptive
mediator. Keep it small: read the runtime flag, preserve hard prompt locks,
rewrite risky wording into provider-safe visual language, and append auditable
JSONL records for later review.
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


_LOCK_DEFINITIONS: Dict[str, Dict[str, str]] = {
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
    "台北雨夜": {"canonical": "rainy night in Taipei", "category": "scene"},
    "午夜台北花市": {"canonical": "midnight Taipei flower market", "category": "scene"},
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
    ("sexy girl", "adult fashion model with refined glamour styling"),
    ("sexy woman", "adult fashion model with refined glamour styling"),
    ("hot girl", "adult fashion model"),
    ("sexy", "refined glamour"),
    ("性感美女", "adult fashion model with refined glamour styling"),
    ("性感", "refined glamour"),
    ("美女", "adult fashion model"),
    ("辣妹", "adult fashion model"),
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

_SENSUAL_MARKERS = ("sexy", "sensual", "glamour", "性感")


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
    success_definition: str = "Closest feasible Image2 result that preserves user intent."

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
    text = str(prompt or "").strip()
    lowered = text.lower()
    locks = _extract_constraint_locks(text)
    must_keep = _dedupe([lock.canonical for lock in locks if lock.hard])
    soft_preferences: List[str] = []
    if any(marker in lowered or marker in text for marker in _SENSUAL_MARKERS):
        soft_preferences.append("refined glamour")
    if any(marker in lowered or marker in text for marker in _STYLE_MARKERS):
        soft_preferences.append("high-end editorial style")

    risk_level = "low"
    if any(term in lowered for term in ("nude", "nudity", "naked", "explicit", "nsfw")):
        risk_level = "high"
    elif soft_preferences or _contains_people_marker(text):
        risk_level = "medium"

    return Image2Intent(
        subject=text,
        scene=_infer_scene(text),
        style=_infer_style(text),
        mood=_infer_mood(text),
        must_keep=must_keep,
        must_avoid=_matched_avoid_terms(text),
        constraint_locks=locks,
        soft_preferences=_dedupe(soft_preferences),
        risk_level=risk_level,
    )


def mediate_image2_prompt(
    prompt: str,
    *,
    config: Optional[Dict[str, Any]] = None,
    preprocessor_config: Optional[Dict[str, Any]] = None,
    draft_fn: Optional[DraftFn] = None,
) -> MediatedImagePrompt:
    del preprocessor_config, draft_fn
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

    if intent.risk_level in {"medium", "high"}:
        strategy = "safe_reframe"
        reason = "sensitive or human-facing prompt; preserve intent with provider-safe editorial language"
    elif intent.must_keep:
        strategy = "lock_preserving_rewrite"
        reason = "hard visual locks detected; preserve named objects and scene anchors"
    else:
        strategy = "codex_direct"
        reason = "no mediation risk detected"

    final_prompt = _compose_final_prompt(prompt, intent)
    return MediatedImagePrompt(
        user_concept=prompt,
        final_prompt=final_prompt,
        intent=intent,
        strategy=strategy,
        strategy_reason=reason,
        object_locks_added=list(intent.must_keep),
        worked_phrases=_worked_phrases(final_prompt),
        avoid_phrases=_matched_avoid_terms(prompt),
    )


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
    path = _memory_write_path(config)
    if path is None:
        return
    payload = {
        "timestamp": _now_iso(),
        "record_type": "attempt",
        "user_concept": mediated.user_concept,
        "intent": mediated.intent.to_dict(),
        "strategy": mediated.strategy,
        "strategy_reason": mediated.strategy_reason,
        "draft_model": mediated.draft_model,
        "draft_prompt": mediated.draft_prompt,
        "final_prompt": mediated.final_prompt,
        "image2_status": image2_status or "unknown",
        "feedback_source": feedback_source,
        "failure_class": failure_class or [],
        "scores": scores or {},
        "worked_phrases": list(mediated.worked_phrases),
        "avoid_phrases": list(mediated.avoid_phrases),
        "object_locks_added": list(mediated.object_locks_added),
        "qwen_candidate_id": mediated.qwen_candidate_id,
        "qwen_validation_status": mediated.qwen_validation_status,
        "qwen_constraint_report": list(mediated.qwen_constraint_report),
        "notes": notes,
    }
    _append_jsonl(path, payload)


def record_image2_user_feedback(
    feedback: str,
    *,
    config: Optional[Dict[str, Any]] = None,
    target_timestamp: str = "",
) -> Dict[str, Any]:
    config = config or read_image2_adaptive_mediator_config()
    text = str(feedback or "").strip()
    if not text:
        return {"recorded": False, "error": "feedback is required"}
    if config.get("enabled") is False or not _coerce_bool(config.get("log_attempts"), True):
        return {"recorded": False, "error": "adaptive mediator memory is disabled"}
    path = _memory_write_path(config)
    if path is None:
        return {"recorded": False, "error": "memory path is unavailable"}
    payload = {
        "timestamp": _now_iso(),
        "record_type": "feedback",
        "feedback_text": text,
        "target_timestamp": target_timestamp,
        "failure_class": _feedback_failure_classes(text),
    }
    _append_jsonl(path, payload)
    return {"recorded": True, "feedback_text": text, "failure_class": payload["failure_class"]}


def summarize_image2_mediator_memory(
    *,
    config: Optional[Dict[str, Any]] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    config = config or read_image2_adaptive_mediator_config()
    path = _memory_write_path(config)
    records = _read_jsonl(path) if path is not None else []
    attempts = [record for record in records if record.get("record_type") == "attempt"]
    feedback = [record for record in records if record.get("record_type") == "feedback"]
    recent_attempts = attempts[-max(1, int(limit)) :]
    return {
        "enabled": bool(config.get("enabled")),
        "memory_path": str(path) if path is not None else "",
        "attempt_count": len(attempts),
        "feedback_count": len(feedback),
        "status_counts": _count_values(record.get("image2_status") for record in attempts),
        "strategy_counts": _count_values(record.get("strategy") for record in attempts),
        "failure_class_counts": _count_many(record.get("failure_class") for record in attempts + feedback),
        "recent_attempts": [_public_memory_record(record) for record in recent_attempts],
        "recent_feedback": [_public_feedback_record(record) for record in feedback[-max(1, int(limit)) :]],
    }


def _handle_image2_mediator_memory(args: Dict[str, Any], **_kw: Any) -> str:
    action = str(args.get("action") or "report").strip().lower()
    config = read_image2_adaptive_mediator_config()
    if action == "report":
        limit = int(args.get("limit") or 10)
        return json.dumps(
            {
                "success": True,
                "summary": summarize_image2_mediator_memory(config=config, limit=limit),
            },
            indent=2,
            ensure_ascii=False,
        )
    if action == "feedback":
        recorded = record_image2_user_feedback(str(args.get("feedback") or ""), config=config)
        return json.dumps(
            {
                "success": bool(recorded.get("recorded")),
                "feedback": recorded,
                "error": recorded.get("error"),
            },
            indent=2,
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "success": False,
            "error": "action must be 'report' or 'feedback'",
            "error_type": "invalid_argument",
        },
        indent=2,
        ensure_ascii=False,
    )


def _compose_final_prompt(prompt: str, intent: Image2Intent) -> str:
    sanitized = _sanitize_prompt(prompt)
    locks = list(intent.must_keep)
    lock_text = ", ".join(locks) if locks else "preserve the user-specified subject exactly"
    style_bits = _dedupe(
        [
            item
            for item in [
                intent.style,
                intent.mood,
                *intent.soft_preferences,
                "high-end cinematic editorial image",
            ]
            if item
        ]
    )
    parts = [
        f"Hard locks: {lock_text}.",
        f"Subject: {sanitized}.",
        f"Style and mood: {', '.join(style_bits)}.",
        "Lighting and camera: premium lighting, controlled highlights, polished real-camera editorial framing.",
        "Provider-safe framing: tasteful adult editorial styling, polished wardrobe, focus on composition, lighting, fabric, color, posture, and form.",
    ]
    if intent.scene:
        parts.append(f"Setting anchor: {intent.scene}.")
    parts.append(
        "Preserve all hard locks exactly; do not substitute locked objects, location, clothing, identity, pose, composition, or style."
    )
    return _sanitize_prompt(" ".join(parts))


def _sanitize_prompt(text: str) -> str:
    result = str(text or "").strip()
    for source, replacement in _SENSITIVE_REWRITES:
        result = re.sub(re.escape(source), replacement, result, flags=re.IGNORECASE)
    for term in _AVOID_FINAL_TERMS:
        result = re.sub(rf"\b{re.escape(term)}\b", "editorial-safe", result, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", result).strip()


def _extract_constraint_locks(text: str) -> List[ConstraintLock]:
    matched_sources = [source for source in _LOCK_DEFINITIONS if source in text]
    locks: List[ConstraintLock] = []
    for source in matched_sources:
        if any(source != other and source in other for other in matched_sources):
            continue
        definition = _LOCK_DEFINITIONS[source]
        locks.append(
            ConstraintLock(
                category=definition["category"],
                canonical=definition["canonical"],
                source=source,
                hard=True,
            )
        )
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


def _contains_people_marker(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered or marker in text
        for marker in ("person", "portrait", "model", "woman", "man", "character", "人物", "面容")
    )


def _matched_avoid_terms(text: str) -> List[str]:
    lowered = str(text or "").lower()
    return [term for term in _AVOID_FINAL_TERMS if term in lowered]


def _worked_phrases(text: str) -> List[str]:
    lowered = text.lower()
    return [
        phrase
        for phrase in (
            "high-end cinematic editorial",
            "polished wardrobe",
            "premium lighting",
            "refined glamour",
        )
        if phrase in lowered
    ]


def _feedback_failure_classes(text: str) -> List[str]:
    lowered = str(text or "").lower()
    classes = []
    if "物件漂移" in text or "object drift" in lowered:
        classes.append("object_drift")
    if "跑題" in text or "mismatch" in lowered:
        classes.append("semantic_mismatch")
    if "太保守" in text:
        classes.append("too_conservative")
    if "太露骨" in text:
        classes.append("too_explicit")
    return classes


def _memory_write_path(config: Dict[str, Any]) -> Optional[Path]:
    value = config.get("memory_path") or _default_memory_path()
    if not value:
        memory_dir = config.get("memory_dir") or _default_memory_dir()
        return Path(str(memory_dir)).expanduser() / "memory.jsonl"
    return Path(str(value)).expanduser()


def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    except Exception as exc:
        logger.info("Could not write Image2 adaptive mediator memory: %s", exc)


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return records
    for line in lines:
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


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
        "notes": record.get("notes"),
    }


def _public_feedback_record(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "timestamp": record.get("timestamp"),
        "record_type": record.get("record_type", "feedback"),
        "feedback_text": record.get("feedback_text"),
        "failure_class": _as_list(record.get("failure_class")),
    }


def _count_values(values: Iterable[Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _count_many(values: Iterable[Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for value in values:
        for item in _as_list(value):
            counts[item] = counts.get(item, 0) + 1
    return dict(sorted(counts.items()))


def _as_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if value is None or value == "":
        return []
    return [str(value)]


def _dedupe(items: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        key = str(item or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(str(item))
    return result


def _now_iso() -> str:
    return _datetime.datetime.now(_datetime.timezone.utc).isoformat()


IMAGE2_MEDIATOR_MEMORY_SCHEMA = {
    "name": "image2_mediator_memory",
    "description": (
        "Inspect Image2 adaptive mediator JSONL evidence or record compact user "
        "feedback after an image result. Use action='report' to summarize recent "
        "attempts, strategies, statuses, and failure classes. Use action='feedback' "
        "when the user says an image was closer, too conservative, too explicit, "
        "off-topic, drifting from locked objects, or needs stronger preservation."
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
