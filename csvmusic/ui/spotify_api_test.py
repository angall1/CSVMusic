# tabs only
import re
import secrets
import socket
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
	QComboBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
	QMessageBox, QProgressBar, QPushButton, QStackedWidget, QTreeWidget,
	QTreeWidgetItem, QVBoxLayout, QWidget,
)

from csvmusic.core.spotify_api import SpotifyAPIError, fetch_spotify_playlist_api, fetch_spotify_user_playlists
from csvmusic.core.spotify_import import fetch_spotify_playlist
from csvmusic.core.spotify_oauth import create_authorization_url, create_pkce_pair, exchange_authorization_code


CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 3000
CALLBACK_URL = f"http://{CALLBACK_HOST}:{CALLBACK_PORT}/callback"
DEFAULT_CLIENT_ID = "bda6888318054aa7a413b8bb8a004a1a"
_CLIENT_ID_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def callback_port_available(host: str = CALLBACK_HOST, port: int = CALLBACK_PORT) -> bool:
	try:
		with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
			listener.bind((host, port))
	except OSError:
		return False
	return True


class SpotifyPlaylistsWorker(QThread):
	finished_playlists = Signal(bool, object, str)

	def __init__(self, token: str, parent=None):
		super().__init__(parent)
		self.token = token

	def run(self) -> None:
		try:
			self.finished_playlists.emit(True, fetch_spotify_user_playlists(self.token), "")
		except Exception as exc:
			self.finished_playlists.emit(False, None, str(exc))


class SpotifySelectedPlaylistsWorker(QThread):
	playlist_loaded = Signal(int, int, bool, object, str)
	all_finished = Signal()

	def __init__(self, playlists: list[dict], token: str, parent=None):
		super().__init__(parent)
		self.playlists = playlists
		self.token = token

	def run(self) -> None:
		for index, selected in enumerate(self.playlists, start=1):
			if self.isInterruptionRequested():
				break
			try:
				result = fetch_spotify_playlist_api(selected["url"], self.token)
			except SpotifyAPIError as exc:
				if "denied access" not in str(exc).casefold():
					self.playlist_loaded.emit(index, len(self.playlists), False, selected, str(exc))
					continue
				try:
					result = fetch_spotify_playlist(selected["url"])
				except Exception as fallback_exc:
					self.playlist_loaded.emit(index, len(self.playlists), False, selected, f"{exc} Public-page fallback also failed: {fallback_exc}")
					continue
				fallback_note = (
					"Spotify Web API restricts tracks for followed playlists that you do not own or collaborate on. "
					"Loaded public page metadata instead."
				)
				if result.warning:
					fallback_note += f" {result.warning}"
				result.warning = fallback_note
			except Exception as exc:
				self.playlist_loaded.emit(index, len(self.playlists), False, selected, str(exc))
				continue
			else:
				pass
			self.playlist_loaded.emit(index, len(self.playlists), True, result, "")
		self.all_finished.emit()


class SpotifySignInWorker(QThread):
	open_browser = Signal(str)
	finished_sign_in = Signal(bool, str, str)

	def __init__(self, client_id: str, parent=None):
		super().__init__(parent)
		self.client_id = client_id

	def run(self) -> None:
		verifier, challenge = create_pkce_pair()
		state = secrets.token_urlsafe(24)
		result: dict[str, str] = {}

		class Handler(BaseHTTPRequestHandler):
			def do_GET(handler_self) -> None:
				parsed = urlparse(handler_self.path)
				if parsed.path != "/callback":
					handler_self.send_error(404)
					return
				params = parse_qs(parsed.query)
				for key in ("state", "code", "error"):
					result[key] = (params.get(key) or [""])[0]
				body = b"<html><body><h2>Spotify sign-in complete</h2><p>Return to CSVMusic.</p></body></html>"
				handler_self.send_response(200)
				handler_self.send_header("Content-Type", "text/html; charset=utf-8")
				handler_self.send_header("Content-Length", str(len(body)))
				handler_self.end_headers()
				handler_self.wfile.write(body)

			def log_message(handler_self, _format: str, *args) -> None:
				pass

		try:
			server = HTTPServer((CALLBACK_HOST, CALLBACK_PORT), Handler)
		except OSError:
			self.finished_sign_in.emit(False, "", f"Port {CALLBACK_PORT} is already in use.")
			return
		server.timeout = 0.5
		self.open_browser.emit(create_authorization_url(self.client_id, CALLBACK_URL, challenge, state))
		deadline = time.monotonic() + 180
		while not result and time.monotonic() < deadline and not self.isInterruptionRequested():
			server.handle_request()
		server.server_close()
		if self.isInterruptionRequested():
			return
		if not result:
			self.finished_sign_in.emit(False, "", "Spotify sign-in timed out after three minutes.")
			return
		if result.get("state") != state:
			self.finished_sign_in.emit(False, "", "Spotify returned an invalid security state.")
			return
		if result.get("error") or not result.get("code"):
			self.finished_sign_in.emit(False, "", f"Spotify sign-in failed: {result.get('error') or 'missing code'}")
			return
		try:
			tokens = exchange_authorization_code(self.client_id, result["code"], CALLBACK_URL, verifier)
		except SpotifyAPIError as exc:
			self.finished_sign_in.emit(False, "", str(exc))
			return
		self.finished_sign_in.emit(True, str(tokens["access_token"]), "")


class SpotifyAPITestDialog(QDialog):
	def __init__(self, parent=None):
		super().__init__(parent)
		self.access_token = ""
		self.user_playlists: list[dict] = []
		self.selected_ids: set[str] = set()
		self.sign_in_worker = None
		self.playlists_worker = None
		self.selected_worker = None
		self.setWindowTitle("Spotify API Setup Wizard")
		self.resize(920, 720)
		self._build_ui()

	def _build_ui(self) -> None:
		layout = QVBoxLayout(self)
		self.step_label = QLabel()
		self.step_label.setStyleSheet("font-size: 20px; font-weight: bold;")
		layout.addWidget(self.step_label)
		self.pages = QStackedWidget()
		self.pages.addWidget(self._dashboard_page())
		self.pages.addWidget(self._signin_page())
		self.pages.addWidget(self._selection_page())
		self.pages.addWidget(self._results_page())
		self.pages.currentChanged.connect(self._page_changed)
		layout.addWidget(self.pages, 1)
		nav = QHBoxLayout()
		self.back_button = QPushButton("Back")
		self.back_button.clicked.connect(lambda: self.pages.setCurrentIndex(max(0, self.pages.currentIndex() - 1)))
		self.next_button = QPushButton("Next")
		self.next_button.clicked.connect(self._next_page)
		nav.addWidget(self.back_button)
		nav.addStretch(1)
		nav.addWidget(self.next_button)
		layout.addLayout(nav)
		self._page_changed(0)

	def _dashboard_page(self) -> QWidget:
		page = QWidget()
		layout = QVBoxLayout(page)
		text = QLabel(
			"1. Open the <a href='https://developer.spotify.com/dashboard'>Spotify Developer Dashboard</a>.<br><br>"
			"2. Create an app with any name and description.<br><br>"
			"3. Add the exact callback URL below as a Redirect URI.<br><br>"
			"4. Under <b>Which API/SDKs are you planning to use?</b>, select <b>Web API</b> only. "
			"Leave Web Playback SDK, Ads API, Android, and iOS unchecked.<br><br>"
			"5. Accept the terms and create the app. Never enter the Client Secret in CSVMusic."
		)
		text.setOpenExternalLinks(True)
		text.setWordWrap(True)
		layout.addWidget(text)
		row = QHBoxLayout()
		self.callback_input = QLineEdit(CALLBACK_URL)
		self.callback_input.setReadOnly(True)
		self.copy_callback_button = QPushButton("Copy")
		self.copy_callback_button.clicked.connect(self._copy_callback)
		row.addWidget(QLabel("Callback URL:"))
		row.addWidget(self.callback_input, 1)
		row.addWidget(self.copy_callback_button)
		layout.addLayout(row)
		port_row = QHBoxLayout()
		self.port_status = QLabel()
		recheck = QPushButton("Recheck port")
		recheck.clicked.connect(self._check_port)
		port_row.addWidget(self.port_status, 1)
		port_row.addWidget(recheck)
		layout.addLayout(port_row)
		layout.addStretch(1)
		self._check_port()
		return page

	def _signin_page(self) -> QWidget:
		page = QWidget()
		layout = QVBoxLayout(page)
		info = QLabel("Enter the public Client ID. Browser sign-in uses PKCE and never requires the Client Secret. CSVMusic then verifies access by loading your playlists.")
		info.setWordWrap(True)
		layout.addWidget(info)
		form = QFormLayout()
		self.client_id_input = QLineEdit(DEFAULT_CLIENT_ID)
		form.addRow("Client ID:", self.client_id_input)
		layout.addLayout(form)
		self.sign_in_button = QPushButton("Sign in with Spotify")
		self.sign_in_button.clicked.connect(self._sign_in)
		layout.addWidget(self.sign_in_button)
		self.sign_in_progress = QProgressBar()
		self.sign_in_progress.setRange(0, 0)
		self.sign_in_progress.hide()
		layout.addWidget(self.sign_in_progress)
		self.sign_in_status = QLabel("Not signed in or verified yet.")
		self.sign_in_status.setWordWrap(True)
		layout.addWidget(self.sign_in_status)
		layout.addStretch(1)
		return page

	def _selection_page(self) -> QWidget:
		page = QWidget()
		layout = QVBoxLayout(page)
		controls = QHBoxLayout()
		self.playlist_search = QLineEdit()
		self.playlist_search.setPlaceholderText("Search playlists or owners...")
		self.playlist_search.textChanged.connect(self._render_choices)
		self.playlist_sort = QComboBox()
		self.playlist_sort.addItems(["Name A-Z", "Name Z-A", "Most tracks", "Fewest tracks"])
		self.playlist_sort.currentIndexChanged.connect(self._render_choices)
		self.check_all_button = QPushButton("Check All")
		self.check_all_button.clicked.connect(self._toggle_all)
		controls.addWidget(self.playlist_search, 1)
		controls.addWidget(self.playlist_sort)
		controls.addWidget(self.check_all_button)
		layout.addLayout(controls)
		self.selection_tree = QTreeWidget()
		self.selection_tree.setHeaderLabels(["Playlist", "Owner", "Tracks"])
		self.selection_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
		self.selection_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
		self.selection_tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
		self.selection_tree.itemChanged.connect(self._check_changed)
		layout.addWidget(self.selection_tree, 1)
		self.selection_status = QLabel("Playlists are unchecked by default.")
		layout.addWidget(self.selection_status)
		return page

	def _results_page(self) -> QWidget:
		page = QWidget()
		layout = QVBoxLayout(page)
		self.results_status = QLabel("Selected playlists will load here.")
		layout.addWidget(self.results_status)
		self.results_progress = QProgressBar()
		self.results_progress.hide()
		layout.addWidget(self.results_progress)
		self.results_tree = QTreeWidget()
		self.results_tree.setHeaderLabels(["Playlist / Track", "Artist", "Album", "Duration"])
		for column in range(3):
			self.results_tree.header().setSectionResizeMode(column, QHeaderView.Stretch)
		self.results_tree.header().setSectionResizeMode(3, QHeaderView.ResizeToContents)
		self.results_tree.itemClicked.connect(self._toggle_result)
		layout.addWidget(self.results_tree, 1)
		return page

	def _page_changed(self, index: int) -> None:
		titles = ("Step 1 of 4 - Developer Dashboard", "Step 2 of 4 - Sign in and verify", "Step 3 of 4 - Select playlists", "Step 4 of 4 - Loaded tracks")
		self.step_label.setText(titles[index])
		self.back_button.setEnabled(index > 0)
		self.next_button.setVisible(index < 3)
		self.next_button.setText("Load Selected Playlists" if index == 2 else "Next")
		if index == 1:
			self.next_button.setEnabled(bool(self.access_token and self.user_playlists))
		elif index == 2:
			self.next_button.setEnabled(bool(self.selected_ids))
		else:
			self.next_button.setEnabled(True)

	def _next_page(self) -> None:
		if self.pages.currentIndex() == 2:
			self._load_selected()
		else:
			self.pages.setCurrentIndex(self.pages.currentIndex() + 1)

	def _copy_callback(self) -> None:
		QGuiApplication.clipboard().setText(CALLBACK_URL)
		self.copy_callback_button.setText("Copied")

	def _check_port(self) -> None:
		available = callback_port_available()
		self.port_status.setText(f"Port {CALLBACK_PORT} is {'available' if available else 'already in use'} on {CALLBACK_HOST}.")
		self.port_status.setStyleSheet(f"color: {'#137333' if available else '#b06000'}; font-weight: bold;")

	def _sign_in(self) -> None:
		client_id = self.client_id_input.text().strip()
		if not _CLIENT_ID_RE.fullmatch(client_id):
			QMessageBox.warning(self, "Invalid Client ID", "Enter the 32-character Client ID from Spotify app settings.")
			return
		if not callback_port_available():
			QMessageBox.warning(self, "Port unavailable", f"Port {CALLBACK_PORT} is already in use.")
			return
		self.sign_in_button.setEnabled(False)
		self.sign_in_progress.show()
		self.sign_in_status.setText("Waiting for browser authorization...")
		self.sign_in_worker = SpotifySignInWorker(client_id, self)
		self.sign_in_worker.open_browser.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
		self.sign_in_worker.finished_sign_in.connect(self._signed_in)
		self.sign_in_worker.start()

	def _signed_in(self, ok: bool, token: str, error: str) -> None:
		self.sign_in_worker = None
		if not ok:
			self._verification_failed(f"Sign-in failed: {error}")
			return
		self.access_token = token
		self.sign_in_status.setText("Signed in. Verifying access and loading playlists...")
		self.playlists_worker = SpotifyPlaylistsWorker(token, self)
		self.playlists_worker.finished_playlists.connect(self._verified)
		self.playlists_worker.start()

	def _verification_failed(self, message: str) -> None:
		self.access_token = ""
		self.sign_in_progress.hide()
		self.sign_in_button.setEnabled(True)
		self.sign_in_status.setText(message)
		self.sign_in_status.setStyleSheet("color: #b00020; font-weight: bold;")

	def _verified(self, ok: bool, playlists: object, error: str) -> None:
		self.playlists_worker = None
		if not ok:
			self._verification_failed(f"Verification failed: {error}")
			return
		self.sign_in_progress.hide()
		self.sign_in_button.setEnabled(True)
		self.user_playlists = list(playlists or [])
		self.selected_ids.clear()
		self._render_choices()
		self.sign_in_status.setText(f"Verified successfully. Found {len(self.user_playlists)} playlists.")
		self.sign_in_status.setStyleSheet("color: #137333; font-weight: bold;")
		self.next_button.setEnabled(True)

	def _sorted_playlists(self) -> list[dict]:
		mode = self.playlist_sort.currentIndex()
		if mode == 1:
			return sorted(self.user_playlists, key=lambda p: p["name"].casefold(), reverse=True)
		if mode == 2:
			return sorted(self.user_playlists, key=lambda p: (-p["total"], p["name"].casefold()))
		if mode == 3:
			return sorted(self.user_playlists, key=lambda p: (p["total"], p["name"].casefold()))
		return sorted(self.user_playlists, key=lambda p: p["name"].casefold())

	def _render_choices(self, *_args) -> None:
		query = self.playlist_search.text().strip().casefold()
		self.selection_tree.blockSignals(True)
		self.selection_tree.clear()
		for playlist in self._sorted_playlists():
			if query and query not in playlist["name"].casefold() and query not in playlist["owner"].casefold():
				continue
			item = QTreeWidgetItem([playlist["name"], playlist["owner"], str(playlist["total"])])
			item.setData(0, Qt.UserRole, playlist)
			item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
			item.setCheckState(0, Qt.Checked if playlist["id"] in self.selected_ids else Qt.Unchecked)
			self.selection_tree.addTopLevelItem(item)
		self.selection_tree.blockSignals(False)
		self._update_selection()

	def _visible_items(self) -> list[QTreeWidgetItem]:
		return [self.selection_tree.topLevelItem(i) for i in range(self.selection_tree.topLevelItemCount())]

	def _check_changed(self, item: QTreeWidgetItem, _column: int) -> None:
		playlist = item.data(0, Qt.UserRole)
		if item.checkState(0) == Qt.Checked:
			self.selected_ids.add(playlist["id"])
		else:
			self.selected_ids.discard(playlist["id"])
		self._update_selection()

	def _toggle_all(self) -> None:
		items = self._visible_items()
		check = not items or not all(item.checkState(0) == Qt.Checked for item in items)
		self.selection_tree.blockSignals(True)
		for item in items:
			item.setCheckState(0, Qt.Checked if check else Qt.Unchecked)
			playlist_id = item.data(0, Qt.UserRole)["id"]
			(self.selected_ids.add if check else self.selected_ids.discard)(playlist_id)
		self.selection_tree.blockSignals(False)
		self._update_selection()

	def _update_selection(self) -> None:
		items = self._visible_items()
		all_checked = bool(items) and all(item.checkState(0) == Qt.Checked for item in items)
		self.check_all_button.setText("Uncheck All" if all_checked else "Check All")
		self.selection_status.setText(f"{len(self.selected_ids)} playlist(s) selected.")
		if self.pages.currentIndex() == 2:
			self.next_button.setEnabled(bool(self.selected_ids))

	def _load_selected(self) -> None:
		selected = [p for p in self.user_playlists if p["id"] in self.selected_ids]
		if not selected:
			return
		self.pages.setCurrentIndex(3)
		self.results_tree.clear()
		self.results_progress.setRange(0, len(selected))
		self.results_progress.setValue(0)
		self.results_progress.show()
		self.results_status.setText(f"Loading 0 of {len(selected)} playlists...")
		self.selected_worker = SpotifySelectedPlaylistsWorker(selected, self.access_token, self)
		self.selected_worker.playlist_loaded.connect(self._playlist_loaded)
		self.selected_worker.all_finished.connect(self._loading_finished)
		self.selected_worker.start()

	def _playlist_loaded(self, index: int, total: int, ok: bool, playlist: object, error: str) -> None:
		self.results_progress.setValue(index)
		self.results_status.setText(f"Loading {index} of {total} playlists...")
		if not ok:
			name = playlist.get("name", "Playlist") if isinstance(playlist, dict) else "Playlist"
			self.results_tree.addTopLevelItem(QTreeWidgetItem([f"{name} - failed: {error}", "", "", ""]))
			return
		tracks = getattr(playlist, "tracks", [])
		warning = getattr(playlist, "warning", None)
		label = getattr(playlist, "name", "Playlist") + (" (fallback)" if warning else "")
		parent = QTreeWidgetItem([label, "", "", f"{len(tracks)} tracks"])
		parent.setData(0, Qt.UserRole, "playlist")
		if warning:
			parent.setToolTip(0, warning)
			QTreeWidgetItem(parent, [f"Warning: {warning}", "", "", ""])
		for number, track in enumerate(tracks, start=1):
			ms = int(track.get("duration_ms") or 0)
			duration = f"{ms // 60000}:{(ms // 1000) % 60:02d}" if ms else ""
			QTreeWidgetItem(parent, [f"{number}. {track.get('title', '')}", track.get("artists", ""), track.get("album", ""), duration])
		self.results_tree.addTopLevelItem(parent)

	def _loading_finished(self) -> None:
		self.selected_worker = None
		self.results_progress.hide()
		self.results_status.setText(f"Loaded {self.results_tree.topLevelItemCount()} playlists. Click one to expand its tracks.")

	def _toggle_result(self, item: QTreeWidgetItem, _column: int) -> None:
		if item.parent() is None:
			item.setExpanded(not item.isExpanded())

	def closeEvent(self, event) -> None:
		for worker in (self.sign_in_worker, self.playlists_worker, self.selected_worker):
			if worker and worker.isRunning():
				worker.requestInterruption()
				worker.wait(1500)
		super().closeEvent(event)
