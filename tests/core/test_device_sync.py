import pathlib

from csvmusic.core.device_sync import PortableDevice, _ipod_track_identity, delete_device_playlist, list_device_playlists, sync_mass_storage


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
