# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import sys, pathlib

try:
    root_dir = pathlib.Path(__file__).resolve().parent
except NameError:
    root_dir = pathlib.Path.cwd()

def _posix(path: pathlib.Path) -> str:
    return path.resolve().as_posix()

def add_dir(path_obj: pathlib.Path, target: str, container: list[tuple[str, str]]) -> None:
    if path_obj.exists():
        container.append((_posix(path_obj), target))

datas: list[tuple[str, str]] = []
binaries: list[tuple[str, str]] = []
hiddenimports = []

add_dir(root_dir / "resources", "resources", datas)
add_dir(root_dir / "licenses", "licenses", datas)

ffmpeg_map = {
    "win": (root_dir / "resources" / "ffmpeg" / "windows" / "ffmpeg.exe", "ffmpeg/windows"),
    "darwin": (root_dir / "resources" / "ffmpeg" / "darwin" / "ffmpeg", "ffmpeg/darwin"),
    "linux": (root_dir / "resources" / "ffmpeg" / "linux" / "ffmpeg", "ffmpeg/linux"),
}
for key, (src, dest) in ffmpeg_map.items():
    if sys.platform.startswith(key) and src.exists():
        binaries.append((_posix(src), dest))
        break

for pkg in ("PySide6", "shiboken6", "yt_dlp", "ytmusicapi", "mutagen"):
    tmp_datas, tmp_bins, tmp_hidden = collect_all(pkg)
    for entry, target in tmp_datas:
        datas.append((_posix(pathlib.Path(entry)), target))
    for entry, target in tmp_bins:
        binaries.append((_posix(pathlib.Path(entry)), target))
    hiddenimports += tmp_hidden

pathex = [_posix(root_dir)]

script = _posix(root_dir / "csvmusic" / "app.py")

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

icon_path = root_dir / "resources" / "app.ico"
exe_kwargs = {}
if icon_path.exists():
    exe_kwargs["icon"] = _posix(icon_path)

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
