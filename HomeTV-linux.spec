# -*- mode: python ; coding: utf-8 -*-
# Linux build spec. Must be built ON Ubuntu (PyInstaller does not cross-compile).
#
# This build relies on system VLC being installed on the target machine
# (`sudo apt install vlc`). python-vlc locates the system libvlc at runtime,
# so we do not bundle VLC's libraries or plugins here — that keeps the build
# small and avoids Linux's fragile VLC-plugin bundling.
#
# Build:   venv/bin/pyinstaller HomeTV-linux.spec
# Result:  dist/HomeTV/HomeTV   (an onedir bundle; run that executable)

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=["vlc"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HomeTV",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    target_arch=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="HomeTV",
)
