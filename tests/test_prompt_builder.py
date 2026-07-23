import unittest

from promptcase_studio.models import ChangeItem, ContextFile, ScanBundle
from promptcase_studio.prompt_builder import (
    PROMPT_MAX_CHARS,
    _test_scope_guidance,
    build_prompt,
    build_prompt_package,
)


class PromptBuilderTests(unittest.TestCase):
    def test_scope_guidance_uses_business_notes_instead_of_file_count(self):
        changes = [
            ChangeItem(
                "C:/sample",
                f"src/user/User{layer}.java",
                "변경",
                "manual",
                True,
            )
            for layer in ("Controller", "ServiceImpl", "Mapper", "Dto")
        ]
        bundle = ScanBundle(
            changes=changes,
            change_notes=["사용자 저장 시 변경 없음 알림을 추가함"],
        )

        self.assertEqual(_test_scope_guidance(bundle)[0], 1)
        prompt = build_prompt(bundle, "사용자 저장 로직 변경")
        self.assertIn("권장 테스트 흐름: 1개", prompt)
        self.assertIn("계층별 파일 수는 하나의 흐름으로 통합", prompt)

    def test_scope_guidance_caps_large_unannotated_change_at_five(self):
        bundle = ScanBundle(
            changes=[
                ChangeItem("C:/sample", f"src/Feature{index}Service.java", "변경", "manual", True)
                for index in range(30)
            ]
        )

        self.assertEqual(_test_scope_guidance(bundle)[0], 5)

    def test_prompt_records_contract_versions_and_keeps_schema_complete(self):
        change = ChangeItem(
            root="C:/sample",
            path="src/service/UserService.java",
            change_type="변경",
            source="manual",
            exists=True,
        )
        bundle = ScanBundle(
            changes=[change],
            contexts=[
                ContextFile(
                    root=change.root,
                    path=change.path,
                    mode="focused",
                    reason="변경 파일 근거",
                    score=1000,
                    excerpt="class UserService { UserDto findActiveUser() { return mapper.selectActiveUser(); } }",
                )
            ],
            scanned_files=4,
        )
        prompt = build_prompt(bundle, "활성 사용자 조회 조건을 변경함")
        self.assertIn("프롬프트 버전: 3.2.0", prompt)
        self.assertIn("응답 스키마 버전: 2.1.0", prompt)
        self.assertIn("품질 정책 버전: 1.3.0", prompt)
        self.assertIn('"documentTitle"', prompt)
        self.assertIn("근거의 우선순위는 Git diff", prompt)
        self.assertNotIn("{{", prompt)
        self.assertTrue(prompt.rstrip().endswith("}"))

    def test_large_frontend_backend_change_keeps_request_and_all_change_headers(self):
        changes = []
        contexts = []
        for index in range(72):
            layer = "frontend" if index % 2 == 0 else "backend"
            suffix = "tsx" if layer == "frontend" else "java"
            path = f"src/{layer}/PlanBase{index:02d}.{suffix}"
            change = ChangeItem(
                root="C:/business-plan",
                path=path,
                change_type="변경",
                source="git-working-tree",
                exists=True,
            )
            changes.append(change)
            contexts.append(
                ContextFile(
                    root=change.root,
                    path=path,
                    mode="focused+diff",
                    reason="변경 파일별 독립 근거",
                    score=1000,
                    excerpt=(
                        (
                            "[Git diff]\n사업계획관리시스템 기반사항의 조회 조건을 반영\n"
                            "[현재 소스]\n기반사항 입력값을 검증하고 조회 결과를 표시\n"
                        )
                        if index == 71
                        else (
                            "[Git diff]\n공통 입력값의 조회 조건을 수정\n"
                            "[현재 소스]\n입력값을 검증하고 조회 결과를 표시\n"
                        )
                    )
                    * 15,
                )
            )
        bundle = ScanBundle(
            changes=changes,
            contexts=contexts,
            change_notes=[
                "feat: 저장 시 변경된 사항이 없으면 Alert 처리",
                "refactor: node 삭제에 대한 edge 처리 대응",
            ],
            scanned_files=6400,
            warnings=["변경 파일 근거가 예산에 맞게 축약됨"],
        )

        request = "사업계획관리시스템 기반사항 반영"
        prompt = build_prompt(bundle, request)
        self.assertLessEqual(len(prompt), PROMPT_MAX_CHARS)
        self.assertLess(prompt.index(request), prompt.index("# 변경 파일 목록"))
        self.assertIn("변경 항목: 72개", prompt)
        self.assertIn("사용자 변경 요약: 2개", prompt)
        self.assertIn("저장 시 변경된 사항이 없으면 Alert 처리", prompt)
        self.assertIn("PlanBase00.tsx", prompt)
        self.assertIn("PlanBase71.java", prompt)
        self.assertIn("항목 수는 커밋과 파일 수가 아니라", prompt)
        context_prompt = prompt[prompt.index("# 선택된 소스 근거") :]
        self.assertLess(context_prompt.index("PlanBase71.java"), context_prompt.index("PlanBase00.tsx"))
        self.assertTrue(prompt.rstrip().endswith("}"))

    def test_oversized_request_is_bounded_without_cutting_output_contract(self):
        bundle = ScanBundle(
            changes=[
                ChangeItem("C:/sample", "src/PlanService.java", "변경", "manual", True)
            ],
            contexts=[
                ContextFile(
                    "C:/sample",
                    "src/PlanService.java",
                    "full",
                    "변경 근거",
                    1000,
                    "class PlanService {}" * 5000,
                )
            ],
        )
        prompt = build_prompt(bundle, "사업계획 기반사항 반영 " * 3000)
        self.assertLessEqual(len(prompt), PROMPT_MAX_CHARS)
        self.assertIn("개발 의뢰 일부 생략", prompt)
        self.assertTrue(prompt.rstrip().endswith("}"))

    def test_evidence_excludes_prompt_examples_and_redacts_request_secrets(self):
        bundle = ScanBundle(
            changes=[ChangeItem("C:/sample", "src/UserService.java", "변경", "manual", True)],
            contexts=[
                ContextFile(
                    "C:/sample",
                    "src/UserService.java",
                    "focused",
                    "변경 근거",
                    1000,
                    "class UserService { void findUser() {} }",
                )
            ],
        )
        prompt, evidence = build_prompt_package(
            bundle,
            "사용자 조회 조건 변경 GEMINI_API_KEY=do-not-send-this-secret",
        )

        self.assertIn("사업계획관리시스템", prompt)
        self.assertNotIn("사업계획관리시스템", evidence)
        self.assertNotIn("do-not-send-this-secret", prompt)
        self.assertNotIn("do-not-send-this-secret", evidence)
        self.assertIn("[REDACTED]", evidence)


if __name__ == "__main__":
    unittest.main()
