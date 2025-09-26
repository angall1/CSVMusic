# tabs only
import pathlib
from typing import Union, List, Dict, Optional
import pandas as pd

# Canonical column names we expect (case-insensitive matching supported)
_CANON = {
	"track name": "Track name",
	"artist name": "Artist name",
	"album": "Album",
	"playlist name": "Playlist name",
	"isrc": "ISRC",
	"spotify - id": "Spotify - id",
	# Optional/ignored if missing:
	"type": "Type",
	"duration ms": "Duration (ms)",
	"duration (ms)": "Duration (ms)",
}

# Minimum set required to build track entries (we do NOT require "Type")
_REQUIRED = ["Track name", "Artist name", "Album", "Playlist name", "ISRC", "Spotify - id"]

def _read_csv_robust(path: pathlib.Path) -> pd.DataFrame:
	"""
	Try a few reasonable ways to read the CSV (handles BOM, comma/semicolon, fallback engine).
	"""
	errs = []
	for kwargs in (
		{"encoding": None, "sep": ","},
		{"encoding": "utf-8-sig", "sep": ","},
		{"encoding": None, "sep": ";"},
		{"encoding": "utf-8-sig", "sep": ";"},
		{"encoding": "utf-8", "sep": ",", "engine": "python"},
		{"encoding": "utf-8-sig", "sep": ",", "engine": "python"},
	):
		try:
			return pd.read_csv(path, **kwargs)
		except Exception as e:
			errs.append(f"{kwargs}: {e}")
	raise ValueError("Failed to read CSV with multiple strategies:\n" + "\n".join(errs))

def _normalize_headers(df: pd.DataFrame) -> pd.DataFrame:
	"""
	Return a copy of df with standardized column names per _CANON.
	Matches case-insensitively and tolerates minor spacing/punctuation differences.
	"""
	def norm(s: str) -> str:
		return "".join(ch for ch in s.strip().lower() if ch.isalnum() or ch.isspace()).replace("  ", " ")
	# Build reverse lookup from normalized header → canonical
	reverse = {}
	for k, v in _CANON.items():
		reverse[norm(k)] = v

	renames = {}
	for col in df.columns:
		key = norm(str(col))
		if key in reverse:
			renames[col] = reverse[key]
	# apply
	out = df.copy()
	if renames:
		out = out.rename(columns=renames)
	return out

def load_csv(path: Union[str, pathlib.Path]) -> pd.DataFrame:
	"""
	Load the CSV and normalize headers.
	Raises FileNotFoundError or ValueError on problems.
	"""
	p = pathlib.Path(path)
	if not p.exists():
		raise FileNotFoundError(str(p))
	df = _read_csv_robust(p)
	df = _normalize_headers(df)

	# Check required columns (we intentionally do NOT require "Type")
	missing = [c for c in _REQUIRED if c not in df.columns]
	if missing:
		raise ValueError(f"CSV missing required columns: {missing}")

	# Normalize key columns to strings (avoid NaN weirdness later)
	for c in _REQUIRED:
		df[c] = df[c].astype(str).fillna("").str.strip()

	# If present, normalize optional columns
	if "Type" in df.columns:
		df["Type"] = df["Type"].astype(str).fillna("").str.strip().str.lower()
	if "Duration (ms)" in df.columns:
		# Best-effort numeric
		df["Duration (ms)"] = pd.to_numeric(df["Duration (ms)"], errors="coerce").fillna(0).astype(int)

	return df

def list_playlists(df: pd.DataFrame) -> List[str]:
	"""
	Return sorted unique playlist names (non-empty only).
	"""
	if "Playlist name" not in df.columns:
		return []
	pls = df["Playlist name"].dropna().astype(str).map(str.strip)
	return sorted([p for p in pls.unique().tolist() if p != ""])

def _is_valid_track_row(row: pd.Series) -> bool:
	"""
	Heuristic: treat as a track if there's a non-empty Track name OR a Spotify id.
	We DO NOT rely on 'Type' (exports vary).
	"""
	title = str(row.get("Track name", "")).strip()
	spid = str(row.get("Spotify - id", "")).strip()
	return (len(title) > 0) or (len(spid) > 0)

def tracks_from_csv(df: pd.DataFrame, playlist: Optional[str] = None) -> List[Dict]:
	"""
	Convert CSV rows to internal track dicts.
	- Optional playlist filter (exact match).
	- Ignores rows that don't look like tracks.
	- Duration is 0 if not provided; downstream matchers can still score by title/artist.
	"""
	work = df
	if playlist:
		work = work[work["Playlist name"] == playlist]

	# Keep only plausible tracks
	mask = work.apply(_is_valid_track_row, axis=1)
	work = work[mask]

	out: List[Dict] = []
	for _, r in work.iterrows():
		isrc = str(r.get("ISRC", "")).strip()
		spid = str(r.get("Spotify - id", "")).strip()
		# duration if present
		if "Duration (ms)" in work.columns:
			try:
				dur_ms = int(r.get("Duration (ms)", 0)) if pd.notna(r.get("Duration (ms)")) else 0
			except Exception:
				dur_ms = 0
		else:
			dur_ms = 0

		out.append({
			"title": str(r.get("Track name", "")).strip(),
			"artists": str(r.get("Artist name", "")).strip(),
			"album": str(r.get("Album", "")).strip(),
			"playlist": str(r.get("Playlist name", "")).strip(),
			"isrc": isrc if isrc and isrc.lower() != "nan" else None,
			"sp_id": spid if spid and spid.lower() != "nan" else None,
			"duration_ms": dur_ms,
			"year": None,          # CSV doesn't include year
			"cover_url": None,     # CSV doesn't include cover
			"track_no": 0,
			"disc_no": 1,
		})
	return out
