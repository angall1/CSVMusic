import pathlib

from csvmusic.core.device_sync import PortableDevice, _ipod_helper_path, _ipod_platform_bundle, _ipod_tool_paths, _ipod_track_identity, _ready_playlists, _run_ipod_helper, delete_device_playlist, list_device_playlists, sync_mass_storage


def test_mass_storage_sync_copies_ready_playlists_and_skips_incomplete(tmp_path: pathlib.Path) -> None:
	output = tmp_path / "output"
	device_root = tmp_path / "player"
	ready_folder = output / "Ready"
	ready_folder.mkdir(parents=True)
	(device_root).mkdir()
	track_path = ready_folder / "Artist - Song.mp3"
	track_path.write_bytes(b"audio-data")
	library = {
		"output_dir": str(output),
		"format": "mp3",
		"playlists": [
			{"name": "Ready", "tracks": [{"playlist": "Ready", "artists": "Artist", "title": "Song", "enabled": True}]},
			{"name": "Missing", "tracks": [{"playlist": "Missing", "artists": "Artist", "title": "Gone", "enabled": True}]},
		],
	}
	events: list[tuple[int, int, str]] = []
	device = PortableDevice("Test Player", device_root, "mass_storage", "test")

	result = sync_mass_storage(device, library, lambda done, total, message: events.append((done, total, message)))

	assert result.playlists == 1
	assert result.tracks_copied == 1
	assert result.tracks_reused == 0
	assert result.playlists_skipped == ("Missing",)
	assert (device_root / "CSVMusic" / "Ready" / track_path.name).read_bytes() == b"audio-data"
	playlist_text = (device_root / "CSVMusic" / "Playlists" / "Ready.m3u8").read_text(encoding="utf-8")
	assert "#PLAYLIST:Ready" in playlist_text
	assert f"../Ready/{track_path.name}" in playlist_text
	assert events[-1][:2] == (1, 1)
	device_playlists = list_device_playlists(device)
	assert [(playlist.name, playlist.track_count) for playlist in device_playlists] == [("Ready", 1)]
	delete_device_playlist(device, "Ready")
	assert list_device_playlists(device) == []
	assert (device_root / "CSVMusic" / "Ready" / track_path.name).is_file()


def test_mass_storage_sync_reuses_same_size_managed_file(tmp_path: pathlib.Path) -> None:
	output = tmp_path / "output"
	device_root = tmp_path / "player"
	source_folder = output / "Ready"
	destination_folder = device_root / "CSVMusic" / "Ready"
	source_folder.mkdir(parents=True)
	destination_folder.mkdir(parents=True)
	name = "Artist - Song.mp3"
	(source_folder / name).write_bytes(b"same")
	(destination_folder / name).write_bytes(b"same")
	library = {
		"output_dir": str(output), "format": "mp3",
		"playlists": [{"name": "Ready", "tracks": [{"playlist": "Ready", "artists": "Artist", "title": "Song"}]}],
	}
	device = PortableDevice("Test Player", device_root, "mass_storage", "test")

	result = sync_mass_storage(device, library, lambda _done, _total, _message: None)

	assert result.tracks_copied == 0
	assert result.tracks_reused == 1


def test_playlist_with_queued_replacement_is_not_ready_even_when_old_file_exists(tmp_path: pathlib.Path) -> None:
	output = tmp_path / "output"
	track_path = output / "ROCK" / "Black Sabbath - War Pigs.mp3"
	track_path.parent.mkdir(parents=True)
	track_path.write_bytes(b"old-live-version")
	track = {
		"playlist": "ROCK", "artists": "Black Sabbath", "title": "War Pigs",
		"enabled": True, "force_redownload": True,
	}
	library = {"output_dir": str(output), "format": "mp3", "playlists": [{"name": "ROCK", "tracks": [track]}]}

	ready, skipped = _ready_playlists(library)

	assert ready == []
	assert skipped == ["ROCK"]


def test_ready_playlists_are_sorted_alphabetically(tmp_path: pathlib.Path) -> None:
	output = tmp_path / "output"
	playlists = []
	for name in ("Zebra", "alpha", "Middle"):
		path = output / name / f"Artist - {name}.mp3"
		path.parent.mkdir(parents=True)
		path.write_bytes(b"audio")
		playlists.append({"name": name, "tracks": [{"playlist": name, "artists": "Artist", "title": name}]})
	library = {"output_dir": str(output), "format": "mp3", "playlists": playlists}

	ready, skipped = _ready_playlists(library)

	assert [playlist["name"] for playlist, _tracks in ready] == ["alpha", "Middle", "Zebra"]
	assert skipped == []


def test_ipod_identity_only_marks_explicit_alternatives_for_replacement() -> None:
	assert _ipod_track_identity({"sp_id": "spotify-track", "downloaded_video_id": "automatic"}) == "auto:automatic"
	assert _ipod_track_identity({
		"youtube_video_id": "source", "preferred_video_id": "source",
	}) == "auto:source"
	assert _ipod_track_identity({
		"youtube_video_id": "source", "preferred_video_id": "replacement",
	}) == "selected:replacement"
	assert _ipod_track_identity({
		"preferred_video_id": "replacement", "preferred_selection_locked": True,
	}) == "selected:replacement"


def test_ipod_tool_paths_prefer_bundled_release_helper(monkeypatch, tmp_path: pathlib.Path) -> None:
	bundle = tmp_path / "resources" / "ipod" / _ipod_platform_bundle()
	(bundle / "bin").mkdir(parents=True)
	(bundle / "lib").mkdir()
	(bundle / "bin" / "ipod-sync").write_bytes(b"helper")
	monkeypatch.setattr("csvmusic.core.device_sync.resource_base", lambda: tmp_path / "resources")

	helper, libraries = _ipod_tool_paths()

	assert helper == bundle / "bin" / "ipod-sync"
	assert libraries == bundle / "lib"


def test_ipod_bundle_matches_native_platform(monkeypatch) -> None:
	monkeypatch.setattr("csvmusic.core.device_sync.sys.platform", "darwin")
	monkeypatch.setattr("csvmusic.core.device_sync.platform.machine", lambda: "arm64")
	assert _ipod_platform_bundle() == "darwin-arm64"
	monkeypatch.setattr("csvmusic.core.device_sync.platform.machine", lambda: "x86_64")
	assert _ipod_platform_bundle() == "darwin-x86_64"
	monkeypatch.setattr("csvmusic.core.device_sync.sys.platform", "linux")
	assert _ipod_platform_bundle() == "linux-x86_64"


def test_native_ipod_helper_uses_posix_paths_and_library_environment(monkeypatch, tmp_path: pathlib.Path) -> None:
	helper = tmp_path / "ipod-sync"
	libraries = tmp_path / "lib"
	libraries.mkdir()
	helper.write_bytes(b"helper")
	captured = {}
	class Result:
		returncode = 0
		stdout = b"ok"
		stderr = b""
	def run(command, **kwargs):
		captured.update(command=command, kwargs=kwargs)
		return Result()
	monkeypatch.setattr("csvmusic.core.device_sync.sys.platform", "darwin")
	monkeypatch.setattr("csvmusic.core.device_sync._ipod_tool_paths", lambda: (helper, libraries))
	monkeypatch.setattr("csvmusic.core.device_sync.subprocess.run", run)

	assert _run_ipod_helper(["inspect", "/Volumes/IPOD"]) == "ok"
	assert captured["command"] == [str(helper), "inspect", "/Volumes/IPOD"]
	assert captured["kwargs"]["env"]["DYLD_LIBRARY_PATH"].startswith(str(libraries))
	assert _ipod_helper_path(tmp_path) == str(tmp_path.resolve())
