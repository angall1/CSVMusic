from csvmusic.core.spotify_api import fetch_spotify_playlist_api, fetch_spotify_user_playlists


class Response:
	def __init__(self, data, status_code=200, headers=None):
		self.data = data
		self.status_code = status_code
		self.headers = headers or {}

	def json(self):
		return self.data


class Session:
	def __init__(self, responses):
		self.responses = list(responses)
		self.calls = []

	def get(self, url, **kwargs):
		self.calls.append((url, kwargs))
		return self.responses.pop(0)


def test_fetch_spotify_playlist_api_maps_metadata_and_paginates():
	session = Session([
		Response({"id": "37i9dQZF1DXcBWIGoYBM5M", "name": "Today", "tracks": {"total": 1}}),
		Response({
			"total": 1,
			"next": None,
			"items": [{"item": {
				"type": "track",
				"id": "1234567890abcdef",
				"name": "Song",
				"artists": [{"name": "Artist One"}, {"name": "Artist Two"}],
				"duration_ms": 123000,
				"track_number": 4,
				"disc_number": 1,
				"external_ids": {"isrc": "USABC1234567"},
				"album": {
					"name": "Album",
					"release_date": "2024-06-01",
					"images": [{"url": "cover.jpg"}],
				},
			}}],
		}),
	])

	playlist = fetch_spotify_playlist_api(
		"https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
		"test-token",
		session=session,
	)

	assert playlist.name == "Today"
	assert playlist.total_count == 1
	assert playlist.tracks[0] == {
		"title": "Song",
		"artists": "Artist One, Artist Two",
		"album": "Album",
		"playlist": "Today",
		"isrc": "USABC1234567",
		"sp_id": "1234567890abcdef",
		"duration_ms": 123000,
		"year": 2024,
		"cover_url": "cover.jpg",
		"track_no": 4,
		"disc_no": 1,
	}
	assert session.calls[0][1]["headers"] == {"Authorization": "Bearer test-token"}
	assert session.calls[1][1]["params"] == {"limit": 50, "offset": 0}


def test_fetch_spotify_user_playlists_maps_and_paginates():
	session = Session([Response({
		"next": None,
		"items": [{
			"id": "playlist-id",
			"name": "Road Trip",
			"owner": {"display_name": "Austin"},
			"items": {"total": 42},
			"public": False,
			"collaborative": True,
			"external_urls": {"spotify": "https://open.spotify.com/playlist/playlist-id"},
		}],
	})])

	playlists = fetch_spotify_user_playlists("test-token", session=session)

	assert playlists == [{
		"id": "playlist-id",
		"name": "Road Trip",
		"owner": "Austin",
		"total": 42,
		"public": False,
		"collaborative": True,
		"url": "https://open.spotify.com/playlist/playlist-id",
	}]
	assert session.calls[0][1]["params"] == {"limit": 50, "offset": 0}
