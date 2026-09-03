# tabs only
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

from csvmusic.ui.theme import BASE, HIGHLIGHT, HIGHLIGHT_TEXT, TEXT, apply_retro_theme


def _luminance(color) -> float:
	channels = []
	for value in (color.redF(), color.greenF(), color.blueF()):
		channels.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
	return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(left, right) -> float:
	lighter, darker = sorted((_luminance(left), _luminance(right)), reverse=True)
	return (lighter + 0.05) / (darker + 0.05)


def test_retro_theme_uses_bundled_font_and_high_contrast_palette() -> None:
	app = QApplication.instance() or QApplication([])
	family = apply_retro_theme(app)
	palette = app.palette()

	assert family.casefold() == "comic neue"
	assert palette.color(QPalette.WindowText) == TEXT
	assert palette.color(QPalette.Base) == BASE
	assert palette.color(QPalette.Highlight) == HIGHLIGHT
	assert palette.color(QPalette.HighlightedText) == HIGHLIGHT_TEXT
	assert _contrast(TEXT, BASE) >= 7.0
	assert _contrast(HIGHLIGHT_TEXT, HIGHLIGHT) >= 7.0
