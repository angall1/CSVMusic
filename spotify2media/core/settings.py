# tabs only
import json, os, sys, pathlib

_SETTINGS_FILE = "settings.json"

def _settings_dir() -> pathlib.Path:
	if sys.platform.startswith("win"):
		appdata = os.environ.get("APPDATA")
		if appdata:
			return pathlib.Path(appdata) / "Spotify2Media"
	return pathlib.Path.home() / ".local" / "share" / "spotify2media"

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
