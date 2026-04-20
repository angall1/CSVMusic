# tabs only
import os, pathlib, subprocess, requests, io, contextlib
from dataclasses import dataclass
from typing import Dict, Optional, List
import re, sys
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC
from mutagen.mp4 import MP4, MP4Cover
from csvmusic.core.paths import ffmpeg_path, ytdlp_path, INTERNAL_YTDLP
from csvmusic.core.log import log

YTM_URL = "https://music.youtube.com/watch?v={vid}"
YT_URL = "https://www.youtube.com/watch?v={vid}"
YOUTUBE_CLIENTS: list[str] = ["ios", "tv_embedded", "webremix"]
_YOUTUBE_RISK_PATTERNS: tuple[tuple[str, str], ...] = (
	("http error 429", "YouTube returned HTTP 429"),
	("too many requests", "YouTube is rate limiting requests"),
	("sign in to confirm you're not a bot", "YouTube asked for bot verification"),
	("sign in to confirm you’re not a bot", "YouTube asked for bot verification"),
	("confirm you’re not a bot", "YouTube asked for bot verification"),
	("confirm you're not a bot", "YouTube asked for bot verification"),
	("this content isn't available, try again later", "YouTube temporarily blocked the session"),
	("unable to download video data: http error 403", "YouTube rejected the download request"),
)
_YOUTUBE_LARGE_BATCH_THRESHOLD = 250
_YOUTUBE_EXTREME_BATCH_THRESHOLD = 500

class DownloadError(Exception): pass


@dataclass(frozen=True)
class YouTubeMitigationProfile:
	label: str
	track_sleep_s: float = 0.0
	request_sleep_s: float = 0.0
	sleep_interval_s: float = 0.0
	max_sleep_interval_s: float = 0.0
	limit_rate: str | None = None
	warning: str | None = None
	reason: str | None = None

	@property
	def active(self) -> bool:
		return any((
			self.track_sleep_s > 0,
			self.request_sleep_s > 0,
			self.sleep_interval_s > 0,
			self.max_sleep_interval_s > 0,
			bool(self.limit_rate),
		))


YOUTUBE_MITIGATION_NONE = YouTubeMitigationProfile(label="normal")
YOUTUBE_MITIGATION_LARGE_BATCH = YouTubeMitigationProfile(
	label="large-batch",
	track_sleep_s=2.0,
	request_sleep_s=0.75,
	sleep_interval_s=5.0,
	max_sleep_interval_s=10.0,
	limit_rate="1.5M",
	warning="Large YouTube batch detected. Downloads will be paced to reduce rate-limit risk.",
	reason="large playlist size",
)
YOUTUBE_MITIGATION_AGGRESSIVE = YouTubeMitigationProfile(
	label="aggressive",
	track_sleep_s=6.0,
	request_sleep_s=1.25,
	sleep_interval_s=8.0,
	max_sleep_interval_s=15.0,
	limit_rate="900K",
	warning="YouTube started throttling or blocking requests. Applying slower download pacing automatically.",
	reason="YouTube rate-limit response",
)

_WINDOWS = sys.platform.startswith("win")

def _hidden_subprocess_kwargs() -> dict:
	if not _WINDOWS:
		return {}
	startupinfo = subprocess.STARTUPINFO()
	startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
	flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
	return {"startupinfo": startupinfo, "creationflags": flags}

def _run(cmd: list[str]) -> int:
	proc = _run_capture(cmd)
	if proc.returncode != 0:
		err = (proc.stderr or "").strip()
		out = (proc.stdout or "").strip()
		log(f"yt-dlp command failed rc={proc.returncode} cmd={' '.join(cmd)} stderr={err[:500]} stdout={out[:200]}")
	return proc.returncode

def _run_capture(cmd: list[str]) -> subprocess.CompletedProcess[str]:
	return subprocess.run(
		cmd,
		stdout=subprocess.PIPE,
		stderr=subprocess.PIPE,
		text=True,
		**_hidden_subprocess_kwargs()
	)

def _run_ytdlp_module(args: list[str]) -> tuple[int, str, str]:
	stdout_buf = io.StringIO()
	stderr_buf = io.StringIO()
	try:
		from yt_dlp import main as yt_dlp_main
	except Exception as exc:
		return 1, "", f"failed to import yt_dlp module: {exc}"
	with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
		try:
			rc = yt_dlp_main(args)
		except SystemExit as exc:
			code = exc.code
			if isinstance(code, int):
				rc = code
			elif code is None:
				rc = 0
			else:
				rc = 1
		except Exception as exc:
			return 1, stdout_buf.getvalue(), f"{stderr_buf.getvalue()}\n{exc}".strip()
	return int(rc or 0), stdout_buf.getvalue(), stderr_buf.getvalue()

def _summarize_tool_output(stderr: str, stdout: str) -> str:
	def _clean_lines(text: str) -> list[str]:
		lines: list[str] = []
		for raw in text.splitlines():
			line = raw.strip()
			if not line:
				continue
			if line.startswith("[download]") or line.startswith("\r[download]"):
				continue
			lines.append(line)
		return lines
	lines = _clean_lines(stderr) + _clean_lines(stdout)
	if not lines:
		return "no diagnostic output"
	interesting = lines[-3:]
	msg = " | ".join(interesting)
	msg = re.sub(r"\s+", " ", msg).strip()
	return msg[:280]


def youtube_batch_mitigation(track_count: int, *, using_cookies: bool) -> YouTubeMitigationProfile:
	if track_count >= _YOUTUBE_EXTREME_BATCH_THRESHOLD:
		return YOUTUBE_MITIGATION_AGGRESSIVE
	if track_count >= _YOUTUBE_LARGE_BATCH_THRESHOLD and not using_cookies:
		return YOUTUBE_MITIGATION_LARGE_BATCH
	return YOUTUBE_MITIGATION_NONE


def detect_youtube_risk(detail: str) -> str | None:
	text = (detail or "").lower()
	for pattern, reason in _YOUTUBE_RISK_PATTERNS:
		if pattern in text:
			return reason
	return None


def build_ytdlp_mitigation_args(profile: YouTubeMitigationProfile | None) -> list[str]:
	if not profile or not profile.active:
		return []
	args: list[str] = []
	if profile.request_sleep_s > 0:
		args += ["--sleep-requests", f"{profile.request_sleep_s:g}"]
	if profile.sleep_interval_s > 0:
		args += ["--sleep-interval", f"{profile.sleep_interval_s:g}"]
	if profile.max_sleep_interval_s > 0:
		args += ["--max-sleep-interval", f"{profile.max_sleep_interval_s:g}"]
	if profile.limit_rate:
		args += ["--limit-rate", profile.limit_rate]
	return args

def _strip_cookie_args(cmd: list[str]) -> list[str]:
	new: list[str] = []
	skip_next = False
	for i, tok in enumerate(cmd):
		if skip_next:
			skip_next = False
			continue
		if tok == "--cookies-from-browser":
			skip_next = True
			continue
		if tok.startswith("--cookies-from-browser="):
			continue
		new.append(tok)
	return new

def _run_ytdlp(cmd: list[str]) -> int:
	"""
	Run yt-dlp command. If it fails specifically due to browser cookie copy
	issues (common when Chrome/Edge is running or profiles are locked), retry
	once without the cookies flag so public videos can still be fetched.
	"""
	if cmd and cmd[0] == INTERNAL_YTDLP:
		rc, stdout, stderr = _run_ytdlp_module(cmd[1:])
	else:
		proc = subprocess.run(
			cmd,
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
			text=True,
			**_hidden_subprocess_kwargs()
		)
		rc = proc.returncode
		stdout = proc.stdout or ""
		stderr = proc.stderr or ""
	if rc == 0:
		return 0
	log(f"yt-dlp command failed rc={rc} cmd={' '.join(cmd)} stderr={stderr[:500]} stdout={stdout[:200]}")
	# Detect cookie DB copy failure and retry without cookies
	if any(t.startswith("--cookies-from-browser") or t == "--cookies-from-browser" for t in cmd):
		lower_err = stderr.lower()
		if "could not copy" in lower_err and "cookie" in lower_err:
			no_cookie_cmd = _strip_cookie_args(cmd)
			log("yt-dlp retrying without browser cookies due to cookie DB copy error")
			if no_cookie_cmd and no_cookie_cmd[0] == INTERNAL_YTDLP:
				rc2, stdout2, stderr2 = _run_ytdlp_module(no_cookie_cmd[1:])
			else:
				proc2 = subprocess.run(
					no_cookie_cmd,
					stdout=subprocess.PIPE,
					stderr=subprocess.PIPE,
					text=True,
					**_hidden_subprocess_kwargs()
				)
				rc2 = proc2.returncode
				stdout2 = proc2.stdout or ""
				stderr2 = proc2.stderr or ""
			if rc2 != 0:
				log(f"yt-dlp retry (no-cookies) failed rc={rc2} cmd={' '.join(no_cookie_cmd)} stderr={stderr2[:500]} stdout={stdout2[:200]}")
				return rc2
			return 0
	return rc

def _run_ytdlp_detail(cmd: list[str]) -> tuple[int, str]:
	if cmd and cmd[0] == INTERNAL_YTDLP:
		rc, stdout, stderr = _run_ytdlp_module(cmd[1:])
	else:
		proc = _run_capture(cmd)
		rc = proc.returncode
		stdout = proc.stdout or ""
		stderr = proc.stderr or ""
	if rc == 0:
		return 0, ""
	detail = _summarize_tool_output(stderr, stdout)
	log(f"yt-dlp detail rc={rc} cmd={' '.join(cmd)} detail={detail}")
	if any(t.startswith("--cookies-from-browser") or t == "--cookies-from-browser" for t in cmd):
		lower_err = stderr.lower()
		if "could not copy" in lower_err and "cookie" in lower_err:
			no_cookie_cmd = _strip_cookie_args(cmd)
			log("yt-dlp retrying without browser cookies due to cookie DB copy error")
			if no_cookie_cmd and no_cookie_cmd[0] == INTERNAL_YTDLP:
				rc2, stdout2, stderr2 = _run_ytdlp_module(no_cookie_cmd[1:])
			else:
				proc2 = _run_capture(no_cookie_cmd)
				rc2 = proc2.returncode
				stdout2 = proc2.stdout or ""
				stderr2 = proc2.stderr or ""
			if rc2 == 0:
				return 0, ""
			detail2 = _summarize_tool_output(stderr2, stdout2)
			log(f"yt-dlp retry detail rc={rc2} cmd={' '.join(no_cookie_cmd)} detail={detail2}")
			return rc2, detail2
	return rc, detail

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


def _replace_file(src: pathlib.Path, dst: pathlib.Path) -> None:
	if dst.exists():
		try:
			dst.unlink()
		except Exception:
			pass
	src.replace(dst)


def _audio_processing_enabled(audio_processing: Dict | None) -> bool:
	if not audio_processing:
		return False
	return (
		bool(audio_processing.get("normalize"))
		or int(audio_processing.get("bass_gain", 0) or 0) != 0
		or int(audio_processing.get("treble_gain", 0) or 0) != 0
		or int(audio_processing.get("volume_gain", 0) or 0) != 0
	)


def _audio_filter_chain(audio_processing: Dict | None) -> str | None:
	if not _audio_processing_enabled(audio_processing):
		return None
	filters: list[str] = []
	bass_gain = int(audio_processing.get("bass_gain", 0) or 0) if audio_processing else 0
	treble_gain = int(audio_processing.get("treble_gain", 0) or 0) if audio_processing else 0
	volume_gain = int(audio_processing.get("volume_gain", 0) or 0) if audio_processing else 0
	if bass_gain:
		filters.append(f"bass=g={bass_gain}:f=110:w=0.6")
	if treble_gain:
		filters.append(f"treble=g={treble_gain}:f=6000:w=0.6")
	if audio_processing and audio_processing.get("normalize"):
		filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
	if volume_gain:
		filters.append(f"volume={volume_gain}dB")
	return ",".join(filters) if filters else None


def _append_audio_filter(args: list[str], audio_processing: Dict | None) -> None:
	filter_chain = _audio_filter_chain(audio_processing)
	if filter_chain:
		args += ["-af", filter_chain]


def _normalize_to_m4a(src: pathlib.Path, dst: pathlib.Path, ffmpeg_bin: str, video_id: str, audio_processing: Dict | None = None) -> pathlib.Path:
	tmp_dst = dst.with_name(dst.stem + ".normalized.m4a")
	if tmp_dst.exists():
		try:
			tmp_dst.unlink()
		except Exception:
			pass

	if not _audio_processing_enabled(audio_processing):
		proc = _run_capture([ffmpeg_bin, "-y", "-i", str(src), "-vn", "-sn", "-c:a", "copy", str(tmp_dst)])
		rc = proc.returncode
		if rc == 0 and tmp_dst.exists():
			if src != dst:
				try: src.unlink()
				except Exception: pass
			_replace_file(tmp_dst, dst)
			return dst

	args = [ffmpeg_bin, "-y", "-i", str(src), "-vn", "-sn"]
	_append_audio_filter(args, audio_processing)
	args += ["-c:a", "aac", "-b:a", "192k", str(tmp_dst)]
	proc = _run_capture(args)
	rc = proc.returncode
	detail = _summarize_tool_output(proc.stderr or "", proc.stdout or "")
	if rc == 0 and tmp_dst.exists():
		if src != dst:
			try: src.unlink()
			except Exception: pass
		_replace_file(tmp_dst, dst)
		return dst

	try:
		if tmp_dst.exists():
			tmp_dst.unlink()
	except Exception:
		pass
	log(f"download_m4a: ffmpeg normalization failed video_id={video_id} src='{src.name}' dst='{dst.name}' rc={rc}")
	raise DownloadError(f"failed to produce .m4a: {detail}")

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


def _extractor_args(client: str) -> list[str]:
	return ["--extractor-args", f"youtube:player_client={client}"]


def download_m4a(video_id: str, dst_dir: pathlib.Path, base_name: str, *, yt_dlp_bin: str | None = None, ffmpeg_bin: str | None = None, extra_yt_dlp_args: List[str] | None = None, audio_processing: Dict | None = None) -> pathlib.Path:
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
	# Resolve yt-dlp automatically if not provided
	yt_bin = yt_dlp_bin or ytdlp_path()
	cookies_args: list[str] = list(extra_yt_dlp_args or [])
	primary_base = [
		yt_bin,
		"-f", "ba[ext=m4a]/bestaudio[ext=m4a]/bestaudio",
		"--no-playlist",
		"--force-overwrites",
		"--retries", "5",
		"--fragment-retries", "5",
		"--socket-timeout", "30",
	]
	fallback_base = [
		yt_bin,
		"-f", "bestaudio",
		"--no-continue",
		"--no-playlist",
		"--force-overwrites",
		"--retries", "5",
		"--fragment-retries", "5",
		"--socket-timeout", "30",
	]
	success = False
	last_detail = "no yt-dlp attempts recorded"
	for base_url in (YTM_URL.format(vid=video_id), YT_URL.format(vid=video_id)):
		for client in YOUTUBE_CLIENTS:
			extractor_args = _extractor_args(client)
			cmd_primary = primary_base + extractor_args + cookies_args + ["-o", out_tpl, base_url]
			rc, detail = _run_ytdlp_detail(cmd_primary)
			if rc == 0:
				success = True
				log(f"download_m4a: primary succeeded video_id={video_id} client={client} url={base_url}")
				break
			last_detail = detail
			log(f"download_m4a: primary failed video_id={video_id} client={client} url={base_url}")
			cmd_fallback = fallback_base + extractor_args + cookies_args + ["-o", out_tpl, base_url]
			rc, detail = _run_ytdlp_detail(cmd_fallback)
			if rc == 0:
				success = True
				log(f"download_m4a: fallback succeeded video_id={video_id} client={client} url={base_url}")
				break
			last_detail = detail
			log(f"download_m4a: fallback failed video_id={video_id} client={client} url={base_url}")
		if success:
			break
	if not success:
		search_url = f"ytsearch1:{base_name}"
		for client in YOUTUBE_CLIENTS:
			extractor_args = _extractor_args(client)
			cmd_search = primary_base + extractor_args + cookies_args + ["-o", out_tpl, search_url]
			rc, detail = _run_ytdlp_detail(cmd_search)
			if rc == 0:
				success = True
				log(f"download_m4a: search fallback succeeded query='{base_name}' client={client}")
				break
			last_detail = detail
			log(f"download_m4a: search fallback failed query='{base_name}' client={client}")
	if not success:
		log(f"download_m4a: all extractor clients failed video_id={video_id} base='{base_name}'")
		raise DownloadError(f"yt-dlp failed for m4a: {last_detail}")

	# What got written?
	cands = _list_downloads(dst_dir, safe_base)
	if not cands:
		raise DownloadError("downloaded file not found")

	src = cands[0]
	dst = dst_dir / (safe_base + ".m4a")
	ffmpeg_bin = ffmpeg_bin or ffmpeg_path()
	return _normalize_to_m4a(src, dst, ffmpeg_bin, video_id, audio_processing)

def download_mp3(video_id: str, dst_dir: pathlib.Path, base_name: str, cbr_320: bool = False, *, yt_dlp_bin: str | None = None, ffmpeg_bin: str | None = None, extra_yt_dlp_args: List[str] | None = None, audio_processing: Dict | None = None) -> pathlib.Path:
	dst_dir.mkdir(parents=True, exist_ok=True)
	safe_base = _safe(base_name)
	tmp = dst_dir / (safe_base + ".tmp")
	if tmp.exists():
		try: tmp.unlink()
		except Exception: pass
	_cleanup_outputs(dst_dir, safe_base)
	yt_bin = yt_dlp_bin or ytdlp_path()
	cookies_args: list[str] = list(extra_yt_dlp_args or [])
	cmd_base = [
		yt_bin,
		"-f", "bestaudio",
		"--no-playlist",
		"--force-overwrites",
		"--retries", "5",
		"--fragment-retries", "5",
		"--socket-timeout", "30",
	]
	success = False
	last_detail = "no yt-dlp attempts recorded"
	for base_url in (YTM_URL.format(vid=video_id), YT_URL.format(vid=video_id)):
		for client in YOUTUBE_CLIENTS:
			extractor_args = _extractor_args(client)
			cmd = cmd_base + extractor_args + cookies_args + ["-o", str(tmp), base_url]
			rc, detail = _run_ytdlp_detail(cmd)
			if rc == 0:
				success = True
				log(f"download_mp3: yt-dlp succeeded video_id={video_id} client={client} url={base_url}")
				break
			last_detail = detail
			log(f"download_mp3: yt-dlp attempt failed video_id={video_id} client={client} url={base_url}")
		if success:
			break
	if not success:
		search_url = f"ytsearch1:{base_name}"
		for client in YOUTUBE_CLIENTS:
			extractor_args = _extractor_args(client)
			cmd = cmd_base + extractor_args + cookies_args + ["-o", str(tmp), search_url]
			rc, detail = _run_ytdlp_detail(cmd)
			if rc == 0:
				success = True
				log(f"download_mp3: search fallback succeeded query='{base_name}' client={client}")
				break
			last_detail = detail
			log(f"download_mp3: search fallback failed query='{base_name}' client={client}")
	if not success:
		log(f"download_mp3: yt-dlp initial fetch failed video_id={video_id} base='{base_name}'")
		raise DownloadError(f"yt-dlp failed for mp3 temp: {last_detail}")

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
	_append_audio_filter(args, audio_processing)
	if cbr_320:
		args += ["-codec:a","libmp3lame","-b:a","320k"]
	else:
		args += ["-codec:a","libmp3lame","-q:a","0"]  # V0
	args += [str(dst)]
	proc = _run_capture(args)
	rc = proc.returncode
	detail = _summarize_tool_output(proc.stderr or "", proc.stdout or "")
	try: src.unlink()
	except Exception: pass
	if rc != 0 or not dst.exists():
		log(f"download_mp3: ffmpeg transcode failed video_id={video_id} dst='{dst.name}' rc={rc}")
		raise DownloadError(f"ffmpeg mp3 transcode failed: {detail}")
	return dst

def write_m3u(out_dir: pathlib.Path, playlist_name: str, tracks_done: List[Dict], ext: str, *, suffix: str = ".m3u8", encoding: str = "utf-8") -> pathlib.Path:
	playlist_dir = out_dir / _safe(playlist_name)
	playlist_dir.mkdir(parents=True, exist_ok=True)
	fp = playlist_dir / f"{_safe(playlist_name)}{suffix}"
	with fp.open("w", encoding=encoding, errors="ignore") as f:
		f.write("#EXTM3U\n")
		f.write(f"#EXTPLAYLIST:{playlist_name}\n")
		for t in tracks_done:
			title = t["title"]; artists = t["artists"]; album = t["album"]
			rel = pathlib.Path(f"{_safe(artists)} - {_safe(title)}.{ext}")
			dur = int(round((t.get("duration_ms") or 0)/1000))
			f.write(f"#EXTINF:{dur},{artists} - {title}\n")
			if t.get("isrc"): f.write(f"#EXTISRC:{t['isrc']}\n")
			f.write(f"#EXTALBUM:{album}\n")
			f.write(str(rel.as_posix()) + "\n")
	return fp
