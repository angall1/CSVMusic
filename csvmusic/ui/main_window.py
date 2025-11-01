# tabs only
import pathlib
from functools import partial
from typing import List, Tuple
from PySide6.QtWidgets import (
	QMainWindow, QWidget, QFileDialog, QMessageBox, QApplication,
	QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
	QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox,
	QRadioButton, QButtonGroup, QProgressBar, QToolButton, QSizePolicy, QFrame, QComboBox,
	QDialog, QListWidget, QListWidgetItem, QTextEdit
)
from PySide6.QtCore import Qt, QSignalBlocker, QSize
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap, QFontDatabase, QGuiApplication, QBrush

from csvmusic.core.csv_import import load_csv, tracks_from_csv
from csvmusic.core.settings import load_settings, save_settings
from csvmusic.core.downloader import sanitize_name
from csvmusic.core.preflight import run_preflight_checks
from csvmusic.core.paths import app_icon_path, resource_base
from csvmusic.ui.workers import PipelineWorker, SingleDownloadWorker
from csvmusic.core.browsers import list_profiles, list_available_browsers

# Status colors (Material Design theme)
YELLOW = QColor(255, 152, 0)     # Material warning orange (#ff9800)
RED = QColor(244, 67, 54)         # Material error red (#f44336)
GREEN = QColor(76, 175, 80)       # Material success green (#4caf50)


class HelpDialog(QDialog):
	"""Modal dialog showing export instructions"""
	def __init__(self, parent=None):
		super().__init__(parent)
		self.setWindowTitle("How to Export CSV")
		self.setMinimumSize(600, 400)
		self.resize(700, 500)

		layout = QVBoxLayout(self)
		layout.setSpacing(20)
		layout.setContentsMargins(24, 24, 24, 24)

		# Title
		title = QLabel("<h2>How to Export CSV from TuneMyMusic</h2>")
		layout.addWidget(title)

		# Instructions
		help_text = QLabel(
			"<ol style='line-height: 1.8;'>"
			"<li>Visit <a href='https://www.tunemymusic.com/home'>TuneMyMusic.com</a></li>"
			"<li>Select your music platform (Spotify, Apple Music, YouTube Music, etc.)</li>"
			"<li>Paste your playlist URL or connect your account</li>"
			"<li>Choose <b>File</b> as the destination</li>"
			"<li>Click <b>Export to file → CSV</b></li>"
			"<li>Save the CSV file to your computer</li>"
			"</ol>"
			"<p style='margin-top: 20px;'>Once you have the CSV file (e.g., 'My Spotify Library.csv'),<br>"
			"return to CSVMusic and select it using the <b>CSV Browse</b> button.</p>"
		)
		help_text.setWordWrap(True)
		help_text.setOpenExternalLinks(True)
		help_text.setTextFormat(Qt.RichText)
		layout.addWidget(help_text)

		layout.addStretch()

		# Close button
		button_layout = QHBoxLayout()
		button_layout.addStretch()
		close_btn = QPushButton("Close")
		close_btn.setObjectName("primary")
		close_btn.setMinimumWidth(120)
		close_btn.clicked.connect(self.accept)
		button_layout.addWidget(close_btn)
		layout.addLayout(button_layout)


class AdvancedSettingsDialog(QDialog):
	"""Modal dialog for advanced settings"""
	def __init__(self, parent=None):
		super().__init__(parent)
		self.setWindowTitle("Advanced Settings")
		self.setMinimumSize(700, 500)
		self.resize(800, 550)

		layout = QVBoxLayout(self)
		layout.setSpacing(20)
		layout.setContentsMargins(24, 24, 24, 24)

		# Title
		title = QLabel("<h2>Advanced Settings</h2>")
		layout.addWidget(title)

		note = QLabel("These overrides are optional. Leave blank to use bundled tools.")
		note.setWordWrap(True)
		note.setStyleSheet("color: #b3b3b3;")
		layout.addWidget(note)

		# Settings form
		form_layout = QVBoxLayout()
		form_layout.setSpacing(16)

		# yt-dlp path
		ytdlp_group = QVBoxLayout()
		lbl_ytdlp = QLabel("<b>yt-dlp path:</b>")
		self.ed_ytdlp = QLineEdit()
		self.ed_ytdlp.setPlaceholderText("Auto-detect from PATH")
		ytdlp_buttons = QHBoxLayout()
		btn_ytdlp = QPushButton("Browse…")
		btn_ytdlp.clicked.connect(self._browse_ytdlp)
		btn_ytdlp_clear = QPushButton("Clear")
		btn_ytdlp_clear.clicked.connect(lambda: self.ed_ytdlp.clear())
		ytdlp_buttons.addWidget(self.ed_ytdlp, 1)
		ytdlp_buttons.addWidget(btn_ytdlp)
		ytdlp_buttons.addWidget(btn_ytdlp_clear)
		ytdlp_group.addWidget(lbl_ytdlp)
		ytdlp_group.addLayout(ytdlp_buttons)
		form_layout.addLayout(ytdlp_group)

		# FFmpeg path
		ffmpeg_group = QVBoxLayout()
		lbl_ffmpeg = QLabel("<b>FFmpeg path:</b>")
		self.ed_ffmpeg = QLineEdit()
		self.ed_ffmpeg.setPlaceholderText("Uses bundled binary by default")
		ffmpeg_buttons = QHBoxLayout()
		btn_ffmpeg = QPushButton("Browse…")
		btn_ffmpeg.clicked.connect(self._browse_ffmpeg)
		btn_ffmpeg_clear = QPushButton("Clear")
		btn_ffmpeg_clear.clicked.connect(lambda: self.ed_ffmpeg.clear())
		ffmpeg_buttons.addWidget(self.ed_ffmpeg, 1)
		ffmpeg_buttons.addWidget(btn_ffmpeg)
		ffmpeg_buttons.addWidget(btn_ffmpeg_clear)
		ffmpeg_group.addWidget(lbl_ffmpeg)
		ffmpeg_group.addLayout(ffmpeg_buttons)
		form_layout.addLayout(ffmpeg_group)

		# Browser cookies
		cookies_group = QVBoxLayout()
		lbl_cookies = QLabel("<b>Use browser cookies:</b>")
		self.combo_cookies = QComboBox()
		self.combo_cookies.setEditable(False)
		cookies_group.addWidget(lbl_cookies)
		cookies_group.addWidget(self.combo_cookies)
		form_layout.addLayout(cookies_group)

		# Profile selection
		self.profile_panel = QWidget()
		profile_layout = QVBoxLayout(self.profile_panel)
		profile_layout.setContentsMargins(0, 0, 0, 0)
		lbl_profile = QLabel("<b>Profile:</b>")
		self.combo_profile = QComboBox()
		self.combo_profile.setEditable(False)
		profile_layout.addWidget(lbl_profile)
		profile_layout.addWidget(self.combo_profile)
		self.profile_panel.setVisible(False)
		form_layout.addWidget(self.profile_panel)

		# Firefox tip
		lbl_ff_tip = QLabel("Tip: For reliable cookies on Windows, use Firefox or export a cookies.txt. <a href='https://www.mozilla.org/firefox/download/'>Get Firefox</a>")
		lbl_ff_tip.setOpenExternalLinks(True)
		lbl_ff_tip.setWordWrap(True)
		lbl_ff_tip.setStyleSheet("color: #888;")
		form_layout.addWidget(lbl_ff_tip)

		# Cookies file
		cookie_file_group = QVBoxLayout()
		lbl_cookie_file = QLabel("<b>Cookies file (.txt):</b>")
		self.ed_cookies_file = QLineEdit()
		self.ed_cookies_file.setPlaceholderText("Optional: Netscape cookies.txt (YouTube domain)")
		cookie_file_buttons = QHBoxLayout()
		btn_cookie_file = QPushButton("Browse...")
		btn_cookie_file.clicked.connect(self._browse_cookies_file)
		btn_cookie_file_clear = QPushButton("Clear")
		btn_cookie_file_clear.clicked.connect(lambda: self.ed_cookies_file.clear())
		cookie_file_buttons.addWidget(self.ed_cookies_file, 1)
		cookie_file_buttons.addWidget(btn_cookie_file)
		cookie_file_buttons.addWidget(btn_cookie_file_clear)
		cookie_file_group.addWidget(lbl_cookie_file)
		cookie_file_group.addLayout(cookie_file_buttons)
		form_layout.addLayout(cookie_file_group)

		# Cookie status
		self.lbl_cookie_status = QLabel("")
		self.lbl_cookie_status.setVisible(False)
		form_layout.addWidget(self.lbl_cookie_status)

		layout.addLayout(form_layout)
		layout.addStretch()

		# Close button
		button_layout = QHBoxLayout()
		button_layout.addStretch()
		close_btn = QPushButton("Close")
		close_btn.setObjectName("primary")
		close_btn.setMinimumWidth(120)
		close_btn.clicked.connect(self.accept)
		button_layout.addWidget(close_btn)
		layout.addLayout(button_layout)

	def _browse_ytdlp(self):
		path, _ = QFileDialog.getOpenFileName(self, "Select yt-dlp executable", "", "Executables (*.exe *.bat *.cmd);;All files (*)")
		if path:
			self.ed_ytdlp.setText(path)

	def _browse_ffmpeg(self):
		path, _ = QFileDialog.getOpenFileName(self, "Select FFmpeg executable", "", "Executables (*.exe);;All files (*)")
		if path:
			self.ed_ffmpeg.setText(path)

	def _browse_cookies_file(self):
		path, _ = QFileDialog.getOpenFileName(self, "Select cookies.txt", "", "Text files (*.txt);;All files (*)")
		if path:
			self.ed_cookies_file.setText(path)


class AlternativesDialog(QDialog):
	"""Modal dialog for selecting alternative matches for a track"""
	def __init__(self, track: dict, options: list, parent=None):
		super().__init__(parent)
		self.track = track
		self.options = options
		self.selected_option = None
		self.action = None  # 'download', 'skip', or None

		self.setWindowTitle("Select Alternative Match")
		self.setMinimumSize(800, 500)
		self.resize(900, 600)

		layout = QVBoxLayout(self)
		layout.setSpacing(16)
		layout.setContentsMargins(20, 20, 20, 20)

		# Track info header
		track_info = QLabel(f"<h2>{track.get('artists', 'Unknown')} — {track.get('title', 'Unknown')}</h2>")
		track_info.setWordWrap(True)
		layout.addWidget(track_info)

		if not options:
			no_matches = QLabel("<p style='color: #ff9800;'>No alternative matches found for this track.</p>")
			layout.addWidget(no_matches)
		else:
			# Instructions
			instructions = QLabel(f"<p>Found {len(options)} alternative matches. Select one and click Download, or Skip this track.</p>")
			instructions.setWordWrap(True)
			layout.addWidget(instructions)

			# List of alternatives (scrollable)
			self.list_widget = QListWidget()
			self.list_widget.setAlternatingRowColors(True)
			self.list_widget.setWordWrap(True)

			for idx, option in enumerate(options):
				score = option.get("score", 0.0)
				title = option.get("title", "Unknown")
				author = option.get("author", "Unknown")
				duration = option.get("duration_seconds", 0)
				video_id = option.get("videoId", "")

				mins = duration // 60
				secs = duration % 60

				# Create rich text item
				item_text = f"""
					<b>Match Score: {score:.2%}</b><br>
					<span style='font-size: 13pt;'>{title}</span><br>
					<span style='color: #b3b3b3;'>by {author} • Duration: {mins}:{secs:02d}</span><br>
					<span style='color: #888; font-size: 9pt;'>Video ID: {video_id}</span>
				"""

				item = QListWidgetItem()
				item.setData(Qt.UserRole, option)  # Store the full option dict
				item.setSizeHint(QSize(0, 90))  # Fixed height for each item
				self.list_widget.addItem(item)

				# Create a widget for the item with proper text wrapping
				item_widget = QLabel(item_text)
				item_widget.setWordWrap(True)
				item_widget.setTextFormat(Qt.RichText)
				item_widget.setMargin(8)
				self.list_widget.setItemWidget(item, item_widget)

			# Select first item by default
			if self.list_widget.count() > 0:
				self.list_widget.setCurrentRow(0)

			layout.addWidget(self.list_widget, 1)  # Stretch factor 1

		# Buttons
		button_layout = QHBoxLayout()
		button_layout.addStretch()

		if options:
			self.download_btn = QPushButton("Download Selected")
			self.download_btn.setObjectName("primary")
			self.download_btn.setMinimumWidth(150)
			self.download_btn.clicked.connect(self._on_download)
			button_layout.addWidget(self.download_btn)

		self.skip_btn = QPushButton("Skip Track")
		self.skip_btn.setMinimumWidth(120)
		self.skip_btn.clicked.connect(self._on_skip)
		button_layout.addWidget(self.skip_btn)

		self.cancel_btn = QPushButton("Cancel")
		self.cancel_btn.setMinimumWidth(100)
		self.cancel_btn.clicked.connect(self.reject)
		button_layout.addWidget(self.cancel_btn)

		layout.addLayout(button_layout)

	def _on_download(self):
		"""User clicked Download"""
		current_item = self.list_widget.currentItem()
		if current_item:
			self.selected_option = current_item.data(Qt.UserRole)
			self.action = 'download'
			self.accept()
		else:
			QMessageBox.warning(self, "No Selection", "Please select an alternative from the list.")

	def _on_skip(self):
		"""User clicked Skip"""
		self.action = 'skip'
		self.accept()

	def get_result(self):
		"""Returns (action, selected_option) tuple"""
		return self.action, self.selected_option

class StatusWidget(QWidget):
	"""Custom status widget with colored indicator badge"""
	def __init__(self, status_text: str = "", color: str = "#b3b3b3", parent=None):
		super().__init__(parent)
		layout = QHBoxLayout(self)
		layout.setContentsMargins(12, 0, 12, 0)
		layout.setSpacing(10)

		# Colored indicator badge (circle)
		self.indicator = QLabel()
		self.indicator.setFixedSize(14, 14)
		self.indicator.setStyleSheet(f"""
			QLabel {{
				background-color: {color};
				border-radius: 7px;
			}}
		""")
		layout.addWidget(self.indicator)

		# Status text
		self.label = QLabel(status_text)
		self.label.setStyleSheet("color: #e0e0e0; font-size: 13px;")
		layout.addWidget(self.label, 1)

		layout.addStretch()

	def set_status(self, status_text: str, color: str):
		"""Update status text and indicator color"""
		self.label.setText(status_text)
		self.indicator.setStyleSheet(f"""
			QLabel {{
				background-color: {color};
				border-radius: 7px;
			}}
		""")

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
		self.last_playlist_name: str | None = None
		self._allow_path_persist = False
		icon_p = app_icon_path()
		if icon_p:
			self.setWindowIcon(QIcon(str(icon_p)))

		root = QWidget(self); self.setCentralWidget(root)
		vl = QVBoxLayout(root)
		vl.setSpacing(self._px(12))

		# Setup modern fonts (system default, no custom font needed)
		default_pt = max(self.font().pointSize(), 10)
		retro_font_family = self.font().family()  # Use system default
		btn_font = QFont(retro_font_family, default_pt, QFont.Weight.Medium)
		self._button_font = btn_font

		# ── Top toolbar row ─────────────────────────
		top = QHBoxLayout()

		# TuneMyMusic button - opens link directly
		btn_tunemymusic = QPushButton("TuneMyMusic  ")
		btn_tunemymusic.setFont(btn_font)
		btn_tunemymusic.setIcon(self._get_icon("launch"))
		btn_tunemymusic.setIconSize(QSize(self._px(20), self._px(20)))
		btn_tunemymusic.setLayoutDirection(Qt.RightToLeft)  # Icon on right
		btn_tunemymusic.clicked.connect(lambda: self._open_url("https://www.tunemymusic.com/home"))
		top.addWidget(btn_tunemymusic)

		top.addStretch(1)

		# Help button with Material Design question mark icon (icon on right)
		btn_help = QPushButton("How to Export CSV  ")
		btn_help.setFont(btn_font)
		btn_help.setIcon(self._get_icon("help"))
		btn_help.setIconSize(QSize(self._px(20), self._px(20)))
		btn_help.setLayoutDirection(Qt.RightToLeft)
		btn_help.clicked.connect(self._open_help_dialog)
		top.addWidget(btn_help)

		# Settings button with Material Design settings icon (icon on right)
		btn_adv = QPushButton("Advanced Settings  ")
		btn_adv.setFont(btn_font)
		btn_adv.setIcon(self._get_icon("settings"))
		btn_adv.setIconSize(QSize(self._px(20), self._px(20)))
		btn_adv.setLayoutDirection(Qt.RightToLeft)
		btn_adv.clicked.connect(self._open_advanced_settings)
		top.addWidget(btn_adv)

		vl.addLayout(top)

		# Settings state (loaded/saved via dialogs)
		self._settings_ytdlp = ""
		self._settings_ffmpeg = ""
		self._settings_cookies_browser = ""
		self._settings_cookies_file = ""

		# ── CSV picker ─────────────────────────────────────────────────────────────
		row1 = QHBoxLayout()
		self.ed_csv = QLineEdit(); self.ed_csv.setPlaceholderText("Path to 'My Spotify Library.csv'")
		self.ed_csv.setFont(QFont(retro_font_family, default_pt + 1))
		btn_csv = QPushButton("Browse…  ")
		btn_csv.setIcon(self._get_icon("file"))
		btn_csv.setIconSize(QSize(self._px(16), self._px(16)))
		btn_csv.setLayoutDirection(Qt.RightToLeft)
		btn_csv.clicked.connect(self.on_browse_csv)
		btn_csv.setFont(btn_font)
		lbl_csv = QLabel("CSV:"); lbl_csv.setFont(QFont(retro_font_family, default_pt + 2, QFont.Bold))
		row1.addWidget(lbl_csv); row1.addWidget(self.ed_csv, 1); row1.addWidget(btn_csv)
		vl.addLayout(row1)

		# ── Output folder ─────────────────────────────────────────────────────────
		row2 = QHBoxLayout()
		self.ed_out = QLineEdit(); self.ed_out.setPlaceholderText("Output folder")
		self.ed_out.setFont(QFont(retro_font_family, default_pt + 1))
		btn_out = QPushButton("Choose…  ")
		btn_out.setIcon(self._get_icon("folder"))
		btn_out.setIconSize(QSize(self._px(16), self._px(16)))
		btn_out.setLayoutDirection(Qt.RightToLeft)
		btn_out.clicked.connect(self.on_browse_out)
		btn_out.setFont(btn_font)
		btn_open_out = QPushButton("Open  ")
		btn_open_out.setIcon(self._get_icon("folder"))
		btn_open_out.setIconSize(QSize(self._px(16), self._px(16)))
		btn_open_out.setLayoutDirection(Qt.RightToLeft)
		btn_open_out.clicked.connect(self.on_open_output)
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

		# ── Controls with progress indicator ──────────────────────────────────────
		row4 = QHBoxLayout()

		# Start button with Play icon (icon on right)
		self.btn_start = QPushButton("Start  ")
		self.btn_start.setIcon(self._get_icon("play"))
		self.btn_start.setIconSize(QSize(self._px(18), self._px(18)))
		self.btn_start.setLayoutDirection(Qt.RightToLeft)
		self.btn_start.clicked.connect(self.on_start)
		self.btn_start.setObjectName("primary")  # Use accent color for primary action
		self.btn_start.setFont(QFont(retro_font_family, default_pt + 1, QFont.Weight.Medium))

		# Stop button with Stop icon (destructive/red, icon on right)
		self.btn_stop = QPushButton("Stop  ")
		self.btn_stop.setIcon(self._get_icon("stop"))
		self.btn_stop.setIconSize(QSize(self._px(18), self._px(18)))
		self.btn_stop.setLayoutDirection(Qt.RightToLeft)
		self.btn_stop.setEnabled(False)
		self.btn_stop.clicked.connect(self.on_stop)
		self.btn_stop.setObjectName("destructive")
		self.btn_stop.setFont(QFont(retro_font_family, default_pt + 1, QFont.Weight.Medium))

		# Clear button with Clear/Delete icon (destructive/red, icon on right)
		self.btn_clear = QPushButton("Clear  ")
		self.btn_clear.setIcon(self._get_icon("clear"))
		self.btn_clear.setIconSize(QSize(self._px(18), self._px(18)))
		self.btn_clear.setLayoutDirection(Qt.RightToLeft)
		self.btn_clear.setEnabled(False)
		self.btn_clear.clicked.connect(self.on_clear)
		self.btn_clear.setObjectName("destructive")
		self.btn_clear.setFont(QFont(retro_font_family, default_pt + 1, QFont.Weight.Medium))

		row4.addWidget(self.btn_start)
		row4.addWidget(self.btn_stop)
		row4.addWidget(self.btn_clear)

		# Spinning progress indicator using QLabel with animation
		self.spinner_label = QLabel()
		self.spinner_label.setFixedSize(self._px(32), self._px(32))
		self.spinner_label.setVisible(False)
		self.spinner_label.setAlignment(Qt.AlignCenter)
		row4.addWidget(self.spinner_label)

		# Create spinner animation
		from PySide6.QtCore import QTimer
		self.spinner_angle = 0
		self.spinner_timer = QTimer()
		self.spinner_timer.timeout.connect(self._update_spinner)
		self.spinner_color = "#ff9800"  # Default: yellow/orange

		row4.addStretch(1)
		vl.addLayout(row4)

		# ── Table ─────────────────────────────────────────────────────────────────
		self.table = QTableWidget(0, 5)
		self.table.setHorizontalHeaderLabels(["#", "Artist", "Title", "Status", "Actions"])
		self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
		self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
		self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
		self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
		self.table.horizontalHeader().resizeSection(3, self._px(220))  # Fixed width for Status column with indicator
		self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
		self.table.horizontalHeader().resizeSection(4, self._px(160))  # Fixed width for Actions column
		header_font = QFont(retro_font_family, default_pt + 2, QFont.Bold)
		self.table.horizontalHeader().setFont(header_font)

		# Set default row height for better spacing
		self.table.verticalHeader().setDefaultSectionSize(self._px(48))
		self.table.verticalHeader().setMinimumSectionSize(self._px(48))

		# Disable alternating row colors to allow custom backgrounds
		self.table.setAlternatingRowColors(False)

		# Override qt-material's aggressive table styling to allow cell background colors
		self.table.setStyleSheet("""
			QTableWidget {
				gridline-color: #424242;
				background-color: #1e1e1e;
			}
			QTableWidget::item {
				padding: 8px;
				border: none;
			}
		""")

		vl.addWidget(self.table, 1)

		# ── Bottom status ─────────────────────────────────────────────────────────
		status_row = QHBoxLayout()
		self.lbl_log = QLabel("")
		self.lbl_log.setTextInteractionFlags(Qt.TextSelectableByMouse)
		status_row.addWidget(self.lbl_log, 1)

		# Percentage label next to progress bar
		self.lbl_progress_pct = QLabel("0%")
		self.lbl_progress_pct.setFont(QFont(retro_font_family, default_pt, QFont.Weight.Bold))
		self.lbl_progress_pct.setMinimumWidth(self._px(50))
		self.lbl_progress_pct.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
		status_row.addWidget(self.lbl_progress_pct)
		vl.addLayout(status_row)

		self.progress = QProgressBar()
		self.progress.setMinimum(0)
		self.progress.setValue(0)
		self.progress.setTextVisible(False)  # We show percentage separately
		self.progress.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
		vl.addWidget(self.progress)

		self._load_last_session()
		self._load_settings_from_file()

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

	def _get_icon(self, icon_name: str) -> QIcon:
		"""Get Material Design icon using qtawesome"""
		import qtawesome as qta

		# Map to Material Design icon names
		icon_map = {
			"launch": "mdi6.launch",              # External link icon
			"help": "mdi6.help-circle-outline",   # Question mark icon
			"settings": "mdi6.cog",               # Settings gear icon
			"play": "mdi6.play",                  # Play/Start icon
			"stop": "mdi6.stop",                  # Stop icon
			"clear": "mdi6.delete-outline",       # Clear/Delete icon
			"folder": "mdi6.folder-open",         # Folder icon for browse buttons
			"file": "mdi6.file-document",         # File icon for file browse
		}

		try:
			# Use Material Design Icons from qtawesome
			if icon_name in icon_map:
				# Destructive actions use white color (on red background)
				if icon_name in ("stop", "clear"):
					return qta.icon(icon_map[icon_name], color='white')
				return qta.icon(icon_map[icon_name], color='#e6e6e6')  # Light gray text
		except Exception:
			pass

		# Fallback to system icons
		return self.style().standardIcon(self.style().StandardPixmap.SP_MessageBoxQuestion)

	def _update_spinner(self):
		"""Update the spinning progress indicator (clockwise)"""
		# Increment angle clockwise (positive direction)
		self.spinner_angle = (self.spinner_angle + 30) % 360

		# Draw spinner
		pixmap = QPixmap(self._px(32), self._px(32))
		pixmap.fill(Qt.transparent)

		from PySide6.QtGui import QPainter, QPen
		painter = QPainter(pixmap)
		painter.setRenderHint(QPainter.Antialiasing)

		# Draw circular spinner
		pen = QPen(QColor(self.spinner_color))
		pen.setWidth(self._px(3))
		pen.setCapStyle(Qt.RoundCap)
		painter.setPen(pen)

		# Draw arc - start from top and go clockwise
		rect = pixmap.rect().adjusted(self._px(4), self._px(4), -self._px(4), -self._px(4))
		# Qt angles: 0 = 3 o'clock, 90*16 = 12 o'clock (top), positive = counter-clockwise
		# To go clockwise from top: start at 90 degrees, subtract angle
		start_angle = (90 - self.spinner_angle) * 16
		painter.drawArc(rect, start_angle, 120 * 16)

		painter.end()
		self.spinner_label.setPixmap(pixmap)

	def _open_url(self, url: str):
		"""Open URL in default browser"""
		from PySide6.QtGui import QDesktopServices
		from PySide6.QtCore import QUrl
		QDesktopServices.openUrl(QUrl(url))

	def _open_help_dialog(self):
		"""Open the help dialog"""
		dialog = HelpDialog(self)
		dialog.exec()

	def _open_advanced_settings(self):
		"""Open the advanced settings dialog"""
		dialog = AdvancedSettingsDialog(self)

		# Populate from settings
		cfg = load_settings()
		dialog.ed_ytdlp.setText(cfg.get("yt_dlp_path", "") or "")
		dialog.ed_ffmpeg.setText(cfg.get("ffmpeg_path", "") or "")
		dialog.ed_cookies_file.setText(cfg.get("cookies_file", "") or "")

		# Populate browser combo
		dialog.combo_cookies.addItem("Disabled", "")
		for b in list_available_browsers():
			dialog.combo_cookies.addItem(b.capitalize(), b)

		# Set current browser
		stored_browser = str(cfg.get("cookies_browser") or "")
		if stored_browser:
			parts = stored_browser.split(":", 1)
			sb = parts[0].strip()
			sp = parts[1].strip() if len(parts) == 2 else None
			for i in range(dialog.combo_cookies.count()):
				if dialog.combo_cookies.itemData(i) == sb:
					dialog.combo_cookies.setCurrentIndex(i)
					# Populate profiles if needed
					self._populate_dialog_profiles(dialog, sb, sp)
					break
		else:
			# Default to Firefox if available
			for i in range(dialog.combo_cookies.count()):
				if dialog.combo_cookies.itemData(i) == "firefox":
					dialog.combo_cookies.setCurrentIndex(i)
					self._populate_dialog_profiles(dialog, "firefox", None)
					break

		# Connect browser change handler
		dialog.combo_cookies.currentIndexChanged.connect(
			lambda: self._populate_dialog_profiles(dialog, dialog.combo_cookies.currentData(), None)
		)

		# Show dialog
		if dialog.exec() == QDialog.Accepted:
			# Save settings
			cookies_browser = dialog.combo_cookies.currentData()
			if dialog.profile_panel.isVisible() and dialog.combo_profile.count() > 0:
				profile = dialog.combo_profile.currentData()
				if profile:
					cookies_browser = f"{cookies_browser}:{profile}"

			cfg = {
				"yt_dlp_path": dialog.ed_ytdlp.text().strip() or None,
				"ffmpeg_path": dialog.ed_ffmpeg.text().strip() or None,
				"cookies_browser": cookies_browser if cookies_browser else None,
				"cookies_file": dialog.ed_cookies_file.text().strip() or None,
			}
			save_settings(cfg)
			self._settings_ytdlp = cfg.get("yt_dlp_path", "") or ""
			self._settings_ffmpeg = cfg.get("ffmpeg_path", "") or ""
			self._settings_cookies_browser = cfg.get("cookies_browser", "") or ""
			self._settings_cookies_file = cfg.get("cookies_file", "") or ""

	def _populate_dialog_profiles(self, dialog, browser, stored_profile):
		"""Populate profile dropdown in dialog"""
		dialog.combo_profile.clear()
		if not browser:
			dialog.profile_panel.setVisible(False)
			return
		profiles = list_profiles(browser)
		chromium_like = browser in ("edge", "chrome", "brave", "opera", "vivaldi")
		if not profiles:
			if chromium_like:
				dialog.combo_profile.addItem("Default", "Default")
				dialog.profile_panel.setVisible(True)
			else:
				dialog.profile_panel.setVisible(False)
				return
		else:
			for p in profiles:
				dialog.combo_profile.addItem(p, p)
			dialog.profile_panel.setVisible(True)
		if stored_profile:
			for i in range(dialog.combo_profile.count()):
				if dialog.combo_profile.itemData(i) == stored_profile:
					dialog.combo_profile.setCurrentIndex(i)
					break

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
		return self._settings_ytdlp or None

	def _ffmpeg_override(self) -> str | None:
		return self._settings_ffmpeg or None

	def _cookies_browser(self) -> str | None:
		return self._settings_cookies_browser or None

	def _cookies_file(self) -> str | None:
		return self._settings_cookies_file or None

	def _load_settings_from_file(self):
		"""Load settings from file into internal state"""
		cfg = load_settings()
		self._settings_ytdlp = cfg.get("yt_dlp_path", "") or ""
		self._settings_ffmpeg = cfg.get("ffmpeg_path", "") or ""
		self._settings_cookies_browser = cfg.get("cookies_browser", "") or ""
		self._settings_cookies_file = cfg.get("cookies_file", "") or ""

	def _persist_settings(self, *, include_paths: bool = False) -> None:
		def _norm(text: str) -> str | None:
			value = text.strip() if text else ""
			return value or None
		cfg = {
			"yt_dlp_path": _norm(self._settings_ytdlp),
			"ffmpeg_path": _norm(self._settings_ffmpeg),
			"cookies_browser": _norm(self._settings_cookies_browser),
			"cookies_file": _norm(self._settings_cookies_file),
		}
		if include_paths:
			cfg["csv_path"] = _norm(self.ed_csv.text())
			cfg["output_dir"] = _norm(self.ed_out.text())
		save_settings(cfg)

	def _load_last_session(self) -> None:
		"""Load CSV and output paths from last session"""
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
		self.table.setRowCount(len(self.tracks))
		for i, t in enumerate(self.tracks):
			self.table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
			# Artist column
			artist = t.get('artists', '').strip()
			self.table.setItem(i, 1, QTableWidgetItem(artist if artist else "None"))
			# Title column
			self.table.setItem(i, 2, QTableWidgetItem(t['title']))
			# Status column - use StatusWidget with colored indicator
			status_widget = StatusWidget("Queued", "#b3b3b3")
			self.table.setCellWidget(i, 3, status_widget)
			# Actions column
			btn_alt = QPushButton("Alternatives")
			btn_alt.setMinimumHeight(self._px(32))
			btn_alt.setStyleSheet("padding: 6px 12px;")
			btn_alt.setEnabled(False)
			btn_alt.clicked.connect(partial(self.on_open_alternatives, i))
			self.table.setCellWidget(i, 4, btn_alt)
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
		self.spinner_color = "#ff9800"  # Yellow spinner
		self.spinner_label.setVisible(True)
		self.spinner_timer.start(50)  # Update every 50ms
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
			# Stop the spinner timer first before changing color to prevent segfault
			if self.spinner_timer.isActive():
				self.spinner_timer.stop()
			self.spinner_color = "#f44336"  # Turn spinner red
			# Restart spinner with red color
			self.spinner_timer.start(50)
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
		try:
			info = self.track_results.get(row_idx)
			if not info:
				QMessageBox.information(self, "Results pending", "This track is still processing. Try again shortly.")
				return
			track = info.get("track")
			if not track:
				QMessageBox.warning(self, "Unavailable", "Track metadata is missing for this row.")
				return
			options = info.get("options") or []

			# Show modal dialog
			dialog = AlternativesDialog(track, options, self)
			if dialog.exec() == QDialog.Accepted:
				action, selected_option = dialog.get_result()

				if action == 'download' and selected_option:
					# User wants to download the selected alternative
					self._download_alternative(row_idx, track, selected_option)
				elif action == 'skip':
					# User wants to skip this track
					self._skip_track(row_idx, track)
		except Exception as e:
			from csvmusic.core.log import log
			log(f"Error opening alternatives for row {row_idx}: {e}")
			import traceback
			log(traceback.format_exc())
			try:
				QMessageBox.critical(self, "Error", f"Failed to open alternatives: {str(e)}")
			except Exception:
				pass

	def _download_alternative(self, row_idx: int, track: dict, option: dict):
		"""Download a manually selected alternative"""
		out_dir = self.ed_out.text().strip()
		if not out_dir:
			QMessageBox.warning(self, "Missing Output", "Choose an output folder before downloading.")
			return

		fmt = "m4a" if self.rb_m4a.isChecked() else "mp3"

		# Start download worker
		worker = SingleDownloadWorker(
			row_idx,
			track,
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

		# Store worker temporarily
		if not hasattr(self, '_manual_workers'):
			self._manual_workers = {}
		self._manual_workers[row_idx] = worker

		worker.sig_status.connect(self.on_row_status)
		worker.sig_finished.connect(lambda r, p: self._on_manual_download_finished(r, p))
		worker.start()

		self.lbl_log.setText(f"Manual download started: {track.get('artists','')} — {track.get('title','')}")

	def _skip_track(self, row_idx: int, track: dict):
		"""Skip a track and mark it as skipped"""
		self.on_row_status(row_idx, "Skipped (user)")
		self.lbl_log.setText(f"Skipped: {track.get('artists','')} — {track.get('title','')}")

		# Update track results
		info = self.track_results.get(row_idx, {})
		info["skipped"] = True
		self.track_results[row_idx] = info

	def _on_manual_download_finished(self, row_idx: int, payload: dict):
		"""Handle completion of manual download"""
		# Update track results
		info = self.track_results.setdefault(row_idx, {})
		info.update(payload)

		track = info.get("track")
		if info.get("downloaded"):
			self.lbl_log.setText(f"Manual download complete: {track.get('artists','')} — {track.get('title','')}")
			self.on_row_status(row_idx, f"Done → {payload.get('file_path', 'file')}")
		else:
			err = info.get("error") or "Unknown error"
			self.lbl_log.setText(f"Manual download failed: {err}")
			self.on_row_status(row_idx, f"Fail: {err[:120]}")

		# Clean up worker
		if hasattr(self, '_manual_workers'):
			self._manual_workers.pop(row_idx, None)

	def on_clear(self):
		if self.worker:
			return
		# Check for running manual download workers
		if hasattr(self, '_manual_workers'):
			for worker in self._manual_workers.values():
				if worker and worker.isRunning():
					QMessageBox.information(self, "Busy", "Wait for in-progress manual downloads to finish before clearing.")
					return
		self.tracks = []
		self.total = 0
		self.table.setRowCount(0)
		self.ed_csv.clear()
		self.lbl_log.clear()

		# Reset progress bar properly
		self.progress.setMaximum(100)
		self.progress.setValue(0)
		self.lbl_progress_pct.setText("0%")

		self.btn_start.setEnabled(True)
		self.btn_stop.setEnabled(False)
		self.btn_clear.setEnabled(False)
		self._allow_path_persist = False
		self._persist_settings(include_paths=True)
		self.track_results = {}
		self.action_buttons = {}
		# Clean up any manual workers
		if hasattr(self, '_manual_workers'):
			self._manual_workers.clear()

	def on_row_status(self, row_idx: int, status: str):
		"""Update status widget with colored indicator"""
		if 0 <= row_idx < self.table.rowCount():
			# Determine color based on status
			color = "#b3b3b3"  # Default gray

			if status.startswith("Done"):
				color = "#4caf50"  # Green - success
			elif status.startswith("Fail"):
				color = "#f44336"  # Red - complete failure
			elif status.startswith("Skipped") or status.startswith("Downloading") or status.startswith("Tagging"):
				color = "#ff9800"  # Orange/Yellow - partial failure or in progress

			# Get or create the StatusWidget in column 3
			status_widget = self.table.cellWidget(row_idx, 3)
			if isinstance(status_widget, StatusWidget):
				status_widget.set_status(status, color)
			else:
				# Create new StatusWidget if it doesn't exist
				status_widget = StatusWidget(status, color)
				self.table.setCellWidget(row_idx, 3, status_widget)

	def on_progress(self, processed: int, total: int):
		self.progress.setMaximum(total)
		self.progress.setValue(processed)

		# Update percentage label
		if total > 0:
			pct = round((processed / total) * 100)
			self.lbl_progress_pct.setText(f"{pct}%")
		else:
			self.lbl_progress_pct.setText("0%")

	def on_done(self, msg: str, matched: list, skipped: list, failed: list):
		from PySide6.QtWidgets import QApplication
		self.btn_start.setEnabled(True)
		self.btn_stop.setEnabled(False)
		self.btn_clear.setEnabled(True)
		self.spinner_timer.stop()
		self.spinner_label.setVisible(False)
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

		# Stop manual download workers if running
		if hasattr(self, '_manual_workers'):
			for worker in list(self._manual_workers.values()):
				if worker and worker.isRunning():
					worker.quit()
					worker.wait(1000)

		event.accept()
