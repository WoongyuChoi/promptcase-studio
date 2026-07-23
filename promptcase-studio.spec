# -*- mode: python ; coding: utf-8 -*-

import json
import os
import re
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)


project_root = Path(SPECPATH).resolve()
private_bundle_enabled = os.environ.get("PROMPTCASE_PRIVATE_BUNDLE", "").strip() == "1"
version_source = (project_root / "promptcase_studio" / "__init__.py").read_text(
    encoding="utf-8"
)
version_match = re.search(r'^__version__\s*=\s*"(\d+\.\d+\.\d+)"', version_source, re.M)
if not version_match:
    raise SystemExit("Cannot read Promptcase Studio version.")
app_version = version_match.group(1)
version_parts = tuple(int(part) for part in app_version.split(".")) + (0,)
version_resource = VSVersionInfo(
    ffi=FixedFileInfo(filevers=version_parts, prodvers=version_parts),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",
                    [
                        StringStruct("CompanyName", "Promptcase Studio"),
                        StringStruct("FileDescription", "Promptcase Studio"),
                        StringStruct("FileVersion", app_version),
                        StringStruct("InternalName", "PromptcaseStudio"),
                        StringStruct("OriginalFilename", "PromptcaseStudio.exe"),
                        StringStruct("ProductName", "Promptcase Studio"),
                        StringStruct("ProductVersion", app_version),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)

# The standard build contains public application resources only.
datas = [
    (str(project_root / "config" / "app.settings.json"), "config"),
    (str(project_root / "config" / "qwen.settings.json"), "config"),
    (str(project_root / "prompts"), "prompts"),
    (str(project_root / "schemas"), "schemas"),
    (str(project_root / "templates"), "templates"),
    (str(project_root / "favicon.ico"), "."),
]

if private_bundle_enabled:
    dotenv_path = project_root / ".env"
    if not dotenv_path.is_file():
        raise SystemExit("Private bundle requires the Git-ignored .env file.")

    dotenv_values = {}
    for raw_line in dotenv_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        dotenv_values[key.strip()] = value.strip().strip('"').strip("'")
    if not dotenv_values.get("GEMINI_API_KEY"):
        raise SystemExit("Private bundle requires GEMINI_API_KEY in .env.")

    qwen_path = project_root / "config" / "qwen.settings.json"
    local_settings_path = project_root / "config" / "app.settings.local.json"
    if local_settings_path.is_file():
        try:
            local_settings = json.loads(
                local_settings_path.read_text(encoding="utf-8-sig")
            )
            configured_path = (
                local_settings.get("providers", {})
                .get("secure", {})
                .get("settingsPath", "")
            )
            if configured_path:
                candidate = Path(os.path.expandvars(str(configured_path))).expanduser()
                qwen_path = candidate if candidate.is_absolute() else project_root / candidate
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
    if not qwen_path.is_file():
        raise SystemExit("Private bundle requires the selected Qwen settings file.")

    qwen_settings = json.loads(qwen_path.read_text(encoding="utf-8-sig"))
    selected_type = (
        qwen_settings.get("security", {}).get("auth", {}).get("selectedType", "openai")
    )
    provider_entries = qwen_settings.get("modelProviders", {}).get(selected_type, [])
    if not isinstance(provider_entries, list) or not provider_entries:
        raise SystemExit("Private Qwen settings do not contain a selected provider.")
    selected_provider = provider_entries[0]
    env_key = str(selected_provider.get("envKey", ""))
    embedded_qwen_key = str(qwen_settings.get("env", {}).get(env_key, ""))
    if env_key and not embedded_qwen_key and not dotenv_values.get(env_key):
        raise SystemExit("Private bundle cannot find the Qwen credential.")

    datas.extend(
        [
            (str(dotenv_path), "_private"),
            (str(qwen_path.resolve()), "_private"),
        ]
    )

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
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(project_root / "favicon.ico")],
    version=version_resource,
)
