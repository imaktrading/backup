#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""③ RESTOCK PSA の再仕入れ可否を判定 (メルカリ価格の技を借用)。

技の借用元:
  - メルカリ検索→価格抽出: iMakMercari/mercari_scout.scrape_search_results と同手法
    (ただし共有 profile は触らず、別 profile で公開検索のみ = profile lock 事故回避)
  - V8計算: iMakeBayAPI/pricing_engine.compute_listing_price (category=TCG(PSA10))

入力: デスクトップの 03_PSA再仕入れ候補_*.csv (set_no / ebay_price / title)
      ※ 手動CSVが無ければ最新 funnel_*.csv の RESTOCK∩PSA10 行から自動生成 (set_noはtitleから抽出)
出力: 同ディレクトリに ..._メルカリ判定.csv + コンソール要約

判定: 同カードPSA10 の最安(メルカリ on_sale) を仕入れ原価とし、V8推奨eBay価格 <= 現eBay価格 なら
      「再仕入れGO」(畳むはずの死蔵を救出可)。
"""
import csv
import datetime
import glob
import os
import re
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMakeBayAPI")))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DESK = r"C:\Users\imax2\OneDrive\デスクトップ"
FUNNEL_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "funnel_output"))
CATEGORY = "TCG(PSA10)"
SETNO_RE = re.compile(r"\b([A-Z]{2,3}\d{2}-\d{2,3}|P-\d{2,3}|SB\d{2}-\d{2,3}|#\d{3}/[A-Z0-9]+|#\d{2,3})\b")


def search_keyword(title, set_no):
    sn = set_no.strip() if set_no else ""
    if not sn:
        m = SETNO_RE.search(title)
        sn = m.group(1) if m else ""
    return ("PSA10 " + sn).strip() if sn else ""


def is_psa10(name):
    n = name.replace(" ", "").upper()
    if any(b in n for b in ("PSA9", "PSA8", "PSA7", "BGS", "ARS")):
        return False
    # 「PSA10相当」= 未鑑定の同等品 (生カード)。本物のPSA10 slabではないので除外
    # (2026-06-09 ユーザー指摘: 相当は除外)。原文の 相当 で判定 (upper非影響)。
    if "相当" in name:
        return False
    return "PSA10" in n


def _card_tokens(card_no):
    """カード番号を英数トークン列に分解 ('OP11-106'→['OP11','106'] / 'P-041'→['P','041'])。"""
    return [t for t in re.split(r"[^A-Za-z0-9]", (card_no or "").upper()) if t]


def _name_matches_card(name, card_no):
    """商品名が対象カード番号を『トークン連続一致』で含むか (id-strict, fail-closed)。

    番号をハイフン区切りでトークン化し、商品名のトークン列に連続部分列として現れるか判定。
    単純な部分文字列照合だと promo の短い番号 'P-041' が遊戯王 'FOTB-JP041'(=JP041) 等に
    誤マッチする (2026-06-09 実機: P-041 検索が遊戯王スラブ¥23,100を拾った)。トークン連続
    一致なら 'P','041' が分離して並ぶ正規表記のみ拾い、'JP041'(1トークン) を弾く。

    SNKRDUNK 側 (parse_search_for_card) と同じ fail-closed 思想。番号が無ければ採用しない。
    """
    parts = _card_tokens(card_no)
    if not parts:
        return False
    tokens = [t for t in re.split(r"[^A-Za-z0-9]", (name or "").upper()) if t]
    m = len(parts)
    for i in range(len(tokens) - m + 1):
        if tokens[i:i + m] == parts:
            return True
    return False


def _ebay_item_id(url):
    """eBay URL から item id を抽出 ('.../itm/358596483319' → '358596483319')。"""
    mt = re.search(r"/itm/(\d+)", url or "")
    return mt.group(1) if mt else ""


def _extract_card_no(title, set_no):
    """set_no か title からカード番号を取り出す (ハイフン保持, 例 'OP11-106' / 'P-041')。"""
    sn = (set_no or "").strip()
    if not sn:
        mt = SETNO_RE.search(title or "")
        sn = mt.group(1) if mt else ""
    return sn


def name_jp_for_card(card_no, _cache={}):
    """カタログ(共有DB)から card_no の日本語カード名を引く (無ければ None)。

    検索語に日本語名を足すと番号だけの曖昧検索より精度が上がる (promo の他カード誤マッチ低減)。
    カテゴリは番号書式から一意でないので主要TCGを順に試す。lookup は ID完全一致のみ (fail-closed)。
    """
    if not card_no:
        return None
    if card_no in _cache:
        return _cache[card_no]
    nj = None
    try:
        if r"C:/dev/iMak" not in sys.path:
            sys.path.insert(0, r"C:/dev/iMak")
        from iMakCatalog import api
        for cat in ("one_piece_tcg", "pokemon_tcg", "dragonball_scg", "gundam_tcg"):
            try:
                rec = api.lookup(cat, card_no)
            except Exception:
                rec = None
            if rec and rec.get("name_jp"):
                nj = rec["name_jp"]
                break
    except Exception:
        nj = None
    _cache[card_no] = nj
    return nj


def card_meta_for_key(key, _cache={}, _db=r"C:/dev/iMak_data/catalog/products.sqlite"):
    """canonical product_id(固有KEY) → {name_jp, image, set, get_info, variant_type, rarity, hint}。

    Step6 P2/P3: KEY が指す**その1枚の変種**の識別属性を catalog 共有DB から厳密引き。
    変種の text 識別子は set_name 列だけでなく **specs.get_info(入手元セット) / variant_type(alt_art等)
    / rarity** に在る(_p1 と _p2 は set_name=None でも get_info=神速の拳 vs EGGHEAD で区別可)。
    hint = これらを束ねた照合トークン source(メルカリ/SNKRDUNK 両チャネルで variant pin に使う=画像不要)。
    KEY 無 / catalog 未収録 → None (呼出側は bare fallback)。
    """
    if not key:
        return None
    if key in _cache:
        return _cache[key]
    import json
    import sqlite3
    out = None
    try:
        con = sqlite3.connect(_db)
        r = con.execute(
            "SELECT name_jp, images, set_name, specs FROM products WHERE product_id=?", (key,)
        ).fetchone()
        con.close()
        if r:
            try:
                imgs = json.loads(r[1]) if r[1] else []
            except Exception:
                imgs = []
            imgs = sorted(imgs, key=lambda u: (0 if ("OP-JA" in u or "onepiece-cardgame" in u or "JP" in u) else 1))
            sp = {}
            try:
                sp = json.loads(r[3]) if r[3] else {}
            except Exception:
                sp = {}
            get_info = (sp.get("get_info") or "").strip()         # 入手元set(日本語) → メルカリ用
            set_name_ebay = (sp.get("set_name_ebay") or "").strip()  # set名(英語) → SNKRDUNK用
            variant_type = (sp.get("variant_type") or "").strip()
            rarity = (sp.get("rarity") or "").strip()
            out = {
                "name_jp": r[0], "image": imgs[0] if imgs else "", "set": r[2] or "",
                "get_info": get_info, "set_name_ebay": set_name_ebay,
                "variant_type": variant_type, "rarity": rarity,
                # hint = 変種識別トークン source。set名は **日本語(get_info)とブー英語(set_name_ebay)両方**
                # 入れる: メルカリ=JP名 / SNKRDUNK=EN名 と marketplace で言語が違うため(E2Eで判明)。
                # set列がNoneでも get_info/set_name_ebay が入手元セットを持つ → 両 marketplace と突合可。
                # key(suffix _p1 等)は marketplace に出ず部分一致雑音になるため hint に入れない。
                "hint": [r[2] or "", get_info, set_name_ebay, variant_type, rarity, r[0] or ""],
            }
    except Exception:
        out = None
    _cache[key] = out
    return out


def build_card_query(title, set_no, key=None):
    """1カード分の検索情報を作る → {kw, card_no, name_jp, key, image}。

    Step6 P2: canonical KEY があれば catalog 厳密引きの name_jp + 変種画像を使う(bare曖昧回避)。
    kw = 'PSA10 <name_jp> <card_no>'。card_no は照合用、image は P3 画像pin用。
    key 無 / catalog 未収録 → 従来の bare card_no 経路に fallback (後方互換)。
    """
    card_no = _extract_card_no(title, set_no)
    meta = card_meta_for_key(key) if key else None
    nj = (meta.get("name_jp") if meta else None) or name_jp_for_card(card_no)
    image = meta.get("image") if meta else ""
    hint = meta.get("hint") if meta else []
    if not card_no:
        return {"kw": "", "card_no": "", "name_jp": nj, "key": key or "", "image": image or "", "hint": hint}
    kw = f"PSA10 {nj} {card_no}" if nj else f"PSA10 {card_no}"
    return {"kw": kw, "card_no": card_no, "name_jp": nj, "key": key or "", "image": image or "", "hint": hint}


def build_input_from_funnel():
    """手動CSVが無いとき、最新 funnel_*.csv の RESTOCK∩PSA10 から入力CSVを生成。

    funnel 列(title/price/ebay_url) を 03_PSA再仕入れ候補_<日付>.csv (set_no空/ebay_price/title/ebay_url)
    に落とす。set_no は title から SETNO_RE で後段が自動抽出する。生成パスを返す(無ければ None)。
    """
    ffiles = glob.glob(os.path.join(FUNNEL_DIR, "funnel_*.csv"))
    if not ffiles:
        return None
    fsrc = max(ffiles, key=os.path.getmtime)
    frows = list(csv.DictReader(open(fsrc, encoding="utf-8")))
    cands = [r for r in frows
             if "RESTOCK" in (r.get("flags") or "").split("|") and is_psa10(r.get("title", ""))]
    if not cands:
        return None
    out = os.path.join(DESK, f"03_PSA再仕入れ候補_{datetime.date.today():%Y%m%d}.csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["set_no", "ebay_price", "title", "ebay_url"])
        w.writeheader()
        for r in cands:
            w.writerow({"set_no": "", "ebay_price": r.get("price", ""),
                        "title": r.get("title", ""), "ebay_url": r.get("ebay_url", "")})
    print(f"手動CSVが無いため funnel から自動生成: {os.path.basename(out)} "
          f"(RESTOCK∩PSA10 = {len(cands)}枚, 元: {os.path.basename(fsrc)})", flush=True)
    return out


def _chrome_major():
    """インストール済 Chrome のメジャー版を取得 (失敗時 None = uc自動検出に委ねる)。

    uc.Chrome の自動検出が driver 版を取り違える事故 (2026-06-09: driver149 vs Chrome148)
    を防ぐため、レジストリ BLBeacon から実機の Chrome 版を読んで version_main に渡す。
    """
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                k = winreg.OpenKey(hive, r"Software\Google\Chrome\BLBeacon")
                v, _ = winreg.QueryValueEx(k, "version")
                winreg.CloseKey(k)
                return int(str(v).split(".")[0])
            except OSError:
                continue
    except Exception:
        pass
    return None


# 通常出品のみ採用 (個人=MERCARI / メルカリShops=BEYOND)。不明 itemtype は除外 (fail-closed)。
_ALLOWED_ITEM_TYPES = ("ITEM_TYPE_MERCARI", "ITEM_TYPE_BEYOND")
# オークション item の cell内マーカー。itemtype は auction でも ITEM_TYPE_MERCARI のため
# 判別不可 (2026-06-09 実機: EB02-015 のオークションが itemtype=MERCARI で混入)。
# これらは rendered auction cell のみに出現 (i18n JSON は item-cell ブロック外なので汚染なし、
# 実機4ダンプで cell内出現=実auctionのみ・現在価格/残り時間は全体でも1回確認済)。
_AUCTION_MARKERS = ("オークション", "入札", "現在価格", "残り時間")


def parse_mercari_items(src):
    """検索結果HTMLを item-cell 単位で {type,name,price,href} に分解する純関数。

    各 item-cell ブロック内の itemtype / aria-label('<名前>の画像 <価格>円') / href を
    同一ブロックから取るので name·price·href が必ず対応する
    (旧実装は names/prices/urls を別々の findall で取得→添字ズレで別カードの価格を拾う事故源。
     2026-06-09 ユーザー指摘『2行目が違うカード』の構造的原因)。

    通常出品のみ返す。①itemtype が _ALLOWED_ITEM_TYPES 以外を除外 ②cell内に _AUCTION_MARKERS が
    あればオークションとして除外 (2026-06-09 ユーザー指摘『オークションは確定価格でなく仕入不可』)。
    返り値は DOM順 (=価格昇順)。
    """
    items = []
    for b in re.split(r'data-testid="item-cell"', src)[1:]:
        it = re.search(r'itemtype="([A-Z_]+)"', b)
        if not it or it.group(1) not in _ALLOWED_ITEM_TYPES:
            continue
        if any(mk in b for mk in _AUCTION_MARKERS):   # オークション cell を除外
            continue
        al = re.search(r'aria-label="(.+?)の画像\s*([\d,]+)円"', b)
        if not al:
            continue
        hr = re.search(r'href="(/(?:item/m\w+|shops/product/\w+))"', b)
        items.append({
            "type": it.group(1),
            "name": al.group(1).strip(),
            "price": int(al.group(2).replace(",", "")),
            "href": f"https://jp.mercari.com{hr.group(1)}" if hr else "",
        })
    return items


def pick_cheapest_psa10(items, card_no, variant_hint=None):
    """価格昇順 items から PSA10 かつ対象カード番号一致の最安を選ぶ (純関数)。

    Step6 P3: variant_hint(canonical変種の get_info=入手元set 等)があれば、番号一致の中で
    hint(セット名/コード)に一致する**正変種**に絞ってから最安。SNKRDUNK と同じ思想・画像不要。
    - hint一致あり → その最安 (正変種)
    - hint一致無し + 候補単一 → 採用 (変種曖昧なし。seller がset未記載なだけ)
    - hint一致無し + 候補複数 → None (誤variant買わない fail-closed)
    - hint無 (KEY未解決) → 従来どおり番号一致の最安
    """
    matches = [it for it in items  # DOM順 = 価格昇順
               if it["price"] > 0 and is_psa10(it["name"]) and _name_matches_card(it["name"], card_no)]
    if not matches:
        return None

    def _ret(it):
        return (it["price"], it["href"], it["name"])
    if not variant_hint:
        return _ret(matches[0])
    from snkrdunk_psa_resource import _hint_tokens, _print_signal, _item_print
    toks = _hint_tokens(variant_hint)
    if not toks:
        return _ret(matches[0])           # hint からトークン取れず → 従来最安
    # ①set トークン採点で最高スコア群(=正set)に絞る → ②同setで複数なら print種別で tie-break → 最安。
    scored = [(sum(1 for t in toks if t in (it["name"] or "").upper().replace(" ", "").replace("-", "")), it)
              for it in matches]   # matches は価格昇順を保持
    top = max(s for s, _ in scored)
    if top == 0:
        return _ret(matches[0]) if len(matches) == 1 else None   # 決め手無+複数 → fail-closed
    topgroup = [it for s, it in scored if s == top]              # 価格昇順保持
    if len(topgroup) == 1:
        return _ret(topgroup[0])                                 # set で一意 → その最安
    target = _print_signal(variant_hint)
    matched = [it for it in topgroup if _item_print(it["name"]) == target]
    if matched:
        return _ret(matched[0])           # 正 print種別の最安 (価格昇順保持)
    return None                           # 同set・print でも一意化できず → fail-closed


def parse_image_search_results(src):
    """画像検索モーダル(image-grid)の結果を [{price,sold,href}] に分解する純関数。

    モーダル結果は商品名を持たない (サムネ＋価格のみ)。番号照合は別途 item ページを開いて行う。
    各 result anchor は data-location='image_search:similar_looks_modal:item_thumbnail'、
    aria-label='[売り切れ ]<価格>円'、href=/item/m… or /shops/product/… (2026-06-09 実機確認)。
    """
    out = []
    for a in re.split(r'data-location="image_search:similar_looks_modal:item_thumbnail"', src)[1:]:
        seg = a[:600]
        hr = re.search(r'href="(/(?:item/m\w+|shops/product/\w+))"', seg)
        al = re.search(r'aria-label="(売り切れ\s*)?([\d,]+)円"', seg)
        if hr and al:
            out.append({"href": "https://jp.mercari.com" + hr.group(1),
                        "sold": bool(al.group(1)),
                        "price": int(al.group(2).replace(",", ""))})
    return out


def image_search_fallback(drv, ebay_item_id, card_no, max_open=12):
    """キーワードで0件のとき、自社eBay出品のPSAスラブ画像でメルカリ画像検索 → 番号+PSA10検証 → 最安。

    画像検索は『似ている商品』(視覚類似)なので別カード/別ジャンルのスラブも混ざる。結果に名前が
    無いため、販売中候補を価格昇順で開き og:title で番号(token連続一致)+PSA10 を検証、最初に通った
    =最安を返す (2026-06-09 POCで EB02-015 を ¥14,500 で正しく取得・キーワード版と一致を確認)。
    返り値 (price, url, name) or None。
    """
    if not ebay_item_id or not card_no:
        return None
    try:
        from ebay_getitem_images import fetch_listing_images
    except Exception:
        return None
    pics = fetch_listing_images(ebay_item_id)
    if not pics:
        return None
    import requests
    img_path = os.path.join(os.environ.get("TEMP", "."), f"slab_{ebay_item_id}.jpg")
    try:
        ir = requests.get(pics[0], timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        with open(img_path, "wb") as f:
            f.write(ir.content)
    except Exception:
        return None
    from selenium.webdriver.common.by import By
    try:
        drv.get("https://jp.mercari.com/search?keyword=%20"); time.sleep(7)
        btn = drv.find_elements(By.CSS_SELECTOR, '[data-testid="image-search-button"]')
        if not btn:
            return None
        btn[0].click(); time.sleep(2)
        fin = drv.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
        if not fin:
            return None
        fin[0].send_keys(img_path); time.sleep(11)
        res = parse_image_search_results(drv.page_source)
    except Exception:
        return None
    onsale = sorted([r for r in res if not r["sold"]], key=lambda x: x["price"])
    for r in onsale[:max_open]:
        try:
            drv.get(r["href"]); time.sleep(4)
            ps = drv.page_source
            # オークション除外: 詳細ページの bid-button(=入札) で判別 (通常は checkout-button)。
            # テキスト(入札する/現在価格)は i18n にも入り使えず、ボタンの testid が確実な鑑別子
            # (2026-06-09 実機: auction=bid-button / normal=checkout-button)。
            if 'data-testid="bid-button"' in ps or 'data-testid="checkout-button"' not in ps:
                continue
            mt = re.search(r'<meta property="og:title" content="([^"]+)"', ps)
            title = mt.group(1) if mt else ""
            if is_psa10(title) and _name_matches_card(title, card_no):
                return (r["price"], r["href"], title)
        except Exception:
            continue
    return None


def fetch_mercari_cheapest(cards):
    """各カードの メルカリ on_sale 最安(PSA10) を取得 → {idx: (price, url, name)}。

    cards: [{"kw":検索語, "card_no":照合番号, "ebay_item_id":フォールバック用}] のリスト。
    キーワード検索で0件なら、ebay_item_id があれば画像検索フォールバックを試す。
    """
    import undetected_chromedriver as uc
    opts = uc.ChromeOptions()
    opts.add_argument("--headless=new"); opts.add_argument("--no-sandbox")
    opts.add_argument("--lang=ja-JP"); opts.add_argument("--window-size=1280,1400")
    _maj = _chrome_major()
    drv = uc.Chrome(options=opts, version_main=_maj) if _maj else uc.Chrome(options=opts)
    out = {}
    try:
        drv.set_page_load_timeout(50)
        for i, c in enumerate(cards):
            kw = c.get("kw"); card_no = c.get("card_no"); eid = c.get("ebay_item_id")
            if not kw:
                out[i] = None
                print(f"  [{i+1}/{len(cards)}] (検索語なし) skip", flush=True)
                continue
            url = "https://jp.mercari.com/search?keyword=" + urllib.parse.quote(kw) + "&status=on_sale&order=asc&sort=price"
            try:
                drv.get(url); time.sleep(8)
                # item-cell 単位で抽出 (name·price·href 対応保証 + 通常出品のみ=オークション除外)
                best = pick_cheapest_psa10(parse_mercari_items(drv.page_source), card_no, c.get("hint"))
                via = "kw"
                if best is None and eid:           # キーワード0件→画像検索フォールバック
                    best = image_search_fallback(drv, eid, card_no)
                    via = "画像検索" if best else "kw"
                out[i] = best
                tag = f"¥{best[0]} ({via})" if best else "PSA10在庫なし"
                print(f"  [{i+1}/{len(cards)}] {card_no or kw}: {tag}", flush=True)
            except Exception as e:
                out[i] = None
                print(f"  [{i+1}/{len(cards)}] {card_no or kw}: ERR {str(e)[:30]}", flush=True)
    finally:
        try:
            drv.quit()
        except Exception:
            pass
    return out


def main():
    import pricing_engine

    # キャッシュ: 当日中に既に判定結果があれば再スクレイプしない (連打=数分スクレイプ→BANリスク回避)。
    # 価格再取得したいときは --force を付けて実行。
    done = glob.glob(os.path.join(DESK, "03_PSA再仕入れ候補_*_メルカリ判定.csv"))
    if done and "--force" not in sys.argv:
        latest = max(done, key=os.path.getmtime)
        if datetime.date.fromtimestamp(os.path.getmtime(latest)) == datetime.date.today():
            print(f"当日の判定結果が既にあります（再スクレイプしません）: {os.path.basename(latest)}")
            print("価格を取り直す場合は --force を付けて実行してください。")
            return  # returncode 0 → 既存の判定CSVが自動で開く

    files = [p for p in glob.glob(os.path.join(DESK, "03_PSA再仕入れ候補_*.csv"))
             if "_メルカリ判定" not in os.path.basename(p)]
    if files:
        src = max(files, key=os.path.getmtime)
    else:
        src = build_input_from_funnel()
        if not src:
            sys.exit("03_PSA再仕入れ候補_*.csv が無く、funnel_*.csv にも RESTOCK∩PSA10 がありません。"
                     "先に『ファネル分析』を実行してください。")
    rows = list(csv.DictReader(open(src, encoding="utf-8-sig")))
    cards = [{**build_card_query(r.get("title", ""), r.get("set_no", "")),
              "ebay_item_id": _ebay_item_id(r.get("ebay_url", ""))} for r in rows]
    print(f"対象: {src}\nPSA {len(rows)}枚 のメルカリ最安(PSA10)を取得中 (name_jp検索+画像検索フォールバック)...", flush=True)
    found = fetch_mercari_cheapest(cards)

    results = []
    for i, r in enumerate(rows):
        cur = float(r["ebay_price"]) if r.get("ebay_price") else 0
        best = found.get(i)
        rec = judge = murl = None
        cost = best[0] if best else None
        if cost and cur:
            calc = pricing_engine.compute_listing_price(cost_jpy=cost, median_usd=cur, category=CATEGORY)
            rec = calc["price"]
            judge = "再仕入れGO" if rec <= cur else "原価高(再仕入れ不可)"
            murl = best[1]
        elif cur and best is None:
            judge = "メルカリにPSA10在庫なし"
        else:
            judge = "取得失敗"
        results.append({"set_no": r.get("set_no") or search_keyword(r.get("title", ""), "").replace("PSA10 ", ""),
                        "ebay_now_usd": cur, "mercari_jpy": cost, "v8_recommended_usd": rec,
                        "判定": judge, "mercari_url": murl, "ebay_url": r.get("ebay_url"), "title": r.get("title")})

    # スプシ「PSA再仕入れ」タブに集約 (デスクトップCSV廃止 2026-06-07。再仕入れ系をシートに統一)
    if results:
        header = list(results[0].keys())
        rows2d = [header] + [[r.get(k, "") for k in header] for r in results]
        try:
            from sheet_io import write_rows_to_tab, MAINT_URL
            write_rows_to_tab("PSA再仕入れ", rows2d)
            print(f"🃏 「PSA再仕入れ」タブ更新: {len(results)}件 → {MAINT_URL}")
        except Exception as _e:
            print(f"⚠ 「PSA再仕入れ」タブ更新失敗: {type(_e).__name__}: {_e}")

    go = [x for x in results if x["判定"] == "再仕入れGO"]
    nost = [x for x in results if x["判定"] == "メルカリにPSA10在庫なし"]
    high = [x for x in results if x["判定"].startswith("原価高")]
    print(f"\n=== ③ メルカリ再仕入れ判定 ({len(rows)}枚) ===")
    print(f"  再仕入れGO(救出可・黒字): {len(go)}件")
    print(f"  原価高(再仕入れ不可): {len(high)}件")
    print(f"  メルカリPSA10在庫なし: {len(nost)}件")
    print(f"\n再仕入れGO 上位(eBay価格高い順):")
    for x in sorted(go, key=lambda v: -v["ebay_now_usd"])[:12]:
        print(f"  {x['set_no']:<12} メルカリ¥{x['mercari_jpy']} → eBay現${x['ebay_now_usd']:.0f} (V8推奨${x['v8_recommended_usd']:.0f})")
    # 出力はスプシ「PSA再仕入れ」タブ (上で更新済)


if __name__ == "__main__":
    main()
