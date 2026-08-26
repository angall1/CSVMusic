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
https://github.com/angall1/CSVMusic/releases/tag/v1.6.6

Download one of the following based on your OS:

### Windows
https://github.com/angall1/CSVMusic/releases/download/v1.6.6/CSVMusic-windows.zip

### macOS (Apple Silicon)
https://github.com/angall1/CSVMusic/releases/download/v1.6.6/CSVMusic-macos-arm64.zip

### macOS (Intel)
https://github.com/angall1/CSVMusic/releases/download/v1.6.6/CSVMusic-macos-intel.zip

### Linux
https://github.com/angall1/CSVMusic/releases/download/v1.6.6/CSVMusic-linux.zip

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

# What's New In 1.6.6 (Since 1.6.0)

## Updates and MP3 reliability

- Added a lightweight startup update check that prompts when a newer stable CSVMusic release is available, with options to download, be reminded later, or skip that version.
- Fixed intermittent MP3 failures when YouTube exposes only a combined audio/video stream. CSVMusic still prefers audio-only downloads and now safely falls back to extracting audio from the best available combined stream.

## YouTube reliability

- Fixed preflight incorrectly reporting the bundled yt-dlp as too old when antivirus scanning or slower storage made its version probe take more than three seconds.
- Added yt-dlp's automatic YouTube client selection as an early fallback, allowing current upstream clients such as `visionos` to recover when a forced client temporarily exposes no playable formats.
- Updated and pinned yt-dlp to `2026.08.19`, fixing widespread HTTP 403 failures with current YouTube `web_embedded` downloads and preventing release builds from silently changing downloader versions.
- Fixed current YouTube player-challenge failures by packaging Deno and `yt-dlp-ejs`, passing the runtime explicitly, and validating both before downloads begin.
- Updated YouTube client fallbacks and diagnostics for current yt-dlp behavior, including clearer HTTP 403, throttling, and JavaScript-runtime messages.
- Added adaptive pacing when YouTube starts throttling or blocking a playlist download.
- Improved force-download handling for low-confidence matches and added candidate fallbacks.

## Playlist imports and workflow

- Added first-class **Exportify CSV** support for `Track URI`, `Album Name`, `Artist Name(s)`, release dates, and CSVs without a playlist column.
- Renamed **Load Playlist** to **Resume Playlist** and replaced its folder/file fork with one chooser that accepts a folder or `.m3u`/`.m3u8` file.
- Added a compact **Paste URL…** action to Alternatives for downloading a specific YouTube or YouTube Music video.
- Improved playlist accounting so existing files, queued tracks, duplicate entries, skipped matches, and failures reconcile with the requested track total.

## Audio and Windows packaging

- Shortened exceptionally long track filenames with a stable uniqueness suffix, preventing Windows output-path failures from being misreported as YouTube throttling.
- Added optional native **Opus** output under Settings. Opus streams are remuxed without lossy re-encoding and support metadata and artwork.
- Prevented FFmpeg failures caused by selecting Apple Music or iTunes auto-import folders.
- Fixed Windows release builds by accepting Deno's PowerShell-formatted SHA256 metadata while retaining archive integrity verification on every platform.
- Forced UTF-8 for packaged downloader and FFmpeg subprocesses so Unicode song titles and sanitized punctuation work reliably on Windows.

---

# How It Works

1. Open the app. First launch may take a few seconds.
2. Click **Choose...** next to **Source**.
3. Paste a supported playlist or album link, then load it.
4. Choose an output folder.
5. Click **Start**.

## Library Mode

Library Mode keeps multiple public Spotify playlists in one persistent local catalog:

1. Click **Choose...** next to **Source**, then choose **Library Mode**.
2. Paste one or more public Spotify playlist URLs, one per line, and click **Add URLs**.
3. Choose the shared output folder and M4A or MP3 format.
4. Select playlists and click **Scan Selected**, or use **Rescan All**. The public-page scanner opens each playlist and scrolls until it has collected the available track metadata and artwork.
5. Check or uncheck individual tracks. The playlist table shows how many enabled tracks are missing from disk.
6. Click **Use Enabled Tracks in CSVMusic**, then start the normal download.

The library is saved locally as `library.json` in CSVMusic's settings folder by default. **Save As...** can create a portable library file. Rescanning preserves track selections and manual YouTube corrections while reporting added and removed tracks.

For standalone development testing, launch only the Library Mode window with:

```powershell
.\.venv\Scripts\python.exe -m csvmusic.library_mode_ui
```

To fix a wrong download, select the track, click **Set YouTube Match...**, and paste the correct YouTube or YouTube Music video URL. That track is queued for replacement, and the replacement flag clears after a successful download. **Toggle Redownload** can also replace a track while retaining automatic matching.

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
- Spotify's public website can change without notice. Library Mode uses an experimental browser-based scanner for public playlists; review any incomplete-scan warning before downloading. TuneMyMusic CSV import remains available as a fallback.

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

### Spotify Web API metadata test

An experimental metadata-only importer is available for testing Spotify Web API access. It retrieves playlist and track metadata and prints the normalized result as JSON. It does not save the access token.

For the guided graphical test, run:

```powershell
.\.venv\Scripts\python.exe -m csvmusic.spotify_api_test_ui
```

The graphical test is a four-page wizard:

1. Configure the Spotify Developer Dashboard, copy the callback URL, and check the callback port.
2. Enter the public Client ID, sign in with Spotify, and verify API access.
3. Search and sort your playlists, then select any number with checkboxes or **Check All**. Nothing is selected by default.
4. Load the selected playlists and click each playlist to expand its returned tracks.

Authentication uses Authorization Code with PKCE and never requires the Client Secret. The command-line procedure below remains available for troubleshooting.

Spotify currently exposes playlist items through Web API only when the signed-in user owns or collaborates on that playlist. Followed public playlists still appear in the user's playlist list, so the wizard automatically falls back to Spotify's public page metadata when Web API returns this access restriction. Fallback playlists are labeled in the results and may be partial when Spotify's public page does not expose every track.

An additional unsigned-browser experiment can render and scroll a public playlist without Spotify credentials:

```powershell
.\.venv\Scripts\python.exe -m csvmusic.spotify_public_scrape_ui
```

It uses a temporary, non-persistent browser profile and captures only track rows Spotify renders publicly. Spotify may display a sign-in wall or stop exposing additional rows, so this does not guarantee a complete playlist.

#### One-time Spotify setup

1. Sign in to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard). Spotify currently requires a Premium account for Development Mode apps.
2. Select **Create app**. A suggested name is `CSVMusic Local Test`.
3. Enter `CSVMusic playlist metadata test` as the description.
4. Add `http://127.0.0.1:3000/callback` as the redirect URI. The current command-line test does not receive this callback, but registering it prepares the app for the planned desktop PKCE login.
5. In **Which API/SDKs are you planning to use?**, check **Web API** only. Leave **Web Playback SDK**, **Ads API**, **Android**, and **iOS** unchecked. CSVMusic only needs Web API access to request playlist and track metadata; it does not use Spotify playback, advertising, or mobile SDKs.
6. Accept Spotify's terms and create the app. Spotify's official [app setup documentation](https://developer.spotify.com/documentation/web-api/concepts/apps) explains each field.
7. Keep the app's **Client Secret** private. Do not add it to this repository, settings, or a packaged EXE. The eventual desktop integration will use [Authorization Code with PKCE](https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow), which requires only the public Client ID in the application.

#### Get a temporary token for this test

1. Open Spotify's [Get Playlist Items reference](https://developer.spotify.com/documentation/web-api/reference/get-playlists-items).
2. Sign in and use its **Try it** authorization control to create a user access token. If testing a private playlist, authorize `playlist-read-private`.
3. Copy only the generated access-token value. Do not paste the 32-character **Client ID** from the app settings: it identifies your app but cannot authorize an API request. Never paste the **Client Secret**. Spotify access tokens normally expire after one hour; see Spotify's [access-token documentation](https://developer.spotify.com/documentation/web-api/concepts/access-token).
4. In PowerShell, from the CSVMusic repository, set the token for the current terminal and run the importer:

```powershell
$env:SPOTIFY_ACCESS_TOKEN = "your-access-token"
.\.venv\Scripts\python.exe -m csvmusic.fetch_spotify_api "https://open.spotify.com/playlist/PLAYLIST_ID"
```

Replace `PLAYLIST_ID` with the playlist link or paste the complete Spotify playlist URL between the quotes. Under Spotify's current Development Mode rules, the signed-in user must own or collaborate on the playlist. A `401` means the token is missing or expired; a `403` generally means the user or app cannot access that playlist.

Remove the token from the terminal when finished:

```powershell
Remove-Item Env:SPOTIFY_ACCESS_TOKEN
```
