from csvmusic.ui.spotify_public_scrape import jittered_scroll_delay_ms, metadata_gap_positions, normalized_capture


def test_normalized_capture_maps_public_row():
	assert normalized_capture({
		"id": "track-id",
		"title": " Song ",
		"artists": ["Artist One", "Artist Two"],
		"album": "Album",
		"cover_url": "https://i.scdn.co/image/cover",
	}) == {
		"id": "track-id",
		"title": "Song",
		"artists": "Artist One, Artist Two",
		"album": "Album",
		"cover_url": "https://i.scdn.co/image/cover",
	}


def test_normalized_capture_rejects_missing_identity():
	assert normalized_capture({"title": "Song"}) is None


def test_production_scroll_jitter_centers_on_moderate_interval():
	values = [jittered_scroll_delay_ms(350) for _ in range(100)]
	assert all(322 <= value <= 378 for value in values)


def test_metadata_verification_ignores_recommendations_beyond_reported_total():
	tracks = [
		{"album": "Album", "cover_url": "album-cover"},
		{"album": "Album 2", "cover_url": "album-cover-2"},
		{"album": "", "cover_url": "playlist-cover"},
	]

	assert metadata_gap_positions(tracks, "playlist-cover", reported_total=2) == []


def test_metadata_verification_reports_incomplete_playlist_rows():
	tracks = [
		{"album": "Album", "cover_url": "album-cover"},
		{"album": "", "cover_url": "playlist-cover"},
	]

	assert metadata_gap_positions(tracks, "playlist-cover", reported_total=2) == [2]
