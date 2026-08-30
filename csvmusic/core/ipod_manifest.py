import argparse
import json
import os
import pathlib
import sys

from mutagen import File as MutagenFile

from csvmusic.core.track_output import expected_track_path


def _field(value: object) -> str:
	return str(value or "").replace("\t", " ").replace("\r", " ").replace("\n", " ")


def _tag(audio: object, name: str, fallback: object = "") -> str:
	values = audio.get(name) if audio else None
	if isinstance(values, list) and values:
		return _field(values[0])
	return _field(values or fallback)


def windows_to_wsl(path: pathlib.Path) -> str:
	resolved = path.resolve()
	drive, tail = os.path.splitdrive(str(resolved))
	if not drive:
		return str(resolved).replace("\\", "/")
	posix_tail = tail.lstrip("\\/").replace("\\", "/")
	return f"/mnt/{drive[0].lower()}/{posix_tail}"


def emit_manifest(library_path: pathlib.Path, playlist_name: str) -> int:
	library = json.loads(library_path.read_text(encoding="utf-8"))
	playlist = next((item for item in library.get("playlists", []) if item.get("name") == playlist_name), None)
	if not playlist:
		raise ValueError(f"Playlist not found: {playlist_name}")
	root = pathlib.Path(library.get("output_dir") or "")
	fmt = str(library.get("format") or "mp3")
	count = 0
	for index, track in enumerate(playlist.get("tracks", []), start=1):
		path = expected_track_path(track, root, fmt)
		if not path.is_file():
			raise FileNotFoundError(path)
		audio = MutagenFile(path, easy=True)
		info = getattr(audio, "info", None)
		title = _tag(audio, "title", track.get("title"))
		artist = _tag(audio, "artist", track.get("artists"))
		album = _tag(audio, "album", track.get("album"))
		duration_ms = round(float(getattr(info, "length", 0)) * 1000)
		bitrate = round(float(getattr(info, "bitrate", 0)) / 1000)
		sample_rate = int(getattr(info, "sample_rate", 0))
		fields = (
			windows_to_wsl(path),
			title,
			artist,
			album,
			index,
			duration_ms,
			path.stat().st_size,
			bitrate,
			sample_rate,
			(
				("selected:" if track.get("preferred_selection_locked") or (
					track.get("preferred_video_id") and track.get("preferred_video_id") != track.get("youtube_video_id")
				) else "auto:")
				+ str(track.get("preferred_video_id") or track.get("downloaded_video_id") or track.get("youtube_video_id")
					or track.get("sp_id") or f"text:{track.get('artists', '')}|{track.get('title', '')}")
			),
		)
		print("\t".join(_field(value) for value in fields))
		count += 1
	return count


def main() -> int:
	if hasattr(sys.stdout, "reconfigure"):
		sys.stdout.reconfigure(encoding="utf-8")
	parser = argparse.ArgumentParser(description="Emit a libgpod-compatible CSVMusic playlist manifest.")
	parser.add_argument("library", type=pathlib.Path)
	parser.add_argument("playlist")
	args = parser.parse_args()
	emit_manifest(args.library, args.playlist)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
