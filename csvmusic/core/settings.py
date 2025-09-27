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
	linux_old = pathlib.Path.home() / ".local" / "share" / "spotify2media"
	linux_new = pathlib.Path.home() / ".local" / "share" / "csvmusic"
	if linux_old.exists() and not linux_new.exists():
		try:
			linux_old.rename(linux_new)
		except Exception:
			return linux_old
	return linux_new

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

def save_settings(data: dict) -> None:
	try:
		p = settings_path()
		existing = load_settings()
		merged = dict(existing)
		merged.update({k: v for k, v in data.items()})
		with p.open("w", encoding="utf-8") as f:
			json.dump(merged, f, ensure_ascii=False, indent=2)
	except Exception:
		pass
