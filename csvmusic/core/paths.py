# tabs only
import os, sys, shutil, pathlib, stat

_FFMPEG_CACHE: pathlib.Path | None = None


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

def _candidate_roots() -> list[pathlib.Path]:
	roots: list[pathlib.Path] = []
	try:
		roots.append(resource_base())
	except Exception:
		pass
	try:
		exe_dir = pathlib.Path(sys.executable).resolve().parent
		roots.extend([
			exe_dir,
			exe_dir / "resources",
			exe_dir.parent,
			exe_dir.parent / "resources",
		])
	except Exception:
		pass
	meipass = _meipass_dir()
	if meipass:
		roots.extend([meipass, meipass / "resources"])
	try:
		module_root = pathlib.Path(__file__).resolve().parents[2]
		roots.append(module_root / "resources")
	except Exception:
		pass
	return [r.resolve() for r in roots if isinstance(r, pathlib.Path)]


def _ffmpeg_candidates(name: str, plat: str) -> list[pathlib.Path]:
	seen: set[pathlib.Path] = set()
	cands: list[pathlib.Path] = []
	for root in _candidate_roots():
		if root in seen:
			continue
		seen.add(root)
		for rel in (
			pathlib.Path("ffmpeg") / plat / name,
			pathlib.Path("resources") / "ffmpeg" / plat / name,
			pathlib.Path("ffmpeg") / name,
			pathlib.Path(name),
		):
			candidate = (root / rel).resolve()
			if candidate not in cands:
				cands.append(candidate)
	try:
		exe_path = pathlib.Path(sys.executable).resolve()
		local = exe_path.with_name(name)
		if local not in cands:
			cands.append(local)
	except Exception:
		pass
	return cands

def ffmpeg_packaged_path() -> pathlib.Path:
	global _FFMPEG_CACHE
	if _FFMPEG_CACHE and _FFMPEG_CACHE.exists():
		return _FFMPEG_CACHE
	plat = platform_key()
	name = "ffmpeg.exe" if plat == "windows" else "ffmpeg"
	for candidate in _ffmpeg_candidates(name, plat):
		if candidate.exists():
			_FFMPEG_CACHE = candidate
			return candidate
		parent = candidate.parent
		if parent.name.lower() == plat and parent.parent.exists():
			alt = parent.parent / name
			if alt.exists():
				_FFMPEG_CACHE = alt
				return alt
	fallback = resource_base() / "ffmpeg" / plat / name
	_FFMPEG_CACHE = fallback
	return fallback


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
