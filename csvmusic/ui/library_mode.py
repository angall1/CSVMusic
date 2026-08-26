# tabs only
import pathlib
import random

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontDatabase, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (
	QAbstractItemView, QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView,
	QFrame, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QSizePolicy, QSplitter,
	QProgressBar, QScrollArea, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from csvmusic.core.library import (
	add_playlist_urls, enabled_tracks, export_csv, library_status, load_library,
	merge_playlist_scan, new_library, playlist_by_id, save_library,
)
from csvmusic.core.log import log
from csvmusic.core.settings import settings_path
from csvmusic.core.paths import resource_base
from csvmusic.core.track_output import expected_track_path
from csvmusic.core.youtube_url import YouTubeVideoUrlError, parse_youtube_video_id
from csvmusic.ui.spotify_public_scrape import SpotifyPublicScrapeDialog
from csvmusic.core.youtube_music_import import fetch_youtube_music_source
from csvmusic.core.apple_music_import import fetch_apple_music_source
from csvmusic.version import APP_VERSION


class DirectLibraryScanWorker(QThread):
	finished_scan = Signal(object)

	def __init__(self, url: str, platform: str, parent=None):
		super().__init__(parent)
		self.url = url
		self.platform = platform

	def run(self) -> None:
		try:
			source = fetch_apple_music_source(self.url) if self.platform == "apple_music" else fetch_youtube_music_source(self.url)
			self.finished_scan.emit({
				"id": source.id, "name": source.name, "tracks": source.tracks,
				"reported_total": source.total_count, "message": source.warning or "",
				"complete": not bool(source.warning), "platform": self.platform,
				"cover_url": getattr(source, "cover_url", None),
			})
		except Exception as exc:
			self.finished_scan.emit({"error": str(exc), "complete": False, "platform": self.platform})


class ClickableFrame(QFrame):
	clicked = Signal()

	def mousePressEvent(self, event) -> None:
		self.clicked.emit()
		super().mousePressEvent(event)


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


def _source_placeholder_icon(platform: str) -> QIcon:
	pixmap = QPixmap(48, 48)
	colors = {"spotify": "#1b8f48", "youtube_music": "#b52424", "apple_music": "#595959"}
	pixmap.fill(QColor(colors.get(platform, "#000080")))
	painter = QPainter(pixmap)
	painter.setPen(Qt.white)
	font = QFont("Comic Sans MS", 18, QFont.Bold)
	painter.setFont(font)
	label = {"spotify": "S", "youtube_music": "Y", "apple_music": "A"}.get(platform, "♪")
	painter.drawText(pixmap.rect(), Qt.AlignCenter, label)
	painter.end()
	return QIcon(pixmap)


def _settings_icon() -> QIcon:
	pixmap = QPixmap(24, 24)
	pixmap.fill(Qt.transparent)
	painter = QPainter(pixmap)
	painter.setRenderHint(QPainter.Antialiasing)
	pen = QPen(QColor("#202020"), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
	painter.setPen(pen)
	painter.drawEllipse(QRectF(7, 7, 10, 10))
	painter.drawEllipse(QRectF(10.5, 10.5, 3, 3))
	for start, end in (
		((12, 2), (12, 7)), ((12, 17), (12, 22)), ((2, 12), (7, 12)), ((17, 12), (22, 12)),
		((5, 5), (8.5, 8.5)), ((15.5, 15.5), (19, 19)), ((19, 5), (15.5, 8.5)), ((8.5, 15.5), (5, 19)),
	):
		painter.drawLine(QPointF(*start), QPointF(*end))
	painter.end()
	return QIcon(pixmap)


def _add_playlist_icon() -> QIcon:
	pixmap = QPixmap(24, 24)
	pixmap.fill(Qt.transparent)
	painter = QPainter(pixmap)
	painter.setRenderHint(QPainter.Antialiasing)
	pen = QPen(QColor("#ffffff"), 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
	painter.setPen(pen)
	painter.drawLine(QPointF(12, 4), QPointF(12, 20))
	painter.drawLine(QPointF(4, 12), QPointF(20, 12))
	painter.end()
	return QIcon(pixmap)


def _song_status_icon(kind: str) -> QIcon:
	pixmap = QPixmap(24, 24)
	pixmap.fill(Qt.transparent)
	painter = QPainter(pixmap)
	painter.setRenderHint(QPainter.Antialiasing)
	if kind == "downloaded":
		painter.setPen(QPen(QColor("#006400"), 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
		painter.drawLine(QPointF(4, 12), QPointF(10, 18))
		painter.drawLine(QPointF(10, 18), QPointF(21, 5))
	else:
		painter.setPen(QPen(QColor("#800000"), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
		painter.setBrush(QColor("#ffd34d"))
		painter.drawPolygon(QPolygonF([QPointF(12, 2), QPointF(22, 21), QPointF(2, 21)]))
		painter.setPen(QPen(QColor("#800000"), 2.5, Qt.SolidLine, Qt.RoundCap))
		painter.drawLine(QPointF(12, 8), QPointF(12, 15))
		painter.drawPoint(QPointF(12, 18))
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
		self.resize(1280, 800)
		self.library_path = settings_path().parent / "library.json"
		self.library = self._load_or_create()
		self.scan_queue: list[dict] = []
		self.scans_completed = 0
		self.scraper: SpotifyPublicScrapeDialog | None = None
		self.direct_worker: DirectLibraryScanWorker | None = None
		self.scan_dialog: LibraryScanProgressDialog | None = None
		self.scan_cancelled = False
		self.scan_warnings: list[str] = []
		self.image_manager = QNetworkAccessManager(self)
		self.image_cache: dict[str, QIcon] = {}
		self.image_waiters: dict[str, list[object]] = {}
		self.track_art_targets: dict[int, QLabel] = {}
		self.playlist_art_targets: dict[int, QLabel] = {}
		self.image_requests: set[str] = set()
		self.image_queue: list[str] = []
		self.image_active = 0
		self.image_concurrency = 2
		self.header_font_family = self._load_header_font()
		self._build_ui()
		self._refresh()

	def _load_or_create(self) -> dict:
		if self.library_path.exists():
			try:
				return load_library(self.library_path)
			except Exception as exc:
				log(f"library load failed path={self.library_path} error={exc}")
		return new_library()

	def _load_header_font(self) -> str:
		font_path = resource_base() / "fonts" / "VCR_OSD_MONO_HEADERS.ttf"
		if font_path.exists():
			font_id = QFontDatabase.addApplicationFont(str(font_path))
			if font_id != -1:
				families = QFontDatabase.applicationFontFamilies(font_id)
				if families:
					return families[0]
		return "Tahoma"

	def _build_ui(self) -> None:
		self.setFont(QFont("Comic Sans MS", 9))
		self.setStyleSheet("""
			QDialog { background: #c0c0c0; color: #101010; font-family: "Comic Sans MS"; }
			QWidget#libraryHeader {
				background: #000080; border-top: 2px solid #ffffff; border-left: 2px solid #ffffff;
				border-right: 2px solid #000000; border-bottom: 2px solid #000000;
			}
			QWidget#addPanel, QWidget#downloadPanel, QWidget#bottomPanel {
				background: #c0c0c0; border-top: 2px solid #ffffff; border-left: 2px solid #ffffff;
				border-right: 2px solid #404040; border-bottom: 2px solid #404040;
			}
			QWidget#bottomPanel { border-bottom: 4px solid #808080; }
			QPushButton, QToolButton, QComboBox {
				background: #c0c0c0;
				border-top: 2px solid #ffffff; border-left: 2px solid #ffffff;
				border-right: 2px solid #000000; border-bottom: 2px solid #000000;
				padding: 3px 7px; min-height: 19px; color: #101010;
			}
			QPushButton:pressed, QToolButton:pressed {
				background: #c0c0c0; border-top: 2px solid #000000; border-left: 2px solid #000000;
				border-right: 2px solid #ffffff; border-bottom: 2px solid #ffffff;
			}
			QPushButton:checked { background: #000080; color: #ffffff; }
			QLineEdit, QTreeWidget {
				background: #ffffff; border-top: 2px solid #404040; border-left: 2px solid #404040;
				border-right: 2px solid #ffffff; border-bottom: 2px solid #ffffff;
				selection-background-color: #000080; selection-color: #ffffff;
			}
			QHeaderView::section {
				background: #c0c0c0;
				border-top: 1px solid #ffffff; border-left: 1px solid #ffffff;
				border-right: 1px solid #000000; border-bottom: 1px solid #000000;
				padding: 4px; font-weight: 600;
			}
			QProgressBar {
				background: #ffffff; border-top: 2px solid #404040; border-left: 2px solid #404040;
				border-right: 2px solid #ffffff; border-bottom: 2px solid #ffffff;
				text-align: center; min-height: 18px;
			}
			QProgressBar::chunk { background: #000080; border-right: 2px solid #c0c0c0; }
			QMenu { background: #c0c0c0; border: 2px outset #ffffff; }
			QMenu::item:selected { background: #000080; color: #ffffff; }
		""")
		header_font = QFont(self.header_font_family, 10)
		header_font.setBold(True)
		layout = QVBoxLayout(self)
		layout.setContentsMargins(12, 12, 12, 12)
		layout.setSpacing(8)
		header = QWidget()
		header.setObjectName("libraryHeader")
		header_layout = QHBoxLayout(header)
		header_layout.setContentsMargins(8, 4, 5, 4)
		title = QLabel(f"CSVMusic  v{APP_VERSION}")
		title.setFont(QFont(self.header_font_family, 15))
		title.setStyleSheet("color: white;")
		header_layout.addWidget(title)
		header_layout.addStretch(1)
		for label, message in (
			("Settings", "Library settings controls will live here."),
			("Tutorial", "The Library Mode tutorial will open here."),
			("Info", "Library Mode supports public Spotify, Apple Music, and YouTube playlists."),
		):
			button = QPushButton(label)
			button.setFlat(True)
			button.setStyleSheet("QPushButton { color: #101010; min-width: 70px; }")
			button.clicked.connect(lambda _checked=False, text=message: self._placeholder_message(text))
			header_layout.addWidget(button)
		layout.addWidget(header)

		upper = QHBoxLayout()
		upper.setSpacing(8)
		add_panel = QWidget()
		add_panel.setObjectName("addPanel")
		add_panel.setMinimumHeight(124)
		add_layout = QVBoxLayout(add_panel)
		add_layout.setContentsMargins(12, 10, 12, 10)
		add_title = QLabel("Add to library")
		add_title.setFont(header_font)
		add_layout.addWidget(add_title)
		url_description = QLabel("Public playlists: Spotify, YouTube Music, YouTube, and Apple Music")
		url_description.setStyleSheet("color: #505050; font-size: 11px;")
		add_layout.addWidget(url_description)
		url_row = QHBoxLayout()
		self.urls_input = QLineEdit()
		self.urls_input.setPlaceholderText("Paste playlist URL")
		self.urls_input.returnPressed.connect(self._add_urls)
		add_button = QToolButton()
		add_button.setIcon(_add_playlist_icon())
		add_button.setIconSize(QSize(24, 24))
		add_button.setToolTip("Add playlist")
		add_button.setAccessibleName("Add playlist")
		add_button.setFixedSize(42, 38)
		add_button.setStyleSheet("QToolButton { background: #008000; }")
		add_button.clicked.connect(self._add_urls)
		url_row.addWidget(self.urls_input, 1)
		url_row.addWidget(add_button)
		add_layout.addLayout(url_row)
		csv_row = QHBoxLayout()
		csv_row.setSpacing(6)
		csv_label = QLabel("Import a playlist from CSV:")
		csv_label.setStyleSheet("color: #505050; font-size: 10px;")
		csv_button = QPushButton("Add CSV...")
		csv_button.setToolTip("Import a CSV playlist file")
		csv_button.setFixedHeight(26)
		csv_button.clicked.connect(lambda: self._placeholder_message("CSV library import will be connected in a later pass."))
		csv_row.addStretch(1)
		csv_row.addWidget(csv_label)
		csv_row.addWidget(csv_button)
		add_layout.addLayout(csv_row)
		path_row = QHBoxLayout()
		self.path_label = QLabel(str(self.library_path))
		self.path_label.setStyleSheet("color: #505050; font-size: 10px;")
		self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
		open_button = QPushButton("Open Library...")
		open_button.clicked.connect(self._open_library)
		save_as_button = QPushButton("Save As...")
		save_as_button.clicked.connect(self._save_as)
		path_row.addWidget(QLabel("Library:"))
		path_row.addWidget(self.path_label, 1)
		path_row.addWidget(open_button)
		path_row.addWidget(save_as_button)
		path_widget = QWidget()
		path_widget.setLayout(path_row)
		path_widget.setVisible(False)
		add_layout.addWidget(path_widget)
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
		output_widget = QWidget()
		output_widget.setLayout(output_row)
		output_widget.setVisible(False)
		add_layout.addWidget(output_widget)
		add_layout.addStretch(1)
		upper.addWidget(add_panel, 3)

		download_panel = QWidget()
		download_panel.setObjectName("downloadPanel")
		download_panel.setMinimumHeight(124)
		download_layout = QVBoxLayout(download_panel)
		download_layout.setContentsMargins(12, 10, 12, 10)
		download_title = QLabel("Download activity")
		download_title.setFont(header_font)
		download_layout.addWidget(download_title)
		self.download_progress = QProgressBar()
		self.download_progress.setRange(0, 100)
		self.download_progress.setValue(0)
		self.download_progress.setFormat("No download running")
		download_layout.addWidget(self.download_progress)
		self.download_activity = QLabel("Ready")
		self.download_activity.setStyleSheet("font-weight: bold; color: #000080;")
		download_layout.addWidget(self.download_activity)
		self.download_detail = QLabel("yt-dlp and FFmpeg activity, current track, and errors will appear here.")
		self.download_detail.setWordWrap(True)
		self.download_detail.setStyleSheet("color: #404040; font-size: 11px;")
		download_layout.addWidget(self.download_detail)
		download_layout.addStretch(1)
		upper.addWidget(download_panel, 5)
		layout.addLayout(upper)

		splitter = QSplitter()
		left = QWidget()
		left.setObjectName("bottomPanel")
		left_layout = QVBoxLayout(left)
		left_layout.setContentsMargins(8, 7, 8, 8)
		playlist_heading = QHBoxLayout()
		playlist_heading_label = QLabel("Playlists")
		playlist_heading_label.setFont(header_font)
		playlist_heading.addWidget(playlist_heading_label)
		playlist_heading.addStretch(1)
		rescan_all = QPushButton("Rescan All")
		rescan_all.clicked.connect(self._rescan_all)
		playlist_heading.addWidget(rescan_all)
		left_layout.addLayout(playlist_heading)
		self.playlist_tree = QTreeWidget()
		self.playlist_tree.setHeaderLabels(["Playlists"])
		self.playlist_tree.setHeaderHidden(True)
		self.playlist_tree.setRootIsDecorated(False)
		self.playlist_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
		self.playlist_tree.setIconSize(QSize(48, 48))
		self.playlist_tree.itemSelectionChanged.connect(self._show_tracks)
		self.playlist_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
		left_layout.addWidget(self.playlist_tree)
		right = QWidget()
		right.setObjectName("bottomPanel")
		right_layout = QVBoxLayout(right)
		right_layout.setContentsMargins(8, 7, 8, 8)
		right_actions = QHBoxLayout()
		songs_heading = QLabel("Songs")
		songs_heading.setFont(header_font)
		right_actions.addWidget(songs_heading)
		right_actions.addStretch(1)
		right_layout.addLayout(right_actions)
		self.track_tree = QTreeWidget()
		self.track_tree.setHeaderLabels(["Songs"])
		self.track_tree.setHeaderHidden(True)
		self.track_tree.setRootIsDecorated(False)
		self.track_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
		self.track_tree.setIconSize(QSize(42, 42))
		self.track_art_timer = QTimer(self)
		self.track_art_timer.setSingleShot(True)
		self.track_art_timer.setInterval(80)
		self.track_art_timer.timeout.connect(self._load_visible_track_images)
		self.track_tree.verticalScrollBar().valueChanged.connect(lambda _value: self.track_art_timer.start())
		self.track_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
		right_layout.addWidget(self.track_tree)
		splitter.addWidget(left)
		splitter.addWidget(right)
		splitter.setSizes([480, 800])
		layout.addWidget(splitter, 1)
		self.status = QLabel()
		self.status.setWordWrap(True)
		layout.addWidget(self.status)
		body_font = QFont("Comic Sans MS", 9)
		for widget in self.findChildren(QWidget):
			widget.setFont(body_font)
		title.setFont(QFont(self.header_font_family, 15))
		for heading in (add_title, download_title, playlist_heading_label, songs_heading):
			font = QFont(self.header_font_family, 10)
			font.setBold(True)
			heading.setFont(font)
		self.playlist_tree.header().setFont(QFont(self.header_font_family, 9))

	def _placeholder_message(self, message: str) -> None:
		self.status.setText(message)

	def showEvent(self, event) -> None:
		super().showEvent(event)
		screen = self.screen()
		if screen is None:
			return
		available = screen.availableGeometry()
		margin = 16
		width = max(1, min(self.width(), available.width() - (margin * 2)))
		height = max(1, min(self.height(), available.height() - (margin * 2)))
		self.setMaximumSize(max(1, available.width() - margin), max(1, available.height() - margin))
		self.resize(width, height)
		x = available.x() + max(0, (available.width() - width) // 2)
		y = available.y() + max(0, (available.height() - height) // 2)
		self.move(x, y)

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
		value = self.urls_input.text().strip()
		if not value:
			self.status.setText("Paste a public playlist URL first.")
			return
		before = len(self.library.get("playlists", []))
		values = [value]
		added, errors = add_playlist_urls(self.library, values)
		self._save()
		self.urls_input.clear()
		self._refresh()
		if errors:
			self.status.setText(errors[0])
		elif not added and len(self.library.get("playlists", [])) == before:
			self.status.setText("That playlist is already in this library.")
		else:
			self.status.setText("Playlist added. Use its refresh button to load tracks and cover art.")

	def _selected_ids(self) -> set[str]:
		return {str(item.data(0, Qt.UserRole)) for item in self.playlist_tree.selectedItems()}

	def _rescan_all(self) -> None:
		self._begin_scan(list(self.library.get("playlists", [])))

	def _rescan_playlist(self, playlist_id: str) -> None:
		playlist = playlist_by_id(self.library, playlist_id)
		if playlist:
			self._begin_scan([playlist])

	def _begin_scan(self, playlists: list[dict]) -> None:
		if self.scraper is not None or self.direct_worker is not None:
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
		if playlist.get("platform") in ("youtube_music", "apple_music"):
			platform = str(playlist["platform"])
			self.direct_worker = DirectLibraryScanWorker(playlist["url"], platform, self)
			self.direct_worker.finished_scan.connect(self._scan_finished)
			self.direct_worker.start()
			if self.scan_dialog:
				self.scan_dialog.setRange(0, 0)
				self.scan_dialog.setLabelText(
					f"Playlist {self.scans_completed + 1}: {playlist.get('name') or playlist['id']}\n"
					f"Loading {'Apple Music' if platform == 'apple_music' else 'YouTube Music'} metadata..."
				)
			return
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
		if data.get("error"):
			self.scan_warnings.append(str(data["error"]))
		playlist_id = str(data.get("id") or "")
		if not self.scan_cancelled and playlist_id and data.get("tracks"):
			message = str(data.get("message") or "")
			warning = None if data.get("complete") else message
			if warning:
				self.scan_warnings.append(f"{data.get('name') or playlist_id}: {warning}")
			merge_playlist_scan(
				self.library,
				f"{data.get('platform')}:{playlist_id}" if data.get("platform") in ("youtube_music", "apple_music") else playlist_id,
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
		if self.direct_worker:
			self.direct_worker.deleteLater()
			self.direct_worker = None
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
		self.library["playlists"] = [
			item for item in self.library.get("playlists", [])
			if f"{item.get('platform') or 'spotify'}:{item.get('id')}" != playlist_id and item.get("id") != playlist_id
		]
		self._save()
		self._refresh()

	@staticmethod
	def _playlist_error_count(playlist: dict) -> int:
		return sum(
			1 for track in playlist.get("tracks", [])
			if track.get("download_error") or track.get("last_error") or track.get("error")
		)

	def _show_playlist_errors(self, playlist: dict) -> None:
		lines = []
		for track in playlist.get("tracks", []):
			error = track.get("download_error") or track.get("last_error") or track.get("error")
			if error:
				lines.append(f"{track.get('title') or 'Unknown song'} - {track.get('artists') or 'Unknown artist'}\n{error}")
		if not lines:
			QMessageBox.information(self, "Playlist Errors", "No saved download errors were found for this playlist.")
			return
		QMessageBox.warning(self, "Playlist Download Errors", "\n\n".join(lines))

	def _show_track_error(self, track: dict) -> None:
		error = track.get("download_error") or track.get("last_error") or track.get("error")
		when = str(track.get("last_error_at") or "Unknown time").replace("T", " ")
		QMessageBox.warning(
			self,
			"Song Download Error",
			f"{track.get('title') or 'Unknown song'} - {track.get('artists') or 'Unknown artist'}\n\n"
			f"Last failure: {when}\n\n{error or 'No saved error details are available.'}",
		)

	def _refresh(self, *_args) -> None:
		output = self.library.get("output_dir") or ""
		status = library_status(self.library, output, self.format_combo.currentText()) if hasattr(self, "format_combo") else {"playlists": {}, "totals": {}}
		selected = self._selected_ids() if hasattr(self, "playlist_tree") else set()
		self.playlist_tree.clear()
		self.playlist_art_targets.clear()
		playlists = list(self.library.get("playlists", []))
		playlists.sort(
			key=lambda playlist: (
				self._playlist_error_count(playlist),
				status.get("playlists", {}).get(f"{playlist.get('platform') or 'spotify'}:{playlist.get('id')}", {}).get("missing", 0),
			),
			reverse=True,
		)
		for playlist_index, playlist in enumerate(playlists):
			key = f"{playlist.get('platform') or 'spotify'}:{playlist.get('id')}"
			counts = status.get("playlists", {}).get(key, {})
			track_count = len(playlist.get("tracks", []))
			total = playlist.get("reported_total") or track_count
			last_scan = str(playlist.get("last_scanned_at") or "Never").replace("T", " ")[:19]
			name = playlist.get("name") or (
				"Unscanned Apple Music Playlist" if playlist.get("platform") == "apple_music"
				else "Unscanned YouTube Music Playlist" if playlist.get("platform") == "youtube_music"
				else "Unscanned Spotify Playlist"
			)
			item = QTreeWidgetItem([""])
			item.setData(0, Qt.UserRole, key)
			item.setToolTip(0, f"Last scanned: {last_scan}")
			item.setSizeHint(0, QSize(0, 68))
			error_count = self._playlist_error_count(playlist)
			missing_count = int(counts.get("missing", 0) or 0)
			if error_count:
				row_color = QColor("#dda0a0")
			elif missing_count:
				row_color = QColor("#e7bcbc")
			else:
				row_color = QColor("#c8ddc8")
			self.playlist_tree.addTopLevelItem(item)
			card = ClickableFrame()
			card.setObjectName("playlistCard")
			card.setFont(QFont("Comic Sans MS", 9))
			card.setStyleSheet(
				f"#playlistCard {{ background: {row_color.name()}; border-top: 2px solid #ffffff; border-left: 2px solid #ffffff; "
				"border-right: 2px solid #404040; border-bottom: 2px solid #404040; }"
			)
			card.clicked.connect(lambda target=item: self.playlist_tree.setCurrentItem(target))
			card_layout = QHBoxLayout(card)
			card_layout.setContentsMargins(6, 4, 6, 4)
			card_layout.setSpacing(7)
			art = QLabel()
			art.setFixedSize(52, 52)
			art.setAlignment(Qt.AlignCenter)
			art.setPixmap(_source_placeholder_icon(str(playlist.get("platform") or "spotify")).pixmap(52, 52))
			art.setStyleSheet("background: #606060; border: 1px inset #404040;")
			card_layout.addWidget(art)
			name_label = QLabel(str(name))
			name_label.setWordWrap(True)
			name_label.setFont(QFont("Comic Sans MS", 10, QFont.Bold))
			card_layout.addWidget(name_label, 1)
			status_layout = QVBoxLayout()
			status_layout.setSpacing(0)
			status_layout.setAlignment(Qt.AlignVCenter)
			tracks_label = QLabel(f"{track_count}/{total} tracks")
			status_labels = [tracks_label]
			missing_label = QLabel(f"{missing_count} missing") if missing_count else None
			error_label = QPushButton(f"{error_count} errors") if error_count else None
			if missing_label:
				status_labels.append(missing_label)
			if error_label:
				status_labels.append(error_label)
			for status_label in status_labels:
				status_label.setFont(QFont("Comic Sans MS", 9))
				status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
				status_label.setMinimumWidth(112)
				status_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
			for status_label in status_labels:
				status_layout.addWidget(status_label)
			if error_count:
				error_label.setToolTip("View playlist download errors")
				error_label.setFixedHeight(24)
				error_label.clicked.connect(lambda _checked=False, source=playlist: self._show_playlist_errors(source))
			card_layout.addLayout(status_layout)
			playlist_status = QLabel()
			playlist_status.setFixedSize(26, 26)
			playlist_status.setAlignment(Qt.AlignCenter)
			playlist_status.setPixmap(_song_status_icon("warning" if error_count or missing_count else "downloaded").pixmap(24, 24))
			playlist_status.setToolTip(
				"One or more songs have download errors" if error_count
				else f"{missing_count} song(s) have no downloaded file" if missing_count
				else "Every song has a downloaded file"
			)
			card_layout.addWidget(playlist_status)
			refresh_button = QToolButton()
			refresh_button.setIcon(_playlist_action_icon("refresh"))
			refresh_button.setIconSize(QSize(20, 20))
			refresh_button.setToolTip("Rescan this playlist")
			refresh_button.setAccessibleName("Rescan playlist")
			refresh_button.setFixedSize(32, 32)
			refresh_button.setStyleSheet("QToolButton { color: white; background: #008000; }")
			refresh_button.clicked.connect(lambda _checked=False, playlist_id=key: self._rescan_playlist(str(playlist_id)))
			delete_button = QToolButton()
			delete_button.setIcon(_playlist_action_icon("delete"))
			delete_button.setIconSize(QSize(20, 20))
			delete_button.setToolTip("Remove this playlist")
			delete_button.setAccessibleName("Delete playlist")
			delete_button.setFixedSize(32, 32)
			delete_button.setStyleSheet("QToolButton { color: white; background: #c00000; }")
			delete_button.clicked.connect(lambda _checked=False, playlist_id=key: self._remove_playlist(str(playlist_id)))
			card_layout.addSpacing(12)
			card_layout.addWidget(refresh_button)
			card_layout.addSpacing(4)
			card_layout.addWidget(delete_button)
			self.playlist_tree.setItemWidget(item, 0, card)
			self.playlist_art_targets[playlist_index] = art
			self._request_image(str(playlist.get("cover_url") or ""), art)
			if key in selected:
				item.setSelected(True)
		if not self.playlist_tree.selectedItems() and self.playlist_tree.topLevelItemCount():
			self.playlist_tree.topLevelItem(0).setSelected(True)
		self._show_tracks()
		totals = status.get("totals", {})
		if totals:
			self.status.setText(
				f"Tracks {totals.get('enabled', 0)} | Downloaded {totals.get('downloaded', 0)} | "
				f"Missing {totals.get('missing', 0)}"
			)

	def _show_tracks(self) -> None:
		ids = self._selected_ids()
		self.track_tree.blockSignals(True)
		self.track_tree.clear()
		self.track_art_targets.clear()
		output = pathlib.Path(self.library.get("output_dir") or "")
		fmt = self.format_combo.currentText()
		for playlist_id in ids:
			playlist = playlist_by_id(self.library, playlist_id)
			if not playlist:
				continue
			indexed_tracks = list(enumerate(playlist.get("tracks", [])))
			def issue_order(entry: tuple[int, dict]) -> int:
				_original_index, source_track = entry
				if source_track.get("download_error") or source_track.get("last_error") or source_track.get("error"):
					return 0
				probe = dict(source_track)
				probe["playlist"] = playlist.get("name") or "Playlist"
				return 2 if expected_track_path(probe, output, fmt).exists() else 1
			indexed_tracks.sort(key=issue_order)
			for display_index, (index, track) in enumerate(indexed_tracks):
				candidate = dict(track)
				candidate["playlist"] = playlist.get("name") or "Playlist"
				has_error = bool(track.get("download_error") or track.get("last_error") or track.get("error"))
				file_exists = expected_track_path(candidate, output, fmt).exists()
				if has_error:
					state = "Error"
				elif track.get("force_redownload"):
					state = "Redownload"
				elif file_exists:
					state = "Downloaded"
				else:
					state = "Missing"
				downloaded_title = str(track.get("downloaded_video_title") or "").strip() if file_exists else ""
				downloaded_publisher = str(track.get("downloaded_video_publisher") or "").strip() if file_exists else ""
				youtube_info = (
					f'Downloaded: "{downloaded_title}" - "{downloaded_publisher}"' if downloaded_title and downloaded_publisher
					else f'Downloaded: "{downloaded_title}"' if downloaded_title
					else ""
				)
				item = QTreeWidgetItem([""])
				item.setData(0, Qt.UserRole, (playlist_id, index))
				item.setSizeHint(0, QSize(0, 88))
				item.setData(0, Qt.UserRole + 1, str(track.get("cover_url") or ""))
				self.track_tree.addTopLevelItem(item)
				card = QFrame()
				card.setFont(QFont("Comic Sans MS", 9))
				card.setObjectName("songCard")
				if state == "Error":
					shade = "#dda0a0"
				elif not file_exists:
					shade = "#e7bcbc"
				else:
					shade = "#d4d0c8" if display_index % 2 == 0 else "#c0c0c0"
				card.setStyleSheet(
					f"#songCard {{ background: {shade}; border-top: 2px solid #ffffff; border-left: 2px solid #ffffff; "
					"border-right: 2px solid #404040; border-bottom: 2px solid #404040; }}"
				)
				card_layout = QHBoxLayout(card)
				card_layout.setContentsMargins(8, 6, 8, 6)
				card_layout.setSpacing(9)
				position = QLabel(str(track.get("track_no") or (index + 1)))
				position.setFont(QFont("Comic Sans MS", 10, QFont.Bold))
				position.setAlignment(Qt.AlignCenter)
				position.setFixedWidth(30)
				position.setStyleSheet("color: #303030;")
				card_layout.addWidget(position)
				art = QLabel("♪")
				art.setAlignment(Qt.AlignCenter)
				art.setFixedSize(58, 58)
				art.setStyleSheet("background: #3f3f3f; color: white; border: 1px inset #777; font-size: 20px;")
				art.setScaledContents(False)
				card_layout.addWidget(art)
				text_column = QVBoxLayout()
				text_column.setSpacing(1)
				text_column.setAlignment(Qt.AlignVCenter)
				album = str(track.get("album") or "").strip()
				primary = QLabel(f"{track.get('title') or ''} - {track.get('artists') or ''}")
				primary.setFont(QFont("Comic Sans MS", 10, QFont.Bold))
				primary.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
				primary.setTextInteractionFlags(Qt.TextSelectableByMouse)
				album_label = QLabel(album)
				album_label.setFont(QFont("Comic Sans MS", 9))
				album_label.setStyleSheet("color: #303030;")
				album_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
				album_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
				download = QLabel(youtube_info)
				download.setFont(QFont("Comic Sans MS", 8))
				download.setStyleSheet("color: #555555;")
				download.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
				download.setTextInteractionFlags(Qt.TextSelectableByMouse)
				text_column.addWidget(primary)
				text_column.addWidget(album_label)
				text_column.addWidget(download)
				card_layout.addLayout(text_column, 1)
				icon_kind = "downloaded" if file_exists and not has_error else "warning"
				status_icon = QLabel()
				status_icon.setFixedSize(26, 26)
				status_icon.setAlignment(Qt.AlignCenter)
				status_icon.setPixmap(_song_status_icon(icon_kind).pixmap(24, 24))
				status_icon.setToolTip("Last download failed" if has_error else "Audio file found" if icon_kind == "downloaded" else "Audio file is missing")
				card_layout.addWidget(status_icon)
				if has_error:
					state_label = QPushButton("Error")
					state_label.setToolTip("View the saved download error")
					state_label.clicked.connect(lambda _checked=False, source=track: self._show_track_error(source))
				else:
					state_label = QLabel(state)
					state_label.setAlignment(Qt.AlignCenter)
					state_label.setStyleSheet("font-weight: 600; color: #303030;")
				state_label.setMinimumWidth(72)
				card_layout.addWidget(state_label)
				settings_button = QToolButton()
				settings_button.setIcon(_settings_icon())
				settings_button.setIconSize(QSize(24, 24))
				settings_button.setToolTip("Choose an alternative YouTube match")
				settings_button.setAccessibleName("Track alternatives")
				settings_button.setFixedSize(42, 42)
				settings_button.clicked.connect(lambda _checked=False, target=item: self._open_track_settings(target))
				card_layout.addWidget(settings_button)
				self.track_tree.setItemWidget(item, 0, card)
				self.track_art_targets[self.track_tree.indexOfTopLevelItem(item)] = art
		self.track_tree.blockSignals(False)
		self.track_art_timer.start(0)

	def _open_track_settings(self, item: QTreeWidgetItem) -> None:
		self.track_tree.clearSelection()
		item.setSelected(True)
		self._set_youtube_match()

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
			target = self.track_art_targets.get(index)
			if target:
				self._request_image(str(item.data(0, Qt.UserRole + 1) or ""), target, priority=True)

	def _request_image(self, url: str, item: object, *, priority: bool = False) -> None:
		if not url.startswith(("https://", "http://")):
			return
		cached = self.image_cache.get(url)
		if cached is not None:
			self._apply_cached_image(item, cached)
			return
		self.image_waiters.setdefault(url, []).append(item)
		if url in self.image_requests or url in self.image_queue:
			return
		if priority:
			self.image_queue.insert(0, url)
		else:
			self.image_queue.append(url)
		self._pump_image_queue()

	def _apply_cached_image(self, target: object, icon: QIcon) -> None:
		if isinstance(target, QLabel):
			pixmap = icon.pixmap(target.width(), target.height())
			target.setPixmap(pixmap.scaled(target.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
		elif isinstance(target, QTreeWidgetItem):
			target.setIcon(0, icon)

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
					self._apply_cached_image(item, icon)
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
		if self.direct_worker and self.direct_worker.isRunning():
			self.scan_cancelled = True
			self.scan_queue.clear()
			self.status.setText("Finishing the current playlist metadata request before closing...")
			event.ignore()
			return
		if self.scraper and self.scraper.running:
			self.scraper._finish("Library scan cancelled because Library Mode was closed.")
		if self.scan_dialog:
			self.scan_dialog.close()
		self._save()
		super().closeEvent(event)
