import pandas as pd

from csvmusic.core.csv_import import load_csv, tracks_from_csv, deduplicate_tracks


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


def test_multi_playlist_csv_accepted(tmp_path):
	"""load_csv must not raise when CSV spans multiple playlists."""
	path = tmp_path / "multi.csv"
	pd.DataFrame([
		{"Track name": "Song A", "Artist name": "Artist X", "Playlist name": "Playlist 1"},
		{"Track name": "Song B", "Artist name": "Artist Y", "Playlist name": "Playlist 1"},
		{"Track name": "Song A", "Artist name": "Artist X", "Playlist name": "Playlist 2"},
	]).to_csv(path, index=False)
	df = load_csv(path)  # must not raise
	playlists = df["Playlist name"].unique().tolist()
	assert set(playlists) == {"Playlist 1", "Playlist 2"}


def test_deduplicate_tracks_merges_playlists(tmp_path):
	"""Songs shared across playlists must appear once, with all playlists listed."""
	path = tmp_path / "multi.csv"
	pd.DataFrame([
		{"Track name": "Song A", "Artist name": "Artist X", "Playlist name": "Playlist 1"},
		{"Track name": "Song B", "Artist name": "Artist Y", "Playlist name": "Playlist 1"},
		{"Track name": "Song A", "Artist name": "Artist X", "Playlist name": "Playlist 2"},
	]).to_csv(path, index=False)
	df = load_csv(path)
	tracks = tracks_from_csv(df)
	deduped = deduplicate_tracks(tracks)

	# Only 2 unique songs
	assert len(deduped) == 2

	# Song A should carry both playlist names
	song_a = next(t for t in deduped if t["title"] == "Song A")
	assert set(song_a["playlists"]) == {"Playlist 1", "Playlist 2"}

	# Song B should carry only its own playlist
	song_b = next(t for t in deduped if t["title"] == "Song B")
	assert song_b["playlists"] == ["Playlist 1"]
