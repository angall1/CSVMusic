# tabs only
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from csvmusic.ui.spotify_public_scrape import SpotifyPublicScrapeDialog


def main() -> int:
	app = QApplication.instance() or QApplication(sys.argv)
	dialog = SpotifyPublicScrapeDialog()
	if len(sys.argv) > 1:
		dialog.url_input.setText(sys.argv[1])
	dialog.show()
	if len(sys.argv) > 1:
		QTimer.singleShot(0, dialog.start_scrape)
	return app.exec()


if __name__ == "__main__":
	raise SystemExit(main())
