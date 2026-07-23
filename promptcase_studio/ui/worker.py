from __future__ import annotations

import traceback
from datetime import date
from pathlib import Path
from typing import Any

from PyQt5.QtCore import QThread, pyqtSignal

from promptcase_studio.models import AnalysisRequest, ChangeItem
from promptcase_studio.pipeline import PipelinePausedError, run_pipeline
from promptcase_studio.scanner import collect_git_changes


def _git_change_input_line(item: ChangeItem) -> str:
    absolute = (Path(item.root) / Path(item.path)).resolve(strict=False)
    return f"{item.change_type}: {absolute}"


class PipelineWorker(QThread):
    log_message = pyqtSignal(str, str)
    response_chunk = pyqtSignal(str)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, request: AnalysisRequest, settings: dict[str, Any]):
        super().__init__()
        self.request = request
        self.settings = settings

    def run(self) -> None:
        try:
            result = run_pipeline(
                self.request,
                self.settings,
                log=lambda level, message: self.log_message.emit(level, message),
                on_chunk=self.response_chunk.emit,
            )
            self.completed.emit(result)
        except PipelinePausedError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # GUI 경계에서 traceback을 run console에 남긴다.
            self.log_message.emit("ERROR", str(exc))
            self.log_message.emit("TRACE", traceback.format_exc())
            self.failed.emit(str(exc))


class GitDiffWorker(QThread):
    log_message = pyqtSignal(str, str)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        roots: list[Path],
        date_from: date | None,
        date_to: date | None,
    ):
        super().__init__()
        self.roots = roots
        self.date_from = date_from
        self.date_to = date_to

    def run(self) -> None:
        try:
            records: list[str] = []
            for root in self.roots:
                changes = collect_git_changes(
                    root,
                    self.date_from,
                    self.date_to,
                    lambda level, message: self.log_message.emit(level, message),
                )
                records.extend(_git_change_input_line(item) for item in changes)
            self.completed.emit(list(dict.fromkeys(records)))
        except Exception as exc:
            self.log_message.emit("ERROR", str(exc))
            self.log_message.emit("TRACE", traceback.format_exc())
            self.failed.emit(str(exc))
