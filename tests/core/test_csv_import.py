import pandas as pd

from csvmusic.core.csv_import import load_csv, tracks_from_csv


def test_csv_without_spotify_id_imports(tmp_path):
	path = tmp_path / "apple_music.csv"
	pd.DataFrame([
		{
			"Track name": "Everybody Needs Somebody to Love",
			"Artist name": "The Blues Brothers",
			"Playlist name": "Apple Export",
			"Duration (ms)": 206000,
		}
	]).to_csv(path, index=False)

	df = load_csv(path)
	tracks = tracks_from_csv(df)

	assert len(tracks) == 1
	assert tracks[0]["title"] == "Everybody Needs Somebody to Love"
	assert tracks[0]["artists"] == "The Blues Brothers"
	assert tracks[0]["sp_id"] is None
	assert tracks[0]["duration_ms"] == 206000
	assert tracks[0]["track_no"] == 1
	assert tracks[0]["disc_no"] == 1


def test_csv_import_preserves_explicit_track_and_disc_numbers(tmp_path):
	path = tmp_path / "album.csv"
	pd.DataFrame([{
		"Track name": "Finale",
		"Artist name": "Original Cast",
		"Playlist name": "Album",
		"Track number": 12,
		"Disc number": 2,
	}]).to_csv(path, index=False)

	track = tracks_from_csv(load_csv(path))[0]

	assert track["track_no"] == 12
	assert track["disc_no"] == 2
