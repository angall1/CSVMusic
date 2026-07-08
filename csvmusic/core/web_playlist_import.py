# tabs only
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

from yt_dlp import YoutubeDL


class WebPlaylistImportError(Exception):
	pass


@dataclass
class WebPlaylistSource:
	id: str
	name: str
	tracks: list[dict]
	total_count: int | None = None
	source_type: str = "playlist"
	warning: str | None = None


def fetch_web_playlist(value: str, platform: str) -> WebPlaylistSource:
	url = _validate_url(value, platform)
	options = {
		"quiet": True,
		"no_warnings": True,
		"skip_download": True,
		"extract_flat": "in_playlist",
		"ignoreerrors": True,
	}
	try:
		with YoutubeDL(options) as ydl:
			info = ydl.extract_info(url, download=False)
	except Exception as exc:
		raise WebPlaylistImportError(f"Could not load {platform} playlist. Is it public?") from exc
	if not isinstance(info, dict):
		raise WebPlaylistImportError(f"Could not find {platform} playlist. Is it public?")
	entries = info.get("entries")
	if not isinstance(entries, list):
		raise WebPlaylistImportError(f"This {platform} link is not a playlist.")
	name = _text(info.get("title")) or f"{platform} Playlist"
	tracks = _tracks_from_entries(entries, name)
	if not tracks:
		raise WebPlaylistImportError(f"{platform} loaded the playlist, but no playable tracks were found.")
	total_count = _integer(info.get("playlist_count") or info.get("n_entries"))
	warning = None
	if total_count and len(tracks) < total_count:
		warning = (
			f"{platform} only exposed {len(tracks)} of {total_count} playlist tracks. "
			"Make sure the playlist and all its tracks are public."
		)
	return WebPlaylistSource(
		id=_text(info.get("id")) or _source_id(url),
		name=name,
		tracks=tracks,
		total_count=total_count or len(entries),
		warning=warning,
	)


def _validate_url(value: str, platform: str) -> str:
	text = (value or "").strip()
	if not text:
		raise WebPlaylistImportError(f"Paste a {platform} playlist link first.")
	parsed = urlparse(text)
	host = parsed.netloc.lower().removeprefix("www.")
	if platform == "SoundCloud":
		if host != "soundcloud.com" or "/sets/" not in parsed.path.lower():
			raise WebPlaylistImportError("Paste a SoundCloud playlist or set link.")
	elif platform == "YouTube":
		if host not in ("youtube.com", "youtu.be") or not parse_qs(parsed.query).get("list"):
			raise WebPlaylistImportError("Paste a regular YouTube playlist link containing a playlist ID.")
	return text


def _tracks_from_entries(entries: list[Any], playlist_name: str) -> list[dict]:
	tracks: list[dict] = []
	seen: set[str] = set()
	for entry in entries:
		if not isinstance(entry, dict):
			continue
		entry_id = _text(entry.get("id") or entry.get("url"))
		if entry_id and entry_id in seen:
			continue
		title = _text(entry.get("track") or entry.get("title"))
		artist = _text(entry.get("artist") or entry.get("creator") or entry.get("uploader") or entry.get("channel"))
		artist, title = _split_title(title, artist)
		if not title:
			continue
		if entry_id:
			seen.add(entry_id)
		tracks.append({
			"title": title,
			"artists": artist or "Unknown Artist",
			"album": _text(entry.get("album")),
			"playlist": playlist_name,
			"isrc": _text(entry.get("isrc")) or None,
			"sp_id": entry_id or None,
			"duration_ms": _duration_ms(entry.get("duration")),
			"year": _integer(entry.get("release_year")),
			"cover_url": _thumbnail(entry),
			"track_no": len(tracks) + 1,
			"disc_no": 1,
		})
	return tracks


def _split_title(title: str, fallback_artist: str) -> tuple[str, str]:
	cleaned = re.sub(r"\s*[\[(](official|lyrics?|audio|video|visualizer|music video)[^)\]]*[\])]\s*", " ", title, flags=re.I)
	cleaned = re.sub(r"\s+", " ", cleaned).strip(" -")
	if not fallback_artist and " - " in cleaned:
		artist, track = cleaned.split(" - ", 1)
		return artist.strip(), track.strip()
	return fallback_artist, cleaned


def _thumbnail(entry: dict[str, Any]) -> str | None:
	value = _text(entry.get("thumbnail"))
	if value:
		return value
	thumbs = entry.get("thumbnails")
	if isinstance(thumbs, list):
		for thumb in reversed(thumbs):
			if isinstance(thumb, dict) and _text(thumb.get("url")):
				return _text(thumb.get("url"))
	return None


def _source_id(url: str) -> str:
	parsed = urlparse(url)
	return (parse_qs(parsed.query).get("list") or [parsed.path.rstrip("/").split("/")[-1]])[0]


def _integer(value: Any) -> int | None:
	try:
		return int(value)
	except Exception:
		return None


def _duration_ms(value: Any) -> int:
	try:
		return int(float(value or 0) * 1000)
	except Exception:
		return 0


def _text(value: Any) -> str:
	return re.sub(r"\s+", " ", str(value or "")).strip()
