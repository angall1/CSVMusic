import json
from types import SimpleNamespace

from mutagen.id3 import ID3
from csvmusic.core.source_quality import capture_source, store_source, read_source, KEY
from csvmusic.core.audio_quality import audio_quality, _inspect


def test_capture_never_uses_video_bitrate(tmp_path):
	path = tmp_path / "encoded.mp3"
	path.write_bytes(b"")
	capture_source(json.dumps({"id": "video", "acodec": "mp4a.40.2", "vcodec": "avc1", "tbr": 1400}))
	store_source(path)
	audio = type("MP3", (), {})()
	audio.tags = ID3(path)
	assert read_source(audio)["kbps"] is None


def test_source_bitrate_not_output_bitrate(monkeypatch, tmp_path):
	path = tmp_path / "encoded.mp3"
	path.write_bytes(b"")
	capture_source(json.dumps({"id": "video", "acodec": "opus", "vcodec": "none", "abr": 64, "format_id": "249"}))
	store_source(path)
	audio = type("MP3", (), {})()
	audio.tags = ID3(path)
	audio.info = SimpleNamespace(bitrate=320000)
	monkeypatch.setattr("csvmusic.core.audio_quality.mutagen.File", lambda _: audio)
	quality = audio_quality(path)
	assert quality["kbps"] == 64
	assert quality["low"]
	assert quality["codec"] == "OPUS"
	_inspect.cache_clear()


def test_missing_metadata_never_reuses_previous_source(tmp_path):
	capture_source(json.dumps({"id": "video", "acodec": "opus", "abr": 128}))
	capture_source("normal log output without metadata")
	path = tmp_path / "next.mp3"
	store_source(path)
	assert not path.exists()


def test_old_mp3_does_not_claim_source_quality(monkeypatch, tmp_path):
	path = tmp_path / "old.mp3"
	path.write_bytes(b"test")
	audio = type("MP3", (), {})()
	audio.tags = {}
	audio.info = SimpleNamespace(bitrate=192000)
	monkeypatch.setattr("csvmusic.core.audio_quality.mutagen.File", lambda _: audio)
	assert audio_quality(path)["label"] == "Source quality unknown"
	_inspect.cache_clear()
