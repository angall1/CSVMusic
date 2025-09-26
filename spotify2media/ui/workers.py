# tabs only
from PySide6.QtCore import QObject, Signal, QThread
import pathlib, traceback, time
from typing import Optional, List, Dict, Set

from spotify2media.core.csv_import import load_csv, tracks_from_csv
from spotify2media.core.ytmusic_match import batch_match
from spotify2media.core.downloader import (
	download_m4a, download_mp3, tag_file, yt_thumbnail_bytes, write_m3u, sanitize_name
)

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
			results = batch_match(tracks)
			matched = sum(1 for r in results if not r.get("skipped"))
			skipped_initial = total - matched
			self.sig_match_stats.emit(matched, skipped_initial)
			playlist_name = self.playlist or (tracks[0]["playlist"] if tracks else "Playlist")
			if not playlist_name:
				playlist_name = "Playlist"
			safe_playlist = sanitize_name(playlist_name) or "Playlist"
			dest_dir = self.out_dir / safe_playlist
			dest_dir.mkdir(parents=True, exist_ok=True)
			done_tracks: List[Dict] = []
			failed_tracks: List[Dict] = []
			processed = 0
			for idx, r in enumerate(results):
				if self._stop:
					break
				t = r["track"]
				title = t["title"]
				artists = t["artists"]
				options = r.get("options") or []
				payload = {
					"track": t,
					"options": options,
					"match": r.get("match"),
					"confidence": r.get("confidence", 0.0),
					"skipped": bool(r.get("skipped")),
					"error": r.get("error"),
					"playlist_name": playlist_name,
					"file_path": None,
					"downloaded": False
				}

				if r.get("skipped"):
					self.sig_row_status.emit(idx, "Skipped (no good match)")
					processed += 1
					self.sig_progress.emit(processed, total)
					self.sig_track_result.emit(idx, payload)
					continue

				vid = r["match"]["videoId"]
				self.sig_row_status.emit(idx, f"Downloading ({self.fmt})…")
				error_msg = None

				try:
					base = f"{artists} - {title}"
					if self.fmt == "m4a":
						fp = download_m4a(vid, dest_dir, base, yt_dlp_bin=self.yt_dlp_path, ffmpeg_bin=self.ffmpeg_path_override)
					else:
						fp = download_mp3(vid, dest_dir, base, yt_dlp_bin=self.yt_dlp_path, ffmpeg_bin=self.ffmpeg_path_override)
					self.sig_row_status.emit(idx, "Tagging…")
					cover = yt_thumbnail_bytes(vid) if self.embed_art else None
					tag_file(fp, t, cover)
					self.sig_row_status.emit(idx, f"Done → {fp.name}")
					done_tracks.append(t)
				except Exception as e:
					err = str(e)
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
				time.sleep(0.02)
			if done_tracks:
				ext = "m4a" if self.fmt == "m4a" else "mp3"
				if self.write_m3u8:
					m3u = write_m3u(self.out_dir, playlist_name, done_tracks, ext, suffix=".m3u8", encoding="utf-8")
					self.sig_log.emit(f"[m3u] wrote: {m3u}")
				if self.write_m3u_plain:
					m3u_plain = write_m3u(self.out_dir, playlist_name, done_tracks, ext, suffix=".m3u", encoding="cp1252")
					self.sig_log.emit(f"[m3u] wrote: {m3u_plain}")
			skipped_tracks = []
			for r in results:
				if r.get("skipped"):
					reason = r.get("error") or "No confident match"
					entry = {"track": r["track"], "reason": reason, "options": r.get("options", [])}
					skipped_tracks.append(entry)
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

	def run(self):
		try:
			safe_playlist = sanitize_name(self.playlist_name) or "Playlist"
			dest_dir = self.out_dir / safe_playlist
			dest_dir.mkdir(parents=True, exist_ok=True)

			base = f"{self.track.get('artists','')} - {self.track.get('title','')}"
			vid = self.match.get("videoId")
			self.sig_status.emit(self.row_idx, f"Downloading ({self.fmt})…")
			if self.fmt == "m4a":
				fp = download_m4a(vid, dest_dir, base, yt_dlp_bin=self.yt_dlp_path, ffmpeg_bin=self.ffmpeg_path_override)
			else:
				fp = download_mp3(vid, dest_dir, base, yt_dlp_bin=self.yt_dlp_path, ffmpeg_bin=self.ffmpeg_path_override)
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
