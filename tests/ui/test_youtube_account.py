from PySide6.QtWidgets import QApplication, QTabWidget

from csvmusic.ui.library_mode import LibrarySettingsDialog
from csvmusic.ui.workers import YouTubeSessionTestWorker


def test_verified_session_and_sign_out(monkeypatch, tmp_path):
	from types import SimpleNamespace
	from PySide6.QtWidgets import QMessageBox
	monkeypatch.setattr("csvmusic.ui.library_mode.load_settings", lambda: {})
	saved = {}
	monkeypatch.setattr("csvmusic.ui.library_mode.save_settings", saved.update)
	monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
	dialog = LibrarySettingsDialog({"output_dir": str(tmp_path)})
	path = tmp_path / "external-cookies.txt"
	path.write_text("preserve this user file")
	dialog.cookies_file.setText(str(path))
	monkeypatch.setattr(dialog, "sender", lambda: SimpleNamespace(path=str(path)))
	dialog._youtube_test_result(True, "PASS")
	assert dialog.connect_youtube.text() == "Sign out"
	assert "confirmed" in dialog.account_confirmed.text()
	dialog._account_action()
	assert saved["use_cookies"] is False
	assert saved["cookies_file"] is None
	assert dialog.cookies_file.text() == ""
	assert path.read_text() == "preserve this user file"
	assert "Sign in" in dialog.connect_youtube.text()
	dialog.close()


def test_fallback_controls_are_in_advanced_subtab(monkeypatch, tmp_path):
	monkeypatch.setattr("csvmusic.ui.library_mode.load_settings", lambda: {})
	dialog = LibrarySettingsDialog({"output_dir": str(tmp_path)})
	groups = dialog.findChildren(QTabWidget)
	account_tabs = next(group for group in groups if group.tabText(0) == "Account")
	assert account_tabs.tabText(1) == "Advanced"
	assert account_tabs.widget(1).isAncestorOf(dialog.cookies_file)
	assert account_tabs.widget(0).isAncestorOf(dialog.connect_youtube)
	dialog.close()


def test_account_has_dedicated_tab(monkeypatch, tmp_path):
	monkeypatch.setattr("csvmusic.ui.library_mode.load_settings", lambda: {})
	dialog = LibrarySettingsDialog({"output_dir": str(tmp_path)})
	tabs = dialog.findChild(QTabWidget)
	assert "YouTube Account" in [tabs.tabText(index) for index in range(tabs.count())]
	assert dialog.session_test.text() == "Test YouTube connection"
	dialog._test_youtube_connection()
	assert "Sign in" in dialog.session_status.text()
	dialog.close()


def test_file_import_starts_test(monkeypatch, tmp_path):
	monkeypatch.setattr("csvmusic.ui.library_mode.load_settings", lambda: {})
	dialog = LibrarySettingsDialog({"output_dir": str(tmp_path)})
	calls = []
	monkeypatch.setattr(dialog, "_test_youtube_connection", lambda: calls.append(True))
	monkeypatch.setattr("csvmusic.ui.library_mode.QFileDialog.getOpenFileName", lambda *args: ("cookies.txt", ""))
	dialog._browse_cookies()
	assert calls == [True]
	dialog.close()


def test_session_worker_reports_verified_login(monkeypatch):
	monkeypatch.setattr("csvmusic.core.youtube_session.validate_cookie_file", lambda path: (True, "valid"))
	monkeypatch.setattr("csvmusic.core.youtube_session.verify_youtube_session", lambda path: True)
	worker = YouTubeSessionTestWorker("test.txt")
	results = []
	worker.sig_done.connect(lambda ok, message: results.append((ok, message)))
	worker.run()
	assert results[0][0] is True
	assert "login only" in results[0][1]


def test_session_worker_does_not_expose_network_exception(monkeypatch):
	monkeypatch.setattr("csvmusic.core.youtube_session.validate_cookie_file", lambda path: (True, "valid"))
	def fail(path):
		raise RuntimeError("secret-cookie-value")
	monkeypatch.setattr("csvmusic.core.youtube_session.verify_youtube_session", fail)
	worker = YouTubeSessionTestWorker("test.txt")
	results = []
	worker.sig_done.connect(lambda ok, message: results.append((ok, message)))
	worker.run()
	assert results[0][0] is False
	assert "secret-cookie-value" not in results[0][1]
