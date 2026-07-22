# tabs only
import pathlib

from csvmusic.core.downloader import sanitize_name


def expected_track_path(track: dict, out_root: pathlib.Path, fmt: str) -> pathlib.Path:
	playlist_name = track.get("playlist") or "Playlist"
	base = f"{track.get('artists', '')} - {track.get('title', '')}"
	return out_root / sanitize_name(playlist_name) / f"{sanitize_name(base)}.{fmt}"


def duplicate_output_rows(tracks: list[dict], out_root: pathlib.Path, fmt: str) -> dict[int, int]:
	"""Map duplicate row indexes to the first row that owns the same output path."""
	first_by_path: dict[str, int] = {}
	duplicates: dict[int, int] = {}
	for row, track in enumerate(tracks):
		path_key = str(expected_track_path(track, out_root, fmt)).casefold()
		primary = first_by_path.get(path_key)
		if primary is None:
			first_by_path[path_key] = row
		else:
			duplicates[row] = primary
	return duplicates
