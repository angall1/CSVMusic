import pytest
from csvmusic.core.release_year import release_year, metadata_year


@pytest.mark.parametrize("value, expected", [(1999, 1999), ("2001-04-12", 2001), ("2002-03", 2002), ({"year": 2003}, 2003), ({"isoString": "2004-02-03T00:00:00Z"}, 2004), (None, None), ("unknown", None), ("20201234", None), ("2020 remix", None)])
def test_release_year(value, expected):
	assert release_year(value) == expected


def test_upload_date_is_not_a_release_year():
	assert metadata_year({"upload_date": "20260101", "uploadDate": "2026-01-01", "date": "2026-01-01"}) is None


def test_spotify_track_and_album_dates():
	from csvmusic.core.spotify_import import _tracks_from_items, _tracks_from_embed_items
	track = {"name": "Song", "artists": [{"name": "Artist"}], "albumOfTrack": {"name": "Album", "date": {"year": 1998}}}
	assert _tracks_from_items([{"track": track}], "Mix")[0]["year"] == 1998
	assert _tracks_from_embed_items([{"entityType": "track", "title": "Song", "subtitle": "Artist"}], "Album", album_year=2001)[0]["year"] == 2001


def test_other_services_explicit_release_dates():
	from csvmusic.core.deezer_import import _tracks_from_items
	from csvmusic.core.amazon_music_import import _amazon_track
	from csvmusic.core.apple_music_import import _tracks_from_ld
	from csvmusic.core.youtube_music_import import _tracks_from_playlist
	assert _tracks_from_items([{"title": "Song", "album": {"release_date": "2005-03-04"}}], "Mix")[0]["year"] == 2005
	assert _amazon_track({"type": "track", "title": "Song", "artistName": "Artist", "releaseDate": "2006-04-01"}, "Mix")["year"] == 2006
	assert _tracks_from_ld({"track": [{"name": "Song", "datePublished": "2007-01-01"}]}, "Mix")[0]["year"] == 2007
	assert _tracks_from_playlist([{"videoId": "abc", "title": "Song", "artists": [{"name": "Artist"}], "year": "2008"}], "Mix")[0]["year"] == 2008


def test_rescan_preserves_known_year_but_accepts_new_year():
	from csvmusic.core.library import merge_playlist_scan
	library = {"playlists": [{"id": "test", "platform": "spotify", "name": "Mix", "tracks": [{"id": "one", "title": "Song", "artists": "Artist", "year": 1999}]}]}
	for incoming, expected in [(None, 1999), ("invalid", 1999), ("2001", 2001)]:
		result = merge_playlist_scan(library, "spotify:test", "Mix", [{"id": "one", "title": "Song", "artists": "Artist", "year": incoming}])
		assert result["tracks"][0]["year"] == expected


@pytest.mark.parametrize("extension, factory, key, expected", [("mp3", "EasyID3", "date", "1999"), ("m4a", "MP4", "\xa9day", ["1999"]), ("opus", "OggOpus", "date", ["1999"])])
def test_tag_writer_receives_release_year(monkeypatch, tmp_path, extension, factory, key, expected):
	from csvmusic.core import downloader
	class Tags(dict):
		def save(self, *args, **kwargs):
			pass
	tags = Tags()
	monkeypatch.setattr(downloader, factory, lambda path: tags)
	monkeypatch.setattr(downloader, "ID3", lambda path: tags)
	downloader.tag_file(tmp_path / ("song." + extension), {"year": 1999}, None)
	assert tags[key] == expected
