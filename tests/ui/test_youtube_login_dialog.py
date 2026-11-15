import sys
import time
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QThread
from PySide6.QtWidgets import QDialog

from csvmusic.ui.youtube_login import YouTubeLoginDialog

# Stands in for Firefox: like the real one, it cannot start with a leaked LD_LIBRARY_PATH.
FAKE_FIREFOX = """#!/bin/sh
[ -n "$LD_LIBRARY_PATH" ] && exit 1
while [ $# -gt 0 ]; do
	[ "$1" = "-profile" ] && profile="$2"
	shift
done
exec "{python}" -c "
import sqlite3, sys
with sqlite3.connect(sys.argv[1] + '/cookies.sqlite') as db:
	db.execute('CREATE TABLE moz_cookies (host, path, isSecure, expiry, name, value, isHttpOnly)')
	db.execute(\\"INSERT INTO moz_cookies VALUES ('.youtube.com', '/', 1, 2147483647, 'SAPISID', 'test', 1)\\")
" "$profile"
"""


def open_dialog(monkeypatch, tmp_path, script: str) -> YouTubeLoginDialog:
	firefox = tmp_path / "firefox"
	firefox.write_text(script.format(python=sys.executable))
	firefox.chmod(0o755)
	monkeypatch.setattr("csvmusic.ui.youtube_login.find_firefox", lambda: str(firefox))
	monkeypatch.setattr("csvmusic.ui.youtube_login.settings_path", lambda: tmp_path / "settings.json")
	return YouTubeLoginDialog()


def wait_until(condition, timeout: float = 15.0) -> None:
	deadline = time.monotonic() + timeout
	while not condition() and time.monotonic() < deadline:
		QCoreApplication.processEvents()
		QThread.msleep(20)
	assert condition()


def test_firefox_starts_without_the_bundled_library_path(monkeypatch, tmp_path):
	monkeypatch.setenv("LD_LIBRARY_PATH", "/opt/CSVMusic/_internal")
	monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
	dialog = open_dialog(monkeypatch, tmp_path, FAKE_FIREFOX)
	with patch("csvmusic.core.subprocess_env.sys.frozen", True, create=True):
		dialog._start()
	wait_until(lambda: dialog.result() == QDialog.Accepted)
	assert dialog.cookie_path.endswith("youtube-cookies.txt")
	dialog.deleteLater()


def test_firefox_that_dies_before_creating_a_profile_is_reported(monkeypatch, tmp_path):
	dialog = open_dialog(monkeypatch, tmp_path, "#!/bin/sh\nexit 3\n")
	dialog._start()
	wait_until(lambda: dialog.start.isEnabled())
	assert "exit code 3" in dialog.status.text()
	assert not dialog.cookie_path
	dialog.deleteLater()
