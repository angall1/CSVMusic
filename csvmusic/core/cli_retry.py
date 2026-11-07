# tabs only
"""Owned, atomic retry lists and playlist-order recovery for the headless CLI."""
import hashlib
import json
import os
import pathlib
import tempfile
import uuid
from dataclasses import dataclass

from csvmusic.core.csv_import import write_skipped_csv


def file_digest(path: pathlib.Path) -> str | None:
	return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _atomic_json(path: pathlib.Path, value: dict) -> None:
	fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".csvmusic-", suffix=".tmp")
	try:
		with os.fdopen(fd, "w", encoding="utf-8") as handle:
			json.dump(value, handle, ensure_ascii=False, indent=2)
		os.replace(temporary, path)
	finally:
		pathlib.Path(temporary).unlink(missing_ok=True)


@dataclass
class RetryBatch:
	path: pathlib.Path
	tracks: list[dict]
	indices: list[int]
	completed: set[int]
	fmt: str
	playlist: str
	input_digest: str | None = None
	m3u_digest: str | None = None
	is_retry: bool = False

	@property
	def state_path(self) -> pathlib.Path:
		return self.path.with_suffix(".state.json")

	def playlist_tracks(self) -> list[dict]:
		return [track for index, track in enumerate(self.tracks) if index in self.completed]

	def save(self, failed: list[dict], m3u: pathlib.Path) -> None:
		if self.is_retry and file_digest(self.path) != self.input_digest:
			raise ValueError("The retry CSV changed during this run; it was not overwritten. Keep the CSV and retry again.")
		if not failed:
			# Only remove a verified retry file that was the input to this run.
			if self.is_retry:
				self.path.unlink()
				self.state_path.unlink()
			return
		# A new immutable generation prevents interrupted writes or concurrent
		# retries from destroying the previous recoverable pair of files.
		new_path = self.path.parent / f"skipped-{uuid.uuid4().hex}.csv"
		write_skipped_csv(new_path, failed)
		state = {
			"version": 1, "format": self.fmt, "playlist": self.playlist,
			"tracks": self.tracks, "completed": sorted(self.completed),
			"pending": [index for index in range(len(self.tracks)) if index not in self.completed],
			"csv_sha256": file_digest(new_path), "m3u_sha256": file_digest(m3u),
		}
		_atomic_json(new_path.with_suffix(".state.json"), state)
		if self.is_retry:
			self.path.unlink()
			self.state_path.unlink()
		self.path = new_path


def prepare_retry_batch(csv_path: pathlib.Path, dest_dir: pathlib.Path, tracks: list[dict], fmt: str, playlist: str, m3u: pathlib.Path, *, write_m3u: bool) -> RetryBatch:
	"""Load only a matching retry sidecar; ordinary exports never own other CSVs."""
	state_path = csv_path.with_suffix(".state.json")
	if not state_path.exists():
		if csv_path.name.startswith("skipped-"):
			raise ValueError("Retry state is missing. Keep the .csv and .state.json together, or rerun the original CSV.")
		return RetryBatch(dest_dir / f"skipped-{uuid.uuid4().hex}.csv", tracks, list(range(len(tracks))), set(), fmt, playlist)
	try:
		state = json.loads(state_path.read_text(encoding="utf-8"))
		assert state["version"] == 1 and state["format"] == fmt and state["playlist"] == playlist
		assert csv_path.resolve().parent == dest_dir.resolve()
		assert file_digest(csv_path) == state["csv_sha256"]
		original = state["tracks"]
		completed, pending = state["completed"], state["pending"]
		assert isinstance(original, list) and all(isinstance(t, dict) for t in original)
		assert all(type(i) is int for i in completed + pending)
		assert sorted(completed + pending) == list(range(len(original)))
		assert pending == sorted(pending) and len(pending) == len(tracks)
		if write_m3u:
			assert file_digest(m3u) == state["m3u_sha256"]
	except (OSError, ValueError, KeyError, TypeError, AssertionError) as exc:
		raise ValueError("Retry state does not match this CSV, output folder, format, or playlist file. Rerun the original CSV instead; no files were changed.") from exc
	return RetryBatch(csv_path, original, pending, set(completed), fmt, playlist, state["csv_sha256"], state["m3u_sha256"], True)
