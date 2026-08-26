# tabs only
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from csvmusic.ui.library_mode import LibraryModeDialog


def main() -> int:
	app = QApplication.instance() or QApplication(sys.argv)
	dialog = LibraryModeDialog()

	def _tracks_ready(tracks: object, description: str, output: str, fmt: str) -> None:
		QMessageBox.information(
			dialog,
			"Library Test Successful",
			f"{description}\n\n{len(list(tracks or []))} enabled tracks are ready.\n"
			f"Format: {fmt.upper()}\nOutput folder: {output}",
		)

	dialog.tracks_ready.connect(_tracks_ready)
	dialog.show()
	return app.exec()


if __name__ == "__main__":
	raise SystemExit(main())
