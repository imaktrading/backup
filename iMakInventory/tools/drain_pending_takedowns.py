"""drain_pending_takedowns — 取下げ待ちを今すぐ送る (eBay の日次API上限から回復した後用).

なぜ要るか (2026-08-24):
    eBay の 1 日の呼出上限 (エラー 518) に当たると、取下げが 1 件も送れなくなる。
    上限は毎日 16:00 頃 (米国 0:00) に戻るが、**次の巡回の取下げ送信は巡回の最後**
    (開始から 2〜3 時間後) なので、回復してもすぐには送られない。
    実害 08-24: 11:00 に上限到達 → 4 件が「仕入元は売切なのに eBay で買える」状態で
    5 時間残った。回復した時点で待たずに送れる口をここに置く。

やること (巡回と同じ判断・同じ API):
    1. pending_revise.jsonl (取下げ待ち) を読む
    2. 1 件ずつ eBay の現在数量を見る
       - 残り 0 / 終了済 → 何もしない (もう買えない)
       - 残り > 0        → qty=0 を送る
    3. 送った後に**もう一度 eBay を見て 0 になったか確認する** (送っただけで終わらせない)

キューからの削除はしない。巡回側の drain / prune に任せる (台帳の持ち主は巡回)。
二重に消すと「送ったのに記録が無い」が生まれるため。

使い方:
    python -m tools.drain_pending_takedowns              # 確認だけ (何も送らない)
    python -m tools.drain_pending_takedowns --execute    # 実際に取下げる
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

PENDING_FILE = ROOT_DIR / "decision_log" / "pending_revise.jsonl"


def _read_pending() -> list:
    if not PENDING_FILE.exists():
        return []
    out = []
    for line in PENDING_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("item_id"):
            out.append(e)
    return out


def ebay_state(item_id: str) -> tuple:
    """(残り数量, listing 状態) を返す。取れなければ (None, None) = 触らない."""
    from ebay_actions.trading_api_client import _call_trading  # noqa: PLC0415

    body = ("<?xml version='1.0' encoding='utf-8'?>"
            "<GetItemRequest xmlns='urn:ebay:apis:eBLBaseComponents'>"
            f"<ItemID>{item_id}</ItemID><DetailLevel>ReturnAll</DetailLevel>"
            "</GetItemRequest>")
    res = _call_trading("GetItem", body, raw_xml_cap=None)
    xml = res.get("raw_xml") or ""
    q = re.search(r"<Quantity>(\d+)</Quantity>", xml)
    s = re.search(r"<QuantitySold>(\d+)</QuantitySold>", xml)
    st = re.search(r"<ListingStatus>(\w+)</ListingStatus>", xml)
    if not q or not s:
        return None, (st.group(1) if st else None)
    return int(q.group(1)) - int(s.group(1)), (st.group(1) if st else None)


def main() -> int:
    p = argparse.ArgumentParser(description="取下げ待ちを今すぐ送る (API上限からの回復後)")
    p.add_argument("--execute", action="store_true", help="実際に送る (既定は確認のみ)")
    p.add_argument("--item-id", action="append", help="対象を絞る (複数可)")
    args = p.parse_args()

    entries = _read_pending()
    if args.item_id:
        want = set(args.item_id)
        entries = [e for e in entries if e["item_id"] in want]
    # 同じ item が複数回積まれていることがある (毎 cycle 再検知)。1 回にまとめる
    seen, targets = set(), []
    for e in entries:
        if e["item_id"] not in seen:
            seen.add(e["item_id"])
            targets.append(e)

    if not targets:
        print("取下げ待ちはありません")
        return 0

    print(f"取下げ待ち {len(targets)} 件 (実行={'する' if args.execute else 'しない (確認のみ)'})")
    from ebay_actions.trading_api_client import revise_inventory_status  # noqa: PLC0415

    still_live, sent_ok, failed = [], [], []
    for e in targets:
        iid = e["item_id"]
        avail, status = ebay_state(iid)
        if avail is None:
            print(f"  {iid}: eBay の状態を取得できず → 触らない ({status})")
            failed.append(iid)
            continue
        if avail <= 0 or status == "Completed":
            print(f"  {iid}: 残り {avail} ({status}) → もう買えない。何もしない")
            continue

        still_live.append(iid)
        if not args.execute:
            print(f"  {iid}: 残り {avail} ({status}) → ★買える状態。--execute で取下げます")
            continue

        r = revise_inventory_status(iid, 0)
        after, _ = ebay_state(iid)          # 送っただけで終わらせない
        if after == 0:
            print(f"  {iid}: 取下げ完了 (残り 0 を確認)")
            sent_ok.append(iid)
        else:
            code = r.get("error_code")
            print(f"  {iid}: ★取下げできていません (残り {after} / err={code} "
                  f"{str(r.get('error_message'))[:60]})")
            failed.append(iid)

    print(f"\n買える状態だったもの {len(still_live)} 件 / 取下げ完了 {len(sent_ok)} 件 / "
          f"未完了 {len(failed)} 件")
    if failed:
        print("★未完了が残っています。次の巡回でも再送されますが、"
              "eBay 上限 (518) が続いているなら回復を待ってからやり直してください")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
