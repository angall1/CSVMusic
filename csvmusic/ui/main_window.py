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
	QComboBox, QSlider
)
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap, QFontDatabase, QGuiApplication

from csvmusic.core.csv_import import load_csv, tracks_from_csv, deduplicate_tracks
from csvmusic.core.settings import load_settings, save_settings
from csvmusic.core.downloader import sanitize_name, youtube_batch_mitigation
from csvmusic.core.preflight import run_preflight_checks
from csvmusic.core.paths import app_icon_path, resource_base
from csvmusic.ui.workers import PipelineWorker, SingleDownloadWorker, CookiesCheckWorker, AlternativesFetchWorker
from csvmusic.core.browsers import list_profiles

YELLOW = QColor(255, 244, 179)   # soft yellow
RED = QColor(255, 205, 210)      # soft red
GREEN = QColor(200, 230, 201)    # soft green

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
				color: {win_text};
			}}
			QCheckBox, QRadioButton {{
				color: {win_text};
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
		lbl_link.setOpenExternalLinks(True)
		lbl_link.setTextInteractionFlags(Qt.TextBrowserInteraction)
		lbl_link.setStyleSheet("a { color: #000080; text-decoration: none; }")
		top.addWidget(lbl_link)
		btn_help = QToolButton()
		btn_help.setText("TUTORIAL ▸")
		btn_help.setCheckable(True)
		btn_help.setToolButtonStyle(Qt.ToolButtonTextOnly)
		btn_font = QFont(retro_font_family, default_pt + 1, QFont.Bold)
		btn_help.setFont(btn_font)
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
		help_layout.setSpacing(self._px(6))
		help_text = QLabel(
			"Instructions:\n"
			"1) Click the link above → select your music platform\n"
			"2) Paste your playlist URL\n"
			"3) Choose destination\n"
			"4) Export to file → CSV\n"
			"\n"
			"Save the exported CSV (e.g., 'My Spotify Library.csv'), then select it below.\n"
			"\n"
			"Tips:\n"
			"• Use EQUALIZER if you want louder output, bass/treble changes, or track-to-track volume matching.\n"
			"• Use LOAD PLAYLIST if you already have songs in a playlist folder and only want to download the new ones.\n"
			"• LOAD PLAYLIST accepts the playlist CSV plus either the output folder, the playlist folder, or that playlist's .m3u/.m3u8 file."
		)
		help_text.setFont(QFont(retro_font_family, default_pt + 3))
		help_text.setWordWrap(True)
		help_text.setMinimumHeight(self._px(160))
		help_layout.addWidget(help_text)
		self.help_panel.setVisible(False)
		vl.addWidget(self.help_panel)
		def _toggle_help(checked: bool):
			self.help_panel.setVisible(checked)
			btn_help.setText("TUTORIAL ▾" if checked else "TUTORIAL ▸")
		btn_help.toggled.connect(_toggle_help)

		self.load_panel = QFrame()
		self.load_panel.setFrameShape(QFrame.StyledPanel)
		self.load_panel.setStyleSheet("background-color: #bcb7ae;")
		load_layout = QVBoxLayout(self.load_panel)
		load_layout.setContentsMargins(self._px(12), self._px(10), self._px(12), self._px(10))
		load_layout.setSpacing(self._px(8))
		load_note = QLabel(
			"Use this when you already have music in a playlist folder and want CSVMusic to skip files that are already there."
		)
		load_note.setWordWrap(True)
		load_note.setFont(QFont(retro_font_family, default_pt))
		load_layout.addWidget(load_note)
		load_row_csv = QHBoxLayout()
		lbl_load_csv = QLabel("Playlist CSV:")
		lbl_load_csv.setFont(QFont(retro_font_family, default_pt + 1, QFont.Bold))
		self.ed_load_csv = QLineEdit()
		self.ed_load_csv.setPlaceholderText("CSV for the playlist you want to refresh")
		self.ed_load_csv.setFont(QFont(retro_font_family, default_pt + 1))
		btn_load_csv = QPushButton("Browse…")
		btn_load_csv.setFont(btn_font)
		btn_load_csv.clicked.connect(self.on_browse_load_csv)
		load_row_csv.addWidget(lbl_load_csv)
		load_row_csv.addWidget(self.ed_load_csv, 1)
		load_row_csv.addWidget(btn_load_csv)
		load_layout.addLayout(load_row_csv)
		load_row_source = QHBoxLayout()
		lbl_load_source = QLabel("Current music:")
		lbl_load_source.setFont(QFont(retro_font_family, default_pt + 1, QFont.Bold))
		self.ed_load_source = QLineEdit()
		self.ed_load_source.setPlaceholderText("Playlist folder, output folder, or that playlist's .m3u/.m3u8 file")
		self.ed_load_source.setFont(QFont(retro_font_family, default_pt + 1))
		btn_load_source = QPushButton("Browse…")
		btn_load_source.setFont(btn_font)
		btn_load_source.clicked.connect(self.on_browse_load_source)
		load_row_source.addWidget(lbl_load_source)
		load_row_source.addWidget(self.ed_load_source, 1)
		load_row_source.addWidget(btn_load_source)
		load_layout.addLayout(load_row_source)
		load_action_row = QHBoxLayout()
		self.btn_scan_existing = QPushButton("Load Existing Playlist")
		self.btn_scan_existing.setFont(QFont(retro_font_family, default_pt + 2, QFont.Bold))
		self.btn_scan_existing.clicked.connect(self.on_load_playlist)
		load_action_row.addWidget(self.btn_scan_existing)
		load_action_row.addStretch(1)
		load_layout.addLayout(load_action_row)
		self.load_panel.setVisible(False)
		vl.addWidget(self.load_panel)
		def _toggle_load_panel(checked: bool):
			self.load_panel.setVisible(checked)
			btn_load.setText("LOAD PLAYLIST ▾" if checked else "LOAD PLAYLIST ▸")
		btn_load.toggled.connect(_toggle_load_panel)

		self.equalizer_panel = QFrame()
		self.equalizer_panel.setFrameShape(QFrame.StyledPanel)
		self.equalizer_panel.setStyleSheet("background-color: #bcb7ae;")
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
			self.equalizer_panel.setVisible(checked)
			btn_eq.setText("EQUALIZER ▾" if checked else "EQUALIZER ▸")
		btn_eq.toggled.connect(_toggle_equalizer)

		self.advanced_panel = QFrame()
		self.advanced_panel.setFrameShape(QFrame.StyledPanel)
		adv_layout = QVBoxLayout(self.advanced_panel)
		adv_layout.setContentsMargins(self._px(12), self._px(10), self._px(12), self._px(10))
		adv_layout.setSpacing(self._px(8))
		# Darker background for clarity
		self.advanced_panel.setStyleSheet("background-color: #bcb7ae;")
		note = QLabel("These overrides are optional. Leave blank to use bundled tools.")
		note.setWordWrap(True)
		note.setFont(QFont(retro_font_family, default_pt))
		adv_layout.addWidget(note)
		row_ytdlp = QHBoxLayout()
		lbl_ytdlp = QLabel("yt-dlp path:")
		lbl_ytdlp.setFont(QFont(retro_font_family, default_pt + 1, QFont.Bold))
		self.ed_ytdlp = QLineEdit()
		self.ed_ytdlp.setPlaceholderText("Auto-detect from PATH")
		self.ed_ytdlp.setFont(QFont(retro_font_family, default_pt + 1))
		self.ed_ytdlp.textChanged.connect(lambda _=None: self._persist_settings())
		btn_ytdlp = QPushButton("Browse…")
		btn_ytdlp.setFont(btn_font)
		btn_ytdlp.clicked.connect(self.on_browse_ytdlp)
		btn_ytdlp_clear = QPushButton("Clear")
		btn_ytdlp_clear.setFont(btn_font)
		btn_ytdlp_clear.clicked.connect(self.on_clear_ytdlp)
		row_ytdlp.addWidget(lbl_ytdlp)
		row_ytdlp.addWidget(self.ed_ytdlp, 1)
		row_ytdlp.addWidget(btn_ytdlp)
		row_ytdlp.addWidget(btn_ytdlp_clear)
		adv_layout.addLayout(row_ytdlp)
		row_ffmpeg = QHBoxLayout()
		lbl_ffmpeg = QLabel("FFmpeg path:")
		lbl_ffmpeg.setFont(QFont(retro_font_family, default_pt + 1, QFont.Bold))
		self.ed_ffmpeg = QLineEdit()
		self.ed_ffmpeg.setPlaceholderText("Uses bundled binary by default")
		self.ed_ffmpeg.setFont(QFont(retro_font_family, default_pt + 1))
		self.ed_ffmpeg.textChanged.connect(lambda _=None: self._persist_settings())
		btn_ffmpeg = QPushButton("Browse…")
		btn_ffmpeg.setFont(btn_font)
		btn_ffmpeg.clicked.connect(self.on_browse_ffmpeg)
		btn_ffmpeg_clear = QPushButton("Clear")
		btn_ffmpeg_clear.setFont(btn_font)
		btn_ffmpeg_clear.clicked.connect(self.on_clear_ffmpeg)
		row_ffmpeg.addWidget(lbl_ffmpeg)
		row_ffmpeg.addWidget(self.ed_ffmpeg, 1)
		row_ffmpeg.addWidget(btn_ffmpeg)
		row_ffmpeg.addWidget(btn_ffmpeg_clear)
		adv_layout.addLayout(row_ffmpeg)
		self.cb_readability_mode = QCheckBox("Readable text")
		self.cb_readability_mode.setFont(QFont(retro_font_family, default_pt + 1, QFont.Bold))
		self.cb_readability_mode.toggled.connect(self.on_toggle_readability_mode)
		adv_layout.addWidget(self.cb_readability_mode)
		# Firefox is the only browser-cookie path reliable enough to expose directly.
		self._detected_firefox_profile: str | None = None
		self._cookies_test_ok = False
		row_firefox = QHBoxLayout()
		lbl_firefox = QLabel("YouTube login:")
		lbl_firefox.setFont(QFont(retro_font_family, default_pt + 1, QFont.Bold))
		self.cb_use_cookies = QCheckBox("Use Cookies")
		self.cb_use_cookies.setFont(QFont(retro_font_family, default_pt + 1, QFont.Bold))
		self.cb_use_cookies.setEnabled(False)
		self.cb_use_cookies.toggled.connect(lambda _=None: self._persist_settings())
		self.btn_detect_firefox_cookies = QPushButton("Detect Cookies from Firefox")
		self.btn_detect_firefox_cookies.setFont(btn_font)
		self.btn_detect_firefox_cookies.clicked.connect(self.on_detect_firefox_cookies)
		self.btn_test_cookies = QPushButton("Test Cookies")
		self.btn_test_cookies.setFont(btn_font)
		self.btn_test_cookies.clicked.connect(self.on_test_cookies)
		row_firefox.addWidget(lbl_firefox)
		row_firefox.addWidget(self.cb_use_cookies)
		row_firefox.addWidget(self.btn_detect_firefox_cookies)
		row_firefox.addWidget(self.btn_test_cookies)
		row_firefox.addStretch(1)
		adv_layout.addLayout(row_firefox)
		lbl_ff_tip = QLabel("Cookies help with age-restricted or sign-in-only YouTube results. Sign into YouTube in Firefox, click Detect, then Test. The Use Cookies checkbox unlocks only after the test passes. <a href=\"https://www.mozilla.org/firefox/download/\">Get Firefox</a>")
		lbl_ff_tip.setOpenExternalLinks(True)
		lbl_ff_tip.setTextInteractionFlags(Qt.TextBrowserInteraction)
		lbl_ff_tip.setFont(QFont(retro_font_family, default_pt))
		adv_layout.addWidget(lbl_ff_tip)
		# Cookies file alternative
		row_cookie_file = QHBoxLayout()
		lbl_cookie_file = QLabel("Cookies file (.txt):")
		lbl_cookie_file.setFont(QFont(retro_font_family, default_pt + 1, QFont.Bold))
		self.ed_cookies_file = QLineEdit()
		self.ed_cookies_file.setPlaceholderText("Optional: Netscape cookies.txt (YouTube domain)")
		self.ed_cookies_file.setFont(QFont(retro_font_family, default_pt + 1))
		self.ed_cookies_file.textChanged.connect(self.on_cookies_file_changed)
		btn_cookie_file = QPushButton("Browse...")
		btn_cookie_file.setFont(btn_font)
		btn_cookie_file.clicked.connect(self.on_browse_cookies_file)
		btn_cookie_file_clear = QPushButton("Clear")
		btn_cookie_file_clear.setFont(btn_font)
		btn_cookie_file_clear.clicked.connect(self.on_clear_cookies_file)
		row_cookie_file.addWidget(lbl_cookie_file)
		row_cookie_file.addWidget(self.ed_cookies_file, 1)
		row_cookie_file.addWidget(btn_cookie_file)
		row_cookie_file.addWidget(btn_cookie_file_clear)
		adv_layout.addLayout(row_cookie_file)
		# Cookie check status label
		self.lbl_cookie_status = QLabel("")
		self.lbl_cookie_status.setVisible(False)
		self.lbl_cookie_status.setFont(QFont(retro_font_family, max(default_pt - 1, 8)))
		adv_layout.addWidget(self.lbl_cookie_status)
		self.advanced_panel.setVisible(False)
		vl.addWidget(self.advanced_panel)

		def _toggle_advanced(checked: bool):
			self.advanced_panel.setVisible(checked)
			btn_adv.setText("SETTINGS ▾" if checked else "SETTINGS ▸")
		btn_adv.toggled.connect(_toggle_advanced)

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
		self.rb_m4a = QRadioButton("m4a (AAC, preferred)"); self.rb_m4a.setChecked(True)
		self.rb_mp3 = QRadioButton("mp3")
		self.grp_fmt = QButtonGroup(self); self.grp_fmt.addButton(self.rb_m4a); self.grp_fmt.addButton(self.rb_mp3)
		self.grp_fmt.buttonToggled.connect(lambda _button, checked: self._persist_settings() if checked else None)
		self.cb_m3u8 = QCheckBox("Write .m3u8")
		self.cb_m3u_plain = QCheckBox("Write .m3u"); self.cb_m3u_plain.setChecked(True)
		self.cb_album_art = QCheckBox("Embed album art"); self.cb_album_art.setChecked(True)
		controls_font = QFont(retro_font_family, default_pt + 2)
		for w in (self.rb_m4a, self.rb_mp3, self.cb_m3u8, self.cb_m3u_plain, self.cb_album_art):
			w.setFont(controls_font)
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
		self.table = QTableWidget(0, 5)
		self.table.setHorizontalHeaderLabels(["#", "Title", "Playlists", "Status", "Actions"])
		self.table.verticalHeader().setVisible(False)
		self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
		self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
		self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
		self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
		self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
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

	def _apply_font_family(self, family: str) -> None:
		self.setFont(QFont(family, self._default_pt))
		self._root_widget.setStyleSheet(self._base_stylesheet_template.replace("__FONT_FAMILY__", family))
		self._button_font = QFont(family, self._default_pt + 2, QFont.Bold)
		self._swap_font_family(self, family)
		for widget in self.findChildren(QWidget):
			self._swap_font_family(widget, family)
		self.table.horizontalHeader().setFont(QFont(family, self._default_pt + 2, QFont.Bold))

	def on_toggle_readability_mode(self, checked: bool) -> None:
		self._readability_mode = bool(checked)
		family = self._readable_font_family if self._readability_mode else self._retro_font_family
		self._apply_font_family(family)
		self._persist_settings()

	def _make_eq_slider(self, parent_layout: QVBoxLayout, label: str, font_family: str, default_pt: int) -> tuple[QSlider, QLabel, QLabel]:
		row = QHBoxLayout()
		lbl = QLabel(f"{label}:")
		lbl.setFont(QFont(font_family, default_pt + 1, QFont.Bold))
		slider = QSlider(Qt.Horizontal)
		slider.setRange(-15, 15)
		slider.setValue(0)
		slider.setTickInterval(1)
		slider.setTickPosition(QSlider.TicksBelow)
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
		from PySide6.QtGui import QDesktopServices
		from PySide6.QtCore import QUrl
		QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

	def _collect_tracks_preview(self, csv_path: str | None = None) -> List[dict]:
		target_csv = csv_path or self.ed_csv.text().strip()
		df = load_csv(target_csv)
		self.raw_tracks = tracks_from_csv(df, None)  # use entire CSV
		return deduplicate_tracks(self.raw_tracks)

	def _set_row_highlight(self, row_idx: int, color: QColor | None) -> None:
		if not (0 <= row_idx < self.table.rowCount()):
			return
		for col in (0, 1, 2):
			item = self.table.item(row_idx, col)
			if item is None:
				continue
			item.setBackground(color if color is not None else QColor(Qt.transparent))

	def _playlist_dir_name(self, tracks: list[dict]) -> str:
		playlist_names: list[str] = []
		for t in tracks:
			for pl in t.get("playlists") or [t.get("playlist") or ""]:
				if pl and pl not in playlist_names:
					playlist_names.append(pl)
		if playlist_names:
			if len(playlist_names) <= 2:
				playlist_name = " + ".join(playlist_names)
			else:
				playlist_name = " + ".join(playlist_names[:2]) + f" + {len(playlist_names) - 2} more"
		else:
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
		# Support both old 'playlist' (str) and new 'playlists' (list) fields
		playlists_field = track.get("playlists")
		if playlists_field and isinstance(playlists_field, list) and playlists_field:
			playlist_name = playlists_field[0]
		else:
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
			playlists_str = ", ".join(track.get("playlists") or [track.get("playlist") or ""])
			self.table.setItem(i, 2, QTableWidgetItem(playlists_str))
			btn_alt = QPushButton("Alternatives")
			btn_alt.setEnabled(False)
			btn_alt.clicked.connect(partial(self.on_open_alternatives, i))
			self.table.setCellWidget(i, 4, btn_alt)
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
				self.table.setItem(i, 3, QTableWidgetItem("Queued"))
				self._set_row_highlight(i, YELLOW)
				queued_rows.append(i)
		self.total = len(tracks)
		self.progress.setMaximum(max(len(queued_rows), 1))
		self.progress.setValue(0)
		self.last_playlist_name = self._playlist_dir_name(tracks)
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
			tracks_override=active_tracks,
			row_indices=queued_rows,
			raw_tracks_override=getattr(self, "raw_tracks", None),
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
		for info in self.resolve_items.values():
			download_worker = info.get("download_worker")
			if download_worker and download_worker.isRunning():
				QMessageBox.information(self, "Busy", "Wait for in-progress manual downloads to finish before clearing.")
				return
		self.tracks = []
		self.raw_tracks = []
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
		self._clear_resolution_panel()

	def on_row_status(self, row_idx: int, status: str):
		if 0 <= row_idx < self.table.rowCount():
			item = QTableWidgetItem(status)
			if status.startswith("Fail"):
				self._set_row_highlight(row_idx, RED)
			elif status.startswith("Skipped"):
				self._set_row_highlight(row_idx, YELLOW)
			elif status.startswith("Done") or status.startswith("Already downloaded"):
				self._set_row_highlight(row_idx, GREEN)
			elif status.startswith("Queued"):
				self._set_row_highlight(row_idx, YELLOW)
			else:
				self._set_row_highlight(row_idx, None)
			item.setBackground(self.table.item(row_idx, 1).background())
			self.table.setItem(row_idx, 3, item)

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
			"download_worker": None,
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
			self
		)
		record["download_worker"] = worker
		worker.sig_status.connect(self.on_row_status)
		worker.sig_finished.connect(self.on_resolution_finished)
		worker.start()
		self.lbl_log.setText(f"Manual download queued: {record['track'].get('artists','')} — {record['track'].get('title','')}")

	def on_resolution_skip(self, row_idx: int) -> None:
		record = self.resolve_items.pop(row_idx, None)
		if not record:
			return
		for key in ("download_worker", "alt_worker"):
			worker = record.get(key)
			if worker and worker.isRunning():
				worker.quit()
				worker.wait(1000)
		self.lbl_log.setText(f"Skipped track: {record['track'].get('artists','')} — {record['track'].get('title','')}")
		self.on_row_status(row_idx, "Skipped (removed)")
		info = self.track_results.get(row_idx)
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
		record["widget"].setParent(None)
		record["widget"].deleteLater()
		if not self.resolve_items:
			self.resolve_box.setVisible(False)

	def on_resolution_close(self, row_idx: int) -> None:
		record = self.resolve_items.pop(row_idx, None)
		if not record:
			return
		for key in ("download_worker", "alt_worker"):
			worker = record.get(key)
			if worker and worker.isRunning():
				worker.quit()
				worker.wait(1000)
		record["widget"].setParent(None)
		record["widget"].deleteLater()
		if not self.resolve_items:
			self.resolve_box.setVisible(False)

	def on_resolution_finished(self, row_idx: int, payload: dict) -> None:
		record = self.resolve_items.get(row_idx)
		if record:
			record["download_worker"] = None
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
		self._rewrite_playlists()

	def _clear_resolution_panel(self) -> None:
		for record in list(self.resolve_items.values()):
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

		# Build map of downloaded info: { (title, artist): (track, abs_path) }
		downloaded_info = {}
		for row in range(self.table.rowCount()):
			info = self.track_results.get(row)
			if not info or not info.get("downloaded") or info.get("removed"):
				continue
			track = info.get("track")
			fp = info.get("file_path")
			if not track or not fp:
				continue
			key = (track.get("title", "").lower().strip(), track.get("artists", "").lower().strip())
			abs_path = pathlib.Path(fp).resolve()
			downloaded_info[key] = (track, abs_path)

		# Build per-playlist maps: {playlist_name: [(track, abs_path)]} mapped by original sequence
		pl_entries: dict[str, list[tuple[dict, pathlib.Path]]] = {}
		
		# If we have raw_tracks (from a CSV load), map through them to preserve sequence
		raw_tracks = getattr(self, "raw_tracks", None)
		if raw_tracks is not None:
			for rt in raw_tracks:
				key = (rt.get("title", "").lower().strip(), rt.get("artists", "").lower().strip())
				if key in downloaded_info:
					track, abs_path = downloaded_info[key]
					# which playlist did this original row belong to?
					pl = rt.get("playlist")
					if not pl and rt.get("playlists"):
						pl = rt.get("playlists")[0]
					if not pl:
						pl = self.last_playlist_name or "Playlist"
					pl_entries.setdefault(pl, []).append((track, abs_path))
		else:
			# Fallback for old/simple M3U scans where raw_tracks is not populated
			for track, abs_path in downloaded_info.values():
				playlists_field = track.get("playlists")
				if playlists_field and isinstance(playlists_field, list):
					track_playlists = [pl for pl in playlists_field if pl]
				else:
					pl = info.get("playlist_name") or track.get("playlist") or ""
					track_playlists = [pl] if pl else []
				if not track_playlists:
					track_playlists = [self.last_playlist_name or "Playlist"]
				for pl_name in track_playlists:
					pl_entries.setdefault(pl_name, []).append((track, abs_path))

		if not pl_entries:
			# Nothing downloaded — remove files for last known playlist only
			name = self.last_playlist_name or "Playlist"
			self._remove_playlist_file(out_root, name, ".m3u8")
			self._remove_playlist_file(out_root, name, ".m3u")
			return

		# Determine extension from actual files
		ext = "m4a"
		for _, abs_path in next(iter(pl_entries.values())):
			suf = abs_path.suffix.lower().lstrip('.')
			if suf in ("m4a", "mp3"):
				ext = suf
				break

		# All M3U files go into the same shared folder as the audio files
		first_path = next(iter(next(iter(pl_entries.values()))))[1]
		shared_dir = first_path.parent

		for pl_name, entries in pl_entries.items():
			if write_m3u8:
				self._write_playlist_file(out_root, pl_name, entries, ext, ".m3u8", "utf-8", target_dir=shared_dir)
			else:
				self._remove_playlist_file(out_root, pl_name, ".m3u8", shared_dir=shared_dir)
			if write_m3u_plain:
				self._write_playlist_file(out_root, pl_name, entries, ext, ".m3u", "utf-8-sig", target_dir=shared_dir)
			else:
				self._remove_playlist_file(out_root, pl_name, ".m3u", shared_dir=shared_dir)

	def _write_playlist_file(self, out_root: pathlib.Path, playlist_name: str, entries: list[tuple[dict, pathlib.Path]], ext: str, suffix: str, encoding: str, *, target_dir: pathlib.Path | None = None) -> None:
		playlist_dir = target_dir if target_dir is not None else (out_root / sanitize_name(playlist_name))
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

	def _remove_playlist_file(self, out_root: pathlib.Path, playlist_name: str, suffix: str, *, shared_dir: pathlib.Path | None = None) -> None:
		if shared_dir is not None:
			file_path = shared_dir / f"{sanitize_name(playlist_name)}{suffix}"
		else:
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
			for key in ("download_worker", "alt_worker"):
				self._shutdown_thread(record.get(key), wait_ms=1000)
				record[key] = None

		event.accept()
