from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from promptcase_studio.template_catalog import UNIT_TEST_TEMPLATE
from promptcase_studio.gemini_models import AUTO_GEMINI_MODEL, normalize_gemini_model_id


APP_NAME = "Promptcase Studio"
APP_DATA_ENV = "PROMPTCASE_STUDIO_DATA_DIR"


@dataclass(frozen=True)
class RuntimePaths:
    """Read-only application resources and writable user data locations."""

    resource_root: Path
    data_root: Path
    frozen: bool

    @property
    def default_settings(self) -> Path:
        root = self.data_root if self.frozen else self.resource_root
        return root / "config" / "app.settings.json"

    @property
    def local_settings(self) -> Path:
        return self.data_root / "config" / "app.settings.local.json"

    @property
    def dotenv(self) -> Path:
        return self.data_root / ".env"


def _running_frozen() -> bool:
    return bool(getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None))


def _repository_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _user_data_root() -> Path:
    configured = os.environ.get(APP_DATA_ENV, "").strip()
    if configured:
        return Path(os.path.expandvars(configured)).expanduser().resolve()

    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    else:
        xdg_data_home = os.environ.get("XDG_DATA_HOME", "").strip()
        base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    return (base / APP_NAME).resolve()


def build_runtime_paths(
    *,
    frozen: bool | None = None,
    resource_root: str | Path | None = None,
    data_root: str | Path | None = None,
) -> RuntimePaths:
    """Build paths without touching the filesystem.

    Explicit roots make the frozen-layout behavior independently testable without
    starting a PyInstaller executable.
    """

    is_frozen = _running_frozen() if frozen is None else frozen
    if resource_root is not None:
        resources = Path(resource_root).resolve()
    elif is_frozen:
        resources = Path(str(getattr(sys, "_MEIPASS"))).resolve()
    else:
        resources = _repository_root()

    if is_frozen:
        writable = Path(data_root).resolve() if data_root is not None else _user_data_root()
    else:
        # Source runs intentionally keep the existing repository-relative behavior.
        writable = resources
    return RuntimePaths(resource_root=resources, data_root=writable, frozen=is_frozen)


RUNTIME_PATHS = build_runtime_paths()
RESOURCE_ROOT = RUNTIME_PATHS.resource_root
APP_DATA_ROOT = RUNTIME_PATHS.data_root

# Compatibility alias: direct consumers historically used PROJECT_ROOT for
# editable prompts and icons. In a packaged run these files are initialized in
# APP_DATA_ROOT; in source mode APP_DATA_ROOT is the repository root.
PROJECT_ROOT = APP_DATA_ROOT
DEFAULT_SETTINGS_PATH = RUNTIME_PATHS.default_settings
LOCAL_SETTINGS_PATH = RUNTIME_PATHS.local_settings
DOTENV_PATH = RUNTIME_PATHS.dotenv


_RUNTIME_DIRECTORIES = (
    "config",
    "prompts",
    "schemas",
    "templates",
    "runs",
    "outputs",
)
_MANAGED_DIRECTORIES = ("prompts", "schemas", "templates")
_MANAGED_FILES = (
    ("config/app.settings.json", "config/app.settings.json"),
    ("favicon.ico", "favicon.ico"),
)
_SEEDED_FILES = (("config/qwen.settings.json", "config/qwen.settings.json"),)
_RESOURCE_STATE = "config/.bundled-resources.json"


def _copy_file_if_missing(source: Path, destination: Path) -> None:
    if destination.exists() or not source.is_file():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _managed_resource_files(paths: RuntimePaths) -> list[tuple[str, Path, Path]]:
    rows: list[tuple[str, Path, Path]] = []
    for relative in _MANAGED_DIRECTORIES:
        source_directory = paths.resource_root / relative
        if not source_directory.is_dir():
            continue
        for source in sorted(path for path in source_directory.rglob("*") if path.is_file()):
            resource_relative = source.relative_to(paths.resource_root).as_posix()
            rows.append((resource_relative, source, paths.data_root / resource_relative))
    for source_relative, destination_relative in _MANAGED_FILES:
        source = paths.resource_root / source_relative
        if source.is_file():
            rows.append((destination_relative, source, paths.data_root / destination_relative))
    return rows


def _replace_from_bundle(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.bundle-update.tmp")
    shutil.copy2(source, temporary)
    for attempt in range(1, 6):
        try:
            temporary.replace(destination)
            return
        except PermissionError:
            if attempt >= 5:
                temporary.unlink(missing_ok=True)
                raise
            time.sleep(0.1 * attempt)


def _read_resource_state(path: Path) -> dict[str, str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    files = value.get("files", {}) if isinstance(value, dict) else {}
    return {
        str(key): str(file_hash)
        for key, file_hash in files.items()
        if isinstance(key, str) and isinstance(file_hash, str)
    }


def _write_resource_state(path: Path, files: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps({"schemaVersion": 1, "files": files}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _synchronize_managed_resources(paths: RuntimePaths) -> None:
    rows = _managed_resource_files(paths)
    state_path = paths.data_root / _RESOURCE_STATE
    previous = _read_resource_state(state_path)
    legacy_install = not state_path.exists() and any(destination.exists() for _, _, destination in rows)
    backup_root: Path | None = None
    next_state: dict[str, str] = {}

    for relative, source, destination in rows:
        bundled_hash = _file_hash(source)
        current_hash = _file_hash(destination) if destination.is_file() else ""
        previous_hash = previous.get(relative, "")
        replace = not destination.exists() or current_hash == previous_hash or legacy_install

        if legacy_install and current_hash and current_hash != bundled_hash:
            if backup_root is None:
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                backup_root = paths.data_root / "backups" / f"bundled-resources-{stamp}"
            backup = backup_root / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, backup)

        if replace and current_hash != bundled_hash:
            _replace_from_bundle(source, destination)
            current_hash = bundled_hash

        if current_hash == bundled_hash:
            next_state[relative] = bundled_hash
        elif previous_hash:
            # A user-edited copy remains active. Keep the last known baseline so
            # reverting that edit later can resume automatic upgrades.
            next_state[relative] = previous_hash

    _write_resource_state(state_path, next_state)


def _ensure_qwen_timeout(path: Path) -> None:
    if not path.is_file():
        return
    try:
        settings = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return
    changed = False
    providers = settings.get("modelProviders", {}) if isinstance(settings, dict) else {}
    if isinstance(providers, dict):
        for entries in providers.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                generation = entry.setdefault("generationConfig", {})
                if isinstance(generation, dict) and "timeout" not in generation:
                    generation["timeout"] = 300000
                    changed = True
    if changed:
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)


def initialize_runtime_environment(paths: RuntimePaths = RUNTIME_PATHS) -> RuntimePaths:
    """Initialize a writable packaged-app workspace on first launch.

    Managed defaults are upgraded only while their previous copy is unchanged.
    User edits are preserved, and a legacy install without resource state is
    backed up before its defaults are migrated. Qwen connection settings are
    seeded once and never replaced. Secrets are absent from every allowlist.
    """

    if not paths.frozen:
        return paths

    for directory in _RUNTIME_DIRECTORIES:
        (paths.data_root / directory).mkdir(parents=True, exist_ok=True)

    _synchronize_managed_resources(paths)
    for source_relative, destination_relative in _SEEDED_FILES:
        _copy_file_if_missing(
            paths.resource_root / source_relative,
            paths.data_root / destination_relative,
        )
        _ensure_qwen_timeout(paths.data_root / destination_relative)
    return paths


def resource_path(value: str | Path, paths: RuntimePaths = RUNTIME_PATHS) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (paths.resource_root / path).resolve()


def resolve_project_path(value: str | Path, paths: RuntimePaths = RUNTIME_PATHS) -> Path:
    text = os.path.expandvars(str(value))
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = paths.data_root / path
    return path.resolve()


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


def _migrate_legacy_template_path(settings: dict[str, Any]) -> dict[str, Any]:
    template_path = str(settings.get("templatePath", "")).replace("\\", "/")
    if template_path in UNIT_TEST_TEMPLATE.legacy_paths:
        settings["templatePath"] = UNIT_TEST_TEMPLATE.relative_path
    return settings


def _migrate_gemini_model(settings: dict[str, Any]) -> dict[str, Any]:
    providers = settings.get("providers", {})
    if not isinstance(providers, dict):
        return settings
    online = providers.get("online", {})
    if not isinstance(online, dict):
        return settings
    selected = normalize_gemini_model_id(online.get("model"))
    if online.get("fallbackOnDailyQuota") is True:
        selected = AUTO_GEMINI_MODEL
    online["model"] = selected
    online.pop("fallbackOnDailyQuota", None)
    return settings


def load_settings() -> dict[str, Any]:
    initialize_runtime_environment()
    settings = _read_json(DEFAULT_SETTINGS_PATH)
    settings = _deep_merge(settings, _read_json(LOCAL_SETTINGS_PATH))
    settings = _migrate_legacy_template_path(settings)
    return _migrate_gemini_model(settings)


def save_local_settings(settings: dict[str, Any]) -> None:
    initialize_runtime_environment()
    LOCAL_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = LOCAL_SETTINGS_PATH.with_name(LOCAL_SETTINGS_PATH.name + ".tmp")
    temp_path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(LOCAL_SETTINGS_PATH)


def read_dotenv(path: Path | None = None) -> dict[str, str]:
    dotenv_path = DOTENV_PATH if path is None else path
    values: dict[str, str] = {}
    if not dotenv_path.exists():
        return values
    for raw_line in dotenv_path.read_text(encoding="utf-8-sig").splitlines():
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
    initialize_runtime_environment()
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
    DOTENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOTENV_PATH.write_text("\n".join(lines), encoding="utf-8")
