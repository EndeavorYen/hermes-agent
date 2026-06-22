from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


def build_visual_delivery_manifest(package_payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(package_payload, dict):
        package_payload = {}
    delivery_metadata = package_payload.get("delivery_metadata")
    if not isinstance(delivery_metadata, dict):
        delivery_metadata = {}

    request_id = str(package_payload.get("visual_request_id") or delivery_metadata.get("visual_request_id") or "")
    selected_ids = {
        str(item)
        for item in delivery_metadata.get("selected_visual_artifact_ids", [])
        if item
    }
    artifacts = delivery_metadata.get("visual_artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}

    failures: list[str] = []
    deliverables = []
    if not selected_ids and artifacts:
        failures.append("missing_selected_visual_artifact_ids")
        return {
            "version": "visual_delivery_manifest.v0.2",
            "request_id": request_id or None,
            "deliverables": [],
            "failures": failures,
        }
    for ref, entry in artifacts.items():
        if not isinstance(entry, dict):
            continue
        entry = _entry_with_ledger_artifact(entry)
        artifact_id = str(entry.get("artifact_id") or "")
        if selected_ids and artifact_id not in selected_ids:
            continue
        artifact_request_id = str(entry.get("request_id") or "")
        if request_id and artifact_request_id and artifact_request_id != request_id:
            failures.append("cross_request_visual_artifact")
            continue
        if _stale_or_unstable_artifact(entry):
            failures.append("stale_visual_artifact")
            continue
        deliverable = _deliverable(str(ref), entry, package_payload)
        if deliverable.get("kind") == "video" and deliverable.get("uploadable_file") is not True:
            failures.append("video_ref_not_local_file")
        deliverables.append(deliverable)

    return {
        "version": "visual_delivery_manifest.v0.2",
        "request_id": request_id or None,
        "deliverables": deliverables,
        "failures": sorted(set(failures)),
    }


def select_deliverable_artifacts(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    deliverables = manifest.get("deliverables") if isinstance(manifest, dict) else []
    if not isinstance(deliverables, list):
        return []
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in deliverables:
        if not isinstance(item, dict):
            continue
        identity = str(item.get("identity") or item.get("ref") or "")
        artifact_id = str(item.get("artifact_id") or "")
        dedupe_keys = [f"identity:{identity}"] if identity else []
        if artifact_id:
            dedupe_keys.append(f"artifact:{artifact_id}")
        if not dedupe_keys or any(key in seen for key in dedupe_keys):
            continue
        seen.update(dedupe_keys)
        selected.append(item)
    return selected


def _entry_with_ledger_artifact(entry: dict[str, Any]) -> dict[str, Any]:
    artifact_id = str(entry.get("artifact_id") or "")
    if not artifact_id:
        return entry
    try:
        from agent.visual.attempt_ledger import VisualAttemptLedger
        from agent.visual.tracking import default_visual_ledger_path

        artifact = VisualAttemptLedger(default_visual_ledger_path()).get_artifact(artifact_id)
    except Exception:
        return entry
    merged = dict(entry)
    for key in (
        "request_id",
        "attempt_id",
        "kind",
        "content_hash",
        "mime_type",
        "width",
        "height",
        "freshness_status",
        "is_stable",
    ):
        if artifact.get(key) is not None:
            merged[key] = artifact.get(key)
    return merged


def _stale_or_unstable_artifact(entry: dict[str, Any]) -> bool:
    freshness = entry.get("freshness_status")
    if freshness is not None and str(freshness).strip().lower() != "fresh":
        return True
    stable = entry.get("is_stable")
    if stable is False or stable == 0 or str(stable).strip().lower() in {"0", "false", "no"}:
        return True
    return False


def _deliverable(ref: str, entry: dict[str, Any], package_payload: dict[str, Any]) -> dict[str, Any]:
    identity = (
        entry.get("content_hash")
        or entry.get("source_identity")
        or entry.get("source_url")
        or entry.get("uri")
        or ref
    )
    return {
        "request_id": entry.get("request_id") or package_payload.get("visual_request_id"),
        "attempt_id": entry.get("attempt_id"),
        "artifact_id": entry.get("artifact_id"),
        "kind": entry.get("kind") or _kind_from_ref(ref, package_payload),
        "ref": ref,
        "identity": str(identity),
        "width": entry.get("width"),
        "height": entry.get("height"),
        "delivery_ref_type": _delivery_ref_type(ref),
        "uploadable_file": _delivery_ref_type(ref) in {"local_path", "file_uri"},
    }


def _kind_from_ref(ref: str, package_payload: dict[str, Any]) -> str | None:
    if ref in set(package_payload.get("images") or []):
        return "image"
    if ref in set(package_payload.get("videos") or []):
        return "video"
    lowered = ref.lower()
    if lowered.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        return "image"
    if lowered.endswith((".mp4", ".mov", ".webm", ".mkv")):
        return "video"
    return None


def _delivery_ref_type(ref: str) -> str:
    parsed = urlparse(ref)
    if parsed.scheme == "file":
        return "file_uri"
    if parsed.scheme in {"http", "https"}:
        return "remote_url"
    if parsed.scheme == "":
        return "local_path"
    return "other"
