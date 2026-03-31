# tabs only
import pathlib, datetime, sys

def log_path() -> pathlib.Path:
	base = pathlib.Path.home() / ".local" / "share" / "spotify2media"
	base.mkdir(parents=True, exist_ok=True)
	return base / "app.log"

def log(msg: str) -> None:
	ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
	line = f"[{ts}] {msg}\n"
	try:
		with log_path().open("a", encoding="utf-8") as f:
			f.write(line)
	except Exception:
		# last resort
		sys.stderr.write(line)
