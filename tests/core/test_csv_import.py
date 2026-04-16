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
