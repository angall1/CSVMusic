# tabs only
import json, os, sys, pathlib

_SETTINGS_FILE = "settings.json"

def _settings_dir() -> pathlib.Path:
	if sys.platform.startswith("win"):
		appdata = os.environ.get("APPDATA")
		if appdata:
			appdata_path = pathlib.Path(appdata)
			old = appdata_path / "Spotify2Media"
			new = appdata_path / "CSVMusic"
			if old.exists() and not new.exists():
				try:
					old.rename(new)
				except Exception:
					return old
			return new
	home = pathlib.Path.home()
	if sys.platform.startswith("darwin"):
		new = home / "Library" / "Application Support" / "CSVMusic"
		old_candidates = [
			home / "Library" / "Application Support" / "Spotify2Media",
			home / ".local" / "share" / "csvmusic",
			home / ".local" / "share" / "spotify2media",
		]
	else:
		xdg_data_home = os.environ.get("XDG_DATA_HOME")
		base = pathlib.Path(xdg_data_home).expanduser() if xdg_data_home else home / ".local" / "share"
		new = base / "csvmusic"
		old_candidates = [base / "spotify2media"]
	for old in old_candidates:
		if not old.exists() or new.exists():
			continue
		try:
			new.parent.mkdir(parents=True, exist_ok=True)
			old.rename(new)
		except Exception:
			return old
		break
	return new

def settings_path() -> pathlib.Path:
	d = _settings_dir()
	d.mkdir(parents=True, exist_ok=True)
	return d / _SETTINGS_FILE

def load_settings() -> dict:
	p = settings_path()
	if not p.exists():
		return {}
	try:
		with p.open("r", encoding="utf-8") as f:
			data = json.load(f)
			if isinstance(data, dict):
				return data
	except Exception:
		pass
	return {}

def _should_clear(value: object) -> bool:
	if value is None:
		return True
	if isinstance(value, str) and value.strip() == "":
		return True
	return False


def save_settings(data: dict) -> None:
	try:
		p = settings_path()
		existing = load_settings()
		merged = {k: v for k, v in existing.items() if not _should_clear(v)}
		updates = {k: v for k, v in data.items() if not _should_clear(v)}
		drops = [k for k, v in data.items() if _should_clear(v)]
		merged.update(updates)
		for key in drops:
			merged.pop(key, None)
		with p.open("w", encoding="utf-8") as f:
			json.dump(merged, f, ensure_ascii=False, indent=2)
	except Exception:
		pass
