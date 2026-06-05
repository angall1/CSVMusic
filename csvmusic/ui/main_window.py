# tabs only
import pathlib
import sqlite3
from functools import partial
from typing import List, Tuple
from PySide6.QtWidgets import (
	QMainWindow, QWidget, QFileDialog, QMessageBox,
	QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
	QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox,
	QRadioButton, QButtonGroup, QProgressBar, QToolButton, QSizePolicy, QFrame,
	QComboBox, QSlider, QDialog
)
from PySide6.QtCore import Qt, QSignalBlocker, QUrl, Signal, QRect, QSize
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap, QFontDatabase, QGuiApplication, QDesktopServices, QPainter, QPen

from csvmusic.core.csv_import import load_csv, tracks_from_csv
from csvmusic.core.settings import load_settings, save_settings
from csvmusic.core.downloader import sanitize_name, youtube_batch_mitigation
from csvmusic.core.preflight import run_preflight_checks
from csvmusic.core.paths import app_icon_path, resource_base
from csvmusic.ui.workers import PipelineWorker, SingleDownloadWorker, CookiesCheckWorker, AlternativesFetchWorker
from csvmusic.core.browsers import list_profiles

YELLOW = QColor(255, 244, 179)   # soft yellow
RED = QColor(255, 205, 210)      # soft red
GREEN = QColor(200, 230, 201)    # soft green

class NotchedSlider(QWidget):
	valueChanged = Signal(int)

	def __init__(self, orientation: Qt.Orientation = Qt.Horizontal, parent: QWidget | None = None):
		super().__init__(parent)
		self._orientation = orientation
		self._minimum = 0
		self._maximum = 100
		self._value = 0
		self._tick_interval = 1
		self.setMouseTracking(True)

	def setRange(self, minimum: int, maximum: int) -> None:
		self._minimum = int(minimum)
		self._maximum = max(int(maximum), self._minimum)
		self.setValue(self._value)
		self.update()

	def setMinimum(self, minimum: int) -> None:
		self.setRange(minimum, self._maximum)

	def setMaximum(self, maximum: int) -> None:
		self.setRange(self._minimum, maximum)

	def setValue(self, value: int) -> None:
		value = max(self._minimum, min(self._maximum, int(value)))
		if value == self._value:
			self.update()
			return
		self._value = value
		self.valueChanged.emit(value)
		self.update()

	def value(self) -> int:
		return self._value

	def setTickInterval(self, interval: int) -> None:
		self._tick_interval = max(1, int(interval))
		self.update()

	def setTickPosition(self, _position) -> None:
		self.update()

	def setSingleStep(self, _step: int) -> None:
		pass

	def setPageStep(self, _step: int) -> None:
		pass

	def _groove_rect(self) -> QRect:
		margin_x = 12
		groove_h = 4
		return QRect(margin_x, (self.height() - groove_h) // 2, max(1, self.width() - (margin_x * 2)), groove_h)

	def _handle_rect(self) -> QRect:
		groove = self._groove_rect()
		x = self._value_to_x(self._value)
		handle_w = 12
		handle_h = 24
		return QRect(x - (handle_w // 2), groove.center().y() - (handle_h // 2), handle_w, handle_h)

	def _value_to_x(self, value: int) -> int:
		groove = self._groove_rect()
		span = max(1, self._maximum - self._minimum)
		ratio = (value - self._minimum) / span
		return groove.left() + int(round(ratio * groove.width()))

	def _x_to_value(self, x: int) -> int:
		groove = self._groove_rect()
		if groove.width() <= 0:
			return self._minimum
		clamped = max(groove.left(), min(groove.right(), x))
		ratio = (clamped - groove.left()) / groove.width()
		return int(round(self._minimum + (self._maximum - self._minimum) * ratio))

	def mousePressEvent(self, event) -> None:
		if event.button() == Qt.LeftButton and self._orientation == Qt.Horizontal:
			self.setValue(self._x_to_value(int(event.position().x())))
			event.accept()
			return
		super().mousePressEvent(event)

	def mouseMoveEvent(self, event) -> None:
		if event.buttons() & Qt.LeftButton and self._orientation == Qt.Horizontal:
			self.setValue(self._x_to_value(int(event.position().x())))
			event.accept()
			return
		super().mouseMoveEvent(event)

	def paintEvent(self, _event) -> None:
		painter = QPainter(self)
		painter.setRenderHint(QPainter.Antialiasing, False)
		groove = self._groove_rect()
		handle = self._handle_rect()
		panel = QColor("#d4d0c8") if self.isEnabled() else QColor("#c0c0c0")
		shadow = QColor("#808080")
		dark = QColor("#404040")
		light = QColor("#ffffff")
		tick = QColor("#6c6c6c") if self.isEnabled() else QColor("#9a9a9a")

		painter.fillRect(groove, panel)
		painter.setPen(QPen(dark, 1))
		painter.drawLine(groove.left(), groove.top(), groove.right(), groove.top())
		painter.drawLine(groove.left(), groove.top(), groove.left(), groove.bottom())
		painter.setPen(QPen(light, 1))
		painter.drawLine(groove.left(), groove.bottom(), groove.right(), groove.bottom())
		painter.drawLine(groove.right(), groove.top(), groove.right(), groove.bottom())

		painter.setPen(QPen(tick, 1))
		step = max(1, self._tick_interval)
		for value in range(self._minimum, self._maximum + 1, step):
			x = self._value_to_x(value)
			painter.drawLine(x, groove.top() - 6, x, groove.top() - 2)
			painter.drawLine(x, groove.bottom() + 2, x, groove.bottom() + 6)

		painter.fillRect(handle, panel)
		painter.setPen(QPen(light, 1))
		painter.drawLine(handle.left(), handle.top(), handle.right(), handle.top())
		painter.drawLine(handle.left(), handle.top(), handle.left(), handle.bottom())
		painter.setPen(QPen(shadow, 1))
		painter.drawLine(handle.right(), handle.top(), handle.right(), handle.bottom())
		painter.drawLine(handle.left(), handle.bottom(), handle.right(), handle.bottom())
		painter.setPen(QPen(dark, 1))
		center_x = handle.center().x()
		painter.drawLine(center_x - 1, handle.top() + 4, center_x - 1, handle.bottom() - 4)
		painter.drawLine(center_x + 1, handle.top() + 4, center_x + 1, handle.bottom() - 4)

class RetroRadioButton(QRadioButton):
	def sizeHint(self) -> QSize:
		fm = self.fontMetrics()
		indicator = 18
		gap = 10
		height = max(24, indicator + 6, fm.height() + 8)
		width = indicator + gap + fm.horizontalAdvance(self.text()) + 12
		return QSize(width, height)

	def paintEvent(self, _event) -> None:
		painter = QPainter(self)
		painter.setRenderHint(QPainter.Antialiasing, False)
		panel = QColor("#d4d0c8")
		light = QColor("#ffffff")
		dark = QColor("#404040")
		shadow = QColor("#808080")
		text_color = QColor("#000000") if self.isEnabled() else QColor("#808080")
		indicator = 18
		left = 2
		top = max(2, (self.height() - indicator) // 2)
		rect = QRect(left, top, indicator, indicator)

		painter.setPen(light)
		painter.drawArc(rect, 45 * 16, 180 * 16)
		painter.drawArc(rect, 135 * 16, 180 * 16)
		inner = rect.adjusted(1, 1, -1, -1)
		painter.setPen(dark)
		painter.drawArc(inner, 225 * 16, 180 * 16)
		painter.drawArc(inner, 315 * 16, 180 * 16)
		fill = rect.adjusted(2, 2, -2, -2)
		painter.fillRect(fill, panel)

		if self.isChecked():
			dot = rect.adjusted(4, 4, -4, -4)
			painter.setPen(Qt.NoPen)
			painter.setBrush(QColor("#101010"))
			painter.drawEllipse(dot)

		text_x = rect.right() + 11
		text_rect = QRect(text_x, 0, max(1, self.width() - text_x), self.height())
		painter.setPen(text_color)
		painter.setFont(self.font())
		painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self.text())

		if self.hasFocus():
			painter.setPen(QPen(shadow, 1, Qt.DotLine))
			painter.setBrush(Qt.NoBrush)
			painter.drawRect(text_rect.adjusted(1, 3, -2, -4))

class MainWindow(QMainWindow):
	def __init__(self):
		super().__init__()
		self._scale = self._compute_scale_factor()
		self.setWindowTitle("CSVMusic")
		min_w, min_h = self._clamp_to_screen(760, 520)
		self.setMinimumSize(min_w, min_h)
		init_w, init_h = self._clamp_to_screen(self._px(980), self._px(640))
		self.resize(max(min_w, init_w), max(min_h, init_h))

		self.worker: PipelineWorker | None = None
		self.tracks: list[dict] = []
		self.total = 0
		self.track_results: dict[int, dict] = {}
		self.action_buttons: dict[int, QPushButton] = {}
		self.resolve_items: dict[int, dict] = {}
		self.manual_download_workers: dict[int, SingleDownloadWorker] = {}
		self.last_playlist_name: str | None = None
		self._allow_path_persist = False
		self.cookie_check_worker: CookiesCheckWorker | None = None
		icon_p = app_icon_path()
		if icon_p:
			self.setWindowIcon(QIcon(str(icon_p)))
		self._row_icon_size = self._px(28)
		self._default_track_icon = QIcon()
		if icon_p:
			pm = QPixmap(str(icon_p))
			if not pm.isNull():
				self._default_track_icon = QIcon(pm.scaled(
					self._row_icon_size,
					self._row_icon_size,
					Qt.KeepAspectRatio,
					Qt.SmoothTransformation
				))

		root = QWidget(self); self.setCentralWidget(root)
		vl = QVBoxLayout(root)
		vl.setSpacing(self._px(8))
		win_base = "#c0c0c0"
		win_panel = "#d4d0c8"
		win_text = "#000000"
		win_light = "#ffffff"
		win_shadow = "#808080"
		win_dark = "#404040"
		progress_chunk = "#000080"
		font_candidate = "MS Sans Serif"
		fonts_dir = resource_base() / "fonts"
		vcr_path = fonts_dir / "VCR_OSD_MONO.ttf"
		if vcr_path.exists():
			font_id = QFontDatabase.addApplicationFont(str(vcr_path))
			if font_id != -1:
				families = QFontDatabase.applicationFontFamilies(font_id)
				if families:
					font_candidate = families[0]
		self._retro_font_family = font_candidate if font_candidate in QFontDatabase().families() else "Tahoma"
		self._readable_font_family = self._pick_readable_font_family()
		self._default_pt = max(self.font().pointSize(), 9)
		self._root_widget = root
		self._base_stylesheet_template = f"""
			QWidget {{
				background-color: {win_base};
				color: {win_text};
				font-family: '__FONT_FAMILY__';
			}}
			QLineEdit, QComboBox, QTableWidget {{
				background-color: {win_panel};
				color: {win_text};
				border-top: {self._px(2)}px solid {win_light};
				border-left: {self._px(2)}px solid {win_light};
				border-right: {self._px(2)}px solid {win_shadow};
				border-bottom: {self._px(2)}px solid {win_shadow};
				selection-background-color: #000080;
				selection-color: #ffffff;
			}}
			QTableWidget QHeaderView::section {{
				background-color: {win_panel};
				color: {win_text};
				border: {self._px(1)}px solid {win_shadow};
			}}
			QScrollBar {{ background: {win_panel}; }}
			QPushButton {{
				background-color: {win_panel};
				color: {win_text};
				border-top: {self._px(2)}px solid {win_light};
				border-left: {self._px(2)}px solid {win_light};
				border-right: {self._px(2)}px solid {win_dark};
				border-bottom: {self._px(2)}px solid {win_dark};
				padding: {self._px(4)}px {self._px(12)}px;
				min-height: {self._px(18)}px;
			}}
			QPushButton:disabled {{
				color: #808080;
				border-top: {self._px(2)}px solid {win_light};
				border-left: {self._px(2)}px solid {win_light};
				border-right: {self._px(2)}px solid {win_shadow};
				border-bottom: {self._px(2)}px solid {win_shadow};
			}}
			QPushButton:pressed {{
				border-top: {self._px(2)}px solid {win_dark};
				border-left: {self._px(2)}px solid {win_dark};
				border-right: {self._px(2)}px solid {win_light};
				border-bottom: {self._px(2)}px solid {win_light};
			}}
			QToolButton {{
				background-color: {win_panel};
				color: {win_text};
				border-top: {self._px(2)}px solid {win_light};
				border-left: {self._px(2)}px solid {win_light};
				border-right: {self._px(2)}px solid {win_dark};
				border-bottom: {self._px(2)}px solid {win_dark};
				padding: {self._px(4)}px {self._px(10)}px;
				min-height: {self._px(18)}px;
			}}
			QToolButton:pressed, QToolButton:checked {{
				border-top: {self._px(2)}px solid {win_dark};
				border-left: {self._px(2)}px solid {win_dark};
				border-right: {self._px(2)}px solid {win_light};
				border-bottom: {self._px(2)}px solid {win_light};
				padding-left: {self._px(11)}px;
				padding-top: {self._px(5)}px;
				padding-right: {self._px(9)}px;
				padding-bottom: {self._px(3)}px;
			}}
			QToolButton:disabled {{
				color: #808080;
				border-top: {self._px(2)}px solid {win_light};
				border-left: {self._px(2)}px solid {win_light};
				border-right: {self._px(2)}px solid {win_shadow};
				border-bottom: {self._px(2)}px solid {win_shadow};
			}}
			QCheckBox, QRadioButton {{
				color: {win_text};
			}}
			QRadioButton::indicator {{
				width: {self._px(14)}px;
				height: {self._px(14)}px;
				border-top: {self._px(2)}px solid {win_light};
				border-left: {self._px(2)}px solid {win_light};
				border-right: {self._px(2)}px solid {win_dark};
				border-bottom: {self._px(2)}px solid {win_dark};
				background-color: {win_panel};
				border-radius: {self._px(7)}px;
			}}
			QRadioButton::indicator:checked {{
				background-color: {win_panel};
				image: none;
				border-top: {self._px(2)}px solid {win_dark};
				border-left: {self._px(2)}px solid {win_dark};
				border-right: {self._px(2)}px solid {win_light};
				border-bottom: {self._px(2)}px solid {win_light};
			}}
			QProgressBar {{
				background-color: {win_panel};
				color: {win_text};
				border-top: {self._px(2)}px solid {win_light};
				border-left: {self._px(2)}px solid {win_light};
				border-right: {self._px(2)}px solid {win_shadow};
				border-bottom: {self._px(2)}px solid {win_shadow};
				height: {self._px(18)}px;
			}}
			QProgressBar::chunk {{
				background-color: {progress_chunk};
			}}
			QSlider::groove:horizontal {{
				background-color: #8b877f;
				border-top: {self._px(1)}px solid {win_dark};
				border-left: {self._px(1)}px solid {win_dark};
				border-right: {self._px(1)}px solid {win_light};
				border-bottom: {self._px(1)}px solid {win_light};
				height: {self._px(4)}px;
				margin: {self._px(10)}px 0 {self._px(8)}px 0;
			}}
			QSlider::handle:horizontal {{
				background-color: {win_light};
				border-top: {self._px(2)}px solid {win_light};
				border-left: {self._px(2)}px solid {win_light};
				border-right: {self._px(2)}px solid {win_dark};
				border-bottom: {self._px(2)}px solid {win_dark};
				width: {self._px(8)}px;
				margin: {self._px(-10)}px 0 {self._px(-10)}px 0;
			}}
			QSlider::sub-page:horizontal {{
				background-color: #8b877f;
			}}
			QSlider::add-page:horizontal {{
				background-color: #8b877f;
			}}
		"""
		retro_font_family = self._retro_font_family
		default_pt = self._default_pt
		self._readability_mode = False
		self.setFont(QFont(retro_font_family, default_pt))
		self._root_widget.setStyleSheet(self._base_stylesheet_template.replace("__FONT_FAMILY__", retro_font_family))

		# ── Title header: icon + name ────────────────────────────────────────────
		title_row = QHBoxLayout()
		title_row.setSpacing(self._px(8))
		logo = QLabel()
		icon_path = app_icon_path()
		if icon_path:
			pm = QPixmap(str(icon_path))
			if not pm.isNull():
				logo_size = self._px(40)
				logo.setPixmap(pm.scaled(logo_size, logo_size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
				logo.setFixedSize(logo_size, logo_size)
				logo.setStyleSheet("background: transparent;")
		else:
			logo.setFixedSize(self._px(40), self._px(40))
		logo.setAlignment(Qt.AlignCenter)
		title_block = QVBoxLayout()
		title_block.setSpacing(0)
		title_label = QLabel("CSVMusic")
		title_font = QFont(retro_font_family, default_pt + 6, QFont.Bold)
		title_label.setFont(title_font)
		title_label.setStyleSheet("color: #000000;")
		title_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
		tagline = QLabel("CSV playlist downloader")
		tagline.setFont(QFont(retro_font_family, default_pt + 1))
		tagline.setStyleSheet("color: #404040;")
		title_block.addWidget(title_label)
		title_block.addWidget(tagline)
		title_row.addWidget(logo)
		title_row.addLayout(title_block)
		title_row.addStretch(1)
		vl.addLayout(title_row)

		# ── Top help row: link + utility toggles ──────────────────────────────────
		top = QHBoxLayout()
		top.setSpacing(self._px(6))
		lbl_link = QLabel('<a href="https://www.tunemymusic.com/home">TuneMyMusic (export CSV)</a>')
		link_font = QFont(retro_font_family, default_pt + 3, QFont.Bold)
		lbl_link.setFont(link_font)
		lbl_link.setOpenExternalLinks(False)
		lbl_link.setTextInteractionFlags(Qt.LinksAccessibleByMouse | Qt.LinksAccessibleByKeyboard)
		lbl_link.linkActivated.connect(self.on_open_external_link)
		lbl_link.setStyleSheet("a { color: #000080; text-decoration: none; }")
		top.addWidget(lbl_link)
		btn_help = QToolButton()
		btn_help.setText("TUTORIAL ▸")
		btn_help.setCheckable(True)
		btn_help.setToolButtonStyle(Qt.ToolButtonTextOnly)
		btn_font = QFont(retro_font_family, default_pt + 1, QFont.Bold)
		btn_help.setFont(btn_font)
		self.btn_tutorial = btn_help
		self._button_font = btn_font
		top.addStretch(1)
		top.addWidget(btn_help)
		btn_load = QToolButton()
		btn_load.setText("LOAD PLAYLIST ▸")
		btn_load.setCheckable(True)
		btn_load.setToolButtonStyle(Qt.ToolButtonTextOnly)
		btn_load.setFont(btn_font)
		self.btn_load_existing = btn_load
		top.addWidget(btn_load)
		btn_eq = QToolButton()
		btn_eq.setText("EQUALIZER ▸")
		btn_eq.setCheckable(True)
		btn_eq.setToolButtonStyle(Qt.ToolButtonTextOnly)
		btn_eq.setFont(btn_font)
		self.btn_equalizer = btn_eq
		top.addWidget(btn_eq)
		btn_adv = QToolButton()
		btn_adv.setText("SETTINGS ▸")
		btn_adv.setCheckable(True)
		btn_adv.setToolButtonStyle(Qt.ToolButtonTextOnly)
		btn_adv.setFont(btn_font)
		self.btn_advanced = btn_adv
		top.addWidget(btn_adv)
		vl.addLayout(top)

		self.help_panel = QFrame()
		self.help_panel.setFrameShape(QFrame.StyledPanel)
		help_layout = QVBoxLayout(self.help_panel)
		help_layout.setContentsMargins(self._px(12), self._px(10), self._px(12), self._px(10))
		help_layout.setSpacing(self._px(8))
		help_heading = QLabel("Export one playlist as CSV, then import it here.")
		help_heading.setFont(QFont(retro_font_family, default_pt + 2, QFont.Bold))
		help_heading.setWordWrap(True)
		help_layout.addWidget(help_heading)
		help_intro = QLabel("Follow these steps:")
		help_intro.setFont(QFont(retro_font_family, default_pt + 1))
		help_layout.addWidget(help_intro)
		help_steps_box = QFrame()
		help_steps_box.setFrameShape(QFrame.StyledPanel)
		steps_layout = QVBoxLayout(help_steps_box)
		steps_layout.setContentsMargins(self._px(10), self._px(8), self._px(10), self._px(8))
		steps_layout.setSpacing(self._px(6))
		for line in (
			"1. Click the TuneMyMusic link above.",
			"2. Select your music platform.",
			"3. Paste your playlist URL.",
			"4. Choose Export to file → CSV.",
			"5. Save the CSV, then select it in CSVMusic.",
		):
			step_label = QLabel(line)
			step_label.setFont(QFont(retro_font_family, default_pt + 1))
			step_label.setWordWrap(True)
			steps_layout.addWidget(step_label)
		help_layout.addWidget(help_steps_box)
		help_tip_heading = QLabel("Tips")
		help_tip_heading.setFont(QFont(retro_font_family, default_pt + 2, QFont.Bold))
		help_layout.addWidget(help_tip_heading)
		help_tips_box = QFrame()
		help_tips_box.setFrameShape(QFrame.StyledPanel)
		tips_layout = QVBoxLayout(help_tips_box)
		tips_layout.setContentsMargins(self._px(10), self._px(8), self._px(10), self._px(8))
		tips_layout.setSpacing(self._px(6))
		for line in (
			"• Use EQUALIZER for volume matching, gain, bass, or treble changes.",
			"• Use LOAD PLAYLIST when the folder already has songs and you only want the missing ones.",
			"• LOAD PLAYLIST accepts the playlist CSV plus the output folder, playlist folder, or that playlist's .m3u/.m3u8 file.",
		):
			tip_label = QLabel(line)
			tip_label.setFont(QFont(retro_font_family, default_pt + 1))
			tip_label.setWordWrap(True)
			tips_layout.addWidget(tip_label)
		help_layout.addWidget(help_tips_box)
		self.help_panel.setVisible(False)
		vl.addWidget(self.help_panel)
		def _toggle_help(checked: bool):
			self._toggle_top_dialog(btn_help, self.help_dialog, "TUTORIAL", checked)
		btn_help.toggled.connect(_toggle_help)

		self.load_panel = QFrame()
		self.load_panel.setFrameShape(QFrame.StyledPanel)
		load_layout = QVBoxLayout(self.load_panel)
		load_layout.setContentsMargins(self._px(12), self._px(10), self._px(12), self._px(10))
		load_layout.setSpacing(self._px(10))
		load_heading = QLabel("Refresh an existing playlist folder")
		load_heading.setFont(QFont(retro_font_family, default_pt + 4, QFont.Bold))
		load_layout.addWidget(load_heading)
		load_note = QLabel("Point CSVMusic at the original playlist CSV and the folder that already contains the downloaded songs.")
		load_note.setWordWrap(True)
		load_note.setFont(QFont(retro_font_family, default_pt + 1))
		load_layout.addWidget(load_note)
		csv_section = QFrame()
		csv_section.setFrameShape(QFrame.StyledPanel)
		csv_layout = QVBoxLayout(csv_section)
		csv_layout.setContentsMargins(self._px(10), self._px(8), self._px(10), self._px(8))
		csv_layout.setSpacing(self._px(6))
		lbl_load_csv = QLabel("1. Playlist CSV")
		lbl_load_csv.setFont(QFont(retro_font_family, default_pt + 2, QFont.Bold))
		csv_layout.addWidget(lbl_load_csv)
		self.ed_load_csv = QLineEdit()
		self.ed_load_csv.setPlaceholderText("CSV for the playlist you want to refresh")
		self.ed_load_csv.setFont(QFont(retro_font_family, default_pt + 1))
		csv_layout.addWidget(self.ed_load_csv)
		load_row_csv = QHBoxLayout()
		btn_load_csv = QPushButton("Browse…")
		btn_load_csv.setFont(btn_font)
		btn_load_csv.clicked.connect(self.on_browse_load_csv)
		load_row_csv.addWidget(btn_load_csv)
		load_row_csv.addStretch(1)
		csv_layout.addLayout(load_row_csv)
		load_layout.addWidget(csv_section)
		source_section = QFrame()
		source_section.setFrameShape(QFrame.StyledPanel)
		source_layout = QVBoxLayout(source_section)
		source_layout.setContentsMargins(self._px(10), self._px(8), self._px(10), self._px(8))
		source_layout.setSpacing(self._px(6))
		lbl_load_source = QLabel("2. Current music location")
		lbl_load_source.setFont(QFont(retro_font_family, default_pt + 2, QFont.Bold))
		source_layout.addWidget(lbl_load_source)
		self.ed_load_source = QLineEdit()
		self.ed_load_source.setPlaceholderText("Playlist folder, output folder, or that playlist's .m3u/.m3u8 file")
		self.ed_load_source.setFont(QFont(retro_font_family, default_pt + 1))
		source_layout.addWidget(self.ed_load_source)
		load_row_source = QHBoxLayout()
		btn_load_source = QPushButton("Browse…")
		btn_load_source.setFont(btn_font)
		btn_load_source.clicked.connect(self.on_browse_load_source)
		load_row_source.addWidget(btn_load_source)
		load_row_source.addStretch(1)
		source_layout.addLayout(load_row_source)
		load_hint = QLabel("Accepted locations: the output folder, the playlist folder, or that playlist's .m3u/.m3u8 file.")
		load_hint.setFont(QFont(retro_font_family, default_pt + 1))
		load_hint.setWordWrap(True)
		source_layout.addWidget(load_hint)
		load_layout.addWidget(source_section)
		action_section = QFrame()
		action_section.setFrameShape(QFrame.StyledPanel)
		action_layout = QVBoxLayout(action_section)
		action_layout.setContentsMargins(self._px(10), self._px(8), self._px(10), self._px(8))
		action_layout.setSpacing(self._px(6))
		lbl_load_action = QLabel("3. Scan existing files")
		lbl_load_action.setFont(QFont(retro_font_family, default_pt + 2, QFont.Bold))
		action_layout.addWidget(lbl_load_action)
		load_action_row = QHBoxLayout()
		self.btn_scan_existing = QPushButton("Load Existing Playlist")
		self.btn_scan_existing.setFont(QFont(retro_font_family, default_pt + 2, QFont.Bold))
		self.btn_scan_existing.clicked.connect(self.on_load_playlist)
		load_action_row.addWidget(self.btn_scan_existing)
		load_action_row.addStretch(1)
		action_layout.addLayout(load_action_row)
		load_warning = QLabel("The selected CSV must match the playlist folder you are scanning.")
		load_warning.setFont(QFont(retro_font_family, default_pt))
		load_warning.setWordWrap(True)
		action_layout.addWidget(load_warning)
		load_layout.addWidget(action_section)
		self.load_panel.setVisible(False)
		vl.addWidget(self.load_panel)
		def _toggle_load_panel(checked: bool):
			self._toggle_top_dialog(btn_load, self.load_dialog, "LOAD PLAYLIST", checked)
		btn_load.toggled.connect(_toggle_load_panel)

		self.equalizer_panel = QFrame()
		self.equalizer_panel.setFrameShape(QFrame.StyledPanel)
		eq_layout = QVBoxLayout(self.equalizer_panel)
		eq_layout.setContentsMargins(self._px(12), self._px(10), self._px(12), self._px(10))
		eq_layout.setSpacing(self._px(8))
		eq_note = QLabel("Optional FFmpeg audio processing. EQ is applied before track loudness leveling.")
		eq_note.setWordWrap(True)
		eq_note.setFont(QFont(retro_font_family, default_pt))
		eq_layout.addWidget(eq_note)
		self.cb_eq_enabled = QCheckBox("Equalizer ON")
		self.cb_eq_enabled.setFont(QFont(retro_font_family, default_pt + 3, QFont.Bold))
		self.cb_eq_enabled.toggled.connect(self._set_equalizer_controls_enabled)
		self.cb_eq_enabled.toggled.connect(lambda _=None: self._persist_settings())
		eq_layout.addWidget(self.cb_eq_enabled)
		self.cb_eq_normalize = QCheckBox("Match volume between tracks")
		self.cb_eq_normalize.setFont(QFont(retro_font_family, default_pt + 1, QFont.Bold))
		self.cb_eq_normalize.toggled.connect(lambda _=None: self._persist_settings())
		eq_layout.addWidget(self.cb_eq_normalize)
		self.slider_volume, self.lbl_volume_value, self.lbl_volume = self._make_eq_slider(eq_layout, "Output Gain", retro_font_family, default_pt)
		self.slider_bass, self.lbl_bass_value, self.lbl_bass = self._make_eq_slider(eq_layout, "Bass", retro_font_family, default_pt)
		self.slider_treble, self.lbl_treble_value, self.lbl_treble = self._make_eq_slider(eq_layout, "Treble", retro_font_family, default_pt)
		self._equalizer_child_controls = [
			self.cb_eq_normalize,
			self.lbl_volume,
			self.slider_volume,
			self.lbl_volume_value,
			self.lbl_bass,
			self.slider_bass,
			self.lbl_bass_value,
			self.lbl_treble,
			self.slider_treble,
			self.lbl_treble_value,
		]
		self._set_equalizer_controls_enabled(False)
		self.equalizer_panel.setVisible(False)
		vl.addWidget(self.equalizer_panel)
		def _toggle_equalizer(checked: bool):
			self._toggle_top_dialog(btn_eq, self.equalizer_dialog, "EQUALIZER", checked)
		btn_eq.toggled.connect(_toggle_equalizer)

		self.advanced_panel = QFrame()
		self.advanced_panel.setFrameShape(QFrame.StyledPanel)
		adv_layout = QVBoxLayout(self.advanced_panel)
		adv_layout.setContentsMargins(self._px(14), self._px(12), self._px(14), self._px(12))
		adv_layout.setSpacing(self._px(12))
		settings_heading = QLabel("Settings")
		settings_heading.setFont(QFont(retro_font_family, default_pt + 4, QFont.Bold))
		adv_layout.addWidget(settings_heading)
		note = QLabel("These overrides are optional. Leave blank to use the bundled defaults.")
		note.setWordWrap(True)
		note.setFont(QFont(retro_font_family, default_pt + 1))
		adv_layout.addWidget(note)
		settings_columns = QHBoxLayout()
		settings_columns.setSpacing(self._px(12))
		adv_layout.addLayout(settings_columns, 1)
		settings_left = QVBoxLayout()
		settings_left.setSpacing(self._px(12))
		settings_right = QVBoxLayout()
		settings_right.setSpacing(self._px(12))
		settings_columns.addLayout(settings_left, 1)
		settings_columns.addLayout(settings_right, 1)

		display_section = QFrame()
		display_section.setFrameShape(QFrame.StyledPanel)
		display_layout = QVBoxLayout(display_section)
		display_layout.setContentsMargins(self._px(12), self._px(10), self._px(12), self._px(10))
		display_layout.setSpacing(self._px(8))
		display_heading = QLabel("Display")
		display_heading.setFont(QFont(retro_font_family, default_pt + 3, QFont.Bold))
		display_layout.addWidget(display_heading)
		self.cb_readability_mode = QCheckBox("Readable text")
		self.cb_readability_mode.setFont(QFont(retro_font_family, default_pt + 1, QFont.Bold))
		self.cb_readability_mode.toggled.connect(self.on_toggle_readability_mode)
		display_layout.addWidget(self.cb_readability_mode)
		display_note = QLabel("Switches popup windows and the main app to a cleaner system font.")
		display_note.setWordWrap(True)
		display_note.setFont(QFont(retro_font_family, default_pt))
		display_layout.addWidget(display_note)
		settings_left.addWidget(display_section)

		paths_section = QFrame()
		paths_section.setFrameShape(QFrame.StyledPanel)
		paths_layout = QVBoxLayout(paths_section)
		paths_layout.setContentsMargins(self._px(12), self._px(10), self._px(12), self._px(10))
		paths_layout.setSpacing(self._px(8))
		paths_heading = QLabel("Tool paths")
		paths_heading.setFont(QFont(retro_font_family, default_pt + 3, QFont.Bold))
		paths_layout.addWidget(paths_heading)
		lbl_ytdlp = QLabel("yt-dlp path:")
		lbl_ytdlp.setFont(QFont(retro_font_family, default_pt + 2, QFont.Bold))
		paths_layout.addWidget(lbl_ytdlp)
		self.ed_ytdlp = QLineEdit()
		self.ed_ytdlp.setPlaceholderText("Auto-detect from PATH")
		self.ed_ytdlp.setFont(QFont(retro_font_family, default_pt + 1))
		self.ed_ytdlp.textChanged.connect(lambda _=None: self._persist_settings())
		paths_layout.addWidget(self.ed_ytdlp)
		row_ytdlp = QHBoxLayout()
		row_ytdlp.setSpacing(self._px(6))
		btn_ytdlp = QPushButton("Browse…")
		btn_ytdlp.setFont(btn_font)
		btn_ytdlp.clicked.connect(self.on_browse_ytdlp)
		btn_ytdlp_clear = QPushButton("Clear")
		btn_ytdlp_clear.setFont(btn_font)
		btn_ytdlp_clear.clicked.connect(self.on_clear_ytdlp)
		row_ytdlp.addWidget(btn_ytdlp)
		row_ytdlp.addWidget(btn_ytdlp_clear)
		row_ytdlp.addStretch(1)
		paths_layout.addLayout(row_ytdlp)
		paths_layout.addSpacing(self._px(4))
		lbl_ffmpeg = QLabel("FFmpeg path:")
		lbl_ffmpeg.setFont(QFont(retro_font_family, default_pt + 2, QFont.Bold))
		paths_layout.addWidget(lbl_ffmpeg)
		self.ed_ffmpeg = QLineEdit()
		self.ed_ffmpeg.setPlaceholderText("Uses bundled binary by default")
		self.ed_ffmpeg.setFont(QFont(retro_font_family, default_pt + 1))
		self.ed_ffmpeg.textChanged.connect(lambda _=None: self._persist_settings())
		paths_layout.addWidget(self.ed_ffmpeg)
		row_ffmpeg = QHBoxLayout()
		row_ffmpeg.setSpacing(self._px(6))
		btn_ffmpeg = QPushButton("Browse…")
		btn_ffmpeg.setFont(btn_font)
		btn_ffmpeg.clicked.connect(self.on_browse_ffmpeg)
		btn_ffmpeg_clear = QPushButton("Clear")
		btn_ffmpeg_clear.setFont(btn_font)
		btn_ffmpeg_clear.clicked.connect(self.on_clear_ffmpeg)
		row_ffmpeg.addWidget(btn_ffmpeg)
		row_ffmpeg.addWidget(btn_ffmpeg_clear)
		row_ffmpeg.addStretch(1)
		paths_layout.addLayout(row_ffmpeg)
		settings_left.addWidget(paths_section)

		audio_section = QFrame()
		audio_section.setFrameShape(QFrame.StyledPanel)
		audio_layout = QVBoxLayout(audio_section)
		audio_layout.setContentsMargins(self._px(12), self._px(10), self._px(12), self._px(10))
		audio_layout.setSpacing(self._px(8))
		audio_heading = QLabel("Audio defaults")
		audio_heading.setFont(QFont(retro_font_family, default_pt + 3, QFont.Bold))
		audio_layout.addWidget(audio_heading)
		lbl_mp3_quality = QLabel("MP3 quality")
		lbl_mp3_quality.setFont(QFont(retro_font_family, default_pt + 2, QFont.Bold))
		audio_layout.addWidget(lbl_mp3_quality)
		row_mp3_quality = QHBoxLayout()
		row_mp3_quality.setSpacing(self._px(10))
		self.slider_mp3_quality = NotchedSlider(Qt.Horizontal)
		self.slider_mp3_quality.setRange(0, 10)
		self.slider_mp3_quality.setValue(0)
		self.slider_mp3_quality.setTickInterval(1)
		self.slider_mp3_quality.setMaximumWidth(self._px(360))
		self.slider_mp3_quality.setMinimumHeight(self._px(34))
		self.slider_mp3_quality.valueChanged.connect(self._on_mp3_quality_changed)
		self.lbl_mp3_quality_value = QLabel("0 = Best")
		self.lbl_mp3_quality_value.setMinimumWidth(self._px(116))
		self.lbl_mp3_quality_value.setFont(QFont(retro_font_family, default_pt + 1))
		row_mp3_quality.addWidget(self.slider_mp3_quality, 1)
		row_mp3_quality.addWidget(self.lbl_mp3_quality_value)
		row_mp3_quality.addStretch(1)
		audio_layout.addLayout(row_mp3_quality)
		lbl_mp3_quality_note = QLabel(
			"Only applies to MP3 output. 0 = best quality / largest files. 10 = worst quality / smallest files."
		)
		lbl_mp3_quality_note.setWordWrap(True)
		lbl_mp3_quality_note.setFont(QFont(retro_font_family, default_pt))
		audio_layout.addWidget(lbl_mp3_quality_note)
		audio_layout.addSpacing(self._px(4))
		self.cb_force_download = QCheckBox("Force download low-confidence matches")
		self.cb_force_download.setFont(QFont(retro_font_family, default_pt + 1, QFont.Bold))
		self.cb_force_download.toggled.connect(lambda _=None: self._persist_settings())
		audio_layout.addWidget(self.cb_force_download)
		force_note = QLabel("If no confident match is found, CSVMusic will still download the best result from YouTube / YouTube Music and mark that row in yellow.")
		force_note.setWordWrap(True)
		force_note.setFont(QFont(retro_font_family, default_pt))
		audio_layout.addWidget(force_note)
		settings_left.addWidget(audio_section)
		legacy_section = QFrame()
		legacy_section.setFrameShape(QFrame.StyledPanel)
		legacy_layout = QVBoxLayout(legacy_section)
		legacy_layout.setContentsMargins(self._px(12), self._px(10), self._px(12), self._px(10))
		legacy_layout.setSpacing(self._px(8))
		legacy_heading = QLabel("Legacy iPod")
		legacy_heading.setFont(QFont(retro_font_family, default_pt + 3, QFont.Bold))
		legacy_layout.addWidget(legacy_heading)
		self.cb_legacy_ipod_mode = QCheckBox("Legacy iPod mode")
		self.cb_legacy_ipod_mode.setFont(QFont(retro_font_family, default_pt + 1, QFont.Bold))
		self.cb_legacy_ipod_mode.toggled.connect(self.on_toggle_legacy_ipod_mode)
		legacy_layout.addWidget(self.cb_legacy_ipod_mode)
		legacy_note = QLabel("Applies older-device-friendly MP3 defaults and safer artwork handling for classic iPods and similar players.")
		legacy_note.setWordWrap(True)
		legacy_note.setFont(QFont(retro_font_family, default_pt))
		legacy_layout.addWidget(legacy_note)
		lbl_legacy_mp3 = QLabel("MP3 encoding")
		lbl_legacy_mp3.setFont(QFont(retro_font_family, default_pt + 2, QFont.Bold))
		legacy_layout.addWidget(lbl_legacy_mp3)
		self.combo_legacy_mp3_mode = QComboBox()
		self.combo_legacy_mp3_mode.setFont(QFont(retro_font_family, default_pt + 1))
		self.combo_legacy_mp3_mode.addItem("Use current VBR setting", "vbr")
		self.combo_legacy_mp3_mode.addItem("CBR 192 kbps", "cbr_192")
		self.combo_legacy_mp3_mode.addItem("CBR 256 kbps", "cbr_256")
		self.combo_legacy_mp3_mode.addItem("CBR 320 kbps", "cbr_320")
		self.combo_legacy_mp3_mode.currentIndexChanged.connect(lambda _=None: self._persist_settings())
		legacy_layout.addWidget(self.combo_legacy_mp3_mode)
		lbl_legacy_art = QLabel("Album art")
		lbl_legacy_art.setFont(QFont(retro_font_family, default_pt + 2, QFont.Bold))
		legacy_layout.addWidget(lbl_legacy_art)
		self.combo_legacy_cover_art = QComboBox()
		self.combo_legacy_cover_art.setFont(QFont(retro_font_family, default_pt + 1))
		self.combo_legacy_cover_art.addItem("Standard 600x600", "standard")
		self.combo_legacy_cover_art.addItem("Medium 450x450", "medium")
		self.combo_legacy_cover_art.addItem("Small 300x300", "small")
		self.combo_legacy_cover_art.addItem("Disable embedded art", "off")
		self.combo_legacy_cover_art.currentIndexChanged.connect(lambda _=None: self._persist_settings())
		legacy_layout.addWidget(self.combo_legacy_cover_art)
		legacy_tip = QLabel("If an iPod freezes on some songs, try CBR 192 kbps and Small 300x300 artwork first.")
		legacy_tip.setWordWrap(True)
		legacy_tip.setFont(QFont(retro_font_family, default_pt))
		legacy_layout.addWidget(legacy_tip)
		settings_right.addWidget(legacy_section)
		# Firefox is the only browser-cookie path reliable enough to expose directly.
		self._detected_firefox_profile: str | None = None
		self._cookies_test_ok = False
		cookies_section = QFrame()
		cookies_section.setFrameShape(QFrame.StyledPanel)
		cookies_layout = QVBoxLayout(cookies_section)
		cookies_layout.setContentsMargins(self._px(12), self._px(10), self._px(12), self._px(10))
		cookies_layout.setSpacing(self._px(8))
		cookies_heading = QLabel("YouTube cookies")
		cookies_heading.setFont(QFont(retro_font_family, default_pt + 3, QFont.Bold))
		cookies_layout.addWidget(cookies_heading)
		row_firefox = QHBoxLayout()
		row_firefox.setSpacing(self._px(8))
		lbl_firefox = QLabel("YouTube login:")
		lbl_firefox.setFont(QFont(retro_font_family, default_pt + 2, QFont.Bold))
		self.cb_use_cookies = QCheckBox("Use Cookies")
		self.cb_use_cookies.setFont(QFont(retro_font_family, default_pt + 1, QFont.Bold))
		self.cb_use_cookies.setEnabled(False)
		self.cb_use_cookies.toggled.connect(lambda _=None: self._persist_settings())
		row_firefox.addWidget(lbl_firefox)
		row_firefox.addWidget(self.cb_use_cookies)
		row_firefox.addStretch(1)
		cookies_layout.addLayout(row_firefox)
		row_firefox_buttons = QHBoxLayout()
		row_firefox_buttons.setSpacing(self._px(6))
		self.btn_detect_firefox_cookies = QPushButton("Detect Cookies from Firefox")
		self.btn_detect_firefox_cookies.setFont(btn_font)
		self.btn_detect_firefox_cookies.clicked.connect(self.on_detect_firefox_cookies)
		self.btn_test_cookies = QPushButton("Test Cookies")
		self.btn_test_cookies.setFont(btn_font)
		self.btn_test_cookies.clicked.connect(self.on_test_cookies)
		row_firefox_buttons.addWidget(self.btn_detect_firefox_cookies)
		row_firefox_buttons.addWidget(self.btn_test_cookies)
		row_firefox_buttons.addStretch(1)
		cookies_layout.addLayout(row_firefox_buttons)
		lbl_ff_tip = QLabel("Cookies help with age-restricted or sign-in-only YouTube results. Sign into YouTube in Firefox, click Detect, then Test. The Use Cookies checkbox unlocks only after the test passes. <a href=\"https://www.mozilla.org/firefox/download/\">Get Firefox</a>")
		lbl_ff_tip.setOpenExternalLinks(False)
		lbl_ff_tip.setTextInteractionFlags(Qt.LinksAccessibleByMouse | Qt.LinksAccessibleByKeyboard)
		lbl_ff_tip.linkActivated.connect(self.on_open_external_link)
		lbl_ff_tip.setWordWrap(True)
		lbl_ff_tip.setFont(QFont(retro_font_family, default_pt))
		cookies_layout.addWidget(lbl_ff_tip)
		cookies_layout.addSpacing(self._px(4))
		# Cookies file alternative
		lbl_cookie_file = QLabel("Cookies file (.txt):")
		lbl_cookie_file.setFont(QFont(retro_font_family, default_pt + 2, QFont.Bold))
		cookies_layout.addWidget(lbl_cookie_file)
		self.ed_cookies_file = QLineEdit()
		self.ed_cookies_file.setPlaceholderText("Optional: Netscape cookies.txt (YouTube domain)")
		self.ed_cookies_file.setFont(QFont(retro_font_family, default_pt + 1))
		self.ed_cookies_file.textChanged.connect(self.on_cookies_file_changed)
		cookies_layout.addWidget(self.ed_cookies_file)
		row_cookie_file = QHBoxLayout()
		row_cookie_file.setSpacing(self._px(6))
		btn_cookie_file = QPushButton("Browse...")
		btn_cookie_file.setFont(btn_font)
		btn_cookie_file.clicked.connect(self.on_browse_cookies_file)
		btn_cookie_file_clear = QPushButton("Clear")
		btn_cookie_file_clear.setFont(btn_font)
		btn_cookie_file_clear.clicked.connect(self.on_clear_cookies_file)
		row_cookie_file.addWidget(btn_cookie_file)
		row_cookie_file.addWidget(btn_cookie_file_clear)
		row_cookie_file.addStretch(1)
		cookies_layout.addLayout(row_cookie_file)
		# Cookie check status label
		self.lbl_cookie_status = QLabel("")
		self.lbl_cookie_status.setVisible(False)
		self.lbl_cookie_status.setFont(QFont(retro_font_family, max(default_pt - 1, 8)))
		cookies_layout.addWidget(self.lbl_cookie_status)
		settings_right.addWidget(cookies_section)
		settings_left.addStretch(1)
		settings_right.addStretch(1)
		self.advanced_panel.setVisible(False)
		vl.addWidget(self.advanced_panel)

		def _toggle_advanced(checked: bool):
			self._toggle_top_dialog(btn_adv, self.advanced_dialog, "SETTINGS", checked)
		btn_adv.toggled.connect(_toggle_advanced)

		self.help_dialog = self._create_panel_dialog(vl, self.help_panel, "Tutorial", self._px(720), self._px(360))
		self.load_dialog = self._create_panel_dialog(vl, self.load_panel, "Load Playlist", self._px(720), self._px(420))
		self.equalizer_dialog = self._create_panel_dialog(vl, self.equalizer_panel, "Equalizer", self._px(720), self._px(360))
		self.advanced_dialog = self._create_panel_dialog(vl, self.advanced_panel, "Settings", self._px(980), self._px(620))
		self._top_dialogs = {
			self.btn_tutorial: (self.help_dialog, "TUTORIAL"),
			self.btn_load_existing: (self.load_dialog, "LOAD PLAYLIST"),
			self.btn_equalizer: (self.equalizer_dialog, "EQUALIZER"),
			self.btn_advanced: (self.advanced_dialog, "SETTINGS"),
		}
		for button, (dialog, label) in self._top_dialogs.items():
			dialog.finished.connect(lambda _result=0, btn=button, text=label: self._on_top_dialog_closed(btn, text))

		# ── CSV picker ─────────────────────────────────────────────────────────────
		row1 = QHBoxLayout()
		row1.setSpacing(self._px(6))
		self.ed_csv = QLineEdit(); self.ed_csv.setPlaceholderText("Path to one playlist CSV file")
		self.ed_csv.setFont(QFont(retro_font_family, default_pt + 1))
		btn_csv = QPushButton("Browse…"); btn_csv.clicked.connect(self.on_browse_csv)
		btn_csv.setFont(btn_font)
		lbl_csv = QLabel("CSV:")
		lbl_csv.setFont(QFont(retro_font_family, default_pt + 2, QFont.Bold))
		lbl_csv.setFixedWidth(self._px(78))
		row1.addWidget(lbl_csv); row1.addWidget(self.ed_csv, 1); row1.addWidget(btn_csv)
		vl.addLayout(row1)

		# ── Output folder ─────────────────────────────────────────────────────────
		row2 = QHBoxLayout()
		row2.setSpacing(self._px(6))
		self.ed_out = QLineEdit(); self.ed_out.setPlaceholderText("Output folder")
		self.ed_out.setFont(QFont(retro_font_family, default_pt + 1))
		btn_out = QPushButton("Choose…"); btn_out.clicked.connect(self.on_browse_out)
		btn_out.setFont(btn_font)
		btn_open_out = QPushButton("Open"); btn_open_out.clicked.connect(self.on_open_output)
		btn_open_out.setFont(btn_font)
		lbl_out = QLabel("Output:")
		lbl_out.setFont(QFont(retro_font_family, default_pt + 2, QFont.Bold))
		lbl_out.setFixedWidth(self._px(78))
		row2.addWidget(lbl_out); row2.addWidget(self.ed_out, 1); row2.addWidget(btn_out); row2.addWidget(btn_open_out)
		vl.addLayout(row2)

		# ── Format + options + actions ────────────────────────────────────────────
		row3 = QHBoxLayout()
		row3.setSpacing(self._px(10))
		self.rb_m4a = RetroRadioButton("m4a (AAC, preferred)"); self.rb_m4a.setChecked(True)
		self.rb_mp3 = RetroRadioButton("mp3")
		self.grp_fmt = QButtonGroup(self); self.grp_fmt.addButton(self.rb_m4a); self.grp_fmt.addButton(self.rb_mp3)
		self.grp_fmt.buttonToggled.connect(lambda _button, checked: self._persist_settings() if checked else None)
		self.cb_m3u8 = QCheckBox("Write .m3u8")
		self.cb_m3u_plain = QCheckBox("Write .m3u"); self.cb_m3u_plain.setChecked(True)
		self.cb_album_art = QCheckBox("Embed album art"); self.cb_album_art.setChecked(True)
		controls_font = QFont(retro_font_family, default_pt + 2)
		for w in (self.rb_m4a, self.rb_mp3, self.cb_m3u8, self.cb_m3u_plain, self.cb_album_art):
			w.setFont(controls_font)
		for w in (self.rb_m4a, self.rb_mp3):
			w.setMinimumHeight(self._px(24))
		lbl_fmt = QLabel("Format:")
		lbl_fmt.setFont(QFont(retro_font_family, default_pt + 2, QFont.Bold))
		lbl_fmt.setFixedWidth(self._px(78))
		row3.addWidget(lbl_fmt)
		row3.addWidget(self.rb_m4a)
		row3.addWidget(self.rb_mp3)
		row3.addSpacing(self._px(12))
		lbl_extras = QLabel("Extras:")
		lbl_extras.setFont(QFont(retro_font_family, default_pt + 2, QFont.Bold))
		row3.addWidget(lbl_extras)
		row3.addWidget(self.cb_m3u8)
		row3.addWidget(self.cb_m3u_plain)
		row3.addWidget(self.cb_album_art)
		row3.addStretch(1)
		vl.addLayout(row3)

		row4 = QHBoxLayout()
		row4.setSpacing(self._px(8))
		self.btn_start = QPushButton("START"); self.btn_start.clicked.connect(self.on_start)
		self.btn_stop = QPushButton("STOP"); self.btn_stop.setEnabled(False); self.btn_stop.clicked.connect(self.on_stop)
		self.btn_clear = QPushButton("CLEAR"); self.btn_clear.setEnabled(False); self.btn_clear.clicked.connect(self.on_clear)
		for w in (self.btn_start, self.btn_stop, self.btn_clear):
			w.setFont(QFont(retro_font_family, default_pt + 3, QFont.Bold))
		row4.addWidget(self.btn_start)
		row4.addWidget(self.btn_stop)
		row4.addWidget(self.btn_clear)
		row4.addStretch(1)
		vl.addLayout(row4)

		# ── Table ─────────────────────────────────────────────────────────────────
		self.table = QTableWidget(0, 4)
		self.table.setHorizontalHeaderLabels(["#", "Title", "Status", "Actions"])
		self.table.verticalHeader().setVisible(False)
		self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
		self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
		self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
		self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
		header_font = QFont(retro_font_family, default_pt + 2, QFont.Bold)
		self.table.horizontalHeader().setFont(header_font)
		vl.addWidget(self.table, 1)

		# ── Bottom status ─────────────────────────────────────────────────────────
		self.lbl_log = QLabel("")
		self.lbl_log.setTextInteractionFlags(Qt.TextSelectableByMouse)
		vl.addWidget(self.lbl_log)

		self.progress = QProgressBar()
		self.progress.setMinimum(0)
		self.progress.setValue(0)
		self.progress.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
		vl.addWidget(self.progress)

		self.resolve_box = QFrame()
		self.resolve_box.setFrameShape(QFrame.StyledPanel)
		self.resolve_box.setVisible(False)
		res_layout = QVBoxLayout(self.resolve_box)
		res_layout.setContentsMargins(self._px(12), self._px(10), self._px(12), self._px(10))
		res_layout.setSpacing(self._px(6))
		self.resolve_header = QLabel("Alternative matches pending")
		res_layout.addWidget(self.resolve_header)
		self.resolve_items_layout = QVBoxLayout()
		self.resolve_items_layout.setSpacing(self._px(8))
		res_layout.addLayout(self.resolve_items_layout)
		vl.addWidget(self.resolve_box)

		self._load_last_session()

	def _compute_scale_factor(self) -> float:
		screen = QGuiApplication.primaryScreen()
		if screen is None:
			return 1.0
		dpi = screen.logicalDotsPerInch() or 96.0
		scale = dpi / 96.0
		return max(0.85, min(scale, 3.0))

	def _px(self, value: int) -> int:
		return max(1, int(round(value * self._scale)))

	def _pick_readable_font_family(self) -> str:
		families = set(QFontDatabase().families())
		for candidate in ("Segoe UI", "Tahoma", "Verdana", "Arial", self.font().family()):
			if candidate in families:
				return candidate
		return self.font().family()

	def _swap_font_family(self, widget: QWidget, family: str) -> None:
		font = widget.font()
		font.setFamily(family)
		widget.setFont(font)

	def _apply_font_family_to_widget_tree(self, root: QWidget, family: str) -> None:
		self._swap_font_family(root, family)
		for widget in root.findChildren(QWidget):
			self._swap_font_family(widget, family)

	def _apply_font_family(self, family: str) -> None:
		self.setFont(QFont(family, self._default_pt))
		self._root_widget.setStyleSheet(self._base_stylesheet_template.replace("__FONT_FAMILY__", family))
		self._button_font = QFont(family, self._default_pt + 2, QFont.Bold)
		self._swap_font_family(self, family)
		for widget in self.findChildren(QWidget):
			self._swap_font_family(widget, family)
		self.table.horizontalHeader().setFont(QFont(family, self._default_pt + 2, QFont.Bold))
		self._refresh_top_dialog_styles()

	def _refresh_top_dialog_styles(self) -> None:
		family = self._readable_font_family if self._readability_mode else self._retro_font_family
		dialog_stylesheet = self._base_stylesheet_template.replace("__FONT_FAMILY__", family)
		for dialog in (
			getattr(self, "help_dialog", None),
			getattr(self, "load_dialog", None),
			getattr(self, "equalizer_dialog", None),
			getattr(self, "advanced_dialog", None),
		):
			if dialog is not None:
				dialog.setStyleSheet(dialog_stylesheet)
		for panel in (
			getattr(self, "help_panel", None),
			getattr(self, "load_panel", None),
			getattr(self, "equalizer_panel", None),
			getattr(self, "advanced_panel", None),
		):
			if panel is not None:
				self._apply_font_family_to_widget_tree(panel, family)

	def on_toggle_readability_mode(self, checked: bool) -> None:
		self._readability_mode = bool(checked)
		family = self._readable_font_family if self._readability_mode else self._retro_font_family
		self._apply_font_family(family)
		self._persist_settings()

	def _make_eq_slider(self, parent_layout: QVBoxLayout, label: str, font_family: str, default_pt: int) -> tuple[NotchedSlider, QLabel, QLabel]:
		row = QHBoxLayout()
		lbl = QLabel(f"{label}:")
		lbl.setFont(QFont(font_family, default_pt + 1, QFont.Bold))
		lbl.setFixedWidth(self._px(96))
		slider = NotchedSlider(Qt.Horizontal)
		slider.setRange(-15, 15)
		slider.setValue(0)
		slider.setTickInterval(1)
		slider.setSingleStep(1)
		slider.setPageStep(1)
		slider.setFixedWidth(self._px(520))
		slider.setMinimumHeight(self._px(34))
		value_label = QLabel("0 dB")
		value_label.setMinimumWidth(self._px(52))
		value_label.setFont(QFont(font_family, default_pt + 1))
		def _on_change(value: int) -> None:
			value_label.setText(f"{value:+d} dB" if value else "0 dB")
			self._persist_settings()
		slider.valueChanged.connect(_on_change)
		row.addWidget(lbl)
		row.addWidget(slider, 1)
		row.addWidget(value_label)
		parent_layout.addLayout(row)
		return slider, value_label, lbl

	def _create_panel_dialog(self, root_layout: QVBoxLayout, panel: QFrame, title: str, width: int, height: int) -> QDialog:
		root_layout.removeWidget(panel)
		panel.setVisible(True)
		dialog = QDialog(self)
		dialog.setWindowTitle(title)
		dialog.setModal(False)
		dialog.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
		dialog_layout = QVBoxLayout(dialog)
		dialog_layout.setContentsMargins(0, 0, 0, 0)
		dialog_layout.addWidget(panel)
		family = self._readable_font_family if self._readability_mode else self._retro_font_family
		dialog.setStyleSheet(self._base_stylesheet_template.replace("__FONT_FAMILY__", family))
		self._apply_font_family_to_widget_tree(panel, family)
		dialog.setMinimumSize(width, height)
		dialog.resize(width, height)
		return dialog

	def _set_top_button_label(self, button: QToolButton, base_label: str, open_state: bool) -> None:
		button.setText(f"{base_label} {'▾' if open_state else '▸'}")

	def _on_top_dialog_closed(self, button: QToolButton, base_label: str) -> None:
		blocker = QSignalBlocker(button)
		button.setChecked(False)
		del blocker
		self._set_top_button_label(button, base_label, False)

	def _close_other_top_dialogs(self, active_button: QToolButton | None) -> None:
		for button, (dialog, label) in getattr(self, "_top_dialogs", {}).items():
			if button is active_button:
				continue
			if dialog.isVisible():
				dialog.hide()
			if button.isChecked():
				blocker = QSignalBlocker(button)
				button.setChecked(False)
				del blocker
			self._set_top_button_label(button, label, False)

	def _toggle_top_dialog(self, button: QToolButton, dialog: QDialog, base_label: str, checked: bool) -> None:
		if checked:
			self._close_other_top_dialogs(button)
			self._set_top_button_label(button, base_label, True)
			dialog.show()
			dialog.raise_()
			dialog.activateWindow()
		else:
			dialog.hide()
			self._set_top_button_label(button, base_label, False)

	def _set_equalizer_controls_enabled(self, enabled: bool) -> None:
		self.cb_eq_enabled.setText("Equalizer ON" if enabled else "Equalizer OFF")
		for widget in getattr(self, "_equalizer_child_controls", []):
			widget.setEnabled(enabled)

	def _audio_processing_options(self) -> dict:
		if not self.cb_eq_enabled.isChecked():
			return {}
		return {
			"enabled": True,
			"normalize": self.cb_eq_normalize.isChecked(),
			"volume_gain": self.slider_volume.value(),
			"bass_gain": self.slider_bass.value(),
			"treble_gain": self.slider_treble.value(),
		}

	def _mp3_quality_value(self) -> int:
		return max(0, min(10, int(self.slider_mp3_quality.value())))

	def _legacy_export_options(self) -> dict:
		enabled = bool(self.cb_legacy_ipod_mode.isChecked())
		return {
			"enabled": enabled,
			"mp3_mode": self.combo_legacy_mp3_mode.currentData() or "vbr",
			"cover_art_mode": self.combo_legacy_cover_art.currentData() or "standard",
		}

	def _set_legacy_controls_enabled(self, enabled: bool) -> None:
		self.combo_legacy_mp3_mode.setEnabled(enabled)
		self.combo_legacy_cover_art.setEnabled(enabled)

	def on_toggle_legacy_ipod_mode(self, checked: bool) -> None:
		self._set_legacy_controls_enabled(bool(checked))
		self._persist_settings()

	def _on_mp3_quality_changed(self, value: int) -> None:
		value = max(0, min(10, int(value)))
		if value == 0:
			label = "0 = Best"
		elif value == 10:
			label = "10 = Worst"
		else:
			label = f"{value} = Lower"
		self.lbl_mp3_quality_value.setText(label)
		self._persist_settings()

	def _clamp_to_screen(self, width: int, height: int) -> Tuple[int, int]:
		screen = QGuiApplication.primaryScreen()
		if screen is None:
			return int(width), int(height)
		geo = screen.availableGeometry()
		max_w = max(int(geo.width() * 0.95), 640)
		max_h = max(int(geo.height() * 0.95), 480)
		return min(int(width), max_w), min(int(height), max_h)

	def on_browse_csv(self):
		p, _ = QFileDialog.getOpenFileName(self, "Select CSV", "", "CSV files (*.csv);;All files (*)")
		if p:
			self.ed_csv.setText(p)
			self.btn_clear.setEnabled(True)
			self._allow_path_persist = True
			self._persist_settings(include_paths=True)

	def on_browse_load_csv(self):
		p, _ = QFileDialog.getOpenFileName(self, "Select Playlist CSV", "", "CSV files (*.csv);;All files (*)")
		if p:
			self.ed_load_csv.setText(p)
			self._persist_settings(include_paths=True)

	def on_browse_out(self):
		p = QFileDialog.getExistingDirectory(self, "Select Output Folder", "")
		if p:
			self.ed_out.setText(p)
			self.btn_clear.setEnabled(True)
			self._allow_path_persist = True
			self._persist_settings(include_paths=True)

	def _prompt_load_source_path(self) -> pathlib.Path | None:
		msg = QMessageBox(self)
		msg.setWindowTitle("Current Music")
		msg.setText("Choose what to browse.")
		msg.setInformativeText("Select either the playlist folder/output folder, or the playlist's .m3u/.m3u8 file.")
		folder_btn = msg.addButton("Choose Folder", QMessageBox.AcceptRole)
		file_btn = msg.addButton("Choose Playlist File", QMessageBox.AcceptRole)
		msg.addButton(QMessageBox.Cancel)
		msg.exec()
		clicked = msg.clickedButton()
		initial = self.ed_load_source.text().strip() or self.ed_out.text().strip() or ""
		if clicked == folder_btn:
			path = QFileDialog.getExistingDirectory(self, "Select Playlist Folder or Output Folder", initial)
			return pathlib.Path(path) if path else None
		if clicked == file_btn:
			path, _ = QFileDialog.getOpenFileName(
				self,
				"Select Playlist File",
				initial,
				"Playlist files (*.m3u *.m3u8);;All files (*)"
			)
			return pathlib.Path(path) if path else None
		return None

	def on_browse_load_source(self):
		path = self._prompt_load_source_path()
		if path:
			self.ed_load_source.setText(str(path))
			self._persist_settings(include_paths=True)

	def on_browse_ytdlp(self):
		path, _ = QFileDialog.getOpenFileName(self, "Select yt-dlp executable", "", "Executables (*.exe *.bat *.cmd);;All files (*)")
		if path:
			self.ed_ytdlp.setText(path)
			self._persist_settings()

	def on_clear_ytdlp(self):
		self.ed_ytdlp.clear()
		self._persist_settings()

	def on_browse_ffmpeg(self):
		path, _ = QFileDialog.getOpenFileName(self, "Select FFmpeg executable", "", "Executables (*.exe);;All files (*)")
		if path:
			self.ed_ffmpeg.setText(path)
			self._persist_settings()

	def on_clear_ffmpeg(self):
		self.ed_ffmpeg.clear()
		self._persist_settings()

	def on_open_output(self):
		path = self.ed_out.text().strip()
		if not path:
			QMessageBox.information(self, "No folder", "Select an output folder first.")
			return
		p = pathlib.Path(path)
		if not p.exists() or not p.is_dir():
			QMessageBox.warning(self, "Missing folder", "The selected output folder does not exist.")
			return
		QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

	def on_open_external_link(self, url: str) -> None:
		if not url:
			return
		if not QDesktopServices.openUrl(QUrl(url)):
			QMessageBox.warning(
				self,
				"Could Not Open Link",
				f"CSVMusic could not open this link automatically:\n{url}\n\nOpen it manually in your browser."
			)

	def _collect_tracks_preview(self, csv_path: str | None = None) -> List[dict]:
		target_csv = csv_path or self.ed_csv.text().strip()
		df = load_csv(target_csv)
		return tracks_from_csv(df, None)  # use entire CSV

	def _set_row_highlight(self, row_idx: int, color: QColor | None) -> None:
		if not (0 <= row_idx < self.table.rowCount()):
			return
		for col in (0, 1, 2):
			item = self.table.item(row_idx, col)
			if item is None:
				continue
			item.setBackground(color if color is not None else QColor(Qt.transparent))

	def _playlist_dir_name(self, tracks: list[dict]) -> str:
		playlist_name = tracks[0].get("playlist") or "Playlist"
		return sanitize_name(playlist_name)

	def _resolve_load_playlist_root(self, selected_path: pathlib.Path, tracks: list[dict]) -> pathlib.Path:
		playlist_dir_name = self._playlist_dir_name(tracks)
		if not selected_path.exists():
			raise ValueError("The selected file or folder no longer exists. Choose the playlist folder or its .m3u/.m3u8 file again.")
		if selected_path.is_file():
			if selected_path.suffix.lower() not in (".m3u", ".m3u8"):
				raise ValueError("Load Playlist only accepts a folder or a playlist file ending in .m3u or .m3u8.")
			if selected_path.parent.name != playlist_dir_name:
				raise ValueError(
					f"This playlist file is not inside the expected playlist folder '{playlist_dir_name}'. "
					f"Choose the '{playlist_dir_name}' folder or its .m3u/.m3u8 file."
				)
			return selected_path.parent.parent
		if selected_path.is_dir():
			if (selected_path / playlist_dir_name).is_dir():
				return selected_path
			if selected_path.name == playlist_dir_name:
				return selected_path.parent
			raise ValueError(
				f"Could not find the playlist folder '{playlist_dir_name}' in that location. "
				f"Choose the main output folder or the '{playlist_dir_name}' playlist folder."
			)
		raise ValueError("Load Playlist expects a folder or an .m3u/.m3u8 playlist file.")

	def _expected_track_path(self, track: dict, out_root: pathlib.Path, fmt: str) -> pathlib.Path:
		playlist_name = track.get("playlist") or "Playlist"
		base = f"{track.get('artists','')} - {track.get('title','')}"
		return out_root / sanitize_name(playlist_name) / f"{sanitize_name(base)}.{fmt}"

	def _build_track_preview(self) -> tuple[list[dict], list[int]]:
		csv_path = self.ed_csv.text().strip()
		out_dir = self.ed_out.text().strip()
		if not csv_path or not pathlib.Path(csv_path).exists():
			raise FileNotFoundError("Please choose a valid CSV file.")
		if not out_dir:
			raise ValueError("Please choose an output folder.")
		tracks = self._collect_tracks_preview()
		if not tracks:
			return [], []
		fmt = "m4a" if self.rb_m4a.isChecked() else "mp3"
		out_root = pathlib.Path(out_dir)
		self.tracks = tracks
		self.track_results = {}
		self.action_buttons = {}
		self._clear_resolution_panel()
		self.table.setRowCount(len(tracks))
		queued_rows: list[int] = []
		for i, track in enumerate(tracks):
			self.table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
			title_item = QTableWidgetItem(f"{track['artists']} — {track['title']}")
			if not self._default_track_icon.isNull():
				title_item.setIcon(self._default_track_icon)
			self.table.setItem(i, 1, title_item)
			self.table.setRowHeight(i, self._row_icon_size + self._px(8))
			btn_alt = QPushButton("Alternatives")
			btn_alt.setEnabled(False)
			btn_alt.clicked.connect(partial(self.on_open_alternatives, i))
			self.table.setCellWidget(i, 3, btn_alt)
			self.action_buttons[i] = btn_alt
			expected_path = self._expected_track_path(track, out_root, fmt)
			if expected_path.exists():
				self.track_results[i] = {
					"track": track,
					"options": [],
					"match": None,
					"confidence": 1.0,
					"skipped": False,
					"error": None,
					"playlist_name": track.get("playlist") or "Playlist",
					"file_path": str(expected_path),
					"downloaded": True,
					"existing": True,
					"cover_bytes": None,
				}
				self.on_row_status(i, f"Already downloaded → {expected_path.name}")
				btn_alt.setEnabled(True)
			else:
				self.table.setItem(i, 2, QTableWidgetItem("Queued"))
				self._set_row_highlight(i, YELLOW)
				queued_rows.append(i)
		self.total = len(tracks)
		self.progress.setMaximum(max(len(queued_rows), 1))
		self.progress.setValue(0)
		self.last_playlist_name = tracks[0].get("playlist") or "Playlist"
		return tracks, queued_rows

	def _yt_dlp_override(self) -> str | None:
		val = self.ed_ytdlp.text().strip()
		return val or None

	def _ffmpeg_override(self) -> str | None:
		val = self.ed_ffmpeg.text().strip()
		return val or None

	def _cookies_browser(self) -> str | None:
		if not self.cb_use_cookies.isChecked():
			return None
		if self._detected_firefox_profile:
			return f"firefox:{self._detected_firefox_profile}"
		return None

	def _cookies_file(self) -> str | None:
		if not self.cb_use_cookies.isChecked():
			return None
		val = self.ed_cookies_file.text().strip()
		return val or None

	def _cookie_test_browser(self) -> str | None:
		if self._detected_firefox_profile:
			return f"firefox:{self._detected_firefox_profile}"
		return None

	def _cookie_test_file(self) -> str | None:
		val = self.ed_cookies_file.text().strip()
		return val or None

	def _set_cookies_tested(self, ok: bool) -> None:
		self._cookies_test_ok = ok
		self.cb_use_cookies.setEnabled(ok)
		block = QSignalBlocker(self.cb_use_cookies)
		self.cb_use_cookies.setChecked(ok)
		del block
		self._persist_settings()

	def _detect_firefox_profile(self) -> str | None:
		profiles = list_profiles("firefox")
		if not profiles:
			return None
		auth_cookie_names = ("__Secure-3PSID","__Secure-1PSID","SAPISID","APISID","SID","SSID","HSID")
		fallback: str | None = None
		for p in profiles:
			db = pathlib.Path(p, "cookies.sqlite")
			if not db.exists():
				continue
			if fallback is None:
				fallback = p
			try:
				conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
				cur = conn.cursor()
				cur.execute(
					"SELECT name FROM moz_cookies WHERE (host LIKE '%youtube.com' OR host LIKE '%google.com') AND name IN (?,?,?,?,?,?,?) LIMIT 1",
					auth_cookie_names
				)
				has_auth_cookie = cur.fetchone() is not None
				conn.close()
				if has_auth_cookie:
					return p
			except Exception:
				pass
		if fallback:
			return fallback
		for p in profiles:
			if pathlib.Path(p).exists():
				return p
		return None

	def on_detect_firefox_cookies(self) -> None:
		profile = self._detect_firefox_profile()
		self._set_cookies_tested(False)
		if not profile:
			self._detected_firefox_profile = None
			self._persist_settings()
			self._set_cookie_status("Firefox cookies not found. Install Firefox and sign into YouTube first.", ok=False)
			return
		self._detected_firefox_profile = profile
		self._persist_settings()
		self._set_cookie_status(f"Firefox cookies detected: {pathlib.Path(profile).name}", ok=True)

	def on_browse_cookies_file(self):
		p, _ = QFileDialog.getOpenFileName(self, "Select cookies.txt", "", "Text files (*.txt);;All files (*)")
		if p:
			self.ed_cookies_file.setText(p)
			self._set_cookies_tested(False)
			self._persist_settings()

	def on_clear_cookies_file(self):
		self.ed_cookies_file.clear()
		self._set_cookies_tested(False)
		self._persist_settings()

	def on_cookies_file_changed(self, _text: str) -> None:
		self._set_cookies_tested(False)
		self._persist_settings()

	def on_test_cookies(self) -> None:
		self._start_cookie_check(show_required=True)

	def _set_cookie_status(self, text: str, *, ok: bool | None) -> None:
		self.lbl_cookie_status.setVisible(True)
		self.lbl_cookie_status.setText(text)
		if ok is True:
			self.lbl_cookie_status.setStyleSheet("color: #006400")
		elif ok is False:
			self.lbl_cookie_status.setStyleSheet("color: #8B0000")
		else:
			self.lbl_cookie_status.setStyleSheet("color: #000000")

	def _start_cookie_check(self, *, show_required: bool = False) -> None:
		# Only check when a browser is selected
		cookies = self._cookie_test_browser()
		cookies_file = self._cookie_test_file()
		if not cookies and not cookies_file:
			if show_required:
				self._set_cookie_status("Select Firefox cookies or a cookies.txt file first.", ok=False)
			else:
				self.lbl_cookie_status.setVisible(False)
			return
		self._set_cookie_status("Checking cookies…", ok=None)
		self.btn_test_cookies.setEnabled(False)
		# Cancel prior worker if any
		if hasattr(self, "cookie_check_worker") and self.cookie_check_worker:
			try:
				self.cookie_check_worker.quit()
				self.cookie_check_worker.wait(200)
			except Exception:
				pass
		self.cookie_check_worker = CookiesCheckWorker(cookies, cookies_file, self._yt_dlp_override(), self)
		def _finish_cookie_check(ok: bool, msg: str) -> None:
			self.btn_test_cookies.setEnabled(True)
			self._set_cookies_tested(ok)
			self._set_cookie_status(msg, ok=ok)
		self.cookie_check_worker.sig_done.connect(_finish_cookie_check)
		self.cookie_check_worker.start()

	def _persist_settings(self, *, include_paths: bool = False) -> None:
		def _norm(text: str) -> str | None:
			value = text.strip()
			return value or None
		cfg = {
			"yt_dlp_path": _norm(self.ed_ytdlp.text()),
			"ffmpeg_path": _norm(self.ed_ffmpeg.text()),
			"cookies_browser": f"firefox:{self._detected_firefox_profile}" if self._detected_firefox_profile else None,
			"cookies_file": _norm(self.ed_cookies_file.text()),
			"readability_mode": self._readability_mode,
			"use_cookies": self.cb_use_cookies.isChecked(),
			"cookies_test_ok": self._cookies_test_ok,
			"eq_enabled": self.cb_eq_enabled.isChecked(),
			"eq_normalize": self.cb_eq_normalize.isChecked(),
			"eq_volume_gain": self.slider_volume.value(),
			"eq_bass_gain": self.slider_bass.value(),
			"eq_treble_gain": self.slider_treble.value(),
			"mp3_quality": self._mp3_quality_value(),
			"force_download_mode": self.cb_force_download.isChecked(),
			"legacy_ipod_mode": self.cb_legacy_ipod_mode.isChecked(),
			"legacy_mp3_mode": self.combo_legacy_mp3_mode.currentData(),
			"legacy_cover_art_mode": self.combo_legacy_cover_art.currentData(),
			"format": "m4a" if self.rb_m4a.isChecked() else "mp3",
		}
		if include_paths:
			cfg["csv_path"] = _norm(self.ed_csv.text())
			cfg["output_dir"] = _norm(self.ed_out.text())
			cfg["load_csv_path"] = _norm(self.ed_load_csv.text())
			cfg["load_source_path"] = _norm(self.ed_load_source.text())
		save_settings(cfg)

	def _load_last_session(self) -> None:
		cfg = load_settings()
		csv_path = cfg.get("csv_path") or ""
		out_dir = cfg.get("output_dir") or ""
		if csv_path and pathlib.Path(csv_path).exists():
			self._allow_path_persist = True
			blocker_csv = QSignalBlocker(self.ed_csv)
			self.ed_csv.setText(csv_path)
			del blocker_csv
		else:
			self.ed_csv.clear()
		if out_dir and pathlib.Path(out_dir).exists():
			self._allow_path_persist = True
			blocker_out = QSignalBlocker(self.ed_out)
			self.ed_out.setText(out_dir)
			del blocker_out
		else:
			self.ed_out.clear()
		load_csv_path = cfg.get("load_csv_path") or ""
		if load_csv_path and pathlib.Path(load_csv_path).exists():
			blocker_load_csv = QSignalBlocker(self.ed_load_csv)
			self.ed_load_csv.setText(load_csv_path)
			del blocker_load_csv
		else:
			self.ed_load_csv.clear()
		load_source_path = cfg.get("load_source_path") or ""
		if load_source_path and pathlib.Path(load_source_path).exists():
			blocker_load_source = QSignalBlocker(self.ed_load_source)
			self.ed_load_source.setText(load_source_path)
			del blocker_load_source
		else:
			self.ed_load_source.clear()
		yt_path = cfg.get("yt_dlp_path") or ""
		blocker_yt = QSignalBlocker(self.ed_ytdlp)
		self.ed_ytdlp.setText(yt_path)
		del blocker_yt
		block_readability = QSignalBlocker(self.cb_readability_mode)
		self.cb_readability_mode.setChecked(bool(cfg.get("readability_mode", False)))
		del block_readability
		block_force = QSignalBlocker(self.cb_force_download)
		self.cb_force_download.setChecked(bool(cfg.get("force_download_mode", False)))
		del block_force
		block_legacy = QSignalBlocker(self.cb_legacy_ipod_mode)
		self.cb_legacy_ipod_mode.setChecked(bool(cfg.get("legacy_ipod_mode", False)))
		del block_legacy
		legacy_mp3_mode = str(cfg.get("legacy_mp3_mode") or "vbr")
		legacy_cover_mode = str(cfg.get("legacy_cover_art_mode") or "standard")
		for idx in range(self.combo_legacy_mp3_mode.count()):
			if self.combo_legacy_mp3_mode.itemData(idx) == legacy_mp3_mode:
				block_legacy_mp3 = QSignalBlocker(self.combo_legacy_mp3_mode)
				self.combo_legacy_mp3_mode.setCurrentIndex(idx)
				del block_legacy_mp3
				break
		for idx in range(self.combo_legacy_cover_art.count()):
			if self.combo_legacy_cover_art.itemData(idx) == legacy_cover_mode:
				block_legacy_art = QSignalBlocker(self.combo_legacy_cover_art)
				self.combo_legacy_cover_art.setCurrentIndex(idx)
				del block_legacy_art
				break
		self._set_legacy_controls_enabled(self.cb_legacy_ipod_mode.isChecked())
		self._readability_mode = bool(cfg.get("readability_mode", False))
		self._apply_font_family(self._readable_font_family if self._readability_mode else self._retro_font_family)
		ff_path = cfg.get("ffmpeg_path") or ""
		blocker_ff = QSignalBlocker(self.ed_ffmpeg)
		self.ed_ffmpeg.setText(ff_path)
		del blocker_ff
		stored_browser = str(cfg.get("cookies_browser") or "")
		self._detected_firefox_profile = None
		self._cookies_test_ok = bool(cfg.get("cookies_test_ok", False))
		if stored_browser.startswith("firefox:"):
			profile = stored_browser.split(":", 1)[1].strip()
			if profile and pathlib.Path(profile, "cookies.sqlite").exists():
				self._detected_firefox_profile = profile
				self._set_cookie_status(f"Firefox cookies detected: {pathlib.Path(profile).name}", ok=True)
		elif stored_browser == "firefox":
			profile = self._detect_firefox_profile()
			if profile:
				self._detected_firefox_profile = profile
				self._set_cookie_status(f"Firefox cookies detected: {pathlib.Path(profile).name}", ok=True)
		self.cb_use_cookies.setEnabled(self._cookies_test_ok)
		block_use_cookies = QSignalBlocker(self.cb_use_cookies)
		self.cb_use_cookies.setChecked(bool(cfg.get("use_cookies", False)) and self._cookies_test_ok)
		del block_use_cookies
		# Load cookies file path
		cookie_file = cfg.get("cookies_file") or ""
		block_cf = QSignalBlocker(self.ed_cookies_file)
		self.ed_cookies_file.setText(cookie_file)
		del block_cf
		eq_has_saved_values = bool(cfg.get("eq_normalize", False)) or any(
			int(cfg.get(key, 0) or 0) != 0
			for key in ("eq_volume_gain", "eq_bass_gain", "eq_treble_gain")
		)
		eq_enabled = bool(cfg.get("eq_enabled", eq_has_saved_values))
		block_eq_enabled = QSignalBlocker(self.cb_eq_enabled)
		self.cb_eq_enabled.setChecked(eq_enabled)
		del block_eq_enabled
		self._set_equalizer_controls_enabled(eq_enabled)
		block_norm = QSignalBlocker(self.cb_eq_normalize)
		self.cb_eq_normalize.setChecked(bool(cfg.get("eq_normalize", False)))
		del block_norm
		volume_gain = int(cfg.get("eq_volume_gain", 0) or 0)
		bass_gain = int(cfg.get("eq_bass_gain", 0) or 0)
		treble_gain = int(cfg.get("eq_treble_gain", 0) or 0)
		block_volume = QSignalBlocker(self.slider_volume)
		self.slider_volume.setValue(max(-15, min(15, volume_gain)))
		del block_volume
		self.lbl_volume_value.setText(f"{self.slider_volume.value():+d} dB" if self.slider_volume.value() else "0 dB")
		block_bass = QSignalBlocker(self.slider_bass)
		self.slider_bass.setValue(max(-15, min(15, bass_gain)))
		del block_bass
		self.lbl_bass_value.setText(f"{self.slider_bass.value():+d} dB" if self.slider_bass.value() else "0 dB")
		block_treble = QSignalBlocker(self.slider_treble)
		self.slider_treble.setValue(max(-15, min(15, treble_gain)))
		del block_treble
		self.lbl_treble_value.setText(f"{self.slider_treble.value():+d} dB" if self.slider_treble.value() else "0 dB")
		mp3_quality = int(cfg.get("mp3_quality", 0) or 0)
		block_mp3_quality = QSignalBlocker(self.slider_mp3_quality)
		self.slider_mp3_quality.setValue(max(0, min(10, mp3_quality)))
		del block_mp3_quality
		if self.slider_mp3_quality.value() == 0:
			self.lbl_mp3_quality_value.setText("0 = Best")
		elif self.slider_mp3_quality.value() == 10:
			self.lbl_mp3_quality_value.setText("10 = Worst")
		else:
			self.lbl_mp3_quality_value.setText(f"{self.slider_mp3_quality.value()} = Lower")
		stored_format = str(cfg.get("format") or "").lower()
		if stored_format in ("m4a", "mp3"):
			block_m4a = QSignalBlocker(self.rb_m4a)
			block_mp3 = QSignalBlocker(self.rb_mp3)
			self.rb_m4a.setChecked(stored_format == "m4a")
			self.rb_mp3.setChecked(stored_format == "mp3")
			del block_m4a
			del block_mp3
		self.btn_clear.setEnabled(bool(self.ed_csv.text().strip() or self.ed_out.text().strip()))

	def on_start(self):
		csv_path = self.ed_csv.text().strip()
		out_dir = self.ed_out.text().strip()
		if not csv_path or not pathlib.Path(csv_path).exists():
			QMessageBox.warning(self, "Missing CSV", "Please choose a valid CSV file.")
			return
		if not out_dir:
			QMessageBox.warning(self, "Missing Output", "Please choose an output folder.")
			return
		yt_override = self._yt_dlp_override()
		ff_override = self._ffmpeg_override()
		result = run_preflight_checks(yt_override, ff_override, skip_network=False)
		if result.errors:
			lines = "\n - ".join(["Preflight failed due to:"] + result.errors)
			QMessageBox.critical(self, "Preflight errors", lines)
			self.lbl_log.setText("Preflight errors detected. Resolve dependencies and try again.")
			return
		if result.warnings:
			warn_lines = "\n - ".join(["Warnings detected:"] + result.warnings)
			warn_lines += "\n\nContinue anyway?"
			choice = QMessageBox.question(self, "Preflight warnings", warn_lines, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
			if choice != QMessageBox.Yes:
				self.lbl_log.setText("Start cancelled after preflight warnings.")
				return
		if result.details:
			detail_lines = [f"{key}: {value}" for key, value in sorted(result.details.items())]
			self.lbl_log.setText("; ".join(detail_lines))
		self._allow_path_persist = True
		self._persist_settings(include_paths=self._allow_path_persist)

		try:
			self.tracks, queued_rows = self._build_track_preview()
		except Exception as e:
			QMessageBox.critical(self, "CSV Error", f"Failed to parse CSV:\n{e}")
			return
		if not self.tracks:
			QMessageBox.information(self, "No Tracks", "No tracks found in the CSV.")
			return
		if not queued_rows:
			self.btn_clear.setEnabled(True)
			self.lbl_log.setText("Everything in this playlist is already downloaded.")
			self._rewrite_playlists()
			QMessageBox.information(self, "Nothing to Download", "Every track in this playlist is already present in the output folder.")
			return
		batch_policy = youtube_batch_mitigation(len(self.tracks), using_cookies=bool(self._cookies_browser() or self._cookies_file()))
		if batch_policy.warning:
			msg = batch_policy.warning
			if batch_policy.reason:
				msg += f"\n\nReason: {batch_policy.reason.capitalize()}."
			msg += "\n\nContinue with automatic throttling enabled?"
			choice = QMessageBox.question(self, "YouTube risk warning", msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
			if choice != QMessageBox.Yes:
				self.lbl_log.setText("Start cancelled after YouTube risk warning.")
				return

		self.progress.setValue(0)
		self.progress.setMaximum(len(queued_rows))

		fmt = "m4a" if self.rb_m4a.isChecked() else "mp3"
		want_m3u8 = self.cb_m3u8.isChecked()
		want_m3u_plain = self.cb_m3u_plain.isChecked()
		embed_art = self.cb_album_art.isChecked()
		cookies_browser = self._cookies_browser()

		active_tracks = [self.tracks[i] for i in queued_rows]

		self.btn_scan_existing.setEnabled(False)
		self.btn_start.setEnabled(False)
		self.btn_stop.setEnabled(True)
		self.btn_clear.setEnabled(False)
		self.lbl_log.setText(f"Starting… {len(queued_rows)} new track(s) queued, {len(self.tracks) - len(queued_rows)} already in folder.")

		# playlist=None → worker picks a default name internally
		self.worker = PipelineWorker(
			csv_path,
			out_dir,
			None,
			fmt,
			want_m3u8,
			want_m3u_plain,
			embed_art,
			yt_override,
			ff_override,
			cookies_browser,
			self._cookies_file(),
			self._audio_processing_options(),
			mp3_quality=self._mp3_quality_value(),
			legacy_options=self._legacy_export_options(),
			force_download=bool(self.cb_force_download.isChecked()),
			tracks_override=active_tracks,
			row_indices=queued_rows,
			parent=self,
		)
		self.worker.sig_log.connect(self.lbl_log.setText)
		self.worker.sig_warning.connect(lambda msg: QMessageBox.warning(self, "YouTube throttling detected", msg))
		self.worker.sig_total.connect(lambda n: self.lbl_log.setText(f"Queued {n} tracks…"))
		self.worker.sig_match_stats.connect(lambda m, s: self.lbl_log.setText(f"Matched: {m} | Skipped: {s}"))
		self.worker.sig_row_status.connect(self.on_row_status)
		self.worker.sig_progress.connect(self.on_progress)
		self.worker.sig_done.connect(self.on_done)
		self.worker.sig_track_result.connect(self.on_track_result)
		self.worker.start()

	def on_stop(self):
		if self.worker:
			self.worker.stop()
			self.lbl_log.setText("Stopping…")
			self.btn_clear.setEnabled(False)

	def on_load_playlist(self):
		try:
			load_csv = self.ed_load_csv.text().strip()
			if not load_csv or not pathlib.Path(load_csv).exists():
				raise FileNotFoundError("Choose the playlist CSV in the Load Playlist panel first.")
			tracks = self._collect_tracks_preview(load_csv)
		except FileNotFoundError as e:
			QMessageBox.warning(self, "Missing CSV", str(e))
			return
		except Exception as e:
			QMessageBox.critical(self, "CSV Error", f"Failed to parse CSV:\n{e}")
			return
		if not tracks:
			QMessageBox.information(self, "No Tracks", "No tracks found in the CSV.")
			return
		try:
			selected_source = self.ed_load_source.text().strip()
			if not selected_source:
				raise ValueError("Choose the current music folder or a playlist .m3u/.m3u8 file in the Load Playlist panel first.")
			resolved_out_root = self._resolve_load_playlist_root(pathlib.Path(selected_source), tracks)
		except ValueError as e:
			QMessageBox.warning(self, "Invalid Playlist Selection", str(e))
			return
		self.ed_csv.setText(load_csv)
		self.ed_out.setText(str(resolved_out_root))
		try:
			tracks, queued_rows = self._build_track_preview()
		except ValueError as e:
			QMessageBox.warning(self, "Missing Output", str(e))
			return
		except Exception as e:
			QMessageBox.critical(self, "Load Error", f"Failed to load the playlist:\n{e}")
			return
		self.btn_start.setEnabled(bool(queued_rows))
		self.btn_stop.setEnabled(False)
		self.btn_clear.setEnabled(True)
		self.lbl_log.setText(
			f"Loaded {len(tracks)} track(s): {len(queued_rows)} queued, {len(tracks) - len(queued_rows)} already downloaded."
		)
		self._allow_path_persist = True
		self._persist_settings(include_paths=True)

	def on_track_result(self, row_idx: int, payload: dict) -> None:
		self.track_results[row_idx] = payload
		btn = self.action_buttons.get(row_idx)
		if btn:
			btn.setEnabled(True)
		track = payload.get("track")
		if track and 0 <= row_idx < len(self.tracks):
			self.tracks[row_idx] = track
		self._update_track_icon(row_idx, payload.get("cover_bytes"))
		playlist_name = payload.get("playlist_name")
		if playlist_name:
			self.last_playlist_name = playlist_name

	def _update_track_icon(self, row_idx: int, cover_bytes: bytes | None) -> None:
		if not (0 <= row_idx < self.table.rowCount()):
			return
		item = self.table.item(row_idx, 1)
		if item is None:
			return
		if cover_bytes:
			pm = QPixmap()
			pm.loadFromData(cover_bytes)
			if not pm.isNull():
				item.setIcon(QIcon(pm.scaled(
					self._row_icon_size,
					self._row_icon_size,
					Qt.KeepAspectRatioByExpanding,
					Qt.SmoothTransformation
				)))
				return
		if not self._default_track_icon.isNull():
			item.setIcon(self._default_track_icon)

	def on_open_alternatives(self, row_idx: int) -> None:
		info = self.track_results.get(row_idx)
		if not info:
			QMessageBox.information(self, "Results pending", "This track is still processing. Try again shortly.")
			return
		track = info.get("track")
		if not track:
			QMessageBox.warning(self, "Unavailable", "Track metadata is missing for this row.")
			return
		for other_row in list(self.resolve_items.keys()):
			if other_row != row_idx:
				self.on_resolution_close(other_row)
		options = info.get("options") or []
		self.on_resolution_options(row_idx, track, options)
		record = self.resolve_items.get(row_idx)
		if record and not record.get("loaded_more"):
			self.on_refresh_alternatives(row_idx)

	def on_clear(self):
		if self.worker:
			return
		for worker in self.manual_download_workers.values():
			if worker and worker.isRunning():
				QMessageBox.information(self, "Busy", "Wait for in-progress manual downloads to finish before clearing.")
				return
		self.tracks = []
		self.total = 0
		self.table.setRowCount(0)
		self.ed_csv.clear()
		self.lbl_log.clear()
		self.progress.setMaximum(0)
		self.progress.setValue(0)
		self.btn_scan_existing.setEnabled(True)
		self.btn_start.setEnabled(True)
		self.btn_stop.setEnabled(False)
		self.btn_clear.setEnabled(False)
		self._allow_path_persist = False
		self._persist_settings(include_paths=True)
		self.track_results = {}
		self.action_buttons = {}
		self.manual_download_workers = {}
		self._clear_resolution_panel()

	def on_row_status(self, row_idx: int, status: str):
		if 0 <= row_idx < self.table.rowCount():
			item = QTableWidgetItem(status)
			if status.startswith("Fail"):
				self._set_row_highlight(row_idx, RED)
			elif status.startswith("Skipped"):
				self._set_row_highlight(row_idx, YELLOW)
			elif status.startswith("Low confidence"):
				self._set_row_highlight(row_idx, YELLOW)
			elif status.startswith("Done") or status.startswith("Already downloaded"):
				self._set_row_highlight(row_idx, GREEN)
			elif status.startswith("Queued"):
				self._set_row_highlight(row_idx, YELLOW)
			else:
				self._set_row_highlight(row_idx, None)
			item.setBackground(self.table.item(row_idx, 1).background())
			self.table.setItem(row_idx, 2, item)

	def on_progress(self, processed: int, total: int):
		self.progress.setMaximum(total)
		self.progress.setValue(processed)

	def on_done(self, msg: str, matched: list, skipped: list, failed: list):
		from PySide6.QtWidgets import QApplication
		self.btn_scan_existing.setEnabled(True)
		self.btn_start.setEnabled(True)
		self.btn_stop.setEnabled(False)
		self.btn_clear.setEnabled(True)
		self.lbl_log.setText(msg)
		self._persist_settings(include_paths=self._allow_path_persist)
		QApplication.beep()
		if self.worker:
			self.worker.quit()
			self.worker.wait(1000)
			self.worker = None
		self._rewrite_playlists()
		requested = self.total or (len(matched) + len(skipped) + len(failed))
		already_downloaded = sum(1 for info in self.track_results.values() if info.get("existing"))
		processed = len(matched) + len(skipped) + len(failed) + already_downloaded
		pending = max(requested - processed, 0)
		lines = [
			f"Tracks requested: {requested}",
			f"Downloaded: {len(matched)}",
			f"Already in folder: {already_downloaded}",
			f"Skipped (no confident match): {len(skipped)}",
			f"Failed (errors): {len(failed)}"
		]
		if pending:
			lines.append(f"Pending (not processed): {pending}")
		if skipped:
			lines.append("")
			lines.append("Skipped examples:")
			for item in skipped[:5]:
				t = item.get("track", {})
				reason = item.get("reason") or "No confident match"
				lines.append(f" - {t.get('artists','')} — {t.get('title','')} ({reason})")
			if len(skipped) > 5:
				lines.append(f" - … {len(skipped) - 5} more")
		if failed:
			lines.append("")
			lines.append("Failed downloads:")
			for item in failed[:5]:
				t = item.get("track", {})
				reason = item.get("error") or "Unknown error"
				lines.append(f" - {t.get('artists','')} — {t.get('title','')} ({reason[:80]})")
			if len(failed) > 5:
				lines.append(f" - … {len(failed) - 5} more")
		if skipped:
			lines.append("")
			lines.append("Review alternative matches below to rescue skipped songs without rerunning the pipeline.")
		summary = "\n".join(lines)
		QMessageBox.information(self, "Download Summary", summary)
	def on_resolution_options(self, row_idx: int, track: dict, options: list) -> None:
		record = self.resolve_items.get(row_idx)
		if record:
			record["all_options"] = self._merge_options(record.get("all_options", []), options)
			self._refresh_option_combo(record)
		else:
			record = self._create_resolution_item(row_idx, track, options or [])
			self.resolve_items[row_idx] = record
			self.resolve_items_layout.addWidget(record["widget"])
		self.track_results.setdefault(row_idx, {"track": track})["options"] = record.get("all_options", [])
		self.resolve_box.setVisible(True)

	def _merge_options(self, existing: list, new_opts: list) -> list:
		seen = {opt.get("videoId") for opt in existing if opt.get("videoId")}
		for opt in new_opts:
			vid = opt.get("videoId")
			if vid and vid not in seen:
				existing.append(opt)
				seen.add(vid)
		return sorted(existing, key=lambda o: o.get("score", 0.0), reverse=True)

	def _refresh_option_combo(self, record: dict) -> None:
		combo = record["combo"]
		current_vid = None
		if combo.count() > 0:
			cur_data = combo.currentData()
			if isinstance(cur_data, dict):
				current_vid = cur_data.get("videoId")
		combo.clear()
		options = record.get("all_options", [])
		record["visible_options"] = options
		status = record["status_label"]
		if not options:
			combo.addItem("No matches found yet", None)
			record["btn_download"].setEnabled(False)
			status.setText("No matches found yet.")
		else:
			record["btn_download"].setEnabled(True)
			for opt in options:
				combo.addItem(self._format_option(opt), opt)
			status.setText(f"Showing {len(options)} result(s).")
		if current_vid:
			for idx in range(combo.count()):
				data = combo.itemData(idx)
				if isinstance(data, dict) and data.get("videoId") == current_vid:
					combo.setCurrentIndex(idx)
					break

	def _resolution_has_running_worker(self, row_idx: int) -> bool:
		record = self.resolve_items.get(row_idx)
		if not record:
			return False
		for key in ("alt_worker",):
			worker = record.get(key)
			if worker and worker.isRunning():
				return True
		return False

	def _create_resolution_item(self, row_idx: int, track: dict, options: list) -> dict:
		widget = QFrame()
		widget.setFrameShape(QFrame.StyledPanel)
		layout = QVBoxLayout(widget)
		layout.setContentsMargins(self._px(8), self._px(6), self._px(8), self._px(6))
		layout.setSpacing(self._px(4))
		title = QLabel(f"{track.get('artists','')} — {track.get('title','')}")
		title.setWordWrap(True)
		layout.addWidget(title)
		status_label = QLabel("Loading more choices when opened.")
		status_label.setWordWrap(True)
		layout.addWidget(status_label)
		combo = QComboBox()
		combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
		layout.addWidget(combo)
		btn_row = QHBoxLayout()
		btn_row.setSpacing(self._px(6))
		btn_download = QPushButton("Download")
		btn_skip = QPushButton("Skip Song")
		btn_close = QPushButton("Close")
		panel_font = self._button_font
		for w in (btn_download, btn_skip, btn_close):
			w.setFont(panel_font)
		btn_row.addWidget(btn_download)
		btn_row.addWidget(btn_skip)
		btn_row.addWidget(btn_close)
		btn_row.addStretch(1)
		layout.addLayout(btn_row)
		record = {
			"widget": widget,
			"track": track,
			"all_options": options,
			"visible_options": [],
			"combo": combo,
			"status_label": status_label,
			"btn_download": btn_download,
			"btn_skip": btn_skip,
			"btn_close": btn_close,
			"row_idx": row_idx,
			"alt_worker": None,
			"loaded_more": False
		}
		self._refresh_option_combo(record)
		btn_download.clicked.connect(partial(self.on_resolution_download, row_idx))
		btn_skip.clicked.connect(partial(self.on_resolution_skip, row_idx))
		btn_close.clicked.connect(partial(self.on_resolution_close, row_idx))
		return record

	def _format_option(self, option: dict) -> str:
		score = option.get("score") or 0.0
		title = option.get("title") or ""
		author = option.get("author") or ""
		dur = option.get("duration_seconds") or 0
		mins = dur // 60
		secs = dur % 60
		source = "Official Song" if option.get("source") == "music" else "YouTube Result"
		return f"[{source}] {score:.2f} • {title} ({author}) [{mins}:{secs:02d}]"

	def on_refresh_alternatives(self, row_idx: int) -> None:
		record = self.resolve_items.get(row_idx)
		if not record:
			return
		worker = record.get("alt_worker")
		if worker and worker.isRunning():
			return
		exclude_ids = {opt.get("videoId") for opt in record.get("all_options", []) if opt.get("videoId")}
		record["status_label"].setText("Looking for more choices…")
		worker = AlternativesFetchWorker(row_idx, record["track"], exclude_ids, self)
		record["alt_worker"] = worker
		worker.sig_done.connect(self.on_alternatives_fetched)
		worker.start()

	def on_alternatives_fetched(self, row_idx: int, options: list, error: str) -> None:
		record = self.resolve_items.get(row_idx)
		if not record:
			return
		record["alt_worker"] = None
		record["loaded_more"] = True
		if error:
			record["status_label"].setText(f"Could not refresh alternatives: {error}")
			return
		if options:
			record["all_options"] = self._merge_options(record.get("all_options", []), options)
			self.track_results.setdefault(row_idx, {"track": record["track"]})["options"] = record.get("all_options", [])
		record["status_label"].setText("Updated with more choices.")
		self._refresh_option_combo(record)

	def on_resolution_download(self, row_idx: int) -> None:
		record = self.resolve_items.get(row_idx)
		if not record:
			return
		active_worker = self.manual_download_workers.get(row_idx)
		if active_worker and active_worker.isRunning():
			QMessageBox.information(self, "Already Downloading", "This song already has an alternative download in progress.")
			return
		out_dir = self.ed_out.text().strip()
		if not out_dir:
			QMessageBox.warning(self, "Missing Output", "Choose an output folder before downloading.")
			return
		option = record["combo"].currentData()
		if not isinstance(option, dict) or not option.get("videoId"):
			QMessageBox.warning(self, "No Selection", "Select a candidate before downloading.")
			return
		fmt = "m4a" if self.rb_m4a.isChecked() else "mp3"
		record["btn_download"].setEnabled(False)
		record["btn_skip"].setEnabled(False)
		record["btn_close"].setEnabled(False)
		worker = SingleDownloadWorker(
			row_idx,
			record["track"],
			option,
			out_dir,
			fmt,
			self.cb_album_art.isChecked(),
			self._yt_dlp_override(),
			self._ffmpeg_override(),
			self._cookies_browser(),
			self._cookies_file(),
			self._audio_processing_options(),
			self._mp3_quality_value(),
			self._legacy_export_options(),
			parent=self
		)
		self.manual_download_workers[row_idx] = worker
		worker.sig_status.connect(self.on_row_status)
		worker.sig_finished.connect(self.on_resolution_finished)
		worker.start()
		self.lbl_log.setText(f"Manual download queued: {record['track'].get('artists','')} — {record['track'].get('title','')}")
		self.on_row_status(row_idx, "Queued (manual alternative)")

	def on_resolution_skip(self, row_idx: int) -> None:
		download_worker = self.manual_download_workers.get(row_idx)
		if download_worker and download_worker.isRunning():
			QMessageBox.information(
				self,
				"Please wait",
				"Finish the manual alternative download for this song before skipping it."
			)
			return
		if self._resolution_has_running_worker(row_idx):
			QMessageBox.information(
				self,
				"Please wait",
				"Finish loading this alternatives list before skipping the song."
			)
			return
		record = self.resolve_items.pop(row_idx, None)
		info = self.track_results.get(row_idx)
		track = None
		if record:
			track = record.get("track")
		elif info:
			track = info.get("track")
		if not track:
			return
		self.lbl_log.setText(f"Skipped track: {track.get('artists','')} — {track.get('title','')}")
		self.on_row_status(row_idx, "Skipped (removed)")
		if info:
			fp = info.get("file_path")
			if fp:
				try:
					pathlib.Path(fp).unlink(missing_ok=True)
				except Exception:
					pass
			info["removed"] = True
		self._rewrite_playlists()
		btn = self.action_buttons.get(row_idx)
		if btn:
			btn.setEnabled(False)
		if record:
			record["widget"].setParent(None)
			record["widget"].deleteLater()
		if not self.resolve_items:
			self.resolve_box.setVisible(False)

	def on_resolution_close(self, row_idx: int) -> None:
		record = self.resolve_items.pop(row_idx, None)
		if not record:
			return
		alt_worker = record.get("alt_worker")
		if alt_worker and alt_worker.isRunning():
			self._shutdown_thread(alt_worker, wait_ms=500)
			record["alt_worker"] = None
		record["widget"].setParent(None)
		record["widget"].deleteLater()
		if not self.resolve_items:
			self.resolve_box.setVisible(False)

	def on_resolution_finished(self, row_idx: int, payload: dict) -> None:
		self.manual_download_workers.pop(row_idx, None)
		record = self.resolve_items.get(row_idx)
		if record:
			record["btn_download"].setEnabled(True)
			record["btn_skip"].setEnabled(True)
			record["btn_close"].setEnabled(True)
		info = self.track_results.setdefault(row_idx, {})
		info.update(payload)
		track = info.get("track")
		if track and 0 <= row_idx < len(self.tracks):
			self.tracks[row_idx] = track
		if info.get("downloaded"):
			self.lbl_log.setText(f"Manual download complete: {track.get('artists','')} — {track.get('title','')}")
			if record:
				record["widget"].setParent(None)
				record["widget"].deleteLater()
				self.resolve_items.pop(row_idx, None)
				if not self.resolve_items:
					self.resolve_box.setVisible(False)
			self.on_row_status(row_idx, "Done (manual override)")
			btn = self.action_buttons.get(row_idx)
			if btn:
				btn.setEnabled(True)
		else:
			err = info.get("error") or "Unknown error"
			self.lbl_log.setText(f"Manual download failed: {err}")
			if record:
				record["status_label"].setText(f"Download failed: {err}")
		self._rewrite_playlists()

	def _clear_resolution_panel(self) -> None:
		for record in list(self.resolve_items.values()):
			alt_worker = record.get("alt_worker")
			if alt_worker and alt_worker.isRunning():
				self._shutdown_thread(alt_worker, wait_ms=500)
				record["alt_worker"] = None
			widget = record.get("widget")
			if widget is not None:
				widget.setParent(None)
				widget.deleteLater()
		self.resolve_items.clear()
		self.resolve_box.setVisible(False)

	def _rewrite_playlists(self) -> None:
		out_dir_text = self.ed_out.text().strip()
		if not out_dir_text:
			return
		out_root = pathlib.Path(out_dir_text)
		write_m3u8 = self.cb_m3u8.isChecked()
		write_m3u_plain = self.cb_m3u_plain.isChecked()
		ordered_entries: list[tuple[dict, pathlib.Path]] = []
		playlist_name = None
		for row in range(self.table.rowCount()):
			info = self.track_results.get(row)
			if not info or not info.get("downloaded") or info.get("removed"):
				continue
			track = info.get("track")
			fp = info.get("file_path")
			if not track or not fp:
				continue
			path_obj = pathlib.Path(fp).resolve()
			ordered_entries.append((track, path_obj))
			if not playlist_name:
				playlist_name = info.get("playlist_name") or track.get("playlist")
		if not ordered_entries:
			name = self.last_playlist_name or "Playlist"
			self._remove_playlist_file(out_root, name, ".m3u8")
			self._remove_playlist_file(out_root, name, ".m3u")
			return
		playlist_name = playlist_name or self.last_playlist_name or "Playlist"
		self.last_playlist_name = playlist_name
		entries_resolved: list[tuple[dict, pathlib.Path]] = []
		for track, abs_path in ordered_entries:
			entries_resolved.append((track, abs_path))
		# determine extension from actual files
		ext = "m4a"
		for _, abs_path in entries_resolved:
			suf = abs_path.suffix.lower().lstrip('.')
			if suf in ("m4a", "mp3"):
				ext = suf
				break
		if write_m3u8:
			self._write_playlist_file(out_root, playlist_name, entries_resolved, ext, ".m3u8", "utf-8")
		else:
			self._remove_playlist_file(out_root, playlist_name, ".m3u8")
		if write_m3u_plain:
			self._write_playlist_file(out_root, playlist_name, entries_resolved, ext, ".m3u", "utf-8-sig")
		else:
			self._remove_playlist_file(out_root, playlist_name, ".m3u")

	def _write_playlist_file(self, out_root: pathlib.Path, playlist_name: str, entries: list[tuple[dict, pathlib.Path]], ext: str, suffix: str, encoding: str) -> None:
		playlist_dir = out_root / sanitize_name(playlist_name)
		playlist_dir.mkdir(parents=True, exist_ok=True)
		file_path = playlist_dir / f"{sanitize_name(playlist_name)}{suffix}"
		try:
			lines = ["#EXTM3U", f"#EXTPLAYLIST:{playlist_name}"]
			root_resolved = playlist_dir.resolve()
			for track, abs_path in entries:
				duration = int(round((track.get("duration_ms") or 0) / 1000))
				artists = track.get("artists", "")
				title = track.get("title", "")
				lines.append(f"#EXTINF:{duration},{artists} - {title}")
				abs_path = abs_path.resolve()
				try:
					path_obj = abs_path.relative_to(root_resolved)
				except ValueError:
					path_obj = abs_path
				path_str = str(path_obj)
				lines.append(path_str)
			content = "\r\n".join(lines) + "\r\n"
			with file_path.open("w", encoding=encoding, errors="ignore", newline="") as f:
				f.write(content)
		except Exception as exc:
			self.lbl_log.setText(f"Failed to update playlists: {exc}")

	def _remove_playlist_file(self, out_root: pathlib.Path, playlist_name: str, suffix: str) -> None:
		file_path = out_root / sanitize_name(playlist_name) / f"{sanitize_name(playlist_name)}{suffix}"
		if file_path.exists():
			try:
				file_path.unlink()
			except Exception:
				pass

	def _shutdown_thread(self, thread, *, wait_ms: int = 1500) -> None:
		if not thread:
			return
		try:
			if hasattr(thread, "stop"):
				thread.stop()
		except Exception:
			pass
		try:
			thread.requestInterruption()
		except Exception:
			pass
		try:
			thread.quit()
		except Exception:
			pass
		try:
			if thread.isRunning():
				thread.wait(wait_ms)
		except Exception:
			pass
		try:
			if thread.isRunning():
				thread.terminate()
				thread.wait(1000)
		except Exception:
			pass

	def closeEvent(self, event):
		"""Ensure all threads are stopped before closing"""
		# Stop main worker if running
		self._shutdown_thread(self.worker, wait_ms=3000)
		self.worker = None

		# Stop cookie check worker if running
		self._shutdown_thread(self.cookie_check_worker, wait_ms=500)
		self.cookie_check_worker = None

		# Stop resolution workers if running
		for record in list(self.resolve_items.values()):
			for key in ("alt_worker",):
				self._shutdown_thread(record.get(key), wait_ms=1000)
				record[key] = None
		for row_idx, worker in list(self.manual_download_workers.items()):
			self._shutdown_thread(worker, wait_ms=1000)
			self.manual_download_workers.pop(row_idx, None)

		event.accept()
