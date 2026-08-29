from csvmusic.ui.spotify_public_scrape import jittered_scroll_delay_ms, metadata_gap_positions, normalized_capture, ordered_playlist_tracks, recover_single_missing_position


def test_normalized_capture_maps_public_row():
	assert normalized_capture({
		"id": "track-id",
		"position": 7,
		"title": " Song ",
		"artists": ["Artist One", "Artist Two"],
		"album": "Album",
		"cover_url": "https://i.scdn.co/image/cover",
	}) == {
		"id": "track-id",
		"position": 7,
		"title": "Song",
		"artists": "Artist One, Artist Two",
		"album": "Album",
		"cover_url": "https://i.scdn.co/image/cover",
	}


def test_playlist_position_filter_excludes_recommendations_and_orders_rows():
	tracks = [
		{"id": "recommended", "position": None},
		{"id": "second", "position": 2},
		{"id": "outside", "position": 4},
		{"id": "first", "position": 1},
	]
	assert [track["id"] for track in ordered_playlist_tracks(tracks, 3)] == ["first", "second"]


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


def test_single_positionless_final_track_is_recovered():
	existing = {
		str(position): {"id": str(position), "position": position}
		for position in range(1, 53)
	}
	captured = [{"id": "last-track", "position": None, "title": "Final Song"}]

	recovered = recover_single_missing_position(captured, existing, 53)

	assert recovered[0]["position"] == 53


def test_ambiguous_positionless_tracks_are_not_guessed():
	existing = {"1": {"id": "1", "position": 1}}
	captured = [
		{"id": "unknown-a", "position": None},
		{"id": "unknown-b", "position": None},
	]

	recovered = recover_single_missing_position(captured, existing, 2)

	assert all(track["position"] is None for track in recovered)
