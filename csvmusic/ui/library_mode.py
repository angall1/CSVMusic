# tabs only
import pathlib
import random
import shutil
import datetime
import html

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QThread, QTimer, QUrl, QUrlQuery, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (
	QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
	QGridLayout, QHBoxLayout, QHeaderView, QFrame, QInputDialog, QLabel, QLineEdit, QListWidget,
	QListWidgetItem, QMessageBox, QPushButton, QSizePolicy, QSlider, QSplitter, QProgressBar,
	QPlainTextEdit, QScrollArea, QTabWidget, QTextBrowser, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from csvmusic.core.library import (
	add_playlist_urls, edit_library_track, enabled_tracks, export_csv, library_status, library_track_path, load_library,
	import_csv_playlist, merge_playlist_scan, new_library, playlist_by_id, record_library_download_result,
	rename_library_playlist, save_library,
)
from csvmusic.core.log import log
from csvmusic.core.settings import load_settings, save_settings, settings_path
from csvmusic.core.paths import resource_base
from csvmusic.core.track_output import expected_track_path
from csvmusic.core.downloader import sanitize_name, tag_file, write_m3u, youtube_batch_mitigation, youtube_risk_acknowledgement
from csvmusic.core.youtube_url import YouTubeVideoUrlError, parse_youtube_video_id
from csvmusic.ui.spotify_public_scrape import SpotifyPublicScrapeDialog
from csvmusic.ui.device_sync import DeviceSyncDialog
from csvmusic.ui.workers import AlternativesFetchWorker, PipelineWorker, SingleDownloadWorker
from csvmusic.core.youtube_music_import import fetch_youtube_music_source
from csvmusic.core.apple_music_import import fetch_apple_music_source
from csvmusic.core.spotify_import import fetch_spotify_playlist
from csvmusic.core.deezer_import import fetch_deezer_source
from csvmusic.core.amazon_music_import import fetch_amazon_music_source
from csvmusic.version import APP_VERSION


class DirectLibraryScanWorker(QThread):
	finished_scan = Signal(object)

	def __init__(self, url: str, platform: str, parent=None, *, source_id: str = ""):
		super().__init__(parent)
		self.url = url
		self.platform = platform
		self.source_id = source_id

	def run(self) -> None:
		try:
			if self.platform == "csv":
				from csvmusic.core.csv_import import load_csv, tracks_from_csv
				tracks = tracks_from_csv(load_csv(self.url))
				if not tracks:
					raise ValueError("The CSV did not contain any usable tracks.")
				self.finished_scan.emit({
					"id": self.source_id,
					"name": tracks[0].get("playlist") or pathlib.Path(self.url).stem,
					"tracks": tracks, "reported_total": len(tracks), "message": "",
					"complete": bool(tracks), "platform": "csv", "cover_url": None, "direct": True,
				})
				return
			if self.platform == "apple_music":
				source = fetch_apple_music_source(self.url)
			elif self.platform == "spotify_album":
				source = fetch_spotify_playlist(self.url)
			elif self.platform == "deezer":
				source = fetch_deezer_source(self.url)
			elif self.platform == "amazon_music":
				source = fetch_amazon_music_source(self.url)
			else:
				source = fetch_youtube_music_source(self.url)
			self.finished_scan.emit({
				"id": source.id, "name": source.name, "tracks": source.tracks,
				"reported_total": source.total_count, "message": source.warning or "",
				"complete": not bool(source.warning), "platform": "spotify" if self.platform == "spotify_album" else self.platform,
				"cover_url": getattr(source, "cover_url", None), "direct": True,
			})
		except Exception as exc:
			self.finished_scan.emit({"error": str(exc), "complete": False, "platform": self.platform, "direct": True})


class ClickableFrame(QFrame):
	clicked = Signal()

	def mousePressEvent(self, event) -> None:
		self.clicked.emit()
		super().mousePressEvent(event)

class EditablePlaylistTitle(QLabel):
	double_clicked = Signal()

	def __init__(self, text: str = "", parent=None):
		self._full_text = str(text)
		super().__init__("", parent)
		self.setMinimumWidth(0)
		self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
		self._update_tooltip()
		self._update_elided_text()

	def setText(self, text: str) -> None:
		self._full_text = str(text)
		self._update_tooltip()
		self._update_elided_text()

	def _update_tooltip(self) -> None:
		self.setToolTip(f"{self._full_text}\n\nDouble-click to rename this playlist and its output folder")

	def resizeEvent(self, event) -> None:
		super().resizeEvent(event)
		self._update_elided_text()

	def _update_elided_text(self) -> None:
		available = max(20, self.width() - 4)
		metrics = self.fontMetrics()
		words = self._full_text.split()
		lines: list[str] = []
		while words and len(lines) < 3:
			if len(lines) == 2:
				lines.append(metrics.elidedText(" ".join(words), Qt.ElideRight, available))
				break
			line_words: list[str] = []
			while words:
				candidate = " ".join((*line_words, words[0]))
				if line_words and metrics.horizontalAdvance(candidate) > available:
					break
				line_words.append(words.pop(0))
				if metrics.horizontalAdvance(candidate) > available:
					break
			line = " ".join(line_words)
			lines.append(metrics.elidedText(line, Qt.ElideRight, available))
		QLabel.setText(self, "\n".join(lines))

	def mouseDoubleClickEvent(self, event) -> None:
		if event.button() == Qt.LeftButton:
			self.double_clicked.emit()
			event.accept()
			return
		super().mouseDoubleClickEvent(event)


class EditableTrackText(QLabel):
	double_clicked = Signal()

	def mouseDoubleClickEvent(self, event) -> None:
		if event.button() == Qt.LeftButton:
			self.double_clicked.emit()
			event.accept()
			return
		super().mouseDoubleClickEvent(event)


def _playlist_action_icon(kind: str) -> QIcon:
	pixmap = QPixmap(28, 28)
	pixmap.fill(Qt.transparent)
	painter = QPainter(pixmap)
	painter.setRenderHint(QPainter.Antialiasing)
	painter.scale(1.35, 1.35)
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


def _rescan_all_icon() -> QIcon:
	pixmap = QPixmap(34, 26)
	pixmap.fill(Qt.transparent)
	painter = QPainter(pixmap)
	painter.setRenderHint(QPainter.Antialiasing)
	pen = QPen(Qt.white, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
	painter.setPen(pen)
	painter.drawArc(QRectF(2.5, 3.5, 18, 18), 35 * 16, 285 * 16)
	painter.setBrush(Qt.white)
	painter.drawPolygon(QPolygonF([QPointF(18.5, 2.5), QPointF(19.5, 9), QPointF(13.5, 6.5)]))
	painter.setBrush(Qt.NoBrush)
	for y in (7, 13, 19):
		painter.drawEllipse(QRectF(24, y - 1, 2, 2))
		painter.drawLine(QPointF(28, y), QPointF(33, y))
	painter.end()
	return QIcon(pixmap)


def _stop_icon() -> QIcon:
	pixmap = QPixmap(24, 24)
	pixmap.fill(Qt.transparent)
	painter = QPainter(pixmap)
	painter.setRenderHint(QPainter.Antialiasing)
	painter.setPen(QPen(QColor("#ffffff"), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
	painter.setBrush(QColor("#d00000"))
	painter.drawPolygon(QPolygonF([
		QPointF(8, 2), QPointF(16, 2), QPointF(22, 8), QPointF(22, 16),
		QPointF(16, 22), QPointF(8, 22), QPointF(2, 16), QPointF(2, 8),
	]))
	painter.setPen(QPen(Qt.white, 3, Qt.SolidLine, Qt.RoundCap))
	painter.drawLine(QPointF(7, 12), QPointF(17, 12))
	painter.end()
	return QIcon(pixmap)


def _paper_icon() -> QIcon:
	pixmap = QPixmap(24, 24)
	pixmap.fill(Qt.transparent)
	painter = QPainter(pixmap)
	painter.setRenderHint(QPainter.Antialiasing)
	painter.setPen(QPen(QColor("#303030"), 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
	painter.setBrush(QColor("#fffdf0"))
	painter.drawPolygon(QPolygonF([
		QPointF(4, 2), QPointF(15, 2), QPointF(21, 8), QPointF(21, 22), QPointF(4, 22),
	]))
	painter.setBrush(QColor("#d8d8c8"))
	painter.drawPolygon(QPolygonF([QPointF(15, 2), QPointF(15, 8), QPointF(21, 8)]))
	for y in (11, 15, 19):
		painter.drawLine(QPointF(8, y), QPointF(17, y))
	painter.end()
	return QIcon(pixmap)


def _download_icon() -> QIcon:
	pixmap = QPixmap(24, 24)
	pixmap.fill(Qt.transparent)
	painter = QPainter(pixmap)
	painter.setRenderHint(QPainter.Antialiasing)
	painter.setPen(QPen(Qt.white, 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
	painter.drawLine(QPointF(12, 3), QPointF(12, 15))
	painter.drawLine(QPointF(6, 10), QPointF(12, 16))
	painter.drawLine(QPointF(18, 10), QPointF(12, 16))
	painter.drawLine(QPointF(5, 21), QPointF(19, 21))
	painter.end()
	return QIcon(pixmap)


def _clear_search_icon() -> QIcon:
	pixmap = QPixmap(20, 20)
	pixmap.fill(Qt.transparent)
	painter = QPainter(pixmap)
	painter.setRenderHint(QPainter.Antialiasing)
	painter.setPen(QPen(QColor("#ffffff"), 2.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
	painter.drawLine(QPointF(5, 5), QPointF(15, 15))
	painter.drawLine(QPointF(15, 5), QPointF(5, 15))
	painter.end()
	return QIcon(pixmap)


def _header_button_icon(kind: str) -> QIcon:
	pixmap = QPixmap(24, 24)
	pixmap.fill(Qt.transparent)
	painter = QPainter(pixmap)
	painter.setRenderHint(QPainter.Antialiasing)
	pen = QPen(QColor("#202020"), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
	painter.setPen(pen)
	painter.setBrush(Qt.NoBrush)
	if kind == "equalizer":
		for x, knob_y in ((5, 7), (11, 14), (17, 9)):
			painter.drawLine(QPointF(x, 3), QPointF(x, 19))
			painter.setBrush(QColor("#e8e8e8"))
			painter.drawRoundedRect(QRectF(x - 2.5, knob_y - 2, 5, 4), 1, 1)
			painter.setBrush(Qt.NoBrush)
	elif kind == "sync":
		# Two clean chasing arrows remain recognizable at toolbar scale and
		# avoid the overlapping player/arrow silhouette used previously.
		painter.drawArc(QRectF(3.5, 3.5, 17, 17), 35 * 16, 125 * 16)
		painter.drawArc(QRectF(3.5, 3.5, 17, 17), 215 * 16, 125 * 16)
		painter.setBrush(QColor("#202020"))
		painter.drawPolygon(QPolygonF([QPointF(20.5, 4), QPointF(20, 10), QPointF(15, 6.5)]))
		painter.drawPolygon(QPolygonF([QPointF(3.5, 20), QPointF(4, 14), QPointF(9, 17.5)]))
	elif kind == "settings":
		painter.drawEllipse(QRectF(5, 5, 12, 12))
		painter.drawEllipse(QRectF(9, 9, 4, 4))
		for start, end in (((11, 2), (11, 5)), ((11, 17), (11, 20)), ((2, 11), (5, 11)), ((17, 11), (20, 11))):
			painter.drawLine(QPointF(*start), QPointF(*end))
	elif kind == "tutorial":
		painter.setBrush(QColor("#fffbea"))
		painter.drawPolygon(QPolygonF([QPointF(2, 4), QPointF(10.5, 6), QPointF(10.5, 19), QPointF(2, 17)]))
		painter.drawPolygon(QPolygonF([QPointF(11.5, 6), QPointF(20, 4), QPointF(20, 17), QPointF(11.5, 19)]))
		painter.drawLine(QPointF(11, 6), QPointF(11, 19))
	elif kind == "info":
		painter.setBrush(QColor("#f4f4f4"))
		painter.drawEllipse(QRectF(2.5, 2.5, 17, 17))
		painter.setFont(QFont("Times New Roman", 13, QFont.Bold))
		painter.drawText(pixmap.rect(), Qt.AlignCenter, "i")
	else:
		# Open door with a separate exit arrow for Legacy Mode.
		painter.setBrush(QColor("#f3f3f3"))
		painter.drawRect(QRectF(2.5, 2.5, 12, 19))
		painter.drawLine(QPointF(6, 6), QPointF(11, 6))
		painter.drawPoint(QPointF(11.5, 12))
		painter.drawLine(QPointF(9, 16.5), QPointF(21, 16.5))
		painter.drawLine(QPointF(17, 12.5), QPointF(21, 16.5))
		painter.drawLine(QPointF(17, 20.5), QPointF(21, 16.5))
	painter.end()
	return QIcon(pixmap)


def _source_placeholder_icon(platform: str) -> QIcon:
	pixmap = QPixmap(48, 48)
	colors = {"spotify": "#1b8f48", "youtube_music": "#b52424", "apple_music": "#595959", "deezer": "#6b35b5", "amazon_music": "#1678a5", "csv": "#000080"}
	pixmap.fill(QColor(colors.get(platform, "#000080")))
	painter = QPainter(pixmap)
	painter.setPen(Qt.white)
	font = QFont("Comic Sans MS", 18, QFont.Bold)
	painter.setFont(font)
	label = {"spotify": "S", "youtube_music": "Y", "apple_music": "A", "deezer": "D", "amazon_music": "A", "csv": "C"}.get(platform, "♪")
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


def _folder_icon() -> QIcon:
	pixmap = QPixmap(32, 28)
	pixmap.fill(Qt.transparent)
	painter = QPainter(pixmap)
	painter.setRenderHint(QPainter.Antialiasing, True)
	outline = QPen(QColor("#362800"), 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
	painter.setPen(outline)
	# Dark rear pocket and a large tab make the silhouette readable at toolbar size.
	painter.setBrush(QColor("#b88716"))
	painter.drawPolygon(QPolygonF([
		QPointF(2.5, 6.5), QPointF(2.5, 3.5), QPointF(13, 3.5), QPointF(17, 7.5),
		QPointF(29.5, 7.5), QPointF(29.5, 23.5), QPointF(2.5, 23.5),
	]))
	# A pale sheet peeking out reinforces that the folder is open.
	painter.setBrush(QColor("#fff8d0"))
	painter.setPen(QPen(QColor("#756a42"), 1.2))
	painter.drawPolygon(QPolygonF([
		QPointF(6, 8), QPointF(26, 8), QPointF(25, 20), QPointF(5, 20),
	]))
	# Bright angled front flap gives the icon its open, skeuomorphic shape.
	painter.setBrush(QColor("#f2c94c"))
	painter.setPen(outline)
	painter.drawPolygon(QPolygonF([
		QPointF(2.5, 11), QPointF(30, 11), QPointF(26.5, 25), QPointF(5, 25),
	]))
	painter.setPen(QPen(QColor("#fff0a0"), 1.5, Qt.SolidLine, Qt.RoundCap))
	painter.drawLine(QPointF(5, 13), QPointF(27.5, 13))
	painter.setPen(QPen(QColor("#8f670d"), 1.2, Qt.SolidLine, Qt.RoundCap))
	painter.drawLine(QPointF(6, 22.5), QPointF(25, 22.5))
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
		self.resize(560, 350)
		layout = QVBoxLayout(self)
		layout.setContentsMargins(12, 10, 12, 10)
		layout.setSpacing(7)
		self.label = QLabel("Preparing playlist scan...")
		self.label.setWordWrap(True)
		self.progress = QProgressBar()
		self.cancel_button = QPushButton("Cancel")
		self.cancel_button.clicked.connect(self.canceled.emit)
		layout.addWidget(self.label)
		layout.addWidget(self.progress)
		layout.addSpacing(3)
		preview_label = QLabel("Live page preview")
		preview_label.setStyleSheet("font-weight: bold; color: #303030;")
		layout.addWidget(preview_label)
		self.preview = QScrollArea()
		self.preview.setMinimumHeight(185)
		self.preview.setMaximumHeight(210)
		self.preview.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
		self.preview.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
		self.preview.setWidgetResizable(False)
		self.preview.setFocusPolicy(Qt.NoFocus)
		self.preview.viewport().setAttribute(Qt.WA_TransparentForMouseEvents, True)
		layout.addWidget(self.preview, 1)
		layout.addSpacing(3)
		layout.addWidget(self.cancel_button)

	def setRange(self, minimum: int, maximum: int) -> None:
		self.progress.setRange(minimum, maximum)

	def setValue(self, value: int) -> None:
		self.progress.setValue(value)

	def setLabelText(self, text: str) -> None:
		self.label.setText(text)

	def attach_browser(self, browser) -> None:
		browser.setMinimumSize(1000, 650)
		browser.resize(1000, 650)
		browser.setFocusPolicy(Qt.NoFocus)
		browser.setAttribute(Qt.WA_TransparentForMouseEvents, True)
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
		browser.setAttribute(Qt.WA_TransparentForMouseEvents, False)
		browser.setFocusPolicy(Qt.StrongFocus)
		browser.hide()
		browser.setParent(owner)


class LibraryEqualizerDialog(QDialog):
	def __init__(self, parent=None):
		super().__init__(parent)
		self.setWindowTitle("Library Equalizer")
		self.resize(600, 470)
		self.setFont(QFont("Comic Sans MS", 9))
		self.setStyleSheet("""
			QDialog { background: #c0c0c0; color: #101010; }
			QFrame#equalizerSection {
				background: #c0c0c0; border-top: 2px solid #ffffff; border-left: 2px solid #ffffff;
				border-right: 2px solid #404040; border-bottom: 2px solid #404040;
			}
			QPushButton {
				background: #c0c0c0; border-top: 2px solid #ffffff; border-left: 2px solid #ffffff;
				border-right: 2px solid #000000; border-bottom: 2px solid #000000;
				padding: 4px 10px; min-height: 20px;
			}
			QPushButton:pressed {
				border-top: 2px solid #000000; border-left: 2px solid #000000;
				border-right: 2px solid #ffffff; border-bottom: 2px solid #ffffff;
			}
			QSlider::groove:horizontal { height: 7px; background: #686868; border-top: 2px solid #404040; border-left: 2px solid #404040; border-right: 2px solid #ffffff; border-bottom: 2px solid #ffffff; }
			QSlider::sub-page:horizontal { background: #000080; border: 1px solid #000040; }
			QSlider::handle:horizontal { width: 18px; margin: -9px 0; background: #d4d0c8; border-top: 2px solid #ffffff; border-left: 2px solid #ffffff; border-right: 2px solid #404040; border-bottom: 2px solid #404040; }
			QSlider::handle:horizontal:pressed { background: #b8b4ac; border-top-color: #404040; border-left-color: #404040; border-right-color: #ffffff; border-bottom-color: #ffffff; }
		""")
		layout = QVBoxLayout(self)
		heading = QLabel("EQUALIZER")
		heading.setFont(QFont("Comic Sans MS", 14, QFont.Bold))
		heading.setStyleSheet("background: #000080; color: white; padding: 7px; border: 2px outset white;")
		layout.addWidget(heading)
		section = QFrame()
		section.setObjectName("equalizerSection")
		section_layout = QVBoxLayout(section)
		section_layout.setContentsMargins(14, 12, 14, 14)
		note = QLabel("Optional FFmpeg audio processing. These settings are applied to newly downloaded tracks.")
		note.setWordWrap(True)
		section_layout.addWidget(note)
		self.enabled = QCheckBox("Equalizer ON")
		self.enabled.setFont(QFont("Comic Sans MS", 11, QFont.Bold))
		self.normalize = QCheckBox("Match volume between tracks")
		section_layout.addWidget(self.enabled)
		section_layout.addWidget(self.normalize)
		self.sliders: dict[str, QSlider] = {}
		self.value_labels: dict[str, QLabel] = {}
		for key, label in (("volume", "Output gain"), ("bass", "Bass"), ("treble", "Treble")):
			label_row = QHBoxLayout()
			name = QLabel(label)
			name.setFont(QFont("Comic Sans MS", 10, QFont.Bold))
			value_label = QLabel("0 dB")
			value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
			value_label.setMinimumWidth(55)
			label_row.addWidget(name)
			label_row.addStretch(1)
			label_row.addWidget(value_label)
			section_layout.addLayout(label_row)
			slider = QSlider(Qt.Horizontal)
			slider.setRange(-12, 12)
			slider.setTickInterval(1)
			slider.setTickPosition(QSlider.TicksBelow)
			slider.setSingleStep(1)
			slider.setPageStep(1)
			slider.setMinimumHeight(38)
			slider.valueChanged.connect(lambda value, target=value_label: target.setText(f"{value:+d} dB" if value else "0 dB"))
			section_layout.addWidget(slider)
			self.sliders[key] = slider
			self.value_labels[key] = value_label
		layout.addWidget(section, 1)
		buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
		buttons.accepted.connect(self._save)
		buttons.rejected.connect(self.reject)
		layout.addWidget(buttons)
		cfg = load_settings()
		self.enabled.setChecked(bool(cfg.get("eq_enabled", False)))
		self.normalize.setChecked(bool(cfg.get("eq_normalize", False)))
		for key, slider in self.sliders.items():
			slider.setValue(int(cfg.get(f"eq_{key}_gain", 0) or 0))
		self.enabled.toggled.connect(self._enabled_changed)
		self._enabled_changed(self.enabled.isChecked())

	def _enabled_changed(self, enabled: bool) -> None:
		self.enabled.setText("Equalizer ON" if enabled else "Equalizer OFF")
		self.normalize.setEnabled(enabled)
		for slider in self.sliders.values():
			slider.setEnabled(enabled)

	def _save(self) -> None:
		save_settings({
			"eq_enabled": self.enabled.isChecked(),
			"eq_normalize": self.normalize.isChecked(),
			"eq_volume_gain": self.sliders["volume"].value(),
			"eq_bass_gain": self.sliders["bass"].value(),
			"eq_treble_gain": self.sliders["treble"].value(),
		})
		self.accept()


class LibrarySettingsDialog(QDialog):
	def __init__(self, library: dict, parent=None, *, download_confirmation: bool = False):
		super().__init__(parent)
		self.library = library
		self.setWindowTitle("Confirm Download Settings" if download_confirmation else "Library Download Settings")
		self.resize(650, 500)
		self.setFont(QFont("Comic Sans MS", 9))
		self.setStyleSheet("""
			QDialog { background: #c0c0c0; color: #101010; }
			QFrame#settingsSection {
				background: #c0c0c0; border-top: 2px solid #ffffff; border-left: 2px solid #ffffff;
				border-right: 2px solid #404040; border-bottom: 2px solid #404040;
			}
			QPushButton, QComboBox {
				background: #c0c0c0; border-top: 2px solid #ffffff; border-left: 2px solid #ffffff;
				border-right: 2px solid #000000; border-bottom: 2px solid #000000;
				padding: 4px 8px; min-height: 20px;
			}
			QPushButton:pressed {
				border-top: 2px solid #000000; border-left: 2px solid #000000;
				border-right: 2px solid #ffffff; border-bottom: 2px solid #ffffff;
			}
			QLineEdit {
				background: white; border-top: 2px solid #404040; border-left: 2px solid #404040;
				border-right: 2px solid #ffffff; border-bottom: 2px solid #ffffff; padding: 4px;
			}
			QTabWidget::pane { border: 2px inset #ffffff; background: #c0c0c0; }
			QTabBar::tab { background: #a8a8a8; border: 2px outset #ffffff; padding: 6px 16px; }
			QTabBar::tab:selected { background: #c0c0c0; }
			QSlider::groove:horizontal { height: 7px; background: #686868; border-top: 2px solid #404040; border-left: 2px solid #404040; border-right: 2px solid #ffffff; border-bottom: 2px solid #ffffff; }
			QSlider::sub-page:horizontal { background: #000080; border: 1px solid #000040; }
			QSlider::handle:horizontal { width: 18px; margin: -9px 0; background: #d4d0c8; border-top: 2px solid #ffffff; border-left: 2px solid #ffffff; border-right: 2px solid #404040; border-bottom: 2px solid #404040; }
			QSlider::handle:horizontal:pressed { background: #b8b4ac; border-top-color: #404040; border-left-color: #404040; border-right-color: #ffffff; border-bottom-color: #ffffff; }
		""")
		layout = QVBoxLayout(self)
		heading = QLabel("DOWNLOAD SETTINGS")
		heading.setFont(QFont("Comic Sans MS", 14, QFont.Bold))
		heading.setStyleSheet("background: #000080; color: white; padding: 7px; border: 2px outset white;")
		layout.addWidget(heading)
		tabs = QTabWidget()
		layout.addWidget(tabs, 1)
		general = QWidget()
		general_layout = QVBoxLayout(general)
		location_section = self._section("Download location")
		location_layout = location_section.layout()
		output_row = QHBoxLayout()
		self.output = QLineEdit(str(library.get("output_dir") or ""))
		self.output.setPlaceholderText("Choose where playlist folders will be created")
		browse = QPushButton("Browse…")
		browse.clicked.connect(self._browse)
		output_row.addWidget(self.output, 1)
		output_row.addWidget(browse)
		location_layout.addWidget(QLabel("Output folder"))
		location_layout.addLayout(output_row)
		general_layout.addWidget(location_section)
		audio_section = self._section("Audio defaults")
		audio_layout = audio_section.layout()
		format_row = QHBoxLayout()
		format_row.addWidget(QLabel("Audio format"))
		self.format = QComboBox()
		self.format.addItems(["m4a", "mp3", "opus"])
		self.format.setCurrentText(str(library.get("format") or "m4a"))
		format_row.addWidget(self.format)
		format_row.addStretch(1)
		audio_layout.addLayout(format_row)
		cfg = load_settings()
		audio_layout.addWidget(QLabel("MP3 quality — move right for better quality / larger files"))
		self.mp3_quality = QSlider(Qt.Horizontal)
		self.mp3_quality.setRange(0, 10)
		self.mp3_quality.setTickPosition(QSlider.TicksBelow)
		self.mp3_quality.setTickInterval(1)
		self.mp3_quality.setSingleStep(1)
		self.mp3_quality.setPageStep(1)
		self.mp3_quality.setMinimumHeight(38)
		stored_mp3_quality = max(0, min(10, int(cfg.get("mp3_quality", 0) or 0)))
		self.mp3_quality.setValue(10 - stored_mp3_quality)
		audio_layout.addWidget(self.mp3_quality)
		self.mp3_quality_value = QLabel()
		self.mp3_quality_value.setAlignment(Qt.AlignCenter)
		self.mp3_quality.valueChanged.connect(self._update_mp3_quality_label)
		audio_layout.addWidget(self.mp3_quality_value)
		self._update_mp3_quality_label(self.mp3_quality.value())
		self.embed_art = QCheckBox("Embed album artwork")
		self.embed_art.setChecked(bool(cfg.get("embed_art", True)))
		self.force = QCheckBox("Force-download low-confidence matches")
		self.force.setChecked(bool(cfg.get("force_download_mode", False)))
		self.m3u8 = QCheckBox("Write M3U8 playlists")
		self.m3u8.setChecked(bool(cfg.get("write_m3u8", True)))
		for widget in (self.embed_art, self.force, self.m3u8):
			audio_layout.addWidget(widget)
		m3u_row = QHBoxLayout()
		self.m3u_output = QLineEdit(str(cfg.get("m3u_output_dir") or ""))
		self.m3u_output.setPlaceholderText("Same folder as each playlist's audio (default)")
		self.m3u_output.setReadOnly(True)
		m3u_browse = QPushButton("Choose folder...")
		m3u_browse.clicked.connect(self._choose_m3u_output)
		m3u_same = QPushButton("Same as audio")
		m3u_same.clicked.connect(self.m3u_output.clear)
		m3u_row.addWidget(self.m3u_output, 1)
		m3u_row.addWidget(m3u_browse)
		m3u_row.addWidget(m3u_same)
		audio_layout.addLayout(m3u_row)
		self.m3u8.clicked.connect(self._m3u_toggled)
		general_layout.addWidget(audio_section)
		general_layout.addStretch(1)
		tabs.addTab(general, "General")
		advanced = QWidget()
		advanced_layout = QVBoxLayout(advanced)
		tools_section = self._section("Tool paths — Advanced")
		tools_layout = tools_section.layout()
		note = QLabel("These overrides are optional. Leave them blank to use CSVMusic's bundled tools or automatic PATH detection.")
		note.setWordWrap(True)
		tools_layout.addWidget(note)
		self.ytdlp = QLineEdit(str(cfg.get("yt_dlp_path") or ""))
		self.ytdlp.setPlaceholderText("Auto-detect yt-dlp")
		self.ffmpeg = QLineEdit(str(cfg.get("ffmpeg_path") or ""))
		self.ffmpeg.setPlaceholderText("Use bundled FFmpeg")
		self._add_tool_path(tools_layout, "yt-dlp executable", self.ytdlp)
		self._add_tool_path(tools_layout, "FFmpeg executable", self.ffmpeg)
		advanced_layout.addWidget(tools_section)
		advanced_layout.addStretch(1)
		tabs.addTab(advanced, "Advanced")
		buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
		if download_confirmation:
			buttons.button(QDialogButtonBox.Save).setText("Start Download")
		buttons.accepted.connect(self._save)
		buttons.rejected.connect(self.reject)
		layout.addWidget(buttons)

	def _section(self, title: str) -> QFrame:
		section = QFrame()
		section.setObjectName("settingsSection")
		section_layout = QVBoxLayout(section)
		section_layout.setContentsMargins(12, 10, 12, 12)
		heading = QLabel(title)
		heading.setFont(QFont("Comic Sans MS", 11, QFont.Bold))
		section_layout.addWidget(heading)
		return section

	def _add_tool_path(self, layout: QVBoxLayout, label: str, field: QLineEdit) -> None:
		layout.addWidget(QLabel(label))
		row = QHBoxLayout()
		row.addWidget(field, 1)
		browse = QPushButton("Browse…")
		browse.clicked.connect(lambda _checked=False, target=field: self._browse_tool(target))
		clear = QPushButton("Clear")
		clear.clicked.connect(field.clear)
		row.addWidget(browse)
		row.addWidget(clear)
		layout.addLayout(row)

	def _browse_tool(self, field: QLineEdit) -> None:
		path, _ = QFileDialog.getOpenFileName(self, "Choose executable", field.text())
		if path:
			field.setText(path)

	def _browse(self) -> None:
		path = QFileDialog.getExistingDirectory(self, "Choose Library Output", self.output.text())
		if path:
			self.output.setText(path)

	def _choose_m3u_output(self) -> bool:
		start = self.m3u_output.text().strip() or self.output.text().strip()
		path = QFileDialog.getExistingDirectory(self, "Choose Playlist File Folder", start)
		if path:
			self.m3u_output.setText(path)
			return True
		return False

	def _m3u_toggled(self, checked: bool) -> None:
		if checked and not self.m3u_output.text().strip():
			self._choose_m3u_output()

	def _update_mp3_quality_label(self, value: int) -> None:
		if value >= 10:
			text = "10 = Best quality"
		elif value <= 0:
			text = "0 = Lowest quality"
		else:
			text = f"Quality {value} / 10"
		self.mp3_quality_value.setText(text)

	def _save(self) -> None:
		if not self.output.text().strip():
			QMessageBox.warning(self, "Missing Output", "Choose an output folder.")
			return
		self.library["output_dir"] = self.output.text().strip()
		self.library["format"] = self.format.currentText()
		save_settings({
			"yt_dlp_path": self.ytdlp.text().strip() or None,
			"ffmpeg_path": self.ffmpeg.text().strip() or None,
			# FFmpeg/libmp3lame uses the inverse scale: 0 is its best quality.
			"mp3_quality": 10 - self.mp3_quality.value(),
			"embed_art": self.embed_art.isChecked(),
			"force_download_mode": self.force.isChecked(),
			"write_m3u8": self.m3u8.isChecked(),
			"m3u_output_dir": self.m3u_output.text().strip() or None,
		})
		self.accept()


class TrackAlternativesDialog(QDialog):
	selected = Signal(str, str, int)

	def __init__(self, track: dict, parent=None):
		super().__init__(parent)
		self.track = track
		self.options: list[dict] = []
		self.worker: AlternativesFetchWorker | None = None
		self.setWindowTitle("Song Settings")
		self.resize(700, 500)
		self.setFont(QFont("Comic Sans MS", 9))
		self.setStyleSheet("""
			QDialog { background: #c0c0c0; color: #101010; }
			QFrame#songSettingsSection { background: #c0c0c0; border: 2px outset #ffffff; }
			QPushButton { background: #c0c0c0; border: 2px outset #ffffff; padding: 4px 9px; min-height: 20px; }
			QPushButton:pressed { border: 2px inset #ffffff; }
			QLineEdit, QListWidget { background: white; border: 2px inset #ffffff; padding: 3px; }
			QListWidget::item { padding: 6px; }
			QListWidget::item:selected { background: #000080; color: #ffffff; }
			QTabWidget::pane { border: 2px inset #ffffff; background: #c0c0c0; }
			QTabBar::tab { background: #a8a8a8; border: 2px outset #ffffff; padding: 6px 16px; }
			QTabBar::tab:selected { background: #c0c0c0; }
			QSlider::groove:horizontal { height: 7px; background: #686868; border-top: 2px solid #404040; border-left: 2px solid #404040; border-right: 2px solid #ffffff; border-bottom: 2px solid #ffffff; }
			QSlider::sub-page:horizontal { background: #000080; border: 1px solid #000040; }
			QSlider::handle:horizontal { width: 18px; margin: -9px 0; background: #d4d0c8; border-top: 2px solid #ffffff; border-left: 2px solid #ffffff; border-right: 2px solid #404040; border-bottom: 2px solid #404040; }
			QSlider::handle:horizontal:pressed { background: #b8b4ac; border-top-color: #404040; border-left-color: #404040; border-right-color: #ffffff; border-bottom-color: #ffffff; }
		""")
		layout = QVBoxLayout(self)
		heading = QLabel("SONG SETTINGS")
		heading.setFont(QFont("Comic Sans MS", 14, QFont.Bold))
		heading.setStyleSheet("background: #000080; color: white; padding: 7px; border: 2px outset white;")
		layout.addWidget(heading)
		song = QLabel(f"{track.get('title', '')}  —  {track.get('artists', '')}")
		song.setFont(QFont("Comic Sans MS", 11, QFont.Bold))
		song.setWordWrap(True)
		layout.addWidget(song)
		current_label = str(track.get("preferred_video_label") or track.get("preferred_video_id") or "")
		if not current_label and track.get("downloaded_video_title"):
			publisher = str(track.get("downloaded_video_publisher") or "").strip()
			current_label = str(track["downloaded_video_title"]) + (f" — {publisher}" if publisher else "")
		if not current_label:
			current_label = "Automatic matching (not downloaded yet)"
		self.current_match = QLabel(f"Current selection: {current_label}")
		self.current_match.setWordWrap(True)
		self.current_match.setStyleSheet("background: #ffffff; border: 2px inset #ffffff; padding: 6px; color: #000080;")
		layout.addWidget(self.current_match)
		self.pending_match = QLabel("New selection: No change")
		self.pending_match.setWordWrap(True)
		self.pending_match.setStyleSheet("background: #ffffcc; border: 2px inset #ffffff; padding: 6px; font-weight: bold;")
		layout.addWidget(self.pending_match)
		tabs = QTabWidget()
		layout.addWidget(tabs, 1)
		match_tab = QWidget()
		match_layout = QVBoxLayout(match_tab)
		self.status = QLabel("Searching YouTube and YouTube Music...")
		self.status.setWordWrap(True)
		match_layout.addWidget(self.status)
		self.list = QListWidget()
		self.list.itemDoubleClicked.connect(self._open_item)
		self.list.itemSelectionChanged.connect(self._alternative_selected)
		match_layout.addWidget(self.list, 1)
		self.manual = QLineEdit()
		self.manual.setPlaceholderText("Or paste a YouTube URL")
		self.manual.textChanged.connect(self._manual_selection_changed)
		match_layout.addWidget(self.manual)
		tabs.addTab(match_tab, "YouTube Match")
		audio_tab = QWidget()
		audio_layout = QVBoxLayout(audio_tab)
		audio_section = QFrame()
		audio_section.setObjectName("songSettingsSection")
		audio_section_layout = QVBoxLayout(audio_section)
		audio_heading = QLabel("Individual sound level")
		audio_heading.setFont(QFont("Comic Sans MS", 11, QFont.Bold))
		audio_section_layout.addWidget(audio_heading)
		audio_note = QLabel("Adjust only this song. 0 dB keeps its original level; negative values make it quieter and positive values make it louder.")
		audio_note.setWordWrap(True)
		audio_section_layout.addWidget(audio_note)
		self.volume_value = QLabel("0 dB")
		self.volume_value.setAlignment(Qt.AlignCenter)
		self.volume_value.setFont(QFont("Comic Sans MS", 12, QFont.Bold))
		audio_section_layout.addWidget(self.volume_value)
		self.volume = QSlider(Qt.Horizontal)
		self.volume.setRange(-12, 12)
		self.volume.setTickInterval(1)
		self.volume.setTickPosition(QSlider.TicksBelow)
		self.volume.setSingleStep(1)
		self.volume.setPageStep(1)
		self.volume.setMinimumHeight(38)
		self.volume.setValue(max(-12, min(12, int(track.get("audio_volume_gain", 0) or 0))))
		self.volume.valueChanged.connect(self._volume_changed)
		audio_section_layout.addWidget(self.volume)
		reset_volume = QPushButton("Reset to 0 dB")
		reset_volume.clicked.connect(lambda: self.volume.setValue(0))
		audio_section_layout.addWidget(reset_volume, 0, Qt.AlignLeft)
		audio_layout.addWidget(audio_section)
		audio_layout.addStretch(1)
		tabs.addTab(audio_tab, "Sound Level")
		buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
		self.save_button = buttons.button(QDialogButtonBox.Save)
		self.save_button.setText("Save Settings")
		buttons.accepted.connect(self._accept_choice)
		buttons.rejected.connect(self.reject)
		layout.addWidget(buttons)
		self._volume_changed(self.volume.value())
		self.worker = AlternativesFetchWorker(0, track, parent=self)
		self.worker.sig_done.connect(self._loaded)
		self.worker.start()

	def _loaded(self, _row: int, options: list, error: str) -> None:
		self.options = options
		self.status.setText(error or f"Found {len(options)} alternatives. Double-click to preview in your browser.")
		for option in options:
			source_label = "YouTube Music" if option.get("source") == "music" else "YouTube"
			album = option.get("album")
			if isinstance(album, dict):
				album = album.get("name") or album.get("title") or ""
			album = str(album or "").strip()
			markers = set(option.get("version_markers") or [])
			warning = ""
			if "live" in markers:
				warning = "  ⚠ LIVE"
			elif "acoustic" in markers:
				warning = "  ⚠ ACOUSTIC"
			album_text = f"  •  Album: {album}" if album else ""
			item = QListWidgetItem(f"[{source_label}]  {option.get('title', 'Unknown')} — {option.get('author', '')}{album_text}{warning}")
			item.setData(Qt.UserRole, option)
			item.setToolTip(f"Source: {source_label}" + (f"\nAlbum: {album}" if album else "") + (f"\nDetected version: {', '.join(sorted(markers))}" if markers else ""))
			self.list.addItem(item)

	def _open_item(self, item: QListWidgetItem) -> None:
		option = item.data(Qt.UserRole) or {}
		if option.get("videoId"):
			QDesktopServices.openUrl(QUrl(f"https://www.youtube.com/watch?v={option['videoId']}"))

	def _alternative_selected(self) -> None:
		item = self.list.selectedItems()[0] if self.list.selectedItems() else None
		if item is None:
			if not self.manual.text().strip():
				self.pending_match.setText("New selection: No change")
			return
		option = item.data(Qt.UserRole) or {}
		title = str(option.get("title") or "Unknown video")
		author = str(option.get("author") or "").strip()
		self.pending_match.setText(f"New selection: {title}" + (f" — {author}" if author else ""))
		self.save_button.setText("Save Selection")
		if self.manual.text():
			self.manual.blockSignals(True)
			self.manual.clear()
			self.manual.blockSignals(False)

	def _manual_selection_changed(self, value: str) -> None:
		value = value.strip()
		if value:
			self.list.clearSelection()
			self.pending_match.setText(f"New selection: {value}")
			self.save_button.setText("Save Selection")
		elif not self.list.selectedItems():
			self.pending_match.setText("New selection: No change")
			self.save_button.setText("Save Settings")

	def _accept_choice(self) -> None:
		value = self.manual.text().strip()
		video_id = str(self.track.get("preferred_video_id") or "")
		label = str(self.track.get("preferred_video_label") or video_id)
		try:
			if value:
				video_id = parse_youtube_video_id(value)
				label = value
			elif self.list.selectedItems():
				option = self.list.selectedItems()[0].data(Qt.UserRole) or {}
				video_id = str(option.get("videoId") or "")
				label = str(option.get("title") or video_id)
		except YouTubeVideoUrlError as exc:
			QMessageBox.warning(self, "Invalid YouTube URL", str(exc))
			return
		self.selected.emit(video_id, label, self.volume.value())
		self.accept()

	def _volume_changed(self, value: int) -> None:
		self.volume_value.setText(f"{value:+d} dB" if value else "0 dB")


class LibraryGuideDialog(QDialog):
	def __init__(self, title: str, heading: str, html: str, parent=None):
		super().__init__(parent)
		self.setWindowTitle(title)
		self.resize(780, 650)
		self.setFont(QFont("Comic Sans MS", 9))
		self.setStyleSheet("""
			QDialog { background: #c0c0c0; color: #101010; }
			QTextBrowser { background: #ffffff; border: 2px inset #ffffff; padding: 10px; }
			QPushButton { background: #c0c0c0; border: 2px outset #ffffff; padding: 5px 14px; font-weight: bold; }
			QPushButton:pressed { border: 2px inset #ffffff; }
		""")
		layout = QVBoxLayout(self)
		title_label = QLabel(heading)
		title_label.setFont(QFont("Comic Sans MS", 14, QFont.Bold))
		title_label.setStyleSheet("background: #000080; color: white; padding: 7px; border: 2px outset white;")
		layout.addWidget(title_label)
		browser = QTextBrowser()
		browser.setOpenExternalLinks(True)
		browser.setHtml(html)
		layout.addWidget(browser, 1)
		close_button = QPushButton("Close")
		close_button.clicked.connect(self.accept)
		layout.addWidget(close_button, 0, Qt.AlignRight)


class DownloadLogDialog(QDialog):
	def __init__(self, parent=None):
		super().__init__(parent)
		self.setWindowTitle("Library Download Log")
		self.resize(820, 520)
		self.setFont(QFont("Comic Sans MS", 9))
		self.setStyleSheet("""
			QDialog { background: #c0c0c0; color: #101010; }
			QPlainTextEdit { background: #101010; color: #e8e8e8; border: 2px inset #ffffff; font-family: Consolas, monospace; }
			QPushButton { background: #c0c0c0; border: 2px outset #ffffff; padding: 5px 14px; font-weight: bold; }
			QPushButton:pressed { border: 2px inset #ffffff; }
		""")
		layout = QVBoxLayout(self)
		heading = QLabel("DOWNLOAD PROCESS & ERROR LOG")
		heading.setFont(QFont("Comic Sans MS", 14, QFont.Bold))
		heading.setStyleSheet("background: #000080; color: white; padding: 7px; border: 2px outset white;")
		layout.addWidget(heading)
		self.output = QPlainTextEdit()
		self.output.setReadOnly(True)
		self.output.document().setMaximumBlockCount(5000)
		self.output.setPlaceholderText("Download process notes, warnings, and errors will appear here.")
		layout.addWidget(self.output, 1)
		buttons = QHBoxLayout()
		copy_button = QPushButton("Copy Log")
		copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self.output.toPlainText()))
		clear_button = QPushButton("Clear")
		clear_button.clicked.connect(self.output.clear)
		close_button = QPushButton("Close")
		close_button.clicked.connect(self.hide)
		buttons.addWidget(copy_button)
		buttons.addWidget(clear_button)
		buttons.addStretch(1)
		buttons.addWidget(close_button)
		layout.addLayout(buttons)

	def append(self, level: str, message: str) -> None:
		timestamp = datetime.datetime.now().strftime("%H:%M:%S")
		clean = " ".join(str(message or "").split())
		if clean:
			self.output.appendPlainText(f"[{timestamp}] [{level.upper()}] {clean}")

	def begin_run(self, playlist: str, track_count: int) -> None:
		self.output.clear()
		self.append("note", f"Starting playlist: {playlist}")
		self.append("note", f"Tracks queued: {track_count}")


class StartupDisclaimerDialog(QDialog):
	def __init__(self, parent=None, *, show_preference: bool = True):
		super().__init__(parent)
		self.setWindowTitle("CSVMusic - Before You Start")
		self.setModal(True)
		self.setMinimumSize(1000, 650)
		self.resize(1000, 650)
		self.setFont(QFont("Comic Sans MS", 10))
		self.setStyleSheet("""
			QDialog { background: #c0c0c0; color: #101010; font-family: "Comic Sans MS"; }
			QLabel#disclaimerBanner {
				background: #000080; color: #ffff00; border: 3px outset #ffffff;
				padding: 12px; font-size: 19px; font-weight: bold;
			}
			QFrame#warningCard { background: #ffff99; border: 3px outset #ffffff; }
			QFrame#dangerCard { background: #ffe0b2; border: 3px outset #ffffff; }
			QFrame#infoCard { background: #cce8ff; border: 3px outset #ffffff; }
			QLabel#cardText { color: #101010; font-family: "Comic Sans MS"; font-size: 10pt; }
			QCheckBox { background: #ffffcc; border: 2px inset #ffffff; padding: 11px 18px; font-family: "Comic Sans MS"; font-size: 15px; font-weight: bold; }
			QCheckBox::indicator { width: 30px; height: 30px; }
			QPushButton {
				background: #008000; color: white; border: 3px outset #ffffff;
				padding: 9px 22px; font-family: "Comic Sans MS"; font-size: 12px; font-weight: bold;
			}
			QPushButton:pressed { border: 3px inset #ffffff; }
		""")
		layout = QVBoxLayout(self)
		layout.setContentsMargins(14, 14, 14, 14)
		layout.setSpacing(10)
		banner = QLabel("!!!  BEFORE YOU START  !!!" if show_preference else "SAFETY & SUPPORT")
		banner.setObjectName("disclaimerBanner")
		banner.setAlignment(Qt.AlignCenter)
		layout.addWidget(banner)
		cards = QGridLayout()
		cards.setHorizontalSpacing(10)
		cards.setVerticalSpacing(10)
		cards.setColumnStretch(0, 1)
		cards.setColumnStretch(1, 1)
		cards.setRowStretch(0, 1)
		cards.setRowStretch(1, 1)
		cards.setRowMinimumHeight(0, 220)
		cards.setRowMinimumHeight(1, 220)

		def add_card(row: int, column: int, object_name: str, text: str) -> None:
			card = QFrame()
			card.setObjectName(object_name)
			card.setMinimumHeight(220)
			card.setMaximumHeight(220)
			card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
			card_layout = QVBoxLayout(card)
			card_layout.setContentsMargins(12, 10, 12, 10)
			label = QLabel(text)
			label.setObjectName("cardText")
			label.setTextFormat(Qt.RichText)
			label.setWordWrap(True)
			label.setOpenExternalLinks(True)
			label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
			card_layout.addWidget(label)
			cards.addWidget(card, row, column)

		add_card(0, 0, "warningCard", """
			<font color="#000080" size="5"><b>1. Try to avoid enormous playlists</b></font><br><br>
			Large playlists are supported, but they naturally require many more page loads, searches, downloads, and metadata operations. This means they can take a long time and are more likely to encounter incomplete public metadata, temporary service limits, or an interrupted scan.
		""")
		add_card(0, 1, "dangerCard", """
			<font color="#804000" size="5"><b>2. YouTube requests and throttling</b></font><br><br>
			YouTube sometimes slows or temporarily rejects repeated requests with HTTP 403 errors, rate limits, sign-in checks, or extraction failures. These are usually service protections rather than a broken playlist. CSVMusic adds pauses and throttling to reduce the chance, and waiting before retrying often helps.<br><br>
			<a href="https://github.com/yt-dlp/yt-dlp"><b>yt-dlp project</b></a> &nbsp;|&nbsp;
			<a href="https://github.com/yt-dlp/yt-dlp/wiki/FAQ"><b>yt-dlp FAQ</b></a>
		""")
		add_card(1, 0, "infoCard", """
			<font color="#000080" size="5"><b>3. Review automatic results</b></font><br><br>
			Song matching and scraped metadata are not guaranteed to be correct. Review yellow low-confidence entries and use Song Settings to choose alternatives. Only download media you are authorized to access and use.
		""")
		add_card(1, 1, "infoCard", """
			<font color="#000080" size="5"><b>4. Need help?</b></font><br><br>
			Open the Download Log and include the relevant error. Remove personal paths, cookies, tokens, or account details before sharing logs.<br><br>
			<a href="https://github.com/angall1/CSVMusic/issues"><b>Post a GitHub issue</b></a> &nbsp;|&nbsp;
			<a href="https://www.reddit.com/user/agalli/"><b>Message agalli on Reddit</b></a><br><br>
			<a href="https://buymeacoffee.com/agalli"><b>Enjoying CSVMusic? Buy me a coffee</b></a>
		""")
		layout.addLayout(cards, 1)
		self.hide_next_time = QCheckBox("Don't show this disclaimer again")
		self.hide_next_time.setVisible(show_preference)
		layout.addWidget(self.hide_next_time, 0, Qt.AlignCenter)
		continue_button = QPushButton("I UNDERSTAND - CONTINUE" if show_preference else "CLOSE")
		continue_button.clicked.connect(self._continue)
		layout.addWidget(continue_button, 0, Qt.AlignCenter)

	def _continue(self) -> None:
		if self.hide_next_time.isChecked():
			save_settings({"hide_startup_disclaimer": True})
		self.accept()


class LibraryModeDialog(QDialog):
	tracks_ready = Signal(object, str, str, str)
	legacy_mode_requested = Signal()

	def __init__(self, parent=None):
		super().__init__(parent)
		self.setWindowTitle("CSVMusic Library Mode")
		self.resize(1280, 800)
		self.library_path = settings_path().parent / "library.json"
		self.library = self._load_or_create()
		self.scan_queue: list[dict] = []
		self.scans_completed = 0
		self.scan_results: list[dict] = []
		self.current_scan_name = ""
		self.scraper: SpotifyPublicScrapeDialog | None = None
		self.direct_worker: DirectLibraryScanWorker | None = None
		self.download_worker: PipelineWorker | None = None
		self.single_download_worker: SingleDownloadWorker | None = None
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
		self.track_display_batch = 200
		self.track_display_limit = self.track_display_batch
		self.shown_playlist_ids: frozenset[str] = frozenset()
		self.track_state_labels: dict[tuple[str, int], QWidget] = {}
		self.track_cards: dict[tuple[str, int], QFrame] = {}
		self.download_track_states: dict[tuple[str, int], str] = {}
		self.download_row_targets: dict[int, tuple[str, int]] = {}
		self.download_log_dialog = DownloadLogDialog(self)
		self.header_font_family = self._load_header_font()
		self._build_ui()
		self._refresh()
		if not bool(load_settings().get("hide_startup_disclaimer", False)):
			QTimer.singleShot(0, self._show_startup_disclaimer)

	def _show_startup_disclaimer(self) -> None:
		dialog = StartupDisclaimerDialog(self)
		dialog.exec()

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
				padding: 4px 8px; min-height: 21px; color: #101010;
				font-size: 10pt; font-weight: 600;
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
			QScrollBar:vertical {
				background: #a8a8a8; width: 18px; margin: 18px 0 18px 0;
				border-top: 2px solid #505050; border-left: 2px solid #505050;
				border-right: 2px solid #ffffff; border-bottom: 2px solid #ffffff;
			}
			QScrollBar::handle:vertical {
				min-height: 30px;
				background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #f4f4f4, stop:0.18 #d8d8d8, stop:0.72 #b8b8b8, stop:1 #8c8c8c);
				border-top: 2px solid #ffffff; border-left: 2px solid #ffffff;
				border-right: 2px solid #404040; border-bottom: 2px solid #404040;
			}
			QScrollBar::handle:vertical:hover { background: #dcdcdc; }
			QScrollBar::handle:vertical:pressed {
				background: #a8a8a8; border-top: 2px solid #404040; border-left: 2px solid #404040;
				border-right: 2px solid #ffffff; border-bottom: 2px solid #ffffff;
			}
			QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
				height: 18px; background: #c0c0c0;
				border-top: 2px solid #ffffff; border-left: 2px solid #ffffff;
				border-right: 2px solid #404040; border-bottom: 2px solid #404040;
			}
			QScrollBar::sub-line:vertical { subcontrol-position: top; subcontrol-origin: margin; }
			QScrollBar::add-line:vertical { subcontrol-position: bottom; subcontrol-origin: margin; }
			QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: #a8a8a8; }
			QScrollBar:horizontal {
				background: #a8a8a8; height: 18px; margin: 0 18px 0 18px;
				border-top: 2px solid #505050; border-left: 2px solid #505050;
				border-right: 2px solid #ffffff; border-bottom: 2px solid #ffffff;
			}
			QScrollBar::handle:horizontal {
				min-width: 30px;
				background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f4f4f4, stop:0.18 #d8d8d8, stop:0.72 #b8b8b8, stop:1 #8c8c8c);
				border-top: 2px solid #ffffff; border-left: 2px solid #ffffff;
				border-right: 2px solid #404040; border-bottom: 2px solid #404040;
			}
			QScrollBar::handle:horizontal:hover { background: #dcdcdc; }
			QScrollBar::handle:horizontal:pressed {
				background: #a8a8a8; border-top: 2px solid #404040; border-left: 2px solid #404040;
				border-right: 2px solid #ffffff; border-bottom: 2px solid #ffffff;
			}
			QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
				width: 18px; background: #c0c0c0;
				border-top: 2px solid #ffffff; border-left: 2px solid #ffffff;
				border-right: 2px solid #404040; border-bottom: 2px solid #404040;
			}
			QScrollBar::sub-line:horizontal { subcontrol-position: left; subcontrol-origin: margin; }
			QScrollBar::add-line:horizontal { subcontrol-position: right; subcontrol-origin: margin; }
			QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: #a8a8a8; }
			QMenu { background: #c0c0c0; border: 2px outset #ffffff; }
			QMenu::item:selected { background: #000080; color: #ffffff; }
		""")
		header_font = QFont(self.header_font_family, 13)
		header_font.setBold(True)
		layout = QVBoxLayout(self)
		layout.setContentsMargins(12, 12, 12, 12)
		layout.setSpacing(8)
		header = QWidget()
		header.setObjectName("libraryHeader")
		header_layout = QHBoxLayout(header)
		header_layout.setContentsMargins(8, 4, 5, 4)
		header_layout.setSpacing(10)
		title = QLabel(f"CSVMusic  v{APP_VERSION}")
		title.setFont(QFont(self.header_font_family, 15))
		title.setStyleSheet("color: white;")
		header_layout.addWidget(title)
		header_layout.addStretch(1)
		for label, icon_kind, callback in (
			("Sync", "sync", self._open_device_sync),
			("Equalizer", "equalizer", self._open_equalizer),
			("Settings", "settings", self._open_settings),
			("Tutorial", "tutorial", self._open_tutorial),
			("Info", "info", self._open_info),
			("Legacy Mode", "legacy", self._switch_to_legacy_mode),
		):
			button = QPushButton(label)
			button.setIcon(_header_button_icon(icon_kind))
			button.setIconSize(QSize(22, 22))
			button.setFlat(True)
			button.setStyleSheet("QPushButton { color: #101010; min-width: 70px; }")
			if callable(callback):
				button.clicked.connect(callback)
			else:
				button.clicked.connect(lambda _checked=False, text=callback: self._placeholder_message(text))
			header_layout.addWidget(button)
		layout.addWidget(header)

		upper = QHBoxLayout()
		upper.setSpacing(8)
		add_panel = QWidget()
		add_panel.setObjectName("addPanel")
		add_panel.setMinimumHeight(178)
		add_layout = QVBoxLayout(add_panel)
		add_layout.setContentsMargins(12, 10, 12, 10)
		add_title = QLabel("Add to library")
		add_title.setFont(header_font)
		add_layout.addWidget(add_title)
		url_description = QLabel("Public playlists and albums: Spotify, YouTube Music, Apple Music, Deezer, and Amazon Music")
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
		add_layout.addSpacing(8)
		csv_divider = QFrame()
		csv_divider.setFrameShape(QFrame.HLine)
		csv_divider.setFrameShadow(QFrame.Sunken)
		add_layout.addWidget(csv_divider)
		add_layout.addSpacing(6)
		csv_row = QHBoxLayout()
		csv_row.setSpacing(12)
		csv_text = QVBoxLayout()
		csv_text.setSpacing(2)
		csv_heading = QLabel("OR IMPORT A CSV PLAYLIST")
		csv_heading.setFont(QFont("Comic Sans MS", 9, QFont.Bold))
		csv_heading.setStyleSheet("color: #000080;")
		csv_description = QLabel("Import a TuneMyMusic, Exportify, or compatible CSVMusic CSV directly into this library.")
		csv_description.setWordWrap(True)
		csv_description.setStyleSheet("color: #505050; font-size: 9pt;")
		csv_text.addWidget(csv_heading)
		csv_text.addWidget(csv_description)
		csv_button = QPushButton("Add CSV...")
		csv_button.setToolTip("Import a CSV playlist into this library")
		csv_button.setMinimumHeight(34)
		csv_button.clicked.connect(self._add_csv_playlist)
		csv_row.addLayout(csv_text, 1)
		csv_row.addWidget(csv_button, 0, Qt.AlignVCenter)
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
		upper.addWidget(add_panel, 2)

		download_panel = QWidget()
		download_panel.setObjectName("downloadPanel")
		download_panel.setMinimumHeight(178)
		download_layout = QVBoxLayout(download_panel)
		download_layout.setContentsMargins(12, 10, 12, 10)
		download_title = QLabel("Download activity")
		download_title.setFont(header_font)
		download_layout.addWidget(download_title)
		self.download_target = QLabel("Target playlist: None selected")
		self.download_target.setStyleSheet("font-weight: bold; color: #303030;")
		self.download_target.setWordWrap(True)
		download_layout.addWidget(self.download_target)
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
		download_buttons = QHBoxLayout()
		self.download_button = QPushButton("Download")
		self.download_button.setIcon(_download_icon())
		self.download_button.setIconSize(QSize(24, 24))
		self.download_button.setStyleSheet("QPushButton { background: #008000; color: white; font-weight: bold; padding: 5px 12px; }")
		self.download_button.clicked.connect(self._start_download)
		self.stop_download_button = QPushButton("Stop")
		self.stop_download_button.setIcon(_stop_icon())
		self.stop_download_button.setIconSize(QSize(24, 24))
		self.stop_download_button.setStyleSheet("QPushButton { background: #b00000; color: white; font-weight: bold; padding: 5px 10px; }")
		self.stop_download_button.setEnabled(False)
		self.stop_download_button.clicked.connect(self._stop_download)
		self.download_log_button = QPushButton("Log")
		self.download_log_button.setIcon(_paper_icon())
		self.download_log_button.setIconSize(QSize(24, 24))
		self.download_log_button.clicked.connect(self._show_download_log)
		download_buttons.addWidget(self.download_button)
		download_buttons.addWidget(self.stop_download_button)
		download_buttons.addStretch(1)
		download_buttons.addWidget(self.download_log_button)
		download_layout.addLayout(download_buttons)
		download_layout.addStretch(1)
		upper.addWidget(download_panel, 3)
		layout.addLayout(upper)

		splitter = QSplitter()
		left = QWidget()
		left.setObjectName("bottomPanel")
		left_layout = QVBoxLayout(left)
		left_layout.setContentsMargins(8, 7, 8, 8)
		playlist_heading = QGridLayout()
		playlist_heading.setContentsMargins(0, 0, 0, 0)
		playlist_heading.setHorizontalSpacing(7)
		playlist_heading.setColumnStretch(0, 1)
		playlist_heading.setColumnStretch(2, 1)
		playlist_heading_label = QLabel("Playlists")
		playlist_heading_label.setFont(header_font)
		playlist_heading.addWidget(playlist_heading_label, 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
		playlist_actions = QWidget()
		playlist_actions_layout = QHBoxLayout(playlist_actions)
		playlist_actions_layout.setContentsMargins(0, 0, 0, 0)
		playlist_actions_layout.setSpacing(6)
		rescan_all = QPushButton("Rescan All")
		rescan_all.setIcon(_rescan_all_icon())
		rescan_all.setIconSize(QSize(34, 26))
		rescan_all.setStyleSheet("QPushButton { background: #008000; color: white; font-weight: bold; padding: 4px 10px; }")
		rescan_all.clicked.connect(self._rescan_all)
		playlist_actions_layout.addWidget(rescan_all)
		open_output = QToolButton()
		open_output.setIcon(_folder_icon())
		open_output.setIconSize(QSize(28, 24))
		open_output.setFixedSize(42, 34)
		open_output.setToolTip("Open the library output folder")
		open_output.setAccessibleName("Open output folder")
		open_output.clicked.connect(self._open_output_folder)
		playlist_actions_layout.addWidget(open_output)
		playlist_heading.addWidget(playlist_actions, 0, 2, Qt.AlignRight | Qt.AlignVCenter)
		left_layout.addLayout(playlist_heading)
		self.playlist_tree = QTreeWidget()
		self.playlist_tree.setHeaderLabels(["Playlists"])
		self.playlist_tree.setHeaderHidden(True)
		self.playlist_tree.setRootIsDecorated(False)
		self.playlist_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
		self.playlist_tree.setIconSize(QSize(48, 48))
		self.playlist_tree.itemSelectionChanged.connect(self._show_tracks)
		self.playlist_tree.itemSelectionChanged.connect(self._update_download_target)
		self.playlist_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
		left_layout.addWidget(self.playlist_tree)
		right = QWidget()
		right.setObjectName("bottomPanel")
		right_layout = QVBoxLayout(right)
		right_layout.setContentsMargins(8, 7, 8, 8)
		right_actions = QGridLayout()
		right_actions.setContentsMargins(0, 0, 0, 0)
		right_actions.setHorizontalSpacing(8)
		right_actions.setColumnStretch(0, 1)
		right_actions.setColumnStretch(2, 1)
		right_actions.setColumnMinimumWidth(0, 150)
		right_actions.setColumnMinimumWidth(2, 150)
		songs_heading = QLabel("Songs")
		songs_heading.setFont(header_font)
		right_actions.addWidget(songs_heading, 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
		search_controls = QWidget()
		search_layout = QHBoxLayout(search_controls)
		search_layout.setContentsMargins(0, 0, 0, 0)
		search_layout.setSpacing(5)
		self.song_search = QLineEdit()
		self.song_search.setPlaceholderText("Search songs...")
		self.song_search.setFixedWidth(280)
		self.song_search.textChanged.connect(self._show_tracks)
		search_layout.addWidget(self.song_search)
		clear_search = QToolButton()
		clear_search.setText("X")
		clear_search.setFixedSize(24, 24)
		clear_search.setStyleSheet("QToolButton { background: #c00000; color: white; font-weight: bold; font-size: 11px; }")
		clear_search.setToolTip("Clear song search")
		clear_search.setAccessibleName("Clear song search")
		clear_search.clicked.connect(self.song_search.clear)
		search_layout.addWidget(clear_search)
		right_actions.addWidget(search_controls, 0, 1, Qt.AlignCenter)
		self.load_more_tracks_button = QPushButton("Load More Songs")
		self.load_more_tracks_button.setVisible(False)
		self.load_more_tracks_button.clicked.connect(self._load_more_tracks)
		right_actions.addWidget(self.load_more_tracks_button, 0, 2, Qt.AlignRight | Qt.AlignVCenter)
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
		left.setMinimumWidth(500)
		splitter.setSizes([512, 768])
		layout.addWidget(splitter, 1)
		self.status = QLabel()
		self.status.setWordWrap(True)
		layout.addWidget(self.status)
		body_font = QFont("Comic Sans MS", 9)
		for widget in self.findChildren(QWidget):
			widget.setFont(body_font)
		title.setFont(QFont(self.header_font_family, 15))
		for heading in (add_title, download_title, playlist_heading_label, songs_heading):
			font = QFont(self.header_font_family, 13)
			font.setBold(True)
			heading.setFont(font)
		self.playlist_tree.header().setFont(QFont(self.header_font_family, 9))

	def _placeholder_message(self, message: str) -> None:
		self.status.setText(message)

	def _show_download_log(self) -> None:
		self.download_log_dialog.show()
		self.download_log_dialog.raise_()
		self.download_log_dialog.activateWindow()

	def _add_csv_playlist(self) -> None:
		path, _ = QFileDialog.getOpenFileName(self, "Import CSV Playlist", "", "CSV files (*.csv);;All files (*)")
		if not path:
			return
		try:
			playlist, created = import_csv_playlist(self.library, path)
		except Exception as exc:
			log(f"library CSV import failed path={path} error={exc}")
			QMessageBox.critical(self, "CSV Import Failed", str(exc))
			return
		self._save()
		self._refresh()
		name = str(playlist.get("name") or pathlib.Path(path).stem)
		count = len(playlist.get("tracks", []))
		self.status.setText(
			f"{'Imported' if created else 'Refreshed'} CSV playlist '{name}' with {count} tracks."
		)

	def _switch_to_legacy_mode(self) -> None:
		"""Switch interfaces only; both modes continue using the shared core workers and settings."""
		log("library mode requested legacy interface")
		self.legacy_mode_requested.emit()
		self.accept()

	def _open_equalizer(self) -> None:
		if LibraryEqualizerDialog(self).exec():
			self.status.setText("Equalizer settings saved and will be applied to new downloads.")

	def _open_device_sync(self) -> None:
		DeviceSyncDialog(self.library, self).exec()

	def _open_tutorial(self) -> None:
		html = """
		<style>
			body { font-family: 'Comic Sans MS'; font-size: 11pt; color: #101010; }
			h2 { color: #000080; margin-top: 18px; }
			h3 { color: #006000; margin-top: 14px; }
			li { margin-bottom: 7px; }
			.note { background: #ffffcc; border: 1px solid #808000; padding: 8px; }
		</style>
		<h2>1. Add and scan a playlist</h2>
		<ol>
			<li>Paste a public Spotify, YouTube Music, or Apple Music playlist URL into <b>Add to library</b>.</li>
			<li>Press the green add button. A new, unscanned playlist appears in red.</li>
			<li>Press that playlist's green refresh button. Keep CSVMusic open while it captures and verifies the track list.</li>
			<li>When the scan finishes, review its captured count and any warning. Large song lists appear 200 at a time; use <b>Load More Songs</b> to browse farther.</li>
		</ol>
		<div class="note"><b>Regular YouTube playlists are allowed with a warning.</b> YouTube Music is recommended because ordinary videos often do not provide dependable song, artist, album, or artwork metadata. Carefully review imported results.</div>
		<h2>2. Choose songs and download</h2>
		<ol>
			<li>Click the playlist you want to work with. Only the selected playlist is downloaded.</li>
			<li>Use each song's checkbox to include or exclude it.</li>
			<li>Press <b>Download</b> or <b>Download Missing</b>. Review the settings, choose the output folder and format, then press <b>Start Download</b>.</li>
			<li>The Download Activity panel shows the target playlist, current track, progress, skipped matches, and failures.</li>
		</ol>
		<h2>3. Correct a song or adjust its volume</h2>
		<ol>
			<li>Press the gear beside a song.</li>
			<li>On <b>YouTube Match</b>, single-click a result. The yellow New Selection box confirms the pending choice. Double-click a result to preview it in your browser.</li>
			<li>On <b>Sound Level</b>, adjust that song from -12 dB to +12 dB.</li>
			<li>Press <b>Save</b> to mark the changed song for redownload. Cancel leaves its saved settings unchanged.</li>
		</ol>
		<h2>4. Keep the library current</h2>
		<ul>
			<li>Press a playlist's green refresh button after changing it on the source service.</li>
			<li><b>Download Missing</b> fetches newly added or replacement tracks without downloading existing files again.</li>
			<li>The red trash button permanently removes the playlist metadata and its downloaded output folder after confirmation.</li>
		</ul>
		<h2>Switch to the original interface</h2>
		<p>Press <b>Legacy Mode</b> in the top bar to return to the original non-library CSVMusic interface. Both interfaces use the same downloader, matching engine, FFmpeg processing, equalizer values, and saved tool settings.</p>
		<h2>Import a CSV with TuneMyMusic</h2>
		<p>CSV playlists work directly in Library Mode and use the same download, settings, and song-correction tools:</p>
		<ol>
			<li>Open <a href="https://www.tunemymusic.com/transfer">TuneMyMusic</a> and choose your music service as the source.</li>
			<li>Connect the source account if requested, then select the playlist or library items you need.</li>
			<li>Choose <b>Export to file</b> as the destination and select CSV.</li>
			<li>Download the completed CSV. Review the title and artist columns for mismatches.</li>
			<li>Return to Library Mode, press <b>Add CSV...</b>, and choose the exported file. It appears immediately as a populated library playlist.</li>
			<li>Use the CSV playlist's green refresh button later to reread changes from the same file.</li>
		</ol>
		<p>For a pasted text list, TuneMyMusic also offers an official <a href="https://www.tunemymusic.com/transfer/freetext-to-file">Free text to CSV exporter</a>.</p>
		"""
		LibraryGuideDialog("Library Mode Tutorial", "LIBRARY MODE TUTORIAL", html, self).exec()

	def _open_info(self) -> None:
		html = f"""
		<style>
			body {{ font-family: 'Comic Sans MS'; font-size: 11pt; color: #101010; }}
			h2 {{ color: #000080; margin-top: 18px; }}
			li {{ margin-bottom: 7px; }}
			.note {{ background: #ffffcc; border: 1px solid #808000; padding: 8px; }}
			.disclaimer-warning {{ background: #ffff99; border: 2px outset #ffffff; padding: 12px; margin-top: 12px; }}
			.disclaimer-throttle {{ background: #ffe0b2; border: 2px outset #ffffff; padding: 12px; margin-top: 12px; }}
			.disclaimer-info {{ background: #cce8ff; border: 2px outset #ffffff; padding: 12px; margin-top: 12px; }}
		</style>
		<h2>CSVMusic Library Mode v{APP_VERSION}</h2>
		<p>Library Mode keeps a reusable local catalog of playlists, tracks, artwork URLs, download choices, per-song volume adjustments, and download results.</p>
		<h2>Supported playlist sources</h2>
		<ul>
			<li>Public Spotify playlists, captured from Spotify's public web page without a Spotify developer application.</li>
			<li>YouTube Music playlists from music.youtube.com.</li>
			<li>Regular YouTube playlists after acknowledging that their song metadata may be inaccurate.</li>
			<li>Apple Music playlists that expose public metadata.</li>
			<li>TuneMyMusic, Exportify, and compatible CSVMusic CSV playlist files.</li>
		</ul>
		<div class="note">Regular YouTube playlists can be added after a warning, but ordinary video titles and channels cannot consistently identify the correct artist, song, album, or artwork. YouTube Music remains the more reliable option.</div>
		<h2>How matching and downloads work</h2>
		<p>Playlist services supply metadata and artwork. CSVMusic searches YouTube Music for audio matches, downloads through yt-dlp, processes and tags audio with FFmpeg, and stores each playlist in its own output folder.</p>
		<p>Automatic matching can be wrong. Use a song's gear button to preview alternatives and save the correct version before downloading again.</p>
		<p><b>Library Mode and Legacy Mode are two interfaces over the same core mechanics.</b> Downloader, matching, tagging, FFmpeg processing, tool paths, and equalizer settings remain shared so backend fixes apply to both modes.</p>
		<h2>Local data and privacy</h2>
		<ul>
			<li>The library database is stored locally at <code>{self.library_path}</code>.</li>
			<li>Spotify scraping uses a temporary unsigned browser profile and does not require Spotify credentials.</li>
			<li>Optional YouTube cookies and tool overrides are controlled in Advanced Settings.</li>
			<li>Deleting a playlist permanently removes its library metadata and its downloaded playlist folder. CSVMusic refuses deletion if another playlist shares that folder name.</li>
		</ul>
		<h2>Important limitations</h2>
		<ul>
			<li>Public websites can change their layout, rate-limit requests, or expose an incomplete list.</li>
			<li>Always review incomplete-scan warnings and captured totals before downloading.</li>
			<li>Only download media you are authorized to save and follow the source service's terms and applicable law.</li>
		</ul>
		<h2>Safety &amp; Support</h2>
		<div class="disclaimer-warning">
			<h2>1. Try to avoid enormous playlists</h2>
			Large playlists are supported, but they naturally require many more page loads, searches, downloads, and metadata operations. This means they can take a long time and are more likely to encounter incomplete public metadata, temporary service limits, or an interrupted scan.
		</div>
		<div class="disclaimer-throttle">
			<h2>2. YouTube requests and throttling</h2>
			YouTube sometimes slows or temporarily rejects repeated requests with HTTP 403 errors, rate limits, sign-in checks, or extraction failures. These are usually service protections rather than a broken playlist. CSVMusic adds pauses and throttling to reduce the chance, and waiting before retrying often helps.<br><br>
			<a href="https://github.com/yt-dlp/yt-dlp"><b>yt-dlp project</b></a> &nbsp;|&nbsp;
			<a href="https://github.com/yt-dlp/yt-dlp/wiki/FAQ"><b>yt-dlp FAQ</b></a>
		</div>
		<div class="disclaimer-info">
			<h2>3. Review automatic results</h2>
			Song matching and scraped metadata are not guaranteed to be correct. Review yellow low-confidence entries and use Song Settings to choose alternatives. Only download media you are authorized to access and use.
		</div>
		<div class="disclaimer-info">
			<h2>4. Need help?</h2>
			Open the Download Log and include the relevant error. Remove personal paths, cookies, tokens, or account details before sharing logs.<br><br>
			<a href="https://github.com/angall1/CSVMusic/issues"><b>Post a GitHub issue</b></a> &nbsp;|&nbsp;
			<a href="https://www.reddit.com/user/agalli/"><b>Message agalli on Reddit</b></a><br><br>
			<a href="https://buymeacoffee.com/agalli"><b>Enjoying CSVMusic? Buy me a coffee</b></a>
		</div>
		"""
		LibraryGuideDialog("About Library Mode", "LIBRARY MODE INFO", html, self).exec()

	def _open_settings(self, _checked: bool = False, *, download_confirmation: bool = False) -> bool:
		accepted = bool(LibrarySettingsDialog(self.library, self, download_confirmation=download_confirmation).exec())
		if accepted:
			self.output_label.setText(self.library.get("output_dir") or "No output folder selected")
			self.format_combo.setCurrentText(str(self.library.get("format") or "m4a"))
			self._save()
			self._update_download_target()
			self.status.setText("Library download settings saved.")
		return accepted

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
		host = QUrl(value).host().casefold().removeprefix("www.")
		if host in ("youtube.com", "youtu.be"):
			if not QUrlQuery(QUrl(value)).queryItemValue("list").strip():
				message = (
					"This is a single YouTube video link, not a playlist link. Open the playlist on YouTube and copy its URL. "
					"The correct address contains '?list=' or '&list=' followed by the playlist ID."
				)
				self.status.setText(message)
				QMessageBox.information(self, "Playlist Link Required", message)
				return
			warning = QMessageBox(self)
			warning.setIcon(QMessageBox.Warning)
			warning.setWindowTitle("Regular YouTube Playlist")
			warning.setText("Regular YouTube playlists may import inaccurate song information.")
			warning.setInformativeText(
				"Unlike YouTube Music, ordinary videos often have inconsistent titles, uploader names, albums, and artwork. "
				"CSVMusic will try to interpret them, but some songs may need manual title edits or replacement selections."
			)
			add_anyway = warning.addButton("Add Anyway", QMessageBox.AcceptRole)
			warning.addButton(QMessageBox.Cancel)
			warning.setDefaultButton(QMessageBox.Cancel)
			warning.exec()
			if warning.clickedButton() is not add_anyway:
				self.status.setText("YouTube playlist was not added.")
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
			self.status.setText("Playlist added. Press its green refresh button to scan tracks and cover art.")

	def _selected_ids(self) -> set[str]:
		return {str(item.data(0, Qt.UserRole)) for item in self.playlist_tree.selectedItems()}

	def _selected_playlists(self) -> list[dict]:
		selected = self._selected_ids()
		return [
			playlist for playlist in self.library.get("playlists", [])
			if f"{playlist.get('platform') or 'spotify'}:{playlist.get('id')}" in selected or str(playlist.get("id")) in selected
		]

	def _update_download_target(self) -> None:
		playlists = self._selected_playlists()
		if not playlists:
			self.download_target.setText("Target playlist: None selected")
			self.download_button.setText("Download")
			self.download_button.setEnabled(False)
			return
		names = [str(playlist.get("name") or "Unscanned Playlist") for playlist in playlists]
		label = names[0] if len(names) == 1 else f"{len(names)} playlists: " + ", ".join(names)
		self.download_target.setText(f"Target playlist: {label}")
		self.download_button.setText("Download")
		if not (self.download_worker and self.download_worker.isRunning()):
			self.download_button.setEnabled(True)

	def _rescan_all(self) -> None:
		self._begin_scan(list(self.library.get("playlists", [])))

	def _rescan_playlist(self, playlist_id: str) -> None:
		playlist = playlist_by_id(self.library, playlist_id)
		if playlist:
			self._begin_scan([playlist])

	def _begin_scan(self, playlists: list[dict]) -> None:
		if (self.scraper is not None and self.scraper.running) or self.direct_worker is not None:
			QMessageBox.information(self, "Scan Running", "A playlist scan is already running.")
			return
		if not playlists:
			QMessageBox.information(self, "No Playlists", "Select or add at least one playlist.")
			return
		self.scan_queue = list(playlists)
		self.scans_completed = 0
		self.scan_cancelled = False
		self.scan_warnings = []
		self.scan_results = []
		self.current_scan_name = ""
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
			if not self.scan_cancelled and self.scan_results:
				lines = []
				for result in self.scan_results:
					if result.get("error"):
						lines.append(f"✗ {result['name']}\n  Failed: {result['error']}")
						continue
					diff = result.get("diff") or {}
					captured = result.get("captured", 0)
					reported = result.get("reported") or captured
					lines.append(
						f"{'✓' if not result.get('warning') else '⚠'} {result['name']}\n"
						f"  Tracks: {captured}/{reported}  •  Added: {diff.get('added', 0)}  •  "
						f"Removed: {diff.get('removed', 0)}  •  Unchanged: {diff.get('unchanged', 0)}\n"
						f"  Downloaded: {result.get('downloaded', 0)}  •  Missing: {result.get('missing', 0)}"
						+ (f"\n  Warning: {result['warning']}" if result.get("warning") else "")
					)
				QMessageBox.information(self, "Rescan Summary", "\n\n".join(lines))
			return
		playlist = self.scan_queue.pop(0)
		self.current_scan_name = str(playlist.get("name") or playlist.get("id") or "Playlist")
		self.status.setText(f"Scanning {playlist.get('name') or playlist['id']} ({len(self.scan_queue)} remaining)...")
		is_spotify_album = playlist.get("platform") == "spotify" and playlist.get("source_type") == "album"
		if playlist.get("platform") in ("youtube_music", "youtube", "apple_music", "deezer", "amazon_music", "csv") or is_spotify_album:
			platform = "spotify_album" if is_spotify_album else str(playlist["platform"])
			self.direct_worker = DirectLibraryScanWorker(
				playlist.get("csv_path") or playlist["url"], platform, self, source_id=str(playlist.get("id") or "")
			)
			self.direct_worker.finished_scan.connect(self._scan_finished)
			self.direct_worker.start()
			if self.scan_dialog:
				self.scan_dialog.setRange(0, 0)
				self.scan_dialog.setLabelText(
					f"Playlist {self.scans_completed + 1}: {playlist.get('name') or playlist['id']}\n"
					f"Loading {'CSV' if platform == 'csv' else 'Spotify album' if platform == 'spotify_album' else 'Apple Music' if platform == 'apple_music' else 'Deezer' if platform == 'deezer' else 'Amazon Music' if platform == 'amazon_music' else 'YouTube' if platform == 'youtube' else 'YouTube Music'} metadata..."
				)
			return
		if self.scraper is None:
			self.scraper = SpotifyPublicScrapeDialog(self)
			self.scraper.scrape_finished.connect(self._scan_finished)
			self.scraper.scrape_progress.connect(self._scan_progress_changed)
			self.scraper.resize(1100, 780)
			log("library scan created reusable Spotify browser")
		else:
			log("library scan reusing Spotify browser for next playlist")
		self.scraper.setWindowTitle(f"Library Scan - {playlist.get('name') or playlist['id']}")
		self.scraper.url_input.setText(playlist["url"])
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
			self.scan_results.append({"name": self.current_scan_name or "Playlist", "error": str(data["error"])})
		playlist_id = str(data.get("id") or "")
		if not self.scan_cancelled and playlist_id and data.get("tracks"):
			message = str(data.get("message") or "")
			warning = None if data.get("complete") else message
			if warning:
				self.scan_warnings.append(f"{data.get('name') or playlist_id}: {warning}")
			target_id = f"{data.get('platform')}:{playlist_id}" if data.get("platform") else playlist_id
			merged = merge_playlist_scan(
				self.library,
				target_id,
				str(data.get("name") or "Spotify Playlist"),
				list(data.get("tracks") or []),
				reported_total=data.get("reported_total"),
				warning=warning,
				cover_url=data.get("cover_url"),
			)
			self._save()
			playlist_key = f"{merged.get('platform') or 'spotify'}:{merged.get('id')}"
			counts = library_status(
				self.library,
				self.library.get("output_dir") or "",
				self.format_combo.currentText(),
			).get("playlists", {}).get(playlist_key, {})
			self.scan_results.append({
				"name": str(merged.get("name") or data.get("name") or playlist_id),
				"captured": len(merged.get("tracks") or []),
				"reported": data.get("reported_total"),
				"diff": dict(merged.get("last_diff") or {}),
				"downloaded": int(counts.get("downloaded", 0) or 0),
				"missing": int(counts.get("missing", 0) or 0),
				"warning": warning,
			})
			log(f"library playlist scan merged id={playlist_id} tracks={len(data.get('tracks') or [])} complete={bool(data.get('complete'))}")
		is_direct_result = bool(data.get("direct"))
		if self.scraper and not is_direct_result:
			if self.scan_dialog:
				self.scan_dialog.detach_browser(self.scraper.browser, self.scraper)
			# Reuse the same QWebEngine profile for the next Spotify playlist.
			# Deleting it here can block Qt's event loop during Chromium teardown,
			# preventing the inter-playlist timer from ever firing.
			self.scraper.hide()
			log("library scan retained Spotify browser for reuse")
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
		output = str(self.library.get("output_dir") or "").strip()
		folder = pathlib.Path(output) / (sanitize_name(str(name)) or "Playlist") if output else None
		folder_note = f"\n\nDownloaded media and embedded artwork in this folder will also be permanently deleted:\n{folder}" if folder else ""
		if QMessageBox.question(
			self,
			"Delete Playlist and Downloads",
			f"Delete '{name}' from the library?{folder_note}\n\nThis cannot be undone.",
			QMessageBox.Yes | QMessageBox.No,
			QMessageBox.No,
		) != QMessageBox.Yes:
			return
		if folder and folder.exists():
			shared = [
				other for other in self.library.get("playlists", [])
				if other is not playlist and (sanitize_name(str(other.get("name") or "Playlist")) or "Playlist") == folder.name
			]
			if shared:
				QMessageBox.critical(
					self,
					"Shared Download Folder",
					"This playlist shares its download folder with another library playlist. Rename one playlist before deleting it so unrelated songs are not removed.",
				)
				return
			try:
				root = pathlib.Path(output).resolve()
				target = folder.resolve()
				if target.parent != root or target == root:
					raise ValueError("The playlist download folder is outside the configured output directory.")
				shutil.rmtree(target)
				log(f"library playlist files deleted playlist={name!r} path={target}")
			except Exception as exc:
				log(f"library playlist deletion failed playlist={name!r} path={folder} error={exc}")
				QMessageBox.critical(self, "Delete Failed", f"The downloaded files could not be removed, so the playlist was kept.\n\n{exc}")
				return
		art_urls = {str(playlist.get("cover_url") or "")}
		art_urls.update(str(track.get("cover_url") or "") for track in playlist.get("tracks", []))
		for url in art_urls:
			self.image_cache.pop(url, None)
			self.image_waiters.pop(url, None)
			self.image_queue = [queued for queued in self.image_queue if queued != url]
		self.library["playlists"] = [
			item for item in self.library.get("playlists", [])
			if f"{item.get('platform') or 'spotify'}:{item.get('id')}" != playlist_id and item.get("id") != playlist_id
		]
		self._save()
		self._refresh()
		self.status.setText(f"Deleted '{name}', its library metadata, and its downloaded media.")

	def _open_output_folder(self) -> None:
		output = str(self.library.get("output_dir") or "").strip()
		if not output:
			QMessageBox.information(self, "No Output Folder", "Choose an output folder in Download Settings first.")
			return
		folder = pathlib.Path(output).expanduser()
		try:
			folder.mkdir(parents=True, exist_ok=True)
			resolved = folder.resolve()
		except Exception as exc:
			QMessageBox.warning(self, "Open Output Failed", f"The output folder is unavailable:\n{folder}\n\n{exc}")
			return
		if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(resolved))):
			QMessageBox.warning(self, "Open Output Failed", f"Could not open:\n{resolved}")
			return
		log(f"library output folder opened path={resolved}")

	def _rename_playlist(self, playlist_id: str) -> None:
		playlist = playlist_by_id(self.library, playlist_id)
		if not playlist:
			return
		if self.download_worker and self.download_worker.isRunning():
			QMessageBox.information(self, "Download in Progress", "Wait for the current download to finish before renaming its playlist folder.")
			return
		old_name = str(playlist.get("name") or "Playlist")
		new_name, accepted = QInputDialog.getText(self, "Rename Playlist", "Playlist name:", text=old_name)
		if not accepted or new_name.strip() == old_name:
			return
		try:
			updated, folder = rename_library_playlist(
				self.library,
				playlist_id,
				new_name,
				self.library.get("output_dir") or None,
			)
			cfg = load_settings()
			m3u_output = str(cfg.get("m3u_output_dir") or "").strip()
			if m3u_output:
				playlist_output_dir = pathlib.Path(m3u_output)
				playlist_tracks = []
				for source_track in updated.get("tracks", []):
					if source_track.get("enabled", True):
						entry = dict(source_track)
						entry["playlist"] = updated["name"]
						playlist_tracks.append(entry)
				fmt = str(self.library.get("format") or "m4a")
				for suffix, setting, encoding in ((".m3u8", "write_m3u8", "utf-8"), (".m3u", "write_m3u_plain", "utf-8-sig")):
					old_file = playlist_output_dir / f"{sanitize_name(old_name)}{suffix}"
					if old_file.exists():
						old_file.unlink()
					if cfg.get(setting, setting == "write_m3u8"):
						write_m3u(pathlib.Path(self.library.get("output_dir") or ""), updated["name"], playlist_tracks, fmt, suffix=suffix, encoding=encoding, playlist_output_dir=playlist_output_dir)
			self._save()
		except Exception as exc:
			log(f"library playlist rename failed id={playlist_id} old={old_name!r} new={new_name!r} error={exc}")
			QMessageBox.critical(self, "Rename Failed", str(exc))
			return
		self._refresh()
		folder_note = f" Output folder: {folder}" if folder else ""
		self.status.setText(f"Renamed '{old_name}' to '{updated['name']}'.{folder_note}")
		log(f"library playlist renamed id={playlist_id} old={old_name!r} new={updated['name']!r} folder={folder}")

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
				0 if not playlist.get("last_scanned_at") else 1,
				-self._playlist_error_count(playlist),
				-int(status.get("playlists", {}).get(f"{playlist.get('platform') or 'spotify'}:{playlist.get('id')}", {}).get("missing", 0) or 0),
				str(playlist.get("name") or "").casefold(),
			),
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
				else "Unscanned YouTube Playlist" if playlist.get("platform") == "youtube"
				else "Unscanned CSV Playlist" if playlist.get("platform") == "csv"
				else "Unscanned Spotify Playlist"
			)
			item = QTreeWidgetItem([""])
			item.setData(0, Qt.UserRole, key)
			item.setToolTip(0, f"Last scanned: {last_scan}")
			error_count = self._playlist_error_count(playlist)
			missing_count = int(counts.get("missing", 0) or 0)
			redownload_count = int(counts.get("redownload", 0) or 0)
			unscanned = not bool(playlist.get("last_scanned_at"))
			incomplete_scan = bool(playlist.get("scan_warning")) or bool(total and track_count < total)
			item.setSizeHint(0, QSize(0, 78 if unscanned or incomplete_scan or redownload_count else 68))
			if unscanned:
				row_color = QColor("#e08080")
			elif incomplete_scan:
				row_color = QColor("#f0cf82")
			elif error_count:
				row_color = QColor("#dda0a0")
			elif redownload_count:
				row_color = QColor("#fff0a8")
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
			name_label = EditablePlaylistTitle(str(name))
			name_label.setWordWrap(False)
			name_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
			name_label.setFont(QFont("Comic Sans MS", 10, QFont.Bold))
			name_label.setFixedHeight(name_label.fontMetrics().lineSpacing() * 3)
			name_label.double_clicked.connect(lambda playlist_id=key: self._rename_playlist(str(playlist_id)))
			card_layout.addWidget(name_label, 1)
			status_layout = QVBoxLayout()
			status_layout.setSpacing(0)
			status_layout.setAlignment(Qt.AlignVCenter)
			tracks_label = QLabel("NOT SCANNED\nClick green ↻" if unscanned else f"{track_count}/{total} tracks")
			if unscanned:
				tracks_label.setStyleSheet("color: #700000; font-weight: bold; background: #ffd0a0; border: 1px solid #904000; padding: 3px;")
			status_labels = [tracks_label]
			scan_label = QLabel("INCOMPLETE SCAN") if incomplete_scan else None
			missing_label = QLabel(f"{missing_count} missing") if missing_count else None
			redownload_label = QLabel(f"{redownload_count} queued") if redownload_count else None
			error_label = QPushButton(f"{error_count} errors") if error_count else None
			if scan_label:
				scan_label.setStyleSheet("color: #704000; font-weight: bold;")
				scan_label.setToolTip(str(playlist.get("scan_warning") or "The captured track count is below Spotify's reported total."))
				status_labels.append(scan_label)
			if missing_label:
				status_labels.append(missing_label)
			if redownload_label:
				status_labels.append(redownload_label)
			if error_label:
				status_labels.append(error_label)
			for status_label in status_labels:
				status_label.setFont(QFont("Comic Sans MS", 9))
				status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
				status_label.setMinimumWidth(100 if unscanned else 112)
				status_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
			for status_label in status_labels:
				status_layout.addWidget(status_label)
			if error_count:
				error_label.setToolTip("View playlist download errors")
				error_label.setFixedHeight(28)
				error_label.clicked.connect(lambda _checked=False, source=playlist: self._show_playlist_errors(source))
			card_layout.addLayout(status_layout)
			playlist_status = QLabel()
			playlist_status.setFixedSize(26, 26)
			playlist_status.setAlignment(Qt.AlignCenter)
			playlist_status.setPixmap(_song_status_icon("warning" if unscanned or incomplete_scan or error_count or missing_count or redownload_count else "downloaded").pixmap(24, 24))
			playlist_status.setToolTip(
				"This playlist has not been scanned. Press the green refresh button." if unscanned
				else str(playlist.get("scan_warning") or "The playlist scan was incomplete. Rescan it.") if incomplete_scan
				else "One or more songs have download errors" if error_count
				else f"{missing_count} song(s) have no downloaded file" if missing_count
				else f"{redownload_count} song replacement(s) are queued" if redownload_count
				else "Every song has a downloaded file"
			)
			if not unscanned:
				card_layout.addWidget(playlist_status)
			refresh_button = QToolButton()
			refresh_button.setIcon(_playlist_action_icon("refresh"))
			refresh_button.setIconSize(QSize(28, 28))
			refresh_button.setToolTip("Scan this playlist now" if unscanned else "Rescan this playlist")
			refresh_button.setAccessibleName("Rescan playlist")
			refresh_button.setFixedSize(42, 42)
			refresh_button.setStyleSheet("QToolButton { color: white; background: #008000; }")
			refresh_button.clicked.connect(lambda _checked=False, playlist_id=key: self._rescan_playlist(str(playlist_id)))
			delete_button = QToolButton()
			delete_button.setIcon(_playlist_action_icon("delete"))
			delete_button.setIconSize(QSize(28, 28))
			delete_button.setToolTip("Remove this playlist")
			delete_button.setAccessibleName("Delete playlist")
			delete_button.setFixedSize(42, 42)
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
		self._update_download_target()
		totals = status.get("totals", {})
		if totals:
			self.status.setText(
				f"Tracks {totals.get('enabled', 0)} | Downloaded {totals.get('downloaded', 0)} | "
				f"Missing {totals.get('missing', 0)}"
			)

	def _show_tracks(self) -> None:
		ids = self._selected_ids()
		query = self.song_search.text().casefold().strip() if hasattr(self, "song_search") else ""
		selection_key = (frozenset(ids), query)
		if selection_key != self.shown_playlist_ids:
			self.shown_playlist_ids = selection_key
			self.track_display_limit = self.track_display_batch
		self.track_tree.blockSignals(True)
		self.track_tree.clear()
		self.track_art_targets.clear()
		self.track_state_labels.clear()
		self.track_cards.clear()
		output = pathlib.Path(self.library.get("output_dir") or "")
		fmt = self.format_combo.currentText()
		total_tracks = 0
		displayed_tracks = 0
		for playlist_id in ids:
			playlist = playlist_by_id(self.library, playlist_id)
			if not playlist:
				continue
			indexed_tracks = list(enumerate(playlist.get("tracks", [])))
			if query:
				indexed_tracks = [
					entry for entry in indexed_tracks
					if query in " ".join(str(entry[1].get(field) or "") for field in (
						"title", "artists", "album", "downloaded_video_title", "downloaded_video_publisher",
					)).casefold()
				]
			total_tracks += len(indexed_tracks)
			def issue_order(entry: tuple[int, dict]) -> int:
				_original_index, source_track = entry
				if source_track.get("low_confidence_review"):
					return 0
				if source_track.get("download_error") or source_track.get("last_error") or source_track.get("error"):
					return 1
				probe = dict(source_track)
				probe["playlist"] = playlist.get("name") or "Playlist"
				return 3 if library_track_path(probe, output, fmt).exists() else 2
			indexed_tracks.sort(key=issue_order)
			remaining = max(0, self.track_display_limit - displayed_tracks)
			for display_index, (index, track) in enumerate(indexed_tracks[:remaining], start=displayed_tracks):
				target_key = (str(playlist_id), index)
				candidate = dict(track)
				candidate["playlist"] = playlist.get("name") or "Playlist"
				has_error = bool(track.get("download_error") or track.get("last_error") or track.get("error"))
				needs_review = bool(track.get("low_confidence_review"))
				file_exists = library_track_path(candidate, output, fmt).exists()
				if needs_review:
					state = "Review"
				elif has_error:
					state = "Error"
				elif track.get("force_redownload"):
					state = "Redownload"
				elif file_exists:
					state = "Downloaded"
				else:
					state = "Missing"
				downloaded_title = str(track.get("downloaded_video_title") or "").strip() if file_exists else ""
				if downloaded_title.startswith(("http://", "https://")):
					downloaded_title = str(track.get("title") or "Downloaded song").strip()
				downloaded_publisher = str(track.get("downloaded_video_publisher") or "").strip() if file_exists else ""
				youtube_info = (
					f'Downloaded: "{downloaded_title}" - "{downloaded_publisher}"' if downloaded_title and downloaded_publisher
					else f'Downloaded: "{downloaded_title}"' if downloaded_title
					else ""
				)
				track_gain = int(track.get("audio_volume_gain", 0) or 0)
				if track_gain:
					gain_text = f"Song level: {track_gain:+d} dB"
					youtube_info = f"{youtube_info}  •  {gain_text}" if youtube_info else gain_text
				item = QTreeWidgetItem([""])
				item.setData(0, Qt.UserRole, (playlist_id, index))
				item.setSizeHint(0, QSize(0, 88))
				item.setData(0, Qt.UserRole + 1, str(track.get("cover_url") or ""))
				self.track_tree.addTopLevelItem(item)
				card = QFrame()
				card.setFont(QFont("Comic Sans MS", 9))
				card.setObjectName("songCard")
				runtime_state = self.download_track_states.get(target_key)
				if runtime_state in ("Matching", "Downloading", "Tagging"):
					state = runtime_state
				if runtime_state in ("Matching", "Downloading", "Tagging"):
					shade = "#fff0a8"
				elif needs_review:
					shade = "#fff0a8"
				elif state == "Error":
					shade = "#dda0a0"
				elif track.get("force_redownload"):
					shade = "#fff0a8"
				elif not file_exists:
					shade = "#e7bcbc"
				else:
					shade = "#c8ddc8" if display_index % 2 == 0 else "#b8ceb8"
				card.setStyleSheet(
					f"#songCard {{ background: {shade}; border-top: 2px solid #ffffff; border-left: 2px solid #ffffff; "
					"border-right: 2px solid #404040; border-bottom: 2px solid #404040; }"
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
				title_text = html.escape(str(track.get("title") or ""))
				artist_text = html.escape(str(track.get("artists") or ""))
				primary = EditableTrackText(f"<b>{title_text}</b> - {artist_text}")
				primary.setTextFormat(Qt.RichText)
				primary.setFont(QFont("Comic Sans MS", 10))
				primary.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
				primary.setTextInteractionFlags(Qt.TextSelectableByMouse)
				primary.setToolTip("Double-click to edit the song title and album")
				primary.double_clicked.connect(lambda playlist_key=str(playlist_id), track_index=index: self._edit_track_metadata(playlist_key, track_index))
				album_label = EditableTrackText(album or "No album listed")
				album_label.setFont(QFont("Comic Sans MS", 9))
				album_label.setStyleSheet("color: #303030;")
				album_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
				album_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
				album_label.setToolTip("Double-click to edit the song title and album")
				album_label.double_clicked.connect(lambda playlist_key=str(playlist_id), track_index=index: self._edit_track_metadata(playlist_key, track_index))
				download = QLabel(youtube_info)
				download_font = QFont("Comic Sans MS", 8)
				download_font.setBold(needs_review)
				download.setFont(download_font)
				download.setStyleSheet("color: #555555;")
				download.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
				download.setTextInteractionFlags(Qt.TextSelectableByMouse)
				text_column.addWidget(primary)
				text_column.addWidget(album_label)
				text_column.addWidget(download)
				card_layout.addLayout(text_column, 1)
				icon_kind = "downloaded" if file_exists and not has_error and not track.get("force_redownload") and not needs_review else "warning"
				status_icon = QLabel()
				status_icon.setFixedSize(26, 26)
				status_icon.setAlignment(Qt.AlignCenter)
				status_icon.setPixmap(_song_status_icon(icon_kind).pixmap(24, 24))
				status_icon.setToolTip(
					"Review this low-confidence downloaded match" if needs_review
					else "Last download failed" if has_error
					else "Replacement queued for the next Download run" if track.get("force_redownload")
					else "Audio file found" if icon_kind == "downloaded"
					else "Audio file is missing"
				)
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
				self.track_state_labels[target_key] = state_label
				self.track_cards[target_key] = card
				if needs_review:
					accept_button = QToolButton()
					accept_button.setText("✓")
					accept_button.setToolTip("Accept this low-confidence match")
					accept_button.setAccessibleName("Accept downloaded match")
					accept_button.setFixedSize(38, 38)
					accept_button.setStyleSheet("QToolButton { background: #008000; color: white; font-size: 22px; font-weight: bold; }")
					accept_button.clicked.connect(
						lambda _checked=False, playlist_key=str(playlist_id), track_index=index: self._accept_low_confidence(playlist_key, track_index)
					)
					card_layout.addWidget(accept_button)
					reject_button = QToolButton()
					reject_button.setText("✕")
					reject_button.setToolTip("Reject this match and choose an alternative")
					reject_button.setAccessibleName("Reject downloaded match")
					reject_button.setFixedSize(38, 38)
					reject_button.setStyleSheet("QToolButton { background: #c00000; color: white; font-size: 20px; font-weight: bold; }")
					reject_button.clicked.connect(lambda _checked=False, target=item: self._open_track_settings(target))
					card_layout.addWidget(reject_button)
				else:
					settings_button = QToolButton()
					settings_button.setIcon(_settings_icon())
					settings_button.setIconSize(QSize(24, 24))
					settings_button.setToolTip("Song settings: YouTube match and sound level")
					settings_button.setAccessibleName("Song settings")
					settings_button.setFixedSize(42, 42)
					settings_button.clicked.connect(lambda _checked=False, target=item: self._open_track_settings(target))
					card_layout.addWidget(settings_button)
				self.track_tree.setItemWidget(item, 0, card)
				self.track_art_targets[self.track_tree.indexOfTopLevelItem(item)] = art
				displayed_tracks += 1
		self.track_tree.blockSignals(False)
		remaining_tracks = max(0, total_tracks - displayed_tracks)
		self.load_more_tracks_button.setVisible(remaining_tracks > 0)
		self.load_more_tracks_button.setText(f"Load More Songs ({remaining_tracks} remaining)")
		self.track_art_timer.start(0)
		if (self.download_worker and self.download_worker.isRunning()) or (self.single_download_worker and self.single_download_worker.isRunning()):
			self._set_library_lists_locked(True)

	def _set_library_lists_locked(self, locked: bool) -> None:
		"""Lock row actions during downloads without disabling either scrollbar."""
		mode = QAbstractItemView.NoSelection if locked else QAbstractItemView.ExtendedSelection
		for tree in (self.playlist_tree, self.track_tree):
			tree.setSelectionMode(mode)
			tree.setEnabled(True)
			for row in range(tree.topLevelItemCount()):
				widget = tree.itemWidget(tree.topLevelItem(row), 0)
				if widget:
					widget.setEnabled(not locked)
		self.song_search.setEnabled(not locked)

	def _edit_track_metadata(self, playlist_id: str, track_index: int) -> None:
		if (self.download_worker and self.download_worker.isRunning()) or (self.single_download_worker and self.single_download_worker.isRunning()):
			QMessageBox.information(self, "Download in Progress", "Wait for the current download to finish before editing song metadata.")
			return
		playlist = playlist_by_id(self.library, playlist_id)
		if not playlist or track_index < 0 or track_index >= len(playlist.get("tracks", [])):
			return
		track = playlist["tracks"][track_index]
		dialog = QDialog(self)
		dialog.setWindowTitle("Edit Song Metadata")
		layout = QVBoxLayout(dialog)
		form = QFormLayout()
		title_edit = QLineEdit(str(track.get("title") or ""))
		album_edit = QLineEdit(str(track.get("album") or ""))
		form.addRow("Song title:", title_edit)
		form.addRow("Album:", album_edit)
		layout.addLayout(form)
		note = QLabel("These edits are saved with the library and kept when the playlist is rescanned.")
		note.setWordWrap(True)
		layout.addWidget(note)
		buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
		buttons.accepted.connect(dialog.accept)
		buttons.rejected.connect(dialog.reject)
		layout.addWidget(buttons)
		if dialog.exec() != QDialog.Accepted:
			return
		scroll_position = self.track_tree.verticalScrollBar().value()
		output_root = pathlib.Path(self.library.get("output_dir") or "")
		fmt = str(self.library.get("format") or self.format_combo.currentText() or "m4a")
		old_file_track = dict(track)
		old_file_track["playlist"] = playlist.get("name") or "Playlist"
		old_path = expected_track_path(old_file_track, output_root, fmt)
		try:
			updated = edit_library_track(self.library, playlist_id, track_index, title_edit.text(), album_edit.text())
			new_file_track = dict(updated)
			new_file_track["playlist"] = playlist.get("name") or "Playlist"
			new_path = expected_track_path(new_file_track, output_root, fmt)
			local_file_updated = False
			if old_path.exists():
				if old_path != new_path:
					if new_path.exists():
						raise FileExistsError(f"Cannot rename the audio file because '{new_path.name}' already exists.")
					new_path.parent.mkdir(parents=True, exist_ok=True)
					old_path.rename(new_path)
				tag_file(new_path, new_file_track, None)
				local_file_updated = True
			cfg = load_settings()
			playlist_tracks = []
			for source_track in playlist.get("tracks", []):
				if not source_track.get("enabled", True):
					continue
				playlist_track = dict(source_track)
				playlist_track["playlist"] = playlist.get("name") or "Playlist"
				playlist_tracks.append(playlist_track)
			if cfg.get("write_m3u8", True):
				write_m3u(output_root, playlist.get("name") or "Playlist", playlist_tracks, fmt, suffix=".m3u8", encoding="utf-8", playlist_output_dir=cfg.get("m3u_output_dir"))
			if cfg.get("write_m3u_plain", False):
				write_m3u(output_root, playlist.get("name") or "Playlist", playlist_tracks, fmt, suffix=".m3u", encoding="utf-8-sig", playlist_output_dir=cfg.get("m3u_output_dir"))
			self._save()
		except Exception as exc:
			QMessageBox.warning(self, "Edit Failed", str(exc))
			return
		self._refresh()
		QTimer.singleShot(0, lambda value=scroll_position: self.track_tree.verticalScrollBar().setValue(value))
		message = f"Updated metadata for '{updated['title']}'."
		if local_file_updated:
			message += " The existing audio file and playlist entry were updated locally."
		self.status.setText(message)

	def _accept_low_confidence(self, playlist_id: str, track_index: int) -> None:
		playlist = playlist_by_id(self.library, playlist_id)
		if not playlist or track_index < 0 or track_index >= len(playlist.get("tracks", [])):
			return
		track = playlist["tracks"][track_index]
		track["low_confidence_review"] = False
		self._save()
		self._refresh()
		self.status.setText(f"Accepted the downloaded match for '{track.get('title') or 'song'}'.")

	def _load_more_tracks(self) -> None:
		self.track_display_limit += self.track_display_batch
		self._show_tracks()

	def _open_track_settings(self, item: QTreeWidgetItem) -> None:
		self.track_tree.clearSelection()
		item.setSelected(True)
		playlist_id, index = item.data(0, Qt.UserRole)
		track = playlist_by_id(self.library, playlist_id)["tracks"][index]
		dialog = TrackAlternativesDialog(track, self)

		def _selected(video_id: str, label: str, volume_gain: int) -> None:
			scroll_position = self.track_tree.verticalScrollBar().value()
			old_video_id = str(track.get("preferred_video_id") or "")
			old_volume_gain = int(track.get("audio_volume_gain", 0) or 0)
			track["preferred_video_id"] = video_id or None
			track["preferred_video_label"] = label or None
			track["preferred_selection_locked"] = bool(video_id)
			track["audio_volume_gain"] = max(-12, min(12, int(volume_gain)))
			if old_video_id != video_id or old_volume_gain != track["audio_volume_gain"]:
				track["force_redownload"] = True
			self._save()
			self._refresh()
			QTimer.singleShot(0, lambda value=scroll_position: self.track_tree.verticalScrollBar().setValue(value))
			if old_video_id != video_id or old_volume_gain != track["audio_volume_gain"]:
				self.status.setText(
					f"Saved a replacement for '{track.get('title') or 'song'}'. "
					"It is queued for the next Download run."
				)

		dialog.selected.connect(_selected)
		dialog.exec()

	def _start_alternative_download(self, playlist_id: str, index: int, video_id: str, label: str) -> None:
		if self.download_worker and self.download_worker.isRunning():
			QMessageBox.information(self, "Download in Progress", "The alternative was saved and will be used next time. Wait for the current playlist download to finish before replacing this song.")
			return
		if self.single_download_worker and self.single_download_worker.isRunning():
			QMessageBox.information(self, "Song Download in Progress", "Wait for the current replacement song to finish downloading.")
			return
		playlist = playlist_by_id(self.library, playlist_id)
		if not playlist or not (0 <= index < len(playlist.get("tracks", []))):
			return
		output = str(self.library.get("output_dir") or "").strip()
		if not output:
			QMessageBox.information(self, "No Output Folder", "The alternative was saved. Choose an output folder in Download Settings before downloading it.")
			return
		track = dict(playlist["tracks"][index])
		track["playlist"] = playlist.get("name") or "Playlist"
		track["library_playlist_id"] = playlist_id
		track["library_track_index"] = index
		clean_title = str(label or "").strip()
		if clean_title.startswith(("http://", "https://")):
			clean_title = str(track.get("title") or "Selected alternative")
		match = {"videoId": video_id, "title": clean_title, "author": track.get("artists") or ""}
		cfg = load_settings()
		audio = {}
		if cfg.get("eq_enabled"):
			audio = {
				"enabled": True,
				"normalize": bool(cfg.get("eq_normalize", False)),
				"volume_gain": int(cfg.get("eq_volume_gain", 0) or 0),
				"bass_gain": int(cfg.get("eq_bass_gain", 0) or 0),
				"treble_gain": int(cfg.get("eq_treble_gain", 0) or 0),
			}
		track_gain = int(track.get("audio_volume_gain", 0) or 0)
		if track_gain:
			audio["enabled"] = True
			audio["volume_gain"] = int(audio.get("volume_gain", 0) or 0) + track_gain
		legacy = {
			"enabled": bool(cfg.get("legacy_ipod_mode", False)),
			"mp3_mode": cfg.get("legacy_mp3_mode") or "vbr",
			"cover_art_mode": cfg.get("legacy_cover_art_mode") or "standard",
		}
		fmt = str(self.library.get("format") or "m4a")
		target = (playlist_id, index)
		self.download_track_states[target] = "Downloading"
		self._show_tracks()
		self._set_library_lists_locked(True)
		self.download_button.setEnabled(False)
		use_cookies = bool(cfg.get("use_cookies", False))
		worker = SingleDownloadWorker(
			index, track, match, output, fmt, bool(cfg.get("embed_art", True)),
			cfg.get("yt_dlp_path"), cfg.get("ffmpeg_path"),
			cfg.get("cookies_browser") if use_cookies else None,
			cfg.get("cookies_file") if use_cookies else None,
			audio_processing=audio, mp3_quality=int(cfg.get("mp3_quality", 0) or 0),
			legacy_options=legacy, force_download=True, parent=self,
		)
		self.single_download_worker = worker
		worker.sig_status.connect(lambda _row, status, selected=target: self._single_download_status(selected, status))
		worker.sig_finished.connect(lambda _row, payload, selected=target: self._single_download_finished(selected, payload))
		worker.finished.connect(self._single_download_thread_finished)
		self.download_activity.setText(f"Replacing with selected alternative: {clean_title}")
		worker.start()

	def _single_download_status(self, target: tuple[str, int], status: str) -> None:
		self.download_track_states[target] = self._compact_download_status(status)
		label = self.track_state_labels.get(target)
		if label:
			label.setText(self.download_track_states[target])
		card = self.track_cards.get(target)
		if card:
			card.setStyleSheet("#songCard { background: #fff0a8; border: 2px outset #ffffff; }")
		self.download_activity.setText(status)

	def _single_download_finished(self, target: tuple[str, int], payload: dict) -> None:
		track = payload.get("track") or {}
		record_library_download_result(
			self.library_path, target[0], track,
			downloaded=bool(payload.get("downloaded")), error=payload.get("error"), match=payload.get("match"),
			low_confidence=bool(payload.get("low_confidence")), confidence=payload.get("confidence"),
		)
		self.download_track_states.pop(target, None)
		self.library = load_library(self.library_path)
		self._show_tracks()
		if payload.get("downloaded"):
			self.download_activity.setText(f"Downloaded selected alternative: {(payload.get('match') or {}).get('title') or track.get('title')}")
		else:
			self.download_activity.setText(f"Alternative download failed: {payload.get('error') or 'Unknown error'}")

	def _single_download_thread_finished(self) -> None:
		if self.single_download_worker:
			self.single_download_worker.deleteLater()
		self.single_download_worker = None
		self._set_library_lists_locked(False)
		self.download_button.setEnabled(True)

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
		track["preferred_selection_locked"] = bool(video_id)
		track["force_redownload"] = bool(video_id)
		self._save()
		self._refresh()

	def _export_csv(self) -> None:
		path, _ = QFileDialog.getSaveFileName(self, "Export Library CSV", str(self.library_path.with_suffix(".csv")), "CSV (*.csv)")
		if path:
			export_csv(path, self.library, self._selected_ids() or None)
			self.status.setText(f"Exported enabled tracks to {path}")

	def _start_download(self) -> None:
		if (self.download_worker and self.download_worker.isRunning()) or (self.single_download_worker and self.single_download_worker.isRunning()):
			return
		if not self._selected_ids():
			QMessageBox.information(self, "Select Playlist", "Select the playlist you want to download first.")
			return
		if not self._open_settings(download_confirmation=True):
			return
		selected_ids = self._selected_ids()
		selected_playlists = self._selected_playlists()
		if not selected_ids or not selected_playlists:
			QMessageBox.information(self, "Select Playlist", "Select the playlist you want to download first.")
			return
		output = str(self.library.get("output_dir") or "").strip()
		if not output:
			return
		fmt = str(self.library.get("format") or "m4a")
		all_playlist_tracks = enabled_tracks(self.library, selected_ids)
		tracks = list(all_playlist_tracks)
		output_path = pathlib.Path(output)
		tracks = [track for track in tracks if track.get("force_redownload") or not library_track_path(track, output_path, fmt).exists()]
		if not tracks:
			QMessageBox.information(self, "Playlist Current", "All enabled tracks in the selected playlist are already downloaded.")
			return
		for track in tracks:
			track["library_path"] = str(self.library_path)
		cfg = load_settings()
		use_cookies = bool(cfg.get("use_cookies", False))
		batch_policy = youtube_batch_mitigation(
			len(tracks),
			using_cookies=bool(use_cookies and (cfg.get("cookies_browser") or cfg.get("cookies_file"))),
		)
		risk_message = youtube_risk_acknowledgement(batch_policy)
		if risk_message:
			choice = QMessageBox.question(
				self,
				"YouTube Risk Warning",
				risk_message,
				QMessageBox.Yes | QMessageBox.No,
				QMessageBox.No,
			)
			if choice != QMessageBox.Yes:
				self.download_activity.setText("Download cancelled after YouTube risk warning.")
				self.download_detail.setText("No YouTube requests were started.")
				log(f"library download cancelled at risk acknowledgement tracks={len(tracks)}")
				return
			self.download_detail.setText(
				f"YouTube protection active: randomized waits and reduced request rate ({batch_policy.label})."
			)
		audio = {}
		if cfg.get("eq_enabled"):
			audio = {
				"enabled": True,
				"normalize": bool(cfg.get("eq_normalize", False)),
				"volume_gain": int(cfg.get("eq_volume_gain", 0) or 0),
				"bass_gain": int(cfg.get("eq_bass_gain", 0) or 0),
				"treble_gain": int(cfg.get("eq_treble_gain", 0) or 0),
			}
		legacy = {
			"enabled": bool(cfg.get("legacy_ipod_mode", False)),
			"mp3_mode": cfg.get("legacy_mp3_mode") or "vbr",
			"cover_art_mode": cfg.get("legacy_cover_art_mode") or "standard",
		}
		target_names = [str(playlist.get("name") or "Unscanned Playlist") for playlist in selected_playlists]
		target_text = target_names[0] if len(target_names) == 1 else f"{len(target_names)} playlists: " + ", ".join(target_names)
		self.download_row_targets = {
			row: (str(track.get("library_playlist_id") or ""), int(track.get("library_track_index", -1)))
			for row, track in enumerate(tracks)
		}
		self.download_track_states = {target: "Queued" for target in self.download_row_targets.values()}
		self.download_log_dialog.begin_run(target_text, len(tracks))
		self.download_log_dialog.append("note", f"Format: {fmt.upper()} | Output: {output}")
		if batch_policy.active:
			self.download_log_dialog.append("warning", f"YouTube throttling profile enabled: {batch_policy.label}")
		for target in self.download_row_targets.values():
			label = self.track_state_labels.get(target)
			if label:
				label.setText("Queued")
				label.setToolTip("Queued for download")
		self.download_worker = PipelineWorker(
			"", output, None, fmt,
			bool(cfg.get("write_m3u8", True)), bool(cfg.get("write_m3u_plain", False)),
			bool(cfg.get("embed_art", True)), cfg.get("yt_dlp_path"), cfg.get("ffmpeg_path"),
			cfg.get("cookies_browser") if use_cookies else None,
			cfg.get("cookies_file") if use_cookies else None,
			audio_processing=audio, mp3_quality=int(cfg.get("mp3_quality", 0) or 0),
			legacy_options=legacy, force_download=bool(cfg.get("force_download_mode", False)),
			tracks_override=tracks, m3u_tracks_override=all_playlist_tracks,
			m3u_output_dir=cfg.get("m3u_output_dir"),
			row_indices=list(range(len(tracks))), parent=self,
		)
		self.download_worker.sig_total.connect(self._download_total)
		self.download_worker.sig_log.connect(self._download_log_message)
		self.download_worker.sig_progress.connect(self._download_progressed)
		self.download_worker.sig_row_status.connect(self._download_track_status)
		self.download_worker.sig_warning.connect(self._show_download_warning)
		self.download_worker.sig_track_result.connect(self._download_track_result)
		self.download_worker.sig_done.connect(self._download_done)
		self.download_button.setEnabled(False)
		self.stop_download_button.setEnabled(True)
		self._set_library_lists_locked(True)
		self.load_more_tracks_button.setEnabled(False)
		self.download_target.setText(f"Downloading playlist: {target_text}")
		self.download_activity.setText(f"Starting {len(tracks)} track(s) from {target_text}...")
		self.download_progress.setRange(0, len(tracks))
		self.download_progress.setValue(0)
		log(f"library download started tracks={len(tracks)} output={output} format={fmt}")
		self.download_worker.start()

	def _download_total(self, total: int) -> None:
		self.download_progress.setRange(0, max(1, total))

	def _download_progressed(self, processed: int, total: int) -> None:
		self.download_progress.setRange(0, max(1, total))
		self.download_progress.setValue(processed)
		self.download_progress.setFormat(f"{processed} / {total}")

	def _download_track_status(self, row: int, status: str) -> None:
		self.download_activity.setText(f"Track {row + 1}: {status}")
		self.download_log_dialog.append("note", f"Track {row + 1}: {status}")
		target = self.download_row_targets.get(row)
		compact = self._compact_download_status(status)
		if target:
			self.download_track_states[target] = compact
		label = self.track_state_labels.get(target) if target else None
		if label:
			label.setText(compact)
			label.setToolTip(status)
		card = self.track_cards.get(target) if target else None
		if card and compact in ("Matching", "Downloading", "Tagging"):
			card.setStyleSheet(
				"#songCard { background: #fff0a8; border-top: 2px solid #ffffff; border-left: 2px solid #ffffff; "
				"border-right: 2px solid #806000; border-bottom: 2px solid #806000; }"
			)

	@staticmethod
	def _compact_download_status(status: str) -> str:
		lower = status.casefold()
		if lower.startswith("fail") or "failed" in lower:
			return "Failed"
		if lower.startswith("done") or "low confidence" in lower:
			return "Done"
		if "tagging" in lower:
			return "Tagging"
		if "download" in lower or "trying" in lower or "safe mode" in lower:
			return "Downloading"
		if "search" in lower or "match" in lower:
			return "Matching"
		if "skip" in lower:
			return "Skipped"
		return status[:18]

	def _download_log_message(self, message: str) -> None:
		level = "warning" if "[warn]" in message.casefold() else "note"
		self.download_log_dialog.append(level, message)

	def _show_download_warning(self, message: str) -> None:
		self.download_detail.setText(message)
		self.download_log_dialog.append("warning", message)
		QMessageBox.warning(self, "YouTube Throttling Detected", message)

	def _download_track_result(self, row: int, payload: dict) -> None:
		track = payload.get("track") or {}
		if payload.get("error"):
			self.download_log_dialog.append(
				"error",
				f"{track.get('artists') or 'Unknown artist'} — {track.get('title') or 'Unknown song'}: {payload['error']}",
			)
		if track.get("library_playlist_id") and (payload.get("downloaded") or payload.get("error")):
			record_library_download_result(
				self.library_path, track["library_playlist_id"], track,
				downloaded=bool(payload.get("downloaded")), error=payload.get("error"), match=payload.get("match"),
				low_confidence=bool(payload.get("low_confidence")), confidence=payload.get("confidence"),
			)
			target = self.download_row_targets.get(row)
			if target:
				self.download_track_states.pop(target, None)
			try:
				self.library = load_library(self.library_path)
			except Exception as exc:
				log(f"library live reload after track download failed error={exc}")
			self._show_tracks()

	def _download_done(self, message: str, done: list, skipped: list, failed: list) -> None:
		log(f"library download finished downloaded={len(done)} skipped={len(skipped)} failed={len(failed)}")
		self.download_activity.setText(message)
		self.download_detail.setText(f"Downloaded {len(done)} • Skipped {len(skipped)} • Failed {len(failed)}")
		self.download_log_dialog.append("note", f"Finished: downloaded {len(done)}, skipped {len(skipped)}, failed {len(failed)}")
		self.download_button.setEnabled(True)
		self.stop_download_button.setEnabled(False)
		self._set_library_lists_locked(False)
		self.load_more_tracks_button.setEnabled(True)
		self.download_worker = None
		self.download_row_targets.clear()
		self.download_track_states.clear()
		try:
			self.library = load_library(self.library_path)
		except Exception as exc:
			log(f"library reload after download failed error={exc}")
		self._refresh()

	def _stop_download(self) -> None:
		if self.download_worker and self.download_worker.isRunning():
			self.download_activity.setText("Stopping after the current operation...")
			self.download_worker.stop()

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
		if self.download_worker and self.download_worker.isRunning():
			self.download_worker.stop()
			self.status.setText("Stopping the current download before closing...")
			event.ignore()
			return
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
