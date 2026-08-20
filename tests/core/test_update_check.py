import datetime

from csvmusic.core import update_check


class FakeResponse:
	def __init__(self, payload: dict):
		self.payload = payload

	def raise_for_status(self) -> None:
		pass

	def json(self) -> dict:
		return self.payload


def test_parse_release_version_accepts_github_tag():
	assert update_check.parse_release_version("v1.6.4") == (1, 6, 4)
	assert update_check.parse_release_version("1.7.0") == (1, 7, 0)
	assert update_check.parse_release_version("nightly") is None


def test_update_check_is_due_once_per_day():
	now = datetime.datetime(2026, 8, 20, 12, tzinfo=datetime.timezone.utc)

	assert not update_check.should_check_for_updates("2026-08-20T00:00:01+00:00", now=now)
	assert update_check.should_check_for_updates("2026-08-19T11:59:59+00:00", now=now)
	assert update_check.should_check_for_updates("invalid", now=now)


def test_fetch_available_update_returns_newer_stable_release(monkeypatch):
	monkeypatch.setattr(update_check.requests, "get", lambda *_args, **_kwargs: FakeResponse({
		"tag_name": "v1.7.0",
		"html_url": "https://github.com/angall1/CSVMusic/releases/tag/v1.7.0",
		"draft": False,
		"prerelease": False,
	}))

	result = update_check.fetch_available_update("1.6.4")

	assert result == update_check.UpdateInfo(
		version="1.7.0",
		url="https://github.com/angall1/CSVMusic/releases/tag/v1.7.0",
	)


def test_fetch_available_update_ignores_current_or_sketchy_release(monkeypatch):
	monkeypatch.setattr(update_check.requests, "get", lambda *_args, **_kwargs: FakeResponse({
		"tag_name": "v1.6.4",
		"html_url": "https://github.com/angall1/CSVMusic/releases/tag/v1.6.4",
		"draft": False,
		"prerelease": False,
	}))
	assert update_check.fetch_available_update("1.6.4") is None

	monkeypatch.setattr(update_check.requests, "get", lambda *_args, **_kwargs: FakeResponse({
		"tag_name": "v9.9.9",
		"html_url": "https://example.com/not-csvmusic",
		"draft": False,
		"prerelease": False,
	}))
	assert update_check.fetch_available_update("1.6.4") is None
