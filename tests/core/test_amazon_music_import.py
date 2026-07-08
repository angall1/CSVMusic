import json

from csvmusic.core.amazon_music_import import parse_amazon_music_page, parse_amazon_music_source


def test_parse_amazon_music_url():
	_, source_type, source_id = parse_amazon_music_source(
		"https://music.amazon.com/playlists/B012345678"
	)
	assert (source_type, source_id) == ("playlist", "B012345678")


def test_parse_amazon_embedded_track_data():
	data = {
		"playlistName": "Favorites",
		"items": [{
			"__typename": "Track",
			"id": "track-1",
			"title": "Song",
			"artistName": "Artist",
			"albumName": "Album",
			"duration": 210,
		}],
	}
	page = f'<script type="application/json">{json.dumps(data)}</script>'
	source = parse_amazon_music_page(page, "B012345678", "playlist")
	assert source.name == "Favorites"
	assert source.tracks[0]["title"] == "Song"
	assert source.tracks[0]["duration_ms"] == 210000
