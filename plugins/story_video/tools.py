from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .audit import ProviderAudit, normalize_provider
from .quality import CLOSE_EVIDENCE_SCALES, QUALITY_THRESHOLD, validate_quality_ledger
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
        "script.md",
        "storyboard.md",
        "scene_ledger.json",
        "production_checklist.json",
        "script_quality_report.json",
        "pronunciation_lexicon.json",
    )
    missing = tuple(
        name for name in required if not _nonempty(context.project_dir / name)
    )
    violations: list[str] = []
    parsed: dict[str, Any] = {}
    for name in (
        "scene_ledger.json",
        "production_checklist.json",
        "script_quality_report.json",
        "pronunciation_lexicon.json",
    ):
        path = context.project_dir / name
        if name in missing:
            continue
        payload = _load_json(path)
        if payload is None:
            violations.append(f"{name} is not valid JSON")
        else:
            parsed[name] = payload
    ledger = parsed.get("scene_ledger.json")
    if isinstance(ledger, dict):
        violations.extend(validate_quality_ledger(ledger).violations)
    report = parsed.get("script_quality_report.json")
    if isinstance(report, dict):
        status = str(report.get("status") or "").upper()
        if status != "PASS":
            violations.append(f"script_quality_report.status={status or '<missing>'}")
        try:
            version = int(report.get("quality_contract_version"))
        except (TypeError, ValueError):
            version = 0
        if version < 2:
            violations.append("script_quality_report.quality_contract_version<2")
        checks = report.get("checks")
        required_checks = ("visual_evidence", "narrative_roles", "claim_confidence")
        if not isinstance(checks, dict) or any(
            str(checks.get(name) or "").upper() != "PASS" for name in required_checks
        ):
            violations.append("script_quality_report required checks are not PASS")
    pronunciation = parsed.get("pronunciation_lexicon.json")
    if isinstance(pronunciation, dict):
        if (
            str(pronunciation.get("schema") or "")
            != "story_video_pronunciation_lexicon_v1"
        ):
            violations.append("pronunciation_lexicon schema is invalid")
        if str(pronunciation.get("language") or "") != "zh-TW":
            violations.append("pronunciation_lexicon language is not zh-TW")
        if str(pronunciation.get("review_status") or "").upper() != "PASS":
            violations.append("pronunciation_lexicon review_status is not PASS")
        entries = pronunciation.get("entries")
        if not isinstance(entries, list):
            violations.append("pronunciation_lexicon entries are not a list")
        else:
            for index, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    violations.append(
                        f"pronunciation_lexicon entry[{index}] is not an object"
                    )
                    continue
                display = str(entry.get("display") or "").strip()
                spoken = str(entry.get("spoken") or "").strip()
                expected_pinyin = str(entry.get("expected_pinyin") or "").strip()
                source = str(entry.get("source") or "").strip()
                if not display or not spoken:
                    violations.append(
                        f"pronunciation_lexicon entry[{index}] requires display and spoken"
                    )
                if not expected_pinyin:
                    violations.append(
                        f"pronunciation_lexicon entry[{index}] expected_pinyin is missing"
                    )
                if not source:
                    violations.append(
                        f"pronunciation_lexicon entry[{index}] source is missing"
                    )
                if (
                    str(entry.get("risk") or "").strip().lower() == "high"
                    and display
                    and spoken == display
                ):
                    violations.append(
                        f"pronunciation_lexicon entry[{index}] high-risk spoken alias is unchanged"
                    )
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
    rel = "manifests/shot_candidate_manifest.json"
    manifest = _load_json(context.project_dir / rel)
    if not isinstance(manifest, dict):
        return PhaseProof(phase="keyframes", ok=False, missing=(rel,))
    provider = normalize_provider(manifest.get("provider"))
    judge_provider = normalize_provider(manifest.get("judge_provider"))
    selected = _selected_outputs(manifest)
    violations: list[str] = []
    if provider not in {"openai", "openai-codex"}:
        violations.append(f"source provider is {provider or '<missing>'}, not OpenAI")
    if not selected:
        violations.append("no selected current keyframe output")
    if judge_provider not in {"openai", "openai-codex"}:
        violations.append(
            f"keyframe judge provider is {judge_provider or '<missing>'}, not OpenAI"
        )
    evidence_missing = False
    scales: set[str] = set()
    close_evidence = False
    for output in selected:
        output_provider = normalize_provider(output.get("provider"))
        output_judge = normalize_provider(output.get("judge_provider"))
        prompt_path = str(output.get("prompt_path") or "").strip()
        local_path = str(output.get("local_path") or "").strip()
        vision = output.get("vision_evidence")
        blockers = output.get("hard_blockers")
        try:
            score = float(output.get("quality_score"))
        except (TypeError, ValueError):
            score = 0.0
        if (
            output_provider not in {"openai", "openai-codex"}
            or output_judge not in {"openai", "openai-codex"}
            or score < QUALITY_THRESHOLD
            or not prompt_path
            or not _nonempty(context.project_dir / prompt_path)
            or not local_path
            or not _nonempty(context.project_dir / local_path)
            or not isinstance(blockers, list)
            or bool(blockers)
            or not isinstance(vision, dict)
            or str(vision.get("status") or "").upper() != "PASS"
            or not str(vision.get("response_id") or "").strip()
        ):
            evidence_missing = True
        scale = str(output.get("shot_scale") or "").strip().lower()
        if scale:
            scales.add(scale)
        if scale in CLOSE_EVIDENCE_SCALES:
            close_evidence = True
    if evidence_missing:
        violations.append("selected keyframe missing OpenAI vision score evidence")
    if selected and (len(scales) < 2 or not close_evidence):
        violations.append("keyframes do not prove representative shot-scale coverage")
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
    quality = validate_quality_ledger(ledger if isinstance(ledger, dict) else {})
    violations: list[str] = list(quality.violations)
    manifest = _load_json(
        context.project_dir / "manifests" / "shot_candidate_manifest.json"
    )
    outputs = (
        manifest.get("outputs")
        if isinstance(manifest, dict) and isinstance(manifest.get("outputs"), list)
        else []
    )
    selected_by_shot: dict[str, list[dict[str, Any]]] = {}
    for output in outputs:
        if not isinstance(output, dict) or output.get("selected") is not True:
            continue
        shot_id = str(output.get("shot_id") or "").strip()
        if shot_id:
            selected_by_shot.setdefault(shot_id, []).append(output)

    missing: list[str] = []
    selected_paths: list[Path] = []
    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            missing.append(f"scene[{index}].shots")
            continue
        scene_id = str(scene.get("scene_id") or index)
        shots = scene.get("shots")
        if not isinstance(shots, list):
            missing.append(f"{scene_id}.shots")
            continue
        for shot_index, shot in enumerate(shots):
            if not isinstance(shot, dict):
                missing.append(f"{scene_id}.shot[{shot_index}].selected_asset")
                continue
            shot_id = str(shot.get("shot_id") or f"{scene_id}_SH{shot_index:02d}")
            rows = selected_by_shot.get(shot_id, [])
            if len(rows) > 1:
                violations.append(f"{shot_id} has multiple selected candidates")
            asset = shot.get("selected_asset_path") or shot.get("selected_asset")
            if not asset and len(rows) == 1:
                asset = rows[0].get("local_path")
            if not asset:
                missing.append(f"{shot_id}.selected_asset")
                continue
            path = Path(str(asset))
            if not path.is_absolute():
                path = context.project_dir / path
            if not _nonempty(path):
                missing.append(f"{shot_id}.selected_asset_file")
                continue
            selected_paths.append(path.resolve())
            if len(rows) != 1:
                violations.append(f"{shot_id} lacks exactly one selected candidate audit row")
    if len(selected_paths) != len(set(selected_paths)):
        violations.append("duplicate selected asset files")
    return PhaseProof(
        phase="batch",
        ok=not missing and not violations,
        missing=tuple(missing),
        violations=tuple(violations),
    )


def _validate_voice(context: StoryVideoRunContext) -> PhaseProof:
    manifest_path = context.project_dir / "manifests" / "narration_manifest.json"
    manifest = _load_json(manifest_path)
    if not isinstance(manifest, dict):
        return PhaseProof(
            phase="voice",
            ok=False,
            missing=("manifests/narration_manifest.json",),
        )

    missing: list[str] = []
    violations: list[str] = []
    provider = normalize_provider(str(manifest.get("provider") or ""))
    allowed_providers = tuple(
        normalize_provider(value)
        for value in context.provider_policy.get("tts", [])
        if normalize_provider(value)
    )
    expected = ", ".join(allowed_providers) or "<missing-policy>"
    if provider not in allowed_providers:
        violations.append(
            f"production narration provider is {provider or '<missing>'}, expected {expected}"
        )
    if provider == "azure" and str(manifest.get("engine") or "") != "Azure AI Speech":
        violations.append("production narration engine is not Azure AI Speech")
    if provider == "local-qwen":
        if str(manifest.get("engine") or "") != "Qwen3-TTS via MLX-Audio":
            violations.append("production narration engine is not Qwen3-TTS via MLX-Audio")
        if str(manifest.get("inference_mode") or "") != "offline":
            violations.append("local Qwen narration inference_mode is not offline")
        if str(manifest.get("network_fallback") or "") != "forbidden":
            violations.append("local Qwen narration network fallback is not forbidden")
        if not str(manifest.get("model") or "").strip():
            missing.append("local Qwen narration model")
        profile_value = str(manifest.get("voice_profile") or "").strip()
        if not profile_value:
            missing.append("local Qwen narration voice_profile")
        else:
            profile_path = Path(profile_value)
            if not profile_path.is_absolute():
                profile_path = context.project_dir / profile_path
            if not _nonempty(profile_path):
                missing.append("local Qwen narration voice_profile_file")
        pronunciation_path = context.project_dir / "qc" / "pronunciation_qc_report.json"
        pronunciation_report = _load_json(pronunciation_path)
        if not isinstance(pronunciation_report, dict):
            missing.append("qc/pronunciation_qc_report.json")
        else:
            if (
                str(pronunciation_report.get("schema") or "")
                != "story_video_pronunciation_qc_v1"
            ):
                violations.append("local Qwen pronunciation QC schema is invalid")
            if str(pronunciation_report.get("status") or "").upper() != "PASS":
                violations.append("local Qwen pronunciation QC is not PASS")
        if str(manifest.get("pronunciation_status") or "").upper() != "PASS":
            violations.append("local Qwen narration pronunciation status is not PASS")
    if str(manifest.get("language") or "") != "zh-TW":
        violations.append("production narration language is not zh-TW")
    if str(manifest.get("profile_status") or "") != "locked_by_user":
        violations.append("production narration profile is not locked_by_user")
    if str(manifest.get("voice_contract_status") or "").upper() != "PASS":
        violations.append("production narration voice contract is not PASS")
    if not str(manifest.get("voice") or "").strip():
        missing.append("narration voice")
    if not str(manifest.get("rate") or "").strip():
        missing.append("narration rate")

    outputs = manifest.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        missing.append("audio narration segments")
    else:
        for index, output in enumerate(outputs):
            if not isinstance(output, dict):
                missing.append(f"audio narration segment[{index}]")
                continue
            if provider == "local-qwen":
                if not str(output.get("display_text") or "").strip():
                    missing.append(f"audio narration segment[{index}].display_text")
                if not str(output.get("spoken_text") or "").strip():
                    missing.append(f"audio narration segment[{index}].spoken_text")
                if str(output.get("pronunciation_status") or "").upper() != "PASS":
                    violations.append(
                        f"audio narration segment[{index}] pronunciation is not PASS"
                    )
            audio = str(output.get("audio") or "").strip()
            if not audio:
                missing.append(f"audio narration segment[{index}].audio")
                continue
            audio_path = Path(audio)
            if not audio_path.is_absolute():
                audio_path = context.project_dir / audio_path
            if not _nonempty(audio_path):
                missing.append(f"audio narration segment[{index}].audio_file")

    return PhaseProof(
        phase="voice",
        ok=not missing and not violations,
        missing=tuple(missing),
        violations=tuple(violations),
    )


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
    timeline = manifest.get("timeline")
    if not isinstance(timeline, dict) or (
        str(timeline.get("shot_density_status") or "").upper() != "PASS"
        or not isinstance(timeline.get("selected_shot_count"), int)
        or int(timeline.get("selected_shot_count") or 0) <= 0
    ):
        violations.append("render manifest lacks selected-shot density evidence")
    cards = manifest.get("cards")
    if not isinstance(cards, dict) or not isinstance(
        cards.get("opening"), dict
    ) or not isinstance(cards.get("ending"), dict):
        violations.append("render manifest lacks opening and ending cards")

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
    shot_density = evidence.get("shot_density") if isinstance(evidence, dict) else None
    if not isinstance(shot_density, dict) or (
        str(shot_density.get("status") or "").upper() != "PASS"
        or not isinstance(shot_density.get("selected_shot_count"), int)
        or int(shot_density.get("selected_shot_count") or 0) <= 0
    ):
        violations.append("render QC lacks selected-shot density evidence")
    title_cards = evidence.get("title_cards") if isinstance(evidence, dict) else None
    if not isinstance(title_cards, dict) or (
        str(title_cards.get("status") or "").upper() != "PASS"
        or title_cards.get("opening") is not True
        or title_cards.get("ending") is not True
    ):
        violations.append("render QC lacks opening and ending card evidence")
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
