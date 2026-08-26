# tabs only
import argparse
import json
import os

from csvmusic.core.spotify_api import SpotifyAPIError, fetch_spotify_playlist_api


def main() -> int:
	parser = argparse.ArgumentParser(description="Test Spotify Web API playlist metadata loading")
	parser.add_argument("playlist", help="Spotify playlist URL, URI, or ID")
	parser.add_argument("--token", help="Spotify access token (otherwise SPOTIFY_ACCESS_TOKEN is used)")
	args = parser.parse_args()
	token = args.token or os.environ.get("SPOTIFY_ACCESS_TOKEN", "")
	try:
		playlist = fetch_spotify_playlist_api(args.playlist, token)
	except SpotifyAPIError as exc:
		parser.error(str(exc))
	print(json.dumps({
		"id": playlist.id,
		"name": playlist.name,
		"total_count": playlist.total_count,
		"tracks": playlist.tracks,
	}, ensure_ascii=False, indent=2))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
