import json

import pytest

from csvmusic.core.amazon_music_import import (
	parse_amazon_music_page,
	parse_amazon_music_source,
	parse_amazon_music_web_player,
)


def test_parse_amazon_music_url():
	_, source_type, source_id = parse_amazon_music_source(
		"https://music.amazon.com/playlists/B012345678"
	)
	assert (source_type, source_id) == ("playlist", "B012345678")


def test_parse_regional_amazon_user_playlist_url():
	_, source_type, source_id = parse_amazon_music_source(
		"https://music.amazon.com.au/user-playlists/daea9ffc0295452eba17c71d124ec636a0u0?ref=share"
	)
	assert (source_type, source_id) == ("playlist", "daea9ffc0295452eba17c71d124ec636a0u0")


@pytest.mark.parametrize("host", [
	"music.amazon.com",
	"music.amazon.co.uk",
	"music.amazon.de",
	"music.amazon.ca",
	"music.amazon.co.jp",
	"music.amazon.com.br",
	"music.amazon.com.mx",
])
def test_parse_amazon_user_playlist_domains(host):
	_, source_type, source_id = parse_amazon_music_source(
		f"https://{host}/user-playlists/shared123?ref=share"
	)
	assert (source_type, source_id) == ("playlist", "shared123")


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
	assert "Amazon Music only let CSVMusic load 1 playlist tracks from this link" in source.warning
	assert "If the original playlist has more tracks than this" in source.warning


def test_parse_amazon_web_player_rows():
	data = {
		"methods": [{
			"template": {
				"interface": "Web.TemplatesInterface.v1_0.Touch.DetailTemplateInterface.DetailTemplate",
				"headerText": {"text": "Old music"},
				"headerImage": "https://example.com/playlist.jpg",
				"templateData": {"deeplink": "/user-playlists/shared-id"},
				"widgets": [{
					"items": [{
						"interface": "Web.TemplatesInterface.v1_0.Touch.WidgetsInterface.VisualRowItemElement",
						"id": "B012345678",
						"primaryText": "Song",
						"secondaryText1": "Artist",
						"secondaryText2": "Album",
						"secondaryText3": "04:52",
						"image": "https://example.com/song.jpg",
						"primaryLink": {"deeplink": "/albums/B000000000?trackAsin=B012345678"},
					}],
				}],
			},
		}],
	}
	source = parse_amazon_music_web_player(data, "shared-id", "playlist")
	assert source.name == "Old music"
	assert source.total_count == 1
	assert source.tracks[0]["artists"] == "Artist"
	assert source.tracks[0]["duration_ms"] == 292000
