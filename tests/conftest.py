# tabs only
import pytest

try:
	from PySide6.QtCore import QCoreApplication, QEvent
	from PySide6.QtWidgets import QApplication
except ImportError:
	# Headless installs (e.g. the Docker image) ship without PySide6; only the
	# Qt-free tests can run there.
	QApplication = None
	collect_ignore = ["ui", "test_app_environment.py"]


@pytest.fixture(scope="session", autouse=True)
def qt_application():
	"""Keep one Qt application alive until all test widgets are disposed."""
	if QApplication is None:
		yield None
		return
	app = QApplication.instance() or QApplication([])
	yield app
	for widget in app.topLevelWidgets():
		widget.close()
		widget.deleteLater()
	QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
	app.processEvents()
	app.quit()
