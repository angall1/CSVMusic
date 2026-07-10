import base64
import json

import pytest

from csvmusic.core.spotify_import import (
	SpotifyPlaylistNotFoundError,
	parse_spotify_playlist_id,
	parse_spotify_source,
	parse_spotify_playlist_page,
	parse_spotify_page,
	parse_spotify_embed_page,
	SpotifySource,
)


def _page(state):
	encoded = base64.b64encode(json.dumps(state).encode("utf-8")).decode("ascii")
	return f'<html><script id="initialState">{encoded}</script></html>'


def _embed_page(entity):
	return f'<html><script id="__NEXT_DATA__">{json.dumps({"props": {"pageProps": {"state": {"data": {"entity": entity}}}}})}</script></html>'


def test_parse_spotify_playlist_id_from_url():
	assert parse_spotify_playlist_id("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=abc") == "37i9dQZF1DXcBWIGoYBM5M"


def test_parse_spotify_source_from_album_url():
	source = parse_spotify_source("https://open.spotify.com/album/584Igcr5ixQUeE4rHIPN9c?trackId=4iHlEMh9a32EDOoQk2lQGt")

	assert source.type == "album"
	assert source.id == "584Igcr5ixQUeE4rHIPN9c"


def test_parse_spotify_playlist_page_tracks():
	state = {
		"entities": {
			"items": {
				"spotify:playlist:37i9dQZF1DXcBWIGoYBM5M": {
					"__typename": "Playlist",
					"id": "37i9dQZF1DXcBWIGoYBM5M",
					"name": "Today",
					"content": {
						"totalCount": 1,
						"items": [
							{
								"itemV2": {
									"data": {
										"__typename": "Track",
										"name": "Song",
										"uri": "spotify:track:1234567890abcdef",
										"duration": {"totalMilliseconds": 123000},
										"albumOfTrack": {
											"name": "Album",
											"coverArt": {
												"sources": [
													{"url": "small.jpg", "width": 64},
													{"url": "large.jpg", "width": 640},
												]
											},
										},
										"artists": {
											"items": [
												{"profile": {"name": "Artist One"}},
												{"profile": {"name": "Artist Two"}},
											]
										},
										"externalIds": {"isrc": "USABC1234567"},
									}
								}
							}
						],
					},
				}
			}
		}
	}

	playlist = parse_spotify_playlist_page(_page(state), "37i9dQZF1DXcBWIGoYBM5M")

	assert playlist.name == "Today"
	assert playlist.total_count == 1
	assert playlist.tracks == [
		{
			"title": "Song",
			"artists": "Artist One, Artist Two",
			"album": "Album",
			"playlist": "Today",
			"isrc": "USABC1234567",
			"sp_id": "1234567890abcdef",
			"duration_ms": 123000,
			"year": None,
			"cover_url": "large.jpg",
			"track_no": 1,
			"disc_no": 1,
		}
	]


def test_parse_spotify_playlist_page_missing_playlist_message():
	state = {"entities": {"items": {}}}

	with pytest.raises(SpotifyPlaylistNotFoundError, match="Could not find playlist. Is it public\\?"):
		parse_spotify_playlist_page(_page(state), "37i9dQZF1DXcBWIGoYBM5M")


def test_parse_spotify_playlist_page_warns_when_partial():
	state = {
		"entities": {
			"items": {
				"spotify:playlist:37i9dQZF1DXcBWIGoYBM5M": {
					"__typename": "Playlist",
					"id": "37i9dQZF1DXcBWIGoYBM5M",
					"name": "Long Playlist",
					"content": {
						"totalCount": 2,
						"items": [
							{
								"itemV2": {
									"data": {
										"__typename": "Track",
										"name": "Song",
										"uri": "spotify:track:1234567890abcdef",
										"artists": {"items": [{"profile": {"name": "Artist"}}]},
									}
								}
							}
						],
					},
				}
			}
		}
	}

	playlist = parse_spotify_playlist_page(_page(state), "37i9dQZF1DXcBWIGoYBM5M")

	assert "Spotify only let CSVMusic load 1 of 2 playlist tracks from this link" in playlist.warning
	assert "the missing tracks will be skipped" in playlist.warning
	assert "Open TuneMyMusic from CSVMusic" in playlist.warning
	assert "Export the playlist as a CSV file" in playlist.warning
	assert "Back in CSVMusic, choose CSV File and load that CSV" in playlist.warning


def test_parse_spotify_playlist_page_warns_when_exactly_100_tracks():
	items = []
	for index in range(100):
		items.append({
			"itemV2": {
				"data": {
					"__typename": "Track",
					"name": f"Song {index}",
					"uri": f"spotify:track:{index:016d}",
					"artists": {"items": [{"profile": {"name": "Artist"}}]},
				}
			}
		})
	state = {
		"entities": {
			"items": {
				"spotify:playlist:37i9dQZF1DXcBWIGoYBM5M": {
					"__typename": "Playlist",
					"id": "37i9dQZF1DXcBWIGoYBM5M",
					"name": "Possibly Capped",
					"content": {
						"totalCount": 100,
						"items": items,
					},
				}
			}
		}
	}

	playlist = parse_spotify_playlist_page(_page(state), "37i9dQZF1DXcBWIGoYBM5M")

	assert len(playlist.tracks) == 100
	assert "Spotify only let CSVMusic load 100 playlist tracks from this link" in playlist.warning
	assert "If the original playlist has more tracks than this" in playlist.warning
	assert "Open TuneMyMusic from CSVMusic" in playlist.warning


def test_parse_spotify_album_page_tracks():
	state = {
		"entities": {
			"items": {
				"spotify:album:584Igcr5ixQUeE4rHIPN9c": {
					"__typename": "Album",
					"id": "584Igcr5ixQUeE4rHIPN9c",
					"name": "Portal 2",
					"coverArt": {
						"sources": [
							{"url": "small.jpg", "width": 64},
							{"url": "large.jpg", "width": 640},
						]
					},
					"tracksV2": {
						"items": [
							{
								"track": {
									"__typename": "Track",
									"name": "Science Is Fun",
									"uri": "spotify:track:5OdZJPQCR624D4yq7UVUNx",
									"duration": {"totalMilliseconds": 156066},
									"trackNumber": 1,
									"discNumber": 1,
									"artists": {
										"items": [
											{"profile": {"name": "Aperture Science Psychoacoustic Laboratories"}}
										]
									},
								}
							}
						],
					},
				}
			}
		}
	}

	album = parse_spotify_page(_page(state), SpotifySource("album", "584Igcr5ixQUeE4rHIPN9c"))

	assert album.source_type == "album"
	assert album.name == "Portal 2"
	assert album.tracks[0]["title"] == "Science Is Fun"
	assert album.tracks[0]["album"] == "Portal 2"
	assert album.tracks[0]["cover_url"] == "large.jpg"


def test_parse_spotify_embed_album_page_tracks():
	entity = {
		"type": "album",
		"id": "584Igcr5ixQUeE4rHIPN9c",
		"title": "Portal 2",
		"coverArt": {"sources": [{"url": "cover.jpg", "width": 640}]},
		"trackList": [
			{
				"uri": "spotify:track:5OdZJPQCR624D4yq7UVUNx",
				"title": "Science Is Fun",
				"subtitle": "Aperture Science Psychoacoustic Laboratories",
				"duration": 156066,
				"entityType": "track",
			}
		],
	}

	album = parse_spotify_embed_page(_embed_page(entity), SpotifySource("album", "584Igcr5ixQUeE4rHIPN9c"))

	assert album.source_type == "album"
	assert album.tracks[0]["title"] == "Science Is Fun"
	assert album.tracks[0]["album"] == "Portal 2"
	assert album.tracks[0]["cover_url"] == "cover.jpg"


def test_parse_spotify_embed_playlist_warns_when_exactly_100_tracks():
	entity = {
		"type": "playlist",
		"id": "37i9dQZF1DXcBWIGoYBM5M",
		"title": "Possibly Capped",
		"trackCount": 100,
		"trackList": [
			{
				"uri": f"spotify:track:{index:016d}",
				"title": f"Song {index}",
				"subtitle": "Artist",
				"duration": 180000,
				"entityType": "track",
			}
			for index in range(100)
		],
	}

	playlist = parse_spotify_embed_page(_embed_page(entity), SpotifySource("playlist", "37i9dQZF1DXcBWIGoYBM5M"))

	assert len(playlist.tracks) == 100
	assert "Spotify only let CSVMusic load 100 playlist tracks from this link" in playlist.warning
	assert "If the original playlist has more tracks than this" in playlist.warning
	assert "Open TuneMyMusic from CSVMusic" in playlist.warning
