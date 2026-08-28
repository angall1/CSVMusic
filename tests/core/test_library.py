import pathlib

from csvmusic.core.library import (
	add_playlist_urls, clear_redownload_flag, edit_library_track, enabled_tracks, library_status, load_library, merge_playlist_scan,
	import_csv_playlist, new_library, record_library_download_result, rename_library_playlist, save_library,
)
from csvmusic.core.track_output import expected_track_path


URL = "https://open.spotify.com/playlist/611N3KSs459UD5IVPH1ES4"
YOUTUBE_URL = "https://music.youtube.com/playlist?list=PLX9UXSa6UdR8"
APPLE_URL = "https://music.apple.com/us/playlist/disco-essentials/pl.88cf86bb7a8f4b5d9feb7e393e5bbc73"


def _track(track_id="one", title="Song"):
	return {"id": track_id, "title": title, "artists": "Artist", "album": "Album", "cover_url": "cover.jpg"}


def test_track_metadata_edits_survive_rescan():
	library = new_library()
	added, errors = add_playlist_urls(library, [URL])
	assert added and not errors
	playlist_id = "spotify:611N3KSs459UD5IVPH1ES4"
	merge_playlist_scan(library, playlist_id, "Playlist", [_track()])
	library["playlists"][0]["tracks"][0]["last_downloaded_at"] = "2026-01-01T00:00:00+00:00"
	updated = edit_library_track(library, playlist_id, 0, "Correct Title", "Correct Album")
	assert updated["force_redownload"] is True
	merge_playlist_scan(library, playlist_id, "Playlist", [_track(title="Scraped Title")])
	rescanned = library["playlists"][0]["tracks"][0]
	assert rescanned["title"] == "Correct Title"
	assert rescanned["album"] == "Correct Album"


def test_library_round_trip_and_add_urls(tmp_path):
	library = new_library("Test", str(tmp_path / "music"))
	added, errors = add_playlist_urls(library, [URL, URL, "invalid"])
	assert len(added) == 1
	assert len(errors) == 1
	path = tmp_path / "library.json"
	save_library(path, library)
	assert load_library(path)["playlists"][0]["id"] == "611N3KSs459UD5IVPH1ES4"


def test_csv_is_imported_directly_and_refreshes_same_library_playlist(tmp_path):
	path = tmp_path / "Road Trip.csv"
	path.write_text(
		"Track name,Artist name,Playlist name,Cover URL\n"
		"First Song,First Artist,Road Trip,https://example.com/first.jpg\n",
		encoding="utf-8",
	)
	library = new_library()

	playlist, created = import_csv_playlist(library, path)

	assert created is True
	assert playlist["platform"] == "csv"
	assert playlist["name"] == "Road Trip"
	assert playlist["last_scanned_at"]
	assert playlist["tracks"][0]["cover_url"] == "https://example.com/first.jpg"
	playlist["tracks"][0]["enabled"] = False
	path.write_text(
		"Track name,Artist name,Playlist name,Cover URL\n"
		"First Song,First Artist,Road Trip,https://example.com/first.jpg\n"
		"Second Song,Second Artist,Road Trip,https://example.com/second.jpg\n",
		encoding="utf-8",
	)

	refreshed, created = import_csv_playlist(library, path)

	assert created is False
	assert len(library["playlists"]) == 1
	assert len(refreshed["tracks"]) == 2
	assert refreshed["tracks"][0]["enabled"] is False
	assert refreshed["last_diff"] == {"added": 1, "removed": 0, "unchanged": 1}


def test_add_youtube_music_and_reject_regular_youtube_playlist_urls():
	library = new_library()
	added, errors = add_playlist_urls(library, [
		YOUTUBE_URL,
		"https://www.youtube.com/playlist?list=PLanother123",
		YOUTUBE_URL,
	])

	assert len(errors) == 1
	assert "Standard YouTube playlists are not supported" in errors[0]
	assert [item["platform"] for item in added] == ["youtube_music"]
	assert added[0]["url"] == YOUTUBE_URL


def test_add_apple_music_playlist_url():
	library = new_library()
	added, errors = add_playlist_urls(library, [APPLE_URL, APPLE_URL])

	assert errors == []
	assert len(added) == 1
	assert added[0]["platform"] == "apple_music"
	assert added[0]["id"] == "pl.88cf86bb7a8f4b5d9feb7e393e5bbc73"
	assert added[0]["url"] == APPLE_URL


def test_youtube_scan_preserves_video_as_download_match():
	library = new_library()
	add_playlist_urls(library, [YOUTUBE_URL])
	playlist = merge_playlist_scan(
		library,
		"youtube_music:PLX9UXSa6UdR8",
		"YouTube Mix",
		[{"youtube_video_id": "video123", "title": "Song", "artists": "Artist"}],
	)

	assert playlist["tracks"][0]["preferred_video_id"] == "video123"
	assert enabled_tracks(library, {"youtube_music:PLX9UXSa6UdR8"})[0]["library_playlist_id"] == "youtube_music:PLX9UXSa6UdR8"


def test_rescan_preserves_selection_and_override():
	library = new_library()
	add_playlist_urls(library, [URL])
	playlist = merge_playlist_scan(library, "611N3KSs459UD5IVPH1ES4", "Mix", [_track("one"), _track("two")], reported_total=2)
	playlist["tracks"][0]["enabled"] = False
	playlist["tracks"][1]["preferred_video_id"] = "youtube-id"
	playlist = merge_playlist_scan(library, "611N3KSs459UD5IVPH1ES4", "Mix", [_track("two"), _track("three")], reported_total=2)
	assert playlist["last_diff"] == {"added": 1, "removed": 1, "unchanged": 1}
	assert playlist["tracks"][0]["preferred_video_id"] == "youtube-id"
	assert [track["sp_id"] for track in enabled_tracks(library)] == ["two", "three"]


def test_rename_playlist_updates_folder_m3u_tracks_and_survives_rescan(tmp_path):
	library = new_library(output_dir=str(tmp_path))
	add_playlist_urls(library, [URL])
	playlist = merge_playlist_scan(library, "611N3KSs459UD5IVPH1ES4", "Old Mix", [_track("one")])
	old_folder = tmp_path / "Old Mix"
	old_folder.mkdir()
	(old_folder / "Old Mix.m3u8").write_text(
		"#EXTM3U\n#EXTPLAYLIST:Old Mix\nArtist - Song.mp3\n",
		encoding="utf-8",
	)

	renamed, folder = rename_library_playlist(library, "spotify:611N3KSs459UD5IVPH1ES4", "New Mix", tmp_path)

	assert folder == tmp_path / "New Mix"
	assert not old_folder.exists()
	assert (folder / "New Mix.m3u8").read_text(encoding="utf-8").splitlines()[1] == "#EXTPLAYLIST:New Mix"
	assert renamed["tracks"][0]["playlist"] == "New Mix"
	renamed = merge_playlist_scan(library, "611N3KSs459UD5IVPH1ES4", "Remote Name", [_track("one")])
	assert renamed["name"] == "New Mix"
	assert renamed["tracks"][0]["playlist"] == "New Mix"


def test_rename_playlist_refuses_another_playlist_folder_name(tmp_path):
	library = new_library(output_dir=str(tmp_path))
	add_playlist_urls(library, [URL, "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"])
	library["playlists"][0]["name"] = "First"
	library["playlists"][1]["name"] = "Existing Name"

	try:
		rename_library_playlist(library, "spotify:611N3KSs459UD5IVPH1ES4", "Existing Name", tmp_path)
	except ValueError as exc:
		assert "already uses" in str(exc)
	else:
		raise AssertionError("Expected playlist-name collision to be rejected")


def test_rescan_saves_and_preserves_playlist_cover():
	library = new_library()
	add_playlist_urls(library, [URL])
	playlist = merge_playlist_scan(
		library,
		"611N3KSs459UD5IVPH1ES4",
		"Mix",
		[_track("one")],
		cover_url="https://i.scdn.co/image/custom-playlist-cover",
	)
	assert playlist["cover_url"] == "https://i.scdn.co/image/custom-playlist-cover"

	playlist = merge_playlist_scan(library, "611N3KSs459UD5IVPH1ES4", "Mix", [_track("one")])
	assert playlist["cover_url"] == "https://i.scdn.co/image/custom-playlist-cover"


def test_library_status_uses_real_output_files(tmp_path):
	library = new_library()
	add_playlist_urls(library, [URL])
	playlist = merge_playlist_scan(library, "611N3KSs459UD5IVPH1ES4", "Mix", [_track("one"), _track("two", "Other Song")])
	playlist["tracks"][1]["enabled"] = False
	track = enabled_tracks(library)[0]
	path = expected_track_path(track, pathlib.Path(tmp_path), "m4a")
	path.parent.mkdir(parents=True)
	path.write_bytes(b"audio")
	status = library_status(library, tmp_path, "m4a")
	assert status["totals"] == {"enabled": 2, "downloaded": 1, "missing": 1, "disabled": 0, "redownload": 0}


def test_successful_replacement_clears_redownload_flag(tmp_path):
	library = new_library()
	add_playlist_urls(library, [URL])
	playlist = merge_playlist_scan(library, "611N3KSs459UD5IVPH1ES4", "Mix", [_track("one")])
	playlist["tracks"][0]["force_redownload"] = True
	path = tmp_path / "library.json"
	save_library(path, library)

	clear_redownload_flag(path, "611N3KSs459UD5IVPH1ES4", playlist["tracks"][0])

	assert load_library(path)["playlists"][0]["tracks"][0]["force_redownload"] is False


def test_redownload_flag_does_not_make_existing_file_missing(tmp_path):
	library = new_library()
	add_playlist_urls(library, [URL])
	playlist = merge_playlist_scan(library, "611N3KSs459UD5IVPH1ES4", "Mix", [_track("one")])
	playlist["tracks"][0]["force_redownload"] = True
	track = enabled_tracks(library)[0]
	path = expected_track_path(track, pathlib.Path(tmp_path), "m4a")
	path.parent.mkdir(parents=True)
	path.write_bytes(b"audio")

	status = library_status(library, tmp_path, "m4a")["totals"]

	assert status == {"enabled": 1, "downloaded": 1, "missing": 0, "disabled": 0, "redownload": 1}


def test_library_download_error_is_recorded_and_cleared_on_success(tmp_path):
	library = new_library()
	add_playlist_urls(library, [URL])
	playlist = merge_playlist_scan(library, "611N3KSs459UD5IVPH1ES4", "Mix", [_track("one")])
	path = tmp_path / "library.json"
	save_library(path, library)

	record_library_download_result(path, "spotify:611N3KSs459UD5IVPH1ES4", playlist["tracks"][0], downloaded=False, error="yt-dlp failed")
	failed = load_library(path)["playlists"][0]["tracks"][0]
	assert failed["last_error"] == "yt-dlp failed"
	assert failed["last_error_at"]
	library = load_library(path)
	merge_playlist_scan(library, "spotify:611N3KSs459UD5IVPH1ES4", "Mix", [_track("one")])
	save_library(path, library)
	failed = load_library(path)["playlists"][0]["tracks"][0]
	assert failed["last_error"] == "yt-dlp failed"

	record_library_download_result(
		path,
		"spotify:611N3KSs459UD5IVPH1ES4",
		failed,
		downloaded=True,
		match={"videoId": "video-one", "title": "Actual YouTube Video", "author": "Uploader"},
	)
	completed = load_library(path)["playlists"][0]["tracks"][0]
	assert completed["last_error"] is None
	assert completed["last_downloaded_at"]
	assert completed["downloaded_video_title"] == "Actual YouTube Video"
	assert completed["downloaded_video_publisher"] == "Uploader"
