# tabs only
import os, sys, shutil, pathlib, stat
from typing import Iterable

try:
	from csvmusic.core.log import log as _log
except Exception:
	def _log(msg: str) -> None:
		pass


def _debug(msg: str) -> None:
	try:
		_log(msg)
	except Exception:
		pass

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

def _dedup(paths: Iterable[pathlib.Path]) -> list[pathlib.Path]:
	seen: set[pathlib.Path] = set()
	result: list[pathlib.Path] = []
	for path in paths:
		resolved = path.resolve()
		if resolved in seen:
			continue
		seen.add(resolved)
		result.append(resolved)
	return result


def _ffmpeg_candidates(name: str, plat: str) -> list[pathlib.Path]:
	paths: list[pathlib.Path] = []
	meipass = _meipass_dir()
	if meipass:
		paths.extend([
			meipass / "ffmpeg" / plat / name,
			meipass / "resources" / "ffmpeg" / plat / name,
		])
	try:
		exe_dir = pathlib.Path(sys.executable).resolve().parent
		paths.extend([
			exe_dir / "ffmpeg" / plat / name,
			exe_dir / "resources" / "ffmpeg" / plat / name,
			exe_dir.parent / "ffmpeg" / plat / name,
			exe_dir.parent / "resources" / "ffmpeg" / plat / name,
		])
	except Exception:
		pass
	try:
		res_base = resource_base()
		paths.append(res_base / "ffmpeg" / plat / name)
		paths.append(res_base.parent / "ffmpeg" / plat / name)
	except Exception:
		pass
	try:
		module_root = pathlib.Path(__file__).resolve().parents[2]
		paths.append(module_root / "resources" / "ffmpeg" / plat / name)
		paths.append(module_root / "ffmpeg" / plat / name)
	except Exception:
		pass
	paths.append(pathlib.Path.cwd() / "ffmpeg" / plat / name)
	try:
		exe_path = pathlib.Path(sys.executable).resolve()
		paths.append(exe_path.with_name(name))
	except Exception:
		pass
	unique = _dedup(paths)
	_debug(f"ffmpeg search candidates: {unique}")
	return unique

def ffmpeg_packaged_path() -> pathlib.Path:
	global _FFMPEG_CACHE
	if _FFMPEG_CACHE and _FFMPEG_CACHE.exists():
		return _FFMPEG_CACHE
	plat = platform_key()
	name = "ffmpeg.exe" if plat == "windows" else "ffmpeg"
	_debug(f"Resolving ffmpeg for platform={plat}")
	for candidate in _ffmpeg_candidates(name, plat):
		if candidate.exists():
			_debug(f"ffmpeg found at {candidate}")
			_FFMPEG_CACHE = candidate
			return candidate
		parent = candidate.parent
		if parent.name.lower() == plat and parent.parent.exists():
			alt = parent.parent / name
			if alt.exists():
				_debug(f"ffmpeg found via parent fallback at {alt}")
				_FFMPEG_CACHE = alt
				return alt
	fallbacks: list[pathlib.Path] = []
	try:
		res_base = resource_base()
		fallbacks.append(res_base / "ffmpeg" / plat / name)
		fallbacks.append(res_base.parent / "ffmpeg" / plat / name)
	except Exception:
		pass
	try:
		module_root = pathlib.Path(__file__).resolve().parents[2]
		fallbacks.append(module_root / "resources" / "ffmpeg" / plat / name)
	except Exception:
		pass
	fallbacks.append(pathlib.Path(name))
	_debug(f"ffmpeg fallback candidates: {fallbacks}")
	for fb in _dedup(fallbacks):
		if fb.exists():
			_debug(f"ffmpeg found via fallback at {fb}")
			_FFMPEG_CACHE = fb
			return fb
	which = shutil.which(name)
	if which:
		_debug(f"ffmpeg found via PATH at {which}")
		_FFMPEG_CACHE = pathlib.Path(which)
		return _FFMPEG_CACHE
	if fallbacks:
		_debug(f"ffmpeg not found; returning first fallback {fallbacks[0]}")
		_FFMPEG_CACHE = fallbacks[0]
		return fallbacks[0]
	_debug("ffmpeg not found anywhere; raising runtime error")
	raise RuntimeError("ffmpeg binary not found (packaged or system).")


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
