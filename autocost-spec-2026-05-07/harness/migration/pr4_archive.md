# PR-4: archive 절차

전제: **PR-1, PR-2, PR-3 머지 완료** — 운영 메인이 자립 가능 상태.

본 PR의 목표:
1. `unitlab_autocost` repo를 archive (read-only, 더 이상 작업 안 함)
2. sidecar `autocost_enriched.db` 폐기
3. 운영 메인 README에 흡수 사실 기록

---

## 1. 사전 검증 (archive 전)

흡수가 정말 자립한지 확인:

```bash
# 운영 메인 측에서 (이 repo 의존 없이) 다음이 모두 통과해야 함:
cd <운영-메인-repo>

# 1. 운영 DB 단독으로 backtest 돌아감 (sidecar 의존 0)
python -m cost_analysis_program.backtest

# 2. trigger 7-condition 통과 유지
python -m cost_analysis_program.tools.backtest_bootstrap

# 3. 사용자 시연 endpoint 작동
curl http://운영서버/api/cost-prediction/health
curl -X POST http://운영서버/api/refresh-data

# 4. 노션 ETL 정상 동작 (cost_type, projects 메타 적재)
python -m agents.notion_etl --dry-run
```

모두 통과하면 archive 진입.

---

## 2. archive 절차

### 2.1 이 repo (`unitlab_autocost`)

```bash
# README.md 갱신
cat > README.md <<'EOF'
# unitlab_autocost (ARCHIVED 2026-MM-DD)

이 repo는 모듈러 건축 원가 예측 prototype. 검증 완료 후 운영 메인 repo로 흡수됨.

**현재 운영 위치**: archdj/unitlab `원가분석-프로그램` branch

archive 시점 baseline:
- LOO ±20% hit-rate 60% (9/15)
- median APE 17.5%
- 자재 MAPE bootstrap 점추정 21.8%
- 7-condition trigger 7/7 통과 (PLAN.md §10.1)

흡수 PR 이력:
- PR-1: 운영 schema + ETL 흡수 (cost_type, package, projects 메타)
- PR-1.5: vendors 마스터 (옵션)
- PR-2: 모델 코드 이동 + data_access 단순화
- PR-3: API + React 프론트 통합
- PR-4: 본 archive

이력 보존 목적으로 read-only 유지.
EOF

# GitHub 측 archive 처리
# Settings → General → Archive this repository (운영 책임자)
```

### 2.2 sidecar DB 폐기

```bash
# 흡수 검증 완료 후, 안전하게 삭제 가능:
rm autocost-spec-2026-05-07/harness/data/autocost_enriched.db

# 백업 보존 권장:
mv autocost-spec-2026-05-07/harness/data/autocost_enriched.db \
   autocost-spec-2026-05-07/harness/data/autocost_enriched.archived-$(date +%Y%m%d).db
```

또는 `harness/data/` 전체를 .gitignore화 + 로컬 보존.

### 2.3 운영 메인 README

```markdown
## 원가 예측 모듈 (2026-05 흡수 완료)

`cost_analysis_program/` 패키지. 이전엔 별도 repo `archdj/unitlab_autocost` 에서 prototype.
흡수 PR 이력: ../unitlab_autocost/autocost-spec-2026-05-07/harness/migration/ 참조 (archived).
```

---

## 3. 의존성 정리

### 3.1 이 repo에서 운영 메인을 참조하던 경로

`unitlab-notion-cost/src/data_access.py`:
```python
# 이전:
DB_PATH = REPO_ROOT.parent.parent / "unitlab-cost-analysis" / "db" / "cost_analysis.db"
# archive 시 의미 없음 — 운영 메인이 자체 경로 사용
```

운영 메인의 새 `data_access.py`는 자체 경로 컨벤션 사용 (PR-2 spec).

### 3.2 운영 메인이 이 repo를 참조한 적 없음 ✅
양방향 의존성 없음 — clean archive 가능.

---

## 4. 보존 자료

archive 후에도 참조 가치:

- `autocost-spec-2026-05-07/PLAN.md` / `ROADMAP.md` / `docs/` — 흡수 시점의 결정 이력
- `autocost-spec-2026-05-07/harness/migration/pr1~pr4.md` — 흡수 PR 자체 spec
- `unitlab-notion-cost/reports/` — bootstrap CI / sweep 결과 (baseline 측정 history)
- memory `project_*.md` — grilling 결정 이력

이들은 운영 메인 ADR로 옮기거나 archive에 그대로 보존 (선택).

---

## 5. 산출물 체크리스트

- [ ] 운영 메인 측 PR-1/2/3 모두 머지 완료 검증
- [ ] PR-4 사전 검증 (§1) 4 항목 통과
- [ ] 이 repo `README.md` archive 명시로 갱신
- [ ] sidecar DB 백업 후 폐기 (또는 .gitignore화)
- [ ] 운영 메인 README에 흡수 사실 기록
- [ ] GitHub repo archive 처리 (운영 책임자)
- [ ] memory `project_phase1_identity.md` 에 archive 일자 추가

---

## 6. Phase 2 검토 진입 조건 (Out of scope)

archive 후, Phase 2 (외부 SaaS화) 검토는 **별도 PRD**:
- multi-tenancy schema 설계
- 외부 회원가입/SSO
- F4 업로드 UI 부활
- 외부 회사 데이터 도메인 transfer 검증

본 archive는 Phase 1 종결 의미. Phase 2는 새 design phase.
