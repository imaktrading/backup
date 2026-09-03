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
    ② 出品30日超・未販売   … **TCG と G-SHOCK だけ**。アクセス (累計表示) の少ない順

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
TIER_NAME = {TIER_OOS: "① 仕入元が死んでいる",
             TIER_STALE: "② TCG 30日超・未販売 (空く額の大きい順)"}
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
STALE_MAX_AGE = {"TCG": 30, "G-shock": 365}
STALE_CATEGORIES = tuple(STALE_MAX_AGE)


def _f(v):
    try:
        return float(str(v or 0).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return 0.0


def tier_of(row, min_age=MIN_AGE_DAYS, category=None, stale_cats=STALE_CATEGORIES,
            max_age=None, restock_pending=None):
    """その出品を落とす順の何番に置くか。触らないものは None (純関数, test可)。

    ★2026-08-26 ユーザー確定:
      ・**閾値を設けない**。「表示◯回以上なら」の線はカテゴリごとに桁が違って必ず取りこぼす。
      ・**仕入元が死んでいる分は全カテゴリ**。買えないものを残す意味は無い。
      ★2026-09-02 更新: 仕入元が活きている分は **TCG だけ**にした (G-shock を外した)。
        根拠は STALE_CATEGORIES のコメント。落とす順は **空く額の大きい順**
        (TCG 30日超ではアクセスの多寡で売却率が変わらないため)。
    """
    if restock_pending and str(row.get("item_id") or row.get("itemID") or "").strip() \
            in restock_pending:
        # ★2026-09-03: 再仕入れが「仕入元を見つけた、これから数量を戻す」と決めた出品。
        #   ①(数量0)は需要を見ないので、放っておくと **戻す直前の出品を落とす**。
        #   実測: 戻す予定12件のうち8件が①の対象に入っていた。
        #   取下げ(CULL)は「生涯ずっと需要ゼロ」に限るので、こちらとは元々重ならない。
        return None
    if _f(row.get("qty")) == 0:
        return TIER_OOS                   # 買えないので稼ぎようがない (全カテゴリ)
    if _f(row.get("sold_qty")) + _f(row.get("sales90")) > 0:
        return None                       # 売れた実績あり
    if stale_cats and category not in stale_cats:
        return None                       # 線を引けるデータが無いカテゴリは触らない
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


def pick(rows, target, shelf_of, cat_of=None, only_tier=None, restock_pending=None):
    """目標額に届くまで、順位の上から選ぶ。戻り: (選んだ行, 空く額) 純関数, test可。

    ①② とも **空く額の大きい順**。1件で空く額が大きいほうが先。

    ★2026-09-02: ② を「アクセスの少ない順」から変えた。TCG の30日超では
      アクセス (表示/クリック/ウォッチ) のどの区分でも売却率が0%で、
      **アクセスの多寡が結果を変えない**ことが実測で分かったため
      (表示5,000回以上の241件も、ウォッチ2以上の56件も、売れたのは0件)。
      であれば **目標額に少ない件数で届く順** = 高い順に落とすのが正しい。
      取り返しのつかない操作 (End) の回数が減る。
    """
    cand = []
    for r in rows:
        t = tier_of(r, category=(cat_of(r) if cat_of else None),
                    restock_pending=restock_pending)
        if t is None:
            continue
        # ★2026-09-02 ユーザー指示: **在庫ありの取下げはボタンを分ける**。
        #   ①(仕入元が死んでいる)は「買えないので落として損が無い」。
        #   ②(在庫はあるが期限超え)は「売れるかもしれない物を捨てる」判断で、重さが違う。
        #   混ぜて1つのボタンにすると、重い方を軽い気持ちで押すことになる。
        if only_tier is not None and t != only_tier:
            continue
        rank = -shelf_of(r)          # ①② とも 空く額の大きい順
        cand.append((t, rank, r))
    cand.sort(key=lambda x: (x[0], x[1]))
    picked, total = [], 0.0
    for t, _rank, r in cand:
        if total >= target:
            break
        picked.append((t, r))
        total += shelf_of(r)
    return picked, total


def listed_today_amount(csv_dir=CSV_DIR, today=None):
    """その日に作った入稿CSVの金額合計 (US価格)。純関数寄り, test可。"""
    today = today or datetime.date.today()
    stamp = today.strftime("%Y%m%d")
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
    import gspread
    from google.oauth2.service_account import Credentials
    gc = gspread.authorize(Credentials.from_service_account_file(
        LF.CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets",
                               "https://www.googleapis.com/auth/drive"]))
    by_item = {}
    for sid in LF.SHEET_IDS:
        for row in gc.open_by_key(sid).get_worksheet_by_id(LF.SHEET_GID).get_all_values()[1:]:
            iid = (row[1] if len(row) > 1 else "").strip()
            c = (row[17] if len(row) > 17 else "").strip()
            if iid.isdigit() and c:
                by_item[iid] = c

    def cat_of(row):
        return by_item.get(row.get("item_id"))

    return fr, shelf_of, cat_of


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
           "tier1": 0, "tier2": 0, "cache_note": "", "error": ""}
    try:
        listed = listed_today_amount()
        target = listed * RATIO
        out["listed_today"], out["target"] = listed, target
        if target <= 0:
            return out

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

        if not rows or sum(shelf_of(r) for r in rows) < target:
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

        picked, total = pick(rows, target, shelf_of, cat_of,
                             restock_pending=restock_pending_ids())
        byt = collections.Counter(t for t, _r in picked)
        out.update(picked=len(picked), amount=total,
                   tier1=byt.get(TIER_OOS, 0), tier2=byt.get(TIER_STALE, 0))
    except Exception as e:                                     # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"[:60]
    return out


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

    listed = listed_today_amount()
    target = a.amount if a.amount is not None else listed * a.ratio
    print(f"今日の出品額 ${listed:,.0f} × {a.ratio} = **落とす目標 ${target:,.0f}**")

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
          f"{'/'.join(STALE_CATEGORIES)} の 期限超え・未販売を 空く額の大きい順")
    if target <= 0:
        print("  今日はまだ出品していないので、落とす分もありません")
        return 0
    _keep = restock_pending_ids()
    if _keep:
        print(f"  🛡 再仕入れが戻す予定の {len(_keep)}件 は落としません")
    picked, total = pick(rows, target, shelf_of, cat_of,
                         only_tier=(int(a.tier) if getattr(a, "tier", None) else None),
                         restock_pending=_keep)
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
    if not keep:
        print("  実機確認後の対象なし。処理終了。")
        return 0
    picked = keep
    print(f"  → End 確定 = {len(picked)}件 (${sum(shelf_of(r) for _t, r in picked):,.0f})")
    ids = [r["item_id"] for _t, r in picked]
    ok, ng = CE.end_on_ebay([{"item_id": i} for i in ids])
    CE.remember_done(ok)
    print(f"\n▶ eBay に送信 → 成功 {len(ok)}件 / {len(ids)}件")
    for iid, msg in ng[:8]:
        print(f"   ⚠ {iid}: {msg}")
    if ok:
        import cull_writeback as CW
        n = CW.apply(set(ok), commit=True)
        print(f"▶ スプシ更新 → {n}行 (B列を空 + Q列に印)")
        try:
            import oos_status_refresh as OS
            OS.main_commit()
        except Exception as e:                                 # noqa: BLE001
            print(f"   ⚠ 在庫なしシートの状態列は次回に持ち越します: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
