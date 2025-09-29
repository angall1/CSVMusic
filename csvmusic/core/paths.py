# tabs only
import os, sys, shutil, pathlib, stat


def _meipass_dir() -> pathlib.Path | None:
	if hasattr(sys, "_MEIPASS"):
		try:
			return pathlib.Path(sys._MEIPASS)  # type: ignore[attr-defined]
		except Exception:
			return None
	return None

def _is_frozen() -> bool:
	return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")

def resource_base() -> pathlib.Path:
	if _is_frozen():
		base = pathlib.Path(sys._MEIPASS)	# type: ignore[attr-defined]
		candidates = [
			base / "resources",
			pathlib.Path(sys.executable).resolve().parent / "resources",
			base
		]
		for cand in candidates:
			if cand.exists():
				return cand
		return base
	return pathlib.Path(__file__).resolve().parents[2] / "resources"

def splash_image_path() -> pathlib.Path | None:
	base = resource_base()
	for name in ("splash_small.png", "splash.png"):
		p = base / name
		if p.exists():
			return p
	return None

def app_icon_path() -> pathlib.Path | None:
	base = resource_base()
	candidates = [
		base / "app.ico",
		base / "icon.ico",
		base / "app.png",
		base / "icon.png"
	]
	if sys.platform.startswith("win"):
		exe_icon = pathlib.Path(sys.executable).with_suffix(".ico")
		candidates.append(exe_icon)
	for path in candidates:
		if path and path.exists():
			return path
	return None

def platform_key() -> str:
	p = sys.platform
	if p.startswith("darwin"):
		return "darwin"
	if p.startswith("linux"):
		return "linux"
	if p.startswith("win"):
		return "windows"
	raise RuntimeError(f"Unsupported platform: {p}")

def ffmpeg_packaged_path() -> pathlib.Path:
	name = "ffmpeg.exe" if platform_key() == "windows" else "ffmpeg"
	plat = platform_key()
	base = resource_base()
	exe_dir = pathlib.Path(sys.executable).resolve().parent
	meipass = _meipass_dir()
	search_roots = [base, exe_dir]
	if meipass:
		search_roots.extend([meipass, meipass / "resources"])
	search_roots.extend([
		exe_dir / "resources",
		base.parent,
	])

	checked: set[pathlib.Path] = set()
	for root in search_roots:
		if not isinstance(root, pathlib.Path):
			continue
		if root in checked:
			continue
		checked.add(root)
		for rel in (
			pathlib.Path("ffmpeg") / plat / name,
			pathlib.Path("resources") / "ffmpeg" / plat / name,
			pathlib.Path("ffmpeg") / name,
			pathlib.Path(name),
		):
			candidate = root / rel
			if candidate.exists():
				return candidate

	for root in checked:
		try:
			found = next(root.rglob(name))
			if found.exists():
				return found
		except Exception:
			continue

	return base / "ffmpeg" / plat / name

def ensure_executable(p: pathlib.Path) -> None:
	try:
		mode = p.stat().st_mode
		p.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
	except Exception:
		pass

def ffmpeg_path() -> str:
	override = os.environ.get("FFMPEG_BIN")
	if override and shutil.which(override):
		return override
	p = ffmpeg_packaged_path()
	if p.exists():
		ensure_executable(p)
		return str(p)
	sys_ff = shutil.which("ffmpeg")
	if sys_ff:
		return sys_ff
	raise RuntimeError("ffmpeg binary not found (packaged or system).")
