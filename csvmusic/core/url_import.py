# tabs only
from dataclasses import dataclass
from urllib.parse import urlparse

from csvmusic.core.apple_music_import import fetch_apple_music_source
from csvmusic.core.amazon_music_import import fetch_amazon_music_source
from csvmusic.core.deezer_import import fetch_deezer_source
from csvmusic.core.spotify_import import fetch_spotify_playlist
from csvmusic.core.web_playlist_import import fetch_web_playlist
from csvmusic.core.youtube_music_import import fetch_youtube_music_source


class URLImportError(Exception):
	pass


@dataclass
class ImportedMusicSource:
	platform: str
	source_type: str
	id: str
	name: str
	tracks: list[dict]
	total_count: int | None = None
	warning: str | None = None


def fetch_music_url(value: str) -> ImportedMusicSource:
	text = (value or "").strip()
	if not text:
		raise URLImportError("Paste a music playlist or album link first.")
	host = urlparse(text).netloc.lower()
	try:
		if host in ("open.spotify.com", "play.spotify.com") or text.startswith("spotify:"):
			source = fetch_spotify_playlist(text)
			return ImportedMusicSource("Spotify", source.source_type, source.id, source.name, source.tracks, source.total_count, source.warning)
		if host == "music.apple.com":
			source = fetch_apple_music_source(text)
			return ImportedMusicSource("Apple Music", source.source_type, source.id, source.name, source.tracks, source.total_count, source.warning)
		if host == "music.youtube.com":
			source = fetch_youtube_music_source(text)
			return ImportedMusicSource("YouTube Music", source.source_type, source.id, source.name, source.tracks, source.total_count, source.warning)
		if host in ("www.youtube.com", "youtube.com", "youtu.be"):
			source = fetch_web_playlist(text, "YouTube")
			return ImportedMusicSource("YouTube", source.source_type, source.id, source.name, source.tracks, source.total_count, source.warning)
		if host.removeprefix("www.") == "soundcloud.com":
			source = fetch_web_playlist(text, "SoundCloud")
			return ImportedMusicSource("SoundCloud", source.source_type, source.id, source.name, source.tracks, source.total_count, source.warning)
		if host.removeprefix("www.") in ("deezer.com", "deezer.page.link"):
			source = fetch_deezer_source(text)
			return ImportedMusicSource("Deezer", source.source_type, source.id, source.name, source.tracks, source.total_count, source.warning)
		if "music.amazon." in host:
			source = fetch_amazon_music_source(text)
			return ImportedMusicSource("Amazon Music", source.source_type, source.id, source.name, source.tracks, source.total_count, source.warning)
	except Exception as exc:
		if isinstance(exc, URLImportError):
			raise
		raise URLImportError(str(exc)) from exc
	raise URLImportError(
		"Unsupported link. Use Spotify, Apple Music, YouTube Music, YouTube, "
		"SoundCloud, Deezer, Amazon Music, or CSV."
	)
