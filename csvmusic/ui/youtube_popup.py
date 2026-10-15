"""Isolated Google-hosted sign-in. No injected scripts or password collection."""
import os
from pathlib import Path
import tempfile

from PySide6.QtCore import QThread, QTimer, QUrl, Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from csvmusic.core.settings import settings_path
from csvmusic.core.youtube_session import youtube_cookie_text, verify_youtube_session


class SessionVerificationWorker(QThread):
	result = Signal(bool)

	def __init__(self, cookies: str, parent=None):
		super().__init__(parent)
		self.cookies = cookies
		self.verified_text = ""

	def run(self) -> None:
		try:
			with tempfile.TemporaryDirectory(prefix="csvmusic-login-") as folder:
				path = Path(folder) / "cookies.txt"
				fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
				with os.fdopen(fd, "w", encoding="utf-8") as stream:
					stream.write(self.cookies)
				ok = verify_youtube_session(str(path))
				if ok and not self.isInterruptionRequested():
					self.verified_text = self.cookies
				self.result.emit(bool(self.verified_text))
		except Exception:
			self.result.emit(False)
		finally:
			self.cookies = ""


class YouTubePopupDialog(QDialog):
	def __init__(self, parent=None):
		super().__init__(parent)
		self.setWindowTitle("Sign in to YouTube — experimental")
		self.resize(620, 760)
		self.cookie_path = ""
		self.cookies = {}
		self.worker = None
		self.cancelled = False
		layout = QVBoxLayout(self)
		note = QLabel("Sign in on Google's page below. CSVMusic stores only YouTube cookies locally and checks whether YouTube recognizes your login. Google may block this embedded browser; if so, use the fallback in Settings. No verification or security warnings are bypassed.")
		note.setWordWrap(True)
		layout.addWidget(note)
		self.address = QLabel()
		layout.addWidget(self.address)
		self.view = QWebEngineView(self)
		# Unnamed profiles are off-the-record: no normal browser/profile access.
		self.profile = QWebEngineProfile(self)
		self.page = QWebEnginePage(self.profile, self.view)
		self.view.setPage(self.page)
		layout.addWidget(self.view, 1)
		self.status = QLabel("Waiting for YouTube sign-in…")
		self.status.setWordWrap(True)
		layout.addWidget(self.status)
		self.retry = QPushButton("Check sign-in again")
		self.retry.clicked.connect(self._verify)
		layout.addWidget(self.retry)
		cancel = QPushButton("Cancel / use another method")
		cancel.clicked.connect(self.reject)
		layout.addWidget(cancel)
		self.timer = QTimer(self)
		self.timer.setSingleShot(True)
		self.timer.setInterval(2500)
		self.timer.timeout.connect(self._verify)
		store = self.profile.cookieStore()
		store.cookieAdded.connect(self._cookie_added)
		store.cookieRemoved.connect(self._cookie_removed)
		self.view.urlChanged.connect(self._url_changed)
		self.view.load(QUrl("https://accounts.google.com/ServiceLogin?service=youtube&continue=https%3A%2F%2Fwww.youtube.com%2F&hl=en"))

	def _url_changed(self, url) -> None:
		# Never display query strings, which can contain authentication tokens.
		self.address.setText(f"{url.scheme()}://{url.host()}")
		if url.host() == "www.youtube.com":
			self.timer.start()

	def _cookie_added(self, cookie) -> None:
		domain = cookie.domain().lower().lstrip(".")
		if domain != "youtube.com" and not domain.endswith(".youtube.com"):
			return
		name = bytes(cookie.name()).decode("latin-1")
		self.cookies[(cookie.domain(), cookie.path(), name)] = {
			"domain": cookie.domain(), "path": cookie.path(), "name": name,
			"value": bytes(cookie.value()).decode("latin-1"), "secure": cookie.isSecure(),
			"http_only": cookie.isHttpOnly(),
			"expires": 0 if cookie.isSessionCookie() else cookie.expirationDate().toSecsSinceEpoch(),
		}
		if name in ("SAPISID", "__Secure-1PAPISID", "__Secure-3PAPISID"):
			self.timer.start()

	def _cookie_removed(self, cookie) -> None:
		self.cookies.pop((cookie.domain(), cookie.path(), bytes(cookie.name()).decode("latin-1")), None)

	def _verify(self) -> None:
		if self.cancelled or (self.worker and self.worker.isRunning()):
			return
		self.retry.setEnabled(False)
		self.status.setText("Checking the session with YouTube…")
		self.worker = SessionVerificationWorker(youtube_cookie_text(list(self.cookies.values())), self)
		self.worker.finished.connect(self._finished)
		self.worker.start()

	def _finished(self) -> None:
		self.retry.setEnabled(True)
		if self.cancelled:
			self.worker.verified_text = ""
			super().reject()
			return
		text = self.worker.verified_text
		self.worker.verified_text = ""
		if not text:
			self.status.setText("Sign-in is not verified yet. Finish signing in, then retry. If Google says this browser is unsupported, cancel and use the browser or manual-export fallback.")
			return
		path = settings_path().parent / "youtube-login" / "popup-cookies.txt"
		path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
		fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".cookies")
		try:
			with os.fdopen(fd, "w", encoding="utf-8") as stream:
				stream.write(text)
			os.replace(temporary, path)
		except OSError:
			self.status.setText("Login was recognized, but the cookies could not be saved. Check folder permissions and retry.")
			return
		finally:
			Path(temporary).unlink(missing_ok=True)
		self.cookie_path = str(path)
		self.timer.stop()
		self.view.stop()
		self.accept()

	def reject(self) -> None:
		self.cancelled = True
		self.timer.stop()
		self.view.stop()
		if self.worker and self.worker.isRunning():
			self.worker.requestInterruption()
			self.status.setText("Cancelling the session check…")
			return
		super().reject()

	def closeEvent(self, event) -> None:
		self.reject()
		if self.worker and self.worker.isRunning():
			event.ignore()
		else:
			event.accept()

	def done(self, result) -> None:
		self.timer.stop()
		self.view.stop()
		self.cookies.clear()
		# Page must die before its off-the-record profile.
		self.page.deleteLater()
		self.page.destroyed.connect(self.profile.deleteLater)
		super().done(result)
