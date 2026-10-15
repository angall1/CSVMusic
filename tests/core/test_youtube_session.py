import pytest

from csvmusic.core.youtube_session import validate_cookie_file
from csvmusic.core import downloader


@pytest.mark.parametrize("domain,expiry,prefix,expected", [
	(".youtube.com", "2147483647", "#HttpOnly_", True),
	(".youtube.com", "0", "", True),
	(".youtube.com", "1", "", False),
	(".notyoutube.com", "2147483647", "", False),
	(".google.com", "2147483647", "", False),
])
def test_cookie_validation(tmp_path, domain, expiry, prefix, expected):
	path = tmp_path / "cookies.txt"
	path.write_text(f"# Netscape HTTP Cookie File\n{prefix}{domain}\tTRUE\t/\tTRUE\t{expiry}\tSAPISID\tfake-test-value\n")
	ok, message = validate_cookie_file(str(path))
	assert ok is expected
	assert "fake-test-value" not in message


def test_bad_cookie_file(tmp_path):
	path = tmp_path / "cookies.txt"
	assert not validate_cookie_file(str(path))[0]
	path.write_text("not a cookie file")
	assert not validate_cookie_file(str(path))[0]


def test_authenticated_clients_use_ytdlp_defaults():
	assert downloader._youtube_clients(["--cookies", "cookies.txt"]) == [None]
	assert downloader._youtube_clients(["--cookies-from-browser", "firefox"]) == [None]
	assert downloader._youtube_clients([]) == downloader.YOUTUBE_CLIENTS


@pytest.mark.parametrize("runner", [downloader._run_ytdlp, downloader._run_ytdlp_detail])
def test_authenticated_failure_never_retries_anonymously(monkeypatch, runner):
	calls = []
	def fail(args):
		calls.append(args)
		return 1, "", "Requested format is not available"
	monkeypatch.setattr(downloader, "_run_ytdlp_module", fail)
	result = runner([downloader.INTERNAL_YTDLP, "--cookies", "cookies.txt", "url"])
	assert (result[0] if isinstance(result, tuple) else result) == 1
	assert len(calls) == 1
	assert "--cookies" in calls[0]
