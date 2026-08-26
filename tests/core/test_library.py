import pathlib

from csvmusic.core.library import (
	add_playlist_urls, clear_redownload_flag, enabled_tracks, library_status, load_library, merge_playlist_scan,
	new_library, record_library_download_result, save_library,
)
from csvmusic.core.track_output import expected_track_path


URL = "https://open.spotify.com/playlist/611N3KSs459UD5IVPH1ES4"
YOUTUBE_URL = "https://music.youtube.com/playlist?list=PLX9UXSa6UdR8"
APPLE_URL = "https://music.apple.com/us/playlist/disco-essentials/pl.88cf86bb7a8f4b5d9feb7e393e5bbc73"


def _track(track_id="one", title="Song"):
	return {"id": track_id, "title": title, "artists": "Artist", "album": "Album", "cover_url": "cover.jpg"}


def test_library_round_trip_and_add_urls(tmp_path):
	library = new_library("Test", str(tmp_path / "music"))
	added, errors = add_playlist_urls(library, [URL, URL, "invalid"])
	assert len(added) == 1
	assert len(errors) == 1
	path = tmp_path / "library.json"
	save_library(path, library)
	assert load_library(path)["playlists"][0]["id"] == "611N3KSs459UD5IVPH1ES4"


def test_add_youtube_music_and_regular_youtube_playlist_urls():
	library = new_library()
	added, errors = add_playlist_urls(library, [
		YOUTUBE_URL,
		"https://www.youtube.com/playlist?list=PLanother123",
		YOUTUBE_URL,
	])

	assert errors == []
	assert [item["platform"] for item in added] == ["youtube_music", "youtube_music"]
	assert added[0]["url"] == YOUTUBE_URL
	assert added[1]["url"] == "https://music.youtube.com/playlist?list=PLanother123"


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
