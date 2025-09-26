# CSVMusic

CSVMusic is a Windows desktop app that turns the playlist CSV files you export from TuneMyMusic into ready-to-play, fully tagged audio. Point the app at a TuneMyMusic CSV and it handles YouTube Music lookup, `yt-dlp` downloads, and FFmpeg processing automatically.

## Quick Start
- Download the latest release zip and extract it.
- Run `CSVMusic.exe` (all dependencies, including FFmpeg, are bundled).
- Load your TuneMyMusic CSV and let the download queue finish.

## Highlights
- Accepts TuneMyMusic exports sourced from Spotify, Apple Music, YouTube, Deezer, and more.
- Chooses the best YouTube Music match before downloading.
- Writes ID3/M4A tags and embeds artwork so files drop straight into any library.

## Notes
- Keep the extracted folder together; the app expects FFmpeg alongside the executable.
- CSV data stays on the machine—only YouTube Music is contacted for audio streams.
- Rich metadata included by TuneMyMusic (duration, ISRC) helps improve matching accuracy.

## Contributing
Developers can run the source version by creating a virtual environment, installing with `pip install -e .`, and launching `python -m spotify2media.app`. See `AGENTS.md` for repo guidelines if you plan to contribute changes.

Enjoy building a local library from any streaming service!
