"""G-shock pre-flight: 出品ユニバースの型番リストを一括 catalog 照合し miss を先出しする。

目的: 「出品時に catalog 無し → 依頼 → 再走」の reactive サイクルを、出品前の
バッチ照合で潰す。型番リストを与えると以下に分類してレポートする:

  - HIT        : lookup_gshock が canonical に解決 (= 出品 OK、何もしない)
  - MISSING    : catalog に痕跡なし (= 真の未収録、backfill 対象)
  - AMBIGUOUS  : catalog に suffix 違いの canonical は在るが入力が bare で 1:N 曖昧
                 (= catalog 追加では直らない。フル型番を取り直す対象)

MISSING だけを一括 backfill すれば、reactive 依頼がほぼ消える。
AMBIGUOUS は入力側 (Amazon/画像/タグ) で suffix を確定させる必要がある。

使い方:
    python iMakCatalog/integrations/gshock_preflight.py models.txt            # 1行1型番
    python iMakCatalog/integrations/gshock_preflight.py models.txt --json out.json
    echo "GA-2100-1A1JF" | python iMakCatalog/integrations/gshock_preflight.py -
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

from gshock_lookup import (  # noqa: E402
    lookup_gshock, _normalize_forms, _split_region, _has_region_twin,
)

HIT, MISSING, AMBIGUOUS = "HIT", "MISSING", "AMBIGUOUS"


def classify(model: str) -> dict:
    """型番1件を HIT / MISSING / AMBIGUOUS に分類."""
    rec = lookup_gshock(model)
    if rec:
        return {"input": model, "status": HIT, "canonical": rec["product_id"]}
    # None: 曖昧(1:N) か 真の未収録 か
    forms = _normalize_forms(model)
    base = _split_region(forms[0])[0] if forms else model.strip().upper()
    if _has_region_twin(base):
        # catalog に suffix 付き canonical が在る = 入力 bare が曖昧
        return {"input": model, "status": AMBIGUOUS, "canonical": None,
                "note": "catalog に suffix 違い canonical 在り。フル型番(JF/JR 等)を取り直す"}
    return {"input": model, "status": MISSING, "canonical": None,
            "note": "catalog に痕跡なし。backfill 対象"}


def run(models: list[str]) -> dict:
    seen = set()
    results = []
    for m in models:
        m = (m or "").strip()
        if not m or m in seen:
            continue
        seen.add(m)
        results.append(classify(m))
    buckets = {HIT: [], MISSING: [], AMBIGUOUS: []}
    for r in results:
        buckets[r["status"]].append(r)
    return {
        "total": len(results),
        "hit": len(buckets[HIT]),
        "missing": len(buckets[MISSING]),
        "ambiguous": len(buckets[AMBIGUOUS]),
        "missing_list": [r["input"] for r in buckets[MISSING]],
        "ambiguous_list": [r["input"] for r in buckets[AMBIGUOUS]],
        "results": results,
    }


def _read_models(arg: str) -> list[str]:
    if arg == "-":
        return sys.stdin.read().splitlines()
    return Path(arg).read_text(encoding="utf-8").splitlines()


if __name__ == "__main__":
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        sys.exit(1)
    src = argv[0]
    models = _read_models(src)
    report = run(models)
    print(f"total={report['total']}  HIT={report['hit']}  "
          f"MISSING={report['missing']}  AMBIGUOUS={report['ambiguous']}")
    if report["missing_list"]:
        print("\n--- MISSING (backfill 対象) ---")
        for m in report["missing_list"]:
            print(f"  {m}")
    if report["ambiguous_list"]:
        print("\n--- AMBIGUOUS (フル型番取り直し) ---")
        for m in report["ambiguous_list"]:
            print(f"  {m}")
    if "--json" in argv:
        out = argv[argv.index("--json") + 1]
        json.dump(report, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n[json] {out}")
