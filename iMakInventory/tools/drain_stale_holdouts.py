"""drain_stale_holdouts — action_required.jsonl の stale holdout を安全ドレイン (deadlock 解除).

背景 (2026-07-07): 07-04 eBay API 518 で取下げが止まり backlog 発生 → 急増ガードが毎cycle
全件を再 HOLD する deadlock 化 → action_required が unique 335 / 2227 entry に肥大化し、
閾値を恒常超過で新規売切も保留され続ける (新 fail-OPEN の温床)。

このツールは eBay active listing snapshot (GetSellerList CSV) の qty で各 holdout を判定:
  - eBay qty=0 / ended (active に不在) = 既に取下げ済 = 非漏れ → archive + action_required から削除
  - eBay qty>0 = live 漏れ → **触らない** (別途 reverse_audit/release_holdouts で取下げ)
  - item_id 空欄 = 判定不能 → 触らない (手動)
= 「非漏れの stale 記録」 だけ物理削除して backlog を閾値以下に戻す。qty>0 の本物は絶対消さない
(fail-CLOSED)。全削除は released_revise.jsonl + processed_revise.jsonl に archive (silent 化禁止)。
"""
from __future__ import annotations
import csv, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
try: sys.stdout.reconfigure(encoding="utf-8",errors="replace")
except Exception: pass
from tools.release_holdouts import (ACTION_REQUIRED_FILE, _load_action_required,
    _archive_release, _remove_released_from_action_required)

def _qty_map_from_csv(csv_path):
    m={}
    with open(csv_path,encoding="utf-8-sig",newline="") as f:
        for r in csv.DictReader(f):
            iid=(r.get("Item number") or "").strip()
            if not iid: continue
            try: q=int(r.get("Available quantity") or 0)
            except (TypeError,ValueError): q=0
            m[iid]=m.get(iid,0)+q
    return m

def main():
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument("--csv",required=True)
    ap.add_argument("--execute",action="store_true")
    a=ap.parse_args()
    qty=_qty_map_from_csv(a.csv)
    print(f"eBay active qty_map: {len(qty)} item")
    entries=_load_action_required()
    print(f"action_required: {len(entries)} entries")
    drain=[]; keep_leak=set(); keep_noid=0
    for e in entries:
        iid=(e.get("item_id") or "").strip()
        if not iid:
            keep_noid+=1; continue
        q=qty.get(iid,0)  # active に不在 = 0 (ended/取下げ済)
        if q>0:
            keep_leak.add(iid)  # live 漏れ → 触らない
        else:
            drain.append(e)
    uids_drain={(e.get("item_id") or "") for e in drain}
    print(f"  drain 対象 (qty=0/ended): {len(drain)} entries / {len(uids_drain)} unique item")
    print(f"  keep (qty>0 live 漏れ): {len(keep_leak)} item {sorted(keep_leak)}")
    print(f"  keep (item_id 空欄, 手動): {keep_noid} entries")
    if not a.execute:
        print("\n[dry-run] --execute で実削除")
        return
    keys=set()
    for e in drain:
        _archive_release(e,{"success":True,"msg":"drained: eBay qty=0/ended (stale holdout, deadlock解除)"})
        keys.add((e.get("ts",""),e.get("item_id",""),e.get("reason","")))
    removed=_remove_released_from_action_required(keys)
    print(f"\n=== 実行完了 ===")
    print(f"  archive: {len(drain)} entries / action_required 削除: {removed} entries")
    rest=_load_action_required()
    print(f"  残 action_required: {len(rest)} entries")


if __name__ == "__main__":
    main()
