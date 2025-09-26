# tabs only
from dataclasses import dataclass
import shutil, subprocess, sys
from typing import Dict, List
import pathlib
import os

import requests

from spotify2media.core.paths import ffmpeg_path

_WINDOWS = sys.platform.startswith("win")


def _hidden_subprocess_kwargs() -> dict:
	if not _WINDOWS:
		return {}
	startupinfo = subprocess.STARTUPINFO()
	startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
	flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
	return {"startupinfo": startupinfo, "creationflags": flags}


@dataclass
class PreflightCheckResult:
	errors: List[str]
	warnings: List[str]
	details: Dict[str, str]



def _valid_executable(path: pathlib.Path) -> bool:
	return path.exists() and path.is_file() and os.access(path, os.X_OK)


def _check_yt_dlp(errors: List[str], warnings: List[str], details: Dict[str, str], override: str | None = None) -> None:
	bin_path = None
	if override:
		over = pathlib.Path(override)
		if _valid_executable(over):
			bin_path = str(over)
		else:
			errors.append(f"yt-dlp override invalid: {override}")
	if bin_path is None:
		bin_path = shutil.which("yt-dlp")
		if not bin_path:
			errors.append("yt-dlp not found in PATH. Install it or configure the path in Advanced Settings.")
			return
	try:
		proc = subprocess.run(
			[bin_path, "--version"],
			stdout=subprocess.PIPE,
			stderr=subprocess.STDOUT,
			text=True,
			timeout=5,
			**_hidden_subprocess_kwargs()
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
		proc = subprocess.run(
			[path, "-version"],
			stdout=subprocess.PIPE,
			stderr=subprocess.STDOUT,
			text=True,
			timeout=5,
			**_hidden_subprocess_kwargs()
		)
		if proc.returncode != 0:
			errors.append("ffmpeg responded with a non-zero exit code. Verify the bundled binary works.")
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


def run_preflight_checks(yt_dlp_override: str | None = None, ffmpeg_override: str | None = None, *, skip_network: bool = False) -> PreflightCheckResult:
	errors: List[str] = []
	warnings: List[str] = []
	details: Dict[str, str] = {}
	_check_yt_dlp(errors, warnings, details, yt_dlp_override)
	_check_ffmpeg(errors, warnings, details, ffmpeg_override)
	if not skip_network:
		_check_network(warnings, details)
	return PreflightCheckResult(errors=errors, warnings=warnings, details=details)
