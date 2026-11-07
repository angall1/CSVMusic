# tabs only
import pathlib

import pandas as pd
import pytest

from csvmusic import download_csv as cli
from csvmusic.core import csv_import


@pytest.fixture
def batch(tmp_path, monkeypatch):
	source = tmp_path / "input.csv"
	pd.DataFrame([{"Playlist name": "Mix", "Track name": title, "Artist name": "Artist", "Album": "Album", "Track number": i + 16, "Disc number": 2} for i, title in enumerate(["First", "Middle", "Last"])]).to_csv(source, index=False)
	state = {"fail": {"Middle"}, "tagged": []}
	def match(tracks):
		return [{"track": t, "skipped": t["title"] in state["fail"], "match": {"videoId": "test", "title": t["title"]}, "confidence": 1} for t in tracks]
	def download(vid, dest, base, **kwargs):
		p = dest / (base + ".mp3")
		p.write_bytes(b"audio")
		return p
	monkeypatch.setattr(cli, "batch_match", match)
	monkeypatch.setattr(cli, "download_mp3", download)
	monkeypatch.setattr(cli, "tag_file", lambda fp, t, cover: state["tagged"].append(t.copy()))
	monkeypatch.setattr(cli, "track_cover_bytes", lambda *a: None)
	monkeypatch.setattr(cli, "log", lambda *a: None)
	monkeypatch.setattr(cli.time, "sleep", lambda *a: None)
	def run(path=source, *extra):
		return cli.main(["prog", "--csv", str(path), "--out", str(tmp_path / "out"), "--format", "mp3", *extra])
	return source, tmp_path / "out" / "Mix", state, run


def test_retry_restores_order_and_metadata_and_owns_only_its_files(batch):
	source, dest, state, run = batch
	assert run() == 2
	unrelated = dest / "skipped.csv"
	unrelated.write_text("keep me")
	retry = next(dest.glob("skipped-*.csv"))
	assert "Artist - Middle.mp3" not in (dest / "Mix.m3u8").read_text(encoding="utf-8")
	state["fail"] = set()
	assert run(retry) == 0
	media = [line for line in (dest / "Mix.m3u8").read_text(encoding="utf-8").splitlines() if not line.startswith("#")]
	assert media == ["Artist - First.mp3", "Artist - Middle.mp3", "Artist - Last.mp3"]
	assert state["tagged"][-1]["track_no"] == 17
	assert state["tagged"][-1]["disc_no"] == 2
	assert not retry.exists() and not retry.with_suffix(".state.json").exists()
	assert unrelated.read_text() == "keep me"


def test_different_input_same_playlist_does_not_delete_retry_list(batch):
	source, dest, state, run = batch
	assert run() == 2
	retry = next(dest.glob("skipped-*.csv"))
	before = retry.read_bytes()
	state["fail"] = set()
	other = source.with_name("other.csv")
	other.write_bytes(source.read_bytes())
	assert run(other) == 0
	assert retry.read_bytes() == before
	assert retry.with_suffix(".state.json").exists()


def test_no_skipped_csv_does_not_touch_existing_retry_files(batch):
	source, dest, state, run = batch
	assert run() == 2
	before = {p.name: p.read_bytes() for p in dest.glob("skipped-*")}
	assert run(source, "--no-skipped-csv") == 2
	assert {p.name: p.read_bytes() for p in dest.glob("skipped-*")} == before


@pytest.mark.parametrize("target", ["csv", "m3u", "state"])
def test_changed_retry_inputs_fail_without_overwriting(batch, target):
	source, dest, state, run = batch
	assert run() == 2
	retry = next(dest.glob("skipped-*.csv"))
	path = {"csv": retry, "m3u": dest / "Mix.m3u8", "state": retry.with_suffix(".state.json")}[target]
	path.write_bytes(path.read_bytes() + b"\nCHANGED")
	before = {p.name: p.read_bytes() for p in dest.iterdir()}
	assert run(retry) == 1
	assert {p.name: p.read_bytes() for p in dest.iterdir()} == before


def test_partial_retry_generates_new_owned_pair(batch):
	source, dest, state, run = batch
	assert run() == 2
	old = next(dest.glob("skipped-*.csv"))
	assert run(old) == 2
	new = next(dest.glob("skipped-*.csv"))
	assert old != new and not old.exists()
	assert new.with_suffix(".state.json").exists()


def test_skipped_writer_is_atomic_and_preserves_numbers(tmp_path, monkeypatch):
	path = tmp_path / "retry.csv"
	path.write_bytes(b"original")
	def fail(*args):
		raise OSError("disk failure")
	with monkeypatch.context() as patcher:
		patcher.setattr(csv_import.os, "replace", fail)
		with pytest.raises(OSError):
			csv_import.write_skipped_csv(path, [])
	assert path.read_bytes() == b"original"
	assert list(tmp_path.iterdir()) == [path]
	csv_import.write_skipped_csv(path, [{"track": {"title": "Song", "artists": "Artist", "playlist": "Mix", "track_no": 17, "disc_no": 2}}])
	track = csv_import.tracks_from_csv(csv_import.load_csv(path))[0]
	assert (track["track_no"], track["disc_no"]) == (17, 2)
