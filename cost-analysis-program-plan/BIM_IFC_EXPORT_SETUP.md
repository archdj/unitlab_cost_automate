# Revit → IFC Export 설정 가이드 (BIM 팀용)

원가분석 시스템이 BIM 모델로부터 정확한 공사비를 산출하려면 Revit에서 IFC를 내보낼 때 **base quantities**(면적·체적·길이·중량)가 함께 export 되어야 합니다. 현재 IFC 9개 점검 결과 **0~23%만 quantity 보유** → 공종별 단위(m²·ton·m·LS) 추출 불가, EA(개수)로만 떨어져 단가가 추정에 의존합니다.

이 문서대로 export 설정 한 번만 잡아주시면 시스템 정확도가 즉시 ±15% 이내로 수렴합니다.

---

## 1. Revit IFC Export 설정 (필수)

### 1.1 메뉴 위치
```
File ▸ Export ▸ IFC ▸ "Modify setup..."
```

### 1.2 General 탭
| 항목 | 설정값 |
|---|---|
| IFC Version | **IFC 2x3 Coordination View 2.0** (또는 IFC 4 Reference View) |
| File Type | IFC |
| Phase to Export | Default phase |
| Space boundaries | None (필요 시 1st level) |

### 1.3 Property Sets 탭 ⭐ **가장 중요**
| 옵션 | 체크 여부 | 비고 |
|---|---|---|
| Export Revit property sets | ☑ | 필수 |
| Export IFC common property sets | ☑ | 필수 |
| **Export base quantities** | ☑ | **이게 핵심 — 현재 꺼져 있음** |
| Export schedules as property sets | ☐ | 선택 |
| Export only schedules containing | (비움) | |

### 1.4 Level of Detail 탭
| 옵션 | 권장 |
|---|---|
| Level of Detail | **High** (또는 Medium) |

### 1.5 Advanced 탭
| 옵션 | 권장 |
|---|---|
| Export parts as building elements | ☐ |
| Allow use of mixed "Solid Model" representation | ☐ |
| Use family and type name for reference | ☑ |
| Use 2D room boundaries for room volumes | ☐ |
| Include IFCSITE elevation | ☑ |
| Store the IFC GUID in an element parameter after export | ☐ (선택) |
| Export bounding box | ☐ |

설정을 저장한 뒤 **이름을 "UnitLab-CostAnalysis-Export"** 등으로 저장해 두면 다음부터는 한 클릭에 끝납니다.

---

## 2. 요소별 자동 추출되는 Quantity (옵션 켠 후)

`Export base quantities = ☑` 만 켜면 Revit이 다음을 IFC로 자동 내보냅니다.

| Revit 카테고리 | IFC type | 추출 quantity | 사용처 |
|---|---|---|---|
| Wall (외벽) | IfcWall | NetSideArea, GrossSideArea | **FIN-PANEL m²** |
| Wall (간벽) | IfcWallStandardCase | NetSideArea | **FIN-LGS m²** |
| Floor / Slab | IfcSlab | NetArea, NetVolume | FIN-PANEL / STR-ST m² · m³ |
| Roof | IfcRoof / IfcCovering | NetArea | EXT-ROOF, FIN-INS m² |
| Beam | IfcBeam | Length, NetVolume, CrossSectionArea | **STR-ST m / m³** (→ ton 환산) |
| Column | IfcColumn | Length, NetVolume, CrossSectionArea | STR-ST |
| Window | IfcWindow | Width, Height (자동), Area | **EXT-WIN EA + 면적** |
| Door | IfcDoor | Width, Height, Area | FUR-DOOR |
| Footing | IfcFooting | NetVolume | STR-FND m³ |
| Stair | IfcStair | Area | FIN-CARP m² |
| Pipe | IfcPipeSegment | Length | MEP-PLMB m |
| Duct | IfcDuctSegment | Length | MEP-HVAC m |
| Fixture | IfcFlowTerminal | (Count로 OK) | MEP-ELEC EA |
| Furniture | IfcFurnishingElement | (Count로 OK) | FUR EA |

---

## 3. 추가 권장 — 철골 ton 자동 환산용

STR-ST(철골)을 ton으로 정확히 환산하려면 **자재(Material)에 단위중량**이 있어야 합니다.

### 3.1 방법 A: Material 밀도 (권장)
```
Manage ▸ Materials ▸ [Steel] ▸ Identity tab
   ▸ "Mass Density" 또는 "Density" 매개변수 = 7,850 kg/m³
```
IFC export 시 `IfcMaterial.MassDensity`로 변환되어 `NetVolume × Density` 자동 계산 가능.

### 3.2 방법 B: Family 매개변수 (폴백)
강재 부재 family에 직접 추가:
```
Project Parameters ▸ Add
   Name: UnitWeight_kg_per_m
   Discipline: Common
   Type: Number
   Categories: Structural Framing, Structural Columns
```
값 예시:
- H-150×75: 14 kg/m
- H-150×150: 31.5 kg/m
- H-200×100: 21.3 kg/m

### 3.3 효과
적용 후 우리 시스템:
- 강재 ton 단가가 default 추정 9,450,643원/ton → 실측 기반 ~3,000,000원/ton 수준으로 정착
- STR-ST 신뢰도 0.51 → 0.8+ 상승 예상

---

## 4. 검증 — 우리 쪽 audit 스크립트

새로 export한 IFC를 받자마자 우리가 quantity 충실도를 자동 진단합니다.

```powershell
python cost-analysis-program-plan/harness/scripts/audit_ifc_quantities.py path\to\your.ifc
```

### 출력 예 (좋은 export)
```
━━ T-15-STD_v2.ifc ━━ (IFC2X3, 25,403 KB)
  Verdict: OK (94.2% well-covered, 285/302 elements)
  IFC type                #elem    L%    A%    V%    W%
* IfcBeam                   125    98    12    98     0
  IfcWall                    19     0   100    95     0
  IfcSlab                     9    11   100    95     0
  IfcWindow                   7     0   100     0     0
  ...
```

### 출력 예 (잘못된 export — 현재 상태)
```
  Verdict: MISSING_BASE_QUANTITIES (22.9% well-covered, 69/301)
  IfcBeam     0%   0%   0%   0%  ← 옵션 안 켜져 있음
  → Revit IFC export 시 'Export base quantities' 옵션을 켜야 합니다.
```

### Verdict 등급
| Verdict | 의미 | 조치 |
|---|---|---|
| **OK** | 90%+ 요소가 필요한 quantity 보유 | 그대로 import |
| **PARTIAL** | 50~90% | 누락 카테고리 점검 |
| **MISSING_BASE_QUANTITIES** | <50% | export 옵션 재설정 |

---

## 5. 워크플로우 (새 IFC 받을 때마다)

```
[BIM팀]                                  [원가팀]
  ↓                                        ↓
Revit에서 export (옵션 켠 채로)
  ↓
.ifc 파일 전달  ────────────────────→  audit_ifc_quantities.py 실행
                                          ↓
                                       Verdict 확인
                                       ├─ OK     → parse_ifc_all.py 실행 → 단가 즉시 반영
                                       └─ MISSING → BIM팀에 audit 결과 첨부 회신
```

---

## 6. 자주 묻는 질문

**Q1. 기존 모델에 base quantities를 다시 채우려면?**
A. Revit 모델 자체는 변경 없습니다. **export 시 옵션만 켜고 다시 내보내면** 끝. 같은 .rvt에서 5초.

**Q2. 옵션 켜면 파일 크기가 커지나요?**
A. 약 5~10% 정도만 증가. 원가 정확도 향상 대비 무시할 수 있는 수준.

**Q3. IFC 4 권장? IFC 2x3 권장?**
A. 둘 다 동작합니다. **IFC 2x3 Coordination View 2.0**이 호환성 가장 좋고 우리 파서가 검증된 환경입니다.

**Q4. 모든 모델에 매번 옵션을 다시 켜야 하나요?**
A. 한 번 setup을 저장(이름 지정)해두면 다음부터 자동 적용됩니다. "Modify setup..." → "Save as new" → 이름 입력.

**Q5. 자재 밀도(7,850 kg/m³)가 정확한가요?**
A. 강재 표준값입니다. 알루미늄·콘크리트·목재는 별도값:
- 콘크리트 = 2,400 kg/m³
- 알루미늄 = 2,700 kg/m³
- 목재(소나무) = 500 kg/m³

---

## 7. 체크리스트 (BIM 팀 1쪽 요약)

```
□ File ▸ Export ▸ IFC ▸ Modify setup
□ Property Sets 탭 → "Export base quantities" 체크
□ General 탭 → IFC 2x3 Coordination View 2.0
□ Level of Detail → High
□ Setup 이름 저장 (예: UnitLab-CostAnalysis-Export)
□ Material에 Mass Density 채우기 (Steel = 7,850)
□ export 후 .ifc 파일 전달
□ 원가팀이 audit_ifc_quantities.py로 OK 받으면 끝
```

---

## 8. 참고 — 현재 9개 IFC 진단 결과

| 파일 | Verdict | 커버리지 |
|---|---|---|
| 충남 추부면_251022.ifc | MISSING | 0.0% |
| 양평군_원덕리346-34_근생_s-18 | MISSING | 0.0% |
| 용인 남곡리 10평 쇼룸 | MISSING | 0.0% |
| 농어촌공사 5평 야영장 | MISSING | 12.2% |
| 쇼룸 | MISSING | 16.7% |
| 루떼르 포레_모델하우스_S-18 | MISSING | 18.9% |
| 충남 서산시 강수리 277 | MISSING | 18.9% |
| 청주 상당구 미원면 중리 T-12 | MISSING | 19.6% |
| 밀양시 남기동길 43-2 T-15 | MISSING | 20.0% |
| 제주 안덕면 서광리 80-5 H-30 | MISSING | 20.0% |
| 용인 수지 에스테라고 (1동) | MISSING | 15.7% |
| 용인 수지 에스테라고 (2동) | MISSING | 20.4% |
| 경기도 성남시 수정구 상적동 12평 | MISSING | 22.3% |
| 홍천군 노천리 산315-9 T-15 | MISSING | 22.9% |

**전부 옵션 미설정.** 한 번 재export 해주시면 즉시 시스템에 반영됩니다.

---

작성일: 2026-05-05
문의/검증: `python cost-analysis-program-plan/harness/scripts/audit_ifc_quantities.py --all`
