# tabs only
import sys
from spotify2media.core.csv_import import load_csv, tracks_from_csv
from spotify2media.core.ytmusic_match import batch_match

def main(argv):
	if len(argv) < 2:
		print("Usage: python -m spotify2media.match_csv <csv_path> [--playlist \"Playlist Name\"]")
		return 2
	csv = argv[1]
	pl = None
	if len(argv) >= 4 and argv[2] == "--playlist":
		pl = argv[3]
	df = load_csv(csv)
	tracks = tracks_from_csv(df, pl)
	print(f"Tracks to match: {len(tracks)}")
	results = batch_match(tracks)
	done = sum(1 for r in results if not r["skipped"])
	skipped = len(results) - done
	print(f"Matched: {done}  |  Skipped: {skipped}")
	for r in results[:10]:
		t = r["track"]
		if r["skipped"]:
			print(f"[SKIP] {t['artists']} — {t['title']}")
		else:
			m = r["match"]; conf = r["confidence"]
			d = m.get("duration_seconds") or 0
			print(f"[OK {conf:.2f}] {t['artists']} — {t['title']}  ->  {m['title']} ({d}s)  id={m['videoId']}")
	return 0

if __name__ == "__main__":
	sys.exit(main(sys.argv))
