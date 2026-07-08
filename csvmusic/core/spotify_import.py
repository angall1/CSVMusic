# tabs only
import base64
import html
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
import time

import requests


class SpotifyImportError(Exception):
	"""Base class for user-facing Spotify import errors."""


class SpotifyPlaylistNotFoundError(SpotifyImportError):
	pass


@dataclass
class SpotifyPlaylist:
	id: str
	name: str
	tracks: list[dict]
	total_count: int | None = None
	source_type: str = "playlist"
	warning: str | None = None


@dataclass
class SpotifySource:
	type: str
	id: str


_SPOTIFY_PLAYLIST_ID_RE = re.compile(r"^[A-Za-z0-9]{16,32}$")


def parse_spotify_playlist_id(value: str) -> str:
	source = parse_spotify_source(value, expected_type="playlist")
	return source.id


def parse_spotify_source(value: str, *, expected_type: str | None = None) -> SpotifySource:
	text = (value or "").strip()
	if not text:
		raise SpotifyImportError("Paste a Spotify playlist or album link first.")
	if text.startswith("spotify:"):
		parts = text.split(":")
		if len(parts) != 3 or parts[1] not in ("playlist", "album"):
			raise SpotifyImportError("Paste a Spotify playlist or album link.")
		source_type = parts[1]
		source_id = parts[2].strip()
	elif _SPOTIFY_PLAYLIST_ID_RE.match(text):
		source_type = expected_type or "playlist"
		source_id = text
	else:
		parsed = urlparse(text)
		host = parsed.netloc.lower()
		parts = [part for part in parsed.path.split("/") if part]
		if host not in ("open.spotify.com", "play.spotify.com"):
			raise SpotifyImportError("Paste a Spotify playlist or album link from open.spotify.com.")
		if len(parts) < 2 or parts[0].lower() not in ("playlist", "album"):
			raise SpotifyImportError("This Spotify link is not a playlist or album link.")
		source_type = parts[0].lower()
		source_id = parts[1].strip()
	if expected_type and source_type != expected_type:
		raise SpotifyImportError(f"This Spotify link is not a {expected_type} link.")
	if not _SPOTIFY_PLAYLIST_ID_RE.match(source_id):
		raise SpotifyImportError("This Spotify link does not contain a valid ID.")
	return SpotifySource(source_type, source_id)


def fetch_spotify_playlist(value: str, *, timeout: int = 20, session: requests.Session | None = None) -> SpotifyPlaylist:
	source = parse_spotify_source(value)
	url = f"https://open.spotify.com/{source.type}/{source.id}"
	client = session or requests.Session()
	last_result: SpotifyPlaylist | None = None
	for attempt in range(3):
		result = _fetch_spotify_source_page(client, url, source, timeout)
		embed_result = _fetch_embed_source_page(client, source, timeout)
		if embed_result and len(embed_result.tracks) > len(result.tracks):
			result = embed_result
		if not result.warning:
			return result
		last_result = result
		time.sleep(0.4 * (attempt + 1))
	return last_result if last_result is not None else _fetch_spotify_source_page(client, url, source, timeout)


def _fetch_spotify_source_page(client: requests.Session, url: str, source: SpotifySource, timeout: int) -> SpotifyPlaylist:
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
		raise SpotifyImportError("Spotify took too long to respond. Check your connection and try again.") from exc
	except requests.RequestException as exc:
		raise SpotifyImportError(f"Could not reach Spotify: {exc}") from exc
	if resp.status_code in (401, 403, 404):
		if source.type == "playlist":
			raise SpotifyPlaylistNotFoundError("Could not find playlist. Is it public?")
		raise SpotifyPlaylistNotFoundError("Could not find album. Is the link correct?")
	if resp.status_code >= 400:
		raise SpotifyImportError(f"Spotify returned HTTP {resp.status_code}. Try again later.")
	return parse_spotify_page(resp.content.decode("utf-8", errors="replace"), source)


def _fetch_embed_source_page(client: requests.Session, source: SpotifySource, timeout: int) -> SpotifyPlaylist | None:
	try:
		resp = client.get(
			f"https://open.spotify.com/embed/{source.type}/{source.id}",
			headers={
				"User-Agent": "Mozilla/5.0",
				"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
				"Accept-Language": "en-US,en;q=0.9",
			},
			timeout=timeout,
		)
	except requests.RequestException:
		return None
	if resp.status_code >= 400:
		return None
	try:
		return parse_spotify_embed_page(resp.content.decode("utf-8", errors="replace"), source)
	except SpotifyImportError:
		return None


def parse_spotify_playlist_page(html_text: str, playlist_id: str) -> SpotifyPlaylist:
	return parse_spotify_page(html_text, SpotifySource("playlist", playlist_id))


def parse_spotify_page(html_text: str, source: SpotifySource) -> SpotifyPlaylist:
	state = _extract_initial_state(html_text)
	if source.type == "album":
		return _parse_album_state(state, source.id)
	return _parse_playlist_state(state, source.id)


def parse_spotify_embed_page(html_text: str, source: SpotifySource) -> SpotifyPlaylist:
	data = _extract_next_data(html_text)
	entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity")
	if not isinstance(entity, dict):
		raise SpotifyImportError("Spotify embed did not return track data.")
	if entity.get("type") != source.type or entity.get("id") != source.id:
		raise SpotifyImportError("Spotify embed returned the wrong item.")
	name = _clean_text(entity.get("title") or entity.get("name")) or ("Spotify Album" if source.type == "album" else "Spotify Playlist")
	items = entity.get("trackList") if isinstance(entity.get("trackList"), list) else []
	tracks = _tracks_from_embed_items(items, name, album_name=name if source.type == "album" else None, cover_url=_embed_cover_url(entity))
	if not tracks:
		raise SpotifyImportError("Spotify embed loaded, but no playable tracks were found.")
	total_count = _safe_int(entity.get("trackCount") or entity.get("totalCount")) or len(tracks)
	warning = None
	if total_count and len(tracks) < total_count:
		label = "album" if source.type == "album" else "playlist"
		warning = (
			f"Spotify only exposed {len(tracks)} of {total_count} {label} tracks publicly. "
			"Export it as CSV for a complete import."
		)
	return SpotifyPlaylist(id=source.id, name=name, tracks=tracks, total_count=total_count, source_type=source.type, warning=warning)


def _parse_playlist_state(state: dict[str, Any], playlist_id: str) -> SpotifyPlaylist:
	playlist = _find_playlist_entity(state, playlist_id)
	if not playlist:
		raise SpotifyPlaylistNotFoundError("Could not find playlist. Is it public?")
	name = _clean_text(playlist.get("name")) or "Spotify Playlist"
	content = playlist.get("content") if isinstance(playlist.get("content"), dict) else {}
	items = content.get("items") if isinstance(content.get("items"), list) else []
	total_count = _safe_int(content.get("totalCount"))
	tracks = _tracks_from_items(items, name)
	if not tracks:
		raise SpotifyImportError("Spotify loaded the playlist, but no playable tracks were found.")
	warning = None
	if total_count and len(tracks) < total_count:
		warning = (
			f"Spotify only exposed {len(tracks)} of {total_count} playlist tracks publicly. "
			"Make sure the playlist is public, or export it as CSV for a complete import."
		)
	return SpotifyPlaylist(id=playlist_id, name=name, tracks=tracks, total_count=total_count, source_type="playlist", warning=warning)


def _parse_album_state(state: dict[str, Any], album_id: str) -> SpotifyPlaylist:
	album = _find_album_entity(state, album_id)
	if not album:
		raise SpotifyPlaylistNotFoundError("Could not find album. Is the link correct?")
	name = _clean_text(album.get("name")) or "Spotify Album"
	tracks_v2 = album.get("tracksV2") if isinstance(album.get("tracksV2"), dict) else {}
	items = tracks_v2.get("items") if isinstance(tracks_v2.get("items"), list) else []
	total_count = _safe_int(tracks_v2.get("totalCount"))
	tracks = _tracks_from_items(items, name, album_name=name, cover_url=_album_cover_url(album))
	if not tracks:
		raise SpotifyImportError("Spotify loaded the album, but no playable tracks were found.")
	warning = None
	if total_count and len(tracks) < total_count:
		warning = (
			f"Spotify only exposed {len(tracks)} of {total_count} album tracks publicly. "
			"Try a Spotify playlist link or CSV export for a complete import."
		)
	return SpotifyPlaylist(id=album_id, name=name, tracks=tracks, total_count=total_count, source_type="album", warning=warning)


def _extract_initial_state(html_text: str) -> dict[str, Any]:
	match = re.search(r'<script[^>]+id=["\']initialState["\'][^>]*>(.*?)</script>', html_text or "", re.S | re.I)
	if not match:
		raise SpotifyImportError("Spotify did not return playlist data. The page may require sign-in, or Spotify changed its page format.")
	raw = html.unescape(match.group(1).strip())
	try:
		decoded = base64.b64decode(raw).decode("utf-8", errors="replace")
		return json.loads(decoded)
	except Exception as exc:
		raise SpotifyImportError("Spotify returned playlist data in an unexpected format.") from exc


def _extract_next_data(html_text: str) -> dict[str, Any]:
	match = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html_text or "", re.S | re.I)
	if not match:
		raise SpotifyImportError("Spotify embed did not return playlist data.")
	try:
		return json.loads(html.unescape(match.group(1).strip()))
	except Exception as exc:
		raise SpotifyImportError("Spotify embed returned data in an unexpected format.") from exc


def _find_playlist_entity(state: dict[str, Any], playlist_id: str) -> dict[str, Any] | None:
	items = state.get("entities", {}).get("items", {})
	if not isinstance(items, dict):
		return None
	key = f"spotify:playlist:{playlist_id}"
	entity = items.get(key)
	if isinstance(entity, dict):
		return entity
	for value in items.values():
		if isinstance(value, dict) and value.get("__typename") == "Playlist" and value.get("id") == playlist_id:
			return value
	return None


def _find_album_entity(state: dict[str, Any], album_id: str) -> dict[str, Any] | None:
	items = state.get("entities", {}).get("items", {})
	if not isinstance(items, dict):
		return None
	key = f"spotify:album:{album_id}"
	entity = items.get(key)
	if isinstance(entity, dict):
		return entity
	for value in items.values():
		if isinstance(value, dict) and value.get("__typename") == "Album" and value.get("id") == album_id:
			return value
	return None


def _tracks_from_items(items: list[Any], playlist_name: str, *, album_name: str | None = None, cover_url: str | None = None) -> list[dict]:
	tracks: list[dict] = []
	seen: set[str] = set()
	for idx, item in enumerate(items, start=1):
		data = _track_data(item)
		if not data:
			continue
		title = _clean_text(data.get("name") or data.get("title"))
		if not title:
			continue
		artists = _artists_text(data)
		if not artists:
			continue
		sp_id = _spotify_id(data.get("uri") or data.get("id"))
		if sp_id and sp_id in seen:
			continue
		if sp_id:
			seen.add(sp_id)
		tracks.append({
			"title": title,
			"artists": artists,
			"album": _album_name(data) or album_name or "",
			"playlist": playlist_name,
			"isrc": _external_id(data, "isrc"),
			"sp_id": sp_id,
			"duration_ms": _duration_ms(data),
			"year": None,
			"cover_url": _cover_url(data) or cover_url,
			"track_no": _safe_int(data.get("trackNumber")) or idx,
			"disc_no": _safe_int(data.get("discNumber")) or 1,
		})
	return tracks


def _track_data(item: Any) -> dict[str, Any] | None:
	if not isinstance(item, dict):
		return None
	candidates = [
		item.get("itemV2", {}).get("data") if isinstance(item.get("itemV2"), dict) else None,
		item.get("item", {}).get("data") if isinstance(item.get("item"), dict) else None,
		item.get("track") if isinstance(item.get("track"), dict) else None,
		item.get("data") if isinstance(item.get("data"), dict) else None,
	]
	for candidate in candidates:
		if isinstance(candidate, dict) and candidate.get("__typename") in (None, "Track"):
			return candidate
	return None


def _tracks_from_embed_items(items: list[Any], playlist_name: str, *, album_name: str | None = None, cover_url: str | None = None) -> list[dict]:
	tracks: list[dict] = []
	seen: set[str] = set()
	for idx, item in enumerate(items, start=1):
		if not isinstance(item, dict) or item.get("entityType") != "track":
			continue
		title = _clean_text(item.get("title"))
		artists = _clean_text(item.get("subtitle")).replace("\u00a0", " ")
		sp_id = _spotify_id(item.get("uri"))
		if not title or not artists:
			continue
		if sp_id and sp_id in seen:
			continue
		if sp_id:
			seen.add(sp_id)
		tracks.append({
			"title": title,
			"artists": artists,
			"album": album_name or "",
			"playlist": playlist_name,
			"isrc": None,
			"sp_id": sp_id,
			"duration_ms": _safe_int(item.get("duration")) or 0,
			"year": None,
			"cover_url": cover_url,
			"track_no": idx,
			"disc_no": 1,
		})
	return tracks


def _artists_text(data: dict[str, Any]) -> str:
	artists = data.get("artists")
	names: list[str] = []
	if isinstance(artists, dict):
		for artist in artists.get("items") or []:
			if not isinstance(artist, dict):
				continue
			name = _clean_text(artist.get("profile", {}).get("name") if isinstance(artist.get("profile"), dict) else artist.get("name"))
			if name:
				names.append(name)
	elif isinstance(artists, list):
		for artist in artists:
			if isinstance(artist, dict):
				name = _clean_text(artist.get("name"))
				if name:
					names.append(name)
	return ", ".join(names)


def _album_name(data: dict[str, Any]) -> str:
	album = data.get("albumOfTrack") or data.get("album")
	if isinstance(album, dict):
		return _clean_text(album.get("name"))
	return ""


def _cover_url(data: dict[str, Any]) -> str | None:
	album = data.get("albumOfTrack") or data.get("album")
	cover = album.get("coverArt") if isinstance(album, dict) else None
	sources = cover.get("sources") if isinstance(cover, dict) else None
	if not isinstance(sources, list):
		return None
	best = None
	best_size = -1
	for source in sources:
		if not isinstance(source, dict):
			continue
		url = _clean_text(source.get("url"))
		if not url:
			continue
		size = _safe_int(source.get("width")) or _safe_int(source.get("height")) or 0
		if size > best_size:
			best = url
			best_size = size
	return best


def _album_cover_url(album: dict[str, Any]) -> str | None:
	cover = album.get("coverArt") if isinstance(album, dict) else None
	sources = cover.get("sources") if isinstance(cover, dict) else None
	if not isinstance(sources, list):
		return None
	return _best_source_url(sources)


def _embed_cover_url(entity: dict[str, Any]) -> str | None:
	cover = entity.get("coverArt") if isinstance(entity, dict) else None
	sources = cover.get("sources") if isinstance(cover, dict) else None
	if not isinstance(sources, list):
		return None
	return _best_source_url(sources)


def _best_source_url(sources: list[Any]) -> str | None:
	best = None
	best_size = -1
	for source in sources:
		if not isinstance(source, dict):
			continue
		url = _clean_text(source.get("url"))
		if not url:
			continue
		size = _safe_int(source.get("width")) or _safe_int(source.get("height")) or 0
		if size > best_size:
			best = url
			best_size = size
	return best


def _duration_ms(data: dict[str, Any]) -> int:
	for key in ("duration", "durationMs", "duration_ms"):
		value = data.get(key)
		if isinstance(value, dict):
			for nested in ("totalMilliseconds", "milliseconds", "ms"):
				ms = _safe_int(value.get(nested))
				if ms:
					return ms
		else:
			ms = _safe_int(value)
			if ms:
				return ms
	return 0


def _external_id(data: dict[str, Any], name: str) -> str | None:
	external = data.get("externalIds") or data.get("external_ids")
	if isinstance(external, dict):
		value = _clean_text(external.get(name) or external.get(name.upper()))
		return value or None
	return None


def _spotify_id(value: Any) -> str | None:
	text = _clean_text(value)
	if not text:
		return None
	if text.startswith("spotify:track:"):
		return text.rsplit(":", 1)[-1]
	return text if _SPOTIFY_PLAYLIST_ID_RE.match(text) else None


def _safe_int(value: Any) -> int | None:
	try:
		return int(value)
	except Exception:
		return None


def _clean_text(value: Any) -> str:
	return re.sub(r"\s+", " ", str(value or "")).strip()
