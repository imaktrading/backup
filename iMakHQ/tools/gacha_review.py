#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gacha_review.py — ガチャポンの目視確認 (対象年齢 + 使う写真) (2026-08-20)。

なぜ人が見るのか:
    米国 CPSIA では 12歳以下向けの玩具が規制対象。対象年齢は **どこからも機械的に
    取れない** ことを実測で確認した (2026-08-20):
      - 楽天の商品ページ HTML: `対象年齢` の記載 0件
      - メーカー公式 (タカラトミーアーツ): ページは在るが中身も画像も JS 描画で
        HTTP では取れない
    印字は台紙・パッケージの写真に写っている。だから人が見る。
    バンダイ分は JAN から取れるので、そちらは収集時に落としてもらう
    (`iMak_data/harvest/requests/2026-08-19_gacha_age_check_handoff_response.md`)。

画面ですること (1件あたり数秒):
    1. 台紙の「対象年齢」を見て **15+ / 15才未満 / 読めない** を押す
    2. 出品に使う写真を選ぶ (1枚目が eBay のギャラリー画像)
    公式ページのリンクが在れば横に出す (無ければ「公式リンク未取得」と出す)。

答えは記録して次回から聞かない (PSA の verified_certs.json と同じ考え)。
15+ を押した物だけが CSV に載る。他は **出さない** (fail-closed)。
"""
from __future__ import annotations

import html as _html
import json
import os
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

LEDGER = r"C:\dev\iMak_data\hq\gacha_age_verified.json"
SERVER_PORT = 8788

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
    """(答え済み, 聞く必要がある) に分ける (純関数)。

    ★「15才未満」「読めない」も答え済みとして扱う = 毎回同じ物を聞かない。
      ただし出品には回さない (下の `confirmed` に入らない)。
    """
    done, ask = [], []
    for it in items:
        rec = (ledger or {}).get(it.get("url", ""))
        (done if rec and rec.get("age") else ask).append(it)
    return done, ask


def confirmed(items: list, ledger: dict) -> list:
    """15+ と答えた物だけ返す (fail-closed)。選んだ写真を pics に反映する。"""
    out = []
    for it in items:
        rec = (ledger or {}).get(it.get("url", "")) or {}
        if rec.get("age") != "15+":
            continue
        picked = [p for p in (rec.get("pics") or []) if p]
        it = dict(it)
        if picked:
            it["pics"] = picked
        out.append(it)
    return out


def skipped_reasons(items: list, ledger: dict) -> dict:
    """出さなかった物の理由と件数 (メール/ログ用)。"""
    label = {"under15": "15才未満 (出せません)", "unreadable": "対象年齢が読めない",
             "": "未回答"}
    out: dict = {}
    for it in items:
        a = ((ledger or {}).get(it.get("url", "")) or {}).get("age", "")
        if a == "15+":
            continue
        k = label.get(a, a)
        out[k] = out.get(k, 0) + 1
    return out


def build_html(items: list) -> str:
    """目視画面 (純関数)。画像は /img/<url> 経由で出す (楽天の直リンク対策)。"""
    def img(u):
        return "/img/" + urllib.parse.quote(u, safe="")

    cards = []
    for i, it in enumerate(items):
        pics = it.get("pics") or []
        thumbs = "\n".join(
            f'<label class="p"><input type="checkbox" name="pic{i}" value="{_html.escape(u)}"'
            f'{" checked" if k < 6 else ""}>'
            f'<img src="{img(u)}" loading="lazy"></label>' for k, u in enumerate(pics))
        official = it.get("official_url")
        off = (f'<a href="{_html.escape(official)}" target="_blank">公式ページを開く</a>'
               if official else '<span class="no">公式リンク未取得 (抽出くんに依頼中)</span>')
        cards.append(f"""
<div class="card" id="c{i}" data-url="{_html.escape(it.get('url',''))}">
  <h2>{i+1}. {_html.escape(it.get('title_jp',''))}</h2>
  <div class="meta">全{it.get('pieces','?')}種 / 仕入 ¥{it.get('cost_jpy',0):,}
    / {_html.escape(it.get('maker_jp') or 'メーカー不明')}
    &nbsp;|&nbsp; <a href="{_html.escape(it.get('url',''))}" target="_blank">仕入元</a>
    &nbsp;|&nbsp; {off}</div>
  <div class="pics">{thumbs}</div>
  <div class="btns">
    <button class="ok"  onclick="ans({i},'15+')">対象年齢 15才以上 → 出す</button>
    <button class="ng"  onclick="ans({i},'under15')">15才未満 → 出さない</button>
    <button class="unk" onclick="ans({i},'unreadable')">読めない → 出さない</button>
    <span class="state" id="s{i}"></span>
  </div>
</div>""")

    return """<!doctype html><meta charset="utf-8"><title>ガチャ 目視確認</title>
<style>
body{font-family:system-ui,sans-serif;margin:16px;background:#f6f6f6}
.card{background:#fff;border:1px solid #ddd;border-radius:8px;padding:12px;margin:0 0 14px}
h2{font-size:15px;margin:0 0 4px}
.meta{font-size:12px;color:#555;margin-bottom:8px}
.no{color:#a00}
.pics{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
.p{position:relative;display:inline-block}
.p img{width:150px;height:150px;object-fit:contain;background:#fff;border:2px solid #ccc;border-radius:4px}
.p input{position:absolute;top:4px;left:4px;transform:scale(1.5)}
.p input:checked+img{border-color:#0a0}
button{font-size:14px;padding:7px 12px;margin-right:6px;border-radius:5px;border:1px solid #999;cursor:pointer}
.ok{background:#dfd}.ng{background:#fdd}.unk{background:#eee}
.state{font-weight:700;margin-left:6px}
#bar{position:sticky;top:0;background:#222;color:#fff;padding:10px;border-radius:6px;margin-bottom:12px}
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
  const s=document.getElementById('s'+i);
  s.textContent={'15+':'✅ 15才以上','under15':'🚫 15才未満','unreadable':'❓読めない'}[v];
  document.getElementById('cnt').textContent=Object.keys(A).length;
  const n=document.getElementById('c'+(i+1)); if(n) n.scrollIntoView({behavior:'smooth'});
}
function send(){
  const out=[];
  document.querySelectorAll('.card').forEach((c,i)=>{
    if(!(i in A)) return;
    const pics=[...c.querySelectorAll('input[type=checkbox]:checked')].map(x=>x.value);
    out.push({url:c.dataset.url, age:A[i], pics:pics});
  });
  if(!out.length){document.getElementById('msg').textContent=' 1件も答えていません';return;}
  fetch('/submit',{method:'POST',body:JSON.stringify(out)})
    .then(()=>document.getElementById('msg').textContent=' 送信しました。閉じてOK');
}
</script>""".replace("__CARDS__", "\n".join(cards)).replace("__N__", str(len(items)))


# ── サーバ ─────────────────────────────────────────────────────────


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):                                  # noqa: D102
        pass

    def do_GET(self):                                           # noqa: N802
        if self.path.startswith("/img/"):
            url = urllib.parse.unquote(self.path[5:])
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                data = urllib.request.urlopen(req, timeout=20).read()
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
            _STATE["result"] = json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:                                       # noqa: BLE001
            _STATE["result"] = []
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
        _EVENT.set()


def run_review(items: list, *, open_browser: bool = True, timeout_sec: int = 10800,
               ledger_path: str = LEDGER) -> dict:
    """目視画面を出して答えを待つ。戻り: 更新後の ledger。

    答えが来なければ ledger は変わらない = その回は1件も出ない (fail-closed)。
    """
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
    print("     台紙の対象年齢を見て 3つのボタンから選び、最後に「✉️ HQ に送信」")

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
        ledger[u] = {"age": r.get("age", ""), "pics": r.get("pics") or [],
                     "at": datetime.now().isoformat(timespec="seconds")}
    save_ledger(ledger, ledger_path)
    print(f"  ✅ 目視の回答を記録: {len(_STATE['result'])}件")
    return ledger
