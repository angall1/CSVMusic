import sqlite3

import pytest

from csvmusic.core.youtube_login import import_login_cookies, login_command
from csvmusic.core.youtube_session import validate_cookie_file


def make_profile(tmp_path, host=".youtube.com", expiry=2147483647):
	profile = tmp_path / "dedicated"
	profile.mkdir()
	with sqlite3.connect(profile / "cookies.sqlite") as database:
		database.execute("CREATE TABLE moz_cookies (host, path, isSecure, expiry, name, value, isHttpOnly)")
		database.executemany("INSERT INTO moz_cookies VALUES (?, '/', 1, ?, 'SAPISID', ?, 1)", [
			(host, expiry, "test-youtube"),
			(".google.com", expiry, "test-google"),
			(".notyoutube.com", expiry, "test-unrelated"),
		])
	return profile


def test_import_only_youtube(tmp_path):
	profile = make_profile(tmp_path)
	destination = tmp_path / "output" / "cookies.txt"
	import_login_cookies(profile, destination)
	assert validate_cookie_file(str(destination))[0]
	text = destination.read_text()
	assert "test-youtube" in text
	assert "#HttpOnly_.youtube.com" in text
	assert "test-google" not in text
	assert "test-unrelated" not in text
	assert not list(destination.parent.glob("*.cookies"))


@pytest.mark.parametrize("host,expiry", [(".notyoutube.com", 2147483647), (".youtube.com", 1)])
def test_bad_session_preserves_previous_file(tmp_path, host, expiry):
	profile = make_profile(tmp_path, host, expiry)
	destination = tmp_path / "cookies.txt"
	destination.write_text("previous session")
	with pytest.raises(ValueError):
		import_login_cookies(profile, destination)
	assert destination.read_text() == "previous session"
	assert not list(tmp_path.glob("*.cookies"))


def test_missing_profile_is_not_created(tmp_path):
	with pytest.raises(ValueError):
		import_login_cookies(tmp_path / "missing", tmp_path / "cookies.txt")
	assert not (tmp_path / "missing").exists()


def test_dedicated_profile_command(tmp_path):
	command = login_command("firefox", tmp_path / "profile with spaces")
	assert command[command.index("-profile") + 1] == str(tmp_path / "profile with spaces")
	assert "-no-remote" in command
	assert command[-1] == "https://www.youtube.com/"
