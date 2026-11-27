from pathlib import Path
from csvmusic.core.library import write_library_playlists


def test_manifest_rebuild_preserves_order_duplicates_and_actual_paths(tmp_path):
	root = tmp_path / "music"
	folder = root / "Mix"
	folder.mkdir(parents=True)
	first = folder / "07- Artist - First.mp3"
	second = folder / "Artist - Second.mp3"
	first.write_bytes(b"audio")
	second.write_bytes(b"audio")
	one = {"title": "First", "artists": "Artist", "album": "Album", "downloaded_path": str(first)}
	two = {"title": "Second", "artists": "Artist", "album": "Album"}
	playlist = {"id": "mix", "platform": "spotify", "name": "Mix", "tracks": [two, one, two, dict(one, enabled=False), {"title": "Missing", "artists": "Artist", "album": "Album"}]}
	library = {"output_dir": str(root), "format": "mp3", "playlists": [playlist]}
	settings = {"m3u_output_dir": str(tmp_path / "lists"), "write_m3u_plain": True}
	files = write_library_playlists(library, {"spotify:mix"}, settings)
	assert len(files) == 2
	entries = [line for line in files[0].read_text().splitlines() if not line.startswith("#")]
	assert entries == ["../music/Mix/Artist - Second.mp3", "../music/Mix/07- Artist - First.mp3", "../music/Mix/Artist - Second.mp3"]
	# Refresh removes old entries, including when the remote playlist becomes empty.
	playlist["tracks"] = []
	write_library_playlists(library, {"spotify:mix"}, settings)
	assert not [line for line in files[0].read_text().splitlines() if not line.startswith("#")]
	files[0].unlink()
	write_library_playlists(library, {"spotify:mix"}, settings)
	assert files[0].is_file()


def test_manifest_settings_disabled_do_not_write(tmp_path):
	library = {"output_dir": str(tmp_path), "playlists": [{"id": "test", "name": "Mix", "tracks": []}]}
	assert write_library_playlists(library, {"test"}, {"write_m3u8": False, "write_m3u_plain": False}) == []
	assert not list(tmp_path.iterdir())
