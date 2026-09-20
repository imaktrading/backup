#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""カタログの中身を画像つきで見る (HTML を開く。絞り込みは画面の中で)。

    python iMakHQ/tools/catalog_browse.py

★2026-09-20 ユーザー「こんな画面構成で、カタログの内容も見てみたいな。カード番号や、
  キャラ、ポケモンなのか、ワンピなのか等、絞れて」
  → 続けて「開ける前に条件入れないとダメでしょ。開けてから絞り込みたい」。
  カタログは10万件あって1枚の HTML には収まらないので、**画面から出品くんに聞く**形に
  した (`/api/catalog`)。商材の切り替えも絞り込みも、開いたまま出来る。

★これは **1丁目1番地の判定道具**。ユーザー「本当にカタログにないのか、引き方に問題が
  あるのか、一発でわかる」。売れ筋の画面で「要補充」と出た番号をここで引けば、
  ①カタログに無い のか ②こちらの引き方が悪い のかが その場で分かる。
  0件で返れば ①、出てくれば ②。

★**値は写すだけ**。ここで直さない。おかしければカタログに直してもらう。
"""
import json
import os
import sqlite3
import sys
import webbrowser

DB = None   # ↓ catalog_lookup から借りる
OUT = r"C:/dev/iMak_data/hq/catalog_browse.html"
API = "http://127.0.0.1:8770/api/catalog"

GAMES = [("pokemon_tcg", "ポケモン"), ("one_piece_tcg", "ワンピース"),
         ("dragonball_scg", "ドラゴンボール"), ("gundam_tcg", "ガンダム"),
         ("yugioh_tcg", "遊戯王"), ("uniqlo_ut", "UT"), ("gshock", "G-SHOCK"),
         ("", "全部")]


# ★2026-09-20: 引き方と画像の選び方は **tools/catalog_lookup.py が唯一の口**。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import catalog_lookup as _CL                                   # noqa: E402

DB = _CL.DB
first_image = _CL.first_image
_is_en_image = _CL.is_en_image
is_cert_image = _CL.is_cert_image
spec_of = _CL.spec_of


def fetch(conn, game="", q="", limit=400):
    """カタログを引く (I/O)。q は 番号・名前・セット・特性のどれに当たってもよい。"""
    sql = ["SELECT product_id, name, name_jp, category, set_name, images, specs FROM products"]
    where, args = [], []
    if game:
        where.append("category = ?")
        args.append(game)
    if q:
        where.append("(product_id LIKE ? OR name LIKE ? OR name_jp LIKE ? "
                     "OR set_name LIKE ? OR specs LIKE ?)")
        args += ["%" + q + "%"] * 5
    if where:
        sql.append("WHERE " + " AND ".join(where))
    sql.append("ORDER BY product_id LIMIT ?")
    args.append(limit)
    return conn.execute(" ".join(sql), args).fetchall()


_PAGE = """<!doctype html><html lang="ja"><meta charset="utf-8">
<title>カタログを見る</title>
<style>
 :root{--bg:#14161a;--card:#1b1e24;--line:#2a2f38;--ink:#e8eaed;--ink2:#a9b0bb;--ink3:#767d88;
       --sunken:#20242b}
 html,body{height:100%}
 body{margin:0;background:var(--bg);color:var(--ink);height:100vh;
      display:flex;flex-direction:column;overflow:hidden;
      font:14px/1.6 "Yu Gothic UI","Segoe UI",system-ui,sans-serif}
 header{padding:16px 22px;border-bottom:1px solid var(--line);flex:none}
 h1{margin:0 0 4px;font-size:20px}
 .sum{color:var(--ink2);font-size:13px}
 .bar{display:flex;gap:6px;padding:12px 22px;flex-wrap:wrap;align-items:center;
      border-bottom:1px solid var(--line);background:var(--bg);flex:none}
 .chip{background:var(--card);border:1px solid var(--line);color:var(--ink2);border-radius:20px;
       padding:5px 14px;font-size:13px;cursor:pointer}
 .chip.on{background:#1e3a5f;color:#8ec8ff;border-color:#2f5d94}
 input.s{background:var(--card);border:1px solid var(--line);color:var(--ink);border-radius:8px;
         padding:7px 12px;font-size:14px;min-width:300px}
 .grid{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;padding:16px 22px;
       overflow-y:auto;flex:1 1 auto;align-content:start}
 @media(max-width:1500px){.grid{grid-template-columns:repeat(4,1fr)}}
 @media(max-width:1200px){.grid{grid-template-columns:repeat(3,1fr)}}
 .it{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
 .ph{display:flex;align-items:center;justify-content:center;height:280px;margin-bottom:10px}
 img.c{max-width:100%;max-height:280px;object-fit:contain;border-radius:6px}
 .none{width:190px;height:265px;display:flex;align-items:center;justify-content:center;
       border:2px dashed #a8703a;border-radius:6px;color:#ffc48e;font-size:13px;font-weight:700}
 .nm{font-weight:700;font-size:15px}
 .en{color:var(--ink2);font-size:12px}
 .no{color:var(--ink3);font-size:12px;margin:6px 0 4px}
 .set{color:var(--ink3);font-size:11px;line-height:1.4}
 .tag{display:inline-block;border-radius:20px;padding:1px 9px;font-size:11px;font-weight:700;
      background:var(--sunken);color:var(--ink2);margin-right:5px}
 .tag.cert{background:#5f3a1e;color:#ffc48e}
 .msg{padding:40px 22px;color:#ffc48e;font-size:15px;font-weight:700}
</style>
<header><h1>カタログを見る</h1><div class="sum" id="sum">読み込み中…</div></header>
<div class="bar" id="games"></div>
<div class="bar">
  <input class="s" id="q" placeholder="番号・名前・セットで絞る (例 105/078 / ピカチュウ) — Enter で検索">
  <span class="chip" id="go">検索</span>
  <span class="sum">値は写すだけ。直すのはカタログの仕事</span>
</div>
<div class="grid" id="g"></div>
<script>
var API = "__API__", GAMES = __GAMES__, game = "pokemon_tcg";
function esc(v){return (v==null?"":String(v)).replace(/[&<>"]/g,function(c){
  return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c];});}
function chips(){
  document.getElementById("games").innerHTML = GAMES.map(function(g){
    return "<span class='chip"+(g[0]===game?" on":"")+"' data-g='"+g[0]+"'>"+esc(g[1])+"</span>";
  }).join("");
  document.querySelectorAll("#games .chip").forEach(function(b){
    b.onclick=function(){ game=b.dataset.g; chips(); load(); };});
}
function load(){
  var q = document.getElementById("q").value.trim();
  document.getElementById("sum").textContent = "読み込み中…";
  fetch(API+"?game="+encodeURIComponent(game)+"&q="+encodeURIComponent(q)+"&limit=400")
    .then(function(r){return r.json();})
    .then(function(d){
      if(d.error){ document.getElementById("g").innerHTML =
        "<div class='msg'>出品くんに聞けませんでした: "+esc(d.error)+"</div>"; return; }
      var rows = d.rows || [], cert = 0, noimg = 0;
      document.getElementById("g").innerHTML = rows.length ? rows.map(function(r){
        if(r.cert) cert++;
        if(!r.image) noimg++;
        var img = r.image ? "<img class='c' src='"+esc(r.image)+"' loading='lazy' alt=''>"
                          : "<div class='none'>画像なし</div>";
        var tags = "<span class='tag'>"+esc(r.category)+"</span>";
        if(r.rarity) tags += "<span class='tag'>"+esc(r.rarity)+"</span>";
        if(r.cert) tags += "<span class='tag cert'>鑑定画像</span>";
        return "<div class='it'><div class='ph'>"+img+"</div>"+
          "<div class='nm'>"+esc(r.name_jp||r.name||r.product_id)+"</div>"+
          "<div class='en'>"+esc(r.name!==r.name_jp?r.name:"")+"</div>"+
          "<div class='no'>"+esc(r.product_id)+" · "+esc(r.no)+"</div>"+
          "<div>"+tags+"</div><div class='set'>"+esc(r.set_name||"")+"</div></div>";
      }).join("") : "<div class='msg'>0件 — この条件ではカタログに在りません "+
                    "(引き方ではなく、データが無い)</div>";
      var s = rows.length+"件";
      if(q) s += " · 絞り込み「"+esc(q)+"」";
      if(cert) s += " · 鑑定画像しか無い物 "+cert+"件";
      if(noimg) s += " · 画像なし "+noimg+"件";
      if(rows.length>=400) s += " · ★400件で打ち切り (絞り込んでください)";
      document.getElementById("sum").innerHTML = s;
    })
    .catch(function(){ document.getElementById("g").innerHTML =
      "<div class='msg'>出品くんに聞けませんでした。コンソールが動いているか見てください</div>"; });
}
document.getElementById("go").onclick = load;
document.getElementById("q").onkeydown = function(e){ if(e.key==="Enter") load(); };
chips(); load();
</script></html>
"""


def page():
    """画面の本体 (純関数)。中身は開いてから出品くんに聞く。"""
    return _PAGE.replace("__API__", API).replace("__GAMES__", json.dumps(GAMES, ensure_ascii=False))


def main(_argv):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(page())
    # 開く前に1回だけ実機で確かめる (出品くんが止まっていたら、そう言う)
    try:
        conn = sqlite3.connect(DB)
        n = len(fetch(conn, "pokemon_tcg", "", 5))
        print("カタログは読めています (見本 %d件)" % n)
    except Exception as e:                                     # noqa: BLE001
        print("⚠ カタログを読めません: %s" % e)
    print("→ %s (絞り込みは画面の中で)" % OUT)
    webbrowser.open("file:///" + OUT.replace("\\", "/"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
