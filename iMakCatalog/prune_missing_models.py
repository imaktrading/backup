"""missing_models.csv の prune — resolver.resolve() で解決可能な行を除去.

背景: missing_models は解決済 item を pruning せず、毎日の auto-add/pdca/psa_mismatch を
stale 再発行させていた(2026-06-16 報告 / 2026-06-21 HQ Q1 GO: (b) Catalog が即prune)。
本スクリプトは「現時点で resolver が canonical product_id を返す行」= 解決済 を除去する暫定手段。
恒久策は出品/取込時の auto-prune(別途)。

使い方:
  python prune_missing_models.py --dry-run   # 除去候補のみ表示(書込なし)
  python prune_missing_models.py             # backup 取得後に実行(解決済を除去)
"""
from __future__ import annotations
import argparse, csv, re, sys, shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import resolver  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CSV_PATH = Path("C:/dev/iMak_data/catalog/missing_models.csv")


def parse_tcg(model: str):
    """PSA model 文字列 → (brand, card_no, subject). gshock 以外用."""
    m = re.match(r"cert(\d+)\s+(.*)", model)
    if m:
        model = m.group(2)
    subject = None
    ms = re.search(r"\[([^\]]+)\]", model)
    if ms:
        subject = ms.group(1)
    model = re.sub(r"\s*\([^)]*\)\s*$", "", model)  # 末尾 (auto候補...) 除去
    cn = None
    brand = model
    mc = re.search(r"#\s*([A-Za-z0-9-]+)\s*$", model)
    if mc:
        cn = mc.group(1); brand = model[:mc.start()].strip()
    else:
        mc = re.search(r"-([A-Za-z]{0,4}\d[\w-]*)\s*$", model)
        if mc:
            cn = mc.group(1); brand = model[:mc.start()].strip()
    brand = re.sub(r"\[[^\]]*\]", "", brand).strip(" -")
    return brand, cn, subject


def resolves(category: str, model: str) -> str:
    if category == "gshock":
        ctx = {"category": "gshock", "signals": {"model": model}}
    else:
        brand, cn, subj = parse_tcg(model)
        ctx = {"category": category, "signals": {"brand": brand, "subject": subj or "", "card_no": cn or ""}}
    try:
        return resolver.resolve(ctx) or ""
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with CSV_PATH.open(encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        fields = rdr.fieldnames
        rows = list(rdr)

    keep, pruned = [], []
    for r in rows:
        key = resolves(r["category"], r["model"])
        (pruned if key else keep).append((r, key))

    print(f"total={len(rows)}  prune(解決済)={len(pruned)}  keep(未解決)={len(keep)}")
    for r, key in pruned:
        print(f"  PRUNE [{r['category']}] {key:16s} <- {r['model'][:70]}")
    print("--- keep (未解決) ---")
    for r, key in keep:
        print(f"  KEEP  [{r['category']}] {r['model'][:80]}")

    if args.dry_run:
        print("\n(dry-run: 書込なし)")
        return
    backup = CSV_PATH.with_suffix(f".csv.bak_prune")
    shutil.copy2(CSV_PATH, backup)
    with CSV_PATH.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r, _ in keep:
            w.writerow(r)
    print(f"\n✅ pruned {len(pruned)} 行除去。backup={backup.name}  残={len(keep)}")


if __name__ == "__main__":
    main()
