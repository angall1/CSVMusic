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
	"youtube - id": "YouTube - id",
	# Optional/ignored if missing:
	"type": "Type",
	"duration ms": "Duration (ms)",
	"duration (ms)": "Duration (ms)",
}

# Minimum set required to build track entries
# Only Track name and Artist name are truly required for searching
_REQUIRED = ["Track name", "Artist name"]
_OPTIONAL = ["Album", "Playlist name", "ISRC", "Spotify - id", "YouTube - id"]

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

	# Check required columns
	missing = [c for c in _REQUIRED if c not in df.columns]
	if missing:
		raise ValueError(f"CSV missing required columns: {missing}")

	# Normalize required columns to strings (avoid NaN weirdness later)
	for c in _REQUIRED:
		df[c] = df[c].astype(str).fillna("").str.strip()

	# Add missing optional columns with defaults
	for c in _OPTIONAL:
		if c not in df.columns:
			df[c] = ""
		else:
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
	Heuristic: treat as a track if there's a non-empty Track name OR Artist name.
	We DO NOT rely on 'Type' (exports vary across sources).
	"""
	title = str(row.get("Track name", "")).strip()
	artist = str(row.get("Artist name", "")).strip()
	return (len(title) > 0) or (len(artist) > 0)

def _strip_youtube_metadata(combined: str) -> str:
	"""
	Remove common YouTube video metadata that isn't part of artist/title.
	Examples: (Lyrics), [Official Video], (Audio), etc.
	"""
	import re

	# Remove common metadata patterns (order matters - do specific patterns first)
	patterns = [
		# Parenthetical/bracketed metadata
		r'\s*\(+\s*[Oo]fficial\s+[Ll]yrics?\s*\)+',
		r'\s*\[+\s*[Oo]fficial\s+[Ll]yrics?\s*\]+',
		r'\s*\(+\s*[Oo]fficial\s+[Vv]ideo\s*\)+',
		r'\s*\[+\s*[Oo]fficial\s+[Vv]ideo\s*\]+',
		r'\s*\(+\s*[Oo]fficial\s+[Aa]udio\s*\)+',
		r'\s*\[+\s*[Oo]fficial\s+[Aa]udio\s*\]+',
		r'\s*\(+\s*[Ll]yrics?\s*\)+',
		r'\s*\[+\s*[Ll]yrics?\s*\]+',
		r'\s*\(+\s*[Aa]udio\s*\)+',
		r'\s*\[+\s*[Aa]udio\s*\]+',
		r'\s*\(+\s*[Ll]yric\s+[Vv]ideo\s*\)+',
		# End-of-string patterns
		r'\s*[Oo]fficial\s+[Ll]yrics?\s*$',
		r'\s*[Oo]fficial\s+[Vv]ideo\s*$',
		r'\s*[Oo]fficial\s*$',
		r'\s*[Ll]yrics?\s+[Vv]ideo\s*$',
		r'\s*//\s*[Ll]yrics?\s*$',
		r'\s*\|\|?\s*[Ll]yrics?\s*$',
		r'\s*[Ll]yrics?\s*$',
	]

	cleaned = combined
	for pattern in patterns:
		cleaned = re.sub(pattern, ' ', cleaned)

	# Clean up extra whitespace
	cleaned = re.sub(r'\s+', ' ', cleaned).strip()
	return cleaned

def _is_fake_artist(artist: str) -> bool:
	"""
	Detect if the parsed "artist" is actually a YouTube channel/genre name,
	not a real artist. Common examples: Lyrics channels, etc.
	NOTE: We deliberately DO NOT include variant terms (nightcore, sped, slowed)
	because these should be preserved as part of the title.
	"""
	if not artist:
		return False

	artist_lower = artist.lower().strip()

	# Known fake artist patterns (YouTube channels, NOT variant terms)
	fake_patterns = [
		'lyrics',
		'lyric video',
		'official video',
		'audio',
		'official audio',
		'music video',
	]

	# Check if artist is exactly one of these fake patterns
	if artist_lower in fake_patterns:
		return True

	return False

def _is_variant_term(text: str) -> bool:
	"""Check if text is a variant/alternative version identifier that should be kept in the title"""
	text_lower = text.lower().strip()
	variant_terms = ['nightcore', 'nightstep', 'sped', 'slowed', 'reverb', '8d', 'remix', 'cover']
	return any(term in text_lower for term in variant_terms)

def _parse_combined_title(combined: str) -> tuple[str, str]:
	"""
	YouTube exports often combine artist and title in one field.
	Try to split them intelligently, handling YouTube-specific patterns:
	- Lyrics videos: "Artist - Song (Lyrics)"
	- Nightcore/Variants: "Nightcore - Song" (keep "Nightcore - Song" as full title)
	- Multiple artists: "Artist1 · Artist2 - Song"

	Returns: (title, artist)
	"""
	combined = combined.strip()
	if not combined:
		return "", ""

	# First, strip YouTube metadata (Lyrics, Official Video, etc.)
	cleaned = _strip_youtube_metadata(combined)

	# Look for a dash separator (most common)
	if " - " in cleaned:
		parts = cleaned.split(" - ", 1)
		left, right = parts[0].strip(), parts[1].strip()

		# Handle empty parts
		if not left or not right:
			return cleaned, ""

		# IMPORTANT: If left side is a variant term (nightcore, sped, etc.),
		# keep the FULL "Variant - Song" as the title
		if _is_variant_term(left):
			return cleaned, ""  # Keep full title including variant prefix

		# Check if left has multiple artists separated by ·
		if "·" in left and not _is_fake_artist(left.split("·")[0].strip()):
			# "Artist1 · Artist2 - Title" pattern
			return right, left.replace("·", ",")

		# Check if left side is a fake artist (like "Lyrics")
		if _is_fake_artist(left):
			# Strip the fake artist prefix, use remainder as title
			return right, ""

		# Heuristic for "Title - Artist" format:
		# Right side is VERY short (3-6 chars), has no spaces, and left is MUCH longer (3x+)
		# This catches cases like "Pretty Rave Girl 2010 - S3RL" but not "Basshunter - DotA"
		if (3 <= len(right) <= 6 and
		    " " not in right and
		    len(left) >= len(right) * 3 and
		    not _is_fake_artist(right)):
			return left, right

		# Check if right side is a fake artist (uncommon but possible)
		if _is_fake_artist(right):
			return left, ""

		# Default: assume "Artist - Title" format (most common in music)
		return right, left

	# No dash found - use the whole thing as title, let YouTube Music match
	return cleaned, ""

def tracks_from_csv(df: pd.DataFrame, playlist: Optional[str] = None) -> List[Dict]:
	"""
	Convert CSV rows to internal track dicts.
	- Optional playlist filter (exact match).
	- Ignores rows that don't look like tracks.
	- Duration is 0 if not provided; downstream matchers can still score by title/artist.
	- Intelligently parses YouTube exports where artist/title are combined.
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
		ytid = str(r.get("YouTube - id", "")).strip()
		album = str(r.get("Album", "")).strip()
		playlist = str(r.get("Playlist name", "")).strip()

		track_name = str(r.get("Track name", "")).strip()
		artist_name = str(r.get("Artist name", "")).strip()

		# If artist is missing or "nan" but track name exists, try to parse them
		if (not artist_name or artist_name.lower() == "nan") and track_name:
			parsed_title, parsed_artist = _parse_combined_title(track_name)
			track_name = parsed_title
			artist_name = parsed_artist

		# duration if present
		if "Duration (ms)" in work.columns:
			try:
				dur_ms = int(r.get("Duration (ms)", 0)) if pd.notna(r.get("Duration (ms)")) else 0
			except Exception:
				dur_ms = 0
		else:
			dur_ms = 0

		out.append({
			"title": track_name,
			"artists": artist_name,
			"album": album if album and album.lower() != "nan" else "",
			"playlist": playlist if playlist and playlist.lower() != "nan" else "Unknown Playlist",
			"isrc": isrc if isrc and isrc.lower() != "nan" else None,
			"sp_id": spid if spid and spid.lower() != "nan" else None,
			"yt_id": ytid if ytid and ytid.lower() != "nan" else None,
			"duration_ms": dur_ms,
			"year": None,          # CSV doesn't include year
			"cover_url": None,     # CSV doesn't include cover
			"track_no": 0,
			"disc_no": 1,
		})
	return out
