from csvmusic.core import ytmusic_match


class FakeYTMusic:
	def __init__(self, results):
		self.results = results

	def search(self, _query, filter, limit):
		return self.results.get(filter, [])[:limit]


def test_search_filter_uses_video_author_as_channel():
	yt = FakeYTMusic({
		"videos": [
			{
				"videoId": "abc123",
				"title": "Same Song",
				"author": "Uploader Channel",
				"duration": "3:05",
			}
		]
	})

	results = ytmusic_match._search_filter(yt, "same song", "videos", 10)

	assert results[0]["author"] == "Uploader Channel"
	assert results[0]["channel"] == "Uploader Channel"
	assert results[0]["duration_seconds"] == 185


def test_search_filter_falls_back_to_video_artist_names_for_uploader():
	yt = FakeYTMusic({
		"videos": [
			{
				"videoId": "abc123",
				"title": "Same Song",
				"artists": [{"name": "Uploader One"}, {"name": "Uploader Two"}],
				"duration_seconds": 201,
			}
		]
	})

	results = ytmusic_match._search_filter(yt, "same song", "videos", 10)

	assert results[0]["author"] == "Uploader One, Uploader Two"
	assert results[0]["channel"] == "Uploader One, Uploader Two"


def test_short_tracks_allow_small_absolute_duration_variance():
	track = {"duration_ms": 15000}

	assert ytmusic_match._duration_within_tolerance(track, {"duration_seconds": 22}) is True
	assert ytmusic_match._duration_within_tolerance(track, {"duration_seconds": 24}) is False


def test_alternative_ranking_can_include_duration_mismatch():
	yt = FakeYTMusic({
		"songs": [{
			"videoId": "song-candidate",
			"title": "Tiny Song",
			"artists": [{"name": "Artist"}],
			"duration": "0:30",
		}],
		"videos": [],
	})
	track = {"title": "Tiny Song", "artists": "Artist", "duration_ms": 15000}

	assert ytmusic_match._rank_candidates(yt, track, enforce_duration=True) == []
	assert len(ytmusic_match._rank_candidates(yt, track, enforce_duration=False)) == 1


def test_confident_youtube_music_song_is_preferred_over_higher_scoring_video(monkeypatch):
	yt = FakeYTMusic({
		"songs": [{"videoId": "music", "title": "Song", "artists": [{"name": "Artist"}], "duration": "3:00"}],
		"videos": [{"videoId": "video", "title": "Song", "author": "Artist Official", "duration": "3:00"}],
	})
	track = {"title": "Song", "artists": "Artist", "duration_ms": 180000}

	def fake_score(_track, candidate):
		return 0.75 if candidate["source"] == "music" else 0.95

	monkeypatch.setattr(ytmusic_match, "_score", fake_score)
	options = ytmusic_match._rank_candidates(yt, track)
	assert [option["videoId"] for option in options[:2]] == ["music", "video"]


def test_unconfident_music_result_does_not_displace_confident_video(monkeypatch):
	yt = FakeYTMusic({
		"songs": [{"videoId": "music", "title": "Wrong", "artists": [{"name": "Other"}], "duration": "3:00"}],
		"videos": [{"videoId": "video", "title": "Song", "author": "Artist", "duration": "3:00"}],
	})
	track = {"title": "Song", "artists": "Artist", "duration_ms": 180000}

	def fake_score(_track, candidate):
		return 0.4 if candidate["source"] == "music" else 0.8

	monkeypatch.setattr(ytmusic_match, "_score", fake_score)
	options = ytmusic_match._rank_candidates(yt, track)
	assert options[0]["videoId"] == "video"


def test_manual_alternatives_group_youtube_music_first(monkeypatch):
	options = [
		{"videoId": "video", "source": "videos", "score": 0.95},
		{"videoId": "music", "source": "music", "score": 0.35},
	]
	monkeypatch.setattr(ytmusic_match, "YTMusic", lambda: object())
	monkeypatch.setattr(ytmusic_match, "_rank_candidates", lambda *_args, **_kwargs: options)
	results = ytmusic_match.more_candidates({"title": "Song"})
	assert [result["videoId"] for result in results] == ["music", "video"]


def test_live_and_acoustic_versions_are_strongly_penalized_unless_requested():
	track = {"title": "The Trooper", "artists": "Iron Maiden", "duration_ms": 240000}
	studio = {"title": "The Trooper", "author": "Iron Maiden", "duration_seconds": 240}
	live = {"title": "The Trooper (Live at Rock in Rio)", "author": "Iron Maiden", "duration_seconds": 240}
	acoustic = {"title": "The Trooper (Acoustic)", "author": "Iron Maiden", "duration_seconds": 240}
	assert ytmusic_match._score(track, studio) > ytmusic_match._score(track, live)
	assert ytmusic_match._score(track, studio) > ytmusic_match._score(track, acoustic)
	requested = {"title": "The Trooper Live", "artists": "Iron Maiden", "duration_ms": 240000}
	assert ytmusic_match._score(requested, live) > ytmusic_match._score(requested, studio)


def test_live_album_is_detected_when_song_title_omits_live_marker():
	track = {"title": "War Pigs - 2009 Remaster", "artists": "Black Sabbath", "duration_ms": 475000}
	studio = {"title": "War Pigs (2009 Remaster)", "author": "Black Sabbath", "album": {"name": "Paranoid"}, "duration_seconds": 475}
	live = {"title": "War Pigs (2023 Remaster)", "author": "Black Sabbath", "album": {"name": "Live Evil"}, "duration_seconds": 559}
	assert ytmusic_match._candidate_version_markers(live) >= {"live"}
	assert "live" not in ytmusic_match._candidate_version_markers(studio)
	assert ytmusic_match._score(track, studio) > ytmusic_match._score(track, live)


def test_remaster_word_does_not_weaken_unrequested_live_penalty():
	track = {"title": "War Pigs - 2009 Remaster", "artists": "Black Sabbath"}
	studio = {"title": "War Pigs / Luke's Wall", "author": "Black Sabbath", "album": {"name": "Paranoid"}}
	live = {"title": "War Pigs (2023 Remaster)", "author": "Black Sabbath", "album": {"name": "Live Evil"}}
	assert ytmusic_match._score(track, studio) > ytmusic_match._score(track, live)


def test_search_preserves_album_metadata_for_scoring_and_display():
	yt = FakeYTMusic({
		"songs": [{"videoId": "live", "title": "War Pigs (2023 Remaster)", "artists": [{"name": "Black Sabbath"}], "album": {"name": "Live Evil"}, "duration": "9:19"}],
	})
	result = ytmusic_match._search_filter(yt, "War Pigs", "songs", 10)[0]
	assert result["album"] == {"name": "Live Evil"}


def test_requested_extended_version_beats_single_versions():
	track = {"title": "Hocus Pocus - Extended Version", "artists": "Focus", "duration_ms": 420000}
	extended = {"title": "Hocus Pocus (Extended Version)", "author": "Focus", "duration_seconds": 420}
	single = {"title": "Hocus Pocus (U.S. Single Version)", "author": "Focus", "duration_seconds": 420}
	original_single = {"title": "Hocus Pocus (Original Single Version)", "author": "Focus", "duration_seconds": 420}
	assert ytmusic_match._score(track, extended) > ytmusic_match._score(track, single)
	assert ytmusic_match._score(track, extended) > ytmusic_match._score(track, original_single)


def test_requested_single_version_does_not_choose_extended_version():
	track = {"title": "Hocus Pocus - U.S. Single Version", "artists": "Focus", "duration_ms": 240000}
	single = {"title": "Hocus Pocus (U.S. Single Version)", "author": "Focus", "duration_seconds": 240}
	extended = {"title": "Hocus Pocus (Extended Version)", "author": "Focus", "duration_seconds": 240}
	assert ytmusic_match._score(track, single) > ytmusic_match._score(track, extended)
