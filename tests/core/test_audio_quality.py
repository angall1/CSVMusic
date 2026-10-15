from types import SimpleNamespace

import pytest

from csvmusic.core.audio_quality import audio_quality, classify_audio_quality, _inspect


@pytest.mark.parametrize("codec,bitrate,low", [
	("MP3", 96000, True), ("MP3", 128000, False),
	("AAC", 64000, True), ("AAC", 128000, False),
	("OPUS", 64000, True), ("OPUS", 128000, False),
	("MP3", None, False), ("FLAC", 800000, False),
])
def test_quality_thresholds(codec, bitrate, low):
	quality = classify_audio_quality(codec, bitrate)
	assert quality["low"] is low
	assert "source" in quality["tooltip"]


def test_missing_and_unreadable_files_are_unknown(tmp_path):
	path = tmp_path / "track.mp3"
	assert audio_quality(path)["label"] == "Source quality unknown"
	path.write_bytes(b"bad audio")
	assert audio_quality(path)["label"] == "Source quality unknown"
	assert not audio_quality(path)["low"]


def test_replaced_file_refreshes_cached_quality(monkeypatch, tmp_path):
	path = tmp_path / "track.mp3"
	path.write_bytes(b"first")
	audio = type("MP3", (), {})()
	audio.info = SimpleNamespace(bitrate=96000)
	source = {"codec": "opus", "kbps": 64}
	monkeypatch.setattr("csvmusic.core.audio_quality.read_source", lambda _: source)
	monkeypatch.setattr("csvmusic.core.audio_quality.mutagen.File", lambda _: audio)
	assert audio_quality(path)["low"]
	audio.info.bitrate = 192000
	source["kbps"] = 128
	path.write_bytes(b"replacement is longer")
	assert not audio_quality(path)["low"]
	_inspect.cache_clear()
