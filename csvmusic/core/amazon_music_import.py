# tabs only
import html
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests


class AmazonMusicImportError(Exception):
	pass


@dataclass
class AmazonMusicSource:
	id: str
	name: str
	tracks: list[dict]
	total_count: int | None = None
	source_type: str = "playlist"
	warning: str | None = None


def fetch_amazon_music_source(value: str, *, timeout: int = 20, session: requests.Session | None = None) -> AmazonMusicSource:
	url, source_type, source_id = parse_amazon_music_source(value)
	client = session or requests.Session()
	try:
		response = client.get(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"}, timeout=timeout)
	except requests.RequestException as exc:
		raise AmazonMusicImportError("Could not reach Amazon Music. Check your connection and try again.") from exc
	if response.status_code in (401, 403, 404):
		raise AmazonMusicImportError("Could not find Amazon Music playlist or album. Is it public?")
	if response.status_code >= 400:
		raise AmazonMusicImportError(f"Amazon Music returned HTTP {response.status_code}. Try again later.")
	return parse_amazon_music_page(response.content.decode("utf-8", errors="replace"), source_id, source_type)


def parse_amazon_music_source(value: str) -> tuple[str, str, str]:
	text = (value or "").strip()
	parsed = urlparse(text)
	host = parsed.netloc.lower()
	if "music.amazon." not in host:
		raise AmazonMusicImportError("Paste an Amazon Music playlist or album link.")
	match = re.search(r"/(playlists|albums)/([A-Za-z0-9]+)", parsed.path, re.I)
	if not match:
		raise AmazonMusicImportError("This Amazon Music link does not identify a playlist or album.")
	return text, "playlist" if match.group(1).lower() == "playlists" else "album", match.group(2)


def parse_amazon_music_page(page: str, source_id: str, source_type: str) -> AmazonMusicSource:
	objects = _json_objects(page)
	name = ""
	tracks: list[dict] = []
	seen: set[str] = set()
	for root in objects:
		for item in _walk(root):
			if not name and isinstance(item, dict):
				name = _text(item.get("playlistName") or item.get("albumName"))
			track = _amazon_track(item, name or "Amazon Music")
			if not track:
				continue
			key = str(track.get("sp_id") or f"{track['artists']}:{track['title']}")
			if key in seen:
				continue
			seen.add(key)
			track["track_no"] = len(tracks) + 1
			tracks.append(track)
	if not tracks:
		raise AmazonMusicImportError(
			"Amazon Music did not expose tracks for this link. Is it public and available without signing in?"
		)
	name = name or f"Amazon Music {source_type.title()}"
	for track in tracks:
		track["playlist"] = name
	return AmazonMusicSource(source_id, name, tracks, len(tracks), source_type)


def _json_objects(page: str) -> list[Any]:
	out: list[Any] = []
	for match in re.finditer(r"<script[^>]*>(.*?)</script>", page or "", re.S | re.I):
		text = html.unescape(match.group(1).strip())
		candidates = [text]
		if "=" in text:
			candidates.append(text.split("=", 1)[1].strip().rstrip(";"))
		for candidate in candidates:
			try:
				out.append(json.loads(candidate))
				break
			except Exception:
				continue
	return out


def _walk(value: Any):
	if isinstance(value, dict):
		yield value
		for child in value.values():
			yield from _walk(child)
	elif isinstance(value, list):
		for child in value:
			yield from _walk(child)


def _amazon_track(item: Any, playlist_name: str) -> dict | None:
	if not isinstance(item, dict):
		return None
	title = _text(item.get("title") or item.get("trackName"))
	artist = item.get("artistName") or item.get("artist")
	if isinstance(artist, dict):
		artist = artist.get("name")
	artist = _text(artist)
	item_type = _text(item.get("type") or item.get("__typename")).lower()
	if not title or not artist or ("track" not in item_type and "song" not in item_type):
		return None
	return {
		"title": title,
		"artists": artist,
		"album": _text(item.get("albumName")),
		"playlist": playlist_name,
		"isrc": _text(item.get("isrc")) or None,
		"sp_id": _text(item.get("id") or item.get("asin")) or None,
		"duration_ms": _duration_ms(item),
		"year": None,
		"cover_url": _text(item.get("imageUrl") or item.get("artwork")) or None,
		"track_no": 0,
		"disc_no": 1,
	}


def _duration_ms(item: dict[str, Any]) -> int:
	try:
		value = int(item.get("duration") or item.get("durationMs") or 0)
		return value if value > 10000 else value * 1000
	except Exception:
		return 0


def _text(value: Any) -> str:
	return re.sub(r"\s+", " ", str(value or "")).strip()
