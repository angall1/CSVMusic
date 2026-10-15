# tabs only
import pytest

from csvmusic.core import downloader


@pytest.mark.parametrize("message", [
	"ERROR: Sign in to confirm your age",
	"ERROR: This video may be inappropriate for some users",
	"ERROR: This video is age-restricted",
	"ERROR: This video is age restricted",
	"ERROR: AGE_RESTRICTED",
])
@pytest.mark.parametrize("using_cookies", [False, True])
def test_age_errors_offer_account_specific_recovery(message, using_cookies):
	detail = downloader._summarize_tool_output(message, "", using_cookies=using_cookies)
	assert "Settings > YouTube Account" in detail
	if using_cookies:
		assert "Cookies were used" in detail
		assert "reconnect or refresh" in detail
		assert "Enable cookies" not in detail
	else:
		assert "Enable cookies" in detail
		assert "Use this YouTube session for downloads" in detail
		assert "Save" in detail and "retry" in detail
		assert "eligible" in detail


@pytest.mark.parametrize("message", [
	"ERROR: Sign in to confirm you're not a bot",
	"ERROR: Private video. Sign in if you have access",
	"ERROR: Requested format is not available",
])
def test_unrelated_errors_are_not_age_restrictions(message):
	assert not downloader.is_age_restriction_error(message)
	assert "Age-restricted" not in downloader._summarize_tool_output(message, "")


@pytest.mark.parametrize("download", [downloader.download_mp3, downloader.download_m4a, downloader.download_opus])
@pytest.mark.parametrize("cookie_args", [[], ["--cookies", "cookies.txt"], ["--cookies-from-browser", "firefox"]])
def test_age_restriction_stops_fallbacks_without_losing_guidance(monkeypatch, tmp_path, download, cookie_args):
	calls = []
	def fail(args):
		calls.append(args)
		return 1, "", "ERROR: Sign in to confirm your age"
	monkeypatch.setattr(downloader, "_run_ytdlp_module", fail)
	monkeypatch.setattr(downloader, "ytdlp_js_runtime_args", lambda _bin: [])
	with pytest.raises(downloader.AgeRestrictedError) as error:
		download("selected-video", tmp_path, "Artist - Song", yt_dlp_bin=downloader.INTERNAL_YTDLP, extra_yt_dlp_args=cookie_args)
	assert "Settings > YouTube Account" in str(error.value)
	assert ("Cookies were used" in str(error.value)) == bool(cookie_args)
	assert len(calls) == 1
	assert all(argument in calls[0] for argument in cookie_args)


def test_successful_download_ignores_age_warning(monkeypatch):
	monkeypatch.setattr(downloader, "_run_ytdlp_module", lambda args: (0, "", "WARNING: age-restricted"))
	assert downloader._run_ytdlp_detail([downloader.INTERNAL_YTDLP, "url"]) == (0, "")
