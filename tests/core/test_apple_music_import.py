import html
import json

from csvmusic.core.apple_music_import import parse_apple_music_page


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
	assert source.tracks[0]["duration_ms"] == 190533
	assert source.tracks[0]["cover_url"] == "https://example.com/1200x1200bb.jpg"
