# tabs only
import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def qt_application():
	"""Keep one Qt application alive until all test widgets are disposed."""
	app = QApplication.instance() or QApplication([])
	yield app
	for widget in app.topLevelWidgets():
		widget.close()
		widget.deleteLater()
	QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
	app.processEvents()
	app.quit()
