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
import os
import time
import webbrowser

# 現物PSA画像: iMakTCG/data/psa_cache.json (cert#→CardImageUrl=cloudfront)。出品に使った実画像。
_PSA_CACHE = None
_PSA_CACHE_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMakTCG", "data", "psa_cache.json"))


def psa_image_for_cert(cert):
    """PSA cert# → 出品に使った現物PSA画像URL(psa_cache.json の CardImageUrl)。無ければ ''。"""
    global _PSA_CACHE
    if _PSA_CACHE is None:
        try:
            with open(_PSA_CACHE_PATH, encoding="utf-8") as f:
                _PSA_CACHE = json.load(f)
        except Exception:
            _PSA_CACHE = {}
    if not cert:
        return ""
    rec = _PSA_CACHE.get(str(cert).strip())
    return (rec.get("CardImageUrl", "") if isinstance(rec, dict) else "") or ""


def build_confirm_html(items):
    """items: [{idx, title, card_no, psa_image, ref_image, ref_label, ebay_url, no_image}]
    → 確認用 HTML。各カードに 現物PSA画像(左)と catalog正カード(右)を並べ、同じカードか目視 →
    checkbox(既定ON、現物PSA画像が引けない=赤枠で要注意)。"""
    css = """
    body{font-family:'Segoe UI',Meiryo,sans-serif;margin:0;background:#f4f4f4;font-size:15px}
    h1{background:#2a7;color:#fff;margin:0;padding:12px 16px;font-size:17px;position:sticky;top:0;z-index:5}
    .bar{position:sticky;top:46px;background:#fff;padding:8px 16px;border-bottom:1px solid #ccc;z-index:4}
    .bar button{font-size:14px;padding:6px 14px;margin-right:8px;cursor:pointer}
    .go{background:#2a7;color:#fff;border:none;border-radius:4px;font-weight:bold;padding:8px 20px}
    .grid{display:flex;flex-wrap:wrap;gap:10px;padding:12px}
    .card{width:340px;border:1px solid #ccc;border-radius:6px;background:#fff;padding:8px}
    .card.noimg{border-color:#c33;border-width:2px}
    .card.off{opacity:.5;background:#fff4f4}
    .rsn{display:none;margin:4px 0;font-size:12px;width:100%}
    .card.off .rsn{display:block}
    .pair{display:flex;gap:6px;justify-content:center;margin:4px 0}
    .col{text-align:center;flex:1}
    .col .cap{font-size:11px;color:#666}
    .col.psa .cap{color:#06c;font-weight:bold}
    .col.cat .cap{color:#2a7;font-weight:bold}
    .card img{max-width:150px;max-height:170px;display:block;margin:2px auto;border:1px solid #eee}
    .ph{width:150px;height:170px;display:flex;align-items:center;justify-content:center;color:#c33;
        font-size:12px;border:1px dashed #c33;margin:2px auto;text-align:center}
    .t{font-size:13px;word-break:break-word;margin:4px 0}
    .lbl{font-size:12px;color:#060;word-break:break-word}
    .no{font-size:12px;color:#555}
    label.sel{display:flex;align-items:center;gap:6px;font-weight:bold;margin-bottom:4px}
    a{font-size:12px;color:#06c}
    #done{display:none;padding:40px;font-size:20px;color:#2a7;text-align:center}
    """
    rows = []
    def _s(v):
        """list/tuple は ' / ' 連結、None は空、それ以外は str に正規化(catalog hint が list のため)。"""
        if isinstance(v, (list, tuple)):
            return " / ".join(str(x) for x in v if x not in (None, ""))
        return "" if v is None else str(v)

    for it in items:
        idx = it.get("idx")
        cls = "card noimg" if it.get("no_image") else "card"
        cardno = _html.escape(_s(it.get("card_no")))

        def _img(url, ph_text):
            return (f"<img src='{_html.escape(_s(url))}' loading='lazy'>" if url
                    else f"<div class='ph'>{ph_text}</div>")
        psa_col = (f"<div class='col psa'><div class='cap'>① 現物(出品PSA)</div>"
                   f"{_img(it.get('psa_image',''), '現物PSA画像なし<br>eBayで確認')}</div>")
        cat_col = (f"<div class='col cat'><div class='cap'>② 解決先(catalog)</div>"
                   f"{_img(it.get('ref_image',''), 'catalog画像なし<br>(KEY未解決)')}</div>")
        rsn = ("<select class='rsn'>"
               "<option value='catalog'>②catalogが違う(KEY誤解決/画像違い)</option>"
               "<option value='cert'>①現物が違う(商品管理シートcert#誤)</option>"
               "<option value='listing'>①②一致だが売った物と違う(出品誤)</option>"
               "<option value='unknown'>判断できない/その他</option>"
               "</select>")
        rows.append(
            f"<div class='{cls}' id='c{idx}' data-idx='{idx}'>"
            f"<label class='sel'><input type='checkbox' checked onchange=\"tog({idx})\"> 仕入れる(①=②なら)</label>"
            f"<div class='no'>{cardno}</div>"
            f"<div class='pair'>{psa_col}{cat_col}</div>"
            f"<div class='t'>{_html.escape(_s(it.get('title')))}</div>"
            f"<div class='lbl'>{_html.escape(_s(it.get('ref_label')))}</div>"
            f"<a href='{_html.escape(_s(it.get('ebay_url')))}' target='_blank'>元eBay出品を見る</a>"
            f"{rsn}"
            "</div>"
        )
    js = """
    function tog(i){var c=document.getElementById('c'+i);
      c.classList.toggle('off', !c.querySelector('input').checked);}
    function all(v){document.querySelectorAll('.card input').forEach(function(b){
      b.checked=v; tog(b.closest('.card').dataset.idx);});}
    function go(){
      var ids=[], rej=[];
      document.querySelectorAll('.card').forEach(function(c){
        var i=parseInt(c.dataset.idx);
        if(c.querySelector('input[type=checkbox]').checked){ ids.push(i); }
        else { rej.push({idx:i, reason:c.querySelector('.rsn').value}); }
      });
      fetch('/confirm',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({confirmed:ids, rejected:rej})}).then(function(){
        document.getElementById('main').style.display='none';
        var d=document.getElementById('done');
        d.style.display='block';
        d.textContent='✅ 確定'+ids.length+'件 / 不一致'+rej.length+'件。ターミナルに戻って探索完了を待ってください。';
      });
    }
    """
    head = (f"<h1>PSA再仕入れ 目視確認 — {len(items)}件。①現物(出品PSA) と ②解決先(catalog) が"
            "同じカード・同じ変種ならチェックON → 確定。(チェックした分だけ Mercari/SNKRDUNK を探索)</h1>")
    bar = ("<div class='bar'><button class='go' onclick='go()'>✅ 確定して探索開始</button>"
           "<button onclick='all(true)'>全部ON</button>"
           "<button onclick='all(false)'>全部OFF</button>"
           "<span style='color:#c33;font-size:13px'>※赤枠=現物PSA画像なし(eBayで現物確認してから判断)</span></div>")
    return (f"<!doctype html><html lang='ja'><head><meta charset='utf-8'><title>PSA再仕入れ 確認</title>"
            f"<style>{css}</style></head><body>"
            f"<div id='main'>{head}{bar}<div class='grid'>{''.join(rows)}</div></div>"
            f"<div id='done'></div><script>{js}</script></body></html>")


def confirm_targets(items, timeout=1800):
    """ブラウザで確認 → {"confirmed":[idx], "rejected":[{idx,reason}]} を返す。

    確定(チェックON)= ①現物と②catalogが一致 → 探索対象。
    不一致(OFF)= reason付きで返す(PDCA台帳へ)。タイムアウト/未確定は None。
    """
    page = build_confirm_html(items).encode("utf-8")
    state = {"done": False, "confirmed": [], "rejected": []}

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
            state["rejected"] = [{"idx": int(d.get("idx")), "reason": d.get("reason") or "unknown"}
                                 for d in (data.get("rejected") or []) if d.get("idx") is not None]
            state["done"] = True
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
    while not state["done"] and time.time() < deadline:
        httpd.handle_request()
    httpd.server_close()
    if not state["done"]:
        return None
    return {"confirmed": state["confirmed"], "rejected": state["rejected"]}
