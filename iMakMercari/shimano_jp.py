#!/usr/bin/env python3
"""Shimano (and other JP fishing brands) スペック取得モジュール

- Shimano公式は Akamai完全ブロックのため、ナチュラム(naturum.co.jp)経由で取得
- 検索→商品ページ→「商品詳細」セクションの仕様テキストをパース
- ローカル JSON キャッシュで重複アクセスを回避

仕様テキストフォーマット例:
  ギア比：6
  自重（g）：185
  最大ドラグ力（kg）：3
  ベアリング数BB／ローラー：6／1
  ...

使用例:
  from shimano_jp import fetch_reel_specs
  specs = fetch_reel_specs(driver, "Shimano 23 Stradic C2000SHG")
"""
import json
import re
import time
import urllib.parse
from pathlib import Path

from selenium.webdriver.common.by import By

CACHE_PATH = Path(__file__).parent / "data" / "shimano_jp_cache.json"
CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

NATURUM_SEARCH_URL = "https://www.naturum.co.jp/search/?q={kw}"
NATURUM_PRODUCT_RE = re.compile(r"/product/\?itemcd=(\d+)")


def _normalize(s: str) -> str:
    if not s:
        return ""
    # 全角→半角、空白除去、大文字化
    s = s.translate(str.maketrans({
        "Ａ":"A","Ｂ":"B","Ｃ":"C","Ｄ":"D","Ｅ":"E","Ｆ":"F","Ｇ":"G","Ｈ":"H","Ｉ":"I",
        "Ｊ":"J","Ｋ":"K","Ｌ":"L","Ｍ":"M","Ｎ":"N","Ｏ":"O","Ｐ":"P","Ｑ":"Q","Ｒ":"R",
        "Ｓ":"S","Ｔ":"T","Ｕ":"U","Ｖ":"V","Ｗ":"W","Ｘ":"X","Ｙ":"Y","Ｚ":"Z",
        "０":"0","１":"1","２":"2","３":"3","４":"4","５":"5","６":"6","７":"7","８":"8","９":"9",
        "－":"-","　":" ",
    }))
    return s.replace(" ", "").upper()


def _load_cache():
    """キャッシュロード時に汚染データ（matched_itemに型番含まれず）を自動排除"""
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
        print(f"  [Shimano(cache)] 汚染データ {purged}件 自動破棄（matched_item型番不一致）")
        # クリーン後を保存して恒久的に修正
        try:
            CACHE_PATH.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    return cleaned


def _is_valid_cached_specs(specs, cache_key):
    """キャッシュの specs が信頼できるか検証。
    matched_item に target type_keyword 含まれてなければ汚染データ → False。
    """
    if not specs:
        return False
    matched = _normalize(specs.get("matched_item", ""))
    target = cache_key  # cache_key は既に _normalize 済
    # 型番抽出パターン（fetch_reel_specs と同じ）
    type_patterns = [r"(C\d{4}[A-Z]+)", r"(\d{4}[A-Z]+)", r"(\d{3,4}M?D?)"]
    target_type = None
    for pat in type_patterns:
        m = re.search(pat, target)
        if m:
            target_type = m.group(1)
            break
    if not target_type:
        return False  # target から型番取れない → そもそもキャッシュすべきでない
    matched_type = None
    for pat in type_patterns:
        m = re.search(pat, matched)
        if m:
            matched_type = m.group(1)
            break
    if not matched_type:
        return False  # matched_item に型番なし → 汚染データ
    if matched_type != target_type:
        return False  # 型番不一致 → 別商品の specs
    return True


def _save_cache(cache):
    try:
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def search_naturum(driver, keyword: str, max_results: int = 5) -> list:
    """ナチュラムで検索→商品ページURL一覧返す"""
    url = NATURUM_SEARCH_URL.format(kw=urllib.parse.quote(keyword))
    driver.get(url)
    time.sleep(8)
    src = driver.page_source
    itemcds = list(set(NATURUM_PRODUCT_RE.findall(src)))
    return [f"https://www.naturum.co.jp/product/?itemcd={cd}" for cd in itemcds[:max_results]]


def get_naturum_product_title(driver) -> str:
    """現ページから商品タイトル取得（ナチュラム）"""
    try:
        title_el = driver.find_element(By.TAG_NAME, "h1")
        return title_el.text.strip()
    except Exception:
        try:
            return driver.title.strip()
        except Exception:
            return ""


def parse_naturum_specs(body_text: str) -> dict:
    """ナチュラム商品ページのbodyテキストから仕様抽出"""
    out = {
        "weight_g": "",
        "gear_ratio": "",
        "max_drag_kg": "",
        "line_capacity_nylon": "",
        "line_capacity_pe": "",
        "ball_bearings": "",
        "line_per_turn_cm": "",
        "handle_arm_mm": "",
        "spool_size": "",
        "country": "",  # ナチュラムには記載なし、別取得
    }
    # 「商品詳細」セクション以降を対象
    if "商品詳細" in body_text:
        body_text = body_text.split("商品詳細", 1)[1]

    patterns = [
        ("weight_g",            r"自重[\s（(]*g[\s）)]*[:：]\s*([\d.]+)"),
        ("gear_ratio",          r"ギア比[\s]*[:：]\s*([\d.:]+)"),
        ("max_drag_kg",         r"最大ドラグ力[\s（(]*kg[\s）)]*[:：]\s*([\d.]+)"),
        # 糸巻量: 数字/区切り記号のみで限定（漢字・英字を範囲記号として扱う問題回避）
        ("line_capacity_nylon", r"糸巻量ナイロン[\s（(]*lb[\-－]m[\s）)]*[:：]\s*([0-9\-－、,，\.\s]+?)(?:糸巻|ベアリング|最大巻|ハンドル|スプール|フロロ|PE|$)"),
        ("line_capacity_pe",    r"糸巻量PE[\s（(]*号[\-－]m[\s）)]*[:：]\s*([0-9\-－、,，\.\s]+?)(?:糸巻|ベアリング|最大巻|ハンドル|夢屋|商品|$)"),
        ("ball_bearings",       r"ベアリング数BB[／/]ローラー[\s]*[:：]\s*([\d]+\s*[／/]\s*[\d]+)"),
        ("line_per_turn_cm",    r"最大巻上長[\s（(]*cm[／/][^)）]*[\s）)]*[:：]\s*([\d]+)"),
        ("handle_arm_mm",       r"ハンドル長[\s（(]*mm[\s）)]*[:：]\s*([\d]+)"),
        ("spool_size",          r"スプール\s*径[\s（(]*mm[\s）)]*[／/][^：:]+[:：]\s*([\d./]+)"),
    ]
    for key, pat in patterns:
        m = re.search(pat, body_text)
        if m:
            v = m.group(1).strip()
            v = re.sub(r'\s+', '', v)
            out[key] = v
    # ベアリング "6/1" → "6+1"
    if out["ball_bearings"]:
        out["ball_bearings"] = out["ball_bearings"].replace("／", "+").replace("/", "+")
    # ギア比 "6" → "6.0:1" or keep as is
    gr = out["gear_ratio"]
    if gr and ":" not in gr:
        out["gear_ratio"] = f"{gr}:1"
    return out


def fetch_reel_specs(driver, model_name: str) -> dict:
    """モデル名からShimano（ナチュラム経由）公式スペック取得

    Args:
      driver: Selenium driver
      model_name: 例 "Shimano 23 Stradic C2000SHG"

    Returns:
      {weight_g, gear_ratio, ..., source_url, matched_item}
    """
    cache = _load_cache()
    cache_key = _normalize(model_name)
    if cache_key in cache:
        return cache[cache_key]

    # 既知 Shimano シリーズキーワード（日本語表記、Naturum向け）
    KNOWN_SERIES = [
        ("ストラディック", ["ストラディック", "STRADIC"]),
        ("ヴァンキッシュ", ["ヴァンキッシュ", "VANQUISH"]),
        ("ヴァンフォード", ["ヴァンフォード", "VANFORD"]),
        ("アルテグラ",     ["アルテグラ", "ULTEGRA"]),
        ("ステラ",         ["ステラ", "STELLA"]),
        ("ツインパワー",   ["ツインパワー", "TWIN POWER", "TWINPOWER"]),
        ("セフィアSS",     ["セフィア", "SEPHIA"]),
        ("カルカッタ",     ["カルカッタ", "CALCUTTA"]),
        ("メタニウム",     ["メタニウム", "METANIUM"]),
        ("バンタム",       ["バンタム", "BANTAM"]),
        ("アンタレス",     ["アンタレス", "ANTARES"]),
        ("バルケッタ",     ["バルケッタ", "BARCHETTA"]),
        ("オシア",         ["オシア", "OCEA"]),
        ("ナスキー",       ["ナスキー", "NASCI"]),
        ("シエナ",         ["シエナ", "SIENNA"]),
        ("カーディフ",     ["カーディフ", "CARDIFF"]),
    ]
    # 既知シリーズ名 + 型番 でナチュラム検索
    title_upper = model_name.upper()
    series_jp = None
    for jp_kw, aliases in KNOWN_SERIES:
        for alias in aliases:
            if alias.upper() in title_upper:
                series_jp = jp_kw
                break
        if series_jp:
            break

    # 型番抽出（C2000SHG, 4000XG 等）→ 検索キーワードに含める
    type_match = re.search(r"(C?\d{3,4}[A-Z]+)", model_name.upper())
    type_kw = type_match.group(1) if type_match else ""

    if series_jp:
        search_kw = f"shimano {series_jp} {type_kw}".strip()
    else:
        # フォールバック: 旧ロジック
        cleaned = re.sub(r"\b(\d{2})\b", "", model_name)
        cleaned = re.sub(r"加古川店】|中古|【|】|\|", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        search_kw = cleaned

    print(f"  [Shimano(Naturum)] 検索: {search_kw}")
    try:
        product_urls = search_naturum(driver, search_kw, max_results=5)
        print(f"  [Shimano(Naturum)] 検索結果: {len(product_urls)}件")
    except Exception as e:
        print(f"  [Shimano(Naturum)] 検索失敗: {e}")
        return {}

    if not product_urls:
        return {}

    target_norm = _normalize(model_name)
    # 型番抽出（C2000SHG, 4000XG 等）
    type_patterns = [
        r"(C\d{4}[A-Z]+)",      # C2000SHG, C3000XG
        r"(\d{4}[A-Z]+)",       # 4000XG, 1000FA
        r"(\d{3,4}M?D?)",       # 1000, 2500SHG, 4000FD, 4000FA
    ]

    def _extract_type(text):
        """ページ/タイトルから型番を抽出（target と同じパターンで）"""
        for pat in type_patterns:
            m = re.search(pat, text)
            if m:
                return m.group(1)
        return None

    type_keyword = _extract_type(target_norm)

    # 安全装置: type_keyword 抽出失敗時は specs採用禁止（推測しないルール準拠）
    if not type_keyword:
        print(f"  [Shimano(Naturum)] 型番抽出失敗 → specs取得スキップ（誤マッチ防止）")
        return {}

    target_year_match = re.search(r"(?<![A-Z\d])(\d{2})(?![\d])", target_norm)
    target_year = target_year_match.group(1) if target_year_match else None

    best_partial = None
    for url in product_urls:
        try:
            print(f"  [Shimano(Naturum)] 取得: {url}")
            driver.get(url)
            time.sleep(6)
            page_title = get_naturum_product_title(driver)
            page_title_norm = _normalize(page_title)
            print(f"    title: {page_title[:60]}")

            # 型番厳格チェック（C2000S と C2000SHG は別物として区別）
            page_type = _extract_type(page_title_norm)
            if type_keyword and page_type:
                if page_type != type_keyword:
                    # 完全一致しない → 近似（C2000S vs C2000SHG等）はログ出力＋スキップ
                    if page_type.startswith(type_keyword) or type_keyword.startswith(page_type):
                        print(f"    ⚠️ 型番近似スキップ: target='{type_keyword}' vs page='{page_type}' (別仕様の可能性)")
                    continue
            elif type_keyword and type_keyword not in page_title_norm:
                # フォールバック: 型番抽出失敗時は従来の含有チェック
                continue

            body = driver.find_element(By.TAG_NAME, "body").text
            specs = parse_naturum_specs(body)

            # 年式マッチ確認
            page_year_match = re.search(r"(?<![A-Z\d])(\d{2})(?![\d])", page_title_norm)
            quality = "type_only"
            if target_year and page_year_match and page_year_match.group(1) == target_year:
                quality = "exact"

            specs["source_url"] = url
            specs["matched_item"] = page_title
            specs["match_quality"] = quality

            if quality == "exact":
                # キャッシュ保存前に検証（汚染防止）
                if _is_valid_cached_specs(specs, cache_key):
                    cache[cache_key] = specs
                    _save_cache(cache)
                print(f"    ✓ 完全一致: {page_title}")
                return specs
            if best_partial is None:
                best_partial = specs

        except Exception as e:
            print(f"    取得失敗: {e}")
            continue

    if best_partial:
        if _is_valid_cached_specs(best_partial, cache_key):
            cache[cache_key] = best_partial
            _save_cache(cache)
            print(f"    △ 型番一致（年式違い）: {best_partial.get('matched_item','')[:60]}")
            return best_partial
        else:
            print(f"    ⚠️ best_partial 検証失敗（matched_item型番不一致）→ 破棄")

    print(f"  [Shimano(Naturum)] 該当なし → Amazon フォールバック試行")
    try:
        from amazon_jp import fetch_reel_specs as _fetch_amazon
        result = _fetch_amazon(driver, model_name)
        if result:
            result["match_quality"] = "amazon"
            # Amazon結果も検証してからキャッシュ
            if _is_valid_cached_specs(result, cache_key):
                cache[cache_key] = result
                _save_cache(cache)
            return result
    except Exception as e:
        print(f"  [Shimano→Amazon] 失敗: {e}")

    print(f"  [Shimano] {model_name} 全DBで該当なし、空欄で続行")
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
        for model in ["Shimano 23 Stradic C2000SHG", "Shimano 25 Ultegra C2000S", "Shimano 24 Vanford 4000XG"]:
            print(f"\n=== {model} ===")
            r = fetch_reel_specs(drv, model)
            for k, v in r.items():
                print(f"  {k}: {v}")
    finally:
        drv.quit()
