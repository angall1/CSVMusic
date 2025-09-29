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
tmp_ret = collect_all('pandas')
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

splash_args = []
if sys.platform.startswith('win'):
	for splash_name in ('splash_small.png', 'splash.png'):
		splash_path = root_dir / 'resources' / splash_name
		if splash_path.exists():
			splash = Splash(
				str(splash_path),
				binaries=a.binaries,
				datas=a.datas,
				text_pos=None,
				text_size=12,
				minify_script=True,
				always_on_top=True,
				max_img_size=(768, 768),
			)
			splash_args = [splash, splash.binaries]
			break

icon_path = None
for icon_name in ('app.ico', 'icon.ico'):
	candidate = root_dir / 'resources' / icon_name
	if candidate.exists():
		icon_path = str(candidate)
		break

exe = EXE(
	pyz,
	a.scripts,
	a.binaries,
	a.datas,
	*splash_args,
	[],
	name='CSVMusic',
	debug=False,
	bootloader_ignore_signals=False,
	strip=False,
	upx=True,
	upx_exclude=[],
	runtime_tmpdir=None,
	console=False,
	icon=icon_path,
	disable_windowed_traceback=False,
	argv_emulation=False,
	target_arch=None,
	codesign_identity=None,
	entitlements_file=None,
)
