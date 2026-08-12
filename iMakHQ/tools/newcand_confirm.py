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
OUT_HEADER = ["url", "category", "product_id", "cert", "候補タイトル", "元itemID", "日付"]
NG_TAB = "新規候補NG"
NG_HEADER = ["url", "理由", "日付"]

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
        out.append({"src": tab, "src_itemid": (r[0] or "").strip(),
                    "src_cert": (r[1] or "").strip(), "url": url})
    return out


def parse_result(data):
    """POST(JSON) → {picks:[{idx,pid,category,cert}], rejects:[idx], holds:[idx]} (純関数)。"""
    picks = []
    for d in (data.get("picks") or []):
        if d.get("idx") is None or not (d.get("pid") or "").strip():
            continue
        picks.append({"idx": int(d["idx"]), "pid": d["pid"].strip(),
                      "category": (d.get("category") or "").strip(),
                      "cert": re.sub(r"\D", "", str(d.get("cert") or ""))})
    return {"picks": picks,
            "rejects": [int(i) for i in (data.get("rejects") or [])],
            "holds": [int(i) for i in (data.get("holds") or [])]}


# ---------------------------------------------------------------------------
# catalog 参照 (I/O)
# ---------------------------------------------------------------------------
def catalog_variants(card_no, db=DB_PATH):
    """カード番号 → 版の一覧 [{pid, category, name, image}]。無ければ []。

    `OP05-002` は `OP05-002` / `_p` / `_p1` / `_p2` / `_EB02_LF` のように**版が複数**ある。
    ここで2件以上返った時だけ人が絵柄で選ぶ。
    """
    if not card_no:
        return []
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT product_id, category, name, name_en, images FROM products "
            "WHERE product_id = ? OR product_id LIKE ? ORDER BY LENGTH(product_id), product_id",
            (card_no, card_no + "\\_%")).fetchall()
        if not rows:
            # ポケモンの印刷番号 (006/020) は product_id と別体系なので specs 側を見る
            rows = con.execute(
                "SELECT product_id, category, name, name_en, images FROM products "
                "WHERE specs LIKE ? ORDER BY product_id LIMIT 12",
                (f'%"card_number": "{card_no}%',)).fetchall()
        out = []
        for r in rows:
            try:
                imgs = json.loads(r["images"] or "[]")
            except Exception:
                imgs = []
            img = imgs[0] if isinstance(imgs, list) and imgs else ""
            if isinstance(img, dict):
                img = img.get("url") or ""
            out.append({"pid": r["product_id"], "category": r["category"],
                        "name": r["name_en"] or r["name"] or "", "image": img})
        return out
    finally:
        con.close()


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
        card_no = extract_card_no(title)
        variants = catalog_variants(card_no) if card_no else []
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
.v{border:1px solid #ccc;border-radius:4px;padding:4px;cursor:pointer;text-align:center;font-size:10px;width:110px}
.v.sel{border-color:#0a7;background:#e7f7f1;box-shadow:0 0 0 1px #0a7 inset}
.v img{width:100px;height:135px;object-fit:contain;background:#f7f7f7}
.v .pid{font-weight:bold;word-break:break-all}
.one{font-size:12px;color:#076;font-weight:bold}
.warn{font-size:12px;color:#a40}
.act{margin-top:6px;display:flex;gap:6px;align-items:center;flex-wrap:wrap}
button{font-size:12px;padding:3px 10px;border:1px solid #bbb;background:#fff;border-radius:4px;cursor:pointer}
button.go{border-color:#0a7;color:#065}
button.go.sel{background:#0a7;color:#fff}
button.ng{border-color:#c33;color:#900}
button.ng.sel{background:#c33;color:#fff}
button.hold.sel{background:#888;color:#fff}
input.cert{font-size:12px;width:120px;padding:2px 4px}
#go{position:fixed;right:14px;bottom:14px;font-size:15px;padding:10px 20px;background:#0a7;color:#fff;border:none;border-radius:6px}
"""

_JS = """
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
  var picks=[],rejects=[],holds=[],nocert=0;
  document.querySelectorAll('.it').forEach(function(b){
    var a=b.dataset.act||'';
    var idx=parseInt(b.dataset.idx,10);
    if(a==='go'){
      var cert=(b.querySelector('input.cert')||{}).value||'';
      if(!cert.replace(/\\D/g,'')) nocert++;
      picks.push({idx:idx, pid:b.dataset.pid||'', category:b.dataset.cat||'', cert:cert});
    }
    else if(a==='ng'){rejects.push(idx);}
    else if(a==='hold'){holds.push(idx);}
  });
  var msg='出品する '+picks.length+'件 / 該当なし '+rejects.length+'件 / 保留 '+holds.length+'件';
  if(nocert) msg+='\\n\\n鑑定番号が空のものが '+nocert+'件あります。空のままだと候補タブ止まりで出品には回りません。';
  if(!confirm(msg+'\\n\\nこの内容で確定しますか?')) return;
  fetch('/',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({picks:picks,rejects:rejects,holds:holds})}).then(function(){
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
        img = prc._proxied(it["url"])
        ph = (f"<div class='ph'><a href='{_html.escape(it['url'])}' target='_blank'>"
              f"<img src='{_html.escape(img)}' loading='lazy'></a></div>")
        price = f"¥{it['price']:,}" if isinstance(it["price"], int) else ""
        title = it["title"] or "(タイトル不明 — リンクを開いて確認)"
        vs = it["variants"]
        if len(vs) == 1:
            v = vs[0]
            body_v = (f"<div class='one'>カタログで確定: {_html.escape(v['pid'])} "
                      f"{_html.escape(v['name'])} ({_html.escape(v['category'])})</div>")
            pid0, cat0 = v["pid"], v["category"]
        elif vs:
            cards = "".join(
                f"<div class='v' data-pid=\"{_html.escape(v['pid'])}\" "
                f"data-cat=\"{_html.escape(v['category'])}\" onclick='pickV(this)'>"
                + (f"<img src='{_html.escape(prc._proxied(v['image']))}' loading='lazy'>"
                   if v["image"] else "<div style='height:135px;color:#999'>画像なし</div>")
                + f"<div class='pid'>{_html.escape(v['pid'])}</div></div>" for v in vs)
            body_v = (f"<div class='warn'>版が {len(vs)} つあります — 絵柄で選んでください</div>"
                      f"<div class='vs'>{cards}</div>")
            pid0, cat0 = "", ""
        else:
            body_v = ("<div class='warn'>カタログに該当なし "
                      "(番号が読めない/未収録)。出品には回せません</div>")
            pid0, cat0 = "", ""
        parts.append(
            f"<div class='it' data-idx='{it['idx']}' data-pid=\"{_html.escape(pid0)}\" "
            f"data-cat=\"{_html.escape(cat0)}\">{ph}<div class='body'>"
            f"<div class='t'>{_html.escape(title[:110])}</div>"
            f"<div class='meta'>{price} ｜ 番号 {_html.escape(it['card_no'] or '?')} ｜ "
            f"元 {_html.escape(it['src'])} (出品 {_html.escape(it['src_itemid'])})</div>"
            f"{body_v}"
            "<div class='act'>鑑定番号 <input class='cert' placeholder='写真のラベルから'>"
            "<button class='go' data-a='go' onclick='setAct(this)'>出品する</button>"
            "<button class='ng' data-a='ng' onclick='setAct(this)'>該当なし</button>"
            "<button class='hold' data-a='hold' onclick='setAct(this)'>保留</button>"
            "</div></div></div>")
    parts.append(f"<button id='go' onclick='go()'>確定</button><script>{_JS}</script>")
    return "".join(parts).encode("utf-8")


# ---------------------------------------------------------------------------
# 書込 (I/O)
# ---------------------------------------------------------------------------
def _append_tab(tab, header, new_rows):
    cur = sheet_io.read_tab(tab) or []
    body = cur[1:] if cur else []
    sheet_io.write_rows_to_tab(tab, [header] + body + new_rows)


def save(items, res):
    """確定結果を候補タブ / NGタブへ (I/O)。戻り: (確定件数, NG件数)。"""
    today = _today()
    by_idx = {it["idx"]: it for it in items}
    picks = []
    for p in res["picks"]:
        it = by_idx.get(p["idx"])
        if not it:
            continue
        picks.append([it["url"], p["category"], p["pid"], p["cert"],
                      (it["title"] or "")[:60], it["src_itemid"], today])
    ngs = [[by_idx[i]["url"], "該当なし(目視)", today] for i in res["rejects"] if i in by_idx]
    if picks:
        _append_tab(OUT_TAB, OUT_HEADER, picks)
        print(f"  ✅ {OUT_TAB}: +{len(picks)}件")
        _no_cert = [p for p in picks if not p[3]]
        if _no_cert:
            print(f"     ⚠ うち鑑定番号なし {len(_no_cert)}件 = 出品には回せない (候補タブ止まり)")
    if ngs:
        _append_tab(NG_TAB, NG_HEADER, ngs)
        print(f"  🚫 {NG_TAB}: +{len(ngs)}件 (次回は出さない)")
    if res["holds"]:
        print(f"  ⏸ 保留 {len(res['holds'])}件 (台帳はそのまま = 次回また出る)")
    return len(picks), len(ngs)


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
