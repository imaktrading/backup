# -*- coding: utf-8 -*-
"""一番くじ 補URL再仕入れ (catalog無し・2段階・参照=自出品の公式画像)。

eBay在庫なし(監視くん取下げ=管理シート 売り切れ○)の一番くじを、mercari で同じ景品の
代替supplyに差し替えて再出品する。catalog は使わない(mercariに公式KEYが無く自動マッチ不能の
ため。2026-06-24 ユーザー判断)。自出品画像は公式(パッケージ品)で実写と画像検索マッチしない
ので参照(見比べ)専用 = 種にしない。

2段階(ユーザー設計):
  パスA「画像特定」 : python ichibankuji_restock.py identify [件数]
      OOS一番くじをキーワード検索 → 実写候補 → ブラウザで各景品の正しい1枚を選択 → 送信
  パスB「画像検索+確定」: python ichibankuji_restock.py expand
      選んだ実写で mercari画像検索 → 同景品を拡張 → 最終supplyを選択 → 送信
      → A列に昇格(死んだ旧A列を置換)+ B列クリア + 売り切れ○クリア → 通常②で再出品
      (補URL列 AC-AG には候補群を記録=監査用)

サーバは port 8766 (PSA Review=8765 と非競合)。
"""
import html as _html
import json
import os
import re
import sys
import threading
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMakeBayAPI")))

import sheet_io
from mercari_psa_resource import parse_mercari_items, parse_image_search_results, _chrome_major
from psa_resource_html import mercari_image_url
from ebay_getitem_images import fetch_listing_images

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SHEET_ID = "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk"
GID = 851100680
PORT = 8766
PICKS_FILE = r"C:/dev/iMak_data/dedupe/ichibankuji_picks.json"
CONFIRMED_FILE = r"C:/dev/iMak_data/dedupe/ichibankuji_confirmed.json"
REFRESH_FILE = r"C:/dev/iMak_data/dedupe/ichibankuji_refresh.json"   # 内容刷新の確定(scrape+Claude後)
COL_SOLD = 3       # D 売り切れ
COL_CAT = 17       # R カテゴリ
COL_TITLE = 2      # C 日本語タイトル
COL_KUJI_URL = 8   # I 公式くじURL(ユーザーが恒久入力。生成PLのV列は出品後クリアされるため別列)
_NOISE = ["新品", "未開封", "未使用", "送料無料", "即決", "匿名配送", "正規品", "限定", "おまけつき", "おまけ付き"]


# ---------------- 純粋ロジック ----------------
def clean_kw(title):
    """C列(日本語mercariタイトル)→ mercari検索語。

    ノイズ除去 + **「一番くじ」を必ず含める**(category=一番くじ確定なので、タイトルに
    無くても先頭に付ける。2026-06-24 ユーザー指摘: 一番くじ/賞名が検索に入ってないと弱い)。
    賞名(A賞/B賞/…/ラストワン)はタイトルに在れば残す(無い物は付けられない=タイトル依存)。
    """
    t = re.sub(r"【[^】]*】", " ", title or "")
    t = re.sub(r"[☆★()（）\[\]]", " ", t)
    for w in _NOISE:
        t = t.replace(w, " ")
    t = re.sub(r"\s+", " ", t).strip()
    if "一番くじ" not in t and "一番" not in t:
        t = "一番くじ " + t
    return t


def extract_prize(c_title, ebay_title=""):
    """賞ランク(A賞/B賞/…/ラストワン)を抽出。C列(日本語)優先→eBayタイトル(英語)補完。

    一番くじでない通常フィギュアを除外するため、賞は検索のマスト要素(2026-06-24 ユーザー)。
    取れなければ '' (=賞不明 → 検索が不正確になるので呼出側でフラグ)。
    """
    m = re.search(r"(ラストワン賞|ラストワン|ラスト賞|[A-Z]賞)", c_title or "")
    if m:
        g = m.group(0)
        return "ラストワン" if "ラストワン" in g else g
    et = ebay_title or ""
    m = re.search(r"\b([A-Z])\s*Prize\b", et, re.I)
    if m:
        return m.group(1).upper() + "賞"
    if re.search(r"last\s*one", et, re.I):
        return "ラストワン"
    return ""


def build_keyword(c_title, ebay_title=""):
    """検索語を組む。戻り: (keyword, prize)。一番くじ必須 + 賞必須(取れれば付与)。

    prize='' のときは賞不明(検索が通常フィギュアと混ざる恐れ)→ 呼出側でフラグ表示。
    """
    kw = clean_kw(c_title)
    prize = extract_prize(c_title, ebay_title)
    if prize and prize not in kw:
        kw = kw + " " + prize
    return kw, prize


def _card(url, price, image, name, multi=False, cond="", ship=""):
    """候補カード(選択+画像+価格+状態/送料+リンク)。multi=True で checkbox(複数選択)。

    image は検索結果から取得した実URL(Shops含む)。cond/ship は詳細ページ由来(新品+送料込みのみ通過)。
    """
    img = image or mercari_image_url(url)   # 実src優先、無ければ /item/m から構築
    img_tag = (f"<img src='{_html.escape(img)}' loading='lazy'>" if img
               else "<div class=noimg>画像なし</div>")
    pr = f"¥{price:,}" if price else ""
    cs = ""
    if cond or ship:
        cs = f"<br><span style='color:#070;font-size:10px'>{_html.escape(cond)} {_html.escape(ship)}</span>"
    if multi:
        inp = f"<input type=checkbox class=pick value='{_html.escape(url)}'>"
    else:
        inp = f"<input type=radio class=pick name='{_html.escape(name)}' value='{_html.escape(url)}'>"
    return (f"<label class=cand>{inp}{img_tag}<div class=meta>{pr}{cs}<br>"
            f"<a href='{_html.escape(url)}' target=_blank>開く</a></div></label>")


def build_identify_html(items):
    """パスA: 各OOS景品に 参照(公式)+ キーワード候補(実写・ラジオ)。戻り: HTML文字列。

    items: [{row,item_id,title,ref_image,candidates:[{url,price}]}]
    """
    return _page("画像特定 (パスA): 正しい景品を1つ選ぶ", items, stage="identify")


def build_expand_html(items):
    """パスB: 各景品に 参照(公式)+選んだ実写 + 画像検索の拡張候補(ラジオ)。戻り: HTML文字列。

    items: [{row,item_id,title,ref_image,picked_image,candidates:[{url,price}]}]
    """
    return _page("画像検索+確定 (パスB): 最終supplyを1つ選ぶ", items, stage="expand")


def _page(heading, items, stage):
    parts = ["<!doctype html><meta charset=utf-8><title>", _html.escape(heading), "</title>",
             "<style>body{font-family:sans-serif;margin:0;background:#f4f4f4}"
             ".hd{position:sticky;top:0;background:#2a7;color:#fff;padding:10px;font-weight:bold;z-index:9}"
             ".item{background:#fff;margin:10px;padding:10px;border-radius:6px}"
             ".title{font-weight:bold;margin-bottom:6px}.body{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-start}"
             ".ref img,.ref .noimg{max-width:150px;max-height:150px;border:2px solid #2a7}"
             ".ref{font-size:11px;color:#666;text-align:center}"
             ".cand{display:inline-block;border:1px solid #ccc;border-radius:4px;padding:4px;margin:3px;cursor:pointer;text-align:center;background:#fafafa}"
             ".cand input{display:block;margin:0 auto 3px}.cand img{max-width:120px;max-height:120px}"
             ".cand:has(input:checked){border:3px solid #07f;background:#e8f2ff}"
             ".noimg{width:120px;height:120px;display:flex;align-items:center;justify-content:center;color:#999;border:1px dashed #ccc}"
             ".meta{font-size:11px}.skip{color:#a00}"
             "button{font-size:16px;padding:8px 24px;background:#07f;color:#fff;border:0;border-radius:5px;cursor:pointer}"
             "</style>"]
    multi = (stage == "expand")
    sel_hint = "同じ景品を**複数**選べる(主supply=最安+補URL)" if multi else "正しい景品を**1つ**選ぶ"
    parts.append(f"<div class=hd>{_html.escape(heading)} — 各行で{sel_hint}、下の『送信』</div>")
    for it in items:
        nm = f"row_{it['row']}"
        parts.append(f"<div class=item data-row='{it['row']}' data-multi='{1 if multi else 0}'>")
        ebay_url = f"https://www.ebay.com/itm/{it['item_id']}"
        prize = it.get("prize", "")
        prize_tag = (f"<b style='color:#070'>[{_html.escape(prize)}]</b>" if prize
                     else "<b style='color:#a00'>[⚠️賞不明=通常フィギュア混入注意]</b>")
        parts.append(f"<div class=title>{prize_tag} {_html.escape(it['title'])} "
                     f"<small>(row {it['row']} / 旧itemID {it['item_id']}) "
                     f"<a href='{ebay_url}' target=_blank>🔗 eBay出品元を見る</a></small></div>")
        parts.append("<div class=body>")
        # 参照(公式)
        rimg = it.get("ref_image") or ""
        rtag = f"<img src='{_html.escape(rimg)}'>" if rimg else "<div class=noimg>公式画像なし</div>"
        parts.append(f"<div class=ref>{rtag}<div>公式(参照)</div></div>")
        # パスBは「選んだ実写」も並べる
        if stage == "expand" and it.get("picked_image"):
            parts.append(f"<div class=ref><img src='{_html.escape(it['picked_image'])}'><div>選んだ実写</div></div>")
        # 候補
        cands = it.get("candidates") or []
        if not cands:
            parts.append("<div class=skip>候補なし</div>")
        for c in cands:
            parts.append(_card(c["url"], c.get("price", 0), c.get("image", ""), nm, multi=multi,
                               cond=c.get("cond", ""), ship=c.get("ship", "")))
        # 該当なし: 単一選択(identify)のみ明示。複数選択(expand)は未チェック=skip。
        if not multi:
            parts.append(f"<label class=cand><input type=radio class=pick name='{nm}' value='NONE'>"
                         f"<div class=noimg>該当なし<br>(skip)</div></label>")
        parts.append("</div>")
        # 手動rescue: 候補が弱い時、自分で見つけた mercari URL を貼る(ラジオより優先)
        parts.append(f"<div style='margin-top:6px;font-size:12px'>または手動: "
                     f"<input type=text class=manurl placeholder='候補が弱い時 mercari URL を貼る(実写の出品)' "
                     f"style='width:60%;padding:3px'></div>")
        parts.append("</div>")
    parts.append("<div style='padding:16px'><button id=sendbtn onclick='submit()'>送信</button></div>")
    parts.append("""<script>
function submit(){
  var picks={}, chosen=0;
  document.querySelectorAll('.item').forEach(function(it){
    var multi = it.dataset.multi==='1';
    var arr=[];
    var man=it.querySelector('.manurl'); var manv = man ? man.value.trim() : '';
    if(manv) arr.push(manv);                              // 手動URL(rescue)も採用
    it.querySelectorAll('input.pick:checked').forEach(function(ip){
      if(ip.value && ip.value!=='NONE') arr.push(ip.value);
    });
    // 重複除去
    arr = arr.filter(function(u,i){return arr.indexOf(u)===i;});
    picks[it.dataset.row]= multi ? arr : (arr[0]||'');    // expand=配列(複数) / identify=単一
    if(arr.length) chosen++;
  });
  if(!confirm(chosen+' 行で選択しました。送信しますか?(未選択は除外)')) return;
  var btn=document.getElementById('sendbtn'); if(btn){btn.disabled=true; btn.textContent='送信中...';}
  fetch('/submit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(picks)})
   .then(r=>r.json())
   .then(_=>{document.body.innerHTML='<h2 style="padding:24px;color:#070">✅ 送信完了('+chosen+'件)。このタブを閉じてOK。ターミナルに戻ってください。</h2>';})
   .catch(e=>{
     if(btn){btn.disabled=false; btn.textContent='送信';}
     alert('❌ 送信できませんでした: '+e+'\\n\\nサーバ経由で開いていますか?\\n  python ichibankuji_restock.py identify\\n(静的ファイルを直接開くと送信できません)');
   });
}
</script>""")
    return "".join(parts)


# ---------------- I/O ----------------
def get_oos_ichibankuji(limit):
    """管理シート: category=一番くじ + 売り切れ○ + B列itemID。戻り [{row,item_id,title}]。"""
    ws = sheet_io._product_ws()
    out = []
    for i, row in enumerate(ws.get_all_values(), start=1):
        if i == 1:
            continue
        cat = (row[COL_CAT] if len(row) > COL_CAT else "").strip()
        b = (row[1] if len(row) > 1 else "").strip()
        sold = (row[COL_SOLD] if len(row) > COL_SOLD else "").strip()
        title = (row[2] if len(row) > 2 else "").strip()
        if cat == "一番くじ" and b and sold:
            out.append({"row": i, "item_id": b, "title": title})
        if len(out) >= limit:
            break
    return out


def _retry(fn, tries=5, what=""):
    """transient(API 503 / getaddrinfo / timeout)はリトライ。最終失敗は送出。"""
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"  ⚠ {what}失敗({i+1}/{tries}): {type(e).__name__}: {str(e)[:50]} → リトライ", flush=True)
            time.sleep(5)
    raise last


def write_restock(sheet_rows):
    """{row:int → {a, b, aux}} を A列=a(新supply) / B列=b(在庫補充後itemID) / D列(売り切れ)空 / 補URL=aux。

    新規出品でなく既存listing在庫補充なので **B列はitemIDを保持/更新**(空にしない)。
    """
    if not sheet_rows:
        return 0
    ws = sheet_io._product_ws()
    reqs = []
    for row, d in sheet_rows.items():
        reqs.append({"range": f"A{row}", "values": [[d.get("a", "")]]})
        reqs.append({"range": f"B{row}", "values": [[d.get("b", "")]]})
        reqs.append({"range": f"D{row}", "values": [[""]]})   # 売り切れ解除(在庫補充済)
    ws.batch_update(reqs, value_input_option="RAW")
    aux = {row: d["aux"] for row, d in sheet_rows.items() if d.get("aux")}
    if aux:
        sheet_io.write_aux_urls(aux)
    return len(sheet_rows)


def serve_and_collect(html_str):
    """HTML を port で配信 → 送信(POST /submit)を受けて {row(str): value} を返す。"""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    box = {}
    done = threading.Event()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html_str.encode("utf-8"))

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(n).decode("utf-8") if n else "{}"
            try:
                box["data"] = json.loads(raw)
            except Exception:
                box["data"] = {}
            try:
                _d = box.get("data") or {}
                _nz = {k: v for k, v in _d.items() if v and v != "NONE"}
                print(f"  📥 受信: {len(_d)}行 / 選択あり {len(_nz)}行 → {_nz}", flush=True)
            except Exception:
                pass
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            done.set()

    srv = HTTPServer(("127.0.0.1", PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{PORT}/"
    print(f"  🌐 ブラウザで選択 → 送信: {url}")
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass
    done.wait(timeout=1800)
    try:
        srv.shutdown()
    except Exception:
        pass
    return box.get("data") or {}


def _ebay_title(item_id):
    """eBay出品の Title を GetItem で取得(賞=英語 Prize の補完用)。失敗は ''。"""
    import requests
    import ebay_getitem_images as g
    try:
        k = g._load_keys()
    except Exception:
        return ""
    hdr = {"X-EBAY-API-CALL-NAME": "GetItem", "X-EBAY-API-SITEID": "0",
           "X-EBAY-API-COMPATIBILITY-LEVEL": g._COMPAT, "X-EBAY-API-APP-NAME": k["AppID"],
           "X-EBAY-API-DEV-NAME": k["DevID"], "X-EBAY-API-CERT-NAME": k["AppSecret"],
           "Content-Type": "text/xml"}
    body = ('<?xml version="1.0" encoding="utf-8"?><GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
            f"<RequesterCredentials><eBayAuthToken>{k['AuthToken']}</eBayAuthToken></RequesterCredentials>"
            f"<ItemID>{item_id}</ItemID></GetItemRequest>")
    txt = ""
    for _ in range(4):
        try:
            txt = requests.post(g._ENDPOINT, data=body.encode("utf-8"), headers=hdr, timeout=30).text
            break
        except Exception:
            time.sleep(3)
    m = re.search(r"<Title>(.*?)</Title>", txt)
    return _html.unescape(m.group(1)) if m else ""


def _ebay_status(item_id):
    """GetItem(appトークン) → (ListingStatus, Quantity:int)。失敗は ('?', -1)。"""
    import requests
    import ebay_getitem_images as g
    try:
        k = g._load_keys()
    except Exception:
        return ("?", -1)
    hdr = {"X-EBAY-API-CALL-NAME": "GetItem", "X-EBAY-API-SITEID": "0",
           "X-EBAY-API-COMPATIBILITY-LEVEL": g._COMPAT, "X-EBAY-API-APP-NAME": k["AppID"],
           "X-EBAY-API-DEV-NAME": k["DevID"], "X-EBAY-API-CERT-NAME": k["AppSecret"], "Content-Type": "text/xml"}
    body = ('<?xml version="1.0" encoding="utf-8"?><GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
            f"<RequesterCredentials><eBayAuthToken>{k['AuthToken']}</eBayAuthToken></RequesterCredentials>"
            f"<ItemID>{item_id}</ItemID><DetailLevel>ReturnAll</DetailLevel></GetItemRequest>")
    txt = ""
    for _ in range(4):
        try:
            txt = requests.post(g._ENDPOINT, data=body.encode("utf-8"), headers=hdr, timeout=30).text
            break
        except Exception:
            time.sleep(4)
    st = re.search(r"<ListingStatus>(.*?)</ListingStatus>", txt)
    q = re.search(r"<Quantity>(\d+)</Quantity>", txt)
    return (st.group(1) if st else "?", int(q.group(1)) if q else -1)


def _sell_token():
    """売り手OAuthトークン(Trading書込用)。refresh してから返す(PSA取下げ/復活で実績)。"""
    import json as _j
    import subprocess
    import ebay_getitem_images as g
    base = os.path.dirname(os.path.abspath(g.__file__))
    try:
        subprocess.run([sys.executable, "oauth_sell_setup.py", "refresh"], cwd=base, capture_output=True, timeout=60)
    except Exception:
        pass
    return _j.load(open(os.path.join(base, "ebay_oauth_token_sell.json"), encoding="utf-8"))["access_token"]


def _trading_iaf(call, inner, tok):
    """Trading API を IAF(売り手OAuth)で叩く。transient リトライ。戻り: レスポンスXML。"""
    import requests
    import ebay_getitem_images as g
    hdr = {"X-EBAY-API-CALL-NAME": call, "X-EBAY-API-SITEID": "0",
           "X-EBAY-API-COMPATIBILITY-LEVEL": g._COMPAT, "X-EBAY-API-IAF-TOKEN": tok, "Content-Type": "text/xml"}
    body = (f'<?xml version="1.0" encoding="utf-8"?><{call}Request xmlns="urn:ebay:apis:eBLBaseComponents">'
            f"{inner}</{call}Request>")
    last = None
    for _ in range(5):
        try:
            return requests.post(g._ENDPOINT, data=body.encode("utf-8"), headers=hdr, timeout=40).text
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(5)
    raise last


def _ack_ok(txt):
    m = re.search(r"<Ack>(.*?)</Ack>", txt)
    return bool(m) and m.group(1) in ("Success", "Warning")


def _short_err(txt):
    m = re.findall(r"<ShortMessage>(.*?)</ShortMessage>", txt)
    return "; ".join(m[:2]) if m else txt[:80]


def ebay_restock(item_id, tok=None):
    """eBay listing を在庫補充(新規出品でなく既存を戻す)。戻り: (item_id, action)。

    - Active & qty==0 → ReviseFixedPriceItem で Quantity=1(同 itemID 復活)
    - Completed(取下げ済) → RelistFixedPriceItem(同内容・新 itemID)
    - Active & qty>0 → 既に在庫あり(no-op)
    """
    status, qty = _ebay_status(item_id)
    tok = tok or _sell_token()
    if status == "Completed":
        # Relist は元の Quantity(取下げ時=0)をコピーするので Quantity=1 を明示(在庫復活)。
        t = _trading_iaf("RelistFixedPriceItem",
                         f"<Item><ItemID>{item_id}</ItemID><Quantity>1</Quantity></Item>", tok)
        m = re.search(r"<ItemID>(\d+)</ItemID>", t)
        if _ack_ok(t) and m:
            return m.group(1), "relist(新ID・qty=1)"
        raise RuntimeError(f"Relist失敗: {_short_err(t)}")
    if status == "Active":
        if qty > 0:
            return item_id, "在庫あり(no-op)"
        t = _trading_iaf("ReviseFixedPriceItem", f"<Item><ItemID>{item_id}</ItemID><Quantity>1</Quantity></Item>", tok)
        if _ack_ok(t):
            return item_id, "revise qty=1"
        raise RuntimeError(f"Revise失敗: {_short_err(t)}")
    raise RuntimeError(f"未対応 status={status}")


def _make_driver():
    """uc.Chrome 起動。DNS一時失敗(getaddrinfo)で初期化が稀にコケるのでリトライ。"""
    import undetected_chromedriver as uc
    maj = _chrome_major()
    last = None
    for attempt in range(3):
        try:
            opts = uc.ChromeOptions()   # uc は options を消費するので毎回生成
            for a in ("--headless=new", "--no-sandbox", "--lang=ja-JP", "--window-size=1280,1400"):
                opts.add_argument(a)
            return uc.Chrome(options=opts, version_main=maj) if maj else uc.Chrome(options=opts)
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"  ⚠ Chrome起動失敗(attempt {attempt+1}/3): {type(e).__name__} → リトライ", flush=True)
            time.sleep(6)
    raise last


def _href_to_image(src):
    """検索結果HTMLの各item-cellから href→実画像src を作る (item=mercdn / shops=mercari-shops 両対応)。

    Shops は assets.mercari-shops-static.com の webp で mercari_image_url では構築不能なため、
    検索結果の <img src/srcset> を直接拾う(2026-06-24 候補画像が出ない件)。
    """
    out = {}
    for b in re.split(r'data-testid="item-cell"', src)[1:]:
        hr = re.search(r'href="(/(?:item/m\w+|shops/product/\w+))"', b)
        if not hr:
            continue
        im = re.search(r'(?:src|srcset)="(https://[^"\s]+?\.(?:jpg|jpeg|png|webp)[^"\s]*)"', b)
        out["https://jp.mercari.com" + hr.group(1)] = im.group(1) if im else ""
    return out


def kw_search(drv, kw, limit):
    """段階1: キーワード検索(実写候補・通常出品のみ)。

    関連度順(価格昇順にしない): 価格昇順だと「台座のみ/アクリル台座」等の安いアクセサリが
    上位に来て本体が埋もれる(2026-06-24 ユーザー指摘)。新品フィルタも外す(recall優先・
    正しい景品を見つけるのが目的。新品担保はパスBの最終確認で)。画像は実src を付与。
    """
    url = "https://jp.mercari.com/search?keyword=" + urllib.parse.quote(kw) + "&status=on_sale"
    drv.get(url)
    time.sleep(8)
    src = drv.page_source
    imgmap = _href_to_image(src)
    items = parse_mercari_items(src)[:limit]
    for it in items:
        it["image"] = imgmap.get(it["href"], "")
    return items


def image_search_from_url(drv, mercari_url, limit):
    """段階2: 選んだ実写(mercari_url の画像)で mercari画像検索 → 同景品 候補(価格昇順)。"""
    from selenium.webdriver.common.by import By
    import requests
    img = mercari_image_url(mercari_url)
    if not img:
        return []
    p = os.path.join(os.environ.get("TEMP", "."), "ichi_seed.jpg")
    try:
        with open(p, "wb") as f:
            f.write(requests.get(img, timeout=30, headers={"User-Agent": "Mozilla/5.0"}).content)
    except Exception:
        return []
    try:
        drv.get("https://jp.mercari.com/search?keyword=%20")
        time.sleep(7)
        btn = drv.find_elements(By.CSS_SELECTOR, '[data-testid="image-search-button"]')
        if not btn:
            return []
        btn[0].click()
        time.sleep(2)
        fin = drv.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
        if not fin:
            return []
        fin[0].send_keys(p)
        time.sleep(12)
        src = drv.page_source
        res = parse_image_search_results(src)
    except Exception:
        return []
    # 画像検索モーダルから href→実画像src(item=mercdn / shops=mercari-shops 両対応)。
    # parse_image_search_results は画像を返さない+Shopsは mercari_image_url で構築不可のため。
    imgmap = {}
    for seg in re.split(r'data-location="image_search:similar_looks_modal:item_thumbnail"', src)[1:]:
        hr = re.search(r'href="(/(?:item/m\w+|shops/product/\w+))"', seg)
        if not hr:
            continue
        im = re.search(r'(?:src|srcset)="(https://[^"\s]+?\.(?:jpg|jpeg|png|webp)[^"\s]*)"', seg)
        imgmap["https://jp.mercari.com" + hr.group(1)] = im.group(1) if im else ""
    onsale = sorted([r for r in res if not r["sold"]], key=lambda x: x["price"])
    for r in onsale:
        r["image"] = imgmap.get(r["href"], "")
    return onsale[:limit]


_KEEP_COND = ("新品、未使用", "未使用に近い")   # 新品扱い。これ以外(目立った傷/やや傷…)は除外


def _cond_ship(drv, url):
    """商品詳細ページから (状態, 送料負担) を取得。失敗は ('','')。"""
    try:
        drv.get(url)
        time.sleep(3)
        s = drv.page_source
        c = re.search(r"(新品、未使用|未使用に近い|目立った傷や汚れなし|やや傷や汚れあり|傷や汚れあり|全体的に状態が悪い)", s)
        ship = "送料込み" if "送料込み" in s else ("着払い" if "着払い" in s else "")
        return (c.group(1) if c else "", ship)
    except Exception:
        return ("", "")


def _filter_new_freeship(drv, raw):
    """画像検索候補を **新品(新品、未使用/未使用に近い) かつ 送料込み** だけに絞る(詳細ページ訪問)。

    状態/送料は検索結果に無く詳細ページにしかないため各候補を訪問(やや遅い)。
    やや傷/目立った傷/着払い は除外(2026-06-24 ユーザー: 新品+送料込みのみ)。
    """
    kept = []
    for c in raw:
        cond, ship = _cond_ship(drv, c["href"])
        if cond in _KEEP_COND and ship == "送料込み":
            c["cond"], c["ship"] = cond, ship
            kept.append(c)
    return kept


# ---------------- パス ----------------
def pass_identify(n, cand_n):
    targets = get_oos_ichibankuji(n)
    print(f"画像特定(パスA): OOS一番くじ {len(targets)}件 (各最安{cand_n}候補)")
    if not targets:
        print("対象なし"); return
    drv = _make_driver()
    items = []
    try:
        drv.set_page_load_timeout(50)
        for i, t in enumerate(targets, 1):
            pics = fetch_listing_images(t["item_id"])
            et = _ebay_title(t["item_id"])             # 一番くじ+賞は生成済eBayタイトルが確実
            kw, prize = build_keyword(t["title"], et)  # C列(日本語作品/キャラ)+一番くじ+賞
            print(f"  [{i}/{len(targets)}] 賞={prize or '不明'} kw={kw[:32]}", flush=True)
            try:
                raw = kw_search(drv, kw, cand_n)
            except Exception as e:  # noqa: BLE001
                print(f"     ⚠ 検索失敗: {e}"); raw = []
            items.append({"row": t["row"], "item_id": t["item_id"], "title": t["title"],
                          "prize": prize, "ref_image": pics[0] if pics else "",
                          "candidates": [{"url": c["href"], "price": c["price"],
                                          "image": c.get("image", "")} for c in raw]})
    finally:
        try: drv.quit()
        except Exception: pass
    picks = serve_and_collect(build_identify_html(items))
    # picks: {row(str): url|'NONE'|''}。url が入った行を保存(パスBの種)。
    saved = []
    by_row = {str(it["row"]): it for it in items}
    for row, val in picks.items():
        if val and val != "NONE" and row in by_row:
            it = by_row[row]
            saved.append({"row": int(row), "item_id": it["item_id"], "title": it["title"],
                          "ref_image": it["ref_image"], "picked_url": val})
    os.makedirs(os.path.dirname(PICKS_FILE), exist_ok=True)
    with open(PICKS_FILE, "w", encoding="utf-8") as f:
        json.dump(saved, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 画像特定 {len(saved)}件 保存: {PICKS_FILE}")
    print("   次: python ichibankuji_restock.py expand")


def pass_expand(cand_n, dry=False):
    if not os.path.exists(PICKS_FILE):
        print(f"picks がありません。先に identify を実行: {PICKS_FILE}"); return
    picks = json.load(open(PICKS_FILE, encoding="utf-8"))
    picks = [p for p in picks if p.get("picked_url")]
    print(f"画像検索+確定(パスB): {len(picks)}件 (各最安{cand_n}候補)")
    if not picks:
        print("特定済(picked_url)が無い"); return
    drv = _make_driver()
    items = []
    try:
        drv.set_page_load_timeout(50)
        for i, p in enumerate(picks, 1):
            print(f"  [{i}/{len(picks)}] 画像検索: {p['title'][:30]}", flush=True)
            try:
                raw = image_search_from_url(drv, p["picked_url"], cand_n)
            except Exception as e:  # noqa: BLE001
                print(f"     ⚠ 画像検索失敗: {e}"); raw = []
            print(f"     候補 {len(raw)}件 → 状態/送料 確認中(新品+送料込みのみ)...", flush=True)
            raw = _filter_new_freeship(drv, raw)
            print(f"     新品+送料込み {len(raw)}件", flush=True)
            items.append({"row": p["row"], "item_id": p["item_id"], "title": p["title"],
                          "ref_image": p.get("ref_image", ""),
                          "picked_image": mercari_image_url(p["picked_url"]),
                          "candidates": [{"url": c["href"], "price": c["price"],
                                          "image": c.get("image", "") or mercari_image_url(c["href"]),
                                          "cond": c.get("cond", ""), "ship": c.get("ship", "")}
                                         for c in raw]})
    finally:
        try: drv.quit()
        except Exception: pass
    finals = serve_and_collect(build_expand_html(items))
    by_row = {it["row"]: it for it in items}   # row → 表示item(item_id 等)
    confirmed = {}   # row → {item_id, a(主supply), aux(補・最大5)}
    for row, val in finals.items():
        urls = val if isinstance(val, list) else ([val] if (val and val != "NONE") else [])
        seen = set()
        urls = [u for u in urls if u and u != "NONE" and not (u in seen or seen.add(u))]
        if urls:
            r = int(row)
            confirmed[r] = {"item_id": (by_row.get(r) or {}).get("item_id", ""),
                            "a": urls[0],          # 先頭(最安 or 手動)= 主supply → A列
                            "aux": urls[1:6]}      # 残り = 補URL(mercari/Shops混在OK・最大5)
    if not confirmed:
        print("確定なし(全行 未選択/該当なし)"); return
    # 書込前に確定を保存(API障害で落ちても再選択不要 → write で再適用)
    _save_confirmed(confirmed)
    print(f"  💾 確定を保存(失敗時は再選択不要・write で再適用): {CONFIRMED_FILE}")
    if dry:
        print(f"\n🧪 DRY-RUN: eBay/スプシ 書込なし。確定予定 {len(confirmed)}件:")
        for r in sorted(confirmed):
            d = confirmed[r]
            st, q = _ebay_status(d["item_id"]) if d["item_id"] else ("?", -1)
            plan = "Relist(新ID)" if st == "Completed" else ("Revise qty=1" if st == "Active" and q == 0 else f"({st} qty{q})")
            print(f"   row{r} itemID={d['item_id']}({st}/qty{q}→{plan}): A列← {d['a']}")
            for u in d["aux"]:
                print(f"            補URL← {u}")
        print(f"   → 本番反映: python ichibankuji_restock.py write")
        return
    try:
        n = _apply_restock(confirmed)
    except Exception as e:  # noqa: BLE001
        print(f"\n❌ 反映が最終的に失敗: {type(e).__name__}: {str(e)[:60]}")
        print(f"   選択は保存済 → 復旧: python ichibankuji_restock.py write")
        return
    print(f"\n✅ 完了 {n}件: eBay在庫補充 + A列=新supply + B列=itemID + 売り切れ解除 + 補URL")


def _save_confirmed(confirmed):
    """confirmed = {row:int → {item_id, a, aux}} を保存(書込失敗時の再適用用)。"""
    payload = {"items": {str(k): v for k, v in confirmed.items()}}
    os.makedirs(os.path.dirname(CONFIRMED_FILE), exist_ok=True)
    with open(CONFIRMED_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _load_confirmed():
    d = json.load(open(CONFIRMED_FILE, encoding="utf-8"))
    return {int(k): v for k, v in (d.get("items") or {}).items()}


def _apply_restock(confirmed):
    """confirmed={row:{item_id,a,aux}} → eBay在庫補充(Revise/Relist) + スプシ書込。

    eBay: qty0 Active→Revise qty=1(同ID) / Completed→Relist(新ID)。B列はそのitemIDを保持/更新。
    スプシ: A列=新supply / B列=補充後itemID / 売り切れ解除 / 補URL。
    """
    tok = None
    try:
        tok = _sell_token()
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ 売り手トークン取得失敗: {e}(eBay補充はskip・スプシのみ)")
    sheet_rows = {}
    for row in sorted(confirmed):
        d = confirmed[row]
        item_id = (d.get("item_id") or "").strip()
        new_id, action = item_id, "no_itemid(eBay補充skip)"
        if item_id and tok:
            try:
                new_id, action = _retry(lambda: ebay_restock(item_id, tok), what=f"row{row} eBay在庫補充")
            except Exception as e:  # noqa: BLE001
                action = f"❌FAILED:{type(e).__name__}"
                new_id = item_id
                print(f"  ❌ row{row} eBay在庫補充 最終失敗: {e}(スプシは書く)")
        print(f"  📦 row{row}: {action}  itemID={new_id}")
        sheet_rows[row] = {"a": d.get("a", ""), "b": new_id, "aux": d.get("aux", [])}
    n = _retry(lambda: write_restock(sheet_rows), what="スプシ書込")
    return n


def pass_write():
    """確定(保存済 or dry後)を eBay在庫補充 + スプシ反映。dry/失敗後の本番反映に使う。"""
    if not os.path.exists(CONFIRMED_FILE):
        print(f"確定ファイルなし: {CONFIRMED_FILE}"); return
    confirmed = _load_confirmed()
    if not confirmed:
        print("確定なし"); return
    print(f"確定 {len(confirmed)}件 を eBay在庫補充 + スプシ反映...")
    n = _apply_restock(confirmed)
    print(f"✅ 完了 {n}件: eBay在庫補充(Revise/Relist) + A列=新supply + B列=itemID + 売り切れ解除 + 補URL")


# ---------------- 内容刷新 (refresh): タイトル/itemSP/価格を新規ロジックで刷新 → FileExchange Revise CSV ----------------
def _gen():
    """新規生成器 ichibankuji_to_csv を import 流用(無改変)。戻り (module, gen_dir)。"""
    gd = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMak_ichibankuji"))
    if gd not in sys.path:
        sys.path.insert(0, gd)
    import ichibankuji_to_csv as gen
    return gen, gd


def _sheet_meta():
    """管理シートを1回読み、{row(int): {title(C), kuji_url(I)}} を返す。"""
    ws = sheet_io._product_ws()
    out = {}
    for i, row in enumerate(ws.get_all_values(), start=1):
        if i == 1:
            continue
        title = (row[COL_TITLE] if len(row) > COL_TITLE else "").strip()
        kuji = (row[COL_KUJI_URL] if len(row) > COL_KUJI_URL else "").strip()
        out[i] = {"title": title, "kuji_url": kuji}
    return out


def _match_prize(prize, prizes):
    """extract_prize の賞(A賞/ラストワン 等)を scrape の prizes[].prize に突合。無ければ None。

    scrape は 'ラストワン賞'、extract_prize は 'ラストワン' と末尾差があるので 賞 を除いて比較。
    """
    if not prize:
        return None
    key = prize.rstrip("賞")
    for p in prizes:
        pp = (p.get("prize") or "").rstrip("賞")
        if pp == key or (key and key in pp):
            return p
    return None


def _manual_prize(prizes):
    """賞マッチ失敗時の手動賞指定(CLI)。番号入力で1つ選ぶ。空/s = skip(None)。"""
    if not prizes:
        print("      賞候補なし → skip")
        return None
    print("      ⚠️ 賞マッチ失敗。手動指定してください:")
    for i, p in enumerate(prizes, 1):
        print(f"        {i}. {p.get('prize','')}: {(p.get('name') or '')[:36]}")
    try:
        ans = input("      番号 (空/s=skip): ").strip()
    except EOFError:
        ans = ""
    if ans.isdigit() and 1 <= int(ans) <= len(prizes):
        return prizes[int(ans) - 1]
    return None


def _build_refreshed_row(gen, base_desc, series_name, release_year, price_jpy, main_image,
                         kuji_url, supply_url, prize_p, cost_jpy):
    """1賞ぶんを Claude+pricing+build_row で刷新。戻り (ebay_row|None, new_title, price, note)。"""
    series_data = {
        "series_name": series_name, "release_year": release_year, "price_jpy": price_jpy,
        "main_image": main_image, "url": kuji_url, "mercari_url": supply_url, "prizes": [],
    }
    prize_data = {"prize": prize_p.get("prize", ""), "name": prize_p.get("name", ""),
                  "size_cm": prize_p.get("size_cm", "")}
    claude_result = gen.analyze_with_claude(series_data, prize_data)
    if not claude_result:
        return None, "", 0, "Claude失敗"
    if not claude_result.get("is_figure", True):
        return None, claude_result.get("title", ""), 0, "非フィギュア判定→skip"

    # pricing: cost = 新supply実価格。新発売 median 信頼性低のため gap_limit=10.0(generator 同条件)
    listing_price = gen.DEFAULT_PRICE
    ebay_median = 0.0
    price_status = "GO"
    try:
        if cost_jpy and int(cost_jpy) > 0:
            from pricing_engine import compute_listing_price
            try:
                from listing_common import PRICE_CHECK_CONFIG
                if PRICE_CHECK_CONFIG.get("ichibankuji", {}).get("enabled"):
                    from check_csv_core import fetch_ebay_market_median
                    _kw = " ".join((claude_result.get("title", "") or "").split()[:5])
                    ebay_median, _hits = fetch_ebay_market_median(
                        keywords=_kw, category_ids=str(gen.EBAY_CATEGORY),
                        condition_id=str(gen.CONDITION_ID), limit=30)
            except Exception:
                pass
            pricing = compute_listing_price(int(cost_jpy), ebay_median, gen.PROFIT_CATEGORY,
                                            gap_limit_override=10.0)
            listing_price = max(pricing.get("price", gen.DEFAULT_PRICE), 9.98)
            price_status = pricing.get("status", "GO")
    except Exception as e:  # noqa: BLE001
        print(f"      ⚠️ pricing失敗: {e}(DEFAULT_PRICE使用)")

    ebay_row = gen.build_row(series_data, prize_data, claude_result, listing_price, base_desc)

    # 物理ゲート(新規生成と同じ品質基準): error は HOLD=skip(fail-closed)
    try:
        from listing_common import gate_row_or_hold
        allowed, viol = gate_row_or_hold(ebay_row, category="ichibankuji",
                                         sku=ebay_row.get("CustomLabel", ""),
                                         price_status=price_status, median_usd=ebay_median)
        if not allowed:
            errs = [f"{f}={i}" for f, i, s in viol if s == "error"]
            return None, ebay_row.get("*Title", ""), listing_price, f"HOLD:{errs}"
    except Exception as e:  # noqa: BLE001
        print(f"      ⚠️ gate skip(非致命): {e}")

    return ebay_row, ebay_row.get("*Title", ""), listing_price, "OK"


def pass_refresh():
    """確定(confirmed.json)の各行を scrape+Claude で刷新 → プレビュー表示 + REFRESH_FILE 保存。

    dry必須(表示→明示 `refresh write`)。eBay/CSV への書込はしない。
    """
    if not os.path.exists(CONFIRMED_FILE):
        print(f"確定ファイルなし: {CONFIRMED_FILE}(先に identify→expand)"); return
    confirmed = _load_confirmed()
    if not confirmed:
        print("確定なし"); return
    gen, gd = _gen()
    base_path = os.path.join(gd, "ICHIBANKUJI.txt")
    base_desc = open(base_path, encoding="utf-8").read() if os.path.exists(base_path) else None
    meta = _sheet_meta()

    # 同一くじURLは1回 scrape(重い処理を集約)
    drv = _make_driver()
    scraped = {}
    try:
        drv.set_page_load_timeout(60)
        urls = {(meta.get(r) or {}).get("kuji_url", "") for r in confirmed}
        for u in sorted(x for x in urls if x and x != "-"):
            print(f"  🔎 scrape: {u}", flush=True)
            try:
                scraped_sd = _retry(lambda: gen.scrape_1kuji(drv, u), tries=3, what="scrape_1kuji")
            except Exception as e:  # noqa: BLE001
                print(f"     ⚠ scrape失敗: {e}"); scraped_sd = None
            scraped[u] = scraped_sd
    finally:
        try: drv.quit()
        except Exception: pass

    planned = []   # [{item_id, sku, row, old_title, new_title, price}]
    for row in sorted(confirmed):
        d = confirmed[row]
        item_id = (d.get("item_id") or "").strip()
        m = meta.get(row) or {}
        kuji_url = (m.get("kuji_url") or "").strip()
        title_jp = m.get("title") or ""
        supply = (d.get("a") or "").strip()
        print(f"\n  [row{row}] itemID={item_id} {title_jp[:30]}", flush=True)
        if not kuji_url or kuji_url == "-":
            print("     ⚠️ I列(公式くじURL)空 → skip(刷新不可)"); continue
        sd = scraped.get(kuji_url)
        if not sd or not sd.get("prizes"):
            print("     ⚠️ scrape不可/賞0 → skip"); continue
        prize = extract_prize(title_jp, _ebay_title(item_id))   # C列(日本語)+eBayタイトル(英語)から賞
        pp = _match_prize(prize, sd["prizes"])
        if not pp:
            pp = _manual_prize(sd["prizes"])
        if not pp:
            print(f"     賞={prize or '不明'} → 確定できず skip"); continue
        cost = gen.fetch_mercari_price(supply) if supply else 0
        if not cost:
            print(f"     ⚠️ 新supply価格取得不可({supply[:40]}) → DEFAULT_PRICE", flush=True)
        ebay_row, new_title, price, note = _build_refreshed_row(
            gen, base_desc, sd.get("series_name", ""), sd.get("release_year", ""),
            sd.get("price_jpy", ""), sd.get("main_image", ""), kuji_url, supply, pp, cost)
        if not ebay_row:
            print(f"     ⏭ {note}"); continue
        old_title = _ebay_title(item_id)
        planned.append({"item_id": item_id, "sku": ebay_row.get("CustomLabel", ""),
                        "row": ebay_row, "old_title": old_title, "new_title": new_title,
                        "price": price})
        print(f"     ✅ 賞={pp.get('prize')} cost¥{cost or '?'} → ${price}")

    if not planned:
        print("\n刷新対象なし"); return
    os.makedirs(os.path.dirname(REFRESH_FILE), exist_ok=True)
    with open(REFRESH_FILE, "w", encoding="utf-8") as f:
        json.dump({"items": planned}, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*70}\n🧪 刷新プレビュー {len(planned)}件(eBay/CSV 未書込):")
    for p in planned:
        act, st, q = plan_action(p["item_id"])
        tag = {"revise": "Revise→同ID", "add": "Add→新ID(出し直し)", "skip": f"skip({st})"}[act]
        print(f"\n  itemID={p['item_id']}  ${p['price']}  [{st} qty{q} → {tag}]")
        print(f"    旧: {p['old_title']}")
        print(f"    新: {p['new_title']}")
    print(f"\n💾 保存: {REFRESH_FILE}")
    print("  → 確認OKなら本番反映: python ichibankuji_restock.py refresh write")
    print("     (Active=Revise同ID / Completed=Add新ID で振分 → 出品くんで FileExchange 入稿)")


def plan_action(item_id):
    """現状 eBay 状態から刷新の適用方法を決める。戻り: 'revise'(同ID) / 'add'(新ID) / 'skip'。

    itemID を変えずに済むなら Revise(同ID=view/watcher 温存)、終了済で無理なら Add(新ID=出し直し)。
    監視くん/原因は無関係 — 「今 eBay でどうなってるか」だけで決まる(2026-06-24 ユーザー方針)。
    """
    if not item_id:
        return ("skip", "?", -1)
    st, q = _ebay_status(item_id)
    if st == "Active":
        return ("revise", st, q)      # Revise 可 = 同ID で内容刷新 + qty=1
    if st == "Completed":
        return ("add", st, q)         # 終了済 = Revise不可 → 新規Addで出し直し(新ID)
    return ("skip", st, q)            # 状態不明 = fail-closed(推測でいじらない)


def _write_addform_csv(rows, path):
    """ebay_row dict list → Add形式CSV(generator と同形式 utf-8-sig)+ Free Shipping 後処理。"""
    import csv as _csv
    keys = list(rows[0].keys())
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    try:
        from freeshipping_postprocess import transform_csv_to_freeshipping
        transform_csv_to_freeshipping(path)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ Free Shipping 後処理 失敗(非致命): {type(e).__name__}: {e}")


def refresh_write():
    """REFRESH_FILE(刷新確定) → 現状eBay状態で振分: Active→Revise CSV(同ID) / Completed→Add CSV(新ID)。"""
    if not os.path.exists(REFRESH_FILE):
        print(f"刷新確定なし: {REFRESH_FILE}(先に refresh)"); return
    planned = (json.load(open(REFRESH_FILE, encoding="utf-8")).get("items")) or []
    if not planned:
        print("刷新確定なし"); return
    import ichibankuji_restock_revise as rv
    gen, gd = _gen()
    out_dir = os.path.dirname(gen.OUTPUT_CSV)

    # 現状 eBay 状態で Revise(同ID) / Add(新ID) に振り分け
    revise_planned, add_planned, skipped_status = [], [], []
    for p in planned:
        act, st, q = plan_action(p.get("item_id", ""))
        print(f"  itemID={p.get('item_id')}: {st} qty{q} → {act}")
        (revise_planned if act == "revise" else add_planned if act == "add" else skipped_status).append(p)
    if skipped_status:
        print(f"  ⚠️ 状態不明で除外 {len(skipped_status)}件(fail-closed): {[p.get('item_id') for p in skipped_status]}")

    outputs = []
    # Active → Revise CSV(同ID・内容刷新 + qty=1 + PicURL/ScheduleTime削除)
    if revise_planned:
        add_tmp = os.path.join(out_dir, "ichibankuji_restock_add_tmp.csv")
        revise_csv = os.path.join(out_dir, "ichibankuji_restock_revise.csv")
        _write_addform_csv([p["row"] for p in revise_planned], add_tmp)
        sku_to_itemid = {p["sku"]: p["item_id"] for p in revise_planned if p.get("sku")}
        n, sk = rv.convert_file(add_tmp, revise_csv, sku_to_itemid)
        try:
            os.remove(add_tmp)
        except Exception:
            pass
        outputs.append((revise_csv, n, "Revise(同ID=view/watcher温存)"))
        if sk:
            print(f"  ⚠️ Revise: itemID未解決で除外 {len(sk)}件: {[s[0] for s in sk]}")
    # Completed → Add CSV(新ID・新規出し直し。PicURL/ScheduleTime はそのまま=新規出品)
    if add_planned:
        add_csv = os.path.join(out_dir, "ichibankuji_restock_add.csv")
        _write_addform_csv([p["row"] for p in add_planned], add_csv)
        outputs.append((add_csv, len(add_planned), "Add(新ID=終了済の出し直し)"))

    if not outputs:
        print("出力対象なし(全件 状態不明)"); return
    print()
    for path, cnt, kind in outputs:
        print(f"✅ {kind} CSV 出力: {path}  ({cnt}件)")
    print("  → 出品くんで FileExchange 入稿(Revise=旧ID内容刷新 / Add=新ID出し直し)")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "identify":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        pass_identify(n, cand_n=10)
    elif mode == "expand":
        pass_expand(cand_n=10, dry=("--dry" in sys.argv))
    elif mode == "write":
        pass_write()
    elif mode == "refresh":
        if len(sys.argv) > 2 and sys.argv[2] == "write":
            refresh_write()
        else:
            pass_refresh()
    else:
        print("使い方:\n  python ichibankuji_restock.py identify [件数]   # パスA 画像特定\n"
              "  python ichibankuji_restock.py expand [--dry]      # パスB 画像検索+確定(--dry=書込なしテスト)\n"
              "  python ichibankuji_restock.py write               # dry/失敗後の本番反映(再選択不要)\n"
              "  python ichibankuji_restock.py refresh             # 内容刷新プレビュー(scrape+Claude、書込なし)\n"
              "  python ichibankuji_restock.py refresh write       # 刷新を Revise CSV 出力(出品くん入稿用)")


if __name__ == "__main__":
    main()
