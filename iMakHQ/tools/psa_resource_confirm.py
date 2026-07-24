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
import re
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
_OG_CACHE = {}


def _fetch_og_image(url):
    """商品ページ(SNKRDUNK等)の og:image を取得(キャッシュ)。失敗 ''。"""
    if not url:
        return ""
    if url in _OG_CACHE:
        return _OG_CACHE[url]
    img = ""
    for a in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            h = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "replace")
            m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', h)
            img = m.group(1) if m else ""
            break
        except Exception as e:
            if "getaddrinfo" in str(e) and a < 2:
                time.sleep(2)
                continue
            break
    _OG_CACHE[url] = img
    return img


def _resolve_image_url(u):
    """仕入候補のURL(出品ページ)→ 実画像URL。catalog/eBay画像はそのまま。
    - mercari item (m<id>) → 静的CDN画像(ページ取得不要)
    - mercari shops(/shops/product/ 等 m<id>無)→ og:image
    - snkrdunk 商品ページ → og:image
    """
    u = u or ""
    # 既に直画像URL(CDN host / 画像拡張子)なら解決不要でそのまま(SNKRDUNK thumbnailUrl 等)。
    if "cdn.snkrdunk.com" in u or u.lower().split("?", 1)[0].endswith(
            (".jpg", ".jpeg", ".png", ".webp", ".gif")):
        return u
    if "mercari" in u and "/images/" not in u and "mercdn.net" not in u:
        m = re.search(r"\b(m\d{9,})\b", u)
        if m:
            return f"https://static.mercdn.net/item/detail/orig/photos/{m.group(1)}_1.jpg"
        return _fetch_og_image(u)          # mercari shops 等は og:image
    if "snkrdunk.com" in u and "/images/" not in u:
        return _fetch_og_image(u)          # snkrdunk の商品ページURL(画像でない)→ og:image
    return u


def _fix_url(u):
    """catalog の既知の壊れURLパターンを補正。
    dbs-cardgame.com の画像が /fw/jp/images/ で 404(正: /fw/images/。余分な jp/)= DBS多数。"""
    return (u or "").replace("dbs-cardgame.com/fw/jp/images/", "dbs-cardgame.com/fw/images/")


def _fetch_image(url, retries=4):
    """画像を取得して (bytes, content-type) を返す。成功のみキャッシュ(失敗は次回再試行)。失敗 (None,None)。"""
    if not url:
        return None, None
    url = _fix_url(url)
    # URLにスペース等が含まれると urllib が弾く(catalog の "Other Product Card" 等は実在するが
    # 生スペース)。既存の %xx を壊さず空白等だけエンコード。
    url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")
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
.card{width:420px;border:1px solid #ccc;border-radius:6px;background:#fff;padding:8px}
.card.noimg{border-color:#c33;border-width:2px}
.card.off{opacity:.55;background:#fff4f4}
.rsn{display:none;margin:4px 0;font-size:12px;width:100%}
.card.off .rsn{display:block}
.pair{display:flex;gap:6px;margin:4px 0}
.col{flex:1;min-width:0}
.col .cap{font-size:11px;color:#666;text-align:center}
.col.psa .cap{color:#06c;font-weight:bold}
.col.cat .cap{color:#2a7;font-weight:bold}
.col.psa img{width:200px;height:270px;object-fit:contain;display:block;margin:2px auto;border:1px solid #eee;background:#fafafa}
.ph{min-height:120px;display:flex;align-items:center;justify-content:center;color:#c33;
    font-size:12px;border:1px dashed #c33;margin:2px;text-align:center;padding:4px}
.cands{display:flex;flex-direction:column;gap:5px;height:270px;overflow-y:scroll}
.cand{display:flex;align-items:center;gap:6px;border:1px solid #eee;border-radius:4px;padding:3px 4px;cursor:pointer}
.cand img{width:100px;height:135px;object-fit:cover;border:1px solid #eee;margin:0;background:#fafafa}
.cand .cph{width:100px;height:135px;display:flex;align-items:center;justify-content:center;font-size:10px;color:#999;border:1px dashed #ccc}
.cand:has(input:checked){border-color:#2a7;background:#eafaf1}
.clbl{font-size:11px;word-break:break-word;line-height:1.2}
.rsn{display:none;margin-top:3px;font-size:10px;color:#888;align-items:center;gap:3px}
.cand:has(.ck:not(:checked)) .rsn{display:inline-flex}
.rb{font-size:10px;padding:1px 5px;border:1px solid #bbb;border-radius:3px;background:#fff;cursor:pointer}
.rb.sel{background:#c33;color:#fff;border-color:#c33;font-weight:bold}
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


def _serve_confirm(page_bytes, extract, timeout):
    """page を /img プロキシ付きで配信し、POST(JSON)を extract(data)->result で受けて返す。

    画像は多数並行のため ThreadingHTTPServer + サーバ側取得(ホットリンク/DNS/CORS回避)。
    確定ボタンが押される(POST)まで待ち、extract の戻りを返す。タイムアウト/未確定は None。
    """
    state = {"done": False, "result": None}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.startswith("/img?"):
                u = (urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("u") or [""])[0]
                # 出品ページURL(mercari/snkrdunk)→実画像URLに解決してから取得。
                # これが無いとRESTOCK仕入候補のページURLをそのままHTMLとして掴み画像が出ない
                # (_resolve_image_url が定義only・未配線だった。2026-06-19 真因)。
                u = _resolve_image_url(u)
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
            self.wfile.write(page_bytes)

        def do_POST(self):
            ln = int(self.headers.get("Content-Length", 0) or 0)
            try:
                data = json.loads(self.rfile.read(ln) or b"{}")
            except Exception:
                data = {}
            state["result"] = extract(data)
            state["done"] = True
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
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
    return state["result"] if state["done"] else None


def confirm_targets(items, timeout=10800):   # 2026-07-24 ユーザー要望で 30分→3時間に延長
    """探索前 目視確認 → {"confirmed":[{idx,key}], "rejected":[{idx,reason}]}。未確定は None。"""
    def _ex(data):
        return {"confirmed": [{"idx": int(d["idx"]), "key": d.get("key") or ""}
                              for d in (data.get("confirmed") or []) if d.get("idx") is not None],
                "rejected": [{"idx": int(d["idx"]), "reason": d.get("reason") or "unknown"}
                             for d in (data.get("rejected") or []) if d.get("idx") is not None]}
    return _serve_confirm(build_confirm_html(items).encode("utf-8"), _ex, timeout)


_JS_RESTOCK = """
function imgFail(el,big){var d=document.createElement('div'); d.className=big?'ph':'cph';
  d.textContent='画像なし'; if(el.parentNode) el.parentNode.replaceChild(d,el);}
function upd(i){var c=document.getElementById('c'+i);
  var n=c.querySelectorAll('.ck:checked').length;
  c.classList.toggle('off', n===0);
  var b=document.getElementById('cnt'+i);
  if(b) b.textContent = n? ('RESTOCK ✓ 買う候補 '+n+'件') : 'RESTOCKしない(全候補 仕入見送り)';}
function setAll(v){document.querySelectorAll('.ck').forEach(function(b){b.checked=v;});
  document.querySelectorAll('.card').forEach(function(c){upd(c.dataset.idx);});}
function setRsn(btn){var cand=btn.closest('.cand'); var ck=cand.querySelector('.ck');
  ck.dataset.rsn=btn.dataset.r;
  cand.querySelectorAll('.rb').forEach(function(b){b.classList.toggle('sel', b.dataset.r===btn.dataset.r);});}
function go(){
  var conf=[]; var diffs=[]; var skip=0;
  document.querySelectorAll('.card').forEach(function(c){
    var idx=parseInt(c.dataset.idx); var urls=[];
    c.querySelectorAll('.ck').forEach(function(ck){
      if(ck.checked){urls.push(ck.dataset.url);}
      else if((ck.dataset.rsn||'skip')==='diff'){diffs.push({idx:idx, url:ck.dataset.url});}
      else{skip++;}});
    if(urls.length) conf.push({idx:idx, urls:urls});
  });
  if(diffs.length && !confirm('違う(別カード)が'+diffs.length+'件。検索の精度事故=即対応対象です。確定しますか?')) return;
  fetch('/confirm',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({confirmed:conf, diffs:diffs, skip:skip})}).then(function(){
    document.getElementById('main').style.display='none';
    var d=document.getElementById('done'); d.style.display='block';
    d.textContent='✅ RESTOCK確定 '+conf.length+'件。ターミナルに戻ってください。';});
}
"""


def build_restock_html(items):
    """RESTOCK視覚確証 HTML。items: [{idx, title, card_no, ebay_url, ref_image,
    candidates:[{channel,url,price}], v8}]。① 現物 と 仕入候補(買う物の出品画像) を並べ目視一致。
    候補のurl(出品ページ)はプロキシが画像へ解決(mercari→CDN / snkrdunk→og:image)。"""
    rows = []
    for it in items:
        idx = it.get("idx")
        ref = it.get("ref_image") or ""
        ref_tag = (f"<img src='{_proxied(ref)}' loading='lazy' onerror='imgFail(this,1)'>" if ref
                   else "<div class='ph'>現物画像なし</div>")
        cand_html = []
        for cd in (it.get("candidates") or []):
            u = cd.get("url") or ""
            # 画像は cd.image(SNKRDUNK=実カードthumbnail)優先、無ければ url を解決(mercari=CDN直画像)。
            # SNKRDUNK は listing ページの og:image がサイト既定ロゴで全候補同一になるため image を使う。
            imgsrc = cd.get("image") or u
            img = (f"<img src='{_proxied(imgsrc)}' loading='lazy' onerror='imgFail(this,0)'>" if imgsrc
                   else "<div class='cph'>画像なし</div>")
            price = cd.get("price")
            pstr = f"¥{price:,}" if isinstance(price, int) else (_s(price) if price else "")
            # 候補ごとに個別チェック(既定ON)。①と違う候補だけ外せる(1つ違っても全部NGにならない)。
            # チェック外す=買わない。理由は2択: 「見送り」(高い/出品者不安/納期長 等=business判断、
            # 記録のみ)と「違う」(検索が別カードを拾った誤検出=生成への改善信号→違う率トレンド)。
            # 既定 skip(外す多数は見送り)。違うカードの時だけ「違う」を押す。
            _nm = _s(cd.get("name"))
            _nm_html = f"<br><span class='cnm'>{_html.escape(_nm[:48])}</span>" if _nm else ""
            cand_html.append(
                f"<label class='cand'><input type='checkbox' class='ck' checked "
                f"data-idx='{idx}' data-url='{_html.escape(_s(u))}' data-rsn='skip' onchange='upd({idx})'>{img}"
                f"<span class='clbl'>{_html.escape(_s(cd.get('channel')))} {pstr}{_nm_html}"
                f"<br><a href='{_html.escape(_s(u))}' target='_blank'>開く</a>"
                f"<span class='rsn'>外す理由:"
                f"<button type='button' class='rb sel' data-r='skip' onclick='setRsn(this)'>見送り</button>"
                f"<button type='button' class='rb' data-r='diff' onclick='setRsn(this)'>違う</button>"
                f"</span></span></label>")
        if not cand_html:
            cand_html = ["<div class='cph'>仕入候補なし</div>"]
        v8 = _s(it.get("v8"))
        v8_html = f"<div class='lbl'>{_html.escape(v8)}</div>" if v8 else ""
        rows.append(
            f"<div class='card' id='c{idx}' data-idx='{idx}'>"
            f"<div class='cnt' id='cnt{idx}'>RESTOCK ✓(買う候補のみ残す)</div>"
            f"<div class='no'>{_html.escape(_s(it.get('card_no')))}</div>"
            f"<div class='pair'><div class='col psa'><div class='cap'>① 現物(出品)</div>{ref_tag}</div>"
            f"<div class='col cat'><div class='cap'>仕入候補(チェック=買う / 外す=仕入見送り)</div>"
            f"<div class='cands'>{''.join(cand_html)}</div></div></div>"
            f"<div class='t'>{_html.escape(_s(it.get('title')))}</div>{v8_html}"
            f"<a href='{_html.escape(_s(it.get('ebay_url')))}' target='_blank'>元eBay出品</a>"
            "</div>")
    head = (f"<h1>RESTOCK 視覚確証 — {len(items)}件。① 現物 と見比べて<b>買う候補だけチェックを残す</b>。"
            "買わない候補(違うカード / 高い / 出品者不安 / 納期長 等)は<b>仕入見送り=チェックを外す</b>。"
            "1つでも残ればRESTOCK確定 → 確定。</h1>")
    bar = ("<div class='bar'><button class='go' onclick='go()'>✅ RESTOCK確定</button>"
           "<button onclick='setAll(true)'>全部ON</button>"
           "<button onclick='setAll(false)'>全部OFF</button>"
           "<span style='color:#c33;font-size:13px'>※チェック=買う / 外す=買わない(理由: 見送り or 違う を選択)</span></div>")
    return (f"<!doctype html><html lang='ja'><head><meta charset='utf-8'><title>RESTOCK確証</title>"
            f"<style>{_CSS}</style></head><body>"
            f"<div id='main'>{head}{bar}<div class='grid'>{''.join(rows)}</div></div>"
            f"<div id='done'></div><script>{_JS_RESTOCK}</script></body></html>")


def parse_restock_result(data):
    """RESTOCK確証 POST(JSON)→ {confirmed:[{idx,urls}], diffs:[{idx,url}], skip}。純関数(test可)。

    confirmed=買う候補(チェック残)。diffs=「違う(別カード)」と判定された個別候補(=検索が別カードを
    拾った精度事故)。**率を待たず1件でも即対応**するため、件数でなく個別(どのカードのどの候補が
    別物か)を返す。skip=見送り(高い/出品者不安/納期長 等=business判断)の件数のみ(action不要)。
    """
    out = []
    for d in (data.get("confirmed") or []):
        if d.get("idx") is None:
            continue
        urls = [u for u in (d.get("urls") or []) if u]
        if urls:
            out.append({"idx": int(d["idx"]), "urls": urls})
    diffs = [{"idx": int(d["idx"]), "url": d.get("url", "")}
             for d in (data.get("diffs") or []) if d.get("idx") is not None]
    return {"confirmed": out, "diffs": diffs, "skip": int(data.get("skip") or 0)}


def restock_confirm(items, timeout=10800):   # 2026-07-24 ユーザー要望で 30分→3時間に延長
    """RESTOCK視覚確証 → {confirmed:[{idx,urls}], diffs:[{idx,url}], skip} を返す
    (候補1つでも残ればRESTOCK)。未確定は None。"""
    return _serve_confirm(build_restock_html(items).encode("utf-8"), parse_restock_result, timeout)
