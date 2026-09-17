"""市場で売れた実績の台帳 (Terapeak 抜き出しの CSV を1本に溜める)。

拡張 (iMakHQ/tools/terapeak_grab) が出した `terapeak_*.csv` を拾って、
`C:/dev/iMak_data/hq/market_sold/ledger.csv` に追記する。同じ出品は1行にしかならない。

    python iMakHQ/tools/market_ledger.py ingest          # ダウンロード等から取り込む
    python iMakHQ/tools/market_ledger.py report          # 売れているカードと前回との差

★台帳に貯めるのは **出品ごとの行** (eBay が出した「期間中に何個売れたか」付き)。
  カード単位の集計は report の時に作る。集計を焼いて保存すると、後から数え直せなくなる。
"""

import csv
import glob
import os
import re
import sys
import collections
import statistics
import datetime

LEDGER_DIR = r"C:/dev/iMak_data/hq/market_sold"
LEDGER = os.path.join(LEDGER_DIR, "ledger.csv")

# 拡張が出す CSV の置き場 (新しい順に見る)
SEARCH_DIRS = [
    os.path.join(os.path.expanduser("~"), "Downloads"),
    os.path.join(os.path.expanduser("~"), "OneDrive", "デスクトップ"),
    os.path.join(os.path.expanduser("~"), "Desktop"),
    LEDGER_DIR,
]

# 台帳の鍵: 同じ検索で同じ出品なら1行 (取り直したら新しい方で上書き)
KEY_COLS = ("種別", "検索語", "itemId", "期間")

_CARD_NO = re.compile(r"\b(\d{1,3}\s*/\s*(?:\d{1,3}|[A-Z]{1,3}-?[A-Z]?))\b")


def card_no(title):
    """タイトルからカード番号 (123/456 や 270/SM-P) を取る。取れなければ None。

    ★eBay のタイトルは書き方がばらばらなので、番号だけを鍵にする。弾コードは
      セラーによって付いたり付かなかったりするので、鍵にすると取りこぼす。
    """
    if not title:
        return None
    m = _CARD_NO.search(title.upper().replace(" /", "/").replace("/ ", "/"))
    return m.group(1).replace(" ", "") if m else None


def _money(s):
    try:
        return float(str(s).replace("$", "").replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _read(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_ledger():
    return _read(LEDGER) if os.path.exists(LEDGER) else []


def merge(kept, incoming, ingested_at=None):
    """台帳 kept に incoming を混ぜる。鍵が同じなら新しい方を残す。

    返り値は (混ぜた後の行, 足された数, 上書きした数)。
    """
    stamp = ingested_at or datetime.date.today().isoformat()
    index = {tuple(r.get(c, "") for c in KEY_COLS): i for i, r in enumerate(kept)}
    rows = list(kept)
    added = updated = 0
    for r in incoming:
        if not r.get("itemId"):
            continue
        r = dict(r)
        r.setdefault("取込日", stamp)
        k = tuple(r.get(c, "") for c in KEY_COLS)
        if k in index:
            r["取込日"] = rows[index[k]].get("取込日", stamp)  # 初めて見た日を残す
            rows[index[k]] = r
            updated += 1
        else:
            index[k] = len(rows)
            rows.append(r)
            added += 1
    return rows, added, updated


def save_ledger(rows):
    cols = []
    for r in rows:
        for c in r:
            if c not in cols:
                cols.append(c)
    os.makedirs(LEDGER_DIR, exist_ok=True)
    with open(LEDGER, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def find_files(paths):
    out = []
    if paths:
        for p in paths:
            out += glob.glob(os.path.join(p, "terapeak_*.csv")) if os.path.isdir(p) else [p]
    else:
        for d in SEARCH_DIRS:
            out += glob.glob(os.path.join(d, "terapeak_*.csv"))
    # summary は 2026-09-18 に廃止。古いものが残っていても取り込まない
    return sorted(set(p for p in out if "_summary_" not in os.path.basename(p)))


def cmd_ingest(paths):
    files = find_files(paths)
    if not files:
        print("取り込む CSV が見つかりません (terapeak_*.csv)")
        return 1
    rows = load_ledger()
    before = len(rows)
    for p in files:
        rows, added, updated = merge(rows, _read(p))
        print(f"  {os.path.basename(p):<32} 新規 {added:4} / 更新 {updated:4}")
    save_ledger(rows)
    print(f"\n台帳 {before} → {len(rows)}行  ({LEDGER})")
    return 0


def by_card(rows, kind="Sold"):
    """カード番号ごとに 売れた数・出品本数・実売中央値 をまとめる。"""
    agg = collections.defaultdict(lambda: {"sold": 0, "listings": 0, "prices": [], "title": ""})
    unknown = 0
    for r in rows:
        if r.get("種別") != kind:
            continue
        try:
            n = int(r.get("売れた数") or 0)
        except ValueError:
            n = 0
        k = card_no(r.get("タイトル"))
        if not k:
            unknown += n
            continue
        a = agg[k]
        a["sold"] += n
        a["listings"] += 1
        p = _money(r.get("平均落札"))
        if p:
            a["prices"].append(p)
        if len(r.get("タイトル", "")) > len(a["title"]):
            a["title"] = r["タイトル"]
    return agg, unknown


def cmd_report(_):
    rows = load_ledger()
    if not rows:
        print("台帳が空です。先に ingest してください")
        return 1
    sold = [r for r in rows if r.get("種別") == "Sold"]
    days = sorted(set(r.get("取込日", "") for r in rows))
    print(f"台帳 {len(rows)}行 (Sold {len(sold)}) / 取込 {days[0]}〜{days[-1]}")
    agg, unknown = by_card(rows)
    total = sum(a["sold"] for a in agg.values()) + unknown
    print(f"販売 {total}個 / 番号が読めた {total - unknown}個 / カード {len(agg)}種類")
    multi = {k: a for k, a in agg.items() if a["sold"] >= 2}
    print(f"**2個以上売れたカード {len(multi)}種類**\n")
    print(f"{'個数':>4} {'中央値':>9}  {'番号':<12} カード")
    for k, a in sorted(agg.items(), key=lambda x: -x[1]["sold"])[:30]:
        med = statistics.median(a["prices"]) if a["prices"] else 0
        print(f"{a['sold']:>4} {med:>9.2f}  {k:<12} {a['title'][:52]}")
    if len(days) > 1:
        newest = days[-1]
        fresh = {k for k, a in by_card([r for r in rows if r.get("取込日") == newest])[0].items()}
        old = {k for k, a in by_card([r for r in rows if r.get("取込日") != newest])[0].items()}
        print(f"\n{newest} に初めて出てきたカード: {len(fresh - old)}種類")
    return 0


def main(argv):
    cmds = {"ingest": cmd_ingest, "report": cmd_report}
    if len(argv) < 2 or argv[1] not in cmds:
        print(__doc__)
        return 1
    return cmds[argv[1]](argv[2:])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
