# Repository Guidelines

## Project Structure & Module Organization
The root hosts packaging metadata (`pyproject.toml`, `CSVMusic.spec`) and build outputs (`build/`, `dist/`). Source lives in `csvmusic/`. Platform integrations and CSV tooling are under `csvmusic/core/`, UI widgets reside in `csvmusic/ui/`, and reusable resources sit in `resources/` (FFmpeg binaries) and `licenses/`. Prefer placing new backend helpers inside `core/` modules; shared UI assets belong under `ui/` to avoid bundling issues.

## Build, Test, and Development Commands
- `python -m venv .venv && source .venv/bin/activate` creates the recommended local environment; install dependencies with `pip install -e .`.
- `python -m csvmusic.app` launches the Qt desktop client with hot-reload friendly logging.
- `python -m build` generates sdist and wheel artifacts for distribution.
- `pyinstaller CSVMusic.spec` reproduces the packaged binary; ensure `resources/ffmpeg/**` paths stay intact before running.

## Coding Style & Naming Conventions
Indent with tabs only (see `csvmusic/app.py`). Keep module and file names lowercase_with_underscores, and prefer descriptive dataclass models for shared state (see `core/models.py`). Use type hints on new public functions. Route logging through `csvmusic.core.log.log` so PyInstaller captures messages uniformly. Strings should favour double quotes for consistency with existing files.

## Testing Guidelines
No automated suite ships yet; add tests under `tests/` mirroring the package layout (e.g. `tests/core/test_downloader.py`). Use `pytest` (`pip install pytest`, then `pytest`) and target at least smoke coverage for Spotify fetching, CSV matching, and download orchestration. When adding UI behaviour, isolate business logic in testable helpers inside `core/` before wiring signals in Qt.

## Commit & Pull Request Guidelines
Adopt imperative, scope-tagged commits such as `feat: add YouTube fallback matching` or `fix(core): guard ffmpeg timeouts`. Keep subject lines ≤72 characters and expand context in the body when touching multiple modules. Pull requests should outline functional changes, manual test evidence (commands run and playlists tried), and note any resource updates so release bundles can be regenerated.

## Security & Configuration Tips
No external Spotify credentials are required—imports flow strictly through CSV. Scrub downloaded media paths from logs before sharing traces, and avoid bundling new licensing or FFmpeg binaries directly inside feature branches.
