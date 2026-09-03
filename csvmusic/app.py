# tabs only
if __package__ in (None, ""):
	import sys, pathlib
	sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import builtins, sys, time, subprocess, pathlib

# --- Hard block tkinter imports everywhere (some libs import it implicitly) ---
_orig_import = builtins.__import__
def _no_tk_import(name, globals=None, locals=None, fromlist=(), level=0):
	if name in ("tkinter", "_tkinter", "Tkinter") or name.startswith("tkinter."):
		raise ImportError("tkinter disabled")
	return _orig_import(name, globals, locals, fromlist, level)
builtins.__import__ = _no_tk_import  # install ASAP

# --- If a Tk root sneaks in before the block (rare), close its window quickly ---
try:
	import ctypes
	user32 = ctypes.windll.user32
	for _ in range(20):  # up to ~1s
		hwnd = user32.FindWindowW("TkTopLevel", None)
		if hwnd:
			user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
			break
		time.sleep(0.05)
except Exception:
	pass

from PySide6.QtWidgets import QApplication, QSplashScreen
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtCore import Qt, QTimer
from csvmusic.core.paths import (
	ffmpeg_path,
	splash_image_path,
	app_icon_path,
	resource_base,
)
from csvmusic.core.log import log
from csvmusic.core.subprocess_env import subprocess_kwargs
from csvmusic.version import APP_VERSION
# Qt WebEngine-backed Library Mode must be imported before QApplication is
# constructed. Importing it afterward can deadlock Qt initialization on
# Windows, leaving only the bootstrap window visible.
from csvmusic.ui.library_mode import LibraryModeDialog
from csvmusic.ui.theme import apply_retro_theme

_WINDOWS = sys.platform.startswith("win")

def probe_ffmpeg() -> None:
	path = ffmpeg_path()
	log(f"ffmpeg resolved to: {path}")
	try:
		subprocess.run(
			[path, "-version"],
			capture_output=True,
			text=True,
			encoding="utf-8",
			errors="replace",
			timeout=2,
			**subprocess_kwargs()
		)
	except Exception:
		pass

def show_qt_splash(app: QApplication) -> QSplashScreen | None:
	img_candidates: list[pathlib.Path] = []
	primary = splash_image_path()
	if primary:
		img_candidates.append(primary)
	base = resource_base()
	for fallback_name in ("splash.png",):
		candidate = base / fallback_name
		if candidate not in img_candidates and candidate.exists():
			img_candidates.append(candidate)
	if not img_candidates:
		log("Splash image missing; skipping Qt splash.")
		return None
	pixmap = QPixmap()
	loaded_path = None
	for path in img_candidates:
		if pixmap.load(str(path)):
			loaded_path = path
			break
	if loaded_path is None:
		log("Splash image failed to load from candidates; skipping Qt splash.")
		return None
	log(f"Splash image loaded from {loaded_path}")
	max_width = 720
	max_height = 360
	if pixmap.width() > max_width or pixmap.height() > max_height:
		pixmap = pixmap.scaled(max_width, max_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
	splash = QSplashScreen(pixmap, Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
	splash.show()
	app.processEvents()
	# A slow or failed main-window initialization must never leave an
	# always-on-top splash stranded over the desktop.
	QTimer.singleShot(8000, splash.close)
	return splash

def main() -> int:
	app = QApplication(sys.argv)
	apply_retro_theme(app)
	if _WINDOWS:
		try:
			import ctypes
			ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CSVMusic.CSVMusic")
		except Exception:
			pass
	icon_path = app_icon_path()
	if icon_path:
		app.setWindowIcon(QIcon(str(icon_path)))
		log(f"Application icon set from {icon_path}")
	else:
		log("Application icon missing; using default.")
	# Library Mode is lightweight enough to open directly. Do not place an
	# always-on-top splash or synchronous FFmpeg process in front of it; tool
	# availability is checked by the existing download preflight when needed.

	# Library Mode is the primary application. The legacy window remains
	# available from Library Mode's header and shares the same core modules.
	w = LibraryModeDialog()
	legacy_windows = []

	def _open_legacy_mode() -> None:
		from csvmusic.ui.main_window import MainWindow
		window = MainWindow()
		window.show()
		window.raise_()
		window.activateWindow()
		legacy_windows.append(window)

	w.legacy_mode_requested.connect(_open_legacy_mode)
	if icon_path:
		w.setWindowIcon(QIcon(str(icon_path)))
	else:
		log("Library window icon fallback in use.")
	w.setWindowTitle(f"CSVMusic Library Mode — v{APP_VERSION}")
	w.show()
	return app.exec()

if __name__ == "__main__":
	sys.exit(main())
