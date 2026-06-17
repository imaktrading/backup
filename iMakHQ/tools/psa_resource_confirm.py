# -*- coding: utf-8 -*-
"""PSA再仕入れ — pre-search 目視確認ゲート。

「探す前に、仕入れたい正カードが本当に正しいか」をブラウザで目視確認し、確定した分だけを
Mercari/SNKRDUNK 探索に渡す。番号一致だけでは弾けない変種取り違え(CHR/VMAX・JP/Asia 等)や
KEY未解決(正画像なし)を、探索に時間を使う前に人手で確定する。

post_psa_review の verify→build と同じ思想: 高コスト処理(探索)の前に確認ゲートを置く。

confirm_targets(items) はローカル http サーバを立て、ブラウザで確定ボタンが押されるまで待ち、
チェックされた idx の集合を返す(タイムアウト/キャンセルは None)。build_confirm_html は純関数。
"""
import html as _html
import http.server
import json
import time
import webbrowser


def build_confirm_html(items):
    """items: [{idx, title, card_no, ref_image, ref_label, ebay_url, no_image}]
    → 確認用 HTML 文字列。各カードに checkbox(既定ON、正画像なしは赤枠)。"""
    css = """
    body{font-family:'Segoe UI',Meiryo,sans-serif;margin:0;background:#f4f4f4;font-size:15px}
    h1{background:#2a7;color:#fff;margin:0;padding:12px 16px;font-size:17px;position:sticky;top:0;z-index:5}
    .bar{position:sticky;top:46px;background:#fff;padding:8px 16px;border-bottom:1px solid #ccc;z-index:4}
    .bar button{font-size:14px;padding:6px 14px;margin-right:8px;cursor:pointer}
    .go{background:#2a7;color:#fff;border:none;border-radius:4px;font-weight:bold;padding:8px 20px}
    .grid{display:flex;flex-wrap:wrap;gap:10px;padding:12px}
    .card{width:220px;border:1px solid #ccc;border-radius:6px;background:#fff;padding:8px}
    .card.noimg{border-color:#c33;border-width:2px}
    .card.off{opacity:.4}
    .card img{max-width:200px;max-height:180px;display:block;margin:4px auto}
    .ph{width:200px;height:180px;display:flex;align-items:center;justify-content:center;color:#c33;
        font-size:13px;border:1px dashed #c33;margin:4px auto}
    .t{font-size:13px;word-break:break-word;margin:4px 0}
    .lbl{font-size:12px;color:#060;word-break:break-word}
    .no{font-size:12px;color:#555}
    label.sel{display:flex;align-items:center;gap:6px;font-weight:bold;margin-bottom:4px}
    a{font-size:12px;color:#06c}
    #done{display:none;padding:40px;font-size:20px;color:#2a7;text-align:center}
    """
    rows = []
    for it in items:
        idx = it.get("idx")
        cls = "card noimg" if it.get("no_image") else "card"
        img = it.get("ref_image") or ""
        img_tag = (f"<img src='{_html.escape(img)}' loading='lazy'>" if img
                   else "<div class='ph'>正画像なし(KEY未解決)<br>↓eBayで確認</div>")
        cardno = _html.escape(it.get("card_no") or "")
        rows.append(
            f"<div class='{cls}' id='c{idx}' data-idx='{idx}'>"
            f"<label class='sel'><input type='checkbox' checked onchange=\"tog({idx})\"> 仕入れる</label>"
            f"<div class='no'>{cardno}</div>"
            f"{img_tag}"
            f"<div class='t'>{_html.escape(it.get('title',''))}</div>"
            f"<div class='lbl'>{_html.escape(it.get('ref_label',''))}</div>"
            f"<a href='{_html.escape(it.get('ebay_url',''))}' target='_blank'>元eBay出品を見る</a>"
            "</div>"
        )
    js = """
    function tog(i){var c=document.getElementById('c'+i);
      c.classList.toggle('off', !c.querySelector('input').checked);}
    function all(v){document.querySelectorAll('.card input').forEach(function(b){
      b.checked=v; tog(b.closest('.card').dataset.idx);});}
    function go(){
      var ids=[]; document.querySelectorAll('.card').forEach(function(c){
        if(c.querySelector('input').checked) ids.push(parseInt(c.dataset.idx));});
      fetch('/confirm',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({confirmed:ids})}).then(function(){
        document.getElementById('main').style.display='none';
        var d=document.getElementById('done');
        d.style.display='block'; d.textContent='✅ '+ids.length+'件を確定しました。ターミナルに戻って探索完了を待ってください。';
      });
    }
    """
    head = (f"<h1>PSA再仕入れ 目視確認 — {len(items)}件。仕入れる正カードだけチェックON → 確定。"
            "(チェックしたものだけ Mercari/SNKRDUNK を探索します)</h1>")
    bar = ("<div class='bar'><button class='go' onclick='go()'>✅ 確定して探索開始</button>"
           "<button onclick='all(true)'>全部ON</button>"
           "<button onclick='all(false)'>全部OFF</button>"
           "<span style='color:#c33;font-size:13px'>※赤枠=正画像なし(eBayで現物確認してから判断)</span></div>")
    return (f"<!doctype html><html lang='ja'><head><meta charset='utf-8'><title>PSA再仕入れ 確認</title>"
            f"<style>{css}</style></head><body>"
            f"<div id='main'>{head}{bar}<div class='grid'>{''.join(rows)}</div></div>"
            f"<div id='done'></div><script>{js}</script></body></html>")


def confirm_targets(items, timeout=1800):
    """ブラウザで確認 → チェックされた idx の list を返す。タイムアウト/未確定は None。"""
    page = build_confirm_html(items).encode("utf-8")
    state = {"confirmed": None}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page)

        def do_POST(self):
            ln = int(self.headers.get("Content-Length", 0) or 0)
            try:
                data = json.loads(self.rfile.read(ln) or b"{}")
            except Exception:
                data = {}
            state["confirmed"] = [int(x) for x in (data.get("confirmed") or [])]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

    httpd = http.server.HTTPServer(("127.0.0.1", 0), H)
    httpd.timeout = 1
    port = httpd.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    print(f"  ブラウザで確認してください → {url}", flush=True)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    deadline = time.time() + timeout
    while state["confirmed"] is None and time.time() < deadline:
        httpd.handle_request()
    httpd.server_close()
    return state["confirmed"]
