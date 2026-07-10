import csvmusic.core.youtube_music_import as youtube_music_import
from csvmusic.core.youtube_music_import import fetch_youtube_music_source, parse_youtube_playlist_id, _tracks_from_playlist


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


def test_fetch_youtube_music_playlist_requests_all_tracks(monkeypatch):
	calls = []

	class _YTMusic:
		def get_playlist(self, playlist_id, limit=None):
			calls.append((playlist_id, limit))
			return {
				"title": "Long List",
				"trackCount": 150,
				"tracks": [
					{
						"videoId": str(index),
						"title": f"Song {index}",
						"artists": [{"name": "Artist"}],
						"duration_seconds": 180,
					}
					for index in range(150)
				],
			}

	monkeypatch.setattr(youtube_music_import, "YTMusic", _YTMusic)

	source = fetch_youtube_music_source("https://music.youtube.com/playlist?list=PLabc123")

	assert calls == [("PLabc123", None)]
	assert len(source.tracks) == 150
	assert source.warning is None


def test_fetch_youtube_music_warns_when_partial(monkeypatch):
	class _YTMusic:
		def get_playlist(self, playlist_id, limit=None):
			return {
				"title": "Partial List",
				"trackCount": 2,
				"tracks": [{
					"videoId": "abc",
					"title": "Song",
					"artists": [{"name": "Artist"}],
				}],
			}

	monkeypatch.setattr(youtube_music_import, "YTMusic", _YTMusic)

	source = fetch_youtube_music_source("https://music.youtube.com/playlist?list=PLabc123")

	assert "YouTube Music only let CSVMusic load 1 of 2 playlist tracks from this link" in source.warning
	assert "Export the playlist as a CSV file" in source.warning
