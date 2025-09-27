# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import sys, pathlib

root_dir = pathlib.Path(__file__).resolve().parent

datas = []
binaries = []
hiddenimports = []

# Bundle resource directories so runtime helpers can locate icons/fonts.
datas.append((str(root_dir / 'resources'), 'resources'))
datas.append((str(root_dir / 'licenses'), 'licenses'))

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
    ['spotify2media/app.py'],
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
splash = Splash(
    str(root_dir / 'resources' / 'splash.png'),
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,
    text_size=12,
    minify_script=True,
    always_on_top=True,
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    splash,
    splash.binaries,
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
