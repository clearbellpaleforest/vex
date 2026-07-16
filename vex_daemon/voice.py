"""
Voice ingestion — audio bytes in, transcript onto the mesh.

The watch records Opus (16 kHz mono — the only codec Zepp OS offers) and the
app-side uploads the raw bytes to POST /voice. faster-whisper decodes Opus
directly (PyAV under the hood), so there is no ffmpeg subprocess and no
temp-file conversion step; the upload is written to one temp file, transcribed,
and deleted.

STT is lazy-loaded: the first request pays the model load (~1 s for tiny.en
int8 on CPU), subsequent requests reuse it. If faster-whisper is not installed
the endpoint reports 503 rather than crashing the daemon at import time.

Chamberlain: one module, one job — bytes to text. Routing the transcript onto
the mesh stays in daemon.py next to the rest of /ask.
"""

import os
import tempfile

MAX_AUDIO_BYTES = 5 * 1024 * 1024  # 15 s of Opus is ~30 KB; 5 MB is generous
MODEL_NAME = os.environ.get("VEX_STT_MODEL", "tiny.en")

_MODEL = None


class STTUnavailable(Exception):
    """faster-whisper is not installed or the model cannot load."""


class AudioDecodeError(Exception):
    """The uploaded bytes are not decodable audio."""


def _get_model():
    global _MODEL
    if _MODEL is None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise STTUnavailable("faster-whisper not installed") from e
        try:
            _MODEL = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
        except Exception as e:
            raise STTUnavailable(f"STT model load failed: {e}") from e
    return _MODEL


def transcribe(audio_bytes: bytes) -> dict:
    """Transcribe audio bytes (Opus/WAV/anything PyAV decodes).

    Returns {"text": str, "duration": float, "language": str}.
    Raises STTUnavailable or AudioDecodeError — callers map these to HTTP codes.
    """
    if not audio_bytes:
        raise AudioDecodeError("empty audio")
    model = _get_model()
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".audio", delete=False) as f:
            tmp = f.name
            f.write(audio_bytes)
        try:
            segments, info = model.transcribe(tmp, beam_size=5)
            text = " ".join(seg.text.strip() for seg in segments).strip()
        except Exception as e:
            raise AudioDecodeError(f"audio decode/transcribe failed: {e}") from e
        return {
            "text": text,
            "duration": round(getattr(info, "duration", 0.0), 2),
            "language": getattr(info, "language", ""),
        }
    finally:
        if tmp:
            try:
                os.unlink(tmp)  # never persist voice recordings
            except OSError:
                pass
