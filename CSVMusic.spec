# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import sys, pathlib

# PyInstaller 6.16+ executes spec files without __file__ defined when run via
# python -m PyInstaller, so fall back to the CWD to keep root resolution stable.
try:
	root_dir = pathlib.Path(__file__).resolve().parent
except NameError:
	root_dir = pathlib.Path.cwd()

datas = []
binaries = []
hiddenimports = []


def add_dir(path_obj, target, container):
	"""Append a data directory if it exists to avoid PyInstaller aborts."""
	if path_obj.exists():
		container.append((str(path_obj), target))

# Bundle resource directories so runtime helpers can locate icons/fonts.
add_dir(root_dir / 'resources', 'resources', datas)
add_dir(root_dir / 'licenses', 'licenses', datas)

# Platform-specific FFmpeg binary packaged alongside the app.
ffmpeg_map = {
	'win': (root_dir / 'resources' / 'ffmpeg' / 'windows' / 'ffmpeg.exe', 'ffmpeg/windows'),
	'darwin': (root_dir / 'resources' / 'ffmpeg' / 'darwin' / 'ffmpeg', 'ffmpeg/darwin'),
	'linux': (root_dir / 'resources' / 'ffmpeg' / 'linux' / 'ffmpeg', 'ffmpeg/linux'),
}
for key, (src, dest) in ffmpeg_map.items():
	if sys.platform.startswith(key) and src.exists():
		binaries.append((str(src), dest))
		break

# Collect third-party packages we depend on at runtime.
tmp_ret = collect_all('PySide6')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('shiboken6')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('yt_dlp')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('ytmusicapi')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('mutagen')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


pathex = [str(root_dir)]

a = Analysis(
    ['csvmusic/app.py'],
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

exe = EXE(
	pyz,
	a.scripts,
	a.binaries,
	a.zipfiles,
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
)

COLLECT(
	exe,
	a.binaries,
	a.zipfiles,
	a.datas,
	strip=False,
	upx=True,
	upx_exclude=[],
	name='CSVMusic',
)
