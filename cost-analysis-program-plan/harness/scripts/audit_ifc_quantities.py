"""IFC quantity-coverage audit.

For each Revit-exported IFC, count how many elements per type carry the
`IfcElementQuantity` values our cost engine needs (Length / Area / Volume /
Weight). Coverage gaps map directly to which Revit IFC export option must be
turned on (typically `Export base quantities`).

Usage:
    # one file
    python harness/scripts/audit_ifc_quantities.py path\\to\\file.ifc

    # all IFCs in unitlab-cost-analysis/ifc
    python harness/scripts/audit_ifc_quantities.py --all

    # JSON output
    python harness/scripts/audit_ifc_quantities.py --all --json

The non-JSON output is a per-type table per file plus a one-line verdict.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_IFC_DIR = REPO_ROOT / "unitlab-cost-analysis" / "ifc"


# Element types our cost engine actually maps + which quantity slots we want.
# Matches IFC_WORK_MAP in parse_ifc_all.py.
TARGET_TYPES: dict[str, dict] = {
    "IfcWall":              {"want": ["Area", "Volume"],          "for": "FIN-PANEL m²"},
    "IfcWallStandardCase":  {"want": ["Area"],                    "for": "FIN-LGS m²"},
    "IfcCovering":          {"want": ["Area"],                    "for": "FIN-INS m²"},
    "IfcSlab":              {"want": ["Area", "Volume"],          "for": "FIN-PANEL / STR-ST m² · m³"},
    "IfcBeam":              {"want": ["Length", "Volume"],        "for": "STR-ST m / m³ → ton"},
    "IfcColumn":            {"want": ["Length", "Volume"],        "for": "STR-ST m / m³ → ton"},
    "IfcMember":            {"want": ["Length", "Volume"],        "for": "STR-ST"},
    "IfcPlate":             {"want": ["Area", "Volume"],          "for": "STR-ST m³ → ton"},
    "IfcWindow":            {"want": ["Area"],                    "for": "EXT-WIN (count + size)"},
    "IfcDoor":              {"want": ["Area"],                    "for": "FUR-DOOR (count + size)"},
    "IfcCurtainWall":       {"want": ["Area"],                    "for": "EXT-CLAD m²"},
    "IfcFooting":           {"want": ["Volume"],                  "for": "STR-FND m³"},
    "IfcStair":             {"want": ["Area"],                    "for": "FIN-CARP m²"},
    "IfcPipeSegment":       {"want": ["Length"],                  "for": "MEP-PLMB m"},
    "IfcDuctSegment":       {"want": ["Length"],                  "for": "MEP-HVAC m"},
    "IfcFlowTerminal":      {"want": [],                          "for": "MEP-ELEC (count OK)"},
    "IfcFurnishingElement": {"want": [],                          "for": "FUR (count OK)"},
    "IfcRailing":           {"want": ["Length"],                  "for": "STR-MISC"},
    "IfcPile":              {"want": ["Length", "Volume"],        "for": "STR-FND"},
}


# IfcQuantity* class → bucket name we care about
QUANTITY_FIELDS = {
    "LengthValue": "Length",
    "AreaValue": "Area",
    "VolumeValue": "Volume",
    "WeightValue": "Weight",
    "CountValue": "Count",
}


def audit_file(ifc_path: Path) -> dict:
    try:
        import ifcopenshell
    except ImportError:
        return {"error": "ifcopenshell not installed"}

    try:
        model = ifcopenshell.open(str(ifc_path))
    except Exception as e:
        return {"file": ifc_path.name, "error": f"open failed: {e}"}

    per_type: dict[str, dict] = {}
    for ifc_type, spec in TARGET_TYPES.items():
        try:
            elements = model.by_type(ifc_type)
        except Exception:
            elements = []
        if not elements:
            continue

        present_buckets = defaultdict(int)
        elements_with_any_qto = 0
        for elem in elements:
            buckets_seen: set[str] = set()
            for rel in getattr(elem, "IsDefinedBy", []) or []:
                try:
                    if not rel.is_a("IfcRelDefinesByProperties"):
                        continue
                    pdef = rel.RelatingPropertyDefinition
                    if not pdef.is_a("IfcElementQuantity"):
                        continue
                    for q in pdef.Quantities or []:
                        for field, bucket in QUANTITY_FIELDS.items():
                            v = getattr(q, field, None)
                            if v is not None and float(v) > 0:
                                buckets_seen.add(bucket)
                except Exception:
                    pass
            if buckets_seen:
                elements_with_any_qto += 1
                for b in buckets_seen:
                    present_buckets[b] += 1

        n = len(elements)
        want = spec["want"]
        coverage = {b: round(present_buckets.get(b, 0) / n * 100, 1) for b in ("Length", "Area", "Volume", "Weight")}
        missing = [b for b in want if coverage[b] < 50.0]
        per_type[ifc_type] = {
            "elements": n,
            "elements_with_any_qto": elements_with_any_qto,
            "coverage_pct": coverage,
            "wanted_by_engine": want,
            "missing_critical": missing,
            "engine_use": spec["for"],
        }

    # Verdict
    total_elements = sum(t["elements"] for t in per_type.values())
    well_covered = sum(t["elements"] for t in per_type.values() if not t["missing_critical"])
    overall_pct = round(well_covered / total_elements * 100, 1) if total_elements else 0.0

    if overall_pct >= 90:
        verdict = "OK"
    elif overall_pct >= 50:
        verdict = "PARTIAL"
    else:
        verdict = "MISSING_BASE_QUANTITIES"

    return {
        "file": ifc_path.name,
        "size_kb": round(ifc_path.stat().st_size / 1024),
        "schema": getattr(model, "schema", "?"),
        "total_target_elements": total_elements,
        "well_covered_elements": well_covered,
        "well_covered_pct": overall_pct,
        "verdict": verdict,
        "per_type": per_type,
    }


def print_human(report: dict) -> None:
    print()
    print(f"━━ {report['file']} ━━ ({report.get('schema', '?')}, {report.get('size_kb', 0)} KB)")
    if report.get("error"):
        print(f"  ERROR: {report['error']}")
        return

    print(f"  Verdict: {report['verdict']} ({report['well_covered_pct']}% well-covered, "
          f"{report['well_covered_elements']}/{report['total_target_elements']} elements)")
    print(f"  {'IFC type':22} {'#elem':>6} {'L%':>5} {'A%':>5} {'V%':>5} {'W%':>5}  missing → engine 용도")
    print(f"  {'-'*22} {'-'*6} {'-'*5} {'-'*5} {'-'*5} {'-'*5}  {'-'*45}")
    for ifc_type, t in sorted(report["per_type"].items(), key=lambda x: -x[1]["elements"]):
        c = t["coverage_pct"]
        miss = ",".join(t["missing_critical"]) if t["missing_critical"] else "-"
        flag = " " if not t["missing_critical"] else "*"
        print(
            f"{flag} {ifc_type:22} {t['elements']:>6}"
            f" {c['Length']:>5.0f} {c['Area']:>5.0f} {c['Volume']:>5.0f} {c['Weight']:>5.0f}"
            f"  {miss:6} → {t['engine_use']}"
        )

    if report["verdict"] == "MISSING_BASE_QUANTITIES":
        print()
        print("  → Revit IFC export 시 'Export base quantities' 옵션을 켜야 합니다.")
        print("    (File → Export → IFC → Modify setup → Property Sets 탭)")


def aggregate_summary(reports: list[dict]) -> None:
    if not reports:
        return
    print()
    print("=" * 78)
    print("종합 요약")
    print("=" * 78)
    print(f"{'파일':40} {'verdict':24} {'커버리지':>10}")
    print("-" * 78)
    for r in reports:
        if r.get("error"):
            print(f"{r['file'][:40]:40} ERROR")
            continue
        print(f"{r['file'][:40]:40} {r['verdict']:24} {r['well_covered_pct']:>9.1f}%")
    bad = [r for r in reports if r.get("verdict") == "MISSING_BASE_QUANTITIES"]
    if bad:
        print()
        print(f"⚠ {len(bad)}개 파일이 base quantity 누락 — Revit export 옵션 설정 필요.")


def main() -> None:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="IFC base-quantity coverage audit")
    parser.add_argument("paths", nargs="*", help="IFC file paths")
    parser.add_argument("--all", action="store_true", help=f"audit every .ifc in {DEFAULT_IFC_DIR}")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of tables")
    args = parser.parse_args()

    files: list[Path] = []
    if args.all:
        files.extend(sorted(DEFAULT_IFC_DIR.glob("*.ifc")))
    files.extend(Path(p) for p in args.paths)

    if not files:
        parser.error("provide IFC paths or --all")

    reports = [audit_file(f) for f in files]

    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
        return

    for rep in reports:
        print_human(rep)
    aggregate_summary(reports)


if __name__ == "__main__":
    main()
