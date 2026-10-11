import html
import json

from csvmusic.core.apple_music_import import parse_apple_music_page, parse_apple_music_source_url
from csvmusic.core.apple_music_import import _fetch_catalog_tracks, AppleMusicImportError
import pytest


def test_parse_apple_music_playlist_url():
	url = "https://music.apple.com/us/playlist/disco-essentials/pl.88cf86bb7a8f4b5d9feb7e393e5bbc73"
	assert parse_apple_music_source_url(url) == (
		"playlist",
		"pl.88cf86bb7a8f4b5d9feb7e393e5bbc73",
		url,
	)


def test_parse_apple_music_server_data_tracks():
	server = {
		"data": [
			{
				"data": {
					"sections": [
						{
							"items": [
								{
									"title": "Today\u2019s Hits",
									"contentDescriptor": {"kind": "playlist", "identifiers": {"storeAdamID": "pl.abc"}},
								},
								{
									"id": "track-lockup - pl.abc - 12345",
									"title": "Look at My Life",
									"artistName": "Gracie Abrams",
									"tertiaryLinks": [{"title": "The Secret of Us"}],
									"duration": 190533,
									"artwork": {
										"dictionary": {
											"url": "https://example.com/{w}x{h}bb.{f}",
											"width": 3000,
											"height": 3000,
										}
									},
									"contentDescriptor": {
										"kind": "song",
										"identifiers": {"storeAdamID": "12345"},
									},
								},
							]
						}
					]
				}
			}
		]
	}
	ld = {"@type": "MusicPlaylist", "name": "Today\u2019s Hits", "numTracks": 1}
	page = (
		"<html>"
		f"<script id=\"serialized-server-data\">{html.escape(json.dumps(server))}</script>"
		f"<script type=\"application/ld+json\">{html.escape(json.dumps(ld))}</script>"
		"</html>"
	)

	source = parse_apple_music_page(page, "https://music.apple.com/us/playlist/todays-hits/pl.abc")

	assert source.name == "Today\u2019s Hits"
	assert source.total_count == 1
	assert source.tracks[0]["title"] == "Look at My Life"
	assert source.tracks[0]["artists"] == "Gracie Abrams"
	assert source.tracks[0]["album"] == "The Secret of Us"
	assert source.tracks[0]["duration_ms"] == 190533
	assert source.tracks[0]["cover_url"] == "https://example.com/1200x1200bb.jpg"


def test_parse_apple_music_warns_when_partial():
	server = {
		"data": [{
			"items": [{
				"title": "One",
				"artistName": "Artist",
				"contentDescriptor": {"kind": "song", "identifiers": {"storeAdamID": "1"}},
			}]
		}]
	}
	ld = {"@type": "MusicPlaylist", "name": "Apple List", "numTracks": 2}
	page = (
		"<html>"
		f"<script id=\"serialized-server-data\">{html.escape(json.dumps(server))}</script>"
		f"<script type=\"application/ld+json\">{html.escape(json.dumps(ld))}</script>"
		"</html>"
	)

	source = parse_apple_music_page(page, "https://music.apple.com/us/playlist/apple-list/pl.abc")

	assert "Apple Music only let CSVMusic load 1 of 2 playlist tracks from this link" in source.warning
	assert "Export the playlist as a CSV file" in source.warning


class _Response:
	status_code = 200
	text = "eyJpublic.test.signature"

	def __init__(self, data=None):
		self.data = data

	def raise_for_status(self):
		pass

	def json(self):
		return self.data


def test_catalog_pagination_keeps_all_tracks_and_repeated_songs():
	class Client:
		def __init__(self):
			self.calls = []

		def get(self, url, **kwargs):
			self.calls.append(url)
			if "/assets/" in url:
				return _Response()
			offset = 300 if "offset=300" in url else 0
			data = {"data": [{"id": "same-song", "type": "songs", "attributes": {
				"name": f"Song {i}", "artistName": "Artist", "durationInMillis": 1000,
			}} for i in range(offset, offset + (25 if offset else 300))]}
			if not offset:
				data["next"] = "/v1/catalog/us/playlists/pl.example/tracks?offset=300"
			return _Response(data)

	client = Client()
	tracks = _fetch_catalog_tracks(client, '<script src="/assets/index~test.js"></script>',
		"https://music.apple.com/us/playlist/test/pl.example", "Test", 20)
	assert len(tracks) == 325
	assert tracks[-1]["track_no"] == 325
	assert tracks[-1]["title"] == "Song 324"
	assert len(client.calls) == 3


@pytest.mark.parametrize("next_page", ["https://example.com/steal", "/v1/catalog/us/playlists/pl.example/tracks?limit=100"])
def test_catalog_rejects_external_or_looping_pagination(next_page):
	class Client:
		def get(self, url, **kwargs):
			return _Response() if "/assets/" in url else _Response({"data": [], "next": next_page})

	with pytest.raises(AppleMusicImportError):
		_fetch_catalog_tracks(Client(), '<script src="/assets/index~test.js"></script>',
			"https://music.apple.com/us/playlist/test/pl.example", "Test", 20)


@pytest.mark.parametrize("failure", [False, True])
def test_fetch_attempts_pagination_and_keeps_partial_warning_on_failure(monkeypatch, failure):
	from csvmusic.core import apple_music_import as module
	url = "https://music.apple.com/us/playlist/test/pl.example"
	source = module.AppleMusicSource("pl.example", "Test", [{}] * 300, total_count=325, warning="Partial")
	monkeypatch.setattr(module, "parse_apple_music_page", lambda *args: source)

	def fetch(*args):
		if failure:
			raise module.AppleMusicImportError("Unavailable")
		return [{}] * 325

	monkeypatch.setattr(module, "_fetch_catalog_tracks", fetch)
	class Client:
		def get(self, *args, **kwargs):
			from types import SimpleNamespace
			return SimpleNamespace(status_code=200, content=b"<html></html>")

	result = module.fetch_apple_music_source(url, session=Client())
	assert len(result.tracks) == (300 if failure else 325)
	assert bool(result.warning) is failure
