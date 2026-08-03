"""窓口回答『2026-08-03_yodobashi_url_reverse_lookup_response.md』の完了報告用計測.

**シート/DB には一切書きません** (read-only)。実 snapshot と LOW 実データを使って、
URL 逆引き fallback を入れた前後で:
  - lookup 不能行数 (before=34) が いくつに減ったか
  - 主URL(Amazon)売切 かつ ヨドバシ補で救済可能な行 (row827/832 等) の内訳
  - 誤復活 (在庫あり判定にすべきでない行を in_stock 化していないか) の確認
を出します。

使い方: python tools/measure_yodobashi_url_fallback.py
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import monitor_listings as ml
from sheet_updater import LOW_SHEET_ID, get_listings_worksheet, open_sheet_by_id, read_listings_rows


def _yodo_slot(row):
    for s in row.get("backup_url_slots") or []:
        if s and "yodobashi.com" in s:
            return s
    return None


def _lookup_key_only(snap, key):
    if not snap:
        return None
    ent = snap.get((key or "").strip()) if key else None
    return ent if isinstance(ent, dict) else None


def _lookup_key_then_url(snap, key, url):
    ent = _lookup_key_only(snap, key)
    if ent is None and snap:
        ent = ml._yodobashi_entry_by_url(snap, url)
    return ent


def main():
    snap = ml._load_yodobashi_snapshot()
    if not snap:
        raise SystemExit("snapshot が空/古い. 実 snapshot が必要 (fail-closed で計測になりません)")

    sh = open_sheet_by_id(LOW_SHEET_ID)
    ws = get_listings_worksheet(sh)
    rows = read_listings_rows(ws)

    yodo_rows = [(r, _yodo_slot(r)) for r in rows if _yodo_slot(r)]

    before_uncertain = []
    after_uncertain = []
    rescued_now = []           # before miss / after hit
    stayed_hit = []            # before hit / after hit (回帰)

    for r, yurl in yodo_rows:
        key = r.get("key_number") or ""
        b = _lookup_key_only(snap, key)
        a = _lookup_key_then_url(snap, key, yurl)
        if b is None:
            before_uncertain.append(r)
        else:
            stayed_hit.append(r)
        if a is None:
            after_uncertain.append(r)
        elif b is None:
            rescued_now.append((r, a))

    print(f"yodobashi 補あり 行数            : {len(yodo_rows)}")
    print(f"before (型番のみ) lookup 不能    : {len(before_uncertain)}")
    print(f"after  (型番→URL) lookup 不能    : {len(after_uncertain)}")
    print(f"URL 逆引きで復活した             : {len(rescued_now)}")
    print(f"型番で当たり続けた (回帰チェック): {len(stayed_hit)}")
    print()

    # 具体的に「主URL売切 かつ ヨドバシ in_stock=True」= 本当に救済したい行
    watch = {745, 749, 783, 805, 815, 827, 832, 834}
    def _kind(ins):
        if ins is True:  return "in_stock=True"
        if ins is False: return "in_stock=False"
        return "None"

    print("[watch rows: 窓口が明示的に結果を求めた行]")
    for r, _ in yodo_rows:
        ri = r["row_index"]
        if ri not in watch:
            continue
        yurl = _yodo_slot(r)
        b = _lookup_key_only(snap, r.get("key_number") or "")
        a = _lookup_key_then_url(snap, r.get("key_number") or "", yurl)
        b_ins = (b.get("in_stock") if b else None)
        a_ins = (a.get("in_stock") if a else None)
        print(f"  row{ri:>3}  D={r.get('current_sold','')!s:2}  key={r.get('key_number',''):18s}  "
              f"before={_kind(b_ins):15s}  after={_kind(a_ins):15s}  "
              f"a_price={(a or {}).get('price_jpy')}  item_id={r.get('item_id','')}")

    # AI空 + 主OOS 潜在 の内訳
    ai_empty = [r for r, _ in yodo_rows if not (r.get("key_number") or "").strip()]
    ai_empty_hits_via_url = [
        r for r in ai_empty
        if _lookup_key_then_url(snap, "", _yodo_slot(r)) is not None
    ]
    print()
    print(f"AI列(型番) 空 の 行             : {len(ai_empty)}")
    print(f"  うち URL 逆引きで解決可能    : {len(ai_empty_hits_via_url)}")

    # 誤復活防止の 3 行 (窓口の依頼: これらが in_stock=True にならないこと)
    print()
    print("[誤復活チェック: 745/805/834 が in_stock=True と誤判定しないこと]")
    for ri in (745, 805, 834):
        r = next((x for x, _ in yodo_rows if x["row_index"] == ri), None)
        if r is None:
            continue
        yurl = _yodo_slot(r)
        a = _lookup_key_then_url(snap, r.get("key_number") or "", yurl)
        a_ins = (a.get("in_stock") if a else None)
        ok = a_ins is not True
        print(f"  row{ri}  after_in_stock={_kind(a_ins)}  誤復活しない={ok}")


if __name__ == "__main__":
    main()
