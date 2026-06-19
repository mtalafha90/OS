"""Voice interface for LLM-OS.

Provides Speech-to-Text via openai-whisper and Text-to-Speech via pyttsx3 / espeak.
All capabilities degrade gracefully when optional dependencies are missing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

# ---------------------------------------------------------------------------
# Availability probes (evaluated once at import time)
# ---------------------------------------------------------------------------


def _probe(module: str) -> bool:
    try:
        __import__(module)
        return True
    except ImportError:
        return False


_HAS_WHISPER = _probe("whisper")
_HAS_SOUNDDEVICE = _probe("sounddevice")
_HAS_NUMPY = _probe("numpy")
_HAS_PYTTSX3 = _probe("pyttsx3")
_HAS_ESPEAK = shutil.which("espeak") is not None or shutil.which("espeak-ng") is not None


# ---------------------------------------------------------------------------
# VoiceInterface
# ---------------------------------------------------------------------------


class VoiceInterface:
    """Unified voice interface supporting STT (Whisper) and TTS (pyttsx3/espeak).

    Instantiate once and reuse; the underlying Whisper model is loaded lazily.
    """

    # -----------------------------------------------------------------------
    # Construction / state
    # -----------------------------------------------------------------------

    def __init__(self, model_size: str = "base") -> None:
        """
        Args:
            model_size: Whisper model to load on first use
                        ("tiny", "base", "small", "medium", "large").
        """
        self._model_size = model_size
        self._whisper_model = None  # lazy
        self._pyttsx3_engine = None  # lazy
        self._tts_thread: threading.Thread | None = None
        self._tts_stop = threading.Event()
        self._wake_stop = threading.Event()

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _load_whisper(self):
        """Load the Whisper model (once)."""
        if self._whisper_model is None:
            if not _HAS_WHISPER:
                raise RuntimeError(
                    "openai-whisper is not installed.\nInstall with: pip install openai-whisper"
                )
            import whisper  # type: ignore

            self._whisper_model = whisper.load_model(self._model_size)
        return self._whisper_model

    def _get_pyttsx3(self):
        """Return a (cached) pyttsx3 engine or None."""
        if not _HAS_PYTTSX3:
            return None
        if self._pyttsx3_engine is None:
            try:
                import pyttsx3  # type: ignore

                self._pyttsx3_engine = pyttsx3.init()
            except Exception:
                return None
        return self._pyttsx3_engine

    @staticmethod
    def _espeak_binary() -> str | None:
        return shutil.which("espeak-ng") or shutil.which("espeak")

    # -----------------------------------------------------------------------
    # STT — transcription
    # -----------------------------------------------------------------------

    def transcribe(self, audio_file: str) -> str:
        """Transcribe an audio file using Whisper.

        Args:
            audio_file: Path to an audio file (wav, mp3, ogg, flac, m4a, …).

        Returns:
            Transcribed text string.
        """
        path = Path(audio_file).expanduser()
        if not path.exists():
            return f"Error: audio file not found: {audio_file}"

        try:
            model = self._load_whisper()
            result = model.transcribe(str(path))
            return result["text"].strip()
        except RuntimeError as exc:
            return str(exc)
        except Exception as exc:
            return f"Transcription error: {exc}"

    def listen(self, duration: float = 5.0, device: int | None = None) -> str:
        """Record audio from the microphone and transcribe it.

        Args:
            duration: Recording length in seconds.
            device:   sounddevice device index (None = system default).

        Returns:
            Transcribed text, or an error/install message.
        """
        if not _HAS_SOUNDDEVICE:
            return "sounddevice is not installed.\nInstall with: pip install sounddevice"
        if not _HAS_NUMPY:
            return "numpy is not installed.\nInstall with: pip install numpy"
        if not _HAS_WHISPER:
            return "openai-whisper is not installed.\nInstall with: pip install openai-whisper"

        try:
            import numpy as np  # type: ignore
            import sounddevice as sd  # type: ignore

            sample_rate = 16_000  # Whisper expects 16 kHz mono
            frames = int(duration * sample_rate)
            recording = sd.rec(
                frames,
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
                device=device,
            )
            sd.wait()
            audio = recording[:, 0]  # mono

            # Write to a temporary WAV file for Whisper
            import wave

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name

            try:
                # Write 16-bit PCM WAV manually (avoids scipy dependency)
                pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
                with wave.open(tmp_path, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    wf.writeframes(pcm.tobytes())

                return self.transcribe(tmp_path)
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        except Exception as exc:
            return f"Listen error: {exc}"

    def start_wake_word(
        self,
        callback: Callable[[str], None],
        wake_word: str = "hey llmos",
    ) -> None:
        """Start continuous microphone listening for a wake word.

        When the wake word is detected in transcribed audio the *callback* is
        invoked with the full transcription string.  Runs in a background
        thread.  Call :meth:`stop_wake_word` to terminate.

        Args:
            callback:  Called with the transcription whenever the wake word
                       is detected.
            wake_word: Phrase to listen for (case-insensitive).
        """
        if not _HAS_SOUNDDEVICE or not _HAS_NUMPY or not _HAS_WHISPER:
            missing = []
            if not _HAS_SOUNDDEVICE:
                missing.append("sounddevice")
            if not _HAS_NUMPY:
                missing.append("numpy")
            if not _HAS_WHISPER:
                missing.append("openai-whisper")
            raise RuntimeError(
                f"Missing packages for wake-word detection: {', '.join(missing)}\n"
                f"Install with: pip install {' '.join(missing)}"
            )

        self._wake_stop.clear()

        def _worker() -> None:
            import wave

            import numpy as np  # type: ignore
            import sounddevice as sd  # type: ignore

            sample_rate = 16_000
            chunk_duration = 2.0  # seconds per chunk
            frames_per_chunk = int(chunk_duration * sample_rate)
            lw = wake_word.lower()

            while not self._wake_stop.is_set():
                try:
                    recording = sd.rec(
                        frames_per_chunk,
                        samplerate=sample_rate,
                        channels=1,
                        dtype="float32",
                    )
                    sd.wait()
                    audio = recording[:, 0]

                    # Quick energy gate — skip silence
                    if np.abs(audio).mean() < 0.005:
                        continue

                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                        tmp_path = tmp.name
                    try:
                        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
                        with wave.open(tmp_path, "wb") as wf:
                            wf.setnchannels(1)
                            wf.setsampwidth(2)
                            wf.setframerate(sample_rate)
                            wf.writeframes(pcm.tobytes())

                        text = self.transcribe(tmp_path)
                    finally:
                        try:
                            os.unlink(tmp_path)
                        except OSError:
                            pass

                    if lw in text.lower():
                        try:
                            callback(text)
                        except Exception:
                            pass

                except Exception:
                    time.sleep(0.5)

        t = threading.Thread(target=_worker, daemon=True, name="llmos-wake-word")
        t.start()

    def stop_wake_word(self) -> None:
        """Stop the background wake-word listener."""
        self._wake_stop.set()

    # -----------------------------------------------------------------------
    # TTS — speech synthesis
    # -----------------------------------------------------------------------

    def speak(
        self,
        text: str,
        voice: str | None = None,
        rate: int = 150,
    ) -> None:
        """Convert text to speech.

        Tries pyttsx3 first, then espeak/espeak-ng via subprocess.

        Args:
            text:  Text to speak.
            voice: Voice identifier (pyttsx3 voice id, or espeak voice name).
            rate:  Words-per-minute rate (pyttsx3) / speed value (espeak -s).
        """
        self._tts_stop.clear()

        # ── pyttsx3 ──────────────────────────────────────────────────────
        engine = self._get_pyttsx3()
        if engine is not None:
            try:
                if voice:
                    engine.setProperty("voice", voice)
                engine.setProperty("rate", rate)

                def _run_pyttsx3() -> None:
                    try:
                        engine.say(text)
                        engine.runAndWait()
                    except Exception:
                        pass

                self._tts_thread = threading.Thread(
                    target=_run_pyttsx3, daemon=True, name="llmos-tts"
                )
                self._tts_thread.start()
                return
            except Exception:
                pass

        # ── espeak fallback ───────────────────────────────────────────────
        binary = self._espeak_binary()
        if binary:
            cmd = [binary, "-s", str(rate), "--", text]
            if voice:
                cmd = [binary, "-v", voice, "-s", str(rate), "--", text]

            def _run_espeak() -> None:
                try:
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    while proc.poll() is None:
                        if self._tts_stop.is_set():
                            proc.terminate()
                            return
                        time.sleep(0.05)
                except Exception:
                    pass

            self._tts_thread = threading.Thread(target=_run_espeak, daemon=True, name="llmos-tts")
            self._tts_thread.start()
            return

        # ── nothing available ─────────────────────────────────────────────
        print(
            "[VoiceInterface] No TTS engine available.\n"
            "Install one of:\n"
            "  pip install pyttsx3\n"
            "  apt-get install espeak-ng"
        )

    def stop_speaking(self) -> None:
        """Interrupt any ongoing TTS playback."""
        self._tts_stop.set()
        engine = self._get_pyttsx3()
        if engine is not None:
            try:
                engine.stop()
            except Exception:
                pass
        if self._tts_thread and self._tts_thread.is_alive():
            self._tts_thread.join(timeout=1.0)

    # -----------------------------------------------------------------------
    # Availability report
    # -----------------------------------------------------------------------

    @staticmethod
    def availability() -> dict:
        """Return a dict describing which libraries are available."""
        return {
            "whisper": _HAS_WHISPER,
            "sounddevice": _HAS_SOUNDDEVICE,
            "numpy": _HAS_NUMPY,
            "pyttsx3": _HAS_PYTTSX3,
            "espeak": _HAS_ESPEAK,
        }
