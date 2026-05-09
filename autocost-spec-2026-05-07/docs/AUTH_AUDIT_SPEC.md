# AUTH_AUDIT_SPEC — 사용자/권한 (F5) + 데이터 보안·감사 로그 (F10)

M2에서 외부 사용자 시연이 가능하려면 이 묶음이 필요하다. SSO 등 일부는 M3로 미룬다.

## 1. F5 — 사용자 / 권한

### 1.1 F5.1 회원가입/로그인

- **F5.1 (M2)**: 이메일 + 비밀번호.
  - 비밀번호 해싱: `argon2id`.
  - 세션: HTTP-Only 쿠키 + CSRF 토큰.
- **F5.1.1 SSO (M3, 🟢 낮음)**: OIDC 기반. 지원 IdP 목록은 설정에서 관리.

### 1.2 F5.2 사용자/권한 콘솔

#### F5.2.1 역할 기반 권한 정책

기본 역할 3개:

| 역할 | 조회 | 업로드 | 다운로드 | 삭제 | 학습 |
|---|---|---|---|---|---|
| Admin | ✅ | ✅ | ✅ | ✅ | ✅ |
| Editor | ✅ | ✅ | ✅ | ❌ | ❌ |
| Viewer | ✅ | ❌ | ✅ | ❌ | ❌ |

- 역할별 권한은 DB(`role_permissions`)에서 변경 가능 → 관리자가 콘솔에서 토글.
- 권한 검사는 백엔드 미들웨어 + 프론트 가드 양쪽.

## 2. F10 — 데이터 보안 + 감사 로그

### 2.1 데이터 접근 통제

- 역할별 데이터 조회/다운로드/삭제 권한 분리 (위 표).
- 노션 토큰 등 민감 데이터는 별도 테이블 `secrets` (envelope encryption).
- 다운로드 파일에는 워터마크(요청자 ID + 타임스탬프) 옵션.

### 2.2 F10.1 감사 로그

#### 기록 이벤트

| 이벤트 | source |
|---|---|
| login / logout / login_failed | F5 |
| upload / delete (데이터셋) | F4, F1 |
| predict_run | F2 |
| model_retrain / model_activate / model_rollback | F8 |
| permission_change / user_create / user_delete | F5 |
| master_change | F9 |

#### 스키마 (`harness/sql/audit_log_schema.sql`)

| 컬럼 | 설명 |
|---|---|
| event_id | PK |
| occurred_at | timestamptz |
| user_id | nullable (시스템 이벤트) |
| event_type | 위 enum |
| target_id | 영향받은 객체 (project_id, dataset_id, ...) |
| metadata | JSON |
| request_ip | |

#### F10.1.1 필터/검색

UI: 기간 + 사용자 + 이벤트 유형 + 키워드(메타데이터).
무한 스크롤 또는 페이지네이션. 30일 이전은 cold storage 분리 (선택).

## 3. 작업 항목

- [ ] `harness/sql/users_schema.sql`, `role_permissions_schema.sql`, `audit_log_schema.sql`
- [ ] `src/auth/` — 회원가입/로그인/세션
- [ ] `src/middleware/audit.py` — 모든 변경 요청에서 감사 로그 기록
- [ ] `src/web/admin/users/` — 사용자/역할 콘솔
- [ ] `src/web/admin/audit/` — 감사 로그 조회 화면

## 4. 가정·결정 사항

- M1 까지는 단일 Admin 사용자로 진행 (인증 없이 로컬 사용).
- 감사 로그는 처음부터 기록 (M0부터 stub 형태로 시작), 조회 UI 만 M2.
- 토큰/키 보관은 운영 환경에서 vault 사용 가정 (개발 환경은 `.env`).
