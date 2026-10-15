from PySide6.QtWidgets import QApplication

from csvmusic.ui.library_mode import RescanSummaryDialog


def test_large_rescan_summary_stays_compact():
	app = QApplication.instance() or QApplication([])
	results = [{"name": f"Playlist {i}"} for i in range(100)]
	text = "\n\n".join(f"Playlist {i}\n" + "Warning details " * 30 for i in range(100))
	dialog = RescanSummaryDialog(results, text)
	dialog.show()
	app.processEvents()
	assert dialog.height() <= 360
	assert dialog.width() <= 620
	assert dialog.details.toPlainText() == text
	assert dialog.details.verticalScrollBar().maximum() > 0
	assert dialog.details.isReadOnly()
	dialog.close()
