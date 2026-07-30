# -*- coding: utf-8 -*-
"""Orange Connex 請求書 (xlsx) から **実効関税率** を算出する。

なぜ必要か (2026-07-31):
    SpeedPAK の関税は「事前設定レート」で請求され、**その率はどの資料にも書かれていない**。
    料金表 (RATE_GUIDE_SpeedPAK_Economy_JP_20260730.pdf L430-437) に明記:

      「貨物の申告価値及び平均関税率に基づき、特定割合(事前設定レート)で算出される。
        適用される事前設定レートは随時変更される場合があり、実際の課金時点の
        事前設定レートが優先される。**最終的な決済は請求金額に基づく**」

    = **請求書が唯一の一次情報**。HTS を引いても実際の請求額は分からない。
    実測 (2026-05 の2件) では HSコードが違っても両方 9.95〜9.98% で、
    Orange Connex は真の HTS を見ずに一律レートを当てていた。

    さらに米国側の制度が短期間で動いている:
      2025-09 日本に相互関税15%(IEEPA) → 2026-02-20 最高裁が無効化
      → 一律10%(Section 122) → **2026-07-24 失効**
    → **請求書を継続的に取り込んで実効率を追う**しかない。

使い方:
    python invoice_duty_rate.py <請求書.xlsx> [<請求書2.xlsx> ...]
    python invoice_duty_rate.py --dir C:/dev/iMak_data/shipping/invoices

出力: 明細ごとの実効率 + 仕向地/期間ごとの集計。
      `iMak_data/shipping/duty_rate_history.jsonl` に追記して推移を残す。
"""
from __future__ import annotations

import glob
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

HIST = Path(r"C:\dev\iMak_data\shipping\duty_rate_history.jsonl")

# 請求書 (新版) のシート名と列見出し。書式が変わったらここだけ直す。
SH_ORDER, SH_SKU, SH_FEE = "オーダー", "SKUの詳細", "料金詳細（新版）"


def _num(v):
    try:
        return float(str(v).replace(",", "").replace("¥", "").strip())
    except (TypeError, ValueError):
        return 0.0


def parse(path: str, fx_usd: float = 159.65) -> list[dict]:
    """請求書1ファイル → 明細 list。fx は申告通貨→円の換算に使う。"""
    import warnings
    warnings.filterwarnings("ignore")
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    if SH_SKU not in wb.sheetnames or SH_FEE not in wb.sheetnames:
        raise ValueError(f"想定のシートが無い ({wb.sheetnames}) — 請求書の書式変更を疑うこと")

    sku = {}
    for r in wb[SH_SKU].iter_rows(min_row=2, values_only=True):
        if r and r[0]:
            sku[str(r[0])] = {"dest": r[3], "price": _num(r[4]), "cur": r[5],
                              "title": str(r[7] or "")[:60], "origin": r[9], "hs": str(r[11] or "")}
    order = {}
    for r in wb[SH_ORDER].iter_rows(min_row=2, values_only=True):
        if r and r[1]:
            order[str(r[1])] = {"date": str(r[0])[:10], "service": r[8], "incoterm": r[11]}

    out = []
    for r in wb[SH_FEE].iter_rows(min_row=3, values_only=True):
        tid = str(r[0]) if r and r[0] else ""
        if not tid.startswith("EE") or r[1] != "引落金額":
            continue
        s = sku.get(tid)
        if not s or not s["price"]:
            continue
        yen = s["price"] * (fx_usd if s["cur"] == "USD" else 1.0)
        duty, cust, proc = _num(r[7]), _num(r[8]), _num(r[9])
        ship, fuel = _num(r[5]), _num(r[6])
        out.append({
            "tid": tid, "file": os.path.basename(path),
            "date": order.get(tid, {}).get("date", ""),
            "dest": s["dest"], "hs": s["hs"], "origin": s["origin"], "title": s["title"],
            "declared": s["price"], "cur": s["cur"], "declared_jpy": round(yen),
            "duty": duty, "duty_rate": round(duty / yen, 4) if yen else 0,
            "clearance": cust, "proc_fee": proc,
            "proc_rate": round(proc / duty, 4) if duty else 0,
            "ship": ship, "fuel": fuel,
            "fuel_rate": round(fuel / ship, 4) if ship else 0,
            "incoterm": order.get(tid, {}).get("incoterm", ""),
        })
    return out


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "--dir" in sys.argv:
        i = sys.argv.index("--dir")
        args = sorted(glob.glob(os.path.join(sys.argv[i + 1], "*.xlsx")))
    if not args:
        print(__doc__)
        return 1

    rows = []
    for p in args:
        try:
            rows += parse(p)
        except Exception as e:                                  # noqa: BLE001
            print(f"⚠️ {os.path.basename(p)}: {e}")
    if not rows:
        print("明細0件 — 請求書の書式が変わった可能性")
        return 1

    print(f"{'日付':<11}{'仕向':<5}{'HS':<12}{'申告':>10}{'関税¥':>8}{'実効率':>8}{'処理':>7}{'燃油':>7}")
    for r in sorted(rows, key=lambda x: x["date"]):
        print(f"{r['date']:<11}{str(r['dest']):<5}{r['hs']:<12}"
              f"{r['declared']:>9,.2f}{r['duty']:>8,.0f}{r['duty_rate']*100:>7.2f}%"
              f"{r['proc_rate']*100:>6.2f}%{r['fuel_rate']*100:>6.1f}%")
        print(f"           {r['title'][:64]}")

    print("\n=== 仕向地 × 月 の実効関税率 ===")
    agg = defaultdict(list)
    for r in rows:
        agg[(r["dest"], r["date"][:7])].append(r["duty_rate"])
    for (dest, mon), v in sorted(agg.items()):
        lo, hi = min(v), max(v)
        flag = "" if hi - lo < 0.01 else "  ★ばらつきあり(HTS別レートの可能性)"
        print(f"  {dest} {mon}: n={len(v)} 平均 {sum(v)/len(v)*100:5.2f}% "
              f"(min {lo*100:.2f}% / max {hi*100:.2f}%){flag}")

    HIST.parent.mkdir(parents=True, exist_ok=True)
    known = set()
    if HIST.exists():
        for ln in HIST.read_text(encoding="utf-8").splitlines():
            try:
                known.add(json.loads(ln)["tid"])
            except (ValueError, KeyError):
                pass
    new = [r for r in rows if r["tid"] not in known]
    with HIST.open("a", encoding="utf-8") as fh:
        for r in new:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n履歴に追記: {len(new)}件 (既知 {len(rows)-len(new)}件はスキップ) → {HIST}")
    print("※ レートは Orange Connex の『事前設定レート』で、料金表には記載されない。"
          "請求書が唯一の一次情報 (RATE_GUIDE L430-437)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
