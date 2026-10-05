#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出品した分だけ棚を空ける — 落とす出品を選んで取り下げる (2026-08-26)。

なぜ必要か:
    eBay の出品リミットは **金額** ($1M)。件数は半分以上あまっており、詰まっているのは金額だけ。
    出品を続ける限り棚は埋まり続けるので、**出した分より少し多く落とす**運用にしないと
    出品が止まる。落とす相手は「稼いでいないもの」から選ぶ。

決めたこと (2026-08-26 ユーザー確定):
    - **カテゴリを跨いで横並び**で選ぶ。売れないカテゴリの中で最適化しても、
      売れるカテゴリの1件には及ばない (Gemini 指摘)。棚割は結果として動いてよい。
    - 落とす額は **その日に出品した額の 1.3倍**。毎日少しずつ棚を空け、
      空いた分を成績の良いカテゴリに回す。

落とす順 (上から埋めて、目標額に達したら止める):
    ① 仕入元が死んでいる   … 買えないので稼ぎようがない。**全カテゴリ**。空く額の大きい順
    ② 出品30日超・未販売   … **TCG と G-SHOCK だけ**。売れない作品から
                             (ガンダム/ドラゴンボール → ワンピース → G-SHOCK → ポケモン)
                             → 同じ作品ならウォッチ・表示の少ない順

    ★閾値は設けない (2026-08-26 ユーザー確定)。「表示◯回以上なら」という線は
      カテゴリごとに桁が違って必ずどちらかを取りこぼすので、順位で決める。
    ★空く額は **ミラー込み** で数える。US価格だけ見ると効き目を読み違える
      (実測: ある層は US $63,808 に対し棚は $272,890 空く)。

触らない:
    ・出品30日未満 (まだ判定できない)
    ・売れた実績あり
    ・TCG / G-SHOCK 以外で仕入元が活きているもの (稼いでいるカテゴリを減らさない)
    ・US 以外 (UK/AU/CA は eBaymag のミラー。親を落とせば消える)

使い方:
    python shelf_evict.py                    # 候補を出すだけ
    python shelf_evict.py --end              # eBay に End を送る
    python shelf_evict.py --amount 20000     # 目標額を直接指定する
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime
import glob
import io
import os
import json
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cull_end as CE          # noqa: E402
import listing_funnel as LF    # noqa: E402

# 出品額に対して落とす倍率。1.0 = 出した分だけ入れ替える (棚は一定)。
# ★1.3 (棚を空ける) から 1.0 に戻した (2026-08-26 ユーザー確定)。空きが要らない状況で
#   余計に落とすと、並べていれば売れたかもしれないものを捨てることになる。
#   月末にリミットが迫った時など、空けたい時だけ --ratio を上げる。
RATIO = 1.0
REPORT_GLOB = r"C:\dev\iMak_data\seller_hub\reports\**\eBay-all-active-listings-report-*.csv"
CSV_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "csv_output"))

TIER_OOS, TIER_STALE = 1, 2
TIER_NAME = {TIER_OOS: "① 買えない & 需要ゼロ",
             TIER_STALE: "② 30日超・未販売 (全商材・棚②の表で取下げ / ウォッチ0・200日超 → 売れない作品 → ウォッチ少ない順)"}
# 出品からこれ未満は「まだ判定できない」ので触らない。
MIN_AGE_DAYS = 30
# ★②(仕入元が活きている分)を落とすカテゴリ。
#   2026-09-02 に **G-shock を外した**。生存分析 (売れていない在庫も母数に入れる) の結果:
#     TCG      : 30日超は 239件中2件 (0.84%) しか売れない。売れた実績の最長は49日。
#                ウォッチ/クリック/表示のどれで切っても 30日超は全区分0% (261件/761件で確認)。
#                = 4方向から同じ答え。**30日を過ぎたTCGは売れない**
#     G-shock  : 中央値284日で売れる。180日超でも0.87%、270日超で1.32% 売れている。
#                「30日超・未販売」で落とすと、まだ売れる時期の在庫を捨てる。**対象外にする**
#   他カテゴリ (Tシャツ/モンベル/フィギュア/バッグ) は分母20〜70件で売却率が0〜8%を
#   行き来し、線を引けるデータが無い → 触らない (2026-09-02 ユーザー確定)。
#   ①(仕入元が死んでいる)は **全カテゴリ**が対象。買えないものを残す意味は無い。
# カテゴリごとの「これを過ぎたら売れない」日数。**カテゴリで全く違う**ので一律にしない。
#   TCG     30日 : 30日超は239件中2件(0.84%)。売れた実績の最長49日。
#                  ウォッチ/クリック/表示のどれで切っても30日超は全区分0%
#                  (ウォッチ261件・クリック761件で確認) = 4方向から同じ答え
#   G-shock 365日: 中央値284日で売れる。180日超0.87% / 270日超1.32% と**まだ売れる**。
#                  365日超だけ96件で0件。在庫も180日未満(151件)と365日超(75件)に
#                  分かれていて中間が空なので、線を引く場所を迷わない
#   他カテゴリ    : 分母20〜70件で売却率が0〜8%を行き来し、線を引けるデータが無い。
#                  データが貯まるまで **触らない** (2026-09-02 ユーザー確定)
#   ★見直し前提: `python shelf_evict_review.py` で年齢別の売却率を出し直せる。
#     四半期ごとに見て、数字が変わっていたらここを直す。
# ★2026-09-06 ユーザー確定「出品してから30日で取り下げる」。
#   当店は棚卸をしてこなかったため、月間回転率が 0.8% (月8件 / 出品1,022件) まで
#   落ちている。表示やCTRが低いのは **商品ではなく店の順位** が下がった結果の
#   可能性が高く、その内部データから閾値を決めると悪循環を固定してしまう。
#   よって「何日なら売れるか」を自店データで決めるのをやめ、**30日で回す**に統一する。
# ★2026-09-15 ユーザー「Tシャツは自動出品がほぼ完了したので、対象外から外してもいいかなと」→「そだね」:
#   Tシャツは **仕入元がメルカリ・ラクマ (1点物) の出品だけ** 30日で回す (category_for が "Tシャツ" を返す)。
#   実測 (9/14 ファネル・在庫あり): メルカリ仕入 23件 中央値204日 売れ0 / ラクマ仕入 12件 150日 売れ0。
#   公式仕入のバリエーション出品 (64件・売れ7) は取り下げると戻せないので今までどおり落とさない。
#   **有在庫は全カテゴリ落とさない** (現物がある。動かすなら値下げ・オファー)。
STALE_MAX_AGE = {"TCG": 30, "G-shock": 30, "Tシャツ": 30}
STALE_CATEGORIES = tuple(STALE_MAX_AGE)
# ★2026-10-05 ユーザー「全リスティングを対象にしないと、ずっと残ったままになるでしょ」「G-SHOCK・Tシャツに関わらず、
#   補があるかどうかにして、モンベルとかポーターとかもあるわけだし」:
#   ② は **全商材** が対象 (分かれ目は商材ではなく補があるかどうか・shelf_psa_rules の表)。外すのはこれだけ:
#   ・公式仕入 (Tシャツ(公式等) / 公式サイト仕入): 「公式は値下がりがあるし、売り切れで自然淘汰されるから、除外して」
#   ・有在庫 / 有在庫？: 「有在庫も除外」
#   ・カテゴリが分からない (None): 判断できない物は落とさない
SHELF_EXCLUDED = ("Tシャツ(公式等)", "公式サイト仕入", "有在庫", "有在庫？", None)

ONHAND = "有在庫"
# ★2026-09-15 ユーザー「じゃ、落とすグループに有在庫？にしておいて、後で調べる」:
#   在庫ありなのに **どのシートにも載っていない** 出品 (商品管理シート / 公式仕入 / 有在庫 のどれにも無い)。
#   無在庫なら監視くんが仕入元を見ていない (売り切れても取り下がらない)。調べるまで落とさない。
ONHAND_UNKNOWN = "有在庫？"
KNOWN_CACHE = r"C:/dev/iMak_data/hq/shelf_known_ids_cache.json"
ONHAND_SHEET_ID = "1zbzr1fifHMAcgJ5n_9CcMXzJASxcvk3DutgOQfNElNA"   # 有在庫シート (シート2: B列 出品番号)
ONHAND_GID = 2025152218
# ★2026-09-15 ユーザー「(有在庫のファイルの) ここのどこかにないかな」→ 「①有在庫の仕入れ表」タブ (2行目が見出し、
#   E列「カスタムラベル（管理番号）」= 出品番号)。シート2 に無い Thunder Pass 赤/茶 (357100759244 / 357100717683) が載っていた
ONHAND_PURCHASE_GID = 1530110022
ONHAND_PURCHASE_COL = 4
ONHAND_CACHE = r"C:/dev/iMak_data/hq/shelf_onhand_cache.json"
ONE_OFF_SUPPLY = re.compile(r"jp\.mercari\.com|fril\.jp", re.I)       # メルカリ・ラクマ = 1点物の仕入元


# ★2026-09-27 (残務 №289): Montbell / graniph / UNIQLO の公式サイト仕入は SKU が '… official website'。
#   商品管理シートに行が無いのが正常なので「有在庫？ (どのシートにも無い)」に出さない (表示のノイズだけだった)。
OFFICIAL_SKU = re.compile(r"official\s*website", re.I)
OFFICIAL = "公式サイト仕入"


def is_official_sku(sku):
    """SKU が公式サイト仕入の印を持つか (純関数)。"""
    return bool(OFFICIAL_SKU.search(sku or ""))


def category_for(item_id, sheet_category, supply_url="", onhand=(), known=None, sku=""):
    """棚が使うカテゴリ (純関数, test 可)。

    有在庫 → "有在庫" (どの期限にも入らない = 落とさない) /
    シートのカテゴリが Tシャツ で仕入元がメルカリ・ラクマ → "Tシャツ" (30日で回す) /
    それ以外の Tシャツ (公式仕入など) → "Tシャツ(公式等)" (落とさない) / 他はシートのカテゴリのまま。
    """
    iid = str(item_id or "").strip()
    if onhand and iid in onhand:
        return ONHAND
    if known is not None and iid not in known:
        if is_official_sku(sku):
            return OFFICIAL                # 公式サイト仕入 = シートに行が無いのが正常 (落とさない)
        return ONHAND_UNKNOWN              # どのシートにも無い = 調べるまで落とさない
    if (sheet_category or "").strip() == "Tシャツ":
        return "Tシャツ" if ONE_OFF_SUPPLY.search(supply_url or "") else "Tシャツ(公式等)"
    return sheet_category or None


def onhand_ids_from(onhand_rows, product_rows_list, purchase_rows=None):
    """有在庫の出品番号 (純関数, test 可)。

    有在庫シート (1〜3行目は見出し、B列 出品番号) + 商品管理シートで **出品番号があるのに仕入元URL (A列) が空**
    の行 (= 有在庫。巡回対象外で正常 / onhand_stock_rows_have_no_supply_url)。
    """
    out = set()
    for r in (purchase_rows or [])[2:]:                 # ①有在庫の仕入れ表 (E列 = 出品番号)
        iid = (r[ONHAND_PURCHASE_COL] if len(r) > ONHAND_PURCHASE_COL else "").strip()
        if iid.isdigit() and len(iid) == 12:
            out.add(iid)
    for r in (onhand_rows or [])[3:]:
        iid = (r[1] if len(r) > 1 else "").strip()
        if iid.isdigit():
            out.add(iid)
    for rows in product_rows_list or []:
        for r in rows[1:]:
            iid = (r[1] if len(r) > 1 else "").strip()
            if iid.isdigit() and not ((r[0] if r else "") or "").strip():
                out.add(iid)
    return out


def known_ids_from(product_rows_list, official_item_ids=(), onhand=()):
    """出品が載っている台帳の出品番号 (純関数, test 可): 商品管理シート B列 + 公式仕入 + 有在庫。"""
    out = set(str(i) for i in (official_item_ids or ())) | set(onhand or ())
    for rows in product_rows_list or []:
        for r in rows[1:]:
            iid = (r[1] if len(r) > 1 else "").strip()
            if iid.isdigit():
                out.add(iid)
    return out


def load_known_ids(gc=None, product_rows_list=None, onhand=None):
    """台帳に載っている出品番号 (I/O)。読めなければ前回の写し。写しも無ければ None (= 有在庫？ の判定をしない)。"""
    try:
        if gc is None:
            import gspread
            from google.oauth2.service_account import Credentials
            gc = gspread.authorize(Credentials.from_service_account_file(
                LF.CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"]))
        if product_rows_list is None:
            product_rows_list = [gc.open_by_key(sid).get_worksheet_by_id(LF.SHEET_GID).get_all_values()
                                 for sid in LF.SHEET_IDS]
        sys.path.insert(0, r"C:\dev\iMak\iMakMercari")
        from ut_catalog_values import load_official_identities
        official = {v.get("item_id") for v in (load_official_identities() or {}).values() if v.get("item_id")}
        if not official:
            raise ValueError("公式仕入の出品シートが0件")
        if onhand is None:
            onhand = load_onhand_ids(gc, product_rows_list) or set()
        ids = known_ids_from(product_rows_list, official, onhand)
        if ids:
            os.makedirs(os.path.dirname(KNOWN_CACHE), exist_ok=True)
            with open(KNOWN_CACHE, "w", encoding="utf-8") as f:
                json.dump(sorted(ids), f)
            return ids
    except Exception as e:                                         # noqa: BLE001
        print(f"  ⚠ 台帳の出品番号を読めず、前回の写しを使います ({type(e).__name__})")
    try:
        with open(KNOWN_CACHE, encoding="utf-8") as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return None


def load_onhand_ids(gc=None, product_rows_list=None):
    """有在庫の出品番号 (I/O)。シートを読めなければ前回の写し。写しも無ければ None。"""
    try:
        if gc is None:
            import gspread
            from google.oauth2.service_account import Credentials
            gc = gspread.authorize(Credentials.from_service_account_file(
                LF.CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"]))
        if product_rows_list is None:
            product_rows_list = [gc.open_by_key(sid).get_worksheet_by_id(LF.SHEET_GID).get_all_values()
                                 for sid in LF.SHEET_IDS]
        book = gc.open_by_key(ONHAND_SHEET_ID)
        oh = book.get_worksheet_by_id(ONHAND_GID).get_all_values()
        buy = book.get_worksheet_by_id(ONHAND_PURCHASE_GID).get_all_values()
        ids = onhand_ids_from(oh, product_rows_list, buy)
        if ids:
            os.makedirs(os.path.dirname(ONHAND_CACHE), exist_ok=True)
            with open(ONHAND_CACHE, "w", encoding="utf-8") as f:
                json.dump(sorted(ids), f)
            return ids
    except Exception as e:                                         # noqa: BLE001
        print(f"  ⚠ 有在庫の一覧をシートから読めず、前回の写しを使います ({type(e).__name__})")
    try:
        with open(ONHAND_CACHE, encoding="utf-8") as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return None


def _f(v):
    try:
        return float(str(v or 0).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return 0.0


# ★2026-09-07 ユーザー確定: ② は **売れない作品から先に落とす**。
#   ポケモンを最後まで残す (= 落とすのは一番最後)。
#   根拠 (2026-09-07 実測。注文レポート 8/07〜9/05 と live 出品数):
#     ポケモン      273件 → 17件売れた (6.2%/月)  ← 唯一 売れている
#     G-SHOCK      217件 →  3件 (1.4%)
#     ワンピース      211件 →  2件 (0.9%)
#     ガンダム        15件 →  0件 / ドラゴンボール 10件 → 0件 (母数が小さいので断定はしない)
#   ★見直し前提: 数字が変われば順番も変える。同じ集計は
#     `ebay-all-orders-report` の Item Title を作品で数えれば出る。
FRANCHISE_ORDER = (
    (("gundam", "dragon ball", "dragonball"), 0),   # 実績0 → 先に落とす
    (("one piece",), 1),
    (("g-shock", "gshock", "g shock"), 2),
    (("pokemon",), 3),                              # 唯一売れている → 最後まで残す
)
FRANCHISE_OTHER = 1                                  # 判定できないものは真ん中 (極端に扱わない)


def franchise_rank(title):
    """② の落とす順で使う作品の順位。小さいほど先に落ちる (純関数, test可)。"""
    t = (title or "").lower()
    for keys, rank in FRANCHISE_ORDER:
        if any(k in t for k in keys):
            return rank
    return FRANCHISE_OTHER


def tier_of(row, min_age=MIN_AGE_DAYS, category=None, stale_cats=None,
            max_age=None, restock_pending=None, no_demand=None):
    """その出品を落とす順の何番に置くか。触らないものは None (純関数, test可)。

    ★2026-08-26 ユーザー確定:
      ・**閾値を設けない**。「表示◯回以上なら」の線はカテゴリごとに桁が違って必ず取りこぼす。
      ・**仕入元が死んでいる分は全カテゴリ**。買えないものを残す意味は無い。
      ★2026-09-06 更新: 仕入元が活きている分は **TCG と G-SHOCK** (どちらも30日)。
        2026-09-02 に G-shock を外したが、9/06 の「30日で回す」で戻した。
        落とす順は **売れない作品から → ウォッチ少ない順** (pick の docstring 参照)。
    """
    if restock_pending and str(row.get("item_id") or row.get("itemID") or "").strip() \
            in restock_pending:
        # ★2026-09-03: 再仕入れが「仕入元を見つけた、これから数量を戻す」と決めた出品。
        #   ①(数量0)は需要を見ないので、放っておくと **戻す直前の出品を落とす**。
        #   実測: 戻す予定12件のうち8件が①の対象に入っていた。
        #   取下げ(CULL)は「生涯ずっと需要ゼロ」に限るので、こちらとは元々重ならない。
        return None
    if _f(row.get("qty")) == 0:
        # ★2026-09-03: ①は「数量0」だけで拾っていたので、**需要があった出品まで落としていた**。
        #   実測: ①の候補259件のうち 88件が再仕入れに回すべきもの (売れた/ウォッチ/表示あり)。
        #   数量0で落として良いのは、取下げ(CULL)と同じ **生涯ずっと需要ゼロ** の分だけ。
        #   no_demand が渡されない / その集合に無い = 判定できない → **落とさない** (fail-closed)。
        if no_demand is None:
            return TIER_OOS               # 呼び側が判定材料を持たない時は従来どおり
        iid = str(row.get("item_id") or row.get("itemID") or "").strip()
        return TIER_OOS if iid in no_demand else None
    if _f(row.get("sold_qty")) + _f(row.get("sales90")) > 0:
        return None                       # 売れた実績あり
    if category in SHELF_EXCLUDED:
        return None                       # 公式仕入・有在庫・カテゴリ不明は落とさない (2026-10-05)
    if stale_cats and category not in stale_cats:
        return None                       # 呼び手が絞った時だけ
    # ★2026-09-02: 一律 min_age ではなく **カテゴリごとの日数**で判定する。
    #   TCG を落とす日数(30)で G-shock を落とすと、まだ売れる時期の在庫を捨てる
    #   (G-shock は中央値284日で売れる)。
    limit = (max_age or STALE_MAX_AGE).get(category, min_age)
    if _f(row.get("age_days")) <= limit:
        return None                       # その日数まではまだ売れる
    return TIER_STALE


DESK = r"C:\Users\imax2\OneDrive\デスクトップ"
PROMO_GLOB = r"C:/dev/iMak_data/seller_hub/reports/**/*promoted*.csv"


def restock_pending_ids():
    """再仕入れが「これから数量を戻す」と決めている itemID (I/O)。読めなければ空集合。

    ★2026-09-03: ①(数量0)は需要を見ないので、**戻す直前の出品を落としていた**
      (実測: 戻す予定12件のうち8件が①の対象)。ここで除く。
      読めない時は空集合 = 従来どおりの動き (棚を止めない)。
    """
    try:
        sys.path.insert(0, os.path.normpath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMakeBayAPI")))
        from sheet_io import read_tab
        import psa_restock_writeback as W
        rows = read_tab("RESTOCK確定")
        if not rows or len(rows) < 2:
            return set()
        h = rows[0]
        ii = h.index("itemID") if "itemID" in h else 0
        si = h.index("RESTOCK状態") if "RESTOCK状態" in h else None
        out = set()
        for r in rows[1:]:
            iid = (r[ii] if ii < len(r) else "").strip()
            if not iid:
                continue
            st = (r[si] if (si is not None and si < len(r)) else "") or ""
            if W.ST_DONE in st or W.ST_ENDED in st:
                continue          # 既に戻した / 出品が終了している = 守る必要が無い
            out.add(iid)
        return out
    except Exception as e:                                     # noqa: BLE001
        print(f"  ⚠ 再仕入れ予定の読み取りskip ({type(e).__name__}) → 従来どおり選びます")
        return set()


def no_demand_ids(rows):
    """「生涯ずっと表示もクリックも販売もゼロ」= 落として損が無い itemID (純関数)。

    取下げ(CULL)と同じ判定 (`listing_funnel.classify` の cull)。①はこの集合に限る。
    ★2026-09-03: ①は数量0だけで拾っていたため、**需要があった88件**まで対象にしていた。
      それらは再仕入れに回すべきもので、落とすと目視で確認した仕事ごと捨てることになる。
    """
    def _n(v):
        try:
            return float(str(v or 0).replace(",", ""))
        except (TypeError, ValueError):
            return 0.0

    out = set()
    for r in rows:
        if _n(r.get("qty")) != 0:
            continue
        demand = _n(r.get("sold_qty")) + _n(r.get("watch")) + _n(r.get("sales90"))
        owner = LF.restock_owner(r)
        if not owner:
            out.add(str(r.get("item_id") or "").strip())      # 戻す口が無い = 畳む
            continue
        if owner == "PSA10":
            worth = demand > 0 or _n(r.get("impr")) >= 1
        else:
            worth = demand > 0 or _n(r.get("impr_total")) > 0
        if not worth:
            out.add(str(r.get("item_id") or "").strip())
    out.discard("")
    return out


def load_clicks(pattern=PROMO_GLOB):
    """itemID → (クリック数, 広告表示数)。最新の広告レポートから (無ければ空)。

    ★2026-09-02 ユーザー指示: 候補CSVに **価格・経過日数・表示・ウォッチ** を載せる。
      「CSVだと経過日数やVIEW/WATCHが分からないから判断できない」ため。
      クリックはファネルに無く広告レポートにしかないので、ここで読む。
    """
    import glob as _g
    files = sorted(_g.glob(pattern, recursive=True), key=os.path.getmtime)
    if not files:
        return {}
    out = {}
    try:
        rows = list(csv.reader(io.open(files[-1], encoding="utf-8-sig", errors="replace")))
    except OSError:
        return {}
    hdr = next((i for i, r in enumerate(rows[:8])
                if any((c or "").strip() == "Item ID" for c in r)), None)
    if hdr is None:
        return {}
    h = [(c or "").strip() for c in rows[hdr]]
    need = ("Item ID", "Total Promoted Listings Clicks",
            "Promoted Listings Impressions (via eBay Placements)")
    if any(n not in h for n in need):
        return {}
    ii, ci, mi = (h.index(n) for n in need)
    for r in rows[hdr + 1:]:
        if len(r) <= max(ii, ci, mi):
            continue
        iid = (r[ii] or "").strip()
        if not iid:
            continue
        try:
            out[iid] = (float((r[ci] or "0").replace(",", "")),
                        float((r[mi] or "0").replace(",", "")))
        except ValueError:
            pass
    return out


CAND_HEADER = ["理由", "itemID", "タイトル", "カテゴリ", "価格$", "経過日数",
               "表示", "クリック", "ウォッチ", "空く枠$", "eBay"]


def candidate_rows(picked, shelf_of, cat_of=None, clicks=None):
    """候補 → CSV の行 (純関数)。人が見て判断できる材料を全部載せる。"""
    clicks = clicks or {}
    out = []
    for t, r in picked:
        iid = r.get("item_id", "")
        clk, pimpr = clicks.get(iid, ("", ""))
        out.append([TIER_NAME.get(t, t), iid, (r.get("title") or "")[:70],
                    (cat_of(r) if cat_of else ""), round(_f(r.get("price")), 2),
                    int(_f(r.get("age_days"))),
                    int(_f(r.get("impr_total")) or (pimpr or 0)),
                    ("" if clk == "" else int(clk)), int(_f(r.get("watch"))),
                    round(shelf_of(r)), r.get("ebay_url", "")])
    return out


def write_candidates(picked, shelf_of, cat_of=None, path=None, clicks=None):
    """候補CSVを書く。書けなくても走行は止めない (おまけ)。戻り: 書けたパス or 空文字。"""
    path = path or os.path.join(DESK, "棚END候補_%s.csv"
                                % datetime.date.today().strftime("%Y%m%d"))
    try:
        with io.open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(CAND_HEADER)
            for row in candidate_rows(picked, shelf_of, cat_of, clicks):
                w.writerow(row)
        return path
    except OSError as e:                                       # noqa: BLE001
        print("  ⚠ 候補CSVを書けません (%s)。画面の一覧で判断してください" % type(e).__name__)
        return ""


# ★2026-09-15 ユーザー「WATCHが0で200日以上なら、カテゴリ関係なく、不良在庫＝陳列居座り＝SEOロスじゃないのかな」:
#   ② の中で **作品より先に** 落とす。実測 (9/15 ファネル・US 200日超): ウォッチ0 63件 → 90日で売れ1 (対象外の UNIQLO) /
#   ウォッチ1以上 50件 → 売れ2。在庫ありで落とす候補に入っているウォッチ0・200日超は50件 (G-SHOCK 41 / ワンピース他 8 / DB 1)。
#   どれも既に30日超の候補なので、変わるのは **落ちる順番だけ** (有在庫・売れた物・対象外カテゴリは今までどおり残す)。
DEAD_SHELF_AGE = 200


def is_dead_shelf(row):
    """ウォッチ0 で出品200日超 = 居座り (純関数, test可)。"""
    return _f(row.get("watch")) == 0 and _f(row.get("age_days")) > DEAD_SHELF_AGE


# ★2026-10-01 ユーザー「落とす前に、価格改定が何回行われたかを判定基準にできない？」「そそ、値下げ履歴ね」:
#   ②(仕入元は活きている・30日超・未販売) は、**一度も値下げしていない出品は落とさない**。
#   値下げ候補に回し、値下げしても売れなかった物だけ落とす。表示やウォッチの線ではない (2026-08-26 の決定と両立)。
#   値下げの履歴はリバイスくんの台帳 (毎日更新)。台帳が読めない時は判断できないので ② は落とさない (壊す側に倒さない)。
PRICE_CHANGES_PATH = r"C:/dev/iMak_data/revise/price_change_counts.json"
# ★2026-10-01 リバイスくん回答: 値段は仕入値に合わせて毎日上下するので、「下げた回数」は 1,636件中1,510件が1以上
#   (= 回数では見分けがつかない)。**出品した時の値段から差し引きでいくら下がったか** で見る。
# ★2026-10-01 ユーザー「％だと、価格によってムラがでるね」→ 価格帯ごとの **金額** で決める。
#   表は設定ファイル (コードに触らずに変えられる)。無い時は下の既定値。
SETTINGS_PATH = r"C:/dev/iMak_data/hq/shelf_evict_settings.json"
# まだ値下げしていないので落とさなかった ② (= 値下げ候補)。★2026-10-03: 定義が無く NameError で
#   一度も書けていなかった (10/1 から 231件が候補に回らず)
PRICE_DOWN_FIRST_PATH = r"C:/dev/iMak_data/hq/price_down_before_evict.json"
DEFAULT_PRICE_DOWN_BANDS = [[50, 5], [200, 15], [500, 30], [None, 50]]   # [出品時の値段の上限($), 下がっていれば値下げ済み($)]


def load_price_down_bands(path=SETTINGS_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            bands = (json.load(f) or {}).get("price_down_bands")
        if bands:
            return bands
    except Exception:
        pass
    return DEFAULT_PRICE_DOWN_BANDS


def down_needed(first_price, bands):
    """出品時の値段 → 「値下げ済み」とみなす下げ幅 ($) (純関数)。"""
    for upper, amount in bands:
        if upper is None or first_price < upper:
            return amount
    return bands[-1][1]


def load_price_downs(path=PRICE_CHANGES_PATH):
    """itemID → (出品時の値段, 今の値段)。台帳が読めない時は None (= 判断できない)。"""
    try:
        with open(path, encoding="utf-8") as f:
            items = (json.load(f) or {}).get("items") or {}
        out = {}
        for k, v in items.items():
            try:
                out[str(k)] = (float((v or {}).get("first_price")), float((v or {}).get("now_price")))
            except Exception:
                out[str(k)] = None
        return out
    except Exception:
        return None


def needs_price_down_first(item_id, price_downs, bands=None):
    """② を落とす前に、まず値下げを試すべきか (純関数)。

    出品時の値段から、価格帯ごとの金額 (bands) 以上 下がっていれば False (= 値下げ済みなので落としてよい)。
    台帳が無い / その出品が載っていない / 値段が分からない時は True (= 判断できないので落とさない)。
    """
    if price_downs is None:
        return True
    fp = price_downs.get(str(item_id))
    if not fp or fp[0] is None or fp[1] is None or fp[0] <= 0:
        return True
    first, now = fp
    return (first - now) < down_needed(first, bands or DEFAULT_PRICE_DOWN_BANDS)


def pick(rows, target, shelf_of, cat_of=None, only_tier=None, restock_pending=None,
         no_demand=None, price_downs=False, held=None, psa_judge=None, decisions=None):
    """目標額に届くまで、順位の上から選ぶ。戻り: (選んだ行, 空く額) 純関数, test可。

    ① は 空く額の大きい順 (買えないので、少ない回数で目標に届くのが正しい)。

    ★2026-09-07 ユーザー確定: ② は **売れない作品から**。ポケモンは最後まで残す
      (順位は FRANCHISE_ORDER。根拠の実測もそこに書いてある)。

    ★2026-09-06 ユーザー確定: 作品が同じなら **ウォッチ少ない順 → 表示少ない順 → 金額 大きい順**。
      2026-09-02 に「アクセスは結果を変えない」として金額順にしたが、その判断は
      **回転率0.8%まで落ちた自店データ** に基づいていた。店の順位が下がっている状態では
      アクセスの少なさが商品の良し悪しを表さないため、この結論自体が信用できない。
      需要の薄いものから先に落とす、という素直な順に戻す。
      金額は3番目 = 同じくらい needs のないものが並んだ時に、少ない件数で枠を空ける。
    """
    cand = []
    _BANDS = load_price_down_bands() if price_downs is not False else None
    for r in rows:
        t = tier_of(r, category=(cat_of(r) if cat_of else None),
                    restock_pending=restock_pending, no_demand=no_demand)
        if t is None:
            continue
        # ★2026-09-02 ユーザー指示: **在庫ありの取下げはボタンを分ける**。
        #   ①(仕入元が死んでいる)は「買えないので落として損が無い」。
        #   ②(在庫はあるが期限超え)は「売れるかもしれない物を捨てる」判断で、重さが違う。
        #   混ぜて1つのボタンにすると、重い方を軽い気持ちで押すことになる。
        if only_tier is not None and t != only_tier:
            continue
        # ★2026-10-04 ユーザー確定「やってみよう」: PSA (TCG) の ② は棚②の新しい表 + 市場の門で決める
        #   (shelf_psa_rules。表の正本は管理表タブ「棚②の新ルール案 (HQ)」)。落とすのは表で「取下げ」かつ
        #   市場の門を通らなかった物だけ。補優先・残すは held へ (補優先は補URL③が先に探す)。
        #   G-SHOCK / Tシャツ は今までどおり「値下げ済みなら落とす」。
        if t == TIER_STALE and price_downs is not False and psa_judge is not None:
            # ★2026-10-05: 全商材を同じ表で (補があるかどうか)。市場の門は PSA だけ (_psa_judge の中)
            d = psa_judge(r)
            if decisions is not None:
                decisions.append(d)
            if d.get("verdict") != "取下げ":
                continue                  # 補優先・残す (内訳は decisions。値下げ候補とは別)
        # price_downs=False は「値下げ履歴の判定をしない」(ラベルの件数など表示用の呼び出し)
        elif t == TIER_STALE and price_downs is not False and needs_price_down_first(r.get("item_id"), price_downs, _BANDS):
            if held is not None:
                held.append(r)
            continue
        if t == TIER_OOS:
            rank = (0, 0, -shelf_of(r))              # ① 空く額の大きい順
        else:
            rank = (0 if is_dead_shelf(r) else 1,    # ② ウォッチ0・200日超を先に (2026-09-15)
                    franchise_rank(r.get("title")),  #    → 売れない作品から (2026-09-07)
                    _f(r.get("watch")),              #    → ウォッチ少ない順
                    _f(r.get("impr_total")),         #    → 表示少ない順
                    -shelf_of(r))                    #    → 金額 大きい順
        cand.append((t, rank, r))
    cand.sort(key=lambda x: (x[0], x[1]))
    picked, total = [], 0.0
    for t, _rank, r in cand:
        if total >= target:
            break
        picked.append((t, r))
        total += shelf_of(r)
    return picked, total


def _upload_amount_on(csv_dir, stamp):
    """その日付の入稿CSVの金額合計 (US価格)。無ければ 0。"""
    total = 0.0
    for p in glob.glob(os.path.join(csv_dir, f"*_upload_{stamp}_*.csv")):
        if p.endswith((".bak", ".json")):
            continue
        try:
            with open(p, encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    total += _f(row.get("*StartPrice") or row.get("StartPrice"))
        except OSError:
            continue
    return total


def upload_days(csv_dir=CSV_DIR):
    """入稿CSVがある日付 (YYYYMMDD) を新しい順に。純関数寄り, test可。"""
    import re as _re
    days = set()
    for p in glob.glob(os.path.join(csv_dir, "*_upload_*.csv")):
        if p.endswith((".bak", ".json")):
            continue
        m = _re.search(r"_upload_(\d{8})_", os.path.basename(p))
        if m:
            days.add(m.group(1))
    return sorted(days, reverse=True)


def listed_today_amount(csv_dir=CSV_DIR, today=None):
    """落とす目標額のもとになる出品額 (US価格)。

    ★2026-09-06 ユーザー確定「金額指定なしなら **前回の出品額ぶん**」。
      それまでは「その日の出品額」だったので、出品していない日は $0 になり
      **押しても何も落ちなかった** (実際 9/6 に押して0件)。
      出していない日でも棚は回したいので、**直近で出品した日の額**を使う。
      その日に出していればその額 = 従来と同じ動き。
    """
    today = today or datetime.date.today()
    total = _upload_amount_on(csv_dir, today.strftime("%Y%m%d"))
    if total > 0:
        return total
    for stamp in upload_days(csv_dir):
        v = _upload_amount_on(csv_dir, stamp)
        if v > 0:
            return v
    return 0.0



EVICTED_LOG = r"C:/dev/iMak_data/hq/shelf_evicted_log.json"


def evicted_today_amount(today=None, path=None):
    """今日すでに棚で落とした額 (I/O)。読めなければ 0。

    ★2026-09-03: 目標は「今日の出品額」なので、**押すたびに同じ額が落ちていた**
      (実測: 空欄で2回押して $14,939 + $15,624 = 出品額の2倍)。
      落とした分を覚えて、2回目からは残りだけにする。
    """
    import json as _j
    today = (today or datetime.date.today()).isoformat()
    try:
        with io.open(path or EVICTED_LOG, encoding="utf-8") as f:
            return _f((_j.load(f) or {}).get(today, 0))
    except Exception:                                          # noqa: BLE001
        return 0.0


# ★2026-10-05 ユーザー「一気に落とすのはアレだね」→「じゃ、50で」: ② は1日50件まで (並び順の上から)。
#   溜まっている 294件 (10/5) は約1週間で片付き、その後は1日10件前後しか増えないので実質上限なし。
#   値は設定ファイル (shelf_evict_settings.json の "daily_cap") で変えられる
DEFAULT_DAILY_CAP = 50


def daily_cap(path=SETTINGS_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            v = (json.load(f) or {}).get("daily_cap")
        return int(v) if v is not None else DEFAULT_DAILY_CAP
    except Exception:                                          # noqa: BLE001
        return DEFAULT_DAILY_CAP


def evicted_today_count(today=None, path=None):
    """今日すでに棚で落とした件数 (I/O)。読めなければ 0。"""
    import json as _j
    today = (today or datetime.date.today()).isoformat()
    try:
        with io.open(path or EVICTED_LOG, encoding="utf-8") as f:
            return int(_f((_j.load(f) or {}).get(today + "#n", 0)))
    except Exception:                                          # noqa: BLE001
        return 0


def cap_today(picked, cap, done_today):
    """今日あと何件落としてよいかで切る (純関数)。picked は並び順どおり。"""
    return picked[:max(0, cap - done_today)]


def remember_evicted(amount, today=None, path=None):
    """落とした額と件数を今日ぶんに足す。書けなくても処理は止めない。"""
    import json as _j
    path = path or EVICTED_LOG
    today = (today or datetime.date.today()).isoformat()
    try:
        try:
            with io.open(path, encoding="utf-8") as f:
                data = _j.load(f) or {}
        except Exception:                                      # noqa: BLE001
            data = {}
        data[today] = _f(data.get(today, 0)) + _f(amount)
        data[today + "#n"] = int(_f(data.get(today + "#n", 0))) + 1          # ★2026-10-05 1日50件の数え
        for old in sorted(data)[:-28]:
            data.pop(old, None)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with io.open(path, "w", encoding="utf-8") as f:
            _j.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
    except Exception:                                          # noqa: BLE001
        pass


def remaining_target(listed, evicted, ratio=RATIO):
    """今日あと いくら落としてよいか (純関数)。マイナスは0。"""
    return max(0.0, listed * ratio - evicted)

# ★落とさないカテゴリ (2026-08-28 ユーザー確定)。
#   アパレル (UNIQLO/GU) はバリエーション出品で、**公式在庫が戻れば監視くんが数量を戻す**。
#   出品が生きていれば復活できるが、**取り下げると戻せない** (出し直しになる)。
#   数量0 でも触らない。タイトルで判定するのは、台帳に行が無い出品 (実測で存在) でも
#   守れるようにするため (fail-closed = 迷ったら落とさない)。
#   ★衣類は銘柄を問わず守る。UNIQLO/GU 以外の T シャツ (例: Dragon Ball DAIMA) も
#     同じ性質 (公式在庫が戻る) なので、迷ったら落とさない側に倒す。
#     守り過ぎても候補は 200件以上 残るので、棚が空かなくなる心配はない。
PROTECTED_TITLE = re.compile(
    r"UNIQLO|GU|AIRism|Sukajan|Graphic Tee|T-?Shirt|Tee|Hoodie|Sweat", re.I)


def is_protected(title):
    """落としてはいけない出品か (純関数, test 可)。"""
    return bool(PROTECTED_TITLE.search(title or ""))


def age_days_of(start_iso, now=None):
    """出品日 ISO → 経過日数 (純関数, test 可)。読めなければ 0。"""
    import datetime as _dt
    if not start_iso:
        return 0
    try:
        t = _dt.datetime.strptime(start_iso[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return 0
    return max(0, ((now or _dt.datetime.utcnow()) - t).days)


def rows_from_live(live, done, title_key, now=None):
    """live 出品一覧 → ①(数量0)の行 (純関数, test 可)。**レポートも funnel も要らない**。

    ★2026-08-28 ユーザー指摘「手動で毎回最新をDLする方が非効率でしょ」。
      ①(数量0) は毎回取り直している live 一覧から直接わかるので、Seller Hub の
      レポート/ファネルを待つ必要がない。レポートが要るのは ②(表示回数の少ない順) の
      並び順だけで、そこは日々変わらない。
      実害 (2026-08-28): 5日前のレポートで、在庫が戻った出品を候補に挙げていた。

    棚額はミラー込み (US 価格だけ見ると効き目を読み違える)。ミラーは通貨が違うので
    USD 換算値 (`usd`) を足す。
    """
    import collections as _c
    mir = _c.defaultdict(float)
    for v in live.values():
        if (v.get("cur") or "") != "USD":
            mir[title_key(v.get("title") or "")] += float(v.get("usd") or 0)
    out = []
    for iid, v in live.items():
        if (v.get("cur") or "") != "USD" or iid in done:
            continue
        if int(v.get("avail") or 0) > 0:
            continue                      # まだ売れる = 棚を空ける対象ではない
        if is_protected(v.get("title")):
            continue                      # アパレル = 監視くんが数量を戻すので落とさない
        out.append({"item_id": iid, "title": v.get("title") or "",
                    "price": float(v.get("usd") or 0), "qty": 0,
                    "sold_qty": 0, "sales90": 0, "impr_total": 0,
                    "age_days": age_days_of(v.get("start"), now),
                    "_mirror": mir.get(title_key(v.get("title") or ""), 0.0)})
    return out


def _load_live():
    """live 一覧から ①の行 + 棚額 (I/O)。取れなければ ([], None)。"""
    import itemid_writeback_audit as A
    try:
        live = A._fetch_live(use_cache=True)
    except Exception as e:                                         # noqa: BLE001
        print(f"  ⚠ live 一覧を取れず、ファネルだけで判定します: {type(e).__name__}")
        return [], None
    rows = rows_from_live(live, CE.load_done(), LF._title_key)

    def shelf_of(row):
        return _f(row.get("price")) + _f(row.get("_mirror"))

    print(f"  live 一覧から ①(数量0) {len(rows)}件 "
          f"(レポート不要・常に最新)")
    return rows, shelf_of


CATEGORY_CACHE = r"C:/dev/iMak_data/hq/shelf_category_cache.json"


def _category_cache_load():
    """itemID→カテゴリ の前回の写し。無ければ空。"""
    try:
        import json as _j
        with io.open(CATEGORY_CACHE, encoding="utf-8") as f:
            return _j.load(f) or {}
    except Exception:                                          # noqa: BLE001
        return {}


def _category_cache_save(by_item):
    """写しを残す。書けなくても本処理は止めない。"""
    try:
        import json as _j
        os.makedirs(os.path.dirname(CATEGORY_CACHE), exist_ok=True)
        with io.open(CATEGORY_CACHE, "w", encoding="utf-8") as f:
            _j.dump(by_item, f, ensure_ascii=False)
    except Exception:                                          # noqa: BLE001
        pass


def _load():
    """(funnel の US 行, itemID→ミラー込み棚額, 行→カテゴリ) を返す。"""
    done = CE.load_done()
    fr = [r for r in csv.DictReader(
        open(sorted(glob.glob(os.path.join(LF.OUT_DIR, "funnel_*.csv")))[-1],
             encoding="utf-8-sig")) if r["item_id"] not in done]
    mir = collections.defaultdict(float)
    reps = sorted(glob.glob(REPORT_GLOB, recursive=True))
    if reps:
        seen = set()
        for r in csv.DictReader(open(reps[-1], encoding="utf-8-sig", errors="replace")):
            i = (r.get("Item number") or "").strip()
            if not i or i in done or i in seen:
                continue
            seen.add(i)
            if (r.get("Listing site") or "").strip() != "US":
                mir[LF._title_key(r.get("Title"))] += _f(r.get("Current price"))

    def shelf_of(row):
        return _f(row.get("price")) + mir.get(LF._title_key(row.get("title")), 0.0)

    # カテゴリは商品管理シートの R列が正 (funnel の eBay カテゴリは混在して信用できない)。
    # ★2026-09-03: ここが Google の 500/503 で落ちると、ボタンの件数ラベルごと消える
    #   (実測。表示のために毎回シートを叩いている)。取れた分をローカルに残し、
    #   叩けなかった時は前回の写しを使う。カテゴリは日に何度も変わる値ではない。
    by_item = _category_cache_load()
    supply, onhand, known = {}, None, None
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        gc = gspread.authorize(Credentials.from_service_account_file(
            LF.CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets",
                                   "https://www.googleapis.com/auth/drive"]))
        fresh, sheets = {}, []
        for sid in LF.SHEET_IDS:
            vals = gc.open_by_key(sid).get_worksheet_by_id(LF.SHEET_GID).get_all_values()
            sheets.append(vals)
            for row in vals[1:]:
                iid = (row[1] if len(row) > 1 else "").strip()
                c = (row[17] if len(row) > 17 else "").strip()
                if iid.isdigit() and c:
                    fresh[iid] = c
                if iid.isdigit():
                    supply[iid] = ((row[0] if row else "") or "").strip()   # 仕入元URL (Tシャツの1点物判定)
        if fresh:
            by_item = fresh
            _category_cache_save(fresh)
        onhand = load_onhand_ids(gc, sheets)
        known = load_known_ids(gc, sheets, onhand)
    except Exception as e:                                     # noqa: BLE001
        if not by_item:
            raise
        print(f"  ⚠ カテゴリはシートを読めず前回の写しを使います ({type(e).__name__})")
        onhand = load_onhand_ids()
        known = load_known_ids()
    if onhand:
        print(f"  🛡 有在庫 {len(onhand)}件 は落としません")

    def cat_of(row):
        iid = str(row.get("item_id") or "")
        return category_for(iid, by_item.get(iid), supply.get(iid, ""), onhand, known,
                            sku=row.get("sku") or "")

    return fr, shelf_of, cat_of


def split_verified(status_by_item):
    """送った分を「本当に終わった」「まだ生きている」に分ける。純関数。

    ★2026-09-03: 画面に「✅ END」と出たのに **生きたままの出品**があった (実測)。
      送信の戻り値を信じず、eBay の実状態で数え直す。
      状態が読めないものは **終わった側に入れない** (fail-closed。
      黙って済ませると、売れる状態で残ったことに誰も気づかない)。
    戻り: (終わった itemID, 要対応 [(itemID, 状態)])
    """
    done, todo = [], []
    for iid, st in status_by_item.items():
        if st and st != "Active":
            done.append(iid)
        else:
            todo.append((iid, st or "読めない"))
    return done, todo


def _verify_ended(ids):
    """送った直後に eBay を読み直して、本当に終わったかを確かめる (I/O)。

    戻り: 本当に終わった itemID。落ちていない分は画面に「要対応」で出す。
    """
    if not ids:
        return ids
    try:
        from ebay_getitem_images import fetch_listing_status
    except Exception as e:                                     # noqa: BLE001
        print(f"  ⚠ 照合できません ({type(e).__name__}) → 送信結果をそのまま使います")
        return ids
    print(f"\n▶ 実物を読み直して照合します ({len(ids)}件)...")
    status = {}
    for iid in ids:
        try:
            status[iid] = fetch_listing_status(iid)
        except Exception:                                      # noqa: BLE001
            status[iid] = None
    done, todo = split_verified(status)
    print(f"  ✅ 終了を確認 {len(done)}件")
    if todo:
        print(f"  ⚠️ **まだ生きています {len(todo)}件 = 要対応** (次回もう一度対象に上がります)")
        for iid, st in todo:
            print(f"     ✗ {iid}: {st}")
    return done


def count_workload():
    """押したら何件・いくら落とせるか (2026-08-31・ラベル/ヒント用、eBay を叩かない)。

    ★badge の計算は開くたび自動で走る。live 一覧のキャッシュが無い/古い時に
      ここで取りに行くと ~24 call の重い sweep が走ってしまう
      (cull_end.count_workload と同じ理由で eBay を叩かない設計にする。
      2026-08-24 に表示のための取得で API 上限を使い切り、取下げが5時間止まった)。
      キャッシュが新しければ使い、無ければ「①はキャッシュ待ち」と正直に出す。

    戻り: {"picked": 選定件数, "amount": 空く額, "target": 落とす目標額,
           "listed_today": 今日の出品額, "tier1": ①件数, "tier2": ②件数,
           "cache_note": 補足 (キャッシュが古い/無い時), "error": 読めなかった理由}
    """
    out = {"picked": 0, "amount": 0.0, "target": 0.0, "listed_today": 0.0,
           "tier1": 0, "tier2": 0, "max_picked": 0, "max_amount": 0.0,
           "cache_note": "", "error": ""}
    try:
        listed = listed_today_amount()
        # ★2026-09-18: main() は「今日すでに落とした分」を引くのに、ここは引いていなかった。
        #   3件 落とした直後もボタンは 3件 のままで「押しても件数が減りませんでした」と
        #   出ていた (実際は押しても『今日はもう落とす分がありません』で何も起きない)。
        #   main() と同じ remaining_target を通す (二重実装しない)。
        # ★2026-10-05 ユーザー「上限は不要」: 落とす量は理由 (棚②のルール) で決まる。出品額に合わせた上限は無い
        target = float("inf")
        out["listed_today"] = listed
        # ★2026-09-03: 目標額を聞けるようにしたので、ボタンには **今日いくらまで空けられるか**
        #   (=対象すべて) を出す。今日の出品額しか出さないと「押せる上限」が分からない。
        #   出品が0件の日でも上限は出す (target<=0 でも先へ進む)。

        import itemid_writeback_audit as A
        rows, shelf_of, cat_of = [], None, None
        if A.CACHE.exists():
            import time as _t
            age = _t.time() - A.CACHE.stat().st_mtime
            if age < A.CACHE_MAX_AGE_SEC:
                import json as _j
                live = _j.loads(A.CACHE.read_text(encoding="utf-8"))
                rows = rows_from_live(live, CE.load_done(), LF._title_key)
                shelf_of = lambda r: _f(r.get("price")) + _f(r.get("_mirror"))  # noqa: E731
            else:
                out["cache_note"] = (
                    "① live キャッシュが古い (%d時間前) → 押すと更新されます" % int(age / 3600))
        else:
            out["cache_note"] = "① live キャッシュがまだありません → 押すと作られます"

        # ★2026-09-03: ②(在庫はあるが売れない)は経過日数と販売実績が要る。live 一覧には
        #   その列が無いので、**必ずファネルも読む**。読まないと ② が常に0件になり、
        #   ボタンに「対象なし」と出てしまう (実測でそうなっていた)。ファネルはローカルCSV。
        if True:
            frows, fshelf, fcat = _load()
            seen = {r["item_id"] for r in rows}
            rows = rows + [r for r in frows if r.get("item_id") not in seen]
            cat_of = fcat
            _live_shelf = shelf_of
            if _live_shelf:
                def shelf_of(row, _l=_live_shelf, _f2=fshelf):  # noqa: F811
                    return _l(row) if "_mirror" in row else _f2(row)
            else:
                shelf_of = fshelf

        # ★2026-09-03: 棚のボタンは②だけになった (①は取下げに統合)。
        #   ラベルの件数も②に揃える。①を混ぜると押しても出てこない数字になる。
        # ★2026-09-03: ラベル計算では **スプシを読まない**。再仕入れ予定の読み取りは
        #   Google の 503 で落ちることがあり、そのたびボタンの件数が消える (実測)。
        #   ここは表示なので、守りは押した時 (main) に効かせれば足りる。
        _keep, _nd = set(), no_demand_ids(rows)
        # ★2026-10-04: PSA は棚②の新しい表で決めるので、件数も前回の判定 (市場の門の後) で数える。
        #   値下げの台帳はローカルの JSON なので読んでよい (eBay・市場の API は叩かない)。
        _pj = _last_psa_judge()
        _pd = load_price_downs() if _pj is not None else False
        mpicked, mtotal = pick(rows, float("inf"), shelf_of, cat_of, only_tier=TIER_STALE,
                               restock_pending=_keep, no_demand=_nd, price_downs=_pd, psa_judge=_pj)
        _cap = cap_today(mpicked, daily_cap(), evicted_today_count())       # ★2026-10-05 1日50件まで
        out.update(max_picked=len(mpicked), max_amount=mtotal, picked=len(_cap),
                   amount=sum(shelf_of(r) for _t, r in _cap), tier2=len(_cap))
        if False:                          # 上限を外したので「今日の目標」で切らない (2026-10-05)
            picked, total = pick(rows, target, shelf_of, cat_of, only_tier=TIER_STALE,
                                 restock_pending=_keep, no_demand=_nd, price_downs=_pd, psa_judge=_pj)
            byt = collections.Counter(t for t, _r in picked)
            out.update(picked=len(picked), amount=total,
                       tier1=byt.get(TIER_OOS, 0), tier2=byt.get(TIER_STALE, 0))
    except Exception as e:                                     # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"[:60]
    return out


def _aux_by_item():
    """itemID → 補URL が1本以上あるか。商品管理シート (HIGH・LOW) の両方から (I/O)。"""
    import gspread
    from google.oauth2.service_account import Credentials
    import sheet_io as _S
    gc = gspread.authorize(Credentials.from_service_account_file(
        LF.CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"]))
    a0, n = _S.PRODUCT_COL_AUX_START, _S.PRODUCT_AUX_MAX
    out = {}
    for sid in LF.SHEET_IDS:
        for r in gc.open_by_key(sid).get_worksheet_by_id(LF.SHEET_GID).get_all_values()[1:]:
            iid = (r[1] if len(r) > 1 else "").strip()
            if iid:
                out[iid] = any((r[k].strip() if len(r) > k else "") for k in range(a0, a0 + n))
    return out


def _psa_judge(price_downs, cat_of=None):
    """② を棚②の表 (補があるかどうか) + 市場の門 (PSA だけ) で決める関数を作る (I/O: 補の有無・表示レポート・市場)。"""
    import shelf_psa_rules as R
    bands = load_price_down_bands()
    try:
        aux = _aux_by_item()
    except Exception as e:                                     # noqa: BLE001
        print(f"  ⚠ 補の有無を読めず ({type(e).__name__}) → ② は今回落としません")
        return lambda r: {"item_id": r.get("item_id"), "verdict": R.KEEP, "code": "補の有無が読めない"}
    traffic, tf = R.load_traffic()
    print(f"  📊 表示レポート: {os.path.basename(tf) if tf else '無し (閲覧が要る行は落としません)'}")
    market = R.Market()
    if market.err:
        print(f"  ⚠ 市場の検索 API に繋がらない ({market.err}) → 市場の門は全部「残す」")

    def judge(r):
        iid = str(r.get("item_id") or "")
        down = not needs_price_down_first(iid, price_downs, bands)
        cat = cat_of(r) if cat_of else "TCG"
        d = R.judge(r, aux.get(iid, False), down, traffic, market if cat == "TCG" else None,
                    use_market=(cat == "TCG"))
        d["category"] = cat
        return d
    return judge


LAST_PSA_DROPS = r"C:/dev/iMak_data/hq/shelf2_last_psa_drops.json"


def _save_last_psa_drops(ids):
    """最後に判定した PSA の「取下げ」(ボタンの件数用。表示のたびに市場 API を叩かない)。"""
    try:
        with open(LAST_PSA_DROPS, "w", encoding="utf-8") as f:
            json.dump({"at": datetime.datetime.now().isoformat(timespec="seconds"),
                       "iids": list(ids)}, f, ensure_ascii=False)
    except OSError:
        pass


def _last_psa_judge():
    """ボタンの件数用の判定: 前回押した時 (試しも含む) に「取下げ」だった物だけ数える。無ければ None。"""
    try:
        with open(LAST_PSA_DROPS, encoding="utf-8") as f:
            ids = set(json.load(f).get("iids") or [])
    except (OSError, ValueError):
        return None
    return lambda r: {"verdict": "取下げ" if str(r.get("item_id") or "") in ids else "残す"}


def _report_psa_decisions(decisions, ended=False):
    """PSA の判定の内訳を出し、台帳と補優先の一覧を書く (I/O)。"""
    import shelf_psa_rules as R
    _save_last_psa_drops([d["item_id"] for d in decisions if d.get("verdict") == R.DROP])
    c = collections.Counter(d["verdict"] for d in decisions)
    print(f"\n  🃏 ② を棚②の表で判定 (全商材・公式仕入と有在庫は除く): {len(decisions)}件 → "
          f"取下げ {c.get(R.DROP, 0)} / 補優先 {c.get(R.HOJU, 0)} / 残す {c.get(R.KEEP, 0)}")
    for cat, n in collections.Counter((d.get("category"), d["verdict"]) for d in decisions).most_common():
        print(f"     {cat[0]} {cat[1]}: {n}")
    for code, n in collections.Counter(d["code"] for d in decisions).most_common():
        print(f"     {code}: {n}")
    ids = R.write_hoju_priority(decisions)
    print(f"     → 補優先 {len(ids)}件 を補URL③・夜の検索の先頭に回します ({R.HOJU_PRIORITY_PATH})")
    if ended:
        R.log_decisions(decisions)
        print(f"     → 判定を台帳に残しました ({R.DECISIONS_PATH})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--end", action="store_true", help="eBay に End を送る")
    ap.add_argument("--tier", choices=("1", "2"), default=None,
                    help="1=仕入元が死んでいる分だけ / 2=在庫はあるが期限超えだけ (既定は両方)")
    ap.add_argument("--amount", type=float, default=None, help="目標額を直接指定")
    ap.add_argument("--ratio", type=float, default=RATIO)
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                          # noqa: BLE001
        pass

    # ★2026-09-24: 前回 落とした後、シートの後始末の前に PC が落ちた分を先に直す
    CE.writeback_done_ledger()

    listed = listed_today_amount()
    if a.amount is not None:
        target = a.amount
    elif True:
        # ★2026-10-05 ユーザー「上限は不要」(Gemini の「1日15〜20件に分散」案も見たうえで)。
        #   棚②のルールで「取下げ」と決まった物を全部落とす。--amount を渡した時だけ金額で切る。
        target = float("inf")
    else:
        # ★2026-09-03: 目標が「今日の出品額」だけだと、**押すたびに同じ額が落ちる**
        #   (実測: 空欄で2回押して $14,939 + $15,624 = 出品額の2倍)。
        #   今日すでに落とした分を引いて、残りだけにする。
        _done_today = evicted_today_amount()
        target = remaining_target(listed, _done_today, a.ratio)
        if _done_today:
            print(f"  ℹ 今日すでに ${_done_today:,.0f} 落としています → 残り ${target:,.0f}")
    if target == float("inf"):
        print(f"落とす量: ルールで「取下げ」と決まった物を、並び順の上から1日{daily_cap()}件まで (今日すでに {evicted_today_count()}件)")
    else:
        print(f"落とす上限 ${target:,.0f}")

    # ★まず live 一覧で ①(数量0) を埋める。ここはレポートもファネルも要らず常に最新。
    #   足りない時だけ ②(表示回数の少ない順) のためにファネルを読む (古ければそう出す)。
    rows, shelf_of = _load_live()
    cat_of = None
    # ★2026-09-02: --tier 2 (在庫ありだけ) の時は **必ず**ファネルを読む。
    #   ①(数量0)で目標に届いても、②の候補はファネルにしか無いので、
    #   短絡すると「落とせる候補がありません」になる (実際に踏んだ)。
    _need_funnel = (getattr(a, "tier", None) == "2")
    if not _need_funnel and rows and shelf_of and sum(shelf_of(r) for r in rows) >= target:
        print("  → ①だけで目標に届くので、レポート/ファネルは読みません")
    else:
        if rows:
            print("  → ①だけでは足りないので、②のためにファネルも読みます")
        frows, fshelf, cat_of = _load()
        seen = {r["item_id"] for r in rows}
        rows = rows + [r for r in frows if r.get("item_id") not in seen]
        _live_shelf = shelf_of

        def shelf_of(row, _l=_live_shelf, _f2=fshelf):            # noqa: F811
            return _l(row) if "_mirror" in row else _f2(row)

    print("対象: 仕入元が死んでいるもの(全カテゴリ) → "
          "全商材 (公式仕入・有在庫は除く) の 30日超・未販売を 棚②の表 (補があるかどうか・PSA は市場の門) で")
    if target <= 0:
        print("  今日はまだ出品していないので、落とす分もありません")
        return 0
    _keep = restock_pending_ids()
    if _keep:
        print(f"  🛡 再仕入れが戻す予定の {len(_keep)}件 は落としません")
    _nd = no_demand_ids(rows)
    print(f"  🛡 ①は「生涯ずっと需要ゼロ」の {len(_nd)}件 に限ります "
          f"(需要があった分は再仕入れへ)")
    _downs = load_price_downs()
    _held, _decisions = [], []
    _judge = _psa_judge(_downs, cat_of) if _downs is not None else None
    picked, total = pick(rows, target, shelf_of, cat_of,
                         only_tier=(int(a.tier) if getattr(a, "tier", None) else None),
                         restock_pending=_keep, no_demand=_nd, price_downs=_downs, held=_held,
                         psa_judge=_judge, decisions=_decisions)
    if _decisions:
        _report_psa_decisions(_decisions, ended=a.end)
    else:
        _save_last_psa_drops([])
    if _downs is None:
        print("  🛡 値下げの履歴 (リバイスくんの台帳) が読めない → ② は今回落としません (判断できない)")
    if _held:
        print(f"  🛡 まだ値下げしていない ② {len(_held)}件 は落とさず「値下げ候補」に回します"
              f" (出品時から価格帯ごとの金額以上 下げても売れない物だけ落とす: {SETTINGS_PATH})")
        try:
            os.makedirs(os.path.dirname(PRICE_DOWN_FIRST_PATH), exist_ok=True)
            with open(PRICE_DOWN_FIRST_PATH, "w", encoding="utf-8") as f:
                json.dump({"at": datetime.datetime.now().isoformat(timespec="seconds"),
                           "items": [{"item_id": r.get("item_id"), "title": r.get("title"),
                                      "price": r.get("price"), "age_days": r.get("age_days"),
                                      "watch": r.get("watch"), "impr_total": r.get("impr_total")}
                                     for r in _held]}, f, ensure_ascii=False, indent=1)
            print(f"     → {PRICE_DOWN_FIRST_PATH}")
        except Exception as e:                                 # noqa: BLE001
            print(f"  ⚠ 値下げ候補を書けず ({type(e).__name__})")
    # ★2026-10-05 ユーザー判断: 落とす前のオファーはやめた (こちらからオファーを送らない)。
    #   以前送った時も数件しか売れず、送ると96時間は出品を直せず取り消せない (仕入元が切れたら終了しかない)。
    #   欲しい人はベストオファーで自分から送ってくる (過去30日 22件)。shelf_offer.py は使っていない
    if target == float("inf") and picked:
        _cap, _done = daily_cap(), evicted_today_count()
        _all = len(picked)
        picked = cap_today(picked, _cap, _done)
        total = sum(shelf_of(r) for _t, r in picked)
        if len(picked) < _all:
            print(f"  📏 1日{_cap}件まで (今日すでに {_done}件) → 並び順の上から {len(picked)}件 / 対象 {_all}件 (残りは明日以降)")
    if not picked:
        print("  落とせる候補がありません")
        return 0
    byt = collections.Counter()
    byv = collections.Counter()
    for t, r in picked:
        byt[t] += 1
        byv[t] += shelf_of(r)
    print(f"\n選定 {len(picked)}件 / 空く額 ${total:,.0f}")
    for t in sorted(byt):
        print(f"   {TIER_NAME[t]:26s}{byt[t]:4d}件 ${byv[t]:9,.0f}")
    print("\n  上位10件:")
    for t, r in picked[:10]:
        print(f"   [{t}] ${shelf_of(r):8,.0f} 表示{_f(r.get('impr_total')):6.0f} "
              f"watch{_f(r.get('watch')):.0f}  {r['item_id']}  {(r.get('title') or '')[:44]}")
    _p = write_candidates(picked, shelf_of, cat_of, clicks=load_clicks())
    if _p:
        print("\n  📄 候補CSV: %s" % _p)
        print("     (価格・経過日数・表示・クリック・ウォッチ入り。中身を見て判断)")
    if not a.end:
        print("\n  → 実際に落とすには --end")
        return 0
    # ★送る直前に eBay の実状態を1件ずつ見る (誤取下げ防止)。
    #   ・既に終了している → 済みリストに入れて外す
    #   ・在庫切れで選んだのに **補充されていた** → 外す (①だけに効く。②③は在庫ありで選んでいる)
    #   ・状態が取れない → 外す (fail-closed。取得失敗を破壊側に倒さない)
    sys.path.insert(0, os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMakeBayAPI")))
    try:
        from ebay_getitem_images import fetch_listing_qty, fetch_listing_status
    except Exception as e:                                     # noqa: BLE001
        print(f"⛔ 在庫検証モジュールを読めないので中止します (fail-closed): {e}")
        return 1
    print(f"\n  現eBay状態を実機確認中 ({len(picked)}件)...", flush=True)
    keep, dropped = [], collections.Counter()
    ended_ids = set()
    for t, r in picked:
        iid = r["item_id"]
        try:
            st = fetch_listing_status(iid)
        except Exception:                                      # noqa: BLE001
            st = None
        if st is None:
            dropped["状態が取れない"] += 1
            continue
        if st != "Active":
            dropped["既に終了"] += 1
            CE.remember_done([iid])
            ended_ids.add(iid)
            continue
        try:
            q = fetch_listing_qty(iid)
        except Exception:                                      # noqa: BLE001
            q = None
        if q is None:
            dropped["在庫が取れない"] += 1
            continue
        if t == TIER_OOS and q > 0:
            dropped["在庫が復活していた"] += 1
            continue
        keep.append((t, r))
    for k, n in dropped.items():
        print(f"   ⏭ 除外 {k}: {n}件")
    # ★2026-09-24: 終わっている分もシートの後始末に通す。前回 End を送った後、後始末の前に
    #   PC が落ちると、B列に死んだ番号が残り続けていた (出品済み扱いのまま再出品されない)。
    if ended_ids:
        try:
            import cull_writeback as CW
            n = CW.apply(ended_ids, commit=True, label="棚②")
            if n:
                print(f"  ▶ 終わっていた分のスプシ後始末 → {n}行 (B列を空 + Q列に「棚② 日付」)")
        except Exception as e:                                 # noqa: BLE001
            print(f"  ⚠ 終わっていた分のスプシ後始末は次回に持ち越し: {type(e).__name__}: {e}")
    if not keep:
        print("  実機確認後の対象なし。処理終了。")
        return 0
    picked = keep
    print(f"  → End 確定 = {len(picked)}件 (${sum(shelf_of(r) for _t, r in picked):,.0f})")
    ids = [r["item_id"] for _t, r in picked]
    amount_of = {r["item_id"]: shelf_of(r) for _t, r in picked}

    def _on_ok(iid):
        # ★2026-09-24: 1件落とすごとに記録する。全部送った後に記録していたので、途中で落ちると
        #   「今日落とした額」が0のまま = 次に押すと目標額をまた全部落としていた (落とし過ぎ)。
        CE.remember_done([iid])
        remember_evicted(amount_of.get(iid, 0))
    ok, ng = CE.end_on_ebay([{"item_id": i} for i in ids], on_ok=_on_ok)
    print(f"\n▶ eBay に送信 → 成功 {len(ok)}件 / {len(ids)}件")
    for iid, msg in ng[:8]:
        print(f"   ⚠ {iid}: {msg}")
    # ★2026-09-03: 送りっぱなしにしない。画面の「成功」と実物が食い違った実例が出た
    #   (落ちていない出品が ✅ と出ていた)。**送った直後に eBay を読み直して照合**し、
    #   落ちていないものは「要対応」として残す (状態同期の安全原則)。
    ok = _verify_ended(ok)
    if ok:
        import cull_writeback as CW
        # ★2026-10-05 棚② は「棚② 日付」の印 = 新規出品で出し直さない (取下げの CULL とは分ける)
        n = CW.apply(set(ok), commit=True, label="棚②")
        print(f"▶ スプシ更新 → {n}行 (B列を空 + Q列に「棚② 日付」= 新規で出し直さない)")
        try:
            import oos_status_refresh as OS
            OS.main_commit()
        except Exception as e:                                 # noqa: BLE001
            print(f"   ⚠ 在庫なしシートの状態列は次回に持ち越します: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
