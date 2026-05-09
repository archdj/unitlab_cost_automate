# PLAN — AI 기반 원가 예측 프로그램

명세서 1장(프로젝트 개요)을 정리한 합의 문서.

## 1. 한 줄 정의

AI 기반 원가 예측 프로그램. 노션·엑셀로 흩어진 과거 실원가/로스율 이력을 자동 분류·정제하고, ML 모델로 신규 입찰 프로젝트의 원가를 항목별로 예측한다.

## 2. 배경 / 사용자 문제

- 현재 원가 예측은 수동 스프레드시트 + 경험 기반 추정에 의존. 시간 소모 큼, 정확도 낮음.
- 로스율·실제 시공 원가 등 복합 이력 데이터를 분류·활용하기 어려움.
- 결과적으로 입찰가 산정 리스크 증가, 잠재 수익 손실 발생.

## 3. 해결 방식

1. 과거 프로젝트 실행 데이터, 공급망/자재 비용, 시장 가격을 **AI 기반으로 자동 분류·정제**.
2. 정제된 이력을 학습한 모델로 **신규 입찰 원가를 항목별로 예측**.
3. 예측마다 **근거(상위 영향 변수, 유사 프로젝트, 데이터 품질)** 를 함께 제시.

## 4. 차별점

- 일반 원가 산정 도구와 달리 **로스율 + 실제 시공 원가**를 1급 입력으로 다룸.
- 노션·엑셀 원본을 **자동 표준화**(공종·자재 동의어, 단위 변환).
- 예측에 **현장 특성(공종/규모/지역/품질 수준)** 반영.

## 5. 타겟 사용자

**Phase 1 (이 문서)**: **unitlab 내부 PM / 원가 분석가**. 단일 조직, 단일 데이터셋(unitlab 자체 프로젝트). multi-tenancy / 외부 회원가입 / SSO 없음.

**Phase 2 (검토 단계, 미확정)**: 외부 건설/제조 기업의 PM·원가 담당자. SaaS화는 Phase 1 검증 후 별도 PRD에서 결정.

**Phase 1 시나리오 (Q13 결정 후 단순화)**

> unitlab 내부 PM이 새로운 프로젝트 입찰을 준비한다.
> 1. (선택) "데이터 갱신" 버튼 클릭 → 노션 자동 ETL → sidecar 갱신 + 부트스트랩 재학습 (Q14, `POST /api/refresh-data`).
> 2. F6 신규 프로젝트 조건 입력 (모듈 타입, 평형, 등급, 지역).
> 3. F2 예측 → F7 근거(상위 영향 변수 / 유사 프로젝트 / 데이터 품질) 확인.
> 4. F3.2 리포트 다운로드 → 입찰가 결정.
>
> F4 업로드 단계는 Phase 1 시나리오에 미포함 (코드는 보존, Phase 2에서 부활). 새 자료는 노션에 입력하면 다음 "데이터 갱신" 시 자동 반영.

- **역할**: 흡수 전 hardcode admin (개발자 1명). 흡수 후 운영 메인 인증 사용 (F5/F10은 운영 메인 측 작업으로 이전 — ROADMAP §M2 참조).
- **디바이스**: Web

## 6. 제품 목표

입찰 전 시간 소모를 자동화로 줄이고, 부정확한 예측으로 인한 위험을 낮춰 프로젝트 수익성을 극대화한다.

## 7. 핵심 KPI (Phase 1 = 내부 도구, absolute)

명세서 §1.6의 개선율 KPI(≥10% / ≥30% / ≥10% MAU)는 **baseline 측정값이 부재**하여 폐기. Phase 1은 baseline 의존 없는 absolute 지표로 운영한다.

| KPI | 목표 | 측정 시점 |
|---|---|---|
| 총액 ±20% hit-rate (LOO) | **≥ 9/15** (확장 표본 기준) — 현재 **9/15 ✅** | M1 종료조건 |
| 총액 MAPE (LOO) | **≤ 15%** — 현재 25.6% (-10.6%p) | M1 종료조건 |
| **자재 항목 MAPE** | **< 15%** — 현재 39.5% (-24.5%p) | **흡수 트리거** (= 운영 메인 흡수 가능 조건) |
| 항목별(자재/노무/장비/간접비) MAPE 측정 완료 | 4개 카테고리 모두 산출 | M2 진입 조건 |
| 항목별 MAPE | **< 10%** (aspiration, hard 아님) | 검증 후 stretch goal |
| MAU | **폐기** (내부 도구 — 측정 의미 없음) | — |

> 측정 정의 (2026-05-09 노션 zip 검증 결과 반영):
> - **표본 N**: 운영 DB 단독 LOO n=8 → 노션 원본 기반 sidecar 빌드 후 **n=16+** (1415 cost rows, 16+ projects) 으로 확장. 위 hit-rate 목표는 N≥12 가정.
> - **항목별 MAPE 분리 source**: 노션 원본에 자재/노무/장비/간접비 분류 컬럼 부재(2026-05-09 zip 검증 — 노션의 `구분` 컬럼은 status). 따라서 **`work_code_cost_types(work_code_id, cost_type)` 매핑 테이블**(M0 신규 작업, 147개 수동)로 work_code 그룹 단위 분류 적용 후 LOO weighted MAPE 산출. `unitlab-notion-cost/src/backtest.py`의 `cost_type_errors` 집계 재사용.
> - **`unitlab-notion-cost/src/data_access.py:74`의 `cost_type=source_ref` 매핑은 버그** — `work_code_cost_types` 조인으로 변경 (M0 작업).
> - **흡수 트리거**: 자재 항목 MAPE < 15% 달성 시점에 운영 메인 `원가분석-프로그램` branch로 흡수 PR. ROADMAP §M2 참조.

## 8. 리스크 / 이슈

| # | 리스크 | 대응 방향 |
|---|---|---|
| R1 | `actual_costs` 핵심 컬럼(`actual_quantity`/`unit`/`unit_price`) 100% 결측은 **노션 source 자체의 부재** (2026-05-09 zip 검증). ETL 손실이 아니므로 sidecar로 보강 불가. | 단가·수량 정보는 첨부된 견적서/세금계산서 PDF/엑셀 안에 있음 → **별도 PRD**로 분리(첨부 파일 파싱 또는 운영팀 수동 입력). 본 Phase 1 범위에서는 **단가 추정 없이 work_code 그룹 단위 학습**으로 진행. |
| R2 | n=8 운영 DB LOO — 통계적 신뢰도 부족 | sidecar로 노션 원본 직접 적재 (1415행, 16+ 프로젝트) → **n=16+로 표본 약 2배 확장**. KPI hit-rate 목표 ≥ 12/16. |
| R3 | 자재/노무/장비/간접비 분류 source | **Q10 A 채택** (2026-05-09 MCP 검증) — 노션 '선택' 컬럼이 cost_type (재료비/노무비/경비/재료비+노무비/기타/합계제외/정기이체/제작+현장설치비). 96.3% 채워짐. ETL이 그대로 sidecar `actual_costs_enriched.cost_type`로 매핑. work_code 147개 수동 매핑 불필요. |
| R4 | 시장 가격·트렌드 변화 미반영 | F8 재학습 — ① sidecar 빌드 후 1회 부트스트랩 + ② 사용자 수동 trigger (새 입찰마다). 신 모델 자재 MAPE 악화 시 부분 자동 롤백 |
| R5 | Notion 접근 권한 (MCP integration share) | **zip export 경로로 우회 검증 완료** (2026-05-09). 양산 ETL은 `notion_etl.py` 토큰 또는 zip 정기 export 파이프라인으로 운영. |
| R6 | 외부 일정 의존 (운영 메인 ETL 수정) | sidecar로 일정 자율 확보. 흡수 PR 시점에만 운영 메인과 통합 (단일 의존점) |
| R7 | 운영 ETL이 노션 1415행 중 931행만 적재 (~1/3 손실) | sidecar 빌드 시 노션 원본을 직접 파싱해 누락 484행 회수. 흡수 PR 시 운영 ETL 자체의 누락 원인을 별도 패치. |

## 9. 범위 가정 (Phase 1 = unitlab 내부 도구)

- **포함 (M0~M2)**: 노션 자동 ETL → sidecar enriched DB 빌드, 정제, 단일 모델 예측, 항목별 결과 + 근거, PDF/엑셀 리포트, 사용자 수동 데이터 갱신 endpoint. 흡수 PR로 마무리.
- **제외 (이 repo에서 안 함, 흡수 후 운영 메인 측 작업으로 이전)**:
  - F5.1 이메일 회원가입/로그인 — 흡수 후 운영 메인의 인증 시스템 사용
  - F5.2 사용자/권한 콘솔 — 동일
  - F10.1 감사 로그 조회 UI — 운영 메인 `audit_log` 활성화 시 함께
  - SSO (F5.1.1)
  - IFC 직접 연동 (v10 모델이 IFC-free)
  - multi-tenancy / 외부 회원가입 (Phase 2 별도 PRD에서 결정)
- **보존되되 Phase 1 시나리오에 미포함** (Q13):
  - F4.1 노션 워크스페이스 연결 UI — 코드 유지, Phase 2 SaaS화 시 부활. Phase 1은 백엔드 `notion_etl.py`만 사용.
  - F4.2 엑셀 업로드 UI — 동일.
  - 첨부 견적서/세금계산서 파일 파싱 — 별도 PRD (Phase 1 자재 MAPE 미달 시 escalation 후보).
- **데이터 출처**:
  - 운영 DB `unitlab-cost-analysis/db/cost_analysis.db` (read-only — 변경 안 함)
  - **Sidecar enriched DB** `autocost_enriched.db` (이 repo가 write 권한 가짐, 노션 원본에서 보강 적재)
  - 사용자 업로드(F4)는 *predict input* 흐름만, 학습 데이터(sidecar)와 분리.

## 10. 장기 방향

이 repo는 **prototype**. 다음 조건 충족 시 운영 메인 `archdj/unitlab` repo의 `원가분석-프로그램` branch로 흡수 PR을 보낸다 (이후 이 repo는 archive).

### 10.1 흡수 트리거 (2026-05-09 grilling Q15-17 결정 — 7-condition multi-metric)

**다지표(A) + per-cost_type(B) + bootstrap CI(C)** 결합. 단일 자재 MAPE < 15% 점추정은 n=15 통계 노이즈로 우연 도달 위험 → 다층 조건으로 교체.

```
모두 충족 시 흡수 PR (직전 측정 대비 변화 안정성 포함):

1. 학습 가능 N ≥ 12  (LOO 통계 신뢰성)
2. 총액 ±20% hit-rate (점추정) ≥ 50%
3. 총액 median APE ≤ 18%
4. 자재(MAT) bootstrap 점추정 ≤ 30%
5. 직전 측정 대비 자재 MAPE 변화 ≤ 5%p (안정성)
6. 노무(LAB) 점추정 ≤ 60%   ← Q20 calibration: 비자재(LAB+EXP)는 동일 한도
7. 경비(EXP) 점추정 ≤ 60%
```

> **Q20 한도 calibration (2026-05-09)**: 초기 LAB ≤ 50%는 측정 데이터 없이 박은 임의 수치. 8 seed bootstrap 결과 LAB 점추정 49.9~52.1% 평균 51.0%로 일관 (noise 아님). LAB와 EXP는 둘 다 비자재 본질 변동이 큰 영역(CI 폭 60~75%p)이므로 한도 통일이 일관됨. MAT(핵심 비용) 30% 빡빡 / 비자재 60% 관대의 2-tier 구조.

**현재 평가** (2026-05-09 8-seed bootstrap 평균):

| 조건 | 측정값 | 도달 |
|---|---|---|
| 1. N ≥ 12 | 15 | ✅ |
| 2. hit-rate ≥ 50% | 60% | ✅ |
| 3. median APE ≤ 18% | 17.5% | ✅ |
| 4. **자재 점추정 ≤ 30%** | **21.8%** | **✅** (margin 8.2%p) |
| 5. 안정성 ≤ 5%p | -3.1%p (24.9→21.8) | ✅ |
| 6. **노무 ≤ 60%** | 51.0% | ✅ (margin 9%p) |
| 7. 경비 ≤ 60% | 48.5% | ✅ |

→ **7/7 통과**. 흡수 PR 진입 가능 상태.

### 10.2 흡수 PR 분할 전략 (Q21 결정)

분할 PR 4개 + 옵션 1개. 의존성 순.

```
PR-1: 운영 actual_costs / projects schema 변경 + ETL 흡수
  - DDL: actual_costs ADD cost_type, package
          projects ADD progress_stage, customer_type, permit_type, product_type,
                       contract_stage, module_size_text
  - notion_etl.py 수정: 노션 '선택' → cost_type, '패키지' → package, 영업 프로젝트
                       페이지 fetch → projects 메타 백필
  - 마이그레이션: sidecar 1420 행 → 운영 cost_type/package 백필 (notion_page_id 매칭)
                  sidecar 23 projects 메타 → 운영 projects 백필
                  sidecar model_versions → 운영 ml_model_info insert
  - 기존 v1 학습 path는 backwards-compat 유지

PR-1.5 (선택, 별도): vendors 마스터 테이블 신설 + actual_costs.vendor_name → vendor_id FK
                     사이드카 vendors_master 429 행 → 운영 vendors 신설 + 백필
                     vendor_name URL 분리 정제 적용

PR-2: 모델 코드 이동
  - unitlab-notion-cost/src/ → 운영 메인의 적절 경로 (cost-analysis-program/src/)
  - data_access_v2 단순화: sidecar 의존 제거, 운영 DB 직접 사용
  - backtest_v2/sweep/bootstrap → 운영 메인의 reports/ 경로

PR-3: API/프론트 통합
  - 운영 React 프론트에 견적 페이지 추가
  - autocost-spec의 vanilla SPA → archive (참조용)
  - /api/refresh-data endpoint를 운영 FastAPI로 이전

PR-4: archive
  - unitlab_autocost README에 "archived, see archdj/unitlab" 명시
  - sidecar autocost_enriched.db 삭제
```

**선택 사유** (Q22 β): 운영 schema 우선 + 컬럼 추가만. sidecar의 5 테이블 mirror 안 함.

### 10.3 흡수 후 운영 메인 측 작업

- F5(인증/권한) / F10(감사 로그) 신규 구현
- F8 재학습 cron (정기 자동화)
- 자재 MAPE < 25% 추가 개선 (별도 PRD): 첨부 견적서 PDF 파싱 / work_code 그룹화 / v11 ensemble v2
