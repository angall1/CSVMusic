"""Explicit, isolated Firefox login; no password handling or browser automation."""
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time

from csvmusic.core.youtube_session import validate_cookie_file


def find_firefox() -> str | None:
	installed = shutil.which("firefox")
	if installed:
		return installed
	candidates = [Path("/Applications/Firefox.app/Contents/MacOS/firefox")]
	for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
		if os.environ.get(variable):
			candidates.append(Path(os.environ[variable]) / "Mozilla Firefox" / "firefox.exe")
	return next((str(path) for path in candidates if path.is_file()), None)


def login_command(executable: str, profile: Path) -> list[str]:
	return [executable, "-no-remote", "-new-instance", "-profile", str(profile), "https://www.youtube.com/"]


def import_login_cookies(profile: Path, destination: Path) -> None:
	"""Read only our dedicated profile after Firefox exits; save YouTube only."""
	database = profile / "cookies.sqlite"
	if not database.is_file():
		raise ValueError("No session found. Sign into YouTube and close the dedicated Firefox window first.")
	with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1) as connection:
		rows = connection.execute("SELECT host, path, isSecure, expiry, name, value, isHttpOnly FROM moz_cookies").fetchall()
	lines = ["# Netscape HTTP Cookie File"]
	for host, path, secure, expiry, name, value, http_only in rows:
		domain = host.lower().lstrip(".")
		if domain != "youtube.com" and not domain.endswith(".youtube.com"):
			continue
		if expiry and expiry <= time.time():
			continue
		if any(char in str(field) for field in (host, path, name, value) for char in ("\t", "\r", "\n")):
			continue
		lines.append("\t".join((
			("#HttpOnly_" if http_only else "") + host,
			"TRUE" if host.startswith(".") else "FALSE", path,
			"TRUE" if secure else "FALSE", str(expiry or 0), name, value,
		)))
	destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
	fd, temporary = tempfile.mkstemp(dir=destination.parent, suffix=".cookies")
	try:
		with os.fdopen(fd, "w", encoding="utf-8") as output:
			output.write("\n".join(lines) + "\n")
		ok, message = validate_cookie_file(temporary)
		if not ok:
			raise ValueError(message)
		os.replace(temporary, destination)
	finally:
		Path(temporary).unlink(missing_ok=True)
