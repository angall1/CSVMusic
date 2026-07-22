# tabs only
import pathlib

from csvmusic.core.track_output import duplicate_output_rows


def _track(title: str, artist: str = "Artist") -> dict:
	return {"title": title, "artists": artist, "playlist": "Playlist"}


def test_duplicate_output_rows_maps_repeated_entries_to_first_row(tmp_path: pathlib.Path) -> None:
	tracks = [_track("One"), _track("Two"), _track("One")]

	duplicates = duplicate_output_rows(tracks, tmp_path, "m4a")

	assert duplicates == {2: 0}


def test_duplicate_output_rows_keeps_different_artists_separate(tmp_path: pathlib.Path) -> None:
	tracks = [_track("One", "Artist A"), _track("One", "Artist B")]

	assert duplicate_output_rows(tracks, tmp_path, "mp3") == {}
