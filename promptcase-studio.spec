# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


project_root = Path(SPECPATH).resolve()

# Only public application resources are bundled. In particular, .env and any
# app.settings.local.json file must never be added to this list.
datas = [
    (str(project_root / "config" / "app.settings.json"), "config"),
    (str(project_root / "config" / "qwen.settings.json"), "config"),
    (str(project_root / "prompts"), "prompts"),
    (str(project_root / "schemas"), "schemas"),
    (str(project_root / "templates"), "templates"),
    (str(project_root / "favicon.ico"), "."),
]

a = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PromptcaseStudio",
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
    icon=[str(project_root / "favicon.ico")],
)
