from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Iterable
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from promptcase_studio.scanner import build_scan_bundle


DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "tmp" / "scope-simulation"
KST = timezone(timedelta(hours=9))

VO_PATHS = (
    "src/main/java/com/example/order/domain/OrderHeaderVo.java",
    "src/main/java/com/example/order/domain/OrderLineVo.java",
    "src/main/java/com/example/order/domain/OrderSummaryVo.java",
)
XML_PATHS = (
    "src/main/resources/mapper/order/OrderMapper.xml",
    "src/main/resources/mapper/order/OrderHistoryMapper.xml",
    "src/main/resources/mapper/order/OrderValidationMapper.xml",
    "src/main/resources/mapper/order/OrderReportMapper.xml",
)
SERVICE_PATH = "src/main/java/com/example/order/service/impl/OrderServiceImpl.java"
TARGET_PATHS = frozenset((*VO_PATHS, *XML_PATHS, SERVICE_PATH))


@dataclass(frozen=True)
class RepositoryProfile:
    name: str
    split_target_commits: bool
    noise_files: int
    noise_commits_before: int
    noise_commits_after: int


@dataclass(frozen=True)
class InputProfile:
    name: str
    manual_text: str
    request_text: str


@dataclass(frozen=True)
class DateProfile:
    name: str
    date_from: date
    date_to: date


@dataclass
class SimulationResult:
    repository: str
    input_profile: str
    date_profile: str
    date_from: str
    date_to: str
    status: str
    changed_target_count: int
    evidence_target_count: int
    target_count: int
    changed_recall: float
    evidence_recall: float
    service_as_change: bool
    service_as_evidence: bool
    false_change_count: int
    false_context_count: int
    changed_count: int
    context_count: int
    selected_commit_count: int
    context_chars: int
    changed_paths: list[str]
    context_paths: list[str]
    missing_target_paths: list[str]
    blind_widened_recall: float
    blind_widened_false_change_count: int
    relation_gated_recall: float
    relation_gated_service_as_change: bool
    relation_gated_false_change_count: int
    warnings: list[str]
    error: str = ""


REPOSITORY_PROFILES = (
    RepositoryProfile("single-commit-clean", False, 24, 2, 2),
    RepositoryProfile("split-commits-noisy", True, 120, 6, 14),
    RepositoryProfile("split-commits-heavy", True, 360, 10, 28),
)


def input_profiles() -> tuple[InputProfile, ...]:
    complete_lines = "\n".join(f"변경: {path}" for path in sorted(TARGET_PATHS))
    vo_lines = "\n".join(f"변경: {path}" for path in VO_PATHS)
    return (
        InputProfile(
            "complete",
            complete_lines,
            "주문 저장 시 VO, Mapper XML과 ServiceImpl 합계 계산 로직을 함께 변경",
        ),
        InputProfile(
            "service-named",
            f"변경: {SERVICE_PATH}",
            "주문 저장 합계 계산과 조회 결과 변경",
        ),
        InputProfile(
            "vo-paths-only",
            vo_lines,
            "VO 3개 수정",
        ),
        InputProfile(
            "vague-no-paths",
            "VO 몇 개 수정",
            "주문 관련 기능 수정",
        ),
    )


def date_profiles(today: date) -> tuple[DateProfile, ...]:
    return (
        DateProfile("exact-target", today - timedelta(days=21), today - timedelta(days=19)),
        DateProfile("vo-commit-day-only", today - timedelta(days=21), today - timedelta(days=21)),
        DateProfile("approximate-wide", today - timedelta(days=28), today - timedelta(days=12)),
        DateProfile("shifted-one-week", today - timedelta(days=14), today - timedelta(days=10)),
        DateProfile("broad-month", today - timedelta(days=35), today - timedelta(days=2)),
    )


def _run_git(repository: Path, arguments: Iterable[str], *, at: datetime | None = None) -> str:
    environment = os.environ.copy()
    if at is not None:
        timestamp = at.isoformat()
        environment["GIT_AUTHOR_DATE"] = timestamp
        environment["GIT_COMMITTER_DATE"] = timestamp
    completed = subprocess.run(
        ["git", "-c", "core.quotepath=false", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )
    return completed.stdout


def _write(repository: Path, relative_path: str, content: str) -> None:
    destination = repository / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content.rstrip() + "\n", encoding="utf-8")


def _append(repository: Path, relative_path: str, content: str) -> None:
    destination = repository / relative_path
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(content.rstrip() + "\n")


def _commit(repository: Path, message: str, at: datetime) -> None:
    _run_git(repository, ["add", "-A"])
    _run_git(repository, ["commit", "--quiet", "--allow-empty", "-m", message], at=at)


def _base_sources() -> dict[str, str]:
    mapper_names = ("OrderMapper", "OrderHistoryMapper", "OrderValidationMapper", "OrderReportMapper")
    sources = {
        "src/main/java/com/example/order/controller/OrderController.java": """
package com.example.order.controller;
import com.example.order.service.OrderService;
public class OrderController {
    private final OrderService service;
    public OrderController(OrderService service) { this.service = service; }
    public long save() { return service.saveOrder(); }
}
""",
        "src/main/java/com/example/order/service/OrderService.java": """
package com.example.order.service;
public interface OrderService {
    long saveOrder();
}
""",
        SERVICE_PATH: """
package com.example.order.service.impl;

import com.example.order.domain.OrderHeaderVo;
import com.example.order.domain.OrderLineVo;
import com.example.order.domain.OrderSummaryVo;
import com.example.order.mapper.OrderMapper;
import com.example.order.mapper.OrderHistoryMapper;
import com.example.order.mapper.OrderValidationMapper;
import com.example.order.mapper.OrderReportMapper;
import com.example.order.service.OrderService;

public class OrderServiceImpl implements OrderService {
    private final OrderMapper orderMapper;
    private final OrderHistoryMapper historyMapper;
    private final OrderValidationMapper validationMapper;
    private final OrderReportMapper reportMapper;

    public long saveOrder() {
        OrderHeaderVo header = new OrderHeaderVo();
        OrderLineVo line = new OrderLineVo();
        OrderSummaryVo summary = new OrderSummaryVo();
        validationMapper.validate(header);
        orderMapper.insertHeader(header);
        historyMapper.insertHistory(line);
        reportMapper.updateSummary(summary);
        return 1L;
    }
}
""",
        VO_PATHS[0]: """
package com.example.order.domain;
public class OrderHeaderVo {
    private String orderId;
    public String getOrderId() { return orderId; }
}
""",
        VO_PATHS[1]: """
package com.example.order.domain;
public class OrderLineVo {
    private long amount;
    public long getAmount() { return amount; }
}
""",
        VO_PATHS[2]: """
package com.example.order.domain;
public class OrderSummaryVo {
    private long totalAmount;
    public long getTotalAmount() { return totalAmount; }
}
""",
    }
    for mapper_name in mapper_names:
        sources[f"src/main/java/com/example/order/mapper/{mapper_name}.java"] = f"""
package com.example.order.mapper;
import com.example.order.domain.OrderHeaderVo;
import com.example.order.domain.OrderLineVo;
import com.example.order.domain.OrderSummaryVo;
public interface {mapper_name} {{
    int insertHeader(OrderHeaderVo value);
    int insertHistory(OrderLineVo value);
    int validate(OrderHeaderVo value);
    int updateSummary(OrderSummaryVo value);
}}
"""
    xml_specs = (
        ("OrderMapper", "insertHeader", "OrderHeaderVo"),
        ("OrderHistoryMapper", "insertHistory", "OrderLineVo"),
        ("OrderValidationMapper", "validate", "OrderHeaderVo"),
        ("OrderReportMapper", "updateSummary", "OrderSummaryVo"),
    )
    for mapper_name, statement, vo_name in xml_specs:
        sources[
            f"src/main/resources/mapper/order/{mapper_name}.xml"
        ] = f"""
<?xml version="1.0" encoding="UTF-8"?>
<mapper namespace="com.example.order.mapper.{mapper_name}">
  <insert id="{statement}" parameterType="com.example.order.domain.{vo_name}">
    INSERT INTO TB_ORDER_AUDIT (ORDER_ID) VALUES (#{{orderId}})
  </insert>
</mapper>
"""
    return sources


def _create_noise_files(repository: Path, count: int) -> None:
    for index in range(count):
        family = index % 12
        role = ("Controller", "ServiceImpl", "Mapper", "Vo")[index % 4]
        relative_path = (
            f"src/main/java/com/example/noise/module{family:02d}/"
            f"Noise{index:03d}{role}.java"
        )
        _write(
            repository,
            relative_path,
            (
                f"package com.example.noise.module{family:02d};\n"
                f"public class Noise{index:03d}{role} {{\n"
                f"    public String value() {{ return \"noise-{index:03d}\"; }}\n"
                "}"
            ),
        )


def _noise_commit(
    repository: Path,
    profile: RepositoryProfile,
    sequence: int,
    at: datetime,
) -> None:
    index = sequence % profile.noise_files
    relative_path = (
        f"src/main/java/com/example/noise/module{index % 12:02d}/"
        f"Noise{index:03d}{('Controller', 'ServiceImpl', 'Mapper', 'Vo')[index % 4]}.java"
    )
    _append(repository, relative_path, f"// noise revision {sequence}")
    subject = (
        f"fix: 주문 조회 보조 처리 {sequence}"
        if sequence % 7 == 0
        else f"chore: unrelated module maintenance {sequence}"
    )
    _commit(repository, subject, at)


def create_repository(
    root: Path,
    profile: RepositoryProfile,
    today: date,
) -> Path:
    repository = root / profile.name
    repository.mkdir(parents=True, exist_ok=False)
    _run_git(repository, ["init", "--quiet"])
    _run_git(repository, ["config", "user.name", "Promptcase Simulation"])
    _run_git(repository, ["config", "user.email", "simulation@promptcase.local"])

    for relative_path, content in _base_sources().items():
        _write(repository, relative_path, content)
    _create_noise_files(repository, profile.noise_files)
    _commit(
        repository,
        "chore: initialize simulation project",
        datetime.combine(today - timedelta(days=40), time(10), KST),
    )

    for sequence in range(profile.noise_commits_before):
        day = 35 - sequence * max(1, 12 // max(1, profile.noise_commits_before))
        _noise_commit(
            repository,
            profile,
            sequence,
            datetime.combine(today - timedelta(days=day), time(9), KST),
        )

    if profile.split_target_commits:
        for path in VO_PATHS:
            _append(repository, path, "// 변경: 주문 금액 검증 필드 보완")
        _commit(
            repository,
            "refactor: order transfer objects",
            datetime.combine(today - timedelta(days=21), time(11), KST),
        )
        for path in XML_PATHS:
            _append(repository, path, "<!-- 변경: 주문 결과 매핑 조건 보완 -->")
        _commit(
            repository,
            "chore: mapping metadata cleanup",
            datetime.combine(today - timedelta(days=20), time(11), KST),
        )
        _append(
            repository,
            SERVICE_PATH,
            """
// 변경: 합계가 0인 경우 저장 결과를 보정
long normalizeSavedCount(long count) {
    return count < 0 ? 0 : count;
}
""",
        )
        _commit(
            repository,
            "fix: calculation edge handling",
            datetime.combine(today - timedelta(days=19), time(11), KST),
        )
    else:
        for path in VO_PATHS:
            _append(repository, path, "// 변경: 주문 금액 검증 필드 보완")
        for path in XML_PATHS:
            _append(repository, path, "<!-- 변경: 주문 결과 매핑 조건 보완 -->")
        _append(
            repository,
            SERVICE_PATH,
            "// 변경: VO 저장 결과와 합계 계산 로직 보정",
        )
        _commit(
            repository,
            "feat: 주문 VO XML ServiceImpl 저장 로직 변경",
            datetime.combine(today - timedelta(days=20), time(11), KST),
        )

    available_seconds = int(timedelta(days=16).total_seconds())
    for sequence in range(profile.noise_commits_after):
        offset_seconds = (
            0
            if profile.noise_commits_after <= 1
            else round(sequence * available_seconds / (profile.noise_commits_after - 1))
        )
        commit_time = (
            datetime.combine(today - timedelta(days=18), time(8), KST)
            + timedelta(seconds=offset_seconds)
        )
        _noise_commit(
            repository,
            profile,
            profile.noise_commits_before + sequence,
            commit_time,
        )
    return repository


def scanner_settings() -> dict[str, object]:
    settings_path = PROJECT_ROOT / "config" / "app.settings.json"
    raw = json.loads(settings_path.read_text(encoding="utf-8-sig"))
    settings = dict(raw.get("scanner", {}))
    settings["maxCandidateFiles"] = max(1000, int(settings.get("maxCandidateFiles", 20000)))
    return settings


def _history_paths(repository: Path, date_from: date, date_to: date) -> set[str]:
    output = _run_git(
        repository,
        [
            "log",
            f"--since={date_from.isoformat()}T00:00:00",
            f"--until={date_to.isoformat()}T23:59:59",
            "--name-only",
            "--format=",
            "--",
            ".",
        ],
    )
    return {
        line.strip().replace("\\", "/")
        for line in output.splitlines()
        if line.strip()
    }


def evaluate_scenario(
    repository: Path,
    repository_profile: RepositoryProfile,
    input_profile: InputProfile,
    date_profile: DateProfile,
    settings: dict[str, object] | None = None,
) -> SimulationResult:
    logs: list[tuple[str, str]] = []
    widened_from = date_profile.date_from - timedelta(days=14)
    widened_to = date_profile.date_to + timedelta(days=14)
    widened_history_paths = _history_paths(repository, widened_from, widened_to)

    def capture(level: str, message: str) -> None:
        logs.append((level, message))

    try:
        bundle = build_scan_bundle(
            [repository.resolve()],
            input_profile.manual_text,
            date_profile.date_from,
            date_profile.date_to,
            True,
            settings or scanner_settings(),
            capture,
            request_text=input_profile.request_text,
        )
    except Exception as exc:
        return SimulationResult(
            repository=repository_profile.name,
            input_profile=input_profile.name,
            date_profile=date_profile.name,
            date_from=date_profile.date_from.isoformat(),
            date_to=date_profile.date_to.isoformat(),
            status="error",
            changed_target_count=0,
            evidence_target_count=0,
            target_count=len(TARGET_PATHS),
            changed_recall=0.0,
            evidence_recall=0.0,
            service_as_change=False,
            service_as_evidence=False,
            false_change_count=0,
            false_context_count=0,
            changed_count=0,
            context_count=0,
            selected_commit_count=0,
            context_chars=0,
            changed_paths=[],
            context_paths=[],
            missing_target_paths=sorted(TARGET_PATHS),
            blind_widened_recall=round(
                len(TARGET_PATHS & widened_history_paths) / len(TARGET_PATHS), 4
            ),
            blind_widened_false_change_count=len(widened_history_paths - TARGET_PATHS),
            relation_gated_recall=0.0,
            relation_gated_service_as_change=False,
            relation_gated_false_change_count=0,
            warnings=[f"{level}: {message}" for level, message in logs if level == "WARN"],
            error=str(exc),
        )

    changed_paths = {item.path.replace("\\", "/") for item in bundle.changes}
    context_paths = {item.path.replace("\\", "/") for item in bundle.contexts}
    evidence_paths = changed_paths | context_paths
    changed_targets = TARGET_PATHS & changed_paths
    evidence_targets = TARGET_PATHS & evidence_paths
    blind_widened_paths = changed_paths | widened_history_paths
    relation_gated_paths = changed_paths | (context_paths & widened_history_paths)
    commits = {
        commit.strip()
        for item in bundle.changes
        for commit in item.commit.split(",")
        if commit.strip()
    }
    return SimulationResult(
        repository=repository_profile.name,
        input_profile=input_profile.name,
        date_profile=date_profile.name,
        date_from=date_profile.date_from.isoformat(),
        date_to=date_profile.date_to.isoformat(),
        status="ok",
        changed_target_count=len(changed_targets),
        evidence_target_count=len(evidence_targets),
        target_count=len(TARGET_PATHS),
        changed_recall=round(len(changed_targets) / len(TARGET_PATHS), 4),
        evidence_recall=round(len(evidence_targets) / len(TARGET_PATHS), 4),
        service_as_change=SERVICE_PATH in changed_paths,
        service_as_evidence=SERVICE_PATH in evidence_paths,
        false_change_count=len(changed_paths - TARGET_PATHS),
        false_context_count=len(context_paths - TARGET_PATHS),
        changed_count=len(changed_paths),
        context_count=len(context_paths),
        selected_commit_count=len(commits),
        context_chars=sum(len(item.excerpt) for item in bundle.contexts),
        changed_paths=sorted(changed_paths),
        context_paths=sorted(context_paths),
        missing_target_paths=sorted(TARGET_PATHS - evidence_paths),
        blind_widened_recall=round(
            len(TARGET_PATHS & blind_widened_paths) / len(TARGET_PATHS), 4
        ),
        blind_widened_false_change_count=len(blind_widened_paths - TARGET_PATHS),
        relation_gated_recall=round(
            len(TARGET_PATHS & relation_gated_paths) / len(TARGET_PATHS), 4
        ),
        relation_gated_service_as_change=SERVICE_PATH in relation_gated_paths,
        relation_gated_false_change_count=len(relation_gated_paths - TARGET_PATHS),
        warnings=list(bundle.warnings)
        + [f"{level}: {message}" for level, message in logs if level == "WARN"],
    )


def _aggregate(results: list[SimulationResult], attribute: str) -> list[dict[str, object]]:
    values = sorted({getattr(result, attribute) for result in results})
    rows: list[dict[str, object]] = []
    for value in values:
        selected = [result for result in results if getattr(result, attribute) == value]
        successful = [result for result in selected if result.status == "ok"]
        rows.append(
            {
                "name": value,
                "scenarios": len(selected),
                "errors": len(selected) - len(successful),
                "changedRecall": round(mean(result.changed_recall for result in successful), 4)
                if successful
                else 0.0,
                "evidenceRecall": round(mean(result.evidence_recall for result in successful), 4)
                if successful
                else 0.0,
                "serviceChangeRate": round(
                    mean(float(result.service_as_change) for result in successful), 4
                )
                if successful
                else 0.0,
                "serviceEvidenceRate": round(
                    mean(float(result.service_as_evidence) for result in successful), 4
                )
                if successful
                else 0.0,
                "averageFalseChanges": round(
                    mean(result.false_change_count for result in successful), 2
                )
                if successful
                else 0.0,
                "blindWidenedRecall": round(
                    mean(result.blind_widened_recall for result in selected), 4
                ),
                "blindWidenedFalseChanges": round(
                    mean(result.blind_widened_false_change_count for result in selected), 2
                ),
                "relationGatedRecall": round(
                    mean(result.relation_gated_recall for result in selected), 4
                ),
                "relationGatedServiceChangeRate": round(
                    mean(float(result.relation_gated_service_as_change) for result in selected),
                    4,
                ),
                "relationGatedFalseChanges": round(
                    mean(result.relation_gated_false_change_count for result in selected), 2
                ),
            }
        )
    return rows


def build_report(results: list[SimulationResult], today: date) -> dict[str, object]:
    successful = [result for result in results if result.status == "ok"]
    return {
        "generatedAt": datetime.now(KST).isoformat(timespec="seconds"),
        "simulationToday": today.isoformat(),
        "targetFiles": sorted(TARGET_PATHS),
        "scenarioCount": len(results),
        "errorCount": len(results) - len(successful),
        "overall": {
            "changedRecall": round(mean(result.changed_recall for result in successful), 4)
            if successful
            else 0.0,
            "evidenceRecall": round(mean(result.evidence_recall for result in successful), 4)
            if successful
            else 0.0,
            "serviceChangeRate": round(
                mean(float(result.service_as_change) for result in successful), 4
            )
            if successful
            else 0.0,
            "serviceEvidenceRate": round(
                mean(float(result.service_as_evidence) for result in successful), 4
            )
            if successful
            else 0.0,
            "blindWidenedRecall": round(
                mean(result.blind_widened_recall for result in results), 4
            ),
            "blindWidenedFalseChanges": round(
                mean(result.blind_widened_false_change_count for result in results), 2
            ),
            "relationGatedRecall": round(
                mean(result.relation_gated_recall for result in results), 4
            ),
            "relationGatedServiceChangeRate": round(
                mean(float(result.relation_gated_service_as_change) for result in results),
                4,
            ),
            "relationGatedFalseChanges": round(
                mean(result.relation_gated_false_change_count for result in results), 2
            ),
        },
        "byRepository": _aggregate(results, "repository"),
        "byInput": _aggregate(results, "input_profile"),
        "byDate": _aggregate(results, "date_profile"),
        "results": [asdict(result) for result in results],
    }


def render_report(report: dict[str, object]) -> str:
    overall = report["overall"]
    lines = [
        "# 변경 범위 회수 시뮬레이션",
        "",
        f"- 기준일: {report['simulationToday']}",
        f"- 시나리오: {report['scenarioCount']}개",
        f"- 오류: {report['errorCount']}개",
        f"- 변경 파일 회수율: {float(overall['changedRecall']) * 100:.1f}%",
        f"- 변경·연관 근거 통합 회수율: {float(overall['evidenceRecall']) * 100:.1f}%",
        f"- ServiceImpl 변경 인식률: {float(overall['serviceChangeRate']) * 100:.1f}%",
        f"- ServiceImpl 근거 인식률: {float(overall['serviceEvidenceRate']) * 100:.1f}%",
        f"- 날짜 ±14일 무조건 확장 회수율/평균 오탐: "
        f"{float(overall['blindWidenedRecall']) * 100:.1f}% / "
        f"{float(overall['blindWidenedFalseChanges']):.2f}개",
        f"- 날짜 ±14일 중 연관 근거 확인 파일만 승격한 회수율/평균 오탐: "
        f"{float(overall['relationGatedRecall']) * 100:.1f}% / "
        f"{float(overall['relationGatedFalseChanges']):.2f}개",
        "",
    ]
    for title, key in (
        ("입력 품질별", "byInput"),
        ("날짜 범위별", "byDate"),
        ("저장소 규모별", "byRepository"),
    ):
        lines.extend(
            [
                f"## {title}",
                "",
                "| 구분 | 시나리오 | 변경 회수율 | 통합 회수율 | Service 변경 | Service 근거 | 평균 오탐 변경 |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in report[key]:
            lines.append(
                f"| {row['name']} | {row['scenarios']} | "
                f"{float(row['changedRecall']) * 100:.1f}% | "
                f"{float(row['evidenceRecall']) * 100:.1f}% | "
                f"{float(row['serviceChangeRate']) * 100:.1f}% | "
                f"{float(row['serviceEvidenceRate']) * 100:.1f}% | "
                f"{float(row['averageFalseChanges']):.2f} |"
            )
        lines.append("")
        lines.extend(
            [
                "| 구분 | ±14일 무조건 회수 | 무조건 오탐 | 연관 확인 승격 회수 | 연관 확인 Service | 연관 확인 오탐 |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in report[key]:
            lines.append(
                f"| {row['name']} | "
                f"{float(row['blindWidenedRecall']) * 100:.1f}% | "
                f"{float(row['blindWidenedFalseChanges']):.2f} | "
                f"{float(row['relationGatedRecall']) * 100:.1f}% | "
                f"{float(row['relationGatedServiceChangeRate']) * 100:.1f}% | "
                f"{float(row['relationGatedFalseChanges']):.2f} |"
            )
        lines.append("")

    lines.extend(
        [
            "## 전체 시나리오",
            "",
            "| 저장소 | 입력 | 날짜 | 변경 회수 | 통합 회수 | Service 변경/근거 | 오탐 변경 | 상태 |",
            "| --- | --- | --- | ---: | ---: | --- | ---: | --- |",
        ]
    )
    for row in report["results"]:
        lines.append(
            f"| {row['repository']} | {row['input_profile']} | {row['date_profile']} | "
            f"{float(row['changed_recall']) * 100:.1f}% | "
            f"{float(row['evidence_recall']) * 100:.1f}% | "
            f"{'Y' if row['service_as_change'] else 'N'}/"
            f"{'Y' if row['service_as_evidence'] else 'N'} | "
            f"{row['false_change_count']} | {row['status']} |"
        )
    return "\n".join(lines) + "\n"


def run_simulation(
    output_directory: Path = DEFAULT_OUTPUT_DIR,
    *,
    today: date | None = None,
    keep_workspaces: bool = False,
    repository_profiles: tuple[RepositoryProfile, ...] = REPOSITORY_PROFILES,
    append: bool = False,
) -> tuple[dict[str, object], Path, Path]:
    simulation_today = today or date.today()
    output_directory.mkdir(parents=True, exist_ok=True)
    workspace = output_directory / f"work-{uuid4().hex}"
    workspace.mkdir()
    results: list[SimulationResult] = []
    json_path = output_directory / "latest-report.json"
    markdown_path = output_directory / "latest-report.md"
    selected_names = {profile.name for profile in repository_profiles}
    if append and json_path.is_file():
        previous = json.loads(json_path.read_text(encoding="utf-8"))
        results.extend(
            SimulationResult(**row)
            for row in previous.get("results", [])
            if row.get("repository") not in selected_names
        )
    settings = scanner_settings()
    try:
        for repository_profile in repository_profiles:
            repository = create_repository(workspace, repository_profile, simulation_today)
            for input_profile in input_profiles():
                for date_profile in date_profiles(simulation_today):
                    results.append(
                        evaluate_scenario(
                            repository,
                            repository_profile,
                            input_profile,
                            date_profile,
                            settings,
                        )
                    )
        report = build_report(results, simulation_today)
        json_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        markdown_path.write_text(render_report(report), encoding="utf-8")
        return report, json_path, markdown_path
    finally:
        if not keep_workspaces:
            shutil.rmtree(workspace, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="날짜와 사용자 입력 품질에 따른 변경 범위 회수율을 로컬 Git Mock으로 측정합니다."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="JSON과 Markdown 보고서 저장 폴더",
    )
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        default=None,
        help="재현용 기준일(YYYY-MM-DD)",
    )
    parser.add_argument(
        "--keep-workspaces",
        action="store_true",
        help="생성한 임시 Git 저장소를 보고서와 함께 유지",
    )
    parser.add_argument(
        "--profile",
        action="append",
        choices=[profile.name for profile in REPOSITORY_PROFILES],
        help="실행할 저장소 프로필. 생략하면 전체 프로필을 실행",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="기존 보고서의 다른 저장소 프로필 결과를 유지하고 선택 프로필만 갱신",
    )
    args = parser.parse_args()
    selected_profiles = (
        tuple(
            profile
            for profile in REPOSITORY_PROFILES
            if profile.name in set(args.profile)
        )
        if args.profile
        else REPOSITORY_PROFILES
    )
    report, json_path, markdown_path = run_simulation(
        args.output.resolve(),
        today=args.today,
        keep_workspaces=args.keep_workspaces,
        repository_profiles=selected_profiles,
        append=args.append,
    )
    overall = report["overall"]
    print(f"시나리오 {report['scenarioCount']}개, 오류 {report['errorCount']}개")
    print(f"변경 회수율 {float(overall['changedRecall']) * 100:.1f}%")
    print(f"통합 회수율 {float(overall['evidenceRecall']) * 100:.1f}%")
    print(f"ServiceImpl 변경 인식률 {float(overall['serviceChangeRate']) * 100:.1f}%")
    print(f"ServiceImpl 근거 인식률 {float(overall['serviceEvidenceRate']) * 100:.1f}%")
    print(
        "연관 근거 확인 후 날짜 보완 회수율 "
        f"{float(overall['relationGatedRecall']) * 100:.1f}%"
    )
    print(f"JSON: {json_path}")
    print(f"Markdown: {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
