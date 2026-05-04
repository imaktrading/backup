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
# 廃盤専用 endpoint (disp_fo). Selenium 不要・plain requests で server-rendered HTML 取得可.
DISCONTINUED_URL_TEMPLATE = "https://webshop.montbell.jp/goods/disp_fo.php?product_id={pid}&force=1"


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
            # 廃盤 path 1: disp_fo.php (公式 廃盤 endpoint、plain requests で server-rendered)
            fo_html = _fetch_disp_fo(product_id)
            if fo_html:
                fo_url = DISCONTINUED_URL_TEMPLATE.format(pid=product_id)
                data = _parse_product(fo_html, None, product_id, fo_url)
                if data and (data.get("name_jp") or data.get("specs", {}).get("weight_g")):
                    _upsert_product(product_id, data, fo_url, source="official_disp_fo")
                    wg = data.get("specs", {}).get("weight_g") or "?"
                    print(f" [DISP_FO: {data.get('name_jp','?')[:30]} / {wg}g / "
                          f"{len(data.get('color_variants', []))} colors]")
                    return True
            # 廃盤 path 2: Wayback 最新 snapshot (disp_fo も miss の保険)
            wayback_html = _fetch_wayback(url)
            if wayback_html:
                data = _parse_product(wayback_html, None, product_id, url)
                if data and (data.get("name_jp") or data.get("specs", {}).get("weight_g")):
                    _upsert_product(product_id, data, url, source="wayback_machine")
                    wg = data.get("specs", {}).get("weight_g") or "?"
                    print(f" [WAYBACK: {data.get('name_jp','?')[:30]} / {wg}g / "
                          f"{len(data.get('color_variants', []))} colors]")
                    return True
            # 全 source miss → 最小情報 stub
            stub = _build_discontinued_stub(product_id, url)
            _upsert_product(product_id, stub, url, source="discontinued_stub")
            print(f" [STUB: discontinued (disp/disp_fo/Wayback ともに miss)]")
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
    """OpenGraph meta tag content を取り出し + HTML entity decode.

    disp_fo HTML は &#039; (= ') 等のエンティティを残したまま返すため、
    unescape しないと "Men&#039;s" のまま name_jp に格納されてしまう
    (department 判定の endswith("Men's") も失敗する).
    """
    import html as _html
    m = re.search(rf'<meta property="og:{key}" content="([^"]+)"', html)
    return _html.unescape(m.group(1)) if m else ""


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
            # 素材: 表地/裏地/中わた サブセクション
            found_sub = False
            for sub_tag in ("表地", "裏地", "中わた"):
                sub_m = re.search(rf"{sub_tag}\s*[:：]\s*([^\n]+?)(?=(?:表地|裏地|中わた|$))", body_clean)
                if sub_m:
                    result[sub_tag] = sub_m.group(1).strip().rstrip("、,")
                    found_sub = True
            # サブタグなし (シンプルな素材 1 行) → 全体を 表地 とみなす
            # (例: 廃盤 disp_fo の 1103242 ウインドブラスト等で発生)
            if not found_sub and body_clean:
                result["表地"] = body_clean
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
def _fetch_disp_fo(product_id: str, timeout: int = 15) -> Optional[str]:
    """廃盤専用 endpoint (disp_fo.php) から HTML を取得.

    特性:
      - Selenium 不要: server-rendered HTML が plain requests で取れる
      - URL: https://webshop.montbell.jp/goods/disp_fo.php?product_id=<pid>&force=1
      - spec block format は disp.php と同一 (【素材】【平均重量】等)

    返値:
      HTML (str) — 商品ページ内容を含む.
      None — 404 / 通信エラー / 商品ページでない (= 仕様 block 不在).
    """
    import requests  # type: ignore
    url = DISCONTINUED_URL_TEMPLATE.format(pid=product_id)
    try:
        r = requests.get(
            url, timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 Chrome/121.0 Safari/537.36",
                "Accept-Language": "ja-JP,ja;q=0.9",
            },
        )
        if r.status_code != 200 or len(r.text) < 5000:
            return None
    except Exception:
        return None
    # 商品ページ判定: 仕様 block が存在すること
    if "ttlType03" not in r.text or "仕様" not in r.text:
        return None
    # 商品名チェック (og:title が あって "Page Not Found" 系でない)
    if "Page Not Found" in r.text or "見つかりません" in r.text:
        return None
    return r.text


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
# 既存 records の disp_fo 補完 (backfill)
# ============================================================================
def _merge_specs(existing: dict, new_data: dict) -> dict:
    """既存 specs に disp_fo 由来の new_data を merge.

    方針:
      - 既存が "Not Specified" / 空 / null → new_data 優先
      - 既存が値あり → 既存優先 (PDF OCR の最初の値を維持)
      - features は UNION (重複排除した union list)
      - 例外: image_urls / color_variants は disp_fo 優先 (OCR で取れないため)
    """
    out = dict(existing)
    for k, v in new_data.items():
        if k in ("features",):
            # union with dedupe
            ex_list = existing.get(k) or []
            new_list = v or []
            merged = list(ex_list)
            for item in new_list:
                if item not in merged:
                    merged.append(item)
            out[k] = merged
        elif k in ("color_variants", "image_urls"):
            # disp_fo 優先 (OCR が空のことが多いため、disp_fo に値があれば採用)
            if v:
                out[k] = v
            elif k not in out or not out.get(k):
                out[k] = v
        else:
            ex = existing.get(k)
            if not ex or ex == "Not Specified":
                out[k] = v
            # 既存が真値なら触らない
    return out


def backfill_from_disp_fo(limit: Optional[int] = None,
                           rate_limit_seconds: float = 1.5,
                           skip_sources: tuple = ("official_disp_fo", "montbell_official")):
    """既存 montbell records を disp_fo で補完.

    対象: PDF OCR 由来の records (source=catalog_pdf_ocr_*).
    処理: disp_fo.php fetch → 成功なら spec/image を merge → upsert.
    既に disp_fo / active source の records は skip.

    Returns:
        {"updated": int, "miss": int, "skipped": int}
    """
    import sqlite3
    import json as _json
    import api  # type: ignore

    conn = sqlite3.connect(str(api._DB_PATH))
    cur = conn.cursor()
    cur.execute(
        "SELECT product_id, source, name, name_jp, specs, source_url "
        "FROM products WHERE category=? ORDER BY product_id",
        (CATEGORY,),
    )
    rows = cur.fetchall()
    conn.close()

    if limit:
        rows = rows[:limit]

    print(f"=== backfill_from_disp_fo: 対象 {len(rows)} records ===")
    updated = 0
    miss = 0
    skipped = 0

    for i, (pid, source, name, name_jp, specs_json, source_url) in enumerate(rows, 1):
        if source in skip_sources:
            skipped += 1
            continue

        print(f"  [{i}/{len(rows)}] {pid} ({source})...", end="", flush=True)
        fo_html = _fetch_disp_fo(pid)
        if not fo_html:
            print(" miss")
            miss += 1
            time.sleep(rate_limit_seconds)
            continue

        fo_url = DISCONTINUED_URL_TEMPLATE.format(pid=pid)
        new_data = _parse_product(fo_html, None, pid, fo_url)
        if not new_data:
            print(" parse-fail")
            miss += 1
            time.sleep(rate_limit_seconds)
            continue

        # merge: 既存 specs と new_data['specs'] を合成
        existing_specs = _json.loads(specs_json or "{}")
        new_specs_block = {
            **new_data.get("specs", {}),
            "color_variants": new_data.get("color_variants", []),
            "size_variants":  new_data.get("size_variants", []),
            "image_urls":     new_data.get("image_urls", []),
            "description_jp": new_data.get("description_jp", ""),
        }
        merged = _merge_specs(existing_specs, new_specs_block)
        merged["disp_fo_augmented"] = True

        # upsert (source は更新しない、source_url は disp_fo に切替)
        api.upsert(
            category=CATEGORY,
            product_id=pid,
            name=name or new_data.get("name_jp", ""),
            name_jp=name_jp or new_data.get("name_jp", ""),
            specs=merged,
            images=merged.get("image_urls", []),
            source=source,  # 既存 source を維持 (origin tracing 保持)
            source_url=fo_url,  # disp_fo の URL に更新 (latest source)
        )
        n_imgs = len(merged.get("image_urls", []))
        n_colors = len(merged.get("color_variants", []))
        print(f" → augmented ({n_imgs} imgs / {n_colors} colors)")
        updated += 1
        time.sleep(rate_limit_seconds)

    print(f"\n=== backfill 完了: updated={updated} miss={miss} skipped={skipped} ===")
    return {"updated": updated, "miss": miss, "skipped": skipped}


# ============================================================================
# webshop.montbell.jp category 一覧から active product_id を発掘 (2026-05-04)
# ============================================================================
# 2025+ はカタログ廃止 → web のみ存在. category.php?category=N が JS 描画
# のため Selenium 必須. ジャケット/ダウン系の category 番号は webshop top
# page から抽出 (cat 1=オールウエザー, 2=ウインドシェル, 3=ソフトシェル,
# 6=ベスト, 12=サーマル, 13=インシュレーション, 14=アルパイン,
# 65=フィールドウエア, 18=サイクル, 110=フィッシング).
JACKET_CATEGORIES = {
    1:   "オールウエザー (雨具)",
    2:   "ウインドシェル",
    3:   "ソフトシェル",
    6:   "ベスト",
    12:  "サーマル (フリース)",
    13:  "インシュレーション (ダウン/化繊綿)",
    14:  "アルパイン",
    65:  "フィールドウエア",
    18:  "サイクルウエア",
    110: "フィッシングウエア",
}
CATEGORY_URL_TEMPLATE = "https://webshop.montbell.jp/goods/category.php?category={cat}"


def discover_active_ids(category_id: int, driver=None,
                         page_pacing: float = 4.0,
                         max_pages_per_sublist: int = 20) -> list:
    """category 一覧ページから全 active product_id を発掘.

    URL chain (active 系):
      1. category.php?category=N         → サブカテゴリ hub. list.php への
                                            link が複数ある.
      2. list.php?category=NNNNN          → 商品リスト本体 (1 page = 50 件まで)
      3. list.php?category=NNNNN&page=K   → page=2,3,... で続き

    Args:
        category_id: webshop の category 番号 (例: 2 = ウインドシェル)
        driver: 既存 Selenium driver. None なら新規起動.
        page_pacing: page 間 sleep (rate limit 緩和).
        max_pages_per_sublist: 1 sublist あたり page 上限 (暴走防止).

    Returns:
        product_id (7 桁 string) の sorted list (全 sublist 統合・重複排除済).
    """
    from selenium.webdriver.common.by import By  # type: ignore

    own_driver = driver is None
    if own_driver:
        driver = _make_driver()
    try:
        # === Step 1: category.php → list.php sublist URLs ===
        hub_url = CATEGORY_URL_TEMPLATE.format(cat=category_id)
        driver.get(hub_url)
        time.sleep(5)
        sublist_urls: set = set()
        for a in driver.find_elements(By.CSS_SELECTOR, "a[href*='list.php']"):
            href = a.get_attribute("href") or ""
            if "list.php?category=" in href:
                # page= パラメータ等を剥がして base 化
                base = re.sub(r"&page=\d+", "", href)
                base = re.sub(r"#.*$", "", base)
                sublist_urls.add(base)

        # === Step 2-3: 各 list.php を pagination 込みで scrape ===
        all_ids: set = set()
        for list_url in sorted(sublist_urls):
            seen_in_sublist: set = set()
            page = 1
            while page <= max_pages_per_sublist:
                if page == 1:
                    paged_url = list_url
                else:
                    sep = "&" if "?" in list_url else "?"
                    paged_url = f"{list_url}{sep}page={page}"
                driver.get(paged_url)
                time.sleep(page_pacing)
                for _ in range(3):
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(1)
                html = driver.page_source
                page_ids = set(re.findall(r"product_id=(\d{7})", html))
                new_in_sublist = page_ids - seen_in_sublist
                if not new_in_sublist:
                    break  # 同じ ID しか出ない = 終端
                seen_in_sublist.update(page_ids)
                all_ids.update(page_ids)
                # 50 未満は最終 page (1 page=50 件設計)
                if len(page_ids) < 50:
                    break
                page += 1
        return sorted(all_ids)
    finally:
        if own_driver:
            try:
                driver.quit()
            except Exception:
                pass


def crawl_jacket_categories(category_ids: list = None, pacing_seconds: int = 5) -> dict:
    """ジャケット/ダウン系 category を全 crawl + 全 active product を upsert.

    Args:
        category_ids: 対象 category list. None なら JACKET_CATEGORIES 全部.
        pacing_seconds: product fetch 間 sleep (rate limit 緩和).

    Returns:
        {"discovered": {cat_id: [pid, ...]},
         "upserted":   {pid: True/False}}
    """
    if category_ids is None:
        category_ids = list(JACKET_CATEGORIES.keys())

    driver = _make_driver()
    discovered = {}
    upserted = {}
    try:
        # Phase A: 各 category から product_id を発掘
        all_ids = []
        for cat_id in category_ids:
            cat_name = JACKET_CATEGORIES.get(cat_id, f"category={cat_id}")
            print(f"\n=== Discover category={cat_id} ({cat_name}) ===")
            ids = discover_active_ids(cat_id, driver=driver)
            print(f"  → {len(ids)} active product_id 発見")
            discovered[cat_id] = ids
            for pid in ids:
                if pid not in all_ids:
                    all_ids.append(pid)
            time.sleep(2)
        print(f"\n=== 全 category 合計 distinct product_id: {len(all_ids)} ===")

        # Phase B: 既存 catalog に無い ID だけ update (既存は active なら回し直し不要)
        import api  # type: ignore
        targets = []
        for pid in all_ids:
            existing = api.lookup(CATEGORY, pid)
            if existing is None:
                targets.append(pid)
        print(f"=== うち未登録 = upsert 対象: {len(targets)} ===")

        # Phase C: 順次 update_one
        for i, pid in enumerate(targets, 1):
            print(f"  [{i}/{len(targets)}]", end=" ")
            ok = update_one(pid, driver=driver)
            upserted[pid] = ok
            time.sleep(pacing_seconds)
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    return {"discovered": discovered, "upserted": upserted}


# ============================================================================
# CLI
# ============================================================================
def _cli():
    args = sys.argv[1:]
    if not args:
        print("Usage:")
        print("  python iMakCatalog/scrapers/montbell.py 1106645")
        print("  python iMakCatalog/scrapers/montbell.py 1106645 1128635 1128648")
        print("  python iMakCatalog/scrapers/montbell.py --backfill        # 全 records disp_fo 補完")
        print("  python iMakCatalog/scrapers/montbell.py --backfill 10     # 先頭 10 records だけ smoke")
        print("  python iMakCatalog/scrapers/montbell.py --discover 2      # category=2 の active id 列挙")
        print("  python iMakCatalog/scrapers/montbell.py --crawl-jackets   # 全ジャケット category を crawl + upsert")
        print("  python iMakCatalog/scrapers/montbell.py --crawl 2,3,13    # 指定 category のみ crawl + upsert")
        sys.exit(1)

    if args[0] == "--backfill":
        lim = int(args[1]) if len(args) > 1 else None
        backfill_from_disp_fo(limit=lim)
        return

    if args[0] == "--discover":
        cat_id = int(args[1])
        ids = discover_active_ids(cat_id)
        print(f"\n=== category={cat_id}: {len(ids)} active product_id ===")
        for pid in ids:
            print(f"  {pid}")
        return

    if args[0] == "--crawl-jackets":
        result = crawl_jacket_categories()
        print(f"\n=== 完了 ===")
        for cat, ids in result["discovered"].items():
            print(f"  category={cat:>3d}: {len(ids):>3d} discovered")
        ok_n = sum(1 for v in result["upserted"].values() if v)
        print(f"  upserted: {ok_n}/{len(result['upserted'])}")
        return

    if args[0] == "--crawl":
        cat_ids = [int(s) for s in args[1].split(",")]
        result = crawl_jacket_categories(category_ids=cat_ids)
        print(f"\n=== 完了 ===")
        for cat, ids in result["discovered"].items():
            print(f"  category={cat:>3d}: {len(ids):>3d} discovered")
        ok_n = sum(1 for v in result["upserted"].values() if v)
        print(f"  upserted: {ok_n}/{len(result['upserted'])}")
        return

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
