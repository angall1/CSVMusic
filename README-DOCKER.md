# CSVMusic in Docker (headless)

Run CSVMusic's CSV downloader on a home server or NAS, with no desktop and no Qt. The image wraps the existing CLI (`python -m csvmusic.download_csv`): CSV → YouTube Music match → download → tag (title, artist, album, year, cover art) → `.m3u8` playlist.

The image targets `linux/amd64` and `linux/arm64`. CI builds and smoke-tests both architectures; Raspberry Pi hardware itself is not tested. It contains Python, FFmpeg and Deno, which yt-dlp needs for YouTube.

## Set up

```bash
git clone https://github.com/angall1/CSVMusic.git
cd CSVMusic
mkdir -p in out config
docker compose build
```

Put your CSV exports in `in/`. Music is written to `out/<playlist name>/`.

## Download a playlist

```bash
docker compose run --rm csvmusic --csv "/in/My Playlist.csv" --out /out --format mp3
```

Useful options (`docker compose run --rm csvmusic --help` lists them all):

| Option | Meaning |
| --- | --- |
| `--format mp3` / `--format m4a` | Output format (default `m4a`) |
| `--cbr320` | MP3 at 320 kbps CBR instead of V0 |
| `--playlist "Name"` | Require that exact playlist name; export one playlist per CSV |
| `--no-m3u` | Don't write the `.m3u8` playlist |
| `--no-skipped-csv` | Don't write a retry CSV/state pair |
| `-v` | Verbose output |

Cover art comes from the CSV's `Cover URL` column when it has one, otherwise from the YouTube thumbnail. Only public HTTP(S) addresses on standard ports are fetched; private/loopback/link-local destinations and redirects to them are rejected. Connections are pinned to a validated public address, including HTTPS hostname verification.

## Tracks that were not downloaded

Tracks without a confident match, or whose download failed, are listed in a uniquely named `out/<playlist>/skipped-<batch-id>.csv` with a `Reason` column. The exact filename is printed at the end of the run. Keep its matching `.state.json` file next to it: this records original playlist order and previously completed tracks. Retry using that exact CSV path and the original output folder and format:

```bash
docker compose run --rm csvmusic --csv "/out/My Playlist/skipped-<batch-id>.csv" --out /out --format mp3
```

The retry rebuilds the M3U with previously downloaded and recovered tracks in their original order, preserving track/disc numbers. Do not use `--no-m3u` if you want recovered songs included. A completed retry removes only its own verified CSV/state pair. A partial retry creates a new pair before removing the old one. Other batches and unrelated `skipped.csv` files are left alone. If the retry CSV or playlist was edited, rerun the original CSV instead. Do not run overlapping jobs against the same playlist folder.

Exit status is `0` on complete success, `2` when some tracks were not downloaded, and `1` for invalid input/setup. Scheduled jobs can use this to detect failures. `--no-skipped-csv` leaves any existing retry files untouched.

## File ownership and folders

Files are created as `PUID:PGID` (default `1000:1000`), not root. Set them to your user (`id -u`, `id -g`) and choose the folders in a `.env` file next to `docker-compose.yml`:

```bash
PUID=1000
PGID=1000
TZ=Europe/Paris
CSVMUSIC_IN=/srv/music/csv
CSVMUSIC_OUT=/srv/music/library
CSVMUSIC_CONFIG=./config
```

If `out/` doesn't exist yet, the container creates it for that user. If you point `/out` at an existing folder that belongs to someone else, the container stops with a message asking you to fix PUID/PGID.

`config/` holds the log (`config/.local/share/csvmusic/app.log`) and yt-dlp's cache.

## Running unattended

The container runs once and exits, so you can run it in `tmux`/`screen`, with `nohup`, or from cron:

```bash
cd /path/to/CSVMusic && docker compose run --rm -T csvmusic --csv "/in/My Playlist.csv" --out /out --format mp3 >> config/cron.log 2>&1
```

Large batches can trigger YouTube rate limits. If many tracks fail with HTTP 429 or "confirm you're not a bot", wait a while and retry from the printed retry CSV. Age-restricted videos need a signed-in YouTube session, which the desktop app supports and the headless CLI does not.

## Update

```bash
git pull
docker compose build --pull
```
