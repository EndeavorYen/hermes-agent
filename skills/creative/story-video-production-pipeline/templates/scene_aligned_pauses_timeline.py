#!/usr/bin/env python3
"""
Template: scene/paragraph-aligned story-video timeline with deliberate pauses.

Copy this into a story-video project and adapt paths, SCENES, image loading,
subtitle drawing, and render implementation. The key pattern is that subtitles
use speech_ranges while visuals use visual_ranges, so each image holds through
an intentional silent breath gap after its narration.
"""
from pathlib import Path
import subprocess

ROOT = Path(".")
OPENING = 4.0
ENDING = 5.0
RATE = "165"
VOICE = "Meijia"  # macOS draft fallback; replace with stronger TTS when available.

SCENES = [
    "Scene 1 narration text...",
    "Scene 2 narration text...",
]
# Ordinary scenes: ~0.4-0.8s; major turns/morals: ~0.8-1.2s.
PAUSES = [0.6, 0.9]

AUDIO_DIR = ROOT / "audio" / "scene_aligned_pauses"
VOICE_CONCAT = AUDIO_DIR / "voiceover_scene_aligned_pauses.mp3"


def run(cmd):
    subprocess.check_call(cmd)


def probe_duration(path: Path) -> float:
    out = subprocess.check_output([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path)
    ], text=True).strip()
    return float(out)


def make_scene_audio():
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    speech_files = []
    concat_items = []
    for i, text in enumerate(SCENES, 1):
        txt = AUDIO_DIR / f"scene_{i:02d}.txt"
        aiff = AUDIO_DIR / f"scene_{i:02d}.aiff"
        mp3 = AUDIO_DIR / f"scene_{i:02d}.mp3"
        silence = AUDIO_DIR / f"silence_after_scene_{i:02d}.mp3"
        txt.write_text(text, encoding="utf-8")
        run(["say", "-v", VOICE, "-r", RATE, "-o", str(aiff), "-f", str(txt)])
        run(["ffmpeg", "-y", "-v", "error", "-i", str(aiff), "-codec:a", "libmp3lame", "-q:a", "4", str(mp3)])
        run([
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
            "-i", "anullsrc=r=22050:cl=mono", "-t", f"{PAUSES[i-1]:.3f}",
            "-codec:a", "libmp3lame", "-q:a", "4", str(silence)
        ])
        speech_files.append(mp3)
        concat_items.extend([mp3, silence])
    concat = AUDIO_DIR / "concat.txt"
    concat.write_text("".join(f"file {p.name}\n" for p in concat_items), encoding="utf-8")
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat), "-c:a", "libmp3lame", "-q:a", "4", str(VOICE_CONCAT)])
    return speech_files


def build_ranges(speech_files):
    scene_durs = [probe_duration(p) for p in speech_files]
    concat_dur = probe_duration(VOICE_CONCAT)
    total = OPENING + concat_dur + ENDING
    speech_ranges = []
    visual_ranges = []
    t = OPENING
    for i, d in enumerate(scene_durs, 1):
        speech_st = t
        speech_en = t + d
        visual_en = speech_en + PAUSES[i - 1]
        speech_ranges.append((speech_st, speech_en, i))
        visual_ranges.append((speech_st, visual_en, i))
        t = visual_en
    # Compensate for small encoder/concat padding on the final scene.
    visual_ranges[-1] = (visual_ranges[-1][0], OPENING + concat_dur, visual_ranges[-1][2])
    return speech_ranges, visual_ranges, total


if __name__ == "__main__":
    files = make_scene_audio()
    speech_ranges, visual_ranges, total = build_ranges(files)
    print("speech_ranges=", speech_ranges)
    print("visual_ranges=", visual_ranges)
    print("total=", total)
    print("Next: render images from visual_ranges; place subtitles only within speech_ranges.")
