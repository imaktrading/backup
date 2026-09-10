# -*- coding: utf-8 -*-
"""ユニクロ UT / GU のカタログを **1枚の HTML** で見られるようにする (2026-09-10 新設).

## なぜ要るか

DB に入れても、入っているかどうかは人が見ないと分からない。
これまでは確認のたびに使い捨ての HTML を書いていた (`_data/catalog/ut_catalog.html` は
生成元が残っていなかった)。**道具にして残す**。

## 何が見えるか

    索引      シリーズ・キャラ / コラボ / 性別 / ブランド / 現役・廃盤 /
              持っている情報 (実寸表・原産国・コラボ紹介文) / 名前の頭文字
    一覧      画像つきのカード。絞り込みと語句検索がその場で効く
    1件の中身  全画像 / 実寸表 (cm・inch) / 素材 / 原産国 / 透け感 / 説明 / コラボ紹介文

★対象は **大人だけ** (キッズ・ベビーは扱わない。2026-09-09 ユーザー確定)。
★一覧の画像は `?width=320` (8KB)。DB が持つ 2100x2800 は1件を開いた時だけ読む
  (1,300件ぶんの原寸を並べるとブラウザが死ぬ)。

実行:
    python tools/ut_catalog_html.py
    python tools/ut_catalog_html.py --open      # 生成して既定のブラウザで開く
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import webbrowser
from collections import Counter
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

OUT = Path("C:/dev/iMak_data/catalog/ut_catalog.html")
KID = {"KIDS", "BABY"}
BRANDS = {"uniqlo_ut": "UT", "gu": "GU"}
PDP = {"UT": "https://www.uniqlo.com/jp/ja/products/{pid}/00",
       "GU": "https://www.gu-global.com/jp/ja/products/{pid}/00"}
# 名前の頭文字の索引。UT の商品名は「コラボ名 + UT」の形なので頭文字がよく効く
KANA = [("あ", "あぁいぃうぅえぇおぉ"), ("か", "かがきぎくぐけげこご"),
        ("さ", "さざしじすずせぜそぞ"), ("た", "ただちぢっつづてでとど"),
        ("な", "なにぬねの"), ("は", "はばぱひびぴふぶぷへべぺほぼぽ"),
        ("ま", "まみむめも"), ("や", "やゃゆゅよょ"), ("ら", "らりるれろ"),
        ("わ", "わをん")]


def _thumb(url: str) -> str:
    return (url or "").split("?")[0] + "?width=320"


def _initial(name: str) -> str:
    """頭文字を索引の見出しに寄せる (英数字はそのまま / カタカナは ひらがなの行へ)."""
    ch = (name or "").strip()[:1]
    if not ch:
        return "#"
    if ch.isascii() and ch.isalnum():
        return ch.upper()
    # カタカナ -> ひらがな に寄せてから行を引く
    h = chr(ord(ch) - 0x60) if "ァ" <= ch <= "ヶ" else ch
    for head, members in KANA:
        if h in members:
            return head
    return "#"


def collect() -> list[dict]:
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    db.row_factory = sqlite3.Row
    out: list[dict] = []
    for cat, brand in BRANDS.items():
        for r in db.execute(
                "SELECT product_id, name, specs, images FROM products WHERE category=?",
                (cat,)):
            s = json.loads(r["specs"] or "{}")
            if str(s.get("gender") or "").upper() in KID:
                continue
            if s.get("is_collab_overview"):        # 商品でない行 (コラボの紹介記事)
                continue
            imgs = json.loads(r["images"] or "[]") or s.get("image_urls") or []
            live = not s.get("official_gone_at")
            out.append({
                "p": r["product_id"], "n": r["name"] or "", "b": brand,
                "g": str(s.get("gender") or "").upper() or "—",
                "s": "現役" if live else "廃盤",
                "i": imgs, "t": _thumb(imgs[0]) if imgs else "",
                "pr": s.get("price_jpy_base") or "",
                "c": [x.get("name") for x in (s.get("color_variants") or [])
                      if isinstance(x, dict) and x.get("name")],
                "z": [x.get("name") for x in (s.get("size_variants") or [])
                      if isinstance(x, dict) and x.get("name")],
                "co": s.get("composition") or "",
                "or": s.get("countries_of_origin") or [],
                "dd": s.get("design_detail") or "",
                "ld": s.get("long_description") or s.get("short_description") or "",
                "ca": s.get("care_instruction") or s.get("washing_information") or "",
                "sc": s.get("size_chart") or [], "si": s.get("size_chart_inch") or [],
                "sa": s.get("size_chart_absent_reason") or "",
                "cb": s.get("collab") or "", "cf": s.get("character_family") or "",
                "cn": s.get("collab_official_name") or "",
                "ct": s.get("collab_official_text") or "",
                # ★仕入れの判断そのもの: 公式で買えるものは商売にならない
                "b2": ("公式で買える" if s.get("in_stock")
                       else ("買えない" if s.get("stock_checked_at") else "未確認")),
                "st": s.get("stock_total") or 0,
                "ss": s.get("stock_by_size") or {},
                "so": (s.get("sold_out_since") or "")[:10],
                "u": PDP[brand].format(pid=r["product_id"]),
                "k": _initial(r["name"] or ""),
            })
    db.close()
    out.sort(key=lambda x: (x["b"], x["cf"] or "\uffff", x["n"]))
    return out


def build(rows: list[dict]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    n_img = sum(len(x["i"]) for x in rows)
    n_sc = sum(1 for x in rows if x["sc"])
    n_or = sum(1 for x in rows if x["or"])
    n_ct = sum(1 for x in rows if x["ct"])
    n_buy = sum(1 for x in rows if x["b2"] == "買えない")
    facets = {
        "仕入れ対象か": Counter(x["b2"] for x in rows),
        "ブランド": Counter(x["b"] for x in rows),
        "状態": Counter(x["s"] for x in rows),
        "性別": Counter(x["g"] for x in rows),
        "シリーズ・キャラ": Counter(x["cf"] or "（なし）" for x in rows),
        "コラボ": Counter(x["cb"] or "（なし）" for x in rows),
        "頭文字": Counter(x["k"] for x in rows),
    }
    have = {"実寸表あり": n_sc, "原産国あり": n_or, "コラボ紹介文あり": n_ct,
            "画像5枚以上": sum(1 for x in rows if len(x["i"]) >= 5)}
    # ★`</script>` が説明文に入ると そこで JS が切れる。エスケープしておく
    data = json.dumps(rows, ensure_ascii=False,
                      separators=(",", ":")).replace("</", "<\\/")
    fjson = json.dumps({k: v.most_common() for k, v in facets.items()},
                       ensure_ascii=False, separators=(",", ":"))
    hjson = json.dumps(have, ensure_ascii=False, separators=(",", ":"))
    return _TEMPLATE.replace("__DATA__", data).replace("__FACETS__", fjson) \
        .replace("__HAVE__", hjson).replace("__NOW__", now) \
        .replace("__N__", f"{len(rows):,}").replace("__NIMG__", f"{n_img:,}") \
        .replace("__NSC__", f"{n_sc:,}").replace("__NBUY__", f"{n_buy:,}")


_TEMPLATE = r"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ユニクロ UT / GU カタログ</title>
<style>
 :root{--bg:#fff;--fg:#16181d;--dim:#6b7280;--line:#e5e7eb;--card:#fff;--accent:#c8102e;
       --chip:#f3f4f6;--shadow:0 1px 3px rgba(0,0,0,.08)}
 @media(prefers-color-scheme:dark){:root{--bg:#111317;--fg:#e8eaed;--dim:#9aa0a6;
       --line:#2a2e35;--card:#1a1d22;--chip:#23272e;--shadow:0 1px 3px rgba(0,0,0,.5)}}
 *{box-sizing:border-box}
 body{margin:0;background:var(--bg);color:var(--fg);
      font:14px/1.6 -apple-system,"Segoe UI","Hiragino Kaku Gothic ProN","Yu Gothic",sans-serif}
 header{position:sticky;top:0;z-index:20;background:var(--bg);border-bottom:1px solid var(--line);
        padding:10px 16px;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
 h1{font-size:16px;margin:0;font-weight:700;letter-spacing:.02em}
 h1 b{color:var(--accent)}
 .stat{color:var(--dim);font-size:12px}
 #q{flex:1;min-width:200px;padding:7px 11px;border:1px solid var(--line);border-radius:7px;
    background:var(--card);color:var(--fg);font-size:14px}
 .wrap{display:flex;align-items:flex-start}
 aside{width:262px;flex:none;padding:14px 12px 60px;border-right:1px solid var(--line);
       position:sticky;top:53px;max-height:calc(100vh - 53px);overflow-y:auto}
 aside h2{font-size:11px;letter-spacing:.12em;color:var(--dim);margin:16px 0 6px;font-weight:700}
 aside h2:first-child{margin-top:0}
 .fx{max-height:230px;overflow-y:auto;margin:0 -4px}
 .f{display:flex;justify-content:space-between;gap:8px;padding:3px 7px;border-radius:5px;
    cursor:pointer;font-size:13px}
 .f:hover{background:var(--chip)}
 .f.on{background:var(--accent);color:#fff}
 .f span:last-child{color:var(--dim);font-variant-numeric:tabular-nums;font-size:12px}
 .f.on span:last-child{color:#fff;opacity:.8}
 .kana{display:flex;flex-wrap:wrap;gap:3px}
 .kana .f{padding:2px 8px;min-width:30px;justify-content:center}
 .kana .f span:last-child{display:none}
 main{flex:1;min-width:0;padding:14px 16px 80px}
 .bar{display:flex;gap:8px;align-items:center;margin-bottom:12px;flex-wrap:wrap;
      font-size:13px;color:var(--dim)}
 .tag{background:var(--chip);border-radius:20px;padding:3px 11px;cursor:pointer;font-size:12px}
 .tag:hover{color:var(--accent)}
 .grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(168px,1fr))}
 .c{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;
    cursor:pointer;box-shadow:var(--shadow);transition:transform .12s}
 .c:hover{transform:translateY(-2px)}
 .c img{width:100%;aspect-ratio:3/4;object-fit:cover;display:block;background:var(--chip)}
 .c .m{padding:7px 9px 9px}
 .c .nm{font-size:12px;line-height:1.4;height:2.8em;overflow:hidden}
 .c .sub{font-size:11px;color:var(--dim);margin-top:4px;display:flex;gap:6px;flex-wrap:wrap}
 .pill{font-size:10px;border-radius:4px;padding:0 4px;background:var(--chip)}
 .pill.gone{background:#7c2d12;color:#fed7aa}
 .pill.buy{background:var(--accent);color:#fff}
 .pill.gu{background:#1e3a8a;color:#dbeafe}
 #ov{position:fixed;inset:0;z-index:40;background:rgba(0,0,0,.62);display:none;
     overflow-y:auto;padding:26px 16px}
 #ov.on{display:block}
 .dl{max-width:1000px;margin:0 auto;background:var(--bg);border-radius:12px;padding:20px}
 .dl .top{display:flex;gap:20px;flex-wrap:wrap}
 .dl .big img{width:min(360px,80vw);border-radius:8px;background:var(--chip)}
 .thumbs{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;max-width:min(360px,80vw)}
 .thumbs img{width:52px;height:69px;object-fit:cover;border-radius:4px;cursor:pointer;
             border:2px solid transparent}
 .thumbs img.on{border-color:var(--accent)}
 .dl .info{flex:1;min-width:260px}
 .dl h3{margin:0 0 4px;font-size:17px}
 table{border-collapse:collapse;width:100%;font-size:13px;margin-top:6px}
 th,td{border:1px solid var(--line);padding:4px 8px;text-align:left}
 th{background:var(--chip);font-weight:600}
 .kv{margin-top:14px}
 .kv div{display:flex;gap:10px;padding:3px 0;border-bottom:1px solid var(--line);font-size:13px}
 .kv div b{flex:none;width:84px;color:var(--dim);font-weight:600}
 .close{float:right;cursor:pointer;color:var(--dim);font-size:22px;line-height:1;padding:0 4px}
 .none{color:var(--dim);padding:40px 0;text-align:center}
 a{color:var(--accent)}
</style></head><body>
<header>
 <h1>ユニクロ <b>UT</b> / GU カタログ</h1>
 <input id="q" placeholder="商品名・品番・コラボ名・素材で検索">
 <div class="stat">__N__着 / 画像 __NIMG__枚 / 実寸表 __NSC__件 ·
   <b style="color:var(--accent)">公式で買えない __NBUY__着</b> = 仕入れ対象 &nbsp;·&nbsp; __NOW__</div>
</header>
<div class="wrap">
 <aside id="idx"></aside>
 <main><div class="bar" id="bar"></div><div class="grid" id="g"></div></main>
</div>
<div id="ov"><div class="dl" id="dl"></div></div>
<script>
const D=__DATA__, F=__FACETS__, H=__HAVE__;
const KEY={"仕入れ対象か":"b2","ブランド":"b","状態":"s","性別":"g","シリーズ・キャラ":"cf","コラボ":"cb","頭文字":"k"};
const HAVEF={"実寸表あり":r=>r.sc.length,"原産国あり":r=>r.or.length,
             "コラボ紹介文あり":r=>r.ct,"画像5枚以上":r=>r.i.length>=5};
let sel={}, have=null, q="";

function idx(){
 let h="";
 h+='<h2>持っている情報</h2><div class="fx">'+Object.keys(H).map(k=>
    `<div class="f${have===k?" on":""}" data-h="${k}"><span>${k}</span><span>${H[k]}</span></div>`
 ).join("")+"</div>";
 for(const g of Object.keys(F)){
   const rows=F[g].map(([v,n])=>
     `<div class="f${(sel[g]||[]).includes(v)?" on":""}" data-g="${g}" data-v="${esc(v)}">`+
     `<span>${esc(v)}</span><span>${n}</span></div>`).join("");
   h+=`<h2>${g}</h2><div class="${g==="頭文字"?"kana":"fx"}">${rows}</div>`;
 }
 const a=document.getElementById("idx"); a.innerHTML=h;
 a.querySelectorAll("[data-g]").forEach(e=>e.onclick=()=>{
   const g=e.dataset.g,v=e.dataset.v,cur=sel[g]||[];
   sel[g]=cur.includes(v)?cur.filter(x=>x!==v):cur.concat([v]);
   if(!sel[g].length)delete sel[g]; idx(); draw();
 });
 a.querySelectorAll("[data-h]").forEach(e=>e.onclick=()=>{
   have=have===e.dataset.h?null:e.dataset.h; idx(); draw();
 });
}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}
function hit(r){
 for(const g of Object.keys(sel)){
   const v=r[KEY[g]]||"（なし）";
   if(!sel[g].includes(v||"（なし）"))return false;
 }
 if(have&&!HAVEF[have](r))return false;
 if(q){const s=(r.n+" "+r.p+" "+r.cb+" "+r.cf+" "+r.co+" "+r.cn).toLowerCase();
       if(!q.split(/\s+/).every(w=>s.includes(w)))return false;}
 return true;
}
function draw(){
 const list=D.filter(hit);
 const chips=Object.entries(sel).flatMap(([g,vs])=>vs.map(v=>
   `<span class="tag" data-g="${g}" data-v="${esc(v)}">${esc(v)} ×</span>`)).join("")
   +(have?`<span class="tag" data-h="1">${have} ×</span>`:"");
 document.getElementById("bar").innerHTML=`<b>${list.length.toLocaleString()}</b>着 ${chips}`;
 document.querySelectorAll("#bar .tag").forEach(e=>e.onclick=()=>{
   if(e.dataset.h){have=null;}
   else{sel[e.dataset.g]=sel[e.dataset.g].filter(x=>x!==e.dataset.v);
        if(!sel[e.dataset.g].length)delete sel[e.dataset.g];}
   idx();draw();
 });
 const g=document.getElementById("g");
 if(!list.length){g.innerHTML='<div class="none">該当なし</div>';return;}
 g.innerHTML=list.map(r=>`<div class="c" data-p="${r.p}">
   <img loading="lazy" src="${r.t}" alt="">
   <div class="m"><div class="nm">${esc(r.n)}</div><div class="sub">
     <span class="pill${r.b==="GU"?" gu":""}">${r.b}</span>
     ${r.b2==="買えない"?'<span class="pill buy">買えない</span>':""}
     ${r.s==="廃盤"?'<span class="pill gone">廃盤</span>':""}
     ${r.sc.length?'<span class="pill">実寸表</span>':""}
     <span>${r.i.length}枚</span></div></div></div>`).join("");
 g.querySelectorAll(".c").forEach(e=>e.onclick=()=>openItem(e.dataset.p));
}
function tbl(rows){
 if(!rows.length)return"";
 const cols=Object.keys(rows[0]).filter(k=>k!=="size");
 const jp={length:"身丈",shoulder:"肩幅",chest:"身幅",sleeve:"裄丈"};
 return`<table><tr><th>サイズ</th>${cols.map(c=>`<th>${jp[c]||c}</th>`).join("")}</tr>`
  +rows.map(r=>`<tr><td>${esc(r.size)}</td>${cols.map(c=>`<td>${esc(r[c]||"")}</td>`).join("")}</tr>`).join("")
  +`</table>`;
}
function openItem(pid){
 const r=D.find(x=>x.p===pid);
 const kv=[["品番",r.p],["ブランド",r.b],["状態",r.s],["性別",r.g],
   ["価格",r.pr?("¥"+Number(r.pr).toLocaleString()):""],["色",r.c.join(" / ")],
   ["サイズ",r.z.join(" / ")],["素材",r.co],["原産国",r.or.join(" / ")],
   ["シリーズ",r.cf],["コラボ",r.cb],["お手入れ",r.ca],
   ["公式在庫",r.b2==="未確認"?"":(r.b2+(r.st?` (${r.st}点)`:"")+(r.so?` / ${r.so} から売り切れ`:""))],
   ["サイズ別在庫",Object.keys(r.ss||{}).length?Object.entries(r.ss).map(([k,v])=>`${k}:${v}`).join("  "):""]]
   .filter(x=>x[1]).map(([k,v])=>`<div><b>${k}</b><span>${esc(v)}</span></div>`).join("");
 document.getElementById("dl").innerHTML=`
  <span class="close" onclick="document.getElementById('ov').classList.remove('on')">×</span>
  <div class="top">
    <div class="big"><img id="bi" src="${r.i[0]||""}" alt="">
      <div class="thumbs">${r.i.map((u,j)=>
        `<img src="${u.split("?")[0]}?width=160" class="${j?"":"on"}" data-u="${u}">`).join("")}</div>
    </div>
    <div class="info"><h3>${esc(r.n)}</h3>
      <div style="color:var(--dim);font-size:12px">
        <a href="${r.u}" target="_blank" rel="noopener">公式ページ</a> · 画像 ${r.i.length}枚</div>
      <div class="kv">${kv}</div>
    </div>
  </div>
  ${r.dd?`<h3 style="margin-top:18px;font-size:14px">仕様</h3>
          <div style="font-size:13px">${r.dd}</div>`:""}
  ${r.ld?`<h3 style="margin-top:14px;font-size:14px">説明</h3>
          <div style="font-size:13px">${r.ld}</div>`:""}
  ${r.ct?`<h3 style="margin-top:14px;font-size:14px">コラボ紹介 ${esc(r.cn)}</h3>
          <div style="font-size:13px">${esc(r.ct)}</div>`:""}
  ${r.sc.length?`<h3 style="margin-top:18px;font-size:14px">実寸表 (仕上がり寸)</h3>
     <div style="display:flex;gap:22px;flex-wrap:wrap">
       <div style="flex:1;min-width:260px"><div style="color:var(--dim);font-size:12px">cm</div>${tbl(r.sc)}</div>
       ${r.si.length?`<div style="flex:1;min-width:260px"><div style="color:var(--dim);font-size:12px">inch</div>${tbl(r.si)}</div>`:""}
     </div>`
   :`<div style="margin-top:16px;color:var(--dim);font-size:13px">実寸表なし${r.sa?" — "+esc(r.sa):(r.s==="廃盤"?" — 廃盤で公式ページごと消えており、復元手段がありません":"")}</div>`}`;
 document.querySelectorAll(".thumbs img").forEach(e=>e.onclick=()=>{
   document.getElementById("bi").src=e.dataset.u;
   document.querySelectorAll(".thumbs img").forEach(x=>x.classList.remove("on"));
   e.classList.add("on");
 });
 document.getElementById("ov").classList.add("on");
 document.getElementById("ov").scrollTop=0;
}
document.getElementById("ov").onclick=e=>{if(e.target.id==="ov")e.currentTarget.classList.remove("on")};
document.onkeydown=e=>{if(e.key==="Escape")document.getElementById("ov").classList.remove("on")};
document.getElementById("q").oninput=e=>{q=e.target.value.trim().toLowerCase();draw()};
idx();draw();
</script></body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()

    rows = collect()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(rows), encoding="utf-8")
    print(f"  {len(rows):,}着 / 画像 {sum(len(x['i']) for x in rows):,}枚 / "
          f"実寸表 {sum(1 for x in rows if x['sc']):,}件")
    print(f"  {out}  ({out.stat().st_size / 1024 / 1024:.1f} MB)")
    if a.open:
        webbrowser.open(out.as_uri())


if __name__ == "__main__":
    main()
