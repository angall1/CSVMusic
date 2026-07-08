# tabs only
import html
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests


class AppleMusicImportError(Exception):
	pass


@dataclass
class AppleMusicSource:
	id: str
	name: str
	tracks: list[dict]
	total_count: int | None = None
	source_type: str = "apple_music"
	warning: str | None = None


def fetch_apple_music_source(value: str, *, timeout: int = 20, session: requests.Session | None = None) -> AppleMusicSource:
	url = _validate_apple_music_url(value)
	client = session or requests.Session()
	try:
		resp = client.get(
			url,
			headers={
				"User-Agent": "Mozilla/5.0",
				"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
				"Accept-Language": "en-US,en;q=0.9",
			},
			timeout=timeout,
		)
	except requests.Timeout as exc:
		raise AppleMusicImportError("Apple Music took too long to respond. Check your connection and try again.") from exc
	except requests.RequestException as exc:
		raise AppleMusicImportError(f"Could not reach Apple Music: {exc}") from exc
	if resp.status_code in (401, 403, 404):
		raise AppleMusicImportError("Could not find Apple Music playlist or album. Is it public?")
	if resp.status_code >= 400:
		raise AppleMusicImportError(f"Apple Music returned HTTP {resp.status_code}. Try again later.")
	return parse_apple_music_page(resp.content.decode("utf-8", errors="replace"), url)


def parse_apple_music_page(html_text: str, url: str = "") -> AppleMusicSource:
	server = _extract_server_data(html_text)
	ld = _extract_ld_playlist(html_text)
	name = _clean_text(_find_header_title(server) or (ld or {}).get("name")) or "Apple Music"
	total_count = _safe_int((ld or {}).get("numTracks"))
	tracks = _tracks_from_server_data(server, name)
	if not tracks and ld:
		tracks = _tracks_from_ld(ld, name)
	if not tracks:
		raise AppleMusicImportError("Apple Music loaded the page, but no playable tracks were found.")
	warning = None
	if total_count and len(tracks) < total_count:
		warning = (
			f"Apple Music only exposed {len(tracks)} of {total_count} tracks publicly. "
			"Try CSV export for a complete import."
		)
	return AppleMusicSource(id=_apple_source_id(url), name=name, tracks=tracks, total_count=total_count, warning=warning)


def _validate_apple_music_url(value: str) -> str:
	text = (value or "").strip()
	if not text:
		raise AppleMusicImportError("Paste an Apple Music playlist or album link first.")
	parsed = urlparse(text)
	if parsed.netloc.lower() != "music.apple.com":
		raise AppleMusicImportError("Paste an Apple Music link from music.apple.com.")
	parts = [part.lower() for part in parsed.path.split("/") if part]
	if len(parts) < 3 or parts[1] not in ("playlist", "album"):
		raise AppleMusicImportError("This Apple Music link is not a playlist or album link.")
	return text


def _extract_server_data(html_text: str) -> dict[str, Any] | None:
	match = re.search(r'<script[^>]+id=["\']serialized-server-data["\'][^>]*>(.*?)</script>', html_text or "", re.S | re.I)
	if not match:
		return None
	try:
		return json.loads(html.unescape(match.group(1).strip()))
	except Exception as exc:
		raise AppleMusicImportError("Apple Music returned page data in an unexpected format.") from exc


def _extract_ld_playlist(html_text: str) -> dict[str, Any] | None:
	match = re.search(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html_text or "", re.S | re.I)
	if not match:
		return None
	try:
		obj = json.loads(html.unescape(match.group(1).strip()))
		return obj if isinstance(obj, dict) else None
	except Exception:
		return None


def _tracks_from_server_data(server: dict[str, Any] | None, playlist_name: str) -> list[dict]:
	if not server:
		return []
	out: list[dict] = []
	seen: set[str] = set()
	for item in _walk_dicts(server):
		content = item.get("contentDescriptor")
		if not isinstance(content, dict) or content.get("kind") != "song":
			continue
		title = _clean_text(item.get("title"))
		artists = _clean_text(item.get("artistName") or item.get("subtitle"))
		if not title or not artists:
			continue
		apple_id = _clean_text((content.get("identifiers") or {}).get("storeAdamID"))
		if apple_id and apple_id in seen:
			continue
		if apple_id:
			seen.add(apple_id)
		out.append(_track_dict(
			title=title,
			artists=artists,
			playlist_name=playlist_name,
			duration_ms=_safe_int(item.get("duration")) or 0,
			cover_url=_artwork_url(item.get("artwork")),
			track_no=len(out) + 1,
			source_id=apple_id or None,
		))
	return out


def _tracks_from_ld(ld: dict[str, Any], playlist_name: str) -> list[dict]:
	out: list[dict] = []
	for item in ld.get("track") or []:
		if not isinstance(item, dict):
			continue
		title = _clean_text(item.get("name"))
		if not title:
			continue
		audio = item.get("audio") if isinstance(item.get("audio"), dict) else {}
		out.append(_track_dict(
			title=title,
			artists="Unknown Artist",
			playlist_name=playlist_name,
			duration_ms=_duration_to_ms(item.get("duration") or audio.get("duration")),
			cover_url=_clean_text(audio.get("thumbnailUrl")) or None,
			track_no=len(out) + 1,
			source_id=_apple_source_id(item.get("url") or ""),
		))
	return out


def _track_dict(title: str, artists: str, playlist_name: str, duration_ms: int, cover_url: str | None, track_no: int, source_id: str | None) -> dict:
	return {
		"title": title,
		"artists": artists,
		"album": "",
		"playlist": playlist_name,
		"isrc": None,
		"sp_id": source_id,
		"duration_ms": duration_ms,
		"year": None,
		"cover_url": cover_url,
		"track_no": track_no,
		"disc_no": 1,
	}


def _find_header_title(server: dict[str, Any] | None) -> str | None:
	if not server:
		return None
	for item in _walk_dicts(server):
		content = item.get("contentDescriptor")
		if isinstance(content, dict) and content.get("kind") in ("playlist", "album") and item.get("title"):
			return _clean_text(item.get("title"))
	return None


def _walk_dicts(value: Any):
	if isinstance(value, dict):
		yield value
		for child in value.values():
			yield from _walk_dicts(child)
	elif isinstance(value, list):
		for child in value:
			yield from _walk_dicts(child)


def _artwork_url(value: Any) -> str | None:
	if not isinstance(value, dict):
		return None
	dct = value.get("dictionary") if isinstance(value.get("dictionary"), dict) else value
	url = _clean_text(dct.get("url"))
	if not url:
		return None
	return url.replace("{w}", "1200").replace("{h}", "1200").replace("{f}", "jpg")


def _duration_to_ms(value: Any) -> int:
	text = _clean_text(value)
	match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", text)
	if not match:
		return 0
	hours = int(match.group(1) or 0)
	mins = int(match.group(2) or 0)
	secs = int(match.group(3) or 0)
	return ((hours * 3600) + (mins * 60) + secs) * 1000


def _apple_source_id(value: str) -> str:
	text = _clean_text(value)
	match = re.search(r"(?:/|i=)(\d{5,})(?:\D|$)", text)
	return match.group(1) if match else text


def _safe_int(value: Any) -> int | None:
	try:
		return int(value)
	except Exception:
		return None


def _clean_text(value: Any) -> str:
	return re.sub(r"\s+", " ", str(value or "")).strip()
