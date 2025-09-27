# CSVMusic

<table align="center">
  <tr>
    <td><img src="https://github.com/user-attachments/assets/4e91f3b1-dc2b-4f00-aa65-924fbc7dfd6f" alt="CSVMusic playlist view" width="420" /></td>
    <td><img src="https://github.com/user-attachments/assets/3912e9fd-7bb4-4d2b-9f8b-baaeea60e006" alt="CSVMusic queue view" width="420" /></td>
  </tr>
</table>

<p align="center"><a href="https://buymeacoffee.com/agalli">Enjoying CSVMusic? Buy me a coffee ☕</a></p>

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

## Release Automation
- Create and push a Git tag for the commit you want to ship.
- Publish a GitHub release; the workflow builds Linux, macOS, and Windows bundles automatically (or trigger the `Release Builds` workflow manually with the release tag).
- The Linux job also uploads the source tarball and wheel built via `python -m build`.
- Each PyInstaller zip includes platform-specific FFmpeg binaries and `yt-dlp`, so the app runs out of the box.
- Keep `resources/ffmpeg/**` and `Spotify2Media.spec` updated if you change binary locations—releases depend on them.

Developers can run the source version by creating a virtual environment, installing with `pip install -e .`, and launching `python -m spotify2media.app`. See `AGENTS.md` for repo guidelines if you plan to contribute changes.

Enjoy building a local library from any streaming service!
