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

OUT_REASONS = [
    ("used", "中古・難あり"),
    ("not_tee", "Tシャツではない / UT・GUではない"),
    ("bundle", "まとめ売り"),
    ("kids", "キッズ"),
    ("unclear", "写真で柄が分からない"),
    ("other", "その他"),
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
        if tag_no and p.get("l1") == tag_no:
            sc += 100
        toks = p["_tok"]
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
    return [p for _sc, p in out[:limit]]


def search_catalog(q, catalog, limit=MAX_CANDS):
    """画面の検索欄 → 名前/コラボ/キャラ/番号 に q を含む商品。純関数。"""
    qn = norm(q)
    if not qn:
        return []
    hits = [p for p in catalog
            if qn == (p.get("l1") or "") or qn in norm(p["name"]) or any(qn in t for t in p["_tok"])]
    hits.sort(key=lambda p: (not p.get("sold_out"), p["pid"]))
    return hits[:limit]


def pending_rows(src, decided, in_high):
    """中間タブ → 目視に出す行 [(行番号, row)]。純関数。

    出さない: URL 無し / 売り切れ印 / 台帳で決着済み / 商品管理シートに既にある URL。
    """
    out = []
    for i, r in enumerate(src[1:], start=2):
        r = list(r) + [""] * (C_SIZE + 1 - len(r))
        url = (r[C_URL] or "").strip()
        if not url.startswith("http") or (r[C_SOLD] or "").strip():
            continue
        if url in decided or url in in_high:
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
    picks = []
    for p in data.get("picks") or []:
        try:
            idx = int(p.get("idx"))
        except (TypeError, ValueError, AttributeError):
            continue
        pid, color = (p.get("pid") or "").strip(), (p.get("color") or "").strip()
        if pid and color:
            picks.append({"idx": idx, "pid": pid, "color": color})
    outs = []
    for o in data.get("outs") or []:
        try:
            outs.append({"idx": int(o.get("idx")), "reason": (o.get("reason") or "").strip()})
        except (TypeError, ValueError, AttributeError):
            continue
    return {"picks": picks, "nocat": _ints(data.get("nocat")),
            "outs": [o for o in outs if o["reason"]], "holds": _ints(data.get("holds"))}


# ── カタログ ────────────────────────────────────────────────────────
_CATALOG = None


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
        cards.append(
            f"<div class='v' data-pid=\"{_html.escape(p['pid'])}\" "
            f"data-colors=\"{_html.escape(json.dumps([c['name'] for c in p['colors']], ensure_ascii=False))}\" "
            f"data-defcolor=\"{_html.escape(dc)}\" onclick='pickV(this)'>"
            + (f"<img src='{_html.escape(prc._proxied(img))}' loading='lazy' onerror='imgFail(this)'>"
               if img else "<div class='noimg'>画像なし</div>")
            + f"<div class='pid'>{_html.escape(p['pid'])}</div>"
            + f"<div class='nm'>{_html.escape(p['name'][:22])}</div>"
            + f"<div class='nm'>{_html.escape((p['collab'] or p['character_family'])[:18])}"
            + (" ・公式売切" if p.get("sold_out") else "") + "</div>"
            # ★色の一覧がカタログに無い商品は、選んでも色を決められず出品できない (catalog に確認中)
            + ("" if p["colors"] else "<div class='nm' style='color:#a40'>色がカタログに無い</div>")
            + f"<button class='zb' data-img=\"{_html.escape(prc._proxied(img))}\" "
              f"onclick='zoom(event,this)'>🔍</button></div>")
    return (f"<div class='one'>カタログ候補 {len(cands)}件 — 柄を見て1つ選び、色を確かめてください</div>"
            f"<div class='vs'>{''.join(cards)}</div>")


_CSS = """
body{font-family:sans-serif;margin:12px;background:#fafafa}
h1{font-size:16px;margin:0 0 6px}.sum{font-size:12px;color:#555;margin-bottom:10px}
.it{background:#fff;border:1px solid #ddd;border-radius:6px;padding:8px;margin-bottom:10px;display:flex;gap:10px}
.it.done{opacity:.45}
.ph{display:flex;flex-direction:column;gap:4px}
.ph img{width:170px;height:220px;object-fit:contain;background:#f4f4f4;border:1px solid #eee}
.ph .sm{display:flex;gap:4px}.ph .sm img{width:54px;height:70px}
.body{flex:1;min-width:0}.t{font-size:13px;font-weight:bold;word-break:break-all}
.meta{font-size:11px;color:#666;margin:2px 0 6px}
.vs{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0}
.v{position:relative;border:1px solid #ccc;border-radius:4px;padding:4px;cursor:pointer;text-align:center;font-size:10px;width:118px}
.v.sel{border-color:#0a7;background:#e7f7f1;box-shadow:0 0 0 1px #0a7 inset}
.v img,.noimg{width:106px;height:140px;object-fit:contain;background:#f7f7f7}
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
input.q{font-size:12px;width:170px}select{font-size:12px}
#zov{display:none;position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:99;align-items:center;justify-content:center;gap:20px}
#zov.on{display:flex}#zov img{max-height:84vh;max-width:44vw;object-fit:contain;background:#fff}
#go{position:fixed;right:14px;bottom:14px;font-size:15px;padding:10px 20px;background:#0a7;color:#fff;border:none;border-radius:6px}
"""

_JS = """
function imgFail(el){var d=document.createElement('div');d.className='noimg';d.textContent='画像なし';
  if(el.parentNode) el.parentNode.replaceChild(d,el);}
function zoom(ev,el){ev.preventDefault();ev.stopPropagation();var box=el.closest('.it');
  var o=document.getElementById('zov');o.querySelector('#zl').src=box.dataset.photo||'';
  o.querySelector('#zr').src=el.dataset.img||((box.querySelector('.v.sel .zb')||{dataset:{}}).dataset.img)||'';
  o.classList.add('on');}
function zclose(){document.getElementById('zov').classList.remove('on');}
document.addEventListener('keydown',function(e){if(e.key==='Escape')zclose();});
function fillColors(box,v){var sel=box.querySelector('select.col');var cs=[];
  try{cs=JSON.parse(v.dataset.colors||'[]');}catch(e){}
  sel.innerHTML="<option value=''>色を選ぶ</option>"+cs.map(function(c){
    return "<option"+(c===v.dataset.defcolor?" selected":"")+">"+c+"</option>";}).join('');}
function pickV(el){var box=el.closest('.it');
  box.querySelectorAll('.v').forEach(function(v){v.classList.remove('sel');});
  el.classList.add('sel');box.dataset.pid=el.dataset.pid;fillColors(box,el);
  setAct(box.querySelector('button.go'));}
function lookup(inp){var box=inp.closest('.it');var q=inp.value.trim();
  if(!q||q===inp.dataset.asked)return;inp.dataset.asked=q;var slot=box.querySelector('.vslot');
  slot.innerHTML="<div class='one'>カタログを引いています… ("+q+")</div>";
  fetch('/api/search?q='+encodeURIComponent(q)+'&color='+encodeURIComponent(box.dataset.color||''))
   .then(function(r){return r.json();}).then(function(d){slot.innerHTML=d.html||'';})
   .catch(function(e){slot.innerHTML="<div class='warn'>引けませんでした ("+e+")</div>";});}
function pickRsn(sel){if(sel.value)setAct(sel.closest('.it').querySelector("button[data-a='out']"));}
function setAct(btn){var box=btn.closest('.it');
  box.querySelectorAll('.act button').forEach(function(b){b.classList.remove('sel');});
  btn.classList.add('sel');box.dataset.act=btn.dataset.a;
  if(btn.dataset.a!=='out'){var s=box.querySelector('select.rsn');if(s)s.value='';}
  box.classList.toggle('done',btn.dataset.a!=='go');}
function go(){var picks=[],nocat=[],outs=[],holds=[],nocolor=0,noreason=0;
  document.querySelectorAll('.it').forEach(function(b){var a=b.dataset.act||'';var idx=parseInt(b.dataset.idx,10);
    if(a==='go'){var c=(b.querySelector('select.col')||{}).value||'';
      if(!b.dataset.pid||!c){nocolor++;holds.push(idx);}else{picks.push({idx:idx,pid:b.dataset.pid,color:c});}}
    else if(a==='cat'){nocat.push(idx);}
    else if(a==='out'){var r=(b.querySelector('select.rsn')||{}).value||'';
      if(!r){noreason++;holds.push(idx);}else{outs.push({idx:idx,reason:r});}}
    else{holds.push(idx);}});
  var msg='出品行に追加 '+picks.length+'件 / カタログに無い '+nocat.length+'件 / 対象外 '+outs.length
    +'件 / 未結論 '+holds.length+'件';
  if(nocolor)msg+='\\n\\n商品か色が未選択 '+nocolor+'件 — 未結論に戻します';
  if(noreason)msg+='\\n\\n対象外なのに理由が未選択 '+noreason+'件 — 未結論に戻します';
  if(!confirm(msg+'\\n\\nこの内容で確定しますか?'))return;
  _send({picks:picks,nocat:nocat,outs:outs,holds:holds},'<h1>確定しました。ウィンドウを閉じてください。</h1>');}
"""


def build_html(items, catalog):
    """items → 目視ページ (bytes)。"""
    import psa_resource_confirm as prc
    import newcand_confirm as NC
    save_js = NC.SAVE_JS.replace("'imak_confirm_draft_'+location.port", "'imak_confirm_draft_ut_identify'")
    parts = ["<!doctype html><meta charset='utf-8'><title>UT 目視特定</title>",
             f"<style>{_CSS}</style>",
             "<h1>メルカリの新品 UT → カタログの商品を選ぶ</h1>",
             f"<div class='sum'>全 {len(items)}件。写真と同じ柄の商品を選び、<b>色を確かめて</b>「この商品」。"
             "候補に無ければ検索欄に作品名・キャラ名・商品番号(6桁)。"
             "<b>確信が無ければ選ばない</b> (違う柄を出すと別デザイン発送になります)。</div>"]
    for it in items:
        r = it["row"]
        photos = [u for u in (r[C_PHOTOS] or "").split("|") if u.strip()]
        main = prc._proxied(photos[0]) if photos else ""
        sm = "".join(f"<a href='{_html.escape(r[C_URL])}' target='_blank'>"
                     f"<img src='{_html.escape(prc._proxied(u))}' loading='lazy' onerror='imgFail(this)'></a>"
                     for u in photos[1:4])
        ph = (f"<div class='ph'><a href='{_html.escape(r[C_URL])}' target='_blank'>"
              f"<img src='{_html.escape(main)}' loading='lazy' onerror='imgFail(this)'></a>"
              f"<div class='sm'>{sm}</div></div>")
        price = f"¥{int(r[C_PRICE]):,}" if str(r[C_PRICE]).isdigit() else (r[C_PRICE] or "")
        parts.append(
            f"<div class='it' data-idx='{it['idx']}' data-pid='' data-color=\"{_html.escape(r[C_COLOR])}\" "
            f"data-photo=\"{_html.escape(main)}\">{ph}<div class='body'>"
            f"<div class='t'>{_html.escape((r[C_TITLE] or '')[:110])}</div>"
            f"<div class='meta'>{_html.escape(price)} ｜ 色 {_html.escape(r[C_COLOR] or '?')} ｜ "
            f"サイズ {_html.escape(r[C_SIZE] or '?')} ｜ {_html.escape((r[C_DESC] or '')[:80])}</div>"
            f"<div class='vslot'>{_cards_html(it['cands'], r[C_COLOR])}</div>"
            "<div class='act'>検索 <input class='q' placeholder='作品名 / キャラ / 6桁番号' "
            "onchange='lookup(this)'>"
            "色 <select class='col'><option value=''>先に商品を選ぶ</option></select>"
            "<button class='go' data-a='go' onclick='setAct(this)'>この商品</button>"
            "<button class='cat' data-a='cat' onclick='setAct(this)'>カタログに無い</button>"
            "<button class='ng' data-a='out' onclick='setAct(this)'>対象外</button>"
            "<select class='rsn' onchange='pickRsn(this)'><option value=''>理由を選ぶ</option>"
            + "".join(f"<option value='{k}'>{_html.escape(v)}</option>" for k, v in OUT_REASONS)
            + "</select><button class='hold' data-a='hold' onclick='setAct(this)'>保留</button>"
            "</div></div></div>")
    parts.append("<div id='zov' onclick='zclose()'><img id='zl' alt=''><img id='zr' alt=''></div>")
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


def _high_urls():
    import sheet_io
    return {u.strip() for u in sheet_io._product_ws().col_values(C_URL + 1)[1:] if u.strip()}


def load_items(limit=DEFAULT_LIMIT):
    src = _read_src()
    rows = pending_rows(src, load_ledger(), _high_urls())
    catalog = load_catalog()
    items = []
    for i, r in rows[:limit] if limit else rows:
        text = " ".join([r[C_TITLE], r[C_DESC]])
        items.append({"idx": i, "row": r, "cands": rank_candidates(text, r[C_COLOR], catalog)})
    return items, len(rows)


def count_workload():
    """パネルの残件 (出品くんは叩かない。スプシ2つとローカルの台帳だけ)。"""
    try:
        return {"pending": len(pending_rows(_read_src(), load_ledger(), _high_urls())), "error": ""}
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
        if url not in in_high:
            add_rows.append(high_row(r))
            in_high.add(url)
        add_led[url] = {"decision": "go", "product_id": p["pid"], "color": p["color"],
                        "title": r[C_TITLE], "size": r[C_SIZE], "at": now}
    for idx in res["nocat"]:
        it = by_idx.get(idx)
        if it:
            add_led[it["row"][C_URL].strip()] = {"decision": "nocat", "title": it["row"][C_TITLE], "at": now}
    for o in res["outs"]:
        it = by_idx.get(o["idx"])
        if it:
            add_led[it["row"][C_URL].strip()] = {"decision": "out", "reason": o["reason"],
                                                 "title": it["row"][C_TITLE], "at": now}
    if add_rows:
        sheet_io.append_product_rows(add_rows)         # 失敗したら例外 = 台帳は書かない
    led.update(add_led)
    save_ledger(led)
    return len(add_rows), len(add_led)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--timeout", type=int, default=10800)
    a = ap.parse_args()
    items, n_all = load_items(a.limit)
    print(f"目視に出す UT: {len(items)}件 (残り全部で {n_all}件)")
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
    print(f"   内訳: この商品 {len(res['picks'])} / カタログに無い {len(res['nocat'])} / "
          f"対象外 {len(res['outs'])} / 未結論 {len(res['holds'])} (未結論は次回また出ます)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
