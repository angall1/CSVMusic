# tabs only
import os, sys, json
import pathlib
from typing import List, Tuple
import shutil

# Public API: list profiles for a browser suitable for yt-dlp's --cookies-from-browser

_WINDOWS = sys.platform.startswith("win")
_MAC = sys.platform == "darwin"
_LINUX = sys.platform.startswith("linux")

def _local_app_data() -> pathlib.Path | None:
	val = os.environ.get("LOCALAPPDATA")
	return pathlib.Path(val) if val else None

def _app_data() -> pathlib.Path | None:
	val = os.environ.get("APPDATA")
	return pathlib.Path(val) if val else None

def _home() -> pathlib.Path:
	return pathlib.Path.home()

def _chromium_base(browser: str) -> pathlib.Path | None:
	# Resolve the base user-data directory for Chromium-based browsers
	if _WINDOWS:
		lad = _local_app_data()
		if not lad: return None
		match browser:
			case "chrome":
				return lad / "Google" / "Chrome" / "User Data"
			case "edge":
				return lad / "Microsoft" / "Edge" / "User Data"
			case "brave":
				return lad / "BraveSoftware" / "Brave-Browser" / "User Data"
			case "vivaldi":
				return lad / "Vivaldi" / "User Data"
			case "opera":
				# Opera stores cookies in profile roots, but not under a common "User Data"; fall back to roaming
				ad = _app_data()
				if not ad: return None
				# Opera Stable / Opera GX Stable; yt-dlp expects browser "opera" (GX is separate, not handled here)
				# Treat base as parent to profile directories
				return ad / "Opera Software"
	else:
		# macOS / Linux common paths
		home = _home()
		if _MAC:
			match browser:
				case "chrome": return home / "Library" / "Application Support" / "Google" / "Chrome"
				case "edge": return home / "Library" / "Application Support" / "Microsoft Edge"
				case "brave": return home / "Library" / "Application Support" / "BraveSoftware" / "Brave-Browser"
				case "vivaldi": return home / "Library" / "Application Support" / "Vivaldi"
				case "opera": return home / "Library" / "Application Support" / "com.operasoftware.Opera"
		elif _LINUX:
			match browser:
				case "chrome": return home / ".config" / "google-chrome"
				case "edge": return home / ".config" / "microsoft-edge"
				case "brave": return home / ".config" / "BraveSoftware" / "Brave-Browser"
				case "vivaldi": return home / ".config" / "vivaldi"
				case "opera": return home / ".config" / "opera"
	return None

def _chromium_profiles_from_local_state(base: pathlib.Path) -> List[str]:
	# Parse the Local State JSON to enumerate known profile directories
	ls_path = base / "Local State"
	if not ls_path.exists():
		return []
	try:
		data = json.loads(ls_path.read_text(encoding="utf-8", errors="ignore"))
		info = data.get("profile", {}).get("info_cache", {})
		profiles = list(info.keys())
		# Ensure deterministic ordering and put Default first if present
		profiles.sort()
		if "Default" in profiles:
			profiles.remove("Default")
			profiles.insert(0, "Default")
		return profiles
	except Exception:
		return []

def _chromium_profiles_by_scanning(base: pathlib.Path) -> List[str]:
	# Fallback: scan for directories that look like profiles
	if not base.exists() or not base.is_dir():
		return []
	result: List[str] = []
	for entry in base.iterdir():
		if not entry.is_dir():
			continue
		name = entry.name
		if name.lower() in ("system profile", "guest profile", "pnacl", "widevinecdmadapter"):
			continue
		# Heuristics: Default, Profile X, or has Cookies DB
		if name == "Default" or name.startswith("Profile "):
			result.append(name)
			continue
		if (entry / "Network" / "Cookies").exists() or (entry / "Cookies").exists():
			result.append(name)
	# Put Default first if present
	if "Default" in result:
		result = ["Default"] + [p for p in result if p != "Default"]
	return result

def _opera_profiles(base: pathlib.Path) -> List[str]:
	# Opera profiles are separate folders under Opera Software, e.g., "Opera Stable", "Opera GX Stable"
	if not base.exists() or not base.is_dir():
		return []
	names = []
	for entry in base.iterdir():
		if not entry.is_dir():
			continue
		# Look for cookie DB as a heuristic
		if (entry / "Network" / "Cookies").exists() or (entry / "Cookies").exists():
			names.append(entry.name)
	return names

def _firefox_profiles() -> List[str]:
	# Return absolute Firefox profile paths (more reliable for yt-dlp)
	if _WINDOWS or _LINUX:
		base = (_app_data() / "Mozilla" / "Firefox") if _WINDOWS else (_home() / ".mozilla" / "firefox")
	else:
		base = _home() / "Library" / "Application Support" / "Firefox"
	ini = base / "profiles.ini"
	if not ini.exists():
		return []
	profiles: List[Tuple[str, str]] = []
	name = None
	path = None
	try:
		for raw in ini.read_text(encoding="utf-8", errors="ignore").splitlines():
			line = raw.strip()
			if not line or line.startswith("#"):
				continue
			if line.startswith("[") and line.endswith("]"):
				if name and path:
					profiles.append((name, path))
				name = None; path = None
				continue
			key, eq, val = line.partition("=")
			if not eq:
				continue
			k = key.strip().lower(); v = val.strip()
			if k == "name":
				name = v
			elif k == "path":
				path = v
		# flush last
		if name and path:
			profiles.append((name, path))
	except Exception:
		return []
	result: List[str] = []
	for _disp, rel in profiles:
		p = pathlib.Path(rel)
		abs_path = p if p.is_absolute() else (base / rel)
		result.append(str(abs_path))
	return result

def list_profiles(browser: str) -> List[str]:
	"""
	Return a list of profile identifiers valid for yt-dlp for the given browser.
	Items are profile directory names (for Chromium: e.g., "Default", "Profile 1").
	For firefox, items are profile directory slugs (e.g., "xxxxxx.default-release").
	"""
	browser = (browser or "").strip().lower()
	if not browser:
		return []
	if browser == "firefox":
		return _firefox_profiles()
	base = _chromium_base(browser)
	if not base:
		return []
	if browser == "opera":
		return _opera_profiles(base)
	profiles = _chromium_profiles_from_local_state(base) or _chromium_profiles_by_scanning(base)
	return profiles

def _has_executable(candidates: List[str]) -> bool:
	for name in candidates:
		if shutil.which(name):
			return True
	return False

def _mac_app_exists(names: List[str]) -> bool:
	for n in names:
		for base in (pathlib.Path("/Applications"), _home() / "Applications"):
			if (base / f"{n}.app").exists():
				return True
	return False

def list_available_browsers() -> List[str]:
	"""
	Return lowercase browser ids that appear to be installed/present.
	Detection prefers user-data/profile presence and falls back to binary/app checks.
	"""
	ids = ["edge", "chrome", "firefox", "brave", "opera", "vivaldi"]
	available: List[str] = []
	for bid in ids:
		present = False
		# Profile base present?
		if bid == "firefox":
			# Presence of profiles.ini is a good indicator
			if _WINDOWS or _LINUX:
				base = (_app_data() / "Mozilla" / "Firefox") if _WINDOWS else (_home() / ".mozilla" / "firefox")
			else:
				base = _home() / "Library" / "Application Support" / "Firefox"
			present = (base / "profiles.ini").exists()
		else:
			base = _chromium_base(bid)
			present = bool(base and base.exists())
		# If not, check executables/app bundles
		if not present:
			if _WINDOWS:
				exe_map = {
					"edge": ["msedge.exe"],
					"chrome": ["chrome.exe"],
					"firefox": ["firefox.exe"],
					"brave": ["brave.exe"],
					"opera": ["opera.exe"],
					"vivaldi": ["vivaldi.exe"],
				}
				present = _has_executable(exe_map.get(bid, []))
			elif _MAC:
				app_map = {
					"edge": ["Microsoft Edge"],
					"chrome": ["Google Chrome"],
					"firefox": ["Firefox"],
					"brave": ["Brave Browser"],
					"opera": ["Opera"],
					"vivaldi": ["Vivaldi"],
				}
				present = _mac_app_exists(app_map.get(bid, []))
			elif _LINUX:
				bin_map = {
					"edge": ["microsoft-edge", "microsoft-edge-stable"],
					"chrome": ["google-chrome", "google-chrome-stable", "chromium"],
					"firefox": ["firefox"],
					"brave": ["brave-browser"],
					"opera": ["opera"],
					"vivaldi": ["vivaldi-stable", "vivaldi"],
				}
				present = _has_executable(bin_map.get(bid, []))
		if present:
			available.append(bid)
	return available
