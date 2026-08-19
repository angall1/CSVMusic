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


def test_exportify_csv_headers_and_filename_playlist_are_supported(tmp_path):
	path = tmp_path / "OFFICE_PLAYLIST.csv"
	pd.DataFrame([{
		"Track URI": "spotify:track:0s1aSsYlLIEiy16LjFWbdp",
		"Track Name": "Dirty Work",
		"Album Name": "Can't Buy A Thrill",
		"Artist Name(s)": "Steely Dan",
		"Release Date": "1972-01-01",
		"Duration (ms)": 187400,
	}]).to_csv(path, index=False)

	track = tracks_from_csv(load_csv(path))[0]

	assert track["title"] == "Dirty Work"
	assert track["artists"] == "Steely Dan"
	assert track["album"] == "Can't Buy A Thrill"
	assert track["playlist"] == "OFFICE_PLAYLIST"
	assert track["sp_id"] == "0s1aSsYlLIEiy16LjFWbdp"
	assert track["duration_ms"] == 187400
	assert track["year"] == 1972


def test_blank_playlist_names_fall_back_to_csv_filename(tmp_path):
	path = tmp_path / "My Playlist.csv"
	pd.DataFrame([{
		"Track name": "Song",
		"Artist name": "Artist",
		"Playlist name": "",
	}]).to_csv(path, index=False)

	track = tracks_from_csv(load_csv(path))[0]

	assert track["playlist"] == "My Playlist"
