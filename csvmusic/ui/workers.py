# tabs only
from PySide6.QtCore import QObject, Signal, QThread
import pathlib, traceback, time
import subprocess
import sqlite3
from typing import List, Dict

from ytmusicapi import YTMusic

from csvmusic.core.csv_import import load_csv, tracks_from_csv
from csvmusic.core.log import log
from csvmusic.core.ytmusic_match import find_best, RATE_LIMIT_S
from csvmusic.core.downloader import (
	download_m4a, download_mp3, tag_file, yt_thumbnail_bytes, write_m3u, sanitize_name
)
from csvmusic.core.paths import ytdlp_path as _resolve_ytdlp

class PipelineWorker(QThread):
	sig_log = Signal(str)                       # log strings
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
		self._stop = False

	def stop(self):
		self._stop = True

	def run(self):
		try:
			self.sig_log.emit("[csv] loading…")
			df = load_csv(self.csv_path)
			tracks = tracks_from_csv(df, self.playlist)
			if not tracks:
				self.sig_done.emit("No tracks selected.", [], [], [])
				return
			total = len(tracks)
			self.sig_total.emit(total)
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
					"downloaded": False
				}

				if match is None:
					if search_error:
						log(f"match skip: query='{t['title']} {t['artists']}' error={search_error}")
					else:
						log(f"match skip: query='{t['title']} {t['artists']}' no candidate >= threshold (confidence={confidence:.2f})")
					payload["skipped"] = True
					payload["error"] = search_error
					reason = search_error or "No confident match"
					skipped_tracks.append({"track": t, "reason": reason, "options": options})
					self.sig_row_status.emit(idx, "Skipped (no good match)")
					processed += 1
					self.sig_progress.emit(processed, total)
					self.sig_track_result.emit(idx, payload)
					skipped_count += 1
					self.sig_match_stats.emit(matched, skipped_count)
					if not self._stop and idx < total - 1:
						time.sleep(RATE_LIMIT_S)
					continue

				payload["match"] = match
				matched += 1
				self.sig_match_stats.emit(matched, skipped_count)
				vid = match["videoId"]
				self.sig_row_status.emit(idx, f"Downloading ({self.fmt})…")
				error_msg = None

				try:
					base = f"{artists} - {title}"
					if self.cookies_file:
						cookies_args = ["--cookies", self.cookies_file]
					elif self.cookies_browser:
						cookies_args = ["--cookies-from-browser", self.cookies_browser]
					else:
						cookies_args = None
					if self.fmt == "m4a":
						fp = download_m4a(vid, dest_dir, base, yt_dlp_bin=self.yt_dlp_path, ffmpeg_bin=self.ffmpeg_path_override, extra_yt_dlp_args=cookies_args)
					else:
						fp = download_mp3(vid, dest_dir, base, yt_dlp_bin=self.yt_dlp_path, ffmpeg_bin=self.ffmpeg_path_override, extra_yt_dlp_args=cookies_args)
					self.sig_row_status.emit(idx, "Tagging…")
					cover = yt_thumbnail_bytes(vid) if self.embed_art else None
					tag_file(fp, t, cover)
					self.sig_row_status.emit(idx, f"Done → {fp.name}")
					done_tracks.append(t)
				except Exception as e:
					err = str(e)
					log(f"download failure: playlist='{playlist_name}' track='{artists} — {title}' fmt={self.fmt} error={err}")
					self.sig_row_status.emit(idx, f"Fail: {err[:120]}")
					failed_tracks.append({"track": t, "error": err})
					error_msg = err
				finally:
					processed += 1
					self.sig_progress.emit(processed, total)

				payload["error"] = error_msg
				if error_msg is None:
					payload["downloaded"] = True
					payload["file_path"] = str(fp)
				self.sig_track_result.emit(idx, payload)
				if not self._stop and idx < total - 1:
					time.sleep(RATE_LIMIT_S)
				time.sleep(0.02)
			if done_tracks:
				ext = "m4a" if self.fmt == "m4a" else "mp3"
				if self.write_m3u8:
					m3u = write_m3u(self.out_dir, playlist_name, done_tracks, ext, suffix=".m3u8", encoding="utf-8")
					self.sig_log.emit(f"[m3u] wrote: {m3u}")
				if self.write_m3u_plain:
					m3u_plain = write_m3u(self.out_dir, playlist_name, done_tracks, ext, suffix=".m3u", encoding="cp1252")
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
				fp = download_m4a(vid, dest_dir, base, yt_dlp_bin=self.yt_dlp_path, ffmpeg_bin=self.ffmpeg_path_override, extra_yt_dlp_args=cookies_args)
			else:
				fp = download_mp3(vid, dest_dir, base, yt_dlp_bin=self.yt_dlp_path, ffmpeg_bin=self.ffmpeg_path_override, extra_yt_dlp_args=cookies_args)
			self.sig_status.emit(self.row_idx, "Tagging…")
			cover = yt_thumbnail_bytes(vid) if self.embed_art else None
			tag_file(fp, self.track, cover)
			self.sig_status.emit(self.row_idx, f"Done → {fp.name}")
			payload = {
				"track": self.track,
				"match": self.match,
				"file_path": str(fp),
				"downloaded": True,
				"error": None,
				"playlist_name": self.playlist_name
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
			# Use a harmless simulation JSON fetch to trigger cookie handling
			cmd += ["-s", "-J", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"]
			proc = subprocess.run(
				cmd,
				stdout=subprocess.PIPE,
				stderr=subprocess.PIPE,
				text=True,
				timeout=12,
			)
			if proc.returncode == 0:
				# Even on success, detect cookie DB issues from logs
				stderr = (proc.stderr or ""); stdout = (proc.stdout or "")
				low_all = (stderr + " \n" + stdout).lower()
				if ("cookie" in low_all) and ("could not" in low_all or "not find" in low_all or "no such file" in low_all):
					self.sig_done.emit(False, "Could not find cookies in database. Check profile selection.")
					return
				# Determine signed-in state
				signed_in = False
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
					proc_acc = subprocess.run(probe, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=12)
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
							proc_home = subprocess.run(probe2, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=12)
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
						probe = [yt]
						if self.cookies_browser:
							probe += ["--cookies-from-browser", self.cookies_browser]
						probe += ["-J", "https://www.youtube.com/feed/you"]
						proc2 = subprocess.run(probe, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=12)
						signed_in = (proc2.returncode == 0 and (proc2.stdout or "").strip().startswith("{"))
				msg = "Signed-in cookies detected" if signed_in else "Guest session (no account cookies)"
				self.sig_done.emit(True, msg)
				return
			stderr = (proc.stderr or "")
			low = stderr.lower()
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

