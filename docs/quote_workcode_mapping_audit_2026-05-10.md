# Quote work_code 매핑 검증 (2026-05-10)

`backtest_v5_quote_sidecar.py`의 `QUOTE_WC_TO_SIDECAR` 매핑 11종에 대한 도메인 검증.
방법: sidecar `material_quote_lines` (item_name + vendor + spec) vs sidecar
`actual_costs_enriched` (raw_title + vendor_name_raw) 동일 work_code로 묶인
top 자재 raw 비교.

## 결과 요약

| Quote WC | Sidecar 매핑 (수정 후) | 상태 | 근거 |
|---|---|---|---|
| STR-ST | 01. 골조 | ✅ 정확 | H형강 spec, 삼남강재 vendor 양측 일치 |
| FIN-PANEL | 02. 판넬 | ✅ 정확 | 우레탄판넬, 진호판넬 vendor 일치 |
| FIN-CARP | 13. 경량 | ✅ 정확 | quote의 L1669/ㄴ2298/UDT3056은 LGS 경량철골 단면 코드 (목공사 naming이지만 자재는 경량) |
| FIN-FLOOR | **11. 바닥난방** | ✏️ 수정 | quote는 온수난방패널/태경에스엔씨 — 12.마루(드림상재/구정마루)와 다른 자재 |
| EXT-WIN | 03. 창호 | ✅ 정확 | 창호, 삼보에스앤씨 일치 |
| MEP-ELEC | 05. 전기 | ✅ 정확 | LED 조명, 소노조명 일치 |
| MEP-HVAC | 07. 환기/공조 | ✅ 정확 | 환풍기/공조, 힘펠 일치 |
| FUR | 14. 수장/도어 | ⚠️ 부분 일치 | quote는 가구/붙박이/인조석(나모바치), sidecar 14는 목자재/도어(삼보)와 가구 일부. sidecar 20.가구 별도 존재(₩590k 미미)지만 14가 amount 큼 |
| FUR-DOOR | 08. 현관문 | ✅ 정확 | 방화문/도어클로저 일치 |
| EXT-DECK | 29.데크 | ✅ 정확 | 데크 자재 |
| SITE-DEMO | 토목 | ⚠️ 무용 | sidecar `토목` 카테고리 MAT 0건. 매핑 자체 효과 X. quote amount는 디자인엠에이 vendor 4건 (item_name='1','2','3','5' 의미 불명) |

## 수정 결과 — 효과 변화

| 지표 | 매핑 수정 전 | 매핑 수정 후 | 비고 |
|---|---:|---:|---|
| MAT proj-sum (point) | 19.1% | 19.1% | 동일 |
| MAT cell | 34.0% | 34.2% | +0.2pp |
| total_wmape | 28.8% | 28.8% | 동일 |

`FIN-FLOOR → 11. 바닥난방` 수정은 amount 작아 전체 영향 미미. 단 의미적 정확성
확보 — production 적용 시 신뢰성.

## 권장 추가 작업

1. **sidecar work_code_text 정규화** — sidecar에 'FUR'(영어), '목공'(1건), '14. 수장/도어',
   '20. 가구' 같이 카테고리 단위 일관성 부족. notion `'공종'` 컬럼 source 정제
   필요 (Phase 2).
2. **매핑 dict 영구 보존** — 운영 work_codes 테이블에 영어 work_code별 한글
   alias 컬럼 추가하면 hard-coded mapping 의존 제거 가능.
3. **모호 매핑 모니터링** — FUR/FIN-CARP는 production 적용 시 cell-단위 wMAPE
   추적해서 sub-카테고리 분리 검토.

## Raw 데이터 샘플 (검증 evidence)

### STR-ST → 01. 골조 (✅)
```
QUOTE:    'H' 150*150*7*10  amt=8,769,600  vendor=삼남강재
SIDECAR:  '테스트베드 H형강'   amt=29,789,760  vendor=삼남강재
```

### FIN-FLOOR (수정 사유)
```
QUOTE FIN-FLOOR: '온수난방패널' (TKBS200)   amt=5,600,000  vendor=태경에스엔씨
SIDECAR 12.마루:  '화성 쌍학리_마루'           amt=900,000     vendor=드림상재
SIDECAR 11.바닥난방: '바닥난방 자재' 1건         amt=1,402,500  vendor=태경에스앤씨 (matches quote)
```

### SITE-DEMO (무용 사유)
```
QUOTE SITE-DEMO: '1','2','3','5' (item_name 의미 불명)  vendor=디자인엠에이
SIDECAR 토목 (MAT): 0건
```

## 다음 1순위 후속 작업 (개정 v3)

1. ~~매핑 정확도 검증~~ ✅ 완료 (이 문서).
2. **학습 풀 N 확대** — 운영 module 매칭 안 된 5건 (N-08/14/15/17/22) project_modules 보강.
3. **Phase 2 production 적용** — `data_access` v2 query에 quote correction 영구 통합 + `/api/notion/estimate` 결과 자동 적용.
4. **FUR 카테고리 sub-분리** — 가구/수장/도어 의미상 분리. v6 측정 검토.
