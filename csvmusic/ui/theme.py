# tabs only
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

from csvmusic.core.log import log
from csvmusic.core.paths import resource_base


WINDOW = QColor("#c0c0c0")
PANEL = QColor("#d4d0c8")
TEXT = QColor("#101010")
DISABLED_TEXT = QColor("#606060")
BASE = QColor("#ffffff")
ALTERNATE_BASE = QColor("#e8e8e8")
HIGHLIGHT = QColor("#000080")
HIGHLIGHT_TEXT = QColor("#ffffff")
TOOLTIP_BASE = QColor("#ffffcc")
LINK = QColor("#0000cc")
VISITED_LINK = QColor("#551a8b")


def _load_body_font() -> str:
	families: list[str] = []
	for name in ("ComicNeue-Regular.ttf", "ComicNeue-Bold.ttf"):
		path = resource_base() / "fonts" / name
		if not path.is_file():
			continue
		font_id = QFontDatabase.addApplicationFont(str(path))
		if font_id >= 0:
			families.extend(QFontDatabase.applicationFontFamilies(font_id))
	if families:
		family = families[0]
		# Existing dialogs intentionally request Comic Sans MS. Substitution
		# preserves that design while resolving to the same bundled font on
		# Windows, macOS, and Linux.
		QFont.insertSubstitution("Comic Sans MS", family)
		QFont.insertSubstitution("Comic Sans", family)
		log(f"Application body font loaded: {family}")
		return family
	log("Bundled Comic Neue font could not be loaded; using the Qt sans-serif fallback.")
	return "Sans Serif"


def retro_palette() -> QPalette:
	palette = QPalette()
	roles = QPalette.ColorRole
	for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
		palette.setColor(group, roles.Window, WINDOW)
		palette.setColor(group, roles.WindowText, TEXT)
		palette.setColor(group, roles.Base, BASE)
		palette.setColor(group, roles.AlternateBase, ALTERNATE_BASE)
		palette.setColor(group, roles.ToolTipBase, TOOLTIP_BASE)
		palette.setColor(group, roles.ToolTipText, TEXT)
		palette.setColor(group, roles.Text, TEXT)
		palette.setColor(group, roles.Button, PANEL)
		palette.setColor(group, roles.ButtonText, TEXT)
		palette.setColor(group, roles.BrightText, QColor("#ffffff"))
		palette.setColor(group, roles.Highlight, HIGHLIGHT)
		palette.setColor(group, roles.HighlightedText, HIGHLIGHT_TEXT)
		palette.setColor(group, roles.Link, LINK)
		palette.setColor(group, roles.LinkVisited, VISITED_LINK)
	palette.setColor(QPalette.ColorGroup.Disabled, roles.Window, WINDOW)
	palette.setColor(QPalette.ColorGroup.Disabled, roles.WindowText, DISABLED_TEXT)
	palette.setColor(QPalette.ColorGroup.Disabled, roles.Base, PANEL)
	palette.setColor(QPalette.ColorGroup.Disabled, roles.Text, DISABLED_TEXT)
	palette.setColor(QPalette.ColorGroup.Disabled, roles.Button, PANEL)
	palette.setColor(QPalette.ColorGroup.Disabled, roles.ButtonText, DISABLED_TEXT)
	palette.setColor(QPalette.ColorGroup.Disabled, roles.Highlight, QColor("#808080"))
	palette.setColor(QPalette.ColorGroup.Disabled, roles.HighlightedText, BASE)
	return palette


def apply_retro_theme(app: QApplication) -> str:
	# Fusion honors QPalette consistently and does not reinterpret controls
	# through the host desktop's dark/light native theme.
	app.setStyle("Fusion")
	family = _load_body_font()
	app.setFont(QFont(family, 9))
	app.setPalette(retro_palette())
	return family
