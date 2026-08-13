#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""捨てた仕入候補を「新規出品の種」に戻す 目視HTML (2026-08-13)。

■ 何のためか
補URL確証で「①違う(別商品)」を押した候補は `補URL候補NG` に、「②要調査」は `補URL要調査` に
記録されるだけで、**その後どこにも使われていなかった**。だが「違う」が意味するのは
「**その出品のカードではない**」だけで、**別の実在カードの仕入元URL**であることが多い。
= 出品していないカードの供給を毎日捨てていた。

■ そのまま出品に回してはいけない理由
「違う」は *何のカードか* を何も言っていない。検索が外した推測のまま出品すると誤出品になる。
なので **同定はゼロからやり直す**: 候補タイトルからカード番号を取り、catalog で版を引き、
**版が複数ある時だけ人が絵柄で選ぶ**。決まらなければ出品しない (fail-closed)。

■ 実測 (2026-08-13 / `補URL候補NG` 142件)
  候補タイトルが復元できた   111件  (探索 cache `psa_research_cache.json` に残っていた)
  カード番号が取れた          95件
    → catalog で1つに決まる   86件   ← 目視すら不要
    → 複数版あり(絵柄で選ぶ)   2件
    → catalog に無い           7件
つまり目視が要るのはごく一部で、大半は機械で決まる。

■ 出力
  - `新規出品候補` タブ: 確定した候補 (url / category / product_id / cert / タイトル / 元itemID / 日付)
  - `新規候補NG`   タブ: 「該当なし」を押した候補 (次回出さない)
  ★商品管理シート本体への行追加は**まだしない**。本体への append は不可逆なので、
    このタブを人が見てから別途 GO を出す運用にする。
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:                                         # Windows 既定 cp932 だと絵文字/記号で落ちる
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import psa_resource_confirm as prc          # noqa: E402  (_proxied / _serve_confirm を再利用)
import sheet_io                              # noqa: E402

CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "psa_research_cache.json")
DB_PATH = r"C:/dev/iMak_data/catalog/products.sqlite"

SRC_TABS = ("補URL候補NG", "補URL要調査")
OUT_TAB = "新規出品候補"
# ★2026-08-13 ユーザー確定「商品管理シートへの追加は危険やから、どこかに保管されていたら
#   コピペする」。なので **貼り付け先の列名をそのまま見出しにする**。
#   商品管理シート: A=仕入元URL / B=itemID(出品後に入る=空のまま) / C=タイトル /
#                   I=cert / R=カテゴリ('TCG') / AI=canonical KEY
OUT_HEADER = ["用途", "HIGH転記", "A列:仕入元URL", "C列:タイトル", "M列:仕入価格(円)",
              "I列:cert", "R列:カテゴリ", "AI列:KEY", "product_id", "元itemID", "日付"]
# ★2026-08-13 ユーザー指摘「価格がないけど大丈夫かな」。大丈夫ではない:
#   商品管理シートに **価格(M/F/N)が無い行は、出品くんが $100 固定**で値付けする
#   (`_cost_plus_price(None)` → 100.00)。¥40,000 のカードが $100 で出たら大赤字。
#   候補の価格は分かっているので M列(現在価格) 用に出す。M は監視くんが毎cycle
#   最安で上書きする列なので、seed として入れておけば以降は自動追随する。
# ★2026-08-13 ユーザー指摘「HIGHへコピーしたかどうか分からなくない?」。
#   商品管理シートの A列(仕入元URL) と突き合わせて **自動で印を付ける** (手でチェックしない)。
OUT_URL_COL, OUT_KEY_COL, OUT_DONE_COL = 2, 7, 1
# 元台帳 (補URL候補NG / 補URL要調査) に付ける結論の印。「どこへ行ったか」がその場で分かる。
SRC_STATUS_HEADER = "状態"
# 「用途」: 同じカード(KEY)が複数あっても **出品するのは1枚だけ**。
#   2枚目以降は捨てず「補URL」= 供給の厚み (無在庫なので仕入元は多いほど良い)。
USE_LIST, USE_AUX = "出品", "補URL(2枚目以降)"
SHEET_CATEGORY = "TCG"   # 商品管理シート R列。PSA は 'TCG'
NG_TAB = "新規候補NG"
NG_HEADER = ["url", "理由", "日付", "候補タイトル"]
# ★2026-08-13 ユーザー指示「カード番号とかを目視でいれて、次回にカタログから引けばいいのでは」。
#   タイトルが残っていない候補 (実測32件) は機械では何も引けないが、**人がページを見れば
#   番号は読める**。読んだ番号をここに置くと、次回の走行でカタログ候補が並ぶ。
#   = 「タイトル不明のまま永遠に結論が出ない」を無くす経路。
CNO_TAB = "候補カード番号"
CNO_HEADER = ["url", "カード番号(目視)", "日付"]
MISSING_CSV = r"C:/dev/iMak_data/catalog/missing_models.csv"

# ★2026-08-13 ユーザー確定: **「該当なし」という着地を 0 にする。**
#   どの候補にも必ず結論があるはず、という指示。結論は次の3つだけ:
#     list    = カタログのカードと一致した → 出品候補へ
#     catalog = 実在するがカタログに無い   → **カタログ追加依頼を出す** (後日出品できる)
#     out     = そもそも出品対象でない     → 理由を必ず選ぶ (まとめ売り/PSA以外 等)
#   旧「該当なし」は catalog と out が混ざっており、**カタログに足りないカードの情報を
#   毎回捨てていた**。hold(保留) は結論ではないので、件数を必ず表示して 0 に寄せる。
OUT_REASONS = [
    ("bundle", "まとめ売り・複数枚"),
    ("notpsa", "PSA10ではない (別グレード/未鑑定)"),
    ("othergenre", "別ジャンル (対象外の商材)"),
    # ★2026-08-13 ユーザー指摘「ページが消えている=売り切れってことだよね?」。その通りで、
    #   消えているのは**その仕入元URL**だけ。カードが特定できるなら出品候補に入れてよい
    #   (無在庫なので仕入元は後で探し直せる)。だから「対象外」に落とすのは
    #   **カードも特定できない時だけ**、と文言で限定する。
    ("gone", "供給が消えた(売り切れ) & カードも特定できない"),
    ("other", "その他"),
]

# タイトルから作品を当てる (カタログ依頼の宛先カテゴリを決めるだけに使う)。
# 当たらなければ空 = カテゴリ不明として依頼する (推測で誤ったカテゴリに入れない)。
_CATEGORY_HINTS = (
    ("one_piece_tcg", ("ワンピース", "ONE PIECE", "onepiece")),
    ("pokemon_tcg", ("ポケモン", "POKEMON", "ポケカ")),
    ("dragonball_scg", ("ドラゴンボール", "DRAGON BALL", "フュージョンワールド")),
    ("gundam_tcg", ("ガンダム", "GUNDAM")),
)


def guess_category(title, variants=()):
    """候補の作品カテゴリ (catalog 依頼の宛先)。分からなければ ""。純関数。"""
    for v in (variants or []):
        if v.get("category"):
            return v["category"]
    t = str(title or "")
    up = t.upper()
    for cat, keys in _CATEGORY_HINTS:
        if any((k.upper() in up) for k in keys):
            return cat
    return ""

# カード番号の書式。TCG は `OP05-002` / `FB01-071` 系、ポケモンは印刷番号 `006/020` 系。
_CARD_NO_RE = re.compile(r"([A-Z]{1,4}\d{1,2}[a-z]?-\d{2,4}|\d{2,3}/\d{2,3})", re.I)


def _today():
    return datetime.datetime.now().strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# 純関数 (test 可)
# ---------------------------------------------------------------------------
def extract_card_no(title):
    """候補タイトル → カード番号 (無ければ "")。純関数。

    例: '【PSA10】ベロ・ベティ(L★){赤/黄}〈OP05-002〉…' → 'OP05-002'
        'PSA10 わるいヘルガー 006/020 ポケモンカード'   → '006/020'
    """
    m = _CARD_NO_RE.search(str(title or ""))
    return m.group(1).upper() if m else ""


def url_title_map(cache):
    """探索 cache → {候補URL: (価格, タイトル)}。純関数。

    ★「違う」を押した時に候補のタイトルを保存していなかったので、後から引くにはここしかない。
      cands / all_cands / loose_cands / best の4か所に [価格, url, タイトル] で入っている。
    """
    out = {}
    for _iid, v in (cache or {}).items():
        m = (v or {}).get("mercari") or {}
        buckets = [m.get(k) or [] for k in ("cands", "all_cands", "loose_cands")]
        b = m.get("best")
        if isinstance(b, (list, tuple)):
            buckets.append([b])
        for lst in buckets:
            for c in lst:
                if isinstance(c, (list, tuple)) and len(c) >= 3 and c[1]:
                    out[c[1]] = (c[0], c[2])
    return out


def pending_rows(src_rows, done_urls):
    """台帳の行 → 未処理だけ (純関数)。done_urls に有る url は落とす。

    src_rows: [(tab, row)] 形式。row は [itemID, cert, url, title, ...]。
    """
    out, seen = [], set()
    for tab, r in src_rows:
        if len(r) < 3:
            continue
        url = (r[2] or "").strip()
        if not url or url in done_urls or url in seen:
            continue
        seen.add(url)
        # ★2026-08-13 以降の行は台帳に候補タイトル/価格を持つ (NG=6,7列目 / 要調査=8,9列目)。
        #   それ以前の行は空なので探索cache から復元する (load_items 側)。
        ct = (r[5] if tab.endswith("NG") and len(r) > 5 else
              (r[7] if len(r) > 7 else "")) or ""
        cp = (r[6] if tab.endswith("NG") and len(r) > 6 else
              (r[8] if len(r) > 8 else "")) or ""
        out.append({"src": tab, "src_itemid": (r[0] or "").strip(),
                    "src_cert": (r[1] or "").strip(), "url": url,
                    "saved_title": str(ct).strip(), "saved_price": str(cp).strip()})
    return out


def parse_result(data):
    """POST(JSON) → 結論3種 + 保留 (純関数)。

    {picks:[{idx,pid,category,cert}],       # 出品候補へ
     catalog_reqs:[idx],                    # カタログ追加依頼へ
     outs:[{idx,reason}],                   # 対象外 (理由必須)
     holds:[idx]}                           # 未結論 (次回また出る)
    """
    picks = []
    for d in (data.get("picks") or []):
        if d.get("idx") is None or not (d.get("pid") or "").strip():
            continue
        picks.append({"idx": int(d["idx"]), "pid": d["pid"].strip(),
                      "category": (d.get("category") or "").strip(),
                      "cert": re.sub(r"\D", "", str(d.get("cert") or ""))})
    valid = {k for k, _ in OUT_REASONS}
    outs = []
    for d in (data.get("outs") or []):
        if d.get("idx") is None:
            continue
        r = (d.get("reason") or "").strip()
        # 理由が無い/知らない値 = 結論になっていない → 保留に落とす (「該当なし」を作らない)
        if r in valid:
            outs.append({"idx": int(d["idx"]), "reason": r})
    out_idx = {o["idx"] for o in outs}
    holds = [int(i) for i in (data.get("holds") or [])]
    holds += [int(d["idx"]) for d in (data.get("outs") or [])
              if d.get("idx") is not None and int(d["idx"]) not in out_idx]
    cnos = []
    for d in (data.get("card_nos") or []):
        no = str(d.get("no") or "").strip().upper()
        if d.get("idx") is not None and no:
            cnos.append({"idx": int(d["idx"]), "no": no})
    return {"picks": picks,
            "catalog_reqs": [int(i) for i in (data.get("catalog_reqs") or [])],
            "outs": outs,
            "card_nos": cnos,
            "holds": sorted(set(holds))}


# ---------------------------------------------------------------------------
# catalog 参照 (I/O)
# ---------------------------------------------------------------------------
# ★2026-08-13 ユーザー指摘「候補の中に英語版がある」。
#   catalog の images は **英語版が先頭**に入っていることが多く (例 EB03-053 は
#   OP-EN → OP-JA の順)、先頭を採ると英語の絵が並ぶ。売っているのは日本語版なので、
#   絵柄を見比べる相手が違ってしまう。日本語の画像を優先して選ぶ。
_JA_IMG_HINTS = ("-JA/", "/JA/", "onepiece-cardgame.com", "pokemon-card.com",
                 "dbs-cardgame", "gundam-gcg.com")


def _first_image(images_json, pid=""):
    """カード画像 (日本語版を優先。同じ版の絵を選ぶ)。純関数。

    ★注意: 英語版のみの行は images に「**基本版**の日本語画像」が混ざっていることがある
      (例 EB03-053_p2 → OP-JA/batch_EB03-053.png = パラレルでない絵)。
      日本語を優先しつつ、**ファイル名に版のIDを含むもの**を先に選ぶ。
    """
    try:
        imgs = json.loads(images_json or "[]")
    except Exception:
        return ""
    urls = []
    for x in (imgs if isinstance(imgs, list) else []):
        u = x.get("url") if isinstance(x, dict) else x
        if u:
            urls.append(str(u))
    ja = [u for u in urls if any(h.upper() in u.upper() for h in _JA_IMG_HINTS)]
    p = str(pid or "").upper()
    if p:
        for u in ja:
            if p in u.upper().rsplit("/", 1)[-1]:
                return u
    return (ja or urls or [""])[0]


def is_en_only(lang):
    """catalog の language が英語版のみか (純関数)。'both'/'ja'/未設定 は日本語あり扱い。"""
    return str(lang or "").strip().lower() == "en"


def _row_to_cand(r):
    return {"pid": r["product_id"], "category": r["category"],
            "name": r["name_en"] or r["name"] or "", "name_jp": r["name"] or "",
            "lang": (r["language"] or ""), "en_only": is_en_only(r["language"]),
            "image": _first_image(r["images"], r["product_id"])}


_CAND_COLS = "product_id, category, name, name_en, images, language"
_MAX_CANDS = 12


def _is_other_card(pid, card_no):
    """`OP05-002` の前方一致で拾った `OP05-0021` のような**別カード**か (純関数)。

    版は `_p1` `_P` `_EB02_LF` のように **区切り記号**が続く。数字が続くのは別番号。
    """
    tail = str(pid or "")[len(card_no):]
    return bool(tail) and tail[0].isdigit()


def catalog_variants(card_no, db=DB_PATH):
    """カード番号 → 版の一覧 [{pid, category, name, image}]。無ければ []。

    `OP05-002` は `OP05-002` / `_p` / `_p1` / `_p2` / `_EB02_LF` のように**版が複数**ある。
    """
    if not card_no:
        return []
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        # ★2026-08-13 バグ修正: 以前は LIKE 'OP05-002\_%' と書いていたが、SQLite は
        #   ESCAPE 句が無いと `\` を**ただの文字**として扱うため **1件も引けなかった**。
        #   結果、版が複数あるカードでも候補が「1件」に見え、目視で選びようがなかった
        #   (実測: EB03-053 は 1件→4件 / OP13-118 は 1件→7件)。
        #   前方一致で取ってから、直後が数字のもの (OP05-0021 等の別カード) を落とす。
        rows = [r for r in con.execute(
            f"SELECT {_CAND_COLS} FROM products WHERE product_id LIKE ? "
            "ORDER BY LENGTH(product_id), product_id", (card_no + "%",)).fetchall()
            if not _is_other_card(r["product_id"], card_no)]
        if not rows:
            # ポケモンの印刷番号 (006/020) は product_id と別体系なので specs 側を見る
            rows = con.execute(
                f"SELECT {_CAND_COLS} FROM products "
                "WHERE specs LIKE ? ORDER BY product_id LIMIT 12",
                (f'%"card_number": "{card_no}%',)).fetchall()
        return [_row_to_cand(r) for r in rows][:_MAX_CANDS]
    finally:
        con.close()


_NAME_INDEX = None


def _name_index(db=DB_PATH):
    """{カード名(日本語): [行]} を1回だけ作る。名前引きの候補出し用 (I/O・cache)。

    ★番号が読めない候補 (タイトルに `〈OP05-002〉` が無い等) でも、名前は書いてある。
      名前で候補を出せば目視で選べる = 「候補が1件も出ない」を無くす。
    """
    global _NAME_INDEX
    if _NAME_INDEX is None:
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        try:
            idx = {}
            for r in con.execute(
                    f"SELECT {_CAND_COLS} FROM products "
                    "WHERE category IN ('one_piece_tcg','pokemon_tcg','dragonball_scg','gundam_tcg')"):
                nm = (r["name"] or "").strip()
                if len(nm) >= 2:
                    idx.setdefault(nm, []).append(_row_to_cand(r))
            _NAME_INDEX = idx
        finally:
            con.close()
    return _NAME_INDEX


def catalog_by_name(title, limit=_MAX_CANDS, db=DB_PATH):
    """候補タイトルに含まれるカード名で catalog を引く [{pid,...}]。

    長い名前を優先 (「モンキー・D・ルフィ」が「ナミ」より先)。同名が大量にある場合は
    limit で頭打ち = 目視で見比べられる数に抑える。
    """
    t = str(title or "")
    if not t:
        return []
    hits = []
    for nm in sorted(_name_index(db), key=len, reverse=True):
        if nm in t:
            hits.extend(_name_index(db)[nm])
            if len(hits) >= limit:
                break
    return hits[:limit]


def catalog_candidates(title, card_no, db=DB_PATH):
    """目視画面に出す catalog 候補 (番号一致 → 足りなければ名前一致で補う)。

    ★必ず**複数**出す。1つしか出さないと「これで合ってますね?」の確認にしかならず、
      目視で特定する画面にならない (2026-08-13 ユーザー指摘)。
    """
    out = catalog_variants(card_no, db) if card_no else []
    if out:
        # 番号が一致した = その番号の版だけが候補。名前で水増ししない
        # (関係ない同名カードを混ぜると、かえって選べなくなる)
        return out[:_MAX_CANDS]
    # 番号が読めない / 番号が catalog に無い → 名前で候補を出す (ここが目視の出番)
    return catalog_by_name(title, _MAX_CANDS, db)


def load_items(limit=0):
    """台帳2本 → 目視対象 items (I/O)。候補タイトル復元 + カード番号抽出 + 版引きまで済ませる。"""
    src_rows = []
    for tab in SRC_TABS:
        for r in (sheet_io.read_tab(tab) or [])[1:]:
            src_rows.append((tab, r))
    done = set()
    for tab in (OUT_TAB, NG_TAB):
        for r in (sheet_io.read_tab(tab) or [])[1:]:
            if r and r[0]:
                done.add(r[0].strip())
    # 前回 目視で入れたカード番号 (タイトルが無くてもここから引ける)
    typed_no = {}
    for r in (sheet_io.read_tab(CNO_TAB) or [])[1:]:
        if r and len(r) > 1 and r[0] and r[1]:
            typed_no[r[0].strip()] = r[1].strip().upper()
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            u2t = url_title_map(json.load(f))
    except Exception as e:
        print(f"⚠ 探索cache を読めない ({type(e).__name__}) → タイトル復元なしで続行")
        u2t = {}

    items = []
    for p in pending_rows(src_rows, done):
        price, title = u2t.get(p["url"], (None, ""))
        # 台帳に保存済のタイトルがあればそちらが正 (押した時点の実物)
        if p.get("saved_title"):
            title = p["saved_title"]
            try:
                price = int(str(p.get("saved_price") or "").replace(",", "")) or price
            except Exception:
                pass
        # ★目視で入れた番号が最優先 (機械が読めなかった/読み違えた分を人が上書きできる)
        card_no = typed_no.get(p["url"], "") or extract_card_no(title)
        variants = catalog_candidates(title, card_no)
        p.update({"price": price, "title": title, "card_no": card_no, "variants": variants})
        items.append(p)
        if limit and len(items) >= limit:
            break
    for i, it in enumerate(items):
        it["idx"] = i
    return items


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
_CSS = """
body{font-family:sans-serif;margin:12px;background:#fafafa}
h1{font-size:16px;margin:0 0 8px}
.sum{font-size:12px;color:#555;margin-bottom:10px}
.it{background:#fff;border:1px solid #ddd;border-radius:6px;padding:8px;margin-bottom:10px;display:flex;gap:10px}
.it.done{opacity:.45}
.ph img{width:190px;height:250px;object-fit:contain;background:#f4f4f4;border:1px solid #eee}
.ph .none{width:190px;height:250px;display:flex;align-items:center;justify-content:center;color:#999;font-size:11px;border:1px dashed #ccc}
.body{flex:1;min-width:0}
.t{font-size:13px;font-weight:bold;margin-bottom:2px;word-break:break-all}
.meta{font-size:11px;color:#666;margin-bottom:6px}
.vs{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0}
.v{position:relative;border:1px solid #ccc;border-radius:4px;padding:4px;cursor:pointer;text-align:center;font-size:10px;width:112px}
.v.sel{border-color:#0a7;background:#e7f7f1;box-shadow:0 0 0 1px #0a7 inset}
.v img{width:100px;height:135px;object-fit:contain;background:#f7f7f7}
.v .pid{font-weight:bold;word-break:break-all}
.v .nm{color:#666}
.v .en{color:#a40;font-weight:bold}   /* 英語版のみ = 日本語版が catalog に無い印 */
.v .zb{position:absolute;top:2px;right:2px;font-size:11px;padding:0 4px;line-height:16px}
.one{font-size:12px;color:#076;font-weight:bold}
.warn{font-size:12px;color:#a40}
.zb2{font-size:11px;padding:1px 6px;margin-top:2px}
/* 虫眼鏡: 候補写真とカタログ画像を並べて拡大 (2026-08-13 ユーザー要望) */
#zov{display:none;position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:99;
     align-items:center;justify-content:center;gap:20px}
#zov.on{display:flex}
#zov .zc{color:#fff;font-size:12px;text-align:center;margin-bottom:4px}
#zov img{max-height:82vh;max-width:44vw;object-fit:contain;background:#fff}
.act{margin-top:6px;display:flex;gap:6px;align-items:center;flex-wrap:wrap}
button{font-size:12px;padding:3px 10px;border:1px solid #bbb;background:#fff;border-radius:4px;cursor:pointer}
button.go{border-color:#0a7;color:#065}
button.go.sel{background:#0a7;color:#fff}
button.cat{border-color:#a60;color:#a60}
button.cat.sel{background:#a60;color:#fff}
button.ng{border-color:#c33;color:#900}
button.ng.sel{background:#c33;color:#fff}
button.hold.sel{background:#888;color:#fff}
select.rsn{font-size:11px}
input.cert{font-size:12px;width:120px;padding:2px 4px}
#go{position:fixed;right:14px;bottom:14px;font-size:15px;padding:10px 20px;background:#0a7;color:#fff;border:none;border-radius:6px}
"""

_JS = """
function zoom(ev, el, side){
  ev.preventDefault(); ev.stopPropagation();
  var box=el.closest('.it');
  var o=document.getElementById('zov');
  o.querySelector('#zl img').src = box.dataset.photo||'';
  var cat = (side==='cat') ? el.dataset.img : (box.querySelector('.v.sel img')||{}).src;
  o.querySelector('#zr img').src = cat||'';
  o.querySelector('#zr .zc').textContent = 'カタログ ' + ((side==='cat')? (el.dataset.pid||'') :
      ((box.querySelector('.v.sel')||{dataset:{}}).dataset.pid||'(未選択)'));
  o.classList.add('on');
}
function zclose(){document.getElementById('zov').classList.remove('on');}
document.addEventListener('keydown',function(e){if(e.key==='Escape')zclose();});
function imgFail(el){var d=document.createElement('div');
  d.style.cssText='width:100px;height:135px;display:flex;align-items:center;justify-content:center;color:#999;border:1px dashed #ccc';
  d.textContent='画像なし'; if(el.parentNode) el.parentNode.replaceChild(d,el);}
function pickV(el){
  var box=el.closest('.it');
  box.querySelectorAll('.v').forEach(function(v){v.classList.remove('sel');});
  el.classList.add('sel');
  box.dataset.pid=el.dataset.pid; box.dataset.cat=el.dataset.cat;
  setAct(box.querySelector('button.go'));
}
function setAct(btn){
  var box=btn.closest('.it');
  box.querySelectorAll('.act button').forEach(function(b){b.classList.remove('sel');});
  btn.classList.add('sel'); box.dataset.act=btn.dataset.a;
  box.classList.toggle('done', btn.dataset.a!=='go');
}
function go(){
  var picks=[],creq=[],outs=[],holds=[],cnos=[],noreason=0;
  document.querySelectorAll('.it').forEach(function(b){
    var a=b.dataset.act||'';
    var idx=parseInt(b.dataset.idx,10);
    var cno=((b.querySelector('input.cno')||{}).value||'').trim();
    if(cno && cno!==(b.dataset.cno||'')) cnos.push({idx:idx, no:cno});
    /* ★鑑定番号はここでは入れない (2026-08-13 ユーザー確定「出品までには入れるから、
       今はカードを特定することに専念しよう」)。この画面の仕事は**版の確定**だけ。 */
    if(a==='go'){
      picks.push({idx:idx, pid:b.dataset.pid||'', category:b.dataset.cat||'', cert:''});
    }
    else if(a==='cat'){creq.push(idx);}
    else if(a==='out'){
      var r=(b.querySelector('select.rsn')||{}).value||'';
      if(!r) noreason++;
      outs.push({idx:idx, reason:r});
    }
    else if(a==='hold'){holds.push(idx);}
    else {holds.push(idx);}   /* 未操作も未結論として数える */
  });
  var msg='出品へ '+picks.length+'件 / カタログ追加依頼 '+creq.length+'件 / 対象外 '
          +outs.length+'件 / **未結論 '+holds.length+'件**';
  if(cnos.length) msg+='\\n\\nカード番号を入れた '+cnos.length+'件 — 次回はカタログ候補が並びます。';
  if(noreason) msg+='\\n\\n対象外なのに理由が未選択 '+noreason+'件 — 理由が無いものは未結論に戻します。';
  if(holds.length) msg+='\\n\\n未結論は次回また出ます (ここを0にするのが目標)。';
  if(!confirm(msg+'\\n\\nこの内容で確定しますか?')) return;
  fetch('/',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({picks:picks,catalog_reqs:creq,outs:outs,holds:holds,
                         card_nos:cnos})}).then(function(){
    document.body.innerHTML='<h1>確定しました。ウィンドウを閉じてください。</h1>';});
}
"""


def build_html(items):
    """items → 目視ページ (bytes)。純関数。"""
    n_one = sum(1 for it in items if len(it["variants"]) == 1)
    n_multi = sum(1 for it in items if len(it["variants"]) > 1)
    n_zero = sum(1 for it in items if not it["variants"])
    parts = [
        "<!doctype html><meta charset='utf-8'><title>新規出品候補 目視</title>",
        f"<style>{_CSS}</style>",
        "<h1>捨てた仕入候補 → 新規出品の種</h1>",
        f"<div class='sum'>{len(items)}件 — カタログで1つに決まる <b>{n_one}</b> / "
        f"版が複数(絵柄で選ぶ) <b>{n_multi}</b> / カタログに無い <b>{n_zero}</b><br>"
        "この画面の仕事は<b>どのカードか(版)を決めること</b>だけです。"
        "鑑定番号は出品の直前に入れるので、ここでは要りません。<br>"
        "番号が読めていない候補は、ページを開いて<b>カード番号</b>を打つと次回に版が並びます。<br>"
        "<b>ページが消えていても(売り切れ)</b>、カードが特定できるなら「出品する」でOKです — "
        "無在庫なので仕入元は後で探し直せます。</div>",
    ]
    for it in items:
        photo = prc._proxied(it["url"])
        ph = (f"<div class='ph'><a href='{_html.escape(it['url'])}' target='_blank'>"
              f"<img src='{_html.escape(photo)}' loading='lazy' onerror='imgFail(this)'></a>"
              f"<div><button class='zb2' onclick='zoom(event,this,\"cand\")'>🔍 拡大</button></div>"
              f"</div>")
        price = f"¥{it['price']:,}" if isinstance(it["price"], int) else ""
        title = it["title"] or "(タイトル不明 — リンクを開いて確認)"
        vs = it["variants"]
        if vs:
            # ★2026-08-13 ユーザー指摘「英語版では一致しているけど、日本語版が候補にない」。
            #   英語版だけしか無い = **日本語版がカタログに未収録** ということ。
            #   英語版を黙って消すと手掛かりが消えるので、印を付けて残し、
            #   「カタログに無い→追加依頼」に誘導する (= それも立派な結論)。
            no_ja = vs and all(v.get("en_only") for v in vs)
            # ★必ず画像付きで並べる。1件でもカードとして出す (文字だけだと見比べられない)。
            cards = "".join(
                f"<div class='v' data-pid=\"{_html.escape(v['pid'])}\" "
                f"data-cat=\"{_html.escape(v['category'])}\" onclick='pickV(this)'>"
                + (f"<img src='{_html.escape(prc._proxied(v['image']))}' loading='lazy' "
                   f"onerror='imgFail(this)'>"
                   if v["image"] else
                   "<div style='width:100px;height:135px;display:flex;align-items:center;"
                   "justify-content:center;color:#999;border:1px dashed #ccc'>画像なし</div>")
                + f"<div class='pid'>{_html.escape(v['pid'])}</div>"
                + f"<div class='nm'>{_html.escape((v.get('name') or '')[:16])}</div>"
                + ("<div class='en'>英語版のみ</div>" if v.get("en_only") else "")
                + f"<button class='zb' data-img=\"{_html.escape(prc._proxied(v['image']))}\" "
                  f"data-pid=\"{_html.escape(v['pid'])}\" "
                  f"onclick='zoom(event,this,\"cat\")'>🔍</button>"
                + "</div>" for v in vs)
            head = (f"<div class='one'>カタログ候補 {len(vs)}件 — 絵柄を見て選んでください</div>"
                    if len(vs) > 1 else
                    "<div class='one'>カタログ候補 1件 — 絵柄が合っていれば選んでください</div>")
            if no_ja:
                head += ("<div class='warn'>⚠ 候補が<b>英語版しかありません</b>。"
                         "絵柄が合っていても<b>日本語版がカタログに未収録</b>なので、"
                         "「カタログに無い→追加依頼」を押してください</div>")
            body_v = head + f"<div class='vs'>{cards}</div>"
        else:
            body_v = ("<div class='warn'>カタログ候補なし "
                      "(番号も名前も読めない/未収録)。出品には回せません</div>")
        parts.append(
            f"<div class='it' data-idx='{it['idx']}' data-pid='' data-cat='' "
            f"data-cno=\"{_html.escape(it['card_no'] or '')}\" "
            f"data-photo=\"{_html.escape(photo)}\">{ph}<div class='body'>"
            f"<div class='t'>{_html.escape(title[:110])}</div>"
            f"<div class='meta'>{price} ｜ 番号 {_html.escape(it['card_no'] or '?')} ｜ "
            f"元 {_html.escape(it['src'])} (出品 {_html.escape(it['src_itemid'])})</div>"
            f"{body_v}"
            f"<div class='act'>カード番号 <input class='cno' "
            f"value=\"{_html.escape(it['card_no'] or '')}\" placeholder='例 OP05-002'>"
            "<button class='go' data-a='go' onclick='setAct(this)'>出品する</button>"
            "<button class='cat' data-a='cat' onclick='setAct(this)'>"
            "カタログに無い→追加依頼</button>"
            "<button class='ng' data-a='out' onclick='setAct(this)'>対象外</button>"
            "<select class='rsn'><option value=''>理由を選ぶ</option>"
            + "".join(f"<option value='{k}'>{_html.escape(v)}</option>" for k, v in OUT_REASONS)
            + "</select>"
            "<button class='hold' data-a='hold' onclick='setAct(this)'>保留</button>"
            "</div></div></div>")
    parts.append(
        "<div id='zov' onclick='zclose()'>"
        "<div id='zl'><div class='zc'>仕入候補の写真</div><img alt=''></div>"
        "<div id='zr'><div class='zc'>カタログ</div><img alt=''></div></div>")
    parts.append(f"<button id='go' onclick='go()'>確定</button><script>{_JS}</script>")
    return "".join(parts).encode("utf-8")


# ---------------------------------------------------------------------------
# 書込 (I/O)
# ---------------------------------------------------------------------------
def _append_tab(tab, header, new_rows):
    cur = sheet_io.read_tab(tab) or []
    body = migrate_out_rows(cur) if tab == OUT_TAB else (cur[1:] if cur else [])
    sheet_io.write_rows_to_tab(tab, [header] + body + new_rows)


def mark_use(rows, listed_keys=(), key_col=OUT_KEY_COL, use_col=0):
    """同じカード(KEY)は1行だけ『出品』、残りは『補URL』にする (純関数)。

    ★同じカードを2枚出品しない (重複くんが後で弾く前に、ここで用途を分けておく)。
      捨てるのではなく**補URL**に回す = 供給の厚みとして残す (無在庫なので仕入元は多いほど良い)。
    listed_keys: 既に出品中/候補済の KEY。含まれるカードは丸ごと補URL扱いにする。
    """
    seen = {str(k).strip() for k in (listed_keys or []) if str(k).strip()}
    out = []
    for r in rows:
        r = list(r)
        key = str(r[key_col] or "").strip()
        r[use_col] = USE_AUX if (key and key in seen) else USE_LIST
        if key:
            seen.add(key)
        out.append(r)
    return out


def migrate_out_rows(cur):
    """旧8列 (用途なし) の保管行を新9列に移す (純関数)。

    2026-08-13 に「用途」列を先頭に足した。既存行は列がずれるので、先頭に空を入れてから
    同じ規則で 出品/補URL を振り直す。ヘッダが新形式ならそのまま返す。
    """
    if not cur or not cur[0]:
        return []
    head = list(cur[0])
    if head == OUT_HEADER:          # ★完全一致で判定する。先頭2列だけ見ると
        return cur[1:]              #   列を足した時に古い行を素通りさせる (2026-08-13 実際に起きた)
    if head[:2] == ["用途", "HIGH転記"] and "M列:仕入価格(円)" not in head:
        # 価格列を足す前の形 (2026-08-13 途中形) → 4列目に空を差し込む
        return [list(r[:4]) + [""] + list(r[4:]) for r in cur[1:] if r]
    if head[0] == OUT_HEADER[0]:            # 用途はあるが HIGH転記 が無い
        return [[r[0], ""] + list(r[1:4]) + [""] + list(r[4:]) for r in cur[1:] if r]
    # 旧形式 (用途も無い)
    return mark_use([["", ""] + list(r[:3]) + [""] + list(r[3:]) for r in cur[1:] if r],
                    listed_keys=())


def already_listed_keys():
    """既に『出品』として保管済の KEY (I/O)。走行をまたいでも二重に出品候補にしない。"""
    keys = set()
    for r in migrate_out_rows(sheet_io.read_tab(OUT_TAB) or []):
        if (len(r) > OUT_KEY_COL and (r[0] or "").strip() == USE_LIST
                and (r[OUT_KEY_COL] or "").strip()):
            keys.add(r[OUT_KEY_COL].strip())
    return keys


def _nurl(u):
    """URL 比較用の正規化 (末尾スラッシュ/クエリ/大小を無視)。純関数。"""
    u = str(u or "").strip().split("?")[0].rstrip("/")
    return u.lower()


def status_of(url, out_rows, ng_rows):
    """元台帳の1行が **どこへ行ったか** (純関数)。未処理なら ""。

    ★2026-08-13 ユーザー指摘「新規出品候補へコピーとかあった方が分かりやすい」。
      台帳を見ただけで結論が分かるようにする (別タブと突き合わせないと分からない状態をやめる)。
    """
    u = _nurl(url)
    for r in out_rows:
        if len(r) > OUT_URL_COL and _nurl(r[OUT_URL_COL]) == u:
            use = (r[0] or "").strip() or USE_LIST
            done = (r[OUT_DONE_COL] or "").strip() if len(r) > OUT_DONE_COL else ""
            return f"新規出品候補へ ({use}{'・HIGH転記済' if done else ''})"
    for r in ng_rows:
        if r and _nurl(r[0]) == u:
            return (r[1] or "結論済").strip()
    return ""


def sync_status():
    """(1) 新規出品候補に **HIGH転記済** の印を付け、(2) 元台帳に **結論** を書き戻す (I/O)。

    どちらも突き合わせて機械が付ける (人がチェックを付けない = 付け忘れが起きない)。
    """
    out_rows = migrate_out_rows(sheet_io.read_tab(OUT_TAB) or [])
    ng_rows = [r for r in (sheet_io.read_tab(NG_TAB) or [])[1:] if r]

    # (1) 商品管理シートの A列(仕入元URL) に在れば「転記済」
    n_done = 0
    try:
        prod = {_nurl(r[0]) for r in sheet_io._product_ws().get_all_values()[1:] if r and r[0]}
    except Exception as e:
        print(f"  ⚠ 商品管理シートを読めず転記チェック skip ({type(e).__name__})")
        prod = None
    if prod is not None and out_rows:
        for r in out_rows:
            while len(r) < len(OUT_HEADER):
                r.append("")
            mark = "済" if _nurl(r[OUT_URL_COL]) in prod else ""
            r[OUT_DONE_COL] = mark
            n_done += 1 if mark else 0
        sheet_io.write_rows_to_tab(OUT_TAB, [OUT_HEADER] + out_rows)
        print(f"  🔖 {OUT_TAB}: HIGH転記済 {n_done}/{len(out_rows)}件")

    # (2) 元台帳に結論を書き戻す
    for tab in SRC_TABS:
        cur = sheet_io.read_tab(tab) or []
        if not cur:
            continue
        head = list(cur[0])
        if SRC_STATUS_HEADER not in head:
            head.append(SRC_STATUS_HEADER)
        si = head.index(SRC_STATUS_HEADER)
        body, n = [], 0
        for r in cur[1:]:
            r = list(r)
            while len(r) <= si:
                r.append("")
            if len(r) > 2 and r[2]:
                st = status_of(r[2], out_rows, ng_rows)
                r[si] = st
                n += 1 if st else 0
            body.append(r)
        sheet_io.write_rows_to_tab(tab, [head] + body)
        print(f"  🔖 {tab}: 結論つき {n}/{len(body)}件")


def append_missing_models(rows, path=MISSING_CSV):
    """カタログ未収録として `missing_models.csv` に積む (I/O)。

    ここに積むと既存の watcher (`auto_catalog_add_request.py`) が
    カタログへの追加依頼書を自動で起票する = **捨てずに結論に変える**経路。
    """
    if not rows:
        return 0
    import csv as _csv
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = _csv.writer(f)
        if new:
            w.writerow(["category", "model", "detected_at"])
        for r in rows:
            w.writerow(r)
    return len(rows)


def save(items, res):
    """結論を書き分ける (I/O)。戻り: {list, catalog, out, hold} 件数。

    ★「該当なし」という置き場は作らない (2026-08-13 ユーザー確定)。
      カタログに無いなら**依頼**、対象外なら**理由つき**。どちらも結論。
    """
    today = _today()
    by_idx = {it["idx"]: it for it in items}
    reason_label = dict(OUT_REASONS)

    picks = []
    for p in res["picks"]:
        it = by_idx.get(p["idx"])
        if not it:
            continue
        key = f"{p['category']}:{p['pid']}" if p["category"] else p["pid"]
        picks.append(["", "", it["url"], (it["title"] or "")[:60],
                      (it.get("price") if isinstance(it.get("price"), int) else ""),
                      p["cert"], SHEET_CATEGORY, key, p["pid"], it["src_itemid"], today])
    picks = mark_use(picks, already_listed_keys())
    if picks:
        _append_tab(OUT_TAB, OUT_HEADER, picks)
        n_list = sum(1 for r in picks if r[0] == USE_LIST)
        print(f"  ✅ {OUT_TAB}: +{len(picks)}件 "
              f"(うち出品 {n_list}件 / 補URL {len(picks) - n_list}件)")
        print("     ℹ 貼り付けるのは『用途=出品』の行だけ。残りは同じカードの別の仕入元です")
        print("     ℹ I列:cert は空のまま = 出品直前に入れる (この画面の仕事は版の確定だけ)")

    # ★同じ確定で入力されたカード番号は、依頼を書く前に反映する (2026-08-13)。
    #   番号を打ったのに「番号不明」で依頼を出していた。さらに、その番号で catalog に
    #   **在る**なら依頼自体が不要 = 次回 候補が並ぶので未結論に戻す。
    typed = {c["idx"]: c["no"] for c in res.get("card_nos", [])}
    creqs, creq_ng = [], []
    n_recheck = 0
    for i in res["catalog_reqs"]:
        it = by_idx.get(i)
        if not it:
            continue
        card_no = typed.get(i) or it["card_no"]
        if typed.get(i) and catalog_variants(typed[i]):
            n_recheck += 1          # 入力番号で catalog に在った → 依頼しない
            continue
        cat = guess_category(it["title"], it["variants"])
        model = (f"{card_no or '番号不明'} {it['title'][:60]} "
                 f"(捨てた仕入候補の目視 {today} / {it['url']})")
        creqs.append([cat, model, f"{today} 00:00:00"])
        creq_ng.append([it["url"], "カタログ未収録 → 追加依頼を起票", today,
                        (it["title"] or "")[:60]])
    if n_recheck:
        print(f"  ↩ 入力された番号で catalog に在った {n_recheck}件 → 依頼せず次回に候補を出す")
    if creqs:
        n = append_missing_models(creqs)
        _append_tab(NG_TAB, NG_HEADER, creq_ng)
        print(f"  📨 カタログ追加依頼: +{n}件 (missing_models.csv → 自動起票)")
        _nocat = [c for c in creqs if not c[0]]
        if _nocat:
            print(f"     ℹ うち作品カテゴリ不明 {len(_nocat)}件 (依頼側で判別してもらう)")

    outs = [[by_idx[o["idx"]]["url"], f"対象外: {reason_label.get(o['reason'], o['reason'])}",
             today, (by_idx[o["idx"]]["title"] or "")[:60]]
            for o in res["outs"] if o["idx"] in by_idx]
    if outs:
        _append_tab(NG_TAB, NG_HEADER, outs)
        print(f"  🚫 対象外: +{len(outs)}件 (理由つきで記録・次回は出さない)")

    cnos = [[by_idx[c["idx"]]["url"], c["no"], today]
            for c in res.get("card_nos", []) if c["idx"] in by_idx]
    if cnos:
        cur = {r[0].strip(): r for r in (sheet_io.read_tab(CNO_TAB) or [])[1:] if r and r[0]}
        for r in cnos:
            cur[r[0]] = r                      # 同じ URL は最新の入力で上書き
        sheet_io.write_rows_to_tab(CNO_TAB, [CNO_HEADER] + list(cur.values()))
        print(f"  ✍ カード番号を記録: +{len(cnos)}件 → 次回はカタログ候補が並びます")

    n_hold = len([i for i in res["holds"] if i in by_idx])
    if n_hold:
        print(f"  ⏸ **未結論 {n_hold}件** — 次回また出ます。ここを0にするのが目標")
    else:
        print("  🎉 未結論 0件 — 全件に結論が付きました")
    return {"list": len(picks), "catalog": len(creqs), "out": len(outs), "hold": n_hold}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="先頭N件だけ見る (0=全部)")
    ap.add_argument("--timeout", type=int, default=10800)
    ap.add_argument("--dry-run", action="store_true", help="件数と内訳だけ出して終わる")
    ap.add_argument("--sync-only", action="store_true",
                    help="目視は開かず、HIGH転記済/結論の印だけ付け直す")
    a = ap.parse_args()

    print("▶ 捨てた仕入候補 → 新規出品の種 (目視)")
    if a.sync_only:
        sync_status()
        return 0
    sync_status()          # 走行前にも最新化 (手でHIGHに貼った分がすぐ反映される)
    items = load_items(limit=a.limit)
    if not items:
        print("  未処理の候補なし。")
        return 0
    n_one = sum(1 for it in items if len(it["variants"]) == 1)
    n_multi = sum(1 for it in items if len(it["variants"]) > 1)
    n_zero = sum(1 for it in items if not it["variants"])
    print(f"  対象 {len(items)}件 — 1つに決まる {n_one} / 版が複数 {n_multi} / catalog に無い {n_zero}")
    if a.dry_run:
        for it in items[:15]:
            print(f"   {it['card_no'] or '?':<12} 版{len(it['variants'])} {it['title'][:50]}")
        return 0
    res = prc._serve_confirm(build_html(items), parse_result, a.timeout)
    if res is None:
        print("  確定されなかった (タイムアウト/未操作) → 何も書かない")
        return 1
    save(items, res)
    sync_status()          # 確定直後に印を更新 (どこへ行ったかを台帳で見えるようにする)
    return 0


if __name__ == "__main__":
    sys.exit(main())
