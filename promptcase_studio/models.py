from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable


LogCallback = Callable[[str, str], None]
ChunkCallback = Callable[[str], None]


@dataclass
class ChangeItem:
    root: str
    path: str
    change_type: str
    source: str
    exists: bool
    modified_at: str = ""
    note: str = ""

    def key(self) -> tuple[str, str]:
        return (self.root.casefold(), self.path.replace("\\", "/").casefold())


@dataclass
class ContextFile:
    root: str
    path: str
    mode: str
    reason: str
    score: int
    excerpt: str


@dataclass
class ScanBundle:
    changes: list[ChangeItem] = field(default_factory=list)
    contexts: list[ContextFile] = field(default_factory=list)
    change_notes: list[str] = field(default_factory=list)
    scanned_files: int = 0
    excluded_files: int = 0
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AnalysisRequest:
    project_roots: list[Path]
    manual_changes: str
    request_text: str
    environment: str
    date_from: date | None = None
    date_to: date | None = None
    include_git: bool = True


@dataclass
class PipelineResult:
    run_id: str
    run_directory: Path
    document_path: Path
    suggested_filename: str
    response_path: Path
    scan_bundle: ScanBundle
