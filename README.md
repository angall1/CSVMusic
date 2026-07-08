# CSVMusic

<table align="center">
  <tr>
    <td><img src="https://github.com/user-attachments/assets/4e91f3b1-dc2b-4f00-aa65-924fbc7dfd6f" alt="CSVMusic playlist view" width="420" /></td>
    <td><img src="https://github.com/user-attachments/assets/3912e9fd-7bb4-4d2b-9f8b-baaeea60e006" alt="CSVMusic queue view" width="420" /></td>
  </tr>
</table>

<p align="center"><a href="https://buymeacoffee.com/agalli">Enjoying CSVMusic? Buy me a coffee</a></p>

**Convert playlists and albums from music links or CSV exports into fully tagged audio files.**

CSVMusic accepts playlist and album links from supported music services, or a playlist exported as CSV from TuneMyMusic, and automatically:
- Finds the best match on YouTube Music
- Downloads the audio
- Adds metadata such as artist, album, and artwork
- Outputs ready-to-use **M4A** or **MP3** files
- Optionally creates `.m3u` / `.m3u8` playlists

---

# Download

Go here:
https://github.com/angall1/CSVMusic/releases/tag/v1.5.0

Download one of the following based on your OS:

### Windows
https://github.com/angall1/CSVMusic/releases/download/v1.5.0/CSVMusic-windows.zip

### macOS (Apple Silicon)
https://github.com/angall1/CSVMusic/releases/download/v1.5.0/CSVMusic-macos-arm64.zip

### macOS (Intel)
https://github.com/angall1/CSVMusic/releases/download/v1.5.0/CSVMusic-macos-intel.zip

### Linux
https://github.com/angall1/CSVMusic/releases/download/v1.5.0/CSVMusic-linux.zip

Unzip the file and run the app.

---

# What's New In 1.5.0

- Paste playlist or album links directly into the app instead of exporting a CSV first.
- Supported direct links include Spotify, Apple Music, YouTube Music, YouTube playlists, SoundCloud sets, Deezer, and Amazon Music pages when public track data is available.
- Large Spotify, Deezer, YouTube, and YouTube Music playlists can load across multiple pages where the service exposes them.
- The app now warns when a service appears to hold back tracks from a larger playlist.
- **Load Playlist** can resume from either the original link or a CSV export.
- Downloads now auto-scroll to keep the active item in view.

---

# How It Works

1. Open the app. First launch may take a few seconds.
2. Click **Choose...** next to **Source**.
3. Paste a supported playlist or album link, then load it.
4. Choose an output folder.
5. Click **Start**.

CSV import is still available when a service link is unsupported or private:

1. Click **Choose...** next to **Source**.
2. Select **CSV File**.
3. Use the TuneMyMusic link in that window if you need to create a CSV:
   - Import your playlist from Spotify, Apple Music, or another service.
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
- Some antivirus software may flag bundled download/processing tools. These are usually false positives.
- Your CSV stays local. Direct links are fetched only to read public playlist or album metadata.
- YouTube Music / YouTube is contacted to search and download audio.
- Cookies are optional, but may help with age-restricted or sign-in-only videos.
- Current YouTube extraction may require a supported JavaScript runtime. Packaged releases include the needed `yt-dlp` extras; source installs should use `pip install -e .` so `yt-dlp[default]` is installed. Node 22+ or Deno 2.3+ is recommended if YouTube reports player challenge errors.
- Private playlists or pages that hide track data may not import directly. If that happens, export a CSV from TuneMyMusic and load that instead.

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
