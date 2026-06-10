# -*- mode: python ; coding: utf-8 -*-

import os

VLC_APP = "/Applications/VLC.app/Contents/MacOS"

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[
        (os.path.join(VLC_APP, "lib", "libvlc.dylib"), "lib"),
        (os.path.join(VLC_APP, "lib", "libvlccore.dylib"), "lib"),
    ],
    datas=[
        (os.path.join(VLC_APP, "plugins"), "plugins"),
    ],
    hiddenimports=["vlc"],
    hookspath=[],
    runtime_hooks=["hook-vlc.py"],
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

app = BUNDLE(
    coll,
    name="HomeTV.app",
    icon=None,
    bundle_identifier="com.hometv.app",
    info_plist={
        "CFBundleName": "HomeTV",
        "CFBundleDisplayName": "HomeTV",
        "CFBundleShortVersionString": "1.0.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "12.0",
    },
)
