import pytest

from csvmusic.core.web_playlist_import import WebPlaylistImportError, _tracks_from_entries, _validate_url


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
