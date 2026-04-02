# CSVMusic

<table align="center">
  <tr>
    <td><img src="https://github.com/user-attachments/assets/4e91f3b1-dc2b-4f00-aa65-924fbc7dfd6f" alt="CSVMusic playlist view" width="420" /></td>
    <td><img src="https://github.com/user-attachments/assets/3912e9fd-7bb4-4d2b-9f8b-baaeea60e006" alt="CSVMusic queue view" width="420" /></td>
  </tr>
</table>

<p align="center"><a href="https://buymeacoffee.com/agalli">Enjoying CSVMusic? Buy me a coffee ☕</a></p>


**Convert playlists from any music service into fully tagged audio files.**

CSVMusic takes a playlist (exported as CSV from TuneMyMusic) and automatically:
- Finds the best match on YouTube Music  
- Downloads the audio  
- Adds proper metadata (artist, album, artwork, etc.)  
- Outputs ready-to-use **M4A** or **MP3** files  
- Optionally creates `.m3u` / `.m3u8` playlists  

---

# Download (Start Here)

Go here:  
https://github.com/angall1/CSVMusic/releases/tag/v1.2.4  

Download one of the following based on your OS:

### Windows
https://github.com/angall1/CSVMusic/releases/download/v1.2.4/CSVMusic-windows.zip  

### macOS
https://github.com/angall1/CSVMusic/releases/download/v1.2.4/CSVMusic-macos.zip  

### Linux
https://github.com/angall1/CSVMusic/releases/download/v1.2.4/CSVMusic-linux.zip  

Unzip the file and run the app.

---

# How It Works

1. Open the app (first launch may take ~10–15 seconds)  
2. Click the **TuneMyMusic link** in the top-left  
3. Follow the steps on that site:
   - Import your playlist (Spotify, Apple Music, etc.)
   - Export to file → **CSV file**
4. Back in CSVMusic:
   - Load the CSV
   - Choose an output folder
   - Click **Start**
5. Wait for downloads to finish  

If a song can’t be matched well:
- It will show up **highlighted in yellow**
- Click **Alternatives** to pick a better version  

---

# What You Get

- Audio files with:
  - Correct artist/title
  - Album info
  - Embedded artwork  
- Optional playlist files:
  - `.m3u`
  - `.m3u8`  

Everything is ready to drop into iTunes, a phone, an MP3 player, etc.

---

# Important Notes

- Keep all files in the extracted folder together  
- The app includes:
  - `ffmpeg`
  - `yt-dlp`  

Because of this, **some antivirus software may flag it**.  
These are **false positives** due to bundled executables used for downloading and processing audio.

- Your CSV stays local  
- Only YouTube Music is contacted for downloading audio  

---

# Supported Sources (via TuneMyMusic)

- Spotify  
- Apple Music  
- YouTube  
- Deezer  
- And most others  

---
