from csvmusic.core.deezer_import import fetch_deezer_source, parse_deezer_source


class _Response:
	def __init__(self, data):
		self._data = data

	def raise_for_status(self):
		pass

	def json(self):
		return self._data


class _Session:
	def get(self, url, timeout):
		if url.endswith("/playlist/123"):
			return _Response({
				"title": "Road Trip",
				"tracks": {
					"data": [{"id": 1, "title": "First", "artist": {"name": "One"}, "duration": 180}],
					"next": "https://api.deezer.com/playlist/123/tracks?index=1",
					"total": 2,
				},
			})
		return _Response({
			"data": [{"id": 2, "title": "Second", "artist": {"name": "Two"}, "duration": 200}],
		})


def test_parse_deezer_album_url():
	assert parse_deezer_source("https://www.deezer.com/us/album/456?utm_source=x") == ("album", "456")


def test_fetch_deezer_playlist_follows_track_pages():
	source = fetch_deezer_source("https://www.deezer.com/playlist/123", session=_Session())
	assert source.name == "Road Trip"
	assert source.total_count == 2
	assert [track["title"] for track in source.tracks] == ["First", "Second"]
