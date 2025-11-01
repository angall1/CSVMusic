# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CSVMusic is a Windows/Linux/macOS desktop application that converts TuneMyMusic CSV playlist exports into locally stored, fully tagged audio files (MP3/M4A). The app uses YouTube Music for lookup, yt-dlp for downloading, and FFmpeg for processing.

## Build and Development Commands

**Environment Setup:**
```bash
python -m venv .venv && source .venv/bin/activate  # (or .venv\Scripts\activate on Windows)
pip install -e .
```

**Running the Application:**
```bash
python -m csvmusic.app  # Launches Qt desktop client with logging
```

**Building Distribution Packages:**
```bash
python -m build  # Generates sdist and wheel in dist/
pyinstaller CSVMusic.spec  # Creates standalone executable
```

**Testing:**
No automated test suite currently exists. When adding tests, create them under `tests/` mirroring the package structure (e.g., `tests/core/test_downloader.py`). Use `pytest` to run tests.

## Code Style

- **Indentation:** Tabs only (never spaces)
- **Naming:** lowercase_with_underscores for modules and files
- **Strings:** Double quotes preferred
- **Type hints:** Required on new public functions
- **Logging:** Always route through `csvmusic.core.log.log` for PyInstaller compatibility

## Architecture Overview

### Module Organization

```
csvmusic/
├── app.py              # Entry point; handles Qt initialization, splash screen, tkinter blocking
├── core/               # Backend logic (platform-agnostic)
│   ├── models.py       # Data classes (Track, MatchResult)
│   ├── csv_import.py   # CSV parsing, column normalization, track extraction
│   ├── ytmusic_match.py # YouTube Music search, scoring algorithm, confidence matching
│   ├── downloader.py   # yt-dlp orchestration, FFmpeg conversion, ID3/M4A tagging
│   ├── paths.py        # Platform-specific resource resolution (ffmpeg, yt-dlp)
│   ├── browsers.py     # Browser cookie extraction for yt-dlp auth
│   ├── config.py       # App configuration
│   ├── settings.py     # User settings persistence
│   ├── preflight.py    # Startup checks
│   └── log.py          # Logging wrapper
├── ui/                 # Qt6 frontend
│   ├── main_window.py  # Primary UI (table view, controls, playlist management)
│   └── workers.py      # QThread workers for async pipeline (CSV load → match → download)
├── match_csv.py        # CLI script for matching only
├── download_csv.py     # CLI script for full pipeline
└── fetch_csv.py        # CLI script for fetching from web sources
```

### Data Flow

1. **CSV Import** (`csv_import.py`):
   - Loads TuneMyMusic CSV with robust encoding/delimiter detection
   - Normalizes column names case-insensitively
   - Extracts tracks into dataclass models

2. **YouTube Music Matching** (`ytmusic_match.py`):
   - Generates query variants (ISRC, cleaned titles, "&" vs "and" swaps)
   - Searches YouTube Music API (songs filter, then videos fallback)
   - Scores candidates based on:
     - Token overlap (title/artist)
     - Duration delta
     - Channel boost ("Topic", "Official")
     - Penalties (live, remix, cover, etc.)
   - Returns best match if confidence ≥ 0.6, or returns all candidates for manual selection

3. **Download & Tagging** (`downloader.py`):
   - Invokes yt-dlp with platform-specific FFmpeg paths
   - Handles browser cookie extraction for auth (with fallback on failure)
   - Downloads as M4A or MP3 (V0 or 320 CBR)
   - Writes ID3v2 (MP3) or MP4 tags (M4A) with artist, album, title, year, track/disc numbers
   - Embeds album art from YouTube thumbnails
   - Generates M3U8 playlists

4. **UI Pipeline** (`workers.py` + `main_window.py`):
   - `PipelineWorker` runs CSV → match → download in a background thread
   - Emits Qt signals for progress updates, row status, logs
   - Main window displays tracks in a table, allows manual match selection, shows download progress

### Key Design Decisions

- **No tkinter:** App explicitly blocks tkinter imports (line 10-14 in `app.py`) because some dependencies try to import it, causing issues on systems without Tk installed
- **Platform FFmpeg bundling:** `resources/ffmpeg/{darwin,linux,windows}/` contains platform-specific binaries; `paths.py` resolves the correct one at runtime
- **PyInstaller packaging:** `CSVMusic.spec` collects all PySide6, yt-dlp, and mutagen dependencies plus resources/licenses into a single-file executable
- **Confidence thresholding:** Matches below 0.6 confidence are marked as "skipped" and can be manually reviewed in the UI
- **Rate limiting:** YouTube Music searches are rate-limited to 0.35s per request to avoid throttling
- **Cookie fallback:** If browser cookie extraction fails (e.g., Chrome is running), yt-dlp retries without cookies for public videos

## Common Workflows

**Adding a new audio format:**
1. Update `downloader.py` with new download function (e.g., `download_opus`)
2. Add FFmpeg conversion logic
3. Update `workers.py` to handle new format in `PipelineWorker`
4. Add UI option in `main_window.py` settings

**Improving match accuracy:**
- Modify scoring algorithm in `ytmusic_match._score()`
- Adjust `_PENALTY_TERMS` or `CONFIDENCE_MIN` constants
- Add new query variants in `_query_variants()`

**Changing UI layout:**
- Edit `main_window.py` (uses PySide6 widgets)
- Table column order/visibility controlled in `_setup_table()`
- Worker signals are connected in `_wire_signals()`

## Release Process

Release builds are automated via GitHub Actions (see README.md). The workflow:
1. Create and push a Git tag
2. Publish a GitHub release (or trigger "Release Builds" workflow manually)
3. Linux, macOS, and Windows executables are built with PyInstaller
4. FFmpeg binaries from `resources/ffmpeg/**` are bundled
5. Source tarball and wheel uploaded from Linux job

**Important:** Keep `resources/ffmpeg/**` paths and `CSVMusic.spec` synchronized. PyInstaller depends on correct resource paths.

## Dependencies

Core libraries:
- **PySide6:** Qt6 bindings for UI
- **yt-dlp:** YouTube video/audio downloading and searching
- **mutagen:** Audio metadata tagging
- **pandas:** CSV manipulation
- **FFmpeg:** (bundled binary) Audio conversion

## Commit Guidelines

Use imperative, scope-tagged commits:
- `feat: add YouTube fallback matching`
- `fix(core): guard ffmpeg timeouts`
- `refactor(ui): extract table setup logic`

Keep subject lines ≤72 characters. Expand context in body when touching multiple modules.
