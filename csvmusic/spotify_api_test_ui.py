# tabs only
import sys

from PySide6.QtWidgets import QApplication

from csvmusic.ui.spotify_api_test import SpotifyAPITestDialog


def main() -> int:
	app = QApplication.instance() or QApplication(sys.argv)
	dialog = SpotifyAPITestDialog()
	dialog.show()
	return app.exec()


if __name__ == "__main__":
	raise SystemExit(main())
