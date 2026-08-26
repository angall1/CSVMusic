import socket

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from csvmusic.core.spotify_api import SpotifyAPIError
from csvmusic.core.spotify_import import SpotifyPlaylist
from csvmusic.ui import spotify_api_test
from csvmusic.ui.spotify_api_test import CALLBACK_URL, SpotifyAPITestDialog, SpotifySelectedPlaylistsWorker, callback_port_available


def test_callback_port_check_detects_used_port():
	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
		listener.bind(("127.0.0.1", 0))
		port = listener.getsockname()[1]
		assert callback_port_available(port=port) is False


def test_callback_port_check_detects_available_port():
	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
		probe.bind(("127.0.0.1", 0))
		port = probe.getsockname()[1]
	assert callback_port_available(port=port) is True


def test_spotify_api_wizard_selects_and_filters_playlists():
	app = QApplication.instance() or QApplication([])
	dialog = SpotifyAPITestDialog()
	assert dialog.callback_input.text() == CALLBACK_URL
	assert dialog.pages.count() == 4
	assert dialog.pages.currentIndex() == 0
	dialog.user_playlists = [
		{"id": "2", "name": "Zulu", "owner": "Austin", "total": 5, "public": True, "collaborative": False, "url": "url-2"},
		{"id": "1", "name": "Alpha", "owner": "Austin", "total": 10, "public": False, "collaborative": False, "url": "url-1"},
	]
	dialog._render_choices()
	assert dialog.selection_tree.topLevelItem(0).text(0) == "Alpha"
	assert dialog.selection_tree.topLevelItem(0).checkState(0) == Qt.Unchecked
	dialog._toggle_all()
	assert dialog.selected_ids == {"1", "2"}
	assert dialog.check_all_button.text() == "Uncheck All"
	dialog.playlist_search.setText("Zulu")
	assert dialog.selection_tree.topLevelItemCount() == 1
	dialog.close()
	app.processEvents()


def test_followed_playlist_uses_public_page_fallback(monkeypatch):
	selected = {"id": "followed", "name": "Followed", "url": "https://open.spotify.com/playlist/followed"}
	playlist = SpotifyPlaylist(id="followed", name="Followed", tracks=[{"title": "Song"}])
	monkeypatch.setattr(
		spotify_api_test,
		"fetch_spotify_playlist_api",
		lambda *_args, **_kwargs: (_ for _ in ()).throw(SpotifyAPIError("Spotify denied access to this playlist.")),
	)
	monkeypatch.setattr(spotify_api_test, "fetch_spotify_playlist", lambda _url: playlist)
	worker = SpotifySelectedPlaylistsWorker([selected], "token")
	loaded = []
	worker.playlist_loaded.connect(lambda *args: loaded.append(args))

	worker.run()

	assert loaded[0][2] is True
	assert "public page metadata" in loaded[0][3].warning
