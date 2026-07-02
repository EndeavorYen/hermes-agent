from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PERCENTAGE_EVIDENCE_RE = re.compile(r"\babout\s+`?\d{1,3}%`?", re.I)
GROK_READY_OVERCLAIM_MARKERS = (
    "routes image/video tasks to Grok visual mode",
    "Grok preflight now",
    "Grok readiness",
    "xAI/Grok media readiness ready",
)


@dataclass(frozen=True)
class ReleaseDocsAuditResult:
    violations: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.violations


def audit_release_docs(
    *,
    release_audit_doc: str,
    llm_slice_doc: str,
    llm_readiness: Mapping[str, Any],
    media_readiness: Mapping[str, Any],
) -> ReleaseDocsAuditResult:
    violations: list[str] = []
    docs = {
        "release_audit_doc": str(release_audit_doc or ""),
        "llm_slice_doc": str(llm_slice_doc or ""),
    }
    media_scope = _text(
        media_readiness.get("media_release_scope")
        or media_readiness.get("public_claim_scope")
    )
    remaining_media_gaps = _string_list(media_readiness.get("remaining_media_gaps"))
    if not remaining_media_gaps:
        remaining_media_gaps = _string_list(media_readiness.get("public_claim_exclusions"))

    for doc_name, doc_text in docs.items():
        if PERCENTAGE_EVIDENCE_RE.search(doc_text):
            violations.append(f"{doc_name}:percentage_release_evidence")
        if _mentions_boundary_counts(doc_text) and not _has_boundary_disclaimer(
            doc_text
        ):
            violations.append(f"{doc_name}:boundary_counts_not_scoped")
        if not _has_reviewable_wow_matrix_fields(doc_text):
            violations.append(f"{doc_name}:wow_matrix_fields_missing")
        for check_name, violation_name in (
            ("package_install_smoke", "package_install_evidence_missing"),
            ("hostile_review", "hostile_review_evidence_missing"),
        ):
            expected_ids = _release_evidence_ids(
                check_name,
                llm_readiness,
                media_readiness if doc_name == "release_audit_doc" else {},
            )
            if expected_ids and not _all_present(doc_text, *expected_ids):
                violations.append(f"{doc_name}:{violation_name}")

    if media_scope == "media_openai_image_only" and remaining_media_gaps:
        release_audit_lower = docs["release_audit_doc"].lower()
        if not _has_completion_audit_boundary(docs["release_audit_doc"]):
            violations.append("release_audit_doc:completion_audit_missing")
        if not _has_slice_manifest_boundary(docs["release_audit_doc"]):
            violations.append("release_audit_doc:slice_manifest_missing")
        if any(
            marker.lower() in release_audit_lower
            for marker in GROK_READY_OVERCLAIM_MARKERS
        ):
            violations.append("release_audit_doc:grok_ready_overclaim")
        if not _media_profile_evidence_present(
            docs["release_audit_doc"],
            media_readiness,
        ):
            violations.append("release_audit_doc:media_profile_evidence_missing")
        for gap in remaining_media_gaps:
            if gap and gap not in docs["release_audit_doc"]:
                violations.append(f"release_audit_doc:media_gap_missing:{gap}")

    if not _llm_profile_evidence_present(docs["llm_slice_doc"], llm_readiness):
        violations.append("llm_slice_doc:llm_profile_evidence_missing")
    if _text(llm_readiness.get("public_claim_scope")) == "llm_only":
        if "llm_only" not in docs["llm_slice_doc"]:
            violations.append("llm_slice_doc:llm_claim_scope_missing")
        if "does not prove" not in docs["llm_slice_doc"].lower():
            violations.append("llm_slice_doc:llm_exclusions_missing")

    return ReleaseDocsAuditResult(violations=tuple(dict.fromkeys(violations)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit Raphael public release docs against readiness evidence."
    )
    parser.add_argument(
        "--release-audit-doc",
        default="docs/raphael-release-slice-audit.md",
    )
    parser.add_argument(
        "--llm-slice-doc",
        default="docs/raphael-llm-public-slice.md",
    )
    parser.add_argument(
        "--llm-readiness",
        default=None,
    )
    parser.add_argument(
        "--media-readiness",
        default=None,
    )
    args = parser.parse_args(argv)
    llm_readiness = (
        Path(args.llm_readiness)
        if args.llm_readiness
        else _default_readiness_path("llm")
    )
    media_readiness = (
        Path(args.media_readiness)
        if args.media_readiness
        else _default_readiness_path("media")
    )

    result = audit_release_docs(
        release_audit_doc=Path(args.release_audit_doc).read_text(encoding="utf-8"),
        llm_slice_doc=Path(args.llm_slice_doc).read_text(encoding="utf-8"),
        llm_readiness=_read_json(llm_readiness),
        media_readiness=_read_json(media_readiness),
    )
    if result.ready:
        print("Raphael release docs audit: pass")
        return 0
    print("Raphael release docs audit: fail")
    for violation in result.violations:
        print(f"- {violation}")
    return 1


def _read_json(path: Path) -> Mapping[str, Any]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    return parsed if isinstance(parsed, Mapping) else {}


def _default_readiness_path(profile: str) -> Path:
    home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
    return home / "raphael" / f"release_readiness.{profile}.json"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _string_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _nested(mapping: Mapping[str, Any], *path: str) -> Any:
    current: Any = mapping
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _llm_profile_evidence_present(
    doc_text: str,
    readiness: Mapping[str, Any],
) -> bool:
    session_id = _text(_nested(readiness, "checks", "llm_live_smoke", "session_id"))
    non_visual_run_id = _text(
        _nested(readiness, "checks", "non_visual_regression", "run_id")
    )
    passed_count = _text(
        _nested(readiness, "checks", "non_visual_regression", "passed_count")
    )
    return _all_present(doc_text, session_id, non_visual_run_id, passed_count)


def _media_profile_evidence_present(
    doc_text: str,
    readiness: Mapping[str, Any],
) -> bool:
    session_id = _text(_nested(readiness, "checks", "llm_live_smoke", "session_id"))
    non_visual_run_id = _text(
        _nested(readiness, "checks", "non_visual_regression", "run_id")
    )
    passed_count = _text(
        _nested(readiness, "checks", "non_visual_regression", "passed_count")
    )
    scope = _text(readiness.get("media_release_scope") or readiness.get("public_claim_scope"))
    return _all_present(doc_text, session_id, non_visual_run_id, passed_count, scope)


def _release_evidence_ids(
    check_name: str,
    *readiness_records: Mapping[str, Any],
) -> tuple[str, ...]:
    ids: list[str] = []
    for readiness in readiness_records:
        run_id = _text(_nested(readiness, "checks", check_name, "run_id"))
        if run_id:
            ids.append(run_id)
    return tuple(dict.fromkeys(ids))


def _all_present(text: str, *needles: str) -> bool:
    return all(needle and needle in text for needle in needles)


def _mentions_boundary_counts(text: str) -> bool:
    return (
        "LLM slice paths" in text
        or "Deferred media paths" in text
        or "unclassified paths" in text
        or "content-boundary violations" in text
    )


def _has_boundary_disclaimer(text: str) -> bool:
    lowered = text.lower()
    has_local_scope = (
        "local review evidence" in lowered or "local boundary evidence" in lowered
    )
    return has_local_scope and (
        "not a field in the readiness json" in lowered
        or "not a readiness json field" in lowered
    )


def _has_completion_audit_boundary(text: str) -> bool:
    lowered = text.lower()
    return (
        "raphael completion audit" in lowered
        and "ultimate sage king ready: no" in lowered
    )


def _has_slice_manifest_boundary(text: str) -> bool:
    lowered = text.lower()
    return (
        "release slice manifest" in lowered
        and ("split_required" in lowered or "split required" in lowered)
    )


def _has_reviewable_wow_matrix_fields(text: str) -> bool:
    required = (
        "user_prompt",
        "expected_visible_behavior",
        "critical_assertions",
        "next_action",
        "proof_layer",
        "visual_quota_used",
    )
    return _all_present(text, *required)


if __name__ == "__main__":
    raise SystemExit(main())
