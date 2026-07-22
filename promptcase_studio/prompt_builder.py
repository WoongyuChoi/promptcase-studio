from __future__ import annotations

import json
from pathlib import Path

from promptcase_studio.config import PROJECT_ROOT
from promptcase_studio.models import ScanBundle
from promptcase_studio.scanner import change_manifest_markdown, context_bundle_markdown


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def build_prompt(bundle: ScanBundle, request_text: str) -> str:
    system_prompt = _read(PROJECT_ROOT / "prompts" / "system.md").strip()
    task_template = _read(PROJECT_ROOT / "prompts" / "unit_test_generation.md")
    schema = json.loads(_read(PROJECT_ROOT / "schemas" / "test_case_response.schema.json"))
    task_prompt = (
        task_template.replace("{{REQUEST_TEXT}}", request_text.strip())
        .replace("{{CHANGE_MANIFEST}}", change_manifest_markdown(bundle.changes))
        .replace("{{CONTEXT_BUNDLE}}", context_bundle_markdown(bundle))
        .replace("{{OUTPUT_SCHEMA}}", json.dumps(schema, ensure_ascii=False, indent=2))
    )
    return f"{system_prompt}\n\n---\n\n{task_prompt.strip()}\n"

