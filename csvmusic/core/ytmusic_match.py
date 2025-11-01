# tabs only
from typing import Dict, List, Optional, Tuple, Set
import re, time, subprocess, json, pathlib

CONFIDENCE_MIN = 0.6
SEARCH_LIMIT = 12
RATE_LIMIT_S = 0.35

_PENALTY_TERMS = {"live","remix","cover","sped","slowed","nightcore","8d","reverb","extended","mashup","edit","karaoke","instrumental","demo"}

def _toks(s: str) -> set:
	return set(re.findall(r"[a-z0-9]+", (s or "").lower()))

def _duration_s(d: Optional[int]) -> int:
	try:
		return int(d) if d is not None else 0
	except Exception:
		return 0

def _score(track: Dict, cand: Dict, debug: bool = False) -> float:
	# title/artist overlap
	track_title = track.get("title","")
	track_artists = track.get("artists","")
	track_tokens = _toks(track_title) | _toks(track_artists)
	cand_title = cand.get("title") or ""
	cand_art = ""
	if cand.get("artists"):
		try:
			cand_art = ", ".join(a.get("name","") for a in cand["artists"])
		except Exception:
			pass
	if not cand_art:
		cand_art = cand.get("author","") or ""
	cand_tokens = _toks(cand_title) | _toks(cand_art)
	overlap = len(track_tokens & cand_tokens) / max(1, len(track_tokens))

	# duration (CSV may not have; cand might)
	sp_s = int(round((track.get("duration_ms") or 0) / 1000))
	yt_s = _duration_s(cand.get("duration_seconds"))
	if sp_s > 0 and yt_s > 0:
		delta = abs(sp_s - yt_s)
		if delta <= 6:
			d_score = 1.0
		elif delta <= 12:
			d_score = 0.9
		elif delta <= 20:
			d_score = 0.78
		elif delta <= 30:
			d_score = 0.62
		else:
			d_score = 0.45
	else:
		d_score = 0.7  # neutral baseline when no duration available

	# channel boost
	channel = (cand.get("author") or "").lower()
	ch_boost = 0.15 if ("topic" in channel or "official" in channel) else 0.0

	# penalties - BUT only penalize if NOT in the user's original track title
	# This fixes the nightcore/sped/slowed/reverb version problem
	track_titleblob = (track_title + " " + track_artists).lower()
	cand_titleblob = (cand_title + " " + cand_art).lower()

	p_pen = 0.0
	exact_match_boost = 0.0
	matched_variants = []
	for t in _PENALTY_TERMS:
		# Case 1: Candidate has variant term but track doesn't → wrong variant, penalize
		if t in cand_titleblob and t not in track_titleblob:
			p_pen += 0.25  # Strong penalty for wrong variants
		# Case 2: Track has variant term but candidate doesn't → missing required variant, DEVASTATING penalty
		elif t in track_titleblob and t not in cand_titleblob:
			p_pen += 0.50  # DEVASTATING penalty - essentially disqualifies non-variant matches
		# Case 3: Both have the term → exact match, massive boost
		elif t in cand_titleblob and t in track_titleblob:
			exact_match_boost += 0.45  # HUGE boost for exact variant matches
			matched_variants.append(t)

	if "remaster" in cand_titleblob and "remaster" not in track_titleblob:
		p_pen *= 0.6

	total = max(0.0, d_score * 0.5 + overlap * 0.45 + ch_boost + exact_match_boost - p_pen)
	final = min(total, 0.99)

	if debug:
		print(f"  '{cand_title[:50]}' by '{cand_art[:30]}'")
		print(f"    overlap={overlap:.2f} dur={d_score:.2f} ch_boost={ch_boost:.2f} variant_boost={exact_match_boost:.2f} pen={p_pen:.2f}")
		if matched_variants:
			print(f"    MATCHED VARIANTS: {matched_variants}")
		print(f"    FINAL SCORE: {final:.4f}")

	return final

def _clean_title_artist(title: str, artists: str) -> str:
	# Basic collapse of whitespace and stray separators for searching
	q = f"{title} {artists}".strip()
	q = re.sub(r"\s+", " ", q)
	q = q.replace(" - ", " ")
	q = q.replace("–", " ").replace("—", " ")
	return q.strip()

def _strip_noise(title: str) -> str:
	# Remove common bracketed qualifiers that hurt search recall
	# e.g., (feat. ...), [Official Video], etc.
	# BUT preserve important variant identifiers like nightcore, sped, slowed
	s = title

	# First, extract and preserve any variant terms from brackets
	preserved_terms = set()  # Use set to avoid duplicates
	for term in _PENALTY_TERMS:
		# Look for the term in any bracketed content
		pattern = r"[\(\[]([^\)\]]*" + re.escape(term) + r"[^\)\]]*)[\)\]]"
		matches = re.findall(pattern, s, re.IGNORECASE)
		for match in matches:
			preserved_terms.add(match.strip())

	# Remove ALL bracketed content (feat., official, etc.)
	s = re.sub(r"[\(\[][^\)\]]*[Ff]eat[^\)\]]*[\)\]]", " ", s)
	s = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", s)

	# Add back the preserved variant terms
	if preserved_terms:
		s = s + " " + " ".join(sorted(preserved_terms))

	return re.sub(r"\s+", " ", s).strip()

def _query_variants(track: Dict) -> List[str]:
	"""
	Generate a small set of search queries to improve recall across
	"&" vs "and", hyphens, and bracketed noise.
	Order variants from most specific to broader fallbacks.
	"""
	title = track.get("title", "") or ""
	artists = track.get("artists", "") or ""
	isrc = track.get("isrc")

	base_title = title
	clean_title = _strip_noise(base_title)
	base = _clean_title_artist(base_title, artists)
	clean = _clean_title_artist(clean_title, artists)

	variants: List[str] = []
	if isrc:
		variants.append(f"{isrc} {clean}")

	variants.append(base)
	if clean != base:
		variants.append(clean)

	# Swap common conjunction styles
	if "&" in base:
		variants.append(base.replace("&", "and"))
	if re.search(r"\band\b", base, flags=re.I):
		variants.append(re.sub(r"\band\b", "&", base, flags=re.I))

	# Hyphen to space (already mostly handled in _clean_title_artist)
	if "-" in base:
		variants.append(base.replace("-", " "))

	# Deduplicate while preserving order
	seen: Set[str] = set()
	out: List[str] = []
	for q in variants:
		qq = re.sub(r"\s+", " ", q).strip()
		if qq and qq not in seen:
			seen.add(qq)
			out.append(qq)
	return out

def _get_ytdlp_path(override: Optional[str] = None) -> str:
	"""Get yt-dlp executable path"""
	if override and pathlib.Path(override).exists():
		return override
	# Try common locations
	import shutil
	ytdlp = shutil.which("yt-dlp")
	if ytdlp:
		return ytdlp
	raise FileNotFoundError("yt-dlp not found in PATH")

def _has_variant_term(query: str) -> bool:
	"""Check if query contains any variant/alternative version terms"""
	q_lower = query.lower()
	return any(term in q_lower for term in _PENALTY_TERMS)

def _search_ytdlp(q: str, limit: int = SEARCH_LIMIT, ytdlp_path: Optional[str] = None) -> List[Dict]:
	"""
	Search YouTube using yt-dlp for a query.
	Returns list of video metadata dictionaries.
	"""
	try:
		ytdlp = _get_ytdlp_path(ytdlp_path)
	except FileNotFoundError:
		return []

	# Use yt-dlp to search YouTube
	# ytsearch{limit}:{query} searches YouTube and returns top N results
	search_query = f"ytsearch{limit}:{q}"

	cmd = [
		ytdlp,
		"--dump-json",
		"--no-playlist",
		"--flat-playlist",
		"--skip-download",
		search_query
	]

	try:
		result = subprocess.run(
			cmd,
			capture_output=True,
			text=True,
			timeout=30,
			check=False
		)

		if result.returncode != 0:
			return []

		# Parse JSON output (one JSON object per line)
		cands = []
		for line in result.stdout.strip().split('\n'):
			if not line.strip():
				continue
			try:
				data = json.loads(line)
				vid = data.get("id") or data.get("url", "").split("=")[-1]
				if not vid:
					continue

				# Extract duration
				duration_s = data.get("duration") or 0

				# Extract uploader/channel
				author = data.get("uploader") or data.get("channel") or ""

				cands.append({
					"videoId": vid,
					"title": data.get("title") or "",
					"artists": None,  # yt-dlp doesn't provide artist breakdown
					"author": author,
					"duration_seconds": int(duration_s) if duration_s else 0
				})

				if len(cands) >= limit:
					break
			except (json.JSONDecodeError, ValueError):
				continue

		return cands
	except (subprocess.TimeoutExpired, Exception):
		return []

def _search(q: str, limit: int = SEARCH_LIMIT, ytdlp_path: Optional[str] = None) -> List[Dict]:
	"""
	Search YouTube for a query.
	For variant versions (nightcore, sped, slowed, etc.), search with higher limit
	since these are often user uploads.
	"""
	has_variant = _has_variant_term(q)

	# For variant versions, search with higher limit to get more results
	search_limit = limit * 2 if has_variant else limit

	return _search_ytdlp(q, search_limit, ytdlp_path)
def _rank_candidates(track: Dict, limit: int = SEARCH_LIMIT, ytdlp_path: Optional[str] = None) -> List[Dict]:
	seen_vids: Set[str] = set()
	all_cands: List[Dict] = []
	for q in _query_variants(track):
		cands = _search(q, limit, ytdlp_path)
		for cand in cands:
			vid = cand.get("videoId")
			if not vid or vid in seen_vids:
				continue
			seen_vids.add(vid)
			all_cands.append(cand)

	scored: List[Dict] = []
	for cand in all_cands:
		s = _score(track, cand)
		item = dict(cand)
		item["score"] = s
		scored.append(item)

	return sorted(scored, key=lambda c: c["score"], reverse=True)

def find_best(track: Dict, ytdlp_path: Optional[str] = None) -> Tuple[Optional[Dict], float, List[Dict]]:
	options = _rank_candidates(track, ytdlp_path=ytdlp_path)
	if not options:
		return None, 0.0, []
	best = options[0]
	return (best if best["score"] >= CONFIDENCE_MIN else None, best["score"], options)

def more_candidates(track: Dict, exclude_ids: Set[str] | None = None, limit: int = SEARCH_LIMIT * 2, ytdlp_path: Optional[str] = None) -> List[Dict]:
	exclude = set(exclude_ids or [])
	options = _rank_candidates(track, limit, ytdlp_path)
	return [opt for opt in options if opt.get("videoId") not in exclude]

def batch_match(tracks: List[Dict], ytdlp_path: Optional[str] = None) -> List[Dict]:
	"""
	Input: list of track dicts (from csv_import.tracks_from_csv)
	Output: list of results with either 'match' or 'skipped': True
	"""
	results = []
	for t in tracks:
		res = {"track": t, "skipped": False, "match": None, "confidence": 0.0, "options": []}
		try:
			match, conf, options = find_best(t, ytdlp_path)
			res["confidence"] = conf
			res["options"] = options
			if match is None:
				res["skipped"] = True
			else:
				res["match"] = match
		except Exception as e:
			res["skipped"] = True
			res["error"] = str(e)
		results.append(res)
		time.sleep(RATE_LIMIT_S)
	return results
