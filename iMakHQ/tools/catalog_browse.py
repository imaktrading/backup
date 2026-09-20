#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""カタログの中身を画像つきで見る (HTML を書いて開く)。

    python iMakHQ/tools/catalog_browse.py                      # 既定 (ポケモン 400件)
    python iMakHQ/tools/catalog_browse.py --game one_piece_tcg --q ルフィ
    python iMakHQ/tools/catalog_browse.py --q 105/078 --limit 200

★2026-09-20 ユーザー「こんな画面構成で、カタログの内容も見てみたいな。カード番号や、
  キャラ、ポケモンなのか、ワンピなのか等、絞れて」。売れ筋の画面と同じ作りにする。

★これは **1丁目1番地の判定道具**。ユーザー「本当にカタログにないのか、引き方に問題が
  あるのか、一発でわかる」。売れ筋の画面で「要補充」と出た番号をここで引けば、
  ①カタログに無い のか ②こちらの引き方が悪い のかが その場で分かる。
  0件で返れば ①、出てくれば ②。

★**値は写すだけ**。ここで直さない。おかしければカタログに直してもらう。
"""
import argparse
import json
import os
import sqlite3
import sys
import webbrowser

DB = r"C:/dev/iMak_data/catalog/products.sqlite"
OUT = r"C:/dev/iMak_data/hq/catalog_browse.html"

GAMES = [("pokemon_tcg", "ポケモン"), ("one_piece_tcg", "ワンピース"),
         ("dragonball_scg", "ドラゴンボール"), ("gundam_tcg", "ガンダム"),
         ("yugioh_tcg", "遊戯王"), ("uniqlo_ut", "UT"), ("gshock", "G-SHOCK"),
         ("", "全部")]


def first_image(images_json):
    """images (JSON配列の文字列) → 先頭のURL (純関数)。無ければ空。"""
    try:
        v = json.loads(images_json) if isinstance(images_json, str) else images_json
    except Exception:                                          # noqa: BLE001
        return ""
    if isinstance(v, list) and v:
        return str(v[0])
    return str(v) if isinstance(v, str) else ""


def is_cert_image(url):
    """PSA の鑑定画像か (純関数)。カタログが実物写真しか持っていない印。

    ★2026-09-20 ユーザー「91はなんで実物画像なの? PSA画像かもしれないけど、
      カタログ画像ないの?」→ 実際にそうだった (CLK-007 は鑑定画像1枚だけ)。
    """
    return "d1htnxwo4o0jhw.cloudfront.net/cert/" in (url or "")


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


def spec_of(specs_json, key):
    """specs (JSON) から1つ取り出す (純関数)。"""
    try:
        d = json.loads(specs_json) if isinstance(specs_json, str) else (specs_json or {})
    except Exception:                                          # noqa: BLE001
        return ""
    return str(d.get(key) or "") if isinstance(d, dict) else ""


_HEAD = """<!doctype html><html lang="ja"><meta charset="utf-8">
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
       padding:5px 14px;font-size:13px}
 .chip.on{background:#1e3a5f;color:#8ec8ff;border-color:#2f5d94}
 input.s{background:var(--card);border:1px solid var(--line);color:var(--ink);border-radius:8px;
         padding:7px 12px;font-size:14px;min-width:280px}
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
 .empty{padding:40px 22px;color:#ffc48e;font-size:15px;font-weight:700}
</style>
"""


def html(rows, game, q):
    """カタログの一覧を1枚の HTML にする (純関数)。"""
    def esc(v):
        return (str(v) if v is not None else "").replace("&", "&amp;") \
            .replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    body, certs, noimg = [], 0, 0
    for pid, name, name_jp, cat, set_name, images, specs in rows:
        url = first_image(images)
        cert = is_cert_image(url)
        certs += 1 if cert else 0
        noimg += 0 if url else 1
        img = ("<img class='c' src='" + esc(url) + "' loading='lazy' alt=''>"
               if url else "<div class='none'>画像なし</div>")
        rarity = spec_of(specs, "rarity")
        no_txt = spec_of(specs, "card_number_text") or pid
        tags = "<span class='tag'>" + esc(cat) + "</span>"
        if rarity:
            tags += "<span class='tag'>" + esc(rarity) + "</span>"
        if cert:
            tags += "<span class='tag cert'>鑑定画像</span>"
        key = " ".join([pid, name or "", name_jp or "", set_name or "", no_txt]).lower()
        body.append(
            "<div class='it' data-k=\"" + esc(key) + "\"><div class='ph'>" + img + "</div>"
            "<div class='nm'>" + esc(name_jp or name or pid) + "</div>"
            "<div class='en'>" + esc(name if name != name_jp else "") + "</div>"
            "<div class='no'>" + esc(pid) + " · " + esc(no_txt) + "</div>"
            "<div>" + tags + "</div>"
            "<div class='set'>" + esc(set_name or "") + "</div></div>")
    games = "".join(
        "<span class='chip" + (" on" if g == game else "") + "'>" + esc(t) + "</span>"
        for g, t in GAMES)
    sub = str(len(rows)) + "件を表示"
    if q:
        sub += " · 絞り込み「" + esc(q) + "」"
    if certs:
        sub += " · 鑑定画像しか無い物 " + str(certs) + "件"
    if noimg:
        sub += " · 画像なし " + str(noimg) + "件"
    grid = ("".join(body) if body else
            "<div class='empty'>0件 — この条件ではカタログに在りません "
            "(引き方ではなく、データが無い)</div>")
    return (_HEAD +
            "<header><h1>カタログを見る</h1><div class='sum'>" + sub +
            " · 値は写すだけ。直すのはカタログの仕事</div></header>"
            "<div class='bar'>" + games +
            "<input class='s' id='q' placeholder='番号・名前・セットで絞る "
            "(例 105/078 / ピカチュウ)'></div>"
            "<div class='grid' id='g'>" + grid + "</div>"
            "<script>"
            "document.getElementById('q').oninput=function(){var v=this.value.toLowerCase();"
            "var n=0;document.querySelectorAll('.it').forEach(function(e){"
            "var ok=(!v||e.dataset.k.indexOf(v)>=0);e.style.display=ok?'':'none';if(ok)n++;});"
            "document.querySelector('.sum').textContent=n+'件';};"
            "</script></html>")


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", default="pokemon_tcg")
    ap.add_argument("--q", default="")
    ap.add_argument("--limit", type=int, default=400)
    a = ap.parse_args(argv[1:])
    conn = sqlite3.connect(DB)
    rows = fetch(conn, a.game, a.q, a.limit)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html(rows, a.game, a.q))
    print("カタログ " + str(len(rows)) + "件 → " + OUT)
    if not rows:
        print("★0件 = この条件ではカタログに無い (引き方ではなく、データが無い)")
    webbrowser.open("file:///" + OUT.replace("\\", "/"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
