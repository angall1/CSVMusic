# tabs only
import pathlib

import pandas as pd

from csvmusic import download_csv
from csvmusic.core import downloader
from csvmusic.core.csv_import import load_csv, tracks_from_csv, write_skipped_csv


def _write_csv(path: pathlib.Path) -> pathlib.Path:
	pd.DataFrame([
		{
			"Playlist name": "Road Trip",
			"Track name": "Dirty Work",
			"Artist name": "Steely Dan",
			"Album": "Can't Buy A Thrill",
			"ISRC": "USMC17200001",
			"Release date": "1972-11-01",
			"Cover URL": "https://example.test/cover.jpg",
			"Duration (ms)": 187400,
		},
		{
			"Playlist name": "Road Trip",
			"Track name": "Obscure B-Side",
			"Artist name": "Nobody Knows",
			"Album": "Lost Tapes",
			"Duration (ms)": 200000,
		},
	]).to_csv(path, index=False)
	return path


def test_track_cover_prefers_csv_cover_url(monkeypatch):
	seen = {}
	def fake_cover(url):
		seen["url"] = url
		return b"source-art"
	monkeypatch.setattr(downloader, "cover_art_url_bytes", fake_cover)
	monkeypatch.setattr(downloader, "yt_thumbnail_bytes", lambda _vid: b"youtube-art")

	cover = downloader.track_cover_bytes({"cover_url": "https://example.test/cover.jpg"}, "vid")

	assert cover == b"source-art"
	assert seen["url"] == "https://example.test/cover.jpg"


def test_track_cover_falls_back_to_youtube_thumbnail(monkeypatch):
	monkeypatch.setattr(downloader, "cover_art_url_bytes", lambda _url: None)
	monkeypatch.setattr(downloader, "yt_thumbnail_bytes", lambda vid: f"thumb:{vid}".encode())

	assert downloader.track_cover_bytes({"cover_url": None}, "vid-1") == b"thumb:vid-1"
	assert downloader.track_cover_bytes({}, "vid-2") == b"thumb:vid-2"


def test_skipped_csv_round_trips_through_load_csv(tmp_path):
	tracks = tracks_from_csv(load_csv(_write_csv(tmp_path / "in.csv")))

	path = write_skipped_csv(tmp_path / "skipped.csv", [{"track": tracks[0], "reason": "no confident match"}])
	again = tracks_from_csv(load_csv(path))

	assert len(again) == 1
	for key in ("title", "artists", "album", "playlist", "isrc", "year", "cover_url", "duration_ms"):
		assert again[0][key] == tracks[0][key]
	assert pd.read_csv(path)["Reason"].tolist() == ["no confident match"]


def test_cli_tags_with_csv_metadata_and_writes_skipped_csv(tmp_path, monkeypatch):
	csv_path = _write_csv(tmp_path / "in.csv")
	out = tmp_path / "out"
	tagged = []

	def fake_match(tracks):
		return [
			{"track": tracks[0], "skipped": False, "match": {"videoId": "vid-1", "title": "Dirty Work"}, "confidence": 0.95},
			{"track": tracks[1], "skipped": True, "match": None, "confidence": 0.2},
		]

	def fake_download_mp3(video_id, dest_dir, base, cbr_320=False):
		fp = pathlib.Path(dest_dir) / f"{base}.mp3"
		fp.write_bytes(b"")
		return fp

	monkeypatch.setattr(download_csv, "batch_match", fake_match)
	monkeypatch.setattr(download_csv, "download_mp3", fake_download_mp3)
	monkeypatch.setattr(download_csv, "track_cover_bytes", lambda track, vid: f"cover:{track['cover_url']}".encode())
	monkeypatch.setattr(download_csv, "tag_file", lambda fp, meta, cover: tagged.append((fp, meta, cover)))
	monkeypatch.setattr(download_csv, "log", lambda _msg: None)

	rc = download_csv.main(["prog", "--csv", str(csv_path), "--out", str(out), "--format", "mp3"])

	assert rc == 0
	assert len(tagged) == 1
	fp, meta, cover = tagged[0]
	assert fp.parent == out / "Road Trip"
	assert meta["album"] == "Can't Buy A Thrill"
	assert meta["isrc"] == "USMC17200001"
	assert meta["year"] == 1972
	assert cover == b"cover:https://example.test/cover.jpg"
	assert (out / "Road Trip" / "Road Trip.m3u8").exists()

	skipped = tracks_from_csv(load_csv(out / "Road Trip" / "skipped.csv"))
	assert [t["title"] for t in skipped] == ["Obscure B-Side"]
