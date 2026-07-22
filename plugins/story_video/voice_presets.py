from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable


DEFAULT_CUSTOM_VOICE_MODEL_PATH = (
    Path.home()
    / ".hermes"
    / "models"
    / "Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit"
)
DEFAULT_MLX_PYTHON = (
    Path.home() / ".hermes" / ".venvs" / "mlx-audio" / "bin" / "python"
)
DEFAULT_PREVIEW_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "preview_qwen_custom_voices.py"
)
DEFAULT_PREVIEW_ROOT = Path.home() / ".hermes" / "story_video_voice_samples"
DEFAULT_SAMPLE_TEXT = (
    "你好，我是 Qwen3-TTS 的聲線示範。這是一小段繁體中文旁白，"
    "讓你比較音色、語氣和清晰度。"
)
MAX_PREVIEW_SPEAKERS = 3
MAX_SAMPLE_TEXT_LENGTH = 160
MAX_RETAINED_PREVIEW_RUNS = 20
_PREVIEW_DIR_PREFIX = "qwen-custom-voice-"

PRESET_VOICES: dict[str, dict[str, Any]] = {
    "vivian": {
        "speaker": "Vivian",
        "gender_style": "女，明亮年輕",
        "native_language": "中文",
        "catalog_voice_id": "qwen_custom_vivian",
        "locale": "zh-CN",
        "traits": {
            "gender_presentation": "female",
            "age_impression": "young",
            "styles": ["bright", "clear"],
        },
        "character_dubbing": True,
    },
    "serena": {
        "speaker": "Serena",
        "gender_style": "女，溫暖柔和",
        "native_language": "中文",
        "catalog_voice_id": "qwen_custom_serena",
        "locale": "zh-CN",
        "traits": {
            "gender_presentation": "female",
            "age_impression": "adult",
            "styles": ["warm", "soft"],
        },
        "character_dubbing": True,
    },
    "uncle_fu": {
        "speaker": "Uncle_Fu",
        "gender_style": "男，低沉成熟",
        "native_language": "中文",
        "catalog_voice_id": "qwen_custom_uncle_fu",
        "locale": "zh-CN",
        "traits": {
            "gender_presentation": "male",
            "age_impression": "older",
            "styles": ["deep", "mature"],
        },
        "character_dubbing": True,
    },
    "ryan": {
        "speaker": "Ryan",
        "gender_style": "男，節奏鮮明",
        "native_language": "英文",
        "character_dubbing": False,
    },
    "aiden": {
        "speaker": "Aiden",
        "gender_style": "男，陽光清晰",
        "native_language": "英文",
        "character_dubbing": False,
    },
    "ono_anna": {
        "speaker": "Ono_Anna",
        "gender_style": "女，輕快俏皮",
        "native_language": "日文",
        "character_dubbing": False,
    },
    "sohee": {
        "speaker": "Sohee",
        "gender_style": "女，溫暖有情感",
        "native_language": "韓文",
        "character_dubbing": False,
    },
    "eric": {
        "speaker": "Eric",
        "gender_style": "男，活潑略沙啞",
        "native_language": "四川話",
        "character_dubbing": False,
    },
    "dylan": {
        "speaker": "Dylan",
        "gender_style": "男，年輕自然",
        "native_language": "北京話",
        "character_dubbing": False,
    },
}


class VoicePresetError(RuntimeError):
    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


def _remove_preview_dir(path: Path, *, root: Path) -> None:
    if path.parent == root and path.name.startswith(_PREVIEW_DIR_PREFIX):
        shutil.rmtree(path, ignore_errors=True)


def _prune_preview_runs(root: Path, *, preserve: Path) -> None:
    directories = [
        path
        for path in root.glob(f"{_PREVIEW_DIR_PREFIX}*")
        if path.is_dir()
    ]
    directories.sort(
        key=lambda path: (path == preserve, path.stat().st_mtime),
        reverse=True,
    )
    for path in directories[MAX_RETAINED_PREVIEW_RUNS:]:
        _remove_preview_dir(path, root=root)


def _load_supported_speakers(model_path: Path) -> set[str]:
    config_path = model_path / "config.json"
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VoicePresetError(
            "voice_preset_model_invalid",
            f"cannot read Qwen CustomVoice model config: {config_path}: {exc}",
        ) from exc
    if payload.get("tts_model_type") != "custom_voice":
        raise VoicePresetError(
            "voice_preset_model_invalid",
            f"Qwen model is not CustomVoice: {model_path}",
        )
    speaker_ids = payload.get("talker_config", {}).get("spk_id", {})
    if not isinstance(speaker_ids, dict) or not speaker_ids:
        raise VoicePresetError(
            "voice_preset_model_invalid",
            f"Qwen CustomVoice model has no preset speakers: {model_path}",
        )
    return {str(name).casefold() for name in speaker_ids}


def _normalize_speakers(speakers: list[Any]) -> list[str]:
    if not speakers:
        raise VoicePresetError(
            "voice_preset_speakers_required",
            "at least one Qwen CustomVoice preset speaker is required",
        )
    if len(speakers) > MAX_PREVIEW_SPEAKERS:
        raise VoicePresetError(
            "voice_preset_limit_exceeded",
            f"at most {MAX_PREVIEW_SPEAKERS} preset speakers can be previewed at once",
        )
    normalized: list[str] = []
    seen: set[str] = set()
    for value in speakers:
        key = str(value or "").strip().casefold()
        preset = PRESET_VOICES.get(key)
        if preset is None:
            raise VoicePresetError(
                "voice_preset_unsupported",
                f"unsupported Qwen CustomVoice preset: {value!r}",
            )
        if key not in seen:
            normalized.append(preset["speaker"])
            seen.add(key)
    return normalized


def preview_custom_voice_presets(
    *,
    speakers: list[Any],
    sample_text: str = "",
    model_path: str | Path = DEFAULT_CUSTOM_VOICE_MODEL_PATH,
    python_path: str | Path = DEFAULT_MLX_PYTHON,
    script_path: str | Path = DEFAULT_PREVIEW_SCRIPT,
    output_root: str | Path = DEFAULT_PREVIEW_ROOT,
    command_runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    normalized = _normalize_speakers(speakers)
    model = Path(model_path).expanduser().resolve()
    supported = _load_supported_speakers(model)
    unsupported = [name for name in normalized if name.casefold() not in supported]
    if unsupported:
        raise VoicePresetError(
            "voice_preset_unsupported",
            "Qwen CustomVoice model does not support: " + ", ".join(unsupported),
        )

    text = str(sample_text or "").strip() or DEFAULT_SAMPLE_TEXT
    if len(text) > MAX_SAMPLE_TEXT_LENGTH:
        raise VoicePresetError(
            "voice_preset_text_invalid",
            f"sample text must be at most {MAX_SAMPLE_TEXT_LENGTH} characters",
        )

    python = Path(python_path).expanduser().absolute()
    script = Path(script_path).expanduser().resolve()
    missing = [str(path) for path in (python, script) if not path.is_file()]
    if missing:
        raise VoicePresetError(
            "voice_preset_runtime_missing",
            "missing local Qwen preview runtime: " + ", ".join(missing),
        )

    root = Path(output_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    output_dir = Path(tempfile.mkdtemp(prefix=_PREVIEW_DIR_PREFIX, dir=root))
    command = [
        str(python),
        str(script),
        "--model",
        str(model),
        "--output-dir",
        str(output_dir),
        "--language",
        "chinese",
        "--text",
        text,
    ]
    for speaker in normalized:
        command.extend(["--speaker", speaker])
    try:
        result = command_runner(
            command,
            capture_output=True,
            text=True,
            timeout=360,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        _remove_preview_dir(output_dir, root=root)
        raise VoicePresetError(
            "voice_preset_preview_timeout",
            "Qwen CustomVoice preview timed out after 360 seconds",
        ) from exc
    except OSError as exc:
        _remove_preview_dir(output_dir, root=root)
        raise VoicePresetError(
            "voice_preset_preview_failed",
            f"cannot start Qwen CustomVoice preview: {exc}",
        ) from exc
    if int(result.returncode or 0) != 0:
        detail = str(result.stderr or result.stdout or "unknown preview failure").strip()
        _remove_preview_dir(output_dir, root=root)
        raise VoicePresetError(
            "voice_preset_preview_failed",
            f"Qwen CustomVoice preview failed: {detail[-1200:]}",
        )

    samples: list[dict[str, str]] = []
    for speaker in normalized:
        path = output_dir / f"{speaker}.wav"
        if not path.is_file() or path.stat().st_size == 0:
            _remove_preview_dir(output_dir, root=root)
            raise VoicePresetError(
                "voice_preset_preview_missing",
                f"Qwen CustomVoice preview did not produce: {path}",
            )
        metadata = PRESET_VOICES[speaker.casefold()]
        samples.append({**metadata, "path": str(path)})
    _prune_preview_runs(root, preserve=output_dir)
    return {
        "model_path": str(model),
        "language": "chinese",
        "speakers": normalized,
        "sample_text": text,
        "samples": samples,
        "media": [f"MEDIA:{sample['path']}" for sample in samples],
    }
