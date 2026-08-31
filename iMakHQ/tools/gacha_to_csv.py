#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gacha_to_csv.py — ガチャポンのコンプ品 (楽天) → eBay 入稿CSV (2026-08-20)。

出品の形は **既存のカプセルトイ出品をそのまま踏襲**する。実物 (itemID 357200557035
VIRUSWEETS フィギュアコレクション) を eBay から読んで写した:
    カテゴリ 69528 / ストアカテゴリ 41827562010 / SKU = 仕入元ID
    Set=Complete Set / Number of Pieces=N / Material=PVC / Age Level=15+ /
    Type=Mini Figure / Brand / Series / Character / Franchise / Theme /
    Country of Origin=Does not apply / MPN は公式品番が取れた物だけ
    タイトル: "<シリーズ> Full Set of N Gashapon NEW"

入力は中間スプシ (Harvest が入れる) か HIGH の商品管理シート。列は PSA10 と同じ:
    A=URL / C=日本語タイトル / E=状態 / F=商品価格 / G=写真URL / M=現在価格(円) / R=カテゴリ

★出さない物 (fail-closed・米国 CPSC)
    - サンリオ: user 判断で「今後扱わない」(2026-06-29、ぬいぐるみ22件を取下げた時)
    - ぬいぐるみ / マスコット等: stuffed animals は **対象年齢の印字と無関係に**
      児童製品確定。4要素判定で逃げられず、第三者試験 + CPC が要る
    実測 2026-08-20: 中間スプシ93行のうち、この2つで75行が落ち、残り18行。

使い方:
    python gacha_to_csv.py --list                     # 出せる行を一覧 (CSVは作らない)
    python gacha_to_csv.py --limit 5                  # 5件だけ CSV 生成
    python gacha_to_csv.py --sheet <id> --tab <name>  # 読む先を変える (既定=中間スプシ)
"""
from __future__ import annotations

import argparse
import csv
import datetime
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
for _p in (SCRIPT_DIR, r"C:\dev\iMak\iMakeBayAPI"):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 中間スプシ。★2026-08-23: 抽出くんは **店ごとにタブを分けて**書いている
#   (rakuten_auc_yuyou / rakuten_auc_toysanta / rakuten_mirakikaku / rakuten_jugem2020 /
#    rakuten_mejirushi)。ここは `rakuten_gacha` 1本を決め打ちしていたので、そんなタブは
#   無く read_sheet が StopIteration で落ち、**ガチャの出品CSVが1件も作れなかった**。
#   タブ名を並べて持つと店が増えるたびに両者で書き写すことになるので、**前方一致で拾う**。
STAGING_SHEET_ID = "1hTdFVGkni4Ih4kZGsBgiCKxpTlOeoO_wJdk8Ek5n41Q"
STAGING_TAB_PREFIX = "rakuten_"
STAGING_TAB = ""            # 空 = 前方一致で全部。--tab で1本に絞れる

OUTPUT_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "csv_output")

# eBay 固定値 — 既存のカプセルトイ出品 (itemID 357200557035) から実測
EBAY_CATEGORY = 69528          # Collectibles > Animation Art & Merchandise > Other Animation Merchandise
STORE_CATEGORY = 41827562010
CONDITION_ID = 1000            # New
LOCATION = "Osaka"
PROFIT_CATEGORY = "ガシャポン"   # pricing_engine のカテゴリ名 (R列の「カプセルトイ」の内部名)
SHEET_CATEGORY = "カプセルトイ"   # シート R列の値
# ★2026-08-31: この定数は**使っていない** (このファイルは API を叩かない)。
#   実際に叩くのは gacha_enrich.py。置いたままだと「ここが Opus」と読めて
#   課金の見直しで迷うので、そちらを唯一の決定口にする。
from gacha_enrich import MODEL  # noqa: F401  (後方互換のため名前だけ残す)
SCHEDULE_WEEKS = 2

# ★出さない語 (fail-closed)。増やすのは可、減らすのは不可。
NG_FRANCHISE = ("サンリオ",)
NG_PLUSH = ("ぬいぐるみ", "マスコット", "フロッキー", "パペット",
            "もこもこ", "ふわふわ", "プラッシュ", "plush", "Plush")

# 日本語タイトルから落とすノイズ
_NOISE = ("ガチャポン", "ガチャガチャ", "コンプリート", "コンプ", "ガチャ",
          "カプセルトイ", "コンプリートセット")

# ★食玩 (シールウエハース等)。2026-08-21 回答書
#   `2026-08-21_gacha_food_toy_disclaimer_response.md` で扱えるようになった。
#   カプセルトイ前提の語・説明文・年齢確認を **全部** 切り替える必要がある。
#   どの行が食玩かは **中間スプシ S列の印だけ** で決める (タイトルから当てない。
#   「チョコ」等の語はキャラ名にも出るので、当てにいくと必ず誤判定する)。
FOOD_TOY_COL = 18                # S列
FOOD_TOY_MARK = "食玩"            # 空 = 通常のカプセルトイ
# `Gashapon` / `Capsule Toy` はどちらも食玩に使えない (カプセルに入っていない)。
# `Shokugan` は日本語そのままの一般名、`Candy Toy` はバンダイ自身が英語で使う一般名。
FOOD_TOY_TERM = "Shokugan Candy Toy"


# ── 純関数 (test 可) ────────────────────────────────────────────────


def strip_shop_suffix(title: str) -> str:
    """楽天タイトル末尾の店名 (`：遊you　楽天市場店`) を落とす。"""
    return (title or "").split("：")[0].strip()


def piece_count(title: str):
    """「全N種」の N。取れなければ None (= 出さない)。"""
    m = re.search(r"全\s*(\d+)\s*種", title or "")
    return int(m.group(1)) if m else None


def has_display_board(title: str) -> bool:
    """台紙付きかどうか (同じ商品の台紙あり/なしを見分ける)。"""
    return "ディスプレイ台紙" in (title or "")


def blocked_reason(title: str):
    """出せない理由。出せるなら None。

    ★2026-08-20: 米国 CPSC。対象年齢の印字では逃げられない区分なので、
      目視の年齢確認 (別途) とは独立にここで落とす。
    """
    t = title or ""
    if any(k in t for k in NG_FRANCHISE):
        return "サンリオ (2026-06-29 user 判断で今後扱わない)"
    if any(k in t for k in NG_PLUSH):
        return "ぬいぐるみ系 (CPSC: 対象年齢と無関係に児童製品)"
    return None


def food_toy_mark(cell: str):
    """S列の印 → True(食玩) / False(通常) / None(意味が取れない = 出さない)。

    fail-closed: 印が読めない行を「たぶん通常」に倒すと、カプセルトイ前提の
    タイトルと説明文のまま食玩が出る (= 嘘の説明で出品する)。
    """
    v = (cell or "").strip()
    if not v:
        return False
    if FOOD_TOY_MARK in v:
        return True
    return None


def series_jp(title: str) -> str:
    """日本語タイトルからシリーズ名だけ取り出す (全N種より前 − ノイズ)。"""
    head = re.split(r"全\s*\d+\s*種", strip_shop_suffix(title))[0]
    for n in _NOISE:
        head = head.replace(n, " ")
    return re.sub(r"\s+", " ", head).strip()


def maker_jp(title: str) -> str:
    """「全N種…セット」の直後に来るメーカー名。取れなければ空 (推測しない)。"""
    m = re.search(r"全\s*\d+\s*種(?:\+ディスプレイ台紙)?セット\s+(\S+)",
                  strip_shop_suffix(title))
    if not m:
        return ""
    w = m.group(1)
    return "" if w in _NOISE else w


def parse_row(row: list, row_no: int = 0) -> dict | None:
    """シート1行 → 中間表現。出せない行は None。

    row は PSA10 と同じ列並び (A=0 / C=2 / E=4 / F=5 / G=6 / M=12 / R=17)。
    """
    def g(i):
        return (row[i].strip() if len(row) > i else "")

    url, title, cat = g(0), g(2), g(17)
    if not url or not title:
        return None
    food_toy = food_toy_mark(g(FOOD_TOY_COL))
    if food_toy is None:
        return None                      # S列の印が読めない = 出さない (fail-closed)
    if cat != SHEET_CATEGORY:
        return None
    if g(1):
        return None                      # itemID 済 = 出品済
    if blocked_reason(title):
        return None
    n = piece_count(title)
    if not n:
        return None                      # 全N種が読めない = 出さない (fail-closed)
    cost = re.sub(r"[^\d]", "", g(12) or g(5))
    if not cost:
        return None
    # ★2026-08-20 user 指示: G列は **そのまま全部** 目視画面に出す。
    #   どれが商品写真かは人が見て選ぶ (こちらで間引くと、隠れて見えなくなる)。
    pics = [p for p in g(6).split("|") if p.startswith("http")]
    # H列 = 商品説明 + JAN + 対象年齢 (Harvest が公式から取れた分だけ書く)。
    # I列 = メーカー公式URL。どちらも 2026-08-20 の入れ替えで入った。
    desc = g(7)
    m = re.search(r"対象年齢[:：]?\s*([^\s/、]+)", desc)
    return {"row": row_no, "url": url, "title_jp": strip_shop_suffix(title), "pieces": n,
            "with_board": has_display_board(title), "series_jp": series_jp(title),
            "maker_jp": maker_jp(title), "cost_jpy": int(cost), "pics": pics,
            "desc_jp": desc, "official_url": g(8), "food_toy": food_toy,
            "age_official": m.group(1) if m else ""}


def is_banner(url: str) -> bool:
    """店のバナー画像か (商品写真ではない)。

    ★2026-08-20 実測: 中間スプシ93行の **全行** で1枚目が店のバナーだった
      (遊you=bn_math…jpg 82件 / アミュームショップ=rkanban.jpg 11件)。
      1枚目は eBay のギャラリー画像になるので、そのまま出すと商品が写らない。
      収集側にも直してもらうが、こちらでも落とす (fail-safe)。
    """
    name = re.sub(r".*/", "", (url or "").lower())
    return name.startswith("bn_") or "kanban" in name or "banner" in name


def supply_sku(url: str) -> str:
    """仕入元URL → SKU = **URL の商品ID部分だけ** (店名は入れない)。

    メルカリ  https://jp.mercari.com/item/m35315305722      → m35315305722
    楽天      https://item.rakuten.co.jp/auc-yuyou/g22062cs02/ → g22062cs02

    ★2026-08-20 ユーザー確定。以前は楽天だけ `auc-yuyou-g22062cs02` と
      **店名を頭に付けて**いた。他カテゴリ (PSA / 一番くじ) は商品IDだけなので
      規約がガチャだけ違っていた。
    """
    m = re.search(r"/item/(m\d+)", url or "")
    if m:
        return m.group(1)
    m = re.search(r"item\.rakuten\.co\.jp/[^/]+/([^/?#]+)", url or "")
    return m.group(1) if m else ""


def capsule_term(maker_en: str, food_toy: bool = False) -> str:
    """メーカーに合ったカプセルトイの呼び方 (純関数)。

    ★`Gashapon` は **バンダイの登録商標**。タカラトミーアーツの商品に付けると
      他社の商標を使うことになる (逆に `ガチャ/ガチャガチャ` はタカラトミーの登録商標)。
      2026-08-20 まで全77件が `Gashapon` 固定だった。

    `Capsule Toy` はどのメーカーでも使える一般名詞なので必ず後ろに残す
    (商標の語を使えない商品でも検索から漏れないように)。
    """
    if food_toy:
        return FOOD_TOY_TERM             # 食玩はカプセルに入っていない
    m = (maker_en or "").lower()
    if "bandai" in m:
        return "Gashapon Capsule Toy"
    if "takara" in m or "tomy" in m:
        return "Gacha Capsule Toy"
    return "Capsule Toy"


def build_title(series_en: str, pieces: int, maker_en: str = "", extra: str = "",
                food_toy: bool = False) -> str:
    """英語タイトル (80字以内)。

    形: `<題材/シリーズ(英語)> <形態> Complete Set N Types <メーカー> Gashapon Japan`
    例: `Isekai Neko Fantasy Cat Mini Figure Complete Set 5 Types Takara Tomy Gashapon`

    ★2026-08-20 にユーザーが実際に売れている出品を提示して確定した形。
      それまでは **メーカー名を先頭**に置いていて (`Takara Tomy A.R.T.S ...`)、
      先頭20字を検索されない語が占領した結果、肝心の題材が途中で切れていた
      (`... Figure Series Li` = Lizard が切れる / 2件が同じタイトルになる)。

    決まり:
      - 先頭は **買い手が検索する英語**。ローマ字のシリーズ名だけで埋めない
      - メーカーは後ろ。`A.R.T.S` のような検索されない部分は落とす
      - 80字を超える時に削るのは **後ろから** (題材は絶対に切らない)
    """
    maker = re.sub(r"\s*A\.?R\.?T\.?S\.?\s*$", "", maker_en or "", flags=re.I).strip()
    term = capsule_term(maker_en, food_toy)
    seen, subject = set(), []
    for w in (series_en or "").split():
        if w.lower() not in seen:
            seen.add(w.lower())
            subject.append(w)
    extras = [w for w in (extra or "").split() if w.lower() not in seen]
    tails = ["Complete Set %d Types %s %s Japan" % (pieces, maker, term),
             "Complete Set %d Types %s %s" % (pieces, maker, term),
             "Complete Set %d %s %s" % (pieces, maker, term),
             # 字数が苦しい時、`Capsule Toy` より **メーカー名+商標語** を残す
             # (`Bandai Gashapon` の方が検索される)
             "Complete Set %d %s %s" % (pieces, maker, term.split()[0]),
             "Complete Set %d %s" % (pieces, term),
             # 最後の砦。ここも食玩に `Capsule Toy` を出してはいけない
             "Complete Set %d %s" % (pieces, "Shokugan" if food_toy else "Capsule Toy")]
    # 削る順: ① おまけの語(extra)を後ろから ② それでも入らなければ後ろの飾りを落とす。
    #   題材(subject)は最後まで守る。切れると別商品と区別が付かなくなる
    for tail in tails:
        tail = re.sub(r"\s+", " ", tail).strip()
        for k in range(len(extras), -1, -1):
            t = " ".join(subject + extras[:k] + [tail])
            if len(t) <= 80:
                return t
    tail = re.sub(r"\s+", " ", tails[-1]).strip()
    words = list(subject)
    while words and len(" ".join(words + [tail])) > 80:
        words.pop()
    return " ".join(words + [tail])


def needs_review(it: dict) -> bool:
    """目視が要るか (純関数)。

    ★食玩は **必ず要る**。gashapon.jp はカプセルトイの商品DBなので対象年齢が
      取れず、H列の `対象年齢` も付かない (2026-08-21 回答書)。
    """
    if it.get("food_toy"):
        return True
    return ("15" not in (it.get("age_official") or "")
            and "15" not in ((it.get("official") or {}).get("age") or ""))


def official_mpn(item: dict) -> str:
    """公式ページのURLに入っているメーカー品番 (純関数)。無ければ空。

    タカラトミーアーツ: `...item.html?n=Y095122` → `Y095122`
    バンダイ (gashapon.jp): 公式ページに品番の記載が無い → 空
      (画像URLの数字は商品ごとに複数あり品番ではない。**推測で入れない**)
    """
    u = item.get("official_url") or ((item.get("official") or {}).get("url") or "")
    m = re.search(r"[?&]n=([A-Za-z]\d{4,})", u)
    return m.group(1) if m else ""


def _jan(item: dict) -> str:
    """商品の JAN (EAN-13)。H列の商品説明末尾に入っている。無ければ空。"""
    import gacha_official as _o
    j = _o.jan_from_text(item.get("desc_jp", "") or "")
    return j if len(j) == 13 else ""


def _release_year(released: str) -> str:
    """公式の発売時期 (2024年12月 第2週) → 西暦。取れなければ空。"""
    m = re.search(r"(\d{4})", released or "")
    return m.group(1) if m else ""


def dedup_board_variants(items: list) -> list:
    """同じ商品の「台紙あり/なし」を1本に寄せる (台紙なしを残す)。

    ★2026-08-20 実測: 93行のうち20組が台紙あり/なしの重複。両方出すと
      同じ絵柄で2出品になる。
    """
    out, seen = [], {}
    for it in sorted(items, key=lambda x: (x["series_jp"], x["with_board"])):
        key = (it["series_jp"], it["pieces"])
        if key in seen:
            continue
        seen[key] = True
        out.append(it)
    return out


# ── I/O ────────────────────────────────────────────────────────────


def write_official_urls(items: list, ledger: dict, sheet_id: str, tab: str) -> int:
    """目視画面で人が貼った公式URLを、中間スプシの **I列** に書き戻す (2026-08-20 user 指示)。

    次回以降その行は公式URLを持った状態で回る (毎回貼り直さなくてよい)。
    既に同じ値が入っている行は触らない。失敗しても走行は止めない。
    """
    # ★2026-08-23: 行番号は **タブごと**。まとめて1タブに書くと別の店の行を潰す。
    by_tab = {}
    for it in items:
        u = ((ledger or {}).get(it.get("url", "")) or {}).get("official_url", "").strip()
        if u and u != (it.get("official_url") or "").strip() and it.get("row"):
            by_tab.setdefault(it.get("tab") or tab, []).append((it["row"], u))
    plan = [(r, u) for v in by_tab.values() for r, u in v]
    if not plan:
        return 0
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        import dns_cache                                        # noqa: F401
        import sheet_io as S
        gc = gspread.authorize(Credentials.from_service_account_file(
            S.CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"]))
        sh = gc.open_by_key(sheet_id)
        ws_by_title = {w.title: w for w in sh.worksheets()}
        written = 0
        for t, rows in by_tab.items():
            ws = ws_by_title.get(t)
            if ws is None:
                print(f"  ⚠️ タブ {t} が見つからず書けません ({len(rows)}行)")
                continue
            ws.batch_update([{"range": "I%d" % r, "values": [[u]]} for r, u in rows],
                            value_input_option="RAW")
            written += len(rows)
            print(f"  ✏️ 公式URLを I列に書きました: {t} {len(rows)}行")
        return written
    except Exception as e:                                      # noqa: BLE001
        print("  ⚠️ 公式URLを書けず (走行は継続): %s: %s" % (type(e).__name__, e))
        return 0


def pick_tabs(all_titles, tab: str = "", prefix: str = STAGING_TAB_PREFIX) -> list:
    """読むタブを決める (純関数)。tab 指定があればそれだけ、無ければ前方一致で全部。

    店が増えても両者で名前を書き写さなくて済むように、並べず前方一致にする。
    順番は固定 (実行のたびに変わると I列の書き戻し先が動く)。
    """
    if tab:
        return [t for t in all_titles if t == tab]
    return sorted(t for t in all_titles if t.startswith(prefix))


def read_sheet(sheet_id: str, tab: str = "") -> list:
    """中間スプシを読む。戻りは [{'tab':…, 'row':…, 'cells':[…]}]。

    行番号は **タブごと**に振られているので、どのタブの何行目かを持っていないと
    I列 (公式URL) の書き戻しが別のタブの行を潰す。
    """
    import gspread
    from google.oauth2.service_account import Credentials
    import dns_cache                                            # noqa: F401
    import sheet_io as S
    gc = gspread.authorize(Credentials.from_service_account_file(
        S.CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"]))
    sh = gc.open_by_key(sheet_id)
    titles = [w.title for w in sh.worksheets()]
    want = pick_tabs(titles, tab)
    if not want:
        raise SystemExit(
            f"★中止: 読むタブがありません (指定={tab!r} / 前方一致={STAGING_TAB_PREFIX!r})。"
            f"実在するタブ: {titles}")
    out = []
    for w in sh.worksheets():
        if w.title not in want:
            continue
        vals = w.get_all_values()[1:]
        print(f"  📄 {w.title}: {len(vals)}行")
        for i, row in enumerate(vals, start=2):     # ヘッダ込みの行番号
            out.append({"tab": w.title, "row": i, "cells": row})
    return out


def _api_key() -> str:
    """API key を読む。既存の置き場所 (一番くじ) をそのまま使う (新しい規約を作らない)。"""
    for p in (os.environ.get("ANTHROPIC_API_KEY", ""),):
        if p:
            return p
    f = r"C:\dev\iMak\iMak_ichibankuji\API key.txt"
    if os.path.isfile(f):
        return open(f, encoding="utf-8").read().strip()
    raise SystemExit("★中止: ANTHROPIC_API_KEY が無く 'API key.txt' も読めません")


def load_description() -> str:
    """`iMakHQ/GACHA.txt` を読む。読めなければ **止める**。

    ★2026-08-20: ここは無ければ ICHIBANKUJI.txt を使う作りで、最初の5件は
      一番くじ用の説明文のまま公開された。skill `ebay-csv-listing` に
      「テンプレが読めなければ止める。黙って代替文を使わない」と書いてある通りにする
      (2026-08-12 にダミー説明6件が入稿OKまで通った実害の再発)。
    """
    p = os.path.join(os.path.dirname(SCRIPT_DIR), "GACHA.txt")   # スクリプト基準の絶対パス
    if not os.path.isfile(p):
        raise SystemExit(f"★中止: 説明文テンプレが見つかりません: {p}")
    text = open(p, encoding="utf-8").read()
    # ★2026-08-21: 品目別の文が消えていたら止める。黙って進むと、食玩に
    #   カプセルトイ用の文が付いたまま (または注意節ごと空で) 出てしまう
    for v in VARIANTS:
        if 'data-when="%s"' % v not in text:
            raise SystemExit(f"★中止: {p} に {v} 用の文がありません")
    return text


VARIANTS = ("capsule", "foodtoy")
_VARIANT_TAG = re.compile(r'<(p|li)\b[^>]*\bdata-when="([^"]*)"[^>]*>.*?</\1>', re.S | re.I)


def select_variant(base: str, variant: str) -> str:
    """説明文テンプレから、その品目に当てはまる文だけ残す (純関数)。

    `data-when="capsule"` / `"foodtoy"` の付いた文は一致した方だけ残る。
    属性の無い文は両方に出る。2026-08-21 回答書:
      - 食玩では「カプセルは入れません」「説明書はカプセル内で折れている」を出さない
      - 食玩では冒頭の `All original packaging ... present and intact.` も出さない
        (菓子を抜くため外装を開けるので、同じ説明文の中で矛盾する)
    """
    if variant not in VARIANTS:
        raise ValueError("知らない品目です: %r" % variant)
    out = _VARIANT_TAG.sub(lambda m: m.group(0) if m.group(2).strip() == variant else "",
                           base or "")
    return re.sub(r'\s*\bdata-when="[^"]*"', "", out)


def _age_en(age_jp: str) -> str:
    """公式の対象年齢 (`15才以上`) → `15+`。読めなければ空 (推測しない)。"""
    m = re.search(r"(\d+)\s*[才歳]", age_jp or "")
    return "%s+" % m.group(1) if m else ""


def build_description(item: dict, series_en: str, maker_en: str, base: str) -> str:
    """テンプレに Specifications を差し込む。公式から取れた事実だけを書く。"""
    base = select_variant(base, "foodtoy" if item.get("food_toy") else "capsule")
    off = item.get("official") or {}
    specs = [f"<li><b>Series:</b> {series_en}</li>",
             f"<li><b>Set:</b> Complete Set ({item['pieces']} pcs)</li>"]
    if maker_en:
        specs.insert(1, f"<li><b>Manufacturer:</b> {maker_en}</li>")
    if item.get("character_en"):
        specs.append(f"<li><b>Character:</b> {item['character_en']}</li>")
    specs.append("<li><b>Material:</b> PVC</li>")
    # ★公式の「2022年6月 第4週」をそのまま出していた。買い手は読めないので西暦だけ
    if _release_year(off.get("released")):
        specs.append("<li><b>Released:</b> %s</li>" % _release_year(off.get("released")))
    # ★公式の「15才以上」をそのまま出して **商品説明に日本語が混ざっていた**。
    #   買い手は読めない。数字だけ取って英語表記にする
    if _age_en(off.get("age")):
        specs.append("<li><b>Age Level:</b> %s (manufacturer)</li>" % _age_en(off.get("age")))
    # ★原産国は公式に記載が無い。Item Specifics 側は Does not apply にしたのに
    #   説明文だけ `Japan` と書いたままだった (2026-08-21 に外した)
    if item["with_board"]:
        specs.append("<li><b>Includes:</b> Display board</li>")
    html = ('<p><span style="text-decoration: underline;"><strong>Specifications'
            "</strong></span></p>\n<ul>\n" + "\n".join(specs) + "\n</ul>")
    marker = '<p><span style="text-decoration: underline;"><strong>Shipping'
    return base.replace(marker, html + "\n" + marker, 1) if marker in base else base + html

def _html_escape(s):
    import html as _h
    return _h.escape(str(s or ""))


def price_usd(cost_jpy: int) -> float:
    from pricing_engine import compute_listing_price
    p = round(compute_listing_price(cost_jpy, 0, PROFIT_CATEGORY)["target_usd"], 2)
    return int(p) + 0.98 if p > 10 else p


def schedule_time() -> str:
    t = datetime.datetime.utcnow() + datetime.timedelta(weeks=SCHEDULE_WEEKS)
    return t.strftime("%Y-%m-%d %H:%M:%S")


def build_row(item: dict, en: dict, base_desc: str) -> dict:
    """FileExchange CSV 1行。埋まらない Item Specifics は **空欄**にする (推測で埋めない)。"""
    from listing_common import get_shipping_policy_name
    price = price_usd(item["cost_jpy"])
    off = item.get("official") or {}
    series = en.get("series_en") or ""
    maker = en.get("maker_en") or ""
    # ★タイトルの先頭は **短い英語の題材**。ローマ字のシリーズ名をそのまま置くと
    #   80字に収まらず、題材が語の途中で切れる (`... Frilled` で Lizard が消えた)。
    #   長いシリーズ名は C:Series に残し、タイトルには短く言い直した物を使う
    subject = (en.get("title_subject") or "").strip() or series
    # 題材が長いと、後ろの `Bandai Gashapon` (よく検索される語) が入らなくなる。
    # 6語まで。それ以上は C:Series が持っているので落としてよい
    subject = " ".join(subject.split()[:6])
    title = build_title(subject, item["pieces"], maker, en.get("title_extra") or "",
                        food_toy=bool(item.get("food_toy")))
    return {
        "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)": "Add",
        "*Category": EBAY_CATEGORY,
        "*Title": title,
        "*Description": build_description(item, series, maker, base_desc),
        "PicURL": "|".join(item["pics"][:12]),
        "*StartPrice": price,
        "ConditionID": CONDITION_ID,
        "CustomLabel": supply_sku(item["url"]),
        "ScheduleTime": schedule_time(),
        "*Format": "FixedPrice",
        "*Duration": "GTC",
        "*Quantity": 1,
        "*Location": LOCATION,
        "BestOfferEnabled": 1,
        "ShippingProfileName": get_shipping_policy_name(price, PROFIT_CATEGORY),
        "ReturnProfileName": "customer1",
        "PaymentProfileName": "SALE",
        # ★JAN(13桁) は EAN-13 そのもの。持っているのに "Does not apply" で捨てていた。
        #   eBay が商品を特定できると検索にも効く。取れない物は **項目ごと出さない**
        "Product:EAN": _jan(item),
        "C:Set": "Complete Set",
        "C:Number of Pieces": item["pieces"],
        "C:Material": "PVC",
        # 対象年齢: 公式で確認できた物はその値、無ければ目視で15才以上を確認した物だけ
        "C:Age Level": "15+",
        "C:Type": "Mini Figure",
        "C:Brand": maker,
        "C:Series": series,
        "C:Character": en.get("character_en") or "",
        "C:Franchise": en.get("franchise_en") or "",
        "C:Theme": en.get("theme") or "",
        "C:Genre": en.get("genre") or "",
        "C:Original/Licensed Reproduction": "Original",
        # ★原産国は公式に記載が無い (バンダイ gashapon.jp / タカラトミーアーツ とも)。
        #   カプセルトイは中国・ベトナム製造が普通で、Japan は推測でしかない。
        #   共通ルールどおり「確認できないなら Does not apply」。空欄にすると
        #   eBay が勝手に Japan を補完するので、明示的に入れる
        "C:Country of Origin": "Does not apply",
        # ★品番が取れた物にだけ入れる。取れないなら **項目ごと出さない**
        #   (`Does not apply` を並べても買い手にも eBay にも何も伝わらない。
        #    2026-08-21 ユーザー指示)
        "C:MPN": official_mpn(item),
        # ★eBay の項目名は `Year Manufactured` (一番くじの出品はこれを使っている)。
        #   `Release Year` は存在しない項目名で、フィルタに当たらなかった
        "C:Year Manufactured": _release_year(off.get("released")),
        "C:Color": "Multicolor",
        "StoreCategoryID": STORE_CATEGORY,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", default=STAGING_SHEET_ID)
    ap.add_argument("--tab", default=STAGING_TAB)
    ap.add_argument("--limit", type=int, default=0, help="この件数だけ作る (0=全部)")
    ap.add_argument("--list", action="store_true", help="出せる行を見るだけ (CSV作らない)")
    ap.add_argument("--no-review", action="store_true",
                    help="目視を飛ばす (★検証用。出品に使ってはいけない)")
    ap.add_argument("--no-browser", action="store_true", help="ブラウザを自動で開かない")
    ap.add_argument("--reviewed-only", action="store_true",
                    help="目視で「出品する」と答えた物だけ作る "
                         "(TEST中はここから少しずつ出す。2026-08-20 ユーザー指示)")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                           # noqa: BLE001
        pass

    rows = read_sheet(a.sheet, a.tab)
    print(f"中間スプシ 合計 {len(rows)}行")
    items, blocked = [], {}
    for rec in rows:
        r, n, tab = rec["cells"], rec["row"], rec["tab"]
        t = (r[2].strip() if len(r) > 2 else "")
        why = blocked_reason(t)
        if why:
            blocked[why] = blocked.get(why, 0) + 1
            continue
        if food_toy_mark(r[FOOD_TOY_COL] if len(r) > FOOD_TOY_COL else "") is None:
            why = "S列の印が読めない (食玩か通常か決まらない)"
            blocked[why] = blocked.get(why, 0) + 1
            continue
        it = parse_row(r, n)
        if it:
            it["tab"] = tab          # I列の書き戻しは **そのタブの**その行に返す
            items.append(it)
    for why, n in blocked.items():
        print(f"  ⏭️ 出さない {n}件: {why}")
    before = len(items)
    items = dedup_board_variants(items)
    if before != len(items):
        print(f"  ⏭️ 台紙あり/なしの重複を寄せた: {before} → {len(items)}件")
    print(f"  ✅ 出せる: {len(items)}件")
    if a.reviewed_only:
        import gacha_review as R
        led = R.load_ledger()
        before = len(items)
        items = [it for it in items
                 if (led.get(it.get("url", "")) or {}).get("decision") == "list"]
        print(f"  🔎 目視で「出品する」と答えた物だけ: {before} → {len(items)}件")
    if a.limit:
        items = items[:a.limit]

    if a.list:
        for it in items:
            print(f"   全{it['pieces']}種 ¥{it['cost_jpy']:,} "
                  f"{'[台紙]' if it['with_board'] else '     '} "
                  f"{it['maker_jp'] or '(メーカー不明)'} / {it['series_jp'][:44]}")
        return 0
    if not items:
        print("出せる行が0件 → CSVは作りません")
        return 0

    # ① 公式の商品ページを見に行く (バンダイは JAN から直行できる)
    import gacha_official as O
    n_off = 0
    for it in items:
        it["official"] = O.lookup(it)
        if it["official"].get("name"):
            n_off += 1
            # 公式の商品画像を出品写真に足す (楽天は1枚しか無い)
            it["pics"] = list(dict.fromkeys(it["pics"] + it["official"]["images"][:11]))
    print("  🔎 公式ページが取れた: %d / %d件" % (n_off, len(items)))

    # ② 対象年齢。公式で 15才以上 と確認できた物は目視を飛ばす
    if not a.no_review:
        import gacha_review as R
        need = [it for it in items if needs_review(it)]
        auto = [it for it in items if not needs_review(it)]
        if auto:
            print("  ✅ 対象年齢を公式で確認済 (目視不要): %d件" % len(auto))
        if need:
            ledger = R.run_review(need, open_browser=not a.no_browser)
            for title, why in R.skipped_reasons(need, ledger):
                print("  ⏭️ 出しません: %s — %s" % (title, why))
            items = auto + R.confirmed(need, ledger)
            write_official_urls(need, ledger, a.sheet, a.tab)
        else:
            items = auto
        print("  ✅ 出品に回す: %d件" % len(items))
        if not items:
            print("出せる行が0件 → CSVは作りません")
            return 0

    # ③ 公式+楽天 → 英語の項目 (Character / Franchise / Theme / Genre / タイトル語)
    import gacha_enrich as E
    en_by_url = E.enrich(items, _api_key())
    if not en_by_url:
        print("英語の項目が作れませんでした → CSVは作りません")
        return 1
    base_desc = load_description()
    out, skipped = [], []
    for it in items:
        en = en_by_url.get(it["url"]) or {}
        if not en.get("series_en"):
            skipped.append(it["series_jp"])
            continue                    # シリーズ名が無い = 出さない (推測しない)
        it["character_en"] = en.get("character_en") or ""
        out.append(build_row(it, en, base_desc))
    for x in skipped:
        print("  ⏭️ 英語名が取れず skip: %s" % x[:50])
    if not out:
        print("英語名が取れた行が0件 → CSVは作りません")
        return 1

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR,
                        "gacha_upload_%s.csv" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        w.writerow(list(out[0].keys()))
        for r in out:
            w.writerow(list(r.values()))
    print(f"\n完了: {len(out)}行 → {path}")
    for r in out:
        print(f"  ${r['*StartPrice']:>7} {r['*Title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
