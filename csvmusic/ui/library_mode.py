# tabs only
import pathlib
import random

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (
	QAbstractItemView, QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView,
	QInputDialog, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
	QProgressBar, QScrollArea, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from csvmusic.core.library import (
	add_playlist_urls, enabled_tracks, export_csv, library_status, load_library,
	merge_playlist_scan, new_library, playlist_by_id, save_library,
)
from csvmusic.core.log import log
from csvmusic.core.settings import settings_path
from csvmusic.core.track_output import expected_track_path
from csvmusic.core.youtube_url import YouTubeVideoUrlError, parse_youtube_video_id
from csvmusic.ui.spotify_public_scrape import SpotifyPublicScrapeDialog


def _playlist_action_icon(kind: str) -> QIcon:
	pixmap = QPixmap(20, 20)
	pixmap.fill(Qt.transparent)
	painter = QPainter(pixmap)
	painter.setRenderHint(QPainter.Antialiasing)
	pen = QPen(Qt.white, 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
	painter.setPen(pen)
	if kind == "refresh":
		painter.drawArc(QRectF(3.5, 3.5, 13, 13), 35 * 16, 285 * 16)
		painter.setBrush(Qt.white)
		painter.drawPolygon(QPolygonF([QPointF(15.8, 2.8), QPointF(16.4, 8.0), QPointF(11.4, 6.4)]))
	else:
		painter.drawRoundedRect(QRectF(5.0, 6.0, 10.0, 11.0), 1.0, 1.0)
		painter.drawLine(QPointF(3.8, 5.0), QPointF(16.2, 5.0))
		painter.drawLine(QPointF(7.5, 3.2), QPointF(12.5, 3.2))
		painter.drawLine(QPointF(8.0, 8.5), QPointF(8.0, 14.5))
		painter.drawLine(QPointF(12.0, 8.5), QPointF(12.0, 14.5))
	painter.end()
	return QIcon(pixmap)


class LibraryScanProgressDialog(QDialog):
	canceled = Signal()

	def __init__(self, parent=None):
		super().__init__(parent)
		self.setWindowTitle("Scanning Spotify Playlists")
		self.setWindowModality(Qt.WindowModal)
		self.resize(720, 260)
		layout = QHBoxLayout(self)
		info = QVBoxLayout()
		self.label = QLabel("Preparing playlist scan...")
		self.label.setWordWrap(True)
		self.progress = QProgressBar()
		self.cancel_button = QPushButton("Cancel")
		self.cancel_button.clicked.connect(self.canceled.emit)
		info.addWidget(self.label)
		info.addWidget(self.progress)
		info.addStretch(1)
		info.addWidget(self.cancel_button)
		layout.addLayout(info, 1)
		preview_column = QVBoxLayout()
		preview_column.addWidget(QLabel("Live page preview"))
		self.preview = QScrollArea()
		self.preview.setFixedSize(340, 200)
		self.preview.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
		self.preview.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
		self.preview.setWidgetResizable(False)
		preview_column.addWidget(self.preview)
		layout.addLayout(preview_column)

	def setRange(self, minimum: int, maximum: int) -> None:
		self.progress.setRange(minimum, maximum)

	def setValue(self, value: int) -> None:
		self.progress.setValue(value)

	def setLabelText(self, text: str) -> None:
		self.label.setText(text)

	def attach_browser(self, browser) -> None:
		browser.setMinimumSize(1000, 650)
		browser.resize(1000, 650)
		self.preview.setWidget(browser)
		browser.show()
		QTimer.singleShot(0, self._offset_preview)
		QTimer.singleShot(750, self._offset_preview)

	def _offset_preview(self) -> None:
		"""Move the clipped preview past Spotify's sidebar and into the track rows."""
		horizontal = self.preview.horizontalScrollBar()
		if horizontal.maximum() > 0:
			horizontal.setValue(round(horizontal.maximum() * 0.42))
		vertical = self.preview.verticalScrollBar()
		vertical.setValue(min(vertical.maximum(), 35))

	def detach_browser(self, browser, owner) -> None:
		self.preview.takeWidget()
		browser.hide()
		browser.setParent(owner)


class LibraryModeDialog(QDialog):
	tracks_ready = Signal(object, str, str, str)

	def __init__(self, parent=None):
		super().__init__(parent)
		self.setWindowTitle("CSVMusic Library Mode")
		self.resize(1100, 720)
		self.library_path = settings_path().parent / "library.json"
		self.library = self._load_or_create()
		self.scan_queue: list[dict] = []
		self.scans_completed = 0
		self.scraper: SpotifyPublicScrapeDialog | None = None
		self.scan_dialog: LibraryScanProgressDialog | None = None
		self.scan_cancelled = False
		self.scan_warnings: list[str] = []
		self.image_manager = QNetworkAccessManager(self)
		self.image_cache: dict[str, QIcon] = {}
		self.image_waiters: dict[str, list[QTreeWidgetItem]] = {}
		self.image_requests: set[str] = set()
		self.image_queue: list[str] = []
		self.image_active = 0
		self.image_concurrency = 2
		self._build_ui()
		self._refresh()

	def _load_or_create(self) -> dict:
		if self.library_path.exists():
			try:
				return load_library(self.library_path)
			except Exception as exc:
				log(f"library load failed path={self.library_path} error={exc}")
		return new_library()

	def _build_ui(self) -> None:
		layout = QVBoxLayout(self)
		title = QLabel("Persistent playlist library")
		title.setStyleSheet("font-size: 20px; font-weight: bold;")
		layout.addWidget(title)
		path_row = QHBoxLayout()
		self.path_label = QLabel(str(self.library_path))
		self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
		open_button = QPushButton("Open Library...")
		open_button.clicked.connect(self._open_library)
		save_as_button = QPushButton("Save As...")
		save_as_button.clicked.connect(self._save_as)
		path_row.addWidget(QLabel("Library file:"))
		path_row.addWidget(self.path_label, 1)
		path_row.addWidget(open_button)
		path_row.addWidget(save_as_button)
		layout.addLayout(path_row)
		output_row = QHBoxLayout()
		self.output_label = QLabel(self.library.get("output_dir") or "No output folder selected")
		choose_output = QPushButton("Choose Output...")
		choose_output.clicked.connect(self._choose_output)
		self.format_combo = QComboBox()
		self.format_combo.addItems(["m4a", "mp3"])
		self.format_combo.setCurrentText(str(self.library.get("format") or "m4a"))
		self.format_combo.currentTextChanged.connect(self._refresh)
		self.format_combo.currentTextChanged.connect(self._format_changed)
		output_row.addWidget(QLabel("Output:"))
		output_row.addWidget(self.output_label, 1)
		output_row.addWidget(choose_output)
		output_row.addWidget(QLabel("Format:"))
		output_row.addWidget(self.format_combo)
		layout.addLayout(output_row)
		url_row = QHBoxLayout()
		self.urls_input = QPlainTextEdit()
		self.urls_input.setPlaceholderText("Paste one Spotify playlist URL per line")
		self.urls_input.setMaximumHeight(90)
		add_button = QPushButton("Add URLs")
		add_button.clicked.connect(self._add_urls)
		url_row.addWidget(self.urls_input, 1)
		url_row.addWidget(add_button)
		layout.addLayout(url_row)
		actions = QHBoxLayout()
		for label, slot in (
			("Rescan All", self._rescan_all),
			("Export CSV...", self._export_csv),
			("Use Enabled Tracks in CSVMusic", self._use_in_csvmusic),
		):
			button = QPushButton(label)
			button.clicked.connect(slot)
			actions.addWidget(button)
		actions.addStretch(1)
		layout.addLayout(actions)
		splitter = QSplitter()
		left = QWidget()
		left_layout = QVBoxLayout(left)
		left_layout.setContentsMargins(0, 0, 0, 0)
		left_layout.addWidget(QLabel("Playlists"))
		self.playlist_tree = QTreeWidget()
		self.playlist_tree.setHeaderLabels(["Playlist", "Tracks", "Missing", "Last scan", "Actions"])
		self.playlist_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
		self.playlist_tree.setIconSize(QSize(48, 48))
		self.playlist_tree.itemSelectionChanged.connect(self._show_tracks)
		self.playlist_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
		for column in range(1, 5):
			self.playlist_tree.header().setSectionResizeMode(column, QHeaderView.ResizeToContents)
		left_layout.addWidget(self.playlist_tree)
		right = QWidget()
		right_layout = QVBoxLayout(right)
		right_layout.setContentsMargins(0, 0, 0, 0)
		right_actions = QHBoxLayout()
		right_actions.addWidget(QLabel("Tracks (checkbox controls download selection)"))
		right_actions.addStretch(1)
		check_all = QPushButton("Check All")
		check_all.clicked.connect(lambda: self._set_all_tracks(True))
		uncheck_all = QPushButton("Uncheck All")
		uncheck_all.clicked.connect(lambda: self._set_all_tracks(False))
		redownload = QPushButton("Toggle Redownload")
		redownload.clicked.connect(self._toggle_redownload)
		correct_match = QPushButton("Set YouTube Match...")
		correct_match.clicked.connect(self._set_youtube_match)
		right_actions.addWidget(check_all)
		right_actions.addWidget(uncheck_all)
		right_actions.addWidget(redownload)
		right_actions.addWidget(correct_match)
		right_layout.addLayout(right_actions)
		self.track_tree = QTreeWidget()
		self.track_tree.setHeaderLabels(["Track", "Artist", "Album", "State"])
		self.track_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
		self.track_tree.setIconSize(QSize(42, 42))
		self.track_art_timer = QTimer(self)
		self.track_art_timer.setSingleShot(True)
		self.track_art_timer.setInterval(80)
		self.track_art_timer.timeout.connect(self._load_visible_track_images)
		self.track_tree.verticalScrollBar().valueChanged.connect(lambda _value: self.track_art_timer.start())
		self.track_tree.itemChanged.connect(self._track_checked)
		for column in range(3):
			self.track_tree.header().setSectionResizeMode(column, QHeaderView.Stretch)
		self.track_tree.header().setSectionResizeMode(3, QHeaderView.ResizeToContents)
		right_layout.addWidget(self.track_tree)
		splitter.addWidget(left)
		splitter.addWidget(right)
		splitter.setSizes([420, 680])
		layout.addWidget(splitter, 1)
		self.status = QLabel()
		self.status.setWordWrap(True)
		layout.addWidget(self.status)

	def _save(self) -> None:
		save_library(self.library_path, self.library)
		log(f"library saved path={self.library_path} playlists={len(self.library.get('playlists', []))}")
		self.path_label.setText(str(self.library_path))

	def _open_library(self) -> None:
		path, _ = QFileDialog.getOpenFileName(self, "Open CSVMusic Library", str(self.library_path.parent), "CSVMusic Library (*.json)")
		if not path:
			return
		try:
			self.library = load_library(path)
		except Exception as exc:
			QMessageBox.critical(self, "Library Error", str(exc))
			return
		self.library_path = pathlib.Path(path)
		self.output_label.setText(self.library.get("output_dir") or "No output folder selected")
		self.format_combo.setCurrentText(str(self.library.get("format") or "m4a"))
		self._refresh()

	def _save_as(self) -> None:
		path, _ = QFileDialog.getSaveFileName(self, "Save CSVMusic Library", str(self.library_path), "CSVMusic Library (*.json)")
		if path:
			self.library_path = pathlib.Path(path).with_suffix(".json")
			self._save()

	def _choose_output(self) -> None:
		path = QFileDialog.getExistingDirectory(self, "Choose Library Output", self.library.get("output_dir") or "")
		if path:
			self.library["output_dir"] = path
			self.output_label.setText(path)
			self._save()
			self._refresh()

	def _format_changed(self, value: str) -> None:
		self.library["format"] = value
		self._save()

	def _add_urls(self) -> None:
		values = self.urls_input.toPlainText().splitlines()
		added, errors = add_playlist_urls(self.library, values)
		self._save()
		self.urls_input.clear()
		self._refresh()
		self.status.setText(f"Added {len(added)} playlist(s)." + (f" {len(errors)} URL(s) were invalid." if errors else ""))

	def _selected_ids(self) -> set[str]:
		return {str(item.data(0, Qt.UserRole)) for item in self.playlist_tree.selectedItems()}

	def _rescan_all(self) -> None:
		self._begin_scan(list(self.library.get("playlists", [])))

	def _rescan_playlist(self, playlist_id: str) -> None:
		playlist = playlist_by_id(self.library, playlist_id)
		if playlist:
			self._begin_scan([playlist])

	def _begin_scan(self, playlists: list[dict]) -> None:
		if self.scraper is not None:
			QMessageBox.information(self, "Scan Running", "A playlist scan is already running.")
			return
		if not playlists:
			QMessageBox.information(self, "No Playlists", "Select or add at least one playlist.")
			return
		self.scan_queue = list(playlists)
		self.scans_completed = 0
		self.scan_cancelled = False
		self.scan_warnings = []
		log(f"library scan started playlists={len(playlists)}")
		self.scan_dialog = LibraryScanProgressDialog(self)
		self.scan_dialog.canceled.connect(self._cancel_scan)
		self.scan_dialog.show()
		self._scan_next()

	def _scan_next(self) -> None:
		if not self.scan_queue:
			self.status.setText("Library scan cancelled." if self.scan_cancelled else "Library scan complete.")
			if self.scan_dialog:
				try:
					self.scan_dialog.canceled.disconnect(self._cancel_scan)
				except RuntimeError:
					pass
				self.scan_dialog.close()
				self.scan_dialog.deleteLater()
				self.scan_dialog = None
			self._refresh()
			if self.scan_warnings and not self.scan_cancelled:
				QMessageBox.warning(
					self,
					"Incomplete Playlist Scan",
					"One or more playlists did not reach Spotify's reported total:\n\n" + "\n".join(self.scan_warnings),
				)
			return
		playlist = self.scan_queue.pop(0)
		self.status.setText(f"Scanning {playlist.get('name') or playlist['id']} ({len(self.scan_queue)} remaining)...")
		self.scraper = SpotifyPublicScrapeDialog(self)
		self.scraper.setWindowTitle(f"Library Scan - {playlist.get('name') or playlist['id']}")
		self.scraper.url_input.setText(playlist["url"])
		self.scraper.scrape_finished.connect(self._scan_finished)
		self.scraper.scrape_progress.connect(self._scan_progress_changed)
		self.scraper.resize(1100, 780)
		self.scraper.page.setVisible(True)
		if self.scan_dialog:
			self.scan_dialog.attach_browser(self.scraper.browser)
		self.scraper.start_scrape()
		if self.scan_dialog:
			self.scan_dialog.setRange(0, 0)
			self.scan_dialog.setLabelText(
				f"Playlist {self.scans_completed + 1}: {playlist.get('name') or playlist['id']}\n"
				"Loading Spotify's public track list..."
			)

	def _scan_progress_changed(self, captured: int, reported_total: int, name: str) -> None:
		if not self.scan_dialog:
			return
		if reported_total > 0:
			self.scan_dialog.setRange(0, reported_total)
			self.scan_dialog.setValue(min(captured, reported_total))
			self.scan_dialog.setLabelText(
				f"Playlist {self.scans_completed + 1}: {name}\n"
				f"Captured {min(captured, reported_total)} of {reported_total} tracks. Scrolling and verifying..."
			)
		else:
			self.scan_dialog.setRange(0, 0)
			self.scan_dialog.setLabelText(
				f"Playlist {self.scans_completed + 1}: {name}\n"
				f"Captured {captured} tracks. Waiting for Spotify to report the total..."
			)

	def _cancel_scan(self) -> None:
		self.scan_cancelled = True
		self.scan_queue.clear()
		self.status.setText("Library scan cancelled.")
		log("library scan cancelled by user")
		if self.scraper and self.scraper.running:
			self.scraper._finish("Library scan cancelled by user.")

	def _scan_finished(self, result: object) -> None:
		data = dict(result or {})
		playlist_id = str(data.get("id") or "")
		if not self.scan_cancelled and playlist_id and data.get("tracks"):
			message = str(data.get("message") or "")
			warning = None if data.get("complete") else message
			if warning:
				self.scan_warnings.append(f"{data.get('name') or playlist_id}: {warning}")
			merge_playlist_scan(
				self.library,
				playlist_id,
				str(data.get("name") or "Spotify Playlist"),
				list(data.get("tracks") or []),
				reported_total=data.get("reported_total"),
				warning=warning,
				cover_url=data.get("cover_url"),
			)
			self._save()
			log(f"library playlist scan merged id={playlist_id} tracks={len(data.get('tracks') or [])} complete={bool(data.get('complete'))}")
		if self.scraper:
			if self.scan_dialog:
				self.scan_dialog.detach_browser(self.scraper.browser, self.scraper)
			self.scraper.close()
			self.scraper.deleteLater()
			self.scraper = None
		self._refresh()
		self.scans_completed += 1
		if self.scan_queue:
			delay_ms = random.randint(900, 1400)
			self.status.setText(f"Playlist saved. Waiting {delay_ms / 1000:.2f}s before the next playlist...")
			if self.scan_dialog:
				self.scan_dialog.setRange(0, 0)
				self.scan_dialog.setLabelText(f"Playlist saved. Starting the next playlist in {delay_ms / 1000:.2f} seconds...")
			log(f"library scan inter_playlist_delay_ms={delay_ms} remaining={len(self.scan_queue)}")
			QTimer.singleShot(delay_ms, self._scan_next)
		else:
			self._scan_next()

	def _remove_playlist(self, playlist_id: str) -> None:
		playlist = playlist_by_id(self.library, playlist_id)
		if not playlist:
			return
		name = playlist.get("name") or "this playlist"
		if QMessageBox.question(
			self,
			"Remove Playlist",
			f"Remove '{name}' from the library?\n\nDownloaded music files will not be deleted.",
			QMessageBox.Yes | QMessageBox.No,
			QMessageBox.No,
		) != QMessageBox.Yes:
			return
		self.library["playlists"] = [item for item in self.library.get("playlists", []) if item.get("id") != playlist_id]
		self._save()
		self._refresh()

	def _refresh(self, *_args) -> None:
		output = self.library.get("output_dir") or ""
		status = library_status(self.library, output, self.format_combo.currentText()) if hasattr(self, "format_combo") else {"playlists": {}, "totals": {}}
		selected = self._selected_ids() if hasattr(self, "playlist_tree") else set()
		self.playlist_tree.clear()
		for playlist in self.library.get("playlists", []):
			counts = status.get("playlists", {}).get(str(playlist.get("id")), {})
			track_count = len(playlist.get("tracks", []))
			total = playlist.get("reported_total") or track_count
			last_scan = str(playlist.get("last_scanned_at") or "Never").replace("T", " ")[:19]
			item = QTreeWidgetItem([
				playlist.get("name") or "Unscanned Spotify Playlist",
				f"{track_count}/{total}",
				str(counts.get("missing", 0)),
				last_scan,
				"",
			])
			item.setData(0, Qt.UserRole, playlist.get("id"))
			item.setSizeHint(0, QSize(0, 52))
			self.playlist_tree.addTopLevelItem(item)
			actions = QWidget()
			actions_layout = QHBoxLayout(actions)
			actions_layout.setContentsMargins(3, 2, 3, 2)
			actions_layout.setSpacing(5)
			refresh_button = QToolButton()
			refresh_button.setIcon(_playlist_action_icon("refresh"))
			refresh_button.setIconSize(QSize(20, 20))
			refresh_button.setToolTip("Rescan this playlist")
			refresh_button.setAccessibleName("Rescan playlist")
			refresh_button.setFixedSize(28, 28)
			refresh_button.setStyleSheet(
				"QToolButton { color: white; background: #169c46; border: none; border-radius: 14px; "
				"width: 28px; height: 28px; } "
				"QToolButton:hover { background: #1db954; }"
			)
			refresh_button.clicked.connect(lambda _checked=False, playlist_id=playlist.get("id"): self._rescan_playlist(str(playlist_id)))
			delete_button = QToolButton()
			delete_button.setIcon(_playlist_action_icon("delete"))
			delete_button.setIconSize(QSize(20, 20))
			delete_button.setToolTip("Remove this playlist")
			delete_button.setAccessibleName("Delete playlist")
			delete_button.setFixedSize(28, 28)
			delete_button.setStyleSheet(
				"QToolButton { color: white; background: #c62828; border: none; border-radius: 14px; "
				"width: 28px; height: 28px; } "
				"QToolButton:hover { background: #e53935; }"
			)
			delete_button.clicked.connect(lambda _checked=False, playlist_id=playlist.get("id"): self._remove_playlist(str(playlist_id)))
			actions_layout.addWidget(refresh_button)
			actions_layout.addWidget(delete_button)
			self.playlist_tree.setItemWidget(item, 4, actions)
			self._request_image(str(playlist.get("cover_url") or ""), item)
			if playlist.get("id") in selected:
				item.setSelected(True)
		self._show_tracks()
		totals = status.get("totals", {})
		if totals:
			self.status.setText(
				f"Enabled {totals.get('enabled', 0)} | Downloaded {totals.get('downloaded', 0)} | "
				f"Missing {totals.get('missing', 0)} | Disabled {totals.get('disabled', 0)}"
			)

	def _show_tracks(self) -> None:
		ids = self._selected_ids()
		self.track_tree.blockSignals(True)
		self.track_tree.clear()
		output = pathlib.Path(self.library.get("output_dir") or "")
		fmt = self.format_combo.currentText()
		for playlist_id in ids:
			playlist = playlist_by_id(self.library, playlist_id)
			if not playlist:
				continue
			for index, track in enumerate(playlist.get("tracks", [])):
				candidate = dict(track)
				candidate["playlist"] = playlist.get("name") or "Playlist"
				if not track.get("enabled", True):
					state = "Disabled"
				elif track.get("force_redownload"):
					state = "Redownload"
				elif expected_track_path(candidate, output, fmt).exists():
					state = "Downloaded"
				else:
					state = "Missing"
				item = QTreeWidgetItem([track.get("title", ""), track.get("artists", ""), track.get("album", ""), state])
				item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
				item.setCheckState(0, Qt.Checked if track.get("enabled", True) else Qt.Unchecked)
				item.setData(0, Qt.UserRole, (playlist_id, index))
				item.setData(0, Qt.UserRole + 2, bool(track.get("enabled", True)))
				item.setSizeHint(0, QSize(0, 46))
				item.setData(0, Qt.UserRole + 1, str(track.get("cover_url") or ""))
				self.track_tree.addTopLevelItem(item)
		self.track_tree.blockSignals(False)
		self.track_art_timer.start(0)

	def _load_visible_track_images(self) -> None:
		count = self.track_tree.topLevelItemCount()
		if count <= 0:
			return
		viewport = self.track_tree.viewport()
		first_item = self.track_tree.itemAt(2, 2)
		last_item = self.track_tree.itemAt(2, max(2, viewport.height() - 3))
		first = self.track_tree.indexOfTopLevelItem(first_item) if first_item else 0
		last = self.track_tree.indexOfTopLevelItem(last_item) if last_item else min(count - 1, first + 12)
		first = max(0, first - 6)
		last = min(count - 1, max(first, last) + 6)
		# Insert in reverse because priority requests are pushed to the front;
		# the top visible row should still be downloaded first.
		for index in range(last, first - 1, -1):
			item = self.track_tree.topLevelItem(index)
			self._request_image(str(item.data(0, Qt.UserRole + 1) or ""), item, priority=True)

	def _request_image(self, url: str, item: QTreeWidgetItem, *, priority: bool = False) -> None:
		if not url.startswith(("https://", "http://")):
			return
		cached = self.image_cache.get(url)
		if cached is not None:
			item.setIcon(0, cached)
			return
		self.image_waiters.setdefault(url, []).append(item)
		if url in self.image_requests or url in self.image_queue:
			return
		if priority:
			self.image_queue.insert(0, url)
		else:
			self.image_queue.append(url)
		self._pump_image_queue()

	def _pump_image_queue(self) -> None:
		while self.image_active < self.image_concurrency and self.image_queue:
			url = self.image_queue.pop(0)
			self.image_requests.add(url)
			self.image_active += 1
			request = QNetworkRequest(QUrl(url))
			request.setTransferTimeout(5000)
			reply = self.image_manager.get(request)
			reply.finished.connect(lambda reply=reply, url=url: self._image_finished(url, reply))

	def _image_finished(self, url: str, reply) -> None:
		self.image_requests.discard(url)
		self.image_active = max(0, self.image_active - 1)
		data = bytes(reply.readAll())
		reply.deleteLater()
		icon = QIcon()
		if len(data) <= 10 * 1024 * 1024:
			pixmap = QPixmap()
			if pixmap.loadFromData(data):
				icon = QIcon(pixmap)
				self.image_cache[url] = icon
		for item in self.image_waiters.pop(url, []):
			try:
				if not icon.isNull():
					item.setIcon(0, icon)
			except RuntimeError:
				pass
		self._pump_image_queue()

	def _track_checked(self, item: QTreeWidgetItem, _column: int) -> None:
		data = item.data(0, Qt.UserRole)
		if not data:
			return
		enabled = item.checkState(0) == Qt.Checked
		if item.data(0, Qt.UserRole + 2) == enabled:
			return
		item.setData(0, Qt.UserRole + 2, enabled)
		playlist = playlist_by_id(self.library, data[0])
		playlist["tracks"][data[1]]["enabled"] = enabled
		self._save()
		self._refresh()

	def _set_all_tracks(self, enabled: bool) -> None:
		for playlist_id in self._selected_ids():
			playlist = playlist_by_id(self.library, playlist_id)
			for track in playlist.get("tracks", []):
				track["enabled"] = enabled
		self._save()
		self._refresh()

	def _toggle_redownload(self) -> None:
		for item in self.track_tree.selectedItems():
			playlist_id, index = item.data(0, Qt.UserRole)
			track = playlist_by_id(self.library, playlist_id)["tracks"][index]
			track["force_redownload"] = not track.get("force_redownload", False)
		self._save()
		self._refresh()

	def _set_youtube_match(self) -> None:
		items = self.track_tree.selectedItems()
		if len(items) != 1:
			QMessageBox.information(self, "Select One Track", "Select exactly one track to set its replacement YouTube match.")
			return
		playlist_id, index = items[0].data(0, Qt.UserRole)
		track = playlist_by_id(self.library, playlist_id)["tracks"][index]
		value, ok = QInputDialog.getText(
			self,
			"Set YouTube Match",
			"Paste the correct YouTube or YouTube Music URL (leave blank to restore automatic matching):",
			text=str(track.get("preferred_video_id") or ""),
		)
		if not ok:
			return
		try:
			video_id = parse_youtube_video_id(value) if value.strip() else None
		except YouTubeVideoUrlError as exc:
			QMessageBox.warning(self, "Invalid YouTube URL", str(exc))
			return
		track["preferred_video_id"] = video_id
		track["preferred_video_label"] = value.strip() or None
		track["force_redownload"] = bool(video_id)
		self._save()
		self._refresh()

	def _export_csv(self) -> None:
		path, _ = QFileDialog.getSaveFileName(self, "Export Library CSV", str(self.library_path.with_suffix(".csv")), "CSV (*.csv)")
		if path:
			export_csv(path, self.library, self._selected_ids() or None)
			self.status.setText(f"Exported enabled tracks to {path}")

	def _use_in_csvmusic(self) -> None:
		tracks = enabled_tracks(self.library, self._selected_ids() or None)
		if not tracks:
			QMessageBox.information(self, "No Tracks", "Scan and enable at least one track first.")
			return
		output = self.library.get("output_dir") or ""
		if not output:
			QMessageBox.warning(self, "Missing Output", "Choose the library output folder first.")
			return
		for track in tracks:
			track["library_path"] = str(self.library_path)
		log(f"library handed to downloader tracks={len(tracks)} output={output}")
		self.tracks_ready.emit(tracks, f"Library: {self.library.get('name') or 'My Library'}", output, self.format_combo.currentText())
		self.accept()

	def closeEvent(self, event) -> None:
		if self.scraper and self.scraper.running:
			self.scraper._finish("Library scan cancelled because Library Mode was closed.")
		if self.scan_dialog:
			self.scan_dialog.close()
		self._save()
		super().closeEvent(event)
