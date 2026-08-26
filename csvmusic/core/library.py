# tabs only
import csv
import datetime
import json
import pathlib
import tempfile
from typing import Any

from csvmusic.core.spotify_import import parse_spotify_source
from csvmusic.core.track_output import expected_track_path
from csvmusic.core.youtube_music_import import parse_youtube_playlist_id
from csvmusic.core.apple_music_import import parse_apple_music_source_url


LIBRARY_VERSION = 1


def new_library(name: str = "My Library", output_dir: str = "") -> dict:
	now = _now()
	return {
		"version": LIBRARY_VERSION,
		"name": (name or "My Library").strip(),
		"output_dir": str(output_dir or ""),
		"created_at": now,
		"updated_at": now,
		"playlists": [],
	}


def load_library(path: str | pathlib.Path) -> dict:
	with pathlib.Path(path).open("r", encoding="utf-8") as handle:
		data = json.load(handle)
	if not isinstance(data, dict) or data.get("version") != LIBRARY_VERSION:
		raise ValueError("This is not a supported CSVMusic library file.")
	if not isinstance(data.get("playlists"), list):
		raise ValueError("The library playlist list is invalid.")
	return data


def save_library(path: str | pathlib.Path, library: dict) -> None:
	target = pathlib.Path(path)
	target.parent.mkdir(parents=True, exist_ok=True)
	library["updated_at"] = _now()
	with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".tmp", prefix="csvmusic-library-", dir=target.parent, delete=False) as handle:
		json.dump(library, handle, ensure_ascii=False, indent=2)
		temporary = pathlib.Path(handle.name)
	temporary.replace(target)


def add_playlist_urls(library: dict, values: list[str]) -> tuple[list[dict], list[str]]:
	existing = {_playlist_key(item) for item in library.get("playlists", [])}
	added: list[dict] = []
	errors: list[str] = []
	for value in values:
		text = str(value or "").strip()
		if not text:
			continue
		try:
			if "music.apple.com" in text.casefold():
				source_type, source_id, url = parse_apple_music_source_url(text)
				platform = "apple_music"
				placeholder = f"Unscanned Apple Music {source_type.title()}"
			elif "youtube.com" in text.casefold() or "youtu.be" in text.casefold():
				source_id = parse_youtube_playlist_id(text)
				platform = "youtube_music"
				url = f"https://music.youtube.com/playlist?list={source_id}"
				placeholder = "Unscanned YouTube Music Playlist"
			else:
				source = parse_spotify_source(text, expected_type="playlist")
				source_id = source.id
				platform = "spotify"
				url = f"https://open.spotify.com/playlist/{source_id}"
				placeholder = "Unscanned Spotify Playlist"
		except Exception as exc:
			errors.append(f"{text}: {exc}")
			continue
		key = f"{platform}:{source_id}"
		if key in existing:
			continue
		playlist = {
			"id": source_id,
			"platform": platform,
			"url": url,
			"name": placeholder,
			"last_scanned_at": None,
			"reported_total": None,
			"scan_warning": None,
			"cover_url": None,
			"tracks": [],
		}
		library.setdefault("playlists", []).append(playlist)
		existing.add(key)
		added.append(playlist)
	return added, errors


def merge_playlist_scan(
	library: dict,
	playlist_id: str,
	name: str,
	tracks: list[dict],
	*,
	reported_total: int | None = None,
	warning: str | None = None,
	cover_url: str | None = None,
) -> dict:
	playlist = playlist_by_id(library, playlist_id)
	if playlist is None:
		raise KeyError(f"Playlist {playlist_id} is not in this library.")
	previous = {_track_key(track): track for track in playlist.get("tracks", [])}
	merged: list[dict] = []
	seen: set[str] = set()
	for position, raw in enumerate(tracks, start=1):
		track = _normalized_track(raw, name, position)
		key = _track_key(track)
		if key in seen:
			continue
		seen.add(key)
		old = previous.get(key, {})
		track["enabled"] = bool(old.get("enabled", True))
		track["preferred_video_id"] = old.get("preferred_video_id") or track.get("preferred_video_id") or None
		track["preferred_video_label"] = old.get("preferred_video_label") or track.get("preferred_video_label") or None
		track["force_redownload"] = bool(old.get("force_redownload", False))
		track["last_error"] = old.get("last_error") or None
		track["last_error_at"] = old.get("last_error_at") or None
		track["last_downloaded_at"] = old.get("last_downloaded_at") or None
		track["downloaded_video_id"] = old.get("downloaded_video_id") or None
		track["downloaded_video_title"] = old.get("downloaded_video_title") or None
		track["downloaded_video_publisher"] = old.get("downloaded_video_publisher") or None
		merged.append(track)
	removed = [old for key, old in previous.items() if key not in seen]
	playlist.update({
		"name": (name or playlist.get("name") or "Spotify Playlist").strip(),
		"last_scanned_at": _now(),
		"reported_total": reported_total,
		"scan_warning": warning,
		"cover_url": cover_url or playlist.get("cover_url"),
		"tracks": merged,
		"last_diff": {
			"added": sum(1 for track in merged if _track_key(track) not in previous),
			"removed": len(removed),
			"unchanged": sum(1 for track in merged if _track_key(track) in previous),
		},
	})
	return playlist


def playlist_by_id(library: dict, playlist_id: str) -> dict | None:
	return next((item for item in library.get("playlists", []) if _playlist_key(item) == playlist_id or item.get("id") == playlist_id), None)


def enabled_tracks(library: dict, playlist_ids: set[str] | None = None) -> list[dict]:
	result: list[dict] = []
	for playlist in library.get("playlists", []):
		if playlist_ids is not None and _playlist_key(playlist) not in playlist_ids and playlist.get("id") not in playlist_ids:
			continue
		for stored in playlist.get("tracks", []):
			track = dict(stored)
			track["enabled"] = True
			track["playlist"] = playlist.get("name") or "Playlist"
			track["library_playlist_id"] = _playlist_key(playlist)
			result.append(track)
	return result


def clear_redownload_flag(path: str | pathlib.Path, playlist_id: str, track: dict) -> None:
	"""Mark one successfully replaced library track as current."""
	library = load_library(path)
	playlist = playlist_by_id(library, playlist_id)
	if playlist is None:
		return
	key = _track_key(track)
	for stored in playlist.get("tracks", []):
		if _track_key(stored) == key:
			stored["force_redownload"] = False
			save_library(path, library)
			return


def record_library_download_result(
	path: str | pathlib.Path,
	playlist_id: str,
	track: dict,
	*,
	downloaded: bool,
	error: str | None = None,
	match: dict | None = None,
) -> None:
	"""Persist a library track's latest download outcome for later inspection."""
	library = load_library(path)
	playlist = playlist_by_id(library, playlist_id)
	if playlist is None:
		return
	key = _track_key(track)
	for stored in playlist.get("tracks", []):
		if _track_key(stored) != key:
			continue
		if downloaded:
			stored["force_redownload"] = False
			stored["last_error"] = None
			stored["last_error_at"] = None
			stored["last_downloaded_at"] = _now()
			stored["downloaded_video_id"] = (match or {}).get("videoId") or stored.get("downloaded_video_id")
			stored["downloaded_video_title"] = (match or {}).get("title") or stored.get("downloaded_video_title")
			stored["downloaded_video_publisher"] = (
				(match or {}).get("author") or (match or {}).get("artists") or stored.get("downloaded_video_publisher")
			)
		elif error:
			stored["last_error"] = str(error).strip()[:4000]
			stored["last_error_at"] = _now()
		save_library(path, library)
		return


def library_status(library: dict, output_dir: str | pathlib.Path, fmt: str) -> dict:
	root = pathlib.Path(output_dir)
	by_playlist: dict[str, dict] = {}
	totals = {"enabled": 0, "downloaded": 0, "missing": 0, "disabled": 0, "redownload": 0}
	for playlist in library.get("playlists", []):
		status = {"enabled": 0, "downloaded": 0, "missing": 0, "disabled": 0, "redownload": 0}
		for stored in playlist.get("tracks", []):
			status["enabled"] += 1
			track = dict(stored)
			track["playlist"] = playlist.get("name") or "Playlist"
			if stored.get("force_redownload"):
				status["redownload"] += 1
			if expected_track_path(track, root, fmt).exists():
				status["downloaded"] += 1
			else:
				status["missing"] += 1
		by_playlist[_playlist_key(playlist)] = status
		for key in totals:
			totals[key] += status[key]
	return {"totals": totals, "playlists": by_playlist}


def export_csv(path: str | pathlib.Path, library: dict, playlist_ids: set[str] | None = None) -> None:
	fields = ["Playlist name", "Track name", "Artist name", "Album", "ISRC", "Spotify - id", "Duration (ms)", "Release date", "Cover URL"]
	with pathlib.Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
		writer = csv.DictWriter(handle, fieldnames=fields)
		writer.writeheader()
		for track in enabled_tracks(library, playlist_ids):
			writer.writerow({
				"Playlist name": track.get("playlist"),
				"Track name": track.get("title"),
				"Artist name": track.get("artists"),
				"Album": track.get("album"),
				"ISRC": track.get("isrc"),
				"Spotify - id": track.get("sp_id"),
				"Duration (ms)": track.get("duration_ms") or 0,
				"Release date": track.get("year"),
				"Cover URL": track.get("cover_url"),
			})


def _normalized_track(raw: dict[str, Any], playlist_name: str, position: int) -> dict:
	track = {
		"title": str(raw.get("title") or "").strip(),
		"artists": str(raw.get("artists") or "").strip(),
		"album": str(raw.get("album") or "").strip(),
		"playlist": playlist_name,
		"isrc": raw.get("isrc") or None,
		"sp_id": raw.get("sp_id") or raw.get("id") or None,
		"duration_ms": int(raw.get("duration_ms") or 0),
		"year": raw.get("year"),
		"cover_url": raw.get("cover_url") or None,
		"track_no": int(raw.get("track_no") or position),
		"disc_no": int(raw.get("disc_no") or 1),
	}
	if raw.get("youtube_video_id"):
		track["youtube_video_id"] = raw["youtube_video_id"]
		track["preferred_video_id"] = raw["youtube_video_id"]
		track["preferred_video_label"] = raw.get("preferred_video_label") or f"https://music.youtube.com/watch?v={raw['youtube_video_id']}"
		track["youtube_video_title"] = raw.get("youtube_video_title") or track["title"]
		track["youtube_video_author"] = raw.get("youtube_video_author") or track["artists"]
	if raw.get("apple_music_id"):
		track["apple_music_id"] = raw["apple_music_id"]
	return track


def _track_key(track: dict) -> str:
	youtube_id = str(track.get("youtube_video_id") or "").strip()
	if youtube_id:
		return f"youtube:{youtube_id}"
	apple_id = str(track.get("apple_music_id") or "").strip()
	if apple_id:
		return f"apple:{apple_id}"
	spotify_id = str(track.get("sp_id") or track.get("id") or "").strip()
	if spotify_id:
		return f"spotify:{spotify_id}"
	return f"text:{str(track.get('artists') or '').casefold().strip()}|{str(track.get('title') or '').casefold().strip()}"


def _now() -> str:
	return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _playlist_key(playlist: dict) -> str:
	return f"{playlist.get('platform') or 'spotify'}:{playlist.get('id')}"
