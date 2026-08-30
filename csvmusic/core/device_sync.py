# tabs only
import ctypes
import datetime
import os
import pathlib
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
		devices.append(PortableDevice(root.name, root, kind, description))
	return devices


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
		if not resolved or any(not path.is_file() for _track, path in resolved):
			skipped.append(name)
			continue
		ready.append((playlist, resolved))
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


def _ipod_tool_paths() -> tuple[pathlib.Path, pathlib.Path]:
	base = pathlib.Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "Temp" / "csvmusic-libgpod"
	return base / "ipod-sync", base / "root" / "usr" / "lib" / "x86_64-linux-gnu"


def ipod_sync_available() -> tuple[bool, str]:
	if not sys.platform.startswith("win"):
		return False, "Classic-iPod database sync is currently available on Windows only."
	if not shutil.which("wsl.exe"):
		return False, "Windows Subsystem for Linux is required for experimental classic-iPod sync."
	helper, libraries = _ipod_tool_paths()
	if not helper.is_file() or not libraries.is_dir():
		return False, "The experimental classic-iPod helper is not installed on this PC."
	return True, ""


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
				_windows_to_wsl(path), tag("title", track.get("title")), tag("artist", track.get("artists")),
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
	command = " ".join((
		f"LD_LIBRARY_PATH='{_windows_to_wsl(libraries)}'",
		f"'{_windows_to_wsl(helper)}'",
		*(f"'{argument.replace(chr(39), '')}'" for argument in arguments),
	))
	result = subprocess.run(["wsl.exe", "-d", "Ubuntu", "--", "bash", "-lc", command], input=input_data, capture_output=True)
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
	output = _run_ipod_helper(["inspect", _windows_to_wsl(stage)])
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
	_run_ipod_helper(["delete", _windows_to_wsl(stage), playlist_name])
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
		_run_ipod_helper(["sync", _windows_to_wsl(stage), name], input_data=_manifest(ready, playlist))
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


def eject_device(device: PortableDevice) -> None:
	if sys.platform.startswith("win"):
		drive = str(device.root)
		script = (
			"$s=New-Object -ComObject Shell.Application;"
			f"$d=$s.Namespace(17).ParseName('{drive}');"
			"$v=$d.Verbs()|Where-Object{($_.Name-replace '&','').Trim()-eq 'Eject'}|Select-Object -First 1;"
			"if(-not $v){exit 2};$v.DoIt()"
		)
		result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script], capture_output=True)
		if result.returncode:
			raise RuntimeError("Windows could not safely eject this device.")
		for _attempt in range(20):
			if not device.root.exists():
				return
			time.sleep(0.25)
		if device.root.exists():
			raise RuntimeError("Windows accepted the eject request, but the device is still mounted.")
		return
	if sys.platform.startswith("darwin"):
		subprocess.run(["diskutil", "eject", str(device.root)], check=True, capture_output=True)
		return
	raise RuntimeError("Automatic eject is not yet available for this Linux mount. Use your desktop's eject control.")
