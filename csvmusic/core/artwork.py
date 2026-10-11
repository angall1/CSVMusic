# tabs only
import re
from urllib.parse import urlsplit, urlunsplit


def artwork_download_urls(url: str) -> list[str]:
	"""Prefer Spotify's full-size album variant, retaining the original fallback."""
	parts = urlsplit(url)
	if parts.hostname == "i.scdn.co" and re.fullmatch(r"/image/ab67616d0000(?:4851|1e02|b273)[0-9a-f]{24}", parts.path):
		large = urlunsplit(parts._replace(path="/image/ab67616d0000b273" + parts.path[-24:]))
		if large != url:
			return [large, url]
	return [url]
