from csvmusic.core.youtube_music_import import parse_youtube_playlist_id, _tracks_from_playlist


def test_parse_youtube_music_playlist_id():
	assert parse_youtube_playlist_id("https://music.youtube.com/playlist?list=PLabc123") == "PLabc123"
	assert parse_youtube_playlist_id("https://www.youtube.com/watch?v=abc&list=VLPLabc123") == "PLabc123"


def test_tracks_from_youtube_music_playlist():
	tracks = _tracks_from_playlist(
		[
			{
				"videoId": "abc",
				"title": "APT.",
				"artists": [{"name": "ROSE"}, {"name": "Bruno Mars"}],
				"duration_seconds": 174,
				"thumbnails": [{"url": "small.jpg", "width": 64}, {"url": "large.jpg", "width": 400}],
			}
		],
		"Pop",
	)

	assert tracks[0]["title"] == "APT."
	assert tracks[0]["artists"] == "ROSE, Bruno Mars"
	assert tracks[0]["duration_ms"] == 174000
	assert tracks[0]["cover_url"] == "large.jpg"
