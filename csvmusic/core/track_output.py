# tabs only
import pathlib
from dataclasses import dataclass

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


@dataclass(frozen=True)
class TrackOutputPlan:
	"""Account for every playlist row before a download starts."""
	duplicate_rows: dict[int, int]
	existing_rows: tuple[int, ...]
	queued_rows: tuple[int, ...]

	@property
	def total_rows(self) -> int:
		return len(self.existing_rows) + len(self.queued_rows) + len(self.duplicate_rows)

	@property
	def unique_file_rows(self) -> int:
		return len(self.existing_rows) + len(self.queued_rows)


def plan_track_outputs(tracks: list[dict], out_root: pathlib.Path, fmt: str) -> TrackOutputPlan:
	"""Classify rows as unique existing files, queued files, or shared-file duplicates."""
	duplicates = duplicate_output_rows(tracks, out_root, fmt)
	existing: list[int] = []
	queued: list[int] = []
	for row, track in enumerate(tracks):
		if row in duplicates:
			continue
		if expected_track_path(track, out_root, fmt).exists() and not track.get("force_redownload", False):
			existing.append(row)
		else:
			queued.append(row)
	return TrackOutputPlan(duplicates, tuple(existing), tuple(queued))
