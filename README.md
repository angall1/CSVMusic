# CSVMusic

<table align="center">
  <tr>
    <td><img src="https://github.com/user-attachments/assets/4e91f3b1-dc2b-4f00-aa65-924fbc7dfd6f" alt="CSVMusic playlist view" width="420" /></td>
    <td><img src="https://github.com/user-attachments/assets/3912e9fd-7bb4-4d2b-9f8b-baaeea60e006" alt="CSVMusic queue view" width="420" /></td>
  </tr>
</table>

<p align="center"><a href="https://buymeacoffee.com/agalli">Enjoying CSVMusic? Buy me a coffee</a></p>

**Convert playlists from any music service into fully tagged audio files.**

CSVMusic takes a playlist exported as CSV from TuneMyMusic and automatically:
- Finds the best match on YouTube Music
- Downloads the audio
- Adds metadata such as artist, album, and artwork
- Outputs ready-to-use **M4A** or **MP3** files
- Optionally creates `.m3u` / `.m3u8` playlists

---

# Download

Go here:
https://github.com/angall1/CSVMusic/releases/tag/v1.4.9

Download one of the following based on your OS:

### Windows
https://github.com/angall1/CSVMusic/releases/download/v1.4.9/CSVMusic-windows.zip

### macOS (Apple Silicon)
https://github.com/angall1/CSVMusic/releases/download/v1.4.9/CSVMusic-macos-arm64.zip

### macOS (Intel)
https://github.com/angall1/CSVMusic/releases/download/v1.4.9/CSVMusic-macos-intel.zip

### Linux
https://github.com/angall1/CSVMusic/releases/download/v1.4.9/CSVMusic-linux.zip

Unzip the file and run the app.

---

# What's New In 1.4.9

- Alternative match results now show the uploader first, making same-title results easier to tell apart.
- Alternative rows include a **Listen** button that opens the selected YouTube result before downloading.
- YouTube cookie-backed downloads no longer retry without cookies for age/sign-in-only failures.
- YouTube player challenge handling now supports current `yt-dlp[default]` EJS requirements and can auto-enable installed Node 22+.
- Accented track and artist filenames are handled more reliably across Unicode normalization differences.
- macOS packaged builds sanitize PyInstaller subprocess environment variables before launching `yt-dlp` or `ffmpeg`.

---

# How It Works

1. Open the app. First launch may take a few seconds.
2. Click the **TuneMyMusic** link in the top-left.
3. On TuneMyMusic:
   - Import your playlist from Spotify, Apple Music, or another service.
   - Export to file as a **CSV file**.
4. Back in CSVMusic:
   - Load the CSV.
   - Choose an output folder.
   - Click **Start**.
5. Wait for downloads to finish.

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
- Your CSV stays local.
- YouTube Music / YouTube is contacted to search and download audio.
- Cookies are optional, but may help with age-restricted or sign-in-only videos.
- Current YouTube extraction may require a supported JavaScript runtime. Packaged releases include the needed `yt-dlp` extras; source installs should use `pip install -e .` so `yt-dlp[default]` is installed. Node 22+ or Deno 2.3+ is recommended if YouTube reports player challenge errors.

---

# Supported Sources

Any service TuneMyMusic can export to CSV should work, including:
- Spotify
- Apple Music
- YouTube
- Deezer
- Most others
