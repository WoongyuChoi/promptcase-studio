from __future__ import annotations

import traceback
from typing import Any

from PyQt5.QtCore import QThread, pyqtSignal

from promptcase_studio.models import AnalysisRequest
from promptcase_studio.pipeline import run_pipeline


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
        except Exception as exc:  # GUI 경계에서 traceback을 run console에 남긴다.
            self.log_message.emit("ERROR", str(exc))
            self.log_message.emit("TRACE", traceback.format_exc())
            self.failed.emit(str(exc))

