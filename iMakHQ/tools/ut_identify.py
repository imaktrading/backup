#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UT の目視特定 — メルカリの新品 UT を、カタログの商品に **人が** 当てる (2026-09-11)。

ユーザー「PSAと同じように目視で特定させよう」。
目的は「メルカリから、公式では買えない新品未使用を出品する」こと (公式仕入の出品ではない)。

流れ:
  抽出くん → 中間スプシ `mercari_uniqlo_ut` タブ (メルカリ新品・コラボT)
  → この画面: メルカリの写真の横に **カタログの候補を公式画像で並べる** → 人が「この商品 + 色」を選ぶ
  → 商品管理シートに Tシャツ行として足す + 選んだ商品を台帳に残す (出品くんが後でカタログを写す)

守ること (理由付き):
  - **機械で確定しない** (2026-08-22 ユーザー確定)。メルカリのタイトルは「ポケモン UT M」程度で
    同じIPに柄違いが何十種もある。候補は並べるだけで、決めるのは人
    (抽出くんの実測 2026-09-11: タグの6桁番号で当てると 呪術廻戦 に ポケモンUT の番号が付いた例あり)
  - **KEY 列 (AI) には書かない**。出品前の行に KEY があると、重複くんが「出品済み」と読んで
    その商品を止める (orphan KEY 事故)。特定結果は台帳に持ち、KEY は出品した時に付く
  - 商品管理シートへは `sheet_io.append_product_rows` だけで書く (N / AN を踏まない)。
    仕入値は **F列だけ** (skill harvest-targeting「仕入値は F のみ」)。M は監視くんの列
  - 選べなかった物は出さない。「カタログに無い」「対象外(理由)」「保留」で終わる

使い方:
  python ut_identify.py              # 目視画面を開く (既定 20件)
  python ut_identify.py --limit=40
  python ut_identify.py --dry-run    # 画面をファイルに書くだけ (書込なし)
"""
from __future__ import annotations

import argparse
import datetime
import html as _html
import json
import os
import re
import sqlite3
import sys
import unicodedata

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
# ★2026-09-13: `ut_catalog_values` (iMakMercari) を関数の中で import していたが、
#   読み込み先を足していたのは1か所だけだった。cf303e8 で KEY の判定を共通化した時に
#   足し忘れ、**画面を単体で起動すると ModuleNotFoundError で落ちていた**
#   (テストは読み込み先を足して走るので気づけなかった)。最初に1回だけ足す。
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..", "iMakMercari")))

MID_SHEET = "1hTdFVGkni4Ih4kZGsBgiCKxpTlOeoO_wJdk8Ek5n41Q"     # 抽出くんの中間スプシ
SRC_TAB = "mercari_uniqlo_ut"
DB_PATH = r"C:/dev/iMak_data/catalog/products.sqlite"
LEDGER = r"C:/dev/iMak_data/hq/ut_identity.json"
SHEET_CATEGORY = "Tシャツ"          # 商品管理シート R列 (tshirt_listing.py が拾う値)
DEFAULT_LIMIT = 20
MAX_CANDS = 24

# 中間スプシ / 商品管理シート の列 (0始まり)。2つのシートは A..T の並びが同じ
C_URL, C_TITLE, C_SOLD, C_COND, C_PRICE, C_PHOTOS, C_DESC = 0, 2, 3, 4, 5, 6, 7
C_CAT, C_COLOR, C_SIZE = 17, 18, 19
# ★2026-09-11 抽出くんの POC: 目視の材料 (中間スプシだけ。商品管理シートには写さない)
C_KW = 23      # X列 = その行を見つけた検索語 (= カタログのコラボ名)
C_TAG = 24     # Y列 = タグ写真から読めた6桁の番号 (読めた時だけ)
_WIDTH = C_TAG + 1

# 対象外 = そもそも出品の材料にならない (商品も決まらない)。PSA の目視 (newcand_confirm) と語をそろえた
OUT_REASONS = [
    ("used", "中古・難あり"),
    ("not_tee", "別ジャンル (Tシャツではない / UT・GUではない)"),
    ("bundle", "まとめ売り・複数枚"),
    ("kids", "キッズ"),
    ("unclear", "写真で柄が分からない"),
    # ★2026-09-12 ユーザー「PSAの理由を流用できるものは追加して、仕入元売り切れとか」
    ("gone", "仕入元が売り切れ・ページが消えた"),
    ("other", "その他"),
]
# ★見送り = **商品は一致した**が今回は出さない (PSA の「見送り(商品は合っている)」と同じ意味)。
#   「対象外」と混ぜない: 見送りは特定結果 (商品と色) を台帳に残す = 後で出したくなった時に使える
#   (listing_data_is_permanent_asset)。出品行には足さない。
SKIP_REASONS = [
    ("skip_price", "仕入値が高い (利益が出ない)"),
    ("skip_seller", "出品者が不安 (評価・発送)"),
    ("skip_other", "その他"),
]

# メルカリの色 (日本語) → カタログの色名に含まれる語
_COLOR_JP = {"ホワイト": "WHITE", "白": "WHITE", "オフホワイト": "OFF WHITE",
             "ブラック": "BLACK", "黒": "BLACK", "グレー": "GRAY", "グレイ": "GRAY",
             "ネイビー": "NAVY", "紺": "NAVY", "ブルー": "BLUE", "青": "BLUE",
             "レッド": "RED", "赤": "RED", "グリーン": "GREEN", "緑": "GREEN",
             "イエロー": "YELLOW", "黄": "YELLOW", "ピンク": "PINK", "ベージュ": "BEIGE",
             "ブラウン": "BROWN", "茶": "BROWN", "パープル": "PURPLE", "紫": "PURPLE",
             "オレンジ": "ORANGE", "ナチュラル": "NATURAL", "クリーム": "CREAM"}

# 候補を絞る語にしない (どの商品にも付く / 汎用すぎる)
_STOP = {"その他", "ut", "uniqlo", "ユニクロ", "gu", "tシャツ", "t", "グラフィックt", "グラフィック",
         "マンガ", "マンガut", "半袖", "長袖", "レギュラーフィット", "リラックスフィット",
         "オーバーサイズ", "ビッグシルエット", "メンズ", "ウィメンズ", "キッズ", "新品", "未使用",
         "サイズ", "コラボ", "レディース", "タグ付き", "新品未使用", "未開封", "海外限定",
         "ホワイト", "ブラック", "グレー", "ネイビー", "ベージュ", "限定", "日本未発売"}

# メルカリの書き方 → カタログの書き方 (**候補を並べるためだけ**。確定には使わない)
_ALIAS = {"ポケットモンスター": "ポケモン", "pokemon": "ポケモン", "ワンピース": "onepiece",
          "ジョジョ": "ジョジョの奇妙な冒険"}


# ── 純関数 ──────────────────────────────────────────────────────────
def norm(s):
    """照合用に正規化 (全角半角・大小・空白・記号・「(UT)」を揃える)。純関数。"""
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[（(]\s*ut\s*[)）]", "", s)
    return re.sub(r"[\s・･/／×x\-‐_.,、。!！?？'’\"“”:：;；&＆]+", "", s)


def _ok_token(v):
    if not v or v in _STOP:
        return False
    if v.isascii() and len(v) < 3:
        return False
    return len(v) >= 2


def _tokens(p):
    """その商品を指す語。コラボ名・公式コラボ名・キャラ系統・キャラ + **商品名の区切りごと**。

    ★2026-09-11: 呪術廻戦 (「マンガUT 集英社創業100周年 /呪術廻戦」) は collab が空で、
      商品名にしか作品名が無い。コラボ欄だけ見ていたので 78件中 13件が候補なしだった。
    """
    out = set()
    raw = [p.get(k) or "" for k in ("collab", "collab_official_name", "character_family", "character")]
    raw.append(p.get("name") or "")
    for s in raw:
        # 「すみっコぐらし UT グラフィックTシャツ コンプリートセット」は「 UT 」で切って前を採る
        for part in re.split(r"[/／|（()）]|\s+UT(?:\s+|$)", unicodedata.normalize("NFKC", s)):
            v = norm(part)
            # 商品名に付く型の言葉を削る (「すみっコぐらし UT グラフィックTシャツ」→「すみっコぐらし」)
            v = re.sub(r"(ut)?(グラフィック)?(tシャツ|t)?$", "", v)
            v = re.sub(r"^(グラフィックt|マンガut)", "", v)
            v = re.sub(r"ut$", "", v)
            # ★型・付属品の語は当て語にしない (「タグ付き」の「付き」で全商品に当たっていた)
            if any(g in v for g in _GENERIC_PARTS):
                continue
            if _ok_token(v):
                out.add(v)
                # 「ジョジョの奇妙な冒険3」→「ジョジョの奇妙な冒険」も (メルカリは部の番号を書かない)
                base = re.sub(r"\d+$", "", v)
                if base != v and _ok_token(base):
                    out.add(base)
    return out


_GENERIC_PARTS = ("フィット", "半袖", "長袖", "セット", "付き", "ぬいぐるみ", "グラフィック", "tシャツ")


def expand_alias(t):
    """正規化した文字にカタログ側の書き方を足す (候補を並べるためだけ)。純関数。"""
    extra = [v for k, v in _ALIAS.items() if norm(k) in t]
    return t + "|" + "|".join(extra) if extra else t


_JP_WORD = re.compile(r"[ァ-ヶー]{3,}|[一-龥々]{2,}[ァ-ヶー一-龥々]*")


def title_words(text):
    """タイトルの固有名っぽい語 (カタカナ3字以上 / 漢字2字以上)。並び順の手掛かり。純関数。"""
    return {w for w in (norm(x) for x in _JP_WORD.findall(unicodedata.normalize("NFKC", text or "")))
            if _ok_token(w)}


def color_word(jp):
    """メルカリの色 → カタログの色名に含まれる語 (無ければ "")。純関数。"""
    jp = (jp or "").strip()
    for k in sorted(_COLOR_JP, key=len, reverse=True):     # オフホワイト を ホワイト より先に
        if k in jp:
            return _COLOR_JP[k]
    return ""


# 「明らかに違う」の判定に使う近い色の束 (★2026-09-12 ユーザー「色が明らかに違うのは、外せないかな」)。
#   出品者の書き方の揺れ (白 / オフホワイト / ナチュラル 等) で正解を隠さないよう、近い色は同じ扱い
_COLOR_NEAR = {
    "WHITE": ("WHITE", "OFF WHITE", "NATURAL", "CREAM", "IVORY"),
    "OFF WHITE": ("WHITE", "OFF WHITE", "NATURAL", "CREAM", "IVORY"),
    "NATURAL": ("WHITE", "OFF WHITE", "NATURAL", "CREAM", "IVORY", "BEIGE"),
    "CREAM": ("WHITE", "OFF WHITE", "NATURAL", "CREAM", "IVORY", "BEIGE", "YELLOW"),
    "BLACK": ("BLACK",),
    "GRAY": ("GRAY", "GREY", "CHARCOAL"),
    "NAVY": ("NAVY", "BLUE"),
    "BLUE": ("BLUE", "NAVY"),
    "RED": ("RED", "WINE"),
    "GREEN": ("GREEN", "OLIVE"),
    "YELLOW": ("YELLOW", "CREAM"),
    "PINK": ("PINK", "RED"),
    "BEIGE": ("BEIGE", "NATURAL", "CREAM", "BROWN"),
    "BROWN": ("BROWN", "BEIGE"),
    "PURPLE": ("PURPLE",),
    "ORANGE": ("ORANGE",),
}


def color_ok(p, color_jp):
    """メルカリの色と、その商品の色の一覧が **明らかに違わない** か。純関数。

    判らない時は True (隠さない): メルカリの色が空 / 知らない色 / 商品の色の一覧が無い。
    """
    w = color_word(color_jp)
    near = _COLOR_NEAR.get(w)
    names = [c["name"].upper() for c in (p.get("colors") or [])]
    if not near or not names:
        return True
    if any(name in ("OTHER", "MULTI", "MULTICOLOR") for name in names):
        return True                      # 柄物など、色名で判断できない商品は隠さない
    return any(n in name for name in names for n in near)


def pick_color(colors, jp):
    """カタログの色一覧からメルカリの色に合う名前 (無ければ "")。純関数。"""
    w = color_word(jp)
    if not w:
        return ""
    exact = [c["name"] for c in colors if c["name"].upper() == w]
    if exact:
        return exact[0]
    part = [c["name"] for c in colors if w in c["name"].upper()]
    return part[0] if part else ""


def image_for(p, color_name=""):
    """その色の公式画像 (無ければ最初の画像)。純関数。"""
    imgs = p.get("images") or []
    dc = next((c.get("displayCode") for c in p.get("colors") or []
               if c["name"] == color_name), "")
    if dc and p.get("l1"):
        hit = [u for u in imgs if f"_{dc}_{p['l1']}" in u]
        if hit:
            return hit[0]
    return imgs[0] if imgs else ""


def gallery(p, color_name=""):
    """その商品の公式画像を全部 (その色の表 → サブ画像 → 他の色の表)。色見本 (chip) は除く。純関数。

    ★2026-09-12 ユーザー「Tシャツはバックプリントもあるから、画像一枚だけだと見逃しちゃうね」。
      背面がサブ画像のどれに入っているかは商品ごとに違う (sub3/sub6/sub11…) ので、
      決め打ちせず全部並べる。
    """
    imgs = [u for u in (p.get("images") or []) if "/chip/" not in u]
    main = image_for(p, color_name)
    subs = [u for u in imgs if "/sub/" in u]
    others = [u for u in imgs if u != main and u not in subs]
    return ([main] if main else []) + subs + others


def rank_candidates(text, color_jp, catalog, hint_kw="", tag_no="", limit=MAX_CANDS):
    """行の文字 → カタログ候補 (点数順)。**並べるだけで確定はしない**。純関数。

    点: タグの番号が一致 +100 / 抽出くんが使った検索語 = コラボ名 +50 /
        作品・キャラ名がタイトルか説明文にある +10 /
        タイトルの語 (ブラッキー 等) が公式の商品名・説明文にある +5 (語ごと) /
        同じ色がある +3 / 公式売り切れ +2
    語も番号も当たらない商品は並べない (全商品を並べると選べない)。
    """
    t = expand_alias(norm(text))
    kw = norm(hint_kw)
    words = title_words(text)
    out = []
    for p in catalog:
        sc = 0
        toks = p["_tok"]
        # タグの番号は、見つけた語と食い違わない時だけ先頭に上げる
        # (★POC 2026-09-11: 486159 が ウォーホル/バスキア/ヘリング の出品に何度も出た = 誤読)
        if tag_no and p.get("l1") == tag_no and (not kw or kw in toks):
            sc += 100
        if kw and kw in toks:
            sc += 50
        if any(tok in t for tok in toks):
            sc += 10
        if sc == 0:
            continue
        sc += 5 * sum(1 for w in words if w in p.get("_desc", "") and w not in toks)
        if pick_color(p.get("colors") or [], color_jp):
            sc += 3
        if p.get("sold_out"):
            sc += 2
        out.append((sc, p))
    out.sort(key=lambda x: (-x[0], x[1]["pid"]))
    return [p for _sc, p in (out[:limit] if limit else out)]        # limit=0 = 全部


def search_catalog(q, catalog, limit=MAX_CANDS):
    """画面の検索欄 → 名前/コラボ/キャラ/番号 に q を含む商品。純関数。"""
    qn = norm(q)
    if not qn:
        return []
    hits = [p for p in catalog
            if qn == (p.get("l1") or "") or qn in norm(p["name"]) or any(qn in t for t in p["_tok"])]
    hits.sort(key=lambda p: (not p.get("sold_out"), p["pid"]))
    return hits[:limit]


NOCAT_RETRY_DAYS = 7      # カタログ追加依頼を出した行を、もう一度見るまでの日数


def _retry_nocat(entry, today=None):
    """「カタログに無い」で依頼を出した行を、もう一度目視に出す頃か (純関数)。

    ★カタログが追加したら候補が出るようになる。出しっぱなしだと二度と見ないので戻す。
    """
    if (entry or {}).get("decision") != "nocat":
        return False
    try:
        t = datetime.datetime.fromisoformat(entry.get("at") or "")
    except ValueError:
        return True
    return ((today or datetime.datetime.now()) - t).days >= NOCAT_RETRY_DAYS


def pending_rows(src, decided, in_high, today=None):
    """中間タブ → 目視に出す行 [(行番号, row)]。純関数。

    出さない: URL 無し / 売り切れ印 / 台帳で決着済み / 商品管理シートに既にある URL。
    ただし「カタログに無い」で依頼を出した行は NOCAT_RETRY_DAYS 後にまた出す。
    """
    out = []
    for i, r in enumerate(src[1:], start=2):
        r = list(r) + [""] * (_WIDTH - len(r))
        url = (r[C_URL] or "").strip()
        if not url.startswith("http") or (r[C_SOLD] or "").strip():
            continue
        if url in in_high:
            continue
        if url in decided and not _retry_nocat(decided.get(url), today):
            continue
        out.append((i, r))
    return out


C_KEY = 34          # AI列 (canonical KEY)


def _needs_key(r):
    """出品済みだが **カタログの KEY が無い** 行か (純関数)。

    ★2026-09-12 ユーザー「既存出品分にKEY入れないとね」。
      KEY が無いと重複くんも二重出品ガードも効かない。目視で商品を決めれば KEY が入る
      (`ut_key_backfill`)。`item:` / `shops:` で始まる KEY は仕入元URL由来で、カタログの KEY ではない。
    """
    from ut_catalog_values import needs_catalog_key
    return needs_catalog_key(r[C_KEY] if len(r) > C_KEY else "")


def sheet_pending_rows(rows2d, decided, today=None):
    """商品管理シートの **まだ出していない Tシャツ行** → 目視に出す行 [(行番号, row)]。純関数。

    ★2026-09-12 ユーザー「残36件も目視を終えたいね」。中間タブに来る前から
      シートに入っている行 (前の運用で入れた分) も、同じ画面で特定する。
      **仕入元が売り切れた行も出す**: 何の商品かが分かれば資産になり、仕入元は後で探し直せる
      (PSA の「ページが消えていてもカードが分かるなら候補にする」と同じ)。
      出さない: B列に itemID (出品済み) / 台帳で決着済み。
    """
    out = []
    for i, r in enumerate(rows2d[1:], start=2):
        r = list(r) + [""] * (_WIDTH - len(r))
        if (r[C_CAT] or "").strip() != SHEET_CATEGORY:
            continue
        if (r[1] or "").strip() and not _needs_key(r):
            continue                      # 出品済みで KEY もある = もう見なくてよい
        url = (r[C_URL] or "").strip()
        if not url.startswith("http"):
            continue
        if url in decided and not _retry_nocat(decided.get(url), today):
            continue
        out.append((i, r))
    return out


def high_row(r, color_jp=""):
    """中間タブの行 → 商品管理シートに足す行 (A..T)。純関数。

    写すのは 仕入元URL / タイトル / 状態 / 仕入値(F) / 写真 / 説明 / カテゴリ / 色 / サイズ だけ。
    B(itemID) は空 = 出品くんが拾う行。M・N・K と KEY(AI) は書かない。
    """
    row = [""] * (C_SIZE + 1)
    for c in (C_URL, C_TITLE, C_COND, C_PRICE, C_PHOTOS, C_DESC, C_SIZE):
        row[c] = r[c] if c < len(r) else ""
    row[C_COLOR] = color_jp or (r[C_COLOR] if C_COLOR < len(r) else "")
    row[C_CAT] = SHEET_CATEGORY
    return row


def _size_from(text):
    """タイトルからサイズを読む (出品側と同じ判定を使う。決められなければ "")。"""
    try:
        sys.path.insert(0, r"C:\dev\iMak\iMakMercari")
        from ut_catalog_values import jp_size
    except ImportError:
        return ""
    return jp_size(text)


def tag_conflict(tag_no, hint_kw, catalog):
    """タグの番号が指す商品と、見つけた検索語が食い違うか → 警告文 (無ければ "")。純関数。

    ★抽出くんの POC (2026-09-11): 番号が読めた18件中5件で食い違った (Vision の誤読か、
      同じ語で別の商品が引っかかったか)。どちらが正しいかは写真を見ないと決まらない。
    """
    tag_no, kw = (tag_no or "").strip(), norm(hint_kw)
    if not tag_no:
        return ""
    hit = next((p for p in catalog if p.get("l1") == tag_no), None)
    if hit is None:
        return f"タグの番号 {tag_no} はカタログに無い (海外限定・旧作かも)"
    if kw and kw not in hit["_tok"]:
        return (f"タグの番号 {tag_no} は「{hit['name'][:20]}」を指していて、"
                f"見つけた語「{hint_kw}」と食い違う — 写真で確かめる")
    return ""


def parse_result(data):
    """画面の POST → {picks, nocat, outs, holds}。壊れた入力は捨てる。純関数。"""
    def _ints(xs):
        out = []
        for x in xs or []:
            try:
                out.append(int(x))
            except (TypeError, ValueError):
                pass
        return out
    def _picks(key, need_reason=False):
        out = []
        for p in data.get(key) or []:
            try:
                idx = int(p.get("idx"))
            except (TypeError, ValueError, AttributeError):
                continue
            pid, color = (p.get("pid") or "").strip(), (p.get("color") or "").strip()
            reason = (p.get("reason") or "").strip()
            drop = [u.strip() for u in (p.get("drop") or []) if isinstance(u, str) and u.strip()]
            if pid and color and (reason or not need_reason):
                out.append({"idx": idx, "pid": pid, "color": color,
                            **({"reason": reason} if need_reason else {}),
                            **({"drop": drop} if drop else {})})
        return out
    picks = _picks("picks")
    skips = _picks("skips", need_reason=True)
    outs = []
    for o in data.get("outs") or []:
        try:
            outs.append({"idx": int(o.get("idx")), "reason": (o.get("reason") or "").strip()})
        except (TypeError, ValueError, AttributeError):
            continue
    return {"picks": picks, "skips": skips, "nocat": _ints(data.get("nocat")),
            "outs": [o for o in outs if o["reason"]], "holds": _ints(data.get("holds"))}


# ── カタログ ────────────────────────────────────────────────────────
_CATALOG = None
KIDS_GENDERS = {"KIDS", "BABY"}      # 候補に出さない (キッズは出品対象外)


def load_catalog(db=DB_PATH):
    """uniqlo_ut の Tシャツ → 画面で使う形。"""
    global _CATALOG
    if _CATALOG is not None and db == DB_PATH:
        return _CATALOG
    con = sqlite3.connect(db)
    out = []
    # ★GU も入れる (中間タブには GU のコラボT も入る。例: ジョジョ DIO)
    for pid, name, specs, images in con.execute(
            "select product_id, name, specs, images from products where category in ('uniqlo_ut','gu')"):
        try:
            s = json.loads(specs or "{}")
        except ValueError:
            s = {}
        if s.get("not_tee"):
            continue
        # ★2026-09-12 ユーザー「候補にキッズモデルの写真がある。キッズはそもそも対象外」。
        #   抽出くんもキッズは集めない (skill harvest-targeting)。候補に出すと取り違えの元
        if (s.get("gender") or "").strip().upper() in KIDS_GENDERS:
            continue
        # ★2026-09-13 (catalog 依頼 hq/requests/2026-09-13_ut_overseas_official_and_english_name):
        #   その国でしか売っていない品 (米国限定の37件など) は **候補に出さない**。
        #   仕入れは「メルカリ日本の新品未使用」が前提なので、日本の店に並んでいない物は
        #   国内に新品が出てくる経路が無い。候補に混ぜると取り違えの元にしかならない。
        if s.get("region_only") is True:
            continue
        try:
            imgs = json.loads(images or "[]") or s.get("image_urls") or []
        except ValueError:
            imgs = s.get("image_urls") or []
        colors = [{"name": c.get("name") or "", "displayCode": c.get("displayCode") or ""}
                  for c in (s.get("color_variants") or []) if c.get("name")]
        p = {"pid": pid, "name": name or "", "l1": str(s.get("l1_id") or ""),
             "collab": s.get("collab") or "", "collab_official_name": s.get("collab_official_name") or "",
             "character_family": s.get("character_family") or "", "character": s.get("character") or "",
             "gender": s.get("gender") or "", "colors": colors, "images": imgs,
             "sold_out": s.get("in_stock") is not True}
        p["_tok"] = _tokens(p)
        p["_desc"] = norm(" ".join([name or "", s.get("long_description") or "",
                                    s.get("short_description") or ""]))
        out.append(p)
    con.close()
    if db == DB_PATH:
        _CATALOG = out
    return out


# ── 画面 ────────────────────────────────────────────────────────────
def _cards_html(cands, color_jp=""):
    import psa_resource_confirm as prc
    if not cands:
        return ("<div class='warn'>候補なし。下の検索欄に作品名・キャラ名・商品番号(6桁)を"
                "入れると、カタログを引き直します</div>")
    cards = []
    for p in cands:
        dc = pick_color(p["colors"], color_jp)
        img = image_for(p, dc)
        gal = [prc._proxied(u) for u in gallery(p, dc)]
        # サブ画像 (背面・着用) を小さく並べる。押すと上の大きい画像が入れ替わる (カードは選ばない)
        thumbs = "".join(f"<img src='{_html.escape(u)}' loading='lazy' onerror='this.remove()' "
                         f"onclick='swapImg(event,this)'>" for u in gal[1:7])
        cards.append(
            f"<div class='v' data-pid=\"{_html.escape(p['pid'])}\" "
            f"data-colors=\"{_html.escape(json.dumps([c['name'] for c in p['colors']], ensure_ascii=False))}\" "
            f"data-imgs=\"{_html.escape(json.dumps(gal))}\" "
            f"data-raw=\"{_html.escape(json.dumps(gallery(p, dc)))}\" "
            f"data-defcolor=\"{_html.escape(dc)}\" onclick='pickV(this)'>"
            + (f"<img class='main' src='{_html.escape(prc._proxied(img))}' loading='lazy' onerror='imgFail(this)'>"
               if img else "<div class='noimg'>画像なし</div>")
            + (f"<div class='th'>{thumbs}</div>" if thumbs else "")
            + (f"<div class='nm'>画像 {len(gal)}枚 (🔍で全部)</div>" if len(gal) > 1 else "")
            + f"<div class='pid'>{_html.escape(p['pid'])}</div>"
            + f"<div class='nm'>{_html.escape(p['name'][:22])}</div>"
            + f"<div class='nm'>{_html.escape((p['collab'] or p['character_family'])[:18])}</div>"
            + ("" if p.get("sold_out") else
               "<div class='nm' style='color:#a40'>⚠ 公式で今買える (対象外)</div>")
            # ★色の一覧がカタログに無い商品は、選んでも色を決められず出品できない (catalog に確認中)
            + ("" if p["colors"] else "<div class='nm' style='color:#a40'>色がカタログに無い</div>")
            + (f"<div class='nm' style='color:#06a'>色違い {len(p['colors'])}色</div>"
               if len(p["colors"]) > 1 else "")
            + "<button class='zb' onclick='zoom(event,this)' title='メルカリの写真と公式画像を全部並べる'>🔍</button></div>")
    return (f"<div class='one'>カタログ候補 {len(cands)}件 — 柄を見て1つ選んでください</div>"
            f"<div class='vs'>{''.join(cards)}</div>")


_CSS = """
body{font-family:sans-serif;margin:12px;background:#fafafa}
h1{font-size:16px;margin:0 0 6px}.sum{font-size:12px;color:#555;margin-bottom:10px}
.it{background:#fff;border:1px solid #ddd;border-radius:6px;padding:8px;margin-bottom:10px;display:flex;gap:10px}
.it.done{opacity:.45}
.ph{display:flex;flex-direction:column;gap:4px}
.ph img{width:170px;height:220px;object-fit:contain;background:#f4f4f4;border:1px solid #eee}
.ph .sm{display:flex;flex-wrap:wrap;gap:3px;width:172px}.ph .sm img{width:40px;height:52px;object-fit:cover}
.body{flex:1;min-width:0}.t{font-size:13px;font-weight:bold;word-break:break-all}
.meta{font-size:11px;color:#666;margin:2px 0 6px}
.vs{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0}
.v{position:relative;border:1px solid #ccc;border-radius:4px;padding:4px;cursor:pointer;text-align:center;font-size:10px;width:118px}
.v.sel{border-color:#0a7;background:#e7f7f1;box-shadow:0 0 0 1px #0a7 inset}
.v img.main,.noimg{width:106px;height:140px;object-fit:contain;background:#f7f7f7}
.v .th{display:flex;flex-wrap:wrap;gap:2px;justify-content:center;margin:2px 0}
.v .th img{width:33px;height:44px;object-fit:cover;border:1px solid #ddd;cursor:zoom-in}
.noimg{display:flex;align-items:center;justify-content:center;color:#999;border:1px dashed #ccc}
.v .pid{font-weight:bold}.v .nm{color:#666}
.v .zb{position:absolute;top:2px;right:2px;font-size:11px;padding:0 4px}
.one{font-size:12px;color:#076;font-weight:bold}.warn{font-size:12px;color:#a40}
.act{margin-top:6px;display:flex;gap:6px;align-items:center;flex-wrap:wrap;font-size:12px}
button{font-size:12px;padding:3px 10px;border:1px solid #bbb;background:#fff;border-radius:4px;cursor:pointer}
button.go{border-color:#0a7;color:#065}button.go.sel{background:#0a7;color:#fff}
button.cat{border-color:#a60;color:#a60}button.cat.sel{background:#a60;color:#fff}
button.ng{border-color:#c33;color:#900}button.ng.sel{background:#c33;color:#fff}
button.hold.sel{background:#888;color:#fff}
button.skip{border-color:#06a;color:#06a}button.skip.sel{background:#06a;color:#fff}
input.q{font-size:12px;width:170px}select{font-size:12px}
#zov{display:none;position:fixed;inset:0;background:rgba(0,0,0,.88);z-index:99;justify-content:center;gap:16px;padding:10px}
#zov.on{display:flex}
#zov .zcol{width:46vw;height:94vh;overflow-y:auto;display:flex;flex-direction:column;gap:8px}
#zov .zcap{color:#fff;font-size:13px;position:sticky;top:0;background:#222;padding:4px}
#zov .zcol img{width:100%;object-fit:contain;background:#fff}
#zov .zx{position:fixed;top:8px;right:12px;font-size:14px;z-index:100}
.ph .zall{font-size:11px}
.imgpick{margin-top:6px;display:flex;flex-wrap:wrap;gap:3px;align-items:center}
.imgpick{gap:6px}
.imgpick img{width:120px;height:160px;object-fit:contain;background:#fff;border:3px solid #0a7;cursor:pointer}
.imgpick img.off{opacity:.25;border-color:#c33}
.imgpick .sep{width:3px;height:160px;background:#999;margin:0 4px}
.imgpick .zp{font-size:12px;padding:4px 10px}
#zov .zcol img.off{opacity:.25;outline:6px solid #c33}
#zov .zcol img.pk{cursor:pointer}
#go{position:fixed;right:14px;bottom:14px;font-size:15px;padding:10px 20px;background:#0a7;color:#fff;border:none;border-radius:6px}
"""

_JS = """
function imgFail(el){var d=document.createElement('div');d.className='noimg';d.textContent='画像なし';
  if(el.parentNode) el.parentNode.replaceChild(d,el);}
/* 🔍 = メルカリの写真 (左) と、その候補の公式画像 (右) を **全部** 縦に並べて見比べる。
   ★2026-09-12: バックプリントは表の画像1枚では見えない。背面がどのサブ画像かは商品ごとに違う */
function _col(id,cap,urls){var c=document.getElementById(id);
  c.innerHTML="<div class='zcap'>"+cap+" ("+urls.length+"枚)</div>"+urls.map(function(u){
    return "<img src='"+u+"' loading='lazy' onerror='this.remove()'>";}).join('');}
function zoom(ev,el){ev.preventDefault();ev.stopPropagation();var box=el.closest('.it');
  var v=el.closest('.v')||box.querySelector('.v.sel')||box.querySelector('.v');
  var ph=[],ca=[];try{ph=JSON.parse(box.dataset.photos||'[]');}catch(e){}
  try{ca=v?JSON.parse(v.dataset.imgs||'[]'):[];}catch(e){}
  _col('zl','メルカリの写真',ph);_col('zr','カタログ '+(v?v.dataset.pid:'(候補なし)'),ca);
  document.getElementById('zov').classList.add('on');}
function zclose(){document.getElementById('zov').classList.remove('on');}
/* サブ画像を押すと、そのカードの大きい画像を入れ替える (カードは選ばない) */
function swapImg(ev,t){ev.stopPropagation();var m=t.closest('.v').querySelector('img.main');if(m)m.src=t.src;}
document.addEventListener('keydown',function(e){if(e.key==='Escape')zclose();});
/* ★2026-09-12 ユーザー「同じ柄で色違いなんてあり得る? 要らない気もする」:
   1色の商品が 1,958 / 色違いがあるのは 56 (実測)。1色なら押した時点で決め、
   色違いがある商品だけ選ぶ欄を出す (メルカリの色に合う色は最初から選ぶ) */
function fillColors(box,v){var sel=box.querySelector('select.col');var wrap=box.querySelector('.colwrap');var cs=[];
  try{cs=JSON.parse(v.dataset.colors||'[]');}catch(e){}
  if(cs.length===1){sel.innerHTML="<option selected>"+cs[0]+"</option>";wrap.style.display='none';return;}
  sel.innerHTML="<option value=''>色を選ぶ</option>"+cs.map(function(c){
    return "<option"+(c===v.dataset.defcolor?" selected":"")+">"+c+"</option>";}).join('');
  wrap.style.display=cs.length>1?'':'none';}
/* ★2026-09-13 ユーザー確定「メインはカタログ画像。出品者の画像は使うなら最後」。
   並びは固定 (カタログ → 仕入元・最大12枚)。ここでは **使わない画像を押して外すだけ**。
   他の色の表は出品側で自動で外すので、ここに出す必要はない */
function showImgs(box){var v=box.querySelector('.v.sel');var s=box.querySelector('.imgpick');
  if(!s||!v){return;}var cr=[],pr=[];
  try{cr=JSON.parse(v.dataset.raw||'[]');}catch(e){}try{pr=JSON.parse(box.dataset.rawphotos||'[]');}catch(e){}
  var ca=[],ph=[];try{ca=JSON.parse(v.dataset.imgs||'[]');}catch(e){}try{ph=JSON.parse(box.dataset.photos||'[]');}catch(e){}
  function tile(u,raw,src){return "<img src='"+u+"' data-src='"+src+"' data-raw='"+(raw||'').replace(/'/g,'%27')+"' onclick='togImg(event,this)' onerror='this.remove()' title='押すと 使わない/使う'>";}
  var h="<div style='width:100%'><span class='nm'>出品に使う画像 (カタログ → 仕入元・最大12枚) — 使わない物を押す</span> "
    +"<button class='zp' onclick='zoomPick(event,this)'>🔍 大きくして選ぶ</button></div>";
  ca.forEach(function(u,i){h+=tile(u,cr[i],'cat');});h+="<span class='sep'></span>";
  ph.forEach(function(u,i){h+=tile(u,pr[i],'sel');});s.innerHTML=h;}
function togImg(ev,el){ev.stopPropagation();el.classList.toggle('off');}
/* ★2026-09-13 ユーザー「画像が小さすぎて判断しづらい」: 画面いっぱいに並べ、そこで押しても外せる
   (押した結果は下の小さい画像と連動する) */
function zoomPick(ev,btn){ev.preventDefault();ev.stopPropagation();var box=btn.closest('.it');
  var ts=[].slice.call(box.querySelectorAll('.imgpick img'));
  function col(id,cap,list){var c=document.getElementById(id);
    c.innerHTML="<div class='zcap'>"+cap+" ("+list.length+"枚) — 押すと 使わない / 使う</div>";
    list.forEach(function(t){var im=document.createElement('img');im.src=t.src;im.className='pk';
      if(t.classList.contains('off'))im.classList.add('off');
      im.onclick=function(e){e.stopPropagation();t.classList.toggle('off');im.classList.toggle('off');};
      c.appendChild(im);});}
  col('zl','カタログ',ts.filter(function(t){return t.dataset.src==='cat';}));
  col('zr','仕入元の写真',ts.filter(function(t){return t.dataset.src==='sel';}));
  document.getElementById('zov').classList.add('on');}
function pickV(el){var box=el.closest('.it');
  box.querySelectorAll('.v').forEach(function(v){v.classList.remove('sel');});
  el.classList.add('sel');box.dataset.pid=el.dataset.pid;fillColors(box,el);showImgs(box);
  setAct(box.querySelector('button.go'));}
function lookup(inp){var box=inp.closest('.it');var q=inp.value.trim();
  if(!q||q===inp.dataset.asked)return;inp.dataset.asked=q;var slot=box.querySelector('.vslot');
  slot.innerHTML="<div class='one'>カタログを引いています… ("+q+")</div>";
  fetch('/api/search?q='+encodeURIComponent(q)+'&color='+encodeURIComponent(box.dataset.color||''))
   .then(function(r){return r.json();}).then(function(d){slot.innerHTML=d.html||'';})
   .catch(function(e){slot.innerHTML="<div class='warn'>引けませんでした ("+e+")</div>";});}
/* 理由を選んだら、その理由の種類 (対象外 / 一致・見送り) のボタンに確定する */
function pickRsn(sel){if(!sel.value)return;
  var a=sel.value.indexOf('skip_')===0?'skip':'out';
  setAct(sel.closest('.it').querySelector("button[data-a='"+a+"']"));}
function setAct(btn){var box=btn.closest('.it');
  box.querySelectorAll('.act button').forEach(function(b){b.classList.remove('sel');});
  btn.classList.add('sel');box.dataset.act=btn.dataset.a;
  var s=box.querySelector('select.rsn');
  if(s){var isSkip=s.value.indexOf('skip_')===0;
    if(btn.dataset.a==='out'&&isSkip)s.value='';
    if(btn.dataset.a==='skip'&&s.value&&!isSkip)s.value='';
    if(btn.dataset.a!=='out'&&btn.dataset.a!=='skip')s.value='';}
  box.classList.toggle('done',btn.dataset.a!=='go');}
function go(){var picks=[],skips=[],nocat=[],outs=[],holds=[],nocolor=0,noreason=0;
  document.querySelectorAll('.it').forEach(function(b){var a=b.dataset.act||'';var idx=parseInt(b.dataset.idx,10);
    var c=(b.querySelector('select.col')||{}).value||'';var r=(b.querySelector('select.rsn')||{}).value||'';
    if(a==='go'){
      var drop=[];b.querySelectorAll('.imgpick img.off').forEach(function(i){if(i.dataset.raw)drop.push(decodeURIComponent(i.dataset.raw));});
      if(!b.dataset.pid||!c){nocolor++;holds.push(idx);}else{picks.push({idx:idx,pid:b.dataset.pid,color:c,drop:drop});}}
    else if(a==='skip'){
      if(!b.dataset.pid||!c){nocolor++;holds.push(idx);}
      else if(r.indexOf('skip_')!==0){noreason++;holds.push(idx);}
      else{skips.push({idx:idx,pid:b.dataset.pid,color:c,reason:r});}}
    else if(a==='cat'){nocat.push(idx);}
    else if(a==='out'){
      if(!r||r.indexOf('skip_')===0){noreason++;holds.push(idx);}else{outs.push({idx:idx,reason:r});}}
    else{holds.push(idx);}});
  var msg='出品行に追加 '+picks.length+'件 / 一致・見送り '+skips.length+'件 / カタログに無い '+nocat.length
    +'件 / 対象外 '+outs.length+'件 / 未結論 '+holds.length+'件';
  if(nocolor)msg+='\\n\\n商品か色が未選択 '+nocolor+'件 — 未結論に戻します';
  if(noreason)msg+='\\n\\n対象外/見送りなのに理由が未選択 '+noreason+'件 — 未結論に戻します';
  if(!confirm(msg+'\\n\\nこの内容で確定しますか?'))return;
  _send({picks:picks,skips:skips,nocat:nocat,outs:outs,holds:holds},
        '<h1>確定しました。ウィンドウを閉じてください。</h1>');}
"""


def build_html(items, catalog):
    """items → 目視ページ (bytes)。"""
    import psa_resource_confirm as prc
    import newcand_confirm as NC
    save_js = NC.SAVE_JS.replace("'imak_confirm_draft_'+location.port", "'imak_confirm_draft_ut_identify'")
    parts = ["<!doctype html><meta charset='utf-8'><title>UT 目視特定</title>",
             f"<style>{_CSS}</style>",
             "<h1>メルカリの新品 UT → カタログの商品を選ぶ</h1>",
             f"<div class='sum'>全 {len(items)}件。写真と同じ柄の商品を選んで「この商品」"
             "(同じ柄で色違いがある商品だけ、色を選ぶ欄が出ます)。"
             "候補は<b>公式で買えない物だけ</b>。無ければ検索欄に作品名・キャラ名・商品番号(6桁)。"
             "<b>確信が無ければ選ばない</b> (違う柄を出すと別デザイン発送になります)。</div>"]
    for it in items:
        r = it["row"]
        photos = [u for u in (r[C_PHOTOS] or "").split("|") if u.strip()]
        main = prc._proxied(photos[0]) if photos else ""
        # メルカリの写真は全部 (背面の写真が2枚目以降にあることが多い)
        sm = "".join(f"<a href='{_html.escape(r[C_URL])}' target='_blank'>"
                     f"<img src='{_html.escape(prc._proxied(u))}' loading='lazy' onerror='imgFail(this)'></a>"
                     for u in photos[1:10])
        ph = (f"<div class='ph'><a href='{_html.escape(r[C_URL])}' target='_blank'>"
              f"<img src='{_html.escape(main)}' loading='lazy' onerror='imgFail(this)'></a>"
              f"<div class='sm'>{sm}</div>"
              "<button class='zall' onclick='zoom(event,this)'>🔍 全部の写真を並べて見比べる</button></div>")
        photos_json = json.dumps([prc._proxied(u) for u in photos[:10]])
        price = f"¥{int(r[C_PRICE]):,}" if str(r[C_PRICE]).isdigit() else (r[C_PRICE] or "")
        parts.append(
            f"<div class='it' data-idx='{it['idx']}' data-pid='' data-color=\"{_html.escape(r[C_COLOR])}\" "
            f"data-photo=\"{_html.escape(main)}\" data-photos=\"{_html.escape(photos_json)}\" "
            f"data-rawphotos=\"{_html.escape(json.dumps(photos[:10]))}\">"
            f"{ph}<div class='body'>"
            f"<div class='t'>{_html.escape((r[C_TITLE] or '')[:110])}</div>"
            f"<div class='meta'>{_html.escape(price)} ｜ 色 {_html.escape(r[C_COLOR] or '?')} ｜ "
            f"サイズ {_html.escape(r[C_SIZE] or '?')}"
            + (" ｜ <b>出品待ちの行</b>" if it.get("src") == "sheet" and not (r[1] or "").strip()
               else "")
            + (f" ｜ <b style='color:#06a'>出品中 ({_html.escape((r[1] or '').strip())}) "
               "— KEY を入れるための特定</b>" if (r[1] or "").strip() else "")
            + (" ｜ <b style='color:#a40'>仕入元は売り切れ済み</b> (商品が分かれば後で探し直せる)"
               if (r[C_SOLD] or "").strip() else "")
            + (f" ｜ 見つけた語 <b>{_html.escape(r[C_KW])}</b>" if r[C_KW] else "")
            + (f" ｜ タグの番号 <b>{_html.escape(r[C_TAG])}</b>" if r[C_TAG] else "")
            + f" ｜ {_html.escape((r[C_DESC] or '')[:80])}</div>"
            + (f"<div class='warn'>⚠ {_html.escape(it['warn'])}</div>" if it.get("warn") else "")
            + (f"<div class='nm' style='font-size:11px;color:#666'>色が明らかに違う候補 "
               f"{it['hidden_color']}件を隠しました (出品者の色の書き違いなら 検索欄で全部出ます)</div>"
               if it.get("hidden_color") else "")
            + (f"<div class='nm' style='font-size:11px;color:#666'>公式で今買える候補 "
               f"{it['hidden_instock']}件を隠しました (公式で買えない物だけが対象)</div>"
               if it.get("hidden_instock") else "")
            + f"<div class='vslot'>{_cards_html(it['cands'], r[C_COLOR])}</div>"
            "<div class='imgpick'></div>"
            "<div class='act'>検索 <input class='q' placeholder='作品名 / キャラ / 6桁番号' "
            "onchange='lookup(this)'>"
            "<span class='colwrap' style='display:none'>色違いあり → 色 "
            "<select class='col'><option value=''></option></select></span>"
            "<button class='go' data-a='go' onclick='setAct(this)'>この商品</button>"
            "<button class='skip' data-a='skip' onclick='setAct(this)' "
            "title='商品と色は合っているが、今回は出さない (高い / 出品者が不安)'>一致・見送り</button>"
            "<button class='cat' data-a='cat' onclick='setAct(this)' "
            "title='カタログに追加依頼を出す。追加されたら1週間後にまたこの画面に出ます'>"
            "カタログに無い→追加依頼</button>"
            "<button class='ng' data-a='out' onclick='setAct(this)'>対象外</button>"
            "<select class='rsn' onchange='pickRsn(this)'><option value=''>理由を選ぶ</option>"
            "<optgroup label='対象外 (商品が決まらない・材料にならない)'>"
            + "".join(f"<option value='{k}'>{_html.escape(v)}</option>" for k, v in OUT_REASONS)
            + "</optgroup><optgroup label='一致・見送り (商品と色は合っている)'>"
            + "".join(f"<option value='{k}'>{_html.escape(v)}</option>" for k, v in SKIP_REASONS)
            + "</optgroup></select><button class='hold' data-a='hold' onclick='setAct(this)'>保留</button>"
            "</div></div></div>")
    parts.append("<div id='zov' onclick='if(event.target===this)zclose()'>"
                 "<div class='zcol' id='zl'></div><div class='zcol' id='zr'></div>"
                 "<button class='zx' onclick='zclose()'>× 閉じる (Esc)</button></div>")
    parts.append(f"<button id='go' onclick='go()'>確定</button><script>{save_js}{_JS}</script>")
    return "".join(parts).encode("utf-8")


def lookup_api(path, query, catalog=None):
    """画面の検索欄 → 候補カードの HTML。"""
    if path != "/api/search":
        return None
    catalog = catalog if catalog is not None else load_catalog()
    hits = search_catalog(query.get("q") or "", catalog)
    return {"n": len(hits), "html": _cards_html(hits, query.get("color") or "")}


# ── 読み書き (I/O) ──────────────────────────────────────────────────
CATALOG_REQ_DIR = r"C:/dev/iMak_data/catalog/requests"


def request_md(rows, today=None, existing=""):
    """「カタログに無い」行 → カタログへの追加依頼書 (純関数)。

    ★PSA の目視と同じ着地: 「該当なし」で捨てずに **カタログ追加依頼**にする。
      UT は型番が読めないことが多いので、PSA の自動起票 (missing_models.csv = 型番前提) には
      乗せず、商品名・写真・仕入元URLを並べた依頼書を出す。
    existing: 同じ日の依頼書が既にある時はその本文 (同じ URL は二度書かない)。
    """
    today = today or datetime.date.today()
    have = set(re.findall(r"https?://\S+", existing))
    new = [r for r in rows if (r.get("url") or "") not in have]
    if not new:
        return ""
    head = existing or (
        f"# 依頼: メルカリで見つけた UT/GU が カタログに無い ({today:%Y-%m-%d})\n\n"
        f"- 依頼日 {today:%Y-%m-%d} / 依頼者 出品くん (UT 目視特定) / 緊急度 低 / フェーズ: 追加\n"
        "- 判定: ①カタログのデータ (公式に在ったはずの商品がカタログに無い)\n\n"
        "## 経緯\n\n"
        "メルカリの新品 UT を目視でカタログの商品に当てる画面 (`iMakHQ/tools/ut_identify.py`) で、\n"
        "**カタログに候補が無かった**行です。海外限定・旧作・GU など、公式の検索に出ない物が多いはずです。\n"
        "**分かる範囲で構いません。** 無い物は「無い」と返してください (出品側はその行を出しません)。\n\n"
        "## 見つからなかった商品\n\n"
        "| メルカリのタイトル | 色 | サイズ | タグの番号 | 見つけた語 | 仕入元 | 写真 |\n"
        "|---|---|---|---|---|---|---|\n")
    body = "".join(
        "| {title} | {color} | {size} | {tag} | {kw} | {url} | {photo} |\n".format(
            title=(r.get("title") or "").replace("|", "／")[:60],
            color=r.get("color") or "", size=r.get("size") or "",
            tag=r.get("tag") or "-", kw=r.get("kw") or "-",
            url=r.get("url") or "", photo=r.get("photo") or "-")
        for r in new)
    return head + body


def write_catalog_request(rows, dir_path=CATALOG_REQ_DIR, today=None):
    """依頼書を書く (同じ日の分は追記)。戻り: (path, 追加件数)。書けなければ (None, 0)。"""
    if not rows:
        return None, 0
    today = today or datetime.date.today()
    path = os.path.join(dir_path, f"{today:%Y-%m-%d}_ut_not_in_catalog.md")
    try:
        existing = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
        md = request_md(rows, today, existing)
        if not md:
            return path, 0
        os.makedirs(dir_path, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(md)
        return path, md.count("\n| ") if not existing else len(rows)
    except OSError as e:                                           # noqa: BLE001
        print(f"  ⚠ カタログ依頼書を書けませんでした ({e}) — 台帳には残っています")
        return None, 0


def load_ledger(path=LEDGER):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_ledger(led, path=LEDGER):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(led, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _read_src():
    import sheet_io
    return sheet_io.read_tab(SRC_TAB, sheet_id=MID_SHEET)


SHEET_IDX_BASE = 1000000     # 画面の通し番号: 中間タブ = 行番号 / 商品管理シート = これ + 行番号


def _product_values():
    import sheet_io
    return sheet_io._product_ws().get_all_values()


def _high_urls(rows2d=None):
    rows2d = rows2d if rows2d is not None else _product_values()
    return {(r[C_URL] or "").strip() for r in rows2d[1:] if (r[C_URL] or "").strip()}


# ★2026-09-13 ユーザー「中間スプシから売れ筋をピックアップして HIGHT に転記し、出品に乗せる」。
#   売れ筋の順位は既に毎晩作っている (`ut_demand_words.py` → 抽出くんの検索順)。
#   目視の画面はそれを見ておらず、中間スプシの行順のままだった。同じ順位を使って並べる。
DEMAND_PATH = r"C:/dev/iMak_data/harvest/ut_demand_words.json"


def load_demand(path=DEMAND_PATH):
    """売れ筋の作品 → [[名前, …], …] 点数の高い順 (I/O。読めなければ空 = 今までの順)。"""
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:                                          # noqa: BLE001
        return []
    works = (d.get("works") if isinstance(d, dict) else d) or []
    works = sorted(works, key=lambda w: -(w.get("score") or 0))
    out = []
    for w in works:
        names = [n for n in (w.get("collab_jp"), w.get("work_en")) if norm(n or "")]
        if names and (w.get("score") or 0) > 0:
            out.append(names)
    return out


def demand_rank(r, demand):
    """その行が売れ筋の何位の作品か (純関数)。当たらなければ末尾 = len(demand)。

    見るのは X列 (見つけた検索語) とタイトル。**並べる順番にしか使わない**
    (作品を決めるのは人。ここで商品を確定しない)。
    """
    text = norm(" ".join([(r[C_KW] if len(r) > C_KW else "") or "",
                          (r[C_TITLE] if len(r) > C_TITLE else "") or ""]))
    for n, names in enumerate(demand or []):
        if any(norm(x) in text for x in names):
            return n
    return len(demand or [])


def order_rows(rows, demand=None):
    """目視に出す順番 (純関数・test 可)。

    ★2026-09-12 ユーザー「既存へのKEYは、全て完了したの？」→ 実測 **0件 / 出品済み79行**。
      原因は順番。画面は中間タブ (集めた新しい行) を先に出しており、そこに98件 溜まっているので
      **出品済みの行が一度も画面に出てこなかった**。

      出品済みで KEY が無い行を先に出す。理由は「まだ出していない行」より危ないから:
        - 既に売れる状態で出ている。KEY が無い = 重複くんから見えない = 同じ物をもう一度
          出してしまう (fail-OPEN)
        - 目視すれば KEY が入り、補URL・再仕入れ・監視の対象にもなる (資産になる)
      まだ出していない行は、遅れても「出品が1日後になる」だけで、危険側には倒れない。

    ★2026-09-13: その次は **売れ筋の作品から** (demand = load_demand())。
      順番: ①出品済みで KEY が無い行 → ②売れ筋の作品 (点数順) → ③それ以外 (元の順)
    """
    def rank(t):
        _i, r, src = t
        listed = len(r) > 1 and (r[1] or "").strip()
        if src == "sheet" and listed:
            return (0, 0)
        return (1, demand_rank(r, demand))
    return sorted(rows, key=rank)


def only_new(rows):
    """出品済みの行 (KEY 埋め) を外し、**新しく出す候補だけ**にする (純関数)。

    ★2026-09-13 ユーザー「目視が入るから、自動で動かそう」: 🤖自動 は出品のためのボタン。
      KEY 埋め (出品済み79件) が先頭に並ぶので、そのままだと最初の数回は出品0件になる。
      KEY 埋めは手動の 🩹 UT 新品 目視特定 に残す。
    """
    return [t for t in rows
            if not (t[2] == "sheet" and len(t[1]) > 1 and (t[1][1] or "").strip())]


def load_items(limit=DEFAULT_LIMIT, new_only=False):
    led = load_ledger()
    prod = _product_values()
    # ★2026-09-12: 中間タブ (抽出くんが集めた分) と 商品管理シートの **まだ出していない Tシャツ行**
    #   (前の運用で入った分) の両方を目視に出す
    rows = [(i, r, "tab") for i, r in pending_rows(_read_src(), led, _high_urls(prod))]
    rows += [(SHEET_IDX_BASE + i, r, "sheet") for i, r in sheet_pending_rows(prod, led)]
    if new_only:
        rows = only_new(rows)
    rows = order_rows(rows, load_demand())
    catalog = load_catalog()
    items = []
    for i, r, _src in rows[:limit] if limit else rows:
        text = " ".join([r[C_TITLE], r[C_DESC]])
        allc = rank_candidates(text, r[C_COLOR], catalog, hint_kw=r[C_KW], tag_no=r[C_TAG],
                               limit=0)
        # 色が明らかに違う候補は隠す (件数は画面に出す。検索欄では色で絞らない)
        keep = [p for p in allc if color_ok(p, r[C_COLOR])]
        # ★2026-09-12 ユーザー「公式で買えないものだけに対象を絞ってほしい」:
        #   公式で今買える商品は、メルカリから仕入れて出す物ではない (目的は「公式では買えない物」)
        oos = [p for p in keep if p.get("sold_out")]
        items.append({"idx": i, "row": r, "src": _src, "cands": oos[:MAX_CANDS],
                      "hidden_color": len(allc) - len(keep),
                      "hidden_instock": len(keep) - len(oos),
                      "warn": tag_conflict(r[C_TAG], r[C_KW], catalog)})
    return items, len(rows)


def count_workload():
    """パネルの残件 (出品くんは叩かない。スプシ2つとローカルの台帳だけ)。"""
    try:
        led, prod = load_ledger(), _product_values()
        n = len(pending_rows(_read_src(), led, _high_urls(prod))) + len(sheet_pending_rows(prod, led))
        return {"pending": n, "error": ""}
    except Exception as e:                                         # noqa: BLE001
        return {"pending": 0, "error": f"{type(e).__name__}: {e}"[:60]}


def save(items, res, now=None):
    """確定した内容を書く → (追加した行数, 台帳に残した数)。

    ★順番: **商品管理シートに足してから台帳**。先に台帳だと、シートへの追加が失敗した行が
      「決着済み」になって二度と画面に出ない (silent drop)。
    """
    import sheet_io
    now = now or datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    by_idx = {it["idx"]: it for it in items}
    catalog = {p["pid"]: p for p in load_catalog()}
    led = load_ledger()
    in_high = _high_urls()
    add_rows, add_led = [], {}
    for p in res["picks"]:
        it = by_idx.get(p["idx"])
        if not it or p["pid"] not in catalog:
            continue                                   # 画面に無い行 / カタログに無い pid は書かない
        r = it["row"]
        url = r[C_URL].strip()
        # 商品管理シートから出した行は、もうシートに在る = 足さない (二重行を作らない)
        if it.get("src") != "sheet" and url not in in_high:
            add_rows.append(high_row(r))
            in_high.add(url)
        # サイズ欄が空の出品はタイトルから読む (決められない時は空のまま = 出品側で止まる)
        add_led[url] = {"decision": "go", "product_id": p["pid"], "color": p["color"],
                        "title": r[C_TITLE], "size": r[C_SIZE] or _size_from(r[C_TITLE]),
                        "at": now, **({"img_drop": p["drop"]} if p.get("drop") else {})}
    for p in res.get("skips") or []:
        it = by_idx.get(p["idx"])
        if not it or p["pid"] not in catalog:
            continue
        r = it["row"]
        # 商品は一致したが今回は出さない。**特定結果は残す** (出品行には足さない)
        add_led[r[C_URL].strip()] = {"decision": "skip", "product_id": p["pid"], "color": p["color"],
                                     "reason": p["reason"], "title": r[C_TITLE], "size": r[C_SIZE],
                                     "at": now}
    req_rows = []
    for idx in res["nocat"]:
        it = by_idx.get(idx)
        if not it:
            continue
        r = it["row"]
        photos = [u for u in (r[C_PHOTOS] or "").split("|") if u.strip()]
        req_rows.append({"url": r[C_URL].strip(), "title": r[C_TITLE], "color": r[C_COLOR],
                         "size": r[C_SIZE], "tag": r[C_TAG], "kw": r[C_KW],
                         "photo": photos[0] if photos else ""})
        add_led[r[C_URL].strip()] = {"decision": "nocat", "title": r[C_TITLE], "at": now}
    for o in res["outs"]:
        it = by_idx.get(o["idx"])
        if it:
            add_led[it["row"][C_URL].strip()] = {"decision": "out", "reason": o["reason"],
                                                 "title": it["row"][C_TITLE], "at": now}
    if add_rows:
        sheet_io.append_product_rows(add_rows)         # 失敗したら例外 = 台帳は書かない
    # カタログに無い分は追加依頼にする (置き場は呼び出し時に読む = test で差し替えられる)
    req_path, n_req = write_catalog_request(req_rows, CATALOG_REQ_DIR)
    if n_req:
        print(f"  📮 カタログに追加依頼: {n_req}件 → {os.path.basename(req_path)}")
    led.update(add_led)
    save_ledger(led)
    return len(add_rows), len(add_led)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--timeout", type=int, default=10800)
    ap.add_argument("--new-only", action="store_true",
                    help="出品済みの行 (KEY 埋め) を出さない。🤖自動 から呼ぶ時に使う")
    a = ap.parse_args()
    items, n_all = load_items(a.limit, new_only=a.new_only)
    n_listed = sum(1 for it in items
                   if it.get("src") == "sheet" and (it["row"][1] or "").strip())
    print(f"目視に出す UT: {len(items)}件 (残り全部で {n_all}件)")
    if n_listed:
        print(f"  うち **出品済みなのに KEY が無い行** {n_listed}件 (先に出しています。"
              f"KEY が無いと重複くんが二重出品を止められません)")
    _dem = load_demand()
    n_hot = sum(1 for it in items if not (it.get("src") == "sheet" and (it["row"][1] or "").strip())
                and demand_rank(it["row"], _dem) < len(_dem))
    if n_hot:
        print(f"  うち **売れ筋の作品** {n_hot}件 ("
              + ("先に出しています)" if a.new_only or not n_listed else "その次に出しています)"))
    if not items:
        print("→ 0件。抽出くんの収集 (mercari_uniqlo_ut タブ) に新しい行が入ったらまた出ます")
        return 0
    n_c = sum(1 for it in items if it["cands"])
    print(f"  カタログ候補が並ぶ {n_c}件 / 候補なし (検索欄で探す) {len(items) - n_c}件")
    page = build_html(items, load_catalog())
    if a.dry_run:
        out = os.path.join(os.environ.get("TEMP", _HERE), "ut_identify_preview.html")
        with open(out, "wb") as f:
            f.write(page)
        print(f"(dry-run) 画面だけ書きました: {out}")
        return 0
    import psa_resource_confirm as prc
    res = prc._serve_confirm(page, parse_result, a.timeout, api=lookup_api)
    if res is None:
        print("⚠ 確定されませんでした (時間切れ / 画面を閉じた)。何も書いていません")
        return 1
    n_add, n_led = save(items, res)
    print(f"✅ 商品管理シートに追加 {n_add}件 (Tシャツ行・出品くんが拾う) / 台帳に記録 {n_led}件")
    print(f"   内訳: この商品 {len(res['picks'])} / 一致・見送り {len(res['skips'])} / "
          f"カタログに無い→追加依頼 {len(res['nocat'])} / "
          f"対象外 {len(res['outs'])} / 未結論 {len(res['holds'])} (未結論は次回また出ます)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
