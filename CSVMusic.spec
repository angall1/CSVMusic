# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import sys, pathlib

try:
	root_dir = pathlib.Path(__file__).resolve().parent
except NameError:
	root_dir = pathlib.Path.cwd()

datas: list[tuple[str, str]] = []
binaries: list[tuple[str, str]] = []
hiddenimports = []


def add_dir(path_obj: pathlib.Path, target: str, container: list[tuple[str, str]]) -> None:
	if path_obj.exists():
		container.append((str(path_obj), target))


add_dir(root_dir / "resources", "resources", datas)
add_dir(root_dir / "licenses", "licenses", datas)

ffmpeg_map = {
	"win": (root_dir / "resources" / "ffmpeg" / "windows" / "ffmpeg.exe", "ffmpeg/windows"),
	"darwin": (root_dir / "resources" / "ffmpeg" / "darwin" / "ffmpeg", "ffmpeg/darwin"),
	"linux": (root_dir / "resources" / "ffmpeg" / "linux" / "ffmpeg", "ffmpeg/linux"),
}
for key, (src, dest) in ffmpeg_map.items():
	if sys.platform.startswith(key) and src.exists():
		binaries.append((str(src), dest))
		break

for pkg in ("PySide6", "shiboken6", "yt_dlp", "ytmusicapi", "mutagen"):
	tmp = collect_all(pkg)
	datas += tmp[0]
	binaries += tmp[1]
	hiddenimports += tmp[2]

pathex = [(root_dir).as_posix()]

script_path = (root_dir / "csvmusic" / "app.py").resolve()
script = script_path.as_posix()

a = Analysis(
    [script],
    pathex=pathex,
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', '_tkinter', 'Tkinter'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

icon_path = (root_dir / "resources" / "app.ico").resolve()
icon_arg = icon_path.as_posix() if icon_path.exists() else None

exe_kwargs = {}
if icon_arg:
	exe_kwargs["icon"] = icon_arg

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='CSVMusic',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    **exe_kwargs,
)
