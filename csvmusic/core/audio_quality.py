"""File-level quality indicators, not claims about the original recording."""
from functools import lru_cache
from pathlib import Path

import mutagen
from csvmusic.core.source_quality import read_source


def classify_audio_quality(codec: str, bitrate: float | None) -> dict:
	codec = codec.upper()
	threshold = {"MP3": 128, "AAC": 96, "OPUS": 96, "VORBIS": 112}.get(codec)
	kbps = round(bitrate / 1000) if bitrate and bitrate > 0 else None
	low = bool(kbps is not None and threshold is not None and kbps < threshold)
	label = f"YT {codec} · ~{kbps} kbps" if kbps else "Source quality unknown"
	if low:
		label = f"⚠ Low source · ~{kbps} kbps"
	return {
		"label": label, "low": low, "codec": codec, "kbps": kbps,
		"tooltip": (
			f"Downloaded YouTube source: {codec}; reported audio bitrate: approximately {kbps} kbps. " if kbps else "YouTube source bitrate was not recorded or not provided. "
		) + (f"Flagged below {threshold} kbps for {codec}. " if low else "") +
		"This describes the selected source stream before conversion, not the saved file's encoding. Bitrate is an estimate, not proof of recording fidelity. Old downloads need a new download to record their actual source.",
	}


@lru_cache(maxsize=4096)
def _inspect(path: str, size: int, modified_ns: int) -> dict:
	try:
		audio = mutagen.File(path)
		if audio is None:
			return classify_audio_quality("Unknown", None)
		source = read_source(audio)
		codec = str(source.get("codec") or "Unknown").upper()
		if codec.startswith("MP4A"):
			codec = "AAC"
		kbps = source.get("kbps")
		return classify_audio_quality(codec, float(kbps) * 1000 if kbps else None)
	except Exception:
		return classify_audio_quality("Unknown", None)


def audio_quality(path: str | Path) -> dict:
	try:
		file = Path(path)
		stat = file.stat()
		return _inspect(str(file), stat.st_size, stat.st_mtime_ns)
	except OSError:
		return classify_audio_quality("Unknown", None)
