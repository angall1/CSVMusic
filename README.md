# CSVMusic

<table align="center">
  <tr>
    <td><img src="https://github.com/user-attachments/assets/4e91f3b1-dc2b-4f00-aa65-924fbc7dfd6f" alt="CSVMusic playlist view" width="420" /></td>
    <td><img src="https://github.com/user-attachments/assets/3912e9fd-7bb4-4d2b-9f8b-baaeea60e006" alt="CSVMusic queue view" width="420" /></td>
  </tr>
</table>

<h2 align="center"><a href="https://buymeacoffee.com/agalli">☕ Enjoying CSVMusic? Buy me a coffee</a></h2>

**Convert playlists and albums from music links or CSV exports into fully tagged audio files.**

CSVMusic accepts playlist and album links from supported music services, or a playlist exported as CSV from TuneMyMusic, and automatically:
- Finds the best match on YouTube Music
- Downloads the audio
- Adds metadata such as artist, album, and artwork
- Outputs ready-to-use **M4A** or **MP3** files, with optional native **Opus** output
- Optionally creates `.m3u` / `.m3u8` playlists

---

# Download

Go here:
https://github.com/angall1/CSVMusic/releases/tag/v1.6.0

Download one of the following based on your OS:

### Windows
https://github.com/angall1/CSVMusic/releases/download/v1.6.0/CSVMusic-windows.zip

### macOS (Apple Silicon)
https://github.com/angall1/CSVMusic/releases/download/v1.6.0/CSVMusic-macos-arm64.zip

### macOS (Intel)
https://github.com/angall1/CSVMusic/releases/download/v1.6.0/CSVMusic-macos-intel.zip

### Linux
https://github.com/angall1/CSVMusic/releases/download/v1.6.0/CSVMusic-linux.zip

Extract the ZIP before running the app. If your desktop does not launch the files directly, open a terminal in the extracted folder and run:

```bash
chmod +x CSVMusic yt-dlp
./CSVMusic
```

If launch fails, copy the terminal output along with `uname -m` and the contents of `/etc/os-release` when reporting the problem.

---

# Python Wheel / Source Install

Install the wheel with `python -m pip install CSVMusic-*.whl`, or install a source checkout with `python -m pip install -e .`.
Then launch CSVMusic with either:

```text
csvmusic
python -m csvmusic
```

Python installations still require a supported graphical desktop environment for the Qt interface. Android, Andronix, and other phone-hosted Linux environments are not currently supported or tested.

---

# What's New In 1.6.0

- Fixed current YouTube player-challenge failures by packaging Deno and `yt-dlp-ejs`, passing the runtime explicitly, and validating both before downloads begin.
- Updated YouTube client fallbacks and error reporting for current yt-dlp behavior, including clearer HTTP 403 and JavaScript-runtime diagnostics.
- Added optional native **Opus** output under Settings. Opus streams are remuxed without lossy re-encoding and support metadata and artwork.
- Added first-class **Exportify CSV** support for `Track URI`, `Album Name`, `Artist Name(s)`, release dates, and CSVs without a playlist column.
- Renamed **Load Playlist** to **Resume Playlist** and replaced its folder/file fork with one chooser that accepts a folder or `.m3u`/`.m3u8` file.
- Added a compact **Paste URL…** action to Alternatives for downloading a specific YouTube or YouTube Music video.
- Improved playlist accounting so existing files, queued tracks, duplicate entries, skipped matches, and failures reconcile with the requested track total.
- Prevented FFmpeg failures caused by selecting Apple Music or iTunes auto-import folders.
- Improved force-download handling for low-confidence matches and added candidate fallbacks.

---

# How It Works

1. Open the app. First launch may take a few seconds.
2. Click **Choose...** next to **Source**.
3. Paste a supported playlist or album link, then load it.
4. Choose an output folder.
5. Click **Start**.

CSV import is still available when a service link is unsupported, private, incomplete, or when CSVMusic warns that a URL import may not contain every track:

1. Click **Choose...** next to **Source**.
2. Select **CSV File**.
3. Use the TuneMyMusic link in that window if you need to create a CSV:
   - Choose the original music service as the source.
   - Paste the same playlist link, or connect the service if TuneMyMusic asks.
   - Export to file as a **CSV file**.
4. Load the CSV, choose an output folder, and click **Start**.

If a song cannot be matched confidently:
- It will show up highlighted in yellow.
- Click **Alternatives** to pick a better result.
- Use **Listen** to preview a candidate in your browser.

---

# What You Get

- Audio files with:
  - Correct artist/title
  - Album info
  - Embedded artwork
- Optional playlist files:
  - `.m3u`
  - `.m3u8`

Everything is ready to drop into iTunes, a phone, an MP3 player, or a local music library.

---

# Important Notes

- Keep all files in the extracted folder together.
- The packaged app includes:
  - `ffmpeg`
  - `yt-dlp`
  - `yt-dlp-ejs`
  - Deno
- Some antivirus software may flag bundled download/processing tools. These are usually false positives.
- Your CSV stays local. Direct links are fetched only to read public playlist or album metadata.
- YouTube Music / YouTube is contacted to search and download audio.
- Cookies are optional, but may help with age-restricted or sign-in-only videos.
- Current YouTube extraction requires a supported JavaScript runtime. Packaged releases include Deno and the needed `yt-dlp` extras; source installs should use `pip install -e .` and provide Deno 2.3+ or Node 22+.
- Private playlists or pages that hide track data may not import directly. If that happens, export a CSV from TuneMyMusic and load that instead.
- Large Spotify playlist links can be capped at 100 tracks by Spotify's public page data. If CSVMusic warns about this, open **Choose... > TuneMyMusic**, choose Spotify as the source, paste the same playlist link, export as CSV, then load that CSV through **Choose... > CSV File**.

---

# Supported Sources

Direct link import supports public playlist or album pages from:
- Spotify
- Apple Music
- YouTube Music
- YouTube playlists
- SoundCloud sets
- Deezer
- Amazon Music, when the page exposes public track data

CSV import supports any service TuneMyMusic can export, including most other music platforms.
