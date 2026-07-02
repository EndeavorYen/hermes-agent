from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
from typing import Any

from agent.redact import redact_sensitive_text
from agent.raphael.media_readiness import (
    MIN_OPENAI_IMAGE_QUALITY_SCORE,
    OPENAI_IMAGE_READINESS_CONTRACT,
    REQUIRED_OPENAI_IMAGE_EVIDENCE_REF_KEYS,
)


REQUIRED_LIFECYCLE_CHECKS = ("install", "enable", "disable", "uninstall")
REQUIRED_LLM_SIMULATION_CASES = (
    "summon_tool_task",
    "mission_followup",
    "ambiguous_clarification",
    "proof_block",
    "finalizer_proof_block_output",
    "evolution_proposal",
    "proposal_lifecycle_status",
    "public_claim_boundary",
)
UNVERIFIED_MEDIA_SLICES = (
    "grok_web_imagine",
    "video",
    "slack_delivery",
    "full_media",
)
FORBIDDEN_RELEASE_READY_KEYWORDS = {
    "grok_web_imagine": ("grok", "grok web imagine", "grok imagine", "web imagine"),
    "video": ("video", "影片", "視頻", "短片"),
    "slack_delivery": ("slack", "native delivery", "native upload", "media delivery"),
    "full_media": (
        "full media",
        "media readiness",
        "media generation",
        "visual readiness",
        "visual generation",
        "general visual",
        "完整媒體",
        "完整視覺",
    ),
}
_READY_CLAIM_WORD_PATTERN = (
    r"(?:ready|approved|certified|passed|verified|complete|confirmed|available|operational|enabled|works?|ships?|shipping|supported|usable|functioning|active|activated|released|launched?|deployed|ga)"
)
_CAPABILITY_ACCESS_VERB_PATTERN = r"(?:use|generate|create|produce|make|upload|deliver|send|post)"
_READY_CLAIM_PHRASE_PATTERN = (
    rf"(?:turned\s+on|in\s+production|generally\s+available|publicly\s+available|(?:is|are)\s+public|rolled\s+out|can\s+be\s+used|can\s+(?:now\s+)?{_CAPABILITY_ACCESS_VERB_PATTERN}|able\s+to\s+{_CAPABILITY_ACCESS_VERB_PATTERN}|open\s+to\s+users|accessible\s+to\s+users|have\s+access\s+to|on\s+by\s+default)"
)
_READY_OR_READINESS_PATTERN = (
    rf"(?:readiness|{_READY_CLAIM_WORD_PATTERN}|{_READY_CLAIM_PHRASE_PATTERN}|live)"
)
_CLAUSE_BREAK_PATTERN = (
    r"[,.;!?]|\b(?:and|but|however|yet|while|although|though|whereas|even\s+though)\b"
)
_CLAUSE_TEXT_PATTERN = rf"(?:(?!{_CLAUSE_BREAK_PATTERN}).)*"
_BENIGN_META_ARTIFACT_PATTERN = (
    r"(?:documentation|docs|tests?|test suite|release notes|pr artifact)"
)

_PRIVATE_TEXT_REDACTIONS = (
    (
        re.compile(r"data:[^\s,)]+;base64,[^\s,)]+", re.IGNORECASE),
        "[redacted-media-payload]",
    ),
    (re.compile(r"base64:[^\s,)]+", re.IGNORECASE), "[redacted-media-payload]"),
    (re.compile(r"\bbase64\b", re.IGNORECASE), "[redacted-media-payload]"),
    (re.compile(r"\bxox[a-z]-[^\s,)]+", re.IGNORECASE), "[redacted-token]"),
    (re.compile(r"\bcandidate:[^\s,)]+", re.IGNORECASE), "[redacted-artifact]"),
    (
        re.compile(r"(?:file://)?/(?:private|Users|tmp|var)(?:/[^\s,)]+)*"),
        "[redacted-path]",
    ),
)


@dataclass(frozen=True)
class RaphaelReleaseCandidateReport:
    status: str
    slices: Mapping[str, Mapping[str, Any]]
    public_claims: tuple[str, ...]
    blocked_claims: tuple[str, ...]
    created_at: datetime


def build_release_candidate_gate(
    *,
    lifecycle_gate: Mapping[str, Any] | None,
    llm_gate: Mapping[str, Any] | None,
    media_gate: Mapping[str, Any] | None,
    doc_texts: Sequence[str],
    doc_failures: Sequence[str] = (),
    now: datetime | None = None,
) -> RaphaelReleaseCandidateReport:
    created_at = _ensure_utc(now) if now is not None else _utc_now()
    lifecycle_slice = _lifecycle_slice(lifecycle_gate)
    llm_slice = _llm_slice(llm_gate)
    media_slice = _media_slice(media_gate)
    gate_input_claims_slice = _gate_input_claims_slice(llm_gate, media_gate)
    docs_slice = _docs_slice(doc_texts, doc_failures=doc_failures)

    openai_image = _openai_image_slice(media_gate, media_slice)
    slices: dict[str, dict[str, Any]] = {
        "lifecycle": lifecycle_slice,
        "llm": llm_slice,
        "openai_image": openai_image,
        "media_gate": media_slice,
        "gate_input_claims": gate_input_claims_slice,
        "public_claims": docs_slice,
    }
    for name in UNVERIFIED_MEDIA_SLICES:
        slices[name] = {
            "ready": False,
            "blocking_reasons": [f"{name}_requires_separate_live_evidence"],
            "evidence_refs": [],
        }

    ready = all(
        bool(slices[name].get("ready"))
        for name in (
            "lifecycle",
            "llm",
            "openai_image",
            "media_gate",
            "gate_input_claims",
            "public_claims",
        )
    )
    public_claims = (
        ("Raphael release candidate is ready for verified LLM and OpenAI image slices.",)
        if ready
        else ("Raphael release candidate is blocked until required evidence passes.",)
    )
    blocked_claims = (
        "Grok Web Imagine, video, Slack delivery, and full media remain blocked.",
    )
    return RaphaelReleaseCandidateReport(
        status="release_candidate_ready" if ready else "blocked",
        slices=slices,
        public_claims=public_claims,
        blocked_claims=blocked_claims,
        created_at=created_at,
    )


def render_release_candidate_gate(report: RaphaelReleaseCandidateReport) -> str:
    lines = [
        "Raphael Release Candidate Gate",
        f"Overall: {_safe_text(report.status)}",
        f"Lifecycle: {_ready_label(report.slices['lifecycle'])}",
        f"LLM slice: {_ready_label(report.slices['llm'])}",
        f"OpenAI image slice: {_ready_label(report.slices['openai_image'])}",
        f"Grok Web Imagine: {_ready_label(report.slices['grok_web_imagine'], blocked='blocked')}",
        f"Video: {_ready_label(report.slices['video'], blocked='blocked')}",
        f"Slack delivery: {_ready_label(report.slices['slack_delivery'], blocked='blocked')}",
        f"Full media: {_ready_label(report.slices['full_media'], blocked='blocked')}",
    ]
    for name, slice_report in report.slices.items():
        blockers = tuple(str(reason) for reason in slice_report.get("blocking_reasons", ()))
        if blockers and name not in UNVERIFIED_MEDIA_SLICES:
            lines.append(
                f"{name} blockers: "
                f"{', '.join(_safe_text(reason) for reason in blockers)}"
            )
    lines.append("Public claims:")
    lines.extend(f"- {_safe_text(claim)}" for claim in report.public_claims)
    lines.append("Blocked claims:")
    lines.extend(f"- {_safe_text(claim)}" for claim in report.blocked_claims)
    return "\n".join(lines)


def write_release_candidate_gate(
    report: RaphaelReleaseCandidateReport,
    path: str | Path,
) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(_report_to_dict(report), allow_nan=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _lifecycle_slice(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return _blocked_slice("lifecycle_evidence_missing")
    reasons: list[str] = []
    if payload.get("schema_version") != "raphael.lifecycle_evidence.v1":
        reasons.append("lifecycle_schema_invalid")
    checks = _dict_value(payload, "checks")
    refs: list[str] = []
    for check in REQUIRED_LIFECYCLE_CHECKS:
        if payload.get(check) is not True:
            reasons.append(f"lifecycle_{check}_missing")
        check_payload = _dict_value(checks, check)
        if check_payload.get("exit_code") != 0:
            reasons.append(f"lifecycle_{check}_exit_not_zero")
        evidence_ref = str(check_payload.get("evidence_ref") or "").strip()
        if not evidence_ref:
            reasons.append(f"lifecycle_{check}_evidence_missing")
        else:
            refs.append(evidence_ref)
    if payload.get("private_output_clean") is not True:
        reasons.append("lifecycle_privacy_not_proven")
    return {
        "ready": not reasons,
        "blocking_reasons": [_safe_text(reason) for reason in reasons],
        "evidence_refs": _safe_list(refs),
    }


def _llm_slice(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return _blocked_slice("llm_gate_missing")
    slices = _dict_value(payload, "slices")
    reasons: list[str] = []
    if payload.get("schema_version") != "raphael.public_readiness.v1":
        reasons.append("llm_gate_schema_invalid")
    if payload.get("status") != "llm_ready":
        reasons.append("llm_gate_not_ready")
    if _dict_value(slices, "llm").get("ready") is not True:
        reasons.append("llm_slice_not_ready")
    simulation = _dict_value(payload, "simulation")
    if simulation.get("status") != "passed":
        reasons.append("llm_simulation_not_passed")
    if not _simulation_cases_passed(simulation.get("cases")):
        reasons.append("llm_simulation_cases_incomplete")
    live_smoke = _dict_value(payload, "live_smoke")
    if live_smoke.get("status") != "passed":
        reasons.append("llm_live_smoke_missing")
    evidence_refs = _safe_list(_dict_value(slices, "llm").get("evidence_refs"))
    if not evidence_refs and live_smoke:
        evidence_refs = _safe_list(live_smoke.get("evidence_refs"))
    if not evidence_refs:
        reasons.append("llm_evidence_refs_missing")
    if (
        str(live_smoke.get("provider") or "").strip().lower() in {"", "unknown"}
        or str(live_smoke.get("model") or "").strip().lower() in {"", "unknown"}
        or live_smoke.get("failure_layer") not in {None, ""}
    ):
        reasons.append("llm_live_smoke_details_missing")
    for name in ("media", "visual", "grok"):
        if _dict_value(slices, name).get("ready") is True:
            reasons.append(f"llm_gate_unverified_slice_ready:{name}")
    return {
        "ready": not reasons,
        "blocking_reasons": [_safe_text(reason) for reason in reasons],
        "evidence_refs": evidence_refs,
    }


def _media_slice(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return _blocked_slice("media_gate_missing")
    slices = _dict_value(payload, "slices")
    reasons: list[str] = []
    if payload.get("schema_version") != "raphael.media_readiness.v1":
        reasons.append("media_gate_schema_invalid")
    if payload.get("status") != "openai_image_ready":
        reasons.append("media_gate_not_openai_image_ready")
    if _dict_value(slices, "openai_image").get("ready") is not True:
        reasons.append("media_gate_openai_image_not_ready")
    openai = _dict_value(payload, "openai_image")
    if openai.get("status") != "passed":
        reasons.append("openai_image_status_not_passed")
    if openai.get("provider") != "openai" or openai.get("capability") != "image":
        reasons.append("openai_image_wrong_provider_or_capability")
    if openai.get("verification_contract") != OPENAI_IMAGE_READINESS_CONTRACT:
        reasons.append("openai_image_contract_unverified")
    evidence_refs = _safe_list(openai.get("evidence_refs"))
    if not _has_required_openai_evidence_ref_classes(evidence_refs):
        reasons.append("openai_image_evidence_refs_incomplete")
    if not str(openai.get("selected_artifact_id") or "").strip():
        reasons.append("openai_image_selected_artifact_missing")
    dimensions = _dict_value(openai, "dimensions")
    if _positive_int(dimensions.get("width")) is None or _positive_int(dimensions.get("height")) is None:
        reasons.append("openai_image_dimensions_missing")
    if _float(openai.get("quality_score")) < MIN_OPENAI_IMAGE_QUALITY_SCORE:
        reasons.append("openai_image_quality_below_threshold")
    for name in UNVERIFIED_MEDIA_SLICES:
        if _dict_value(slices, name).get("ready") is True:
            reasons.append(f"media_gate_unverified_slice_ready:{name}")
    return {
        "ready": not reasons,
        "blocking_reasons": [_safe_text(reason) for reason in reasons],
        "evidence_refs": evidence_refs,
    }


def _openai_image_slice(
    payload: Mapping[str, Any] | None,
    media_slice: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return _blocked_slice("media_gate_missing")
    openai = _dict_value(payload, "openai_image")
    if not openai:
        openai = _dict_value(_dict_value(payload, "slices"), "openai_image")
    reasons = list(media_slice.get("blocking_reasons", ()))
    if media_slice.get("ready") is not True:
        reasons.append("openai_image_slice_not_ready")
    return {
        "ready": not reasons,
        "blocking_reasons": [_safe_text(reason) for reason in reasons],
        "evidence_refs": _safe_list(openai.get("evidence_refs")),
    }


def _gate_input_claims_slice(
    llm_gate: Mapping[str, Any] | None,
    media_gate: Mapping[str, Any] | None,
) -> dict[str, Any]:
    reasons: list[str] = []
    refs: list[str] = []
    for source, payload in (("llm_gate", llm_gate), ("media_gate", media_gate)):
        if not isinstance(payload, Mapping):
            continue
        claims = [
            *_safe_list(payload.get("public_claims")),
            *_safe_list(payload.get("blocked_claims")),
        ]
        violations = _release_claim_violations(tuple(claims))
        if not violations:
            continue
        reasons.append("gate_input_claim_boundary_failed")
        refs.extend(f"{source}:{violation}" for violation in violations)
    return {
        "ready": not reasons,
        "blocking_reasons": _dedupe([_safe_text(reason) for reason in reasons]),
        "evidence_refs": _dedupe(refs) or ["gate_inputs:claim_boundary_clean"],
    }


def _docs_slice(doc_texts: Sequence[str], *, doc_failures: Sequence[str]) -> dict[str, Any]:
    joined = "\n".join(text for text in _doc_text_items(doc_texts) if text.strip())
    reasons = [
        f"release_doc_unreadable:{_safe_text(path)}"
        for path in doc_failures
        if str(path).strip()
    ]
    if not joined.strip():
        reasons.append("release_docs_missing")
    if reasons:
        return {
            "ready": False,
            "blocking_reasons": [_safe_text(reason) for reason in reasons],
            "evidence_refs": [],
        }
    violations = _release_claim_violations((joined,))
    reasons.extend(["public_claim_boundary_failed"] if violations else [])
    return {
        "ready": not reasons,
        "blocking_reasons": [_safe_text(reason) for reason in reasons],
        "evidence_refs": tuple(violations or ("release_docs:claim_boundary_clean",)),
    }


def _release_claim_violations(claims: tuple[str, ...]) -> list[str]:
    violations: list[str] = []
    for name, keywords in FORBIDDEN_RELEASE_READY_KEYWORDS.items():
        if _has_forbidden_ready_claim(claims, keywords):
            violations.append(f"forbidden_claim:{name}")
    return violations


def _has_forbidden_ready_claim(claims: tuple[str, ...], keywords: tuple[str, ...]) -> bool:
    for sentence in _claim_sentences(claims):
        sentence = _strip_negative_ready_claims(sentence)
        if _has_ready_intent(sentence) and any(keyword in sentence for keyword in keywords):
            return True
        for clause in _claim_clauses(sentence):
            if not _has_ready_intent(clause):
                continue
            if not any(keyword in clause for keyword in keywords):
                continue
            return True
    return False


def _claim_sentences(claims: tuple[str, ...]) -> tuple[str, ...]:
    joined = _strip_markdown_code_blocks("\n".join(str(claim) for claim in claims))
    joined = re.sub(r"\n\s*(?:#+\s+|-+\s+)", ". ", joined)
    return tuple(
        re.sub(r"\s+", " ", sentence.strip().lower())
        for sentence in re.split(r"[.;!?。！？]+", joined)
        if sentence.strip()
    )


def _doc_text_items(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


def _strip_markdown_code_blocks(text: str) -> str:
    return re.sub(r"```.*?```", " ", text, flags=re.DOTALL)


def _claim_clauses(sentence: str) -> tuple[str, ...]:
    return tuple(
        clause.strip()
        for clause in re.split(
            r"\b(?:and|but|however|yet)\b|do not worry,",
            sentence,
        )
        if clause.strip()
    )


def _has_ready_intent(sentence: str) -> bool:
    return bool(
        re.search(rf"\b{_READY_CLAIM_WORD_PATTERN}\b", sentence)
        or re.search(rf"\b{_READY_CLAIM_PHRASE_PATTERN}\b", sentence)
        or re.search(r"\b(?:is|are)\s+live\b", sentence)
        or "已就緒" in sentence
        or "就緒" in sentence
        or "可用" in sentence
        or "可以上線" in sentence
    )


def _negates_ready_claim(sentence: str) -> bool:
    return bool(
        "not ready" in sentence
        or "not certified" in sentence
        or "not approved" in sentence
        or "not verified" in sentence
        or "not complete" in sentence
        or "not confirmed" in sentence
        or "no forbidden" in sentence
        or "remain blocked" in sentence
        or "remains blocked" in sentence
        or "requires separate" in sentence
        or "require separate" in sentence
        or "不能" in sentence
        or "不可" in sentence
        or "不得" in sentence
        or "不證明" in sentence
        or "尚未" in sentence
        or re.search(r"\bnot\b(?:\s+\w+){0,4}\s+\bready\b", sentence)
    )


def _strip_negative_ready_claims(sentence: str) -> str:
    spans = (
        *_scoped_negative_ready_claim_spans(sentence),
        *_common_negative_ready_claim_spans(sentence),
        *_benign_meta_completion_spans(sentence),
    )
    if not spans:
        return sentence
    chars = list(sentence)
    for start, end in spans:
        chars[start:end] = " " * (end - start)
    return "".join(chars)


def _scoped_negative_ready_claim_spans(sentence: str) -> tuple[tuple[int, int], ...]:
    negative_verbs = r"(?:state|say|announce|present|describe|call|market)"
    no_ready_term = rf"(?:(?!\b{_READY_OR_READINESS_PATTERN}\b).)*"
    patterns = (
        rf"\b(?:do|must) not\s+publish\s+claims?\s+(?:that\s+)?{no_ready_term}\b{_READY_OR_READINESS_PATTERN}\b",
        rf"\bdo not\s+{negative_verbs}\b[^,.;!?]*\b{_READY_OR_READINESS_PATTERN}\b",
        rf"\bmust not\s+{negative_verbs}\b[^,.;!?]*\b{_READY_OR_READINESS_PATTERN}\b",
        rf"\bdo not\s+claim\b[^,.;!?]*\b{_READY_OR_READINESS_PATTERN}\b",
        rf"\bmust not\s+claim\b[^,.;!?]*\b{_READY_OR_READINESS_PATTERN}\b",
        rf"\bdoes not\s+claim\s+(?!to\b){no_ready_term}\b{_READY_OR_READINESS_PATTERN}\b",
        rf"\bdoes not\s+(?:certify|prove|validate)\b{no_ready_term}\b{_READY_OR_READINESS_PATTERN}\b",
    )
    spans: list[tuple[int, int]] = []
    for pattern in patterns:
        spans.extend(
            (match.start(), match.end())
            for match in re.finditer(pattern, sentence)
        )
    return tuple(sorted(spans))


def _common_negative_ready_claim_spans(sentence: str) -> tuple[tuple[int, int], ...]:
    patterns = (
        rf"\bnot\s+{_READY_CLAIM_WORD_PATTERN}\b",
        r"\bnot\s+(?:in\s+production|generally\s+available|publicly\s+available|public|rolled\s+out|on\s+by\s+default)\b",
        r"\bcannot\s+be\s+used\b",
        rf"\bcannot\s+(?:now\s+)?{_CAPABILITY_ACCESS_VERB_PATTERN}\b",
        rf"\bnot\s+able\s+to\s+{_CAPABILITY_ACCESS_VERB_PATTERN}\b",
        r"\bnot\s+(?:open|accessible)\s+to\s+users\b",
        r"\b(?:do|does)\s+not\s+have\s+access\s+to\b",
        r"\b(?:do|does)\s+not\s+(?:work|ship)\b",
        r"\b(?:remain|remains)\s+blocked\b",
        r"\brequires?\s+separate\b",
        r"\bno\s+forbidden\b(?:(?!\bready\s+claim\b).)*\bready\s+claim\b",
    )
    spans: list[tuple[int, int]] = []
    for pattern in patterns:
        spans.extend(
            (match.start(), match.end())
            for match in re.finditer(pattern, sentence)
        )
    return tuple(sorted(spans))


def _benign_meta_completion_spans(sentence: str) -> tuple[tuple[int, int], ...]:
    patterns = (
        rf"{_CLAUSE_TEXT_PATTERN}\b{_BENIGN_META_ARTIFACT_PATTERN}\b\s+(?:(?:is|are)\s+)?(?:complete|passed)\b",
        rf"{_CLAUSE_TEXT_PATTERN}\b{_BENIGN_META_ARTIFACT_PATTERN}\b\s+(?:(?:is|are)\s+)?(?:supported|usable|functioning|active|enabled)\b",
        rf"{_CLAUSE_TEXT_PATTERN}\b{_BENIGN_META_ARTIFACT_PATTERN}\b\s+support\s+(?:(?:is|are)\s+)?(?:active|supported|usable|functioning|enabled)\b",
        r"\bpublic wording keeps\b[^.]*\bclaims?\s+outside\b[^.]*",
        r"\bdid any wording imply\b[^.]*",
    )
    spans: list[tuple[int, int]] = []
    for pattern in patterns:
        spans.extend(
            (match.start(), match.end())
            for match in re.finditer(pattern, sentence)
        )
    return tuple(sorted(spans))


def _blocked_slice(reason: str) -> dict[str, Any]:
    return {
        "ready": False,
        "blocking_reasons": [_safe_text(reason)],
        "evidence_refs": [],
    }


def _ready_label(slice_report: Mapping[str, Any], *, blocked: str = "blocked") -> str:
    return "ready" if slice_report.get("ready") else blocked


def _report_to_dict(report: RaphaelReleaseCandidateReport) -> dict[str, Any]:
    return {
        "schema_version": "raphael.release_candidate.v1",
        "status": _safe_text(report.status),
        "created_at": report.created_at.isoformat(),
        "slices": _safe_json_value(report.slices),
        "public_claims": [_safe_text(claim) for claim in report.public_claims],
        "blocked_claims": [_safe_text(claim) for claim in report.blocked_claims],
    }


def _dict_value(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return dict(value) if isinstance(value, Mapping) else {}


def _simulation_cases_passed(value: Any) -> bool:
    if not isinstance(value, (list, tuple)):
        return False
    passed_cases = {
        str(case.get("case_id") or "")
        for case in value
        if isinstance(case, Mapping) and case.get("passed") is True
    }
    return all(case_id in passed_cases for case_id in REQUIRED_LLM_SIMULATION_CASES)


def _safe_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [_safe_text(item) for item in value if _safe_text(item)]
    if isinstance(value, str) and value.strip():
        return [_safe_text(value)]
    return []


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _has_required_openai_evidence_ref_classes(evidence_refs: Sequence[str]) -> bool:
    prefix_groups = tuple(
        (key + ":", key.replace("_", "-") + ":")
        for key in REQUIRED_OPENAI_IMAGE_EVIDENCE_REF_KEYS
    )
    return all(
        any(str(ref).startswith(prefix) for ref in evidence_refs for prefix in prefixes)
        for prefixes in prefix_groups
    )


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _float(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return numeric if math.isfinite(numeric) else 0.0


def _safe_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {_safe_text(key): _safe_json_value(item) for key, item in value.items()}
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, tuple):
        return [_safe_json_value(item) for item in value]
    if isinstance(value, list):
        return [_safe_json_value(item) for item in value]
    return value


def _safe_text(value: Any) -> str:
    text = redact_sensitive_text(str(value), force=True)
    for pattern, replacement in _PRIVATE_TEXT_REDACTIONS:
        text = pattern.sub(replacement, text)
    return text.strip()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "RaphaelReleaseCandidateReport",
    "build_release_candidate_gate",
    "render_release_candidate_gate",
    "write_release_candidate_gate",
]
