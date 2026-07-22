from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS_PATH = PROJECT_ROOT / "config" / "app.settings.json"
LOCAL_SETTINGS_PATH = PROJECT_ROOT / "config" / "app.settings.local.json"
DOTENV_PATH = PROJECT_ROOT / ".env"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"설정 파일의 최상위 값은 객체여야 합니다: {path}")
    return value


def load_settings() -> dict[str, Any]:
    settings = _read_json(DEFAULT_SETTINGS_PATH)
    settings = _deep_merge(settings, _read_json(LOCAL_SETTINGS_PATH))
    return settings


def save_local_settings(settings: dict[str, Any]) -> None:
    LOCAL_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = LOCAL_SETTINGS_PATH.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(LOCAL_SETTINGS_PATH)


def resolve_project_path(value: str | Path) -> Path:
    text = os.path.expandvars(str(value))
    path = Path(text)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def read_dotenv(path: Path = DOTENV_PATH) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def get_secret(name: str) -> str:
    return os.environ.get(name, "") or read_dotenv().get(name, "")


def save_dotenv_secret(name: str, value: str) -> None:
    existing = read_dotenv()
    if value:
        existing[name] = value
    elif name in existing:
        del existing[name]
    lines = [
        "# Promptcase Studio local secrets. This file is ignored by Git.",
        *(f"{key}={val}" for key, val in sorted(existing.items())),
        "",
    ]
    DOTENV_PATH.write_text("\n".join(lines), encoding="utf-8")

