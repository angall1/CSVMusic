"""Local cookie validation; never reads passwords or exposes cookie values."""
from http.cookiejar import LoadError, MozillaCookieJar
from pathlib import Path
import time
import warnings
import re

import requests


def youtube_cookie_text(cookies: list[dict]) -> str:
	"""Serialize only YouTube cookies collected from the explicit login window."""
	lines = ["# Netscape HTTP Cookie File"]
	for cookie in cookies:
		host = cookie["domain"]
		domain = host.lower().lstrip(".")
		if domain != "youtube.com" and not domain.endswith(".youtube.com"):
			continue
		fields = (host, cookie["path"], cookie["name"], cookie["value"])
		if any(char in field for field in fields for char in ("\r", "\n", "\t")):
			continue
		lines.append("\t".join((
			("#HttpOnly_" if cookie["http_only"] else "") + host,
			"TRUE" if host.startswith(".") else "FALSE", cookie["path"],
			"TRUE" if cookie["secure"] else "FALSE", str(cookie["expires"]),
			cookie["name"], cookie["value"],
		)))
	return "\n".join(lines) + "\n"


def verify_youtube_session(path: str) -> bool:
	"""Confirm YouTube recognizes a login, without fetching private playlists."""
	if not validate_cookie_file(path)[0]:
		return False
	jar = MozillaCookieJar(path)
	# Netscape expiry 0 represents session cookies for yt-dlp.
	jar.load(ignore_discard=True, ignore_expires=True)
	for cookie in jar:
		if cookie.expires == 0:
			cookie.expires = None
	with requests.Session() as session:
		session.cookies = jar
		response = session.get("https://www.youtube.com/", timeout=(10, 20), allow_redirects=False)
		response.raise_for_status()
		return response.status_code == 200 and bool(re.search(r'"LOGGED_IN"\s*:\s*true\b', response.text))


def validate_cookie_file(path: str) -> tuple[bool, str]:
	"""Check exported auth cookies, not whether YouTube still accepts the session."""
	if not Path(path).is_file():
		return False, "Cookies file not found. Choose an exported Netscape cookies.txt file."
	jar = MozillaCookieJar(path)
	try:
		# CookieJar diagnostics can quote malformed rows, including secret values.
		with warnings.catch_warnings():
			warnings.simplefilter("ignore")
			jar.load(ignore_discard=True, ignore_expires=True)
	except (OSError, LoadError, ValueError):
		return False, "Cannot read this file as Netscape cookies.txt. Export it again; do not paste passwords or JSON."
	now = time.time()
	names = {"SAPISID", "__Secure-1PAPISID", "__Secure-3PAPISID", "SID", "__Secure-1PSID", "__Secure-3PSID"}
	for cookie in jar:
		domain = cookie.domain.lower().lstrip(".")
		if domain != "youtube.com" and not domain.endswith(".youtube.com"):
			continue
		if cookie.name in names and cookie.value and (not cookie.expires or cookie.expires > now):
			return True, "Unexpired YouTube account cookies found. This checks the file only; YouTube may still reject an expired or revoked session."
	return False, "No unexpired YouTube account cookies found. Export cookies from a signed-in YouTube session."
