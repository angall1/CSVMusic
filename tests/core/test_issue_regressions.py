# tabs only
from csvmusic.core.artwork import artwork_download_urls
from csvmusic.core.library import library_track_path


def test_recovers_numbered_file_after_old_rescan(tmp_path):
	track = {"playlist": "List", "artists": "Artist", "title": "Song"}
	folder = tmp_path / "List"
	folder.mkdir()
	path = folder / "023- Artist - Song.mp3"
	path.write_bytes(b"audio")
	assert library_track_path(track, tmp_path, "mp3") == path
	assert not library_track_path(track, tmp_path, "m4a").exists()


def test_ambiguous_numbered_files_are_not_guessed(tmp_path):
	track = {"playlist": "List", "artists": "Artist", "title": "Song"}
	folder = tmp_path / "List"
	folder.mkdir()
	for name in ("01- Artist - Song.mp3", "02- Artist - Song.mp3"):
		(folder / name).write_bytes(b"audio")
	assert not library_track_path(track, tmp_path, "mp3").exists()


def test_small_spotify_art_prefers_full_size_with_fallback():
	suffix = "0123456789abcdef01234567"
	tiny = f"https://i.scdn.co/image/ab67616d00004851{suffix}"
	large = f"https://i.scdn.co/image/ab67616d0000b273{suffix}"
	assert artwork_download_urls(tiny) == [large, tiny]
	assert artwork_download_urls(large) == [large]
	assert artwork_download_urls("https://example.org/cover.jpg") == ["https://example.org/cover.jpg"]


def test_download_art_uses_original_when_large_variant_is_unavailable(monkeypatch):
	from csvmusic.core import downloader
	tiny = "https://i.scdn.co/image/ab67616d000048510123456789abcdef01234567"
	calls = []
	def fetch(url):
		calls.append(url)
		return b"original" if url == tiny else None
	monkeypatch.setattr(downloader, "_fetch_cover_art_url_bytes", fetch)
	assert downloader.cover_art_url_bytes(tiny) == b"original"
	assert calls == artwork_download_urls(tiny)
