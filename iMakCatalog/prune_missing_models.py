"""missing_models の prune — resolver.resolve() で解決可能な行を除去.

背景: missing_models は解決済 item を pruning せず、毎日の auto-add/pdca/psa_mismatch を
stale 再発行させていた(2026-06-16 報告 / 2026-06-21 HQ Q1 GO: (b) Catalog が即prune)。
さらに pdca.db(improvement_queue, source='missing_models')の done が CSV 再import で
pending に戻る機序(done→pending 復活)があり、「CSV除去」と「pdca.db done化」は**セット**で
行わないと毎日復活する(2026-06-21 HQ 実機診断)。Advisor GO=(b) Catalog 自走日次実行。

本スクリプトは2面を同時に prune(セット):
  1. missing_models.csv  : resolver 解決済 行を物理除去
  2. pdca.db improvement_queue (source='missing_models', status='pending')
     : resolver 解決済 を status='done' 化(= CSV 再import でも復活しない)

2026-07-31 追加 (Advisor GO pdca_catalog_queue_tcg_response.md 群B):
  対象外(out-of-scope)確定 cert の永久除外機構を追加.
  `_OUT_OF_SCOPE_CERTS` に列挙された cert 番号 は resolver をバイパスして常に prune 対象.
  対象外 = 参入しないゲーム/期(SDBH, Neo era 等)、または一次情報 (公式 product_id 体系) が
  存在しない一点物 promo (Championship Set 2023 等)。再依頼が起きない形にする恒久措置。

恒久策の日次実行は本スクリプトを scheduler(schtasks 等)で回す。

使い方:
  python prune_missing_models.py --dry-run   # 除去候補のみ表示(書込なし)
  python prune_missing_models.py             # backup 取得後に実行(CSV+pdca 両方)
  python prune_missing_models.py --csv-only  # CSV のみ(pdca.db は触らない)
"""
from __future__ import annotations
import argparse, csv, re, sys, shutil, sqlite3
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import resolver  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CSV_PATH = Path("C:/dev/iMak_data/catalog/missing_models.csv")
PDCA_DB = Path("C:/dev/iMak_data/audit/pdca.db")

# ---------------------------------------------------------------------------
# 対象外 (out-of-scope) 永久除外 cert リスト
# ---------------------------------------------------------------------------
# 追加基準 (どれか):
#   1. 対象外ゲーム/期に属する (SDBH / Neo era 等) = Advisor 確定
#   2. 公式 product_id 体系が公開されていない一点物 promo = 推測 catalog_add 不可
# 追加時は必ず該当 response.md を「why」として付記する。
_OUT_OF_SCOPE_CERTS: dict[str, str] = {
    # 2026-07-31 pdca_catalog_queue_tcg_response.md 群B B-8:
    #   PORTGAS D. ACE CHAMPIONSHIP SET 2023 — 大会入賞者配布 promo、公式 product_id 体系公開無
    "cert153574704": "out_of_scope: OP championship 2023 promo (公式 product_id 無)",
    "cert153574705": "out_of_scope: OP championship 2023 promo (公式 product_id 無)",
    # 2026-07-31 pdca_catalog_queue_tcg_response.md 群B B-7:
    #   POKEMON Neo era (2000-2001) = 無在庫運営と相性が悪く参入せず
    "cert157799487": "out_of_scope: POKEMON Neo era (vintage, 参入せず)",
}


def _extract_cert(model: str) -> str | None:
    """model 文字列先頭の 'certNNN...' を抜く. 無ければ None."""
    m = re.match(r"(cert\d+)\b", model or "")
    return m.group(1) if m else None


def is_out_of_scope(model: str) -> str | None:
    """model が out-of-scope なら理由 str を返す (denylist hit). なければ None."""
    cert = _extract_cert(model)
    if cert and cert in _OUT_OF_SCOPE_CERTS:
        return _OUT_OF_SCOPE_CERTS[cert]
    return None


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


def prune_csv(dry_run: bool) -> int:
    """missing_models.csv の解決済行 + out-of-scope 確定行を物理除去. Returns pruned 件数."""
    if not CSV_PATH.exists():
        print(f"[csv] {CSV_PATH} が無い → skip")
        return 0
    with CSV_PATH.open(encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        fields = rdr.fieldnames
        rows = list(rdr)

    keep, pruned = [], []
    for r in rows:
        oos = is_out_of_scope(r["model"])
        if oos:
            pruned.append((r, oos))
            continue
        key = resolves(r["category"], r["model"])
        (pruned if key else keep).append((r, key))

    print(f"[csv] total={len(rows)}  prune(解決済+対象外)={len(pruned)}  keep(未解決)={len(keep)}")
    for r, key in pruned:
        tag = key if key else "resolved"
        print(f"  PRUNE [{r['category']}] {tag[:32]:32s} <- {r['model'][:70]}")
    for r, key in keep:
        print(f"  KEEP  [{r['category']}] {r['model'][:80]}")
    if dry_run or not pruned:
        return len(pruned)
    backup = CSV_PATH.with_suffix(".csv.bak_prune")
    shutil.copy2(CSV_PATH, backup)
    with CSV_PATH.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r, _ in keep:
            w.writerow(r)
    print(f"  ✅ csv pruned {len(pruned)} 行。backup={backup.name}  残={len(keep)}")
    return len(pruned)


def prune_pdca(dry_run: bool) -> int:
    """pdca.db improvement_queue の pending missing_models で resolver 解決済を done 化.

    done→pending 復活機序(CSV 再import)を断つため CSV prune と必ずセットで行う.
    Returns done 化件数.
    """
    if not PDCA_DB.exists():
        print(f"[pdca] {PDCA_DB} が無い → skip")
        return 0
    con = sqlite3.connect(str(PDCA_DB))
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    rows = cur.execute(
        "SELECT queue_id, category, item_id FROM improvement_queue "
        "WHERE source='missing_models' AND status='pending'"
    ).fetchall()
    resolved, keep = [], []
    for r in rows:
        oos = is_out_of_scope(r["item_id"])
        if oos:
            resolved.append((r, oos))
            continue
        key = resolves(r["category"], r["item_id"])
        (resolved if key else keep).append((r, key))
    print(f"[pdca] pending missing_models={len(rows)}  done化(解決済+対象外)={len(resolved)}  keep(未解決)={len(keep)}")
    for r, key in resolved:
        tag = key if key else "resolved"
        print(f"  DONE  [{r['category']}] {tag[:32]:32s} <- {r['item_id'][:70]}")
    for r, key in keep:
        print(f"  KEEP  [{r['category']}] {r['item_id'][:80]}")
    if dry_run or not resolved:
        con.close()
        return len(resolved)
    backup = PDCA_DB.with_name(PDCA_DB.name + ".bak_prune_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(PDCA_DB, backup)
    now = datetime.now().strftime("%Y-%m-%d")
    for r, _ in resolved:
        cur.execute(
            "UPDATE improvement_queue SET status='done', updated_ts=?, reviewed_ts=? "
            "WHERE queue_id=?",
            (now, now, r["queue_id"]),
        )
    con.commit()
    con.close()
    print(f"  ✅ pdca done化 {len(resolved)} 件。backup={backup.name}")
    return len(resolved)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--csv-only", action="store_true", help="pdca.db を触らず CSV のみ")
    args = ap.parse_args()

    n_csv = prune_csv(args.dry_run)
    n_pdca = 0 if args.csv_only else prune_pdca(args.dry_run)

    mode = "DRY-RUN(書込なし)" if args.dry_run else "適用済"
    print(f"\n=== {mode}: csv prune={n_csv}  pdca done化={n_pdca} ===")


if __name__ == "__main__":
    main()
