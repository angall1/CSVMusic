"""Selected YouTube format metadata, independent of output encoding."""
import json
import math
import threading
from mutagen.id3 import ID3, ID3NoHeaderError, TXXX
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus

_state = threading.local()
KEY = "CSVMUSIC_YOUTUBE_SOURCE"


def capture_source(stdout: str) -> None:
	_state.source = {}
	for line in stdout.splitlines():
		try:
			item = json.loads(line)
			if not isinstance(item, dict) or not item.get("id") or not item.get("acodec"):
				continue
			abr = item.get("abr")
			if abr is None and item.get("vcodec") == "none":
				abr = item.get("tbr")
			abr = float(abr) if abr is not None else None
			if abr is not None and (not math.isfinite(abr) or abr <= 0):
				abr = None
			_state.source = {"version": 1, "video_id": item["id"], "codec": item["acodec"], "kbps": abr, "format_id": item.get("format_id")}
		except (ValueError, TypeError):
			continue


def store_source(path) -> None:
	source = getattr(_state, "source", {})
	if not source:
		return
	text = json.dumps(source)
	if path.suffix == ".mp3":
		try:
			tags = ID3(path)
		except ID3NoHeaderError:
			tags = ID3()
		tags.add(TXXX(encoding=3, desc=KEY, text=[text]))
		tags.save(path)
	elif path.suffix == ".m4a":
		audio = MP4(path)
		audio[f"----:com.csvmusic:{KEY}"] = [text.encode("utf-8")]
		audio.save()
	elif path.suffix == ".opus":
		audio = OggOpus(path)
		audio[KEY] = [text]
		audio.save()


def read_source(audio) -> dict:
	try:
		if type(audio).__name__ == "MP3":
			value = audio.tags[f"TXXX:{KEY}"].text[0]
		elif type(audio).__name__ == "MP4":
			value = bytes(audio.tags[f"----:com.csvmusic:{KEY}"][0]).decode("utf-8")
		else:
			value = audio.tags[KEY][0]
		data = json.loads(value)
		return data if isinstance(data, dict) and data.get("version") == 1 else {}
	except (KeyError, TypeError, ValueError, AttributeError, IndexError):
		return {}
