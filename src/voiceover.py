"""TTS abstraction for Indian male English voiceover.

Providers:
  coqui  — Coqui XTTS-v2 (open-source, CPU, multilingual). Default.
  edge   — edge-tts en-IN-PrabhatNeural (fast, cloud). Fallback.

Each accepts a list of text sections, synthesises per-section WAV chunks,
concatenates with ffmpeg, and returns (wav_path, duration_seconds).

Dry-run mode (env TTS_DRY_RUN=1 or config dry_run=True) generates a short
sine-wave placeholder so the rest of the pipeline can be tested end-to-end
without a real TTS model or network call.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from src import utils

logger = logging.getLogger("voiceover")


def get_audio_duration(path: str | Path) -> float:
    """Return duration in seconds via ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def _concat_wavs(chunk_paths: list[Path], out_wav: Path) -> None:
    """Concatenate WAV chunks with ffmpeg concat demuxer."""
    list_path = out_wav.with_suffix(".concat_list.txt")
    with open(list_path, "w") as f:
        for p in chunk_paths:
            f.write(f"file '{p}'\n")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
         "-i", str(list_path), "-c", "copy", str(out_wav)],
        check=True, capture_output=True,
    )
    list_path.unlink()


def _synthesize_dry_run(sections: list[str], out_wav: Path,
                        audio_cfg: dict) -> None:
    """Generate a short sine-wave placeholder for each section."""
    sr = int(audio_cfg.get("sample_rate", 24000))
    duration_per_section = 3.0  # 3 seconds per section -> enough to verify pipeline
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    chunks: list[Path] = []
    for i in range(len(sections)):
        chunk = out_wav.parent / f"dry_chunk_{i:03d}.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i",
             f"sine=frequency=220:duration={duration_per_section}",
             "-ar", str(sr), "-ac", "1", str(chunk)],
            check=True, capture_output=True,
        )
        chunks.append(chunk)
    _concat_wavs(chunks, out_wav)
    for p in chunks:
        p.unlink()


def _synthesize_coqui(sections: list[str], out_wav: Path,
                      coqui_cfg: dict, audio_cfg: dict) -> None:
    from TTS.api import TTS

    tts = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2", gpu=False)
    speaker = coqui_cfg.get("speaker_wav") or None
    language = coqui_cfg.get("language", "en")
    sr = int(audio_cfg.get("sample_rate", 24000))
    chunk_chars = int(coqui_cfg.get("chunk_chars", 500))

    out_wav.parent.mkdir(parents=True, exist_ok=True)
    chunks: list[Path] = []

    for i, text in enumerate(sections):
        # Chunk long texts within a section for CPU stability
        sub_chunks = [text[j:j + chunk_chars] for j in range(0, len(text), chunk_chars)]
        for ci, sub in enumerate(sub_chunks):
            chunk = out_wav.parent / f"coqui_{i:03d}_{ci:03d}.wav"
            tts.tts_to_file(text=sub, speaker_wav=speaker,
                            language=language, file_path=str(chunk))
            chunks.append(chunk)

    _concat_wavs(chunks, out_wav)
    for p in chunks:
        p.unlink()


async def _synthesize_edge(sections: list[str], out_wav: Path,
                           edge_cfg: dict, audio_cfg: dict) -> None:
    import edge_tts

    voice = edge_cfg.get("voice", "en-IN-PrabhatNeural")
    rate = edge_cfg.get("rate", "+0%")

    out_wav.parent.mkdir(parents=True, exist_ok=True)
    chunks: list[Path] = []

    for i, text in enumerate(sections):
        chunk = out_wav.parent / f"edge_{i:03d}.mp3"
        communicate = edge_tts.Communicate(text, voice, rate=rate)
        await communicate.save(str(chunk))
        chunks.append(chunk)

    _concat_wavs(chunks, out_wav)
    for p in chunks:
        p.unlink()


def synthesize(sections: list[str], out_wav: str | Path,
               config: dict[str, Any] | None = None) -> tuple[Path, float]:
    """Synthesise voiceover audio from a list of section texts.

    Returns (wav_path, duration_seconds).
    """
    if config is None:
        config = utils.load_config("config/tts.yaml")
    if not isinstance(config, dict):
        config = {}

    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    audio_cfg = config.get("audio", {})

    # Dry-run mode: placeholder audio, no real TTS.
    if os.environ.get("TTS_DRY_RUN") or config.get("dry_run"):
        logger.info("TTS dry-run: generating placeholder audio")
        _synthesize_dry_run(sections, out_wav, audio_cfg)
        dur = get_audio_duration(out_wav)
        logger.info("Dry-run audio: %s (%.1f s)", out_wav, dur)
        return out_wav, dur

    provider = (os.environ.get("TTS_PROVIDER") or config.get("provider", "coqui"))
    # Allow runtime voice override (e.g. TTS_VOICE=en-IN-PrabhatNeural)
    voice_override = os.environ.get("TTS_VOICE")
    logger.info("TTS provider=%s sections=%d", provider, len(sections))

    if provider == "coqui":
        _synthesize_coqui(sections, out_wav, config.get("coqui", {}), audio_cfg)
    elif provider == "edge":
        edge_cfg = dict(config.get("edge", {}))
        if voice_override:
            edge_cfg["voice"] = voice_override
        asyncio.run(_synthesize_edge(sections, out_wav, edge_cfg, audio_cfg))
    else:
        raise ValueError(f"Unknown TTS provider: {provider}")

    duration = get_audio_duration(out_wav)
    logger.info("TTS complete: %s (%.1f s)", out_wav, duration)
    return out_wav, duration