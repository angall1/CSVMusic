# Contributing to CSVMusic

Contributions are welcome! Whether you're fixing bugs, adding features, or improving documentation, here's how to get started:

## Development Setup

1. Clone the repository and create a virtual environment:
   ```bash
   git clone https://github.com/angall1/CSVMusic.git
   cd CSVMusic
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

2. Install in editable mode:
   ```bash
   pip install -e .
   ```

3. Run the application:
   ```bash
   python -m csvmusic.app
   ```

## Code Style Guidelines

- **Indentation:** Use tabs only (never spaces)
- **Naming:** `lowercase_with_underscores` for modules and functions
- **Strings:** Prefer double quotes
- **Type hints:** Required on new public functions
- **Logging:** Always use `csvmusic.core.log.log` instead of `print()`

See `CLAUDE.md` for detailed architecture and workflow documentation.

## Submitting Changes

1. Fork the repository and create a feature branch
2. Make your changes following the code style guidelines
3. Test your changes on your platform (see testing notes below)
4. Commit with clear, imperative messages (e.g., "fix: handle missing ISRC field")
5. Push to your fork and open a pull request with a description of your changes

## Testing

Currently there's no automated test suite. When testing changes:
- Test the full pipeline: CSV import → matching → downloading
- Verify UI updates correctly (table, progress bars, status messages)
- Check logs for errors or warnings
- Test edge cases (malformed CSV, missing fields, no matches)

## Reporting Issues

Found a bug or have a feature request? Please help us help you by including:

### Required Information

- **Platform:** Windows/Linux/macOS version (e.g., "Windows 11", "Ubuntu 22.04", "macOS 14.2")
- **CSVMusic Version:** Release version or commit hash
- **Problematic Tracks:** Include the specific song(s) that failed (artist, title, album). Attach a CSV sample or paste the relevant rows so we can replicate the issue
- **Steps to Reproduce:**
  1. Specific actions taken (e.g., "Loaded CSV with 50 tracks")
  2. What happened vs. what you expected
  3. Does it happen consistently or intermittently?

### Helpful Additional Details

- **CSV sample:** If the issue is CSV-specific, attach a minimal example (remove sensitive data)
- **Logs:** Check the console output or log files for error messages
- **Screenshots:** For UI issues, screenshots are extremely helpful
- **Error messages:** Copy the full error text if available

### Example Issue Report

```
**Platform:** Windows 10 22H2
**Version:** v1.2.3

**Problematic Tracks:**
- Artist: Artist Name 1, Title: Song Title 1, Album: Album Name 1
- Artist: Artist Name 2, Title: Song Title 2, Album: Album Name 2
(See attached CSV sample with these tracks)

**Steps to Reproduce:**
1. Load attached CSV file (10 tracks)
2. Click "Start Download"
3. App freezes after 3rd track

**Expected:** All tracks should download
**Actual:** App becomes unresponsive, must force quit

**Logs:**
[Paste relevant log output here]
```
