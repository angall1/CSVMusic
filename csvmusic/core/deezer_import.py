# tabs only
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests


class DeezerImportError(Exception):
	pass


@dataclass
class DeezerSource:
	id: str
	name: str
	tracks: list[dict]
	total_count: int | None = None
	source_type: str = "playlist"
	warning: str | None = None


def fetch_deezer_source(value: str, *, timeout: int = 20, session: requests.Session | None = None) -> DeezerSource:
	client = session or requests.Session()
	text = (value or "").strip()
	if urlparse(text).netloc.lower().removeprefix("www.") == "deezer.page.link":
		try:
			response = client.get(text, timeout=timeout)
			text = response.url
		except requests.RequestException as exc:
			raise DeezerImportError("Could not resolve this Deezer sharing link.") from exc
	source_type, source_id = parse_deezer_source(text)
	base_url = f"https://api.deezer.com/{source_type}/{source_id}"
	data = _get_json(client, base_url, timeout)
	if data.get("error"):
		raise DeezerImportError("Could not find Deezer playlist or album. Is it public?")
	name = _text(data.get("title")) or f"Deezer {source_type.title()}"
	page = data.get("tracks") if isinstance(data.get("tracks"), dict) else {}
	items: list[Any] = list(page.get("data") or [])
	next_url = _text(page.get("next"))
	while next_url:
		next_page = _get_json(client, next_url, timeout)
		items.extend(next_page.get("data") or [])
		next_url = _text(next_page.get("next"))
	tracks = _tracks_from_items(items, name)
	if not tracks:
		raise DeezerImportError("Deezer loaded the source, but no playable tracks were found.")
	total_count = _integer(page.get("total")) or len(items)
	warning = None
	if len(tracks) < total_count:
		warning = f"Deezer returned {len(tracks)} of {total_count} tracks. Some tracks may be unavailable in your region."
	return DeezerSource(source_id, name, tracks, total_count, source_type, warning)


def parse_deezer_source(value: str) -> tuple[str, str]:
	text = (value or "").strip()
	parsed = urlparse(text)
	host = parsed.netloc.lower().removeprefix("www.")
	if host not in ("deezer.com", "deezer.page.link"):
		raise DeezerImportError("Paste a Deezer playlist or album link.")
	match = re.search(r"/(playlist|album)/(\d+)", parsed.path, re.I)
	if not match:
		raise DeezerImportError("This Deezer link does not identify a playlist or album.")
	return match.group(1).lower(), match.group(2)


def _get_json(client: requests.Session, url: str, timeout: int) -> dict[str, Any]:
	try:
		response = client.get(url, timeout=timeout)
		response.raise_for_status()
		data = response.json()
	except requests.RequestException as exc:
		raise DeezerImportError("Could not reach Deezer. Check your connection and try again.") from exc
	except ValueError as exc:
		raise DeezerImportError("Deezer returned data in an unexpected format.") from exc
	return data if isinstance(data, dict) else {}


def _tracks_from_items(items: list[Any], playlist_name: str) -> list[dict]:
	tracks: list[dict] = []
	for item in items:
		if not isinstance(item, dict):
			continue
		title = _text(item.get("title"))
		artist = item.get("artist") if isinstance(item.get("artist"), dict) else {}
		album = item.get("album") if isinstance(item.get("album"), dict) else {}
		if not title:
			continue
		tracks.append({
			"title": title,
			"artists": _text(artist.get("name")) or "Unknown Artist",
			"album": _text(album.get("title")),
			"playlist": playlist_name,
			"isrc": _text(item.get("isrc")) or None,
			"sp_id": str(item.get("id") or "") or None,
			"duration_ms": (_integer(item.get("duration")) or 0) * 1000,
			"year": None,
			"cover_url": _text(album.get("cover_xl") or album.get("cover_big")) or None,
			"track_no": len(tracks) + 1,
			"disc_no": _integer(item.get("disk_number")) or 1,
		})
	return tracks


def _integer(value: Any) -> int | None:
	try:
		return int(value)
	except Exception:
		return None


def _text(value: Any) -> str:
	return re.sub(r"\s+", " ", str(value or "")).strip()
