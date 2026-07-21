#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from plugins.story_video.tone_map import (
    ToneMapError,
    build_tone_catalog,
    resolve_utterance_tone,
)


class TonePkError(RuntimeError):
    pass


SPOKEN_TEXT_NORMALIZATION = "bounded_ellipsis_v1"
SOURCE_ASSEMBLY_CONTRACT = "ffmpeg_concat_pcm_s16le_48000_mono_v1"
CANDIDATE_LINEAGE_SCHEMA = "story_video_candidate_lineage_v1"
_DISPLAY_PAUSE_RE = re.compile(r"(?:\.{3,}|…{2,}|⋯{2,}|—{1,2})")
_CLOSING_MARKS = "」』”’\"'】）》）]"
_TERMINAL_MARKS = "。！？!?"


def _canonical_json_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _validated_candidate_lineages(
    manifest: dict[str, Any],
    chunks: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    if manifest.get("candidate_lineage_schema") != CANDIDATE_LINEAGE_SCHEMA:
        raise TonePkError("generator candidate lineage schema is unsupported")
    generation_mode = manifest.get("generation_mode")
    if generation_mode not in {"full", "selective_repair"}:
        raise TonePkError("generator candidate generation mode is invalid")
    requested_ids = manifest.get("requested_voice_chunk_ids")
    if not isinstance(requested_ids, list) or any(
        not isinstance(value, str) or not value for value in requested_ids
    ):
        raise TonePkError("generator requested candidate IDs are invalid")
    if len(set(requested_ids)) != len(requested_ids):
        raise TonePkError("generator requested candidate IDs are ambiguous")
    chunk_ids = {str(chunk.get("voice_chunk_id") or "") for chunk in chunks}
    if not set(requested_ids) <= chunk_ids:
        raise TonePkError("generator requested unknown candidate IDs")
    lineages: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        chunk_id = str(chunk.get("voice_chunk_id") or "")
        lineage = chunk.get("candidate_lineage")
        if not chunk_id or chunk_id in lineages or not isinstance(lineage, dict):
            raise TonePkError("generator candidate lineage is missing or ambiguous")
        supplied_hash = lineage.get("lineage_sha256")
        canonical = {key: value for key, value in lineage.items() if key != "lineage_sha256"}
        baseline = canonical.get("baseline_candidate_count")
        delta = canonical.get("new_candidate_count")
        cumulative = canonical.get("cumulative_candidate_count")
        requested = chunk_id in set(requested_ids)
        if (
            canonical.get("schema") != CANDIDATE_LINEAGE_SCHEMA
            or canonical.get("generation_mode") != generation_mode
            or canonical.get("requested") is not requested
            or type(baseline) is not int
            or baseline < 0
            or type(delta) is not int
            or delta < 0
            or type(cumulative) is not int
            or cumulative < 1
            or baseline + delta != cumulative
            or chunk.get("candidate_count") != cumulative
            or canonical.get("output_audio_sha256") != chunk.get("audio_sha256")
            or not isinstance(supplied_hash, str)
            or _canonical_json_sha256(canonical) != supplied_hash
        ):
            raise TonePkError("generator candidate lineage is invalid")
        if generation_mode == "full":
            if baseline != 0 or not requested or delta < 1:
                raise TonePkError("generator full candidate lineage is invalid")
        elif requested:
            if baseline < 1 or delta < 1:
                raise TonePkError("generator selective candidate lineage is invalid")
        elif (
            delta != 0
            or baseline != cumulative
        ):
            raise TonePkError("generator unaffected candidate lineage changed")
        lineages[chunk_id] = canonical
    if generation_mode == "full" and set(requested_ids) != chunk_ids:
        raise TonePkError("generator full candidate scope is incomplete")
    return lineages


def normalize_synthesis_spoken_text(text: str) -> str:
    """Apply the generator's exact, versioned display-pause normalization."""

    source = str(text or "")

    def replace(match: re.Match[str]) -> str:
        tail = source[match.end() :].lstrip()
        after_closers = tail.lstrip(_CLOSING_MARKS)
        if not after_closers:
            return "。"
        if after_closers[0] in _TERMINAL_MARKS:
            return ""
        return "，"

    return _DISPLAY_PAUSE_RE.sub(replace, source)


def _source_assembly_fingerprint(chunk_hashes: list[str]) -> str:
    if not chunk_hashes or any(
        not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
        for value in chunk_hashes
    ):
        raise TonePkError("source assembly chunk hashes are invalid")
    payload = json.dumps(
        {
            "contract": SOURCE_ASSEMBLY_CONTRACT,
            "ordered_chunk_audio_sha256s": chunk_hashes,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return _text_sha256(payload)


def _stored_source_assembly_fingerprint(take: dict[str, Any]) -> str | None:
    fields = (
        "source_assembly_contract",
        "source_chunk_audio_sha256s",
        "source_assembly_fingerprint",
    )
    present = [field in take for field in fields]
    if not any(present):
        return None
    if not all(present):
        raise TonePkError("source assembly evidence is incomplete")
    hashes = take["source_chunk_audio_sha256s"]
    if (
        take["source_assembly_contract"] != SOURCE_ASSEMBLY_CONTRACT
        or not isinstance(hashes, list)
    ):
        raise TonePkError("source assembly evidence is invalid")
    expected = _source_assembly_fingerprint(hashes)
    if take["source_assembly_fingerprint"] != expected:
        raise TonePkError("source assembly fingerprint is invalid")
    return expected


def _trusted_pronunciation_contract(
    manifest: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    report_value = manifest.get("pronunciation_qc_report")
    if not isinstance(report_value, str) or not report_value:
        raise TonePkError("pronunciation QC report is missing")
    report_path = Path(report_value)
    if not report_path.is_file():
        raise TonePkError("pronunciation QC report does not exist")
    report = _load_json(report_path, label="pronunciation QC report")
    if report.get("schema") != "story_video_pronunciation_qc_v3":
        raise TonePkError("pronunciation QC schema is unsupported")
    sources = report.get("lexicon_sources")
    if not isinstance(sources, list) or any(
        not isinstance(value, str) or not value for value in sources
    ):
        raise TonePkError("pronunciation lexicon sources are invalid")
    entries, source_hashes = _load_trusted_pronunciation_sources(sources)
    return entries, list(sources), source_hashes


def _load_trusted_pronunciation_sources(
    sources: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    merged: dict[str, dict[str, Any]] = {}
    source_hashes: list[str] = []
    for source_value in sources:
        source = Path(source_value)
        payload = _load_json(source, label="pronunciation lexicon")
        if (
            payload.get("schema") != "story_video_pronunciation_lexicon_v1"
            or payload.get("language") != "zh-TW"
            or (
                source.name == "pronunciation_lexicon.json"
                and str(payload.get("review_status") or "").upper() != "PASS"
            )
        ):
            raise TonePkError("pronunciation lexicon contract is invalid")
        source_hashes.append(_sha256(source))
        rows = payload.get("entries")
        if not isinstance(rows, list):
            raise TonePkError("pronunciation lexicon entries are invalid")
        for row in rows:
            if not isinstance(row, dict):
                raise TonePkError("pronunciation lexicon entry is invalid")
            display = str(row.get("display") or "").strip()
            spoken = str(row.get("spoken") or "").strip()
            if not display or not spoken:
                raise TonePkError("pronunciation lexicon entry is incomplete")
            entry: dict[str, Any] = {
                "display": display,
                "spoken": spoken,
                "expected_pinyin": str(row.get("expected_pinyin") or "").strip(),
                "source": str(row.get("source") or "").strip() or source.name,
                "risk": str(row.get("risk") or "").strip().lower(),
            }
            accepted = row.get("accepted_pinyin_variants") or []
            if not isinstance(accepted, list) or any(
                not isinstance(value, str) or not value.strip()
                for value in accepted
            ):
                raise TonePkError("pronunciation accepted variants are invalid")
            if accepted:
                entry["accepted_pinyin_variants"] = [
                    value.strip() for value in accepted
                ]
            merged[display] = entry
    ordered = sorted(merged.values(), key=lambda entry: len(entry["display"]), reverse=True)
    return ordered, source_hashes


def _compile_pronunciation_contract(
    text: str,
    entries: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    applicable = [entry for entry in entries if entry["display"] in text]
    if not applicable:
        return text, []
    by_display = {entry["display"]: entry for entry in applicable}
    pattern = re.compile(
        "|".join(re.escape(value) for value in sorted(by_display, key=len, reverse=True))
    )
    applied: list[dict[str, Any]] = []
    seen: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        entry = by_display[match.group(0)]
        if entry["display"] not in seen:
            applied.append(entry)
            seen.add(entry["display"])
        return str(entry["spoken"])

    return pattern.sub(replace, text), applied


def stable_pair_seed(run_id: str, utterance_id: str, chunk_index: int) -> int:
    payload = f"{run_id}\0{utterance_id}\0{chunk_index}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big") & 0x7FFFFFFF


def _split_at_boundaries(text: str, boundary_chars: str) -> list[str]:
    chunks: list[str] = []
    start = 0
    for index, character in enumerate(text, start=1):
        if character in boundary_chars:
            chunks.append(text[start:index])
            start = index
    if start < len(text):
        chunks.append(text[start:])
    return chunks


def split_exact_text_on_sentence_then_clause(
    text: str,
    *,
    max_chars: int,
) -> list[str]:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        raise TonePkError("spoken text is empty")
    if max_chars < 1:
        raise TonePkError("canonical chunk size must be positive")
    chunks: list[str] = []
    for sentence in _split_at_boundaries(normalized, "。！？!?；;"):
        if len(sentence) <= max_chars:
            chunks.append(sentence)
            continue
        for clause in _split_at_boundaries(sentence, "，,、：:"):
            while len(clause) > max_chars:
                chunks.append(clause[:max_chars])
                clause = clause[max_chars:]
            if clause:
                chunks.append(clause)
    return chunks


def split_canonical_chunks(text: str, expressive_tone_id: str) -> list[str]:
    max_chars = 18 if expressive_tone_id == "adult.breathless" else 36
    chunks = split_exact_text_on_sentence_then_clause(text, max_chars=max_chars)
    if "".join(chunks) != " ".join(text.split()):
        raise TonePkError("canonical chunking changed spoken text")
    return chunks


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TonePkError(f"cannot load {label}: {path}") from exc
    if not isinstance(payload, dict):
        raise TonePkError(f"{label} must be a JSON object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _validate_source_binding(
    source_project: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    ledger_path = source_project / "dialogue_ledger.json"
    binding_path = source_project / "voice_cast_binding.json"
    story_mode_path = source_project / "story_mode.json"
    ledger = _load_json(ledger_path, label="dialogue ledger")
    binding = _load_json(binding_path, label="voice cast binding")
    story_mode = _load_json(story_mode_path, label="story mode")
    if ledger.get("schema") not in {
        "story_video_dialogue_ledger_v1",
        "story_video_dialogue_ledger_v2",
    }:
        raise TonePkError("source dialogue ledger schema is unsupported")
    if binding.get("schema") not in {
        "story_video_voice_cast_binding_v1",
        "story_video_voice_cast_binding_v2",
    }:
        raise TonePkError("source voice cast binding schema is unsupported")
    if binding.get("status") != "locked":
        raise TonePkError("source voice cast binding is not locked")
    if str(binding.get("dialogue_ledger_sha256") or "") != _sha256(ledger_path):
        raise TonePkError("source dialogue ledger hash does not match cast binding")
    if str(binding.get("story_mode_sha256") or "") != _sha256(story_mode_path):
        raise TonePkError("source story mode hash does not match cast binding")
    cast_path = source_project / "cast_bible.json"
    expected_cast_hash = str(binding.get("cast_bible_sha256") or "")
    if expected_cast_hash and (
        not cast_path.is_file() or expected_cast_hash != _sha256(cast_path)
    ):
        raise TonePkError("source cast bible hash does not match cast binding")
    source_text = str(story_mode.get("source_text") or "")
    expected_source_hash = _text_sha256(source_text) if source_text else ""
    if str(story_mode.get("source_sha256") or "") != expected_source_hash:
        raise TonePkError("story mode source hash does not match source text")
    if str(ledger.get("source_sha256") or "") != expected_source_hash:
        raise TonePkError("dialogue ledger source hash does not match story mode")
    story_mode_name = str(story_mode.get("mode") or "")
    if (
        not story_mode_name
        or str(ledger.get("mode") or "") != story_mode_name
        or str(binding.get("story_mode") or "") != story_mode_name
    ):
        raise TonePkError("source story mode contracts do not match")
    return ledger, binding, story_mode


def _resolved_tone(
    *,
    annotation: dict[str, Any],
    utterance: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(annotation, dict):
        raise TonePkError("tone annotation rows must be objects")
    tone_id = str(annotation.get("tone_id") or "").strip().casefold()
    if not tone_id or tone_id == "general.neutral":
        raise TonePkError(
            "expressive annotation requires an explicit non-neutral tone_id"
        )
    modifiers = annotation.get("modifiers")
    if "modifiers" not in annotation or not isinstance(modifiers, list):
        raise TonePkError("expressive annotation requires an explicit modifiers list")
    try:
        return resolve_utterance_tone(
            emotion=str(utterance.get("emotion") or ""),
            action=str(utterance.get("action") or ""),
            pace=str(annotation.get("pace") or ""),
            tone_id=tone_id,
            intensity=annotation.get("intensity"),
            modifiers=modifiers,
            content_rating="adult_explicit",
        )
    except ToneMapError as exc:
        raise TonePkError(f"invalid tone annotation: {exc}") from exc


def _neutral_tone(utterance: dict[str, Any]) -> dict[str, Any]:
    try:
        return resolve_utterance_tone(
            emotion=str(utterance.get("emotion") or ""),
            action=str(utterance.get("action") or ""),
            pace="natural",
            tone_id="general.neutral",
            intensity=2,
            modifiers=[],
            content_rating="adult_explicit",
        )
    except ToneMapError as exc:  # pragma: no cover - catalog invariant
        raise TonePkError(f"cannot build neutral tone: {exc}") from exc


def _take(
    *,
    variant: str,
    take_id: str,
    spoken_text: str,
    speaker: dict[str, Any],
    chunks: list[str],
    seeds: list[int],
    tone: dict[str, Any],
) -> dict[str, Any]:
    return {
        "variant": variant,
        "take_id": take_id,
        "spoken_text": spoken_text,
        "voice_id": str(speaker.get("voice_id") or ""),
        "engine": str(speaker.get("engine") or ""),
        "profile_id": str(speaker.get("profile_id") or ""),
        "profile_sha256": str(speaker.get("profile_sha256") or ""),
        "canonical_voice_chunks": list(chunks),
        "generation_seeds": list(seeds),
        "voice_chunks": [
            {
                "chunk_index": index,
                "spoken_text": chunk,
                "generation_seed": seeds[index - 1],
            }
            for index, chunk in enumerate(chunks, start=1)
        ],
        "tone": copy.deepcopy(tone),
    }


def build_pair_plan(
    *,
    source_project: Path,
    run_id: str,
    annotations: dict[str, dict[str, Any]],
    expected_utterance_count: int,
) -> dict[str, Any]:
    """Validate immutable inputs and return same-seed/same-chunk A/B specs."""
    project = Path(source_project).expanduser().resolve()
    normalized_run_id = str(run_id or "").strip()
    if not normalized_run_id:
        raise TonePkError("run_id is required")
    if (
        isinstance(expected_utterance_count, bool)
        or not isinstance(expected_utterance_count, int)
        or expected_utterance_count < 1
    ):
        raise TonePkError("expected utterance count must be a positive integer")
    if not isinstance(annotations, dict):
        raise TonePkError("tone annotations must be an object keyed by utterance ID")
    ledger, binding, story_mode = _validate_source_binding(project)
    utterances = ledger.get("utterances")
    if not isinstance(utterances, list) or len(utterances) != expected_utterance_count:
        actual = len(utterances) if isinstance(utterances, list) else 0
        raise TonePkError(
            f"expected {expected_utterance_count} utterances but source has {actual}"
        )
    utterance_ids: list[str] = []
    for expected_order, utterance in enumerate(utterances, start=1):
        if not isinstance(utterance, dict) or utterance.get("order") != expected_order:
            raise TonePkError("source utterance order is not contiguous")
        utterance_id = str(utterance.get("utterance_id") or "").strip()
        if not utterance_id or utterance_id in utterance_ids:
            raise TonePkError("source utterance IDs are missing or duplicated")
        utterance_ids.append(utterance_id)
    if set(annotations) != set(utterance_ids):
        missing = sorted(set(utterance_ids) - set(annotations))
        extra = sorted(set(annotations) - set(utterance_ids))
        raise TonePkError(
            f"annotation IDs do not match source utterances; missing={missing}, extra={extra}"
        )
    speaker_rows = binding.get("speakers")
    if not isinstance(speaker_rows, list) or not speaker_rows:
        raise TonePkError("source voice cast binding has no speakers")
    speakers = {
        str(row.get("speaker_id") or ""): row
        for row in speaker_rows
        if isinstance(row, dict) and str(row.get("speaker_id") or "")
    }
    pairs: list[dict[str, Any]] = []
    for utterance in utterances:
        order = int(utterance["order"])
        utterance_id = str(utterance["utterance_id"])
        speaker_id = str(utterance.get("speaker_id") or "")
        speaker = speakers.get(speaker_id)
        if speaker is None:
            raise TonePkError(
                f"utterance {utterance_id} has no locked voice for speaker {speaker_id!r}"
            )
        voice_id = str(speaker.get("voice_id") or "")
        engine = str(speaker.get("engine") or "")
        if not voice_id or not engine:
            raise TonePkError(f"speaker {speaker_id!r} has incomplete voice routing")
        display_text = str(utterance.get("display_text") or "")
        spoken_text = " ".join(
            str(utterance.get("spoken_text") or display_text).split()
        )
        expressive_tone = _resolved_tone(
            annotation=annotations[utterance_id],
            utterance=utterance,
        )
        chunks = split_canonical_chunks(spoken_text, expressive_tone["tone_id"])
        seeds = [
            stable_pair_seed(normalized_run_id, utterance_id, index)
            for index in range(1, len(chunks) + 1)
        ]
        pair_id = f"PK-{order:04d}"
        neutral = _take(
            variant="neutral",
            take_id=f"{pair_id}__A",
            spoken_text=spoken_text,
            speaker=speaker,
            chunks=chunks,
            seeds=seeds,
            tone=_neutral_tone(utterance),
        )
        expressive = _take(
            variant="expressive",
            take_id=f"{pair_id}__B",
            spoken_text=spoken_text,
            speaker=speaker,
            chunks=chunks,
            seeds=seeds,
            tone=expressive_tone,
        )
        pairs.append(
            {
                "pair_id": pair_id,
                "utterance_id": utterance_id,
                "order": order,
                "speaker_id": speaker_id,
                "action": str(utterance.get("action") or ""),
                "display_text": display_text,
                "spoken_text": spoken_text,
                "voice_id": voice_id,
                "engine": engine,
                "canonical_voice_chunks": list(chunks),
                "generation_seeds": list(seeds),
                "neutral": neutral,
                "expressive": expressive,
            }
        )
    return {
        "schema": "story_video_tone_pk_plan_v1",
        "run_id": normalized_run_id,
        "expected_utterance_count": expected_utterance_count,
        "pair_count": len(pairs),
        "source_binding": {
            "dialogue_ledger_sha256": _sha256(project / "dialogue_ledger.json"),
            "voice_cast_binding_sha256": _sha256(
                project / "voice_cast_binding.json"
            ),
            "story_mode_sha256": _sha256(project / "story_mode.json"),
            "story_source_sha256": str(story_mode.get("source_sha256") or ""),
            "utterance_ids": utterance_ids,
        },
        "pairs": pairs,
    }


def _variant_ledger(
    source_ledger: dict[str, Any],
    plan: dict[str, Any],
    *,
    variant: str,
) -> dict[str, Any]:
    ledger = copy.deepcopy(source_ledger)
    ledger["schema"] = "story_video_dialogue_ledger_v2"
    ledger["content_rating"] = "adult_explicit"
    ledger["tone_catalog"] = build_tone_catalog()
    plan_by_id = {pair["utterance_id"]: pair for pair in plan["pairs"]}
    for row in ledger["utterances"]:
        pair = plan_by_id[str(row["utterance_id"])]
        take = pair[variant]
        row["spoken_text"] = pair["spoken_text"]
        row["canonical_voice_chunks"] = list(take["canonical_voice_chunks"])
        row["generation_seeds"] = list(take["generation_seeds"])
        row["tone"] = copy.deepcopy(take["tone"])
    return ledger


def _write_variant_contracts(
    *,
    source_project: Path,
    output_project: Path,
    source_ledger: dict[str, Any],
    source_binding: dict[str, Any],
    story_mode: dict[str, Any],
    plan: dict[str, Any],
    variant: str,
) -> None:
    variant_dir = output_project / "variants" / variant
    story_mode_path = variant_dir / "story_mode.json"
    ledger_path = variant_dir / "dialogue_ledger.json"
    _write_json(story_mode_path, copy.deepcopy(story_mode))
    cast_source = source_project / "cast_bible.json"
    cast_path = variant_dir / "cast_bible.json"
    if cast_source.is_file():
        _write_json(
            cast_path,
            _load_json(cast_source, label="cast bible"),
        )
    ledger = _variant_ledger(source_ledger, plan, variant=variant)
    _write_json(ledger_path, ledger)
    binding = copy.deepcopy(source_binding)
    binding["story_mode_path"] = str(story_mode_path)
    binding["story_mode_sha256"] = _sha256(story_mode_path)
    binding["dialogue_ledger_path"] = str(ledger_path)
    binding["dialogue_ledger_sha256"] = _sha256(ledger_path)
    if cast_path.is_file():
        binding["cast_bible_path"] = str(cast_path)
        binding["cast_bible_sha256"] = _sha256(cast_path)
    _write_json(variant_dir / "voice_cast_binding.json", binding)


def prepare_project(
    *,
    source_project: Path,
    output_project: Path,
    run_id: str,
    annotations_path: Path,
    expected_utterance_count: int,
) -> dict[str, Any]:
    source = Path(source_project).expanduser().resolve()
    output = Path(output_project).expanduser().resolve()
    if output == source:
        raise TonePkError("output project must differ from source project")
    annotations = _load_json(
        Path(annotations_path).expanduser().resolve(),
        label="tone annotations",
    )
    plan = build_pair_plan(
        source_project=source,
        run_id=run_id,
        annotations=annotations,
        expected_utterance_count=expected_utterance_count,
    )
    source_ledger, source_binding, story_mode = _validate_source_binding(source)
    _write_json(output / "manifests" / "tone_pk_plan.json", plan)
    _write_json(output / "annotations" / "tone_annotations.json", annotations)
    for variant in ("neutral", "expressive"):
        _write_variant_contracts(
            source_project=source,
            output_project=output,
            source_ledger=source_ledger,
            source_binding=source_binding,
            story_mode=story_mode,
            plan=plan,
            variant=variant,
        )
    return {
        "schema": plan["schema"],
        "run_id": plan["run_id"],
        "pair_count": plan["pair_count"],
        "output_project": str(output),
        "plan_path": str(output / "manifests" / "tone_pk_plan.json"),
    }


SHORT_REPLAN_OVERRIDE_SCHEMA = "story_video_tone_pk_chunk_overrides_v1"
SHORT_REPLAN_REVISION = "failed_pairs_short_chunks_v2"


def _short_replan_inputs(
    project: Path,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    source = Path(project).expanduser().resolve()
    plan_path = source / "manifests" / "tone_pk_plan.json"
    manifest_path = source / "manifests" / "tone_pk_manifest.json"
    plan = _load_json(plan_path, label="tone PK plan")
    manifest = _load_json(manifest_path, label="tone PK manifest")
    if plan.get("schema") != "story_video_tone_pk_plan_v1":
        raise TonePkError("tone PK plan schema is unsupported for short replan")
    if manifest.get("schema") != "story_video_tone_pk_manifest_v1":
        raise TonePkError("tone PK manifest schema is unsupported for short replan")
    if plan.get("run_id") != manifest.get("run_id"):
        raise TonePkError("tone PK plan and manifest run IDs differ")
    plan_pairs = plan.get("pairs")
    state_pairs = manifest.get("pairs")
    if not isinstance(plan_pairs, list) or not isinstance(state_pairs, list):
        raise TonePkError("tone PK short replan requires pair lists")
    plan_by_id = {
        str(pair.get("pair_id") or ""): pair
        for pair in plan_pairs
        if isinstance(pair, dict) and str(pair.get("pair_id") or "")
    }
    state_by_id = {
        str(pair.get("pair_id") or ""): pair
        for pair in state_pairs
        if isinstance(pair, dict) and str(pair.get("pair_id") or "")
    }
    if (
        len(plan_by_id) != len(plan_pairs)
        or len(state_by_id) != len(state_pairs)
        or set(plan_by_id) != set(state_by_id)
    ):
        raise TonePkError("tone PK plan and manifest pair IDs differ")
    failed_ids: list[str] = []
    immutable_take_fields = (
        "take_id",
        "spoken_text",
        "voice_id",
        "engine",
        "profile_id",
        "profile_sha256",
        "canonical_voice_chunks",
        "generation_seeds",
        "tone",
    )
    for pair_id in [str(pair["pair_id"]) for pair in plan_pairs]:
        planned = plan_by_id[pair_id]
        observed = state_by_id[pair_id]
        if any(
            planned.get(field) != observed.get(field)
            for field in (
                "pair_id",
                "utterance_id",
                "order",
                "speaker_id",
                "spoken_text",
                "voice_id",
                "engine",
            )
        ):
            raise TonePkError(f"pair identity drifted before short replan: {pair_id}")
        statuses: list[str] = []
        for variant in ("neutral", "expressive"):
            planned_take = planned.get(variant)
            observed_take = observed.get(variant)
            if not isinstance(planned_take, dict) or not isinstance(observed_take, dict):
                raise TonePkError(f"pair take is missing before short replan: {pair_id}")
            if any(
                planned_take.get(field) != observed_take.get(field)
                for field in immutable_take_fields
            ):
                raise TonePkError(
                    f"pair take identity drifted before short replan: {pair_id}/{variant}"
                )
            status = observed_take.get("qc_status")
            if status not in {"PASS", "FAIL"}:
                raise TonePkError(
                    f"pair QC status is unknown before short replan: {pair_id}/{variant}"
                )
            statuses.append(str(status))
        if "FAIL" in statuses:
            failed_ids.append(pair_id)
    if not failed_ids:
        raise TonePkError("short replan has no failed pairs")
    return plan, manifest, failed_ids


def build_failed_short_chunk_overrides(
    source_project: Path,
    *,
    max_chars: int = 12,
) -> dict[str, Any]:
    """Build a private, hash-bound override for only the failed pair union."""
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 1:
        raise TonePkError("short replan max chars must be a positive integer")
    source = Path(source_project).expanduser().resolve()
    plan, _manifest, failed_ids = _short_replan_inputs(source)
    plan_by_id = {str(pair["pair_id"]): pair for pair in plan["pairs"]}
    pairs: dict[str, list[str]] = {}
    for pair_id in failed_ids:
        text = str(plan_by_id[pair_id].get("spoken_text") or "")
        chunks = split_exact_text_on_sentence_then_clause(text, max_chars=max_chars)
        if "".join(chunks) != text:
            raise TonePkError(f"short replan changed canonical text for {pair_id}")
        pairs[pair_id] = chunks
    return {
        "schema": SHORT_REPLAN_OVERRIDE_SCHEMA,
        "source_plan_sha256": _sha256(source / "manifests" / "tone_pk_plan.json"),
        "source_manifest_sha256": _sha256(
            source / "manifests" / "tone_pk_manifest.json"
        ),
        "max_chars": max_chars,
        "pairs": pairs,
    }


def _rewrite_short_replan_variant(
    output: Path,
    *,
    variant: str,
    revised_by_utterance: dict[str, dict[str, Any]],
) -> None:
    variant_dir = output / "variants" / variant
    ledger_path = variant_dir / "dialogue_ledger.json"
    binding_path = variant_dir / "voice_cast_binding.json"
    ledger = _load_json(ledger_path, label=f"{variant} dialogue ledger")
    utterances = ledger.get("utterances")
    if not isinstance(utterances, list):
        raise TonePkError(f"{variant} dialogue ledger has no utterances")
    seen: set[str] = set()
    for row in utterances:
        if not isinstance(row, dict):
            raise TonePkError(f"{variant} dialogue ledger has an invalid utterance")
        utterance_id = str(row.get("utterance_id") or "")
        revised = revised_by_utterance.get(utterance_id)
        if revised is None:
            continue
        take = revised[variant]
        row["canonical_voice_chunks"] = list(take["canonical_voice_chunks"])
        row["generation_seeds"] = list(take["generation_seeds"])
        seen.add(utterance_id)
    if seen != set(revised_by_utterance):
        raise TonePkError(f"{variant} dialogue ledger is missing revised utterances")
    _write_json(ledger_path, ledger)
    binding = _load_json(binding_path, label=f"{variant} voice cast binding")
    binding["dialogue_ledger_path"] = str(ledger_path)
    binding["dialogue_ledger_sha256"] = _sha256(ledger_path)
    story_mode_path = variant_dir / "story_mode.json"
    binding["story_mode_path"] = str(story_mode_path)
    binding["story_mode_sha256"] = _sha256(story_mode_path)
    cast_path = variant_dir / "cast_bible.json"
    if cast_path.is_file():
        binding["cast_bible_path"] = str(cast_path)
        binding["cast_bible_sha256"] = _sha256(cast_path)
    _write_json(binding_path, binding)


def replan_failed_pairs_short(
    *,
    source_project: Path,
    output_project: Path,
    overrides: dict[str, Any],
    max_chars: int = 12,
) -> dict[str, Any]:
    """Clone a run and reset only failed pairs under a new short-chunk identity."""
    source = Path(source_project).expanduser().resolve()
    output = Path(output_project).expanduser().resolve()
    if output == source:
        raise TonePkError("short replan output project must differ from source")
    if output.exists():
        raise TonePkError("short replan output project already exists")
    if not isinstance(overrides, dict):
        raise TonePkError("short replan override must be an object")
    plan, manifest, failed_ids = _short_replan_inputs(source)
    plan_path = source / "manifests" / "tone_pk_plan.json"
    manifest_path = source / "manifests" / "tone_pk_manifest.json"
    if overrides.get("schema") != SHORT_REPLAN_OVERRIDE_SCHEMA:
        raise TonePkError("short replan override schema is unsupported")
    if overrides.get("source_plan_sha256") != _sha256(plan_path):
        raise TonePkError("short replan source plan hash does not match")
    if overrides.get("source_manifest_sha256") != _sha256(manifest_path):
        raise TonePkError("short replan source manifest hash does not match")
    if overrides.get("max_chars") != max_chars:
        raise TonePkError("short replan max chars does not match override")
    override_pairs = overrides.get("pairs")
    if not isinstance(override_pairs, dict) or set(override_pairs) != set(failed_ids):
        raise TonePkError("short replan override pair IDs do not match failed pairs")
    plan_by_id = {str(pair["pair_id"]): pair for pair in plan["pairs"]}
    validated_chunks: dict[str, list[str]] = {}
    for pair_id in failed_ids:
        chunks = override_pairs[pair_id]
        if (
            not isinstance(chunks, list)
            or not chunks
            or any(not isinstance(chunk, str) or not chunk for chunk in chunks)
        ):
            raise TonePkError(f"short replan chunks are invalid for {pair_id}")
        if any(len(chunk) > max_chars for chunk in chunks):
            raise TonePkError(f"short replan chunk exceeds {max_chars} for {pair_id}")
        text = str(plan_by_id[pair_id].get("spoken_text") or "")
        if "".join(chunks) != text:
            raise TonePkError(f"short replan changed canonical text for {pair_id}")
        deterministic = split_exact_text_on_sentence_then_clause(
            text,
            max_chars=max_chars,
        )
        if chunks != deterministic:
            raise TonePkError(f"short replan chunks are not deterministic for {pair_id}")
        validated_chunks[pair_id] = list(chunks)

    revised_plan = copy.deepcopy(plan)
    revision_seed_scope = (
        f"{plan['run_id']}:{SHORT_REPLAN_REVISION}:{_sha256(plan_path)[:16]}"
    )
    revised_by_id = {
        str(pair["pair_id"]): pair for pair in revised_plan["pairs"]
    }
    revised_by_utterance: dict[str, dict[str, Any]] = {}
    for pair_id in failed_ids:
        pair = revised_by_id[pair_id]
        chunks = validated_chunks[pair_id]
        seeds = [
            stable_pair_seed(revision_seed_scope, str(pair["utterance_id"]), index)
            for index in range(1, len(chunks) + 1)
        ]
        pair["canonical_voice_chunks"] = list(chunks)
        pair["generation_seeds"] = list(seeds)
        for variant in ("neutral", "expressive"):
            take = pair[variant]
            take["canonical_voice_chunks"] = list(chunks)
            take["generation_seeds"] = list(seeds)
            take["voice_chunks"] = [
                {
                    "chunk_index": index,
                    "spoken_text": chunk,
                    "generation_seed": seeds[index - 1],
                }
                for index, chunk in enumerate(chunks, start=1)
            ]
        revised_by_utterance[str(pair["utterance_id"])] = pair
    revised_plan["plan_revision"] = {
        "schema": "story_video_tone_pk_plan_revision_v1",
        "revision": SHORT_REPLAN_REVISION,
        "source_plan_sha256": _sha256(plan_path),
        "source_manifest_sha256": _sha256(manifest_path),
        "affected_pair_ids": list(failed_ids),
        "max_chunk_chars": max_chars,
        "seed_scope_sha256": _text_sha256(revision_seed_scope),
        "candidate_budget": {"start": 1, "cap": 3},
    }

    shutil.copytree(source, output)
    archive_dir = output / "archive" / "short_replan_v2"
    _write_json(
        archive_dir / "affected_pairs.json",
        {
            "schema": "story_video_tone_pk_archived_pairs_v1",
            "source_plan_sha256": _sha256(plan_path),
            "source_manifest_sha256": _sha256(manifest_path),
            "pair_ids": list(failed_ids),
            "pairs": [
                copy.deepcopy(pair)
                for pair in manifest["pairs"]
                if str(pair["pair_id"]) in set(failed_ids)
            ],
        },
    )
    _write_json(output / "annotations" / "short_chunk_overrides.json", overrides)
    _write_json(output / "manifests" / "tone_pk_plan.json", revised_plan)
    for variant in ("neutral", "expressive"):
        _rewrite_short_replan_variant(
            output,
            variant=variant,
            revised_by_utterance=revised_by_utterance,
        )

    old_by_id = {str(pair["pair_id"]): pair for pair in manifest["pairs"]}
    migrated_pairs = [
        copy.deepcopy(revised_by_id[pair_id])
        if pair_id in set(failed_ids)
        else copy.deepcopy(old_by_id[pair_id])
        for pair_id in [str(pair["pair_id"]) for pair in plan["pairs"]]
    ]
    write_checkpoint(
        output,
        migrated_pairs,
        run_id=str(plan["run_id"]),
        metadata={
            "generator_path": manifest.get("generator_path", ""),
            "replan_provenance": copy.deepcopy(revised_plan["plan_revision"]),
        },
    )
    for stale_report in (output / "qc" / "tone_pk_qc_report.json",):
        if stale_report.is_file():
            stale_report.replace(archive_dir / stale_report.name)
    for variant in ("neutral", "expressive"):
        stale_manifest = (
            output / "variants" / variant / "manifests" / "narration_manifest.json"
        )
        if stale_manifest.is_file():
            destination = archive_dir / f"{variant}_narration_manifest.json"
            destination.parent.mkdir(parents=True, exist_ok=True)
            stale_manifest.replace(destination)
    return {
        "schema": "story_video_tone_pk_short_replan_result_v1",
        "status": "READY_FOR_GENERATION",
        "affected_pair_count": len(failed_ids),
        "reused_pair_count": len(plan["pairs"]) - len(failed_ids),
        "candidate_budget_start": 1,
        "candidate_budget_cap": 3,
        "output_project": str(output),
    }


_PAIR_EQUAL_FIELDS = (
    ("spoken_text", "spoken text"),
    ("spoken_text_normalization", "spoken text normalization"),
    ("source_spoken_text_sha256", "source spoken text hash"),
    ("canonical_spoken_chunks", "canonical spoken chunk"),
    ("canonical_spoken_text", "canonical spoken text"),
    ("canonical_spoken_text_sha256", "canonical spoken text hash"),
    ("pronunciation_lexicon_sha256s", "pronunciation lexicon hash"),
    ("source_assembly_contract", "source assembly contract"),
    ("voice_id", "voice"),
    ("engine", "engine"),
    ("model_id", "model"),
    ("profile_id", "profile"),
    ("profile_sha256", "profile"),
    ("engine_binding", "engine binding"),
    ("canonical_voice_chunks", "canonical voice chunk"),
    ("generation_seeds", "generation seed"),
)


def _number(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TonePkError(f"{label} evidence is missing or invalid")
    result = float(value)
    if not math.isfinite(result):
        raise TonePkError(f"{label} evidence is missing or invalid")
    return result


def validate_pair_evidence(pair: dict[str, Any]) -> dict[str, Any]:
    """Fail closed unless a completed pair is a fair A/B comparison."""
    if not isinstance(pair, dict):
        raise TonePkError("pair evidence must be an object")
    pair_id = str(pair.get("pair_id") or "")
    neutral = pair.get("neutral")
    expressive = pair.get("expressive")
    if not pair_id or not isinstance(neutral, dict) or not isinstance(expressive, dict):
        raise TonePkError("pair evidence is incomplete")
    for field, label in _PAIR_EQUAL_FIELDS:
        if field not in neutral or field not in expressive:
            raise TonePkError(f"{label} evidence is missing")
        if neutral[field] != expressive[field]:
            raise TonePkError(f"pair {pair_id} {label} drift")
    for take in (neutral, expressive):
        if _stored_source_assembly_fingerprint(take) is None:
            raise TonePkError(f"pair {pair_id} source assembly evidence is missing")
    if neutral["spoken_text"] != pair.get("spoken_text"):
        raise TonePkError(f"pair {pair_id} spoken text drift from pair plan")
    chunks = neutral["canonical_voice_chunks"]
    seeds = neutral["generation_seeds"]
    if (
        not isinstance(chunks, list)
        or not chunks
        or not all(isinstance(value, str) and value for value in chunks)
        or not isinstance(seeds, list)
        or len(seeds) != len(chunks)
    ):
        raise TonePkError(f"pair {pair_id} canonical voice chunk evidence is invalid")
    for take in (neutral, expressive):
        source_chunk_hashes = take.get("source_chunk_audio_sha256s")
        source_chunk_ids = take.get("source_voice_chunk_ids")
        if (
            not isinstance(source_chunk_hashes, list)
            or len(source_chunk_hashes) != len(chunks)
            or not isinstance(source_chunk_ids, list)
            or len(source_chunk_ids) != len(chunks)
            or any(not isinstance(value, str) or not value for value in source_chunk_ids)
            or len(set(source_chunk_ids)) != len(source_chunk_ids)
            or any(
                not re.fullmatch(rf".+__C{index:02d}", chunk_id)
                for index, chunk_id in enumerate(source_chunk_ids, start=1)
            )
        ):
            raise TonePkError(
                f"pair {pair_id} source assembly chunk evidence is invalid"
            )
        lexicon_sources = take.get("pronunciation_lexicon_sources")
        if not isinstance(lexicon_sources, list) or any(
            not isinstance(value, str) or not value for value in lexicon_sources
        ):
            raise TonePkError(
                f"pair {pair_id} pronunciation lexicon sources are invalid"
            )
        pronunciation_entries, lexicon_hashes = _load_trusted_pronunciation_sources(
            lexicon_sources
        )
        expected_spoken_chunks = []
        for chunk in chunks:
            pronunciation_text, _ = _compile_pronunciation_contract(
                chunk,
                pronunciation_entries,
            )
            expected_spoken_chunks.append(
                normalize_synthesis_spoken_text(pronunciation_text)
            )
        spoken_chunks = take["canonical_spoken_chunks"]
        if not isinstance(spoken_chunks, list):
            raise TonePkError(
                f"pair {pair_id} canonical spoken text evidence is invalid"
            )
        canonical_spoken_text = "".join(spoken_chunks)
        if (
            len(spoken_chunks) != len(chunks)
            or spoken_chunks != expected_spoken_chunks
            or take["spoken_text_normalization"] != SPOKEN_TEXT_NORMALIZATION
            or take["source_spoken_text_sha256"]
            != _text_sha256(take["spoken_text"])
            or take["canonical_spoken_text"] != canonical_spoken_text
            or take["canonical_spoken_text_sha256"]
            != _text_sha256(canonical_spoken_text)
            or take["pronunciation_lexicon_sha256s"] != lexicon_hashes
        ):
            raise TonePkError(
                f"pair {pair_id} canonical spoken text evidence is invalid"
            )
    if neutral.get("variant") != "neutral" or expressive.get("variant") != "expressive":
        raise TonePkError(f"pair {pair_id} variant order is invalid")
    if neutral.get("adapter_status") != "neutral_noop":
        raise TonePkError(f"pair {pair_id} neutral adapter status is invalid")
    if expressive.get("adapter_status") != "applied":
        raise TonePkError(f"pair {pair_id} expressive adapter status is invalid")
    neutral_tone = neutral.get("tone")
    expressive_tone = expressive.get("tone")
    if not isinstance(neutral_tone, dict) or neutral_tone.get("tone_id") != "general.neutral":
        raise TonePkError(f"pair {pair_id} neutral tone is invalid")
    if (
        not isinstance(expressive_tone, dict)
        or not str(expressive_tone.get("tone_id") or "")
        or expressive_tone.get("tone_id") == "general.neutral"
    ):
        raise TonePkError(f"pair {pair_id} expressive tone is neutral or missing")
    neutral_lufs = _number(neutral.get("integrated_lufs"), label="neutral loudness")
    expressive_lufs = _number(
        expressive.get("integrated_lufs"), label="expressive loudness"
    )
    loudness_delta = abs(neutral_lufs - expressive_lufs)
    if loudness_delta > 0.5 + 1e-9:
        raise TonePkError(
            f"pair {pair_id} loudness delta {loudness_delta:.2f} LUFS exceeds 0.5"
        )
    for variant, take in (("neutral", neutral), ("expressive", expressive)):
        pause = _number(
            take.get("post_utterance_pause_seconds"),
            label=f"{variant} pause",
        )
        if pause < 0 or pause > 0.45 + 1e-9:
            raise TonePkError(f"pair {pair_id} {variant} pause exceeds 0.45 seconds")
        duration = _number(take.get("duration_seconds"), label=f"{variant} duration")
        if duration <= 0:
            raise TonePkError(f"pair {pair_id} {variant} duration must be positive")
    return {
        "pair_id": pair_id,
        "status": "PASS",
        "loudness_delta_lufs": round(loudness_delta, 3),
        "max_post_utterance_pause_seconds": max(
            float(neutral["post_utterance_pause_seconds"]),
            float(expressive["post_utterance_pause_seconds"]),
        ),
    }


def _artifact_hash_matches(raw_path: Any, raw_hash: Any) -> bool:
    path = Path(str(raw_path or ""))
    expected_hash = str(raw_hash or "")
    return bool(
        re.fullmatch(r"[0-9a-f]{64}", expected_hash)
        and path.is_file()
        and _sha256(path) == expected_hash
    )


def _source_take_is_green(take: dict[str, Any]) -> bool:
    return bool(
        take.get("qc_status") == "PASS"
        and _source_artifact_is_valid(take)
    )


def _source_artifact_is_valid(take: dict[str, Any]) -> bool:
    return _artifact_hash_matches(
        take.get("source_audio_path"), take.get("source_audio_sha256")
    )


def _complete_take_is_green(take: dict[str, Any]) -> bool:
    try:
        loudness = _number(take.get("integrated_lufs"), label="take loudness")
    except TonePkError:
        return False
    return bool(
        _source_take_is_green(take)
        and math.isfinite(loudness)
        and _artifact_hash_matches(
            take.get("normalized_audio_path"),
            take.get("normalized_audio_sha256"),
        )
    )


def pending_takes(
    state: dict[str, Any],
    *,
    phase: str = "complete",
) -> list[dict[str, Any]]:
    """Return only takes that do not have durable green QC and hash evidence."""
    pairs = state.get("pairs") if isinstance(state, dict) else None
    if not isinstance(pairs, list):
        raise TonePkError("tone PK state has no pairs")
    if phase not in {"source", "complete"}:
        raise TonePkError(f"unsupported pending-take phase: {phase}")
    pending: list[dict[str, Any]] = []
    for pair in pairs:
        if not isinstance(pair, dict) or not str(pair.get("pair_id") or ""):
            raise TonePkError("tone PK state contains an invalid pair")
        for variant in ("neutral", "expressive"):
            take = pair.get(variant)
            if not isinstance(take, dict):
                pending.append({"pair_id": pair["pair_id"], "variant": variant})
                continue
            is_green = (
                _source_take_is_green(take)
                if phase == "source"
                else _complete_take_is_green(take)
            )
            if not is_green:
                pending.append({"pair_id": pair["pair_id"], "variant": variant})
    return pending


def normalize_take(
    source: Path,
    output: Path,
    runner: Callable[[list[str]], Any],
    *,
    target_lufs: float = -18.0,
) -> None:
    source_path = Path(source)
    output_path = Path(output)
    if not source_path.is_file():
        raise TonePkError(f"source take does not exist: {source_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    runner(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(source_path),
            "-af",
            f"loudnorm=I={target_lufs:g}:LRA=7:TP=-2,aresample=48000",
            "-ar",
            "48000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
    )


def probe_loudness(
    source: Path,
    runner: Callable[..., Any] = subprocess.run,
) -> float:
    path = Path(source)
    if not path.is_file():
        raise TonePkError(f"normalized take does not exist: {path}")
    result = runner(
        [
            "ffmpeg",
            "-nostats",
            "-v",
            "info",
            "-i",
            str(path),
            "-filter_complex",
            "ebur128=peak=true",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    matches = re.findall(r"\bI:\s*(-?\d+(?:\.\d+)?)\s*LUFS", result.stderr or "")
    if not matches:
        raise TonePkError(f"cannot parse integrated loudness for {path}")
    return float(matches[-1])


def _subtitle_visual_text(pair: dict[str, Any], *, variant: str) -> str:
    speaker = str(pair.get("speaker_name") or pair.get("speaker_id") or "角色")
    action = str(pair.get("action") or "").strip()
    cue = f"{speaker} ({action})" if action else speaker
    if variant == "neutral":
        label = "A｜無情緒"
    else:
        tone_id = str(pair["expressive"]["tone"].get("tone_id") or "")
        tone_definition = build_tone_catalog().get("tones", {}).get(tone_id, {})
        tone_label = str(tone_definition.get("label") or tone_id)
        label = f"B｜有情緒・{tone_label}"
    return f"{label}\n{cue}：『{pair['display_text']}』"


_ROLE_COLORS = (
    "#64B5F6",
    "#81C784",
    "#BA68C8",
    "#FF8A65",
    "#4DD0E1",
    "#F06292",
    "#AED581",
    "#9575CD",
)


def build_pk_timeline(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    takes: list[dict[str, Any]] = []
    spoken_parts: list[str] = []
    cursor = 0.0
    speaker_ids = sorted({str(pair.get("speaker_id") or "") for pair in pairs})
    role_colors = {
        speaker_id: _ROLE_COLORS[index % len(_ROLE_COLORS)]
        for index, speaker_id in enumerate(speaker_ids)
    }
    for pair_index, pair in enumerate(pairs):
        qc = validate_pair_evidence(pair)
        for variant in ("neutral", "expressive"):
            take = pair[variant]
            duration = float(take["duration_seconds"])
            tone_id = str(take["tone"]["tone_id"])
            subtitle_label = (
                "A｜無情緒"
                if variant == "neutral"
                else f"B｜有情緒・{tone_id}"
            )
            takes.append(
                {
                    "pair_id": pair["pair_id"],
                    "utterance_id": pair.get("utterance_id"),
                    "variant": variant,
                    "take_id": take.get("take_id"),
                    "spoken_text": take["spoken_text"],
                    "subtitle_label": subtitle_label,
                    "subtitle_text": _subtitle_visual_text(pair, variant=variant),
                    "role_color": role_colors[str(pair.get("speaker_id") or "")],
                    "start_seconds": round(cursor, 3),
                    "end_seconds": round(cursor + duration, 3),
                    "duration_seconds": duration,
                    "normalized_audio_path": take.get("normalized_audio_path"),
                    "normalized_audio_sha256": take.get("normalized_audio_sha256"),
                    "pair_qc": qc,
                }
            )
            spoken_parts.append(str(take["spoken_text"]))
            cursor += duration
            if variant == "neutral":
                cursor += 0.35
            elif pair_index < len(pairs) - 1:
                cursor += 0.80
    return {
        "schema": "story_video_tone_pk_timeline_v1",
        "takes": takes,
        "spoken_text": "".join(spoken_parts),
        "duration_seconds": round(cursor, 3),
        "ab_silence_seconds": 0.35,
        "inter_pair_silence_seconds": 0.80,
    }


def _pairs_status(pairs: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    if not pairs:
        return "FAIL", []
    pending = pending_takes({"pairs": pairs})
    if pending:
        return "IN_PROGRESS", []
    reports: list[dict[str, Any]] = []
    try:
        reports = [validate_pair_evidence(pair) for pair in pairs]
    except TonePkError:
        return "FAIL", []
    return "PASS", reports


def _narration_manifest(
    pairs: list[dict[str, Any]],
    *,
    run_id: str,
    status: str,
) -> dict[str, Any]:
    chunks: list[dict[str, Any]] = []
    for pair in pairs:
        for variant, letter in (("neutral", "A"), ("expressive", "B")):
            take = pair.get(variant)
            if not isinstance(take, dict):
                continue
            source_chunks = take.get("canonical_voice_chunks")
            if not isinstance(source_chunks, list) or not source_chunks:
                continue
            chunks.append(
                {
                    "voice_chunk_id": f"{pair['pair_id']}__{letter}__001",
                    "utterance_id": pair.get("utterance_id"),
                    "speaker_id": pair.get("speaker_id"),
                    "spoken_text": take.get("spoken_text"),
                    "display_text": take.get("spoken_text"),
                    "audio_path": take.get("normalized_audio_path"),
                    "audio_sha256": take.get("normalized_audio_sha256"),
                    "canonical_voice_chunks": source_chunks,
                    "generation_seeds": take.get("generation_seeds"),
                    "pronunciation_qc": {"status": take.get("qc_status")},
                }
            )
    return {
        "schema": "story_video_narration_manifest_v7",
        "run_id": run_id,
        "status": status,
        "voice_chunk_count": len(chunks),
        "outputs": [
            {
                "scene_id": "S00",
                "spoken_text": "".join(str(row.get("spoken_text") or "") for row in chunks),
                "segments": [
                    {
                        "segment_id": "S00",
                        "voice_chunks": chunks,
                    }
                ],
            }
        ],
    }


def write_checkpoint(
    project: Path,
    pairs: list[dict[str, Any]],
    *,
    run_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project_path = Path(project)
    if not run_id:
        plan_path = project_path / "manifests" / "tone_pk_plan.json"
        if plan_path.is_file():
            run_id = str(_load_json(plan_path, label="tone PK plan").get("run_id") or "")
    run_id = run_id or "tone-pk-unbound"
    status, pair_reports = _pairs_status(pairs)
    state = {
        "schema": "story_video_tone_pk_manifest_v1",
        "run_id": run_id,
        "status": status,
        "pair_count": len(pairs),
        "pair_reports": pair_reports,
        "pairs": copy.deepcopy(pairs),
        **copy.deepcopy(metadata or {}),
    }
    _write_json(project_path / "manifests" / "tone_pk_manifest.json", state)
    _write_json(
        project_path / "manifests" / "narration_manifest.json",
        _narration_manifest(pairs, run_id=run_id, status=status),
    )
    return {
        "status": state["status"],
        "pair_count": len(pairs),
        "pending_takes": pending_takes(state),
    }


def _load_or_initialize_checkpoint(project: Path) -> dict[str, Any]:
    manifest_path = project / "manifests" / "tone_pk_manifest.json"
    if manifest_path.is_file():
        return _load_json(manifest_path, label="tone PK manifest")
    plan = _load_json(
        project / "manifests" / "tone_pk_plan.json",
        label="tone PK plan",
    )
    pairs = plan.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        raise TonePkError("tone PK plan has no pairs")
    write_checkpoint(project, pairs, run_id=str(plan.get("run_id") or ""))
    return _load_json(manifest_path, label="tone PK manifest")


def _flatten_voice_chunks(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        raise TonePkError("generator narration manifest has no outputs")
    for output in outputs:
        segments = output.get("segments") if isinstance(output, dict) else None
        if not isinstance(segments, list):
            raise TonePkError("generator narration output has no segments")
        for segment in segments:
            rows = segment.get("voice_chunks") if isinstance(segment, dict) else None
            if not isinstance(rows, list):
                raise TonePkError("generator narration segment has no voice chunks")
            if not all(isinstance(row, dict) for row in rows):
                raise TonePkError("generator narration voice chunk is invalid")
            chunks.extend(rows)
    return chunks


def _assemble_take_audio(
    chunks: list[dict[str, Any]],
    output: Path,
    runner: Callable[..., Any],
) -> None:
    sources = [Path(str(chunk.get("audio") or "")) for chunk in chunks]
    if not sources or any(not path.is_file() for path in sources):
        raise TonePkError("generator take audio is missing")
    output.parent.mkdir(parents=True, exist_ok=True)
    if len(sources) == 1:
        shutil.copyfile(sources[0], output)
        return
    command = ["ffmpeg", "-y", "-v", "error"]
    for source in sources:
        command.extend(["-i", str(source)])
    inputs = "".join(f"[{index}:a]" for index in range(len(sources)))
    command.extend(
        [
            "-filter_complex",
            f"{inputs}concat=n={len(sources)}:v=0:a=1[aout]",
            "-map",
            "[aout]",
            "-ar",
            "48000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(output),
        ]
    )
    runner(command, check=True)
    if not output.is_file():
        raise TonePkError(f"assembled take audio is missing: {output}")


def _variant_binding_by_speaker(variant_project: Path) -> dict[str, dict[str, Any]]:
    binding = _load_json(
        variant_project / "voice_cast_binding.json",
        label="variant voice cast binding",
    )
    speakers = binding.get("speakers")
    if not isinstance(speakers, list):
        raise TonePkError("variant voice cast binding has no speakers")
    return {
        str(row.get("speaker_id") or ""): row
        for row in speakers
        if isinstance(row, dict) and str(row.get("speaker_id") or "")
    }


def _variant_repair_shot_map(
    variant_project: Path,
    *,
    expected_utterance_ids: set[str],
) -> dict[str, str]:
    """Return the generator's repair IDs after validating the bound ledger."""
    ledger, _binding, _story_mode = _validate_source_binding(variant_project)
    utterances = ledger.get("utterances")
    if not isinstance(utterances, list) or not utterances:
        raise TonePkError("variant dialogue ledger has no utterances")
    mapping: dict[str, str] = {}
    used_shot_ids: set[str] = set()
    for row in utterances:
        if not isinstance(row, dict):
            raise TonePkError("variant dialogue ledger utterance is invalid")
        utterance_id = str(row.get("utterance_id") or "").strip()
        shot_id = str(row.get("shot_id") or "").strip()
        if not utterance_id or not shot_id:
            raise TonePkError("variant repair mapping is missing an utterance or shot ID")
        if utterance_id in mapping or shot_id in used_shot_ids:
            raise TonePkError("variant repair mapping contains duplicate IDs")
        mapping[utterance_id] = shot_id
        used_shot_ids.add(shot_id)
    actual_utterance_ids = set(mapping)
    if actual_utterance_ids != expected_utterance_ids:
        missing = sorted(expected_utterance_ids - actual_utterance_ids)
        unknown = sorted(actual_utterance_ids - expected_utterance_ids)
        raise TonePkError(
            "variant repair mapping does not match pair plan; "
            f"missing={missing}, unknown={unknown}"
        )
    return mapping


def _ingest_generated_variant(
    *,
    project: Path,
    state: dict[str, Any],
    variant: str,
    utterance_ids: set[str],
    runner: Callable[..., Any],
    accumulate_candidates: bool = False,
    reconcile_existing_source: bool = False,
    variant_project_override: Path | None = None,
) -> int:
    variant_project = (
        Path(variant_project_override)
        if variant_project_override is not None
        else project / "variants" / variant
    )
    manifest = _load_json(
        variant_project / "manifests" / "narration_manifest.json",
        label=f"{variant} narration manifest",
    )
    manifest_chunks = _flatten_voice_chunks(manifest)
    candidate_lineages = _validated_candidate_lineages(manifest, manifest_chunks)
    chunks_by_utterance: dict[str, list[dict[str, Any]]] = {}
    for chunk in manifest_chunks:
        utterance_id = str(chunk.get("utterance_id") or "")
        chunks_by_utterance.setdefault(utterance_id, []).append(chunk)
    bindings = _variant_binding_by_speaker(variant_project)
    pronunciation_entries, pronunciation_lexicon_sources, pronunciation_lexicon_sha256s = (
        _trusted_pronunciation_contract(manifest)
    )
    pairs = state.get("pairs")
    if not isinstance(pairs, list):
        raise TonePkError("tone PK manifest has no pairs")
    ingested = 0
    for pair in pairs:
        utterance_id = str(pair.get("utterance_id") or "")
        if utterance_id not in utterance_ids:
            continue
        chunks = chunks_by_utterance.get(utterance_id)
        if not chunks:
            raise TonePkError(f"generator omitted utterance {utterance_id}")
        take = pair.get(variant)
        if not isinstance(take, dict):
            raise TonePkError(f"pair {pair.get('pair_id')} lacks {variant} take")
        expected_chunks = take.get("canonical_voice_chunks")
        expected_seeds = take.get("generation_seeds")
        observed_chunks = [str(chunk.get("display_text") or "") for chunk in chunks]
        observed_spoken_chunks = [
            str(chunk.get("spoken_text") or "") for chunk in chunks
        ]
        observed_seeds = [chunk.get("generation_seed") for chunk in chunks]
        if observed_chunks != expected_chunks or observed_seeds != expected_seeds:
            raise TonePkError(f"generator changed chunks or seeds for {utterance_id}")
        chunk_lineages = [
            candidate_lineages[str(chunk.get("voice_chunk_id") or "")]
            for chunk in chunks
        ]
        requested_chunk_lineages = [
            lineage for lineage in chunk_lineages if lineage["requested"]
        ]
        if manifest.get("generation_mode") == "selective_repair":
            prior_hashes = take.get("source_chunk_audio_sha256s")
            prior_evidence = take.get("candidate_evidence")
            if (
                not isinstance(prior_hashes, list)
                or len(prior_hashes) != len(chunks)
                or not isinstance(prior_evidence, list)
                or len(prior_evidence) != len(chunks)
            ):
                raise TonePkError(
                    f"generator lacks unaffected evidence for {utterance_id}"
                )
            for index, (chunk, lineage) in enumerate(
                zip(chunks, chunk_lineages, strict=True)
            ):
                if lineage["requested"]:
                    continue
                prior_row = prior_evidence[index]
                if (
                    prior_hashes[index] != str(chunk.get("audio_sha256") or "")
                    or prior_row.get("voice_chunk_id")
                    != chunk.get("voice_chunk_id")
                    or prior_row.get("candidate_count")
                    != lineage["cumulative_candidate_count"]
                    or prior_row.get("selected_candidate")
                    != chunk.get("selected_candidate")
                ):
                    raise TonePkError(
                        f"generator changed unaffected evidence for {utterance_id}"
                    )
            if not requested_chunk_lineages:
                continue
        canonical_spoken_chunks: list[str] = []
        for raw_chunk, generated_chunk in zip(
            observed_chunks,
            chunks,
            strict=True,
        ):
            pronunciation_text, applied_entries = _compile_pronunciation_contract(
                raw_chunk,
                pronunciation_entries,
            )
            if (
                generated_chunk.get("pronunciation_entries") or []
            ) != applied_entries or (
                generated_chunk.get("pronunciation_rules") or []
            ) != [entry["display"] for entry in applied_entries]:
                raise TonePkError(
                    f"generator pronunciation evidence changed for {utterance_id}"
                )
            canonical_spoken_chunks.append(
                normalize_synthesis_spoken_text(pronunciation_text)
            )
        canonical_spoken_text = "".join(canonical_spoken_chunks)
        if (
            manifest.get("spoken_text_normalization")
            != SPOKEN_TEXT_NORMALIZATION
            or observed_spoken_chunks != canonical_spoken_chunks
        ):
            raise TonePkError(f"generator changed spoken text for {utterance_id}")
        declared_spoken_evidence = {
            "spoken_text_normalization": SPOKEN_TEXT_NORMALIZATION,
            "source_spoken_text_sha256": _text_sha256(str(take.get("spoken_text") or "")),
            "canonical_spoken_chunks": canonical_spoken_chunks,
            "canonical_spoken_text": canonical_spoken_text,
            "canonical_spoken_text_sha256": _text_sha256(canonical_spoken_text),
            "pronunciation_lexicon_sources": pronunciation_lexicon_sources,
            "pronunciation_lexicon_sha256s": pronunciation_lexicon_sha256s,
        }
        for field, expected in declared_spoken_evidence.items():
            if field in take and take[field] != expected:
                raise TonePkError(
                    f"planned {field} changed for {utterance_id}"
                )
        for field in ("voice_id", "engine", "profile_id", "profile_sha256"):
            if any(str(chunk.get(field) or "") != str(take.get(field) or "") for chunk in chunks):
                raise TonePkError(f"generator changed {field} for {utterance_id}")
        if any(chunk.get("tone") != take.get("tone") for chunk in chunks):
            raise TonePkError(f"generator changed tone evidence for {utterance_id}")
        observed_audio_hashes: list[str] = []
        for chunk in chunks:
            audio_path = Path(str(chunk.get("audio") or ""))
            expected_audio_sha256 = str(chunk.get("audio_sha256") or "")
            if (
                not audio_path.is_file()
                or not re.fullmatch(r"[0-9a-f]{64}", expected_audio_sha256)
                or _sha256(audio_path) != expected_audio_sha256
            ):
                raise TonePkError(
                    f"generator audio hash is invalid for {utterance_id}"
                )
            observed_audio_hashes.append(expected_audio_sha256)
        speaker_binding = bindings.get(str(pair.get("speaker_id") or ""))
        if speaker_binding is None:
            raise TonePkError(f"generator speaker binding is missing for {utterance_id}")
        gates = (
            "alignment_status",
            "pronunciation_status",
            "prosody_status",
            "fluency_status",
        )
        qc_pass = all(
            all(chunk.get(gate) == "PASS" for gate in gates) for chunk in chunks
        )
        if any(
            chunk.get("qc_status") != (
                "PASS" if all(chunk.get(gate) == "PASS" for gate in gates) else "FAIL"
            )
            for chunk in chunks
        ):
            raise TonePkError(f"generator chunk QC evidence is invalid for {utterance_id}")
        adapter_statuses = {
            str((chunk.get("tone_application") or {}).get("adapter_status") or "")
            for chunk in chunks
        }
        if len(adapter_statuses) != 1:
            raise TonePkError(f"generator tone adapter evidence differs for {utterance_id}")
        observed_counts = [chunk.get("candidate_count") for chunk in chunks]
        observed_selected = [chunk.get("selected_candidate") for chunk in chunks]
        if (
            any(type(value) is not int or value < 1 for value in observed_counts)
            or any(type(value) is not int or value < 1 for value in observed_selected)
            or any(
                selected > count
                for selected, count in zip(
                    observed_selected,
                    observed_counts,
                    strict=True,
                )
            )
        ):
            raise TonePkError(f"generator candidate evidence is invalid for {utterance_id}")
        current_assembly_fingerprint = _source_assembly_fingerprint(
            observed_audio_hashes
        )
        stored_assembly_fingerprint = _stored_source_assembly_fingerprint(take)
        assembly_identity_changed = bool(
            stored_assembly_fingerprint
            and stored_assembly_fingerprint != current_assembly_fingerprint
        )
        reuse_source_audio = bool(
            reconcile_existing_source
            and _source_artifact_is_valid(take)
            and stored_assembly_fingerprint == current_assembly_fingerprint
        )
        prior_candidates = int(take.get("candidate_count") or 0)
        lineage_baseline_count = max(
            int(lineage["baseline_candidate_count"]) for lineage in chunk_lineages
        )
        lineage_new_count = max(
            int(lineage["new_candidate_count"]) for lineage in chunk_lineages
        )
        observed_candidate_count = max(observed_counts)
        observed_selected_candidate = max(observed_selected)
        if observed_candidate_count != lineage_baseline_count + lineage_new_count:
            raise TonePkError(
                f"candidate lineage count differs for {utterance_id}"
            )
        if observed_candidate_count > 3:
            raise TonePkError(
                f"candidate budget exceeded while reconciling {utterance_id}"
            )
        preserve_candidate_accounting = (
            (reconcile_existing_source or accumulate_candidates)
            and not assembly_identity_changed
            and (
                prior_candidates == observed_candidate_count
                or (
                    manifest.get("generation_mode") == "full"
                    and prior_candidates > observed_candidate_count
                )
            )
            and type(take.get("selected_candidate")) is int
            and 1 <= take["selected_candidate"] <= prior_candidates
        )
        if (
            (reconcile_existing_source or accumulate_candidates)
            and not preserve_candidate_accounting
            and prior_candidates != lineage_baseline_count
        ):
            raise TonePkError(
                f"candidate lineage baseline differs for {utterance_id}"
            )
        candidate_count = (
            prior_candidates
            if preserve_candidate_accounting
            else observed_candidate_count
        )
        selected_candidate = (
            int(take["selected_candidate"])
            if preserve_candidate_accounting
            else observed_selected_candidate
        )
        observed_candidate_evidence = [
            {
                "voice_chunk_id": str(chunk.get("voice_chunk_id") or ""),
                "candidate_count": int(chunk["candidate_count"]),
                "selected_candidate": int(chunk["selected_candidate"]),
            }
            for chunk in chunks
        ]
        candidate_evidence = (
            copy.deepcopy(take["candidate_evidence"])
            if preserve_candidate_accounting
            and isinstance(take.get("candidate_evidence"), list)
            else observed_candidate_evidence
        )
        if reuse_source_audio:
            source_audio = Path(str(take["source_audio_path"]))
            source_audio_sha256 = str(take["source_audio_sha256"])
        else:
            source_audio = project / "takes" / "source" / f"{take['take_id']}.wav"
            _assemble_take_audio(chunks, source_audio, runner)
            source_audio_sha256 = _sha256(source_audio)
        previous_qc_status = take.get("qc_status")
        reconciled_qc_status = "PASS" if qc_pass else "FAIL"
        take.update(
            {
                **declared_spoken_evidence,
                "model_id": str(manifest.get("model") or ""),
                "engine_binding": copy.deepcopy(
                    speaker_binding.get("engine_binding") or {}
                ),
                "source_audio_path": str(source_audio),
                "source_audio_sha256": source_audio_sha256,
                "source_assembly_contract": SOURCE_ASSEMBLY_CONTRACT,
                "source_chunk_audio_sha256s": observed_audio_hashes,
                "source_assembly_fingerprint": current_assembly_fingerprint,
                "duration_seconds": round(
                    sum(float(chunk.get("speech_duration_sec") or 0) for chunk in chunks),
                    4,
                ),
                "post_utterance_pause_seconds": float(
                    chunks[-1].get("resolved_pause_after_sec") or 0
                ),
                "adapter_status": adapter_statuses.pop(),
                "qc_status": reconciled_qc_status,
                "source_voice_chunk_ids": [
                    str(chunk.get("voice_chunk_id") or "") for chunk in chunks
                ],
                "candidate_count": candidate_count,
                "selected_candidate": selected_candidate,
                "candidate_evidence": candidate_evidence,
            }
        )
        if not reuse_source_audio or previous_qc_status != reconciled_qc_status:
            for stale in (
                "normalized_audio_path",
                "normalized_audio_sha256",
                "integrated_lufs",
            ):
                take.pop(stale, None)
        ingested += 1
        write_checkpoint(
            project,
            pairs,
            run_id=str(state.get("run_id") or ""),
            metadata={
                "generator_path": state.get("generator_path", ""),
                **(
                    {"replan_provenance": copy.deepcopy(state["replan_provenance"])}
                    if isinstance(state.get("replan_provenance"), dict)
                    else {}
                ),
            },
        )
    return ingested


def _short_replan_affected_ids(state: dict[str, Any]) -> set[str]:
    provenance = state.get("replan_provenance")
    if not isinstance(provenance, dict):
        return set()
    if provenance.get("revision") != SHORT_REPLAN_REVISION:
        raise TonePkError("short replan provenance revision is unsupported")
    pair_ids = provenance.get("affected_pair_ids")
    if (
        not isinstance(pair_ids, list)
        or not pair_ids
        or any(not isinstance(value, str) or not value for value in pair_ids)
        or len(set(pair_ids)) != len(pair_ids)
    ):
        raise TonePkError("short replan affected pair IDs are invalid")
    budget = provenance.get("candidate_budget")
    if budget != {"start": 1, "cap": 3}:
        raise TonePkError("short replan candidate budget is invalid")
    pairs = state.get("pairs")
    if not isinstance(pairs, list):
        raise TonePkError("short replan checkpoint has no pairs")
    known = {
        str(pair.get("pair_id") or "")
        for pair in pairs
        if isinstance(pair, dict) and str(pair.get("pair_id") or "")
    }
    if not set(pair_ids) <= known:
        raise TonePkError("short replan affected pair IDs are unknown")
    return set(pair_ids)


def _write_fresh_short_replan_scratch_variant(
    project: Path,
    *,
    variant: str,
    affected_utterance_ids: set[str],
) -> Path:
    source = project / "variants" / variant
    scratch = project / "scratch" / "short_replan_v2" / "variants" / variant
    ledger = _load_json(source / "dialogue_ledger.json", label=f"{variant} ledger")
    rows = ledger.get("utterances")
    if not isinstance(rows, list):
        raise TonePkError(f"{variant} dialogue ledger has no utterances")
    filtered = [
        copy.deepcopy(row)
        for row in rows
        if isinstance(row, dict)
        and str(row.get("utterance_id") or "") in affected_utterance_ids
    ]
    if (
        len(filtered) != len(affected_utterance_ids)
        or {str(row.get("utterance_id") or "") for row in filtered}
        != affected_utterance_ids
    ):
        raise TonePkError(f"{variant} scratch scope does not match affected pairs")
    if scratch.exists():
        existing_ledger, _binding, _story_mode = _validate_source_binding(scratch)
        if existing_ledger.get("utterances") != filtered:
            raise TonePkError(f"fresh short-replan scratch drifted: {variant}")
        return scratch
    ledger["utterances"] = filtered
    story_mode = _load_json(source / "story_mode.json", label=f"{variant} story mode")
    binding = _load_json(
        source / "voice_cast_binding.json",
        label=f"{variant} voice cast binding",
    )
    story_mode_path = scratch / "story_mode.json"
    ledger_path = scratch / "dialogue_ledger.json"
    _write_json(story_mode_path, story_mode)
    _write_json(ledger_path, ledger)
    cast_source = source / "cast_bible.json"
    cast_path = scratch / "cast_bible.json"
    if cast_source.is_file():
        _write_json(cast_path, _load_json(cast_source, label=f"{variant} cast bible"))
    binding["story_mode_path"] = str(story_mode_path)
    binding["story_mode_sha256"] = _sha256(story_mode_path)
    binding["dialogue_ledger_path"] = str(ledger_path)
    binding["dialogue_ledger_sha256"] = _sha256(ledger_path)
    if cast_path.is_file():
        binding["cast_bible_path"] = str(cast_path)
        binding["cast_bible_sha256"] = _sha256(cast_path)
    _write_json(scratch / "voice_cast_binding.json", binding)
    lexicon_source = source / "pronunciation_lexicon.json"
    if lexicon_source.is_file():
        _write_json(
            scratch / "pronunciation_lexicon.json",
            _load_json(lexicon_source, label=f"{variant} pronunciation lexicon"),
        )
    _validate_source_binding(scratch)
    return scratch


def _validate_fresh_scratch_manifest(
    scratch: Path,
    *,
    affected_utterance_ids: set[str],
) -> dict[str, Any]:
    manifest_path = scratch / "manifests" / "narration_manifest.json"
    manifest = _load_json(manifest_path, label="fresh short-replan manifest")
    chunks = _flatten_voice_chunks(manifest)
    lineages = _validated_candidate_lineages(manifest, chunks)
    observed_ids = {str(chunk.get("utterance_id") or "") for chunk in chunks}
    if observed_ids != affected_utterance_ids:
        raise TonePkError("fresh short-replan manifest scope differs from affected pairs")
    for chunk in chunks:
        lineage = lineages[str(chunk.get("voice_chunk_id") or "")]
        if (
            manifest.get("generation_mode") != "full"
            or lineage.get("baseline_candidate_count") != 0
            or lineage.get("new_candidate_count") != 1
            or lineage.get("cumulative_candidate_count") != 1
            or chunk.get("candidate_count") != 1
            or chunk.get("selected_candidate") != 1
        ):
            raise TonePkError("fresh short-replan candidate must start at one")
    return manifest


def _validate_scratch_manifest_scope(
    scratch: Path,
    *,
    affected_utterance_ids: set[str],
) -> dict[str, Any]:
    manifest = _load_json(
        scratch / "manifests" / "narration_manifest.json",
        label="short-replan scratch manifest",
    )
    chunks = _flatten_voice_chunks(manifest)
    _validated_candidate_lineages(manifest, chunks)
    if {str(chunk.get("utterance_id") or "") for chunk in chunks} != affected_utterance_ids:
        raise TonePkError("short-replan scratch manifest scope differs from affected pairs")
    return manifest


def generate_fresh_replanned_takes(
    project: Path,
    generator: Path,
    *,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Generate only changed short-replan identities as full candidate-one runs."""
    project_path = Path(project).expanduser().resolve()
    generator_path = Path(generator).expanduser().resolve()
    if not generator_path.is_file():
        raise TonePkError(f"Qwen generator does not exist: {generator_path}")
    state = _load_checkpoint(project_path)
    affected_pair_ids = _short_replan_affected_ids(state)
    if not affected_pair_ids:
        raise TonePkError("checkpoint is not a fresh short-replan project")
    affected_pairs = [
        pair
        for pair in state["pairs"]
        if str(pair.get("pair_id") or "") in affected_pair_ids
    ]
    affected_utterance_ids = {
        str(pair.get("utterance_id") or "") for pair in affected_pairs
    }
    generation_fields = (
        "candidate_count",
        "selected_candidate",
        "candidate_evidence",
        "source_audio_path",
        "source_audio_sha256",
        "normalized_audio_path",
        "normalized_audio_sha256",
        "integrated_lufs",
        "qc_status",
    )
    before_reused = {
        str(pair["pair_id"]): copy.deepcopy(pair)
        for pair in state["pairs"]
        if str(pair.get("pair_id") or "") not in affected_pair_ids
    }
    state["generator_path"] = str(generator_path)
    manifest_hashes: dict[str, str] = {}
    generated = 0
    for variant in ("neutral", "expressive"):
        state = _load_checkpoint(project_path)
        state["generator_path"] = str(generator_path)
        current_pairs = {
            str(pair["pair_id"]): pair for pair in state["pairs"]
        }
        variant_takes = [current_pairs[pair_id][variant] for pair_id in affected_pair_ids]
        has_any_evidence = [
            any(field in take for field in generation_fields) for take in variant_takes
        ]
        scratch = _write_fresh_short_replan_scratch_variant(
            project_path,
            variant=variant,
            affected_utterance_ids=affected_utterance_ids,
        )
        scratch_manifest = scratch / "manifests" / "narration_manifest.json"
        if scratch_manifest.is_file():
            if not all(has_any_evidence):
                raise TonePkError(
                    f"{variant} fresh short-replan scratch/master evidence is partial"
                )
            _validate_fresh_scratch_manifest(
                scratch,
                affected_utterance_ids=affected_utterance_ids,
            )
            _ingest_generated_variant(
                project=project_path,
                state=state,
                variant=variant,
                utterance_ids=affected_utterance_ids,
                runner=runner,
                reconcile_existing_source=True,
                variant_project_override=scratch,
            )
            state = _load_checkpoint(project_path)
            refreshed = {
                str(pair["pair_id"]): pair for pair in state["pairs"]
            }
            if any(
                refreshed[pair_id][variant].get("candidate_count") != 1
                or not _source_artifact_is_valid(refreshed[pair_id][variant])
                for pair_id in affected_pair_ids
            ):
                raise TonePkError(
                    f"{variant} fresh short-replan master evidence is invalid"
                )
            manifest_hashes[variant] = _sha256(scratch_manifest)
            continue
        if any(has_any_evidence):
            raise TonePkError(
                f"{variant} fresh short-replan master evidence lacks scratch manifest"
            )
        command = [
            sys.executable,
            str(generator_path),
            str(scratch),
            "--voice-cast-binding",
            str(scratch / "voice_cast_binding.json"),
            "--dialogue-ledger",
            str(scratch / "dialogue_ledger.json"),
            "--max-acoustic-retries",
            "0",
            "--emit-failed-qc-manifest",
        ]
        try:
            runner(command, check=True)
        except (OSError, subprocess.SubprocessError) as exc:
            raise TonePkError(
                f"{variant} fresh short-replan Qwen generation failed: {exc}"
            ) from exc
        _validate_fresh_scratch_manifest(
            scratch,
            affected_utterance_ids=affected_utterance_ids,
        )
        generated += _ingest_generated_variant(
            project=project_path,
            state=state,
            variant=variant,
            utterance_ids=affected_utterance_ids,
            runner=runner,
            variant_project_override=scratch,
        )
        manifest_hashes[variant] = _sha256(
            scratch / "manifests" / "narration_manifest.json"
        )
        state = _load_checkpoint(project_path)
        state["generator_path"] = str(generator_path)
    current_by_id = {str(pair["pair_id"]): pair for pair in state["pairs"]}
    if any(current_by_id[pair_id] != pair for pair_id, pair in before_reused.items()):
        raise TonePkError("fresh short-replan changed a reused pair")
    audit = {
        "schema": "story_video_tone_pk_fresh_generation_audit_v1",
        "status": "PASS",
        "affected_pair_count": len(affected_pair_ids),
        "generated_take_count": generated,
        "provider_utterance_count_per_variant": len(affected_utterance_ids),
        "generation_mode": "full",
        "candidate_budget": {"start": 1, "cap": 3},
        "manifest_sha256s": manifest_hashes,
    }
    _write_json(project_path / "scratch" / "short_replan_v2" / "audit.json", audit)
    write_checkpoint(
        project_path,
        state["pairs"],
        run_id=str(state.get("run_id") or ""),
        metadata={
            "generator_path": str(generator_path),
            "replan_provenance": copy.deepcopy(state["replan_provenance"]),
            "fresh_generation_audit": audit,
        },
    )
    return {
        "status": "PASS"
        if not pending_takes({"pairs": state["pairs"]}, phase="source")
        else "FAIL",
        "generated_take_count": generated,
        "affected_pair_count": len(affected_pair_ids),
        "reused_pair_count": len(before_reused),
    }


def _repair_short_replanned_takes(
    project: Path,
    *,
    state: dict[str, Any],
    generator: Path,
    max_candidates: int,
    runner: Callable[..., Any],
) -> dict[str, Any]:
    affected_pair_ids = _short_replan_affected_ids(state)
    pairs = state["pairs"]
    by_pair = {str(pair["pair_id"]): pair for pair in pairs}
    affected_utterance_ids = {
        str(by_pair[pair_id]["utterance_id"]) for pair_id in affected_pair_ids
    }
    before_reused = {
        str(pair["pair_id"]): copy.deepcopy(pair)
        for pair in pairs
        if str(pair.get("pair_id") or "") not in affected_pair_ids
    }
    for variant in ("neutral", "expressive"):
        scratch = project / "scratch" / "short_replan_v2" / "variants" / variant
        _validate_scratch_manifest_scope(
            scratch,
            affected_utterance_ids=affected_utterance_ids,
        )
        _ingest_generated_variant(
            project=project,
            state=state,
            variant=variant,
            utterance_ids=affected_utterance_ids,
            runner=runner,
            reconcile_existing_source=True,
            variant_project_override=scratch,
        )
        state = _load_checkpoint(project)
        state["generator_path"] = str(generator)
    failed = pending_takes(state, phase="source")
    if any(row["pair_id"] not in affected_pair_ids for row in failed):
        raise TonePkError("short-replan repair found a failed reused pair")
    if not failed:
        return {"status": "PASS", "repaired_take_count": 0, "attempts": 0}
    by_pair = {str(pair["pair_id"]): pair for pair in state["pairs"]}
    groups: dict[tuple[str, int], set[str]] = {}
    exhausted: list[tuple[str, str]] = []
    for row in failed:
        used = int(by_pair[row["pair_id"]][row["variant"]].get("candidate_count") or 0)
        remaining = max_candidates - used
        if remaining <= 0:
            exhausted.append((row["pair_id"], row["variant"]))
            continue
        groups.setdefault((row["variant"], remaining), set()).add(row["pair_id"])
    attempts = 0
    for (variant, remaining), target_pair_ids in sorted(groups.items()):
        scratch = project / "scratch" / "short_replan_v2" / "variants" / variant
        shot_map = _variant_repair_shot_map(
            scratch,
            expected_utterance_ids=affected_utterance_ids,
        )
        target_utterance_ids = {
            str(by_pair[pair_id]["utterance_id"]) for pair_id in target_pair_ids
        }
        command = [
            sys.executable,
            str(generator),
            str(scratch),
            "--voice-cast-binding",
            str(scratch / "voice_cast_binding.json"),
            "--dialogue-ledger",
            str(scratch / "dialogue_ledger.json"),
        ]
        for utterance_id in sorted(target_utterance_ids):
            command.extend(["--repair-shot", shot_map[utterance_id]])
        command.extend(
            [
                "--max-acoustic-retries",
                str(remaining - 1),
                "--emit-failed-qc-manifest",
            ]
        )
        try:
            runner(command, check=True)
        except (OSError, subprocess.SubprocessError) as exc:
            raise TonePkError(
                f"{variant} short-replan scratch repair failed: {exc}"
            ) from exc
        _validate_scratch_manifest_scope(
            scratch,
            affected_utterance_ids=affected_utterance_ids,
        )
        _ingest_generated_variant(
            project=project,
            state=state,
            variant=variant,
            utterance_ids=target_utterance_ids,
            runner=runner,
            accumulate_candidates=True,
            variant_project_override=scratch,
        )
        state = _load_checkpoint(project)
        state["generator_path"] = str(generator)
        by_pair = {str(pair["pair_id"]): pair for pair in state["pairs"]}
        attempts += 1
    current_by_id = {str(pair["pair_id"]): pair for pair in state["pairs"]}
    if any(current_by_id[pair_id] != pair for pair_id, pair in before_reused.items()):
        raise TonePkError("short-replan repair changed a reused pair")
    if exhausted:
        labels = ", ".join(f"{pair_id} {variant}" for pair_id, variant in exhausted)
        raise TonePkError(f"candidate budget exhausted for {labels}")
    still_failed = pending_takes(state, phase="source")
    if still_failed:
        raise TonePkError(f"failed takes remain after repair: {still_failed}")
    return {
        "status": "PASS",
        "repaired_take_count": len(failed),
        "attempts": attempts,
    }


def generate_takes(
    project: Path,
    generator: Path,
    *,
    resume: bool,
    runner: Callable[..., Any] = subprocess.run,
    candidate_budgets: dict[tuple[str, str], int] | None = None,
    target_takes: set[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    project_path = Path(project).expanduser().resolve()
    generator_path = Path(generator).expanduser().resolve()
    if not generator_path.is_file():
        raise TonePkError(f"Qwen generator does not exist: {generator_path}")
    state = _load_or_initialize_checkpoint(project_path)
    pairs = state.get("pairs")
    if not isinstance(pairs, list):
        raise TonePkError("tone PK manifest has no pairs")
    fresh_pair_ids = _short_replan_affected_ids(state)
    if fresh_pair_ids and any(
        "candidate_count" not in pair[variant]
        for pair in pairs
        if str(pair.get("pair_id") or "") in fresh_pair_ids
        for variant in ("neutral", "expressive")
    ):
        raise TonePkError(
            "short-replan identities require fresh short-replan generation"
        )
    state["generator_path"] = str(generator_path)
    write_checkpoint(
        project_path,
        pairs,
        run_id=str(state.get("run_id") or ""),
        metadata={"generator_path": str(generator_path)},
    )
    state = _load_checkpoint(project_path)
    pairs = state["pairs"]
    expected_utterance_ids = {str(pair["utterance_id"]) for pair in pairs}
    repair_shot_maps = {
        variant: _variant_repair_shot_map(
            project_path / "variants" / variant,
            expected_utterance_ids=expected_utterance_ids,
        )
        for variant in ("neutral", "expressive")
    }
    ingested_existing = 0
    if resume:
        for variant in ("neutral", "expressive"):
            existing_manifest = (
                project_path
                / "variants"
                / variant
                / "manifests"
                / "narration_manifest.json"
            )
            if not existing_manifest.is_file():
                continue
            utterance_ids = {str(pair["utterance_id"]) for pair in pairs}
            ingested_existing += _ingest_generated_variant(
                project=project_path,
                state=state,
                variant=variant,
                utterance_ids=utterance_ids,
                runner=runner,
                reconcile_existing_source=True,
            )
            state = _load_checkpoint(project_path)
            state["generator_path"] = str(generator_path)
            pairs = state["pairs"]
    source_pending = {
        (row["pair_id"], row["variant"])
        for row in pending_takes(state, phase="source")
    }
    qc_failed_valid_sources = {
        (str(pair["pair_id"]), variant)
        for pair in pairs
        for variant in ("neutral", "expressive")
        if isinstance(pair.get(variant), dict)
        and pair[variant].get("qc_status") != "PASS"
        and _source_artifact_is_valid(pair[variant])
    }
    if resume and target_takes is None and qc_failed_valid_sources:
        failed_labels = ", ".join(
            f"{pair_id}/{variant}"
            for pair_id, variant in sorted(qc_failed_valid_sources)
        )
        raise TonePkError(
            "source audio is valid but speech QC failed for "
            f"{failed_labels}; use qc --repair-failed --max-candidates 3"
        )
    targets = set(source_pending) if resume else {
        (str(pair["pair_id"]), variant)
        for pair in pairs
        for variant in ("neutral", "expressive")
    }
    if target_takes is not None:
        targets &= set(target_takes)
    green_take_keys = {
        (str(pair["pair_id"]), variant)
        for pair in pairs
        for variant in ("neutral", "expressive")
        if isinstance(pair.get(variant), dict)
        and _source_take_is_green(pair[variant])
    }
    skipped_green = len(green_take_keys - targets) if resume else 0
    not_selected = len(source_pending - targets)
    state["generator_path"] = str(generator_path)
    generated = 0
    for variant in ("neutral", "expressive"):
        variant_pairs = [
            pair for pair in pairs if (str(pair["pair_id"]), variant) in targets
        ]
        if not variant_pairs:
            continue
        utterance_ids = {str(pair["utterance_id"]) for pair in variant_pairs}
        command = [
            sys.executable,
            str(generator_path),
            str(project_path / "variants" / variant),
            "--voice-cast-binding",
            str(project_path / "variants" / variant / "voice_cast_binding.json"),
            "--dialogue-ledger",
            str(project_path / "variants" / variant / "dialogue_ledger.json"),
        ]
        existing_source = any(
            isinstance(pair.get(variant), dict)
            and str(pair[variant].get("source_audio_path") or "")
            for pair in variant_pairs
        )
        existing_generation = any(
            isinstance(pair.get(variant), dict)
            and int(pair[variant].get("candidate_count") or 0) > 0
            for pair in variant_pairs
        )
        partial_variant = len(variant_pairs) < len(pairs)
        if existing_source or existing_generation or partial_variant:
            for utterance_id in sorted(utterance_ids):
                command.extend(
                    ["--repair-shot", repair_shot_maps[variant][utterance_id]]
                )
        variant_budgets = [
            candidate_budgets[(str(pair["pair_id"]), variant)]
            for pair in variant_pairs
            if candidate_budgets
            and (str(pair["pair_id"]), variant) in candidate_budgets
        ]
        if variant_budgets:
            remaining_candidates = min(variant_budgets)
            if remaining_candidates < 1:
                raise TonePkError("candidate budget exhausted before repair")
            command.extend(
                ["--max-acoustic-retries", str(remaining_candidates - 1)]
            )
        else:
            command.extend(["--max-acoustic-retries", "0"])
        command.append("--emit-failed-qc-manifest")
        try:
            runner(command, check=True)
        except (OSError, subprocess.SubprocessError) as exc:
            raise TonePkError(f"{variant} Qwen generation failed: {exc}") from exc
        generated += _ingest_generated_variant(
            project=project_path,
            state=state,
            variant=variant,
            utterance_ids=utterance_ids,
            runner=runner,
            accumulate_candidates=bool(variant_budgets),
        )
        state = _load_checkpoint(project_path)
        state["generator_path"] = str(generator_path)
        pairs = state["pairs"]
    write_checkpoint(
        project_path,
        pairs,
        run_id=str(state.get("run_id") or ""),
        metadata={"generator_path": str(generator_path)},
    )
    return {
        "status": "PASS"
        if not pending_takes({"pairs": pairs}, phase="source")
        else "FAIL",
        "generated_take_count": generated,
        "ingested_existing_take_count": ingested_existing,
        "skipped_green_take_count": skipped_green,
        "not_selected_take_count": not_selected,
    }


def repair_failed_takes(
    project: Path,
    *,
    max_candidates: int,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    if not 1 <= max_candidates <= 3:
        raise TonePkError("max candidates must be between 1 and 3")
    project_path = Path(project).expanduser().resolve()
    initial = _load_checkpoint(project_path)
    generator_path = Path(str(initial.get("generator_path") or ""))
    if not generator_path.is_file():
        raise TonePkError("checkpoint has no usable generator path")
    pairs = initial.get("pairs")
    if not isinstance(pairs, list):
        raise TonePkError("tone PK manifest has no pairs")
    if _short_replan_affected_ids(initial):
        return _repair_short_replanned_takes(
            project_path,
            state=initial,
            generator=generator_path,
            max_candidates=max_candidates,
            runner=runner,
        )
    utterance_ids = {str(pair["utterance_id"]) for pair in pairs}
    for variant in ("neutral", "expressive"):
        manifest_path = (
            project_path / "variants" / variant / "manifests" / "narration_manifest.json"
        )
        if manifest_path.is_file():
            _ingest_generated_variant(
                project=project_path,
                state=initial,
                variant=variant,
                utterance_ids=utterance_ids,
                runner=runner,
                reconcile_existing_source=True,
            )
            initial = _load_checkpoint(project_path)
    failed = pending_takes(initial, phase="source")
    if not failed:
        return {"status": "PASS", "repaired_take_count": 0, "attempts": 0}
    pairs = initial["pairs"]
    by_pair = {str(pair.get("pair_id") or ""): pair for pair in pairs}
    budgets: dict[tuple[str, str], int] = {}
    repair_groups: dict[tuple[str, int], set[tuple[str, str]]] = {}
    exhausted: list[tuple[str, str]] = []
    for row in failed:
        pair = by_pair[row["pair_id"]]
        take = pair[row["variant"]]
        used = int(take.get("candidate_count") or 0)
        remaining = max_candidates - used
        if remaining <= 0:
            exhausted.append((row["pair_id"], row["variant"]))
            continue
        budgets[(row["pair_id"], row["variant"])] = remaining
        repair_groups.setdefault((row["variant"], remaining), set()).add(
            (row["pair_id"], row["variant"])
        )
    attempts = 0
    for (_variant, _remaining), target_keys in sorted(repair_groups.items()):
        generate_takes(
            project_path,
            generator_path,
            resume=True,
            runner=runner,
            candidate_budgets={key: budgets[key] for key in target_keys},
            target_takes=target_keys,
        )
        attempts += 1
    current = _load_checkpoint(project_path)
    for pair in current["pairs"]:
        for variant in ("neutral", "expressive"):
            if int(pair[variant].get("candidate_count") or 0) > max_candidates:
                raise TonePkError("candidate budget exceeded after repair")
    if exhausted:
        labels = ", ".join(f"{pair_id} {variant}" for pair_id, variant in exhausted)
        raise TonePkError(f"candidate budget exhausted for {labels}")
    still_failed = pending_takes(current, phase="source")
    if still_failed:
        raise TonePkError(f"failed takes remain after repair: {still_failed}")
    return {
        "status": "PASS",
        "repaired_take_count": len(failed),
        "attempts": attempts,
    }


def normalize_project(
    project: Path,
    *,
    target_lufs: float,
    max_pair_delta_lufs: float,
    normalizer: Callable[..., None] = normalize_take,
    loudness_probe: Callable[[Path], float] = probe_loudness,
    runner: Callable[[list[str]], Any] = lambda command: subprocess.run(
        command, check=True
    ),
) -> dict[str, Any]:
    if not math.isfinite(target_lufs) or not -30 <= target_lufs <= -10:
        raise TonePkError("target LUFS must be between -30 and -10")
    if not math.isfinite(max_pair_delta_lufs) or not 0 <= max_pair_delta_lufs <= 0.5:
        raise TonePkError("max pair delta LUFS must be between 0 and 0.5")
    project_path = Path(project).expanduser().resolve()
    state = _load_checkpoint(project_path)
    source_pending = pending_takes(state, phase="source")
    if source_pending:
        raise TonePkError(f"tone PK has source takes pending: {source_pending}")
    pairs = state.get("pairs")
    if not isinstance(pairs, list):
        raise TonePkError("tone PK manifest has no pairs")
    normalized_count = 0
    for pair in pairs:
        for variant in ("neutral", "expressive"):
            take = pair[variant]
            source = Path(take["source_audio_path"])
            output = project_path / "takes" / "normalized" / f"{take['take_id']}.wav"
            normalizer(
                source,
                output,
                runner,
                target_lufs=target_lufs,
            )
            if not output.is_file():
                raise TonePkError(f"normalized take is missing: {output}")
            take.update(
                {
                    "normalized_audio_path": str(output),
                    "normalized_audio_sha256": _sha256(output),
                    "integrated_lufs": float(loudness_probe(output)),
                }
            )
            normalized_count += 1
            write_checkpoint(
                project_path,
                pairs,
                run_id=str(state.get("run_id") or ""),
                metadata={"generator_path": state.get("generator_path", "")},
            )
    pair_reports = [validate_pair_evidence(pair) for pair in pairs]
    if any(
        report["loudness_delta_lufs"] > max_pair_delta_lufs + 1e-9
        for report in pair_reports
    ):
        raise TonePkError("pair loudness delta exceeds requested maximum")
    write_checkpoint(
        project_path,
        pairs,
        run_id=str(state.get("run_id") or ""),
        metadata={"generator_path": state.get("generator_path", "")},
    )
    report = {
        "schema": "story_video_tone_pk_qc_v1",
        "status": "PASS",
        "pair_count": len(pair_reports),
        "target_lufs": target_lufs,
        "max_pair_delta_lufs": max_pair_delta_lufs,
        "pair_reports": pair_reports,
    }
    _write_json(project_path / "qc" / "tone_pk_qc_report.json", report)
    return {**report, "normalized_take_count": normalized_count}


def _ass_timestamp(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole_seconds, hundredths = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{hundredths:02d}"


def _ass_escape(text: str) -> str:
    return str(text).replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def _ass_color(rgb: str) -> str:
    value = str(rgb).lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", value):
        raise TonePkError(f"invalid role subtitle color: {rgb}")
    red, green, blue = value[0:2], value[2:4], value[4:6]
    return f"&H00{blue}{green}{red}&".upper()


def _write_ass(path: Path, timeline: dict[str, Any], width: int, height: int) -> None:
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Neutral,PingFang TC,78,&H00D0D0D0,&H000000FF,&H00101010,&H00000000,0,0,0,0,100,100,0,0,1,3,0,5,110,110,80,1
Style: Expressive,PingFang TC,78,&H0000D7FF,&H000000FF,&H00101010,&H00000000,0,0,0,0,100,100,0,0,1,3,0,5,110,110,80,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    events = []
    for take in timeline["takes"]:
        style = "Neutral" if take["variant"] == "neutral" else "Expressive"
        label, role_text = str(take["subtitle_text"]).split("\n", maxsplit=1)
        event_text = (
            f"{_ass_escape(label)}\\N"
            f"{{\\c{_ass_color(take['role_color'])}}}{_ass_escape(role_text)}"
        )
        events.append(
            "Dialogue: 0,{start},{end},{style},,0,0,0,,{text}".format(
                start=_ass_timestamp(take["start_seconds"]),
                end=_ass_timestamp(take["end_seconds"]),
                style=style,
                text=event_text,
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")


def render_pk_video(
    project: Path,
    output: Path,
    width: int,
    height: int,
) -> dict[str, Any]:
    if width < 1 or height < 1:
        raise TonePkError("render dimensions must be positive")
    project_path = Path(project).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    state = _load_json(
        project_path / "manifests" / "tone_pk_manifest.json",
        label="tone PK manifest",
    )
    pairs = state.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        raise TonePkError("tone PK manifest has no pairs")
    pending = pending_takes(state)
    if pending:
        raise TonePkError(f"tone PK has pending takes: {pending}")
    timeline = build_pk_timeline(pairs)
    ass_path = project_path / "manifests" / "tone_pk.ass"
    _write_ass(ass_path, timeline, width, height)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s={width}x{height}:r=30:d={timeline['duration_seconds']}",
    ]
    filter_parts: list[str] = []
    audio_labels: list[str] = []
    for index, take in enumerate(timeline["takes"], start=1):
        audio_path = Path(str(take.get("normalized_audio_path") or ""))
        if not audio_path.is_file():
            raise TonePkError(f"normalized take is missing: {audio_path}")
        command.extend(["-i", str(audio_path)])
        delay_ms = round(float(take["start_seconds"]) * 1000)
        label = f"a{index}"
        filter_parts.append(f"[{index}:a]adelay={delay_ms}|{delay_ms}[{label}]")
        audio_labels.append(f"[{label}]")
    filter_parts.append(
        "".join(audio_labels)
        + f"amix=inputs={len(audio_labels)}:duration=longest:normalize=0[aout]"
    )
    command.extend(
        [
            "-filter_complex",
            ";".join(filter_parts),
            "-vf",
            f"ass={ass_path}",
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            "-t",
            str(timeline["duration_seconds"]),
            str(output_path),
        ]
    )
    subprocess.run(command, check=True)
    return {
        "status": "PASS",
        "visual_mode": "black_subtitle",
        "output": str(output_path),
        "pair_count": len(pairs),
        "take_count": len(timeline["takes"]),
        "duration_seconds": timeline["duration_seconds"],
        "subtitle_path": str(ass_path),
    }


def _prepare_command(args: argparse.Namespace) -> dict[str, Any]:
    return prepare_project(
        source_project=args.source_project,
        output_project=args.output_project,
        run_id=args.run_id,
        annotations_path=args.annotations,
        expected_utterance_count=args.expected_utterances,
    )


def _load_checkpoint(project: Path) -> dict[str, Any]:
    return _load_json(
        Path(project).expanduser().resolve()
        / "manifests"
        / "tone_pk_manifest.json",
        label="tone PK manifest",
    )


def _status_command(args: argparse.Namespace) -> dict[str, Any]:
    state = _load_checkpoint(args.project)
    pairs = state.get("pairs")
    if not isinstance(pairs, list):
        raise TonePkError("tone PK manifest has no pairs")
    pending = pending_takes(state)
    status, pair_reports = _pairs_status(pairs)
    takes = [
        pair[variant]
        for pair in pairs
        for variant in ("neutral", "expressive")
        if isinstance(pair.get(variant), dict)
    ]
    return {
        "status": status,
        "pair_count": len(pairs),
        "completed_take_count": len(pairs) * 2 - len(pending),
        "ingested_source_take_count": sum(
            _source_artifact_is_valid(take) for take in takes
        ),
        "source_qc_pass_take_count": sum(
            _source_take_is_green(take) for take in takes
        ),
        "candidate_evidence_take_count": sum(
            type(take.get("candidate_count")) is int
            and take["candidate_count"] > 0
            for take in takes
        ),
        "pending_takes": pending,
        "pair_reports": pair_reports,
    }


def _generate_command(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = (
        Path(args.project).expanduser().resolve()
        / "manifests"
        / "tone_pk_manifest.json"
    )
    state = (
        _load_json(manifest_path, label="tone PK manifest")
        if manifest_path.is_file()
        else None
    )
    if args.fresh_short_replan:
        if state is None:
            raise TonePkError(
                "--fresh-short-replan is only valid for short-replan projects"
            )
        if not _short_replan_affected_ids(state):
            raise TonePkError(
                "--fresh-short-replan is only valid for short-replan projects"
            )
        return generate_fresh_replanned_takes(
            args.project,
            args.generator,
        )
    if state is not None and _short_replan_affected_ids(state):
        raise TonePkError(
            "short-replan projects require fresh short-replan generation via "
            "generate --fresh-short-replan; "
            "use qc --repair-failed for later candidates"
        )
    return generate_takes(
        args.project,
        args.generator,
        resume=args.resume,
    )


def _qc_command(args: argparse.Namespace) -> dict[str, Any]:
    project = Path(args.project).expanduser().resolve()
    repair_result = None
    if args.repair_failed:
        repair_result = repair_failed_takes(
            project,
            max_candidates=args.max_candidates,
        )
    state = _load_checkpoint(project)
    pairs = state.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        raise TonePkError("tone PK manifest has no pairs")
    source_pending = pending_takes(state, phase="source")
    if source_pending:
        raise TonePkError(f"tone PK has failed source takes: {source_pending}")
    complete_pending = pending_takes(state)
    pair_reports = (
        [] if complete_pending else [validate_pair_evidence(pair) for pair in pairs]
    )
    report = {
        "schema": "story_video_tone_pk_qc_v1",
        "status": "PASS",
        "phase": "source_speech" if complete_pending else "pair_final",
        "pair_count": len(pairs),
        "validated_pair_count": len(pair_reports),
        "pair_reports": pair_reports,
        "source_take_count": len(pairs) * 2,
        **({"repair": repair_result} if repair_result is not None else {}),
    }
    _write_json(project / "qc" / "tone_pk_qc_report.json", report)
    return report


def _normalize_command(args: argparse.Namespace) -> dict[str, Any]:
    return normalize_project(
        args.project,
        target_lufs=args.target_lufs,
        max_pair_delta_lufs=args.max_pair_delta_lufs,
    )


def _render_command(args: argparse.Namespace) -> dict[str, Any]:
    return render_pk_video(
        args.project,
        args.output,
        args.width,
        args.height,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare a hash-bound story-video tone PK")
    subcommands = parser.add_subparsers(dest="command", required=True)
    prepare = subcommands.add_parser("prepare", help="write neutral/expressive pair inputs")
    prepare.add_argument("--source-project", type=Path, required=True)
    prepare.add_argument("--output-project", type=Path, required=True)
    prepare.add_argument("--run-id", required=True)
    prepare.add_argument("--annotations", type=Path, required=True)
    prepare.add_argument("--expected-utterances", type=int, required=True)
    prepare.set_defaults(handler=_prepare_command)
    generate = subcommands.add_parser(
        "generate", help="generate or resume source A/B takes"
    )
    generate.add_argument("--project", type=Path, required=True)
    generate.add_argument("--generator", type=Path, required=True)
    generate.add_argument("--resume", action="store_true")
    generate.add_argument(
        "--fresh-short-replan",
        action="store_true",
        help=(
            "run or resume isolated candidate-one generation for a "
            "short-replan project"
        ),
    )
    generate.set_defaults(handler=_generate_command)
    status = subcommands.add_parser("status", help="show resumable take status")
    status.add_argument("--project", type=Path, required=True)
    status.set_defaults(handler=_status_command)
    qc = subcommands.add_parser("qc", help="validate completed A/B evidence")
    qc.add_argument("--project", type=Path, required=True)
    qc.add_argument("--repair-failed", action="store_true")
    qc.add_argument("--max-candidates", type=int, default=3)
    qc.set_defaults(handler=_qc_command)
    normalize = subcommands.add_parser(
        "normalize", help="normalize takes and validate pair loudness"
    )
    normalize.add_argument("--project", type=Path, required=True)
    normalize.add_argument("--target-lufs", type=float, default=-18.0)
    normalize.add_argument("--max-pair-delta-lufs", type=float, default=0.5)
    normalize.set_defaults(handler=_normalize_command)
    render = subcommands.add_parser("render", help="render the black-subtitle PK video")
    render.add_argument("--project", type=Path, required=True)
    render.add_argument("--output", type=Path, required=True)
    render.add_argument("--width", type=int, default=1920)
    render.add_argument("--height", type=int, default=1080)
    render.set_defaults(handler=_render_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.handler(args)
    except TonePkError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
