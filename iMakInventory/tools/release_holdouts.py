"""release_holdouts — action_required.jsonl の HOLD entry を人手で release (= 取下げ実行).

HQ 2026-06-10 Phase 1.6 affirm #1 「burst HOLD が新 fail-OPEN にならないこと」 の load-bearing tool:

- burst HOLD = listing が出品継続 = 本物の大量売切なら eBay で売れ続ける = 在庫不足で履行不能 = BAN risk
- → 人が「本物 or 偽 OOS」 を確認 → 本物だけ release (= revise qty=0 実行) する経路が必須

使用例:
  # dry-run で HOLD 一覧確認 (= 必ず先に実行して人手確認)
  python -m tools.release_holdouts --reason newly_sold_burst_guard_holdout

  # 全件 release (= 本物の売切と判断したとき)
  python -m tools.release_holdouts --reason newly_sold_burst_guard_holdout --execute

  # 特定 item_id だけ release
  python -m tools.release_holdouts --reason newly_sold_burst_guard_holdout --item-id 358543162011 --execute

  # 全 reason 種別から item_id 指定で release
  python -m tools.release_holdouts --item-id 358543162011 --execute

release 経路:
  action_required.jsonl の対象 entry を読込
  → eBay GetItem qty 確認 (= 偽 OOS なら qty=1 のまま → 「本物」 確認、 = qty=0 なら既に対処済)
  → 確認後 ReviseInventoryStatus qty=0 で取下げ実行
  → action_required.jsonl から物理削除 (released_revise.jsonl に archive)
  → processed_revise.jsonl にも 記録 (= 通常の drain と同 ledger)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# 親ディレクトリを sys.path に
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DECISION_LOG_DIR = ROOT_DIR / "decision_log"
ACTION_REQUIRED_FILE = DECISION_LOG_DIR / "action_required.jsonl"
RELEASED_FILE = DECISION_LOG_DIR / "released_revise.jsonl"
PROCESSED_REVISE_FILE = DECISION_LOG_DIR / "processed_revise.jsonl"


def _load_action_required() -> list:
    """action_required.jsonl を全件読込 → list of dict."""
    if not ACTION_REQUIRED_FILE.exists():
        return []
    entries = []
    for line in ACTION_REQUIRED_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _ebay_current_qty(item_id: str, token: str) -> tuple:
    """eBay GetItem で qty 現状確認. Returns: (qty: int|None, msg: str)."""
    if not item_id:
        return None, "item_id 空欄"
    from ebay_actions.trading_api_client import _call_trading  # noqa: PLC0415
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
        f'<ItemID>{item_id}</ItemID></GetItemRequest>'
    )
    try:
        res = _call_trading("GetItem", body, access_token=token)
    except Exception as e:
        return None, f"GetItem 例外: {type(e).__name__}: {e}"
    if res.get("error_code") == "17":
        return 0, "err_17 (Item not found = 既 ended)"
    if not res.get("success"):
        return None, f"GetItem 失敗 ack={res.get('ack')} err={res.get('error_code')}"
    m = re.search(r"<Quantity>(\d+)</Quantity>", res.get("raw_xml", ""))
    if m:
        return int(m.group(1)), f"qty={m.group(1)}"
    return None, "qty tag 不明"


def _execute_revise(item_id: str, token: str) -> tuple:
    """ReviseInventoryStatus qty=0 実行 + verify. Returns: (success: bool, msg: str)."""
    from ebay_actions.trading_api_client import revise_inventory_status  # noqa: PLC0415
    try:
        res = revise_inventory_status(item_id, 0, access_token=token)
    except Exception as e:
        return False, f"revise 例外: {type(e).__name__}: {e}"
    safe = res.get("error_code") in ("17", "231", "21916750")
    success = res.get("success") or safe
    if success:
        # verify
        time.sleep(2.0)
        qty, vmsg = _ebay_current_qty(item_id, token)
        if qty == 0:
            return True, f"revise OK + verify qty=0 ({vmsg})"
        return True, f"revise OK ack={res.get('ack')} ただし verify qty={qty} (= {vmsg})"
    return False, f"revise NG ack={res.get('ack')} err={res.get('error_code')} msg={(res.get('error_message') or '')[:100]}"


def _archive_release(entry: dict, exec_result: dict) -> None:
    """released_revise.jsonl + processed_revise.jsonl に記録."""
    DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)
    archived = {
        **entry,
        "released_at": datetime.now().isoformat(timespec="seconds"),
        "release_result": exec_result,
    }
    with open(RELEASED_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(archived, ensure_ascii=False) + "\n")
    # 通常 cycle 同様 processed_revise にも記録 (= ledger 統一)
    with open(PROCESSED_REVISE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts":         entry.get("ts", ""),
            "sheet":      entry.get("sheet", ""),
            "row_index":  entry.get("row_index", -1),
            "url":        entry.get("url", ""),
            "item_id":    entry.get("item_id", ""),
            "title":      entry.get("title", ""),
            "supplier":   entry.get("supplier", ""),
            "raw_status": entry.get("raw_status", ""),
            "dry_run":    False,
            "consumed_at": datetime.now().isoformat(timespec="seconds"),
            "consumed_via": "release_holdouts_cli",
        }, ensure_ascii=False) + "\n")


def _remove_released_from_action_required(released_keys: set) -> int:
    """action_required.jsonl から released entry を物理削除. Returns: 削除件数."""
    if not ACTION_REQUIRED_FILE.exists():
        return 0
    keep = []
    removed = 0
    for line in ACTION_REQUIRED_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            keep.append(line)
            continue
        key = (entry.get("ts", ""), entry.get("item_id", ""), entry.get("reason", ""))
        if key in released_keys:
            removed += 1
        else:
            keep.append(line)
    ACTION_REQUIRED_FILE.write_text(
        ("\n".join(keep) + "\n") if keep else "",
        encoding="utf-8",
    )
    return removed


def main():
    parser = argparse.ArgumentParser(
        description="action_required.jsonl の HOLD entry を release (取下げ実行).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Phase 1.6 burst HOLD の release 例:\n"
            "  # 1. dry-run で対象確認\n"
            "  python -m tools.release_holdouts --reason newly_sold_burst_guard_holdout\n"
            "  # 2. 本物の売切と確認したら execute\n"
            "  python -m tools.release_holdouts --reason newly_sold_burst_guard_holdout --execute\n"
        ),
    )
    parser.add_argument("--reason", default=None,
                        help="reason filter (例: newly_sold_burst_guard_holdout / reinclude_burst_guard_holdout / item_id_empty / verify_qty_gt0_giveup)")
    parser.add_argument("--item-id", default=None, help="item_id filter (= 単一 item release)")
    parser.add_argument("--execute", action="store_true",
                        help="本実行 (= revise 投げる)。 指定なしは dry-run。")
    args = parser.parse_args()

    entries = _load_action_required()
    print(f"action_required.jsonl total: {len(entries)} 件")

    # フィルタ適用
    filtered = entries
    if args.reason:
        filtered = [e for e in filtered if e.get("reason") == args.reason]
        print(f"  reason={args.reason} で絞込: {len(filtered)} 件")
    if args.item_id:
        filtered = [e for e in filtered if e.get("item_id") == args.item_id]
        print(f"  item_id={args.item_id} で絞込: {len(filtered)} 件")

    if not filtered:
        print("対象なし、 終了。")
        return

    # dry-run mode = 一覧表示のみ
    if not args.execute:
        print(f"\n=== dry-run: {len(filtered)} 件の対象 ===")
        for i, e in enumerate(filtered, 1):
            iid = e.get("item_id") or "(item_id 空欄)"
            print(f"  [{i:3d}] {e.get('sheet','?')} row{e.get('row_index','?')} iid={iid} "
                  f"reason={e.get('reason','')}")
            t = e.get("title") or ""
            if t:
                print(f"        title: {t[:60]}")
        print(f"\n本実行は --execute を付けて再実行。")
        return

    # execute mode
    print(f"\n=== execute mode: {len(filtered)} 件 release ===")
    print(f"  各 entry について eBay 現状確認 + revise qty=0 実行 + action_required から削除")
    from ebay_actions.trading_api_client import load_access_token  # noqa: PLC0415
    token = load_access_token()
    released_keys = set()
    ok_count = ng_count = skip_count = 0
    for i, e in enumerate(filtered, 1):
        iid = e.get("item_id") or ""
        if not iid:
            print(f"  [{i:3d}] SKIP iid 空欄 → 手動取下げ要 (= eBay 検索で item_id 引き直し)")
            skip_count += 1
            continue
        # 現状確認
        qty, qmsg = _ebay_current_qty(iid, token)
        if qty == 0:
            print(f"  [{i:3d}] SKIP iid={iid} 既 qty=0 ({qmsg}) → 対処済、 release ledger に記録のみ")
            _archive_release(e, {"success": True, "msg": f"already qty=0 ({qmsg})"})
            released_keys.add((e.get("ts", ""), iid, e.get("reason", "")))
            ok_count += 1
            continue
        if qty is None:
            print(f"  [{i:3d}] NG  iid={iid} 現状確認失敗: {qmsg}")
            ng_count += 1
            continue
        # 本実行
        ok, rmsg = _execute_revise(iid, token)
        print(f"  [{i:3d}] {'OK' if ok else 'NG'} iid={iid} {rmsg}")
        if ok:
            _archive_release(e, {"success": True, "msg": rmsg})
            released_keys.add((e.get("ts", ""), iid, e.get("reason", "")))
            ok_count += 1
        else:
            ng_count += 1
        time.sleep(0.3)  # pacing
    # action_required.jsonl 物理削除
    removed = _remove_released_from_action_required(released_keys)
    print(f"\n=== 結果 ===")
    print(f"  OK: {ok_count} 件 / NG: {ng_count} 件 / SKIP: {skip_count} 件")
    print(f"  action_required.jsonl から削除: {removed} 件")
    print(f"  released_revise.jsonl に archive: {ok_count} 件")
    sys.exit(0 if ng_count == 0 else 1)


if __name__ == "__main__":
    main()
