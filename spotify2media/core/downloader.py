# tabs only
import os, pathlib, subprocess, requests
from typing import Dict, Optional, List
import re, sys
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC
from mutagen.mp4 import MP4, MP4Cover
from spotify2media.core.paths import ffmpeg_path

YTM_URL = "https://music.youtube.com/watch?v={vid}"

class DownloadError(Exception): pass

_WINDOWS = sys.platform.startswith("win")

def _hidden_subprocess_kwargs() -> dict:
	if not _WINDOWS:
		return {}
	startupinfo = subprocess.STARTUPINFO()
	startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
	flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
	return {"startupinfo": startupinfo, "creationflags": flags}

def _run(cmd: list[str]) -> int:
	proc = subprocess.run(
		cmd,
		stdout=subprocess.PIPE,
		stderr=subprocess.PIPE,
		**_hidden_subprocess_kwargs()
	)
	return proc.returncode

def sanitize_name(name: str) -> str:
	return re.sub(r'[\\/:*?"<>|]+', "_", name or "").strip()

def _safe(name: str) -> str:
	# Backward-compatible helper kept for internal use
	return sanitize_name(name)

def _list_downloads(dir: pathlib.Path, base: str) -> list[pathlib.Path]:
	# Find files that start with our sanitized base (yt-dlp may alter punctuation)
	return sorted(
		[p for p in dir.iterdir() if p.is_file() and p.name.startswith(base + ".")],
		key=lambda x: x.stat().st_mtime, reverse=True
	)

def _cleanup_outputs(dir: pathlib.Path, base: str) -> None:
	for p in dir.glob(f"{base}.*"):
		try:
			p.unlink()
		except Exception:
			pass

def yt_thumbnail_bytes(video_id: str) -> Optional[bytes]:
	# Best-effort cover from YouTube thumbnails
	for quality in ("maxresdefault","sddefault","hqdefault","mqdefault","default"):
		url = f"https://i.ytimg.com/vi/{video_id}/{quality}.jpg"
		try:
			r = requests.get(url, timeout=12)
			if r.status_code == 200 and r.content and len(r.content) > 1024:
				return r.content
		except Exception:
			pass
	return None

def tag_file(path: pathlib.Path, meta: Dict, cover_bytes: Optional[bytes]) -> None:
	if path.suffix.lower() == ".mp3":
		# ID3 (MP3)
		try:
			_ = EasyID3(path)
		except Exception:
			EasyID3.register_text_key("date", "TDRC")
			audio = EasyID3(); audio.save(path)
		audio = EasyID3(path)
		audio["title"] = meta.get("title","")
		audio["artist"] = meta.get("artists","")
		audio["album"] = meta.get("album","")
		if meta.get("year"): audio["date"] = str(meta["year"])
		audio.save()
		id3 = ID3(path)
		if cover_bytes:
			id3.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover_bytes))
			id3.save(v2_version=3)
	else:
		# MP4/M4A
		mp4 = MP4(path)
		mp4["\xa9nam"] = meta.get("title","")
		mp4["\xa9ART"] = [meta.get("artists","")]
		mp4["\xa9alb"] = [meta.get("album","")]
		if meta.get("year"): mp4["\xa9day"] = [str(meta["year"])]
		if cover_bytes:
			mp4["covr"] = [MP4Cover(cover_bytes, imageformat=MP4Cover.FORMAT_JPEG)]
		mp4.save()

def download_m4a(video_id: str, dst_dir: pathlib.Path, base_name: str, *, yt_dlp_bin: str | None = None, ffmpeg_bin: str | None = None) -> pathlib.Path:
	"""
	YT Music only. Save using a sanitized stem so our search matches what yt-dlp writes.
	- If output is already .m4a → done.
	- Else try remux to .m4a (stream copy).
	- Else transcode to AAC .m4a.
	"""
	dst_dir.mkdir(parents=True, exist_ok=True)
	safe_base = _safe(base_name)

	# Force yt-dlp to use our sanitized basename
	out_tpl = str(dst_dir / (safe_base + ".%(ext)s"))
	_cleanup_outputs(dst_dir, safe_base)
	yt_bin = yt_dlp_bin or "yt-dlp"
	cmd = [
		yt_bin,
		"-f", "ba[ext=m4a]/bestaudio[ext=m4a]/bestaudio",
		"--no-playlist",
		"--force-overwrites",
		"--retries", "5",
		"--fragment-retries", "5",
		"--socket-timeout", "30",
		"-o", out_tpl,
		YTM_URL.format(vid=video_id),
	]
	code = _run(cmd)
	if code != 0:
		# retry once without ext filters + use FFMPEG to convert
		cmd_fallback = [
			yt_bin,
			"-f", "bestaudio",
			"--no-continue",
			"--no-playlist",
			"--force-overwrites",
			"--retries", "5",
			"--fragment-retries", "5",
			"--socket-timeout", "30",
			"-o", out_tpl,
			YTM_URL.format(vid=video_id),
		]
		if _run(cmd_fallback) != 0:
			raise DownloadError("yt-dlp failed for m4a")

	# What got written?
	cands = _list_downloads(dst_dir, safe_base)
	if not cands:
		raise DownloadError("downloaded file not found")

	# Already m4a?
	for p in cands:
		if p.suffix.lower() == ".m4a":
			return p

	# Remux/transcode to .m4a
	src = cands[0]
	dst = dst_dir / (safe_base + ".m4a")

	# 1) Remux (copy AAC out of MP4/MOV containers)
	ffmpeg_bin = ffmpeg_bin or ffmpeg_path()
	rc = _run([ffmpeg_bin, "-y", "-i", str(src), "-vn", "-sn", "-c:a", "copy", str(dst)])
	if rc == 0 and dst.exists():
		try: src.unlink()
		except Exception: pass
		return dst

	# 2) Transcode (e.g., Opus/WebM → AAC)
	rc = _run([ffmpeg_bin, "-y", "-i", str(src), "-vn", "-sn", "-c:a", "aac", "-b:a", "192k", str(dst)])
	try: src.unlink()
	except Exception: pass
	if rc != 0 or not dst.exists():
		raise DownloadError("failed to produce .m4a (remux and transcode failed)")
	return dst

def download_mp3(video_id: str, dst_dir: pathlib.Path, base_name: str, cbr_320: bool = False, *, yt_dlp_bin: str | None = None, ffmpeg_bin: str | None = None) -> pathlib.Path:
	dst_dir.mkdir(parents=True, exist_ok=True)
	safe_base = _safe(base_name)
	tmp = dst_dir / (safe_base + ".tmp")
	if tmp.exists():
		try: tmp.unlink()
		except Exception: pass
	_cleanup_outputs(dst_dir, safe_base)
	yt_bin = yt_dlp_bin or "yt-dlp"
	cmd = [
		yt_bin,
		"-f", "bestaudio",
		"--no-playlist",
		"--force-overwrites",
		"--retries", "5",
		"--fragment-retries", "5",
		"--socket-timeout", "30",
		"-o", str(tmp),
		YTM_URL.format(vid=video_id),
	]
	code = _run(cmd)
	if code != 0:
		raise DownloadError("yt-dlp failed for mp3 temp")

	# yt-dlp may append extension to .tmp; find it
	src = None
	if tmp.exists():
		src = tmp
	else:
		cands = _list_downloads(dst_dir, safe_base + ".tmp")
		if cands: src = cands[0]
	if not src:
		raise DownloadError("temp file not found")

	dst = dst_dir / (safe_base + ".mp3")
	ffmpeg_bin = ffmpeg_bin or ffmpeg_path()
	args = [ffmpeg_bin, "-y", "-i", str(src)]
	if cbr_320:
		args += ["-codec:a","libmp3lame","-b:a","320k"]
	else:
		args += ["-codec:a","libmp3lame","-q:a","0"]  # V0
	args += [str(dst)]
	rc = _run(args)
	try: src.unlink()
	except Exception: pass
	if rc != 0 or not dst.exists():
		raise DownloadError("ffmpeg mp3 transcode failed")
	return dst

def write_m3u(out_dir: pathlib.Path, playlist_name: str, tracks_done: List[Dict], ext: str, *, suffix: str = ".m3u8", encoding: str = "utf-8") -> pathlib.Path:
	fp = out_dir / f"{_safe(playlist_name)}{suffix}"
	with fp.open("w", encoding=encoding, errors="ignore") as f:
		f.write("#EXTM3U\n")
		f.write(f"#EXTPLAYLIST:{playlist_name}\n")
		for t in tracks_done:
			title = t["title"]; artists = t["artists"]; album = t["album"]
			rel = pathlib.Path(_safe(playlist_name)) / f"{_safe(artists)} - {_safe(title)}.{ext}"
			dur = int(round((t.get("duration_ms") or 0)/1000))
			f.write(f"#EXTINF:{dur},{artists} - {title}\n")
			if t.get("isrc"): f.write(f"#EXTISRC:{t['isrc']}\n")
			f.write(f"#EXTALBUM:{album}\n")
			if t.get("sp_id"): f.write(f"#EXTSPOTIFYID:{t['sp_id']}\n")
			f.write(str(rel.as_posix()) + "\n")
	return fp
