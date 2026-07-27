# 변경 범위 회수 시뮬레이션

사용자가 일부 파일만 입력하거나 개발 시점을 정확히 기억하지 못하는 상황에서 현재 스캐너가
실제 변경 파일과 연관 근거를 어느 정도 회수하는지 측정한다. 로컬 임시 Git 저장소만
생성하며 외부 네트워크와 AI API를 사용하지 않는다.

## Mock 프로젝트

다음 참조 구조를 가진 Java·MyBatis 프로젝트를 생성한다.

```text
OrderController
  → OrderService
    → OrderServiceImpl
      → OrderHeaderVo / OrderLineVo / OrderSummaryVo
      → Mapper 인터페이스 4개
        ↔ Mapper XML 4개
```

실제 변경 대상으로 VO 3개, Mapper XML 4개와 VO를 직접 참조하는 ServiceImpl 1개를 사용한다.
잡음 파일과 잡음 커밋 수가 다른 세 저장소를 각각 만든다.

- 단일 변경 커밋과 적은 잡음
- VO·XML·ServiceImpl 분리 커밋과 중간 규모 잡음
- 분리 커밋, 소스 360개와 잡음 커밋 38개

각 저장소에서 입력 품질 4종과 날짜 범위 5종을 교차해 총 60개 시나리오를 실행한다.

### 입력 품질

- 전체 변경 파일 명시
- ServiceImpl만 명시
- VO 경로 3개만 명시
- 파일 경로 없이 `VO 몇 개 수정`이라고만 입력

### 날짜 범위

- 실제 변경 3일을 정확히 포함
- VO 커밋 날짜 하루만 선택
- 실제 날짜 전후를 넓게 포함
- 실제 날짜보다 일주일 뒤로 잘못 입력
- 한 달 범위를 포괄 입력

## 실행

```powershell
python scripts/simulate_scope_recall.py
```

프로필별로 나눠 실행하면서 기존 결과에 합칠 수도 있다.

```powershell
python scripts/simulate_scope_recall.py --profile single-commit-clean
python scripts/simulate_scope_recall.py --profile split-commits-noisy --append
python scripts/simulate_scope_recall.py --profile split-commits-heavy --append
```

보고서는 Git에서 제외된 `tmp/scope-simulation/latest-report.json`과
`tmp/scope-simulation/latest-report.md`에 생성된다.

## 측정 기준

- 변경 회수율: 실제 변경 대상 중 `change_manifest`에 포함된 비율
- 통합 회수율: 변경 파일 또는 연관 컨텍스트 중 하나로 확보한 비율
- ServiceImpl 변경 인식률: ServiceImpl을 Excel 프로그램 정보 대상 변경으로 인식한 비율
- ServiceImpl 근거 인식률: ServiceImpl을 변경 또는 연관 컨텍스트로 확보한 비율
- 오탐 변경: 실제 변경 대상이 아닌데 변경 파일로 선택된 수

날짜 오입력 보완 방식도 함께 비교한다.

- 무조건 확장: 입력 날짜에서 앞뒤 14일의 모든 Git 변경 경로를 포함
- 고신뢰 범위 복구: 제한된 확장 구간을 후보 탐색에만 사용하고 실제 Git 변경, 명시적 참조,
  가까운 변경 시점과 실제 변경 hunk 근거가 확인된 파일만 변경으로 승격
- 경로 없는 입력 복구: 입력 표현과 맞는 파일이 2개 이상이며 같은 업무 식별자로 응집된
  커밋 하나만 보완 앵커로 허용
- 명시 commit: GitHub·GitLab URL 또는 SHA가 있으면 날짜와 현재 작업트리 및 관계 복구보다
  우선하며, 선택 프로젝트 경로 안에서 그 commit의 변경만 정확히 사용

## 2026-07-27 기준 결과

| 항목 | 보완 전 | 고신뢰 범위 복구 적용 |
| --- | ---: | ---: |
| 전체 변경 회수율 | 52.8% | 100.0% |
| 통합 근거 회수율 | 75.0% | 100.0% |
| ServiceImpl 변경 인식률 | 58.6% | 100.0% |
| 평균 오탐 변경 | 0.38개 | 0개 |
| 실행 오류 | 2건 | 0건 |

날짜를 앞뒤 14일 무조건 확장하면 실제 변경 회수율은 100%였지만 평균 79.8개의 오탐 변경이
발생했다. 운영 로직은 기본 21일의 확장 구간을 변경 목록으로 사용하지 않고 후보 저장소로만
사용했다. 60개 시나리오에서 실제 대상 8개만 회수했고 무관 변경은 한 건도 승격하지 않았다.

전체 파일 명시, ServiceImpl만 명시, VO 경로만 명시, `VO 몇 개 수정`이라는 경로 없는 입력
각 15개 시나리오가 모두 변경 회수율 100%, ServiceImpl 변경 인식률 100%, 평균 오탐 0개를
기록했다.

분리 커밋, VO 경로 입력과 정확한 날짜를 조합한 대표 시나리오에서는 다음 결과가 나왔다.

```text
사용자 입력: VO 3개
복구 변경: Mapper XML 4개와 ServiceImpl 1개
최종 변경: 실제 대상 8개
무관 변경: 0개
```

## 운영 알고리즘

1. 수동 경로가 매칭되면 점수가 낮은 임의 Git 커밋은 변경 목록에서 제외한다.
2. 입력 날짜 앞뒤의 제한된 구간은 후보 탐색에만 사용한다.
3. 후보는 실제 Git 변경 파일이어야 하며 현재 소스에서 입력 파일과 정확한 import, 타입,
   mapper 계약, SQL 객체 또는 endpoint 관계가 확인되어야 한다.
4. 다른 커밋의 파일은 가까운 변경 시점과 diff의 실제 변경 행 또는 같은 변경 hunk의 참조
   식별자를 추가로 요구한다. 경로·diff 헤더와 무관한 문맥은 승격 근거로 사용하지 않는다.
   여러 입력 파일을 직접 참조하는 경우에도 같은 업무 경로와 비유지보수성 변경을 확인한다.
5. 경로가 전혀 없으면 사용자 표현과 맞는 파일이 2개 이상이고 같은 업무 식별자로 응집된
   커밋 하나만 선택한다. 단일 파일이나 후보 점수가 비슷하면 자동 추측하지 않는다.
6. 동일 Git 저장소의 여러 하위 폴더를 입력해도 복구 파일 한도는 저장소 전체에 한 번만 적용한다.
   경로 없는 의미 복구와 후속 참조 복구도 이 한도를 함께 사용하며, 의미 복구는 입력 경로 토큰과
   직접 일치한 파일만 승격한다.
7. 승격된 파일은 `git-related-recovery`와 선택 이유를 실행 근거에 기록한다.

관계 추출은 Java 계층명을 전제로 하지 않는다. Python import, JavaScript와 TypeScript module,
SQL 객체, MyBatis 계약, SAP 객체 등 기존 범용 참조 신호를 동일하게 사용한다. 별도 회귀
테스트에서 Java, Python, TypeScript와 SQL의 정방향·역방향 복구, 변경되지 않은 파일,
관련 없는 메서드 변경과 기능 비활성화 경로를 검증한다.
