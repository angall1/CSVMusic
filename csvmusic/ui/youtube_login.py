from pathlib import Path

from PySide6.QtCore import QProcess, QThread, Signal
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from csvmusic.core.settings import settings_path
from csvmusic.core.youtube_login import find_firefox, import_login_cookies, login_command


class CookieImportWorker(QThread):
	completed = Signal(bool, str)

	def __init__(self, profile: Path, destination: Path, parent=None):
		super().__init__(parent)
		self.profile, self.destination = profile, destination

	def run(self) -> None:
		try:
			import_login_cookies(self.profile, self.destination)
			self.completed.emit(True, str(self.destination))
		except Exception:
			# Never expose database rows or cookie values in error messages.
			self.completed.emit(False, "No usable YouTube account session found. Sign in, then close the dedicated browser and try again.")


class YouTubeLoginDialog(QDialog):
	def __init__(self, parent=None):
		super().__init__(parent)
		self.setWindowTitle("Connect YouTube account")
		self.resize(520, 260)
		self.cookie_path = ""
		self.worker = None
		self.browser = QProcess(self)
		self.browser.setStandardOutputFile(QProcess.nullDevice())
		self.browser.setStandardErrorFile(QProcess.nullDevice())
		self.browser.finished.connect(self._browser_closed)
		self.browser.errorOccurred.connect(self._browser_error)
		layout = QVBoxLayout(self)
		instructions = QLabel(
			"Open a dedicated Firefox window, sign into YouTube, then close that browser window. "
			"CSVMusic will import its YouTube cookies automatically—no manual export.\n\n"
			"Your normal browser profile is not read. Your password stays on Google's page. "
			"The dedicated profile and cookies stay on this computer; treat them as account credentials. "
			"Only use this account for YouTube in the dedicated window.\n\n"
			"Age verification still applies. Premium formats are not guaranteed, and account use can trigger restrictions."
		)
		instructions.setWordWrap(True)
		layout.addWidget(instructions)
		self.status = QLabel("Firefox must be installed. Settings are saved only when you press Save.")
		self.status.setWordWrap(True)
		layout.addWidget(self.status)
		self.start = QPushButton("Open YouTube sign-in in Firefox")
		self.start.clicked.connect(self._start)
		layout.addWidget(self.start)
		close = QPushButton("Close")
		close.clicked.connect(self.reject)
		layout.addWidget(close)

	def _start(self) -> None:
		executable = find_firefox()
		if not executable:
			self.status.setText("Firefox was not found. Install Firefox, or use the manual cookie export option.")
			return
		self.profile = settings_path().parent / "youtube-login" / "firefox"
		self.profile.mkdir(parents=True, exist_ok=True, mode=0o700)
		command = login_command(executable, self.profile)
		self.start.setEnabled(False)
		self.status.setText("Sign in on YouTube, then close the dedicated Firefox window to finish connecting.")
		self.browser.start(command[0], command[1:])

	def _browser_error(self, error) -> None:
		if error == QProcess.FailedToStart:
			self.status.setText("Firefox could not start. Use the manual export option or check your Firefox installation.")
			self.start.setEnabled(True)

	def _browser_closed(self, *_args) -> None:
		self.status.setText("Importing the YouTube session…")
		self.worker = CookieImportWorker(self.profile, self.profile.parent / "youtube-cookies.txt", self)
		self.worker.completed.connect(self._imported)
		self.worker.finished.connect(self._import_finished)
		self.worker.start()

	def _imported(self, ok: bool, message: str) -> None:
		if ok:
			self.cookie_path = message
		else:
			self.status.setText(message)

	def _import_finished(self) -> None:
		self.start.setEnabled(True)
		if self.cookie_path:
			self.accept()

	def reject(self) -> None:
		if self.browser.state() != QProcess.NotRunning or (self.worker and self.worker.isRunning()):
			self.status.setText("Close the dedicated Firefox window first. CSVMusic will finish importing before closing.")
			return
		super().reject()

	def closeEvent(self, event) -> None:
		if self.browser.state() != QProcess.NotRunning or (self.worker and self.worker.isRunning()):
			self.reject()
			event.ignore()
		else:
			event.accept()
