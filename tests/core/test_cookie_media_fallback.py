import subprocess

import pytest

from csvmusic.core import downloader


@pytest.mark.parametrize("internal", [False, True])
def test_cookie_media_403_retries_once_and_captures_public_source(monkeypatch, internal):
	calls = []
	captured = []
	def run(args):
		calls.append(args)
		return (1, "", "ERROR: unable to download video data: HTTP Error 403: Forbidden") if len(calls) == 1 else (0, "public-source", "")
	monkeypatch.setattr(downloader, "_run_ytdlp_module", run)
	monkeypatch.setattr(downloader, "_run_capture", lambda args: subprocess.CompletedProcess(args, *run(args)))
	monkeypatch.setattr(downloader, "capture_source", captured.append)
	monkeypatch.setattr(downloader, "log", lambda message: None)
	downloader.take_download_notices()
	cmd = [downloader.INTERNAL_YTDLP if internal else "yt-dlp", "--cookies", "secret.txt", "--sleep-interval", "5", "https://www.youtube.com/watch?v=test"]
	assert downloader._run_ytdlp_detail(cmd) == (0, "")
	assert len(calls) == 2
	assert "secret.txt" not in calls[1]
	assert "--no-cookies" in calls[1]
	assert "--sleep-interval" in calls[1]
	assert captured[-1] == "public-source"
	assert len(downloader.take_download_notices()) == 2
	assert "--cookies" in cmd


@pytest.mark.parametrize("error", ["Sign in to confirm your age", "HTTP Error 429: Too many requests", "Sign in to confirm you're not a bot", "private video", "members-only"])
def test_restricted_or_rate_limited_error_never_retries(monkeypatch, error):
	calls = []
	def run(args):
		calls.append(args)
		return 1, "", "unable to download video data: HTTP Error 403: Forbidden " + error
	monkeypatch.setattr(downloader, "_run_ytdlp_module", run)
	monkeypatch.setattr(downloader, "log", lambda message: None)
	try:
		downloader._run_ytdlp_detail([downloader.INTERNAL_YTDLP, "--cookies=secret.txt", "url"])
	except downloader.AgeRestrictedError:
		pass
	assert len(calls) == 1


def test_public_failure_is_bounded(monkeypatch):
	calls = []
	def run(args):
		calls.append(args)
		return 1, "", "unable to download video data: HTTP Error 403: Forbidden"
	monkeypatch.setattr(downloader, "_run_ytdlp_module", run)
	monkeypatch.setattr(downloader, "log", lambda message: None)
	assert downloader._run_ytdlp_detail([downloader.INTERNAL_YTDLP, "--cookies-from-browser", "firefox", "url"])[0] == 1
	assert len(calls) == 2
	assert "firefox" not in calls[1]


@pytest.mark.parametrize("error", [
	"ERROR: unable to download video data: HTTP Error 403: Forbidden",
	"Sign in to confirm you're not a bot",
	"Sign in to confirm your age",
	"signature solving failed",
])
def test_non_rate_errors_do_not_trigger_throttle_mode(error):
	detail = downloader._summarize_tool_output(error, "", using_cookies=True)
	assert downloader.detect_youtube_risk(detail) is None


def test_actual_rate_limit_is_actionable():
	detail = downloader._summarize_tool_output("HTTP Error 429: Too many requests", "")
	assert "wait" in detail
	assert downloader.detect_youtube_risk(detail)


def test_failed_fallback_reports_public_error(monkeypatch):
	responses = iter([
		(1, "", "unable to download video data: HTTP Error 403: Forbidden"),
		(1, "", "HTTP Error 429: Too many requests"),
	])
	monkeypatch.setattr(downloader, "_run_ytdlp_module", lambda args: next(responses))
	monkeypatch.setattr(downloader, "log", lambda message: None)
	rc, detail = downloader._run_ytdlp_detail([downloader.INTERNAL_YTDLP, "--cookies=x", "url"])
	assert rc == 1
	assert "automatic retry without cookies also failed" in detail
	assert "429" in detail
	assert downloader.detect_youtube_risk(detail)


def test_notices_delivered_immediately_and_handler_restored(monkeypatch):
	monkeypatch.setattr(downloader, "log", lambda message: None)
	messages = []
	with pytest.raises(RuntimeError):
		with downloader.download_notice_handler(messages.append):
			downloader._download_notice("Retrying")
			assert messages == ["Retrying"]
			raise RuntimeError("test")
	downloader._download_notice("After")
	assert messages == ["Retrying"]
	downloader.take_download_notices()


def test_huge_batch_warning_does_not_claim_detected_rate_limit():
	profile = downloader.youtube_batch_mitigation(600, using_cookies=True)
	assert profile.active
	assert profile.reason == "large playlist size"
	assert "precaution" in profile.warning
