# tabs only
import pathlib
from functools import partial
from typing import List, Tuple
from PySide6.QtWidgets import (
	QMainWindow, QWidget, QFileDialog, QMessageBox,
	QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
	QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox,
	QRadioButton, QButtonGroup, QProgressBar, QToolButton, QSizePolicy, QFrame, QComboBox
)
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap, QFontDatabase, QGuiApplication

from csvmusic.core.csv_import import load_csv, tracks_from_csv
from csvmusic.core.settings import load_settings, save_settings
from csvmusic.core.downloader import sanitize_name
from csvmusic.core.preflight import run_preflight_checks
from csvmusic.core.paths import app_icon_path, resource_base
from csvmusic.ui.workers import PipelineWorker, SingleDownloadWorker, CookiesCheckWorker
from csvmusic.core.browsers import list_profiles, list_available_browsers

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
		retro_font_family = font_candidate if font_candidate in QFontDatabase().families() else "Tahoma"
		default_pt = max(self.font().pointSize(), 9)
		retro_font = QFont(retro_font_family, default_pt)
		self.setFont(retro_font)
		root.setStyleSheet(f"""
			QWidget {{
				background-color: {win_base};
				color: {win_text};
				font-family: '{retro_font_family}';
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
		""")

		# ── Title header: icon + name ────────────────────────────────────────────
		title_row = QHBoxLayout()
		logo = QLabel()
		icon_path = app_icon_path()
		if icon_path:
			pm = QPixmap(str(icon_path))
			if not pm.isNull():
				logo_size = self._px(56)
				logo.setPixmap(pm.scaled(logo_size, logo_size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
				logo.setFixedSize(logo_size, logo_size)
				logo.setStyleSheet("background: transparent;")
		else:
			logo.setFixedSize(self._px(56), self._px(56))
		logo.setAlignment(Qt.AlignCenter)
		title_label = QLabel("CSVMusic")
		title_font = QFont(retro_font_family, default_pt + 10, QFont.Bold)
		title_label.setFont(title_font)
		title_label.setStyleSheet("color: #000000;")
		title_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
		title_row.addWidget(logo)
		title_row.addSpacing(self._px(12))
		title_row.addWidget(title_label)
		title_row.addStretch(1)
		vl.addLayout(title_row)

		# ── Top help row: link + collapsible instructions ─────────────────────────
		top = QHBoxLayout()
		lbl_link = QLabel('<a href="https://www.tunemymusic.com/home">TuneMyMusic (export CSV)</a>')
		link_font = QFont(retro_font_family, default_pt + 3, QFont.Bold)
		lbl_link.setFont(link_font)
		lbl_link.setOpenExternalLinks(True)
		lbl_link.setTextInteractionFlags(Qt.TextBrowserInteraction)
		lbl_link.setStyleSheet("a { color: #000080; text-decoration: none; }")
		top.addWidget(lbl_link)
		btn_help = QToolButton()
		btn_help.setText("How to export CSV ▸")
		btn_help.setCheckable(True)
		btn_help.setToolButtonStyle(Qt.ToolButtonTextOnly)
		btn_font = QFont(retro_font_family, default_pt + 2, QFont.Bold)
		btn_help.setFont(btn_font)
		self._button_font = btn_font
		top.addStretch(1)
		top.addWidget(btn_help)
		btn_adv = QToolButton()
		btn_adv.setText("Advanced Settings ▸")
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
			"Save the exported CSV (e.g., 'My Spotify Library.csv'), then select it below."
		)
		help_text.setFont(QFont(retro_font_family, default_pt + 3))
		help_text.setWordWrap(True)
		help_text.setMinimumHeight(self._px(160))
		help_layout.addWidget(help_text)
		self.help_panel.setVisible(False)
		vl.addWidget(self.help_panel)
		def _toggle_help(checked: bool):
			self.help_panel.setVisible(checked)
			btn_help.setText("How to export CSV ▾" if checked else "How to export CSV ▸")
		btn_help.toggled.connect(_toggle_help)

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
		# Cookies-from-browser (optional)
		row_cookies = QHBoxLayout()
		lbl_cookies = QLabel("Use browser cookies:")
		lbl_cookies.setFont(QFont(retro_font_family, default_pt + 1, QFont.Bold))
		self.combo_cookies = QComboBox()
		self.combo_cookies.setEditable(False)
		self.combo_cookies.addItem("Disabled", "")
		for b in list_available_browsers():
			self.combo_cookies.addItem(b.capitalize(), b)
		self.combo_cookies.currentIndexChanged.connect(self.on_cookies_browser_changed)
		row_cookies.addWidget(lbl_cookies)
		row_cookies.addWidget(self.combo_cookies, 1)
		adv_layout.addLayout(row_cookies)
		# Browser profile (appears after a browser is selected)
		self.profile_panel = QFrame()
		self.profile_panel.setFrameShape(QFrame.NoFrame)
		self.profile_panel.setVisible(False)
		row_prof = QHBoxLayout(self.profile_panel)
		row_prof.setContentsMargins(0, 0, 0, 0)
		lbl_profile = QLabel("Profile:")
		lbl_profile.setFont(QFont(retro_font_family, default_pt + 1, QFont.Bold))
		self.combo_profile = QComboBox()
		self.combo_profile.setEditable(False)
		self.combo_profile.currentIndexChanged.connect(self.on_profile_changed)
		row_prof.addWidget(lbl_profile)
		row_prof.addWidget(self.combo_profile, 1)
		adv_layout.addWidget(self.profile_panel)
		# Tip: Firefox avoids DPAPI on Windows
		lbl_ff_tip = QLabel("Tip: For reliable cookies on Windows, use Firefox or export a cookies.txt. <a href=\"https://www.mozilla.org/firefox/download/\">Get Firefox</a>")
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
			btn_adv.setText("Advanced Settings ▾" if checked else "Advanced Settings ▸")
		btn_adv.toggled.connect(_toggle_advanced)

		# ── CSV picker ─────────────────────────────────────────────────────────────
		row1 = QHBoxLayout()
		self.ed_csv = QLineEdit(); self.ed_csv.setPlaceholderText("Path to 'My Spotify Library.csv'")
		self.ed_csv.setFont(QFont(retro_font_family, default_pt + 1))
		btn_csv = QPushButton("Browse…"); btn_csv.clicked.connect(self.on_browse_csv)
		btn_csv.setFont(btn_font)
		lbl_csv = QLabel("CSV:"); lbl_csv.setFont(QFont(retro_font_family, default_pt + 2, QFont.Bold))
		row1.addWidget(lbl_csv); row1.addWidget(self.ed_csv, 1); row1.addWidget(btn_csv)
		vl.addLayout(row1)

		# ── Output folder ─────────────────────────────────────────────────────────
		row2 = QHBoxLayout()
		self.ed_out = QLineEdit(); self.ed_out.setPlaceholderText("Output folder")
		self.ed_out.setFont(QFont(retro_font_family, default_pt + 1))
		btn_out = QPushButton("Choose…"); btn_out.clicked.connect(self.on_browse_out)
		btn_out.setFont(btn_font)
		btn_open_out = QPushButton("Open"); btn_open_out.clicked.connect(self.on_open_output)
		btn_open_out.setFont(btn_font)
		lbl_out = QLabel("Output:"); lbl_out.setFont(QFont(retro_font_family, default_pt + 2, QFont.Bold))
		row2.addWidget(lbl_out); row2.addWidget(self.ed_out, 1); row2.addWidget(btn_out); row2.addWidget(btn_open_out)
		vl.addLayout(row2)

		# ── Format + options (single line) ────────────────────────────────────────
		row3 = QHBoxLayout()
		self.rb_m4a = QRadioButton("m4a (AAC, preferred)"); self.rb_m4a.setChecked(True)
		self.rb_mp3 = QRadioButton("mp3")
		self.grp_fmt = QButtonGroup(self); self.grp_fmt.addButton(self.rb_m4a); self.grp_fmt.addButton(self.rb_mp3)
		self.cb_m3u8 = QCheckBox("Write .m3u8"); self.cb_m3u8.setChecked(True)
		self.cb_m3u_plain = QCheckBox("Write .m3u")
		self.cb_album_art = QCheckBox("Embed album art"); self.cb_album_art.setChecked(True)
		controls_font = QFont(retro_font_family, default_pt + 2)
		for w in (self.rb_m4a, self.rb_mp3, self.cb_m3u8, self.cb_m3u_plain, self.cb_album_art):
			w.setFont(controls_font)
		lbl_fmt = QLabel("Format & Options:"); lbl_fmt.setFont(QFont(retro_font_family, default_pt + 2, QFont.Bold))
		row3.addWidget(lbl_fmt)
		row3.addSpacing(self._px(8))
		row3.addWidget(self.rb_m4a)
		row3.addWidget(self.rb_mp3)
		row3.addSpacing(self._px(16))
		row3.addWidget(self.cb_m3u8)
		row3.addWidget(self.cb_m3u_plain)
		row3.addWidget(self.cb_album_art)
		row3.addStretch(1)
		vl.addLayout(row3)

		# ── Controls ──────────────────────────────────────────────────────────────
		row4 = QHBoxLayout()
		self.btn_start = QPushButton("Start"); self.btn_start.clicked.connect(self.on_start)
		self.btn_stop = QPushButton("Stop"); self.btn_stop.setEnabled(False); self.btn_stop.clicked.connect(self.on_stop)
		self.btn_clear = QPushButton("Clear"); self.btn_clear.setEnabled(False); self.btn_clear.clicked.connect(self.on_clear)
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

	def on_browse_out(self):
		p = QFileDialog.getExistingDirectory(self, "Select Output Folder", "")
		if p:
			self.ed_out.setText(p)
			self.btn_clear.setEnabled(True)
			self._allow_path_persist = True
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

	def _collect_tracks_preview(self) -> List[dict]:
		df = load_csv(self.ed_csv.text().strip())
		return tracks_from_csv(df, None)  # use entire CSV

	def _yt_dlp_override(self) -> str | None:
		val = self.ed_ytdlp.text().strip()
		return val or None

	def _ffmpeg_override(self) -> str | None:
		val = self.ed_ffmpeg.text().strip()
		return val or None

	def _cookies_browser(self) -> str | None:
		b = self.combo_cookies.currentData()
		if not isinstance(b, str) or not b.strip():
			return None
		browser = b.strip()
		# Combine with selected profile if present
		if self.profile_panel.isVisible() and self.combo_profile.count() > 0:
			p = self.combo_profile.currentData()
			if isinstance(p, str) and p.strip():
				return f"{browser}:{p.strip()}"
		return browser

	def _cookies_file(self) -> str | None:
		val = self.ed_cookies_file.text().strip()
		return val or None

	def _refresh_profiles(self, *, stored_profile: str | None = None) -> None:
		# Populate profile list for the selected browser
		b = self.combo_cookies.currentData()
		self.combo_profile.clear()
		if not isinstance(b, str) or not b:
			self.profile_panel.setVisible(False)
			return
		profiles = list_profiles(b)
		chromium_like = b in ("edge","chrome","brave","opera","vivaldi")
		if not profiles:
			if chromium_like:
				# Chromium often has a Default profile
				self.combo_profile.addItem("Default", "Default")
				self.profile_panel.setVisible(True)
			else:
				# Firefox: if no profiles resolved, hide and let yt-dlp choose default
				self.profile_panel.setVisible(False)
				return
		else:
			for p in profiles:
				self.combo_profile.addItem(p, p)
			self.profile_panel.setVisible(True)
		# Restore selection if available
		if stored_profile:
			for i in range(self.combo_profile.count()):
				if self.combo_profile.itemData(i) == stored_profile:
					self.combo_profile.setCurrentIndex(i)
					break
		# Kick off cookie check when profiles are ready
		self._start_cookie_check()

	def on_cookies_browser_changed(self) -> None:
		# Toggle and populate profiles based on browser choice
		self._refresh_profiles()
		self._persist_settings()

	def on_profile_changed(self) -> None:
		self._persist_settings()
		self._start_cookie_check()

	def on_browse_cookies_file(self):
		p, _ = QFileDialog.getOpenFileName(self, "Select cookies.txt", "", "Text files (*.txt);;All files (*)")
		if p:
			self.ed_cookies_file.setText(p)
			self._persist_settings()

	def on_clear_cookies_file(self):
		self.ed_cookies_file.clear()
		self._persist_settings()

	def on_cookies_file_changed(self, _text: str) -> None:
		# If a cookies file is provided, it takes precedence; still allow browser/profile selection
		self._persist_settings()
		self._start_cookie_check()

	def _set_cookie_status(self, text: str, *, ok: bool | None) -> None:
		self.lbl_cookie_status.setVisible(True)
		self.lbl_cookie_status.setText(text)
		if ok is True:
			self.lbl_cookie_status.setStyleSheet("color: #006400")
		elif ok is False:
			self.lbl_cookie_status.setStyleSheet("color: #8B0000")
		else:
			self.lbl_cookie_status.setStyleSheet("color: #000000")

	def _start_cookie_check(self) -> None:
		# Only check when a browser is selected
		cookies = self._cookies_browser()
		import sys as _sys
		if _sys.platform.startswith("win") and cookies and not self._cookies_file():
			b = cookies.split(":", 1)[0].strip().lower()
			if b in ("chrome", "edge", "brave", "vivaldi", "opera"):
				self._set_cookie_status("On Windows, Chromium cookies require cookies.txt export.", ok=False)
				return
		if not cookies and not self._cookies_file():
			self.lbl_cookie_status.setVisible(False)
			return
		self._set_cookie_status("Checking cookies…", ok=None)
		# Cancel prior worker if any
		if hasattr(self, "cookie_check_worker") and self.cookie_check_worker:
			try:
				self.cookie_check_worker.quit()
				self.cookie_check_worker.wait(200)
			except Exception:
				pass
		self.cookie_check_worker = CookiesCheckWorker(self._cookies_browser(), self._cookies_file(), self._yt_dlp_override(), self)
		self.cookie_check_worker.sig_done.connect(lambda ok, msg: self._set_cookie_status(msg, ok=ok))
		self.cookie_check_worker.start()

	def _persist_settings(self, *, include_paths: bool = False) -> None:
		def _norm(text: str) -> str | None:
			value = text.strip()
			return value or None
		cfg = {
			"yt_dlp_path": _norm(self.ed_ytdlp.text()),
			"ffmpeg_path": _norm(self.ed_ffmpeg.text()),
			"cookies_browser": self._cookies_browser(),
			"cookies_file": _norm(self.ed_cookies_file.text()),
		}
		if include_paths:
			cfg["csv_path"] = _norm(self.ed_csv.text())
			cfg["output_dir"] = _norm(self.ed_out.text())
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
		yt_path = cfg.get("yt_dlp_path") or ""
		blocker_yt = QSignalBlocker(self.ed_ytdlp)
		self.ed_ytdlp.setText(yt_path)
		del blocker_yt
		ff_path = cfg.get("ffmpeg_path") or ""
		blocker_ff = QSignalBlocker(self.ed_ffmpeg)
		self.ed_ffmpeg.setText(ff_path)
		del blocker_ff
		stored_browser = str(cfg.get("cookies_browser") or "")
		if stored_browser:
			# Support optional profile: "browser[:profile]"
			parts = stored_browser.split(":", 1)
			sb = parts[0].strip()
			sp = parts[1].strip() if len(parts) == 2 else None
			# Set browser selection
			for i in range(self.combo_cookies.count()):
				if self.combo_cookies.itemData(i) == sb:
					block_b = QSignalBlocker(self.combo_cookies)
					self.combo_cookies.setCurrentIndex(i)
					del block_b
					# Populate profiles and set stored
					self._refresh_profiles(stored_profile=sp)
					break
		else:
			# Default to Firefox if available; otherwise Disabled
			set_default = True
			for i in range(self.combo_cookies.count()):
				if self.combo_cookies.itemData(i) == "firefox":
					block_b = QSignalBlocker(self.combo_cookies)
					self.combo_cookies.setCurrentIndex(i)
					del block_b
					self._refresh_profiles()
					set_default = False
					break
			if set_default:
				self.combo_cookies.setCurrentIndex(0)
		# Load cookies file path
		cookie_file = cfg.get("cookies_file") or ""
		block_cf = QSignalBlocker(self.ed_cookies_file)
		self.ed_cookies_file.setText(cookie_file)
		del block_cf
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

		# Build table from all tracks in CSV
		try:
			self.tracks = self._collect_tracks_preview()
		except Exception as e:
			QMessageBox.critical(self, "CSV Error", f"Failed to parse CSV:\n{e}")
			return
		if not self.tracks:
			QMessageBox.information(self, "No Tracks", "No tracks found in the CSV.")
			return

		self.track_results = {}
		self.action_buttons = {}
		self._clear_resolution_panel()
		self.table.setRowCount(len(self.tracks))
		for i, t in enumerate(self.tracks):
			self.table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
			self.table.setItem(i, 1, QTableWidgetItem(f"{t['artists']} — {t['title']}"))
			self.table.setItem(i, 2, QTableWidgetItem("Queued"))
			btn_alt = QPushButton("Alternatives")
			btn_alt.setEnabled(False)
			btn_alt.clicked.connect(partial(self.on_open_alternatives, i))
			self.table.setCellWidget(i, 3, btn_alt)
			self.action_buttons[i] = btn_alt

		# Progress
		self.progress.setValue(0)
		self.progress.setMaximum(len(self.tracks))
		self.total = len(self.tracks)

		fmt = "m4a" if self.rb_m4a.isChecked() else "mp3"
		want_m3u8 = self.cb_m3u8.isChecked()
		want_m3u_plain = self.cb_m3u_plain.isChecked()
		embed_art = self.cb_album_art.isChecked()
		cookies_browser = self._cookies_browser()

		self.btn_start.setEnabled(False)
		self.btn_stop.setEnabled(True)
		self.btn_clear.setEnabled(False)
		self.lbl_log.setText("Starting…")

		# playlist=None → worker picks a default name internally
		self.worker = PipelineWorker(csv_path, out_dir, None, fmt, want_m3u8, want_m3u_plain, embed_art, yt_override, ff_override, cookies_browser, self._cookies_file(), self)
		self.worker.sig_log.connect(self.lbl_log.setText)
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

	def on_track_result(self, row_idx: int, payload: dict) -> None:
		self.track_results[row_idx] = payload
		btn = self.action_buttons.get(row_idx)
		if btn:
			btn.setEnabled(True)
		track = payload.get("track")
		if track and 0 <= row_idx < len(self.tracks):
			self.tracks[row_idx] = track
		playlist_name = payload.get("playlist_name")
		if playlist_name:
			self.last_playlist_name = playlist_name

	def on_open_alternatives(self, row_idx: int) -> None:
		info = self.track_results.get(row_idx)
		if not info:
			QMessageBox.information(self, "Results pending", "This track is still processing. Try again shortly.")
			return
		track = info.get("track")
		if not track:
			QMessageBox.warning(self, "Unavailable", "Track metadata is missing for this row.")
			return
		options = info.get("options") or []
		self.on_resolution_options(row_idx, track, options)

	def on_clear(self):
		if self.worker:
			return
		for info in self.resolve_items.values():
			worker = info.get("worker")
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
				item.setBackground(RED)
				self.table.item(row_idx, 1).setBackground(RED)
			elif status.startswith("Skipped"):
				item.setBackground(YELLOW)
				self.table.item(row_idx, 1).setBackground(YELLOW)
			elif status.startswith("Done"):
				item.setBackground(GREEN)
				self.table.item(row_idx, 1).setBackground(GREEN)
			self.table.setItem(row_idx, 2, item)

	def on_progress(self, processed: int, total: int):
		self.progress.setMaximum(total)
		self.progress.setValue(processed)

	def on_done(self, msg: str, matched: list, skipped: list, failed: list):
		from PySide6.QtWidgets import QApplication
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
		processed = len(matched) + len(skipped) + len(failed)
		pending = max(requested - processed, 0)
		lines = [
			f"Tracks requested: {requested}",
			f"Downloaded: {len(matched)}",
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
			record["options"] = self._merge_options(record.get("options", []), options)
			self._refresh_option_combo(record)
		else:
			record = self._create_resolution_item(row_idx, track, options or [])
			self.resolve_items[row_idx] = record
			self.resolve_items_layout.addWidget(record["widget"])
		self.track_results.setdefault(row_idx, {"track": track})["options"] = record.get("options", [])
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
		options = record.get("options", [])
		if not options:
			combo.addItem("No matches yet", None)
			record["btn_download"].setEnabled(False)
		else:
			record["btn_download"].setEnabled(True)
			for opt in options:
				combo.addItem(self._format_option(opt), opt)
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
			"options": options,
			"combo": combo,
			"btn_download": btn_download,
			"btn_skip": btn_skip,
			"btn_close": btn_close,
			"row_idx": row_idx,
			"worker": None
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
		return f"{score:.2f} • {title} ({author}) [{mins}:{secs:02d}]"

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
			self
		)
		record["worker"] = worker
		worker.sig_status.connect(self.on_row_status)
		worker.sig_finished.connect(self.on_resolution_finished)
		worker.start()
		self.lbl_log.setText(f"Manual download queued: {record['track'].get('artists','')} — {record['track'].get('title','')}")

	def on_resolution_skip(self, row_idx: int) -> None:
		record = self.resolve_items.pop(row_idx, None)
		if not record:
			return
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
		record["widget"].setParent(None)
		record["widget"].deleteLater()
		if not self.resolve_items:
			self.resolve_box.setVisible(False)

	def on_resolution_finished(self, row_idx: int, payload: dict) -> None:
		record = self.resolve_items.get(row_idx)
		if record:
			record["worker"] = None
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
			self._write_playlist_file(out_root, playlist_name, entries_resolved, ext, ".m3u", "cp1252")
		else:
			self._remove_playlist_file(out_root, playlist_name, ".m3u")

	def _write_playlist_file(self, out_root: pathlib.Path, playlist_name: str, entries: list[tuple[dict, pathlib.Path]], ext: str, suffix: str, encoding: str) -> None:
		file_path = out_root / f"{sanitize_name(playlist_name)}{suffix}"
		try:
			lines = ["#EXTM3U", f"#EXTPLAYLIST:{playlist_name}"]
			root_resolved = out_root.resolve()
			for track, abs_path in entries:
				duration = int(round((track.get("duration_ms") or 0) / 1000))
				artists = track.get("artists", "")
				title = track.get("title", "")
				lines.append(f"#EXTINF:{duration},{artists} - {title}")
				abs_path = abs_path.resolve()
				try:
					path_obj = root_resolved / abs_path.relative_to(root_resolved)
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
		file_path = out_root / f"{sanitize_name(playlist_name)}{suffix}"
		if file_path.exists():
			try:
				file_path.unlink()
			except Exception:
				pass

	def closeEvent(self, event):
		"""Ensure all threads are stopped before closing"""
		# Stop main worker if running
		if self.worker and self.worker.isRunning():
			self.worker.stop()
			self.worker.quit()
			self.worker.wait(3000)  # wait up to 3 seconds

		# Stop resolution workers if running
		for record in list(self.resolve_items.values()):
			worker = record.get("worker")
			if worker and worker.isRunning():
				worker.quit()
				worker.wait(1000)

		event.accept()
