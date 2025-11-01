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

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from qt_material import apply_stylesheet
from csvmusic.core.paths import (
	ffmpeg_path,
	app_icon_path,
)
from csvmusic.core.log import log
from csvmusic.version import APP_VERSION

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

def main() -> int:
	# Optional: update native bootloader splash text (if built with --splash)
	pyi_splash = None
	try:
		import pyi_splash as _ps
		pyi_splash = _ps
		pyi_splash.update_text(f"Loading CSVMusic v{APP_VERSION}…")
	except Exception:
		pyi_splash = None

	app = QApplication(sys.argv)

	# Apply qt-material dark theme (using dark_blue for standard look)
	apply_stylesheet(app, theme='dark_blue.xml', extra={
		'font_family': 'Segoe UI',
		'font_size': '14px',
		'danger': '#f44336',
		'warning': '#ff9800',
		'success': '#4caf50',
		'density_scale': '0',
	})

	# Add custom CSS for destructive buttons and table cell coloring
	app.setStyleSheet(app.styleSheet() + """
		QPushButton#destructive {
			background-color: #c62828;
			color: white;
			border: none;
		}
		QPushButton#destructive:hover {
			background-color: #d32f2f;
		}
		QPushButton#destructive:pressed {
			background-color: #b71c1c;
		}
		QPushButton#destructive:disabled {
			background-color: #424242;
			color: #757575;
		}
	""")

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

	# Close PyInstaller splash if it exists
	if pyi_splash is not None:
		try:
			pyi_splash.close()
		except Exception:
			pass

	try:
		probe_ffmpeg()
	except Exception:
		pass

	from csvmusic.ui.main_window import MainWindow
	w = MainWindow()
	if icon_path:
		w.setWindowIcon(QIcon(str(icon_path)))
	else:
		log("Main window icon fallback in use.")
	w.setWindowTitle(f"CSVMusic — v{APP_VERSION}  [{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
	w.show()

	return app.exec()

if __name__ == "__main__":
	sys.exit(main())
