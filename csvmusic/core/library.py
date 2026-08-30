# tabs only
import csv
import datetime
import hashlib
import json
import pathlib
import tempfile
from typing import Any
from urllib.parse import urlparse

from csvmusic.core.spotify_import import parse_spotify_source
from csvmusic.core.downloader import sanitize_name
from csvmusic.core.track_output import expected_track_path
from csvmusic.core.youtube_music_import import parse_youtube_music_source
from csvmusic.core.apple_music_import import parse_apple_music_source_url
from csvmusic.core.deezer_import import parse_deezer_source
from csvmusic.core.amazon_music_import import parse_amazon_music_source
from csvmusic.core.csv_import import load_csv, tracks_from_csv


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
			host = urlparse(text).netloc.lower().removeprefix("www.")
			if "music.apple.com" in text.casefold():
				source_type, source_id, url = parse_apple_music_source_url(text)
				platform = "apple_music"
				placeholder = f"Unscanned Apple Music {source_type.title()}"
			elif "youtube.com" in text.casefold() or "youtu.be" in text.casefold():
				host = urlparse(text).netloc.lower().split(":", 1)[0]
				source_type, source_id = parse_youtube_music_source(text)
				is_youtube_music = host == "music.youtube.com"
				platform = "youtube_music" if is_youtube_music else "youtube"
				url = (
					f"https://music.youtube.com/browse/{source_id}" if source_type == "album"
					else f"https://{'music.' if is_youtube_music else 'www.'}youtube.com/playlist?list={source_id}"
				)
				placeholder = f"Unscanned {'YouTube Music' if is_youtube_music else 'YouTube'} {source_type.title()}"
			elif host in ("deezer.com", "deezer.page.link"):
				source_type, source_id = parse_deezer_source(text)
				platform = "deezer"
				url = text
				placeholder = f"Unscanned Deezer {source_type.title()}"
			elif "music.amazon." in host:
				url, source_type, source_id = parse_amazon_music_source(text)
				platform = "amazon_music"
				placeholder = f"Unscanned Amazon Music {source_type.title()}"
			else:
				source = parse_spotify_source(text)
				source_type = source.type
				source_id = source.id
				platform = "spotify"
				url = f"https://open.spotify.com/{source_type}/{source_id}"
				placeholder = f"Unscanned Spotify {source_type.title()}"
		except Exception as exc:
			errors.append(f"{text}: {exc}")
			continue
		key = f"{platform}:{source_id}"
		if key in existing:
			continue
		playlist = {
			"id": source_id,
			"platform": platform,
			"source_type": source_type,
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


def import_csv_playlist(library: dict, path: str | pathlib.Path) -> tuple[dict, bool]:
	"""Import or refresh one CSV file as a first-class library playlist."""
	source_path = pathlib.Path(path).expanduser().resolve()
	df = load_csv(source_path)
	tracks = tracks_from_csv(df)
	if not tracks:
		raise ValueError("The CSV did not contain any usable tracks.")
	name = str(tracks[0].get("playlist") or source_path.stem).strip() or source_path.stem
	source_id = hashlib.sha256(str(source_path).casefold().encode("utf-8")).hexdigest()[:20]
	key = f"csv:{source_id}"
	playlist = playlist_by_id(library, key)
	created = playlist is None
	if playlist is None:
		playlist = {
			"id": source_id,
			"platform": "csv",
			"url": str(source_path),
			"csv_path": str(source_path),
			"name": name,
			"last_scanned_at": None,
			"reported_total": None,
			"scan_warning": None,
			"cover_url": None,
			"tracks": [],
		}
		library.setdefault("playlists", []).append(playlist)
	merge_playlist_scan(library, key, name, tracks, reported_total=len(tracks))
	playlist["csv_path"] = str(source_path)
	playlist["url"] = str(source_path)
	return playlist, created


def rename_library_playlist(
	library: dict,
	playlist_id: str,
	new_name: str,
	output_dir: str | pathlib.Path | None = None,
) -> tuple[dict, pathlib.Path | None]:
	"""Rename a playlist, its output folder, and its matching M3U files."""
	playlist = playlist_by_id(library, playlist_id)
	if playlist is None:
		raise KeyError(f"Playlist {playlist_id} is not in this library.")
	clean_name = str(new_name or "").strip()
	if not clean_name:
		raise ValueError("Playlist name cannot be blank.")
	old_name = str(playlist.get("name") or "Playlist").strip() or "Playlist"
	old_safe = sanitize_name(old_name) or "Playlist"
	new_safe = sanitize_name(clean_name) or "Playlist"
	for other in library.get("playlists", []):
		if other is playlist:
			continue
		other_safe = sanitize_name(str(other.get("name") or "Playlist")) or "Playlist"
		if other_safe.casefold() == new_safe.casefold():
			raise ValueError("Another library playlist already uses that output-folder name.")

	renamed_folder: pathlib.Path | None = None
	if output_dir:
		root = pathlib.Path(output_dir).expanduser().resolve()
		old_folder = root / old_safe
		new_folder = root / new_safe
		if old_folder.exists() and old_folder.is_dir():
			if old_folder != new_folder and new_folder.exists():
				raise FileExistsError(f"The destination folder already exists: {new_folder}")
			m3u_moves: list[tuple[pathlib.Path, pathlib.Path]] = []
			m3u_unchanged: list[pathlib.Path] = []
			for suffix in (".m3u", ".m3u8"):
				source = old_folder / f"{old_safe}{suffix}"
				destination = old_folder / f"{new_safe}{suffix}"
				if source.exists() and source != destination:
					if destination.exists():
						raise FileExistsError(f"The destination playlist file already exists: {destination}")
					m3u_moves.append((source, destination))
				elif source.exists():
					m3u_unchanged.append(source)
			if old_folder != new_folder:
				old_folder.rename(new_folder)
				renamed_folder = new_folder
			else:
				renamed_folder = old_folder
			for old_file, old_destination in m3u_moves:
				source = renamed_folder / old_file.name
				destination = renamed_folder / old_destination.name
				source.rename(destination)
				_update_m3u_playlist_name(destination, clean_name)
			for old_file in m3u_unchanged:
				_update_m3u_playlist_name(renamed_folder / old_file.name, clean_name)

	playlist["name"] = clean_name
	playlist["custom_name"] = True
	for track in playlist.get("tracks", []):
		track["playlist"] = clean_name
	return playlist, renamed_folder


def edit_library_track(library: dict, playlist_id: str, track_index: int, title: str, album: str) -> dict:
	"""Apply user-owned track metadata overrides that survive future rescans."""
	playlist = playlist_by_id(library, playlist_id)
	if playlist is None:
		raise KeyError(f"Playlist {playlist_id} is not in this library.")
	tracks = playlist.get("tracks", [])
	if track_index < 0 or track_index >= len(tracks):
		raise IndexError("The selected song is no longer in this playlist.")
	clean_title = str(title or "").strip()
	clean_album = str(album or "").strip()
	if not clean_title:
		raise ValueError("Song title cannot be blank.")
	track = tracks[track_index]
	track["title"] = clean_title
	track["album"] = clean_album
	track["custom_title"] = True
	track["custom_album"] = True
	return track


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
	previous: dict[str, dict] = {}
	previous_occurrences: dict[str, int] = {}
	for old_track in playlist.get("tracks", []):
		base_key = _track_base_key(old_track)
		occurrence = int(old_track.get("playlist_occurrence") or (previous_occurrences.get(base_key, 0) + 1))
		previous_occurrences[base_key] = max(previous_occurrences.get(base_key, 0), occurrence)
		old_track["playlist_occurrence"] = occurrence
		previous[_track_key(old_track)] = old_track
	effective_name = str(playlist.get("name") or name or "Spotify Playlist").strip() if playlist.get("custom_name") else str(name or playlist.get("name") or "Spotify Playlist").strip()
	merged: list[dict] = []
	seen: set[str] = set()
	new_occurrences: dict[str, int] = {}
	for position, raw in enumerate(tracks, start=1):
		track = _normalized_track(raw, effective_name, position)
		base_key = _track_base_key(track)
		occurrence = int(raw.get("playlist_occurrence") or (new_occurrences.get(base_key, 0) + 1))
		new_occurrences[base_key] = max(new_occurrences.get(base_key, 0), occurrence)
		track["playlist_occurrence"] = occurrence
		key = _track_key(track)
		if key in seen:
			continue
		seen.add(key)
		old = previous.get(key, {})
		if not old:
			text_key = _track_text_key(track)
			matching_old = [candidate for candidate in playlist.get("tracks", []) if _track_text_key(candidate) == text_key]
			if len(matching_old) == 1:
				old = matching_old[0]
		if old.get("custom_title"):
			track["title"] = old.get("title") or track["title"]
			track["custom_title"] = True
		if old.get("custom_album"):
			track["album"] = old.get("album") or ""
			track["custom_album"] = True
		track["enabled"] = bool(old.get("enabled", True))
		track["preferred_video_id"] = old.get("preferred_video_id") or track.get("preferred_video_id") or None
		track["preferred_video_label"] = old.get("preferred_video_label") or track.get("preferred_video_label") or None
		track["preferred_selection_locked"] = bool(old.get("preferred_selection_locked", False))
		track["audio_volume_gain"] = int(old.get("audio_volume_gain", track.get("audio_volume_gain", 0)) or 0)
		track["force_redownload"] = bool(old.get("force_redownload", False))
		track["last_error"] = old.get("last_error") or None
		track["last_error_at"] = old.get("last_error_at") or None
		track["last_downloaded_at"] = old.get("last_downloaded_at") or None
		track["downloaded_video_id"] = old.get("downloaded_video_id") or None
		track["downloaded_video_title"] = old.get("downloaded_video_title") or None
		track["downloaded_video_publisher"] = old.get("downloaded_video_publisher") or None
		old_downloaded_path = old.get("downloaded_path")
		if not old_downloaded_path and old:
			old_probe = dict(old)
			old_probe["playlist"] = str(playlist.get("name") or effective_name or "Playlist")
			candidate = expected_track_path(old_probe, pathlib.Path(library.get("output_dir") or ""), str(library.get("format") or "mp3"))
			if candidate.is_file():
				old_downloaded_path = str(candidate)
		track["downloaded_path"] = old_downloaded_path or None
		track["low_confidence_review"] = bool(old.get("low_confidence_review", False))
		track["download_confidence"] = old.get("download_confidence")
		merged.append(track)
	removed = [old for key, old in previous.items() if key not in seen]
	playlist.update({
		"name": effective_name,
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


def _update_m3u_playlist_name(path: pathlib.Path, playlist_name: str) -> None:
	raw = path.read_bytes()
	has_bom = raw.startswith(b"\xef\xbb\xbf")
	text = raw.decode("utf-8-sig")
	lines = text.splitlines()
	replacement = f"#EXTPLAYLIST:{playlist_name}"
	for index, line in enumerate(lines):
		if line.startswith("#EXTPLAYLIST:"):
			lines[index] = replacement
			break
	else:
		lines.insert(1 if lines and lines[0] == "#EXTM3U" else 0, replacement)
	ending = "\n" if text.endswith(("\n", "\r")) else ""
	path.write_text("\n".join(lines) + ending, encoding="utf-8-sig" if has_bom else "utf-8")


def playlist_by_id(library: dict, playlist_id: str) -> dict | None:
	return next((item for item in library.get("playlists", []) if _playlist_key(item) == playlist_id or item.get("id") == playlist_id), None)


def enabled_tracks(library: dict, playlist_ids: set[str] | None = None) -> list[dict]:
	result: list[dict] = []
	for playlist in library.get("playlists", []):
		if playlist_ids is not None and _playlist_key(playlist) not in playlist_ids and playlist.get("id") not in playlist_ids:
			continue
		for track_index, stored in enumerate(playlist.get("tracks", [])):
			if not stored.get("enabled", True):
				continue
			track = dict(stored)
			track["playlist"] = playlist.get("name") or "Playlist"
			track["library_playlist_id"] = _playlist_key(playlist)
			track["library_track_index"] = track_index
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
	low_confidence: bool = False,
	confidence: float | None = None,
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
			stored["low_confidence_review"] = bool(low_confidence)
			stored["download_confidence"] = confidence
			probe = dict(track)
			probe["playlist"] = playlist.get("name") or "Playlist"
			downloaded_file = expected_track_path(
				probe, pathlib.Path(library.get("output_dir") or ""), str(library.get("format") or "mp3"),
			)
			if downloaded_file.is_file():
				old_downloaded = str(stored.get("downloaded_path") or "").strip()
				if old_downloaded and stored.get("preferred_selection_locked"):
					old_path = pathlib.Path(old_downloaded)
					output_root = pathlib.Path(library.get("output_dir") or "").resolve()
					try:
						old_resolved = old_path.resolve()
						if old_resolved != downloaded_file.resolve() and old_resolved.is_relative_to(output_root) and old_resolved.is_file():
							old_resolved.unlink()
					except (OSError, RuntimeError):
						pass
				stored["downloaded_path"] = str(downloaded_file)
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
			if library_track_path(track, root, fmt).exists():
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


def _track_base_key(track: dict) -> str:
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


def _track_text_key(track: dict) -> str:
	return f"{str(track.get('artists') or '').casefold().strip()}|{str(track.get('title') or '').casefold().strip()}"


def library_track_path(track: dict, output_dir: str | pathlib.Path, fmt: str) -> pathlib.Path:
	"""Resolve the file actually downloaded for a library row before its current expected filename."""
	stored = str(track.get("downloaded_path") or "").strip()
	if stored:
		stored_path = pathlib.Path(stored)
		if stored_path.is_file():
			return stored_path
	return expected_track_path(track, pathlib.Path(output_dir), fmt)


def _track_key(track: dict) -> str:
	base = _track_base_key(track)
	occurrence = int(track.get("playlist_occurrence") or 1)
	return f"{base}|occurrence:{occurrence}"


def _now() -> str:
	return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _playlist_key(playlist: dict) -> str:
	return f"{playlist.get('platform') or 'spotify'}:{playlist.get('id')}"
