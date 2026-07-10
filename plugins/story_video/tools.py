from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .audit import ProviderAudit, normalize_provider
from .state import PHASES, StoryVideoRunContext, StoryVideoStateStore


@dataclass(frozen=True)
class PhaseProof:
    phase: str
    ok: bool
    missing: tuple[str, ...] = ()
    violations: tuple[str, ...] = ()

    @property
    def marker(self) -> str:
        status = "PASS" if self.ok else "BLOCKED"
        return f"STORY_VIDEO_PHASE_PROOF: {self.phase} {status}"


def _nonempty(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 1
    except OSError:
        return False


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _validate_planning(context: StoryVideoRunContext) -> PhaseProof:
    required = (
        "PROJECT_CONTRACT.md",
        "storyboard.md",
        "scene_ledger.json",
        "production_checklist.json",
    )
    missing = tuple(
        name for name in required if not _nonempty(context.project_dir / name)
    )
    violations: list[str] = []
    for name in ("scene_ledger.json", "production_checklist.json"):
        path = context.project_dir / name
        if name not in missing and _load_json(path) is None:
            violations.append(f"{name} is not valid JSON")
    return PhaseProof(
        phase="planning",
        ok=not missing and not violations,
        missing=missing,
        violations=tuple(violations),
    )


def _selected_outputs(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        return []
    selected = []
    for output in outputs:
        if not isinstance(output, dict):
            continue
        status = str(output.get("status") or output.get("selection") or "").lower()
        if output.get("selected") is True or status in {"selected", "current", "approved"}:
            selected.append(output)
    return selected


def _validate_keyframes(context: StoryVideoRunContext) -> PhaseProof:
    rel = "manifests/scene_generation_manifest.json"
    manifest = _load_json(context.project_dir / rel)
    if not isinstance(manifest, dict):
        return PhaseProof(phase="keyframes", ok=False, missing=(rel,))
    provider = normalize_provider(manifest.get("provider"))
    selected = _selected_outputs(manifest)
    violations: list[str] = []
    if provider not in {"openai", "openai-codex"}:
        violations.append(f"source provider is {provider or '<missing>'}, not OpenAI")
    if not selected:
        violations.append("no selected current keyframe output")
    return PhaseProof(
        phase="keyframes",
        ok=not violations,
        violations=tuple(violations),
    )


def _validate_batch(context: StoryVideoRunContext) -> PhaseProof:
    ledger_path = context.project_dir / "scene_ledger.json"
    ledger = _load_json(ledger_path)
    if ledger is None:
        return PhaseProof(phase="batch", ok=False, missing=("scene_ledger.json",))
    scenes = ledger.get("scenes") if isinstance(ledger, dict) else ledger
    if not isinstance(scenes, list) or not scenes:
        return PhaseProof(
            phase="batch",
            ok=False,
            violations=("scene ledger has no scenes",),
        )
    missing: list[str] = []
    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            missing.append(f"scene[{index}].selected_asset")
            continue
        asset = (
            scene.get("selected_asset")
            or scene.get("selected_asset_path")
            or scene.get("image")
        )
        if not asset:
            missing.append(f"{scene.get('scene_id') or index}.selected_asset")
            continue
        path = Path(str(asset))
        if not path.is_absolute():
            path = context.project_dir / path
        if not path.exists():
            missing.append(f"{scene.get('scene_id') or index}.selected_asset_file")
    return PhaseProof(phase="batch", ok=not missing, missing=tuple(missing))


def _validate_voice(context: StoryVideoRunContext) -> PhaseProof:
    audio_dir = context.project_dir / "audio"
    audio = tuple(audio_dir.glob("*.aiff")) + tuple(audio_dir.glob("*.wav")) + tuple(audio_dir.glob("*.mp3"))
    if not audio:
        return PhaseProof(phase="voice", ok=False, missing=("audio narration segments",))
    return PhaseProof(phase="voice", ok=True)


def _render_manifest_path(context: StoryVideoRunContext) -> Path | None:
    for rel in ("render_manifest.json", "manifests/render_manifest.json"):
        path = context.project_dir / rel
        if _nonempty(path):
            return path
    return None


def _render_artifact_violations(
    context: StoryVideoRunContext,
    manifest: dict[str, Any],
) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    violations: list[str] = []
    output = manifest.get("output")
    if not isinstance(output, dict):
        return ["primary render output metadata"], violations

    artifact = str(output.get("path") or "").strip()
    if not artifact:
        missing.append("primary render output path")
    elif not _nonempty(context.project_dir / artifact):
        missing.append(artifact)

    subtitles = output.get("subtitles")
    if not isinstance(subtitles, dict) or subtitles.get("hard_burned") is not True:
        violations.append("primary render has no hard-burned subtitles")

    motion_policy = str(
        (manifest.get("timeline") or {}).get("motion_policy") or ""
    ).lower()
    if "static" in motion_policy or not any(
        token in motion_policy for token in ("zoom", "pan", "motion")
    ):
        violations.append("primary render has no non-static motion policy")

    qc_rel = str(manifest.get("qc_report") or "render_qc.json").strip()
    qc = _load_json(context.project_dir / qc_rel)
    if not isinstance(qc, dict):
        missing.append(qc_rel)
        return missing, violations
    evidence = qc.get("artifact_quality_evidence") or {}
    caption = (
        evidence.get("caption_visibility") if isinstance(evidence, dict) else None
    )
    if not isinstance(caption, dict) or (
        str(caption.get("status") or "").upper() != "PASS"
        or caption.get("hard_burned") is not True
    ):
        violations.append("render QC lacks hard-burned subtitle evidence")
    motion = evidence.get("motion") if isinstance(evidence, dict) else None
    if not isinstance(motion, dict) or (
        str(motion.get("status") or "").upper() != "PASS"
    ):
        violations.append("render QC lacks non-static motion evidence")
    return missing, violations


def _validate_render(context: StoryVideoRunContext) -> PhaseProof:
    missing: list[str] = []
    violations: list[str] = []
    manifest_path = _render_manifest_path(context)
    manifest = _load_json(manifest_path) if manifest_path is not None else None
    if not isinstance(manifest, dict):
        missing.append("render_manifest.json")
    else:
        artifact_missing, artifact_violations = _render_artifact_violations(
            context, manifest
        )
        missing.extend(artifact_missing)
        violations.extend(artifact_violations)

    qc_rel = (
        str(manifest.get("qc_report") or "render_qc.json")
        if isinstance(manifest, dict)
        else "render_qc.json"
    )
    qc = _load_json(context.project_dir / qc_rel)
    if isinstance(qc, dict):
        provider_qc = (
            (qc.get("visual_source_contract") or {}).get("provider_qc")
            if isinstance(qc.get("visual_source_contract"), dict)
            else None
        )
        if provider_qc and str(provider_qc).upper() != "PASS":
            violations.append(f"provider_qc={provider_qc}")
    audit = ProviderAudit(context).validate()
    violations.extend(audit.violations)
    if audit.event_count == 0:
        violations.append("provider audit has no events")
    return PhaseProof(
        phase="render",
        ok=not missing and not violations,
        missing=tuple(missing),
        violations=tuple(violations),
    )


def validate_phase(context: StoryVideoRunContext) -> PhaseProof:
    validators = {
        "planning": _validate_planning,
        "keyframes": _validate_keyframes,
        "batch": _validate_batch,
        "voice": _validate_voice,
        "render": _validate_render,
        "complete": lambda current: PhaseProof(phase="complete", ok=True),
    }
    return validators[context.phase](context)


def _next_phase(phase: str) -> str:
    index = PHASES.index(phase)
    return PHASES[min(index + 1, len(PHASES) - 1)]


def _context_payload(context: StoryVideoRunContext) -> dict[str, Any]:
    return {
        "success": True,
        "run_id": context.run_id,
        "project_id": context.project_id,
        "project_dir": str(context.project_dir),
        "phase": context.phase,
        "status": context.status,
        "next_call": context.next_call,
        "provider_policy": context.provider_policy,
    }


def story_video_control(
    args: dict[str, Any],
    *,
    session_id: str = "",
    store: StoryVideoStateStore | None = None,
    **_: Any,
) -> str:
    state_store = store or StoryVideoStateStore()
    context = state_store.for_session(session_id)
    if context is None:
        return json.dumps(
            {
                "success": False,
                "error_type": "story_video_context_missing",
                "error": "No active story-video context for this session.",
            },
            ensure_ascii=False,
        )

    action = str(args.get("action") or "status").lower()
    if action == "repair":
        issue = str(args.get("repair_request") or "目前問題").strip()
        context = state_store.update(
            context,
            repair_request=issue,
            repair_phase=context.phase,
        )
        return json.dumps(_context_payload(context), ensure_ascii=False)
    if action == "validate":
        proof = validate_phase(context)
        payload = _context_payload(context)
        payload.update(
            {
                "success": proof.ok,
                "proof": proof.marker,
                "missing": list(proof.missing),
                "violations": list(proof.violations),
            }
        )
        if not proof.ok:
            detail = (proof.missing or proof.violations or (f"{proof.phase} proof",))[0]
            context = state_store.update(
                context,
                repair_request=f"補齊 {proof.phase}：{detail}",
                repair_phase=proof.phase,
            )
            payload.update(_context_payload(context))
            payload["success"] = False
            payload["proof"] = proof.marker
            payload["missing"] = list(proof.missing)
            payload["violations"] = list(proof.violations)
        if proof.ok and context.phase != "complete":
            context = state_store.update(
                context,
                phase=_next_phase(context.phase),
                last_validated_phase=proof.phase,
                repair_request="",
                repair_phase="",
                status="complete" if _next_phase(context.phase) == "complete" else "active",
            )
            payload.update(_context_payload(context))
            payload["proof"] = proof.marker
        return json.dumps(payload, ensure_ascii=False)
    return json.dumps(_context_payload(context), ensure_ascii=False)
