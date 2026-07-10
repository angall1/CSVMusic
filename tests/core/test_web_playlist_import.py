import csvmusic.core.web_playlist_import as web_playlist_import
import pytest

from csvmusic.core.web_playlist_import import WebPlaylistImportError, fetch_web_playlist, _tracks_from_entries, _validate_url


def test_regular_youtube_requires_playlist_id():
	assert _validate_url("https://www.youtube.com/playlist?list=PLabc", "YouTube")
	with pytest.raises(WebPlaylistImportError):
		_validate_url("https://www.youtube.com/watch?v=abc", "YouTube")


def test_soundcloud_requires_set_url():
	assert _validate_url("https://soundcloud.com/artist/sets/my-list", "SoundCloud")
	with pytest.raises(WebPlaylistImportError):
		_validate_url("https://soundcloud.com/artist/song", "SoundCloud")


def test_web_entries_are_normalized():
	tracks = _tracks_from_entries([
		{"id": "a", "title": "Artist - Track (Official Audio)", "duration": 123, "thumbnail": "cover"},
	], "List")
	assert tracks[0]["artists"] == "Artist"
	assert tracks[0]["title"] == "Track"
	assert tracks[0]["duration_ms"] == 123000


def test_web_playlist_warns_when_partial(monkeypatch):
	class _YoutubeDL:
		def __init__(self, options):
			pass

		def __enter__(self):
			return self

		def __exit__(self, exc_type, exc, tb):
			return False

		def extract_info(self, url, download=False):
			return {
				"id": "PLabc",
				"title": "Video List",
				"playlist_count": 2,
				"entries": [{"id": "a", "title": "Artist - Track"}],
			}

	monkeypatch.setattr(web_playlist_import, "YoutubeDL", _YoutubeDL)

	source = fetch_web_playlist("https://www.youtube.com/playlist?list=PLabc", "YouTube")

	assert "YouTube only let CSVMusic load 1 of 2 playlist tracks from this link" in source.warning
	assert "Export the playlist as a CSV file" in source.warning
