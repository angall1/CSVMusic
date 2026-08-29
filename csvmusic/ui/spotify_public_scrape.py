# tabs only
import json
import math
import random
import secrets
from typing import Any
from urllib.parse import urlparse

from PySide6.QtCore import QThread, QTimer, QUrl, Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
	QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
	QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from csvmusic.core.spotify_import import SpotifyImportError, fetch_spotify_playlist, parse_spotify_source
from csvmusic.core.log import log


_SCROLL_INTERVALS_MS = (350, 550, 1200)
_SCROLL_JITTER_RATIO = 0.08


def jittered_scroll_delay_ms(base_ms: int) -> int:
	variance = max(1, round(base_ms * _SCROLL_JITTER_RATIO))
	return random.randint(max(1, base_ms - variance), base_ms + variance)


_CAPTURE_SCRIPT = r"""
(() => {
	const tracks = [];
	const trackLinks = [...document.querySelectorAll('a[href*="/track/"]')];
	for (const trackLink of trackLinks) {
		const precedingHeadings = [...document.querySelectorAll('h1, h2, h3')]
			.filter(heading => heading.compareDocumentPosition(trackLink) & Node.DOCUMENT_POSITION_FOLLOWING);
		const sectionHeading = precedingHeadings.length
			? (precedingHeadings[precedingHeadings.length - 1].innerText || '').trim().toLowerCase()
			: '';
		if (sectionHeading.includes('recommended')) continue;
		const href = trackLink.href || '';
		const match = href.match(/\/track\/([A-Za-z0-9]+)/);
		if (!match) continue;
		const row = trackLink.closest('[role="row"], [data-testid*="tracklist-row"]')
			|| trackLink.parentElement?.parentElement?.parentElement || trackLink.parentElement;
		if (!row) continue;
		const artistLinks = [...row.querySelectorAll('a[href*="/artist/"]')];
		const albumLink = row.querySelector('a[href*="/album/"]');
		const artwork = row.querySelector('img');
		const lines = (row.innerText || '').split('\n').map(x => x.trim()).filter(Boolean);
		const title = (trackLink.innerText || trackLink.textContent || lines[0] || '').trim();
		const positionText = lines.find(line => /^\d{1,5}$/.test(line)) || '';
		const position = positionText ? parseInt(positionText, 10) : null;
		tracks.push({
			id: match[1],
			position,
			title,
			artists: artistLinks.map(x => (x.innerText || x.textContent || '').trim()).filter(Boolean),
			album: albumLink ? (albumLink.innerText || albumLink.textContent || '').trim() : '',
			cover_url: artwork ? (artwork.currentSrc || artwork.src || '') : '',
			text: lines,
		});
	}
	const candidates = [
		document.scrollingElement,
		document.querySelector('main'),
		...document.querySelectorAll('[data-overlayscrollbars-viewport], .os-viewport, [data-testid="playlist-tracklist"]')
	]
		.filter(Boolean)
		.filter(el => el.scrollHeight > el.clientHeight + 100)
		.sort((a, b) => b.scrollHeight - a.scrollHeight)
		.slice(0, 8);
	if (__SHOULD_SCROLL__) {
		for (const scroller of candidates) {
			const distance = Math.max(__MIN_SCROLL_PX__, Math.floor(scroller.clientHeight * __SCROLL_MULTIPLIER__));
			scroller.scrollTop = Math.min(scroller.scrollHeight, scroller.scrollTop + distance);
			scroller.dispatchEvent(new Event('scroll', {bubbles: true}));
		}
		window.scrollBy(0, Math.max(__MIN_SCROLL_PX__, Math.floor(window.innerHeight * __SCROLL_MULTIPLIER__)));
		document.dispatchEvent(new KeyboardEvent('keydown', {key: 'PageDown', code: 'PageDown', bubbles: true}));
	}
	const dialogText = [...document.querySelectorAll('[role="dialog"]')]
		.map(el => el.innerText || '').join(' ').toLowerCase();
	const bodyText = document.body ? document.body.innerText || '' : '';
	const playlistHeading = document.querySelector('main h1, h1');
	let playlistCover = '';
	for (let node = playlistHeading?.parentElement; node && !playlistCover; node = node.parentElement) {
		const image = node.querySelector('img');
		if (image) playlistCover = image.currentSrc || image.src || '';
		if (node.tagName === 'MAIN') break;
	}
	const totalMatch = bodyText.match(/(?:^|\s)([\d,]+)\s+(?:songs|tracks)(?:\s|$)/i);
	return JSON.stringify({
		tracks,
		trackLinks: trackLinks.length,
		scrollers: candidates.length,
		title: document.title,
		playlistCover,
		reportedTotal: totalMatch ? parseInt(totalMatch[1].replace(/,/g, ''), 10) : null,
		signInWall: dialogText.includes('sign up') || dialogText.includes('log in'),
	});
})()
"""


class SpotifyBaselineWorker(QThread):
	finished_baseline = Signal(bool, object, str)

	def __init__(self, url: str, parent=None):
		super().__init__(parent)
		self.url = url

	def run(self) -> None:
		try:
			playlist = fetch_spotify_playlist(self.url)
		except Exception as exc:
			self.finished_baseline.emit(False, None, str(exc))
		else:
			self.finished_baseline.emit(True, playlist, "")


class ScraperWebPage(QWebEnginePage):
	def javaScriptConsoleMessage(self, level, message: str, line_number: int, source_id: str) -> None:
		level_name = getattr(level, "name", str(level))
		if "Warning" not in level_name and "Error" not in level_name:
			return
		source = urlparse(source_id or "")
		safe_source = f"{source.scheme}://{source.netloc}{source.path}" if source.netloc else "inline"
		safe_message = " ".join(str(message).split())[:500]
		log(f"spotify_public_scrape browser_console level={level_name} source={safe_source} line={line_number} message={safe_message}")


def normalized_capture(item: Any) -> dict | None:
	if not isinstance(item, dict):
		return None
	track_id = str(item.get("id") or "").strip()
	title = str(item.get("title") or "").strip()
	artists = item.get("artists") if isinstance(item.get("artists"), list) else []
	artist_text = ", ".join(str(value).strip() for value in artists if str(value).strip())
	if not track_id or not title:
		return None
	return {
		"id": track_id,
		"position": _safe_position(item.get("position")),
		"title": title,
		"artists": artist_text,
		"album": str(item.get("album") or "").strip(),
		"cover_url": str(item.get("cover_url") or "").strip() or None,
	}


def _safe_position(value: Any) -> int | None:
	try:
		position = int(value)
	except (TypeError, ValueError):
		return None
	return position if position > 0 else None


def ordered_playlist_tracks(tracks: list[dict], reported_total: int | None) -> list[dict]:
	"""Return numbered playlist rows in stable order, excluding recommendation cards."""
	if not reported_total:
		return tracks
	by_position: dict[int, dict] = {}
	for track in tracks:
		position = _safe_position(track.get("position"))
		if position is not None and position <= reported_total:
			by_position[position] = track
	return [by_position[position] for position in sorted(by_position)]


def recover_single_missing_position(captured: list[dict], existing: dict[str, dict], reported_total: int | None) -> list[dict]:
	"""Recover one rendered row when Spotify omits its visible playlist number."""
	if not reported_total:
		return captured
	occupied = {
		position for track in existing.values()
		if (position := _safe_position(track.get("position"))) is not None and position <= reported_total
	}
	for track in captured:
		position = _safe_position(track.get("position"))
		if position is not None and position <= reported_total:
			occupied.add(position)
	missing = [position for position in range(1, reported_total + 1) if position not in occupied]
	positionless = [
		track for track in captured
		if not _safe_position(track.get("position")) and track.get("id") not in existing
	]
	unique = {str(track.get("id") or ""): track for track in positionless if track.get("id")}
	if len(missing) == 1 and len(unique) == 1:
		recovered = next(iter(unique.values()))
		recovered["position"] = missing[0]
	return captured


def metadata_gap_positions(tracks: list[dict], playlist_cover_url: str | None, reported_total: int | None = None) -> list[int]:
	rows = tracks[:reported_total] if reported_total and reported_total > 0 else tracks
	return [
		position
		for position, track in enumerate(rows, start=1)
		if not track.get("album")
		or not track.get("cover_url")
		or bool(playlist_cover_url and track.get("cover_url") == playlist_cover_url)
	]


class SpotifyPublicScrapeDialog(QDialog):
	scrape_finished = Signal(object)
	scrape_progress = Signal(int, int, str)

	def __init__(
		self,
		parent=None,
		*,
		zoom_factor: float = 0.25,
		scroll_multiplier: float = 1.4,
		minimum_scroll_px: int = 650,
		interval_ms: int = 350,
	):
		super().__init__(parent)
		self.setWindowTitle("Experimental Public Spotify Playlist Scraper")
		self.resize(1100, 780)
		self.tracks: dict[str, dict] = {}
		self.baseline_count = 0
		self.reported_total: int | None = None
		self.baseline_worker: SpotifyBaselineWorker | None = None
		self.iteration = 0
		self.stalled = 0
		self.running = False
		self.capture_pending = False
		self.next_should_scroll = True
		self.capture_requested_scroll = False
		self.session_id = "not-started"
		self.playlist_id = ""
		self.playlist_name = "Spotify Playlist"
		self.playlist_cover_url: str | None = None
		self.finish_emitted = False
		self.dispose_pending = False
		self.scroll_multiplier = max(0.25, float(scroll_multiplier))
		self.minimum_scroll_px = max(100, int(minimum_scroll_px))
		self._build_ui()
		self.browser.setZoomFactor(max(0.05, min(1.0, float(zoom_factor))))
		self.base_scroll_interval_ms = max(100, int(interval_ms))
		self.timer.setInterval(jittered_scroll_delay_ms(self.base_scroll_interval_ms))

	def _build_ui(self) -> None:
		layout = QVBoxLayout(self)
		intro = QLabel(
			"This opens a public Spotify playlist in a temporary, unsigned browser session. "
			"It scrolls the rendered page and records track rows Spotify exposes publicly. "
			"No Spotify login, cookies, Client ID, or API token is used."
		)
		intro.setWordWrap(True)
		layout.addWidget(intro)
		row = QHBoxLayout()
		self.url_input = QLineEdit()
		self.url_input.setPlaceholderText("https://open.spotify.com/playlist/...")
		self.start_button = QPushButton("Open and Scrape")
		self.start_button.clicked.connect(self.start_scrape)
		self.stop_button = QPushButton("Stop")
		self.stop_button.clicked.connect(lambda: self._finish("Stopped by user."))
		self.stop_button.setEnabled(False)
		self.speed_combo = QComboBox()
		self.speed_combo.addItems(["Fast (0.35s)", "Balanced (0.55s)", "Safe (1.2s)"])
		self.speed_combo.currentIndexChanged.connect(self._speed_changed)
		row.addWidget(self.url_input, 1)
		row.addWidget(QLabel("Scroll speed:"))
		row.addWidget(self.speed_combo)
		row.addWidget(self.start_button)
		row.addWidget(self.stop_button)
		layout.addLayout(row)
		self.status = QLabel("Paste a public playlist URL to begin.")
		self.status.setWordWrap(True)
		layout.addWidget(self.status)
		self.profile = QWebEngineProfile(self)
		self.profile.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)
		# Keep Spotify's rendered labels deterministic across OS locale settings;
		# capture filtering currently recognizes the English Recommended heading.
		self.profile.setHttpAcceptLanguage("en-US,en;q=0.9")
		self.page = ScraperWebPage(self.profile, self)
		self.browser = QWebEngineView()
		self.browser.setPage(self.page)
		self.browser.setZoomFactor(0.25)
		self.browser.loadFinished.connect(self._page_loaded)
		layout.addWidget(self.browser, 3)
		self.table = QTableWidget(0, 5)
		self.table.setHorizontalHeaderLabels(["#", "Title", "Artist", "Album", "Artwork URL"])
		self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
		for column in range(1, 5):
			self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.Stretch)
		layout.addWidget(self.table, 2)
		self.timer = QTimer(self)
		self.base_scroll_interval_ms = _SCROLL_INTERVALS_MS[0]
		self.timer.setInterval(jittered_scroll_delay_ms(self.base_scroll_interval_ms))
		self.timer.timeout.connect(self._capture_visible)

	def _speed_changed(self, index: int) -> None:
		self.base_scroll_interval_ms = _SCROLL_INTERVALS_MS[index]
		self.timer.setInterval(jittered_scroll_delay_ms(self.base_scroll_interval_ms))
		log(
			f"spotify_public_scrape session={self.session_id} speed_changed "
			f"base_interval_ms={self.base_scroll_interval_ms} next_interval_ms={self.timer.interval()}"
		)

	def start_scrape(self) -> None:
		try:
			source = parse_spotify_source(self.url_input.text(), expected_type="playlist")
		except SpotifyImportError as exc:
			self.status.setText(str(exc))
			log(f"spotify_public_scrape start_rejected reason=invalid_playlist_url error={exc}")
			return
		self.session_id = secrets.token_hex(4)
		self.playlist_id = source.id
		self.finish_emitted = False
		self.tracks.clear()
		self.table.setRowCount(0)
		self.iteration = 0
		self.stalled = 0
		self.running = True
		self.capture_pending = False
		self.next_should_scroll = True
		self.capture_requested_scroll = False
		self.start_button.setEnabled(False)
		self.stop_button.setEnabled(True)
		url = f"https://open.spotify.com/playlist/{source.id}"
		log(
			f"spotify_public_scrape session={self.session_id} event=start playlist_id={self.playlist_id} "
			f"base_interval_ms={self.base_scroll_interval_ms} first_interval_ms={self.timer.interval()} zoom={self.browser.zoomFactor():.2f} "
			f"off_the_record={self.profile.isOffTheRecord()}"
		)
		self.status.setText("Phase 1: loading the public embed baseline...")
		self.baseline_worker = SpotifyBaselineWorker(url, self)
		self.baseline_worker.finished_baseline.connect(lambda ok, playlist, error: self._baseline_finished(ok, playlist, error, url))
		self.baseline_worker.finished.connect(lambda worker=self.baseline_worker: self._baseline_worker_ended(worker))
		self.baseline_worker.start()

	def _baseline_finished(self, ok: bool, playlist: object, error: str, url: str) -> None:
		if not self.running:
			return
		if not ok:
			log(f"spotify_public_scrape session={self.session_id} event=baseline_failed playlist_id={self.playlist_id} error={error}")
			self._finish(f"Phase 1 failed: {error}")
			return
		for playlist_position, track in enumerate(getattr(playlist, "tracks", []), start=1):
			track_id = str(track.get("sp_id") or "").strip()
			if track_id:
				position = int(track.get("track_no") or playlist_position)
				self.tracks[f"{position}:{track_id}"] = {
					"id": track_id,
					"position": position,
					"title": track.get("title") or "",
					"artists": track.get("artists") or "",
					"album": track.get("album") or "",
					"cover_url": track.get("cover_url"),
				}
		self.baseline_count = len(self.tracks)
		self.playlist_name = getattr(playlist, "name", "Spotify Playlist")
		self.playlist_cover_url = getattr(playlist, "cover_url", None)
		self.reported_total = getattr(playlist, "total_count", None)
		artwork_count = sum(1 for track in self.tracks.values() if track.get("cover_url"))
		log(
			f"spotify_public_scrape session={self.session_id} event=baseline_complete playlist_id={self.playlist_id} "
			f"tracks={self.baseline_count} reported_total={self.reported_total} artwork={artwork_count} "
			f"warning={bool(getattr(playlist, 'warning', None))}"
		)
		self._render_tracks()
		self.scrape_progress.emit(self.baseline_count, self.reported_total or 0, self.playlist_name)
		if (
			self.reported_total
			and self.baseline_count >= self.reported_total
			and not getattr(playlist, "warning", None)
			and not self._metadata_gap_positions()
		):
			self._finish(f"Success: embed confirmed all {self.reported_total} reported tracks.")
			return
		self.status.setText(
			f"Phase 1 confirmed {self.baseline_count} public embed tracks"
			f" of {self.reported_total or 'an unknown total'}. Phase 2: opening the normal page at 25% zoom..."
		)
		self.browser.load(QUrl(url))

	def _page_loaded(self, ok: bool) -> None:
		if not self.running:
			return
		if not ok:
			log(f"spotify_public_scrape session={self.session_id} event=browser_load_failed playlist_id={self.playlist_id}")
			self._finish("Spotify's public page failed to load.")
			return
		log(
			f"spotify_public_scrape session={self.session_id} event=browser_load_complete playlist_id={self.playlist_id} "
			f"url_host={self.page.url().host()} zoom={self.browser.zoomFactor():.2f}"
		)
		self.status.setText(f"Phase 2: page loaded at 25% zoom. Starting with {self.baseline_count} confirmed tracks and scrolling...")
		self.timer.start()
		self._capture_visible()

	def _capture_visible(self) -> None:
		if self.running and not self.capture_pending:
			self.capture_pending = True
			self.capture_requested_scroll = self.next_should_scroll
			script = _CAPTURE_SCRIPT.replace("__SHOULD_SCROLL__", "true" if self.capture_requested_scroll else "false")
			script = script.replace("__SCROLL_MULTIPLIER__", f"{self.scroll_multiplier:.3f}")
			script = script.replace("__MIN_SCROLL_PX__", str(self.minimum_scroll_px))
			self.page.runJavaScript(script, 0, self._capture_finished)

	def _capture_finished(self, result: Any) -> None:
		self.capture_pending = False
		if isinstance(result, str):
			try:
				result = json.loads(result)
			except ValueError:
				result = None
		if not self.running or not isinstance(result, dict):
			if self.running:
				log(
					f"spotify_public_scrape session={self.session_id} event=capture_invalid_result "
					f"pass={self.iteration + 1} result_type={type(result).__name__}"
				)
				self.status.setText("The browser page did not return capture data; retrying the next scroll pass...")
			return
		before = len(self.tracks)
		browser_total = result.get("reportedTotal")
		if not self.playlist_cover_url and str(result.get("playlistCover") or "").startswith(("https://", "http://")):
			self.playlist_cover_url = str(result["playlistCover"])
		if isinstance(browser_total, (int, float)) and browser_total > 0:
			self.reported_total = max(self.reported_total or 0, int(browser_total))
		captured_tracks = [
			track for raw in (result.get("tracks") or [])
			if (track := normalized_capture(raw)) is not None
		]
		captured_tracks = recover_single_missing_position(captured_tracks, self.tracks, self.reported_total)
		for track in captured_tracks:
			if not track or not track.get("position"):
				continue
			if self.reported_total and int(track["position"]) > self.reported_total:
				continue
			storage_key = f"{int(track['position'])}:{track['id']}"
			if storage_key not in self.tracks:
				self.tracks[storage_key] = track
			else:
				# The public embed often supplies the playlist image as a generic
				# fallback. Rendered rows contain the actual per-album artwork.
				existing = self.tracks[storage_key]
				# The embed's position is authoritative. Numbers found in rendered
				# row text can be years or other metadata and must not replace it.
				for field in ("title", "artists", "album", "cover_url"):
					if track.get(field):
						existing[field] = track[field]
		added = len(self.tracks) - before
		new_ids = list(self.tracks.keys())[before:]
		if self.capture_requested_scroll:
			# The following passes hold position until Spotify renders new IDs.
			self.next_should_scroll = False
		else:
			if added:
				self.stalled = 0
				self.next_should_scroll = True
			else:
				self.stalled += 1
				# Nudge again if this position never produces a new virtualized block.
				self.next_should_scroll = self.stalled % 8 == 0
		self.iteration += 1
		next_delay_ms = jittered_scroll_delay_ms(self.base_scroll_interval_ms)
		self.timer.setInterval(next_delay_ms)
		artwork_count = sum(1 for track in self.tracks.values() if track.get("cover_url"))
		log(
			f"spotify_public_scrape session={self.session_id} event=capture_pass pass={self.iteration} "
			f"action={'scroll' if self.capture_requested_scroll else 'verify'} raw_tracks={len(result.get('tracks') or [])} "
			f"dom_links={result.get('trackLinks', 0)} scrollers={result.get('scrollers', 0)} "
			f"added={added} new_first={new_ids[0] if new_ids else '-'} new_last={new_ids[-1] if new_ids else '-'} "
			f"captured={len(self.tracks)} baseline={self.baseline_count} reported_total={self.reported_total} "
			f"artwork={artwork_count} waits={self.stalled} next_action={'scroll' if self.next_should_scroll else 'verify'} "
			f"next_delay_ms={next_delay_ms} "
			f"sign_in_wall={bool(result.get('signInWall'))} page_title={str(result.get('title') or '')[:120]!r}"
		)
		self._append_rendered_tracks(new_ids)
		self.scrape_progress.emit(len(self.tracks), self.reported_total or 0, self.playlist_name)
		beyond = max(0, len(self.tracks) - self.baseline_count)
		mode = "triple-scrolling next" if self.next_should_scroll else "waiting for the next rendered block"
		self.status.setText(
			f"Baseline {self.baseline_count}; browser discovered {beyond} additional; "
			f"total {len(self.tracks)}/{self.reported_total or '?'}. Pass {self.iteration}, "
			f"DOM track links {result.get('trackLinks', 0)}, scroll containers {result.get('scrollers', 0)}, "
			f"verification waits {self.stalled}; {mode}."
		)
		metadata_gaps = self._metadata_gap_positions()
		if self.reported_total and len(self.tracks) >= self.reported_total and not metadata_gaps:
			self._finish(f"Success: captured all {self.reported_total} reported tracks.")
		elif self.stalled >= self._stalled_safety_limit():
			wall = " Spotify displayed a sign-in wall during the scroll." if result.get("signInWall") else ""
			metadata_note = f" {len(metadata_gaps)} tracks still have incomplete album metadata." if metadata_gaps else ""
			self._finish(f"No new public rows appeared. Captured {len(self.tracks)} tracks.{metadata_note}{wall}")
		elif self.iteration >= self._iteration_safety_limit():
			self._finish(f"Reached the safety limit. Captured {len(self.tracks)} tracks.")

	def _iteration_safety_limit(self) -> int:
		"""Scale the pass ceiling for virtualized playlists instead of truncating large lists at 200 passes."""
		if not self.reported_total:
			return 300
		return max(300, math.ceil(self.reported_total / 4))

	def _stalled_safety_limit(self) -> int:
		"""Give Spotify extra render attempts when a large scan is close to its reported end."""
		if self.reported_total and 0 < self.reported_total - len(self.tracks) <= 2:
			return 20
		if self.reported_total and len(self.tracks) >= int(self.reported_total * 0.9):
			return 80
		return 40

	def _append_rendered_tracks(self, track_ids: list[str]) -> None:
		"""Append only newly discovered rows; rebuilding thousands of table cells every pass freezes Qt."""
		if not track_ids:
			return
		start = self.table.rowCount()
		self.table.setRowCount(start + len(track_ids))
		for offset, track_id in enumerate(track_ids):
			track = self.tracks[track_id]
			row = start + offset
			for column, value in enumerate((row + 1, track["title"], track["artists"], track["album"], track.get("cover_url") or "")):
				self.table.setItem(row, column, QTableWidgetItem(str(value)))

	def _render_tracks(self) -> None:
		rows = list(self.tracks.values())
		self.table.setRowCount(len(rows))
		for row, track in enumerate(rows):
			for column, value in enumerate((row + 1, track["title"], track["artists"], track["album"], track.get("cover_url") or "")):
				self.table.setItem(row, column, QTableWidgetItem(str(value)))

	def _metadata_gap_positions(self) -> list[int]:
		return metadata_gap_positions(list(self.tracks.values()), self.playlist_cover_url, self.reported_total)

	def _finish(self, message: str) -> None:
		was_running = self.running
		self.running = False
		self.timer.stop()
		self.start_button.setEnabled(True)
		self.stop_button.setEnabled(False)
		self.status.setText(message)
		if was_running:
			all_tracks = list(self.tracks.values())
			emitted_tracks = ordered_playlist_tracks(all_tracks, self.reported_total)
			if self.reported_total and len(all_tracks) > len(emitted_tracks):
				discarded = len(all_tracks) - len(emitted_tracks)
				log(
					f"spotify_public_scrape session={self.session_id} event=playlist_position_filter "
					f"discarded={discarded} reported_total={self.reported_total}"
				)
			missing = max(0, (self.reported_total or len(emitted_tracks)) - len(emitted_tracks))
			log(
				f"spotify_public_scrape session={self.session_id} event=finish playlist_id={self.playlist_id} "
				f"captured={len(self.tracks)} baseline={self.baseline_count} reported_total={self.reported_total} "
				f"missing={missing} passes={self.iteration} waits={self.stalled} reason={message!r}"
			)
			if not self.finish_emitted:
				self.finish_emitted = True
				metadata_gaps = metadata_gap_positions(emitted_tracks, self.playlist_cover_url, self.reported_total)
				self.scrape_finished.emit({
					"id": self.playlist_id,
					"name": self.playlist_name,
					"tracks": emitted_tracks,
					"reported_total": self.reported_total,
					"cover_url": self.playlist_cover_url,
					"message": message,
					"complete": bool(self.reported_total and len(emitted_tracks) == self.reported_total and not metadata_gaps),
					"metadata_gap_positions": metadata_gaps,
				})

	def _baseline_worker_ended(self, worker: SpotifyBaselineWorker) -> None:
		if self.baseline_worker is worker:
			self.baseline_worker = None
		if self.dispose_pending:
			QTimer.singleShot(0, self._complete_dispose)

	def dispose(self) -> None:
		"""Stop rendering and safely delete the dialog after any blocking request exits."""
		self.running = False
		self.timer.stop()
		self.browser.stop()
		worker = self.baseline_worker
		if worker and worker.isRunning():
			self.dispose_pending = True
			self.hide()
			return
		self._complete_dispose()

	def _complete_dispose(self) -> None:
		self.dispose_pending = False
		self.close()
		self.deleteLater()

	def closeEvent(self, event) -> None:
		if self.running:
			log(f"spotify_public_scrape session={self.session_id} event=window_closed_while_running playlist_id={self.playlist_id}")
		self.timer.stop()
		self.browser.stop()
		if self.baseline_worker and self.baseline_worker.isRunning():
			self.running = False
			self.dispose_pending = True
			self.hide()
			event.ignore()
			return
		super().closeEvent(event)
