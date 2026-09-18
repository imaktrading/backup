"""市場で売れた実績の台帳 (Terapeak 抜き出しの CSV を1本に溜める)。

拡張 (iMakHQ/tools/terapeak_grab) が出した `terapeak_*.csv` を拾って、
`C:/dev/iMak_data/hq/market_sold/ledger.csv` に追記する。同じ出品は1行にしかならない。

    python iMakHQ/tools/market_ledger.py ingest          # ダウンロード等から取り込む
    python iMakHQ/tools/market_ledger.py report          # 売れているカードと前回との差
    python iMakHQ/tools/market_ledger.py targets         # 探す先 (売れているのに出していない)

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

# ---- 条件セット (ここが唯一の口。手打ちしない) ----
# 2026-09-18 ユーザー確定。変える時はここだけ変える。
#   共通: CCG Individual Cards / 即決+オファー承諾 (オークション除外) / 日本人セラー /
#         売れた数の多い順 / 1ページ50件。価格の下限は入れない ($40未満は実測で4%)
#   Game は URL の aspect に入る (aspect=Game:::One Piece CCG)。実機で確認済み
RESEARCH_BASE = "https://www.ebay.com/sh/research"
CATEGORY_CCG = "183454"

PRESETS = {
    "ポケモン": ["Pokémon TCG"],
    "ワンピース": ["One Piece CCG"],
    # ★2026-09-18: 市場側では Dragon Ball CCG にも66件出ていたが、CCG は 2000年代の
    #   別ゲーム (Score 社)。うちが扱う FB/DBS の弾は Super Card Game なので入れない
    #   (カタログ回答 2026-09-18_aspect_values_vs_ebay_list_response.md)
    "ドラゴンボール": ["Dragon Ball Super Card Game"],
}

DAY_RANGES = {
    "7日": 7, "30日": 30, "90日": 90, "6ヶ月": 180,
    "1年": 365, "2年": 730, "3年": 1095,
}
DEFAULT_DAYS = 90
# ★2026-09-18 ユーザー確定: `PSA10`。eBay の検索は `PSA 10` (間にスペース) も拾うので
#   取りこぼさない (実データで確認済み: "PSA 10 Red's Pikachu 270/SM-P" が入っていた)
KEYWORDS = "PSA10"


def build_url(preset, tab="SOLD", days=DEFAULT_DAYS, keywords=KEYWORDS, now=None):
    """条件セットから Research の URL を作る。

    tab は "SOLD" か "ACTIVE"。days は DAY_RANGES の値 (既定 90)。
    """
    import urllib.parse
    if preset not in PRESETS:
        raise KeyError(f"知らない条件セット: {preset}")
    tab = tab.upper()
    if tab not in ("SOLD", "ACTIVE"):
        raise ValueError(f"tab は SOLD か ACTIVE: {tab}")
    now = now or datetime.datetime.now()
    end = int(now.timestamp() * 1000)
    start = int((now - datetime.timedelta(days=days)).timestamp() * 1000)
    q = [
        ("marketplace", "EBAY-US"),
        ("keywords", keywords),
        ("dayRange", str(days)),
        ("endDate", str(end)),
        ("startDate", str(start)),
        ("categoryId", CATEGORY_CCG),
        ("format", "BEST_OFFER"),
        ("format", "FIXED_PRICE"),
    ]
    q += [("aspect", f"Game:::{g}") for g in PRESETS[preset]]
    q += [
        ("sellerCountry", "JP"),
        ("offset", "0"),
        ("limit", "50"),
        ("tabName", tab),
        ("tz", "Asia/Tokyo"),
    ]
    if tab == "SOLD":
        q.append(("sorting", "-itemssold"))   # 売れた数の多い順 (ACTIVE には無い並び)
    return RESEARCH_BASE + "?" + urllib.parse.urlencode(q)


# ポケモンの形 (175/165 や 270/SM-P)
_CARD_NO = re.compile(r"\b(\d{1,3}\s*/\s*(?:\d{1,3}|[A-Z]{1,3}-?[A-Z]?))\b")
# ワンピース / ドラゴンボールの形 (OP03-057 / ST21-015 / P-001 / FB02-119 / SDV9-020 / MM2-074)
# ★2026-09-18: 斜線の形しか見ていなかったため、この2ゲームは1枚も読めていなかった
_CARD_NO_DASH = re.compile(r"\b([A-Z]{1,4}\d{0,2}-\d{2,3})\b")


def card_no(title):
    """タイトルからカード番号を取る。取れなければ None。

    ★eBay のタイトルは書き方がばらばらなので、番号だけを鍵にする。弾コードは
      セラーによって付いたり付かなかったりするので、鍵にすると取りこぼす。
    """
    if not title:
        return None
    t = title.upper().replace(" /", "/").replace("/ ", "/")
    m = _CARD_NO.search(t)
    if m:
        return m.group(1).replace(" ", "")
    m = _CARD_NO_DASH.search(t)
    return m.group(1) if m else None


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


# ---- 探す先に渡す一覧 (市場で売れているのに、うちが出していないカード) ----
# ★抽出くんの決まり (skill harvest-targeting ①-3): 語にしてよいのは「番号が取れた」か
#   「カタログを引けた」時だけ。訳さない・推測しない。だからここでは番号とカタログの和名しか出さない。
CATALOG_DB = r"C:/dev/iMak_data/catalog/products.sqlite"
TARGETS_CSV = os.path.join(LEDGER_DIR, "demand_market.csv")

# タイトルの中の弾コード (SV2a / S12a / M2a / CLK / sv1a …)
_SET_CODE = re.compile(r"\b((?:SV|S|M|CLK|SM|XY|BW|DP)[0-9]{0,2}[A-Z]?)\b", re.I)


def product_id_candidates(key, title):
    """カード番号 (と市場タイトル) から、カタログの product_id の候補を作る。"""
    if "/" not in key:
        return [key.upper()]                      # OP03-057 / P-043 はそのまま
    num, suffix = key.split("/", 1)
    if not suffix.isdigit():                      # 020/M-P → M-P-020
        return [f"{suffix.upper()}-{num}"]
    out = []
    for m in _SET_CODE.finditer(title or ""):     # 175/165 は弾コードをタイトルから拾う
        code = m.group(1)
        if code.upper() in ("M", "S", "SV"):      # 単独の文字は弾ではない
            continue
        out.append(f"{code}-{num}")
    return out


def lookup_catalog(cands, conn):
    """product_id でカタログを引く。**完全一致だけ** (名前で探さない)。"""
    for pid in cands:
        row = conn.execute(
            "SELECT product_id, name, name_jp, category FROM products WHERE product_id=?", (pid,)
        ).fetchone()
        if row:
            return row
    return None


def missing_cards(rows, live_keys, min_sold=2):
    """市場で min_sold 以上売れたのに、うちが出していないカード。"""
    agg, _ = by_card(rows)
    mine_dash, mine_num = set(), collections.defaultdict(set)
    for k in live_keys:
        m = re.match(r"^([A-Za-z0-9]+)-(\d+)", (k or "").split(":")[-1])
        if m:
            mine_dash.add(f"{m.group(1).upper()}-{m.group(2)}")
            mine_num[m.group(2).lstrip("0")].add(m.group(1).upper())
    out = []
    for k, v in agg.items():
        if v["sold"] < min_sold:
            continue
        if "/" in k:
            sets = mine_num.get(k.split("/")[0].lstrip("0"), set())
            title = re.sub(r"[^A-Z0-9]", "", v["title"].upper())
            have = any(s in title for s in sets)
        else:
            have = k.upper() in mine_dash
        if not have:
            out.append((k, v))
    return sorted(out, key=lambda x: -x[1]["sold"])


# ---- 実売価格 → 上限の仕入れ値 (cost-plus の逆引き) ----
# ★式は持たない。出品と同じ pricing_engine を二分探索で逆に解くだけ。
#   ここに計算式を写すと、値付けを変えた時に2箇所になる (SSOT を割らない)。
PROFIT_CATEGORY = "TCG(PSA10)"


def max_cost_jpy(price_usd, category=PROFIT_CATEGORY, lo=100, hi=300000):
    """その値段で売るには、仕入れがいくらまでなら出せるか (円)。

    出品価格は仕入れ値に対して単調に増えるので、二分探索で解ける。
    解けない (安すぎて下限でも超える) 時は None。
    """
    if not price_usd or price_usd <= 0:
        return None
    sys.path.insert(0, r"C:/dev/iMak/iMakeBayAPI")
    from pricing_engine import compute_listing_price

    def price_of(cost):
        return compute_listing_price(cost, 0, category)["price"]

    try:
        if price_of(lo) > price_usd:
            return None                      # 一番安い仕入れでも、この値段では出せない
        for _ in range(40):
            mid = (lo + hi) / 2
            if price_of(mid) <= price_usd:
                lo = mid
            else:
                hi = mid
        return int(lo // 100 * 100)          # 100円単位で切り捨て (安全側)
    except Exception:                        # noqa: BLE001 価格が出せない時は付けない
        return None


def cmd_targets(argv):
    """探す先の一覧を作る (毎回作り直す。焼いた値は残さない)。"""
    import sqlite3
    rows = load_ledger()
    if not rows:
        print("台帳が空です。先に ingest してください")
        return 1
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import psa_hoju_fill as H
    live = H.select_backfill_targets(H._read_high(), max_backups=H.AUXN + 1)
    miss = missing_cards(rows, [t.get("key") for t in live])

    conn = sqlite3.connect(CATALOG_DB)
    out, hit = [], 0
    for k, v in miss:
        row = lookup_catalog(product_id_candidates(k, v["title"]), conn)
        if row:
            hit += 1
        med = round(statistics.median(v["prices"]), 2) if v["prices"] else 0
        out.append({
            "番号": k,
            "product_id": row[0] if row else "",
            "和名": row[2] if row else "",
            "英名": row[1] if row else "",
            "ゲーム": row[3] if row else "",
            "売れた数": v["sold"],
            "出品本数": v["listings"],
            "実売中央値": med,
            "上限仕入れ値(円)": max_cost_jpy(med) if med else "",
            "市場のタイトル例": v["title"][:80],
        })
    cols = list(out[0].keys())
    with open(TARGETS_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(out)
    print(f"市場で2個以上売れて、うちが出していない: {len(out)}種類 / 販売 "
          f"{sum(r['売れた数'] for r in out)}個")
    print(f"カタログを引けた: {hit}種類 ({hit / len(out):.0%})")
    print(f"→ {TARGETS_CSV}")
    return 0


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
    cmds = {"ingest": cmd_ingest, "report": cmd_report, "targets": cmd_targets}
    if len(argv) < 2 or argv[1] not in cmds:
        print(__doc__)
        return 1
    return cmds[argv[1]](argv[2:])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
