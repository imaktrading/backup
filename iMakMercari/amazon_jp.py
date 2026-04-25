#!/usr/bin/env python3
"""Amazon.co.jp スペック取得モジュール（リール用）

公式DB(Daiwa)/Naturumで取得失敗時の最終フォールバック。
Amazon商品ページの「商品の説明」「仕様」セクションから抽出。
"""
import json
import re
import time
import urllib.parse
from pathlib import Path

from selenium.webdriver.common.by import By

CACHE_PATH = Path(__file__).parent / "data" / "amazon_jp_cache.json"
CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

AMAZON_SEARCH_URL = "https://www.amazon.co.jp/s?k={kw}"
AMAZON_PRODUCT_URL = "https://www.amazon.co.jp/dp/{asin}"
ASIN_RE = re.compile(r"/dp/([A-Z0-9]{10})")


def _normalize(s: str) -> str:
    if not s:
        return ""
    s = s.translate(str.maketrans({
        "Ａ":"A","Ｂ":"B","Ｃ":"C","Ｄ":"D","Ｅ":"E","Ｆ":"F","Ｇ":"G","Ｈ":"H","Ｉ":"I",
        "Ｊ":"J","Ｋ":"K","Ｌ":"L","Ｍ":"M","Ｎ":"N","Ｏ":"O","Ｐ":"P","Ｑ":"Q","Ｒ":"R",
        "Ｓ":"S","Ｔ":"T","Ｕ":"U","Ｖ":"V","Ｗ":"W","Ｘ":"X","Ｙ":"Y","Ｚ":"Z",
        "０":"0","１":"1","２":"2","３":"3","４":"4","５":"5","６":"6","７":"7","８":"8","９":"9",
        "－":"-","　":" ",
    }))
    return s.replace(" ", "").upper()


def _load_cache():
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache):
    try:
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def search_amazon(driver, keyword: str, max_results: int = 5) -> list:
    """Amazon検索→ASIN一覧返す"""
    url = AMAZON_SEARCH_URL.format(kw=urllib.parse.quote(keyword))
    driver.get(url)
    time.sleep(6)
    src = driver.page_source
    asins = []
    seen = set()
    for m in ASIN_RE.finditer(src):
        asin = m.group(1)
        if asin not in seen:
            seen.add(asin)
            asins.append(asin)
        if len(asins) >= max_results:
            break
    return asins


def parse_amazon_specs(body_text: str) -> dict:
    """Amazon商品ページbodyから仕様抽出"""
    out = {
        "weight_g": "",
        "gear_ratio": "",
        "max_drag_kg": "",
        "line_capacity_nylon": "",
        "line_capacity_pe": "",
        "ball_bearings": "",
        "line_per_turn_cm": "",
        "handle_arm_mm": "",
    }
    patterns = [
        ("weight_g",            r"自重[\s（(]*g[\s）)]*[:：]\s*([\d.]+)"),
        ("gear_ratio",          r"ギア比[\s]*[:：]\s*([\d.:]+)"),
        ("max_drag_kg",         r"最大ドラグ力?[\s（(]*kg[\s）)]*[:：]\s*([\d.]+)"),
        ("line_capacity_nylon", r"糸巻量\s*ナイロン[\s（(]*lb[\-－]m[\s）)]*[:：]\s*([0-9\-－、,，\.\s]+?)(?:糸巻|ベアリング|最大巻|ハンドル|スプール|フロロ|PE|$)"),
        ("line_capacity_pe",    r"糸巻量\s*PE[\s（(]*号[\-－]m[\s）)]*[:：]\s*([0-9\-－、,，\.\s]+?)(?:糸巻|ベアリング|最大巻|ハンドル|商品|$)"),
        ("ball_bearings",       r"ベアリング数?\s*BB[／/]ローラー[\s]*[:：]\s*([\d]+\s*[／/]\s*[\d]+)"),
        ("line_per_turn_cm",    r"最大巻上長?[\s（(]*cm[／/][^)）]*[\s）)]*[:：]\s*([\d]+)"),
        ("handle_arm_mm",       r"ハンドル長[\s（(]*mm[\s）)]*[:：]\s*([\d]+)"),
    ]
    for key, pat in patterns:
        m = re.search(pat, body_text)
        if m:
            v = m.group(1).strip()
            v = re.sub(r'\s+', '', v)
            out[key] = v
    if out["ball_bearings"]:
        out["ball_bearings"] = out["ball_bearings"].replace("／", "+").replace("/", "+")
    gr = out["gear_ratio"]
    if gr and ":" not in gr:
        out["gear_ratio"] = f"{gr}:1"
    return out


def fetch_reel_specs(driver, model_name: str) -> dict:
    """モデル名から Amazon 経由でリールスペック取得"""
    cache = _load_cache()
    cache_key = _normalize(model_name)
    if cache_key in cache:
        return cache[cache_key]

    # 検索キーワード（メルカリ店名等のノイズ除去）
    cleaned = re.sub(r"加古川店】|中古|【|】|\|", " ", model_name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    print(f"  [Amazon] 検索: {cleaned}")

    try:
        asins = search_amazon(driver, cleaned, max_results=5)
        print(f"  [Amazon] ヒット: {len(asins)}件")
    except Exception as e:
        print(f"  [Amazon] 検索失敗: {e}")
        return {}

    target_norm = _normalize(model_name)
    type_match = re.search(r"(\d{3,4}[A-Z]+|C\d{4}[A-Z]+|FC?LT\d+[A-Z\-]*|TW\s*\d+[A-Z]*)", target_norm)
    type_keyword = type_match.group(1).replace(" ", "") if type_match else ""

    for asin in asins:
        try:
            url = AMAZON_PRODUCT_URL.format(asin=asin)
            driver.get(url)
            time.sleep(6)
            try:
                page_title = driver.find_element(By.ID, "productTitle").text.strip()
            except Exception:
                page_title = driver.title.strip()
            page_norm = _normalize(page_title)

            # 型番マッチ確認
            if type_keyword and type_keyword not in page_norm:
                continue

            body = driver.find_element(By.TAG_NAME, "body").text
            specs = parse_amazon_specs(body)
            if any(specs.values()):
                specs["source_url"] = url
                specs["matched_item"] = page_title
                specs["match_quality"] = "amazon"
                cache[cache_key] = specs
                _save_cache(cache)
                print(f"  [Amazon] ✓ 取得: {page_title[:50]}")
                return specs
        except Exception as e:
            print(f"    ASIN {asin}: {e}")
            continue

    print(f"  [Amazon] 該当なし")
    return {}


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    import undetected_chromedriver as uc
    opts = uc.ChromeOptions()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--headless=new")
    drv = uc.Chrome(options=opts, version_main=146)
    try:
        for model in ["ダイワ 24 バスX 100H", "ダイワ 21 タトゥーラTW 300XHL"]:
            print(f"\n=== {model} ===")
            r = fetch_reel_specs(drv, model)
            for k, v in r.items():
                print(f"  {k}: {v}")
    finally:
        drv.quit()
