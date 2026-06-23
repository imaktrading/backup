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
COL_SOLD = 3       # D 売り切れ
COL_CAT = 17       # R カテゴリ
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


def _card(url, price, image, name, multi=False):
    """候補カード(選択+画像+価格+リンク)。multi=True で checkbox(複数選択), False で radio(単一)。

    image は検索結果から取得した実URL(Shops含む)。リンクは新品確認用に target=_blank。
    """
    img = image or mercari_image_url(url)   # 実src優先、無ければ /item/m から構築
    img_tag = (f"<img src='{_html.escape(img)}' loading='lazy'>" if img
               else "<div class=noimg>画像なし</div>")
    pr = f"¥{price:,}" if price else ""
    if multi:
        inp = f"<input type=checkbox class=pick value='{_html.escape(url)}'>"
    else:
        inp = f"<input type=radio class=pick name='{_html.escape(name)}' value='{_html.escape(url)}'>"
    return (f"<label class=cand>{inp}{img_tag}<div class=meta>{pr}<br>"
            f"<a href='{_html.escape(url)}' target=_blank>開く(新品確認)</a></div></label>")


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
            parts.append(_card(c["url"], c.get("price", 0), c.get("image", ""), nm, multi=multi))
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


def write_confirmed(confirmations):
    """確定 {row:int → supply_url} を A列昇格 + B列クリア + 売り切れ(D)クリア。

    A列=新supply(死んだ旧A列を置換)、B列空=未出品扱い、D列空=売り切れ解除 → 通常②で再出品。
    """
    if not confirmations:
        return 0
    ws = sheet_io._product_ws()
    reqs = []
    for row, url in confirmations.items():
        reqs.append({"range": f"A{row}", "values": [[url]]})
        reqs.append({"range": f"B{row}", "values": [[""]]})
        reqs.append({"range": f"D{row}", "values": [[""]]})
    ws.batch_update(reqs, value_input_option="RAW")
    return len(confirmations)


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


def pass_expand(cand_n):
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
            items.append({"row": p["row"], "item_id": p["item_id"], "title": p["title"],
                          "ref_image": p.get("ref_image", ""),
                          "picked_image": mercari_image_url(p["picked_url"]),
                          "candidates": [{"url": c["href"], "price": c["price"],
                                          "image": c.get("image", "") or mercari_image_url(c["href"])}
                                         for c in raw]})
    finally:
        try: drv.quit()
        except Exception: pass
    finals = serve_and_collect(build_expand_html(items))
    confirmations = {}   # row → 主supply(A列昇格)
    aux = {}             # row → 補URL(残りの代替supply・最大5)
    for row, val in finals.items():
        urls = val if isinstance(val, list) else ([val] if (val and val != "NONE") else [])
        seen = set()
        urls = [u for u in urls if u and u != "NONE" and not (u in seen or seen.add(u))]
        if urls:
            confirmations[int(row)] = urls[0]    # 先頭(最安 or 手動)= 主supply → A列
            if len(urls) > 1:
                aux[int(row)] = urls[1:6]        # 残り = 補URL(mercari/Shops混在OK・最大5)
    if not confirmations:
        print("確定なし(全行 未選択/該当なし)"); return
    # 書込前に確定を保存(API障害で書込が落ちても再選択不要 → write モードで再適用可)
    _save_confirmed(confirmations, aux)
    print(f"  💾 確定を保存(書込失敗時は再選択不要・write で再適用): {CONFIRMED_FILE}")
    try:
        n = _apply_confirmed(confirmations, aux)
    except Exception as e:  # noqa: BLE001
        print(f"\n❌ スプシ書込が最終的に失敗: {type(e).__name__}: {str(e)[:60]}")
        print(f"   選択は保存済 → 復旧: python ichibankuji_restock.py write")
        return
    print(f"\n✅ 確定 {n}件: A列に新supply昇格 + B列クリア + 売り切れ解除 + 補URL記録 → 通常②で再出品")
    print("   ※ 出品くんで『一番くじ』を走らせると、A列の新supplyで再出品されます")


def _save_confirmed(confirmations, aux):
    payload = {"confirmations": {str(k): v for k, v in confirmations.items()},
               "aux": {str(k): v for k, v in aux.items()}}
    os.makedirs(os.path.dirname(CONFIRMED_FILE), exist_ok=True)
    with open(CONFIRMED_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _apply_confirmed(confirmations, aux):
    """確定をスプシに適用(retry付き)。A列昇格+B列クリア+売り切れ解除、補URL記録。"""
    n = _retry(lambda: write_confirmed(confirmations), what="A列/B列/売り切れ書込") if confirmations else 0
    if aux:
        _retry(lambda: sheet_io.write_aux_urls(aux), what="補URL書込")
    return n


def pass_write():
    """書込失敗の復旧: 保存済 ichibankuji_confirmed.json をスプシに再適用(再選択不要)。"""
    if not os.path.exists(CONFIRMED_FILE):
        print(f"確定ファイルなし: {CONFIRMED_FILE}"); return
    d = json.load(open(CONFIRMED_FILE, encoding="utf-8"))
    confirmations = {int(k): v for k, v in d.get("confirmations", {}).items()}
    aux = {int(k): v for k, v in d.get("aux", {}).items()}
    print(f"確定 {len(confirmations)}件 を再適用...")
    n = _apply_confirmed(confirmations, aux)
    print(f"✅ 再適用 {n}件: A列昇格 + B列クリア + 売り切れ解除 + 補URL記録")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "identify":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        pass_identify(n, cand_n=10)
    elif mode == "expand":
        pass_expand(cand_n=10)
    elif mode == "write":
        pass_write()
    else:
        print("使い方:\n  python ichibankuji_restock.py identify [件数]   # パスA 画像特定\n"
              "  python ichibankuji_restock.py expand              # パスB 画像検索+確定\n"
              "  python ichibankuji_restock.py write               # 書込失敗の復旧(再選択不要)")


if __name__ == "__main__":
    main()
