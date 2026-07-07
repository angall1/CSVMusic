# tabs only
from dataclasses import dataclass
import shutil, subprocess, sys
from typing import Dict, List
import pathlib
import os

import requests

from csvmusic.core.paths import ffmpeg_path, ytdlp_path, INTERNAL_YTDLP
from csvmusic.core.js_runtime import detect_js_runtimes, ytdlp_supports_js_runtimes
from csvmusic.core.subprocess_env import subprocess_kwargs

_MACOS = sys.platform.startswith("darwin")
_MACOS_FFMPEG_FALLBACKS = (
	"/opt/homebrew/bin/ffmpeg",
	"/usr/local/bin/ffmpeg",
	"/opt/local/bin/ffmpeg",
)


@dataclass
class PreflightCheckResult:
	errors: List[str]
	warnings: List[str]
	details: Dict[str, str]



def _valid_executable(path: pathlib.Path) -> bool:
	return path.exists() and path.is_file() and os.access(path, os.X_OK)


def _ffmpeg_probe_timeout(path: str) -> int:
	if _MACOS and "_MEI" in path:
		return 60
	return 5


def _run_ffmpeg_version(path: str) -> subprocess.CompletedProcess[str]:
	return subprocess.run(
		[path, "-version"],
		stdout=subprocess.PIPE,
		stderr=subprocess.STDOUT,
		text=True,
		timeout=_ffmpeg_probe_timeout(path),
		**subprocess_kwargs()
	)


def _system_ffmpeg_candidates() -> list[str]:
	candidates: list[str] = []
	which = shutil.which("ffmpeg")
	if which:
		candidates.append(which)
	if _MACOS:
		for fallback in _MACOS_FFMPEG_FALLBACKS:
			if pathlib.Path(fallback).exists():
				candidates.append(fallback)
	seen: set[str] = set()
	unique: list[str] = []
	for candidate in candidates:
		if candidate in seen:
			continue
		seen.add(candidate)
		unique.append(candidate)
	return unique


def _check_yt_dlp(errors: List[str], warnings: List[str], details: Dict[str, str], override: str | None = None) -> None:
	bin_path: str | None = None
	if override:
		over = pathlib.Path(override)
		if _valid_executable(over):
			bin_path = str(over)
		else:
			errors.append(f"yt-dlp override invalid: {override}")
			return
	if bin_path is None:
		try:
			bin_path = ytdlp_path()
		except Exception as exc:
			errors.append(str(exc))
			return
	if bin_path == INTERNAL_YTDLP:
		try:
			from yt_dlp.version import __version__
			details["yt-dlp"] = f"bundled module ({__version__})"
		except Exception as exc:
			warnings.append(f"Failed to query bundled yt-dlp version: {exc}")
		return
	try:
		proc = subprocess.run(
			[bin_path, "--version"],
			stdout=subprocess.PIPE,
			stderr=subprocess.STDOUT,
			text=True,
			timeout=5,
			**subprocess_kwargs()
		)
		version = (proc.stdout or "").strip().splitlines()[0] if proc.stdout else "unknown"
		details["yt-dlp"] = f"{bin_path} ({version})"
		if proc.returncode != 0:
			warnings.append("yt-dlp returned a non-zero exit code when checking the version.")
	except Exception as exc:
		warnings.append(f"Failed to query yt-dlp version: {exc}")


def _check_ffmpeg(errors: List[str], warnings: List[str], details: Dict[str, str], override: str | None = None) -> None:
	try:
		if override:
			ov = pathlib.Path(override)
			if not _valid_executable(ov):
				errors.append(f"ffmpeg override invalid: {override}")
				return
			path = str(ov)
		else:
			path = ffmpeg_path()
		details["ffmpeg"] = path
		proc = _run_ffmpeg_version(path)
		if proc.returncode != 0:
			errors.append("ffmpeg responded with a non-zero exit code. Verify the bundled binary works.")
	except subprocess.TimeoutExpired as exc:
		for sys_ff in _system_ffmpeg_candidates():
			if sys_ff == details.get("ffmpeg"):
				continue
			try:
				proc = _run_ffmpeg_version(sys_ff)
				details["ffmpeg"] = sys_ff
				warnings.append(
					f"Bundled ffmpeg timed out during preflight; using system ffmpeg at {sys_ff}."
				)
				if proc.returncode != 0:
					errors.append("System ffmpeg responded with a non-zero exit code during fallback.")
				return
			except Exception as fallback_exc:
				warnings.append(f"System ffmpeg fallback failed at {sys_ff}: {fallback_exc}")
		errors.append(f"ffmpeg unavailable: {exc}")
	except Exception as exc:
		errors.append(f"ffmpeg unavailable: {exc}")


def _check_network(warnings: List[str], details: Dict[str, str]) -> None:
	url = "https://music.youtube.com"
	try:
		resp = requests.get(url, timeout=5)
		if resp.status_code >= 400:
			warnings.append(f"Network check returned HTTP {resp.status_code} when reaching {url}.")
		else:
			details["network"] = f"{url} OK"
	except Exception as exc:
		warnings.append(f"Could not reach {url}: {exc}")


def _check_js_runtime(warnings: List[str], details: Dict[str, str], yt_dlp_override: str | None = None) -> None:
	try:
		yt_bin = yt_dlp_override or ytdlp_path()
	except Exception:
		yt_bin = yt_dlp_override
	runtimes = detect_js_runtimes()
	supported = [rt for rt in runtimes if rt.supported]
	if supported:
		details["JavaScript runtime"] = "; ".join(f"{rt.name} {rt.version}" for rt in supported)
	else:
		if runtimes:
			details["JavaScript runtime"] = "; ".join(f"{rt.name} {rt.version} ({rt.reason})" for rt in runtimes)
		else:
			details["JavaScript runtime"] = "not found"
		warnings.append(
			"YouTube may fail with player challenge errors because no supported JavaScript runtime was found. "
			"Install Deno 2.3+ (recommended) or Node 22+."
		)
		return
	if not any(rt.yt_dlp_name == "deno" for rt in supported) and not ytdlp_supports_js_runtimes(yt_bin):
		warnings.append(
			"A supported JavaScript runtime is installed, but this yt-dlp version is too old for CSVMusic to enable it automatically. "
			"Update yt-dlp with the default extras."
		)


def run_preflight_checks(yt_dlp_override: str | None = None, ffmpeg_override: str | None = None, *, skip_network: bool = False) -> PreflightCheckResult:
	errors: List[str] = []
	warnings: List[str] = []
	details: Dict[str, str] = {}
	_check_yt_dlp(errors, warnings, details, yt_dlp_override)
	_check_ffmpeg(errors, warnings, details, ffmpeg_override)
	_check_js_runtime(warnings, details, yt_dlp_override)
	if not skip_network:
		_check_network(warnings, details)
	return PreflightCheckResult(errors=errors, warnings=warnings, details=details)
