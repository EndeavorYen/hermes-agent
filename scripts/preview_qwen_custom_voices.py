#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

import numpy as np


def generate_previews(
    *,
    model_path: str,
    output_dir: str | Path,
    text: str,
    speakers: list[str],
    language: str,
    model_loader: Callable[[str], Any] | None = None,
    audio_writer: Callable[[Path, np.ndarray, int], Any] | None = None,
) -> list[Path]:
    if model_loader is None:
        from mlx_audio.tts.utils import load_model

        model_loader = load_model
    if audio_writer is None:
        from mlx_audio.audio_io import write

        audio_writer = write

    model = model_loader(model_path)
    supported = {
        str(speaker).casefold() for speaker in model.get_supported_speakers()
    }
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for speaker in speakers:
        if speaker.casefold() not in supported:
            raise ValueError(f"unsupported Qwen CustomVoice speaker: {speaker}")
        chunks = list(
            model.generate_custom_voice(
                text=text,
                speaker=speaker,
                language=language,
                temperature=0.7,
                top_p=0.9,
                repetition_penalty=1.05,
                max_tokens=1200,
                verbose=False,
            )
        )
        if not chunks:
            raise RuntimeError(f"Qwen produced no audio for {speaker}")
        sample_rates = {int(chunk.sample_rate) for chunk in chunks}
        if len(sample_rates) != 1:
            raise RuntimeError(f"Qwen returned mixed sample rates for {speaker}")
        audio = np.concatenate(
            [np.asarray(chunk.audio, dtype=np.float32) for chunk in chunks]
        )
        path = destination / f"{speaker}.wav"
        audio_writer(path, audio, sample_rates.pop())
        paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a short batch of local Qwen CustomVoice previews."
    )
    parser.add_argument("--model", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--speaker", action="append", required=True)
    parser.add_argument("--language", default="chinese")
    args = parser.parse_args()
    paths = generate_previews(
        model_path=args.model,
        output_dir=args.output_dir,
        text=args.text,
        speakers=args.speaker,
        language=args.language,
    )
    print(json.dumps({"success": True, "paths": [str(path) for path in paths]}))


if __name__ == "__main__":
    main()
