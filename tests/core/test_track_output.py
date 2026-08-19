# tabs only
import pathlib

from csvmusic.core.track_output import duplicate_output_rows, expected_track_path, plan_track_outputs


def _track(title: str, artist: str = "Artist") -> dict:
	return {"title": title, "artists": artist, "playlist": "Playlist"}


def test_duplicate_output_rows_maps_repeated_entries_to_first_row(tmp_path: pathlib.Path) -> None:
	tracks = [_track("One"), _track("Two"), _track("One")]

	duplicates = duplicate_output_rows(tracks, tmp_path, "m4a")

	assert duplicates == {2: 0}


def test_duplicate_output_rows_keeps_different_artists_separate(tmp_path: pathlib.Path) -> None:
	tracks = [_track("One", "Artist A"), _track("One", "Artist B")]

	assert duplicate_output_rows(tracks, tmp_path, "mp3") == {}


def test_output_plan_reconciles_playlist_rows_with_physical_files(tmp_path: pathlib.Path) -> None:
	unique_tracks = [_track(f"Song {index}") for index in range(1442)]
	duplicate_tracks = [dict(unique_tracks[index]) for index in range(60)]
	tracks = unique_tracks + duplicate_tracks
	for track in unique_tracks[:1434]:
		path = expected_track_path(track, tmp_path, "m4a")
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_bytes(b"audio")

	plan = plan_track_outputs(tracks, tmp_path, "m4a")

	assert plan.total_rows == 1502
	assert plan.unique_file_rows == 1442
	assert len(plan.existing_rows) == 1434
	assert len(plan.queued_rows) == 8
	assert len(plan.duplicate_rows) == 60


def test_output_plan_treats_sanitized_filename_collisions_as_shared_files(tmp_path: pathlib.Path) -> None:
	tracks = [_track("Question"), _track("Question\x01")]

	plan = plan_track_outputs(tracks, tmp_path, "mp3")

	assert plan.queued_rows == (0,)
	assert plan.duplicate_rows == {1: 0}
