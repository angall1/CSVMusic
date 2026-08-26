import pathlib

from csvmusic.core.library import (
	add_playlist_urls, clear_redownload_flag, enabled_tracks, library_status, load_library, merge_playlist_scan,
	new_library, save_library,
)
from csvmusic.core.track_output import expected_track_path


URL = "https://open.spotify.com/playlist/611N3KSs459UD5IVPH1ES4"


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
	playlist = merge_playlist_scan(library, "611N3KSs459UD5IVPH1ES4", "Mix", [_track("one"), _track("two")])
	playlist["tracks"][1]["enabled"] = False
	track = enabled_tracks(library)[0]
	path = expected_track_path(track, pathlib.Path(tmp_path), "m4a")
	path.parent.mkdir(parents=True)
	path.write_bytes(b"audio")
	status = library_status(library, tmp_path, "m4a")
	assert status["totals"] == {"enabled": 1, "downloaded": 1, "missing": 0, "disabled": 1, "redownload": 0}


def test_successful_replacement_clears_redownload_flag(tmp_path):
	library = new_library()
	add_playlist_urls(library, [URL])
	playlist = merge_playlist_scan(library, "611N3KSs459UD5IVPH1ES4", "Mix", [_track("one")])
	playlist["tracks"][0]["force_redownload"] = True
	path = tmp_path / "library.json"
	save_library(path, library)

	clear_redownload_flag(path, "611N3KSs459UD5IVPH1ES4", playlist["tracks"][0])

	assert load_library(path)["playlists"][0]["tracks"][0]["force_redownload"] is False
