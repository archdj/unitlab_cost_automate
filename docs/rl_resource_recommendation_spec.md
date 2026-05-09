# RL 멀티 프로젝트 리소스 추천 — Spec

`unitlab_autocost` 의 wMAPE 개선과는 **별개의 task**. sandbox 문서
(`autocost-spec-2026-05-07/sandbox_5d4b81b6` doc1/doc2/doc3) 의 §리소스 추천 기능을
RL frame으로 구현하는 spec.

---

## 0. 왜 RL 인가 — 적합성 검토

자재 비용 예측은 supervised regression이라 RL 부적합 (`docs/material_outlier_audit_2026-05-09.md` 의 분석 흐름 참조). 그러나 **멀티 프로젝트 리소스 추천**은 RL에 정확히 맞는 sequential decision problem:

| 요소 | RL 필요 조건 | 본 task 적용 |
|---|---|---|
| State | 시점별 상태 변화 | (각 프로젝트 진행상태, 공정 일정, vendor 가용성, 공장 capacity) |
| Action | agent의 선택 | (어느 자재를 언제 발주, 어느 vendor 묶음 사용, 공정 sequence) |
| Reward | 행동 결과 보상 | (MOQ/번들 절감액 + 일정 단축 + 공정 충돌 회피) |
| Sequential | 시간/순서 영향 | 자재 A 발주 후 자재 B 가능 (선행공정 의존) |
| Exploration | 새 조합 시도 | 같은 자재라도 vendor/시점 조합 다양 |

→ **RL 적합 ✅**

---

## 1. 비즈니스 목표 (sandbox 문서 발췌)

doc1_master_plan.html §11 "AI 개발자용 프롬프팅" → 프롬프트 5:
> 멀티 프로젝트 리소스 추천 — 공장 생산 일정 + 팀 중첩 분석 → SEQUENTIAL /
> PARALLEL / BATCH 추천 3종. 번들 묶음 절감 금액 제시.

doc1 §6 번들/MOQ 규칙 (핵심 5공정):
- **P05 창호** — 동일 개구부타입+프레임색상+유리스펙 4세트 MOQ, 번들 시 7~12% 할인
- **P15 계단** — 동일 타입+폭+디딤판+난간 2세트 MOQ
- **P16 난방** — zone 단위 묶음, 1 zone MOQ
- **P17 바닥마감** — 동일 자재코드+두께+패턴, 20㎡ MOQ, 폐기율 3~7%
- **P24 가구** — 동일 레이아웃+마감+하드웨어, 3세트 또는 1 room/project MOQ

→ 여러 프로젝트의 발주를 묶거나 분리하면 **절감 가능**. 이게 RL의 reward로 직결.

doc1 §9 게이트 체계:
```
G1 기본설계 → G2 BIM동결 → G3 현장실측 → G4 선발주승인
→ G5 공장생산 → G6 현장반입 → G7 설치완료 → G8 준공검수
```

각 게이트마다 발주 가능/불가 자재 결정. 예: P15(계단)은 G3 이전 발주 금지.

---

## 2. RL 환경 정의

### 2.1 State `s_t`

```python
state = {
    # === 프로젝트 상태 ===
    "projects": [
        {
            "project_id":      str,
            "current_gate":    "G1"~"G8",
            "anchor_date":     date,
            "module_count":    int,
            "grade":           "ESSENTIAL"/"STANDARD"/"BESPOKE",
            "remaining_processes": [P_code, ...],   # 미발주 공정 list
        }, ...
    ],
    # === 자재 BOM 상태 (각 프로젝트의 자재 요구) ===
    "boq_open": [
        {
            "project_id":   str,
            "process_code": "P01"~"P40",
            "material":     str,
            "spec":         dict,      # 4세트 MOQ 매칭용
            "qty":           float,
            "earliest_gate": "G1"~"G8",  # 이 게이트 이후 발주 가능
            "deadline":      date,
        }, ...
    ],
    # === 공장/팀 capacity ===
    "factory_schedule": {
        date: {"capacity_used": float, "capacity_total": float}, ...
    },
    "team_schedule": {
        team_id: {date_range: project_id, ...}, ...
    },
    # === 누적 ===
    "today":           date,
    "ordered_history": [...],   # 이전 발주
}
```

### 2.2 Action `a_t`

각 step 에서 agent 가 선택할 수 있는 action:

```python
action = {
    "type": "ORDER",     # 발주 결정
    "items": [
        {"project_id": str, "boq_id": str, "vendor_id": str},
        ...   # 묶음 발주 시 multiple
    ],
    "schedule_date": date,
}
# 또는
action = {"type": "WAIT"}     # 1 step 대기

# 또는
action = {
    "type": "ASSIGN_TEAM",
    "team_id": str, "project_id": str, "date_range": (start, end),
}
```

### 2.3 Reward `r_t`

multi-objective reward:

```python
reward = (
    + 1.0 * bundle_savings       # MOQ/번들 적용 시 할인 금액 (원)
    + 0.5 * schedule_compliance  # 일정 준수 (deadline 안 어김)
    - 2.0 * gate_violation       # 게이트 어김 (예: G3 이전 P15 발주)
    - 0.5 * factory_overflow     # 공장 capacity 초과
    - 0.3 * team_conflict        # 같은 팀이 여러 프로젝트 중첩
    - 0.1 * holding_cost         # 너무 일찍 발주 → 보관 비용
)
```

### 2.4 Episode termination

모든 프로젝트가 G8(준공검수) 도달 시 episode 종료. 또는 단순화하여 N년 시뮬레이션.

---

## 3. Data source

### 3.1 학습 가능한 historical data

운영 DB `cost_analysis.db` + sidecar `autocost_enriched.db`:

| Source | 사용 목적 |
|---|---|
| `actual_costs` (1,300 row, 8 프로젝트) | 과거 발주 history → expert demonstration |
| `material_quote_lines` (588 line, 견적서) | vendor 단가 분포, MOQ 검증 |
| `work_codes` 38개 level=2 | 공정 카테고리 |
| sandbox doc 의 P01~P40 매핑 | 게이트/MOQ/번들 규칙 |

### 3.2 시뮬레이션 환경 prerequisite

historical data 만으로는 RL 학습 불가능 (8 프로젝트 = 8 trajectory). 시뮬레이션 환경 필요:

- **Project generator** — sandbox doc 의 module type (T-12, T-15, S-18 등) 으로
  random 프로젝트 생성. anchor_date / module_count / grade 분포는 historical 통계.
- **BOQ template** — 각 module type 별 표준 자재 list. sandbox §6 P01~P40 마스터에서.
- **Vendor pool** — `vendors_master` 의 363개 + 자재별 단가 분포 (`material_quote_lines`).
- **MOQ/번들 룰 엔진** — sandbox §7 의 5개 룰 코드화.

---

## 4. 학습 가능성 평가

### 4.1 RL 알고리즘 후보

| 알고리즘 | 적합성 | 비고 |
|---|---|---|
| **PPO** (Proximal Policy Optimization) | ★★★ | 일반적, sample efficient, 안정 |
| **A2C / A3C** | ★★ | 병렬 학습 가능 |
| **SAC** | ★★ | continuous action 강함, action discrete 인 경우 약함 |
| DQN | ★ | discrete action 만, 본 task 의 multi-item action 에 부적합 |
| **MARL** (multi-agent) | ★★★ | 각 프로젝트를 agent 로 봐서 협업/경쟁 명시 |
| Imitation Learning + RL fine-tune | ★★★ | historical 8 프로젝트 expert demo + simulation fine-tune |

**권장: PPO + Imitation Learning warm-start**.

### 4.2 학습 비용 추정

| 항목 | 추정 |
|---|---|
| 시뮬레이션 환경 구축 | 2~3 주 (BOQ template + MOQ 룰 + scheduler) |
| Imitation 학습 (8 expert traj) | 1 주 |
| RL 환경 + agent 학습 | 1~2 주 (CPU 기반 PPO, 100k~1M step) |
| 평가 + 시각화 | 1 주 |
| **합계** | **5~7 주** (1 dev) |

### 4.3 ROI 예상

sandbox doc §리소스 추천:
> 창호·가구·계단 묶음 발주 / PM 팀 연속 투입 / 게이트 동기화 추천. 절감액·신뢰도 표시.

historical 발주 1,300건 / 25.8억 기준 7~12% 번들 할인 가능 자재 비중 추정:
- P05 창호 + P15 계단 + P24 가구 ≈ 자재의 30~40%
- 이 중 multi-project 묶음 가능 비율 30%
- 평균 할인 10%
- → **잠재 절감액 = 25.8억 × 35% × 30% × 10% ≈ 2,700만원/년**

5~7주 작업 → 연 2,700만원 절감 = ROI 양호.

---

## 5. 실행 단계

### Phase 1 — 시뮬레이션 환경 (3주)

- `harness/sim/project_generator.py` — random 프로젝트 생성기
- `harness/sim/boq_templates.py` — module type → BOQ list
- `harness/sim/moq_engine.py` — 5개 룰 (P05/P15/P16/P17/P24) 코드화
- `harness/sim/scheduler.py` — 공장 capacity / 게이트 체크
- `harness/sim/env.py` — gym.Env 인터페이스

### Phase 2 — Imitation 학습 (1주)

- historical 8 프로젝트 → expert action 추출 (어떤 자재를 언제, 어느 vendor 로 발주했는지)
- Behavior Cloning 으로 baseline policy
- baseline metric: 단순 FIFO 대비 reward 비교

### Phase 3 — RL 학습 (2주)

- PPO agent 환경에서 학습 (100k~1M steps)
- Imitation policy로 warm-start
- 평가: 새 random 프로젝트 셋에서 expert / heuristic / random 대비 reward 비교

### Phase 4 — 검증 + UI (1주)

- 8개 historical 프로젝트 replay 시 RL 추천 vs 실제 발주 비교
- 절감액 추정 dashboard
- sandbox doc 의 리소스 추천 UI 와 통합

---

## 6. Risk

| Risk | 완화 |
|---|---|
| 시뮬레이션 environment 와 reality gap | historical replay 검증 + domain expert review |
| MOQ/번들 룰의 부정확성 | sandbox doc §7 + vendor 와 inteviw 로 룰 정제 |
| RL agent 가 비현실적 발주 (예: 6개월 전 발주) | reward 에 holding_cost penalty 강화 |
| 학습 비용 (CPU/시간) | discrete action space 단순화, episode length 제한 |
| 8개 프로젝트 historical 만으로 expert 부족 | sandbox doc 의 BOQ template 으로 expert demo augmentation |

---

## 7. wMAPE 개선과의 관계

이 RL task 는 자재 wMAPE 개선과 **무관**. 자재 wMAPE 는 supervised regression의
정확도 metric이고, RL은 발주 의사결정의 비용 절감 metric. 두 task 는 독립적으로
실행 가능.

다만 **공유 인프라**:
- `material_quote_lines` (588 line) → vendor 단가 분포 source
- `actual_cost_corrections` (83 row) → expert action ground truth
- `work_code_keywords.py` → 자재 카테고리 매핑

---

## 8. 다음 결정

| 결정 | 옵션 |
|---|---|
| **승인** | Phase 1 즉시 착수 (5~7주 commit) |
| **PoC 먼저** | sandbox doc 의 시뮬레이션 prototype 1주 — 가능성 검증 후 full commit |
| **보류** | 운영 흡수 후 (트리거 재협상 완료 후) 별 도구로 분리 진행 |

권장: **PoC 먼저** (1주). simulation env minimal version + 1개 module type
(T-12) 만 generator 작성 후 imitation 학습 baseline 측정. ROI 확인 후 full commit.
