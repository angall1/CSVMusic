import re
from urllib.parse import parse_qs, urlparse


_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


class YouTubeVideoUrlError(ValueError):
	pass


def parse_youtube_video_id(value: str) -> str:
	"""Return one video ID from a YouTube watch, music, shorts, or youtu.be URL."""
	text = (value or "").strip()
	if not text:
		raise YouTubeVideoUrlError("Paste a YouTube or YouTube Music video URL first.")
	parsed = urlparse(text)
	host = parsed.netloc.casefold().split(":", 1)[0]
	video_id = ""
	if host == "youtu.be":
		video_id = parsed.path.strip("/").split("/", 1)[0]
	elif host in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"):
		parts = [part for part in parsed.path.split("/") if part]
		if parsed.path == "/watch":
			video_id = (parse_qs(parsed.query).get("v") or [""])[0]
		elif len(parts) == 2 and parts[0] in ("shorts", "embed", "live"):
			video_id = parts[1]
		elif parts and parts[0] in ("playlist", "channel", "@"):
			raise YouTubeVideoUrlError("Paste a link to one video, not a playlist or channel.")
	else:
		raise YouTubeVideoUrlError("Only YouTube and YouTube Music video URLs are supported.")
	if not _VIDEO_ID.fullmatch(video_id):
		raise YouTubeVideoUrlError("This link does not contain a valid YouTube video ID.")
	return video_id
