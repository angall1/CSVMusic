import sys
import time
import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QDialog
from csvmusic.ui.youtube_login import YouTubeLoginDialog


def test_firefox_process_receives_clean_environment(monkeypatch, tmp_path):
	monkeypatch.setenv("LD_LIBRARY_PATH", "/bundled/libs")
	monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
	monkeypatch.setattr("csvmusic.core.subprocess_env.sys.frozen", True, raising=False)
	monkeypatch.setattr("csvmusic.ui.youtube_login.find_firefox", lambda: sys.executable)
	monkeypatch.setattr("csvmusic.ui.youtube_login.settings_path", lambda: tmp_path / "settings.json")
	script = "import os, pathlib, sys; assert 'LD_LIBRARY_PATH' not in os.environ; pathlib.Path(sys.argv[1], 'cookies.sqlite').touch()"
	monkeypatch.setattr("csvmusic.ui.youtube_login.login_command", lambda exe, profile: [exe, "-c", script, str(profile)])
	monkeypatch.setattr("csvmusic.ui.youtube_login.import_login_cookies", lambda *args: None)
	dialog = YouTubeLoginDialog()
	dialog._start()
	deadline = time.monotonic() + 10
	while dialog.result() != QDialog.Accepted and time.monotonic() < deadline:
		QCoreApplication.processEvents()
		time.sleep(0.01)
	assert dialog.result() == QDialog.Accepted
	dialog.deleteLater()


@pytest.mark.parametrize("existing_profile", [False, True])
def test_firefox_early_exit_reports_code_without_import(monkeypatch, tmp_path, existing_profile):
	dialog = YouTubeLoginDialog()
	dialog.profile = tmp_path
	if existing_profile:
		(tmp_path / "cookies.sqlite").touch()
	dialog._browser_closed(3)
	assert "exit code 3" in dialog.status.text()
	assert dialog.worker is None
	assert dialog.start.isEnabled()
	dialog.deleteLater()
