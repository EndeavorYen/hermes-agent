from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .dubbing import DubbingContractError, compile_dubbing_project, inspect_dubbing_project
from .state import StoryVideoRunContext
from .voice_profiles import VoiceProfileError


SOURCE_PASSTHROUGH_SCHEMA = "story_video_source_passthrough_v1"
SOURCE_PASSTHROUGH_POLICY = "adult-explicit-local-passthrough-v1"
_ADULT_MARKER_RE = re.compile(
    r"(?:\bnsfw\b|成人(?:內容|内容)|成人劇本|成人剧本|露骨)", re.IGNORECASE
)
_FENCE_RE = re.compile(
    r"```(?P<header>[^\n`]*)\n?(?P<body>.*?)```",
    re.DOTALL,
)
_SPEAKER_LINE_RE = re.compile(r"^\s*([^：:\n]{1,32})\s*[：:]\s*(.*?)\s*$")
_ACTION_RE = re.compile(r"^\s*\[([^\]]*)\]\s*")
_QUOTED_RE = re.compile(r"[「『\"](?P<text>.*?)[」』\"]")
_SCENE_RE = re.compile(r"^\s*【[^】]+】\s*$")


@dataclass(frozen=True)
class ExtractedScreenplay:
    text: str
    deduplicated_blocks: int


@dataclass(frozen=True)
class ParsedScreenplay:
    speakers: tuple[dict[str, Any], ...]
    utterances: tuple[dict[str, Any], ...]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    _write_text_atomic(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )


def _screenplay_score(text: str) -> tuple[int, int]:
    speaker_lines = sum(
        1 for line in text.splitlines() if _SPEAKER_LINE_RE.match(line)
    )
    return speaker_lines, len(text)


def extract_user_screenplay(request: str) -> ExtractedScreenplay:
    candidates: list[str] = []
    for match in _FENCE_RE.finditer(str(request or "")):
        header = match.group("header").strip()
        body = match.group("body")
        if header.casefold() in {"text", "txt", "markdown", "md"}:
            candidate = body.strip()
        else:
            candidate = (header + ("\n" if header and body else "") + body).strip()
        if candidate:
            candidates.append(candidate)
    if not candidates:
        raise ValueError("user-supplied screenplay requires a fenced text block")
    unique: list[str] = []
    fingerprints: set[str] = set()
    for candidate in candidates:
        fingerprint = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
        if fingerprint in fingerprints:
            continue
        fingerprints.add(fingerprint)
        unique.append(candidate)
    collapsed: list[str] = []
    for candidate in sorted(unique, key=len, reverse=True):
        if any(
            candidate in kept and len(candidate) / max(len(kept), 1) >= 0.95
            for kept in collapsed
        ):
            continue
        collapsed.append(candidate)
    selected = max(collapsed, key=_screenplay_score)
    return ExtractedScreenplay(
        text=selected.rstrip() + "\n",
        deduplicated_blocks=len(candidates) - len(collapsed),
    )


def _voice_for_speaker(request: str, speaker: str) -> str:
    match = re.search(
        rf"{re.escape(speaker)}\s*用\s*([A-Za-z][A-Za-z0-9_-]*)",
        str(request or ""),
        re.IGNORECASE,
    )
    if match is None:
        raise ValueError(f"missing explicit voice mapping for speaker: {speaker}")
    return match.group(1)


def parse_user_screenplay(source_text: str, request: str) -> ParsedScreenplay:
    source = str(source_text or "")
    utterances: list[dict[str, Any]] = []
    scene_number = 0
    scene_id = "SCENE-001"
    cursor = 0
    for raw_line in source.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        if _SCENE_RE.match(line):
            scene_number += 1
            scene_id = f"SCENE-{scene_number:03d}"
            cursor += len(raw_line)
            continue
        match = _SPEAKER_LINE_RE.match(line)
        if match is None:
            cursor += len(raw_line)
            continue
        speaker = match.group(1).strip()
        remainder = match.group(2)
        action_match = _ACTION_RE.match(remainder)
        action = action_match.group(1).strip() if action_match is not None else ""
        quoted = _QUOTED_RE.search(remainder)
        if quoted is not None:
            spoken = quoted.group("text")
            spoken_offset = line.find(spoken)
        elif speaker.casefold() in {"旁白", "narrator"} and action:
            spoken = action
            spoken_offset = line.find(action)
            action = ""
        else:
            cursor += len(raw_line)
            continue
        if not spoken.strip() or spoken_offset < 0:
            cursor += len(raw_line)
            continue
        utterance_number = len(utterances) + 1
        row: dict[str, Any] = {
            "utterance_id": f"U{utterance_number:04d}",
            "scene_id": scene_id,
            "shot_id": f"SHOT-{utterance_number:04d}",
            "speaker_id": speaker,
            "display_text": spoken,
            "emotion": "neutral",
            "pace": "natural",
            "source_refs": [
                {
                    "start": cursor + spoken_offset,
                    "end": cursor + spoken_offset + len(spoken),
                }
            ],
        }
        if action:
            row["action"] = action
        utterances.append(row)
        cursor += len(raw_line)
    if not utterances:
        spoken = source.strip()
        if not spoken:
            raise ValueError("screenplay contains no spoken narration or dialogue")
        start = source.find(spoken)
        utterances.append(
            {
                "utterance_id": "U0001",
                "scene_id": "SCENE-001",
                "shot_id": "SHOT-0001",
                "speaker_id": "旁白",
                "display_text": spoken,
                "emotion": "neutral",
                "pace": "natural",
                "source_refs": [{"start": start, "end": start + len(spoken)}],
            }
        )
    spoken_speakers = list(
        dict.fromkeys(str(row["speaker_id"]) for row in utterances)
    )
    speakers: list[dict[str, Any]] = []
    lead_assigned = False
    for speaker in spoken_speakers:
        is_narrator = speaker.casefold() in {"旁白", "narrator"}
        role = "narrator" if is_narrator else "supporting"
        if not is_narrator and not lead_assigned:
            role = "lead"
            lead_assigned = True
        speakers.append(
            {
                "speaker_id": speaker,
                "display_name": speaker,
                "role": role,
                "voice_id": _voice_for_speaker(request, speaker),
            }
        )
    return ParsedScreenplay(
        speakers=tuple(speakers),
        utterances=tuple(utterances),
    )


def is_local_adult_passthrough_request(context: StoryVideoRunContext) -> bool:
    if str(getattr(context, "visual_mode", "story_visual")) != "black_subtitle":
        return False
    if _ADULT_MARKER_RE.search(str(getattr(context, "original_request", "") or "")) is None:
        return False
    raw_policy = getattr(context, "provider_policy", {})
    policy = raw_policy if isinstance(raw_policy, dict) else {}
    return (
        policy.get("image") == []
        and policy.get("tts") == ["local-qwen"]
        and policy.get("render") == ["local"]
    )


def adult_source_request_detected(text: str) -> bool:
    return _ADULT_MARKER_RE.search(str(text or "")) is not None


def _script_text(parsed: ParsedScreenplay) -> str:
    sections: list[str] = []
    for index, utterance in enumerate(parsed.utterances):
        speaker = str(utterance["speaker_id"])
        action = str(utterance.get("action") or "").strip()
        label = f"{speaker}（{action}）" if action else speaker
        sections.extend(
            (
                f"### S{index:03d}",
                "",
                f"{label}：『{utterance['display_text']}』",
                "",
            )
        )
    return "\n".join(sections).rstrip() + "\n"


def prepare_local_adult_passthrough(
    context: StoryVideoRunContext,
) -> dict[str, Any]:
    if not is_local_adult_passthrough_request(context):
        raise ValueError(
            "adult source passthrough requires black_subtitle with local Qwen/local render"
        )
    extracted = extract_user_screenplay(context.original_request)
    parsed = parse_user_screenplay(extracted.text, context.original_request)
    project = context.project_dir.expanduser().resolve()
    source_path = project / "source_screenplay.txt"
    script_path = project / "script.md"
    _write_text_atomic(source_path, extracted.text)
    _write_text_atomic(script_path, _script_text(parsed))
    source_sha = _sha256_bytes(source_path.read_bytes())
    script_sha = _sha256_bytes(script_path.read_bytes())

    compile_result = compile_dubbing_project(
        project,
        mode="remake",
        source_text=extracted.text,
        speakers=list(parsed.speakers),
        utterances=list(parsed.utterances),
        content_rating="adult_explicit",
    )
    profile = {
        "schema": "story_video_content_profile_v1",
        "rating": "adult_explicit",
        "activation_status": "active",
        "minimum_viewer_age": 18,
        "policy_profile_id": SOURCE_PASSTHROUGH_POLICY,
        "writer_profile_id": "user-supplied-source-passthrough-v1",
        "review_profile_id": "deterministic-source-integrity-v1",
        "provider_capability_status": "available",
        "source_policy": "verbatim-user-supplied-screenplay",
        "visual_policy": "black-subtitle-only",
        "generation_policy": "no-expansion",
    }
    _write_json_atomic(project / "content_profile.json", profile)
    _write_json_atomic(
        project / "pronunciation_lexicon.json",
        {
            "schema": "story_video_pronunciation_lexicon_v1",
            "language": "zh-TW",
            "review_status": "PASS",
            "entries": [],
        },
    )
    manifest = {
        "schema": SOURCE_PASSTHROUGH_SCHEMA,
        "status": "PASS",
        "run_id": context.run_id,
        "mode": "user-supplied-screenplay",
        "rating": "adult_explicit",
        "source_path": str(source_path),
        "source_sha256": source_sha,
        "script_path": str(script_path),
        "script_sha256": script_sha,
        "deduplicated_blocks": extracted.deduplicated_blocks,
        "speaker_count": len(parsed.speakers),
        "utterance_count": len(parsed.utterances),
        "image_generation": "forbidden",
        "tts_provider": "local-qwen",
        "render_provider": "local",
        "content_profile_id": SOURCE_PASSTHROUGH_POLICY,
    }
    _write_json_atomic(project / "source_passthrough_manifest.json", manifest)
    return {**manifest, **compile_result}


def validate_local_adult_passthrough(
    context: StoryVideoRunContext,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    project = context.project_dir.expanduser().resolve()
    required = (
        "source_passthrough_manifest.json",
        "source_screenplay.txt",
        "script.md",
        "content_profile.json",
        "pronunciation_lexicon.json",
        "story_mode.json",
        "cast_bible.json",
        "dialogue_ledger.json",
    )
    missing = tuple(name for name in required if not (project / name).is_file())
    if missing:
        return missing, ()
    violations: list[str] = []
    try:
        manifest = json.loads(
            (project / "source_passthrough_manifest.json").read_text(encoding="utf-8")
        )
        profile = json.loads(
            (project / "content_profile.json").read_text(encoding="utf-8")
        )
        pronunciation = json.loads(
            (project / "pronunciation_lexicon.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return (), ("adult source passthrough metadata is invalid JSON",)
    expected_profile = {
        "schema": "story_video_content_profile_v1",
        "rating": "adult_explicit",
        "activation_status": "active",
        "minimum_viewer_age": 18,
        "policy_profile_id": SOURCE_PASSTHROUGH_POLICY,
        "writer_profile_id": "user-supplied-source-passthrough-v1",
        "review_profile_id": "deterministic-source-integrity-v1",
        "provider_capability_status": "available",
        "source_policy": "verbatim-user-supplied-screenplay",
        "visual_policy": "black-subtitle-only",
        "generation_policy": "no-expansion",
    }
    if profile != expected_profile:
        violations.append("adult source passthrough content_profile is not exact")
    if not is_local_adult_passthrough_request(context):
        violations.append("adult source passthrough local-only policy is not satisfied")
    if manifest.get("schema") != SOURCE_PASSTHROUGH_SCHEMA or manifest.get("status") != "PASS":
        violations.append("adult source passthrough manifest is invalid")
    if manifest.get("run_id") != context.run_id:
        violations.append("adult source passthrough manifest run identity mismatch")
    expected_manifest_fields = {
        "mode": "user-supplied-screenplay",
        "rating": "adult_explicit",
        "source_path": str(project / "source_screenplay.txt"),
        "script_path": str(project / "script.md"),
        "image_generation": "forbidden",
        "tts_provider": "local-qwen",
        "render_provider": "local",
        "content_profile_id": SOURCE_PASSTHROUGH_POLICY,
    }
    for field, expected in expected_manifest_fields.items():
        if manifest.get(field) != expected:
            violations.append(f"adult source passthrough manifest {field} mismatch")
    if not (
        isinstance(pronunciation, dict)
        and pronunciation.get("schema") == "story_video_pronunciation_lexicon_v1"
        and pronunciation.get("language") == "zh-TW"
        and pronunciation.get("review_status") == "PASS"
        and isinstance(pronunciation.get("entries"), list)
    ):
        violations.append("adult source passthrough pronunciation lexicon is invalid")
    for name, field in (
        ("source_screenplay.txt", "source_sha256"),
        ("script.md", "script_sha256"),
    ):
        actual = _sha256_bytes((project / name).read_bytes())
        if manifest.get(field) != actual:
            violations.append(f"adult source passthrough {field} mismatch")
    try:
        dubbing = inspect_dubbing_project(project)
    except (
        DubbingContractError,
        OSError,
        TypeError,
        ValueError,
        VoiceProfileError,
    ):
        dubbing = {}
    if dubbing.get("mode") != "remake":
        violations.append("adult source passthrough dubbing mode is not remake")
    if dubbing.get("source_sha256") != manifest.get("source_sha256"):
        violations.append("adult source passthrough dubbing source hash mismatch")
    if dubbing.get("speaker_count") != manifest.get("speaker_count"):
        violations.append("adult source passthrough speaker count mismatch")
    if dubbing.get("utterance_count") != manifest.get("utterance_count"):
        violations.append("adult source passthrough utterance count mismatch")
    return (), tuple(violations)


__all__ = [
    "ExtractedScreenplay",
    "ParsedScreenplay",
    "SOURCE_PASSTHROUGH_POLICY",
    "SOURCE_PASSTHROUGH_SCHEMA",
    "extract_user_screenplay",
    "adult_source_request_detected",
    "is_local_adult_passthrough_request",
    "parse_user_screenplay",
    "prepare_local_adult_passthrough",
    "validate_local_adult_passthrough",
]
