# Excel 템플릿 규약

Promptcase Studio는 `templates/단위테스트 템플릿.xlsx`를 새로 그리지 않습니다. 원본 XLSX의
시트, 병합, 너비, 높이, 테두리와 스타일을 그대로 복사하고 내용 셀만 치환합니다.

현재 템플릿처럼 입력 셀이 비어 있어도 기존 좌표 규약으로 동작합니다. 아래 placeholder를 셀에
넣으면 좌표보다 placeholder 치환을 우선하므로, 향후 행이나 열 배치를 바꿀 때 더 안전합니다.

## 프로그램 정보 시트

4행을 변경 파일 수만큼 복제합니다.

- `{{program}}`: 프로그램 파일명
- `{{project}}`: 프로젝트명과 Frontend 또는 Backend 구분
- `{{work_content}}`: 작업 내용
- `{{change_type}}`: 신규, 변경, 삭제, 이름변경

## 테스트케이스 시트

- `{{name}}` 또는 `{{testcase_name}}`
- `{{type}}` 또는 `{{testcase_type}}`
- `{{procedure}}`
- `{{target_ids}}`
- `{{target_names}}`
- `{{preconditions}}`
- `{{test_data}}`
- `{{expected_result}}`
- `{{notes}}`

## 테스트 결과 시트

- `{{processing_details}}`
- `{{test_details}}`
- `{{result_checks}}`

한 셀 안의 `제목: {{name}}`처럼 고정 문구와 placeholder를 함께 사용할 수도 있습니다. 지원하지
않는 placeholder가 남으면 미완성 문서가 생성되지 않도록 오류로 처리합니다.
