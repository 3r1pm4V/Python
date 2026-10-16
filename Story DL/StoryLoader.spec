# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec cho Story Loader.

Build:  build_exe.bat   (hoac: pyinstaller StoryLoader.spec --noconfirm --clean)
Cau hinh qua bien moi truong: APP_NAME, ONEFILE (1/0), WINDOWED (1/0), ICON.
"""
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

APP_NAME = os.environ.get("APP_NAME", "StoryLoader")
ONEFILE = os.environ.get("ONEFILE", "1") == "1"
WINDOWED = os.environ.get("WINDOWED", "1") == "1"
ICON = os.environ.get("ICON") or None
if ICON and not os.path.isfile(ICON):
    print(f"[spec] Bo qua ICON khong ton tai: {ICON}")
    ICON = None

datas, binaries, hiddenimports = [], [], []

# Cac goi co data/binary/native ext can gom day du
for pkg in ("customtkinter", "selenium", "curl_cffi", "undetected_chromedriver", "ebooklib", "certifi"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# keyring chon backend luc chay (Windows Credential Locker) -> can liet ke ro
hiddenimports += collect_submodules("keyring")
hiddenimports += ["win32ctypes.pywin32.pywintypes", "win32ctypes.pywin32.win32cred", "lxml.etree", "lxml._elementpath"]

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "ruff", "matplotlib", "numpy", "pandas", "scipy", "PIL.ImageQt"],
    noarchive=False,
)
pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name=APP_NAME, debug=False, strip=False, upx=False,
        console=not WINDOWED, icon=ICON,
    )
else:
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True, name=APP_NAME, debug=False, strip=False, upx=False,
        console=not WINDOWED, icon=ICON,
    )
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=APP_NAME)
