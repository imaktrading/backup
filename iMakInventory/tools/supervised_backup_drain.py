"""tools/supervised_backup_drain.py — 補URL売切消込の手動ドレイン (自動が止まる時の fallback)。

自動消込 (cycle Phase1 ⑤) は候補が CLEAR_SURGE_THRESHOLD(20) 超で「消込急増ガード」により HOLD する
(誤一括削除の防止)。backlog 蓄積時や churn が高い時、その genuine な売切補URL を「別で消し込む」ための
正式ツール。dry-run 既定・--execute で実削除。安全機構:
  - compare-and-clear (削除直前に AC-AG を re-read、HQ 差替の生きた補URLは不一致で消さない)
  - 復元アーカイブ (cleared_backups_archive.jsonl に消した url を残す = 誤削除でも復元可)
  - --reverify-snkrdunk で snkrdunk 候補を is_listing_live で削除直前に再確認 (今も本当に売切か)
  - 消込が触るのは補URL(AC-AG)のみ = 主URL/listing/D列は不変

使い方:
  # 1. dry-run で対象確認 (最新 HIGH cycle の genuine 売切補URL 候補を表示)
  python -m tools.supervised_backup_drain
  # 2. supplier 絞り込み / snkrdunk 再確認
  python -m tools.supervised_backup_drain --supplier snkrdunk --reverify-snkrdunk
  # 3. 実削除 (急増ガード override + アーカイブ)
  python -m tools.supervised_backup_drain --execute
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import sheet_updater as su  # noqa: E402

DECISION_LOG_DIR = os.path.join(SCRIPT_DIR, "decision_log")
ARCHIVE = os.path.join(DECISION_LOG_DIR, "cleared_backups_archive.jsonl")


def _dom(u: str) -> str:
    for k in ("mercari", "amazon", "snkrdunk", "fril", "yahoo"):
        if k in (u or ""):
            return k
    return "other"


def _latest_sheet_log(label: str) -> str:
    pat = os.path.join(DECISION_LOG_DIR, f"listings_{label}_*.jsonl")
    logs = sorted(glob.glob(pat), key=os.path.getmtime)
    return logs[-1] if logs else ""


def _collect_candidates(log_path: str, supplier: str | None):
    """decision log から genuine 売切補URL候補 (is_sold=True) を集める。"""
    cands = []
    for ln in open(log_path, encoding="utf-8"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        for s in (d.get("backup_slot_results") or []):
            if s and s.get("is_sold") is True and s.get("url"):
                if supplier and _dom(s["url"]) != supplier:
                    continue
                cands.append({"row_index": d["row_index"], "slot": s["slot"],
                              "expected_url": s["url"], "item_id": d.get("item_id", "")})
    return cands


def main():
    ap = argparse.ArgumentParser(
        description="補URL売切消込 手動ドレイン (自動が急増ガードで止まる時の fallback)",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--label", default="SHEET", help="decision log label (default SHEET=HIGH)")
    ap.add_argument("--supplier", default=None,
                    choices=["mercari", "snkrdunk", "amazon", "fril"], help="supplier 絞り込み")
    ap.add_argument("--reverify-snkrdunk", action="store_true",
                    help="snkrdunk 候補を is_listing_live で削除直前に再確認 (今も売切か)")
    ap.add_argument("--execute", action="store_true", help="本実行 (実削除)。指定なしは dry-run")
    args = ap.parse_args()

    log_path = _latest_sheet_log(args.label)
    if not log_path:
        print(f"[drain] decision log が無い (label={args.label})")
        return
    print(f"[drain] source: {os.path.basename(log_path)}")

    cands = _collect_candidates(log_path, args.supplier)
    from collections import Counter
    by = Counter(_dom(c["expected_url"]) for c in cands)
    print(f"[drain] genuine 売切補URL候補: {len(cands)} 件  内訳={dict(by)}")
    if not cands:
        return

    # snkrdunk 再確認 (削除直前の freshness、is_listing_live で今も売切か)
    if args.reverify_snkrdunk:
        from scrapers.snkrdunk_scraper import _hq_is_listing_live  # noqa: PLC0415
        kept, dropped = [], 0
        for c in cands:
            if _dom(c["expected_url"]) == "snkrdunk":
                live = _hq_is_listing_live(c["expected_url"])
                if live is True:      # 今は在庫あり → 消さない
                    dropped += 1
                    continue
            kept.append(c)
        print(f"[drain] reverify-snkrdunk: 在庫復活で除外 {dropped} 件 → 対象 {len(kept)} 件")
        cands = kept

    if not args.execute:
        print("[drain] === DRY-RUN (実削除なし、--execute で実行) ===")
        for c in cands[:40]:
            col = ["AC", "AD", "AE", "AF", "AG"][c["slot"]]
            print(f"    row{c['row_index']} {col} {c['expected_url'][:60]}")
        if len(cands) > 40:
            print(f"    ... 他 {len(cands) - 40} 件")
        return

    # 本実行: 急増ガード override + compare-and-clear + アーカイブ
    sh = su.open_sheet_by_id(su.HIGH_SHEET_ID)
    ws = su.get_listings_worksheet(sh)
    res = su.clear_sold_backup_cells(
        ws, [{"row_index": c["row_index"], "slot": c["slot"],
              "expected_url": c["expected_url"]} for c in cands],
        enable_surge_guard=False)
    print(f"[drain] ★結果: cleared={res['cleared']} / candidate={res['candidate_count']} "
          f"/ skipped(HQ差替保護)={len(res['skipped_mismatch'])}")

    # 復元アーカイブ追記
    id_by_row = {c["row_index"]: c.get("item_id", "") for c in cands}
    ts = datetime.now().isoformat(timespec="seconds")
    with open(ARCHIVE, "a", encoding="utf-8") as af:
        for e in (res.get("cleared_entries") or []):
            af.write(json.dumps({**e, "item_id": id_by_row.get(e["row_index"], ""),
                                 "ts": ts, "reason": "supervised_drain_tool"},
                                ensure_ascii=False) + "\n")
    print(f"[drain] アーカイブ追記済 → {os.path.basename(ARCHIVE)} (誤削除でも url 復元可)")
    for m in res["skipped_mismatch"][:15]:
        print(f"    skip row{m['row_index']} slot{m['slot']} (セル値≠確認URL)")


if __name__ == "__main__":
    main()
