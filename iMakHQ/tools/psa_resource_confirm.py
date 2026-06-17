# -*- coding: utf-8 -*-
"""PSA再仕入れ — pre-search 目視確認ゲート (v2: ②候補ピッカー)。

探す前に「仕入れたい正カードか」を目視確定し、確定分だけ Mercari/SNKRDUNK 探索に渡す。
 ① 現物 = eBay出品画像(GetItem。出品に使った実画像=必ず有る)。cert→psa_cache はフォールバック。
 ② 候補 = その card番号の catalog 変種をサムネ表示しラジオで選択(解決済KEYは既定選択)。
        ① と ②(選んだ変種)が同じカードなら ON。選んだKEYが探索対象 + 商品管理シートに書戻し。
番号一致では弾けない変種取り違え(CHR/VMAX・JP/Asia)や KEY未解決を、探索前に人手で確定する。

confirm_targets(items) はローカル http サーバを立て、確定ボタンが押されるまで待ち
 {"confirmed":[{idx,key}], "rejected":[{idx,reason}]} を返す(タイムアウト/未確定は None)。
build_confirm_html / ebay_listing_image / psa_image_for_cert 以外は I/O。
"""
import html as _html
import http.server
import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser

# 現物PSA画像フォールバック: iMakTCG/data/psa_cache.json (cert#→CardImageUrl=cloudfront)。
_PSA_CACHE = None
_PSA_CACHE_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMakTCG", "data", "psa_cache.json"))


def psa_image_for_cert(cert):
    """PSA cert# → 現物PSA画像URL(psa_cache.json の CardImageUrl)。無ければ ''。"""
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


def ebay_listing_image(item_id):
    """eBay GetItem の出品画像1枚目(i.ebayimg.com)。自分の出品=必ず有る(ended後~90日も可)。失敗 ''。"""
    if not item_id:
        return ""
    try:
        p = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMakeBayAPI"))
        if p not in sys.path:
            sys.path.insert(0, p)
        from ebay_getitem_images import fetch_listing_images
        pics = fetch_listing_images(item_id)
        return pics[0] if pics else ""
    except Exception:
        return ""


def _s(v):
    """list/tuple は ' / ' 連結、None は空、それ以外 str に正規化(catalog hint が list のため)。"""
    if isinstance(v, (list, tuple)):
        return " / ".join(str(x) for x in v if x not in (None, ""))
    return "" if v is None else str(v)


def _proxied(url):
    """画像URLをローカルプロキシ経由に。ブラウザのreferer由来ホットリンク制限(onepiece-cardgame等)
    や DNS/CORS を回避(サーバ側で取得して渡す)。空は空。"""
    u = _s(url)
    return ("/img?u=" + urllib.parse.quote(u, safe="")) if u else ""


_IMG_CACHE = {}


def _fetch_image(url, retries=3):
    """画像を取得して (bytes, content-type) を返す。成功のみキャッシュ(失敗は次回再試行)。失敗 (None,None)。"""
    if not url:
        return None, None
    if url in _IMG_CACHE:
        return _IMG_CACHE[url]
    for a in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            r = urllib.request.urlopen(req, timeout=15)
            data = r.read()
            ctype = r.headers.get("Content-Type") or "image/jpeg"
            _IMG_CACHE[url] = (data, ctype)
            return data, ctype
        except Exception as e:
            if "getaddrinfo" in str(e) and a < retries - 1:
                time.sleep(2)
                continue
            break
    return None, None


_CSS = """
body{font-family:'Segoe UI',Meiryo,sans-serif;margin:0;background:#f4f4f4;font-size:15px}
h1{background:#2a7;color:#fff;margin:0;padding:12px 16px;font-size:17px;position:sticky;top:0;z-index:5}
.bar{position:sticky;top:46px;background:#fff;padding:8px 16px;border-bottom:1px solid #ccc;z-index:4}
.bar button{font-size:14px;padding:6px 14px;margin-right:8px;cursor:pointer}
.go{background:#2a7;color:#fff;border:none;border-radius:4px;font-weight:bold;padding:8px 20px}
.grid{display:flex;flex-wrap:wrap;gap:10px;padding:12px}
.card{width:360px;border:1px solid #ccc;border-radius:6px;background:#fff;padding:8px}
.card.noimg{border-color:#c33;border-width:2px}
.card.off{opacity:.55;background:#fff4f4}
.rsn{display:none;margin:4px 0;font-size:12px;width:100%}
.card.off .rsn{display:block}
.pair{display:flex;gap:6px;margin:4px 0}
.col{flex:1;min-width:0}
.col .cap{font-size:11px;color:#666;text-align:center}
.col.psa .cap{color:#06c;font-weight:bold}
.col.cat .cap{color:#2a7;font-weight:bold}
.col.psa img{max-width:150px;max-height:180px;display:block;margin:2px auto;border:1px solid #eee}
.ph{min-height:120px;display:flex;align-items:center;justify-content:center;color:#c33;
    font-size:12px;border:1px dashed #c33;margin:2px;text-align:center;padding:4px}
.cands{display:flex;flex-direction:column;gap:3px;max-height:260px;overflow:auto}
.cand{display:flex;align-items:center;gap:5px;border:1px solid #eee;border-radius:4px;padding:2px 3px;cursor:pointer}
.cand img{max-width:48px;max-height:64px;border:1px solid #eee;margin:0}
.cand .cph{width:48px;height:64px;display:flex;align-items:center;justify-content:center;font-size:9px;color:#999;border:1px dashed #ccc}
.cand:has(input:checked){border-color:#2a7;background:#eafaf1}
.clbl{font-size:11px;word-break:break-word;line-height:1.2}
.t{font-size:13px;word-break:break-word;margin:4px 0}
.no{font-size:12px;color:#555}
label.sel{display:flex;align-items:center;gap:6px;font-weight:bold;margin-bottom:4px}
a{font-size:12px;color:#06c}
#done{display:none;padding:40px;font-size:20px;color:#2a7;text-align:center}
"""

_JS = """
function imgFail(el,big){
  var d=document.createElement('div'); d.className=big?'ph':'cph'; d.textContent='画像なし';
  if(el.parentNode) el.parentNode.replaceChild(d,el);
}
function tog(i){var c=document.getElementById('c'+i);
  c.classList.toggle('off', !c.querySelector('input[type=checkbox]').checked);}
function setAll(v){document.querySelectorAll('.card input[type=checkbox]').forEach(function(b){
  b.checked=v; tog(b.closest('.card').dataset.idx);});}
function go(){
  var conf=[], rej=[];
  document.querySelectorAll('.card').forEach(function(c){
    var i=parseInt(c.dataset.idx);
    var pick=c.querySelector('input[type=radio]:checked');
    if(c.querySelector('input[type=checkbox]').checked && pick){
      conf.push({idx:i, key:pick.value});
    } else {
      rej.push({idx:i, reason:c.querySelector('.rsn').value});
    }
  });
  fetch('/confirm',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({confirmed:conf, rejected:rej})}).then(function(){
    document.getElementById('main').style.display='none';
    var d=document.getElementById('done'); d.style.display='block';
    d.textContent='✅ 確定'+conf.length+'件 / 不一致'+rej.length+'件。ターミナルに戻って探索完了を待ってください。';
  });
}
"""


def build_confirm_html(items):
    """items: [{idx, title, card_no, psa_image, candidates:[{key,image,label}], resolved_key,
               ebay_url, no_image}] → 確認HTML。

    ① 現物(出品PSA画像) と ② 候補(catalog変種ラジオ) を並べる。候補ありは既定ON+解決済KEYを
    既定選択、候補なしは既定OFF(catalog未収録→要追加)。
    """
    rows = []
    for it in items:
        idx = it.get("idx")
        cands = it.get("candidates") or []
        off_default = not cands
        cls = "card noimg" if it.get("no_image") else "card"
        if off_default:
            cls += " off"
        cardno = _html.escape(_s(it.get("card_no")))

        psa_img = it.get("psa_image") or ""
        psa_tag = (f"<img src='{_proxied(psa_img)}' loading='lazy' onerror='imgFail(this,1)'>" if psa_img
                   else "<div class='ph'>現物PSA画像なし<br>eBayで確認</div>")
        psa_col = f"<div class='col psa'><div class='cap'>① 現物(出品PSA)</div>{psa_tag}</div>"

        if cands:
            keys = [c.get("key") for c in cands]
            resolved = it.get("resolved_key")
            default = resolved if resolved in keys else (keys[0] if len(keys) == 1 else None)
            opts = []
            for c in cands:
                ck = c.get("key", "")
                chk = " checked" if ck == default else ""
                cimg = c.get("image") or ""
                ctag = (f"<img src='{_proxied(cimg)}' loading='lazy' onerror='imgFail(this,0)'>" if cimg
                        else "<div class='cph'>画像なし</div>")
                opts.append(
                    f"<label class='cand'><input type='radio' name='pick{idx}' value='{_html.escape(_s(ck))}'{chk}>"
                    f"{ctag}<span class='clbl'>{_html.escape(_s(c.get('label')))}</span></label>")
            cat_inner = "<div class='cands'>" + "".join(opts) + "</div>"
        else:
            cat_inner = "<div class='ph'>catalog候補なし<br>(未収録→要追加)</div>"
        cat_col = f"<div class='col cat'><div class='cap'>② 候補(正しい変種を選択)</div>{cat_inner}</div>"

        rsn = ("<select class='rsn'>"
               "<option value='catalog'>②候補が無い/合わない(catalog誤・未収録)</option>"
               "<option value='cert'>①現物が違う(商品管理シートcert#誤)</option>"
               "<option value='listing'>①②一致だが売った物と違う(出品誤)</option>"
               "<option value='unknown'>判断できない/その他</option>"
               "</select>")
        chk_cb = "" if off_default else " checked"
        rows.append(
            f"<div class='{cls}' id='c{idx}' data-idx='{idx}'>"
            f"<label class='sel'><input type='checkbox'{chk_cb} onchange=\"tog({idx})\"> 仕入れる(①=選択②)</label>"
            f"<div class='no'>{cardno}</div>"
            f"<div class='pair'>{psa_col}{cat_col}</div>"
            f"<div class='t'>{_html.escape(_s(it.get('title')))}</div>"
            f"<a href='{_html.escape(_s(it.get('ebay_url')))}' target='_blank'>元eBay出品を見る</a>"
            f"{rsn}"
            "</div>")

    head = (f"<h1>PSA再仕入れ 目視確認 — {len(items)}件。① 現物 と ② 候補(正しい変種を選択)が"
            "同じカードなら 仕入れるON → 確定。(確定した変種だけ探索＋KEYをスプシ書戻し)</h1>")
    bar = ("<div class='bar'><button class='go' onclick='go()'>✅ 確定して探索開始</button>"
           "<button onclick='setAll(true)'>全部ON</button>"
           "<button onclick='setAll(false)'>全部OFF</button>"
           "<span style='color:#c33;font-size:13px'>※候補複数なら現物と同じ変種を選択。候補なし=要catalog追加</span></div>")
    return (f"<!doctype html><html lang='ja'><head><meta charset='utf-8'><title>PSA再仕入れ 確認</title>"
            f"<style>{_CSS}</style></head><body>"
            f"<div id='main'>{head}{bar}<div class='grid'>{''.join(rows)}</div></div>"
            f"<div id='done'></div><script>{_JS}</script></body></html>")


def confirm_targets(items, timeout=1800):
    """ブラウザで確認 → {"confirmed":[{idx,key}], "rejected":[{idx,reason}]}。

    確定(ON+変種選択)= 選んだKEYで探索＋スプシ書戻し。不一致(OFF)= reason付きでPDCA台帳へ。
    タイムアウト/未確定は None。
    """
    page = build_confirm_html(items).encode("utf-8")
    state = {"done": False, "confirmed": [], "rejected": []}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            # 画像プロキシ: ブラウザのreferer由来ホットリンク制限/DNS/CORS を回避(サーバ側取得)
            if self.path.startswith("/img?"):
                u = (urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("u") or [""])[0]
                data, ctype = _fetch_image(u)
                if data:
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Cache-Control", "max-age=3600")
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self.send_response(404)
                    self.end_headers()
                return
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
            state["confirmed"] = [{"idx": int(d["idx"]), "key": d.get("key") or ""}
                                  for d in (data.get("confirmed") or []) if d.get("idx") is not None]
            state["rejected"] = [{"idx": int(d["idx"]), "reason": d.get("reason") or "unknown"}
                                 for d in (data.get("rejected") or []) if d.get("idx") is not None]
            state["done"] = True
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

    # 画像プロキシを多数並行配信するため Threading サーバ(単一スレッドだと画像で詰まる)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    print(f"  ブラウザで確認してください → {url}", flush=True)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    deadline = time.time() + timeout
    while not state["done"] and time.time() < deadline:
        time.sleep(0.3)
    httpd.shutdown()
    httpd.server_close()
    if not state["done"]:
        return None
    return {"confirmed": state["confirmed"], "rejected": state["rejected"]}
