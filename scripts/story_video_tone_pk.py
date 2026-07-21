#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from plugins.story_video.tone_map import (
    ToneMapError,
    build_tone_catalog,
    resolve_utterance_tone,
)


class TonePkError(RuntimeError):
    pass


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
    if ledger.get("schema") != "story_video_dialogue_ledger_v2":
        raise TonePkError("source dialogue ledger must use story_video_dialogue_ledger_v2")
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


def _prepare_command(args: argparse.Namespace) -> dict[str, Any]:
    return prepare_project(
        source_project=args.source_project,
        output_project=args.output_project,
        run_id=args.run_id,
        annotations_path=args.annotations,
        expected_utterance_count=args.expected_utterances,
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
