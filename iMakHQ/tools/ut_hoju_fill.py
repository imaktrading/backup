# -*- coding: utf-8 -*-
"""UT (ユニクロ/GU コラボT) の補URL — 予備の仕入元を貯める (2026-09-03)。

■ なぜ要るか
中古アパレルの出品が止まったのは、**仕入元がすぐ売り切れて出品作業が無駄になった**から
(ユーザー談)。PSA で補URL (同じカードの別個体を貯める) を作ってから、その問題は消えた。
同じ仕組みを UT に持ち込む。

■ UT は PSA と何が違うか
PSA は「型番」1本で同一個体が決まる。UT は **作品 + 柄 + サイズ + 状態** が揃って初めて
同じ商品になる。実測 2026-09-03 (メルカリ):

    推しの子 B小町      拾えた20件 → JPサイズ XXL 一致 2件 → 使える 2件
    ONE PIECE FILM RED  拾えた20件 → JPサイズ XL  一致 6件 → 使える 3件
    怪獣8号             拾えた20件 → JPサイズ XL  一致 0件 (子供服で20件が埋まった)

= 1商品あたり 2〜3本 取れる。PSA と同程度。

★**UT は新品未使用に限る**。中古だと個体ごとに現物写真が要り、仕入元が変わるたび
  2枚目以降の画像を差し替えることになる。新品未使用なら公式画像だけで出せるので、
  仕入元が何本切れても画像はそのままでよい (ユーザー確定 2026-09-03)。

★サイズは **JP のまま**で照合する (メルカリの出品タイトルが JP 表記のため)。
  US 換算 (JP XL → US L) は eBay に出す時だけ。

■ 2つの使い道 (対象が違うだけで、探し方も目視も戻し方も PSA と同じ)
    補URL   … 数量1の行に、予備の仕入元を足す
    再仕入れ … **数量0**の行に、また買える仕入元を見つけて数量を戻す

    ★2026-09-03: 当初「Tシャツは出品が終わっているので新規出品になる」と考えたが
      **誤り**だった。実機で確認したら 売り切れ6件すべて Active・数量0 で、
      PSA と同じ状態。つまり **数量を戻すだけ**でよい (ユーザー指摘)。

■ 使い方
    python ut_hoju_fill.py search            # 補URL用の候補を貯める (夜間向け)
    python ut_hoju_fill.py confirm           # 目視で選んで 補URL(AC-AG) に書く
    python ut_hoju_fill.py restock-search    # 売り切れ行の仕入元を探して貯める
    python ut_hoju_fill.py restock-confirm   # 目視で選んで A列(仕入元URL)を更新
    (どちらの confirm も --dry-run で件数だけ)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "iMakeBayAPI")))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CACHE_PATH = r"C:/dev/iMak_data/hq/ut_hoju_cache.json"
RESTOCK_CACHE_PATH = r"C:/dev/iMak_data/hq/ut_restock_cache.json"
CATEGORY = "Tシャツ"
AUX_MAX = 5
MIN_REVIEWS = 100          # 個人セラーの評価件数の下限 (PSA 側と同じ)
SEARCH_URL = "https://jp.mercari.com/search?status=on_sale&order=asc&sort=price&keyword="

# JP → US。eBay に出す時だけ使う (照合は JP のまま)。
JP_TO_US = {"S": "XS", "M": "S", "L": "M", "XL": "L",
            "XXL": "XL", "3XL": "2XL", "4XL": "3XL"}

_SIZE_ALIASES = [("4XL", "4XL"), ("3XL", "3XL"), ("XXL", "XXL"), ("2XL", "XXL"),
                 ("LL", "XXL"), ("XL", "XL"), ("XS", "XS"),
                 ("L", "L"), ("M", "M"), ("S", "S")]


# ── 純関数 (test 可) ────────────────────────────────────────────────
def jp_size_of(text):
    """タイトルから JP サイズを読む。子供服は 'KIDS'、読めなければ ''。

    ★キッズを弾くのが肝。実測で「怪獣8号 UT」の検索結果20件が **120〜150cm の子供服**で
      埋まり、大人 XL が1件も残らなかった。大人サイズと同じ枠で数えると取りこぼす。
    """
    s = (text or "").upper().replace("　", " ")
    if re.search(r"(^|[^0-9])(1[0-6]0)\s*(CM|センチ|サイズ)?([^0-9]|$)", s) \
            or "子供服" in (text or "") or "キッズ" in (text or "") or "KIDS" in s:
        return "KIDS"
    for token, norm in _SIZE_ALIASES:
        if re.search(r"(^|[^A-Z0-9])" + token + r"([^A-Z0-9]|$)", s):
            return norm
    return ""


def us_size_of(jp):
    """JP サイズ → US サイズ。分からなければ ''。eBay 出品時だけ使う。"""
    return JP_TO_US.get((jp or "").upper(), "")


#  色・柄の言い回しは検索語に入れない。メルカリは **語を全部含む商品しか返さない**ので、
#  1語増やすたびに0件へ近づく。実測 2026-09-03: 「ユニクロ UT 推しの子 B小町 ブラッ Tシャツ」
#  で0件、「推しの子 UT Tシャツ B小町」で20件。色は目視で見分ければよい。
_NOISE = ("ユニクロ", "UNIQLO", "UT", "Tシャツ", "ティーシャツ", "半袖", "グラフィック",
          "プリント", "ビッグプリント", "キャラクター", "コラボ", "限定", "美品",
          "新品", "未使用", "タグ付き", "タグ付", "メンズ", "レディース", "サイズ",
          "ブラック", "ホワイト", "ネイビー", "グリーン", "ブルー", "オレンジ", "ベージュ",
          "レッド", "イエロー", "グレー", "パープル", "ピンク", "白", "黒", "紺", "緑", "赤",
          "半袖Tシャツ", "COLLECTION", "ARCHIVE", "アーカイブ")
_KEY_WORDS = 2      # 検索語に残す語数の上限 (作品名 + 固有名)


def build_keyword(title, max_words=_KEY_WORDS):
    """出品タイトルから メルカリの検索語を作る。作れなければ ''。

    ★きつく絞らない (ユーザー方針 2026-09-03「目視するから主要キーだけで」)。
      **語を足すほど0件に近づく**ので、作品名まわりの 2語だけ残して
      「<語> UT Tシャツ」の形にする。色・柄・サイズは目視で見分ける。
    """
    t = (title or "").strip()
    if not t:
        return ""
    s = t
    for d in _NOISE:
        s = re.sub(re.escape(d), " ", s, flags=re.I)
    s = re.sub(r"[【】（）()\[\]「」、,／/・]", " ", s)
    # サイズ表記・数字だけの塊は検索語にしない (JPサイズは後で照合する)
    for token, _n in _SIZE_ALIASES:
        s = re.sub(r"(^|[^A-Za-z0-9])" + token + r"([^A-Za-z0-9]|$)", " ", s, flags=re.I)
    s = re.sub(r"(^|\s)\d+\s*(CM|センチ)?(\s|$)", " ", s, flags=re.I)
    words = [w for w in re.split(r"[\s　]+", s) if len(w) >= 2][:max_words]
    if not words:
        return ""
    return " ".join(words) + " UT Tシャツ"


def size_matches(want, got):
    """JP サイズが同じか。どちらかが読めない / 子供服なら False (fail-closed)。"""
    if not want or not got or "KIDS" in (want, got):
        return False
    return want.upper() == got.upper()


def is_new_unused(cond):
    """新品未使用か。UT は新品に限る (中古だと個体ごとの写真が要る)。"""
    return "新品" in (cond or "")


def usable_candidate(cond, ship, reviews, is_shops, min_reviews=MIN_REVIEWS):
    """補URL に使えるか (純関数)。PSA の判定に「新品未使用」を足したもの。"""
    if not is_new_unused(cond):
        return False
    if ship != "送料込み":
        return False
    if not is_shops and (reviews is None or reviews < min_reviews):
        return False
    return True


def select_targets(rows2d, max_backups=AUX_MAX, category=CATEGORY, sold_out=False):
    """探す対象の UT 行 → [{row, itemID, title, size, have}] (純関数)。

    sold_out=False (既定) … **出品中**で補URL が max_backups 未満の行 = 予備を足す
    sold_out=True         … **売り切れた**行 = また買える仕入元を探す (再仕入れ)
    """
    import sheet_io
    B, SOLD, TITLE = sheet_io.PRODUCT_COL_ITEMID, 3, 2
    CAT = sheet_io.PRODUCT_COL_CATEGORY
    AUX = sheet_io.PRODUCT_COL_AUX_START

    def cell(r, i):
        return ((r[i] if len(r) > i else "") or "").strip()

    out = []
    for n, r in enumerate(rows2d[1:], start=2):
        if cell(r, CAT) != category or not cell(r, B):
            continue
        if sold_out:
            if not cell(r, SOLD):
                continue              # 売れていない = 再仕入れの対象ではない
        else:
            if cell(r, SOLD):
                continue              # 売り切れ = 補URL の対象ではない
        have = [cell(r, AUX + k) for k in range(AUX_MAX) if cell(r, AUX + k)]
        if not sold_out and len(have) >= max_backups:
            continue
        title = cell(r, TITLE)
        out.append({"row": n, "itemID": cell(r, B), "title": title,
                    "size": jp_size_of(title), "have": have,
                    "keyword": build_keyword(title)})
    return out


def merge_aux(have, picked, max_urls=AUX_MAX):
    """既存の補URL を残したまま、空き枠にだけ足す (純関数・冪等)。"""
    out = list(have)
    for u in picked:
        if u and u not in out and len(out) < max_urls:
            out.append(u)
    return out


# ── I/O ────────────────────────────────────────────────────────────
def load_cache(path=CACHE_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:                                          # noqa: BLE001
        return {}


def save_cache(cache, path=CACHE_PATH):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception:                                          # noqa: BLE001
        pass


def _new_driver():
    """メルカリ用の headless Chrome。PSA 側と同じ作り (ログインしない)。"""
    import tempfile
    import undetected_chromedriver as uc
    import mercari_psa_resource as mp
    mp._quiet_chromedriver()
    o = uc.ChromeOptions()
    o.add_argument("--headless=new")
    o.add_argument("--no-sandbox")
    o.add_argument("--lang=ja-JP")
    o.add_argument("--window-size=1280,1400")
    o.add_argument("--user-data-dir=" + tempfile.mkdtemp(prefix="ut_hoju_"))
    maj = mp._chrome_major()
    d = uc.Chrome(options=o, version_main=maj) if maj else uc.Chrome(options=o)
    d.set_page_load_timeout(50)
    return d


def _cache_path(sold_out):
    return RESTOCK_CACHE_PATH if sold_out else CACHE_PATH


def search(limit=None, sold_out=False):
    """候補を集めてキャッシュに貯める。スプシには書かない (書くのは目視の後)。"""
    import datetime
    import mercari_psa_resource as mp
    import sheet_io

    today = datetime.date.today().isoformat()
    targets = select_targets(sheet_io._product_ws().get_all_values(), sold_out=sold_out)
    targets = [t for t in targets if t["keyword"] and t["size"] and t["size"] != "KIDS"]
    if limit:
        targets = targets[:limit]
    what = "売り切れて再仕入れしたい" if sold_out else "補URLが足りない"
    print(f"▶ {what} UT: {len(targets)}件 を探します")
    if not targets:
        return 0
    cache = load_cache(_cache_path(sold_out))
    drv = _new_driver()
    found = 0
    try:
        for n, t in enumerate(targets, 1):
            url = SEARCH_URL + urllib.parse.quote(t["keyword"])
            try:
                drv.get(url)
                time.sleep(8)
                items = mp.parse_mercari_items(drv.page_source)
            except Exception as e:                             # noqa: BLE001
                print(f"  [{n}/{len(targets)}] {t['itemID']} 取得できず ({type(e).__name__})")
                continue
            same = [it for it in items
                    if size_matches(t["size"], jp_size_of(it.get("name")))]
            cands = []
            for it in same[:8]:
                href = it.get("url") or it.get("href") or ""
                if not href or href in t["have"]:
                    continue
                try:
                    ok, ship, rev = mp._detail_supply_check(drv, href,
                                                            min_reviews=MIN_REVIEWS)
                    cond, _ = mp._parse_cond_ship(drv.page_source)
                except Exception:                              # noqa: BLE001
                    continue
                if usable_candidate(cond, ship, rev, mp._is_shops_url(href)):
                    cands.append({"channel": "mercari", "url": href,
                                  "price": it.get("price"), "name": it.get("name")})
            cache[t["itemID"]] = {"date": today, "size": t["size"],
                                  "keyword": t["keyword"], "candidates": cands}
            found += len(cands)
            print(f"  [{n}/{len(targets)}] {t['itemID']} {t['size']} "
                  f"→ 拾えた{len(items)} / サイズ一致{len(same)} / 使える{len(cands)}")
            if n % 5 == 0:
                save_cache(cache, _cache_path(sold_out))
    finally:
        try:
            drv.quit()
        except Exception:                                      # noqa: BLE001
            pass
    save_cache(cache)
    print(f"\n✅ 候補 {found}本 をキャッシュに貯めました → 目視は `confirm`")
    return found


def confirm(dry_run=False):
    """当日キャッシュの候補を目視で選び、補URL(AC-AG) に **既存を残して**書く。"""
    import datetime
    import psa_resource_confirm as prc
    import sheet_io

    today = datetime.date.today().isoformat()
    vals = sheet_io._product_ws().get_all_values()
    targets = {t["itemID"]: t for t in select_targets(vals)}
    cache = load_cache()

    items, back = [], []
    for iid, c in cache.items():
        if c.get("date") != today or not c.get("candidates"):
            continue
        t = targets.get(iid)
        if not t:
            continue                    # 補URLが埋まった / 売れた = もう対象でない
        items.append({"idx": len(items), "title": t["title"], "card_no": t["size"],
                      "ebay_url": f"https://www.ebay.com/itm/{iid}",
                      "ref_image": prc.ebay_listing_image(iid) or "",
                      "candidates": c["candidates"]})
        back.append(t)
    print(f"▶ 目視できる UT: {len(items)}件")
    if dry_run or not items:
        return 0
    res = prc.restock_confirm(items)
    if res is None:
        print("⚠ 目視が終わらなかったので、書き込みはしていません")
        return 0
    row_to_urls = {}
    for c in res.get("confirmed", []):
        t = back[c["idx"]]
        row_to_urls[t["row"]] = merge_aux(t["have"], c.get("urls") or [])
    if not row_to_urls:
        print("選ばれた候補はありませんでした")
        return 0
    n = sheet_io.write_aux_urls(row_to_urls)
    print(f"✅ 補URL を {n}行 に書きました (既存はそのまま・空き枠にだけ追加)")
    return n


def restock_confirm(dry_run=False):
    """売り切れ行の候補を目視で選び、**数量を戻す** (仕入元URL/売切解除/価格 seed)。

    ★実機で確認したとおり、売り切れの Tシャツも eBay 上は Active・数量0 のまま。
      PSA と同じで **数量を戻すだけ**でよい (新規出品ではない)。
      eBay に数量を送るのは既存の RESTOCK と同じ口 (ここではシートを整えるまで)。
    """
    import datetime
    import psa_resource_confirm as prc
    import sheet_io

    today = datetime.date.today().isoformat()
    vals = sheet_io._product_ws().get_all_values()
    targets = {t["itemID"]: t for t in select_targets(vals, sold_out=True)}
    cache = load_cache(RESTOCK_CACHE_PATH)

    items, back = [], []
    for iid, c in cache.items():
        if c.get("date") != today or not c.get("candidates"):
            continue
        t = targets.get(iid)
        if not t:
            continue                    # 売れた印が消えた = もう対象でない
        items.append({"idx": len(items), "title": t["title"], "card_no": t["size"],
                      "ebay_url": f"https://www.ebay.com/itm/{iid}",
                      "ref_image": prc.ebay_listing_image(iid) or "",
                      "candidates": c["candidates"]})
        back.append(t)
    print(f"▶ 目視できる 売り切れ UT: {len(items)}件")
    if dry_run or not items:
        return 0
    res = prc.restock_confirm(items)
    if res is None:
        print("⚠ 目視が終わらなかったので、書き込みはしていません")
        return 0
    itemid_to_row, itemid_to_url, itemid_to_cost = {}, {}, {}
    for c in res.get("confirmed", []):
        t = back[c["idx"]]
        urls = [u for u in (c.get("urls") or []) if u]
        if not urls:
            continue
        itemid_to_row[t["itemID"]] = t["row"]
        itemid_to_url[t["itemID"]] = urls[0]        # 先頭 = 主の仕入元
        price = _price_of(cache.get(t["itemID"]), urls[0])
        if price:
            itemid_to_cost[t["itemID"]] = price
    if not itemid_to_row:
        print("選ばれた候補はありませんでした")
        return 0
    n = sheet_io.restock_reactivate_master(itemid_to_row, itemid_to_url, itemid_to_cost)
    print(f"✅ {n}行 を再仕入れできる状態にしました "
          f"(仕入元URL更新 + 売り切れ解除 + 仕入値 seed)")
    print("   → eBay の数量を戻すのは RESTOCK と同じ口です")
    return n


def _price_of(cache_entry, url):
    """選ばれた候補の値段 (純関数寄り)。分からなければ None。"""
    for c in ((cache_entry or {}).get("candidates") or []):
        if c.get("url") == url:
            return c.get("price")
    return None


def main():
    args = sys.argv[1:]
    limit = None
    for a in args:
        if a.startswith("--limit="):
            limit = int(a.split("=", 1)[1])
    dry = "--dry-run" in args
    if "restock-search" in args:
        search(limit=limit, sold_out=True)
    elif "restock-confirm" in args:
        restock_confirm(dry_run=dry)
    elif "search" in args:
        search(limit=limit)
    elif "confirm" in args:
        confirm(dry_run=dry)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()


def count_workload(today=None):
    """『押したら何件できるか』を **検索なし** で数える (パネルのラベル用)。

    ★ここでメルカリを叩かない。表示のための取得で時間を使わない (PSA 側と同じ設計)。
    戻り: {"search", "confirm", "restock_search", "restock_confirm", "error"}
    """
    import datetime
    out = {"search": 0, "confirm": 0, "restock_search": 0, "restock_confirm": 0,
           "error": ""}
    try:
        import sheet_io
        today = (today or datetime.date.today()).isoformat()
        vals = sheet_io._product_ws().get_all_values()
        for key, sold, path in (("", False, CACHE_PATH),
                                ("restock_", True, RESTOCK_CACHE_PATH)):
            targets = select_targets(vals, sold_out=sold)
            out[key + "search"] = sum(1 for t in targets
                                      if t["keyword"] and t["size"] and t["size"] != "KIDS")
            ids = {t["itemID"] for t in targets}
            cache = load_cache(path)
            out[key + "confirm"] = sum(1 for iid, c in cache.items()
                                       if iid in ids and c.get("date") == today
                                       and c.get("candidates"))
    except Exception as e:                                     # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"[:60]
    return out
