import codecs
import shutil
import unittest
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from promptcase_studio.models import ChangeItem
from promptcase_studio.scanner import (
    ChangedProfile,
    IndexedFile,
    _body_exclusion_reason,
    _business_family,
    _candidate_relation,
    _extract_reference_signals,
    _extract_terms,
    _file_role,
    _focused_excerpt,
    _logical_stem,
    _normalize_additional_source_suffixes,
    _redact_sensitive_text,
    _read_text,
    _text_similarity,
    _git_diff,
    build_project_index,
    build_scan_bundle,
    collect_changes,
    collect_date_changes,
    collect_git_changes,
    parse_manual_changes,
    parse_manual_notes,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "sample_project"
MULTI_ROOT_FIXTURE = Path(__file__).parent / "fixtures" / "multi_root"
TEMP_ROOT = Path(__file__).resolve().parent.parent / "tmp" / "tests" / "scanner"


@contextmanager
def workspace_temporary_directory():
    """Use normal inherited ACLs; Python 3.13 TemporaryDirectory uses 0700 on Windows."""

    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = TEMP_ROOT / f"case-{uuid4().hex}"
    path.mkdir()
    try:
        yield str(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)


class ScannerTests(unittest.TestCase):
    def test_korean_ngram_similarity_tolerates_spacing_and_partial_wording(self):
        query = "저장시 변경사항 없으면 알림"
        matching = "feat: 저장 시 변경된 사항이 없으면 Alert 처리"
        unrelated = "feat: 사용자 권한과 메뉴 기반 사항 반영"

        self.assertGreater(_text_similarity(query, matching), 0.35)
        self.assertGreater(
            _text_similarity(query, matching),
            _text_similarity(query, unrelated) + 0.2,
        )

    def test_reads_bom_declared_utf8_and_cp949_sources_without_replacement(self):
        samples = {
            "utf8-bom.xml": codecs.BOM_UTF8
            + "<mapper>한글 UTF8 근거</mapper>".encode("utf-8"),
            "utf16-le.xml": codecs.BOM_UTF16_LE
            + "<mapper>한글 UTF16 LE 근거</mapper>".encode("utf-16-le"),
            "utf16-be.xml": codecs.BOM_UTF16_BE
            + "<mapper>한글 UTF16 BE 근거</mapper>".encode("utf-16-be"),
            "declared-latin1.xml": (
                '<?xml version="1.0" encoding="iso-8859-1"?><mapper>caf\u00e9</mapper>'
            ).encode("iso-8859-1"),
            "strict-utf8.java": "class Utf8Sample { String label = \"한글 근거\"; }".encode(
                "utf-8"
            ),
            "legacy-cp949.java": "class LegacySample { String label = \"주문확정상태\"; }".encode(
                "cp949"
            ),
        }
        expected = {
            "utf8-bom.xml": "한글 UTF8 근거",
            "utf16-le.xml": "한글 UTF16 LE 근거",
            "utf16-be.xml": "한글 UTF16 BE 근거",
            "declared-latin1.xml": "café",
            "strict-utf8.java": "한글 근거",
            "legacy-cp949.java": "주문확정상태",
        }

        with workspace_temporary_directory() as temporary:
            root = Path(temporary)
            for name, payload in samples.items():
                with self.subTest(name=name):
                    path = root / name
                    path.write_bytes(payload)
                    text = _read_text(path)
                    self.assertIn(expected[name], text)
                    self.assertNotIn("\ufffd", text)

            bounded_path = root / "bounded-utf8.txt"
            bounded_path.write_bytes("가나다".encode("utf-8"))
            self.assertEqual(_read_text(bounded_path, 2), "가나")

    def test_cross_language_sources_and_manifests_are_indexed_without_generated_trees(self):
        with workspace_temporary_directory() as temporary:
            root = Path(temporary)
            files = {
                "web/order.jsp": "<html/>",
                "sap/zsales.prog.abap": "REPORT zsales.",
                "sap/zi_sales.ddls.asddls": "define view entity ZI_Sales",
                "sap/order.hdbprocedure": "PROCEDURE ORDER_READ AS BEGIN END",
                "db/order_package.pkb": "CREATE PACKAGE order_package",
                "mainframe/order_batch.cbl": "IDENTIFICATION DIVISION.",
                "scripts/deploy.sh": "#!/bin/sh",
                "pyproject.toml": "[project]",
                "go.mod": "module example.test/app",
                "src/App.csproj": "<Project/>",
                "obj/GeneratedAssemblyInfo.cs": "class GeneratedAssemblyInfo {}",
                ".tox/site-packages/copied_dependency.py": "def copied(): pass",
                "vendor/example/dependency.go": "package dependency",
            }
            for relative, content in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            index, _excluded, truncated = build_project_index(root, 100)
            indexed = {item.relative_path for item in index}

            self.assertFalse(truncated)
            self.assertTrue(
                {
                    "web/order.jsp",
                    "sap/zsales.prog.abap",
                    "sap/zi_sales.ddls.asddls",
                    "sap/order.hdbprocedure",
                    "db/order_package.pkb",
                    "mainframe/order_batch.cbl",
                    "scripts/deploy.sh",
                    "pyproject.toml",
                    "go.mod",
                    "src/App.csproj",
                }.issubset(indexed)
            )
            self.assertNotIn("obj/GeneratedAssemblyInfo.cs", indexed)
            self.assertNotIn(".tox/site-packages/copied_dependency.py", indexed)
            self.assertNotIn("vendor/example/dependency.go", indexed)

    def test_configured_source_suffix_is_normalized_and_used_for_index_and_changed_body(self):
        with workspace_temporary_directory() as temporary:
            root = Path(temporary)
            custom_source = root / "src" / "payment.rulex"
            custom_source.parent.mkdir(parents=True)
            custom_source.write_text(
                "RULE PAYMENT_APPROVAL WHEN amount > limit THEN reject\n",
                encoding="utf-8",
            )

            normalized = _normalize_additional_source_suffixes(["rulex", ".RULEX"])
            self.assertEqual(normalized, frozenset({".rulex"}))

            index, _excluded, _truncated = build_project_index(
                root,
                100,
                additional_source_suffixes=normalized,
            )
            self.assertIn("src/payment.rulex", {item.relative_path for item in index})
            indexed_custom_source = next(
                item for item in index if item.relative_path == "src/payment.rulex"
            )
            self.assertEqual(indexed_custom_source.stem, "payment")
            custom_signals = _extract_reference_signals(
                custom_source,
                custom_source.read_text(encoding="utf-8"),
                normalized,
            )
            self.assertIn(
                ("file-stem", "payment"),
                {(signal.kind, signal.value) for signal in custom_signals},
            )

            bundle = build_scan_bundle(
                [root],
                "M src/payment.rulex",
                None,
                None,
                False,
                {
                    "additionalSourceSuffixes": ["rulex"],
                    "maxCandidateFiles": 100,
                    "maxChangedFileChars": 4000,
                    "maxRelatedFiles": 0,
                    "maxContextChars": 8000,
                },
            )
            changed_context = next(
                item for item in bundle.contexts if item.path == "src/payment.rulex"
            )
            self.assertIn("PAYMENT_APPROVAL", changed_context.excerpt)
            self.assertNotIn("지원하지 않는 확장자", "\n".join(bundle.warnings))

    def test_configured_source_suffix_rejects_empty_paths_wildcards_and_binary_types(self):
        invalid_values = (
            "",
            ".",
            "../rulex",
            "source/rulex",
            "*",
            ".exe",
            "archive.zip",
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    _normalize_additional_source_suffixes([value])

    def test_rust_php_ruby_go_and_csharp_imports_emit_exact_leaf_signals(self):
        cases = {
            "src/lib.rs": (
                "use crate::services::{OrderService, order_mapper};\n"
                "mod order_rules;\n",
                {
                    ("import", "OrderService"),
                    ("import-file", "services"),
                    ("import-file", "order_mapper"),
                    ("import-file", "order_rules"),
                },
            ),
            "src/order.php": (
                "<?php\n"
                "use App\\Service\\OrderService;\n"
                "use App\\Repository\\{OrderRepository as Repo, AuditRepository};\n"
                "require_once(__DIR__ . '/bootstrap.php');\n",
                {
                    ("import", "OrderService"),
                    ("import", "OrderRepository"),
                    ("import", "AuditRepository"),
                    ("import-file", "bootstrap"),
                },
            ),
            "lib/order.rb": (
                "require 'support/order_validator'\n"
                "require_relative './order_repository'\n",
                {
                    ("import-file", "order_validator"),
                    ("import-file", "order_repository"),
                },
            ),
            "cmd/main.go": (
                'import orders "example.com/app/orders"\n'
                "import (\n"
                '    "example.com/app/inventory"\n'
                '    api "example.com/app/client/v2"\n'
                ")\n",
                {
                    ("import-file", "orders"),
                    ("import-file", "inventory"),
                    ("import-file", "client"),
                },
            ),
            "src/App.cs": (
                "global using Acme.Orders.OrderService;\n"
                "using Rules = Acme.Orders.OrderRules;\n",
                {
                    ("import", "OrderService"),
                    ("import", "OrderRules"),
                },
            ),
        }
        for path, (source, expected) in cases.items():
            with self.subTest(path=path):
                signals = {
                    (signal.kind, signal.value)
                    for signal in _extract_reference_signals(Path(path), source)
                }
                self.assertTrue(expected.issubset(signals), signals)

    def test_sensitive_config_names_do_not_exclude_business_source_files(self):
        self.assertEqual(_body_exclusion_reason(Path("CredentialController.java")), "")
        self.assertEqual(_body_exclusion_reason(Path("SecretManagerService.py")), "")
        self.assertEqual(
            _body_exclusion_reason(Path("config/api-credentials.json")),
            "민감정보 파일 규칙",
        )
        self.assertEqual(
            _body_exclusion_reason(Path("config/client-secret.properties")),
            "민감정보 파일 규칙",
        )
        for value in (
            "config/prod-api-key.json",
            "config/my_secret_config.yml",
            "config/db-password-prod.properties",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    _body_exclusion_reason(Path(value)),
                    "민감정보 파일 규칙",
                )

    def test_logical_stem_removes_source_and_secondary_role_suffixes(self):
        expected = {
            "src/order.service.ts": "order",
            "src/order.controller.ts": "order",
            "sap/zsales.prog.abap": "zsales",
            "sap/zcl_sales.clas.abap": "zcl_sales",
            "sap/zi_sales.ddls.asddls": "zi_sales",
        }
        for value, stem in expected.items():
            with self.subTest(path=value):
                self.assertEqual(_logical_stem(Path(value)), stem)

        signals = _extract_reference_signals(
            Path("src/order.controller.ts"),
            'import { saveOrder } from "./order.service";',
        )
        signal_values = {
            signal.value for signal in signals if signal.kind in {"file-stem", "import-file"}
        }
        self.assertIn("order", signal_values)
        self.assertNotIn("service", signal_values)

    def test_mybatis_placeholders_are_data_fields_only_inside_mapper_xml(self):
        tsx_signals = _extract_reference_signals(
            Path("KpiMapHeader.tsx"),
            "const style = `${GRAYSCALE}-${opacity}`;",
        )
        plain_xml_signals = _extract_reference_signals(
            Path("runtime.xml"),
            "<configuration><value>${runtimeValue}</value></configuration>",
        )
        mapper_signals = _extract_reference_signals(
            Path("UserMapper.xml"),
            '<mapper namespace="UserMapper"><select id="find">'
            "SELECT * FROM USERS WHERE USER_ID = #{userId} AND TYPE = ${typeName}"
            "</select></mapper>",
        )

        self.assertFalse(any(signal.kind == "data-field" for signal in tsx_signals))
        self.assertFalse(any(signal.kind == "data-field" for signal in plain_xml_signals))
        mapper_fields = {
            signal.value for signal in mapper_signals if signal.kind == "data-field"
        }
        self.assertEqual(mapper_fields, {"userId", "typeName"})

    def test_file_roles_distinguish_frontend_and_backend_layers(self):
        expected = {
            "api/com/sessionApi.ts": "frontend-api",
            "hook/kpi/useKpiMapTaskList.ts": "frontend-hook",
            "store/session.ts": "frontend-store",
            "app/providers/SessionProvider.tsx": "frontend-provider",
            "src/main/java/com/sample/UserController.java": "backend-controller",
            "src/main/java/com/sample/UserServiceImpl.java": "backend-service",
            "src/main/resources/mapper/UserMapper.xml": "backend-mapper",
            "src/main/java/com/sample/UserResponseDto.java": "backend-dto",
        }
        for path, role in expected.items():
            with self.subTest(path=path):
                self.assertEqual(_file_role(Path(path)), role)

    def test_endpoint_signal_connects_frontend_api_to_spring_controller_across_roots(self):
        with workspace_temporary_directory() as temporary:
            workspace = Path(temporary)
            frontend = workspace / "frontend"
            backend = workspace / "backend"
            frontend_file = frontend / "src" / "api" / "userApi.ts"
            backend_file = (
                backend
                / "src"
                / "main"
                / "java"
                / "com"
                / "sample"
                / "UserController.java"
            )
            frontend_file.parent.mkdir(parents=True)
            backend_file.parent.mkdir(parents=True)
            frontend_file.write_text(
                'import sessionApi from "./client";\n'
                "export const loadUser = (userId: string) => "
                "sessionApi.get<User>(`${API_BASE_URL}/api/users/${userId}?active=true`);\n",
                encoding="utf-8",
            )
            backend_file.write_text(
                "package com.sample;\n"
                "@RestController\n"
                '@RequestMapping(value = "/api/users", produces = "application/json")\n'
                "public class UserController {\n"
                '  @GetMapping(path = "/{id}", produces = "application/json", '
                'headers = "X-Mode=active")\n'
                "  public UserDto findUser(String id) { return service.findUser(id); }\n"
                "}\n",
                encoding="utf-8",
            )

            frontend_endpoints = {
                signal.value
                for signal in _extract_reference_signals(
                    frontend_file,
                    frontend_file.read_text(encoding="utf-8"),
                )
                if signal.kind == "endpoint"
            }
            backend_endpoints = {
                signal.value
                for signal in _extract_reference_signals(
                    backend_file,
                    backend_file.read_text(encoding="utf-8"),
                )
                if signal.kind == "endpoint"
            }
            self.assertEqual(frontend_endpoints, {"/api/users/{}"})
            self.assertEqual(backend_endpoints, {"/api/users/{}"})

            bundle = build_scan_bundle(
                [frontend, backend],
                "변경: src/api/userApi.ts",
                None,
                None,
                False,
                {
                    "maxCandidateFiles": 100,
                    "maxChangedFileChars": 4000,
                    "maxRelatedFiles": 4,
                    "maxRelatedFileChars": 3000,
                    "maxContextChars": 10000,
                },
            )
            related = next(
                item
                for item in bundle.contexts
                if item.path.endswith("UserController.java")
            )
            self.assertIn("공통 endpoint", related.reason)
            self.assertIn("/api/users/{}", related.reason)
            self.assertIn("frontend-api와 backend-controller 계층 연결", related.reason)

    def test_fastapi_endpoint_connects_frontend_api_across_roots(self):
        with workspace_temporary_directory() as temporary:
            workspace = Path(temporary)
            frontend = workspace / "frontend"
            backend = workspace / "backend"
            frontend_file = frontend / "src" / "api" / "userApi.ts"
            backend_file = backend / "app" / "routers" / "users.py"
            frontend_file.parent.mkdir(parents=True)
            backend_file.parent.mkdir(parents=True)
            frontend_file.write_text(
                "export const loadUser = (id: string) => "
                "apiClient.get(`/api/users/${id}`);\n",
                encoding="utf-8",
            )
            backend_file.write_text(
                "from fastapi import APIRouter\n"
                'router = APIRouter(prefix="/api/users")\n'
                '@router.get("/{user_id}")\n'
                "def get_user(user_id: int):\n"
                "    return {\"id\": user_id}\n",
                encoding="utf-8",
            )

            backend_endpoints = {
                signal.value
                for signal in _extract_reference_signals(
                    backend_file,
                    backend_file.read_text(encoding="utf-8"),
                )
                if signal.kind == "endpoint"
            }
            self.assertEqual(backend_endpoints, {"/api/users/{}"})
            self.assertEqual(_file_role(Path("app/routers/users.py")), "backend-controller")
            flask_endpoints = {
                signal.value
                for signal in _extract_reference_signals(
                    Path("app/views/orders.py"),
                    "from flask import Blueprint\n"
                    'orders = Blueprint("orders", __name__, url_prefix="/api/orders")\n'
                    '@orders.route("/<int:order_id>")\n'
                    "def get_order(order_id): return {}\n",
                )
                if signal.kind == "endpoint"
            }
            self.assertEqual(flask_endpoints, {"/api/orders/{}"})

            bundle = build_scan_bundle(
                [frontend, backend],
                "변경: src/api/userApi.ts",
                None,
                None,
                False,
                {
                    "maxCandidateFiles": 100,
                    "maxChangedFileChars": 4000,
                    "maxRelatedFiles": 4,
                    "maxRelatedFileChars": 3000,
                    "maxContextChars": 10000,
                },
            )
            related = next(item for item in bundle.contexts if item.path == "app/routers/users.py")
            self.assertIn("공통 endpoint", related.reason)
            self.assertIn("frontend-api와 backend-controller 계층 연결", related.reason)

    def test_jsp_include_and_page_import_are_exact_reference_signals(self):
        with workspace_temporary_directory() as temporary:
            root = Path(temporary)
            page = root / "web" / "orders" / "order.jsp"
            fragment = root / "web" / "fragments" / "order-summary.tag"
            page.parent.mkdir(parents=True)
            fragment.parent.mkdir(parents=True)
            page.write_text(
                '<%@ include file="../fragments/order-summary.tag" %>\n'
                '<%@ page import="com.acme.orders.OrderService" %>\n',
                encoding="utf-8",
            )
            fragment.write_text("<div>주문 요약</div>", encoding="utf-8")

            signals = _extract_reference_signals(
                page,
                page.read_text(encoding="utf-8"),
            )
            signal_pairs = {(signal.value, signal.kind) for signal in signals}
            self.assertIn(("order-summary", "import-file"), signal_pairs)
            self.assertIn(("OrderService", "import"), signal_pairs)
            self.assertEqual(_file_role(Path("web/orders/order.jsp")), "frontend-view")

            bundle = build_scan_bundle(
                [root],
                "변경: web/orders/order.jsp",
                None,
                None,
                False,
                {
                    "maxCandidateFiles": 100,
                    "maxChangedFileChars": 4000,
                    "maxRelatedFiles": 3,
                    "maxRelatedFileChars": 2000,
                    "maxContextChars": 8000,
                },
            )
            related = next(
                item
                for item in bundle.contexts
                if item.path == "web/fragments/order-summary.tag"
            )
            self.assertIn("import-file", related.reason)

    def test_sql_general_objects_connect_non_prefixed_database_files(self):
        with workspace_temporary_directory() as temporary:
            root = Path(temporary)
            package = root / "db" / "order_package.pkb"
            cleanup = root / "db" / "cleanup_order.sql"
            package.parent.mkdir(parents=True)
            package.write_text(
                "CREATE OR REPLACE PACKAGE BODY ORDER_API AS\n"
                "  PROCEDURE load_orders IS BEGIN\n"
                "    SELECT * FROM SALES_ORDER;\n"
                "  END;\n"
                "END;\n",
                encoding="utf-8",
            )
            cleanup.write_text(
                "DELETE FROM SALES_ORDER WHERE EXPIRED_YN = 'Y';\n",
                encoding="utf-8",
            )

            objects = {
                signal.value
                for signal in _extract_reference_signals(
                    package,
                    package.read_text(encoding="utf-8"),
                )
                if signal.kind == "sql-object"
            }
            self.assertEqual(objects, {"ORDER_API", "SALES_ORDER"})

            bundle = build_scan_bundle(
                [root],
                "변경: db/order_package.pkb",
                None,
                None,
                False,
                {
                    "maxCandidateFiles": 100,
                    "maxChangedFileChars": 4000,
                    "maxRelatedFiles": 3,
                    "maxRelatedFileChars": 2000,
                    "maxContextChars": 8000,
                },
            )
            related = next(item for item in bundle.contexts if item.path == "db/cleanup_order.sql")
            self.assertIn("공통 sql-object: SALES_ORDER", related.reason)

    def test_sql_server_bracketed_identifiers_emit_exact_object_signals(self):
        signals = _extract_reference_signals(
            Path("db/read_order.sql"),
            "SELECT * FROM [SalesDb].[dbo].[ORDER_ITEM];\n"
            "UPDATE [dbo].[ORDER_SUMMARY] SET ITEM_COUNT = 1;\n",
        )
        sql_objects = {
            signal.value
            for signal in signals
            if signal.kind == "sql-object"
        }

        self.assertIn("ORDER_ITEM", sql_objects)
        self.assertIn("ORDER_SUMMARY", sql_objects)

    def test_abap_and_cds_exact_references_select_class_and_view_sources(self):
        with workspace_temporary_directory() as temporary:
            root = Path(temporary)
            report = root / "sap" / "zsales.prog.abap"
            service = root / "sap" / "zcl_sales.clas.abap"
            view = root / "sap" / "zi_sales.ddls.asddls"
            report.parent.mkdir(parents=True)
            report.write_text(
                "REPORT zsales.\n"
                "DATA service TYPE REF TO zcl_sales.\n"
                "SELECT * FROM zi_sales INTO TABLE @DATA(rows).\n",
                encoding="utf-8",
            )
            service.write_text(
                "CLASS zcl_sales DEFINITION PUBLIC.\nENDCLASS.\n",
                encoding="utf-8",
            )
            view.write_text(
                "define view entity ZI_Sales as select from I_SalesOrder { key SalesOrder }\n",
                encoding="utf-8",
            )

            signals = {
                (signal.value.casefold(), signal.kind)
                for signal in _extract_reference_signals(
                    report,
                    report.read_text(encoding="utf-8"),
                )
            }
            self.assertIn(("zcl_sales", "abap-object"), signals)
            self.assertIn(("zi_sales", "sql-object"), signals)
            self.assertEqual(_file_role(Path("sap/zsales.prog.abap")), "backend-service")
            self.assertEqual(
                _file_role(Path("sap/zi_sales.ddls.asddls")),
                "backend-mapper",
            )

            bundle = build_scan_bundle(
                [root],
                "변경: sap/zsales.prog.abap",
                None,
                None,
                False,
                {
                    "maxCandidateFiles": 100,
                    "maxChangedFileChars": 5000,
                    "maxRelatedFiles": 4,
                    "maxRelatedFileChars": 2500,
                    "maxContextChars": 10000,
                },
            )
            related_paths = {item.path for item in bundle.contexts[1:]}
            self.assertIn("sap/zcl_sales.clas.abap", related_paths)
            self.assertIn("sap/zi_sales.ddls.asddls", related_paths)

    def test_abap_call_keywords_and_sql_system_tables_do_not_create_shared_object_edges(self):
        first_abap = _extract_reference_signals(
            Path("sap/zsales.prog.abap"),
            "CALL METHOD lo_sales->calculate.\n"
            "CALL FUNCTION 'Z_SALES_READ'.\n",
        )
        second_abap = _extract_reference_signals(
            Path("sap/zinventory.prog.abap"),
            "CALL METHOD lo_inventory->recount.\n"
            "CALL FUNCTION 'Z_INVENTORY_READ'.\n",
        )
        first_sql = _extract_reference_signals(
            Path("db/order_sequence.sql"),
            "SELECT ORDER_SEQ.NEXTVAL FROM DUAL;\n",
        )
        second_sql = _extract_reference_signals(
            Path("db/user_sequence.sql"),
            "SELECT USER_SEQ.NEXTVAL FROM DUAL;\n",
        )
        hana_sql = _extract_reference_signals(
            Path("db/current_timestamp.sql"),
            "SELECT CURRENT_UTCTIMESTAMP FROM SYS.DUMMY;\n",
        )
        db2_sql = _extract_reference_signals(
            Path("db/current_date.sql"),
            "SELECT CURRENT DATE FROM SYSIBM.SYSDUMMY1;\n",
        )

        for signals in (
            first_abap,
            second_abap,
            first_sql,
            second_sql,
            hana_sql,
            db2_sql,
        ):
            sql_objects = {
                signal.value.casefold()
                for signal in signals
                if signal.kind == "sql-object"
            }
            self.assertTrue(
                {"method", "function", "dual"}.isdisjoint(sql_objects)
            )

        self.assertIn(
            ("abap-object", "Z_SALES_READ"),
            {(signal.kind, signal.value) for signal in first_abap},
        )

    def test_focused_excerpt_stratifies_diff_condition_sql_identifier_and_call(self):
        source_lines = [f"const repeatedStatus = value{index};" for index in range(35)]
        source_lines.extend(
            [
                "const fillerBeforeCondition = true;",
                "if (hasPendingChanges) {",
                '  throw new Error("pending change");',
                "}",
                *(f"const conditionGap{index} = {index};" for index in range(12)),
                "SELECT USER_ID FROM TB_USER WHERE ACTIVE_YN = 'Y'",
                *(f"const sqlGap{index} = {index};" for index in range(12)),
                "submitKpiMap(payload);",
                *(f"const callGap{index} = {index};" for index in range(12)),
                "+const diffSentinel = changedValue;",
            ]
        )
        excerpt = _focused_excerpt(
            "\n".join(source_lines),
            ["repeatedStatus"],
            2400,
        )

        self.assertIn("diffSentinel", excerpt)
        self.assertIn("hasPendingChanges", excerpt)
        self.assertIn("SELECT USER_ID", excerpt)
        self.assertIn("repeatedStatus", excerpt)
        self.assertIn("submitKpiMap", excerpt)

    def test_overlapping_roots_do_not_duplicate_the_same_physical_file(self):
        frontend = (MULTI_ROOT_FIXTURE / "frontend").resolve()
        nested_source = (frontend / "src").resolve()
        changes, _indexes, _excluded, _truncated = collect_changes(
            [frontend, nested_source],
            "",
            date(2000, 1, 1),
            None,
            False,
            {"maxCandidateFiles": 100},
        )
        matching = [item for item in changes if item.path.endswith("PlanPage.tsx")]
        self.assertEqual(len(matching), 1)

    def test_related_context_can_follow_an_exact_reference_across_roots(self):
        frontend = (MULTI_ROOT_FIXTURE / "frontend").resolve()
        backend = (MULTI_ROOT_FIXTURE / "backend").resolve()
        bundle = build_scan_bundle(
            [frontend, backend],
            "변경: src/components/PlanPage.tsx",
            None,
            None,
            False,
            {
                "maxCandidateFiles": 100,
                "maxChangedFileChars": 5000,
                "maxRelatedFiles": 4,
                "maxRelatedFileChars": 3000,
                "maxContextChars": 12000,
            },
        )
        related = [
            item
            for item in bundle.contexts
            if item.path.endswith("PlanService.java") and Path(item.root) == backend
        ]
        self.assertEqual(len(related), 1)
        self.assertIn("import", related[0].reason)

    def test_generic_import_name_does_not_create_a_cross_root_relation(self):
        frontend = (MULTI_ROOT_FIXTURE / "frontend").resolve()
        backend = (MULTI_ROOT_FIXTURE / "backend").resolve()
        bundle = build_scan_bundle(
            [frontend, backend],
            "변경: src/main/resources/db/h2/data.sql",
            None,
            None,
            False,
            {
                "maxCandidateFiles": 100,
                "maxChangedFileChars": 5000,
                "maxRelatedFiles": 4,
                "maxRelatedFileChars": 3000,
                "maxContextChars": 12000,
            },
        )
        related_paths = {item.path for item in bundle.contexts[1:]}
        self.assertNotIn("src/layout/SideMenuLayout.tsx", related_paths)

    def test_generic_import_name_does_not_cross_roots_during_expansion(self):
        frontend = (MULTI_ROOT_FIXTURE / "frontend").resolve()
        backend = (MULTI_ROOT_FIXTURE / "backend").resolve()
        bundle = build_scan_bundle(
            [frontend, backend],
            "변경: src/components/PlanPage.tsx",
            None,
            None,
            False,
            {
                "maxCandidateFiles": 100,
                "maxChangedFileChars": 5000,
                "maxRelatedFiles": 8,
                "maxRelatedFileChars": 3000,
                "maxContextChars": 18000,
            },
        )
        related_paths = {item.path for item in bundle.contexts[1:]}
        self.assertNotIn("src/data.ts", related_paths)

    def test_manual_change_parser_supports_korean_and_git_status(self):
        text = (
            "feat: 저장 시 변경된 사항이 없으면 Alert 처리\n"
            "변경: src/service/UserService.java\n"
            "D src/old/Legacy.java\n"
            "M .env.local\n"
            "refactor: node 삭제에 대한 edge 처리 대응"
        )
        rows = parse_manual_changes(text)
        self.assertEqual(rows[0], ("변경", "src/service/UserService.java"))
        self.assertEqual(rows[1], ("삭제", "src/old/Legacy.java"))
        self.assertEqual(rows[2], ("변경", ".env.local"))
        self.assertEqual(
            parse_manual_notes(text),
            [
                "feat: 저장 시 변경된 사항이 없으면 Alert 처리",
                "refactor: node 삭제에 대한 edge 처리 대응",
            ],
        )

    def test_manual_paths_resolve_globally_and_retain_missing_metadata(self):
        frontend = (MULTI_ROOT_FIXTURE / "frontend").resolve()
        backend = (MULTI_ROOT_FIXTURE / "backend").resolve()
        changes, _indexes, _excluded, _truncated = collect_changes(
            [frontend, backend],
            "\n".join(
                (
                    "변경: src/main/java/com/sample/PlanService.java",
                    "삭제: src/main/java/com/sample/LegacyPlanService.java",
                    "변경: src/main/java/com/sample/MissingPlanService.java",
                )
            ),
            None,
            None,
            False,
            {"maxCandidateFiles": 100},
        )
        by_path = {item.path: item for item in changes}
        self.assertEqual(len(changes), 3)
        self.assertEqual(Path(by_path["src/main/java/com/sample/PlanService.java"].root), backend)
        self.assertEqual(Path(by_path["src/main/java/com/sample/LegacyPlanService.java"].root), backend)
        self.assertFalse(by_path["src/main/java/com/sample/LegacyPlanService.java"].exists)
        self.assertEqual(
            Path(by_path["src/main/java/com/sample/MissingPlanService.java"].root), backend
        )
        self.assertFalse(by_path["src/main/java/com/sample/MissingPlanService.java"].exists)
        self.assertFalse(any(Path(item.root) == frontend for item in changes))

    def test_manual_path_cannot_escape_selected_project_root(self):
        root = FIXTURE_ROOT.resolve()
        logs = []
        changes, _indexes, _excluded, _truncated = collect_changes(
            [root],
            "M ../outside/CHANGELOG.md\nM C:/outside/CHANGELOG.md",
            None,
            None,
            False,
            {"maxCandidateFiles": 100},
            lambda level, message: logs.append((level, message)),
        )
        self.assertEqual(changes, [])
        self.assertEqual(sum(level == "WARN" for level, _message in logs), 2)
        self.assertTrue(all("프로젝트 루트 밖" in message for level, message in logs if level == "WARN"))

    def test_sensitive_manual_file_is_kept_as_metadata_without_body(self):
        missing_changes, _indexes, _excluded, _truncated = collect_changes(
            [FIXTURE_ROOT.resolve()],
            "M .env.local",
            None,
            None,
            False,
            {"maxCandidateFiles": 100},
        )
        self.assertEqual(missing_changes[0].path, ".env.local")
        self.assertFalse(missing_changes[0].exists)

        bundle = build_scan_bundle(
            [FIXTURE_ROOT.resolve()],
            "M src/api-credentials.json",
            None,
            None,
            False,
            {"maxCandidateFiles": 100, "maxRelatedFiles": 0, "maxContextChars": 3000},
        )
        self.assertEqual(bundle.contexts[0].mode, "metadata")
        self.assertNotIn("do-not-send-this-value", bundle.contexts[0].excerpt)
        self.assertTrue(any("민감정보 파일 규칙" in warning for warning in bundle.warnings))

    def test_request_terms_prioritize_changed_logic_over_long_import_header(self):
        source = "\n".join(
            [*(f'import Module{index} from "./module{index}";' for index in range(80)),
             "export function saveKpiMap(hasChanges: boolean) {",
             "  if (!hasChanges) {",
             '    alert("저장할 변경 사항이 없습니다");',
             "    return;",
             "  }",
             "  persistKpiMap();",
             "}"]
        )
        excerpt = _focused_excerpt(
            source,
            ["Module", "saveKpiMap", "persistKpiMap"],
            700,
            ["저장", "hasChanges", "alert"],
        )
        self.assertIn("저장할 변경 사항이 없습니다", excerpt)
        self.assertIn("hasChanges", excerpt)

    def test_modern_javascript_module_extensions_are_supported(self):
        bundle = build_scan_bundle(
            [FIXTURE_ROOT.resolve()],
            "변경: scripts/generate-seed.mjs",
            None,
            None,
            False,
            {"maxCandidateFiles": 100, "maxRelatedFiles": 0, "maxContextChars": 3000},
        )
        self.assertIn("generateSeed", bundle.contexts[0].excerpt)
        self.assertFalse(any("지원하지 않는 확장자" in warning for warning in bundle.warnings))

    def test_dynamic_context_follows_import_and_mapper_contract(self):
        bundle = build_scan_bundle(
            [FIXTURE_ROOT.resolve()],
            "변경: src/service/UserService.java",
            None,
            None,
            False,
            {
                "maxCandidateFiles": 100,
                "maxChangedFileChars": 12000,
                "maxRelatedFiles": 8,
                "maxRelatedFileChars": 5000,
                "maxContextChars": 30000,
            },
        )
        paths = [item.path for item in bundle.contexts]
        self.assertIn("src/service/UserService.java", paths)
        self.assertTrue(any(path.endswith("UserMapper.java") for path in paths))
        self.assertTrue(any(path.endswith("UserDto.java") for path in paths))
        mapper_context = next(item for item in bundle.contexts if item.path.endswith("UserMapper.java"))
        self.assertIn("import", mapper_context.reason)

    def test_reference_graph_expands_controller_to_service_mapper_and_dto(self):
        bundle = build_scan_bundle(
            [FIXTURE_ROOT.resolve()],
            "변경: src/controller/UserController.java",
            None,
            None,
            False,
            {
                "maxCandidateFiles": 100,
                "maxChangedFileChars": 8000,
                "maxRelatedFiles": 6,
                "maxRelatedFileChars": 3000,
                "maxContextChars": 20000,
            },
        )
        related = {item.path: item for item in bundle.contexts}
        self.assertIn("src/service/UserService.java", related)
        self.assertIn("src/mapper/UserMapper.java", related)
        self.assertIn("src/dto/UserDto.java", related)
        self.assertIn("정확한 참조를 한 단계 확장", related["src/mapper/UserMapper.java"].reason)

    def test_related_selection_prefers_exact_layer_links_over_nearby_noise(self):
        root = FIXTURE_ROOT.resolve()
        service = root / "src" / "service" / "UserService.java"
        source = service.read_text(encoding="utf-8")
        change = ChangeItem(str(root), "src/service/UserService.java", "변경", "manual", True)
        profile = ChangedProfile(
            change=change,
            path=service,
            role=_file_role(Path(change.path)),
            family=_business_family(Path(change.path)),
            signals=_extract_reference_signals(service, source),
            terms=_extract_terms(service, source),
        )
        mapper_path = root / "src" / "mapper" / "UserMapper.java"
        mapper = IndexedFile(root, mapper_path, "src/mapper/UserMapper.java", 100, 0)
        mapper_relation = _candidate_relation(
            mapper,
            mapper_path.read_text(encoding="utf-8"),
            profile,
        )
        noise_path = root / "src" / "service" / "AuditService.java"
        noise = IndexedFile(root, noise_path, "src/service/AuditService.java", 100, 0)
        noise_relation = _candidate_relation(noise, "class AuditService { void auditLog() {} }", profile)
        self.assertIsNotNone(mapper_relation)
        self.assertTrue(mapper_relation.explicit)
        self.assertIsNone(noise_relation)

    @patch("promptcase_studio.scanner.is_git_repository", return_value=True)
    @patch("promptcase_studio.scanner._git_diff")
    def test_diff_is_preserved_before_current_source_and_for_deleted_files(self, git_diff, _is_repo):
        git_diff.return_value = "@@ -1 +1 @@\n-old condition\n+new condition"
        bundle = build_scan_bundle(
            [FIXTURE_ROOT.resolve()],
            "변경: src/service/UserService.java\n삭제: src/legacy/LegacyService.java",
            None,
            None,
            True,
            {
                "maxCandidateFiles": 100,
                "maxChangedFileChars": 3000,
                "maxDiffChars": 1500,
                "maxRelatedFiles": 0,
                "maxContextChars": 7000,
            },
        )
        existing = next(item for item in bundle.contexts if item.path.endswith("UserService.java"))
        deleted = next(item for item in bundle.contexts if item.path.endswith("LegacyService.java"))
        self.assertLess(existing.excerpt.index("[Git diff]"), existing.excerpt.index("[현재 소스]"))
        self.assertIn("diff", existing.mode)
        self.assertIn("[Git diff]", deleted.excerpt)

    def test_large_change_set_keeps_every_change_within_context_budget(self):
        root = FIXTURE_ROOT.resolve()
        changes = []
        for index in range(72):
            layer = "frontend" if index % 2 == 0 else "backend"
            suffix = "tsx" if layer == "frontend" else "java"
            changes.append(
                ChangeItem(
                    str(root),
                    f"src/{layer}/PlanBase{index:02d}.{suffix}",
                    "변경",
                    "git-working-tree",
                    False,
                )
            )
        with (
            patch(
                "promptcase_studio.scanner.collect_changes",
                return_value=(changes, {str(root): []}, 0, False),
            ),
            patch("promptcase_studio.scanner.is_git_repository", return_value=True),
            patch(
                "promptcase_studio.scanner._git_diff",
                return_value="@@ -1 +1 @@\n-old base plan\n+new base plan\n" * 100,
            ),
        ):
            bundle = build_scan_bundle(
                [root],
                "",
                None,
                None,
                True,
                {
                    "maxCandidateFiles": 200,
                    "maxChangedFileChars": 2000,
                    "maxRelatedFiles": 0,
                    "maxContextChars": 18000,
                },
            )
            self.assertEqual(len(bundle.changes), 72)
            self.assertEqual(len(bundle.contexts), 72)
            self.assertLessEqual(sum(len(item.excerpt) for item in bundle.contexts), 18000)
            self.assertTrue(all(item.excerpt for item in bundle.contexts))
            self.assertTrue(any("예산" in warning for warning in bundle.warnings))

    def test_redacts_common_secret_shapes_before_prompting(self):
        source = '''apiKey: "replace-with-a-real-value-123"
GEMINI_API_KEY=gemini-prefixed-secret-value
OPENAI_API_KEY=openai-prefixed-secret-value
DB_PASSWORD=database-prefixed-secret-value
AWS_SECRET_ACCESS_KEY=aws-secret-access-value
JWT_SECRET=jwt-secret-value
GITHUB_TOKEN=github-token-value
privateKey: private-key-value
DATABASE_URL=postgres://sample:secret@localhost/app
Authorization: Bearer abcdefghijklmnopqrstuvwxyz
<password>super-secret-password</password>'''
        redacted = _redact_sensitive_text(source)
        self.assertEqual(redacted.count("[REDACTED]"), 11)
        self.assertNotIn("replace-with-a-real-value-123", redacted)
        self.assertNotIn("gemini-prefixed-secret-value", redacted)
        self.assertNotIn("openai-prefixed-secret-value", redacted)
        self.assertNotIn("database-prefixed-secret-value", redacted)
        self.assertNotIn("aws-secret-access-value", redacted)
        self.assertNotIn("jwt-secret-value", redacted)
        self.assertNotIn("github-token-value", redacted)
        self.assertNotIn("private-key-value", redacted)
        self.assertNotIn("postgres://sample:secret@localhost/app", redacted)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", redacted)
        self.assertNotIn("super-secret-password", redacted)

    def test_bounded_text_reader_does_not_load_the_entire_file(self):
        class TrackingBytesIO(BytesIO):
            requested_size = None

            def read(self, size=-1):
                self.requested_size = size
                return super().read(size)

        stream = TrackingBytesIO(("가나다라마바사" * 1000).encode("utf-8"))
        with patch.object(Path, "open", return_value=stream):
            text = _read_text(Path("large.sql"), 25)
        self.assertEqual(stream.requested_size, 100)
        self.assertLessEqual(len(text), 25)

    @patch("promptcase_studio.scanner.is_git_repository", return_value=True)
    @patch("promptcase_studio.scanner._run_git")
    def test_git_changes_merge_working_tree_and_history(self, run_git, _is_repo):
        def fake_git(_root, args):
            if "--show-toplevel" in args:
                return str(FIXTURE_ROOT.resolve())
            if "status" in args:
                return " M src/service/UserService.java\n?? src/service/NewService.java\n"
            if "log" in args:
                return "D\tsrc/service/LegacyService.java\n"
            raise AssertionError(args)

        run_git.side_effect = fake_git
        changes = collect_git_changes(FIXTURE_ROOT.resolve(), date(2026, 6, 1))
        by_path = {item.path: item for item in changes}
        self.assertEqual(by_path["src/service/UserService.java"].change_type, "변경")
        self.assertEqual(by_path["src/service/NewService.java"].change_type, "신규")
        self.assertEqual(by_path["src/service/LegacyService.java"].change_type, "삭제")

    @patch("promptcase_studio.scanner.is_git_repository", return_value=True)
    @patch("promptcase_studio.scanner._run_git")
    def test_git_scope_ranking_selects_matching_commit_instead_of_whole_date_range(
        self,
        run_git,
        _is_repo,
    ):
        def fake_git(_root, args):
            if "--show-toplevel" in args:
                return str(FIXTURE_ROOT.resolve())
            if "status" in args:
                return ""
            if "log" in args:
                return (
                    "@@PROMPTCASE-COMMIT@@target123\t2026-07-22T10:00:00+09:00\t"
                    "feat: 저장 시 변경된 사항이 없으면 Alert 처리\n"
                    "M\tsrc/service/UserService.java\n"
                    "M\tsrc/dto/UserDto.java\n"
                    "@@PROMPTCASE-COMMIT@@noise456\t2026-07-21T10:00:00+09:00\t"
                    "feat: 사용자 권한 메뉴 기반 반영\n"
                    "M\tsrc/controller/UserController.java\n"
                    "M\tsrc/mapper/UserMapper.java\n"
                )
            if "show" in args:
                commit = next(
                    value for value in args if value in {"target123", "noise456"}
                )
                if commit == "target123":
                    return (
                        "feat: 저장 시 변경된 사항이 없으면 Alert 처리\n"
                        "+if (!hasChanges) alert('저장할 변경 사항이 없습니다')\n"
                    )
                return "+권한과 메뉴 데이터를 조회한다\n"
            raise AssertionError(args)

        run_git.side_effect = fake_git
        changes = collect_git_changes(
            FIXTURE_ROOT.resolve(),
            date(2026, 7, 20),
            date(2026, 7, 23),
            change_notes=["feat: 저장 시 변경된 사항이 없으면 Alert 처리"],
            request_text="권한, 메뉴, 사용자 기반 사항도 포함하는 사업계획관리 요청",
            scanner_settings={"maxSelectedCommits": 3, "commitEvidenceShortlist": 12},
        )

        self.assertEqual({item.commit for item in changes}, {"target123"})
        self.assertEqual(
            {item.path for item in changes},
            {"src/service/UserService.java", "src/dto/UserDto.java"},
        )
        self.assertTrue(all(item.relevance_score >= 35 for item in changes))
        self.assertTrue(all("커밋 target12" in item.selection_reason for item in changes))

    @patch("promptcase_studio.scanner.collect_date_changes")
    @patch("promptcase_studio.scanner.collect_git_changes")
    @patch("promptcase_studio.scanner.is_git_repository", return_value=True)
    def test_modified_dates_are_not_merged_when_git_is_available(
        self,
        _is_repo,
        collect_git,
        collect_date,
    ):
        root = FIXTURE_ROOT.resolve()
        collect_git.return_value = [
            ChangeItem(
                str(root),
                "src/service/UserService.java",
                "변경",
                "git-history",
                True,
                commit="target123",
                relevance_score=80,
            )
        ]

        changes, _indexes, _excluded, _truncated = collect_changes(
            [root],
            "feat: 저장 변경 없음 알림",
            date(2026, 7, 20),
            date(2026, 7, 23),
            True,
            {"maxCandidateFiles": 100},
            request_text="넓은 시스템 기반 변경 요청",
        )

        collect_date.assert_not_called()
        self.assertEqual([item.path for item in changes], ["src/service/UserService.java"])

    @patch("promptcase_studio.scanner._run_git")
    def test_git_diff_combines_committed_and_working_changes_from_date_base(self, run_git):
        def fake_git(_root, args):
            if args[:2] == ["rev-list", "-1"]:
                return "base-commit\n"
            if args[:6] == [
                "diff",
                "--find-renames",
                "--no-ext-diff",
                "--unified=4",
                "base-commit",
                "--",
            ]:
                return "@@ -1 +1 @@\n-old committed value\n+new working value\n"
            raise AssertionError(args)

        run_git.side_effect = fake_git
        diff = _git_diff(
            FIXTURE_ROOT.resolve(),
            "src/service/UserService.java",
            date(2026, 7, 1),
            date.today(),
        )
        self.assertIn("old committed value", diff)
        self.assertIn("new working value", diff)
        self.assertEqual(run_git.call_count, 2)

    @patch("promptcase_studio.scanner._run_git")
    def test_git_diff_uses_empty_tree_when_repository_started_after_date(self, run_git):
        def fake_git(_root, args):
            if args[:2] == ["rev-list", "-1"]:
                return ""
            if args == ["rev-parse", "--verify", "HEAD"]:
                return "first-commit\n"
            if args[0] == "diff" and "4b825dc642cb6eb9a060e54bf8d69288fbee4904" in args:
                return "@@ -0,0 +1 @@\n+initial content\n"
            raise AssertionError(args)

        run_git.side_effect = fake_git
        diff = _git_diff(
            FIXTURE_ROOT.resolve(),
            "README.md",
            date(2026, 7, 1),
            date.today(),
        )
        self.assertIn("initial content", diff)
        self.assertEqual(run_git.call_count, 3)

    def test_modified_date_range_includes_both_boundary_dates(self):
        root = FIXTURE_ROOT.resolve()
        date_from = date(2026, 7, 1)
        date_to = date(2026, 7, 3)
        start = datetime.combine(date_from, time.min).timestamp()
        end = datetime.combine(date_to, time.max).timestamp()
        next_midnight = datetime.combine(date_to + timedelta(days=1), time.min).timestamp()
        index = [
            IndexedFile(root, root / "before.java", "before.java", 1, start - 0.001),
            IndexedFile(root, root / "start.java", "start.java", 1, start),
            IndexedFile(root, root / "end.java", "end.java", 1, end),
            IndexedFile(
                root,
                root / "next-midnight.java",
                "next-midnight.java",
                1,
                next_midnight,
            ),
        ]

        changes = collect_date_changes(index, date_from, date_to)

        self.assertEqual([item.path for item in changes], ["start.java", "end.java"])

    def test_reversed_date_range_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "시작일은 종료일보다 늦을 수 없습니다"):
            collect_date_changes([], date(2026, 7, 3), date(2026, 7, 1))

    @patch("promptcase_studio.scanner.is_git_repository", return_value=True)
    @patch("promptcase_studio.scanner._run_git")
    def test_git_history_uses_inclusive_start_and_end_of_day(self, run_git, _is_repo):
        date_from = date.today().replace(day=1)
        date_to = date.today()

        def fake_git(_root, args):
            if "--show-toplevel" in args:
                return str(FIXTURE_ROOT.resolve())
            if "status" in args:
                return ""
            if "log" in args:
                return "M\tsrc/service/UserService.java\n"
            raise AssertionError(args)

        run_git.side_effect = fake_git
        changes = collect_git_changes(FIXTURE_ROOT.resolve(), date_from, date_to)
        log_args = next(call.args[1] for call in run_git.call_args_list if "log" in call.args[1])

        self.assertIn(f"--since={date_from.isoformat()}T00:00:00", log_args)
        self.assertIn(f"--until={date_to.isoformat()}T23:59:59", log_args)
        self.assertEqual(changes[0].path, "src/service/UserService.java")

    @patch("promptcase_studio.scanner._run_git")
    def test_historical_git_diff_stops_at_selected_end_date(self, run_git):
        date_to = date.today() - timedelta(days=2)
        date_from = date_to - timedelta(days=2)
        next_midnight = (date_to + timedelta(days=1)).isoformat()

        def fake_git(_root, args):
            if args[:2] == ["rev-list", "-1"]:
                if f"--before={date_from.isoformat()}T00:00:00" in args:
                    return "base-commit\n"
                if f"--before={next_midnight}T00:00:00" in args:
                    return "end-commit\n"
            if args[0] == "diff" and "base-commit" in args and "end-commit" in args:
                return "@@ -1 +1 @@\n-old range value\n+new range value\n"
            raise AssertionError(args)

        run_git.side_effect = fake_git
        diff = _git_diff(
            FIXTURE_ROOT.resolve(),
            "src/service/UserService.java",
            date_from,
            date_to,
        )

        self.assertIn("new range value", diff)
        self.assertEqual(run_git.call_count, 3)


if __name__ == "__main__":
    unittest.main()
