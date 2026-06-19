"""LLM-callable tools for voice I/O (STT + TTS)."""
from __future__ import annotations

from .registry import tool

# Module-level singleton — created lazily so import doesn't trigger model load.
_voice: "VoiceInterface | None" = None  # noqa: F821


def _get_voice() -> "VoiceInterface":  # noqa: F821
    global _voice
    if _voice is None:
        from llmos.voice import VoiceInterface
        _voice = VoiceInterface()
    return _voice


@tool(
    name="speak",
    description=(
        "Have the OS speak text aloud using the system TTS engine "
        "(pyttsx3 or espeak).  Returns immediately; speech plays in the background."
    ),
    properties={
        "text": {
            "type": "string",
            "description": "The text to speak aloud.",
        },
        "voice": {
            "type": "string",
            "description": (
                "Optional voice identifier.  For pyttsx3 this is the voice id string; "
                "for espeak it is a voice name such as 'en', 'en-us', 'de', etc."
            ),
        },
        "rate": {
            "type": "integer",
            "description": "Speech rate in words-per-minute (default: 150).",
        },
    },
    required=["text"],
)
def speak(
    text: str,
    voice: str | None = None,
    rate: int = 150,
) -> str:
    vi = _get_voice()
    av = vi.availability()
    if not av["pyttsx3"] and not av["espeak"]:
        return (
            "No TTS engine available.  Install one of:\n"
            "  pip install pyttsx3\n"
            "  apt-get install espeak-ng"
        )
    vi.speak(text, voice=voice, rate=rate)
    return f"Speaking: {text!r}"


@tool(
    name="listen_microphone",
    description=(
        "Record audio from the microphone for the given duration and return "
        "the transcription produced by Whisper (STT)."
    ),
    properties={
        "duration": {
            "type": "number",
            "description": "Recording duration in seconds (default: 5).",
        },
        "device": {
            "type": "integer",
            "description": (
                "sounddevice device index to record from.  "
                "Omit to use the system default input device."
            ),
        },
    },
    required=[],
)
def listen_microphone(
    duration: float = 5.0,
    device: int | None = None,
) -> str:
    vi = _get_voice()
    av = vi.availability()
    missing = [k for k in ("whisper", "sounddevice", "numpy") if not av[k]]
    if missing:
        pkg_map = {
            "whisper": "openai-whisper",
            "sounddevice": "sounddevice",
            "numpy": "numpy",
        }
        pkgs = " ".join(pkg_map[m] for m in missing)
        return (
            f"Missing packages: {', '.join(missing)}\n"
            f"Install with: pip install {pkgs}"
        )
    return vi.listen(duration=duration, device=device)


@tool(
    name="voice_status",
    description=(
        "Check which voice-related libraries are available on this system "
        "and return install instructions for anything that is missing."
    ),
    properties={},
    required=[],
)
def voice_status() -> str:
    from llmos.voice import VoiceInterface
    av = VoiceInterface.availability()

    lines: list[str] = ["Voice library status:", ""]
    install_hints: list[str] = []

    status_map = {
        "whisper":     ("openai-whisper",  "STT (speech-to-text)"),
        "sounddevice": ("sounddevice",     "microphone recording"),
        "numpy":       ("numpy",           "audio array processing"),
        "pyttsx3":     ("pyttsx3",         "TTS (text-to-speech, Python engine)"),
        "espeak":      (None,              "TTS (espeak/espeak-ng system binary)"),
    }

    for key, (pkg, role) in status_map.items():
        available = av[key]
        mark = "OK" if available else "MISSING"
        lines.append(f"  {mark:8s} {key:<14s} — {role}")
        if not available and pkg:
            install_hints.append(f"  pip install {pkg}")

    if not av["espeak"]:
        install_hints.append("  apt-get install espeak-ng   # (or: apt-get install espeak)")

    if install_hints:
        lines.append("")
        lines.append("To install missing packages:")
        lines.extend(install_hints)

    stt_ok = av["whisper"] and av["sounddevice"] and av["numpy"]
    tts_ok = av["pyttsx3"] or av["espeak"]
    lines.append("")
    lines.append(f"STT ready: {'yes' if stt_ok else 'no'}")
    lines.append(f"TTS ready: {'yes' if tts_ok else 'no'}")

    return "\n".join(lines)
