# tabs only
import sys, pathlib, time, argparse, traceback
from typing import Optional
from csvmusic.core.csv_import import load_csv, tracks_from_csv, write_skipped_csv
from csvmusic.core.ytmusic_match import batch_match
from csvmusic.core.downloader import (
	download_m4a, download_mp3, tag_file, track_cover_bytes, write_m3u, sanitize_name
)
from csvmusic.core.log import log

SKIPPED_CSV_NAME = "skipped.csv"

def main(argv: list[str]) -> int:
	parser = argparse.ArgumentParser(
		prog="csvmusic.download_csv",
		description="CSV -> YT Music match -> download/tag -> M3U"
	)
	parser.add_argument("--csv", required=True, help="Path to 'My Spotify Library.csv'")
	parser.add_argument("--out", required=True, help="Output folder")
	parser.add_argument("--playlist", help="Filter to this playlist name (exact match)")
	parser.add_argument("--format", choices=["m4a","mp3"], default="m4a", help="Output format")
	parser.add_argument("--cbr320", action="store_true", help="MP3 320 kbps CBR (default is V0)")
	parser.add_argument("--no-m3u", action="store_true", help="Do not write an .m3u8 file")
	parser.add_argument("--no-skipped-csv", action="store_true", help=f"Do not write {SKIPPED_CSV_NAME} for unmatched or failed tracks")
	parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
	args = parser.parse_args(argv[1:])

	csv_path = args.csv
	out_root = pathlib.Path(args.out)
	fmt = args.format
	write_m3u_flag = not args.no_m3u

	if args.verbose:
		print(f"[cfg] csv={csv_path}")
		print(f"[cfg] out={out_root}")
		print(f"[cfg] playlist={args.playlist!r}")
		print(f"[cfg] format={fmt} cbr320={args.cbr320} m3u={write_m3u_flag}")

	# Load + select
	df = load_csv(csv_path)
	tracks = tracks_from_csv(df, args.playlist)
	if args.verbose:
		print(f"[csv] detected playlists: {len(set(df['Playlist name'])) if 'Playlist name' in df.columns else 0}")
	if not tracks:
		print("No tracks selected.")
		return 1
	print(f"Tracks selected: {len(tracks)}")

	# Match (YT Music only)
	if args.verbose:
		print("[match] starting YT Music matching…")
	results = batch_match(tracks)
	ok = [r for r in results if not r.get("skipped")]
	sk = [r for r in results if r.get("skipped")]
	print(f"Matched: {len(ok)} | Skipped: {len(sk)}")
	if args.verbose:
		for r in results[:10]:
			t = r["track"]
			if r.get("skipped"):
				print(f"  [SKIP] {t['artists']} — {t['title']}")
			else:
				m = r["match"]; conf = r["confidence"]
				print(f"  [OK {conf:.2f}] {t['artists']} — {t['title']} -> {m['title']} (id={m['videoId']})")

	# Prepare output folders
	playlist_name = args.playlist or (tracks[0]["playlist"] if tracks else "Playlist")
	if not playlist_name:
		playlist_name = "Playlist"
	safe_playlist = sanitize_name(playlist_name) or "Playlist"
	dest_dir = out_root / safe_playlist
	dest_dir.mkdir(parents=True, exist_ok=True)

	done_tracks = []
	not_downloaded = []
	for r in results:
		t = r["track"]
		title = t["title"]; artists = t["artists"]
		base = f"{artists} - {title}"
		if r.get("skipped"):
			print(f"[SKIP] {artists} — {title}")
			not_downloaded.append({"track": t, "reason": f"match error: {r['error']}" if r.get("error") else "no confident match"})
			continue
		vid = r["match"]["videoId"]
		try:
			if args.verbose:
				print(f"[dl] {artists} — {title} (id={vid}) → {fmt}")
			if fmt == "m4a":
				fp = download_m4a(vid, dest_dir, base)
			else:
				fp = download_mp3(vid, dest_dir, base, cbr_320=args.cbr320)
			cover = track_cover_bytes(t, vid)  # CSV "Cover URL" first, then YouTube thumbnail
			tag_file(fp, t, cover)
			print(f"[OK] {artists} — {title}  ->  {fp.name}")
			done_tracks.append(t)
		except Exception as e:
			if args.verbose:
				traceback.print_exc()
			print(f"[FAIL] {artists} — {title}: {str(e)[:140]}")
			log(f"cli download failure: video_id={vid} error={e}")
			not_downloaded.append({"track": t, "reason": f"download failed: {str(e)[:140]}"})
		time.sleep(0.05)

	# M3U
	if write_m3u_flag and done_tracks:
		ext = "m4a" if fmt == "m4a" else "mp3"
		m3u = write_m3u(out_root, playlist_name, done_tracks, ext)
		print(f"Wrote {m3u}")

	# Unmatched/failed tracks, in a CSV that can be passed back to --csv to retry
	skipped_path = dest_dir / SKIPPED_CSV_NAME
	if not args.no_skipped_csv and not_downloaded:
		write_skipped_csv(skipped_path, not_downloaded)
		print(f"Not downloaded: {len(not_downloaded)} (listed in {skipped_path})")
	elif skipped_path.exists() and not args.no_skipped_csv:
		# A retry run that got everything: drop the stale list
		skipped_path.unlink()
	log(f"cli run done: selected={len(tracks)} downloaded={len(done_tracks)} not_downloaded={len(not_downloaded)}")
	return 0

if __name__ == "__main__":
	sys.exit(main(sys.argv))
