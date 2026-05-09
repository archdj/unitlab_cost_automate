from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# 운영 DB 위치 (read-only). AUTOCOST_DB env로 override 가능.
# REPO_ROOT = autocost-spec-2026-05-07/  →  REPO_ROOT.parent.parent = C:/Users/PC/
DEFAULT_DB = REPO_ROOT.parent.parent / "unitlab-cost-analysis" / "db" / "cost_analysis.db"
OPERATIONAL_DB = Path(os.environ.get("AUTOCOST_DB", DEFAULT_DB))

MODEL_VERSION = "v11.0-autocost-mvp"

# 모델 hyperparameter (v10-notion 패턴 승계)
MIN_TIER_SAMPLES = 2
TARGET_SAMPLE_FOR_FULL_CONFIDENCE = 8

# 학습 입력 필터 (notion_actual_costs.md §4)
LEARNABLE_PROMOTION_STATUS = ("approved", "promoted", "validated")

# 리포트 출력 위치
HARNESS_REPORTS = REPO_ROOT / "harness" / "reports"
MODEL_REPORTS = REPO_ROOT / "reports"
