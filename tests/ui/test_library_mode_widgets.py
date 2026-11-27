# tabs only
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from csvmusic.ui.library_mode import (
	_configure_playlist_status_widget, _pending_download_tracks, _playlists_contributing_tracks,
	LibraryModeDialog, LibrarySettingsDialog,
)


def test_scan_unscanned_excludes_previously_scanned_playlists():
	from types import SimpleNamespace
	queued = []
	new = {"id": "new", "last_scanned_at": None}
	old = {"id": "old", "last_scanned_at": "2026-01-01"}
	dialog = SimpleNamespace(library={"playlists": [old, new]}, _begin_scan=queued.extend)
	LibraryModeDialog._scan_unscanned(dialog)
	assert queued == [new]


def test_library_cookie_settings_round_trip(monkeypatch, tmp_path):
	from csvmusic.ui import library_mode
	app = QApplication.instance() or QApplication([])
	cfg = {"use_cookies": True, "cookies_browser": "firefox:my-profile"}
	saved = {}
	monkeypatch.setattr(library_mode, "load_settings", lambda: cfg)
	monkeypatch.setattr(library_mode, "save_settings", saved.update)
	dialog = LibrarySettingsDialog({"output_dir": str(tmp_path)})
	assert dialog.use_cookies.isChecked()
	assert dialog.cookies_browser.currentText() == "firefox:my-profile"
	dialog.cookies_file.setText("cookies.txt")
	dialog._save()
	assert saved["cookies_file"] == "cookies.txt"
	assert saved["use_cookies"] is True
	dialog.close()
	assert app is not None


def test_error_status_button_does_not_use_label_only_alignment_api() -> None:
	app = QApplication.instance() or QApplication([])
	button = QPushButton("1 error")

	_configure_playlist_status_widget(button, unscanned=False)

	assert button.minimumWidth() == 112
	assert "text-align: right" in button.styleSheet()
	assert app is not None


def test_text_status_keeps_right_alignment() -> None:
	app = QApplication.instance() or QApplication([])
	label = QLabel("1 missing")

	_configure_playlist_status_widget(label, unscanned=False)

	assert label.alignment() == Qt.AlignRight | Qt.AlignVCenter
	assert app is not None


def test_download_all_only_returns_missing_files(tmp_path) -> None:
	existing = tmp_path / "already-there.mp3"
	existing.write_bytes(b"audio")
	tracks = [
		{
			"title": "Existing", "artists": "Artist", "downloaded_path": str(existing),
			"force_redownload": True, "_previous_audio_processing_signature": "old",
			"_previous_prefix_numbered": False,
		},
		{
			"title": "Missing", "artists": "Artist", "playlist": "List",
			"_previous_audio_processing_signature": "new", "_previous_prefix_numbered": True,
		},
	]

	pending = _pending_download_tracks(
		tracks, tmp_path, "mp3", audio_signature="new", audio_enabled=True,
		prefix_numbers=True, missing_only=True,
	)

	assert [track["title"] for track in pending] == ["Missing"]


def test_normal_download_keeps_explicit_replacements(tmp_path) -> None:
	existing = tmp_path / "already-there.mp3"
	existing.write_bytes(b"audio")
	track = {
		"title": "Existing", "artists": "Artist", "downloaded_path": str(existing),
		"force_redownload": True, "_previous_audio_processing_signature": "new",
		"_previous_prefix_numbered": False,
	}

	pending = _pending_download_tracks(
		[track], tmp_path, "mp3", audio_signature="new", audio_enabled=True,
		prefix_numbers=False,
	)

	assert pending == [track]


def test_download_label_only_includes_playlists_with_queued_tracks() -> None:
	playlists = [
		{"platform": "spotify", "id": "complete", "name": "Already Complete"},
		{"platform": "spotify", "id": "missing", "name": "Needs Songs"},
		{"platform": "youtube", "id": "also-missing", "name": "Also Needs Songs"},
	]
	tracks = [
		{"library_playlist_id": "spotify:missing"},
		{"library_playlist_id": "youtube:also-missing"},
	]

	active = _playlists_contributing_tracks(playlists, tracks)

	assert [playlist["name"] for playlist in active] == ["Needs Songs", "Also Needs Songs"]


def test_normal_download_skips_existing_files_with_unknown_eq_history(tmp_path) -> None:
	existing = tmp_path / "existing.mp3"
	existing.write_bytes(b"audio")
	tracks = [
		{"title": str(i), "downloaded_path": str(existing), "_previous_audio_processing_signature": None}
		for i in range(23)
	] + [{"title": f"Missing {i}", "artists": "Artist"} for i in range(7)]
	pending = _pending_download_tracks(
		tracks, tmp_path, "mp3", audio_signature="normalize=0|volume=4|bass=0|treble=0",
		audio_enabled=True, prefix_numbers=False,
	)
	assert pending == tracks[23:]


def test_normal_download_reprocesses_known_eq_changes(tmp_path) -> None:
	existing = tmp_path / "existing.mp3"
	existing.write_bytes(b"audio")
	track = {"downloaded_path": str(existing), "_previous_audio_processing_signature": "off"}
	assert _pending_download_tracks(
		[track], tmp_path, "mp3", audio_signature="normalize=0|volume=4|bass=0|treble=0",
		audio_enabled=True, prefix_numbers=False,
	) == [track]


def test_use_existing_file_clears_queue_and_saves(monkeypatch):
	from types import SimpleNamespace
	from csvmusic.ui.library_mode import LibraryModeDialog
	track = {"force_redownload": True, "last_error": "failed"}
	playlist = {"id": "test", "platform": "spotify", "name": "Mix", "tracks": [track]}
	calls = []
	def accept(probe, output, fmt):
		probe.update(downloaded_path="local.mp3", force_redownload=False, last_error=None, last_error_at=None, download_error=None, error=None)
	monkeypatch.setattr("csvmusic.ui.library_mode.use_existing_track_file", accept)
	dialog = SimpleNamespace(download_worker=None, single_download_worker=None,
		library={"playlists": [playlist]}, download_track_states={("spotify:test", 0): "Queued"},
		_save=lambda: calls.append("save"), _refresh=lambda: calls.append("refresh"))
	LibraryModeDialog._use_existing_file(dialog, "spotify:test", 0)
	assert not track["force_redownload"]
	assert track["last_error"] is None
	assert not dialog.download_track_states
	assert calls == ["save", "refresh"]


def test_download_rebuilds_playlist_without_audio_or_encoder_work(monkeypatch, tmp_path):
	from types import SimpleNamespace
	from csvmusic.ui import library_mode
	from csvmusic.core.library import write_library_playlists
	folder = tmp_path / "Mix"
	folder.mkdir()
	(folder / "Artist - Song.mp3").write_bytes(b"existing audio")
	playlist = {"id": "test", "platform": "spotify", "name": "Mix", "tracks": [{"title": "Song", "artists": "Artist", "album": "Album"}]}
	library = {"playlists": [playlist], "output_dir": str(tmp_path), "format": "mp3"}
	messages = []
	monkeypatch.setattr(library_mode, "load_settings", lambda: {})
	monkeypatch.setattr(library_mode.QMessageBox, "information", lambda *args: messages.append(args[-1]))
	monkeypatch.setattr(library_mode, "ffmpeg_supports_mp3", lambda *args: (_ for _ in ()).throw(AssertionError("Encoder should not be checked")))
	dialog = SimpleNamespace(library=library, download_worker=None, single_download_worker=None,
		_selected_ids=lambda: {"spotify:test"}, _selected_playlists=lambda: [playlist], _open_settings=lambda **kwargs: True,
		_regenerate_playlists=lambda ids: write_library_playlists(library, ids, {}))
	library_mode.LibraryModeDialog._start_download(dialog)
	assert (folder / "Mix.m3u8").is_file()
	assert "Rebuilt 1 playlist file" in messages[0]


def test_csv_rescan_selects_only_its_named_playlist(tmp_path):
	from csvmusic.ui.library_mode import DirectLibraryScanWorker
	path = tmp_path / "multi.csv"
	path.write_text("Playlist name,Track name,Artist name\nA,One,Artist\nB,Two,Artist\n", encoding="utf-8")
	worker = DirectLibraryScanWorker(str(path), "csv", source_id="a", csv_playlist_name="A")
	results = []
	worker.finished_scan.connect(results.append)
	worker.run()
	assert [t["title"] for t in results[0]["tracks"]] == ["One"]
	path.write_text("Playlist name,Track name,Artist name\nB,Two,Artist\n", encoding="utf-8")
	worker.run()
	assert results[1]["complete"]
	assert results[1]["tracks"] == []
