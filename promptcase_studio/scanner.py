from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, time
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
    ".jsx",
    ".ts",
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

STATUS_PRIORITY = {"삭제": 4, "이름변경": 3, "신규": 2, "변경": 1}

SENSITIVE_ASSIGNMENT = re.compile(
    r'''(?im)(\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|password|passwd)\b["']?\s*[:=]\s*)(["']?)([^\s"',;}{]{8,})(["']?)'''
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


def _log(callback: LogCallback | None, level: str, message: str) -> None:
    if callback:
        callback(level, message)


def _is_allowed_file(path: Path) -> bool:
    name = path.name.casefold()
    if name.startswith(".env") or name in {".npmrc", ".pypirc", "settings.xml"}:
        return False
    if any(part in name for part in SENSITIVE_NAME_PARTS):
        return False
    if path.suffix.casefold() in {".key", ".pem", ".p12", ".pfx", ".jks"}:
        return False
    return path.suffix.casefold() in ALLOWED_SUFFIXES or name in ALLOWED_NAMES


def _safe_relative(root: Path, path: Path) -> str | None:
    try:
        return path.resolve(strict=False).relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def _read_text(path: Path, max_chars: int = 0) -> str:
    data = path.read_bytes()
    if max_chars > 0:
        data = data[: max_chars * 4]
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            text = data.decode(encoding)
            text = _redact_sensitive_text(text)
            return text[:max_chars] if max_chars > 0 else text
        except UnicodeDecodeError:
            continue
    return _redact_sensitive_text(data.decode("utf-8", errors="replace"))[:max_chars or None]


def _redact_sensitive_text(text: str) -> str:
    def redact_assignment(match: re.Match[str]) -> str:
        return f"{match.group(1)}{match.group(2)}[REDACTED]{match.group(4)}"

    redacted = SENSITIVE_ASSIGNMENT.sub(redact_assignment, text)
    redacted = BEARER_VALUE.sub(r"\1[REDACTED]", redacted)
    return SENSITIVE_XML_VALUE.sub(r"\1[REDACTED]\2", redacted)


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


def collect_git_changes(
    root: Path,
    since_date: date | None = None,
    log: LogCallback | None = None,
) -> list[ChangeItem]:
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

        status_text = _run_git(
            root,
            ["-c", "core.quotepath=false", "status", "--porcelain=v1", "--untracked-files=all"],
        )
        for line in status_text.splitlines():
            if len(line) < 4:
                continue
            raw_status = line[:2]
            raw_path = line[3:].strip().strip('"')
            if " -> " in raw_path:
                raw_path = raw_path.split(" -> ", 1)[1]
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
                )
            )

        if since_date:
            history = _run_git(
                root,
                [
                    "-c",
                    "core.quotepath=false",
                    "log",
                    f"--since={since_date.isoformat()}",
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


def collect_date_changes(index: Iterable[IndexedFile], since_date: date) -> list[ChangeItem]:
    threshold = datetime.combine(since_date, time.min).timestamp()
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
        if item.modified_at >= threshold
    ]


def parse_manual_changes(text: str) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    pattern = re.compile(
        r"^(신규|추가|수정|변경|삭제|이름변경|A|M|D|R)\s*(?:[:：|\t]|\s+-\s+|\s+)\s*(.+)$",
        re.IGNORECASE,
    )
    type_map = {"신규": "신규", "추가": "신규", "A": "신규", "수정": "변경", "변경": "변경", "M": "변경", "삭제": "삭제", "D": "삭제", "이름변경": "이름변경", "R": "이름변경"}
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("-*○• ").strip()
        if not line:
            continue
        match = pattern.match(line)
        if match:
            change_type = type_map[match.group(1).upper() if len(match.group(1)) == 1 else match.group(1)]
            path_text = match.group(2).strip().strip('"').strip("'")
        else:
            change_type = "변경"
            path_text = line.strip('"').strip("'")
        if path_text:
            records.append((change_type, path_text))
    return records


def resolve_manual_changes(
    root: Path,
    index: list[IndexedFile],
    manual_records: list[tuple[str, str]],
    allow_missing: bool = True,
) -> list[ChangeItem]:
    by_relative = {item.relative_path.casefold(): item for item in index}
    by_name: dict[str, list[IndexedFile]] = {}
    for item in index:
        by_name.setdefault(item.path.name.casefold(), []).append(item)

    result: list[ChangeItem] = []
    for change_type, raw_path in manual_records:
        normalized = raw_path.replace("\\", "/").lstrip("./")
        exact = by_relative.get(normalized.casefold())
        matches = [exact] if exact else by_name.get(Path(normalized).name.casefold(), [])
        if matches:
            for item in matches:
                result.append(
                    ChangeItem(
                        root=str(root),
                        path=item.relative_path,
                        change_type=change_type,
                        source="manual",
                        exists=True,
                        modified_at=datetime.fromtimestamp(item.modified_at).isoformat(timespec="seconds"),
                        note="파일명 다중 매칭" if len(matches) > 1 else "",
                    )
                )
            continue

        candidate = Path(raw_path)
        if candidate.is_absolute():
            relative = _safe_relative(root, candidate)
        else:
            relative = normalized
        scoped_absolute = candidate.is_absolute() and relative is not None
        if relative and (allow_missing or scoped_absolute or (root / relative).exists()):
            result.append(
                ChangeItem(
                    root=str(root),
                    path=relative,
                    change_type=change_type,
                    source="manual",
                    exists=(root / relative).exists(),
                    modified_at=_modified_iso(root / relative),
                    note="현재 폴더에서 찾지 못함" if not (root / relative).exists() else "",
                )
            )
    return result


def _merge_changes(changes: Iterable[ChangeItem]) -> list[ChangeItem]:
    merged: dict[tuple[str, str], ChangeItem] = {}
    source_priority = {"manual": 4, "git-working-tree": 3, "git-history": 2, "modified-date": 1}
    for item in changes:
        key = item.key()
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
    since_date: date | None,
    include_git: bool,
    scanner_settings: dict[str, Any],
    log: LogCallback | None = None,
) -> tuple[list[ChangeItem], dict[str, list[IndexedFile]], int, bool]:
    all_changes: list[ChangeItem] = []
    indexes: dict[str, list[IndexedFile]] = {}
    excluded_total = 0
    truncated = False
    manual_records = parse_manual_changes(manual_text)

    for root_index, root in enumerate(roots):
        index, excluded, was_truncated = build_project_index(
            root,
            int(scanner_settings.get("maxCandidateFiles", 10000)),
            log,
        )
        indexes[str(root)] = index
        excluded_total += excluded
        truncated = truncated or was_truncated
        if include_git:
            all_changes.extend(collect_git_changes(root, since_date, log))
        if since_date:
            date_changes = collect_date_changes(index, since_date)
            all_changes.extend(date_changes)
            _log(log, "DATE", f"{root.name}: {since_date.isoformat()} 이후 파일 {len(date_changes)}개")
        all_changes.extend(resolve_manual_changes(root, index, manual_records, allow_missing=root_index == 0))

    return _merge_changes(all_changes), indexes, excluded_total, truncated


def _extract_terms(path: Path, text: str) -> list[str]:
    values: set[str] = {path.stem}
    patterns = [
        r"\bimport\s+(?:static\s+)?([\w.]+)",
        r"\bfrom\s+['\"]([^'\"]+)['\"]",
        r"\b(?:from|import)\s+([\w.]+)",
        r"\b(?:resultType|parameterType|namespace|refid)\s*=\s*['\"]([^'\"]+)['\"]",
        r"\b(?:class|interface|enum|type)\s+([A-Z][A-Za-z0-9_]+)",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, text):
            value = match.split("/")[-1].split(".")[-1]
            value = re.sub(r"[^A-Za-z0-9_가-힣-]", "", value)
            if len(value) >= 3 and value.casefold() not in NOISE_TERMS:
                values.add(value)
    for identifier in re.findall(r"\b[A-Z][A-Za-z0-9_]{3,}\b", text[:20000]):
        if identifier.casefold() not in NOISE_TERMS:
            values.add(identifier)
        if len(values) >= 80:
            break
    return sorted(values, key=lambda value: (-len(value), value.casefold()))[:80]


def _focused_excerpt(text: str, terms: list[str], max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    lines = text.splitlines()
    lowered_terms = [term.casefold() for term in terms[:30]]
    selected: set[int] = set()
    for index, line in enumerate(lines):
        lowered = line.casefold()
        if any(term in lowered for term in lowered_terms):
            selected.update(range(max(0, index - 7), min(len(lines), index + 8)))
        if len(selected) > 240:
            break
    if not selected:
        return text[:max_chars]

    output: list[str] = []
    previous = -2
    for index in sorted(selected):
        if index > previous + 1:
            output.append("... omitted ...")
        output.append(f"{index + 1:>5}: {lines[index]}")
        previous = index
        if sum(len(line) + 1 for line in output) >= max_chars:
            break
    return "\n".join(output)[:max_chars]


def _git_diff(root: Path, relative_path: str, since_date: date | None) -> str:
    chunks: list[str] = []
    try:
        working = _run_git(root, ["diff", "--no-ext-diff", "--unified=3", "--", relative_path])
        cached = _run_git(root, ["diff", "--cached", "--no-ext-diff", "--unified=3", "--", relative_path])
        if working.strip():
            chunks.append(working)
        if cached.strip():
            chunks.append(cached)
        if since_date and not chunks:
            base = _run_git(root, ["rev-list", "-1", f"--before={since_date.isoformat()}", "HEAD"]).strip()
            if base:
                historical = _run_git(root, ["diff", "--no-ext-diff", "--unified=3", base, "HEAD", "--", relative_path])
                if historical.strip():
                    chunks.append(historical)
    except (OSError, subprocess.CalledProcessError):
        return ""
    return _redact_sensitive_text("\n".join(chunks))[:16000]


def _related_score(candidate: IndexedFile, changed_path: Path, terms: list[str], content: str = "") -> int:
    score = 0
    relative_lower = candidate.relative_path.casefold()
    for term in terms[:40]:
        term_lower = term.casefold()
        if candidate.stem.casefold() == term_lower:
            score += 18
        elif term_lower in candidate.path.name.casefold():
            score += 7
        elif term_lower in relative_lower:
            score += 3
        if content and term_lower in content.casefold():
            score += 2
    if candidate.path.parent == changed_path.parent:
        score += 5
    elif candidate.path.parent.name == changed_path.parent.name:
        score += 2
    return score


def build_scan_bundle(
    roots: list[Path],
    manual_text: str,
    since_date: date | None,
    include_git: bool,
    scanner_settings: dict[str, Any],
    log: LogCallback | None = None,
) -> ScanBundle:
    changes, indexes, excluded, truncated = collect_changes(
        roots,
        manual_text,
        since_date,
        include_git,
        scanner_settings,
        log,
    )
    if not changes:
        raise ValueError("변경 파일을 찾지 못했습니다. 날짜, Git Diff 또는 수동 목록을 확인해 주세요.")

    max_changed = int(scanner_settings.get("maxChangedFileChars", 24000))
    max_related = int(scanner_settings.get("maxRelatedFiles", 12))
    max_related_chars = int(scanner_settings.get("maxRelatedFileChars", 7000))
    max_context = int(scanner_settings.get("maxContextChars", 70000))
    contexts: list[ContextFile] = []
    total_chars = 0
    changed_keys = {item.key() for item in changes}
    aggregate_terms: dict[str, set[str]] = {str(root): set() for root in roots}

    for change in changes:
        root = Path(change.root)
        path = root / change.path
        if not change.exists or not path.exists():
            contexts.append(
                ContextFile(change.root, change.path, "metadata", "삭제 또는 현재 미존재 파일", 100, "")
            )
            continue
        if not _is_allowed_file(path):
            contexts.append(
                ContextFile(change.root, change.path, "excluded", "민감정보 또는 비지원 파일명", 100, "")
            )
            continue
        try:
            full_text = _read_text(path)
        except OSError as exc:
            contexts.append(ContextFile(change.root, change.path, "error", f"읽기 실패: {exc}", 100, ""))
            continue
        terms = _extract_terms(path, full_text)
        aggregate_terms.setdefault(change.root, set()).update(terms)
        excerpt = _focused_excerpt(full_text, terms, max_changed)
        mode = "full" if len(full_text) <= max_changed else "focused"
        if change.source.startswith("git"):
            diff = _git_diff(root, change.path, since_date)
            if diff:
                excerpt = f"[CURRENT SOURCE]\n{excerpt}\n\n[GIT DIFF]\n{diff}"
                mode += "+diff"
        excerpt = excerpt[: max_changed + 16000]
        if total_chars + len(excerpt) <= max_context:
            contexts.append(ContextFile(change.root, change.path, mode, "변경 파일 우선 근거", 100, excerpt))
            total_chars += len(excerpt)

    related_candidates: list[tuple[int, IndexedFile, list[str]]] = []
    for root_text, index in indexes.items():
        terms = sorted(aggregate_terms.get(root_text, set()), key=lambda value: (-len(value), value.casefold()))[:100]
        changed_paths = [Path(item.root) / item.path for item in changes if item.root == root_text]
        for candidate_index, candidate in enumerate(index):
            if (root_text.casefold(), candidate.relative_path.casefold()) in changed_keys:
                continue
            base_score = max(
                (_related_score(candidate, changed_path, terms) for changed_path in changed_paths),
                default=0,
            )
            content = ""
            if base_score > 0 or candidate_index < 500:
                try:
                    content = _read_text(candidate.path, 18000)
                except OSError:
                    content = ""
            score = max(
                (_related_score(candidate, changed_path, terms, content) for changed_path in changed_paths),
                default=0,
            )
            if score >= 4:
                related_candidates.append((score, candidate, terms))

    related_candidates.sort(key=lambda row: (-row[0], row[1].relative_path.casefold()))
    related_count = 0
    for score, candidate, terms in related_candidates:
        if related_count >= max_related or total_chars >= max_context:
            break
        try:
            content = _read_text(candidate.path)
        except OSError:
            continue
        excerpt = _focused_excerpt(content, terms, max_related_chars)
        if total_chars + len(excerpt) > max_context:
            continue
        contexts.append(
            ContextFile(
                str(candidate.root),
                candidate.relative_path,
                "full" if len(content) <= max_related_chars else "focused",
                "import 파일명 동일 디렉터리 또는 content reference 점수",
                score,
                excerpt,
            )
        )
        total_chars += len(excerpt)
        related_count += 1

    _log(log, "CONTEXT", f"변경 {len(changes)}개, 관련 근거 {related_count}개, 총 {total_chars:,}자 선정")
    warnings: list[str] = []
    if truncated:
        warnings.append("후보 파일 상한에 도달해 프로젝트 인덱스가 일부 잘렸습니다.")
    if any(item.change_type == "삭제" and item.source == "manual" for item in changes):
        warnings.append("수동 삭제 항목은 현재 소스가 없어 사용자 설명과 연관 파일을 중심으로 분석합니다.")
    return ScanBundle(
        changes=changes,
        contexts=contexts,
        scanned_files=sum(len(index) for index in indexes.values()),
        excluded_files=excluded,
        truncated=truncated,
        warnings=warnings,
    )


def change_manifest_markdown(changes: list[ChangeItem]) -> str:
    rows = ["| 구분 | 파일 | 입력 근거 |", "|---|---|---|"]
    rows.extend(
        f"| {item.change_type} | {_markdown_cell(item.path)} | {item.source} |"
        for item in changes
    )
    return "\n".join(rows)


def _markdown_cell(value: str) -> str:
    return value.replace("|", r"\|")


def context_bundle_markdown(bundle: ScanBundle) -> str:
    sections: list[str] = []
    for item in bundle.contexts:
        safe_excerpt = item.excerpt.replace("```", "` ` `")
        sections.append(
            f"## {item.path}\n\n- mode: {item.mode}\n- reason: {item.reason}\n- score: {item.score}\n\n```text\n{safe_excerpt}\n```"
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
