# tabs only
import ctypes
from ctypes import wintypes
import datetime
import os
import pathlib
import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Callable

from mutagen import File as MutagenFile

from csvmusic.core.downloader import sanitize_name
from csvmusic.core.log import log
from csvmusic.core.library import library_track_path
from csvmusic.core.paths import resource_base
from csvmusic.core.settings import settings_path


ProgressCallback = Callable[[int, int, str], None]
StatusCallback = Callable[[str], None]


@dataclass(frozen=True)
class PortableDevice:
	name: str
	root: pathlib.Path
	kind: str
	description: str

	@property
	def key(self) -> str:
		return f"{self.kind}:{self.root}"


@dataclass(frozen=True)
class SyncResult:
	playlists: int
	tracks_copied: int
	tracks_reused: int
	playlists_skipped: tuple[str, ...]


@dataclass(frozen=True)
class DevicePlaylist:
	name: str
	track_count: int


def _device_kind(root: pathlib.Path) -> tuple[str, str]:
	if (root / "iPod_Control" / "iTunes" / "iTunesDB").is_file():
		return "ipod_classic", "Classic iPod database device (experimental)"
	return "mass_storage", "USB storage player (folders + M3U8 playlists)"


def _windows_devices() -> list[PortableDevice]:
	devices: list[PortableDevice] = []
	get_drive_type = ctypes.windll.kernel32.GetDriveTypeW
	get_volume = ctypes.windll.kernel32.GetVolumeInformationW
	for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
		root_text = f"{letter}:\\"
		if get_drive_type(root_text) != 2:
			continue
		root = pathlib.Path(root_text)
		if not root.exists():
			continue
		label_buffer = ctypes.create_unicode_buffer(261)
		label = ""
		if get_volume(root_text, label_buffer, len(label_buffer), None, None, None, None, 0):
			label = label_buffer.value.strip()
		kind, description = _device_kind(root)
		name = label or f"Removable Drive {letter}:"
		devices.append(PortableDevice(f"{name} ({letter}:)", root, kind, description))
	return devices


def _unix_devices() -> list[PortableDevice]:
	roots: list[pathlib.Path] = []
	if sys.platform.startswith("darwin"):
		bases = [pathlib.Path("/Volumes")]
	else:
		bases = [pathlib.Path("/media") / os.environ.get("USER", ""), pathlib.Path("/run/media") / os.environ.get("USER", "")]
	for base in bases:
		if base.is_dir():
			roots.extend(path for path in base.iterdir() if path.is_dir())
	devices = []
	for root in roots:
		kind, description = _device_kind(root)
		if sys.platform.startswith("darwin") and kind != "ipod_classic" and not _mac_volume_is_portable(root):
			continue
		devices.append(PortableDevice(root.name, root, kind, description))
	return devices


def _mac_volume_is_portable(root: pathlib.Path) -> bool:
	try:
		result = subprocess.run(["diskutil", "info", "-plist", str(root)], capture_output=True, timeout=3)
		if result.returncode:
			return False
		info = plistlib.loads(result.stdout)
		return bool(info.get("Ejectable") or info.get("RemovableMedia") or info.get("Internal") is False)
	except Exception:
		return False


def discover_devices() -> list[PortableDevice]:
	devices = _windows_devices() if sys.platform.startswith("win") else _unix_devices()
	return sorted(devices, key=lambda device: (device.kind != "ipod_classic", device.name.casefold()))


def _ready_playlists(library: dict) -> tuple[list[tuple[dict, list[tuple[dict, pathlib.Path]]]], list[str]]:
	root = pathlib.Path(library.get("output_dir") or "")
	fmt = str(library.get("format") or "mp3")
	ready: list[tuple[dict, list[tuple[dict, pathlib.Path]]]] = []
	skipped: list[str] = []
	for playlist in library.get("playlists", []):
		name = str(playlist.get("name") or "Playlist")
		tracks = [track for track in playlist.get("tracks", []) if track.get("enabled", True)]
		resolved = [(track, library_track_path(track, root, fmt)) for track in tracks]
		# Never sync an existing-but-stale file while an alternative or audio
		# change is still queued. The playlist becomes ready after Download
		# successfully clears force_redownload.
		if not resolved or any(track.get("force_redownload") or not path.is_file() for track, path in resolved):
			skipped.append(name)
			continue
		ready.append((playlist, resolved))
	ready.sort(key=lambda item: str(item[0].get("name") or "Playlist").casefold())
	skipped.sort(key=str.casefold)
	return ready, skipped


def _copy_verified(source: pathlib.Path, destination: pathlib.Path) -> bool:
	destination.parent.mkdir(parents=True, exist_ok=True)
	if destination.is_file() and destination.stat().st_size == source.stat().st_size:
		return False
	shutil.copy2(source, destination)
	if destination.stat().st_size != source.stat().st_size:
		raise OSError(f"Copied file did not verify: {destination}")
	return True


def sync_mass_storage(device: PortableDevice, library: dict, progress: ProgressCallback) -> SyncResult:
	ready, skipped = _ready_playlists(library)
	total = sum(len(tracks) for _playlist, tracks in ready)
	completed = 0
	copied = 0
	reused = 0
	managed_root = device.root / "CSVMusic"
	playlists_root = managed_root / "Playlists"
	playlists_root.mkdir(parents=True, exist_ok=True)
	for playlist, tracks in ready:
		name = str(playlist.get("name") or "Playlist")
		folder_name = sanitize_name(name) or "Playlist"
		folder = managed_root / folder_name
		entries: list[str] = ["#EXTM3U", f"#PLAYLIST:{name}"]
		for track, source in tracks:
			destination = folder / source.name
			if _copy_verified(source, destination):
				copied += 1
			else:
				reused += 1
			entries.append(f"../{folder_name}/{source.name}")
			completed += 1
			progress(completed, total, f"{name}: {track.get('artists', '')} - {track.get('title', '')}")
		playlist_path = playlists_root / f"{folder_name}.m3u8"
		playlist_path.write_text("\n".join(entries) + "\n", encoding="utf-8")
	return SyncResult(len(ready), copied, reused, tuple(skipped))


def _windows_to_wsl(path: pathlib.Path) -> str:
	drive, tail = os.path.splitdrive(str(path.resolve()))
	if not drive:
		return str(path.resolve()).replace("\\", "/")
	posix_tail = tail.lstrip("\\/").replace("\\", "/")
	return f"/mnt/{drive[0].lower()}/{posix_tail}"


def _ipod_platform_bundle() -> str:
	machine = platform.machine().lower()
	architecture = "arm64" if machine in {"arm64", "aarch64"} else "x86_64"
	if sys.platform.startswith("win"):
		return "linux-x86_64"
	if sys.platform.startswith("darwin"):
		return f"darwin-{architecture}"
	return f"linux-{architecture}"


def _ipod_tool_paths() -> tuple[pathlib.Path, pathlib.Path]:
	bundled = resource_base() / "ipod" / _ipod_platform_bundle()
	bundled_helper = bundled / "bin" / "ipod-sync"
	bundled_libraries = bundled / "lib"
	if bundled_helper.is_file() and bundled_libraries.is_dir():
		return bundled_helper, bundled_libraries
	if sys.platform.startswith("win"):
		base = pathlib.Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "Temp" / "csvmusic-libgpod"
		return base / "ipod-sync", base / "root" / "usr" / "lib" / "x86_64-linux-gnu"
	return bundled_helper, bundled_libraries


def ipod_sync_available() -> tuple[bool, str]:
	if sys.platform.startswith("win") and not shutil.which("wsl.exe"):
		return False, "Windows Subsystem for Linux is required for experimental classic-iPod sync."
	helper, libraries = _ipod_tool_paths()
	if not helper.is_file() or not libraries.is_dir():
		return False, f"This installation does not include the {_ipod_platform_bundle()} classic-iPod helper. Reinstall CSVMusic."
	return True, ""


def _ipod_helper_path(path: pathlib.Path) -> str:
	return _windows_to_wsl(path) if sys.platform.startswith("win") else str(path.resolve())


def _manifest(playlists: list[tuple[dict, list[tuple[dict, pathlib.Path]]]], selected: dict) -> bytes:
	rows: list[str] = []
	for playlist, tracks in playlists:
		if playlist is not selected:
			continue
		for index, (track, path) in enumerate(tracks, start=1):
			audio = MutagenFile(path, easy=True)
			info = getattr(audio, "info", None)
			def tag(name: str, fallback: object) -> str:
				value = audio.get(name) if audio else None
				if isinstance(value, list):
					value = value[0] if value else fallback
				return str(value or fallback or "").replace("\t", " ").replace("\r", " ").replace("\n", " ")
			fields = (
				_ipod_helper_path(path), tag("title", track.get("title")), tag("artist", track.get("artists")),
				tag("album", track.get("album")), index, round(float(getattr(info, "length", 0)) * 1000),
				path.stat().st_size, round(float(getattr(info, "bitrate", 0)) / 1000), int(getattr(info, "sample_rate", 0)),
				_ipod_track_identity(track),
			)
			rows.append("\t".join(str(value) for value in fields))
	return (("\n".join(rows) + "\n") if rows else "").encode("utf-8")


def _ipod_track_identity(track: dict) -> str:
	preferred = str(track.get("preferred_video_id") or "").strip()
	source_video = str(track.get("youtube_video_id") or "").strip()
	selected = bool(track.get("preferred_selection_locked")) or bool(preferred and preferred != source_video)
	identity = preferred or track.get("downloaded_video_id") or source_video or track.get("sp_id")
	if not identity:
		identity = f"text:{track.get('artists', '')}|{track.get('title', '')}"
	return f"{'selected' if selected else 'auto'}:{identity}"


def _run_ipod_helper(arguments: list[str], *, input_data: bytes | None = None) -> str:
	helper, libraries = _ipod_tool_paths()
	if sys.platform.startswith("win"):
		command = " ".join((
			f"LD_LIBRARY_PATH='{_windows_to_wsl(libraries)}'",
			f"'{_windows_to_wsl(helper)}'",
			*(f"'{argument.replace(chr(39), '')}'" for argument in arguments),
		))
		invocation = ["wsl.exe", "-d", "Ubuntu", "--", "bash", "-lc", command]
		environment = None
	else:
		invocation = [str(helper), *arguments]
		environment = os.environ.copy()
		variable = "DYLD_LIBRARY_PATH" if sys.platform.startswith("darwin") else "LD_LIBRARY_PATH"
		environment[variable] = os.pathsep.join(filter(None, (str(libraries), environment.get(variable, ""))))
	result = subprocess.run(invocation, input=input_data, capture_output=True, env=environment)
	if result.returncode:
		raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip() or "The iPod helper failed.")
	return result.stdout.decode("utf-8", errors="replace")


def _stage_ipod_control(device: PortableDevice, status: StatusCallback | None = None) -> pathlib.Path:
	stage = pathlib.Path(tempfile.mkdtemp(prefix="csvmusic-ipod-stage-"))
	control = stage / "iPod_Control"
	if status:
		status("Copying the iPod database to a safe staging area...")
	shutil.copytree(device.root / "iPod_Control" / "iTunes", control / "iTunes")
	device_folder = device.root / "iPod_Control" / "Device"
	if device_folder.is_dir():
		shutil.copytree(device_folder, control / "Device")
	return stage


def list_device_playlists(device: PortableDevice, status: StatusCallback | None = None) -> list[DevicePlaylist]:
	if device.kind == "mass_storage":
		if status:
			status("Reading CSVMusic playlists from the player...")
		result: list[DevicePlaylist] = []
		for path in sorted((device.root / "CSVMusic" / "Playlists").glob("*.m3u8")):
			lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
			name_line = next((line for line in lines if line.startswith("#PLAYLIST:")), "")
			name = name_line.removeprefix("#PLAYLIST:").strip() or path.stem
			count = sum(1 for line in lines if line.strip() and not line.startswith("#"))
			result.append(DevicePlaylist(name, count))
		return result
	available, reason = ipod_sync_available()
	if not available:
		raise RuntimeError(reason)
	stage = _stage_ipod_control(device, status)
	if status:
		status("Parsing the staged iPod database and counting playlist songs...")
	output = _run_ipod_helper(["inspect", _ipod_helper_path(stage)])
	playlists: list[DevicePlaylist] = []
	for line in output.splitlines():
		parts = line.split("\t")
		if len(parts) == 3 and parts[0] == "PLAYLIST":
			playlists.append(DevicePlaylist(parts[1], int(parts[2])))
	result = playlists[1:] if playlists else []
	if status:
		status(f"Finished reading {len(result)} iPod playlists.")
	return result


def delete_device_playlist(device: PortableDevice, playlist_name: str) -> None:
	if device.kind == "mass_storage":
		playlist_path = device.root / "CSVMusic" / "Playlists" / f"{sanitize_name(playlist_name) or 'Playlist'}.m3u8"
		if not playlist_path.is_file():
			raise FileNotFoundError(f"Playlist not found on device: {playlist_name}")
		playlist_path.unlink()
		return
	stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
	backup = settings_path().parent / "ipod-backups" / stamp
	backup.mkdir(parents=True, exist_ok=False)
	shutil.copytree(device.root / "iPod_Control" / "iTunes", backup / "iTunes")
	stage = _stage_ipod_control(device)
	_run_ipod_helper(["delete", _ipod_helper_path(stage), playlist_name])
	database_source = stage / "iPod_Control" / "iTunes" / "iTunesDB"
	database_destination = device.root / "iPod_Control" / "iTunes" / "iTunesDB"
	shutil.copy2(database_source, database_destination)
	if database_destination.read_bytes() != database_source.read_bytes():
		raise OSError("The updated iPod database did not verify after deleting the playlist.")
	log(f"iPod playlist deleted device={device.root} playlist={playlist_name} backup={backup}")


def sync_ipod_classic(device: PortableDevice, library: dict, progress: ProgressCallback) -> SyncResult:
	available, reason = ipod_sync_available()
	if not available:
		raise RuntimeError(reason)
	ready, skipped = _ready_playlists(library)
	if not ready:
		raise ValueError("No fully downloaded playlists are ready to sync.")
	stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
	backup = settings_path().parent / "ipod-backups" / stamp
	backup.mkdir(parents=True, exist_ok=False)
	shutil.copytree(device.root / "iPod_Control" / "iTunes", backup / "iTunes")
	device_folder = device.root / "iPod_Control" / "Device"
	if device_folder.is_dir():
		shutil.copytree(device_folder, backup / "Device")
	stage = _stage_ipod_control(device)
	control = stage / "iPod_Control"
	artwork = device.root / "iPod_Control" / "Artwork"
	if artwork.is_dir():
		shutil.copytree(artwork, control / "Artwork")
	stage_music = control / "Music"
	stage_music.mkdir(parents=True)
	device_music = device.root / "iPod_Control" / "Music"
	for folder in device_music.glob("F*"):
		stage_folder = stage_music / folder.name
		stage_folder.mkdir()
		for existing in folder.iterdir():
			if existing.is_file():
				(stage_folder / existing.name).touch()
	initial_media = {path.relative_to(stage) for path in stage_music.rglob("*") if path.is_file()}
	total = sum(len(tracks) for _playlist, tracks in ready)
	done = 0
	for playlist, tracks in ready:
		name = str(playlist.get("name") or "Playlist")
		progress(done, total, f"Preparing {name}...")
		_run_ipod_helper(["sync", _ipod_helper_path(stage), name], input_data=_manifest(ready, playlist))
		done += len(tracks)
		progress(done, total, f"Prepared {name}")
	new_files = [path for path in stage_music.rglob("*") if path.is_file() and path.stat().st_size > 0]
	remaining_media = {path.relative_to(stage) for path in stage_music.rglob("*") if path.is_file()}
	removed_media = sorted(initial_media - remaining_media, key=str)
	additions = [source for source in new_files if not (device.root / source.relative_to(stage)).exists()]
	replacements = [source for source in new_files if (device.root / source.relative_to(stage)).exists()]
	for index, source in enumerate(additions, start=1):
		relative = source.relative_to(stage)
		destination = device.root / relative
		_copy_verified(source, destination)
		progress(total + index, total + len(new_files), f"Copying new iPod media {index}/{len(additions)}")
	database_source = control / "iTunes" / "iTunesDB"
	database_destination = device.root / "iPod_Control" / "iTunes" / "iTunesDB"
	shutil.copy2(database_source, database_destination)
	if database_destination.read_bytes() != database_source.read_bytes():
		raise OSError("The updated iPod database did not verify after copying.")
	for index, source in enumerate(replacements, start=1):
		relative = source.relative_to(stage)
		destination = device.root / relative
		media_backup = backup / "Media" / relative
		media_backup.parent.mkdir(parents=True, exist_ok=True)
		shutil.copy2(destination, media_backup)
		shutil.copy2(source, destination)
		if destination.stat().st_size != source.stat().st_size:
			raise OSError(f"Replacement iPod media did not verify: {destination}")
		progress(
			total + len(additions) + index, total + len(new_files),
			f"Applying selected alternative {index}/{len(replacements)}",
		)
	for relative in removed_media:
		destination = device.root / relative
		if not destination.is_file():
			continue
		media_backup = backup / "Media" / relative
		media_backup.parent.mkdir(parents=True, exist_ok=True)
		if not media_backup.exists():
			shutil.copy2(destination, media_backup)
		destination.unlink()
	log(
		f"iPod sync complete device={device.root} playlists={len(ready)} new_tracks={len(new_files)} "
		f"obsolete_tracks_removed={len(removed_media)} backup={backup}"
	)
	return SyncResult(len(ready), len(new_files), total - len(new_files), tuple(skipped))


def sync_device(device: PortableDevice, library: dict, progress: ProgressCallback) -> SyncResult:
	if device.kind == "ipod_classic":
		return sync_ipod_classic(device, library, progress)
	return sync_mass_storage(device, library, progress)


def _windows_volume_is_ready(drive: str) -> bool:
	try:
		return bool(ctypes.windll.kernel32.GetVolumeInformationW(
			f"{drive}\\", None, 0, None, None, None, None, 0,
		))
	except Exception:
		return pathlib.Path(f"{drive}\\").exists()


def _windows_eject_volume(drive: str) -> None:
	kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
	kernel32.CreateFileW.argtypes = [
		wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
		wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
	]
	kernel32.CreateFileW.restype = wintypes.HANDLE
	kernel32.DeviceIoControl.argtypes = [
		wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
		ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
	]
	kernel32.DeviceIoControl.restype = wintypes.BOOL
	kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
	kernel32.CloseHandle.restype = wintypes.BOOL
	invalid_handle = wintypes.HANDLE(-1).value
	handle = kernel32.CreateFileW(
		f"\\\\.\\{drive}",
		0x80000000 | 0x40000000,  # GENERIC_READ | GENERIC_WRITE
		0x00000001 | 0x00000002,  # FILE_SHARE_READ | FILE_SHARE_WRITE
		None, 3, 0, None,  # OPEN_EXISTING
	)
	if handle == invalid_handle:
		raise ctypes.WinError(ctypes.get_last_error())
	returned = wintypes.DWORD(0)
	try:
		locked = False
		for _attempt in range(12):
			if kernel32.DeviceIoControl(handle, 0x00090018, None, 0, None, 0, ctypes.byref(returned), None):  # FSCTL_LOCK_VOLUME
				locked = True
				break
			time.sleep(0.25)
		if not locked:
			raise ctypes.WinError(ctypes.get_last_error())
		if not kernel32.DeviceIoControl(handle, 0x00090020, None, 0, None, 0, ctypes.byref(returned), None):  # FSCTL_DISMOUNT_VOLUME
			raise ctypes.WinError(ctypes.get_last_error())
		if not kernel32.DeviceIoControl(handle, 0x002D4808, None, 0, None, 0, ctypes.byref(returned), None):  # IOCTL_STORAGE_EJECT_MEDIA
			raise ctypes.WinError(ctypes.get_last_error())
	finally:
		kernel32.CloseHandle(handle)


def eject_device(device: PortableDevice) -> None:
	if sys.platform.startswith("win"):
		drive = str(device.root.drive or device.root).rstrip("\\/")
		direct_error: Exception | None = None
		try:
			_windows_eject_volume(drive)
		except Exception as exc:
			direct_error = exc
			script = (
				"$s=New-Object -ComObject Shell.Application;"
				f"$d=$s.Namespace(17).ParseName('{drive}');"
				"$v=$d.Verbs()|Where-Object{($_.Name-replace '&','').Trim()-eq 'Eject'}|Select-Object -First 1;"
				"if(-not $v){exit 2};$v.DoIt()"
			)
			result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script], capture_output=True)
			if result.returncode:
				raise RuntimeError(f"Windows could not safely eject this device. {direct_error}") from direct_error
		for _attempt in range(60):
			if not _windows_volume_is_ready(drive):
				return
			time.sleep(0.25)
		detail = f" The volume lock failed with: {direct_error}" if direct_error else ""
		raise RuntimeError(f"Windows could not release {drive}; another program may still be using it.{detail}")
	if sys.platform.startswith("darwin"):
		subprocess.run(["diskutil", "eject", str(device.root)], check=True, capture_output=True)
		return
	findmnt = subprocess.run(
		["findmnt", "--noheadings", "--output", "SOURCE", "--target", str(device.root)],
		capture_output=True, text=True, encoding="utf-8", errors="replace",
	) if shutil.which("findmnt") else None
	source = findmnt.stdout.strip().splitlines()[0] if findmnt and findmnt.returncode == 0 and findmnt.stdout.strip() else ""
	if source and shutil.which("udisksctl"):
		unmount = subprocess.run(["udisksctl", "unmount", "--block-device", source], capture_output=True)
		if unmount.returncode:
			raise RuntimeError(unmount.stderr.decode("utf-8", errors="replace").strip() or "Linux could not unmount the player.")
		parent = subprocess.run(
			["lsblk", "--noheadings", "--output", "PKNAME", source], capture_output=True,
			text=True, encoding="utf-8", errors="replace",
		).stdout.strip()
		power_target = f"/dev/{parent}" if parent else source
		power_off = subprocess.run(["udisksctl", "power-off", "--block-device", power_target], capture_output=True)
		if power_off.returncode:
			raise RuntimeError(power_off.stderr.decode("utf-8", errors="replace").strip() or "Linux unmounted the player but could not power it off.")
		return
	if shutil.which("gio"):
		subprocess.run(["gio", "mount", "--unmount", str(device.root)], check=True, capture_output=True)
		return
	raise RuntimeError("No supported Linux eject utility was found (udisksctl or gio).")
