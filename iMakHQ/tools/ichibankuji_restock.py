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
COL_SOLD = 3       # D 売り切れ
COL_CAT = 17       # R カテゴリ
_NOISE = ["新品", "未開封", "未使用", "送料無料", "即決", "匿名配送", "正規品", "限定", "おまけつき", "おまけ付き"]


# ---------------- 純粋ロジック ----------------
def clean_kw(title):
    """C列(日本語mercariタイトル)→ mercari検索語。【】ブロック・ノイズ語・記号を除去。"""
    t = re.sub(r"【[^】]*】", " ", title or "")
    t = re.sub(r"[☆★()（）\[\]]", " ", t)
    for w in _NOISE:
        t = t.replace(w, " ")
    return re.sub(r"\s+", " ", t).strip()


def _card(url, price, image, checked_name, label=""):
    """候補カード(ラジオ+画像+価格+リンク)の HTML。image は検索結果から取得した実URL。"""
    img = image or mercari_image_url(url)   # 実src優先、無ければ /item/m から構築
    img_tag = (f"<img src='{_html.escape(img)}' loading='lazy'>" if img
               else "<div class=noimg>画像なし</div>")
    pr = f"¥{price:,}" if price else ""
    return (f"<label class=cand>"
            f"<input type=radio name='{_html.escape(checked_name)}' value='{_html.escape(url)}'>"
            f"{img_tag}<div class=meta>{pr}<br>"
            f"<a href='{_html.escape(url)}' target=_blank>開く</a>{_html.escape(label)}</div></label>")


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
    parts.append(f"<div class=hd>{_html.escape(heading)} — 各行で1つ選び、下の『送信』を押す</div>")
    for it in items:
        nm = f"row_{it['row']}"
        parts.append(f"<div class=item data-row='{it['row']}'>")
        parts.append(f"<div class=title>{_html.escape(it['title'])} <small>(row {it['row']} / 旧itemID {it['item_id']})</small></div>")
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
            parts.append(_card(c["url"], c.get("price", 0), c.get("image", ""), nm))
        # 該当なし(スキップ)
        parts.append(f"<label class=cand><input type=radio name='{nm}' value='NONE'>"
                     f"<div class=noimg>該当なし<br>(skip)</div></label>")
        parts.append("</div></div>")
    parts.append("<div style='padding:16px'><button onclick='submit()'>送信</button></div>")
    parts.append("""<script>
function submit(){
  var picks={};
  document.querySelectorAll('.item').forEach(function(it){
    var sel=it.querySelector('input[type=radio]:checked');
    picks[it.dataset.row]= sel ? sel.value : '';
  });
  fetch('/submit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(picks)})
   .then(r=>r.json()).then(_=>{document.body.innerHTML='<h2 style=padding:20px>送信完了。タブを閉じてOK。</h2>';});
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


def _make_driver():
    import undetected_chromedriver as uc
    opts = uc.ChromeOptions()
    for a in ("--headless=new", "--no-sandbox", "--lang=ja-JP", "--window-size=1280,1400"):
        opts.add_argument(a)
    maj = _chrome_major()
    return uc.Chrome(options=opts, version_main=maj) if maj else uc.Chrome(options=opts)


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
        res = parse_image_search_results(drv.page_source)
    except Exception:
        return []
    onsale = sorted([r for r in res if not r["sold"]], key=lambda x: x["price"])
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
            kw = clean_kw(t["title"])
            print(f"  [{i}/{len(targets)}] {kw[:34]}", flush=True)
            try:
                raw = kw_search(drv, kw, cand_n)
            except Exception as e:  # noqa: BLE001
                print(f"     ⚠ 検索失敗: {e}"); raw = []
            items.append({"row": t["row"], "item_id": t["item_id"], "title": t["title"],
                          "ref_image": pics[0] if pics else "",
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
    confirmations = {}
    aux = {}   # 補URL記録(候補群)
    by_row = {str(it["row"]): it for it in items}
    for row, val in finals.items():
        if val and val != "NONE":
            confirmations[int(row)] = val
            if row in by_row:
                aux[int(row)] = [val] + [c["url"] for c in by_row[row]["candidates"] if c["url"] != val][:4]
    n = write_confirmed(confirmations)
    if aux:
        try:
            sheet_io.write_aux_urls(aux)   # 候補群を補URL列に記録(監査)
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ 補URL記録スキップ: {e}")
    print(f"\n✅ 確定 {n}件: A列に新supply昇格 + B列クリア + 売り切れ解除 → 通常②(mercari --sheet ichibankuji)で再出品")
    print("   ※ 出品くんで『一番くじ』を走らせると、A列の新supplyで再出品されます")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "identify":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        pass_identify(n, cand_n=5)
    elif mode == "expand":
        pass_expand(cand_n=8)
    else:
        print("使い方:\n  python ichibankuji_restock.py identify [件数]   # パスA 画像特定\n"
              "  python ichibankuji_restock.py expand              # パスB 画像検索+確定")


if __name__ == "__main__":
    main()
