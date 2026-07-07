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
