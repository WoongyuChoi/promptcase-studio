from __future__ import annotations

import re
from pathlib import PurePosixPath


DEFAULT_PROGRAM_CATEGORY = "채산관리시스템"
DEFAULT_DETAIL_CATEGORY = "Program"

_SQL_EXTENSIONS = {
    ".asddls",
    ".cds",
    ".dcls",
    ".ddl",
    ".ddls",
    ".dml",
    ".hdbfunction",
    ".hdbprocedure",
    ".hdbsequence",
    ".hdbsynonym",
    ".hdbtable",
    ".hdbview",
    ".pkb",
    ".pks",
    ".pls",
    ".plsql",
    ".psql",
    ".sql",
}
_SQL_XML_DIRECTORY = re.compile(
    r"(?:^|/)(?:mapper|mappers|mybatis|queries|query|sql|sqlmap)(?:/|$)"
)


def normalize_program_category(value: object) -> str:
    category = str(value or "").strip()
    return category or DEFAULT_PROGRAM_CATEGORY


def classify_program_detail(path: str) -> str:
    """Classify manifest files for the program-information detail column."""
    normalized = str(path).replace("\\", "/").casefold()
    file_path = PurePosixPath(normalized)
    if file_path.suffix in _SQL_EXTENSIONS:
        return "SQL"
    if file_path.suffix == ".xml" and (
        file_path.stem.endswith("mapper")
        or _SQL_XML_DIRECTORY.search(normalized)
    ):
        return "SQL"
    return DEFAULT_DETAIL_CATEGORY


def build_work_content(change_type: str, detail_category: str) -> str:
    """Build a concise work description from local change evidence."""
    detail = str(detail_category or DEFAULT_DETAIL_CATEGORY).strip()
    noun = "프로그램" if detail.casefold() == "program" else detail
    descriptions = {
        "신규": f"요건 변경에 따른 신규 {noun} 추가",
        "삭제": f"요건 변경에 따른 불필요 {noun} 삭제",
        "이름변경": f"요건 변경에 따른 {noun} 명칭 및 참조 경로 변경",
        "변경": (
            "요건 변경에 따른 개발 프로그램 수정"
            if noun == "프로그램"
            else f"요건 변경에 따른 {noun} 수정"
        ),
    }
    return descriptions.get(
        str(change_type or "").strip(),
        descriptions["변경"],
    )
