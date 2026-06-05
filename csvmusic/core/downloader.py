# tabs only
import os, pathlib, subprocess, requests, io, contextlib, json
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
	track_sleep_s=5.0,
	request_sleep_s=0.75,
	sleep_interval_s=5.0,
	max_sleep_interval_s=10.0,
	limit_rate="1.5M",
	warning="Large YouTube batch detected. Downloads will be paced with randomized waits to reduce rate-limit risk.",
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
_TARGET_LOUDNESS_I = -16.0
_TARGET_TRUE_PEAK_DB = -2.5

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
	full_text = " | ".join(lines)
	lower_full = full_text.lower()
	if "sign in to confirm your age" in lower_full or "this video may be inappropriate for some users" in lower_full:
		return "Age-restricted video. Sign into YouTube with Firefox cookies or choose another result."
	if "login_required" in lower_full and "age-restricted" in lower_full:
		return "Age-restricted video. Sign into YouTube with Firefox cookies or choose another result."
	if "sign in to confirm you're not a bot" in lower_full or "sign in to confirm you’re not a bot" in lower_full:
		return "YouTube asked for bot verification. Try Firefox cookies or wait and retry."
	if "no supported javascript runtime could be found" in lower_full:
		return "yt-dlp could not solve the YouTube player challenge. Install a supported JS runtime or update yt-dlp."
	if "requested format is not available" in lower_full:
		return "Requested audio format is not available for this result."
	interesting = lines[-3:]
	msg = " | ".join(interesting)
	msg = re.sub(r"\s+", " ", msg).strip()
	return msg[:280]


def youtube_batch_mitigation(track_count: int, *, using_cookies: bool) -> YouTubeMitigationProfile:
	if track_count >= _YOUTUBE_EXTREME_BATCH_THRESHOLD:
		return YOUTUBE_MITIGATION_AGGRESSIVE
	if track_count >= _YOUTUBE_LARGE_BATCH_THRESHOLD:
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
		if tok == "--cookies":
			skip_next = True
			continue
		if tok.startswith("--cookies="):
			continue
		if tok == "--cookies-from-browser":
			skip_next = True
			continue
		if tok.startswith("--cookies-from-browser="):
			continue
		new.append(tok)
	return new

def _should_retry_without_cookies(stderr: str, stdout: str) -> bool:
	text = f"{stderr or ''}\n{stdout or ''}".lower()
	return any(phrase in text for phrase in (
		"requested format is not available",
		"only images are available for download",
		"signature solving failed",
		"n challenge solving failed",
		"nsig extraction failed",
		"unable to extract initial player response",
		"unable to download api page",
		"video unavailable",
		"this content isn't available",
		"this video is unavailable",
		"sign in to confirm your age",
		"sign in to confirm you're not a bot",
		"sign in to confirm you’re not a bot",
		"login required",
		"login_required",
		"precondition check failed",
	))

def _cmd_uses_cookies(cmd: list[str]) -> bool:
	return any(
		tok in ("--cookies", "--cookies-from-browser")
		or tok.startswith("--cookies=")
		or tok.startswith("--cookies-from-browser=")
		for tok in cmd
	)

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
	# If cookie-backed extraction fails, retry once without cookies so
	# public videos are not blocked by a bad auth/session state.
	if _cmd_uses_cookies(cmd):
		lower_err = stderr.lower()
		if (
			("could not copy" in lower_err and "cookie" in lower_err)
			or ("locked" in lower_err and "cookie" in lower_err)
			or _should_retry_without_cookies(stderr, stdout)
		):
			no_cookie_cmd = _strip_cookie_args(cmd)
			log("yt-dlp retrying without cookies after cookie/session-specific extraction failure")
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
	if _cmd_uses_cookies(cmd):
		lower_err = stderr.lower()
		if (
			("could not copy" in lower_err and "cookie" in lower_err)
			or ("locked" in lower_err and "cookie" in lower_err)
			or _should_retry_without_cookies(stderr, stdout)
		):
			no_cookie_cmd = _strip_cookie_args(cmd)
			log("yt-dlp retrying without cookies after cookie/session-specific extraction failure")
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

_FILENAME_CHAR_MAP = str.maketrans({
	"\\": "＼",
	"/": "／",
	":": "：",
	"*": "＊",
	"?": "？",
	'"': "＂",
	"<": "＜",
	">": "＞",
	"|": "｜",
})

def sanitize_name(name: str) -> str:
	text = (name or "").translate(_FILENAME_CHAR_MAP)
	text = re.sub(r"[\x00-\x1f]+", "", text)
	text = re.sub(r"\s+", " ", text).strip()
	text = text.rstrip(". ")
	return text or "_"

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


def _tone_filter_chain(audio_processing: Dict | None) -> list[str]:
	filters: list[str] = []
	bass_gain = int(audio_processing.get("bass_gain", 0) or 0) if audio_processing else 0
	treble_gain = int(audio_processing.get("treble_gain", 0) or 0) if audio_processing else 0
	if bass_gain:
		filters.append(f"bass=g={bass_gain}:f=110:w=0.6")
	if treble_gain:
		filters.append(f"treble=g={treble_gain}:f=6000:w=0.6")
	return filters


def _extract_loudnorm_json(stderr: str) -> Dict | None:
	matches = re.findall(r"\{\s*\"input_i\".*?\}", stderr or "", flags=re.S)
	if not matches:
		return None
	try:
		return json.loads(matches[-1])
	except Exception:
		return None


def _measure_static_normalize_gain(src: pathlib.Path, ffmpeg_bin: str, audio_processing: Dict | None) -> float:
	pre_filters = _tone_filter_chain(audio_processing)
	filter_parts = list(pre_filters)
	filter_parts.append(f"loudnorm=I={_TARGET_LOUDNESS_I}:TP={_TARGET_TRUE_PEAK_DB}:LRA=11:print_format=json")
	proc = _run_capture([
		ffmpeg_bin, "-hide_banner", "-i", str(src), "-vn", "-sn",
		"-af", ",".join(filter_parts),
		"-f", "null", "-"
	])
	stats = _extract_loudnorm_json((proc.stderr or "") + "\n" + (proc.stdout or ""))
	if not stats:
		return 0.0
	try:
		input_i = float(stats.get("input_i"))
		input_tp = float(stats.get("input_tp"))
	except Exception:
		return 0.0
	target_i = _TARGET_LOUDNESS_I
	target_tp = _TARGET_TRUE_PEAK_DB
	gain = target_i - input_i
	peak_limited_gain = target_tp - input_tp
	return min(gain, peak_limited_gain)


def _audio_filter_chain(audio_processing: Dict | None, src: pathlib.Path | None = None, ffmpeg_bin: str | None = None) -> str | None:
	if not _audio_processing_enabled(audio_processing):
		return None
	filters = _tone_filter_chain(audio_processing)
	total_gain = float(int(audio_processing.get("volume_gain", 0) or 0)) if audio_processing else 0.0
	if audio_processing and audio_processing.get("normalize") and src and ffmpeg_bin:
		total_gain += _measure_static_normalize_gain(src, ffmpeg_bin, audio_processing)
	if abs(total_gain) > 0.01:
		filters.append(f"volume={total_gain:.2f}dB")
	limit_linear = 10 ** (_TARGET_TRUE_PEAK_DB / 20.0)
	filters.append(f"alimiter=limit={limit_linear:.3f}:attack=5:release=50:level=disabled:latency=1")
	return ",".join(filters) if filters else None


def _append_audio_filter(args: list[str], audio_processing: Dict | None, src: pathlib.Path | None = None, ffmpeg_bin: str | None = None) -> None:
	filter_chain = _audio_filter_chain(audio_processing, src=src, ffmpeg_bin=ffmpeg_bin)
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
	_append_audio_filter(args, audio_processing, src=src, ffmpeg_bin=ffmpeg_bin)
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
				return _square_cover_art_bytes(r.content) or r.content
		except Exception:
			pass
	return None

def _square_cover_art_bytes(cover_bytes: bytes, *, size: int = 600) -> Optional[bytes]:
	"""
	Normalize embedded artwork to a square JPEG without stretching.
	Some older players assume cover art is square and distort non-square images.
	The image is center-cropped instead of padded so players do not show borders.
	"""
	if not cover_bytes:
		return None
	try:
		from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
		from PySide6.QtGui import QImage
		src = QImage()
		if src.loadFromData(cover_bytes):
			cropped = src.convertToFormat(QImage.Format_RGB32)
			cropped = cropped.scaled(
				size,
				size,
				Qt.KeepAspectRatioByExpanding,
				Qt.SmoothTransformation
			)
			x = max(0, (cropped.width() - size) // 2)
			y = max(0, (cropped.height() - size) // 2)
			cropped = cropped.copy(x, y, size, size)
			out = QByteArray()
			buf = QBuffer(out)
			buf.open(QIODevice.WriteOnly)
			if cropped.save(buf, "JPEG"):
				data = bytes(out)
				if len(data) > 1024:
					return data
	except Exception as exc:
		log(f"cover art Qt square normalization skipped: {exc}")
	try:
		ffmpeg_bin = ffmpeg_path()
		proc = subprocess.run(
			[
				ffmpeg_bin,
				"-hide_banner",
				"-loglevel", "error",
				"-f", "image2pipe",
				"-i", "pipe:0",
				"-vf", f"scale={size}:{size}:force_original_aspect_ratio=increase,crop={size}:{size}",
				"-frames:v", "1",
				"-f", "image2pipe",
				"-vcodec", "mjpeg",
				"pipe:1",
			],
			input=cover_bytes,
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
			**_hidden_subprocess_kwargs()
		)
		if proc.returncode == 0 and proc.stdout and len(proc.stdout) > 1024:
			return proc.stdout
	except Exception as exc:
		log(f"cover art square normalization skipped: {exc}")
	return None

def tag_file(path: pathlib.Path, meta: Dict, cover_bytes: Optional[bytes], *, cover_size: int = 600) -> None:
	if cover_bytes and cover_size > 0:
		cover_bytes = _square_cover_art_bytes(cover_bytes, size=cover_size) or cover_bytes
	elif cover_size <= 0:
		cover_bytes = None
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

def download_mp3(video_id: str, dst_dir: pathlib.Path, base_name: str, cbr_320: bool = False, *, yt_dlp_bin: str | None = None, ffmpeg_bin: str | None = None, extra_yt_dlp_args: List[str] | None = None, audio_processing: Dict | None = None, mp3_quality: int = 0, cbr_bitrate_kbps: int | None = None) -> pathlib.Path:
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
	_append_audio_filter(args, audio_processing, src=src, ffmpeg_bin=ffmpeg_bin)
	mp3_quality = max(0, min(10, int(mp3_quality)))
	if cbr_bitrate_kbps is not None:
		args += ["-codec:a","libmp3lame","-b:a", f"{max(96, int(cbr_bitrate_kbps))}k"]
	elif cbr_320:
		args += ["-codec:a","libmp3lame","-b:a","320k"]
	else:
		args += ["-codec:a","libmp3lame","-q:a", str(mp3_quality)]
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

def write_m3u(out_dir: pathlib.Path, playlist_name: str, tracks_done: List[Dict], ext: str, *, suffix: str = ".m3u8", encoding: str = "utf-8", target_dir: pathlib.Path | None = None) -> pathlib.Path:
	if target_dir is not None:
		playlist_dir = target_dir
	else:
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
