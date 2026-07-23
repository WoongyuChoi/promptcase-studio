from __future__ import annotations

import codecs
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable

from promptcase_studio.models import ChangeItem, ContextFile, LogCallback, ScanBundle


EXCLUDED_DIRECTORIES = {
    ".git",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "node_modules",
    "build",
    "dist",
    "target",
    "coverage",
    "outputs",
    "runs",
    "qwen-loop-data",
    "__pycache__",
}

ALLOWED_SUFFIXES = {
    ".java",
    ".kt",
    ".py",
    ".js",
    ".mjs",
    ".cjs",
    ".jsx",
    ".ts",
    ".mts",
    ".cts",
    ".tsx",
    ".vue",
    ".sql",
    ".xml",
    ".yml",
    ".yaml",
    ".json",
    ".properties",
    ".gradle",
    ".cs",
    ".go",
    ".rs",
    ".html",
    ".css",
    ".scss",
    ".md",
}

ALLOWED_NAMES = {
    "dockerfile",
    "makefile",
    "pom.xml",
    "build.gradle",
    "settings.gradle",
    "package.json",
    "tsconfig.json",
}

SENSITIVE_NAME_PARTS = {
    "credential",
    "credentials",
    "secret",
    "secrets",
    "private_key",
    "id_rsa",
    "keystore",
    "truststore",
}

NOISE_TERMS = {
    "class",
    "const",
    "default",
    "export",
    "from",
    "function",
    "import",
    "interface",
    "java",
    "main",
    "public",
    "return",
    "service",
    "string",
    "this",
    "void",
}

CALL_NOISE_TERMS = NOISE_TERMS | {
    "add",
    "build",
    "catch",
    "equals",
    "execute",
    "filter",
    "find",
    "forEach",
    "get",
    "hashCode",
    "if",
    "map",
    "of",
    "put",
    "run",
    "set",
    "size",
    "stream",
    "super",
    "then",
    "toString",
}

FOCUS_STOP_TERMS = CALL_NOISE_TERMS | {
    "api",
    "backend",
    "frontend",
    "feat",
    "refactor",
    "system",
    "기능",
    "내용",
    "변경",
    "반영",
    "사항",
    "시스템",
    "요청",
    "적용",
}

LAYER_SUFFIXES = (
    "serviceimpl",
    "controller",
    "repository",
    "mapper",
    "service",
    "resource",
    "request",
    "response",
    "tasklet",
    "decider",
    "entity",
    "model",
    "dto",
    "dao",
    "impl",
    "job",
    "step",
    "vo",
)

EXPLICIT_REFERENCE_KINDS = {
    "endpoint",
    "import",
    "import-file",
    "mapper-contract",
    "namespace",
    "type-reference",
}

# A short filename such as data.ts or index.ts is common in unrelated projects.
# Cross-root graph edges therefore require a distinctive identifier.  Local
# matching may still use these names because directory and family evidence is
# available inside the same project root.
CROSS_ROOT_GENERIC_SIGNALS = {
    "api",
    "app",
    "common",
    "config",
    "constant",
    "constants",
    "data",
    "handler",
    "handlers",
    "index",
    "main",
    "model",
    "models",
    "service",
    "services",
    "settings",
    "store",
    "types",
    "util",
    "utils",
}

ROLE_RELATION_BONUSES = {
    frozenset(("frontend-api", "backend-controller")): 55,
    frozenset(("backend-controller", "backend-service")): 40,
    frozenset(("backend-service", "backend-mapper")): 40,
    frozenset(("backend-service", "backend-dto")): 24,
    frozenset(("backend-controller", "backend-dto")): 20,
    frozenset(("frontend-hook", "frontend-api")): 24,
    frozenset(("frontend-hook", "frontend-store")): 20,
    frozenset(("frontend-provider", "frontend-store")): 20,
    frozenset(("frontend-page", "frontend-hook")): 18,
    frozenset(("frontend-view", "frontend-hook")): 18,
    frozenset(("frontend-page", "frontend-api")): 14,
    frozenset(("frontend-view", "frontend-api")): 14,
}

STATUS_PRIORITY = {"삭제": 4, "이름변경": 3, "신규": 2, "변경": 1}
EMPTY_GIT_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

SENSITIVE_ASSIGNMENT = re.compile(
    r'''(?im)(\b(?:[A-Za-z][A-Za-z0-9]*[_-])*(?:api[_-]?key|access[_-]?key|private[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|secret|token|password|passwd|credentials?|(?:database|datasource|jdbc|redis)[_-]?url|connection[_-]?(?:url|string)|dsn)\b["']?\s*[:=]\s*)(["']?)([^\s"',;}{]{8,})(["']?)'''
)
BEARER_VALUE = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/-]{12,}")
SENSITIVE_XML_VALUE = re.compile(
    r"(?is)(<(?:password|apiKey|accessToken|clientSecret)>)[^<]{8,}(</(?:password|apiKey|accessToken|clientSecret)>)"
)


@dataclass
class IndexedFile:
    root: Path
    path: Path
    relative_path: str
    size: int
    modified_at: float

    @property
    def stem(self) -> str:
        return self.path.stem


@dataclass(frozen=True)
class ReferenceSignal:
    value: str
    kind: str
    weight: int


@dataclass
class ChangedProfile:
    change: ChangeItem
    path: Path
    role: str
    family: str
    signals: list[ReferenceSignal]
    terms: list[str]


@dataclass
class RelatedCandidate:
    score: int
    candidate: IndexedFile
    anchor_path: str
    anchor_role: str
    candidate_role: str
    reason: str
    explicit: bool
    terms: list[str]


def _log(callback: LogCallback | None, level: str, message: str) -> None:
    if callback:
        callback(level, message)


def _is_allowed_file(path: Path) -> bool:
    return _body_exclusion_reason(path) == ""


def _body_exclusion_reason(path: Path) -> str:
    name = path.name.casefold()
    if name.startswith(".env") or name in {".npmrc", ".pypirc", "settings.xml"}:
        return "민감정보 파일 규칙"
    if any(part in name for part in SENSITIVE_NAME_PARTS):
        return "민감정보 파일 규칙"
    if path.suffix.casefold() in {".key", ".pem", ".p12", ".pfx", ".jks"}:
        return "민감정보 파일 규칙"
    if path.suffix.casefold() in ALLOWED_SUFFIXES or name in ALLOWED_NAMES:
        return ""
    return "지원하지 않는 확장자"


def _safe_relative(root: Path, path: Path) -> str | None:
    try:
        return path.resolve(strict=False).relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def _decode_text_prefix(data: bytes, encoding: str) -> str:
    """Decode a bounded byte prefix without treating a cut multibyte tail as corruption."""

    try:
        return data.decode(encoding)
    except UnicodeDecodeError as exc:
        if exc.end == len(data):
            return data[: exc.start].decode(encoding)
        raise


def _xml_declared_encoding(data: bytes) -> str:
    # XML declarations are ASCII-compatible for the encodings handled here.
    # UTF-16 documents are detected by their BOM before this fallback runs.
    prefix = data[:512].decode("ascii", errors="ignore")
    match = re.search(
        r"<\?xml\b[^>]{0,400}\bencoding\s*=\s*['\"]([^'\"]+)['\"]",
        prefix,
        re.IGNORECASE,
    )
    if not match:
        return ""
    try:
        return codecs.lookup(match.group(1).strip()).name
    except LookupError:
        return ""


def _read_text(path: Path, max_chars: int = 0) -> str:
    with path.open("rb") as handle:
        data = handle.read(max_chars * 4 if max_chars > 0 else -1)

    encodings: list[str] = []
    if data.startswith(codecs.BOM_UTF8):
        encodings.append("utf-8-sig")
    elif data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        encodings.append("utf-16")

    declared_encoding = _xml_declared_encoding(data)
    if declared_encoding:
        encodings.append(declared_encoding)
    encodings.extend(("utf-8", "cp949"))

    for encoding in dict.fromkeys(encodings):
        try:
            text = _decode_text_prefix(data, encoding)
            text = _redact_sensitive_text(text)
            return text[:max_chars] if max_chars > 0 else text
        except (LookupError, UnicodeDecodeError):
            continue
    return _redact_sensitive_text(data.decode("utf-8", errors="replace"))[:max_chars or None]


def _redact_sensitive_text(text: str) -> str:
    def redact_assignment(match: re.Match[str]) -> str:
        return f"{match.group(1)}{match.group(2)}[REDACTED]{match.group(4)}"

    redacted = SENSITIVE_ASSIGNMENT.sub(redact_assignment, text)
    redacted = BEARER_VALUE.sub(r"\1[REDACTED]", redacted)
    return SENSITIVE_XML_VALUE.sub(r"\1[REDACTED]\2", redacted)


def redact_sensitive_text(text: str) -> str:
    """Remove common secret shapes before text reaches prompts or run artifacts."""

    return _redact_sensitive_text(text)


def build_project_index(
    root: Path,
    max_files: int,
    log: LogCallback | None = None,
) -> tuple[list[IndexedFile], int, bool]:
    root = root.resolve()
    indexed: list[IndexedFile] = []
    excluded = 0
    truncated = False

    for current, dir_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        dir_names[:] = sorted(
            name
            for name in dir_names
            if name.casefold() not in EXCLUDED_DIRECTORIES
            and not (current_path / name).is_symlink()
        )
        for name in sorted(file_names):
            path = current_path / name
            if path.is_symlink() or not _is_allowed_file(path):
                excluded += 1
                continue
            relative = _safe_relative(root, path)
            if relative is None:
                excluded += 1
                continue
            try:
                stat = path.stat()
            except OSError:
                excluded += 1
                continue
            indexed.append(IndexedFile(root, path, relative, stat.st_size, stat.st_mtime))
            if len(indexed) >= max_files:
                truncated = True
                break
        if truncated:
            break

    _log(log, "SCAN", f"{root.name}: 후보 파일 {len(indexed):,}개 인덱싱")
    return indexed, excluded, truncated


def _run_git(root: Path, args: list[str]) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return completed.stdout


def is_git_repository(root: Path) -> bool:
    try:
        return _run_git(root, ["rev-parse", "--is-inside-work-tree"]).strip() == "true"
    except (OSError, subprocess.CalledProcessError):
        return False


def _status_name(raw: str) -> str:
    text = raw.upper()
    if "D" in text:
        return "삭제"
    if "R" in text:
        return "이름변경"
    if "A" in text or "?" in text:
        return "신규"
    return "변경"


def _validate_date_range(date_from: date | None, date_to: date | None) -> None:
    if date_from and date_to and date_from > date_to:
        raise ValueError("변경 시작일은 종료일보다 늦을 수 없습니다.")


def _git_date_start(value: date) -> str:
    return f"{value.isoformat()}T00:00:00"


def _git_date_end(value: date) -> str:
    return f"{value.isoformat()}T23:59:59"


def collect_git_changes(
    root: Path,
    date_from: date | None = None,
    date_to: date | None = None,
    log: LogCallback | None = None,
) -> list[ChangeItem]:
    _validate_date_range(date_from, date_to)
    if not is_git_repository(root):
        _log(log, "INFO", f"{root.name}: Git 저장소가 아니므로 Diff 수집을 건너뜁니다")
        return []

    records: list[ChangeItem] = []
    try:
        git_root = Path(_run_git(root, ["rev-parse", "--show-toplevel"]).strip()).resolve()

        def selected_relative(raw_path: str) -> tuple[str, Path] | None:
            full_path = (git_root / raw_path).resolve(strict=False)
            try:
                relative_path = full_path.relative_to(root.resolve()).as_posix()
            except ValueError:
                return None
            return relative_path, full_path

        # The working tree represents the current state.  Do not mix it into a
        # historical range whose end date is before today.
        if date_to is None or date_to >= date.today():
            status_text = _run_git(
                root,
                ["-c", "core.quotepath=false", "status", "--porcelain=v1", "--untracked-files=all"],
            )
            for line in status_text.splitlines():
                if len(line) < 4:
                    continue
                raw_status = line[:2]
                raw_path = line[3:].strip().strip('"')
                rename_from = ""
                if " -> " in raw_path:
                    rename_from, raw_path = raw_path.split(" -> ", 1)
                selected = selected_relative(raw_path)
                if selected is None:
                    continue
                relative_path, path = selected
                records.append(
                    ChangeItem(
                        root=str(root),
                        path=relative_path,
                        change_type=_status_name(raw_status),
                        source="git-working-tree",
                        exists=path.exists(),
                        modified_at=_modified_iso(path),
                        note=f"이전 경로: {rename_from}" if rename_from else "",
                    )
                )

        if date_from or date_to:
            date_args: list[str] = []
            if date_from:
                date_args.append(f"--since={_git_date_start(date_from)}")
            if date_to:
                date_args.append(f"--until={_git_date_end(date_to)}")
            history = _run_git(
                root,
                [
                    "-c",
                    "core.quotepath=false",
                    "log",
                    *date_args,
                    "--name-status",
                    "--format=",
                ],
            )
            for line in history.splitlines():
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                raw_status = parts[0]
                raw_path = parts[-1]
                rename_from = parts[1] if raw_status.upper().startswith("R") and len(parts) >= 3 else ""
                selected = selected_relative(raw_path)
                if selected is None:
                    continue
                relative_path, path = selected
                records.append(
                    ChangeItem(
                        root=str(root),
                        path=relative_path,
                        change_type=_status_name(raw_status),
                        source="git-history",
                        exists=path.exists(),
                        modified_at=_modified_iso(path),
                        note=f"이전 경로: {rename_from}" if rename_from else "",
                    )
                )
    except (OSError, subprocess.CalledProcessError) as exc:
        _log(log, "WARN", f"{root.name}: Git 변경 수집 실패 - {exc}")
        return []

    merged = _merge_changes(records)
    _log(log, "GIT", f"{root.name}: Git 변경 {len(merged)}개 수집")
    return merged


def _modified_iso(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        return ""


def collect_date_changes(
    index: Iterable[IndexedFile],
    date_from: date | None,
    date_to: date | None,
) -> list[ChangeItem]:
    _validate_date_range(date_from, date_to)
    threshold_from = (
        datetime.combine(date_from, time.min).timestamp() if date_from else float("-inf")
    )
    threshold_to_exclusive = (
        datetime.combine(date_to + timedelta(days=1), time.min).timestamp()
        if date_to
        else float("inf")
    )
    return [
        ChangeItem(
            root=str(item.root),
            path=item.relative_path,
            change_type="변경",
            source="modified-date",
            exists=True,
            modified_at=datetime.fromtimestamp(item.modified_at).isoformat(timespec="seconds"),
        )
        for item in index
        if threshold_from <= item.modified_at < threshold_to_exclusive
    ]


def _manual_line(raw_line: str) -> tuple[tuple[str, str] | None, str | None]:
    pattern = re.compile(
        r"^(신규|추가|수정|변경|삭제|이름변경|A|M|D|R)\s*(?:[:：|\t]|\s+-\s+|\s+)\s*(.+)$",
        re.IGNORECASE,
    )
    type_map = {"신규": "신규", "추가": "신규", "A": "신규", "수정": "변경", "변경": "변경", "M": "변경", "삭제": "삭제", "D": "삭제", "이름변경": "이름변경", "R": "이름변경"}
    line = raw_line.strip().lstrip("-*○• ").strip()
    if not line:
        return None, None
    match = pattern.match(line)
    has_explicit_status = match is not None
    if match:
        change_type = type_map[match.group(1).upper() if len(match.group(1)) == 1 else match.group(1)]
        path_text = match.group(2).strip().strip('"').strip("'")
    else:
        change_type = "변경"
        path_text = line.strip('"').strip("'")

    normalized = path_text.replace("\\", "/")
    path = Path(normalized)
    name = path.name.casefold()
    looks_like_path = (
        path.suffix.casefold() in ALLOWED_SUFFIXES
        or name in ALLOWED_NAMES
        or (("/" in normalized) and not re.search(r"\s", normalized))
        or (
            has_explicit_status
            and not re.search(r"\s", normalized)
            and (bool(path.suffix) or name.startswith("."))
        )
    )
    if path_text and looks_like_path:
        return (change_type, path_text), None
    return None, line


def parse_manual_changes(text: str) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    for raw_line in text.splitlines():
        record, _note = _manual_line(raw_line)
        if record:
            records.append(record)
    return records


def parse_manual_notes(text: str) -> list[str]:
    notes: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        _record, note = _manual_line(raw_line)
        key = note.casefold() if note else ""
        if note and key not in seen:
            seen.add(key)
            notes.append(note)
    return notes


def resolve_manual_changes(
    root: Path,
    index: list[IndexedFile],
    manual_records: list[tuple[str, str]],
    allow_missing: bool = True,
) -> list[ChangeItem]:
    resolved_root = root.resolve()
    result = resolve_manual_changes_across_roots(
        [resolved_root],
        {str(resolved_root): index},
        manual_records,
    )
    return result if allow_missing else [item for item in result if item.exists]


def _manual_relative_candidates(root: Path, raw_path: str) -> list[str]:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        relative = _safe_relative(root, candidate)
        return [relative] if relative else []

    normalized = raw_path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    values = [normalized] if normalized else []
    parts = [part for part in normalized.split("/") if part]
    if len(parts) > 1 and parts[0].casefold() == root.name.casefold():
        values.append("/".join(parts[1:]))

    safe_values: list[str] = []
    for value in values:
        absolute = root / Path(value.replace("/", os.sep))
        relative = _safe_relative(root, absolute)
        if relative:
            safe_values.append(relative)
    return list(dict.fromkeys(safe_values))


def _unsafe_manual_path(roots: list[Path], raw_path: str) -> bool:
    """Reject traversal and absolute paths outside every selected project root."""

    normalized = raw_path.replace("\\", "/")
    if ".." in [part for part in normalized.split("/") if part]:
        return True
    candidate = Path(raw_path)
    if candidate.drive and not candidate.is_absolute():
        return True
    if candidate.is_absolute():
        return not any(_safe_relative(root, candidate) is not None for root in roots)
    return False


def _manual_item_from_index(
    root: Path,
    item: IndexedFile,
    change_type: str,
    note: str = "",
) -> ChangeItem:
    return ChangeItem(
        root=str(root),
        path=item.relative_path,
        change_type=change_type,
        source="manual",
        exists=True,
        modified_at=datetime.fromtimestamp(item.modified_at).isoformat(timespec="seconds"),
        note=note,
    )


def _existing_parent_depth(root: Path, relative_path: str) -> int:
    parts = [part for part in relative_path.replace("\\", "/").split("/") if part]
    if not parts:
        return 0
    current = root
    depth = 0
    for part in parts[:-1]:
        current = current / part
        if not current.is_dir():
            break
        depth += 1
    return depth


def resolve_manual_changes_across_roots(
    roots: list[Path],
    indexes: dict[str, list[IndexedFile]],
    manual_records: list[tuple[str, str]],
    log: LogCallback | None = None,
) -> list[ChangeItem]:
    """Resolve manual paths globally so one root cannot claim another root's file.

    Resolution order is exact relative path across every root, then basename
    matching. A missing or body-excluded manual item is retained as metadata
    and assigned to the root with the longest existing parent prefix.
    """

    normalized_roots = [root.resolve() for root in roots]
    by_relative: dict[str, dict[str, IndexedFile]] = {}
    by_name: dict[str, dict[str, list[IndexedFile]]] = {}
    for root in normalized_roots:
        root_key = str(root)
        index = indexes.get(root_key, [])
        by_relative[root_key] = {item.relative_path.casefold(): item for item in index}
        name_map: dict[str, list[IndexedFile]] = {}
        for item in index:
            name_map.setdefault(item.path.name.casefold(), []).append(item)
        by_name[root_key] = name_map

    results: list[ChangeItem] = []
    unresolved = 0
    for change_type, raw_path in manual_records:
        if _unsafe_manual_path(normalized_roots, raw_path):
            unresolved += 1
            _log(log, "WARN", f"프로젝트 루트 밖의 수동 변경 경로를 제외: {raw_path}")
            continue
        exact_matches: list[tuple[Path, IndexedFile | None, str]] = []
        relative_candidates_by_root: dict[str, list[str]] = {}
        for root in normalized_roots:
            root_key = str(root)
            relative_candidates = _manual_relative_candidates(root, raw_path)
            relative_candidates_by_root[root_key] = relative_candidates
            for relative in relative_candidates:
                indexed = by_relative[root_key].get(relative.casefold())
                if indexed is not None:
                    exact_matches.append((root, indexed, indexed.relative_path))
                    break
                absolute = root / Path(relative.replace("/", os.sep))
                if absolute.is_file():
                    exact_matches.append((root, None, relative))
                    break

        if exact_matches:
            ambiguous = len(exact_matches) > 1
            for root, indexed, relative in exact_matches:
                note = "동일 상대 경로가 여러 프로젝트 루트에 존재함" if ambiguous else ""
                if indexed is not None:
                    results.append(_manual_item_from_index(root, indexed, change_type, note))
                else:
                    path = root / Path(relative.replace("/", os.sep))
                    results.append(
                        ChangeItem(
                            root=str(root),
                            path=relative,
                            change_type=change_type,
                            source="manual",
                            exists=True,
                            modified_at=_modified_iso(path),
                            note=note,
                        )
                    )
            continue

        basename = Path(raw_path.replace("\\", "/")).name.casefold()
        basename_matches: list[tuple[Path, IndexedFile]] = []
        if basename:
            for root in normalized_roots:
                for item in by_name[str(root)].get(basename, []):
                    basename_matches.append((root, item))
        if basename_matches:
            ambiguous = len(basename_matches) > 1
            for root, item in basename_matches:
                results.append(
                    _manual_item_from_index(
                        root,
                        item,
                        change_type,
                        "파일명 다중 매칭" if ambiguous else "파일명으로 매칭",
                    )
                )
            continue

        if not normalized_roots:
            unresolved += 1
            _log(log, "WARN", f"수동 변경 경로를 프로젝트에서 찾지 못해 제외: {raw_path}")
            continue

        ranked_roots: list[tuple[int, int, Path, str]] = []
        for order, root in enumerate(normalized_roots):
            candidates = relative_candidates_by_root.get(str(root), [])
            if not candidates:
                continue
            best_relative = max(
                candidates,
                key=lambda value: (_existing_parent_depth(root, value), len(value)),
            )
            ranked_roots.append(
                (_existing_parent_depth(root, best_relative), -order, root, best_relative)
            )
        if not ranked_roots:
            unresolved += 1
            _log(log, "WARN", f"수동 변경 경로를 프로젝트 루트에 배정하지 못함: {raw_path}")
            continue
        depth, _negative_order, selected_root, selected_relative = max(
            ranked_roots,
            key=lambda row: (row[0], row[1]),
        )
        results.append(
            ChangeItem(
                root=str(selected_root),
                path=selected_relative,
                change_type=change_type,
                source="manual",
                exists=False,
                modified_at="",
                note=f"본문 확인 불가; 기존 상위 경로 {depth}단계 기준으로 루트 배정",
            )
        )

    _log(log, "MANUAL", f"수동 변경 {len(results)}개 매칭, 미해결 {unresolved}개")
    return results


def _merge_changes(changes: Iterable[ChangeItem]) -> list[ChangeItem]:
    merged: dict[str, ChangeItem] = {}
    source_priority = {"manual": 4, "git-working-tree": 3, "git-history": 2, "modified-date": 1}
    for item in changes:
        key = str((Path(item.root) / Path(item.path)).resolve(strict=False)).casefold()
        previous = merged.get(key)
        if previous is None:
            merged[key] = item
            continue
        if STATUS_PRIORITY.get(item.change_type, 0) > STATUS_PRIORITY.get(previous.change_type, 0):
            previous.change_type = item.change_type
        if source_priority.get(item.source, 0) > source_priority.get(previous.source, 0):
            previous.source = item.source
        previous.exists = previous.exists or item.exists
        previous.modified_at = previous.modified_at or item.modified_at
        previous.note = "; ".join(filter(None, dict.fromkeys([previous.note, item.note])))
    return sorted(merged.values(), key=lambda item: (item.root.casefold(), item.path.casefold()))


def collect_changes(
    roots: list[Path],
    manual_text: str,
    date_from: date | None,
    date_to: date | None,
    include_git: bool,
    scanner_settings: dict[str, Any],
    log: LogCallback | None = None,
) -> tuple[list[ChangeItem], dict[str, list[IndexedFile]], int, bool]:
    _validate_date_range(date_from, date_to)
    all_changes: list[ChangeItem] = []
    indexes: dict[str, list[IndexedFile]] = {}
    excluded_total = 0
    truncated = False
    manual_records = parse_manual_changes(manual_text)

    normalized_roots: list[Path] = []
    for root in roots:
        root = root.resolve()
        normalized_roots.append(root)
        index, excluded, was_truncated = build_project_index(
            root,
            int(scanner_settings.get("maxCandidateFiles", 10000)),
            log,
        )
        indexes[str(root)] = index
        excluded_total += excluded
        truncated = truncated or was_truncated
        if include_git:
            all_changes.extend(collect_git_changes(root, date_from, date_to, log))
        if date_from or date_to:
            date_changes = collect_date_changes(index, date_from, date_to)
            all_changes.extend(date_changes)
            range_label = (
                f"{date_from.isoformat() if date_from else '처음'}부터 "
                f"{date_to.isoformat() if date_to else '현재'}까지"
            )
            _log(log, "DATE", f"{root.name}: {range_label} 파일 {len(date_changes)}개")

    all_changes.extend(
        resolve_manual_changes_across_roots(normalized_roots, indexes, manual_records, log)
    )

    return _merge_changes(all_changes), indexes, excluded_total, truncated


def _clean_reference(value: str) -> str:
    clean = value.strip().strip("'\"").replace("\\", "/")
    clean = clean.rsplit("/", 1)[-1]
    clean = clean.rsplit(".", 1)[-1] if "." in clean and not clean.casefold().endswith(
        tuple(ALLOWED_SUFFIXES)
    ) else clean
    clean = re.sub(r"\.(?:java|kt|kts|xml|tsx?|jsx?|vue|py|sql)$", "", clean, flags=re.IGNORECASE)
    return re.sub(r"[^A-Za-z0-9_가-힣$#{}-]", "", clean)


def _normalize_endpoint(value: str) -> str:
    endpoint = value.strip().strip("'\"`").replace("\\", "/")
    endpoint = re.sub(r"^[A-Za-z][A-Za-z0-9+.-]*://[^/]+", "", endpoint)
    endpoint = re.sub(r"\$\{[^}]+\}", "{}", endpoint)
    endpoint = re.sub(r"^(?:\{\})+(?=/)", "", endpoint)
    api_offset = endpoint.find("/api/")
    if api_offset > 0:
        endpoint = endpoint[api_offset:]
    endpoint = re.split(r"[?#]", endpoint, maxsplit=1)[0]
    endpoint = re.sub(r"\{[^}/]+\}", "{}", endpoint)
    endpoint = re.sub(r":[A-Za-z_][A-Za-z0-9_-]*(?=/|$)", "{}", endpoint)
    endpoint = re.sub(r"/{2,}", "/", endpoint)
    if endpoint and not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    if len(endpoint) > 1:
        endpoint = endpoint.rstrip("/")
    segments = [segment for segment in endpoint.split("/") if segment]
    is_only_base = bool(segments) and all(
        re.fullmatch(r"(?:api|rest|v[0-9]+)", segment, re.IGNORECASE)
        for segment in segments
    )
    if endpoint == "/" or is_only_base or not 2 <= len(endpoint) <= 300:
        return ""
    return endpoint


def _spring_mapping_paths(arguments: str) -> list[str]:
    """Keep path/value literals while ignoring produces, headers and similar metadata."""

    if not arguments:
        return [""]
    quoted = list(re.finditer(r"(['\"`])(.{0,500}?)\1", arguments, re.DOTALL))
    if not quoted:
        return [""]

    # Attribute-looking text inside a quoted path must not influence the
    # nearest named argument calculation, so preserve positions while masking.
    masked = list(arguments)
    for match in quoted:
        masked[match.start() : match.end()] = " " * (match.end() - match.start())
    assignments = list(
        re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*=", "".join(masked))
    )

    values: list[str] = []
    for match in quoted:
        prior = [assignment for assignment in assignments if assignment.end() <= match.start()]
        attribute = prior[-1].group(1).casefold() if prior else ""
        if not attribute or attribute in {"path", "value"}:
            values.append(match.group(2))
    return values or [""]


def _join_endpoint(prefix: str, suffix: str) -> str:
    normalized_prefix = _normalize_endpoint(prefix) if prefix else ""
    normalized_suffix = _normalize_endpoint(suffix) if suffix else ""
    if normalized_suffix.startswith("/api/") or not normalized_prefix:
        return normalized_suffix
    if not normalized_suffix:
        return normalized_prefix
    return _normalize_endpoint(normalized_prefix.rstrip("/") + "/" + normalized_suffix.lstrip("/"))


def _extract_endpoint_values(path: Path, text: str) -> list[str]:
    suffix = path.suffix.casefold()
    values: list[str] = []

    if suffix in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".vue"}:
        call_patterns = (
            r"\bfetch\s*\(\s*(['\"`])(.{1,500}?)\1",
            r"\baxios\s*\.\s*(?:get|post|put|patch|delete|request)\s*\(\s*(['\"`])(.{1,500}?)\1",
            r"\b(?:(?:api|http|client|request|axios)[A-Za-z0-9_$]*|"
            r"[A-Za-z_$][A-Za-z0-9_$]*(?:api|http|client|request|axios)[A-Za-z0-9_$]*)"
            r"\s*\.\s*(?:get|post|put|patch|delete|request)\s*(?:<[^>\r\n]{1,200}>)?\s*\(\s*"
            r"(['\"`])((?:https?://|/|\$\{[^}]{1,100}\}/).{0,499}?)\1",
            r"\b(?:path|url)\s*:\s*(['\"`])(.{1,500}?)\1",
        )
        for pattern in call_patterns:
            values.extend(
                match.group(2)
                for match in re.finditer(pattern, text, re.IGNORECASE | re.DOTALL)
            )
        values.extend(
            match.group(2)
            for match in re.finditer(
                r"(?:\breturn\s+|(?:=|=>)\s*)(['\"`])"
                r"((?:https?://[^'\"`\s]+)?/api(?:/[^'\"`\s]*)?)\1",
                text,
                re.IGNORECASE,
            )
        )

    if suffix in {".java", ".kt"}:
        annotation_pattern = re.compile(
            r"@(RequestMapping|GetMapping|PostMapping|PutMapping|PatchMapping|DeleteMapping)\b"
            r"\s*(?:\((.{0,1000}?)\))?",
            re.IGNORECASE | re.DOTALL,
        )
        annotations = list(annotation_pattern.finditer(text))
        class_match = re.search(r"\b(?:class|interface)\s+[A-Za-z_$][A-Za-z0-9_$]*", text)
        class_offset = class_match.start() if class_match else -1
        class_prefixes: list[str] = []
        for match in annotations:
            if (
                match.group(1).casefold() == "requestmapping"
                and class_offset >= 0
                and match.end() <= class_offset
            ):
                class_prefixes.extend(_spring_mapping_paths(match.group(2) or ""))
        if not class_prefixes:
            class_prefixes = [""]

        for match in annotations:
            if class_offset >= 0 and match.end() <= class_offset:
                continue
            mapping_values = _spring_mapping_paths(match.group(2) or "")
            for prefix in class_prefixes:
                for mapping_value in mapping_values:
                    combined = _join_endpoint(prefix, mapping_value)
                    if combined:
                        values.append(combined)

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        endpoint = _normalize_endpoint(value)
        key = endpoint.casefold()
        if endpoint and key not in seen:
            seen.add(key)
            normalized.append(endpoint)
    return normalized


def _add_signal(
    signals: dict[tuple[str, str], ReferenceSignal],
    value: str,
    kind: str,
    weight: int,
) -> None:
    clean = _normalize_endpoint(value) if kind == "endpoint" else _clean_reference(value)
    if len(clean) < 3 or clean.casefold() in NOISE_TERMS:
        return
    key = (clean.casefold(), kind)
    previous = signals.get(key)
    if previous is None or weight > previous.weight:
        signals[key] = ReferenceSignal(clean, kind, weight)


def _extract_reference_signals(path: Path, text: str) -> list[ReferenceSignal]:
    """Extract bounded, typed references used to build a small dependency graph.

    Exact import and mapper contract references are intentionally stronger than
    incidental identifier occurrences.  This keeps common words and framework
    classes from dominating related-file selection.
    """

    signals: dict[tuple[str, str], ReferenceSignal] = {}
    _add_signal(signals, path.stem, "file-stem", 120)
    source = text[:120000]

    for endpoint in _extract_endpoint_values(path, source):
        _add_signal(signals, endpoint, "endpoint", 130)

    for static_marker, imported in re.findall(
        r"\bimport\s+(static\s+)?([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)+)\s*;?",
        source,
    ):
        parts = imported.split(".")
        leaf = parts[-2] if static_marker and len(parts) > 1 else parts[-1]
        if leaf != "*":
            _add_signal(signals, leaf, "import", 115)

    module_patterns = (
        r"\bfrom\s+['\"]([^'\"]+)['\"]",
        r"\brequire\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
        r"\bimport\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
    )
    for pattern in module_patterns:
        for module in re.findall(pattern, source):
            _add_signal(signals, module, "import-file", 110)

    for names in re.findall(r"\bimport\s*\{([^}]{1,500})\}\s*from\s*['\"]", source):
        for name in names.split(","):
            _add_signal(signals, name.split(" as ", 1)[0], "import", 95)

    for module, imported_names in re.findall(
        r"(?m)^\s*from\s+([\w.]+)\s+import\s+([^\r\n#]+)", source
    ):
        _add_signal(signals, module, "import-file", 105)
        for imported in imported_names.split(","):
            _add_signal(signals, imported.split(" as ", 1)[0], "import", 100)
    for modules in re.findall(r"(?m)^\s*import\s+([^\r\n#]+)", source):
        for module in modules.split(","):
            _add_signal(signals, module.split(" as ", 1)[0], "import-file", 95)

    for attribute, value in re.findall(
        r"\b(namespace|resultType|parameterType|resultMap|ofType|javaType|refid)\s*=\s*['\"]([^'\"]+)['\"]",
        source,
        re.IGNORECASE,
    ):
        kind = "namespace" if attribute.casefold() == "namespace" else "mapper-contract"
        _add_signal(signals, value, kind, 115 if kind == "namespace" else 105)

    for value in re.findall(r"<(?:select|insert|update|delete|sql|resultMap)\b[^>]*\bid\s*=\s*['\"]([^'\"]+)['\"]", source, re.IGNORECASE):
        _add_signal(signals, value, "statement-id", 75)
    if path.suffix.casefold() == ".xml" and re.search(r"<mapper\b", source, re.IGNORECASE):
        for value in re.findall(r"[#\$]\{\s*([A-Za-z_][A-Za-z0-9_.]*)", source):
            _add_signal(signals, value, "data-field", 45)

    for value in re.findall(
        r"\b(?:class|interface|enum|record|type)\s+([A-Z][A-Za-z0-9_$]+)", source
    ):
        _add_signal(signals, value, "definition", 100)
    for value in re.findall(
        r"(?m)(?:^|[\s<(,:])([A-Z][A-Za-z0-9_$]{2,})\s*(?:<[^;=(){}]+>)?\s+[a-z_$][A-Za-z0-9_$]*\s*(?:[;=,)])",
        source,
    ):
        _add_signal(signals, value, "type-reference", 70)
    for value in re.findall(r"<([A-Z][A-Za-z0-9_$]{2,})(?:\s|/?>)", source):
        _add_signal(signals, value, "type-reference", 65)

    for value in re.findall(r"\b([a-z_$][A-Za-z0-9_$]{2,})\s*\(", source):
        if value.casefold() not in {term.casefold() for term in CALL_NOISE_TERMS}:
            _add_signal(signals, value, "call", 35)
    for value in re.findall(r"\b(?:TB|TBL|VW|V)_[A-Z0-9_]{3,}\b", source, re.IGNORECASE):
        _add_signal(signals, value, "data-object", 55)

    ranked = sorted(
        signals.values(),
        key=lambda item: (-item.weight, item.kind, item.value.casefold()),
    )
    return ranked[:120]


def _extract_terms(path: Path, text: str) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for signal in _extract_reference_signals(path, text):
        key = signal.value.casefold()
        if key not in seen:
            seen.add(key)
            values.append(signal.value)
    return values[:80]


def _focus_terms(text: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[가-힣]{2,}", text):
        key = token.casefold()
        if key in FOCUS_STOP_TERMS or key in seen:
            continue
        seen.add(key)
        values.append(token)
    return values[:80]


def _file_role(path: Path) -> str:
    name = path.name.casefold()
    relative = path.as_posix().casefold()
    suffix = path.suffix.casefold()
    path_key = f"/{relative}"
    backend_suffixes = {".java", ".kt", ".cs"}
    frontend_suffixes = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".vue"}

    if suffix in backend_suffixes and (
        re.search(r"(?:controller|resource)\.(?:java|kt|cs)$", name)
        or re.search(r"/(?:controller|controllers)/", path_key)
    ):
        return "backend-controller"
    if suffix in backend_suffixes and (
        re.search(r"(?:service|serviceimpl|usecase)\.(?:java|kt|cs)$", name)
        or re.search(r"/(?:service|services)/", path_key)
    ):
        return "backend-service"
    if (
        re.search(r"(?:mapper|repository|dao)\.(?:java|kt|xml|cs)$", name)
        or re.search(r"/(?:mapper|mappers|repository|repositories|dao)/", path_key)
        or suffix == ".sql"
    ):
        return "backend-mapper"
    if suffix in backend_suffixes and (
        re.search(r"(?:dto|vo|entity|model|request|response)\.(?:java|kt|cs)$", name)
        or re.search(r"/(?:dto|domain|entity|entities|model|models|vo)/", path_key)
    ):
        return "backend-dto"
    if re.search(r"(?:job|step|tasklet|decider)\.(?:java|kt|py)$", name):
        return "backend-batch"

    if suffix in frontend_suffixes and (
        re.search(r"/(?:api|apis|client|clients)/", path_key)
        or re.search(r"(?:api|client)\.(?:[cm]?[jt]sx?|vue)$", name)
    ):
        return "frontend-api"
    if suffix in frontend_suffixes and (
        re.search(r"/(?:hook|hooks|composable|composables)/", path_key)
        or re.match(r"use[A-Z0-9].*\.(?:[cm]?[jt]sx?|vue)$", path.name)
    ):
        return "frontend-hook"
    if suffix in frontend_suffixes and (
        re.search(r"/(?:store|stores|state)/", path_key)
        or re.search(r"(?:store|slice)\.(?:[cm]?[jt]sx?)$", name)
    ):
        return "frontend-store"
    if suffix in frontend_suffixes and (
        re.search(r"/(?:provider|providers|context|contexts)/", path_key)
        or re.search(r"provider\.(?:[cm]?[jt]sx?)$", name)
    ):
        return "frontend-provider"
    if suffix in frontend_suffixes and re.search(r"/(?:pages|routes|router)/", path_key):
        return "frontend-page"
    if suffix in {".yml", ".yaml", ".properties", ".json"}:
        return "configuration"
    if suffix in {".tsx", ".jsx", ".vue", ".html"}:
        return "frontend-view"
    if re.search(r"(?:service|serviceimpl|usecase)\.(?:py|tsx?)$", name):
        return "business"
    if re.search(r"(?:mapper|repository|dao)\.(?:py)$", name):
        return "data-access"
    if re.search(r"(?:dto|vo|entity|model|request|response)\.(?:py|tsx?)$", name):
        return "data-contract"
    return "code"


def _business_family(path: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9가-힣]", "", path.stem).casefold()
    for suffix in LAYER_SUFFIXES:
        if stem.endswith(suffix) and len(stem) > len(suffix) + 1:
            stem = stem[: -len(suffix)]
            break
    return stem if len(stem) >= 3 else ""


def _role_relation_bonus(left: str, right: str) -> int:
    return ROLE_RELATION_BONUSES.get(frozenset((left, right)), 0)


def _focused_excerpt(
    text: str,
    terms: list[str],
    max_chars: int,
    priority_terms: list[str] | None = None,
) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    lines = text.splitlines()
    lowered_terms = [term.casefold() for term in terms[:50] if len(term) >= 3]
    lowered_priority = [
        term.casefold() for term in (priority_terms or [])[:50] if len(term) >= 2
    ]
    center_scores: dict[int, int] = {}
    center_categories: dict[int, set[str]] = {}

    evidence_patterns = (
        r"[가-힣]{2,}",
        r"(?i)\b(?:SELECT|INSERT|UPDATE|DELETE|MERGE|FROM|INTO|JOIN)\b|\b(?:TB|TBL|VW|V)_[A-Z0-9_]{3,}\b",
        r"(?i)\b(?:resultMap|parameterType|resultType|column|property)\b|@(?:Schema|Column|NotNull|Size)",
        r"(?i)\b(?:status|state|resultCode|errorCode|approval|confirm|jobParameter)\b|상태|승인|확정|기준일",
        r"(?i)@(?:Get|Post|Put|Patch|Delete|Request)Mapping|\b(?:route|path)\s*[:=]",
    )
    for index, line in enumerate(lines):
        lowered = line.casefold()
        priority_hits = sum(term in lowered for term in lowered_priority)
        term_hits = sum(term in lowered for term in lowered_terms)
        evidence_hits = sum(bool(re.search(pattern, line)) for pattern in evidence_patterns)
        structural = bool(
            re.search(
                r"(?i)\b(?:class|interface|function|const|public|private|protected|async|return|if|switch|case|SELECT|INSERT|UPDATE|DELETE)\b",
                line,
            )
        )
        categories: set[str] = set()
        if re.match(r"\s*(?:@@|\+\+\+|---|[+-](?![+-]))", line):
            categories.add("diff")
        if re.search(
            r"(?i)\b(?:if|else\s+if|switch|case|when|catch|throw|assert|validate|reject)\b|"
            r"\?\s*[^:]+\s*:",
            line,
        ):
            categories.add("condition")
        if re.search(
            r"(?i)\b(?:SELECT|INSERT|UPDATE|DELETE|MERGE|FROM|INTO|JOIN|WHERE)\b|"
            r"<(?:select|insert|update|delete|resultMap|sql)\b",
            line,
        ):
            categories.add("sql")
        if re.search(
            r"(?i)@(?:Get|Post|Put|Patch|Delete|Request)Mapping|"
            r"\b(?:function|def|fun|public|private|protected|async)\b.*\(|"
            r"\b[A-Za-z_$][A-Za-z0-9_$]*\s*\(",
            line,
        ):
            categories.add("call")
        if priority_hits or term_hits:
            categories.add("identifier")

        category_bonus = sum(
            {
                "diff": 130,
                "condition": 95,
                "sql": 105,
                "call": 45,
                "identifier": 35,
            }[category]
            for category in categories
        )
        score = (
            priority_hits * 220
            + term_hits * 35
            + evidence_hits * 55
            + (25 if structural else 0)
            + category_bonus
        )
        if re.match(r"\s*(?:import\b|package\b|from\s+['\"]|#include\b)", line):
            # Imports are relationship evidence, not the changed behavior itself.
            # Keep them as a last-resort excerpt for barrel files while ensuring
            # handlers, conditions, queries and render logic win the budget.
            score = min(score, 5)
        if score > 0:
            center_scores[index] = score
            center_categories[index] = categories

    if not center_scores:
        head_budget = max(1, int(max_chars * 0.72))
        tail_budget = max_chars - head_budget
        marker = "\n... 중간 내용 생략 ...\n"
        if tail_budget <= len(marker):
            return text[:max_chars]
        return (text[:head_budget].rstrip() + marker + text[-(tail_budget - len(marker)) :].lstrip())[:max_chars]

    ranked_centers = sorted(center_scores, key=lambda index: (-center_scores[index], index))
    ordered_centers: list[int] = []
    center_labels: dict[int, str] = {}

    # Reserve the first windows for different evidence shapes. Without this,
    # a frequently repeated identifier can consume the entire excerpt while a
    # later condition, call, or SQL statement is omitted.
    for category in ("diff", "condition", "sql", "identifier", "call"):
        candidates = sorted(
            (
                index
                for index, categories in center_categories.items()
                if category in categories
            ),
            key=lambda index: (-center_scores[index], index),
        )
        selected = next(
            (
                index
                for index in candidates
                if not any(abs(index - existing) <= 7 for existing in ordered_centers)
            ),
            None,
        )
        if selected is not None:
            ordered_centers.append(selected)
            center_labels[selected] = category
    for center in ranked_centers:
        if not any(abs(center - existing) <= 7 for existing in ordered_centers):
            ordered_centers.append(center)
            center_labels[center] = "related"

    output: list[str] = []
    covered: set[int] = set()
    used = 0
    for center in ordered_centers:
        if any(abs(center - existing) <= 7 for existing in covered):
            continue
        start = max(0, center - 3)
        end = min(len(lines), center + 5)
        block_lines = [f"{index + 1:>5}: {lines[index]}" for index in range(start, end)]
        label = center_labels.get(center, "related")
        block = f"... {label} 근거 {start + 1}행부터 {end}행 ...\n" + "\n".join(block_lines)
        separator = "\n" if not output else "\n... 다른 근거로 이동 ...\n"
        if used + len(separator) + len(block) > max_chars:
            remaining = max_chars - used - len(separator)
            if remaining > 80:
                output.append(separator + block[: remaining - 12].rstrip() + " ... 생략")
            break
        output.append(separator + block)
        used += len(separator) + len(block)
        covered.add(center)
        if used >= max_chars - 80:
            break
    return "".join(output).lstrip()[:max_chars]


def _git_diff(
    root: Path,
    relative_path: str,
    date_from: date | None,
    date_to: date | None,
    max_chars: int = 16000,
) -> str:
    _validate_date_range(date_from, date_to)
    chunks: list[str] = []
    historical_range = date_to is not None and date_to < date.today()
    if date_from or date_to:
        base = ""
        target = ""
        if date_from:
            try:
                base = _run_git(
                    root,
                    ["rev-list", "-1", f"--before={_git_date_start(date_from)}", "HEAD"],
                ).strip()
            except (OSError, subprocess.CalledProcessError):
                base = ""
        if historical_range:
            try:
                # Asking for the commit before the next midnight includes the
                # whole selected end date while excluding later commits.
                next_midnight = _git_date_start(date_to + timedelta(days=1))
                target = _run_git(
                    root,
                    ["rev-list", "-1", f"--before={next_midnight}", "HEAD"],
                ).strip()
            except (OSError, subprocess.CalledProcessError):
                target = ""
        if not base:
            try:
                has_head = bool(_run_git(root, ["rev-parse", "--verify", "HEAD"]).strip())
            except (OSError, subprocess.CalledProcessError):
                has_head = False
            if has_head:
                base = EMPTY_GIT_TREE
        if base and (not historical_range or target):
            try:
                revisions = [base]
                if target:
                    revisions.append(target)
                combined = _run_git(
                    root,
                    [
                        "diff",
                        "--find-renames",
                        "--no-ext-diff",
                        "--unified=4",
                        *revisions,
                        "--",
                        relative_path,
                    ],
                )
                if combined.strip():
                    chunks.append(combined)
            except (OSError, subprocess.CalledProcessError):
                pass
    if not chunks and historical_range:
        return ""
    if not chunks:
        try:
            working = _run_git(
                root,
                ["diff", "--find-renames", "--no-ext-diff", "--unified=4", "--", relative_path],
            )
            cached = _run_git(
                root,
                ["diff", "--cached", "--find-renames", "--no-ext-diff", "--unified=4", "--", relative_path],
            )
            if working.strip():
                chunks.append(working)
            if cached.strip():
                chunks.append(cached)
        except (OSError, subprocess.CalledProcessError):
            return ""
    combined = _redact_sensitive_text("\n".join(chunks)).strip()
    if len(combined) <= max_chars:
        return combined
    marker = "\n... diff 뒷부분 생략 ..."
    return combined[: max(0, max_chars - len(marker))].rstrip() + marker


def _candidate_relation(
    candidate: IndexedFile,
    candidate_text: str,
    profile: ChangedProfile,
    candidate_signals: list[ReferenceSignal] | None = None,
) -> RelatedCandidate | None:
    candidate_stem = candidate.stem.casefold()
    candidate_name = candidate.path.name.casefold()
    candidate_role = _file_role(Path(candidate.relative_path))
    candidate_family = _business_family(Path(candidate.relative_path))
    score = 0
    explicit = False
    reasons: list[str] = []
    focus_terms: list[str] = []

    direct_hits: list[ReferenceSignal] = []
    for signal in profile.signals:
        signal_key = signal.value.casefold()
        if candidate_stem == signal_key or candidate_name.startswith(signal_key + "."):
            direct_hits.append(signal)
    for signal in sorted(direct_hits, key=lambda item: -item.weight)[:3]:
        score += signal.weight
        explicit = explicit or signal.kind in EXPLICIT_REFERENCE_KINDS
        reasons.append(f"{signal.kind}가 파일명과 일치: {signal.value}")
        focus_terms.append(signal.value)

    if candidate_signals is None:
        candidate_signals = _extract_reference_signals(candidate.path, candidate_text) if candidate_text else []
    changed_stem = profile.path.stem.casefold()
    reverse_hits = [
        signal
        for signal in candidate_signals
        if signal.value.casefold() == changed_stem and signal.kind in EXPLICIT_REFERENCE_KINDS
    ]
    if reverse_hits:
        best = max(reverse_hits, key=lambda item: item.weight)
        score += min(115, best.weight)
        explicit = True
        reasons.append(f"후보 파일이 변경 파일을 {best.kind}로 참조")
        focus_terms.append(profile.path.stem)

    changed_by_value: dict[str, list[ReferenceSignal]] = {}
    for signal in profile.signals:
        changed_by_value.setdefault(signal.value.casefold(), []).append(signal)
    shared: list[tuple[int, str, str]] = []
    for signal in candidate_signals:
        matches = changed_by_value.get(signal.value.casefold(), [])
        for changed_signal in matches:
            if signal.kind == "endpoint" and changed_signal.kind == "endpoint":
                score += 140
                explicit = True
                reasons.append(f"공통 endpoint: {signal.value}")
                focus_terms.append(signal.value)
                break
            if signal.kind in {"data-object", "statement-id", "data-field", "mapper-contract"} or changed_signal.kind in {
                "data-object",
                "statement-id",
                "data-field",
                "mapper-contract",
            }:
                shared.append((min(signal.weight, changed_signal.weight), signal.value, signal.kind))
                break
    for weight, value, kind in sorted(shared, reverse=True)[:3]:
        score += max(12, weight // 2)
        reasons.append(f"공통 {kind}: {value}")
        focus_terms.append(value)

    if score > 0:
        role_bonus = _role_relation_bonus(profile.role, candidate_role)
        if role_bonus:
            score += role_bonus
            reasons.append(f"{profile.role}와 {candidate_role} 계층 연결")

    if profile.family and candidate_family == profile.family:
        layer_bonus = 32 if candidate_role != profile.role else 14
        score += layer_bonus
        reasons.append(f"같은 업무명 계열의 {candidate_role} 계층")
    if candidate.path.parent == profile.path.parent:
        score += 8
        reasons.append("변경 파일과 같은 디렉터리")

    if score < 28:
        return None
    unique_reasons = list(dict.fromkeys(reasons))[:5]
    unique_terms = list(dict.fromkeys([*focus_terms, *profile.terms]))[:40]
    return RelatedCandidate(
        score=score,
        candidate=candidate,
        anchor_path=profile.change.path,
        anchor_role=profile.role,
        candidate_role=candidate_role,
        reason="; ".join(unique_reasons),
        explicit=explicit,
        terms=unique_terms,
    )


def _select_related_candidates(
    rows: list[RelatedCandidate],
    profiles: list[ChangedProfile],
    limit: int,
) -> list[RelatedCandidate]:
    if limit <= 0:
        return []
    ranked = sorted(
        rows,
        key=lambda row: (
            not row.explicit,
            -row.score,
            row.candidate.relative_path.casefold(),
            row.anchor_path.casefold(),
        ),
    )
    selected: list[RelatedCandidate] = []
    selected_paths: set[tuple[str, str]] = set()
    anchor_roles: dict[str, set[str]] = {}

    def append(row: RelatedCandidate) -> None:
        key = (str(row.candidate.root).casefold(), row.candidate.relative_path.casefold())
        if key in selected_paths or len(selected) >= limit:
            return
        selected.append(row)
        selected_paths.add(key)
        anchor_roles.setdefault(row.anchor_path.casefold(), set()).add(row.candidate_role)

    # A large change list must not let the input order consume the whole budget.
    # Pick the globally strongest candidate for each anchor before adding a
    # second architectural role.  The profiles argument remains part of this
    # helper's contract for callers and tests that provide the anchor set.
    profile_anchors = {profile.change.path.casefold() for profile in profiles}
    covered_anchors: set[str] = set()
    for row in ranked:
        anchor = row.anchor_path.casefold()
        if anchor in profile_anchors and anchor not in covered_anchors:
            append(row)
            covered_anchors.add(anchor)
        if len(selected) >= limit:
            return selected

    # Then prefer a different architectural role for each changed-file anchor.
    for row in ranked:
        roles = anchor_roles.get(row.anchor_path.casefold(), set())
        if row.candidate_role not in roles:
            append(row)
        if len(selected) >= limit:
            return selected
    for row in ranked:
        append(row)
        if len(selected) >= limit:
            break
    return selected


def _truncate_section(text: str, max_chars: int, marker: str) -> tuple[str, bool]:
    if max_chars <= 0:
        return "", bool(text)
    if len(text) <= max_chars:
        return text, False
    suffix = f"\n... {marker} ..."
    if max_chars <= len(suffix) + 20:
        return text[:max_chars], True
    return text[: max_chars - len(suffix)].rstrip() + suffix, True


def _compose_changed_excerpt(
    change: ChangeItem,
    source: str,
    diff: str,
    terms: list[str],
    budget: int,
    priority_terms: list[str] | None = None,
) -> tuple[str, str, bool]:
    header = (
        f"[변경 사실]\n파일: {change.path}\n구분: {change.change_type}\n"
        f"수집 근거: {change.source}\n"
    )
    if change.note:
        header += f"비고: {change.note}\n"
    remaining = max(0, budget - len(header) - 2)
    blocks: list[str] = [header.rstrip()]
    truncated = False
    modes: list[str] = []

    if diff:
        diff_budget = remaining if not source else max(300, int(remaining * 0.58))
        diff_text, was_truncated = _truncate_section(diff, diff_budget, "diff 예산 초과로 생략")
        if diff_text:
            blocks.append("[Git diff]\n" + diff_text)
            remaining -= len(diff_text) + len("[Git diff]\n\n")
            modes.append("diff")
            truncated = truncated or was_truncated
    if source and remaining > 100:
        excerpt = _focused_excerpt(
            source,
            terms,
            remaining - len("[현재 소스]\n"),
            priority_terms,
        )
        was_truncated = len(source) > len(excerpt)
        if excerpt:
            blocks.append("[현재 소스]\n" + excerpt)
            modes.append("full" if not was_truncated else "focused")
            truncated = truncated or was_truncated
    elif source:
        truncated = True
    if not diff and not source:
        blocks.append("현재 소스와 Git diff를 확보하지 못함")
        modes.append("metadata")
    return "\n\n".join(blocks)[:budget], "+".join(modes) or "metadata", truncated


def build_scan_bundle(
    roots: list[Path],
    manual_text: str,
    date_from: date | None,
    date_to: date | None,
    include_git: bool,
    scanner_settings: dict[str, Any],
    log: LogCallback | None = None,
    request_text: str = "",
) -> ScanBundle:
    _validate_date_range(date_from, date_to)
    change_notes = [redact_sensitive_text(note) for note in parse_manual_notes(manual_text)]
    focus_terms = _focus_terms("\n".join((request_text, *change_notes)))
    changes, indexes, excluded, truncated = collect_changes(
        roots,
        manual_text,
        date_from,
        date_to,
        include_git,
        scanner_settings,
        log,
    )
    if not changes:
        raise ValueError("변경 파일을 찾지 못했습니다. 날짜, Git Diff 또는 수동 목록을 확인해 주세요.")

    max_changed = max(400, int(scanner_settings.get("maxChangedFileChars", 24000)))
    max_related = max(0, int(scanner_settings.get("maxRelatedFiles", 12)))
    max_related_chars = max(300, int(scanner_settings.get("maxRelatedFileChars", 7000)))
    max_context = max(1000, int(scanner_settings.get("maxContextChars", 70000)))
    max_diff_chars = max(500, int(scanner_settings.get("maxDiffChars", 16000)))
    max_content_scan_files = max(0, int(scanner_settings.get("maxContentScanFiles", 2500)))
    max_source_scan_chars = max(
        max_changed,
        int(scanner_settings.get("maxSourceScanChars", max(120000, max_changed * 4))),
    )

    contexts: list[ContextFile] = []
    warnings: list[str] = []
    changed_keys = {item.key() for item in changes}
    changed_physical_keys = {
        str((Path(item.root) / Path(item.path)).resolve(strict=False)).casefold()
        for item in changes
    }
    profiles: list[ChangedProfile] = []
    source_by_key: dict[tuple[str, str], str] = {}

    for change in changes:
        root = Path(change.root)
        path = root / change.path
        source = ""
        if change.exists and path.exists() and _is_allowed_file(path):
            try:
                source = _read_text(path, max_source_scan_chars)
                if path.stat().st_size > max_source_scan_chars or len(source) >= max_source_scan_chars:
                    warnings.append(f"{change.path} 소스 탐색이 문자 상한에서 잘렸습니다.")
            except OSError as exc:
                warnings.append(f"{change.path} 읽기 실패: {exc}")
        elif change.exists and path.exists():
            warnings.append(f"{change.path}는 {_body_exclusion_reason(path)}으로 본문을 제외했습니다.")
        signals = _extract_reference_signals(path, source)
        terms = list(dict.fromkeys([*focus_terms, *_extract_terms(path, source)]))[:120]
        profiles.append(
            ChangedProfile(
                change=change,
                path=path,
                role=_file_role(Path(change.path)),
                family=_business_family(Path(change.path)),
                signals=signals,
                terms=terms,
            )
        )
        source_by_key[change.key()] = source

    # Reserve a bounded share for relationship evidence while guaranteeing a
    # fair, deterministic slice for every changed file first.
    try:
        related_ratio = float(scanner_settings.get("relatedContextRatio", 0.25))
    except (TypeError, ValueError):
        related_ratio = 0.25
    related_ratio = max(0.1, min(related_ratio, 0.4))
    related_reserve = min(int(max_context * related_ratio), max_related * max_related_chars)
    changed_pool = max_context - related_reserve
    if changed_pool < len(changes) * 220:
        changed_pool = max_context
        related_reserve = 0
    remaining_changed = changed_pool
    changed_truncated = 0
    git_root_cache = {
        str(root.resolve()).casefold(): include_git and is_git_repository(root)
        for root in roots
    }
    for index, profile in enumerate(profiles):
        change = profile.change
        root = Path(change.root)
        files_left = len(profiles) - index
        fair_share = max(120, remaining_changed // max(1, files_left))
        budget = min(max_changed + max_diff_chars, fair_share)
        diff = ""
        if git_root_cache.get(str(root.resolve()).casefold(), False):
            diff = _git_diff(root, change.path, date_from, date_to, max_diff_chars)
            if diff:
                _log(log, "DIFF", f"{change.path}: Git diff {len(diff):,}자 확보")
        excerpt, mode, was_truncated = _compose_changed_excerpt(
            change,
            source_by_key.get(change.key(), ""),
            diff,
            profile.terms,
            budget,
            focus_terms,
        )
        contexts.append(
            ContextFile(
                change.root,
                change.path,
                mode,
                "변경 파일별 독립 근거이며 Git diff를 현재 소스보다 우선 배정",
                1000,
                excerpt,
            )
        )
        remaining_changed = max(0, remaining_changed - len(excerpt))
        if was_truncated:
            changed_truncated += 1
        _log(
            log,
            "SCAN-FILE",
            f"{change.change_type} {change.path}: {mode}, 근거 {len(excerpt):,}자, 참조 신호 {len(profile.signals)}개",
        )

    total_chars = sum(len(item.excerpt) for item in contexts)
    related_rows_by_path: dict[tuple[str, str], RelatedCandidate] = {}
    candidate_by_key: dict[tuple[str, str], IndexedFile] = {}
    candidate_content_by_key: dict[tuple[str, str], str] = {}
    candidate_signals_by_key: dict[tuple[str, str], list[ReferenceSignal]] = {}
    candidate_keys_by_stem: dict[tuple[str, str], list[tuple[str, str]]] = {}
    candidate_keys_by_explicit_signal: dict[tuple[str, str], list[tuple[str, str]]] = {}
    candidate_keys_by_stem_global: dict[str, list[tuple[str, str]]] = {}
    candidate_keys_by_explicit_signal_global: dict[str, list[tuple[str, str]]] = {}
    profile_signals_by_root: dict[str, dict[str, set[int]]] = {}
    profile_families_by_root: dict[str, dict[str, set[int]]] = {}
    profile_parents_by_root: dict[str, dict[str, set[int]]] = {}
    profiles_by_id = {id(profile): profile for profile in profiles}
    global_signal_index: dict[str, set[int]] = {}
    for profile in profiles:
        root_key = profile.change.root.casefold()
        signal_index = profile_signals_by_root.setdefault(root_key, {})
        for signal in profile.signals:
            signal_index.setdefault(signal.value.casefold(), set()).add(id(profile))
            signal_value = signal.value.casefold()
            if signal_value not in CROSS_ROOT_GENERIC_SIGNALS:
                global_signal_index.setdefault(signal_value, set()).add(id(profile))
        if profile.family:
            profile_families_by_root.setdefault(root_key, {}).setdefault(profile.family, set()).add(id(profile))
        parent_key = profile.path.parent.as_posix().casefold()
        profile_parents_by_root.setdefault(root_key, {}).setdefault(parent_key, set()).add(id(profile))

    content_scans = 0
    candidate_physical_keys: set[str] = set()
    for root_text, project_index in indexes.items():
        for candidate in project_index:
            key = (root_text.casefold(), candidate.relative_path.casefold())
            physical_key = str(candidate.path.resolve(strict=False)).casefold()
            if physical_key in changed_physical_keys or physical_key in candidate_physical_keys:
                continue
            candidate_physical_keys.add(physical_key)
            candidate_by_key[key] = candidate
            candidate_keys_by_stem.setdefault((key[0], candidate.stem.casefold()), []).append(key)
            candidate_keys_by_stem_global.setdefault(candidate.stem.casefold(), []).append(key)
            local_signal_index = profile_signals_by_root.get(root_text.casefold(), {})
            local_family_index = profile_families_by_root.get(root_text.casefold(), {})
            path_score_possible = (
                candidate.stem.casefold() in local_signal_index
                or candidate.stem.casefold() in global_signal_index
                or _business_family(Path(candidate.relative_path)) in local_family_index
            )
            content = ""
            if path_score_possible or content_scans < max_content_scan_files:
                try:
                    content = _read_text(candidate.path, max(18000, max_related_chars * 2))
                except OSError:
                    content = ""
                candidate_content_by_key[key] = content
                if not path_score_possible:
                    content_scans += 1
            candidate_signals = _extract_reference_signals(candidate.path, content) if content else []
            candidate_signals_by_key[key] = candidate_signals
            for signal in candidate_signals:
                if signal.kind in EXPLICIT_REFERENCE_KINDS:
                    candidate_keys_by_explicit_signal.setdefault(
                        (key[0], signal.value.casefold()), []
                    ).append(key)
                    candidate_keys_by_explicit_signal_global.setdefault(
                        signal.value.casefold(), []
                    ).append(key)

            possible_profile_ids: set[int] = set(
                local_signal_index.get(candidate.stem.casefold(), set())
            )
            for signal in candidate_signals:
                possible_profile_ids.update(local_signal_index.get(signal.value.casefold(), set()))
            candidate_family = _business_family(Path(candidate.relative_path))
            if candidate_family:
                possible_profile_ids.update(local_family_index.get(candidate_family, set()))
            possible_profile_ids.update(
                profile_parents_by_root.get(root_text.casefold(), {}).get(
                    candidate.path.parent.as_posix().casefold(), set()
                )
            )

            cross_root_values = {candidate.stem.casefold()}
            cross_root_values.update(
                signal.value.casefold()
                for signal in candidate_signals
                if signal.kind in EXPLICIT_REFERENCE_KINDS
            )
            for value in cross_root_values - CROSS_ROOT_GENERIC_SIGNALS:
                possible_profile_ids.update(global_signal_index.get(value, set()))
            for profile_id in possible_profile_ids:
                profile = profiles_by_id[profile_id]
                relation = _candidate_relation(candidate, content, profile, candidate_signals)
                if relation is None:
                    continue
                if profile.change.root.casefold() != root_text.casefold() and not relation.explicit:
                    continue
                previous = related_rows_by_path.get(key)
                if previous is None or relation.score > previous.score:
                    related_rows_by_path[key] = relation

    # Follow one additional exact-reference hop.  A changed controller often
    # names only its service, while the service owns the mapper and DTO links
    # needed to understand the observable behavior.  Expansion is deliberately
    # limited to explicit imports and mapper contracts to prevent topic drift.
    direct_rows = sorted(
        related_rows_by_path.values(),
        key=lambda row: (not row.explicit, -row.score, row.candidate.relative_path.casefold()),
    )
    direct_relation_count = len(direct_rows)
    expanded_relation_count = 0
    expansion_limit = min(24, max(4, max_related * 2))
    for seed in direct_rows[:expansion_limit]:
        seed_key = (
            str(seed.candidate.root).casefold(),
            seed.candidate.relative_path.casefold(),
        )
        seed_content = candidate_content_by_key.get(seed_key, "")
        if not seed_content:
            try:
                seed_content = _read_text(seed.candidate.path, max(24000, max_related_chars * 3))
            except OSError:
                continue
            candidate_content_by_key[seed_key] = seed_content
        bridge_change = ChangeItem(
            root=str(seed.candidate.root),
            path=seed.candidate.relative_path,
            change_type="변경",
            source="related-expansion",
            exists=True,
        )
        bridge_profile = ChangedProfile(
            change=bridge_change,
            path=seed.candidate.path,
            role=seed.candidate_role,
            family=_business_family(Path(seed.candidate.relative_path)),
            signals=_extract_reference_signals(seed.candidate.path, seed_content),
            terms=_extract_terms(seed.candidate.path, seed_content),
        )
        if not bridge_profile.signals:
            continue
        seed_root_key = str(seed.candidate.root).casefold()
        expansion_candidate_keys: set[tuple[str, str]] = set()
        for signal in bridge_profile.signals:
            if signal.kind in EXPLICIT_REFERENCE_KINDS:
                signal_value = signal.value.casefold()
                expansion_candidate_keys.update(
                    candidate_keys_by_stem.get((seed_root_key, signal_value), [])
                )
                if signal_value not in CROSS_ROOT_GENERIC_SIGNALS:
                    expansion_candidate_keys.update(
                        candidate_keys_by_stem_global.get(signal_value, [])
                    )
        expansion_candidate_keys.update(
            candidate_keys_by_explicit_signal.get(
                (seed_root_key, seed.candidate.stem.casefold()), []
            )
        )
        if seed.candidate.stem.casefold() not in CROSS_ROOT_GENERIC_SIGNALS:
            expansion_candidate_keys.update(
                candidate_keys_by_explicit_signal_global.get(
                    seed.candidate.stem.casefold(), []
                )
            )
        for candidate_key in sorted(expansion_candidate_keys):
            if candidate_key in changed_keys or candidate_key == seed_key:
                continue
            candidate = candidate_by_key[candidate_key]
            relation = _candidate_relation(
                candidate,
                candidate_content_by_key.get(candidate_key, ""),
                bridge_profile,
                candidate_signals_by_key.get(candidate_key, []),
            )
            if relation is None or not relation.explicit:
                continue
            expanded = RelatedCandidate(
                score=max(30, int(seed.score * 0.25 + relation.score * 0.75)),
                candidate=candidate,
                anchor_path=seed.anchor_path,
                anchor_role=seed.anchor_role,
                candidate_role=relation.candidate_role,
                reason=(
                    f"{seed.candidate.relative_path}의 정확한 참조를 한 단계 확장: "
                    f"{relation.reason}"
                ),
                explicit=True,
                terms=list(dict.fromkeys([*relation.terms, *seed.terms]))[:40],
            )
            previous = related_rows_by_path.get(candidate_key)
            if previous is None or (expanded.explicit and not previous.explicit) or expanded.score > previous.score:
                related_rows_by_path[candidate_key] = expanded
                expanded_relation_count += 1

    _log(
        log,
        "GRAPH",
        f"직접 연관 후보 {direct_relation_count}개, 정확한 참조 2단계 확장 {expanded_relation_count}개",
    )

    selected_related = _select_related_candidates(
        list(related_rows_by_path.values()),
        profiles,
        max_related,
    )
    related_count = 0
    for selected_index, row in enumerate(selected_related):
        remaining = max_context - total_chars
        slots_left = len(selected_related) - selected_index
        if remaining < 180:
            break
        budget = min(max_related_chars, max(180, remaining // max(1, slots_left)))
        try:
            content = _read_text(row.candidate.path, max(max_related_chars * 3, 24000))
        except OSError:
            continue
        excerpt = _focused_excerpt(content, row.terms, budget, focus_terms)
        if not excerpt:
            continue
        contexts.append(
            ContextFile(
                str(row.candidate.root),
                row.candidate.relative_path,
                "full" if len(content) <= budget else "focused",
                f"{row.anchor_path} 연관 근거: {row.reason}",
                row.score,
                excerpt,
            )
        )
        total_chars += len(excerpt)
        related_count += 1
        _log(
            log,
            "RELATED",
            f"{row.candidate.relative_path}: {row.anchor_path} 연관, {row.candidate_role}, 점수 {row.score}, 근거 {len(excerpt):,}자",
        )

    if changed_truncated:
        warnings.append(f"변경 파일 {changed_truncated}개의 근거가 컨텍스트 예산에 맞게 축약되었습니다.")
    if len(selected_related) > related_count:
        warnings.append("컨텍스트 예산이 소진되어 일부 연관 파일 본문을 제외했습니다.")
    _log(
        log,
        "BUDGET",
        f"컨텍스트 {total_chars:,}/{max_context:,}자 사용, 변경 {len(changes)}개, 연관 {related_count}개, 내용 검색 {content_scans}개",
    )
    if truncated:
        warnings.append("후보 파일 상한에 도달해 프로젝트 인덱스가 일부 잘렸습니다.")
    if any(item.change_type == "삭제" and item.source == "manual" for item in changes):
        warnings.append("수동 삭제 항목은 현재 소스가 없어 사용자 설명과 연관 파일을 중심으로 분석합니다.")
    unique_scanned_files = len(
        {
            str(item.path.resolve(strict=False)).casefold()
            for project_index in indexes.values()
            for item in project_index
        }
    )
    duplicate_index_entries = sum(len(index) for index in indexes.values()) - unique_scanned_files
    if duplicate_index_entries:
        warnings.append(
            f"겹치는 프로젝트 루트에서 중복 인덱스 {duplicate_index_entries}개를 한 번만 분석했습니다."
        )
    return ScanBundle(
        changes=changes,
        contexts=contexts,
        change_notes=change_notes,
        scanned_files=unique_scanned_files,
        excluded_files=excluded,
        truncated=truncated,
        warnings=warnings,
    )


def change_manifest_markdown(changes: list[ChangeItem]) -> str:
    rows = [
        "| 구분 | 파일 | 입력 근거 | 수정 시각 | 비고 |",
        "|---|---|---|---|---|",
    ]
    rows.extend(
        f"| {item.change_type} | {_markdown_cell(item.path)} | {item.source} | "
        f"{_markdown_cell(item.modified_at or '-')} | {_markdown_cell(item.note or '-')} |"
        for item in changes
    )
    return "\n".join(rows)


def _markdown_cell(value: str) -> str:
    return value.replace("|", r"\|")


def context_bundle_markdown(bundle: ScanBundle) -> str:
    sections: list[str] = [
        "# 컨텍스트 선택 요약\n\n"
        f"- 변경 항목: {len(bundle.changes)}개\n"
        f"- 선택 근거: {len(bundle.contexts)}개\n"
        f"- 후보 인덱스: {bundle.scanned_files}개\n"
        f"- 제외 파일: {bundle.excluded_files}개\n"
        f"- 경고: {'; '.join(bundle.warnings) if bundle.warnings else '없음'}"
    ]
    if bundle.change_notes:
        sections.append(
            "# 사용자 입력 변경 요약\n\n"
            + "\n".join(f"{index}. {note}" for index, note in enumerate(bundle.change_notes, 1))
        )
    for index, item in enumerate(bundle.contexts, 1):
        safe_excerpt = item.excerpt.replace("```", "` ` `")
        sections.append(
            f"## 근거 {index}: {item.path}\n\n"
            f"- 선택 방식: {item.mode}\n"
            f"- 선택 이유: {item.reason}\n"
            f"- 연관 점수: {item.score}\n"
            f"- 본문 길이: {len(item.excerpt)}자\n\n"
            f"```text\n{safe_excerpt}\n```"
        )
    return "\n\n".join(sections)


def write_scan_artifacts(bundle: ScanBundle, run_directory: Path) -> None:
    run_directory.mkdir(parents=True, exist_ok=True)
    (run_directory / "change_manifest.json").write_text(
        json.dumps([item.__dict__ for item in bundle.changes], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_directory / "project_scan_summary.json").write_text(
        json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_directory / "context_bundle.md").write_text(
        context_bundle_markdown(bundle),
        encoding="utf-8",
    )
