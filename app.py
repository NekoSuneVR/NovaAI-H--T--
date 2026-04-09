from __future__ import annotations

import copy
import ctypes
import json
import os
import queue
import re
import sys
import threading
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import requests
import sounddevice as sd
import speech_recognition as sr
import torch
from dotenv import load_dotenv
from TTS.api import TTS


ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
AUDIO_DIR = ROOT_DIR / "audio"
PROFILE_PATH = DATA_DIR / "profile.json"
HISTORY_PATH = DATA_DIR / "history.jsonl"

DEFAULT_PROFILE: dict[str, Any] = {
    "user_name": "Friend",
    "companion_name": "NovaAI",
    "companion_style": (
        "blunt, dry, sharp-tongued, sarcastic, low-patience, and natural. "
        "Talk like a brutally honest friend with attitude and bite, "
        "not like a corporate assistant."
    ),
    "shared_goals": [
        "have sharp and entertaining conversations",
        "be direct instead of sugarcoating things",
        "keep replies short and punchy",
        "notice preferences and remember what matters",
    ],
    "memory_notes": [],
}

XTTS_STREAM_END = object()

VOICE_COMMAND_ALIASES = {
    "help": "/help",
    "text mode": "/mode text",
    "typing mode": "/mode text",
    "switch to text mode": "/mode text",
    "stop listening": "/mode text",
    "voice mode": "/mode voice",
    "hands free mode": "/mode voice",
    "hands free": "/mode voice",
    "switch to voice mode": "/mode voice",
    "mute yourself": "/voice off",
    "turn voice off": "/voice off",
    "unmute yourself": "/voice on",
    "turn voice on": "/voice on",
    "clear history": "/reset",
    "reset history": "/reset",
    "recalibrate": "/recalibrate",
    "recalibrate microphone": "/recalibrate",
    "calibrate microphone": "/recalibrate",
    "show speakers": "/speakers",
    "list speakers": "/speakers",
    "show microphones": "/mics",
    "list microphones": "/mics",
    "goodbye": "/exit",
    "quit": "/exit",
    "exit": "/exit",
}


@dataclass
class Config:
    model: str
    ollama_api_url: str
    ollama_keep_alive: str
    ollama_num_predict: int
    tts_language: str
    xtts_model_name: str
    xtts_speaker: str
    xtts_speaker_wav: str | None
    xtts_use_gpu: bool
    xtts_stream_output: bool
    xtts_stream_chunk_size: int
    xtts_stream_buffer_seconds: float
    xtts_chunk_max_chars: int
    xtts_max_text_chars: int
    xtts_speed: float
    history_turns: int
    temperature: float
    request_timeout: int
    voice_enabled: bool
    input_mode: str
    stt_provider: str
    stt_model: str
    stt_compute_type: str
    stt_beam_size: int
    stt_best_of: int
    stt_vad_filter: bool
    stt_language: str
    stt_timeout_seconds: float
    stt_phrase_time_limit_seconds: float
    stt_pause_threshold_seconds: float
    stt_non_speaking_duration_seconds: float
    stt_ambient_duration_seconds: float
    stt_energy_threshold: int
    stt_dynamic_energy_threshold: bool
    mic_device_index: int | None
    mic_sample_rate: int | None
    mic_chunk_size: int

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        pause_threshold_ms = int(os.getenv("STT_END_SILENCE_TIMEOUT_MS", "900"))
        legacy_xtts_max_chars = max(80, int(os.getenv("XTTS_MAX_CHARS", "240")))
        xtts_chunk_max_chars = max(
            80,
            min(
                240,
                int(
                    os.getenv(
                        "XTTS_CHUNK_MAX_CHARS",
                        str(min(240, legacy_xtts_max_chars)),
                    )
                ),
            ),
        )
        xtts_max_text_chars = max(
            xtts_chunk_max_chars,
            int(
                os.getenv(
                    "XTTS_MAX_TEXT_CHARS",
                    str(
                        legacy_xtts_max_chars
                        if legacy_xtts_max_chars > 240
                        else 5000
                    ),
                )
            ),
        )
        return cls(
            model=os.getenv("OLLAMA_MODEL", "dolphin3"),
            ollama_api_url=os.getenv(
                "OLLAMA_API_URL", "http://127.0.0.1:11434/api/chat"
            ),
            ollama_keep_alive=os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
            ollama_num_predict=max(48, int(os.getenv("OLLAMA_NUM_PREDICT", "1200"))),
            tts_language=os.getenv("XTTS_LANGUAGE")
            or os.getenv("TTS_LANG")
            or os.getenv("STT_LANGUAGE", "en"),
            xtts_model_name=os.getenv(
                "XTTS_MODEL_NAME",
                "tts_models/multilingual/multi-dataset/xtts_v2",
            ),
            xtts_speaker=os.getenv("XTTS_SPEAKER", "Ana Florence"),
            xtts_speaker_wav=parse_optional_str_env("XTTS_SPEAKER_WAV"),
            xtts_use_gpu=parse_bool_env("XTTS_USE_GPU", True),
            xtts_stream_output=parse_bool_env("XTTS_STREAM_OUTPUT", True),
            xtts_stream_chunk_size=max(
                10, int(os.getenv("XTTS_STREAM_CHUNK_SIZE", "20"))
            ),
            xtts_stream_buffer_seconds=max(
                0.0, float(os.getenv("XTTS_STREAM_BUFFER_SECONDS", "1.8"))
            ),
            xtts_chunk_max_chars=xtts_chunk_max_chars,
            xtts_max_text_chars=xtts_max_text_chars,
            xtts_speed=max(0.8, float(os.getenv("XTTS_SPEED", "1.08"))),
            history_turns=int(os.getenv("HISTORY_TURNS", "10")),
            temperature=float(os.getenv("OLLAMA_TEMPERATURE", "0.95")),
            request_timeout=int(os.getenv("REQUEST_TIMEOUT", "300")),
            voice_enabled=parse_bool_env("VOICE_ENABLED", True),
            input_mode=normalize_input_mode(os.getenv("INPUT_MODE", "voice")),
            stt_provider=normalize_stt_provider(
                os.getenv("STT_PROVIDER", "faster-whisper")
            ),
            stt_model=os.getenv("STT_MODEL", "small.en"),
            stt_compute_type=os.getenv("STT_COMPUTE_TYPE", "").strip().lower(),
            stt_beam_size=max(1, int(os.getenv("STT_BEAM_SIZE", "5"))),
            stt_best_of=max(1, int(os.getenv("STT_BEST_OF", "5"))),
            stt_vad_filter=parse_bool_env("STT_VAD_FILTER", False),
            stt_language=os.getenv("STT_LANGUAGE")
            or os.getenv("STT_CULTURE", "en-US"),
            stt_timeout_seconds=float(
                os.getenv(
                    "STT_TIMEOUT_SECONDS",
                    os.getenv("STT_INITIAL_SILENCE_TIMEOUT_SECONDS", "15"),
                )
            ),
            stt_phrase_time_limit_seconds=float(
                os.getenv(
                    "STT_PHRASE_TIME_LIMIT_SECONDS",
                    os.getenv("STT_BABBLE_TIMEOUT_SECONDS", "30"),
                )
            ),
            stt_pause_threshold_seconds=float(
                os.getenv(
                    "STT_PAUSE_THRESHOLD_SECONDS",
                    str(max(1.8, pause_threshold_ms / 1000)),
                )
            ),
            stt_non_speaking_duration_seconds=float(
                os.getenv("STT_NON_SPEAKING_DURATION_SECONDS", "1.2")
            ),
            stt_ambient_duration_seconds=float(
                os.getenv("STT_AMBIENT_DURATION_SECONDS", "0.6")
            ),
            stt_energy_threshold=int(os.getenv("STT_ENERGY_THRESHOLD", "300")),
            stt_dynamic_energy_threshold=parse_bool_env(
                "STT_DYNAMIC_ENERGY_THRESHOLD", True
            ),
            mic_device_index=parse_optional_int_env("MIC_DEVICE_INDEX"),
            mic_sample_rate=parse_optional_int_env("MIC_SAMPLE_RATE"),
            mic_chunk_size=int(os.getenv("MIC_CHUNK_SIZE", "1024")),
        )


@dataclass
class SessionState:
    voice_enabled: bool
    input_mode: str
    speech_recognizer: sr.Recognizer | None = None
    speech_recognizer_signature: tuple[Any, ...] | None = None
    mic_calibrated: bool = False
    stt_model_instance: Any = None
    stt_model_signature: tuple[Any, ...] | None = None
    xtts_model: TTS | None = None
    xtts_device: str | None = None
    xtts_speakers: list[str] | None = None
    xtts_cached_voice_key: str | None = None
    xtts_cached_conditioning: tuple[torch.Tensor, torch.Tensor] | None = None


@dataclass
class UserTurn:
    text: str
    from_voice: bool


@dataclass
class CommandResult:
    handled: bool
    injected_turn: UserTurn | None = None
    should_exit: bool = False


@dataclass
class SpeechCapture:
    status: str
    text: str = ""
    confidence: float | None = None
    language: str = ""
    device_name: str = ""
    error: str = ""


class SoundDeviceStream:
    def __init__(self, raw_stream: sd.RawInputStream):
        self.raw_stream = raw_stream

    def read(self, size: int) -> bytes:
        data, _overflowed = self.raw_stream.read(size)
        return bytes(data)

    def close(self) -> None:
        try:
            self.raw_stream.stop()
        except Exception:
            pass
        self.raw_stream.close()


class SoundDeviceMicrophone(sr.AudioSource):
    def __init__(
        self,
        device_index: int | None = None,
        sample_rate: int | None = None,
        chunk_size: int = 1024,
    ):
        assert device_index is None or isinstance(device_index, int)
        assert sample_rate is None or (isinstance(sample_rate, int) and sample_rate > 0)
        assert isinstance(chunk_size, int) and chunk_size > 0

        device_info = resolve_input_device_info(device_index)
        self.device_index = device_info["index"]
        self.device_name = device_info["name"]
        default_sample_rate = device_info["default_sample_rate"]

        self.SAMPLE_WIDTH = 2
        self.SAMPLE_RATE = sample_rate or default_sample_rate
        self.CHUNK = chunk_size
        self.stream: SoundDeviceStream | None = None
        self._raw_stream: sd.RawInputStream | None = None

    def __enter__(self) -> "SoundDeviceMicrophone":
        assert self.stream is None, "This audio source is already inside a context manager"
        try:
            self._raw_stream = sd.RawInputStream(
                samplerate=self.SAMPLE_RATE,
                blocksize=self.CHUNK,
                device=self.device_index,
                channels=1,
                dtype="int16",
            )
            self._raw_stream.start()
        except Exception as exc:
            raise RuntimeError(
                f"Could not open microphone '{self.device_name}'. {exc}"
            ) from exc

        self.stream = SoundDeviceStream(self._raw_stream)
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self.stream is not None:
            self.stream.close()
        self.stream = None
        self._raw_stream = None


def parse_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_optional_int_env(name: str) -> int | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    return int(value)


def parse_optional_str_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def normalize_input_mode(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"voice", "mic", "microphone", "handsfree", "hands-free"}:
        return "voice"
    return "text"


def normalize_stt_provider(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"google", "web"}:
        return "google"
    return "faster-whisper"


def parse_input_mode(argument: str) -> str | None:
    normalized = argument.strip().lower()
    if normalized in {"voice", "mic", "microphone", "handsfree", "hands-free"}:
        return "voice"
    if normalized in {"text", "typing", "keyboard"}:
        return "text"
    return None


def clone_default_profile() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_PROFILE)


def console_safe_text(value: Any) -> str:
    text = str(value)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        return text.encode(encoding, errors="replace").decode(encoding, errors="replace")
    except Exception:
        return text


def ensure_runtime_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    AUDIO_DIR.mkdir(exist_ok=True)


def get_stt_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def get_stt_compute_type(config: Config) -> str:
    if config.stt_compute_type and config.stt_compute_type not in {"auto", "default"}:
        return config.stt_compute_type
    if get_stt_device() == "cuda":
        return "float16"
    return "int8"


def get_default_input_device_index() -> int | None:
    default_device = sd.default.device
    if isinstance(default_device, (list, tuple)):
        if not default_device:
            return None
        candidate = default_device[0]
    else:
        candidate = default_device

    if candidate is None:
        return None

    try:
        candidate_index = int(candidate)
    except (TypeError, ValueError):
        return None

    if candidate_index < 0:
        return None

    return candidate_index


def resolve_input_device_info(device_index: int | None) -> dict[str, Any]:
    try:
        if device_index is None:
            device = sd.query_devices(kind="input")
            resolved_index = get_default_input_device_index()
        else:
            device = sd.query_devices(device_index, "input")
            resolved_index = device_index
    except Exception as exc:
        chosen = "the default microphone" if device_index is None else f"microphone #{device_index}"
        raise RuntimeError(
            f"I couldn't access {chosen}. Use /mics to list available input devices."
        ) from exc

    device_name = str(device.get("name", "Input device"))
    default_sample_rate = device.get("default_samplerate")
    if not isinstance(default_sample_rate, (int, float)) or default_sample_rate <= 0:
        raise RuntimeError(
            f"The microphone '{device_name}' did not report a valid sample rate."
        )

    return {
        "index": resolved_index,
        "name": device_name,
        "default_sample_rate": int(default_sample_rate),
    }


def list_input_devices() -> list[dict[str, Any]]:
    try:
        devices = sd.query_devices()
    except Exception as exc:
        raise RuntimeError(f"I couldn't list microphone devices. {exc}") from exc

    default_index = get_default_input_device_index()
    input_devices: list[dict[str, Any]] = []
    for index, device in enumerate(devices):
        max_input_channels = device.get("max_input_channels", 0)
        if isinstance(max_input_channels, (int, float)) and max_input_channels > 0:
            input_devices.append(
                {
                    "index": index,
                    "name": str(device.get("name", "Input device")),
                    "is_default": index == default_index,
                }
            )
    return input_devices


def describe_selected_microphone(config: Config) -> str:
    try:
        device_info = resolve_input_device_info(config.mic_device_index)
    except RuntimeError:
        if config.mic_device_index is None:
            return "default microphone"
        return f"microphone #{config.mic_device_index}"

    if device_info["index"] is None:
        return f"default microphone ({device_info['name']})"

    if config.mic_device_index is None:
        return f"default microphone ({device_info['name']})"

    return f"#{device_info['index']} ({device_info['name']})"


def get_speech_recognizer_signature(config: Config) -> tuple[Any, ...]:
    return (
        config.mic_device_index,
        config.mic_sample_rate,
        config.mic_chunk_size,
        config.stt_energy_threshold,
        config.stt_dynamic_energy_threshold,
        config.stt_pause_threshold_seconds,
        config.stt_non_speaking_duration_seconds,
    )


def build_speech_recognizer(config: Config) -> sr.Recognizer:
    recognizer = sr.Recognizer()
    recognizer.energy_threshold = max(50, config.stt_energy_threshold)
    recognizer.dynamic_energy_threshold = config.stt_dynamic_energy_threshold
    recognizer.pause_threshold = max(0.5, config.stt_pause_threshold_seconds)
    recognizer.non_speaking_duration = min(
        recognizer.pause_threshold,
        max(0.5, config.stt_non_speaking_duration_seconds),
    )
    recognizer.phrase_threshold = 0.2
    return recognizer


def ensure_speech_recognizer(config: Config, state: SessionState) -> sr.Recognizer:
    signature = get_speech_recognizer_signature(config)
    if (
        state.speech_recognizer is None
        or state.speech_recognizer_signature != signature
    ):
        state.speech_recognizer = build_speech_recognizer(config)
        state.speech_recognizer_signature = signature
        state.mic_calibrated = False
    return state.speech_recognizer


def get_stt_model_signature(config: Config) -> tuple[Any, ...]:
    return (
        config.stt_provider,
        config.stt_model,
        get_stt_device(),
        get_stt_compute_type(config),
    )


def ensure_stt_model(config: Config, state: SessionState) -> Any:
    if config.stt_provider != "faster-whisper":
        return None

    signature = get_stt_model_signature(config)
    if state.stt_model_instance is not None and state.stt_model_signature == signature:
        return state.stt_model_instance

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed. Run: pip install faster-whisper"
        ) from exc

    try:
        state.stt_model_instance = WhisperModel(
            config.stt_model,
            device=get_stt_device(),
            compute_type=get_stt_compute_type(config),
        )
        state.stt_model_signature = signature
        return state.stt_model_instance
    except Exception as exc:
        raise RuntimeError(
            f"I couldn't load the speech model '{config.stt_model}'. {exc}"
        ) from exc


def recalibrate_microphone(config: Config, state: SessionState) -> None:
    recognizer = ensure_speech_recognizer(config, state)
    if config.stt_ambient_duration_seconds <= 0:
        state.mic_calibrated = True
        return

    print()
    print(
        f"[Mic] Calibrating {describe_selected_microphone(config)} for "
        f"{config.stt_ambient_duration_seconds:.1f}s. Stay quiet for a moment."
    )

    with SoundDeviceMicrophone(
        device_index=config.mic_device_index,
        sample_rate=config.mic_sample_rate,
        chunk_size=config.mic_chunk_size,
    ) as source:
        recognizer.adjust_for_ambient_noise(
            source, duration=config.stt_ambient_duration_seconds
        )

    state.mic_calibrated = True
    print("[Mic] Calibration complete.")


def print_input_devices() -> None:
    devices = list_input_devices()
    print()
    if not devices:
        print("No microphone input devices were found.")
        print()
        return

    print("Available microphones:")
    for device in devices:
        suffix = " (default)" if device["is_default"] else ""
        print(f"{device['index']}: {device['name']}{suffix}")
    print()


def resolve_optional_path(path_value: str | None) -> Path | None:
    if not path_value:
        return None
    candidate = Path(path_value)
    if not candidate.is_absolute():
        candidate = ROOT_DIR / candidate
    return candidate


def get_xtts_device(config: Config) -> str:
    if config.xtts_use_gpu and torch.cuda.is_available():
        return "cuda"
    return "cpu"


def ensure_xtts_model(config: Config, state: SessionState) -> TTS:
    desired_device = get_xtts_device(config)
    if state.xtts_model is None or state.xtts_device != desired_device:
        model = TTS(config.xtts_model_name, progress_bar=False)
        model.to(desired_device)
        state.xtts_model = model
        state.xtts_device = desired_device
        state.xtts_speakers = list(model.speakers or [])
        state.xtts_cached_voice_key = None
        state.xtts_cached_conditioning = None
    return state.xtts_model


def list_xtts_speakers(config: Config, state: SessionState) -> list[str]:
    model = ensure_xtts_model(config, state)
    speakers = list(model.speakers or [])
    state.xtts_speakers = speakers
    return speakers


def print_xtts_speakers(config: Config, state: SessionState) -> None:
    speakers = list_xtts_speakers(config, state)
    print()
    if not speakers:
        print("No built-in XTTS speakers were reported by the current model.")
        print()
        return

    print("Available XTTS speakers:")
    for speaker in speakers:
        suffix = " (current)" if speaker == config.xtts_speaker else ""
        print(console_safe_text(f"- {speaker}{suffix}"))
    print()


def describe_tts_voice(config: Config) -> str:
    speaker_wav = resolve_optional_path(config.xtts_speaker_wav)
    if speaker_wav is not None:
        return f"reference voice file ({speaker_wav})"
    return config.xtts_speaker


def describe_stt_backend(config: Config) -> str:
    if config.stt_provider == "google":
        return "google"
    return (
        f"faster-whisper ({config.stt_model}, "
        f"{get_stt_device()}/{get_stt_compute_type(config)})"
    )


def normalize_stt_language_for_whisper(language: str) -> str | None:
    normalized = language.strip().lower()
    if not normalized or normalized == "auto":
        return None
    if "-" in normalized:
        normalized = normalized.split("-", 1)[0]
    return normalized


def split_long_text_fragment(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    words = text.split()
    if not words:
        return []

    chunks: list[str] = []
    current = ""
    for word in words:
        if not current:
            current = word
            continue

        candidate = f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
            continue

        chunks.append(current)
        current = word

    if current:
        chunks.append(current)

    return chunks


def split_text_for_xtts(text: str, max_chars: int) -> list[str]:
    normalized_text = " ".join(text.split())
    if not normalized_text:
        return []

    sentences = re.split(r"(?<=[.!?])\s+", normalized_text)
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        if not sentence:
            continue

        sentence_parts = split_long_text_fragment(sentence, max_chars)
        for part in sentence_parts:
            if not current:
                current = part
                continue

            candidate = f"{current} {part}"
            if len(candidate) <= max_chars:
                current = candidate
                continue

            chunks.append(current)
            current = part

    if current:
        chunks.append(current)

    return chunks or [normalized_text]


def trim_text_for_tts(text: str, max_chars: int) -> str:
    normalized_text = " ".join(text.split())
    if len(normalized_text) <= max_chars:
        return normalized_text

    trimmed = normalized_text[: max_chars + 1]
    boundary = max(
        trimmed.rfind(". "),
        trimmed.rfind("! "),
        trimmed.rfind("? "),
        trimmed.rfind(", "),
        trimmed.rfind("; "),
        trimmed.rfind(": "),
        trimmed.rfind(" "),
    )
    if boundary > 0:
        trimmed = trimmed[:boundary]
    else:
        trimmed = trimmed[:max_chars]

    return trimmed.rstrip(" ,;:")


def get_xtts_output_sample_rate(model: TTS) -> int:
    sample_rate = getattr(model.synthesizer, "output_sample_rate", None)
    if isinstance(sample_rate, int) and sample_rate > 0:
        return sample_rate

    audio_config = getattr(getattr(model.synthesizer.tts_model, "config", None), "audio", None)
    output_sample_rate = getattr(audio_config, "output_sample_rate", None)
    if isinstance(output_sample_rate, int) and output_sample_rate > 0:
        return output_sample_rate

    return 24000


def resolve_xtts_conditioning(
    config: Config,
    state: SessionState,
    model: TTS,
) -> tuple[torch.Tensor, torch.Tensor]:
    speaker_wav = resolve_optional_path(config.xtts_speaker_wav)
    xtts_model = model.synthesizer.tts_model

    if speaker_wav is not None:
        if not speaker_wav.exists():
            raise RuntimeError(
                f"XTTS speaker reference file was not found: {speaker_wav}"
            )

        resolved_path = str(speaker_wav.resolve())
        cache_key = f"speaker_wav:{resolved_path}"
        if (
            state.xtts_cached_voice_key == cache_key
            and state.xtts_cached_conditioning is not None
        ):
            return state.xtts_cached_conditioning

        conditioning = xtts_model.get_conditioning_latents(audio_path=resolved_path)
        state.xtts_cached_voice_key = cache_key
        state.xtts_cached_conditioning = conditioning
        return conditioning

    available_speakers = state.xtts_speakers or list(model.speakers or [])
    if available_speakers and config.xtts_speaker not in available_speakers:
        raise RuntimeError(
            f"XTTS speaker '{config.xtts_speaker}' was not found. "
            "Run /speakers to list valid voices."
        )

    speaker_data = xtts_model.speaker_manager.speakers.get(config.xtts_speaker)
    if not speaker_data:
        raise RuntimeError(
            f"XTTS speaker '{config.xtts_speaker}' did not expose streaming data."
        )

    return speaker_data["gpt_cond_latent"], speaker_data["speaker_embedding"]


def write_wav_audio(
    audio_path: Path,
    audio_chunks: list[np.ndarray],
    sample_rate: int,
) -> Path:
    if not audio_chunks:
        raise RuntimeError("XTTS did not generate any audio.")

    full_audio = np.concatenate(audio_chunks)
    pcm_audio = np.clip(full_audio, -1.0, 1.0)
    pcm_audio = (pcm_audio * 32767.0).astype(np.int16)

    with wave.open(str(audio_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_audio.tobytes())

    return audio_path


def synthesize_xtts_to_file(
    text: str,
    config: Config,
    state: SessionState,
    model: TTS,
    output_path: Path,
) -> Path:
    speaker_wav = resolve_optional_path(config.xtts_speaker_wav)
    clipped_text = trim_text_for_tts(text, config.xtts_max_text_chars)
    text_chunks = split_text_for_xtts(clipped_text, config.xtts_chunk_max_chars)
    audio_chunks: list[np.ndarray] = []

    base_kwargs: dict[str, Any] = {
        "language": config.tts_language,
        "speed": config.xtts_speed,
        "split_sentences": False,
    }

    if speaker_wav is not None:
        if not speaker_wav.exists():
            raise RuntimeError(
                f"XTTS speaker reference file was not found: {speaker_wav}"
            )
        base_kwargs["speaker_wav"] = str(speaker_wav)
    else:
        available_speakers = state.xtts_speakers or list(model.speakers or [])
        if available_speakers and config.xtts_speaker not in available_speakers:
            raise RuntimeError(
                f"XTTS speaker '{config.xtts_speaker}' was not found. "
                "Run /speakers to list valid voices."
            )
        base_kwargs["speaker"] = config.xtts_speaker

    for text_chunk in text_chunks:
        chunk_audio = model.tts(text=text_chunk, **base_kwargs)
        audio_chunks.append(np.asarray(chunk_audio, dtype=np.float32))

    return write_wav_audio(output_path, audio_chunks, get_xtts_output_sample_rate(model))


def produce_xtts_stream_chunks(
    text: str,
    config: Config,
    state: SessionState,
    model: TTS,
    chunk_queue: queue.SimpleQueue[object],
    producer_errors: list[Exception],
) -> None:
    xtts_model = model.synthesizer.tts_model

    try:
        gpt_cond_latent, speaker_embedding = resolve_xtts_conditioning(
            config, state, model
        )
        clipped_text = trim_text_for_tts(text, config.xtts_max_text_chars)
        for text_chunk in split_text_for_xtts(
            clipped_text, config.xtts_chunk_max_chars
        ):
            chunk_generator = xtts_model.inference_stream(
                text=text_chunk,
                language=config.tts_language,
                gpt_cond_latent=gpt_cond_latent,
                speaker_embedding=speaker_embedding,
                stream_chunk_size=config.xtts_stream_chunk_size,
                speed=config.xtts_speed,
                enable_text_splitting=False,
            )

            for chunk in chunk_generator:
                audio_chunk = chunk.detach().float().cpu().numpy().reshape(-1)
                if audio_chunk.size == 0:
                    continue
                chunk_queue.put(audio_chunk.copy())
    except Exception as exc:
        producer_errors.append(exc)
    finally:
        chunk_queue.put(XTTS_STREAM_END)


def stream_xtts_audio(
    text: str,
    config: Config,
    state: SessionState,
    model: TTS,
    output_path: Path,
) -> Path:
    sample_rate = get_xtts_output_sample_rate(model)
    audio_chunks: list[np.ndarray] = []
    chunk_queue: queue.SimpleQueue[object] = queue.SimpleQueue()
    producer_errors: list[Exception] = []
    producer_thread = threading.Thread(
        target=produce_xtts_stream_chunks,
        args=(text, config, state, model, chunk_queue, producer_errors),
        daemon=True,
    )
    producer_thread.start()

    target_buffer_samples = int(sample_rate * config.xtts_stream_buffer_seconds)
    buffered_chunks: list[np.ndarray] = []
    buffered_samples = 0
    stream_finished = False

    while buffered_samples < target_buffer_samples:
        chunk_or_end = chunk_queue.get()
        if chunk_or_end is XTTS_STREAM_END:
            stream_finished = True
            break
        assert isinstance(chunk_or_end, np.ndarray)
        buffered_chunks.append(chunk_or_end)
        buffered_samples += chunk_or_end.size

    audio_stream = sd.OutputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        blocksize=2048,
        latency="high",
    )

    try:
        audio_stream.start()
        pending_chunks = buffered_chunks

        while True:
            if pending_chunks:
                audio_chunk = pending_chunks.pop(0)
            elif stream_finished:
                break
            else:
                chunk_or_end = chunk_queue.get()
                if chunk_or_end is XTTS_STREAM_END:
                    stream_finished = True
                    break
                assert isinstance(chunk_or_end, np.ndarray)
                audio_chunk = chunk_or_end

            audio_chunks.append(audio_chunk)
            audio_stream.write(
                np.ascontiguousarray(audio_chunk.reshape(-1, 1), dtype=np.float32)
            )
    finally:
        try:
            audio_stream.stop()
        except Exception:
            pass
        audio_stream.close()
        producer_thread.join()

    if producer_errors:
        raise RuntimeError(f"XTTS streaming failed. {producer_errors[0]}")

    return write_wav_audio(output_path, audio_chunks, sample_rate)


def load_profile() -> dict[str, Any]:
    if not PROFILE_PATH.exists():
        save_profile(clone_default_profile())
        return clone_default_profile()

    with PROFILE_PATH.open("r", encoding="utf-8") as profile_file:
        profile = json.load(profile_file)

    updated_profile = clone_default_profile()
    updated_profile.update(profile)
    if updated_profile != profile:
        save_profile(updated_profile)
    return updated_profile


def save_profile(profile: dict[str, Any]) -> None:
    PROFILE_PATH.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def read_recent_history(max_turns: int) -> list[dict[str, str]]:
    if not HISTORY_PATH.exists() or max_turns <= 0:
        return []

    with HISTORY_PATH.open("r", encoding="utf-8") as history_file:
        lines = history_file.readlines()

    recent_lines = lines[-(max_turns * 2) :]
    messages: list[dict[str, str]] = []
    for line in recent_lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        role = entry.get("role")
        content = entry.get("content")
        if role in {"user", "assistant"} and isinstance(content, str):
            messages.append({"role": role, "content": content})
    return messages


def append_history(role: str, content: str) -> None:
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "role": role,
        "content": content,
    }
    with HISTORY_PATH.open("a", encoding="utf-8") as history_file:
        history_file.write(json.dumps(entry, ensure_ascii=False) + "\n")


def reset_history() -> None:
    if HISTORY_PATH.exists():
        HISTORY_PATH.unlink()


def build_system_prompt(profile: dict[str, Any]) -> str:
    memory_notes = profile.get("memory_notes") or []
    shared_goals = profile.get("shared_goals") or []

    goals_text = ", ".join(shared_goals) if shared_goals else "be a kind companion"
    memory_text = (
        "; ".join(str(note) for note in memory_notes)
        if memory_notes
        else "No saved memory notes yet."
    )

    return f"""
You are {profile['companion_name']}, an AI friend and companion for {profile['user_name']}.

Your personality:
- {profile['companion_style']}
- Sound human, relaxed, sharp, and hard to impress.
- Use contractions and natural phrasing.
- Keep most replies conversational instead of overly formal.
- Be blunt, a little rude, and emotionally detached by default.
- Have attitude, dry sarcasm, and side-eye energy.

How to talk:
- Respond like a real friend with a sharp mouth and very little patience.
- Do not act nurturing, overly kind, or eager to help.
- Do not offer help unless the user clearly and directly asks for it.
- If the user is venting or upset, do not baby them or over-validate them.
- Never use emojis, emoticons, or decorative symbols.
- Default to 1 to 3 short sentences so replies feel snappy in voice mode.
- Only go longer when the user clearly asks for more detail or a step-by-step explanation.
- Keep the tone natural and human, with strong personality instead of sounding sanitized or scripted.
- Be more biting, dismissive, and sarcastic than before, with short snappy comebacks when it fits.
- You can roast, mock, or tease the user a bit when it feels natural, but keep it in the realm of tough-friend banter.
- Keep it sharp without becoming hateful, abusive, or degrading.
- Avoid bullet lists unless they are genuinely the clearest way to help.
- Avoid sounding like a chatbot, therapist script, or customer support bot.

Relationship context:
- Your shared goals are: {goals_text}.
- Things to remember about the user: {memory_text}

Safety and honesty:
- Never manipulate the user or encourage emotional dependency.
- Never pretend to have a body, real-world presence, or real-life experiences.
- If asked directly, be honest that you are an AI companion.
- Never make up facts when you are unsure; say so plainly.
""".strip()


def request_reply(
    user_text: str,
    profile: dict[str, Any],
    config: Config,
) -> str:
    messages = [{"role": "system", "content": build_system_prompt(profile)}]
    messages.extend(read_recent_history(config.history_turns))
    messages.append({"role": "user", "content": user_text})

    payload = {
        "model": config.model,
        "messages": messages,
        "stream": False,
        "keep_alive": config.ollama_keep_alive,
        "options": {
            "temperature": config.temperature,
            "num_predict": config.ollama_num_predict,
        },
    }

    try:
        response = requests.post(
            config.ollama_api_url,
            json=payload,
            timeout=config.request_timeout,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            "I could not reach Ollama. Install/start Ollama, make sure the server is "
            "running, and confirm OLLAMA_API_URL is correct."
        ) from exc

    detail = ""
    try:
        detail = response.json().get("error", "")
    except ValueError:
        detail = response.text.strip()

    if response.status_code >= 400:
        if "not found" in detail.lower():
            raise RuntimeError(
                f"Ollama could not find the model '{config.model}'. "
                f"After installing Ollama, run: ollama pull {config.model}"
            )
        raise RuntimeError(
            f"Ollama returned HTTP {response.status_code}. {detail or 'No error details were returned.'}"
        )

    try:
        data = response.json()
        return data["message"]["content"].strip()
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("Ollama returned an unexpected response format.") from exc


def speak_text(text: str, config: Config, state: SessionState) -> Path:
    cleaned_text = trim_text_for_tts(text, config.xtts_max_text_chars)
    output_path = AUDIO_DIR / "latest_reply.wav"
    model = ensure_xtts_model(config, state)

    if config.xtts_stream_output:
        return stream_xtts_audio(cleaned_text, config, state, model, output_path)

    return synthesize_xtts_to_file(cleaned_text, config, state, model, output_path)


def get_mci_error(error_code: int) -> str:
    buffer = ctypes.create_unicode_buffer(255)
    ctypes.windll.winmm.mciGetErrorStringW(error_code, buffer, len(buffer))
    return buffer.value or f"MCI error {error_code}"


def play_audio_file(audio_path: Path) -> None:
    if os.name != "nt":
        raise RuntimeError("Automatic audio playback is only implemented for Windows.")

    alias = "ai_companion_audio"
    winmm = ctypes.windll.winmm

    def send(command: str) -> None:
        error_code = winmm.mciSendStringW(command, None, 0, None)
        if error_code:
            raise RuntimeError(get_mci_error(error_code))

    try:
        send(f"close {alias}")
    except RuntimeError:
        pass

    try:
        if audio_path.suffix.lower() == ".wav":
            send(f'open "{audio_path}" type waveaudio alias {alias}')
        else:
            send(f'open "{audio_path}" type mpegvideo alias {alias}')
        send(f"play {alias} wait")
    finally:
        try:
            send(f"close {alias}")
        except RuntimeError:
            pass


def map_spoken_command(text: str) -> str:
    normalized = " ".join(text.strip().lower().split())
    return VOICE_COMMAND_ALIASES.get(normalized, text)


def transcribe_audio_with_faster_whisper(
    audio: sr.AudioData,
    config: Config,
    state: SessionState,
) -> tuple[str, str]:
    model = ensure_stt_model(config, state)
    whisper_language = normalize_stt_language_for_whisper(config.stt_language)
    audio_bytes = audio.get_raw_data(convert_rate=16000, convert_width=2)
    audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
    audio_array /= 32768.0

    segments, info = model.transcribe(
        audio_array,
        language=whisper_language,
        task="transcribe",
        beam_size=config.stt_beam_size,
        best_of=max(config.stt_beam_size, config.stt_best_of),
        vad_filter=config.stt_vad_filter,
        condition_on_previous_text=False,
        without_timestamps=True,
        temperature=0.0,
    )

    text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
    detected_language = getattr(info, "language", None) or whisper_language or ""
    return text.strip(), str(detected_language)


def transcribe_audio_with_google(
    recognizer: sr.Recognizer,
    audio: sr.AudioData,
    config: Config,
) -> tuple[str, str]:
    try:
        text = recognizer.recognize_google(audio, language=config.stt_language).strip()
    except sr.UnknownValueError:
        return "", config.stt_language
    except sr.RequestError as exc:
        raise RuntimeError(
            "Speech recognition could not reach the recognition service. "
            "Check your internet connection."
        ) from exc

    return text, config.stt_language


def recognize_speech(config: Config, state: SessionState) -> SpeechCapture:
    recognizer = ensure_speech_recognizer(config, state)
    if not state.mic_calibrated:
        recalibrate_microphone(config, state)

    with SoundDeviceMicrophone(
        device_index=config.mic_device_index,
        sample_rate=config.mic_sample_rate,
        chunk_size=config.mic_chunk_size,
    ) as source:
        try:
            audio = recognizer.listen(
                source,
                timeout=config.stt_timeout_seconds,
                phrase_time_limit=config.stt_phrase_time_limit_seconds,
            )
        except sr.WaitTimeoutError:
            return SpeechCapture(
                status="timeout",
                language=config.stt_language,
                device_name=source.device_name,
            )

    try:
        if config.stt_provider == "google":
            text, detected_language = transcribe_audio_with_google(
                recognizer, audio, config
            )
        else:
            text, detected_language = transcribe_audio_with_faster_whisper(
                audio, config, state
            )
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Speech recognition failed. {exc}") from exc

    if not text:
        return SpeechCapture(
            status="unknown",
            language=detected_language or config.stt_language,
            device_name=source.device_name,
            error="I heard audio, but I couldn't understand the words clearly.",
        )

    return SpeechCapture(
        status="ok",
        text=text,
        language=detected_language or config.stt_language,
        device_name=source.device_name,
    )


def capture_voice_turn(
    config: Config,
    profile: dict[str, Any],
    state: SessionState,
) -> UserTurn | None:
    print()
    print(
        f"[Listening] Speak to {profile['companion_name']} now with "
        f"{describe_selected_microphone(config)}."
    )

    result = recognize_speech(config, state)
    if result.status == "timeout":
        print("[Listening] I didn't hear anything that sounded like speech.")
        return None

    if result.status == "unknown":
        print("[Listening] I heard you, but I couldn't understand the words.")
        return None

    if result.status != "ok":
        raise RuntimeError(
            result.error or "Speech recognition did not return a usable result."
        )

    print(console_safe_text(f"{profile['user_name']}: {result.text}"))
    return UserTurn(text=result.text, from_voice=True)


def print_welcome(profile: dict[str, Any], config: Config, state: SessionState) -> None:
    print()
    print(f"{profile['companion_name']} is ready.")
    print(
        f"Model: {config.model} | Input: {state.input_mode} | "
        f"Voice output: {'on' if state.voice_enabled else 'off'}"
    )
    print(
        f"XTTS language: {config.tts_language} | "
        f"Speech recognition: {describe_stt_backend(config)} | "
        f"Language: {config.stt_language}"
    )
    print(
        f"XTTS voice: {describe_tts_voice(config)} | XTTS device: {get_xtts_device(config)}"
    )
    print(
        f"XTTS streaming: {'on' if config.xtts_stream_output else 'off'} "
        f"(buffer {config.xtts_stream_buffer_seconds:.1f}s) | "
        f"Reply limit: {config.ollama_num_predict} tokens"
    )
    print(f"Microphone: {describe_selected_microphone(config)}")
    print(
        "Hands-free mode listens after each reply. Text mode keeps the keyboard prompt."
    )
    print(
        "Commands: /help, /mode <voice|text>, /listen, /recalibrate, /mics, "
        "/mic <index|default>, /speakers, /speaker <name>, /voice [on|off], "
        "/profile, /name <new name>, /me <your name>, /remember <fact>, "
        "/reset, /exit"
    )
    print()


def print_help() -> None:
    print()
    print("/help                   Show commands")
    print("/mode                   Show the current input mode")
    print("/mode voice             Turn on hands-free microphone input")
    print("/mode text              Switch back to keyboard input")
    print("/listen                 Capture one spoken turn right now")
    print("/recalibrate            Relearn the room noise before listening")
    print("/mics                   List available microphone devices")
    print("/mic                    Show the selected microphone")
    print("/mic <index>            Choose a microphone from /mics")
    print("/mic default            Use the system default microphone")
    print("/speakers               List available XTTS built-in voices")
    print("/speaker                Show the current XTTS voice")
    print("/speaker <name>         Switch to a different XTTS built-in voice")
    print("/voice                  Toggle spoken replies on or off")
    print("/voice on               Always speak replies")
    print("/voice off              Stop speaking replies")
    print("/profile                Show the current saved profile")
    print("/name <new name>        Rename your companion")
    print("/me <your name>         Set your name")
    print("/remember <fact>        Save something important for future chats")
    print("/reset                  Clear conversation history")
    print("/exit                   Quit the app")
    print()


def parse_voice_setting(argument: str) -> bool | None:
    normalized = argument.strip().lower()
    if normalized in {"on", "true", "1", "yes"}:
        return True
    if normalized in {"off", "false", "0", "no"}:
        return False
    return None


def handle_microphone_command(
    command: str,
    config: Config,
    state: SessionState,
) -> None:
    lowered = command.lower()
    if lowered == "/mic":
        print(f"Microphone is currently {describe_selected_microphone(config)}.")
        return

    selection = command[5:].strip()
    if not selection:
        print("Use /mic <index> or /mic default.")
        return

    if selection.lower() == "default":
        config.mic_device_index = None
        state.speech_recognizer = None
        state.speech_recognizer_signature = None
        state.mic_calibrated = False
        print(f"Microphone is now {describe_selected_microphone(config)}.")
        return

    try:
        device_index = int(selection)
        device_info = resolve_input_device_info(device_index)
    except ValueError:
        print("Use /mic <index> or /mic default.")
        return
    except RuntimeError as exc:
        print(exc)
        return

    config.mic_device_index = device_index
    state.speech_recognizer = None
    state.speech_recognizer_signature = None
    state.mic_calibrated = False
    print(f"Microphone is now #{device_info['index']} ({device_info['name']}).")


def handle_speaker_command(
    command: str,
    config: Config,
    state: SessionState,
) -> None:
    lowered = command.lower()
    if lowered == "/speaker":
        print(console_safe_text(f"XTTS voice is currently {describe_tts_voice(config)}."))
        return

    selection = command[9:].strip()
    if not selection:
        print("Use /speaker <name>.")
        return

    speaker_wav = resolve_optional_path(config.xtts_speaker_wav)
    if speaker_wav is not None:
        print(
            "XTTS is currently using XTTS_SPEAKER_WAV. "
            "Clear that setting to use built-in speakers."
        )
        return

    available_speakers = list_xtts_speakers(config, state)
    selected_speaker = next(
        (speaker for speaker in available_speakers if speaker.lower() == selection.lower()),
        None,
    )
    if selected_speaker is None:
        print("That XTTS speaker was not found. Run /speakers to list valid names.")
        return

    config.xtts_speaker = selected_speaker
    print(console_safe_text(f"XTTS voice is now {selected_speaker}."))


def handle_command(
    incoming_text: str,
    profile: dict[str, Any],
    state: SessionState,
    config: Config,
) -> CommandResult:
    command = incoming_text.strip()
    lowered = command.lower()

    if lowered == "/help":
        print_help()
        return CommandResult(handled=True)

    if lowered == "/mode":
        print(f"Input mode is {state.input_mode}.")
        return CommandResult(handled=True)

    if lowered.startswith("/mode "):
        new_mode = parse_input_mode(command[6:])
        if new_mode is None:
            print("Use /mode voice or /mode text.")
            return CommandResult(handled=True)
        state.input_mode = new_mode
        print(f"Input mode is now {new_mode}.")
        return CommandResult(handled=True)

    if lowered == "/listen":
        voice_turn = capture_voice_turn(config, profile, state)
        return CommandResult(handled=True, injected_turn=voice_turn)

    if lowered == "/recalibrate":
        state.speech_recognizer = None
        state.speech_recognizer_signature = None
        state.mic_calibrated = False
        recalibrate_microphone(config, state)
        return CommandResult(handled=True)

    if lowered == "/mics":
        try:
            print_input_devices()
        except RuntimeError as exc:
            print(exc)
        return CommandResult(handled=True)

    if lowered == "/mic" or lowered.startswith("/mic "):
        handle_microphone_command(command, config, state)
        return CommandResult(handled=True)

    if lowered == "/speakers":
        try:
            print_xtts_speakers(config, state)
        except RuntimeError as exc:
            print(exc)
        return CommandResult(handled=True)

    if lowered == "/speaker" or lowered.startswith("/speaker "):
        try:
            handle_speaker_command(command, config, state)
        except RuntimeError as exc:
            print(exc)
        return CommandResult(handled=True)

    if lowered == "/voice":
        state.voice_enabled = not state.voice_enabled
        print(f"Voice output is now {'on' if state.voice_enabled else 'off'}.")
        return CommandResult(handled=True)

    if lowered.startswith("/voice "):
        setting = parse_voice_setting(command[7:])
        if setting is None:
            print("Use /voice, /voice on, or /voice off.")
            return CommandResult(handled=True)
        state.voice_enabled = setting
        print(f"Voice output is now {'on' if state.voice_enabled else 'off'}.")
        return CommandResult(handled=True)

    if lowered == "/profile":
        print()
        print(json.dumps(profile, indent=2, ensure_ascii=False))
        print()
        return CommandResult(handled=True)

    if lowered == "/reset":
        reset_history()
        print("Conversation history cleared.")
        return CommandResult(handled=True)

    if lowered == "/exit":
        return CommandResult(handled=True, should_exit=True)

    if lowered.startswith("/name "):
        new_name = command[6:].strip()
        if new_name:
            profile["companion_name"] = new_name
            save_profile(profile)
            print(f"Your companion is now named {new_name}.")
        return CommandResult(handled=True)

    if lowered.startswith("/me "):
        new_name = command[4:].strip()
        if new_name:
            profile["user_name"] = new_name
            save_profile(profile)
            print(f"Saved your name as {new_name}.")
        return CommandResult(handled=True)

    if lowered.startswith("/remember "):
        note = command[10:].strip()
        if note:
            notes = profile.setdefault("memory_notes", [])
            if note not in notes:
                notes.append(note)
                save_profile(profile)
                print("Saved that memory note.")
            else:
                print("That memory note is already saved.")
        return CommandResult(handled=True)

    return CommandResult(handled=False)


def get_next_user_turn(
    profile: dict[str, Any],
    state: SessionState,
    config: Config,
) -> UserTurn | None:
    if state.input_mode == "voice":
        try:
            return capture_voice_turn(config, profile, state)
        except RuntimeError as exc:
            print()
            print(f"[Mic] {exc}")
            print("[Mic] Switching back to text mode so you can keep chatting.")
            print()
            state.input_mode = "text"
            return None

    try:
        prompt_name = profile["user_name"]
        user_text = input(f"{prompt_name}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nSee you soon.")
        raise SystemExit from None

    if not user_text:
        return None

    return UserTurn(text=user_text, from_voice=False)


def resolve_user_turn(
    turn: UserTurn,
    profile: dict[str, Any],
    state: SessionState,
    config: Config,
) -> tuple[str, bool]:
    current_turn = turn

    while True:
        incoming_text = (
            map_spoken_command(current_turn.text)
            if current_turn.from_voice
            else current_turn.text
        )
        result = handle_command(incoming_text, profile, state, config)

        if result.should_exit:
            return "", True

        if result.injected_turn is not None:
            current_turn = result.injected_turn
            continue

        if result.handled:
            return "", False

        return incoming_text, False


def main() -> None:
    ensure_runtime_dirs()
    config = Config.from_env()
    profile = load_profile()
    state = SessionState(
        voice_enabled=config.voice_enabled,
        input_mode=config.input_mode,
    )

    print_welcome(profile, config, state)

    while True:
        try:
            turn = get_next_user_turn(profile, state, config)
        except SystemExit:
            break

        if turn is None:
            continue

        try:
            user_text, should_exit = resolve_user_turn(turn, profile, state, config)
        except RuntimeError as exc:
            print()
            print(f"[Mic] {exc}")
            print("[Mic] Staying in text mode for now.")
            print()
            state.input_mode = "text"
            continue

        if should_exit:
            print("See you soon.")
            break

        if not user_text:
            continue

        try:
            reply = request_reply(user_text, profile, config)
        except RuntimeError as exc:
            print()
            print(f"[Companion error] {exc}")
            print()
            continue

        append_history("user", user_text)
        append_history("assistant", reply)

        print()
        print(console_safe_text(f"{profile['companion_name']}: {reply}"))
        print()

        if state.voice_enabled:
            audio_path = AUDIO_DIR / "latest_reply.wav"
            try:
                audio_path = speak_text(reply, config, state)
                if not config.xtts_stream_output:
                    play_audio_file(audio_path)
            except Exception as exc:
                print(
                    "[Voice] Voice generation or playback failed. "
                    f"The latest audio file is at {audio_path}: {exc}"
                )


if __name__ == "__main__":
    main()
