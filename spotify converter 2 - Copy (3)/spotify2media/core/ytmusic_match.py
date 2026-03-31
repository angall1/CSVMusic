# tabs only
from typing import Dict, List, Optional, Tuple, Set
import re, time
from ytmusicapi import YTMusic

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

def _score(track: Dict, cand: Dict) -> float:
	# title/artist overlap
	track_tokens = _toks(track.get("title","")) | _toks(track.get("artists",""))
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

	# penalties
	titleblob = (cand_title + " " + cand_art).lower()
	p_pen = 0.0
	for t in _PENALTY_TERMS:
		if t in titleblob:
			p_pen += 0.07
	if "remaster" in titleblob:
		p_pen *= 0.6

	total = max(0.0, d_score * 0.5 + overlap * 0.45 + ch_boost - p_pen)
	return min(total, 0.99)

def _build_query(track: Dict) -> str:
	title = track.get("title","")
	artists = track.get("artists","")
	if track.get("isrc"):
		# try ISRC first (works surprisingly often on Topic uploads)
		return f'{track["isrc"]} {title} {artists}'
	return f"{title} {artists}"

def _search(yt: YTMusic, q: str, limit: int = SEARCH_LIMIT) -> List[Dict]:
	# Primary: songs; Fallback: videos (still on music domain results)
	res = yt.search(q, filter="songs", limit=limit) or []
	cands: List[Dict] = []
	for r in res:
		vid = r.get("videoId")
		if not vid: continue
		cands.append({
			"videoId": vid,
			"title": r.get("title"),
			"artists": r.get("artists"),
			"author": (r.get("artists")[0]["name"] if r.get("artists") else r.get("author") or ""),
			"duration_seconds": r.get("duration_seconds") or 0
		})
	if not cands:
		res = yt.search(q, filter="videos", limit=limit) or []
		for r in res:
			vid = r.get("videoId")
			if not vid: continue
			cands.append({
				"videoId": vid,
				"title": r.get("title"),
				"artists": None,
				"author": r.get("author") or "",
				"duration_seconds": r.get("duration_seconds") or 0
			})
	return cands
def _rank_candidates(yt: YTMusic, track: Dict, limit: int = SEARCH_LIMIT) -> List[Dict]:
	q = _build_query(track)
	cands = _search(yt, q, limit)
	seen: Set[str] = set()
	scored: List[Dict] = []
	for cand in cands:
		vid = cand.get("videoId")
		if not vid or vid in seen:
			continue
		seen.add(vid)
		score = _score(track, cand)
		cand = dict(cand)
		cand["score"] = score
		scored.append(cand)
	return sorted(scored, key=lambda c: c["score"], reverse=True)

def find_best(yt: YTMusic, track: Dict) -> Tuple[Optional[Dict], float, List[Dict]]:
	options = _rank_candidates(yt, track)
	if not options:
		return None, 0.0, []
	best = options[0]
	return (best if best["score"] >= CONFIDENCE_MIN else None, best["score"], options)

def more_candidates(track: Dict, exclude_ids: Set[str] | None = None, limit: int = SEARCH_LIMIT * 2) -> List[Dict]:
	exclude = set(exclude_ids or [])
	yt = YTMusic()
	options = _rank_candidates(yt, track, limit)
	return [opt for opt in options if opt.get("videoId") not in exclude]

def batch_match(tracks: List[Dict]) -> List[Dict]:
	"""
	Input: list of track dicts (from csv_import.tracks_from_csv)
	Output: list of results with either 'match' or 'skipped': True
	"""
	yt = YTMusic()  # anonymous client; should work for public search endpoints
	results = []
	for t in tracks:
		res = {"track": t, "skipped": False, "match": None, "confidence": 0.0, "options": []}
		try:
			match, conf, options = find_best(yt, t)
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
