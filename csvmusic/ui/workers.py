# tabs only
from PySide6.QtCore import QObject, Signal, QThread
import pathlib, traceback, time, random
import subprocess
import sys, json
import sqlite3
import re, unicodedata
from typing import List, Dict

from ytmusicapi import YTMusic

from csvmusic.core.csv_import import load_csv, tracks_from_csv
from csvmusic.core.log import log
from csvmusic.core.ytmusic_match import find_best, more_candidates, RATE_LIMIT_S, CONFIDENCE_MIN
from csvmusic.core.downloader import (
	download_m4a, download_mp3, tag_file, yt_thumbnail_bytes, write_m3u, sanitize_name,
	youtube_batch_mitigation, build_ytdlp_mitigation_args, detect_youtube_risk,
	YOUTUBE_MITIGATION_NONE, YOUTUBE_MITIGATION_AGGRESSIVE, YouTubeMitigationProfile
)
from csvmusic.core.paths import ytdlp_path as _resolve_ytdlp, INTERNAL_YTDLP

_WINDOWS = sys.platform.startswith("win")
_FORCE_FALLBACK_MIN_SCORE = 0.45

def _legacy_cover_size(legacy_options: Dict | None, *, embed_art: bool) -> int:
	if not embed_art:
		return 0
	mode = str((legacy_options or {}).get("cover_art_mode") or "standard").lower()
	if mode == "off":
		return 0
	if mode == "small":
		return 300
	if mode == "medium":
		return 450
	return 600

def _legacy_cbr_bitrate(legacy_options: Dict | None) -> int | None:
	if not legacy_options or not legacy_options.get("enabled"):
		return None
	mode = str(legacy_options.get("mp3_mode") or "").lower()
	if mode == "cbr_192":
		return 192
	if mode == "cbr_256":
		return 256
	if mode == "cbr_320":
		return 320
	return None

def _norm_text(text: str) -> str:
	return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", (text or "").casefold())).strip()

def _tokens(text: str) -> set[str]:
	return {tok for tok in re.findall(r"\w+", _norm_text(text), flags=re.UNICODE) if any(ch.isalnum() for ch in tok)}

def _hidden_subprocess_kwargs() -> dict:
	if not _WINDOWS:
		return {}
	startupinfo = subprocess.STARTUPINFO()
	startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
	flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
	return {"startupinfo": startupinfo, "creationflags": flags}

def _run_yt_dlp_command(cmd: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
	if cmd and cmd[0] == INTERNAL_YTDLP:
		stdout_buf: list[str] = []
		stderr_buf: list[str] = []
		try:
			from yt_dlp import main as yt_dlp_main
		except Exception as exc:
			return subprocess.CompletedProcess(cmd, 1, "", f"failed to import yt_dlp module: {exc}")
		import io
		import contextlib
		out = io.StringIO()
		err = io.StringIO()
		with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
			try:
				rc = yt_dlp_main(cmd[1:])
			except SystemExit as exc:
				code = exc.code
				if isinstance(code, int):
					rc = code
				elif code is None:
					rc = 0
				else:
					rc = 1
			except Exception as exc:
				rc = 1
				err.write(str(exc))
		return subprocess.CompletedProcess(cmd, rc, out.getvalue(), err.getvalue())
	return subprocess.run(
		cmd,
		stdout=subprocess.PIPE,
		stderr=subprocess.PIPE,
		text=True,
		timeout=timeout,
		**_hidden_subprocess_kwargs()
	)

class PipelineWorker(QThread):
	sig_log = Signal(str)                       # log strings
	sig_warning = Signal(str)                   # warning dialog text
	sig_total = Signal(int)                     # total tracks queued
	sig_match_stats = Signal(int, int)          # matched, skipped
	sig_row_status = Signal(int, str)           # row_index, status text
	sig_progress = Signal(int, int)             # processed, total
	sig_done = Signal(str, list, list, list)    # final message, matched, skipped, failed
	sig_track_result = Signal(int, dict)        # per-track summary

	def __init__(self, csv_path: str, out_dir: str, playlist: str | None,
	             fmt: str,
	             write_m3u8: bool, write_m3u_plain: bool,
	             embed_art: bool,
	             yt_dlp_path: str | None,
	             ffmpeg_path_override: str | None,
	             cookies_browser: str | None,
	             cookies_file: str | None,
	             audio_processing: Dict | None = None,
	             mp3_quality: int = 0,
	             legacy_options: Dict | None = None,
	             force_download: bool = False,
	             tracks_override: List[Dict] | None = None,
	             row_indices: List[int] | None = None,
	             parent: QObject | None = None):
		super().__init__(parent)
		self.csv_path = csv_path
		self.out_dir = pathlib.Path(out_dir)
		self.playlist = playlist
		self.fmt = fmt
		self.write_m3u8 = write_m3u8
		self.write_m3u_plain = write_m3u_plain
		self.embed_art = embed_art
		self.yt_dlp_path = yt_dlp_path
		self.ffmpeg_path_override = ffmpeg_path_override
		self.cookies_browser = cookies_browser
		self.cookies_file = cookies_file
		self.audio_processing = audio_processing or {}
		self.mp3_quality = max(0, min(10, int(mp3_quality)))
		self.legacy_options = legacy_options or {}
		self.force_download = bool(force_download)
		self.tracks_override = tracks_override
		self.row_indices = row_indices or []
		self._stop = False
		self._mitigation = YOUTUBE_MITIGATION_NONE

	def stop(self):
		self._stop = True

	def _download_with_profile(self, vid: str, dest_dir: pathlib.Path, base: str, profile: YouTubeMitigationProfile):
		extra_args: list[str] = []
		if self.cookies_file:
			extra_args += ["--cookies", self.cookies_file]
		elif self.cookies_browser:
			extra_args += ["--cookies-from-browser", self.cookies_browser]
		extra_args += build_ytdlp_mitigation_args(profile)
		if self.fmt == "m4a":
			return download_m4a(vid, dest_dir, base, yt_dlp_bin=self.yt_dlp_path, ffmpeg_bin=self.ffmpeg_path_override, extra_yt_dlp_args=extra_args or None, audio_processing=self.audio_processing)
		return download_mp3(vid, dest_dir, base, yt_dlp_bin=self.yt_dlp_path, ffmpeg_bin=self.ffmpeg_path_override, extra_yt_dlp_args=extra_args or None, audio_processing=self.audio_processing, mp3_quality=self.mp3_quality, cbr_bitrate_kbps=_legacy_cbr_bitrate(self.legacy_options))

	def _apply_mitigation(self, profile: YouTubeMitigationProfile, reason: str | None = None) -> None:
		if profile.label == self._mitigation.label:
			return
		self._mitigation = profile
		if profile.warning:
			msg = profile.warning
			if reason:
				msg = f"{msg}\n\nDetected: {reason}"
			self.sig_log.emit(f"[warn] {msg}")
			self.sig_warning.emit(msg)

	def _track_pause_s(self) -> float:
		if self._mitigation.track_sleep_s <= 0:
			return RATE_LIMIT_S
		jitter = min(1.0, self._mitigation.track_sleep_s * 0.2)
		return max(RATE_LIMIT_S, random.uniform(self._mitigation.track_sleep_s - jitter, self._mitigation.track_sleep_s + jitter))

	def _is_official_candidate(self, cand: Dict) -> bool:
		source = str(cand.get("source") or "").lower()
		author = str(cand.get("author") or "").lower()
		title = str(cand.get("title") or "").lower()
		if source == "music":
			return True
		return any(term in author for term in ("topic", "official", "vevo")) or "official" in title

	def _candidate_relevant_to_track(self, track: Dict, cand: Dict) -> bool:
		track_artist_tokens = _tokens(track.get("artists", ""))
		track_title_tokens = _tokens(track.get("title", ""))
		cand_author_tokens = _tokens(cand.get("author", ""))
		cand_title_tokens = _tokens(cand.get("title", ""))
		artist_ok = bool(track_artist_tokens & (cand_author_tokens | cand_title_tokens))
		title_overlap = len(track_title_tokens & cand_title_tokens)
		return artist_ok and title_overlap >= max(1, min(2, len(track_title_tokens)))

	def _force_download_candidates(self, track: Dict, options: List[Dict]) -> List[Dict]:
		if not options:
			return []
		relevant = [opt for opt in options if self._candidate_relevant_to_track(track, opt)]
		pool = relevant or options
		official = [opt for opt in pool if self._is_official_candidate(opt)]
		standard = [opt for opt in pool if opt not in official]

		sequence: list[Dict] = []

		def _append_group(group: list[Dict]) -> None:
			if not group:
				return
			sequence.append(group[0])
			if len(group) > 1 and float(group[1].get("score", 0.0) or 0.0) >= _FORCE_FALLBACK_MIN_SCORE:
				sequence.append(group[1])

		_append_group(official)
		_append_group(standard)

		seen: set[str] = set()
		unique: list[Dict] = []
		for opt in sequence:
			vid = opt.get("videoId")
			if not vid or vid in seen:
				continue
			seen.add(vid)
			unique.append(opt)
		return unique

	def _ordered_force_candidates(self, track: Dict, match: Dict | None, options: List[Dict]) -> List[Dict]:
		if not self.force_download:
			return [match] if match else []
		ordered = self._force_download_candidates(track, options)
		if match and match.get("videoId"):
			match_vid = match.get("videoId")
			if not ordered:
				return [match]
			if ordered[0].get("videoId") != match_vid:
				ordered = [match] + [opt for opt in ordered if opt.get("videoId") != match_vid]
		return ordered or ([match] if match else [])

	def _attempt_status_text(self, candidate: Dict, attempt_idx: int, total_attempts: int, *, safe_mode: bool = False) -> str:
		source_label = "official result" if self._is_official_candidate(candidate) else "YouTube result"
		if total_attempts <= 1:
			base = f"Trying {source_label} ({self.fmt})…"
		elif attempt_idx == 1:
			base = f"Trying {source_label} 1/{total_attempts} ({self.fmt})…"
		else:
			base = f"Trying fallback {source_label} {attempt_idx}/{total_attempts} ({self.fmt})…"
		if safe_mode:
			return f"Safe mode: {base[0].lower()}{base[1:]}"
		return base

	def run(self):
		try:
			self.sig_log.emit("[csv] loading…")
			if self.tracks_override is not None:
				tracks = list(self.tracks_override)
			else:
				df = load_csv(self.csv_path)
				tracks = tracks_from_csv(df, self.playlist)
			if not tracks:
				self.sig_done.emit("No tracks selected.", [], [], [])
				return
			total = len(tracks)
			self.sig_total.emit(total)
			self._mitigation = youtube_batch_mitigation(total, using_cookies=bool(self.cookies_file or self.cookies_browser))
			if self._mitigation.warning:
				self.sig_log.emit(f"[warn] {self._mitigation.warning}")
			self.sig_log.emit("[match] searching on YouTube Music…")
			matched = 0
			skipped_count = 0
			self.sig_match_stats.emit(matched, skipped_count)
			try:
				yt = YTMusic()
			except Exception as exc:
				raise RuntimeError(f"Failed to initialize YTMusic client: {exc}")
			playlist_name = self.playlist or (tracks[0]["playlist"] if tracks else "Playlist")
			if not playlist_name:
				playlist_name = "Playlist"
			safe_playlist = sanitize_name(playlist_name) or "Playlist"
			dest_dir = self.out_dir / safe_playlist
			dest_dir.mkdir(parents=True, exist_ok=True)
			done_tracks: List[Dict] = []
			failed_tracks: List[Dict] = []
			skipped_tracks: List[Dict] = []
			processed = 0
			for idx, track in enumerate(tracks):
				row_idx = self.row_indices[idx] if idx < len(self.row_indices) else idx
				if self._stop:
					break
				t = track
				title = t["title"]
				artists = t["artists"]
				search_error = None
				options: List[Dict] = []
				match = None
				confidence = 0.0
				try:
					match, confidence, options = find_best(yt, t)
				except Exception as exc:
					search_error = str(exc)
				payload = {
					"track": t,
					"options": options,
					"match": match,
					"confidence": confidence,
					"skipped": False,
					"error": None,
					"playlist_name": playlist_name,
					"file_path": None,
					"downloaded": False,
					"cover_bytes": None,
					"forced_match": False
				}

				if match is None and self.force_download and options:
					forced_candidates = self._force_download_candidates(t, options)
					match = forced_candidates[0] if forced_candidates else options[0]
					confidence = float(match.get("score", confidence or 0.0) or 0.0)
					payload["match"] = match
					payload["confidence"] = confidence
					payload["forced_match"] = True

				if match is None:
					if search_error:
						log(f"match skip: query='{t['title']} {t['artists']}' error={search_error}")
					else:
						log(f"match skip: query='{t['title']} {t['artists']}' no candidate >= threshold (confidence={confidence:.2f})")
					payload["skipped"] = True
					payload["error"] = search_error
					reason = search_error or "No confident match"
					skipped_tracks.append({"track": t, "reason": reason, "options": options})
					self.sig_row_status.emit(row_idx, "Skipped (no good match)")
					processed += 1
					self.sig_progress.emit(processed, total)
					self.sig_track_result.emit(row_idx, payload)
					skipped_count += 1
					self.sig_match_stats.emit(matched, skipped_count)
					if not self._stop and idx < total - 1:
						time.sleep(self._track_pause_s())
					continue

				payload["match"] = match
				matched += 1
				self.sig_match_stats.emit(matched, skipped_count)
				vid = match["videoId"]
				low_confidence = payload.get("forced_match") or confidence < CONFIDENCE_MIN
				if low_confidence:
					self.sig_row_status.emit(row_idx, f"Downloading low-confidence match ({self.fmt})…")
				else:
					self.sig_row_status.emit(row_idx, f"Downloading ({self.fmt})…")
				error_msg = None
				candidate_sequence = self._ordered_force_candidates(t, match, options)
				fallback_attempts_enabled = self.force_download and len(candidate_sequence) > 1

				try:
					base = f"{artists} - {title}"
					last_err = None
					fp = None
					cover = None
					for attempt_idx, candidate in enumerate(candidate_sequence, start=1):
						vid = candidate["videoId"]
						if fallback_attempts_enabled:
							self.sig_row_status.emit(
								row_idx,
								self._attempt_status_text(candidate, attempt_idx, len(candidate_sequence))
							)
						try:
							fp = self._download_with_profile(vid, dest_dir, base, self._mitigation)
							self.sig_row_status.emit(row_idx, "Tagging…")
							cover = yt_thumbnail_bytes(vid)
							tag_file(fp, t, cover if self.embed_art else None, cover_size=_legacy_cover_size(self.legacy_options, embed_art=self.embed_art))
							payload["match"] = candidate
							break
						except Exception as candidate_exc:
							last_err = str(candidate_exc)
					if fp is None:
						raise RuntimeError(last_err or "Download failed.")
					if low_confidence:
						self.sig_row_status.emit(row_idx, f"Low confidence → {fp.name}")
					else:
						self.sig_row_status.emit(row_idx, f"Done → {fp.name}")
					done_tracks.append(t)
				except Exception as e:
					err = str(e)
					risk_reason = detect_youtube_risk(err)
					retried = False
					if risk_reason and self._mitigation.label != YOUTUBE_MITIGATION_AGGRESSIVE.label:
						self._apply_mitigation(YOUTUBE_MITIGATION_AGGRESSIVE, risk_reason)
						try:
							self.sig_row_status.emit(row_idx, "Retrying with YouTube safe mode…")
							last_retry_err = None
							fp = None
							cover = None
							for attempt_idx, candidate in enumerate(candidate_sequence, start=1):
								vid = candidate["videoId"]
								if fallback_attempts_enabled:
									self.sig_row_status.emit(
										row_idx,
										self._attempt_status_text(candidate, attempt_idx, len(candidate_sequence), safe_mode=True)
									)
								try:
									fp = self._download_with_profile(vid, dest_dir, base, self._mitigation)
									self.sig_row_status.emit(row_idx, "Tagging…")
									cover = yt_thumbnail_bytes(vid)
									tag_file(fp, t, cover if self.embed_art else None, cover_size=_legacy_cover_size(self.legacy_options, embed_art=self.embed_art))
									payload["match"] = candidate
									break
								except Exception as retry_candidate_exc:
									last_retry_err = str(retry_candidate_exc)
							if fp is None:
								raise RuntimeError(last_retry_err or "Download failed.")
							if low_confidence:
								self.sig_row_status.emit(row_idx, f"Low confidence → {fp.name}")
							else:
								self.sig_row_status.emit(row_idx, f"Done → {fp.name}")
							done_tracks.append(t)
							retried = True
						except Exception as retry_exc:
							err = str(retry_exc)
					if not retried:
						log(f"download failure: playlist='{playlist_name}' track='{artists} — {title}' fmt={self.fmt} error={err}")
						self.sig_row_status.emit(row_idx, f"Fail: {err[:120]}")
						failed_tracks.append({"track": t, "error": err})
						error_msg = err
				finally:
					processed += 1
					self.sig_progress.emit(processed, total)

				payload["error"] = error_msg
				if error_msg is None:
					payload["downloaded"] = True
					payload["file_path"] = str(fp)
					payload["cover_bytes"] = cover
				self.sig_track_result.emit(row_idx, payload)
				if not self._stop and idx < total - 1:
					time.sleep(self._track_pause_s())
				time.sleep(0.02)
			if done_tracks:
				ext = "m4a" if self.fmt == "m4a" else "mp3"
				if self.write_m3u8:
					m3u = write_m3u(self.out_dir, playlist_name, done_tracks, ext, suffix=".m3u8", encoding="utf-8")
					self.sig_log.emit(f"[m3u] wrote: {m3u}")
				if self.write_m3u_plain:
					m3u_plain = write_m3u(self.out_dir, playlist_name, done_tracks, ext, suffix=".m3u", encoding="utf-8-sig")
					self.sig_log.emit(f"[m3u] wrote: {m3u_plain}")
			msg = "All tasks finished."
			if self._stop:
				msg = "Stopped (partial results saved)."
			self.sig_done.emit(msg, done_tracks, skipped_tracks, failed_tracks)
		except Exception:
			self.sig_done.emit("Fatal error:\n" + traceback.format_exc(), [], [], [])



class SingleDownloadWorker(QThread):
	sig_status = Signal(int, str)
	sig_finished = Signal(int, dict)

	def __init__(self, row_idx: int, track: Dict, match: Dict, out_dir: str,
	             fmt: str, embed_art: bool,
	             yt_dlp_path: str | None,
	             ffmpeg_path_override: str | None,
	             cookies_browser: str | None,
	             cookies_file: str | None,
	             audio_processing: Dict | None = None,
	             mp3_quality: int = 0,
	             legacy_options: Dict | None = None,
	             force_download: bool = False,
	             parent: QObject | None = None):
		super().__init__(parent)
		self.row_idx = row_idx
		self.track = track
		self.match = match
		self.out_dir = pathlib.Path(out_dir)
		self.fmt = fmt
		self.embed_art = embed_art
		self.playlist_name = track.get("playlist") or "Playlist"
		self.yt_dlp_path = yt_dlp_path
		self.ffmpeg_path_override = ffmpeg_path_override
		self.cookies_browser = cookies_browser
		self.cookies_file = cookies_file
		self.audio_processing = audio_processing or {}
		self.mp3_quality = max(0, min(10, int(mp3_quality)))
		self.legacy_options = legacy_options or {}
		self.force_download = bool(force_download)

	def run(self):
		try:
			safe_playlist = sanitize_name(self.playlist_name) or "Playlist"
			dest_dir = self.out_dir / safe_playlist
			dest_dir.mkdir(parents=True, exist_ok=True)

			base = f"{self.track.get('artists','')} - {self.track.get('title','')}"
			vid = self.match.get("videoId")
			self.sig_status.emit(self.row_idx, f"Downloading ({self.fmt})…")
			if self.cookies_file:
				cookies_args = ["--cookies", self.cookies_file]
			elif self.cookies_browser:
				cookies_args = ["--cookies-from-browser", self.cookies_browser]
			else:
				cookies_args = None
			if self.fmt == "m4a":
				fp = download_m4a(vid, dest_dir, base, yt_dlp_bin=self.yt_dlp_path, ffmpeg_bin=self.ffmpeg_path_override, extra_yt_dlp_args=cookies_args, audio_processing=self.audio_processing)
			else:
				fp = download_mp3(vid, dest_dir, base, yt_dlp_bin=self.yt_dlp_path, ffmpeg_bin=self.ffmpeg_path_override, extra_yt_dlp_args=cookies_args, audio_processing=self.audio_processing, mp3_quality=self.mp3_quality, cbr_bitrate_kbps=_legacy_cbr_bitrate(self.legacy_options))
			self.sig_status.emit(self.row_idx, "Tagging…")
			cover = yt_thumbnail_bytes(vid)
			tag_file(fp, self.track, cover if self.embed_art else None, cover_size=_legacy_cover_size(self.legacy_options, embed_art=self.embed_art))
			self.sig_status.emit(self.row_idx, f"Done → {fp.name}")
			payload = {
				"track": self.track,
				"match": self.match,
				"file_path": str(fp),
				"downloaded": True,
				"error": None,
				"playlist_name": self.playlist_name,
				"cover_bytes": cover
			}
			self.sig_finished.emit(self.row_idx, payload)
		except Exception as e:
			err = str(e)
			log(f"manual download failure: playlist='{self.playlist_name}' track='{self.track.get('artists','')} — {self.track.get('title','')}' fmt={self.fmt} error={err}")
			self.sig_status.emit(self.row_idx, f"Fail: {err[:120]}")
			payload = {
				"track": self.track,
				"match": self.match,
				"file_path": None,
				"downloaded": False,
				"error": err,
				"playlist_name": self.playlist_name
			}
			self.sig_finished.emit(self.row_idx, payload)


class AlternativesFetchWorker(QThread):
	sig_done = Signal(int, list, str)

	def __init__(self, row_idx: int, track: Dict, exclude_ids: set[str] | None = None, parent: QObject | None = None):
		super().__init__(parent)
		self.row_idx = row_idx
		self.track = track
		self.exclude_ids = set(exclude_ids or set())

	def run(self):
		try:
			options = more_candidates(self.track, exclude_ids=self.exclude_ids, source_mode="all")
			self.sig_done.emit(self.row_idx, options, "")
		except Exception as exc:
			log(f"alternatives fetch failure: track='{self.track.get('artists','')} — {self.track.get('title','')}' error={exc}")
			self.sig_done.emit(self.row_idx, [], str(exc))


class CookiesCheckWorker(QThread):
	# Emits (ok, message)
	sig_done = Signal(bool, str)

	def __init__(self, cookies_browser: str | None, cookies_file: str | None, yt_dlp_path: str | None, parent: QObject | None = None):
		super().__init__(parent)
		self.cookies_browser = cookies_browser
		self.cookies_file = cookies_file
		self.yt_dlp_path = yt_dlp_path

	def run(self):
		try:
			yt = self.yt_dlp_path or _resolve_ytdlp()
			# Firefox profile pre-check: if a concrete profile path is provided, verify cookies DB exists
			ff_signed_in_hint = None
			if self.cookies_browser:
				parts = str(self.cookies_browser).split(":", 1)
				bid = parts[0].strip().lower()
				prof = parts[1].strip() if len(parts) == 2 else None
				if bid == "firefox" and prof:
					try:
						db = pathlib.Path(prof) / "cookies.sqlite"
						if not db.exists():
							self.sig_done.emit(False, "Firefox cookies DB not found for selected profile.")
							return
						conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
						cur = conn.cursor()
						cur.execute(
							"SELECT name FROM moz_cookies WHERE (host LIKE '%youtube.com' OR host LIKE '%google.com') AND name IN (?,?,?,?,?,?,?) LIMIT 1",
							("__Secure-3PSID","__Secure-1PSID","SAPISID","APISID","SID","SSID","HSID")
						)
						ff_signed_in_hint = cur.fetchone() is not None
						conn.close()
					except Exception:
						# Ignore DB probing errors; continue with yt-dlp probing
						pass
			cmd = [yt]
			if self.cookies_file:
				cmd += ["--cookies", self.cookies_file]
			elif self.cookies_browser:
				cmd += ["--cookies-from-browser", self.cookies_browser]
			# Use YouTube homepage extraction to trigger cookie loading without requiring media formats.
			cmd += ["--skip-download", "--flat-playlist", "--playlist-items", "0", "https://www.youtube.com/"]
			proc = _run_yt_dlp_command(cmd, timeout=12)
			if proc.returncode == 0:
				# Even on success, detect cookie DB issues from logs
				stderr = (proc.stderr or ""); stdout = (proc.stdout or "")
				low_all = (stderr + " \n" + stdout).lower()
				if ("cookie" in low_all) and ("could not" in low_all or "not find" in low_all or "no such file" in low_all):
					self.sig_done.emit(False, "Could not find cookies in database. Check profile selection.")
					return
				# Determine signed-in state
				signed_in = False
				account_hint = None
				# No account name probing; keep it lightweight
				if self.cookies_file:
					try:
						with open(self.cookies_file, "r", encoding="utf-8", errors="ignore") as f:
							for line in f:
								line = line.strip()
								if not line or line.startswith("#"):
									continue
								parts = line.split("\t")
								if len(parts) < 7:
									continue
								domain = parts[0].lower()
								name = parts[5]
								if ("youtube.com" in domain or "google.com" in domain) and name in {"__Secure-3PSID","__Secure-1PSID","SAPISID","APISID","SID","SSID","HSID"}:
									signed_in = True
									break
					except Exception:
						pass
					# Try to extract account hint via yt-dlp JSON of feed/you
					probe = [yt, "--cookies", self.cookies_file, "-J", "https://www.youtube.com/feed/you"]
					proc_acc = _run_yt_dlp_command(probe, timeout=12)
					if proc_acc.returncode == 0 and proc_acc.stdout:
						try:
							obj = json.loads(proc_acc.stdout)
							account_hint = self._extract_account_hint(obj)
						except Exception:
							pass
						if not account_hint:
							account_hint = self._extract_account_hint_text(proc_acc.stdout)
					# Fallback: probe homepage for hints
					if not account_hint:
						try:
							probe2 = [yt, "--cookies", self.cookies_file, "-J", "https://www.youtube.com/"]
							proc_home = _run_yt_dlp_command(probe2, timeout=12)
							if proc_home.returncode == 0 and proc_home.stdout:
								try:
									obj2 = json.loads(proc_home.stdout)
									account_hint = self._extract_account_hint(obj2) or self._extract_account_hint_text(proc_home.stdout)
								except Exception:
									account_hint = self._extract_account_hint_text(proc_home.stdout)
						except Exception:
							pass
				else:
					# For Firefox, prefer the DB hint result; otherwise do a lightweight probe
					if ff_signed_in_hint is not None:
						signed_in = bool(ff_signed_in_hint)
					else:
						signed_in = "found youtube account cookies" in low_all
				msg = "Signed-in cookies detected" if signed_in else "Guest session (no account cookies)"
				self.sig_done.emit(True, msg)
				return
			stderr = (proc.stderr or "")
			low = stderr.lower()
			if self.cookies_browser and ff_signed_in_hint is True and "signature solving failed" in low:
				self.sig_done.emit(True, "Signed-in cookies detected. YouTube signature warnings may still affect some videos.")
				return
			if ("could not copy" in low and "cookie" in low) or ("locked" in low and "cookie" in low):
				self.sig_done.emit(False, "Cookie DB locked. Close browser and retry.")
				return
			if "dpapi" in low or "cryptprotectdata" in low:
				self.sig_done.emit(False, "DPAPI decryption error. Use same Windows user.")
				return
			self.sig_done.emit(False, stderr.strip()[:160] or "Cookie test failed.")
		except subprocess.TimeoutExpired:
			self.sig_done.emit(False, "Cookie test timeout.")
		except Exception as e:
			self.sig_done.emit(False, str(e)[:160])
