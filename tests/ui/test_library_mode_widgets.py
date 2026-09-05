# tabs only
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from csvmusic.ui.library_mode import _configure_playlist_status_widget


def test_error_status_button_does_not_use_label_only_alignment_api() -> None:
	app = QApplication.instance() or QApplication([])
	button = QPushButton("1 error")

	_configure_playlist_status_widget(button, unscanned=False)

	assert button.minimumWidth() == 112
	assert "text-align: right" in button.styleSheet()
	assert app is not None


def test_text_status_keeps_right_alignment() -> None:
	app = QApplication.instance() or QApplication([])
	label = QLabel("1 missing")

	_configure_playlist_status_widget(label, unscanned=False)

	assert label.alignment() == Qt.AlignRight | Qt.AlignVCenter
	assert app is not None
