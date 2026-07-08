# tabs only
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

from ytmusicapi import YTMusic


class YouTubeMusicImportError(Exception):
	pass


@dataclass
class YouTubeMusicSource:
	id: str
	name: str
	tracks: list[dict]
	total_count: int | None = None
	source_type: str = "youtube_music"
	warning: str | None = None


def fetch_youtube_music_source(value: str, *, limit: int | None = None) -> YouTubeMusicSource:
	playlist_id = parse_youtube_playlist_id(value)
	try:
		playlist = YTMusic().get_playlist(playlist_id, limit=limit)
	except Exception as exc:
		raise YouTubeMusicImportError("Could not load YouTube Music playlist. Is it public?") from exc
	if not isinstance(playlist, dict):
		raise YouTubeMusicImportError("YouTube Music returned playlist data in an unexpected format.")
	name = _clean_text(playlist.get("title")) or "YouTube Music Playlist"
	raw_tracks = playlist.get("tracks") if isinstance(playlist.get("tracks"), list) else []
	total_count = _safe_int(playlist.get("trackCount"))
	tracks = _tracks_from_playlist(raw_tracks, name)
	if not tracks:
		raise YouTubeMusicImportError("YouTube Music loaded the playlist, but no playable tracks were found.")
	warning = None
	if total_count and len(tracks) < total_count:
		warning = (
			f"YouTube Music only exposed {len(tracks)} of {total_count} playlist tracks. "
			"Try making the playlist public or exporting it as CSV."
		)
	return YouTubeMusicSource(id=playlist_id, name=name, tracks=tracks, total_count=total_count, warning=warning)


def parse_youtube_playlist_id(value: str) -> str:
	text = (value or "").strip()
	if not text:
		raise YouTubeMusicImportError("Paste a YouTube Music playlist link first.")
	if re.fullmatch(r"PL[\w-]+|OLAK5uy_[\w-]+|RDCLAK5uy_[\w-]+|VL[\w-]+", text):
		return text[2:] if text.startswith("VL") else text
	parsed = urlparse(text)
	host = parsed.netloc.lower()
	if host not in ("music.youtube.com", "www.youtube.com", "youtube.com", "youtu.be"):
		raise YouTubeMusicImportError("Paste a YouTube Music or YouTube playlist link.")
	query = parse_qs(parsed.query)
	playlist_id = (query.get("list") or [""])[0].strip()
	if not playlist_id:
		raise YouTubeMusicImportError("This YouTube Music link does not contain a playlist ID.")
	if playlist_id.startswith("VL"):
		playlist_id = playlist_id[2:]
	return playlist_id


def _tracks_from_playlist(items: list[Any], playlist_name: str) -> list[dict]:
	out: list[dict] = []
	seen: set[str] = set()
	for item in items:
		if not isinstance(item, dict):
			continue
		video_id = _clean_text(item.get("videoId"))
		if video_id and video_id in seen:
			continue
		title = _clean_text(item.get("title"))
		artists = _artists_text(item)
		if not artists:
			artists, title = _split_video_title(title, _clean_text(item.get("author") or item.get("channel")))
		if not title or not artists:
			continue
		if video_id:
			seen.add(video_id)
		out.append({
			"title": title,
			"artists": artists,
			"album": _album_text(item),
			"playlist": playlist_name,
			"isrc": None,
			"sp_id": video_id or None,
			"duration_ms": (_safe_int(item.get("duration_seconds")) or 0) * 1000,
			"year": None,
			"cover_url": _cover_url(item),
			"track_no": len(out) + 1,
			"disc_no": 1,
		})
	return out


def _artists_text(item: dict[str, Any]) -> str:
	artists = item.get("artists")
	if isinstance(artists, list):
		names = [_clean_text(a.get("name")) for a in artists if isinstance(a, dict)]
		return ", ".join([name for name in names if name])
	return ""


def _album_text(item: dict[str, Any]) -> str:
	album = item.get("album")
	if isinstance(album, dict):
		return _clean_text(album.get("name"))
	return ""


def _cover_url(item: dict[str, Any]) -> str | None:
	thumbs = item.get("thumbnails")
	if not isinstance(thumbs, list):
		return None
	best = None
	best_size = -1
	for thumb in thumbs:
		if not isinstance(thumb, dict):
			continue
		url = _clean_text(thumb.get("url"))
		size = _safe_int(thumb.get("width")) or _safe_int(thumb.get("height")) or 0
		if url and size > best_size:
			best = url
			best_size = size
	return best


def _split_video_title(title: str, uploader: str) -> tuple[str, str]:
	cleaned = re.sub(r"\s*\((official|lyrics?|audio|video|visualizer|music video|lyric video)[^)]*\)\s*", " ", title, flags=re.I)
	cleaned = re.sub(r"\s*\[(official|lyrics?|audio|video|visualizer|music video|lyric video)[^]]*\]\s*", " ", cleaned, flags=re.I)
	cleaned = re.sub(r"\s+", " ", cleaned).strip(" -")
	for sep in (" - ", " – ", " — "):
		if sep in cleaned:
			left, right = cleaned.split(sep, 1)
			if left.strip() and right.strip():
				return left.strip(), right.strip()
	return (uploader, cleaned) if uploader else ("Unknown Artist", cleaned)


def _safe_int(value: Any) -> int | None:
	try:
		return int(value)
	except Exception:
		return None


def _clean_text(value: Any) -> str:
	return re.sub(r"\s+", " ", str(value or "")).strip()
