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
OUT_HEADER = ["A列:仕入元URL", "C列:タイトル", "I列:cert", "R列:カテゴリ",
              "AI列:KEY", "product_id", "元itemID", "日付"]
SHEET_CATEGORY = "TCG"   # 商品管理シート R列。PSA は 'TCG'
NG_TAB = "新規候補NG"
NG_HEADER = ["url", "理由", "日付", "候補タイトル"]
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
    ("gone", "ページが消えている・確認不能"),
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
    return {"picks": picks,
            "catalog_reqs": [int(i) for i in (data.get("catalog_reqs") or [])],
            "outs": outs,
            "holds": sorted(set(holds))}


# ---------------------------------------------------------------------------
# catalog 参照 (I/O)
# ---------------------------------------------------------------------------
def _first_image(images_json):
    try:
        imgs = json.loads(images_json or "[]")
    except Exception:
        return ""
    img = imgs[0] if isinstance(imgs, list) and imgs else ""
    if isinstance(img, dict):
        img = img.get("url") or ""
    return img or ""


def _row_to_cand(r):
    return {"pid": r["product_id"], "category": r["category"],
            "name": r["name_en"] or r["name"] or "", "name_jp": r["name"] or "",
            "image": _first_image(r["images"])}


_CAND_COLS = "product_id, category, name, name_en, images"
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
        card_no = extract_card_no(title)
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
  var picks=[],creq=[],outs=[],holds=[],nocert=0,noreason=0;
  document.querySelectorAll('.it').forEach(function(b){
    var a=b.dataset.act||'';
    var idx=parseInt(b.dataset.idx,10);
    if(a==='go'){
      var cert=(b.querySelector('input.cert')||{}).value||'';
      if(!cert.replace(/\\D/g,'')) nocert++;
      picks.push({idx:idx, pid:b.dataset.pid||'', category:b.dataset.cat||'', cert:cert});
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
  if(nocert) msg+='\\n\\n鑑定番号が空 '+nocert+'件 — 空だと候補タブ止まりで出品に回りません。';
  if(noreason) msg+='\\n\\n対象外なのに理由が未選択 '+noreason+'件 — 理由が無いものは未結論に戻します。';
  if(holds.length) msg+='\\n\\n未結論は次回また出ます (ここを0にするのが目標)。';
  if(!confirm(msg+'\\n\\nこの内容で確定しますか?')) return;
  fetch('/',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({picks:picks,catalog_reqs:creq,outs:outs,holds:holds})}).then(function(){
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
        "「出品する」を押した分だけ次に進みます。鑑定番号は写真のラベルを見て入れてください "
        "(空でも記録はしますが、出品には回りません)。</div>",
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
                + f"<button class='zb' data-img=\"{_html.escape(prc._proxied(v['image']))}\" "
                  f"data-pid=\"{_html.escape(v['pid'])}\" "
                  f"onclick='zoom(event,this,\"cat\")'>🔍</button>"
                + "</div>" for v in vs)
            head = (f"<div class='one'>カタログ候補 {len(vs)}件 — 絵柄を見て選んでください</div>"
                    if len(vs) > 1 else
                    "<div class='one'>カタログ候補 1件 — 絵柄が合っていれば選んでください</div>")
            body_v = head + f"<div class='vs'>{cards}</div>"
        else:
            body_v = ("<div class='warn'>カタログ候補なし "
                      "(番号も名前も読めない/未収録)。出品には回せません</div>")
        parts.append(
            f"<div class='it' data-idx='{it['idx']}' data-pid='' data-cat='' "
            f"data-photo=\"{_html.escape(photo)}\">{ph}<div class='body'>"
            f"<div class='t'>{_html.escape(title[:110])}</div>"
            f"<div class='meta'>{price} ｜ 番号 {_html.escape(it['card_no'] or '?')} ｜ "
            f"元 {_html.escape(it['src'])} (出品 {_html.escape(it['src_itemid'])})</div>"
            f"{body_v}"
            "<div class='act'>鑑定番号 <input class='cert' placeholder='写真のラベルから'>"
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
    body = cur[1:] if cur else []
    sheet_io.write_rows_to_tab(tab, [header] + body + new_rows)


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
        picks.append([it["url"], (it["title"] or "")[:60], p["cert"], SHEET_CATEGORY,
                      key, p["pid"], it["src_itemid"], today])
    if picks:
        _append_tab(OUT_TAB, OUT_HEADER, picks)
        print(f"  ✅ {OUT_TAB}: +{len(picks)}件 "
              f"(見出しが貼り付け先の列名。商品管理シートに手でコピペしてください)")
        _no_cert = [p for p in picks if not p[2]]
        if _no_cert:
            print(f"     ⚠ うち鑑定番号なし {len(_no_cert)}件 = 出品には回せない (候補タブ止まり)")

    creqs, creq_ng = [], []
    for i in res["catalog_reqs"]:
        it = by_idx.get(i)
        if not it:
            continue
        cat = guess_category(it["title"], it["variants"])
        model = (f"{it['card_no'] or '番号不明'} {it['title'][:60]} "
                 f"(捨てた仕入候補の目視 {today} / {it['url']})")
        creqs.append([cat, model, f"{today} 00:00:00"])
        creq_ng.append([it["url"], "カタログ未収録 → 追加依頼を起票", today,
                        (it["title"] or "")[:60]])
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
    a = ap.parse_args()

    print("▶ 捨てた仕入候補 → 新規出品の種 (目視)")
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
