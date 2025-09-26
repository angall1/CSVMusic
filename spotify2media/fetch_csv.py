# tabs only
import sys
from spotify2media.core.csv_import import load_csv, tracks_from_csv, list_playlists

def main(argv: list[str]) -> int:
	if len(argv) < 2:
		print("Usage: python -m spotify2media.fetch_csv <csv_path> [--playlist \"Playlist Name\"]")
		return 2
	csv = argv[1]
	pl = None
	if len(argv) >= 4 and argv[2] == "--playlist":
		pl = argv[3]
	df = load_csv(csv)
	if pl:
		print(f"Filtering to playlist: {pl}")
	tracks = tracks_from_csv(df, pl)
	print(f"Playlists found: {len(list_playlists(df))}")
	print(f"Tracks selected: {len(tracks)}")
	for t in tracks[:5]:
		print(f"- {t['artists']} — {t['title']}  [{t['playlist']}]")
	return 0

if __name__ == "__main__":
	sys.exit(main(sys.argv))
