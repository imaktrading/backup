#!/usr/bin/env python3
"""Daiwa Japan 公式リールスペック取得モジュール

- gr-search.com 経由で Daiwa.com を検索（モデル名キーワード）
- 商品ページの仕様表からアイテム別スペックを取得
- ローカル JSON キャッシュで重複アクセスを回避
- bandai_jp.py と同じく既存 driver と共有可能

仕様表カラム:
  アイテム / 標準自重(g) / 巻き取り長さ(cm/H1回) / ギア比 / ナイロン(lb-m) /
  PE(号-m) / ハンドルアーム長(mm) / ベアリング(B/R) / 最大ドラグ力(kg) /
  ハンドルノブ交換サイズ / ハンドルノブ仕様 / 価格 / JAN

使用例:
  from daiwa_jp import fetch_reel_specs
  specs = fetch_reel_specs(driver, "21 Caldia FCLT2500S")
  # specs = {"weight_g": 195, "gear_ratio": "5.1:1", "max_drag_kg": "5",
  #          "ball_bearings": "6+1", "line_capacity_pe": "0.6-200", ...}
"""
import json
import os
import re
import time
import urllib.parse
from pathlib import Path

from selenium.webdriver.common.by import By

CACHE_PATH = Path(__file__).parent / "data" / "daiwa_jp_cache.json"
CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

DAIWA_SEARCH_URL = "https://www.gr-search.com/?kw={kw}&env=globe_r2&temp=daiwa&ie=u"
DAIWA_PRODUCT_RE = re.compile(r"https://www\.daiwa\.com/jp/product/[a-z0-9]{4,12}")

# 全角→半角変換（Daiwa スペック表はアイテム名が全角）
ZEN_TO_HAN = str.maketrans({
    "Ａ":"A","Ｂ":"B","Ｃ":"C","Ｄ":"D","Ｅ":"E","Ｆ":"F","Ｇ":"G","Ｈ":"H","Ｉ":"I",
    "Ｊ":"J","Ｋ":"K","Ｌ":"L","Ｍ":"M","Ｎ":"N","Ｏ":"O","Ｐ":"P","Ｑ":"Q","Ｒ":"R",
    "Ｓ":"S","Ｔ":"T","Ｕ":"U","Ｖ":"V","Ｗ":"W","Ｘ":"X","Ｙ":"Y","Ｚ":"Z",
    "０":"0","１":"1","２":"2","３":"3","４":"4","５":"5","６":"6","７":"7","８":"8","９":"9",
    "－":"-","　":" ",
})


def _normalize(s: str) -> str:
    """モデル名比較用に正規化: 全角→半角、空白除去、大文字化"""
    if not s:
        return ""
    return s.translate(ZEN_TO_HAN).replace(" ", "").upper()


def _is_valid_cached_specs(specs, cache_key):
    """キャッシュspecsが信頼できるか検証。matched_item に target type_keyword 含まれるか。
    含まれない → 別商品の specs（汚染データ）→ False。
    """
    if not specs:
        return False
    matched = _normalize(specs.get("matched_item", ""))
    target = cache_key
    type_patterns = [
        r"(FC?\s*LT\d+[A-Z\-]*)",
        r"(LT\d+[A-Z\-]*)",
        r"(TW\s*\d+[A-Z]*)",
        r"(SV\s*TW\s*[\d.]+[A-Z]*)",
        r"(\d{3,4}[A-Z]+)",
        r"([A-Z]{2,4}\d{2,4}[A-Z]*)",
    ]
    target_type = None
    for pat in type_patterns:
        m = re.search(pat, target)
        if m:
            target_type = m.group(1).replace(" ", "")
            break
    if not target_type:
        return False
    matched_type = None
    for pat in type_patterns:
        m = re.search(pat, matched)
        if m:
            matched_type = m.group(1).replace(" ", "")
            break
    if not matched_type:
        return False
    if matched_type != target_type:
        return False
    return True


def _load_cache():
    """キャッシュロード時に汚染データ（matched_item型番不一致）を自動破棄"""
    if not CACHE_PATH.exists():
        return {}
    try:
        raw = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    cleaned = {}
    purged = 0
    for k, v in raw.items():
        if _is_valid_cached_specs(v, k):
            cleaned[k] = v
        else:
            purged += 1
    if purged > 0:
        print(f"  [Daiwa(cache)] 汚染データ {purged}件 自動破棄（matched_item型番不一致）")
        try:
            CACHE_PATH.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    return cleaned


def _load_cache_OLD_REMOVED():
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


def search_daiwa(driver, keyword: str, max_results: int = 5) -> list:
    """gr-search.com で Daiwa を検索→商品ページURL一覧返す"""
    url = DAIWA_SEARCH_URL.format(kw=urllib.parse.quote(keyword))
    driver.get(url)
    time.sleep(10)
    src = driver.page_source
    urls = list(set(DAIWA_PRODUCT_RE.findall(src)))
    return urls[:max_results]


def fetch_product_specs(driver, product_url: str) -> dict:
    """Daiwa 商品ページから仕様表取得→{model_name: spec_dict} 返す"""
    driver.get(product_url)
    time.sleep(8)
    tables = driver.find_elements(By.TAG_NAME, "table")
    if len(tables) < 2:
        return {}

    # 仕様表は通常 Table 1 または最後のテーブル
    spec_table = tables[-1]
    rows = spec_table.find_elements(By.TAG_NAME, "tr")
    if not rows:
        return {}

    # ヘッダー行
    header_cells = rows[0].find_elements(By.TAG_NAME, "th")
    if not header_cells:
        header_cells = rows[0].find_elements(By.TAG_NAME, "td")
    headers = [c.text.strip() for c in header_cells]
    if not headers or "アイテム" not in headers[0]:
        return {}

    result = {}
    for row in rows[1:]:
        # th(アイテム名) と td(スペック値) 両方取得
        cells = row.find_elements(By.CSS_SELECTOR, "th, td")
        if len(cells) < 2:
            continue
        values = [c.text.strip() for c in cells]
        item_name = values[0]
        spec = {}
        for i, h in enumerate(headers[1:], start=1):
            if i < len(values):
                spec[h] = values[i]
        if item_name:
            result[item_name] = spec
    return result


def parse_spec(raw_spec: dict) -> dict:
    """生スペック dict を eBay Item Specifics 形式に変換"""
    out = {
        "weight_g": "",
        "line_per_turn_cm": "",
        "gear_ratio": "",
        "line_capacity_nylon": "",
        "line_capacity_pe": "",
        "handle_arm_mm": "",
        "ball_bearings": "",
        "max_drag_kg": "",
        "jan": "",
        # country はDaiwa公式表に記載なし。空欄にして Claude/Mercari description に判断委譲
    }
    for k, v in raw_spec.items():
        if not v:
            continue
        if "自重" in k:
            out["weight_g"] = v
        elif "巻き取り長さ" in k:
            out["line_per_turn_cm"] = v
        elif "ギア比" in k:
            out["gear_ratio"] = v if ":" in v else f"{v}:1"
        elif "ナイロン" in k:
            out["line_capacity_nylon"] = v
        elif "PE" in k or "ＰＥ" in k:
            out["line_capacity_pe"] = v
        elif "ハンドルアーム" in k:
            out["handle_arm_mm"] = v
        elif "ベアリング" in k:
            # "6/1" or "6+1" 形式に
            out["ball_bearings"] = v.replace("/", "+")
        elif "最大ドラグ" in k or "ドラグ力" in k:
            out["max_drag_kg"] = v
        elif "JAN" in k:
            out["jan"] = v
    return out


def fetch_reel_specs(driver, model_name: str) -> dict:
    """モデル名（Mercariタイトル等）から Daiwa公式スペックを取得

    Args:
      driver: Selenium driver (uc.Chrome 推奨)
      model_name: 例 "21 Caldia FCLT2500S" / "DAIWA TATULA SV TW 8.1L"

    Returns:
      {weight_g, gear_ratio, ball_bearings, ..., country, source_url, matched_item}
      取得失敗時は空dict
    """
    cache = _load_cache()
    cache_key = _normalize(model_name)
    if cache_key in cache:
        return cache[cache_key]

    # 既知 Daiwa シリーズキーワード（日本語/英語両対応、検索ヒット率高い順）
    KNOWN_SERIES = [
        ("カルディア", ["カルディア", "CALDIA"]),
        ("タトゥーラ", ["タトゥーラ", "TATULA"]),
        ("バスX",     ["バスX", "BASX", "BAS X"]),
        ("スティーズ", ["スティーズ", "STEEZ"]),
        ("イグジスト", ["イグジスト", "EXIST"]),
        ("エアリティ", ["エアリティ", "AIRITY"]),
        ("セルテート", ["セルテート", "CERTATE"]),
        ("フリームス", ["フリームス", "FREAMS"]),
        ("レグザ",     ["レグザ", "REGZA"]),
        ("レガリス",   ["レガリス", "LEGALIS"]),
        ("エメラルダス", ["エメラルダス", "EMERALDAS"]),
        ("ソルティガ", ["ソルティガ", "SALTIGA"]),
        ("BG",         ["BG"]),
        ("ジリオン",   ["ジリオン", "ZILLION"]),
        ("月下美人",   ["月下美人", "GEKKABIJIN"]),
        ("ヴァデル",   ["ヴァデル", "VADEL"]),
        ("ブラスト",   ["ブラスト", "BLAST"]),
        # Amazon型タイトル対応で追加
        ("ジョイナス", ["ジョイナス", "JOINUS"]),
        ("PR100",      ["PR100", "21PR100"]),
        ("LIGHT SW X IC", ["LIGHT SW X IC", "ライトSW", "LIGHT SW"]),
        ("プリード",   ["プリード", "PRIDE"]),
        ("プレッソ",   ["プレッソ", "PRESSO"]),
        ("クレスト",   ["クレスト", "CREST"]),
        ("リーガル",   ["リーガル", "REGAL"]),
        ("ファンタジスタ", ["ファンタジスタ", "FANTASISTA"]),
        ("シーボーグ", ["シーボーグ", "SEABORG"]),
        ("リョウガ",   ["リョウガ", "RYOGA"]),
        ("アルファス", ["アルファス", "ALPHAS"]),
        ("シルバークリーク", ["シルバークリーク", "SILVER CREEK"]),
    ]
    # タイトル全体から既知シリーズ名を検索（位置を問わない）
    title_upper = model_name.upper()
    series_kw = None
    for jp_kw, aliases in KNOWN_SERIES:
        for alias in aliases:
            if alias.upper() in title_upper:
                series_kw = jp_kw
                break
        if series_kw:
            break

    if not series_kw:
        # フォールバック: 旧ロジック（DAIWAプレフィックス除去 + 最初の英単語）
        cleaned = re.sub(r"^(DAIWA|ダイワ)\s*", "", model_name, flags=re.IGNORECASE)
        cleaned = re.sub(r"^\d{2}\s*", "", cleaned)
        series_match = re.match(r"([A-Za-z]+)", cleaned)
        series_kw = series_match.group(1) if series_match else cleaned[:10]

    print(f"  [Daiwa] 検索キーワード: {series_kw}")
    try:
        product_urls = search_daiwa(driver, series_kw, max_results=5)
        print(f"  [Daiwa] 検索結果: {len(product_urls)}件")
    except Exception as e:
        print(f"  [Daiwa] 検索失敗: {e}")
        return {}

    target_norm = _normalize(model_name)
    # 型番抽出（複数パターン）
    # FCLT2500S, FC LT2500S, LT2500S, 100H, 8.1L, TW300XHL, C2000SHG, PR100 など
    type_patterns = [
        r"(FC?\s*LT\d+[A-Z\-]*)",       # FCLT2500S, FC LT2500S
        r"(LT\d+[A-Z\-]*)",              # LT2500S
        r"(TW\s*\d+[A-Z]*)",             # TW 300XHL
        r"(SV\s*TW\s*[\d.]+[A-Z]*)",     # SV TW 8.1L
        r"(\d{3,4}[A-Z]+)",              # 100H, 300XHL, 4000XG
        r"([A-Z]{2,4}\d{2,4}[A-Z]*)",   # PR100, AB300, BG3000H 英字prefix+数字
    ]

    def _extract_type(text):
        """ページ/タイトルから型番抽出（同じパターン使用）"""
        for pat in type_patterns:
            m = re.search(pat, text)
            if m:
                return m.group(1).replace(" ", "")
        return None

    type_keyword = _extract_type(target_norm)
    if not type_keyword:
        print(f"  [Daiwa] 型番抽出失敗 from: {model_name}")
        # 安全装置: type_keyword 取れない時は specs採用全面禁止（誤マッチで他商品の specs を取らないため）
        print(f"  [Daiwa] → specs取得スキップ（推測しないルール準拠、空dict返却）")
        return {}

    target_year_match = re.match(r"(\d{2})", target_norm)
    target_year = target_year_match.group(1) if target_year_match else None

    best_partial = None
    for url in product_urls:
        try:
            print(f"  [Daiwa] スペック取得: {url}")
            specs_dict = fetch_product_specs(driver, url)
        except Exception as e:
            print(f"    取得失敗: {e}")
            continue
        if not specs_dict:
            continue
        print(f"    アイテム数: {len(specs_dict)}")
        # デバッグ: 最初の3件のアイテム名（生 + 正規化後）を表示
        for ix, (k, _) in enumerate(specs_dict.items()):
            if ix >= 3: break
            print(f"      raw: {k!r}  → norm: {_normalize(k)!r}")
        print(f"    target_norm: {target_norm!r}  type_keyword: {type_keyword!r}")

        for item_name, raw_spec in specs_dict.items():
            item_norm = _normalize(item_name)
            # 型番厳格チェック: page側からも抽出して完全一致のみ採用
            item_type = _extract_type(item_norm)
            if type_keyword and item_type:
                if item_type != type_keyword:
                    if item_type.startswith(type_keyword) or type_keyword.startswith(item_type):
                        print(f"    ⚠️ 型番近似スキップ: target='{type_keyword}' vs item='{item_type}'")
                    continue
            elif type_keyword and type_keyword not in item_norm:
                # フォールバック: 抽出失敗時は従来の含有チェック
                continue
            if type_keyword:
                # 年式チェック
                item_year_match = re.match(r"(\d{2})", item_norm)
                if target_year and item_year_match and item_year_match.group(1) == target_year:
                    # 完全一致（年+型番）
                    result = parse_spec(raw_spec)
                    result["source_url"] = url
                    result["matched_item"] = item_name
                    result["match_quality"] = "exact"
                    if _is_valid_cached_specs(result, cache_key):
                        cache[cache_key] = result
                        _save_cache(cache)
                    print(f"    ✓ 完全一致: {item_name}")
                    return result
                # 年式違いだが型番一致 → 候補保持
                if best_partial is None:
                    best_partial = (item_name, raw_spec, url)

    if best_partial:
        item_name, raw_spec, url = best_partial
        result = parse_spec(raw_spec)
        result["source_url"] = url
        result["matched_item"] = item_name
        result["match_quality"] = "type_only"
        if _is_valid_cached_specs(result, cache_key):
            cache[cache_key] = result
            _save_cache(cache)
            print(f"    △ 型番一致（年式違い）: {item_name}")
            return result
        else:
            print(f"    ⚠️ best_partial 検証失敗（matched_item型番不一致）→ 破棄")

    print(f"  [Daiwa] 公式DB該当なし → Naturum フォールバック試行")
    # フォールバック1: Naturum (shimano_jp.py の汎用パーサー流用)
    try:
        from shimano_jp import search_naturum, parse_naturum_specs
        nat_kw = f"daiwa {series_kw} {type_keyword or ''}".strip()
        urls = search_naturum(driver, nat_kw, max_results=5)
        for url in urls:
            try:
                driver.get(url)
                time.sleep(6)
                page_title = driver.find_element(By.TAG_NAME, "h1").text.strip()
                page_norm = _normalize(page_title)
                # 型番厳格チェック
                page_type = _extract_type(page_norm)
                if type_keyword and page_type:
                    if page_type != type_keyword:
                        if page_type.startswith(type_keyword) or type_keyword.startswith(page_type):
                            print(f"  [Daiwa→Naturum] ⚠️ 型番近似スキップ: target='{type_keyword}' vs page='{page_type}'")
                        continue
                elif type_keyword and type_keyword not in page_norm:
                    continue
                body = driver.find_element(By.TAG_NAME, "body").text
                specs = parse_naturum_specs(body)
                if any(specs.values()):
                    specs["source_url"] = url
                    specs["matched_item"] = page_title
                    specs["match_quality"] = "naturum"
                    if _is_valid_cached_specs(specs, cache_key):
                        cache[cache_key] = specs
                        _save_cache(cache)
                        print(f"  [Daiwa→Naturum] ✓ 取得: {page_title[:50]}")
                        return specs
                    else:
                        print(f"  [Daiwa→Naturum] ⚠️ 検証失敗 破棄: {page_title[:50]}")
                        continue
            except Exception:
                continue
    except Exception as e:
        print(f"  [Daiwa→Naturum] 失敗: {e}")

    print(f"  [Daiwa] Naturum も該当なし → Amazon フォールバック試行")
    # フォールバック2: Amazon.co.jp
    try:
        from amazon_jp import fetch_reel_specs as _fetch_amazon
        result = _fetch_amazon(driver, model_name)
        if result:
            result["match_quality"] = "amazon"
            if _is_valid_cached_specs(result, cache_key):
                cache[cache_key] = result
                _save_cache(cache)
                return result
            else:
                print(f"  [Daiwa→Amazon] ⚠️ matched_item型番不一致 破棄")
    except Exception as e:
        print(f"  [Daiwa→Amazon] 失敗: {e}")

    print(f"  [Daiwa] {model_name} 全DBで該当なし、空欄で続行")
    return {}


if __name__ == "__main__":
    # 単体テスト
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    import undetected_chromedriver as uc
    opts = uc.ChromeOptions()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--headless=new")
    drv = uc.Chrome(options=opts, version_main=146)
    try:
        for model in ["21 Caldia FCLT2500S", "DAIWA TATULA SV TW 8.1L", "24 BasX 100H"]:
            print(f"\n=== {model} ===")
            r = fetch_reel_specs(drv, model)
            if r:
                for k, v in r.items():
                    print(f"  {k}: {v}")
    finally:
        drv.quit()
