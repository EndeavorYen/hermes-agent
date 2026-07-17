from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .audit import ProviderAudit, normalize_provider
from .engagement import engagement_contract_enabled
from .quality import CLOSE_EVIDENCE_SCALES, QUALITY_THRESHOLD, validate_quality_ledger
from .review_board import (
    V6_QUALITY_CHECKS,
    content_profile_requires_child_curiosity,
    validate_v6_review_bundle,
)
from .state import PHASES, StoryVideoRunContext, StoryVideoStateStore
from .story_contract import story_contract_enabled, validate_story_script_bindings
from .voice_profiles import (
    VOICE_BINDING_NAME,
    VoiceProfileError,
    bind_project_voice_profile,
    inspect_project_voice_profile,
    list_voice_profiles,
)


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _sync_candidate_manifest_phase(context: StoryVideoRunContext) -> None:
    path = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    payload = _load_json(path)
    if not isinstance(payload, dict) or payload.get("phase") == context.phase:
        return
    payload["phase"] = context.phase
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _promote_legacy_scale_repeat_reasons(context: StoryVideoRunContext) -> None:
    """Promote the pre-contract scale-repeat alias without changing shot hashes."""
    path = context.project_dir / "scene_ledger.json"
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return
    changed = False
    for scene in payload.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        for shot in scene.get("shots") or []:
            if not isinstance(shot, dict):
                continue
            canonical = str(
                shot.get("intentional_scale_repeat_reason") or ""
            ).strip()
            legacy = str(shot.get("scale_repetition_reason") or "").strip()
            if not canonical and legacy:
                shot["intentional_scale_repeat_reason"] = legacy
                changed = True
    if not changed:
        return
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


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
    missing = [
        name for name in required if not _nonempty(context.project_dir / name)
    ]
    violations: list[str] = []
    script_text = ""
    if "script.md" not in missing:
        try:
            script_text = (context.project_dir / "script.md").read_text(
                encoding="utf-8"
            )
        except OSError:
            script_text = ""
        if not re.search(r"(?m)^###\s+S\d+\s*$", script_text):
            violations.append("script.md requires ### S00-style narration headings")
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
    ledger_quality_version = 0
    if isinstance(ledger, dict):
        try:
            ledger_quality_version = int(
                ledger.get("quality_contract_version") or 0
            )
        except (TypeError, ValueError):
            ledger_quality_version = 0
        violations.extend(validate_quality_ledger(ledger).violations)
        violations.extend(validate_story_script_bindings(ledger, script_text))
    if ledger_quality_version >= 6:
        for name in ("content_profile.json", "script_review_report.json"):
            path = context.project_dir / name
            if not _nonempty(path):
                missing.append(name)
                continue
            payload = _load_json(path)
            if payload is None:
                violations.append(f"{name} is not valid JSON")
            else:
                parsed[name] = payload
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
        required_checks = ["visual_evidence", "narrative_roles", "claim_confidence"]
        if isinstance(ledger, dict) and engagement_contract_enabled(ledger):
            if version < 3:
                violations.append("script_quality_report.quality_contract_version<3")
            required_checks.extend(("audience_engagement", "visual_truth"))
        if isinstance(ledger, dict) and story_contract_enabled(ledger):
            if version < 4:
                violations.append("script_quality_report.quality_contract_version<4")
            story_checks = [
                "dramatic_arc",
                "read_aloud_liveliness",
                "knowledge_integrity",
                "visual_causality",
                "style_consistency",
            ]
            if ledger_quality_version < 6 or content_profile_requires_child_curiosity(
                ledger, parsed.get("content_profile.json")
            ):
                story_checks.insert(0, "child_curiosity")
            required_checks.extend(story_checks)
        if ledger_quality_version >= 6:
            if version < 6:
                violations.append("script_quality_report.quality_contract_version<6")
            required_checks.extend(V6_QUALITY_CHECKS)
        elif isinstance(ledger, dict):
            if ledger_quality_version >= 5 and version < 5:
                violations.append("script_quality_report.quality_contract_version<5")
        if not isinstance(checks, dict) or any(
            str(checks.get(name) or "").upper() != "PASS" for name in required_checks
        ):
            violations.append("script_quality_report required checks are not PASS")
    if (
        ledger_quality_version >= 6
        and isinstance(ledger, dict)
        and isinstance(report, dict)
        and isinstance(parsed.get("content_profile.json"), dict)
        and isinstance(parsed.get("script_review_report.json"), dict)
    ):
        violations.extend(
            validate_v6_review_bundle(
                context.project_dir,
                ledger,
                report,
                parsed["content_profile.json"],
                parsed["script_review_report.json"],
            )
        )
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
                if (
                    str(entry.get("risk") or "").strip().lower() == "high"
                    and display
                    and spoken
                    and spoken != display
                    and spoken in script_text
                ):
                    violations.append(
                        f"script.md contains spoken alias for high-risk term: {display}"
                    )
    return PhaseProof(
        phase="planning",
        ok=not missing and not violations,
        missing=tuple(missing),
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
    canonical_outputs = isinstance(manifest.get("outputs"), list)
    selected = _selected_outputs(manifest) if canonical_outputs else []
    violations: list[str] = []
    if provider not in {"openai", "openai-codex"}:
        violations.append(f"source provider is {provider or '<missing>'}, not OpenAI")
    if not canonical_outputs:
        violations.append(
            "shot candidate manifest must contain canonical outputs[] from "
            "story_video_quality_control"
        )
    elif not selected:
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
    from .shot_contract import manifest_row_matches_shot_contract

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
    legacy_prompts = {
        str(row.get("shot_id") or ""): str(row.get("prompt") or "").strip()
        for row in (manifest.get("shots") if isinstance(manifest, dict) else []) or []
        if isinstance(row, dict) and str(row.get("shot_id") or "").strip()
    }
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
            if len(rows) == 1 and not manifest_row_matches_shot_contract(
                rows[0],
                shot,
                legacy_prompts.get(shot_id, ""),
            ):
                violations.append(
                    f"{shot_id} selected candidate uses superseded shot contract"
                )
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
        narration_schema = str(manifest.get("schema") or "")
        acoustic_contract = narration_schema in {
            "story_video_narration_manifest_v4",
            "story_video_narration_manifest_v5",
        }
        bound_voice_contract = narration_schema == "story_video_narration_manifest_v5"
        sentence_chunk_contract = (
            str(manifest.get("voice_segmentation") or "")
            == "sentence_chunks_v1"
        )
        if str(manifest.get("engine") or "") != "Qwen3-TTS via MLX-Audio":
            violations.append("production narration engine is not Qwen3-TTS via MLX-Audio")
        if str(manifest.get("inference_mode") or "") != "offline":
            violations.append("local Qwen narration inference_mode is not offline")
        if str(manifest.get("network_fallback") or "") != "forbidden":
            violations.append("local Qwen narration network fallback is not forbidden")
        if not str(manifest.get("model") or "").strip():
            missing.append("local Qwen narration model")
        profile_path: Path | None = None
        profile_value = str(manifest.get("voice_profile") or "").strip()
        if not profile_value:
            missing.append("local Qwen narration voice_profile")
        else:
            profile_path = Path(profile_value)
            if not profile_path.is_absolute():
                profile_path = context.project_dir / profile_path
            if not _nonempty(profile_path):
                missing.append("local Qwen narration voice_profile_file")
        if bound_voice_contract:
            binding_value = str(manifest.get("voice_profile_binding") or "").strip()
            binding_path: Path | None = None
            binding: dict[str, Any] | None = None
            if not binding_value:
                missing.append("local Qwen narration voice_profile_binding")
            else:
                binding_path = Path(binding_value)
                if not binding_path.is_absolute():
                    binding_path = context.project_dir / binding_path
                binding_payload = _load_json(binding_path)
                if not isinstance(binding_payload, dict):
                    missing.append("local Qwen narration voice_profile_binding_file")
                else:
                    binding = binding_payload
            if str(manifest.get("clone_mode") or "") != "full_icl":
                violations.append("local Qwen narration clone mode is not full_icl")
            if binding is not None and binding_path is not None:
                if binding_path.resolve() != (
                    context.project_dir / VOICE_BINDING_NAME
                ).resolve():
                    violations.append(
                        "local Qwen voice profile binding is not project-local"
                    )
                if binding.get("schema") != "story_video_voice_profile_binding_v1":
                    violations.append("local Qwen voice profile binding schema is invalid")
                if (
                    binding.get("status") != "locked"
                    or binding.get("voice_role") != "narrator"
                    or binding.get("language_policy") != "zh-TW"
                    or binding.get("clone_mode") != "full_icl"
                ):
                    violations.append("local Qwen voice profile binding policy is invalid")
                if str(manifest.get("voice_profile_binding_sha256") or "") != _sha256(
                    binding_path
                ):
                    violations.append("local Qwen voice profile binding hash mismatch")
                manifest_profile_id = str(
                    manifest.get("voice_profile_id") or ""
                ).strip()
                if not manifest_profile_id:
                    missing.append("local Qwen narration voice_profile_id")
                elif manifest_profile_id != str(binding.get("profile_id") or ""):
                    violations.append("local Qwen voice profile id does not match binding")
                if profile_path is not None and _nonempty(profile_path):
                    actual_profile_hash = _sha256(profile_path)
                    if (
                        str(manifest.get("voice_profile_sha256") or "")
                        != actual_profile_hash
                        or str(binding.get("profile_sha256") or "")
                        != actual_profile_hash
                    ):
                        violations.append(
                            "local Qwen voice profile hash does not match project binding"
                        )
                    bound_profile_path = Path(
                        str(binding.get("profile_path") or "")
                    ).expanduser()
                    if not bound_profile_path.is_absolute():
                        bound_profile_path = binding_path.parent / bound_profile_path
                    if bound_profile_path.resolve() != profile_path.resolve():
                        violations.append(
                            "local Qwen voice profile path does not match project binding"
                        )
        pronunciation_path = context.project_dir / "qc" / "pronunciation_qc_report.json"
        pronunciation_report = _load_json(pronunciation_path)
        if not isinstance(pronunciation_report, dict):
            missing.append("qc/pronunciation_qc_report.json")
        else:
            qc_schema = str(pronunciation_report.get("schema") or "")
            if qc_schema not in {
                "story_video_pronunciation_qc_v1",
                "story_video_pronunciation_qc_v2",
                "story_video_pronunciation_qc_v3",
            }:
                violations.append("local Qwen pronunciation QC schema is invalid")
            if str(pronunciation_report.get("status") or "").upper() != "PASS":
                violations.append("local Qwen pronunciation QC is not PASS")
            if acoustic_contract:
                if qc_schema != "story_video_pronunciation_qc_v3":
                    violations.append("local Qwen acoustic pronunciation QC is not v3")
                if (
                    str(pronunciation_report.get("method") or "")
                    != "sentence_chunk_plus_forced_alignment_isolated_term_asr"
                ):
                    violations.append(
                        "local Qwen acoustic pronunciation QC lacks isolated term ASR"
                    )
                if sentence_chunk_contract and (
                    str(pronunciation_report.get("method") or "")
                    != "sentence_chunk_plus_forced_alignment_isolated_term_asr"
                    or str(pronunciation_report.get("checked_unit") or "")
                    != "voice_chunk"
                ):
                    violations.append(
                        "local Qwen pronunciation QC lacks sentence chunk evidence"
                    )
                evidence = pronunciation_report.get("acoustic_evidence")
                if not isinstance(evidence, list) or not evidence:
                    missing.append("local Qwen acoustic pronunciation evidence")
                elif qc_schema == "story_video_pronunciation_qc_v3":
                    term_checks = [
                        check
                        for row in evidence
                        if isinstance(row, dict)
                        for check in row.get("term_checks") or []
                        if isinstance(check, dict)
                    ]
                    if any(
                        str(check.get("status") or "").upper() != "PASS"
                        or str(check.get("method") or "")
                        != "forced_alignment_isolated_term_asr"
                        for check in term_checks
                    ):
                        violations.append(
                            "local Qwen isolated pronunciation term QC is not PASS"
                        )
                    required_terms = {
                        str(entry.get("display") or "").strip()
                        for entry in pronunciation_report.get("applied_entries") or []
                        if isinstance(entry, dict)
                        and str(entry.get("risk") or "").lower() == "high"
                    }
                    checked_terms = {
                        str(check.get("display") or "").strip()
                        for check in term_checks
                        if str(check.get("status") or "").upper() == "PASS"
                    }
                    if required_terms - checked_terms:
                        violations.append(
                            "local Qwen pronunciation QC lacks isolated high-risk term evidence"
                        )
        if str(manifest.get("pronunciation_status") or "").upper() != "PASS":
            violations.append("local Qwen narration pronunciation status is not PASS")
        if acoustic_contract:
            for gate in ("alignment_status", "prosody_status"):
                if str(manifest.get(gate) or "").upper() != "PASS":
                    violations.append(f"local Qwen narration {gate} is not PASS")
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
                if acoustic_contract:
                    segments = output.get("segments")
                    if not isinstance(segments, list) or not segments:
                        missing.append(f"audio narration segment[{index}].segments")
                    else:
                        for segment_index, segment in enumerate(segments):
                            if not isinstance(segment, dict):
                                missing.append(
                                    f"audio narration segment[{index}].segments[{segment_index}]"
                                )
                                continue
                            if float(segment.get("timeline_duration_sec") or 0.0) <= 0:
                                missing.append(
                                    f"audio narration segment[{index}].segments[{segment_index}].timeline_duration_sec"
                                )
                            for gate in (
                                "alignment_status",
                                "pronunciation_status",
                                "prosody_status",
                            ):
                                if str(segment.get(gate) or "").upper() != "PASS":
                                    violations.append(
                                        f"audio narration segment[{index}].segments[{segment_index}] "
                                        f"{gate.removesuffix('_status')} is not PASS"
                                    )
                            if sentence_chunk_contract:
                                voice_chunks = segment.get("voice_chunks")
                                if not isinstance(voice_chunks, list) or not voice_chunks:
                                    missing.append(
                                        f"audio narration segment[{index}].segments[{segment_index}].voice_chunks"
                                    )
                                    continue
                                for chunk_index, chunk in enumerate(voice_chunks):
                                    if not isinstance(chunk, dict):
                                        missing.append(
                                            f"audio narration segment[{index}].segments[{segment_index}].voice_chunks[{chunk_index}]"
                                        )
                                        continue
                                    if not str(chunk.get("voice_chunk_id") or "").strip():
                                        missing.append(
                                            f"audio narration segment[{index}].segments[{segment_index}].voice_chunks[{chunk_index}].voice_chunk_id"
                                        )
                                    for gate in (
                                        "alignment_status",
                                        "pronunciation_status",
                                        "prosody_status",
                                    ):
                                        if str(chunk.get(gate) or "").upper() != "PASS":
                                            violations.append(
                                                f"audio narration segment[{index}].segments[{segment_index}].voice_chunks[{chunk_index}] "
                                                f"{gate.removesuffix('_status')} is not PASS"
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


def _shot_density_evidence_passes(
    timeline: dict[str, Any],
    evidence: dict[str, Any],
) -> bool:
    selected_shot_count = evidence.get(
        "selected_shot_count",
        timeline.get("selected_shot_count"),
    )
    if not isinstance(selected_shot_count, int) or selected_shot_count <= 0:
        return False
    if str(evidence.get("status") or "").upper() == "PASS":
        return True
    rate = evidence.get(
        "selected_shots_per_minute",
        timeline.get("selected_shots_per_minute"),
    )
    preferred = timeline.get("preferred_shots_per_minute")
    hard = timeline.get("hard_shots_per_minute")
    if not isinstance(rate, (int, float)) or not isinstance(preferred, dict):
        return False
    if not isinstance(hard, dict):
        hard = {
            "minimum": float(preferred.get("minimum") or 0.0) * 0.9,
            "maximum": float(preferred.get("maximum") or 0.0) * 1.1,
        }
    minimum = float(hard.get("minimum") or 0.0)
    maximum = float(hard.get("maximum") or 0.0)
    return minimum > 0 and minimum <= float(rate) <= maximum


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
        token in motion_policy
        for token in ("zoom", "pan", "motion", "focus_push", "center_zoom")
    ):
        violations.append("primary render has no non-static motion policy")
    timeline = manifest.get("timeline")
    if not isinstance(timeline, dict) or not _shot_density_evidence_passes(
        timeline,
        {
            "status": timeline.get("shot_density_status"),
            "selected_shot_count": timeline.get("selected_shot_count"),
            "selected_shots_per_minute": timeline.get(
                "selected_shots_per_minute"
            ),
        },
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
    if not isinstance(shot_density, dict) or not _shot_density_evidence_passes(
        timeline,
        shot_density,
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
        "auto_mode": context.auto_mode,
        "next_call": context.next_call,
        "provider_policy": context.provider_policy,
    }


def story_video_control(
    args: dict[str, Any],
    *,
    session_id: str = "",
    store: StoryVideoStateStore | None = None,
    voice_registry_path: str | Path | None = None,
    voice_active_profile_path: str | Path | None = None,
    **_: Any,
) -> str:
    state_store = store or StoryVideoStateStore()
    action = str(args.get("action") or "status").lower()
    profile_kwargs: dict[str, Any] = {}
    if voice_registry_path is not None:
        profile_kwargs["registry_path"] = voice_registry_path
    if voice_active_profile_path is not None:
        profile_kwargs["active_profile_path"] = voice_active_profile_path

    if action == "list_voices":
        try:
            payload = list_voice_profiles(**profile_kwargs)
        except VoiceProfileError as exc:
            payload = {
                "success": False,
                "error_type": exc.error_type,
                "error": str(exc),
            }
        else:
            payload.update({"success": True, "action": action})
        return json.dumps(payload, ensure_ascii=False)

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

    _sync_candidate_manifest_phase(context)

    if action == "select_voice":
        voice_id = str(args.get("voice_id") or "").strip()
        if not voice_id:
            return json.dumps(
                {
                    "success": False,
                    "error_type": "voice_profile_id_required",
                    "error": "select_voice requires voice_id.",
                },
                ensure_ascii=False,
            )
        try:
            selection = bind_project_voice_profile(
                context.project_dir,
                profile_id=voice_id,
                **profile_kwargs,
            )
        except VoiceProfileError as exc:
            return json.dumps(
                {
                    "success": False,
                    "error_type": exc.error_type,
                    "error": str(exc),
                },
                ensure_ascii=False,
            )
        payload = _context_payload(context)
        payload.update(
            {
                "action": action,
                "profile_id": selection.profile_id,
                "voice_profile": str(selection.profile_path),
                "profile_sha256": selection.profile_sha256,
                "binding_path": str(selection.binding_path),
                "binding_sha256": selection.binding_sha256,
                "clone_mode": selection.clone_mode,
            }
        )
        return json.dumps(payload, ensure_ascii=False)
    if action == "voice_status":
        try:
            payload = inspect_project_voice_profile(
                context.project_dir,
                **profile_kwargs,
            )
        except VoiceProfileError as exc:
            payload = {
                "success": False,
                "error_type": exc.error_type,
                "error": str(exc),
            }
        else:
            payload.update({"success": True, "action": action})
        return json.dumps(payload, ensure_ascii=False)
    if action == "repair":
        issue = str(args.get("repair_request") or "目前問題").strip()
        context = state_store.update(
            context,
            repair_request=issue,
            repair_phase=context.phase,
        )
        return json.dumps(_context_payload(context), ensure_ascii=False)
    if action == "validate":
        if context.phase == "batch":
            _promote_legacy_scale_repeat_reasons(context)
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
        if proof.ok and context.phase == "planning" and context.planning_only:
            context = state_store.update(
                context,
                last_validated_phase=proof.phase,
                repair_request="",
                repair_phase="",
                status="complete",
            )
            payload.update(_context_payload(context))
            payload["proof"] = proof.marker
        elif proof.ok and context.phase != "complete":
            context = state_store.update(
                context,
                phase=_next_phase(context.phase),
                last_validated_phase=proof.phase,
                repair_request="",
                repair_phase="",
                status="complete" if _next_phase(context.phase) == "complete" else "active",
            )
            _sync_candidate_manifest_phase(context)
            payload.update(_context_payload(context))
            payload["proof"] = proof.marker
        return json.dumps(payload, ensure_ascii=False)
    return json.dumps(_context_payload(context), ensure_ascii=False)
