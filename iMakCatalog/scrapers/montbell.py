"""Montbell catalog scraper - webshop.montbell.jp/goods/disp.php?product_id=<7桁> を fetch.

設計原則 (Phase 4 / 2026-05-03):
  - **新規スクレイピング実装は spec table parser のみ**
  - 既存 iMakMercari/montbell_outlet_scraper.py の Selenium 起動 / URL pattern を参考に流用
  - 既存 iMakMercari/montbell_whitelist.py の eBay 正規値辞書を 2nd-stage 正規化に再利用
  - JP→EN 1st-stage は本ファイルに辞書 (素材/機能/用途/原産国/色 suffix)
  - 既存スクリプト (montbell_outlet_scraper / montbell_listing) は **触らない** (現状運用維持)

データ source:
  webshop.montbell.jp/goods/disp.php?product_id=<7桁> (Selenium 必須、SPA で JS 描画)

CASIO Akamai のような重防御は未確認。要観察 (Phase 4 smoke で検証).

実行:
  python iMakCatalog/scrapers/montbell.py 1106645              # 単独 product
  python iMakCatalog/scrapers/montbell.py 1106645 1128635 ...  # 複数 product
"""
from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# ============================================================================
# sys.path (api / whitelist 参照)
# ============================================================================
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CATALOG_ROOT = Path(__file__).resolve().parent.parent
_MERCARI_DIR = _REPO_ROOT / "iMakMercari"

for p in (_CATALOG_ROOT, _MERCARI_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

CATEGORY = "montbell"
SOURCE = "montbell_official"
PRODUCT_URL_TEMPLATE = "https://webshop.montbell.jp/goods/disp.php?product_id={pid}"


# ============================================================================
# JP → EN 1st-stage 辞書 (生 JP → 英語キーワード)
# ============================================================================
# 素材
_MATERIAL_JP_EN = {
    "ナイロン": "Nylon",
    "ポリエステル": "Polyester",
    "コットン": "Cotton",
    "ウール": "Wool",
    "ポリウレタン": "Polyurethane",
    "ポリアミド": "Polyamide",
    "綿": "Cotton",
    "羊毛": "Wool",
    "ダウン": "Down",
    "シンサレート": "Synthetic",
    "プリマロフト": "Synthetic",
    "クリマプラス": "Polyester",  # モンベル独自フリース素材
    "ストレッチ": "Polyester",     # 多くは Polyester ベース
    "メッシュ": "Polyester",
}

# 機能 (eBay Features フィルタ正規値へ)
_FEATURE_JP_EN = {
    "撥水": "Water Resistant",
    "はっ水": "Water Resistant",
    "防水": "Waterproof",
    "防風": "Windproof",
    "軽量": "Lightweight",
    "ストレッチ": "Stretch",
    "保温": "Insulated",
    "通気": "Breathable",
    "吸汗": "Moisture Wicking",
    "速乾": "Quick Dry",
    "フード付": "Hooded",
    "フード": "Hooded",
    "リフレクター": "Reflective",
    "反射": "Reflective",
    "ジッパー": "Full Zip",
    "ポケット": "Pockets",
    "パッカブル": "Packable",
    "テープシーム": "Taped Seams",
    "防寒": "Thermal",
}

# 用途 (whitelist Performance/Activity に流す)
_ACTIVITY_JP_EN = {
    "ハイキング": "Hiking",
    "トレッキング": "Hiking",
    "登山": "Hiking",
    "アウトドア": "Hiking",
    "キャンプ": "Hiking",
    "クライミング": "Hiking",
    "サイクリング": "Cycling",
    "自転車": "Cycling",
    "スキー": "Skiing",
    "スノーボード": "Skiing",
    "ランニング": "Running & Jogging",
    "走る": "Running & Jogging",
    "ウォーキング": "Walking",
    "釣り": "Hunting",
    "フィッシング": "Hunting",
}

# 原産国
_COUNTRY_JP_EN = {
    "日本": "Japan",
    "中国": "China",
    "ベトナム": "Vietnam",
    "ミャンマー": "Myanmar / Burma",
    "バングラデシュ": "Bangladesh",
    "インドネシア": "Indonesia",
    "タイ": "Thailand",
    "韓国": "South Korea (Republic of Korea)",
    "台湾": "Not Specified",  # 台湾は eBay フィルタにない
}

# 色 suffix → eBay 正規値 (Color フィルタ).
# モンベル型番末尾 (-XX) の suffix code → eBay Color.
_COLOR_SUFFIX_EN = {
    "BK":   "Black",
    "WT":   "White",
    "NV":   "Blue",
    "BL":   "Blue",
    "RD":   "Red",
    "OR":   "Orange",
    "YL":   "Yellow",
    "PK":   "Pink",
    "PL":   "Purple",
    "GY":   "Gray",
    "GR":   "Green",
    "OV":   "Green",
    "BKOV": "Green",
    "DGN":  "Green",
    "DKOV": "Green",
    "GRBL": "Multicolor",
    "BR":   "Brown",
    "BG":   "Beige",
    "TN":   "Beige",
    "KH":   "Green",
    "SV":   "Silver",
    "GLD":  "Gold",
    "IV":   "Ivory",
    "DKFO": "Green",  # DARK FOREST 系
}

# 色 JP 名 → EN (色プルダウンの日本語表記から、suffix が無い場合の fallback)
_COLOR_JP_EN = {
    "ブラック": "Black",
    "ホワイト": "White",
    "ネイビー": "Blue",
    "ブルー": "Blue",
    "レッド": "Red",
    "オレンジ": "Orange",
    "イエロー": "Yellow",
    "ピンク": "Pink",
    "パープル": "Purple",
    "グレー": "Gray",
    "グリーン": "Green",
    "オリーブ": "Green",
    "カーキ": "Green",
    "ダークグリーン": "Green",
    "ブラウン": "Brown",
    "ベージュ": "Beige",
    "シルバー": "Silver",
    "ゴールド": "Gold",
    "アイボリー": "Ivory",
}


# ============================================================================
# Selenium driver (Chrome 147 明示)
# ============================================================================
def _make_driver():
    """undetected_chromedriver 起動.

    Chrome 147 に合わせた version_main 明示で chromedriver mismatch 回避.
    既存 montbell_outlet_scraper._make_driver と同じ起動オプション.
    """
    import undetected_chromedriver as uc  # type: ignore
    opts = uc.ChromeOptions()
    opts.add_argument("--lang=ja-JP")
    opts.add_argument("--window-size=1400,900")
    return uc.Chrome(options=opts, version_main=147)


# ============================================================================
# 公開 API
# ============================================================================
def update_one(product_id: str, driver=None) -> bool:
    """1 product を fetch + parse + upsert. driver は使い回し可.

    廃盤対応 (2026-05-03 追加):
      official 404 時は (1) Wayback Machine 最新 snapshot 試行 →
      (2) 最小情報 stub の順でフォールバック.
      → 中古主体運用で廃盤も catalog に登録する.

    Returns:
        True (成功 = data あり upsert 済), False (parse 失敗 / 完全 miss)
    """
    own_driver = driver is None
    if own_driver:
        driver = _make_driver()
    try:
        url = PRODUCT_URL_TEMPLATE.format(pid=product_id)
        print(f"  {product_id}...", end="", flush=True)
        driver.get(url)
        time.sleep(7)
        # 遅延ロード発火
        for _ in range(3):
            driver.execute_script("window.scrollBy(0, 800)")
            time.sleep(1.2)

        title = driver.title or ""
        if "Page Not Found" in title or "見つかりません" in title:
            # 廃盤 path: Wayback 最新 snapshot 試行
            wayback_html = _fetch_wayback(url)
            if wayback_html:
                data = _parse_product(wayback_html, None, product_id, url)
                if data and (data.get("name_jp") or data.get("specs", {}).get("weight_g")):
                    _upsert_product(product_id, data, url, source="wayback_machine")
                    wg = data.get("specs", {}).get("weight_g") or "?"
                    print(f" [WAYBACK: {data.get('name_jp','?')[:30]} / {wg}g / "
                          f"{len(data.get('color_variants', []))} colors]")
                    return True
            # Wayback も miss → 最小情報 stub
            stub = _build_discontinued_stub(product_id, url)
            _upsert_product(product_id, stub, url, source="discontinued_stub")
            print(f" [STUB: discontinued (公式・Wayback ともに miss)]")
            return True

        html = driver.page_source
        data = _parse_product(html, driver, product_id, url)
        if not data:
            print(" [parse failed]")
            return False

        _upsert_product(product_id, data, url, source=SOURCE)
        wg = data.get("specs", {}).get("weight_g") or "?"
        print(f" [{data.get('name_jp','?')[:30]} / {wg}g / "
              f"{len(data.get('color_variants', []))} colors]")
        return True
    finally:
        if own_driver:
            try:
                driver.quit()
            except Exception:
                pass


def update_many(product_ids: list, pacing_seconds: int = 5) -> dict:
    """複数 product を順次 upsert. driver は使い回し.

    Returns:
        {"success": [...], "failed": [...]}
    """
    driver = _make_driver()
    result = {"success": [], "failed": []}
    try:
        for pid in product_ids:
            if update_one(pid, driver=driver):
                result["success"].append(pid)
            else:
                result["failed"].append(pid)
            time.sleep(pacing_seconds)
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    return result


# ============================================================================
# product page parser
# ============================================================================
def _parse_product(html: str, driver, product_id: str, url: str) -> Optional[dict]:
    """商品詳細ページから catalog records を組立.

    Returns:
        dict (specs / color_variants / size_variants / image_urls 等) or None.
    """
    # OpenGraph metadata (確実な情報源).
    og_title = _og(html, "title")
    og_desc = _og(html, "description")
    og_image = _og(html, "image")

    # 商品名: og:title が "【モンベル】XXX" 形式、prefix 剥がし
    name_jp_full = (og_title or "").replace("【モンベル】", "").strip()
    if not name_jp_full:
        # fallback: driver.title
        t = driver.title.replace("モンベル", "").replace("｜", "").replace("オンラインストア", "").strip()
        name_jp_full = t

    # Department: 末尾の Men's / Women's
    department = "Unisex Adults"
    if name_jp_full.endswith("Men's"):
        department = "Men"
        name_jp = name_jp_full[:-len("Men's")].strip()
    elif name_jp_full.endswith("Women's"):
        department = "Women"
        name_jp = name_jp_full[:-len("Women's")].strip()
    else:
        name_jp = name_jp_full

    # スペック block: <h4 class="ttlType03">仕様</h4> 直後の <p> ブロック内 全 【...】 を抽出
    spec_data = _parse_spec_block(html)

    # カラー / サイズ (HTML 主、driver は active 経路 fallback 用)
    color_variants = _parse_color_variants(html, driver=driver)
    size_variants = _parse_size_variants(html, driver=driver)

    # 価格 (¥XX,XXX)
    prices = re.findall(r"¥([\d,]+)", html)
    retail_jpy = ""
    if prices:
        try:
            retail_jpy = str(int(prices[0].replace(",", "")))
        except ValueError:
            pass

    # 画像 URL
    image_urls = _collect_image_urls(html, og_image, product_id)

    # 用途 (description + name から推定)
    activity = _derive_activity(name_jp + " " + (og_desc or ""))
    # 機能 (spec 機能 + 特長)
    features = _derive_features(spec_data, html)
    # type / style (商品名から推定)
    type_, style = _derive_type_and_style(name_jp)
    # 素材 mapping
    outer_shell = _translate_first_match(spec_data.get("表地", ""), _MATERIAL_JP_EN, "Not Specified")
    lining = _translate_first_match(spec_data.get("裏地", ""), _MATERIAL_JP_EN, "Not Specified")
    insulation = _translate_first_match(spec_data.get("中わた", ""), _MATERIAL_JP_EN, "Not Specified")
    # fabric_type (商品名・素材ベース、Fleece か Softshell か)
    fabric_type = _derive_fabric_type(name_jp, spec_data)
    # 原産国 (公式ページにない場合多い → Not Specified)
    country = _translate_first_match(spec_data.get("原産国", ""), _COUNTRY_JP_EN, "Not Specified")
    # 重量 (整数 g)
    weight_g = _parse_weight_g(spec_data.get("平均重量", "") or spec_data.get("重量", ""))
    # 取扱い (洗濯マークから machine washable 推定)
    care = _derive_care(html)

    return {
        "product_id": product_id,
        "name_jp": name_jp,
        "name_en": "",  # 英訳辞書未対応、後で人手追加 (Phase 5+)
        "description_jp": og_desc or "",
        "url": url,
        "specs": {
            # 素材系
            "outer_shell_material": outer_shell,
            "lining_material": lining,
            "insulation_material": insulation,
            "fabric_type": fabric_type,
            # 機能・用途
            "features": features,
            "performance_activity": activity,
            "garment_care": care,
            "jacket_coat_length": _derive_length(name_jp),
            # 基本属性
            "type": type_,
            "style": style,
            "department": department,
            "country_of_origin": country,
            # 副情報
            "weight_g": weight_g,
            "retail_price_jpy": retail_jpy,
            # 固定値
            "brand": "montbell",
            "size_type": "Regular",
            "theme": "Outdoor",
            "fit": "Regular",
            "accents": "Logo",
            "vintage": "No",
            "handmade": "No",
            "pattern": "Solid",
        },
        "color_variants": color_variants,
        "size_variants": size_variants,
        "image_urls": image_urls,
    }


def _og(html: str, key: str) -> str:
    """OpenGraph meta tag content を取り出し."""
    m = re.search(rf'<meta property="og:{key}" content="([^"]+)"', html)
    return m.group(1) if m else ""


def _parse_spec_block(html: str) -> dict:
    """<h4 class="ttlType03">仕様</h4> 直後の <p> 内の 【...】 セクションを dict 化.

    例: 【素材】表地:ナイロン<br>裏地:ポリエステル → {"表地": "ナイロン", "裏地": "ポリエステル"}
    例: 【平均重量】303g → {"平均重量": "303g"}
    """
    result: dict = {}
    # 仕様 block を抽出
    m = re.search(
        r'<h4[^>]*>仕様</h4>\s*(?:<[^>]+>\s*)*<p[^>]*>(.+?)</p>',
        html, re.DOTALL,
    )
    spec_section = m.group(1) if m else html  # fallback: 全体

    # 【...】 タグ区切り
    sections = re.findall(r"【([^】]+)】([^【]+)", spec_section)
    for tag, body in sections:
        # body 内の HTML タグ除去
        body_clean = re.sub(r"<[^>]+>", " ", body)
        body_clean = re.sub(r"\s+", " ", body_clean).strip()
        if tag == "素材":
            # 素材は 表地/裏地/中わた サブセクション
            for sub_tag in ("表地", "裏地", "中わた"):
                sub_m = re.search(rf"{sub_tag}\s*[:：]\s*([^\n]+?)(?=(?:表地|裏地|中わた|$))", body_clean)
                if sub_m:
                    result[sub_tag] = sub_m.group(1).strip().rstrip("、,")
        else:
            result[tag] = body_clean
    return result


def _parse_color_variants(html: str, driver=None) -> list:
    """カラーバリエーションを取得 (HTML 主、driver は fallback).

    Wayback snapshot は driver なしで HTML のみ → HTML 直接パースを優先.
    HTML から input[name='all_color'] / 【カラー】... を抽出.
    """
    suffix_list = []
    # HTML から input[name='all_color'] の value を直接 regex 抽出
    m_inp = re.search(
        r'<input[^>]+name=[\'"]all_color[\'"][^>]+value=[\'"]([^\'"]+)[\'"]',
        html,
    )
    if m_inp:
        suffix_list = [s for s in m_inp.group(1).split(",") if s]

    # HTML regex で取れなかった場合のみ driver fallback
    if not suffix_list and driver is not None:
        try:
            from selenium.webdriver.common.by import By
            el = driver.find_element(By.CSS_SELECTOR, "input[name='all_color']")
            raw = (el.get_attribute("value") or "").strip()
            suffix_list = [s for s in raw.split(",") if s]
        except Exception:
            pass

    # 【カラー】xxx(BK)、yyy(NV) パターンから JP 名抽出
    jp_map = {}
    m = re.search(r"【カラー】([^【\n<]+)", re.sub(r"<[^>]+>", " ", html))
    if m:
        for jp_name, suffix in re.findall(r"([^()、]+)\(([A-Z0-9]+)\)", m.group(1)):
            jp_map[suffix.strip()] = jp_name.strip()

    out = []
    for sx in suffix_list:
        jp = jp_map.get(sx, "")
        en = _COLOR_SUFFIX_EN.get(sx)
        if not en and jp:
            for jp_key, en_val in _COLOR_JP_EN.items():
                if jp_key in jp:
                    en = en_val
                    break
        out.append({"suffix": sx, "jp": jp, "en": en or "Not Specified"})
    return out


def _parse_size_variants(html: str, driver=None) -> list:
    """サイズバリエーション (HTML 主、driver は fallback)."""
    sizes = []
    seen = set()
    # HTML から select[name='XX_YY_num'] パターンを regex 抽出
    for m in re.finditer(
        r'<select[^>]+name=[\'"]([A-Z0-9]+)_[A-Z0-9]+_num[\'"]', html
    ):
        sz = m.group(1)
        if sz not in seen:
            seen.add(sz)
            sizes.append(sz)
    # HTML 抽出 ゼロかつ driver あれば fallback
    if not sizes and driver is not None:
        try:
            from selenium.webdriver.common.by import By
            for sel_el in driver.find_elements(By.CSS_SELECTOR, "select[name$='_num']"):
                name = sel_el.get_attribute("name") or ""
                mm = re.match(r"^([A-Z0-9]+)_([A-Z0-9]+)_num$", name)
                if mm:
                    sz = mm.group(1)
                    if sz not in seen:
                        seen.add(sz)
                        sizes.append(sz)
        except Exception:
            pass
    return sizes


def _collect_image_urls(html: str, og_image: str, product_id: str) -> list:
    """商品画像 URL 収集. og:image + 公式画像パターン (prod_l, prod_c)."""
    urls = []
    if og_image:
        urls.append(og_image)
    # 公式画像 URL パターン (prod_l_<id>_<n>.jpg, prod_c_<id>_<n>.jpg)
    for m in re.finditer(rf"https?://[^\"']+prod_[a-z]_{product_id}_?\d*\.jpg", html):
        u = m.group(0)
        if u not in urls:
            urls.append(u)
    # 重複排除 + 上限
    return list(dict.fromkeys(urls))[:10]


def _parse_weight_g(text: str) -> str:
    """重量 string ('303g' / '303グラム' 等) → 整数 string ('303')."""
    if not text:
        return ""
    m = re.search(r"(\d+)\s*[gｇ]", text)
    return m.group(1) if m else ""


# ============================================================================
# 推論ヘルパー (商品名・description ベース)
# ============================================================================
def _translate_first_match(text: str, jp_en_dict: dict, default: str) -> str:
    """text 内に jp_en_dict の key が含まれていれば最初に hit した EN 値を返す."""
    if not text:
        return default
    for jp, en in jp_en_dict.items():
        if jp in text:
            return en
    return default


def _derive_activity(text: str) -> str:
    """商品名・description から performance_activity を推定."""
    if not text:
        return "Not Specified"
    for jp, en in _ACTIVITY_JP_EN.items():
        if jp in text:
            return en
    return "Hiking"  # アウトドア商品の default


def _derive_features(spec_data: dict, html: str) -> list:
    """spec 機能 + 特長 + 商品説明から features list を組立 (whitelist Features 値)."""
    features = []
    # 機能 + 特長 sections
    body = (spec_data.get("機能", "") + " " +
            spec_data.get("特長", "") + " " +
            spec_data.get("特徴", ""))
    for jp, en in _FEATURE_JP_EN.items():
        if jp in body and en not in features:
            features.append(en)
    return features or ["Lightweight"]  # default


def _derive_type_and_style(name_jp: str) -> tuple:
    """商品名から (type, style) を推定 (whitelist Type / Style 値)."""
    n = name_jp
    # Type
    if any(k in n for k in ("ベスト", "Vest")):
        type_ = "Vest"
    elif any(k in n for k in ("コート", "Coat")):
        type_ = "Coat"
    else:
        type_ = "Jacket"  # default for outerwear

    # Style
    style = "Not Specified"
    if "ウインドブレーカー" in n or "ウインド" in n:
        style = "Windbreaker"
    elif "パーカ" in n or "パーカー" in n or "Parka" in n:
        style = "Parka"
    elif "アノラック" in n or "Anorak" in n:
        style = "Anorak"
    elif "ダウン" in n or "Down" in n:
        style = "Puffer Jacket"
    elif "レイン" in n or "Rain" in n or "ストームクルーザー" in n:
        style = "Rain Coat"
    elif "シェル" in n or "Shell" in n:
        style = "Windbreaker"
    return type_, style


def _derive_length(name_jp: str) -> str:
    """商品名から jacket_coat_length を推定."""
    if any(k in name_jp for k in ("ロング", "Long", "ベンチコート")):
        return "Long"
    if any(k in name_jp for k in ("ショート", "Short", "クロップド")):
        return "Short"
    return "Mid-Length"  # アウター系 default


def _derive_fabric_type(name_jp: str, spec_data: dict) -> str:
    """商品名・素材から fabric_type を推定."""
    if any(k in name_jp for k in ("フリース", "Fleece", "クリマエア", "シャミース", "Chameece")):
        return "Fleece"
    if "ソフトシェル" in name_jp or "Soft Shell" in name_jp:
        return "Softshell"
    return "Not Specified"


def _derive_care(html: str) -> str:
    """洗濯マーク・テキストから garment_care 推定."""
    if "洗濯機" in html:
        return "Machine Washable"
    if "手洗い" in html or "ドライ" in html:
        return "Hand Wash"
    return "Not Specified"


# ============================================================================
# 廃盤対応: Wayback Machine fallback + 最小情報 stub (2026-05-03 追加)
# ============================================================================
def _fetch_wayback(original_url: str, timeout: int = 15) -> Optional[str]:
    """Wayback Machine 最新 snapshot の HTML を取得.

    取得経路:
      1. Availability API (https://archive.org/wayback/available?url=...)
         で closest snapshot URL を取得
      2. snapshot URL を fetch (HTML 全体)

    返値:
      snapshot HTML (str) or None (snapshot 不在 / 通信エラー).
    """
    import requests  # type: ignore
    try:
        api_url = f"https://archive.org/wayback/available?url={original_url}"
        r = requests.get(api_url, timeout=timeout,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return None
        snapshot = ((r.json() or {}).get("archived_snapshots") or {}).get("closest", {})
        if not snapshot or not snapshot.get("url") or not snapshot.get("available"):
            return None
        snapshot_url = snapshot["url"]
    except Exception:
        return None
    try:
        r2 = requests.get(snapshot_url, timeout=timeout,
                          headers={"User-Agent": "Mozilla/5.0"})
        if r2.status_code != 200:
            return None
        return r2.text
    except Exception:
        return None


def _build_discontinued_stub(product_id: str, url: str) -> dict:
    """公式・Wayback ともに miss の廃盤 product に最小情報 stub を組立.

    catalog に「廃盤として登録あり」の record を残し、後で人手 augment 可能にする.
    name_jp は不明なので空、specs はほぼ Not Specified.
    """
    return {
        "product_id": product_id,
        "name_jp": "",
        "name_en": "",
        "description_jp": "",
        "url": url,
        "specs": {
            "outer_shell_material": "Not Specified",
            "lining_material": "Not Specified",
            "insulation_material": "Not Specified",
            "fabric_type": "Not Specified",
            "features": [],
            "performance_activity": "Not Specified",
            "garment_care": "Not Specified",
            "jacket_coat_length": "Not Specified",
            "type": "Jacket",
            "style": "Not Specified",
            "department": "Not Specified",
            "country_of_origin": "Not Specified",
            "weight_g": "",
            "retail_price_jpy": "",
            "brand": "montbell",
            "size_type": "Regular",
            "theme": "Outdoor",
            "fit": "Regular",
            "accents": "Logo",
            "vintage": "No",
            "handmade": "No",
            "pattern": "Solid",
            "discontinued": True,
        },
        "color_variants": [],
        "size_variants": [],
        "image_urls": [],
    }


# ============================================================================
# DB upsert
# ============================================================================
def _upsert_product(product_id: str, data: dict, url: str, source: str = SOURCE):
    """products テーブルへ upsert. source は active=montbell_official /
    廃盤=wayback_machine / discontinued_stub を区別."""
    import api  # type: ignore
    api.upsert(
        category=CATEGORY,
        product_id=product_id,
        name=data.get("name_jp", ""),
        name_jp=data.get("name_jp", ""),
        specs={
            **data.get("specs", {}),
            "color_variants":   data.get("color_variants", []),
            "size_variants":    data.get("size_variants", []),
            "image_urls":       data.get("image_urls", []),
            "description_jp":   data.get("description_jp", ""),
        },
        images=data.get("image_urls", []),
        source=source,
        source_url=url,
    )


# ============================================================================
# CLI
# ============================================================================
def _cli():
    args = sys.argv[1:]
    if not args:
        print("Usage:")
        print("  python iMakCatalog/scrapers/montbell.py 1106645")
        print("  python iMakCatalog/scrapers/montbell.py 1106645 1128635 1128648")
        sys.exit(1)
    if len(args) == 1:
        ok = update_one(args[0])
        sys.exit(0 if ok else 1)
    else:
        result = update_many(args)
        print(f"\n=== 完了: {len(result['success'])} success / {len(result['failed'])} failed ===")
        if result["failed"]:
            print(f"  failed: {', '.join(result['failed'])}")


if __name__ == "__main__":
    _cli()
