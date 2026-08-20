# tabs only
import datetime
import re
from dataclasses import dataclass

import requests


LATEST_RELEASE_URL = "https://api.github.com/repos/angall1/CSVMusic/releases/latest"
CHECK_INTERVAL = datetime.timedelta(days=1)


@dataclass(frozen=True)
class UpdateInfo:
	version: str
	url: str


def parse_release_version(value: str) -> tuple[int, int, int] | None:
	match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", (value or "").strip(), flags=re.IGNORECASE)
	if match is None:
		return None
	return tuple(int(part) for part in match.groups())


def should_check_for_updates(last_checked: str | None, *, now: datetime.datetime | None = None) -> bool:
	if not last_checked:
		return True
	try:
		checked_at = datetime.datetime.fromisoformat(last_checked.replace("Z", "+00:00"))
	except (TypeError, ValueError):
		return True
	if checked_at.tzinfo is None:
		checked_at = checked_at.replace(tzinfo=datetime.timezone.utc)
	current = now or datetime.datetime.now(datetime.timezone.utc)
	if current.tzinfo is None:
		current = current.replace(tzinfo=datetime.timezone.utc)
	return current - checked_at >= CHECK_INTERVAL


def update_check_timestamp() -> str:
	return datetime.datetime.now(datetime.timezone.utc).isoformat()


def fetch_available_update(current_version: str, *, timeout: float = 8.0) -> UpdateInfo | None:
	response = requests.get(
		LATEST_RELEASE_URL,
		headers={"Accept": "application/vnd.github+json", "User-Agent": f"CSVMusic/{current_version}"},
		timeout=timeout,
	)
	response.raise_for_status()
	payload = response.json()
	if payload.get("draft") or payload.get("prerelease"):
		return None
	latest_text = str(payload.get("tag_name") or "").strip()
	latest = parse_release_version(latest_text)
	current = parse_release_version(current_version)
	url = str(payload.get("html_url") or "").strip()
	if latest is None or current is None or latest <= current:
		return None
	if not url.startswith("https://github.com/angall1/CSVMusic/releases/"):
		return None
	return UpdateInfo(version=".".join(str(part) for part in latest), url=url)
