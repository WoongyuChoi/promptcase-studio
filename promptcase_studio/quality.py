from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from promptcase_studio.models import ChangeItem


REPORT_VERSION = "1.3"

_WORD_RE = re.compile(r"[A-Za-z]+(?:\d+[A-Za-z0-9]*)?|\d+|[가-힣]+")
_CAMEL_BOUNDARY_1 = re.compile(r"([A-Z]+)([A-Z][a-z])")
_CAMEL_BOUNDARY_2 = re.compile(r"([a-z0-9])([A-Z])")
_SPACE_RE = re.compile(r"\s+")

_KOREAN_SUFFIXES = (
    "으로부터",
    "에서부터",
    "되어야",
    "되어",
    "돼야",
    "하면서",
    "으로",
    "에서",
    "에게",
    "까지",
    "부터",
    "처럼",
    "보다",
    "이나",
    "이며",
    "하고",
    "하면",
    "되면",
    "으면",
    "되는",
    "없는",
    "없이",
    "한다",
    "된다",
    "했다",
    "한다면",
    "된",
    "하는",
    "한",
    "이",
    "가",
    "을",
    "를",
    "은",
    "는",
    "의",
    "에",
    "와",
    "과",
    "도",
    "만",
    "로",
)

_ALIASES = {
    "alert": "alert",
    "알림": "alert",
    "경고": "alert",
    "lock": "lock",
    "locked": "lock",
    "잠금": "lock",
    "save": "save",
    "저장": "save",
    "delete": "delete",
    "deleted": "delete",
    "remove": "delete",
    "removed": "delete",
    "삭제": "delete",
    "제거": "delete",
    "permission": "permission",
    "authorization": "permission",
    "권한": "permission",
    "인가": "permission",
    "query": "query",
    "search": "query",
    "조회": "query",
    "error": "error",
    "exception": "error",
    "오류": "error",
    "에러": "error",
    "예외": "error",
    "edge": "edge",
    "연결선": "edge",
    "node": "node",
    "노드": "node",
    "menu": "menu",
    "메뉴": "menu",
    "rename": "rename",
    "이름변경": "rename",
    "user": "user",
    "사용자": "user",
    "session": "session",
    "세션": "session",
    "absent": "absent",
    "없": "absent",
}

_GENERIC_TOKENS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "to",
    "of",
    "for",
    "in",
    "on",
    "is",
    "are",
    "be",
    "verify",
    "confirm",
    "check",
    "test",
    "function",
    "result",
    "change",
    "data",
    "normal",
    "기능",
    "결과",
    "확인",
    "확인한다",
    "변경",
    "변경사항",
    "사항",
    "적용",
    "처리",
    "테스트",
    "데이터",
    "정상",
    "동작",
    "대상",
    "관련",
    "여부",
    "사용",
    "준비",
}

_STRUCTURAL_FILE_TOKENS = {
    "api",
    "assembler",
    "canvas",
    "client",
    "component",
    "constant",
    "controller",
    "dao",
    "dto",
    "editor",
    "entity",
    "facade",
    "handler",
    "handlers",
    "header",
    "hook",
    "impl",
    "layout",
    "mapper",
    "modal",
    "model",
    "page",
    "policy",
    "provider",
    "repository",
    "request",
    "response",
    "service",
    "store",
    "support",
    "types",
    "util",
    "utils",
    "validator",
    "view",
    "vo",
}

_GENERIC_FILE_STEMS = {
    "application",
    "config",
    "constant",
    "constants",
    "data",
    "index",
    "main",
    "package",
    "readme",
    "settings",
    "types",
}
_DOCUMENTATION_SUFFIXES = {".adoc", ".md", ".rst"}

_IMPLEMENTATION_ARTIFACT = re.compile(
    r"(?:클래스|객체|쿼리|메서드|파일|소스\s*코드|빈|컴포넌트|서비스\s*객체|매퍼\s*파일|"
    r"\bclass\b|\bobject\b|\bquery\b|\bmethod\b|\bfile\b|\bsource\s*code\b|"
    r"\bbean\b|\bcomponent\b)",
    re.IGNORECASE,
)
_IMPLEMENTATION_STATE = re.compile(
    r"(?:구현|작성|생성|정의|선언|등록|구성|존재|로딩|로드|초기화|빌드|배포|"
    r"implement(?:ed|ation)?|written|created|defined|declared|registered|configured|"
    r"initiali[sz]ed|built|deployed|exists?)",
    re.IGNORECASE,
)
_PRECONDITION_REQUIREMENT = re.compile(
    r"(?:되어\s*있어야\s*한다|돼\s*있어야\s*한다|되어야\s*한다|돼야\s*한다|"
    r"존재해야\s*한다|있어야\s*한다|must\s+be|should\s+be|has\s+to\s+be|"
    r"needs?\s+to\s+be|required\s+to\s+be)",
    re.IGNORECASE,
)

_CATEGORY_LABELS = {
    "normal": "정상 흐름",
    "negative": "부정 조건",
    "boundary": "경계값",
    "permission": "권한",
    "error": "오류와 예외",
    "deletion": "삭제 영향",
    "regression": "회귀 영향",
}

_CATEGORY_SIGNAL_PATTERNS = {
    "negative": re.compile(
        r"없(?:으면|는|을|이)|미존재|미입력|누락|중복|잘못|불가|거부|제외|비활성|"
        r"no\s+change|invalid|inactive|missing|duplicate|reject|deny|not\s+found",
        re.IGNORECASE,
    ),
    "boundary": re.compile(
        r"최대|최소|상한|하한|경계|초과|미만|이상|이하|빈\s*값|널|"
        r"\bmax(?:imum)?\b|\bmin(?:imum)?\b|boundary|limit|threshold|empty|null|zero",
        re.IGNORECASE,
    ),
    "permission": re.compile(
        r"권한|역할|관리자|인증|인가|로그인|세션|접근\s*제어|"
        r"permission|authorization|authentication|role|login|session|access\s*control",
        re.IGNORECASE,
    ),
    "error": re.compile(
        r"오류|에러|예외|경고|알림|실패|재시도|타임아웃|alert|error|exception|"
        r"warning|failure|retry|timeout",
        re.IGNORECASE,
    ),
    "deletion": re.compile(r"삭제|제거|폐기|drop|delete|remove", re.IGNORECASE),
    "regression": re.compile(
        r"기존|영향|회귀|호환|유지|리팩터|이름\s*변경|rename|refactor|regression|compatib",
        re.IGNORECASE,
    ),
}

_CATEGORY_COVERAGE_PATTERNS = {
    "negative": _CATEGORY_SIGNAL_PATTERNS["negative"],
    "boundary": _CATEGORY_SIGNAL_PATTERNS["boundary"],
    "permission": _CATEGORY_SIGNAL_PATTERNS["permission"],
    "error": _CATEGORY_SIGNAL_PATTERNS["error"],
    "deletion": _CATEGORY_SIGNAL_PATTERNS["deletion"],
    "regression": _CATEGORY_SIGNAL_PATTERNS["regression"],
}

_MANIFEST_ONLY_NOTE = re.compile(
    r"^\s*(?:변경|신규|삭제|제거|이름변경|added?|modified|deleted?|removed?|renamed?)"
    r"(?:\s*[:：]\s*|\s+)(?:[A-Za-z]:)?[^:;\r\n]+\.[A-Za-z0-9]{1,12}\s*$",
    re.IGNORECASE,
)
_EXPLICIT_SCENARIO_RULES = {
    "active": {
        "label": "활성 조건",
        "source": re.compile(r"(?<!비)활성(?:\s*상태|\s*사용자|\s*조건)?|\bactive\b", re.IGNORECASE),
        "procedure": re.compile(r"(?<!비)활성|\bactive\b", re.IGNORECASE),
        "outcome": re.compile(r"(?<!비)활성|\bactive\b", re.IGNORECASE),
    },
    "inactive": {
        "label": "비활성 조건",
        "source": re.compile(r"비활성|\binactive\b|ACTIVE\s*상태가\s*아닌", re.IGNORECASE),
        "procedure": re.compile(r"비활성|\binactive\b|ACTIVE\s*상태가\s*아닌", re.IGNORECASE),
        "outcome": re.compile(
            r"비활성|\binactive\b|ACTIVE\s*상태가\s*아닌|"
            r"(?<!비)활성(?:\s*상태|\s*사용자)?만",
            re.IGNORECASE,
        ),
    },
    "no_change": {
        "label": "변경 없음 조건",
        "source": re.compile(r"변경(?:된|한)?\s*사항(?:이)?\s*없|변경\s*없음|\bno\s+change\b", re.IGNORECASE),
        "procedure": re.compile(r"변경(?:된|한)?\s*사항(?:이)?\s*없|변경\s*없음|\bno\s+change\b", re.IGNORECASE),
        "outcome": re.compile(r"변경\s*없음|알림|경고|차단|저장되지|\bno\s+change\b", re.IGNORECASE),
    },
    "save": {
        "label": "저장 동작",
        "source": re.compile(r"저장|\bsave\b", re.IGNORECASE),
        "procedure": re.compile(r"저장|\bsave\b", re.IGNORECASE),
        "outcome": re.compile(r"저장|반영|갱신|유지|차단|알림|메시지|\bsave\b", re.IGNORECASE),
    },
    "query_condition": {
        "label": "조회조건 동작",
        "source": re.compile(r"조회\s*조건|검색\s*조건|조건.{0,12}조회|\bquery\s+condition\b|\bsearch\s+condition\b", re.IGNORECASE),
        "procedure": re.compile(r"조회|검색|조건|\bquery\b|\bsearch\b", re.IGNORECASE),
        "outcome": re.compile(r"조회|검색|목록|결과|반환|표시|\bquery\b|\bsearch\b", re.IGNORECASE),
    },
    "download": {
        "label": "다운로드 동작",
        "source": re.compile(r"다운로드|내려받|\bdownload\b|\bexport\b", re.IGNORECASE),
        "procedure": re.compile(r"다운로드|내려받|\bdownload\b|\bexport\b", re.IGNORECASE),
        "outcome": re.compile(r"다운로드|파일|생성|내려받|\bdownload\b|\bexport\b", re.IGNORECASE),
    },
    "upload": {
        "label": "업로드 동작",
        "source": re.compile(r"업로드|올리기|\bupload\b|\bimport\b", re.IGNORECASE),
        "procedure": re.compile(r"업로드|올리|\bupload\b|\bimport\b", re.IGNORECASE),
        "outcome": re.compile(r"업로드|반영|등록|처리|\bupload\b|\bimport\b", re.IGNORECASE),
    },
    "delete": {
        "label": "삭제 동작",
        "source": re.compile(r"삭제|제거|\bdelete\b|\bremove\b", re.IGNORECASE),
        "procedure": re.compile(r"삭제|제거|\bdelete\b|\bremove\b", re.IGNORECASE),
        "outcome": re.compile(r"삭제|제거|제외|사라|참조되지|차단|\bdelete\b|\bremove\b", re.IGNORECASE),
    },
    "permission": {
        "label": "권한 조건",
        "source": _CATEGORY_SIGNAL_PATTERNS["permission"],
        "procedure": re.compile(r"권한|역할|계정|로그인|접근|permission|role|login|access", re.IGNORECASE),
        "outcome": re.compile(r"권한|허용|거부|차단|접근|permission|allow|deny|block|access", re.IGNORECASE),
    },
    "boundary": {
        "label": "경계값 조건",
        "source": _CATEGORY_SIGNAL_PATTERNS["boundary"],
        "procedure": _CATEGORY_SIGNAL_PATTERNS["boundary"],
        "outcome": re.compile(r"최대|최소|상한|하한|제한|초과|미만|이상|이하|max|min|limit|boundary", re.IGNORECASE),
    },
    "error": {
        "label": "오류 조건",
        "source": re.compile(r"오류|에러|예외|실패|재시도|타임아웃|error|exception|failure|retry|timeout", re.IGNORECASE),
        "procedure": re.compile(r"오류|에러|예외|잘못|실패|재시도|타임아웃|error|exception|invalid|failure|retry|timeout", re.IGNORECASE),
        "outcome": re.compile(r"오류|에러|예외|메시지|알림|경고|차단|실패|error|exception|message|alert|failure", re.IGNORECASE),
    },
    "lock": {
        "label": "잠금 동작",
        "source": re.compile(r"잠금|키보드.{0,8}(?:제어|차단)|\b(?:locked|lock)\b", re.IGNORECASE),
        "procedure": re.compile(r"잠금|키보드|입력|\b(?:locked|lock)\b", re.IGNORECASE),
        "outcome": re.compile(r"잠금|차단|입력되지|해제|\b(?:locked|lock|unlock)\b", re.IGNORECASE),
    },
}

_DISTINCT_SCENARIO_PATTERNS = {
    "active": re.compile(r"(?<!비)활성|\bactive\b", re.IGNORECASE),
    "missing": re.compile(r"미존재|존재하지\s*않|not\s+found|missing", re.IGNORECASE),
    "inactive": re.compile(
        r"비활성|ACTIVE\s*상태가\s*아닌|not\s+active|inactive",
        re.IGNORECASE,
    ),
    "empty": re.compile(r"빈\s*값|변경\s*사항이\s*없|empty|no\s+change", re.IGNORECASE),
    "permission": _CATEGORY_SIGNAL_PATTERNS["permission"],
    "error": _CATEGORY_SIGNAL_PATTERNS["error"],
    "deletion": _CATEGORY_SIGNAL_PATTERNS["deletion"],
}

_WEAK_CONFIRMATION = re.compile(
    r"(?:기능|변경\s*사항|변경사항|정상\s*동작|동작\s*여부|관련\s*(?:내용|사항))"
    r"(?:이|가|을|를|의)?\s*(?:정상적으로\s*)?(?:반영되었는지\s*)?확인한다$",
    re.IGNORECASE,
)
_ACTIONABLE_OPERATION = re.compile(
    r"입력|선택|지정|클릭|저장|조회|검색|다운로드|내려받|업로드|올리|삭제|추가|수정|등록|"
    r"변경|실행|요청|전송|로그인|진입|접근|호출|갱신|잠금|해제|재시도|취소|"
    r"enter|select|click|save|query|search|download|upload|delete|update|submit|request|login",
    re.IGNORECASE,
)
_OBSERVABLE_OUTCOME = re.compile(
    r"(?:결과|값|상태|목록|건수|메시지|알림|파일|응답|권한|오류|에러|화면).{0,24}"
    r"(?:표시|반영|저장|생성|반환|유지|차단|거부|제외|일치|확인)",
    re.IGNORECASE,
)
_DATA_LABEL_VALUE = re.compile(
    r"(?:기준\s*년도|기준년도|조직\s*코드|조직코드|사용자\s*(?:ID|아이디)|"
    r"상태\s*코드|상태코드|연도|년도|코드|ID|아이디|금액|건수)\s+"
    r"(?:[A-Za-z0-9][A-Za-z0-9_.-]*|\d+)",
    re.IGNORECASE,
)
_NATURAL_DATA_SEPARATOR = re.compile(r",|\b및\b|(?:와|과|이고|이며)(?:\s|$)")
_EXPECTED_OUTCOME_VERB = re.compile(
    r"(?:표시|반영|저장|조회|생성|반환|유지|차단|거부|제외|일치|다운로드|삭제|갱신|전환)"
    r"(?:되지\s*않|되지|되는|된다|된|되|돼|하지|한다|한|하)",
    re.IGNORECASE,
)


def _split_identifier(value: str) -> str:
    text = _CAMEL_BOUNDARY_1.sub(r"\1 \2", value)
    return _CAMEL_BOUNDARY_2.sub(r"\1 \2", text)


def _normalize_korean_token(token: str) -> str:
    if token in {"없으면", "없는", "없이", "없을", "없다"}:
        return "없"
    for suffix in _KOREAN_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 2:
            return token[: -len(suffix)]
    return token


def _tokens(value: str, *, informative_only: bool = False) -> list[str]:
    expanded = _split_identifier(str(value))
    values: list[str] = []
    for match in _WORD_RE.finditer(expanded):
        token = match.group(0).casefold()
        if re.fullmatch(r"[가-힣]+", token):
            token = _normalize_korean_token(token)
        token = _ALIASES.get(token, token)
        if len(token) < 2 and not token.isdigit():
            continue
        if informative_only and token in _GENERIC_TOKENS:
            continue
        values.append(token)
    return values


def _compact_text(value: str) -> str:
    return "".join(_tokens(value))


def _character_ngrams(value: str, size: int = 3) -> set[str]:
    compact = _compact_text(value)
    if not compact:
        return set()
    if len(compact) <= size:
        return {compact}
    return {compact[index : index + size] for index in range(len(compact) - size + 1)}


def _similarity(left: str, right: str) -> tuple[float, int]:
    left_tokens = set(_tokens(left, informative_only=True))
    right_tokens = set(_tokens(right, informative_only=True))
    shared = left_tokens & right_tokens
    union = left_tokens | right_tokens
    token_score = len(shared) / len(union) if union else 0.0

    left_ngrams = _character_ngrams(left)
    right_ngrams = _character_ngrams(right)
    denominator = len(left_ngrams) + len(right_ngrams)
    ngram_score = (
        2 * len(left_ngrams & right_ngrams) / denominator if denominator else 0.0
    )
    return max(token_score, ngram_score), len(shared)


def _is_near_duplicate(left: str, right: str) -> tuple[bool, float]:
    if min(len(left.strip()), len(right.strip())) < 10:
        return False, 0.0
    score, shared = _similarity(left, right)
    left_markers = {
        key for key, pattern in _DISTINCT_SCENARIO_PATTERNS.items() if pattern.search(left)
    }
    right_markers = {
        key for key, pattern in _DISTINCT_SCENARIO_PATTERNS.items() if pattern.search(right)
    }
    if left_markers and right_markers and left_markers.isdisjoint(right_markers):
        return False, score
    # Test procedures intentionally share a subject and an observation verb.
    # A lower threshold misclassifies distinct status and missing-data branches
    # merely because both end in the same result such as null 반환 확인.
    duplicate = score >= 0.88 or (score >= 0.7 and shared >= 2)
    return duplicate, score


def _string_sequence(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _document_lists(structured: Mapping[str, Any]) -> list[tuple[str, list[str]]]:
    test_case = structured.get("testCase")
    test_result = structured.get("testResult")
    case = test_case if isinstance(test_case, Mapping) else {}
    result = test_result if isinstance(test_result, Mapping) else {}
    processing_details = result.get("processingDetails")
    processing_values: list[str] = []
    if isinstance(processing_details, Sequence) and not isinstance(
        processing_details, (str, bytes)
    ):
        for item in processing_details:
            if not isinstance(item, Mapping):
                continue
            title = item.get("title")
            detail = item.get("detail")
            text = " ".join(
                value.strip()
                for value in (title, detail)
                if isinstance(value, str) and value.strip()
            )
            if text:
                processing_values.append(text)
    return [
        ("testCase.procedure", _string_sequence(case.get("procedure"))),
        ("testCase.preconditions", _string_sequence(case.get("preconditions"))),
        ("testResult.processingDetails", processing_values),
        ("testResult.testDetails", _string_sequence(result.get("testDetails"))),
        ("testResult.resultChecks", _string_sequence(result.get("resultChecks"))),
    ]


def find_semantic_duplicates(structured: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return likely within-field paraphrase duplicates as non-blocking issues."""

    issues: list[dict[str, Any]] = []
    for field, values in _document_lists(structured):
        for left_index, left in enumerate(values):
            for right_index in range(left_index + 1, len(values)):
                right = values[right_index]
                duplicate, score = _is_near_duplicate(left, right)
                if not duplicate:
                    continue
                issues.append(
                    {
                        "code": "semantic_duplicate",
                        "severity": "warning",
                        "fields": [f"{field}[{left_index}]", f"{field}[{right_index}]"],
                        "similarity": round(score, 3),
                        "message": "서로 다른 검증 의도인지 확인이 필요한 의미상 유사 문장이 있습니다",
                        "examples": [left, right],
                    }
                )
    return issues


def find_implementation_preconditions(structured: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Find prerequisites that merely assert that implementation artifacts exist."""

    test_case = structured.get("testCase")
    case = test_case if isinstance(test_case, Mapping) else {}
    issues: list[dict[str, Any]] = []
    for index, text in enumerate(_string_sequence(case.get("preconditions"))):
        if not (
            _IMPLEMENTATION_ARTIFACT.search(text)
            and _IMPLEMENTATION_STATE.search(text)
            and _PRECONDITION_REQUIREMENT.search(text)
        ):
            continue
        issues.append(
            {
                "code": "implementation_as_precondition",
                "severity": "warning",
                "fields": [f"testCase.preconditions[{index}]"],
                "message": "구현물의 존재 여부가 아니라 테스트 실행에 필요한 권한과 데이터 및 환경을 작성해야 합니다",
                "examples": [text],
            }
        )
    return issues


def find_non_actionable_test_steps(structured: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Find vague steps that do not tell a tester what to do or observe."""

    test_case = structured.get("testCase")
    test_result = structured.get("testResult")
    case = test_case if isinstance(test_case, Mapping) else {}
    result = test_result if isinstance(test_result, Mapping) else {}
    issues: list[dict[str, Any]] = []
    fields = (
        ("testCase.procedure", _string_sequence(case.get("procedure"))),
        ("testResult.testDetails", _string_sequence(result.get("testDetails"))),
    )
    for field, values in fields:
        for index, text in enumerate(values):
            weak_confirmation = bool(_WEAK_CONFIRMATION.search(text))
            no_operation_or_outcome = not (
                _ACTIONABLE_OPERATION.search(text) or _OBSERVABLE_OUTCOME.search(text)
            )
            if not weak_confirmation and not no_operation_or_outcome:
                continue
            issues.append(
                {
                    "code": "non_actionable_test_step",
                    "severity": "review",
                    "fields": [f"{field}[{index}]"],
                    "message": (
                        "확인 대상만 적지 말고 입력, 선택, 저장, 조회, 다운로드 같은 실제 조작과 "
                        "사용자가 판정할 결과를 구체적으로 작성해야 합니다"
                    ),
                    "examples": [text],
                }
            )
    return issues


def find_unnatural_test_data(structured: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Find label and value chains that read like pasted keywords rather than Korean."""

    test_case = structured.get("testCase")
    case = test_case if isinstance(test_case, Mapping) else {}
    test_data = case.get("testData")
    if not isinstance(test_data, str) or not test_data.strip():
        return []
    matches = list(_DATA_LABEL_VALUE.finditer(test_data))
    if len(matches) < 2:
        return []
    missing_separator = any(
        not _NATURAL_DATA_SEPARATOR.search(
            test_data[left.end() : right.start()]
        )
        for left, right in zip(matches, matches[1:])
    )
    if not missing_separator:
        return []
    return [
        {
            "code": "keyword_like_test_data",
            "severity": "review",
            "fields": ["testCase.testData"],
            "message": (
                "테스트 데이터의 식별 가능한 값은 한국어 조사와 쉼표로 구분해 "
                "키워드 나열이 아닌 자연스러운 문장으로 작성해야 합니다"
            ),
            "examples": [test_data],
        }
    ]


def find_overloaded_expected_result(structured: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Keep the summary cell to at most two directly connected outcomes."""

    test_case = structured.get("testCase")
    case = test_case if isinstance(test_case, Mapping) else {}
    expected_result = case.get("expectedResult")
    if not isinstance(expected_result, str) or not expected_result.strip():
        return []
    outcome_count = len(list(_EXPECTED_OUTCOME_VERB.finditer(expected_result)))
    if outcome_count <= 2:
        return []
    return [
        {
            "code": "overloaded_expected_result",
            "severity": "review",
            "fields": ["testCase.expectedResult"],
            "message": (
                "예상결과는 핵심 관찰 결과 한 개 또는 직접 연결된 두 개만 남겨 두 줄 분량 안으로 작성해야 합니다"
            ),
            "outcome_count": outcome_count,
            "examples": [expected_result],
        }
    ]


def find_step_count_mismatch(structured: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Report step alignment problems as reviewable, not structural."""

    test_case = structured.get("testCase")
    test_result = structured.get("testResult")
    case = test_case if isinstance(test_case, Mapping) else {}
    result = test_result if isinstance(test_result, Mapping) else {}
    procedures = _string_sequence(case.get("procedure"))
    test_details = _string_sequence(result.get("testDetails"))
    issues: list[dict[str, Any]] = []
    if len(procedures) != len(test_details):
        issues.append(
            {
                "code": "step_count_mismatch",
                "severity": "review",
                "fields": ["testCase.procedure", "testResult.testDetails"],
                "message": (
                    "테스트 절차와 관찰 결과의 항목 수가 다릅니다. 같은 순서로 대응하는지 검토해 주세요"
                ),
                "procedure_count": len(procedures),
                "test_detail_count": len(test_details),
            }
        )
    detail_keys = {re.sub(r"\s+", " ", item).casefold() for item in test_details}
    overlap = [
        item
        for item in procedures
        if re.sub(r"\s+", " ", item).casefold() in detail_keys
    ]
    if overlap:
        issues.append(
            {
                "code": "procedure_result_overlap",
                "severity": "review",
                "fields": ["testCase.procedure", "testResult.testDetails"],
                "message": "테스트 절차와 관찰 결과에 같은 문장이 반복되어 역할 구분을 검토해야 합니다",
                "examples": overlap[:3],
            }
        )
    return issues


def find_scope_inflation(
    structured: Mapping[str, Any],
    changes: Sequence[ChangeItem | Mapping[str, Any]],
    change_notes: Sequence[str],
) -> list[dict[str, Any]]:
    """Flag likely padding when a single simple change becomes many document rows."""

    note_count = sum(bool(note.strip()) for note in change_notes)
    if len(changes) > 1 or note_count > 1 or len(changes) + note_count == 0:
        return []
    test_case = structured.get("testCase")
    test_result = structured.get("testResult")
    case = test_case if isinstance(test_case, Mapping) else {}
    result = test_result if isinstance(test_result, Mapping) else {}
    counts = {
        "testCase.procedure": len(_string_sequence(case.get("procedure"))),
        "testCase.preconditions": len(_string_sequence(case.get("preconditions"))),
        "testResult.processingDetails": len(
            result.get("processingDetails")
            if isinstance(result.get("processingDetails"), Sequence)
            and not isinstance(result.get("processingDetails"), (str, bytes))
            else []
        ),
        "testResult.testDetails": len(_string_sequence(result.get("testDetails"))),
    }
    inflated = [field for field, count in counts.items() if count > 3]
    if not inflated:
        return []
    return [
        {
            "code": "overexpanded_simple_change",
            "severity": "review",
            "fields": inflated,
            "message": (
                "단일 변경을 항목 수에 맞추어 부풀리지 말고 실제 조작과 판정에 필요한 단계만 남겨야 합니다"
            ),
            "counts": counts,
        }
    ]


def _all_document_strings(value: Any) -> list[str]:
    values: list[str] = []
    if isinstance(value, str):
        if value.strip():
            values.append(value.strip())
    elif isinstance(value, Mapping):
        for child in value.values():
            values.extend(_all_document_strings(child))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            values.extend(_all_document_strings(child))
    return values


def _reviewable_document_strings(structured: Mapping[str, Any]) -> list[str]:
    # programInfo is deterministic local metadata. File names and change types
    # listed there must not make an otherwise missing scenario look covered.
    selected = {
        key: structured.get(key)
        for key in ("documentTitle", "testCase", "testResult")
        if key in structured
    }
    return _all_document_strings(selected)


def _explicit_note_lines(change_notes: Iterable[str]) -> tuple[list[str], list[str]]:
    """Return all note lines and narrative-only lines used for hard obligations."""

    all_lines: list[str] = []
    narrative_lines: list[str] = []
    for value in change_notes:
        for raw_line in str(value).splitlines() or [str(value)]:
            line = _SPACE_RE.sub(" ", raw_line).strip()
            if not line:
                continue
            all_lines.append(line)
            if not _MANIFEST_ONLY_NOTE.fullmatch(line):
                narrative_lines.append(line)
    return all_lines, narrative_lines


def _explicit_scenarios(
    structured: Mapping[str, Any],
    change_notes: Iterable[str],
) -> dict[str, dict[str, Any]]:
    """Map each explicit user condition to an executable step and observable result."""

    _all_lines, narrative_lines = _explicit_note_lines(change_notes)
    source_text = "\n".join(narrative_lines)
    test_case = structured.get("testCase")
    case = test_case if isinstance(test_case, Mapping) else {}
    test_result = structured.get("testResult")
    result = test_result if isinstance(test_result, Mapping) else {}
    procedure_rows = _string_sequence(case.get("procedure"))
    outcome_rows = [
        *_string_sequence(result.get("testDetails")),
        *_string_sequence(result.get("resultChecks")),
    ]
    expected_result = case.get("expectedResult")
    if isinstance(expected_result, str) and expected_result.strip():
        outcome_rows.append(expected_result.strip())

    scenarios: dict[str, dict[str, Any]] = {}
    for key, rule in _EXPLICIT_SCENARIO_RULES.items():
        source_pattern = rule["source"]
        if not source_text or not source_pattern.search(source_text):
            continue
        procedure_pattern = rule["procedure"]
        outcome_pattern = rule["outcome"]
        procedure_matches = [row for row in procedure_rows if procedure_pattern.search(row)]
        outcome_matches = [row for row in outcome_rows if outcome_pattern.search(row)]
        scenarios[key] = {
            "scenario": key,
            "label": str(rule["label"]),
            "required": True,
            "covered": bool(procedure_matches and outcome_matches),
            "procedure_matches": procedure_matches[:3],
            "outcome_matches": outcome_matches[:3],
            "signal_sources": [
                line for line in narrative_lines if source_pattern.search(line)
            ][:3],
        }
    return scenarios


def _change_value(change: ChangeItem | Mapping[str, Any], name: str) -> str:
    if isinstance(change, Mapping):
        return str(change.get(name, "") or "")
    return str(getattr(change, name, "") or "")


def _clean_note(value: str) -> str:
    text = value.strip()
    text = re.sub(
        r"^\s*(?:feat|fix|refactor|change|changed|add|remove|delete|변경|신규|삭제|제거|이름변경)\s*[:：-]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return _SPACE_RE.sub(" ", text).strip()


def _anchor_terms(value: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for token in _tokens(value, informative_only=True):
        if token in _STRUCTURAL_FILE_TOKENS or token in _GENERIC_FILE_STEMS:
            continue
        if token not in seen:
            seen.add(token)
            values.append(token)
    return values[:8]


def _categories_for_text(value: str, change_type: str = "") -> list[str]:
    categories = [
        key for key, pattern in _CATEGORY_SIGNAL_PATTERNS.items() if pattern.search(value)
    ]
    normalized_type = change_type.strip().casefold()
    if normalized_type in {"삭제", "delete", "deleted", "remove", "removed"}:
        categories.append("deletion")
    if normalized_type in {"이름변경", "rename", "renamed"}:
        categories.append("regression")
    return list(dict.fromkeys(categories))


def _make_anchor(
    anchor_id: str,
    label: str,
    source: str,
    terms: list[str],
    categories: list[str],
    weight: int,
    paths: Iterable[str] = (),
) -> dict[str, Any]:
    return {
        "id": anchor_id,
        "label": label,
        "source": source,
        "terms": terms,
        "categories": categories,
        "weight": weight,
        "paths": sorted(dict.fromkeys(path for path in paths if path)),
    }


def extract_change_anchors(
    changes: Iterable[ChangeItem | Mapping[str, Any]],
    change_notes: Iterable[str],
) -> list[dict[str, Any]]:
    """Build compact, deterministic business-note and file-family anchors."""

    anchors: list[dict[str, Any]] = []
    note_seen: set[str] = set()
    note_values = [str(note) for note in change_notes if str(note).strip()]
    change_values = list(changes)
    for change in change_values:
        note = _change_value(change, "note")
        if note.strip():
            note_values.append(note)

    for note in note_values:
        label = _clean_note(note)
        if not label:
            continue
        key = _SPACE_RE.sub(" ", label).casefold()
        if key in note_seen:
            continue
        note_seen.add(key)
        terms = _anchor_terms(label)
        if not terms:
            continue
        anchors.append(
            _make_anchor(
                f"note-{len(anchors) + 1:03d}",
                label,
                "change_note",
                terms,
                _categories_for_text(label),
                3,
            )
        )

    family_rows: dict[tuple[str, ...], dict[str, Any]] = {}
    ordered_changes = sorted(
        change_values,
        key=lambda item: (
            _change_value(item, "root").casefold(),
            _change_value(item, "path").replace("\\", "/").casefold(),
            _change_value(item, "change_type").casefold(),
        ),
    )
    for change in ordered_changes:
        path = _change_value(change, "path").replace("\\", "/")
        if Path(path).suffix.casefold() in _DOCUMENTATION_SUFFIXES:
            continue
        stem = Path(path).stem
        if stem.casefold() in _GENERIC_FILE_STEMS:
            continue
        terms = _anchor_terms(stem)
        if not terms:
            continue
        # Architecture suffixes differ across layers. The first three remaining
        # domain tokens form a stable family without requiring every file name
        # to appear in the final human-facing document.
        family_key = tuple(terms[:3])
        row = family_rows.setdefault(
            family_key,
            {
                "labels": [],
                "terms": list(family_key),
                "categories": [],
                "paths": [],
                "weight": 1,
            },
        )
        row["labels"].append(stem)
        row["paths"].append(path)
        change_type = _change_value(change, "change_type")
        row["categories"].extend(_categories_for_text(f"{change_type} {stem}", change_type))
        if change_type.strip().casefold() in {
            "삭제",
            "delete",
            "deleted",
            "이름변경",
            "rename",
            "renamed",
        }:
            row["weight"] = 3

    for family_key, row in sorted(family_rows.items()):
        labels = sorted(dict.fromkeys(row["labels"]))
        label = labels[0] if len(labels) == 1 else " ".join(family_key)
        anchor_id = "family-" + "-".join(family_key)
        anchors.append(
            _make_anchor(
                anchor_id,
                label,
                "change_family",
                row["terms"],
                list(dict.fromkeys(row["categories"])),
                max(row["weight"], 2 if len(row["paths"]) >= 3 else 1),
                row["paths"],
            )
        )
    return anchors


def _cover_anchor(anchor: Mapping[str, Any], document_tokens: set[str]) -> dict[str, Any]:
    terms = [str(term) for term in anchor.get("terms", []) if str(term)]
    matched = [term for term in terms if term in document_tokens]
    if not terms:
        covered = False
    elif anchor.get("source") == "change_note":
        required = 1 if len(terms) == 1 else max(2, math.ceil(len(terms) * 0.4))
        covered = len(matched) >= required
    elif len(terms) == 1:
        covered = len(matched) == 1
    else:
        covered = len(matched) >= min(2, len(terms))
    result = dict(anchor)
    result["matched_terms"] = matched
    result["covered"] = covered
    return result


def _scenario_categories(
    structured: Mapping[str, Any],
    changes: Sequence[ChangeItem | Mapping[str, Any]],
    change_notes: Sequence[str],
) -> dict[str, dict[str, Any]]:
    note_rows, explicit_note_rows = _explicit_note_lines(change_notes)
    change_rows: list[str] = []
    for change in changes:
        change_rows.append(
            " ".join(
                value
                for value in (
                    _change_value(change, "change_type"),
                    _change_value(change, "path"),
                    _change_value(change, "note"),
                )
                if value
            )
        )
    source_rows = [*note_rows, *change_rows]
    output_rows = _reviewable_document_strings(structured)
    output_text = "\n".join(output_rows)
    procedure_count = len(
        _string_sequence(
            (structured.get("testCase") or {}).get("procedure")
            if isinstance(structured.get("testCase"), Mapping)
            else None
        )
    )

    categories: dict[str, dict[str, Any]] = {}
    normal_detected = bool(source_rows or changes)
    categories["normal"] = {
        "label": _CATEGORY_LABELS["normal"],
        "detected": normal_detected,
        "covered": normal_detected and procedure_count > 0,
        "signal_sources": source_rows[:6] if normal_detected else [],
        "required": bool(explicit_note_rows),
        "output_matches": ["procedure"] if procedure_count else [],
    }
    for key, label in _CATEGORY_LABELS.items():
        if key == "normal":
            continue
        signal_pattern = _CATEGORY_SIGNAL_PATTERNS[key]
        signal_sources = [row for row in source_rows if signal_pattern.search(row)]
        explicit_sources = [row for row in explicit_note_rows if signal_pattern.search(row)]
        detected = bool(signal_sources)
        coverage_pattern = _CATEGORY_COVERAGE_PATTERNS[key]
        output_matches = sorted(
            dict.fromkeys(match.group(0) for match in coverage_pattern.finditer(output_text))
        )[:8]
        categories[key] = {
            "label": label,
            "detected": detected,
            "covered": detected and bool(output_matches),
            "signal_sources": signal_sources[:6],
            "required": bool(explicit_sources),
            "output_matches": output_matches,
        }
    return categories


def build_quality_report(
    structured: Mapping[str, Any],
    changes: Iterable[ChangeItem | Mapping[str, Any]] = (),
    change_notes: Iterable[str] = (),
) -> dict[str, Any]:
    """Create a JSON-serializable soft quality and change-coverage report."""

    change_values = list(changes)
    note_values = [str(note) for note in change_notes if str(note).strip()]
    issues = [
        *find_semantic_duplicates(structured),
        *find_implementation_preconditions(structured),
        *find_non_actionable_test_steps(structured),
        *find_unnatural_test_data(structured),
        *find_overloaded_expected_result(structured),
        *find_step_count_mismatch(structured),
        *find_scope_inflation(structured, change_values, note_values),
    ]
    explicit_scenarios = _explicit_scenarios(structured, note_values)
    uncovered_explicit_scenarios = [
        scenario for scenario in explicit_scenarios.values() if not scenario["covered"]
    ]
    for scenario in uncovered_explicit_scenarios:
        issues.append(
            {
                "code": "uncovered_explicit_scenario",
                "severity": "required",
                "scenario": scenario["scenario"],
                "message": (
                    f"사용자가 명시한 {scenario['label']}을 실행하는 절차와 관찰 가능한 판정 기준이 "
                    "모두 필요합니다"
                ),
                "signal_sources": scenario["signal_sources"],
            }
        )

    document_tokens = set(_tokens("\n".join(_reviewable_document_strings(structured))))
    anchors = [
        _cover_anchor(anchor, document_tokens)
        for anchor in extract_change_anchors(change_values, note_values)
    ]
    covered_anchors = [anchor for anchor in anchors if anchor["covered"]]
    uncovered_anchors = [anchor for anchor in anchors if not anchor["covered"]]
    actionable_uncovered_anchors = [
        anchor
        for anchor in uncovered_anchors
        if anchor.get("source") == "change_note" or not note_values
    ]
    categories = _scenario_categories(structured, change_values, note_values)
    uncovered_categories = [
        key
        for key, value in categories.items()
        if value["detected"] and not value["covered"]
    ]

    for key in uncovered_categories:
        category = categories[key]
        required = bool(category.get("required"))
        issues.append(
            {
                "code": "uncovered_scenario_category",
                "severity": "required" if required else "review",
                "category": key,
                "message": (
                    f"{'사용자 의뢰와 변경 요약' if required else '변경 근거'}에서 "
                    f"{_CATEGORY_LABELS[key]} 시나리오 신호가 확인되지만 최종 문안에서 찾지 못했습니다"
                ),
            }
        )
    if actionable_uncovered_anchors:
        issues.append(
            {
                "code": "uncovered_change_anchors",
                "severity": "review",
                "count": len(actionable_uncovered_anchors),
                "anchors": [anchor["label"] for anchor in actionable_uncovered_anchors[:8]],
                "message": "최종 문안에서 직접 확인되지 않는 핵심 변경 앵커가 있습니다",
            }
        )

    duplicate_count = sum(issue["code"] == "semantic_duplicate" for issue in issues)
    implementation_count = sum(
        issue["code"] == "implementation_as_precondition" for issue in issues
    )
    non_actionable_count = sum(
        issue["code"] == "non_actionable_test_step" for issue in issues
    )
    unnatural_data_count = sum(
        issue["code"] == "keyword_like_test_data" for issue in issues
    )
    overloaded_expected_result_count = sum(
        issue["code"] == "overloaded_expected_result" for issue in issues
    )
    scope_inflation_count = sum(
        issue["code"] == "overexpanded_simple_change" for issue in issues
    )
    step_count_mismatch_count = sum(
        issue["code"] == "step_count_mismatch" for issue in issues
    )
    procedure_result_overlap_count = sum(
        issue["code"] == "procedure_result_overlap" for issue in issues
    )
    explicit_scenario_penalty = min(30, len(uncovered_explicit_scenarios) * 10)
    actionable_anchors = [
        anchor
        for anchor in anchors
        if anchor.get("source") == "change_note" or not note_values
    ]
    total_anchor_weight = sum(int(anchor["weight"]) for anchor in actionable_anchors)
    uncovered_anchor_weight = sum(
        int(anchor["weight"]) for anchor in actionable_uncovered_anchors
    )
    anchor_penalty = (
        round(20 * uncovered_anchor_weight / total_anchor_weight)
        if total_anchor_weight
        else 0
    )
    score = max(
        0,
        100
        - min(24, duplicate_count * 8)
        - min(30, implementation_count * 10)
        - min(24, non_actionable_count * 8)
        - min(10, unnatural_data_count * 10)
        - min(10, overloaded_expected_result_count * 10)
        - min(10, scope_inflation_count * 10)
        - min(12, step_count_mismatch_count * 12)
        - min(8, procedure_result_overlap_count * 8)
        - explicit_scenario_penalty
        - min(28, len(uncovered_categories) * 7)
        - anchor_penalty,
    )
    blocking = any(
        issue.get("severity") == "required"
        for issue in issues
        if isinstance(issue, Mapping)
    )
    status = "block" if blocking else ("pass" if not issues else "review")
    return {
        "version": REPORT_VERSION,
        "score": score,
        "soft_gate": {"status": status, "blocking": blocking},
        "issues": issues,
        "covered_anchors": covered_anchors,
        "uncovered_anchors": uncovered_anchors,
        "scenario_categories": categories,
        "explicit_scenarios": explicit_scenarios,
        "metrics": {
            "semantic_duplicate_count": duplicate_count,
            "implementation_precondition_count": implementation_count,
            "non_actionable_test_step_count": non_actionable_count,
            "keyword_like_test_data_count": unnatural_data_count,
            "overloaded_expected_result_count": overloaded_expected_result_count,
            "overexpanded_simple_change_count": scope_inflation_count,
            "step_count_mismatch_count": step_count_mismatch_count,
            "procedure_result_overlap_count": procedure_result_overlap_count,
            "anchor_count": len(anchors),
            "covered_anchor_count": len(covered_anchors),
            "uncovered_anchor_count": len(uncovered_anchors),
            "detected_scenario_category_count": sum(
                bool(value["detected"]) for value in categories.values()
            ),
            "uncovered_scenario_category_count": len(uncovered_categories),
            "required_uncovered_scenario_category_count": sum(
                bool(categories[key].get("required")) for key in uncovered_categories
            ),
            "explicit_scenario_count": len(explicit_scenarios),
            "uncovered_explicit_scenario_count": len(uncovered_explicit_scenarios),
        },
    }


def quality_report_markdown(report: Mapping[str, Any], max_items: int = 8) -> str:
    """Render a bounded summary suitable for a final AI review prompt."""

    limit = max(1, min(int(max_items), 20))
    issues = list(report.get("issues", []))
    uncovered = list(report.get("uncovered_anchors", []))
    categories = report.get("scenario_categories", {})
    lines = [
        "## 자동 품질 검토",
        "",
        f"- 품질 점수: {int(report.get('score', 0))}",
        f"- 검토 항목: {len(issues)}건",
        f"- 미커버 변경 앵커: {len(uncovered)}건",
        "- 이 결과는 오탐 가능성이 있는 soft gate이며 근거를 벗어나 새 사실을 만들지 않는다",
    ]
    detected_rows = [
        value
        for value in categories.values()
        if isinstance(value, Mapping) and value.get("detected")
    ] if isinstance(categories, Mapping) else []
    if detected_rows:
        lines.extend(("", "### 시나리오 범주"))
        for value in detected_rows[:limit]:
            state = "반영" if value.get("covered") else "검토 필요"
            lines.append(f"- {value.get('label', '')}: {state}")
    if issues:
        lines.extend(("", "### 우선 검토 사항"))
        for issue in issues[:limit]:
            lines.append(f"- {issue.get('message', issue.get('code', '품질 검토 필요'))}")
            fields = issue.get("fields", [])
            if fields:
                lines.append(f"  대상 필드 {' '.join(str(field) for field in fields)}")
            for example in list(issue.get("examples", []))[:2]:
                lines.append(f"  문제 문장 {example}")
    if uncovered:
        lines.extend(("", "### 미커버 변경 앵커"))
        for anchor in uncovered[:limit]:
            lines.append(f"- {anchor.get('label', anchor.get('id', '변경 앵커'))}")
    lines.extend(
        (
            "",
            "위 항목을 실제 변경 근거와 대조하고 필요한 문장만 교정한 JSON 객체를 다시 작성한다",
        )
    )
    return "\n".join(lines)


__all__ = [
    "build_quality_report",
    "extract_change_anchors",
    "find_implementation_preconditions",
    "find_non_actionable_test_steps",
    "find_overloaded_expected_result",
    "find_step_count_mismatch",
    "find_scope_inflation",
    "find_semantic_duplicates",
    "find_unnatural_test_data",
    "quality_report_markdown",
]
