# tabs only
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

from yt_dlp import YoutubeDL

from csvmusic.core.import_warnings import incomplete_import_warning


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
	tracks = _tracks_from_entries(entries, name, infer_youtube_order=platform == "YouTube")
	if not tracks:
		raise WebPlaylistImportError(f"{platform} loaded the playlist, but no playable tracks were found.")
	total_count = _integer(info.get("playlist_count") or info.get("n_entries"))
	warning = None
	if total_count and len(tracks) < total_count:
		warning = incomplete_import_warning(platform, len(tracks), total_count)
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


def _tracks_from_entries(entries: list[Any], playlist_name: str, *, infer_youtube_order: bool = False) -> list[dict]:
	tracks: list[dict] = []
	seen: set[str] = set()
	channel_rules = _infer_channel_title_rules(entries) if infer_youtube_order else {}
	for entry in entries:
		if not isinstance(entry, dict):
			continue
		entry_id = _text(entry.get("id") or entry.get("url"))
		if entry_id and entry_id in seen:
			continue
		title = _text(entry.get("track") or entry.get("title"))
		artist = _text(entry.get("artist") or entry.get("creator") or entry.get("uploader") or entry.get("channel"))
		if infer_youtube_order:
			artist, title = _split_youtube_title(title, artist, channel_rules.get(_channel_key(artist)))
		else:
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


def _split_youtube_title(title: str, uploader: str, rule: str | None) -> tuple[str, str]:
	parts = _title_parts(title)
	if not parts:
		return uploader, _clean_title(title)
	left, right = parts
	left_matches = _channel_matches_artist(uploader, left)
	right_matches = _channel_matches_artist(uploader, right)
	if left_matches and not right_matches:
		return left, right
	if right_matches and not left_matches:
		return right, left
	if rule == "artist-title":
		return left, right
	if rule == "title-artist":
		return right, left
	return uploader, _clean_title(title)


def _infer_channel_title_rules(entries: list[Any]) -> dict[str, str]:
	votes: dict[str, dict[str, int]] = {}
	for entry in entries:
		if not isinstance(entry, dict):
			continue
		uploader = _text(entry.get("artist") or entry.get("creator") or entry.get("uploader") or entry.get("channel"))
		parts = _title_parts(_text(entry.get("track") or entry.get("title")))
		if not uploader or not parts:
			continue
		left, right = parts
		left_matches = _channel_matches_artist(uploader, left)
		right_matches = _channel_matches_artist(uploader, right)
		if left_matches == right_matches:
			continue
		counts = votes.setdefault(_channel_key(uploader), {"artist-title": 0, "title-artist": 0})
		counts["artist-title" if left_matches else "title-artist"] += 1
	rules: dict[str, str] = {}
	for channel, counts in votes.items():
		total = counts["artist-title"] + counts["title-artist"]
		winner = "artist-title" if counts["artist-title"] > counts["title-artist"] else "title-artist"
		if total >= 2 and counts[winner] / total >= 0.8:
			rules[channel] = winner
	return rules


def _clean_title(title: str) -> str:
	cleaned = re.sub(r"\s*[\[(](official|lyrics?|audio|video|visualizer|music video)[^)\]]*[\])]\s*", " ", title, flags=re.I)
	return re.sub(r"\s+", " ", cleaned).strip(" -")


def _title_parts(title: str) -> tuple[str, str] | None:
	cleaned = _clean_title(title)
	for separator in (" - ", " \u2013 ", " \u2014 "):
		if separator in cleaned:
			left, right = cleaned.split(separator, 1)
			if left.strip() and right.strip():
				return left.strip(), right.strip()
	return None


def _channel_matches_artist(channel: str, artist: str) -> bool:
	channel_key = _channel_key(channel)
	artist_key = _channel_key(artist)
	if not channel_key or not artist_key:
		return False
	return channel_key in {artist_key, f"{artist_key}music", f"{artist_key}official", f"official{artist_key}"}


def _channel_key(value: str) -> str:
	return re.sub(r"[^a-z0-9]", "", value.casefold())


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
