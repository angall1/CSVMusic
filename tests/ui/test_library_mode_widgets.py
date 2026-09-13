# tabs only
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from csvmusic.ui.library_mode import (
	_configure_playlist_status_widget, _pending_download_tracks, _playlists_contributing_tracks,
)


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
