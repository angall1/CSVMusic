# tabs only
from typing import Any

import requests

from csvmusic.core.spotify_import import (
	SpotifyImportError,
	SpotifyPlaylist,
	parse_spotify_source,
)


API_BASE_URL = "https://api.spotify.com/v1"


class SpotifyAPIError(SpotifyImportError):
	pass


def fetch_spotify_user_playlists(
	access_token: str,
	*,
	timeout: int = 20,
	session: requests.Session | None = None,
) -> list[dict]:
	"""Return every playlist owned or followed by the signed-in Spotify user."""
	token = (access_token or "").strip()
	if not token:
		raise SpotifyAPIError("A Spotify access token is required.")
	client = session or requests.Session()
	headers = {"Authorization": f"Bearer {token}"}
	playlists: list[dict] = []
	offset = 0
	limit = 50
	while True:
		page = _get_json(
			client,
			f"{API_BASE_URL}/me/playlists",
			headers,
			timeout,
			params={"limit": limit, "offset": offset},
		)
		items = page.get("items")
		if not isinstance(items, list):
			raise SpotifyAPIError("Spotify returned your playlists in an unexpected format.")
		for item in items:
			playlist = _user_playlist(item)
			if playlist is not None:
				playlists.append(playlist)
		offset += len(items)
		if not items or not page.get("next"):
			break
	return playlists


def fetch_spotify_playlist_api(
	value: str,
	access_token: str,
	*,
	timeout: int = 20,
	session: requests.Session | None = None,
) -> SpotifyPlaylist:
	"""Load a Spotify playlist and all of its track metadata through Web API."""
	source = parse_spotify_source(value, expected_type="playlist")
	token = (access_token or "").strip()
	if not token:
		raise SpotifyAPIError("A Spotify access token is required.")
	client = session or requests.Session()
	headers = {"Authorization": f"Bearer {token}"}
	playlist_data = _get_json(
		client,
		f"{API_BASE_URL}/playlists/{source.id}",
		headers,
		timeout,
		params={"fields": "id,name,tracks.total"},
	)
	name = _text(playlist_data.get("name")) or "Spotify Playlist"
	total = _integer((playlist_data.get("tracks") or {}).get("total"))
	tracks: list[dict] = []
	offset = 0
	limit = 50
	while total is None or offset < total:
		page = _get_json(
			client,
			f"{API_BASE_URL}/playlists/{source.id}/items",
			headers,
			timeout,
			params={"limit": limit, "offset": offset},
		)
		items = page.get("items")
		if not isinstance(items, list):
			raise SpotifyAPIError("Spotify returned playlist tracks in an unexpected format.")
		for item in items:
			track = _track_from_item(item, name, len(tracks) + 1)
			if track is not None:
				tracks.append(track)
		page_total = _integer(page.get("total"))
		if page_total is not None:
			total = page_total
		offset += len(items)
		if not items or not page.get("next"):
			break
	if not tracks:
		raise SpotifyAPIError("Spotify loaded the playlist, but no playable tracks were found.")
	return SpotifyPlaylist(
		id=source.id,
		name=name,
		tracks=tracks,
		total_count=total,
		source_type="playlist",
	)


def _get_json(client: requests.Session, url: str, headers: dict[str, str], timeout: int, *, params: dict[str, Any]) -> dict:
	try:
		response = client.get(url, headers=headers, params=params, timeout=timeout)
	except requests.Timeout as exc:
		raise SpotifyAPIError("Spotify took too long to respond.") from exc
	except requests.RequestException as exc:
		raise SpotifyAPIError(f"Could not reach Spotify: {exc}") from exc
	if response.status_code == 401:
		raise SpotifyAPIError("Spotify rejected the access token. Sign in again and retry.")
	if response.status_code == 403:
		raise SpotifyAPIError("Spotify denied access to this playlist. The signed-in user may need to own or collaborate on it.")
	if response.status_code == 429:
		retry_after = response.headers.get("Retry-After")
		suffix = f" Retry after {retry_after} seconds." if retry_after else ""
		raise SpotifyAPIError(f"Spotify's API rate limit was reached.{suffix}")
	if response.status_code == 404:
		raise SpotifyAPIError("Spotify could not find this playlist.")
	if response.status_code >= 400:
		raise SpotifyAPIError(f"Spotify API returned HTTP {response.status_code}.")
	try:
		data = response.json()
	except ValueError as exc:
		raise SpotifyAPIError("Spotify returned invalid JSON.") from exc
	if not isinstance(data, dict):
		raise SpotifyAPIError("Spotify returned an unexpected response.")
	return data


def _track_from_item(item: Any, playlist_name: str, position: int) -> dict | None:
	if not isinstance(item, dict):
		return None
	data = item.get("item") or item.get("track")
	if not isinstance(data, dict) or data.get("type") not in (None, "track"):
		return None
	title = _text(data.get("name"))
	artists_data = data.get("artists") or []
	artists = ", ".join(
		name for name in (_text(artist.get("name")) for artist in artists_data if isinstance(artist, dict)) if name
	)
	if not title or not artists:
		return None
	album = data.get("album") if isinstance(data.get("album"), dict) else {}
	images = album.get("images") if isinstance(album.get("images"), list) else []
	cover_url = next((_text(image.get("url")) for image in images if isinstance(image, dict) and image.get("url")), None)
	external_ids = data.get("external_ids") if isinstance(data.get("external_ids"), dict) else {}
	release_date = _text(album.get("release_date"))
	return {
		"title": title,
		"artists": artists,
		"album": _text(album.get("name")),
		"playlist": playlist_name,
		"isrc": _text(external_ids.get("isrc")) or None,
		"sp_id": _text(data.get("id")) or None,
		"duration_ms": _integer(data.get("duration_ms")) or 0,
		"year": int(release_date[:4]) if release_date and release_date[:4].isdigit() else None,
		"cover_url": cover_url,
		"track_no": _integer(data.get("track_number")) or position,
		"disc_no": _integer(data.get("disc_number")) or 1,
	}


def _user_playlist(item: Any) -> dict | None:
	if not isinstance(item, dict):
		return None
	playlist_id = _text(item.get("id"))
	name = _text(item.get("name"))
	if not playlist_id or not name:
		return None
	owner_data = item.get("owner") if isinstance(item.get("owner"), dict) else {}
	count_data = item.get("items") if isinstance(item.get("items"), dict) else item.get("tracks")
	count_data = count_data if isinstance(count_data, dict) else {}
	external_urls = item.get("external_urls") if isinstance(item.get("external_urls"), dict) else {}
	return {
		"id": playlist_id,
		"name": name,
		"owner": _text(owner_data.get("display_name") or owner_data.get("id")) or "Unknown",
		"total": _integer(count_data.get("total")) or 0,
		"public": item.get("public"),
		"collaborative": bool(item.get("collaborative")),
		"url": _text(external_urls.get("spotify")) or f"https://open.spotify.com/playlist/{playlist_id}",
	}


def _text(value: Any) -> str:
	return str(value).strip() if value is not None else ""


def _integer(value: Any) -> int | None:
	try:
		return int(value)
	except (TypeError, ValueError):
		return None
