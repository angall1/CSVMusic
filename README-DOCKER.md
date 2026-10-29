# CSVMusic in Docker (headless)

Run CSVMusic's CSV downloader on a home server or NAS, with no desktop and no Qt. The image wraps the existing CLI (`python -m csvmusic.download_csv`): CSV → YouTube Music match → download → tag (title, artist, album, year, cover art) → `.m3u8` playlist.

The image works on `linux/amd64` and `linux/arm64` (e.g. a Raspberry Pi 4/5). It contains Python, FFmpeg and Deno, which yt-dlp needs for YouTube.

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
| `--playlist "Name"` | Only that playlist from a multi-playlist CSV |
| `--no-m3u` | Don't write the `.m3u8` playlist |
| `--no-skipped-csv` | Don't write `skipped.csv` |
| `-v` | Verbose output |

Cover art comes from the CSV's `Cover URL` column when it has one, otherwise from the YouTube thumbnail.

## Tracks that were not downloaded

Tracks without a confident match, or whose download failed, are listed in `out/<playlist>/skipped.csv` with a `Reason` column. It is a normal CSVMusic CSV, so you can retry just those later:

```bash
docker compose run --rm csvmusic --csv "/out/My Playlist/skipped.csv" --out /out --format mp3 --no-m3u
```

Use `--no-m3u` on retries so the playlist file from the first run is kept. When a retry gets everything, `skipped.csv` is removed.

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

`config/` holds the log (`config/.local/share/csvmusic/app.log`) and yt-dlp's cache.

## Running unattended

The container runs once and exits, so you can run it in `tmux`/`screen`, with `nohup`, or from cron:

```bash
cd /path/to/CSVMusic && docker compose run --rm -T csvmusic --csv "/in/My Playlist.csv" --out /out --format mp3 >> config/cron.log 2>&1
```

Large batches can trigger YouTube rate limits. If many tracks fail with HTTP 429 or "confirm you're not a bot", wait a while and retry from `skipped.csv`. Age-restricted videos need a signed-in YouTube session, which the desktop app supports and the headless CLI does not.

## Update

```bash
git pull
docker compose build --pull
```
