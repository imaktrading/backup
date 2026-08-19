#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gacha_review.py — ガチャポンの目視確認 (2026-08-20)。

画面ですること (1件あたり数十秒):
    1. **G列の写真をそのまま全部見る**。店のヘッダーやバナーも混ざっているので、
       出品に使う物にチェックを入れる (1枚目が eBay のギャラリー画像)
    2. 公式の **商品ページ** があれば URL 欄に貼る。送信すると、そのページから
       画像を拾って出品写真に足す
    3. **出品する / 出品しない** を押す。出さない時は理由を書く

なぜ人が見るのか:
    - 対象年齢 (米国 CPSIA) はどこからも機械的に取れない。実測 2026-08-20:
      楽天の商品ページHTMLに `対象年齢` の記載は0件、メーカー公式も中身は JS 描画。
      印字は台紙の写真の中にしかない
    - G列の写真は **744枚中 667枚が店のページ部品** (header/menu/バナー)。
      商品写真が1枚でもある行は93行中11行。機械には選り分けられない

fail-closed: 「出品する」を押した物 **だけ** が CSV に載る。未回答は出さない。
答えは記録して次回は聞かない。
"""
from __future__ import annotations

import html as _html
import json
import os
import re
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

LEDGER = r"C:\dev\iMak_data\hq\gacha_reviewed.json"
SERVER_PORT = 8788
_UA = {"User-Agent": "Mozilla/5.0"}

_STATE: dict = {"items": [], "result": None}
_EVENT = threading.Event()


# ── 純関数 (test 可) ────────────────────────────────────────────────


def load_ledger(path: str = LEDGER) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                           # noqa: BLE001
        return {}


def save_ledger(rec: dict, path: str = LEDGER) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)
    except Exception as e:                                      # noqa: BLE001
        print(f"  ⚠️ 目視の記録を保存できず: {type(e).__name__}: {e}")


def split_answered(items: list, ledger: dict) -> tuple[list, list]:
    """(答え済み, 聞く必要がある) に分ける。出す/出さない どちらも答え済み。"""
    done, ask = [], []
    for it in items:
        rec = (ledger or {}).get(it.get("url", ""))
        (done if rec and rec.get("decision") else ask).append(it)
    return done, ask


def confirmed(items: list, ledger: dict) -> list:
    """「出品する」と答えた物だけ返す。写真は **選んだG列 + 公式** に差し替える。"""
    out = []
    for it in items:
        rec = (ledger or {}).get(it.get("url", "")) or {}
        if rec.get("decision") != "list":
            continue
        pics = list(rec.get("pics") or []) + list(rec.get("official_pics") or [])
        if not pics:
            continue                     # 写真0枚では出せない (fail-closed)
        it = dict(it)
        it["pics"] = pics
        it["official_url"] = rec.get("official_url", "")
        out.append(it)
    return out


def skipped_reasons(items: list, ledger: dict) -> list:
    """出さなかった物 [(タイトル, 理由)]。理由が無い物は「未回答」。"""
    out = []
    for it in items:
        rec = (ledger or {}).get(it.get("url", "")) or {}
        if rec.get("decision") == "list":
            continue
        why = (rec.get("reason") or "").strip()
        if not why:
            why = "出品しない (理由の記入なし)" if rec.get("decision") else "未回答"
        out.append((it.get("title_jp", "")[:40], why))
    return out


def official_image_urls(html_text: str, page_url: str) -> list:
    """公式の商品ページHTML → 商品画像URL (純関数)。取れなければ空。

    JS で描くサイト (タカラトミーアーツ等) は0件になる。**推測で埋めない**。
    アイコン・ロゴ・ボタン類は名前で落とす。
    """
    if not html_text:
        return []
    urls = re.findall(r'(?:src|data-src|content)=["\']([^"\']+\.(?:jpg|jpeg|png))["\']',
                      html_text, re.I)
    urls += re.findall(r'["\'](https?://[^"\']+\.(?:jpg|jpeg|png))["\']', html_text, re.I)
    junk = ("ico_", "icon", "logo", "btn_", "button", "banner", "bn_", "common/",
            "sprite", "spacer", "blank", "arrow", "nav_", "header", "footer")
    out, seen = [], set()
    for u in urls:
        full = urllib.parse.urljoin(page_url, u)
        low = full.lower()
        if any(j in low for j in junk) or full in seen:
            continue
        seen.add(full)
        out.append(full)
    return out[:12]


def build_html(items: list) -> str:
    """目視画面 (純関数)。G列の写真は **1枚も間引かず** 出す。"""
    def proxy(u):
        return "/img/" + urllib.parse.quote(u, safe="")

    cards = []
    for i, it in enumerate(items):
        pics = it.get("pics") or []
        thumbs = "\n".join(
            f'<label class="p"><input type="checkbox" name="pic{i}" value="{_html.escape(u)}">'
            f'<img src="{proxy(u)}" loading="lazy" title="{_html.escape(u)}"></label>'
            for u in pics) or '<span class="no">G列に写真がありません</span>'
        cards.append(f"""
<div class="card" id="c{i}" data-url="{_html.escape(it.get('url',''))}">
  <h2>{i+1}. {_html.escape(it.get('title_jp',''))}</h2>
  <div class="meta">全{it.get('pieces','?')}種 / 仕入 ¥{it.get('cost_jpy',0):,}
    / {_html.escape(it.get('maker_jp') or 'メーカー不明')}
    &nbsp;|&nbsp; <a href="{_html.escape(it.get('url',''))}" target="_blank">仕入元(楽天)を開く</a>
    &nbsp;|&nbsp; <a href="https://www.google.com/search?q={urllib.parse.quote((it.get('maker_jp','') + ' ' + it.get('series_jp','')).strip())}"
       target="_blank">公式を検索</a></div>
  <div class="lbl">G列の写真 ({len(pics)}枚) — 出品に使う物にチェック (1枚目がギャラリー画像)</div>
  <div class="pics">{thumbs}</div>
  <div class="lbl">公式の商品ページURL (あれば。送信時にここから画像も取ります)</div>
  <input class="off" id="o{i}" type="url" placeholder="https://... 公式の商品ページ">
  <div class="btns">
    <button class="ok" onclick="ans({i},'list')">出品する</button>
    <button class="ng" onclick="ans({i},'skip')">出品しない</button>
    <input class="rsn" id="r{i}" placeholder="出品しない理由 (対象年齢が読めない / 12歳以下向け 等)">
    <span class="state" id="s{i}"></span>
  </div>
</div>""")

    return """<!doctype html><meta charset="utf-8"><title>ガチャ 目視確認</title>
<style>
body{font-family:system-ui,sans-serif;margin:16px;background:#f6f6f6}
.card{background:#fff;border:1px solid #ddd;border-radius:8px;padding:12px;margin:0 0 16px}
h2{font-size:15px;margin:0 0 4px}
.meta{font-size:12px;color:#555;margin-bottom:8px}
.lbl{font-size:12px;color:#333;margin:8px 0 4px;font-weight:700}
.no{color:#a00;font-size:13px}
.pics{display:flex;flex-wrap:wrap;gap:6px}
.p{position:relative;display:inline-block}
.p img{width:140px;height:140px;object-fit:contain;background:#fff;border:2px solid #ccc;border-radius:4px}
.p input{position:absolute;top:4px;left:4px;transform:scale(1.6);z-index:2}
.p input:checked+img{border-color:#0a0;border-width:3px}
.off{width:60%;padding:6px;font-size:13px}
.rsn{width:38%;padding:6px;font-size:13px;margin-left:8px}
.btns{margin-top:10px}
button{font-size:14px;padding:7px 14px;margin-right:6px;border-radius:5px;border:1px solid #999;cursor:pointer}
.ok{background:#dfd}.ng{background:#fdd}
.state{font-weight:700;margin-left:8px}
#bar{position:sticky;top:0;background:#222;color:#fff;padding:10px;border-radius:6px;margin-bottom:12px;z-index:9}
#send{background:#fff;color:#000;font-weight:700}
</style>
<div id="bar"><span id="cnt">0</span> / __N__ 件 回答済
  <button id="send" onclick="send()">✉️ HQ に送信</button>
  <span id="msg"></span></div>
__CARDS__
<script>
const A={};
function ans(i,v){
  A[i]=v;
  document.getElementById('s'+i).textContent = (v=='list'?'✅ 出品する':'🚫 出品しない');
  document.getElementById('cnt').textContent=Object.keys(A).length;
  const n=document.getElementById('c'+(i+1)); if(n) n.scrollIntoView({behavior:'smooth'});
}
function send(){
  const out=[];
  document.querySelectorAll('.card').forEach((c,i)=>{
    if(!(i in A)) return;
    out.push({url:c.dataset.url, decision:A[i],
      reason:(document.getElementById('r'+i).value||'').trim(),
      official_url:(document.getElementById('o'+i).value||'').trim(),
      pics:[...c.querySelectorAll('input[type=checkbox]:checked')].map(x=>x.value)});
  });
  if(!out.length){document.getElementById('msg').textContent=' 1件も答えていません';return;}
  document.getElementById('msg').textContent=' 送信中… (公式ページから画像を取ります)';
  fetch('/submit',{method:'POST',body:JSON.stringify(out)})
    .then(r=>r.text()).then(t=>document.getElementById('msg').textContent=' '+t);
}
</script>""".replace("__CARDS__", "\n".join(cards)).replace("__N__", str(len(items)))


# ── I/O ────────────────────────────────────────────────────────────


def fetch_official_images(page_url: str) -> list:
    """公式の商品ページから画像URLを取る。取れなければ空 (推測しない)。"""
    if not (page_url or "").startswith("http"):
        return []
    try:
        req = urllib.request.Request(page_url, headers=_UA)
        raw = urllib.request.urlopen(req, timeout=25).read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("shift_jis", "replace")
        return official_image_urls(text, page_url)
    except Exception as e:                                      # noqa: BLE001
        print(f"  ⚠️ 公式ページを読めず ({type(e).__name__}): {page_url}")
        return []


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):                                  # noqa: D102
        pass

    def do_GET(self):                                           # noqa: N802
        if self.path.startswith("/img/"):
            url = urllib.parse.unquote(self.path[5:])
            try:
                data = urllib.request.urlopen(
                    urllib.request.Request(url, headers=_UA), timeout=20).read()
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.end_headers()
                self.wfile.write(data)
            except Exception:                                   # noqa: BLE001
                self.send_response(404)
                self.end_headers()
            return
        body = build_html(_STATE["items"]).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):                                          # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        try:
            res = json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:                                       # noqa: BLE001
            res = []
        msg = []
        for r in res:
            off = (r.get("official_url") or "").strip()
            r["official_pics"] = fetch_official_images(off) if off else []
            if off:
                msg.append(f"{len(r['official_pics'])}枚")
        _STATE["result"] = res
        note = ("公式から " + " / ".join(msg) + " 取得。") if msg else ""
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write((note + "受け取りました。閉じてOK").encode("utf-8"))
        _EVENT.set()


def run_review(items: list, *, open_browser: bool = True, timeout_sec: int = 10800,
               ledger_path: str = LEDGER) -> dict:
    """目視画面を出して答えを待つ。戻り: 更新後の ledger。"""
    ledger = load_ledger(ledger_path)
    done, ask = split_answered(items, ledger)
    if done:
        print(f"  ✅ 目視済 {len(done)}件 は聞きません (記録から)")
    if not ask:
        print("  ✅ 聞く必要のある物はありません")
        return ledger

    _STATE["items"], _STATE["result"] = ask, None
    _EVENT.clear()
    server = None
    for p in range(SERVER_PORT, SERVER_PORT + 10):
        try:
            server = HTTPServer(("127.0.0.1", p), _Handler)
            break
        except OSError:
            continue
    if not server:
        print("  ⚠️ 画面を出せませんでした → この回は出品しません")
        return ledger
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"  🌐 目視画面: {url}  ({len(ask)}件)")
    if open_browser:
        try:
            import subprocess
            subprocess.run(["cmd", "/c", "start", "", url], check=False)
        except Exception:                                       # noqa: BLE001
            pass
    print("     写真を選ぶ → 公式URLがあれば貼る → 出品する/しない → 「✉️ HQ に送信」")

    got = _EVENT.wait(timeout=timeout_sec)
    try:
        server.shutdown()
    except Exception:                                           # noqa: BLE001
        pass
    if not got or not _STATE["result"]:
        print("  ⚠️ 回答が来ませんでした → この回は出品しません")
        return ledger

    from datetime import datetime
    for r in _STATE["result"]:
        u = (r.get("url") or "").strip()
        if not u:
            continue
        ledger[u] = {"decision": r.get("decision", ""),
                     "reason": (r.get("reason") or "").strip(),
                     "official_url": (r.get("official_url") or "").strip(),
                     "pics": r.get("pics") or [],
                     "official_pics": r.get("official_pics") or [],
                     "at": datetime.now().isoformat(timespec="seconds")}
    save_ledger(ledger, ledger_path)
    print(f"  ✅ 目視の回答を記録: {len(_STATE['result'])}件")
    return ledger
