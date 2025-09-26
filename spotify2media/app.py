# tabs only
if __package__ in (None, ""):
	import sys, pathlib
	sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import builtins, sys, time, subprocess, datetime, pathlib

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
from PySide6.QtCore import Qt
from spotify2media.core.paths import (
	ffmpeg_path,
	splash_image_path,
	app_icon_path,
	resource_base,
)
from spotify2media.core.log import log
from spotify2media.version import APP_VERSION

_WINDOWS = sys.platform.startswith("win")

def _hidden_subprocess_kwargs() -> dict:
	if not _WINDOWS:
		return {}
	startupinfo = subprocess.STARTUPINFO()
	startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
	flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
	return {"startupinfo": startupinfo, "creationflags": flags}

def probe_ffmpeg() -> None:
	path = ffmpeg_path()
	log(f"ffmpeg resolved to: {path}")
	try:
		subprocess.run(
			[path, "-version"],
			capture_output=True,
			text=True,
			timeout=2,
			**_hidden_subprocess_kwargs()
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
	return splash

def main() -> int:
	# Optional: update native bootloader splash text (if built with --splash)
	pyi_splash = None
	try:
		import pyi_splash as _ps
		pyi_splash = _ps
		pyi_splash.update_text(f"Loading Spotify2Media v{APP_VERSION}…")
	except Exception:
		pyi_splash = None

	app = QApplication(sys.argv)
	if _WINDOWS:
		try:
			import ctypes
			ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Spotify2Media.CSVMusic")
		except Exception:
			pass
	icon_path = app_icon_path()
	if icon_path:
		app.setWindowIcon(QIcon(str(icon_path)))
		log(f"Application icon set from {icon_path}")
	else:
		log("Application icon missing; using default.")
	qt_splash = show_qt_splash(app)
	if pyi_splash is not None:
		try:
			pyi_splash.close()
		except Exception:
			pass
		pyi_splash = None

	try:
		probe_ffmpeg()
	except Exception:
		pass

	from spotify2media.ui.main_window import MainWindow
	w = MainWindow()
	if icon_path:
		w.setWindowIcon(QIcon(str(icon_path)))
	else:
		log("Main window icon fallback in use.")
	w.setWindowTitle(f"CSVMusic — v{APP_VERSION}  [{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
	w.show()
	if qt_splash is not None:
		qt_splash.finish(w)

	if pyi_splash is not None:
		try:
			pyi_splash.close()
		except Exception:
			pass

	return app.exec()

if __name__ == "__main__":
	sys.exit(main())
