# tabs only
from dataclasses import dataclass
from functools import lru_cache
import re, shutil, subprocess

from csvmusic.core.paths import INTERNAL_YTDLP
from csvmusic.core.subprocess_env import subprocess_kwargs

_MIN_YTDLP_JS_RUNTIMES = (2026, 6, 9)


@dataclass(frozen=True)
class JsRuntimeInfo:
	name: str
	yt_dlp_name: str
	path: str
	version: str
	supported: bool
	reason: str = ""


def _version_tuple(text: str) -> tuple[int, ...]:
	return tuple(int(part) for part in re.findall(r"\d+", text)[:4])


def _version_at_least(found: tuple[int, ...], minimum: tuple[int, ...]) -> bool:
	width = max(len(found), len(minimum))
	return found + (0,) * (width - len(found)) >= minimum + (0,) * (width - len(minimum))


def _run_version(path: str) -> str:
	proc = subprocess.run(
		[path, "--version"],
		stdout=subprocess.PIPE,
		stderr=subprocess.STDOUT,
		text=True,
		timeout=3,
		**subprocess_kwargs(),
	)
	return (proc.stdout or "").strip().splitlines()[0] if proc.stdout else ""


def _probe_runtime(name: str, yt_dlp_name: str, command_names: tuple[str, ...], minimum: tuple[int, ...] | None) -> JsRuntimeInfo | None:
	for command in command_names:
		path = shutil.which(command)
		if not path:
			continue
		try:
			version = _run_version(path)
		except Exception as exc:
			return JsRuntimeInfo(name, yt_dlp_name, path, "unknown", False, f"version check failed: {exc}")
		if minimum:
			found = _version_tuple(version)
			if not found or not _version_at_least(found, minimum):
				min_text = ".".join(str(part) for part in minimum)
				return JsRuntimeInfo(name, yt_dlp_name, path, version or "unknown", False, f"requires {min_text}+")
		return JsRuntimeInfo(name, yt_dlp_name, path, version or "unknown", True)
	return None


@lru_cache(maxsize=1)
def detect_js_runtimes() -> tuple[JsRuntimeInfo, ...]:
	runtimes: list[JsRuntimeInfo] = []
	for args in (
		("Deno", "deno", ("deno",), (2, 3, 0)),
		("Node", "node", ("node", "nodejs"), (22, 0, 0)),
		("QuickJS", "quickjs", ("qjs",), (2023, 12, 9)),
	):
		info = _probe_runtime(*args)
		if info:
			runtimes.append(info)
	return tuple(runtimes)


def _yt_dlp_version(yt_dlp_bin: str | None) -> str:
	if not yt_dlp_bin or yt_dlp_bin == INTERNAL_YTDLP:
		try:
			from yt_dlp.version import __version__
			return __version__
		except Exception:
			return ""
	try:
		return _run_version(yt_dlp_bin)
	except Exception:
		return ""


@lru_cache(maxsize=16)
def ytdlp_supports_js_runtimes(yt_dlp_bin: str | None = None) -> bool:
	version = _version_tuple(_yt_dlp_version(yt_dlp_bin))
	return bool(version) and _version_at_least(version, _MIN_YTDLP_JS_RUNTIMES)


def ytdlp_js_runtime_args(yt_dlp_bin: str | None = None) -> list[str]:
	if not ytdlp_supports_js_runtimes(yt_dlp_bin):
		return []
	enabled = [
		info.yt_dlp_name
		for info in detect_js_runtimes()
		if info.supported and info.yt_dlp_name != "deno"
	]
	if not enabled:
		return []
	return ["--js-runtimes", ",".join(enabled)]
