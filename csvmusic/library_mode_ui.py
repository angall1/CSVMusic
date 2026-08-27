# tabs only
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from csvmusic.ui.library_mode import LibraryModeDialog


def main() -> int:
	app = QApplication.instance() or QApplication(sys.argv)
	dialog = LibraryModeDialog()
	legacy_windows = []

	def _tracks_ready(tracks: object, description: str, output: str, fmt: str) -> None:
		QMessageBox.information(
			dialog,
			"Library Test Successful",
			f"{description}\n\n{len(list(tracks or []))} enabled tracks are ready.\n"
			f"Format: {fmt.upper()}\nOutput folder: {output}",
		)

	dialog.tracks_ready.connect(_tracks_ready)

	def _open_legacy_mode() -> None:
		# Import lazily so LibraryModeDialog and MainWindow can continue sharing
		# their core workers without introducing an import cycle at startup.
		from csvmusic.ui.main_window import MainWindow
		window = MainWindow()
		window.show()
		window.raise_()
		window.activateWindow()
		legacy_windows.append(window)

	dialog.legacy_mode_requested.connect(_open_legacy_mode)
	dialog.show()
	return app.exec()


if __name__ == "__main__":
	raise SystemExit(main())
