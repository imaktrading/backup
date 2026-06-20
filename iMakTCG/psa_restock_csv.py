#!/usr/bin/env python3
# iMak Trading Japan - PSA Cert → eBay CSV 自動生成スクリプト
#
# ⚠️ これは psa_to_csv.py の **RESTOCK専用 fork** (2026-06-21 新設)。
#    経緯: PSA再仕入れ(RESTOCK)が新規 psa_to_csv.py を編集していたため、ユーザー指示
#    「新規は触るな」で psa_to_csv.py を pristine に戻し、RESTOCK 差分をこちらに隔離した。
#    fork が持つ RESTOCK 差分: ①PSA_RESTOCK_INPUT入力モード ②別profile(PSA_PROFILE_DIR)
#    ③非対話input() isatty guard。
#    ⚠️ drift注意: 新規 psa_to_csv.py の改善はこちらに自動伝播しない。生成ロジックを変えたら
#    両方に反映するか、必要差分のみ手で取り込むこと。呼出元: iMakHQ/tools/psa_restock_build.py。
# 必要: pip install selenium undetected-chromedriver anthropic

import csv
import sys
import os
import time
import re
import json
import base64
import subprocess
import anthropic
import requests
from datetime import datetime, timedelta
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
import pokemon_card_jp
import bandai_tcg_plus

# iMakCatalog (Phase 1: One Piece TCG を bandai_jp.py 直接スクレイプから DB lookup へ移行)
# 2026-05-28: separated worktree (= C:/dev/iMak_catalog/iMakCatalog) を優先参照
# 本元 worktree (= ../iMakCatalog) は master branch 古いため、 variant_meta.py 等の新 module が無い
_CATALOG_SEPARATED = r"C:/dev/iMak_catalog/iMakCatalog"
if os.path.isdir(_CATALOG_SEPARATED):
    sys.path.insert(0, _CATALOG_SEPARATED)
else:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "iMakCatalog"))
from integrations import psa_to_csv as catalog_psa

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# iMakeBayAPI の共通モジュール（listing_validator, profit_params, listing_common 等）を import 可能にする
# build_row() 等で動的 import されるため、モジュールロード時にパスを通しておく必要あり
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "iMakeBayAPI"))
from listing_core import get_csv_output_path as _gcop  # CSV出力先の中央集約用 (iMakHQ/csv_output/<project>_upload_<ts>.csv)
from chrome_util import detect_chrome_major  # uc version_main を実Chromeから検出 (数値ハードコード禁止)

# ===== 設定 =====
CERTS_FILE = "certs.txt"
DESCRIPTION_FILE = "PSA10_snkrdunk.txt"  # 防衛テンプレ (= Stock Photo + cert 違う可能性 明記) を全 TCG listing 適用
DEFAULT_PRICE = 100.00
SCHEDULE_WEEKS = 2

# 市場 median による gate 判定の skip 条件 (OR で評価).
# 出品数 ≤ 閾値 = 薄商い、median 不安定 → gate skip でコストプラス価格出品.
# target_usd ≤ 閾値 = 低額帯、無在庫 + Promoted Standard で焦付きリスク低 → gate skip.
# どちらか満たせば 緩和 (機会損失回避)、両方満たさなければ通常 GO/保留/NO-GO 判定.
# 2026-05-11 ユーザー判断: ≤10件 + ≤$250 OR 条件で導入.
MARKET_GATE_MIN_LISTINGS = 10
MARKET_GATE_MAX_TARGET_USD = 250.0

# API key読み込み
try:
    with open("API key.txt", "r", encoding="utf-8") as f:
        ANTHROPIC_API_KEY = f.read().strip()
except FileNotFoundError:
    print("⚠️ 'API key.txt' が見つかりません。タイトル生成はルールベースにフォールバックします。")
    ANTHROPIC_API_KEY = None

PIC_URL = "https://raw.githubusercontent.com/imaktrading/imaktrading.github.io/main/999.png"
RETURN_POLICY = "No return"
PAYMENT_POLICY = "SALE"
LOCATION = "Osaka"

STORE_CATEGORIES = {
    "Gundam": 42145683010,
    "One Piece": 42142742010,
    "Dragon Ball": 42154739010,
    "Pokemon": 42054519010,
    "NIKKE": 42144249010,
    "Hololive": 42144254010,
}

SHIPPING_POLICIES = [
    (39, "<39"), (60, "40-60"), (100, "60-100"), (200, "100-200"),
    (300, "200-300"), (400, "300-400"), (500, "400-500"),
    (600, "500-600"), (800, "600-800"), (1000, "800-1000"),
]

# ===== eBay API 市場価格取得 =====
EBAY_KEYS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "iMakeBayAPI", "ebay keys.txt"
)
# TOPセラー判定閾値
TOP_SELLER_MIN_FEEDBACK = 500
TOP_SELLER_MIN_PERCENTAGE = 98.0


def load_ebay_keys():
    keys = {}
    try:
        with open(EBAY_KEYS_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    keys[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return keys


def get_ebay_oauth_token(app_id, app_secret):
    credentials = base64.b64encode(f"{app_id}:{app_secret}".encode()).decode()
    # 2026-05-01: getaddrinfo 失敗時に DNS flush + 1 回 retry (dns_resilience).
    # 18:17 事故の直接原因 (token 取得段階で getaddrinfo failed → 全件 $100 fallback)
    # を本体 logic 不変で自動回復させる.
    import sys as _sys, os as _os
    _imakeBayAPI = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "iMakeBayAPI")
    if _imakeBayAPI not in _sys.path:
        _sys.path.insert(0, _imakeBayAPI)
    from dns_resilience import with_dns_retry
    resp = with_dns_retry(
        requests.post,
        "https://api.ebay.com/identity/v1/oauth2/token",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {credentials}",
        },
        data={
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def search_market_price(token, game, card_number, character):
    """eBay Browse APIで市場価格を取得。競合0件なら None を返す。
    価格基準: 全セラー中央値（TOPセラーは参考表示のみ）

    2026-04-28 SSOT 化:
      実体は iMakeBayAPI/market_gate.py (psa_to_csv ↔ check_csv 共通).
      旧ロジック (本ファイル直書き) は market_gate に統合済.
      キャッシュ層 (TTL 600 秒) で連続実行時の median ブレ ($140 vs $115) を解消.
    """
    # market_gate を sys.path から import (iMakeBayAPI への参照は既存と同じ)
    import sys as _sys, os as _os
    _imakeBayAPI = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "iMakeBayAPI")
    if _imakeBayAPI not in _sys.path:
        _sys.path.insert(0, _imakeBayAPI)
    from market_gate import fetch_market_price as _fetch_mg
    return _fetch_mg(token, game, card_number, character)


def fetch_top_seller_item_specifics(token, items, max_items=3):
    """TOPセラーのリスティングから Item Specifics を取得。
    複数セラーの値を集約して最頻値を返す。"""
    # TOPセラーのアイテムを選定
    top_items = []
    for item in items:
        seller = item.get("seller", {})
        score = seller.get("feedbackScore", 0)
        pct_str = seller.get("feedbackPercentage", "0")
        try:
            pct = float(pct_str)
        except (ValueError, TypeError):
            pct = 0
        if score >= TOP_SELLER_MIN_FEEDBACK and pct >= TOP_SELLER_MIN_PERCENTAGE:
            item_id = item.get("itemId", "")
            if item_id:
                top_items.append(item_id)
        if len(top_items) >= max_items:
            break

    if not top_items:
        # TOPセラーがなければ全セラーから上位を取得
        for item in items[:max_items]:
            item_id = item.get("itemId", "")
            if item_id:
                top_items.append(item_id)

    # 各アイテムの詳細を取得
    all_specs = []  # [{name: value}, ...]
    for item_id in top_items:
        try:
            url = f"https://api.ebay.com/buy/browse/v1/item/{item_id}"
            headers = {
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
                "Content-Type": "application/json",
            }
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                continue
            data = resp.json()
            aspects = data.get("localizedAspects", [])
            specs = {}
            for asp in aspects:
                name = asp.get("name", "")
                value = asp.get("value", "")
                if name and value:
                    specs[name] = value
            if specs:
                all_specs.append(specs)
            time.sleep(0.3)
        except Exception as e:
            print(f"    ⚠️ アイテム詳細取得エラー: {e}")

    if not all_specs:
        return {}

    # 全セラーの値を集約: 各項目の最頻値を採用
    from collections import Counter
    merged = {}
    all_keys = set()
    for specs in all_specs:
        all_keys.update(specs.keys())

    for key in all_keys:
        values = [s[key] for s in all_specs if key in s]
        if values:
            # 最頻値
            counter = Counter(values)
            merged[key] = counter.most_common(1)[0][0]

    return merged


# eBay Item Specifics名 → CSV列名のマッピング
EBAY_SPEC_TO_CSV = {
    "Game": "C:Game",
    "Set": "C:Set",
    "Card Type": "C:Card Type",
    "Card Name": "C:Card Name",
    "Character": "C:Character",
    "Card Number": "C:Card Number",
    "Rarity": "C:Rarity",
    "Features": "C:Features",
    "Manufacturer": "C:Manufacturer",
    "Language": "C:Language",
    "Year Manufactured": "C:Year Manufactured",
    "Country of Origin": "C:Country of Origin",
    "Franchise": "C:Franchise",
    "Age Level": "C:Age Level",
    "Autographed": "C:Autographed",
    "Vintage": "C:Vintage",
    "Material": "C:Material",
    "Card Size": "C:Card Size",
    "Customized": "C:Customized",
    "Finish": "C:Finish",
    "Attribute/MTG:Color": "C:Attribute/MTG:Color",
    "Illustrator": "C:Illustrator",
    "Cost": "C:Cost",
    "Attack/Power": "C:Attack/Power",
    "Defense/Toughness": "C:Defense/Toughness",
    "HP": "C:HP",
    "Stage": "C:Stage",
    "Card Condition": "C:Card Condition",
}

# TOPセラーの値で上書きしない項目（PSA/システムが決める値）
SPEC_NO_OVERRIDE = {
    "C:Grade", "C:Professional Grader", "C:Graded",
    "C:Manufacturer", "C:Language", "C:Country of Origin",
    "C:Year Manufactured", "C:Age Level", "C:Autographed",
    "C:Vintage", "C:Material", "C:Customized",
}


RARITY_PATTERN = re.compile(
    r'\s+(LEGEND RARE\+|LEGEND RARE|RARE\+|RARE|COMMON\+|COMMON|UNCOMMON|PROMO|LR\+|LR|R\+|C\+)$',
    re.IGNORECASE
)

def get_shipping_policy(price):
    """V6/V5/Free モード別 Shipping Profile 名 (listing_common 経由)."""
    try:
        from listing_common import get_shipping_policy_name
        return get_shipping_policy_name(price, "TCG(PSA10)")
    except Exception:
        for threshold, policy in SHIPPING_POLICIES:
            if price <= threshold:
                return policy
        return "800-1000"

def get_schedule_time():
    future = datetime.utcnow() + timedelta(weeks=SCHEDULE_WEEKS)
    return future.strftime("%Y-%m-%d %H:%M:%S")


_EBAY_FILTER_AVAILABLE = None
_EBAY_FILTER_REPORT = {
    "validated": 0,           # 正規化で eBay 正規値に書き換え
    "passthrough": 0,         # validate 戻り値が入力と同じ (= 一致 or FREE_TEXT B 案)
    "blanked": 0,             # SELECTION_ONLY で不在 → 空欄
    "truncated": 0,           # 文字数制限超 → 切詰
    "required_blank": 0,      # 必須 field が空欄 (= 出品エラーリスク警告)
    "jp_blanked": 0,          # Item Specifics に日本語混入 → fail-closed 空欄化
    "blanked_samples": [],
    "truncated_samples": [],
    "required_blank_samples": [],
    "jp_blanked_samples": [],
}

# 日本語 codepoint (ひらがな/カタカナ/CJK/半角カナ)。英単語 "Japanese" や em-dash(—)
# は含まれないので影響なし。
_JP_CHAR_RE = re.compile(r'[぀-ヿ㐀-䶿一-鿿ｦ-ﾟ]')


def _contains_japanese(s):
    """文字列に日本語 codepoint が含まれるか (Item Specifics fail-closed ガード用)."""
    return bool(_JP_CHAR_RE.search(str(s or "")))


def _get_ebay_filter():
    global _EBAY_FILTER_AVAILABLE
    if _EBAY_FILTER_AVAILABLE is None:
        try:
            import ebay_filter_masters as _ef  # sys.path に C:/dev/iMak_catalog/iMakCatalog 済
            _EBAY_FILTER_AVAILABLE = _ef
        except Exception as _e:
            print(f"  ⚠️ ebay_filter_masters import 失敗 (= validate skip): {_e}")
            _EBAY_FILTER_AVAILABLE = False
    return _EBAY_FILTER_AVAILABLE if _EBAY_FILTER_AVAILABLE else None


# eBay SELECTION_ONLY だが eBay が裏で受付ける特殊値の whitelist
# 例: Country of Origin = "Does not apply" (= グローバル CLAUDE.md 方針)
#   eBay 公式 API list には未登録だが、 出品は通る。 空欄にすると eBay AI が
#   勝手に Japan 等を補完するため、 明示的に "Does not apply" を入れる必要あり。
EBAY_FILTER_SPECIAL_BYPASS = {
    "Country of Origin": {"does not apply", "japan"},  # NFKC+lower 正規化済 で比較
}


def _sample_append(key, sample, cap=20):
    if len(_EBAY_FILTER_REPORT[key]) < cap:
        _EBAY_FILTER_REPORT[key].append(sample)


def apply_ebay_filter_to_row(row, headers, category="tcg"):
    """row 内 C:<aspect> 値を eBay 正規値 validate.

    3 ケース処理 (= memory:official_x_ebay_filter_max_activation):
      - 一致              → eBay 正規値 (= validate_value で NFKC 正規化済 return)
      - FREE_TEXT 不在    → catalog 値そのまま (= validate_value 改修済 B 案)
      - SELECTION_ONLY 不在 → 空欄 (= validate_value None)

    Gemini 改善 B 同梱:
      - aspect_required + 空欄 → 警告 log (= 出品エラーリスク)
      - 文字数制限超          → truncation
    """
    # 2026-06-03 fail-closed 日本語ガード (ef 有無に関わらず最優先で実行 = validate skip 時も
    # 日本語を出さない)。Item Specifics に日本語 codepoint が混入したら空欄化。
    # eBay US 出品の C:* は英語必須。catalog の name_en 欠落等で日本語 (name_jp) が漏れた場合、
    # 誤値で出すより空欄が安全 (= 出品の正確性原則 / 空欄 > 誤り)。英単語 "Japanese" や
    # em-dash(—) は日本語 codepoint を含まないため無影響。
    for aspect, csv_col in EBAY_SPEC_TO_CSV.items():
        if csv_col not in headers:
            continue
        idx = headers.index(csv_col)
        if idx >= len(row):
            continue
        if _contains_japanese(row[idx]):
            _EBAY_FILTER_REPORT["jp_blanked"] += 1
            _sample_append("jp_blanked_samples", f"{aspect}={str(row[idx]).strip()}")
            row[idx] = ""

    ef = _get_ebay_filter()
    if ef is None:
        return row
    for aspect, csv_col in EBAY_SPEC_TO_CSV.items():
        if csv_col not in headers:
            continue
        idx = headers.index(csv_col)
        if idx >= len(row):
            continue
        raw = str(row[idx] or "").strip()

        # 改善 B-1: 必須 field + 空欄 = 警告 log (= continue で空欄維持)
        if not raw:
            try:
                if ef.is_required(category, aspect):
                    _EBAY_FILTER_REPORT["required_blank"] += 1
                    _sample_append("required_blank_samples", aspect)
            except Exception:
                pass
            continue

        # 改善 B-2: 文字数制限 truncation
        try:
            max_len = ef.get_max_length(category, aspect)
        except Exception:
            max_len = None
        if max_len and len(raw) > max_len:
            _EBAY_FILTER_REPORT["truncated"] += 1
            _sample_append("truncated_samples", f"{aspect}: {len(raw)}→{max_len}")
            raw = raw[:max_len]

        # 改善 A 同梱の validate_value (= NFKC + FREE_TEXT B 案)
        validated = ef.validate_value(category, aspect, raw)
        if validated is None:
            # SELECTION_ONLY 不在 = 空欄
            # ただし whitelist 特殊値 (= 例: Country "Does not apply") は そのまま採用
            bypass_set = EBAY_FILTER_SPECIAL_BYPASS.get(aspect, set())
            if raw.lower() in bypass_set:
                _EBAY_FILTER_REPORT["passthrough"] += 1
                row[idx] = raw
            else:
                _EBAY_FILTER_REPORT["blanked"] += 1
                _sample_append("blanked_samples", f"{aspect}={raw}")
                row[idx] = ""
        elif validated == raw:
            # 一致 or FREE_TEXT B 案 そのまま return
            _EBAY_FILTER_REPORT["passthrough"] += 1
            row[idx] = raw
        else:
            # NFKC 正規化等で eBay 正規表記に書き換え
            _EBAY_FILTER_REPORT["validated"] += 1
            row[idx] = validated
    return row


def print_ebay_filter_report():
    """cycle 終了時に呼出 = listing CSV 全行 validate 後のサマリー."""
    r = _EBAY_FILTER_REPORT
    total = r["validated"] + r["passthrough"] + r["blanked"]
    if total == 0 and r["required_blank"] == 0 and r["truncated"] == 0 and r["jp_blanked"] == 0:
        return
    print()
    print("=" * 60)
    print("eBay フィルタ validate サマリー (= 3 ケース処理 + 改善 B)")
    print("=" * 60)
    print(f"  ✅ passthrough  (= 一致 or FREE_TEXT B 案 そのまま): {r['passthrough']}")
    print(f"  🔧 validated    (= NFKC 正規化で eBay 正規表記に書換)  : {r['validated']}")
    print(f"  ⬜ blanked      (= SELECTION_ONLY 不在で空欄)         : {r['blanked']}")
    print(f"  ✂  truncated    (= 文字数制限超で切詰)                : {r['truncated']}")
    print(f"  ⚠️ required_blank (= 必須 field が空欄 = 出品エラーリスク): {r['required_blank']}")
    print(f"  🚫 jp_blanked    (= Item Specifics 日本語混入で空欄化)   : {r['jp_blanked']}")
    if r["jp_blanked_samples"]:
        print(f"  jp_blanked samples (max 20):")
        for s in r["jp_blanked_samples"]:
            print(f"    - {s}")
    if r["blanked_samples"]:
        print(f"  blanked samples (max 20):")
        for s in r["blanked_samples"]:
            print(f"    - {s}")
    if r["truncated_samples"]:
        print(f"  truncated samples:")
        for s in r["truncated_samples"]:
            print(f"    - {s}")
    if r["required_blank_samples"]:
        print(f"  required_blank samples:")
        for s in r["required_blank_samples"]:
            print(f"    - {s}")

def get_store_category(franchise):
    for key, cat_id in STORE_CATEGORIES.items():
        if key.lower() in franchise.lower():
            return cat_id
    return 42054516010

def smart_titlecase(s):
    """全大文字文字列をタイトルケース化。数字含むトークンは大文字維持、
    接続詞(of/the/and/in)は小文字。ハイフン/スラッシュ区切りも適切に処理。"""
    if not s:
        return s
    connectors = {"of", "the", "and", "in", "a", "an", "to", "for"}
    result = []
    for word in s.split():
        # '-' と '/' の両方で分割して個別に処理
        sub_parts = re.split(r'([-/])', word)
        new_sub = []
        for p in sub_parts:
            if p in ('-', '/'):
                new_sub.append(p)
            elif not p:
                new_sub.append(p)
            elif any(c.isdigit() for c in p):
                if p[0].isdigit() and p[-1].isalpha():
                    new_sub.append(p.lower())
                else:
                    new_sub.append(p.upper())
            elif p.lower() in connectors and result:
                new_sub.append(p.lower())
            else:
                new_sub.append(p.capitalize())
        result.append(''.join(new_sub))
    return ' '.join(result)

def detect_game_info(brand):
    brand_upper = brand.upper()
    if "DUAL IMPACT" in brand_upper:
        return "Gundam Card Game", "Dual Impact", "Gundam"
    elif "NEWTYPE RISING" in brand_upper:
        return "Gundam Card Game", "Newtype Rising", "Gundam"
    elif "STEEL REQUIEM" in brand_upper:
        return "Gundam Card Game", "Steel Requiem", "Gundam"
    elif "HEROIC BEGINNINGS" in brand_upper:
        return "Gundam Card Game", "Heroic Beginnings", "Gundam"
    elif "WINGS OF ADVANCE" in brand_upper:
        return "Gundam Card Game", "Wings of Advance", "Gundam"
    elif "ZEON" in brand_upper:
        return "Gundam Card Game", "Zeon's Rush", "Gundam"
    elif "SEED STRIKE" in brand_upper:
        return "Gundam Card Game", "SEED Strike", "Gundam"
    elif "IRON BLOOM" in brand_upper:
        return "Gundam Card Game", "Iron Bloom", "Gundam"
    elif "GUNDAM" in brand_upper and ("EX BASE" in brand_upper or "PROMOS" in brand_upper):
        return "Gundam Card Game", "Edition Beta Promos", "Gundam"
    elif "GUNDAM" in brand_upper:
        return "Gundam Card Game", brand, "Gundam"
    elif "ONE PIECE" in brand_upper:
        # セット名を清浄化：長いプレフィックス/"JAPANESE"を除去
        prefixes = [
            "ONE PIECE CARD GAME JAPANESE ",
            "ONE PIECE CARD GAME ",
            "ONE PIECE JAPANESE ",
            "ONE PIECE ",
        ]
        short_set = brand
        for prefix in prefixes:
            if brand_upper.startswith(prefix):
                short_set = brand[len(prefix):]
                break
        # "JAPANESE"単独トークン除去
        short_set = re.sub(r'(?i)(?<![A-Za-z])japanese(?![A-Za-z])', '', short_set)
        short_set = re.sub(r'\s+', ' ', short_set).strip()
        # セットコードプレフィックスを除去 (OP\d+, ST\d+, EB\d+, PRB\d+)
        cleaned = re.sub(r'^(OP|ST|EB|PRB)\d+[\s\-]+', '', short_set, flags=re.IGNORECASE)
        if cleaned:
            short_set = cleaned
        # スマートタイトルケース: 数字含むトークンは大文字維持、接続詞は小文字
        short_set = smart_titlecase(short_set)
        # eBay Item Specifics の慣用表記に正規化
        # "Promos" / "Promo" → "Promo Cards" (eBayオートコンプリート候補に合わせる)
        if short_set.lower() in ("promos", "promo"):
            short_set = "Promo Cards"
        # Game名: eBay 公式 API 正規値 "One Piece CCG" 採用 (2026-05-31)
        # = 公式 × eBay フィルタ 最大活用 (= memory:official_x_ebay_filter_max_activation)
        # 検索 query 副作用は _normalize_game_short mapping で吸収済
        return "One Piece CCG", short_set, "One Piece"
    elif "DRAGON BALL" in brand_upper:
        # セット名を短縮：長いプレフィックスを除去して末尾のセット名だけ残す
        # 例: "DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE BLAZING AURA" → "Blazing Aura"
        prefixes = [
            "DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE ",
            "DRAGON BALL SUPER CARD GAME FUSION WORLD ",
            "DRAGON BALL SUPER CARD GAME ",
        ]
        short_set = brand
        for prefix in prefixes:
            if brand_upper.startswith(prefix):
                short_set = brand[len(prefix):].title()
                break
        return "Dragon Ball Super Card Game", short_set, "Dragon Ball"
    elif "POKEMON" in brand_upper:
        return "Pokemon", brand, "Pokemon"
    elif "YU-GI-OH" in brand_upper or "YUGIOH" in brand_upper:
        prefixes = [
            "YU-GI-OH! JAPANESE ", "YU-GI-OH JAPANESE ", "YUGIOH JAPANESE ",
            "YU-GI-OH! ", "YU-GI-OH ", "YUGIOH ",
        ]
        short_set = brand
        for prefix in prefixes:
            if brand_upper.startswith(prefix):
                short_set = brand[len(prefix):]
                break
        cleaned = re.sub(r'^[A-Z]+-?\d+[A-Z]*[\s\-]+', '', short_set, flags=re.IGNORECASE)
        if cleaned:
            short_set = cleaned
        short_set = smart_titlecase(short_set)
        return "Yu-Gi-Oh! TCG", short_set, "Yu-Gi-Oh!"
    else:
        return brand, brand, brand

def generate_title_with_claude(game, set_name, card_number, subject, franchise, card_image_url=None):
    """Claude APIを使ってeBayタイトル・カード情報を生成（画像対応）"""
    if not ANTHROPIC_API_KEY:
        return None
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        # 画像をbase64エンコード
        image_content = []
        if card_image_url:
            try:
                import urllib.request
                with urllib.request.urlopen(card_image_url, timeout=10) as response:
                    image_data = response.read()
                import base64
                image_b64 = base64.b64encode(image_data).decode('utf-8')
                # Content-Typeを判定
                media_type = "image/jpeg"
                if card_image_url.lower().endswith(".png"):
                    media_type = "image/png"
                elif card_image_url.lower().endswith(".webp"):
                    media_type = "image/webp"
                image_content = [{
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": image_b64,
                    }
                }]
                print(f"    📷 カード画像取得成功")
            except Exception as e:
                print(f"    📷 画像読み込みエラー: {e}")

        prompt_text = f"""Analyze this PSA graded Japanese trading card and generate eBay listing data.

Card info from PSA label:
- Game: {game}
- Set: {set_name}
- Card Number: #{card_number}
- PSA Label Text: {subject}
- Franchise: {franchise}

{"Read the card image to extract ONLY values that are CLEARLY PRINTED on the card: Attack/Power number, Cost number, Attribute/Color symbol. Do NOT guess finish or rarity from visual appearance." if image_content else "No image available, use label text only."}

CRITICAL - FACTS ONLY POLICY:
- Populate fields ONLY from verifiable sources: PSA label text or text PRINTED on the card
- NEVER infer Rarity from set name patterns (e.g., "Anniversary" set does NOT mean rarity="Promo")
- NEVER infer Finish from rarity (e.g., "Alternate Art" does NOT automatically mean "Foil")
- NEVER shorten or alter the PSA Subject character name:
  * "O-NAMI" must stay "O-Nami" (not "Nami")
  * "TONY TONY CHOPPER" must stay "Tony Tony Chopper" (not "Tony Chopper")
  * "MONKEY D. LUFFY" must stay "Monkey D. Luffy"
  * "RORONOA ZORO" must stay "Roronoa Zoro"
- If a value is not verifiable from label or printed card text, RETURN BLANK STRING ""
- Blank is ALWAYS better than a guess. The seller takes legal responsibility for listing accuracy.

TITLE RULES (FACTS ONLY - eBay Keyword Spamming Policy compliant):
- Length: up to 80 characters MAX. Use what facts allow - 50-80 char range is acceptable.
- Start with "PSA 10" (factual: card is graded PSA 10)
- Template: PSA 10 [Game] [Set] #[Num] [Exact PSA Subject with full character name] [Rarity if in PSA label]
- Game short names (= iMakKeywords PDF Q1 2026 実データ Rank 準拠):
  * Pokemon (Rank 1, never "Pokemon TCG")
  * Yugioh (Rank 19, no hyphen, never "Yu-Gi-Oh!" / "Yu-Gi-Oh! TCG")
  * One Piece (Rank 13, never "One Piece TCG" / "One Piece Card Game")
  * Dragon Ball SCG (industry abbreviation)
  * Gundam TCG (industry abbreviation, never "Gundam Card Game")
- Character name: use the EXACT name from PSA label Subject. Do not shorten, do not alter:
  * "O-Nami" stays "O-Nami" (never "Nami")
  * "Tony Tony Chopper" stays "Tony Tony Chopper" (never "Tony Chopper")
  * "Monkey D. Luffy" stays "Monkey D. Luffy" (never "Luffy")
  * "Roronoa Zoro" stays "Roronoa Zoro" (never "Zoro")
- Set name: use PSA-provided set name (already cleaned of "JAPANESE" prefix)
- Rarity: ONLY if explicit in PSA Subject. Do not invent rarity.
- ANTI-SPAM / FACTS-ONLY RULES:
  * NEVER add "Foil"/"Holo" unless PSA label explicitly states it
  * NEVER add "Promo" unless PSA Subject contains "PROMO"
  * NEVER add generic fillers like "Anime", "Manga", "Collectible"
  * NEVER add unrelated character or franchise names
  * NEVER pad with keywords that are not verifiable facts
- FORBIDDEN WORDS: "Japanese", "GEM MT", "Japan", "Mint", "Graded", "L@@K"
- NEVER duplicate words
- If title is short (e.g. 50 chars), leave it short. A short factual title is better than a long speculative one.

Return ONLY valid JSON:
{{
  "title": "eBay title max 80 chars",
  "card_name": "Clean card name only, no rarity",
  "rarity": "ONLY extract from PSA label Subject suffix: 'ALTERNATE ART' → 'Alternate Art', 'SPECIAL ART' → 'Special Art', 'SECRET' → 'Secret Rare', 'PARALLEL' → 'Parallel', 'MANGA' → 'Manga Rare'. If PSA Subject has no rarity marker, return BLANK - never guess from set/context.",
  "features": "Same value as rarity (or blank if rarity is blank)",
  "card_type": "ONLY if printed on the card image: 'Leader Card' (if card literally says LEADER), 'Character Card', 'Event Card', 'Stage Card'. Blank if not clearly readable.",
  "attribute": "ONLY the color symbol printed on the card ('Red'/'Blue'/'Green'/'Yellow'/'Black'/'Purple'). Blank if not clearly readable.",
  "cost": "ONLY the cost number printed on the card. Blank if Leader Card or not clearly readable.",
  "power": "ONLY the power number printed on the card. For Leader Cards use front-side power only. Blank if not clearly readable.",
  "finish": "DO NOT guess. If the card is not explicitly labeled as Holo/Foil in the PSA label text, leave this field EMPTY. Never infer Finish from rarity or visual appearance. Blank is ALWAYS correct when uncertain."
}}"""

        # メッセージ構築（画像あり/なし）
        user_content = image_content + [{"type": "text", "text": prompt_text}]

        from card_identifier import CLAUDE_MODEL  # モデル名 SSOT (1箇所集約)
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300,
            system="You are a JSON-only response bot. You must always respond with valid JSON only. Never include any explanation, preamble, or text outside the JSON object.",
            messages=[{"role": "user", "content": user_content}]
        )
        text = message.content[0].text.strip()
        text = re.sub(r'^```json\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        if not text:
            print(f"    ⚠️ Claude空レスポンス")
            return None
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            # リトライ：JSONのみを要求する簡略プロンプトで再試行
            print(f"    🔄 JSON失敗→リトライ")
            retry_content = [{"type": "text", "text": f"""Return ONLY a JSON object for this card:
Game: {game}, Set: {set_name}, Card: #{card_number}, Label: {subject}

{{"title":"PSA 10 {game[:15]} {set_name} #{card_number} [card name] [rarity] (max 80 chars)",
"card_name":"clean card name","rarity":"rarity","features":"rarity",
"card_type":"Battle Card or Extra Card","attribute":"color","cost":"number or blank",
"power":"number or blank","finish":"Foil or Non-Foil"}}"""
            }]
            retry_msg = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=300,
                system="Respond with valid JSON only.",
                messages=[{"role": "user", "content": retry_content}]
            )
            retry_text = retry_msg.content[0].text.strip()
            retry_text = re.sub(r'^```json\s*', '', retry_text)
            retry_text = re.sub(r'\s*```$', '', retry_text)
            try:
                result = json.loads(retry_text)
                print(f"    ✅ リトライ成功")
            except json.JSONDecodeError as je:
                print(f"    ⚠️ リトライも失敗: {je}")
                return None

        if len(result.get('title', '')) > 80:
            result['title'] = None
        return result
    except Exception as e:
        print(f"    Claude APIエラー: {e}")
        return None

# CLAUDE.md禁止ワード（大文字小文字無視で除去）
BANNED_TITLE_WORDS = [
    # 2026-05-01: "japanese", "japan" を削除. JP 印刷版を eBay US で売る運用において
    # これらは事実情報 (TOP 競合 11/15 件で使用、SEO 価値高). 旧 ban は SEO スパム
    # ("look"/"wow"/"l@@k"/"gem mt") と一緒くたにしてた誤分類.
    "gem mt", "gem-mt", "gemmt",
    "mint", "graded", "l@@k", "look", "wow", "nr",
]

# pad_titleフィラーとして不適切な機能語・接続詞
TITLE_STOPWORDS = {
    "of", "the", "and", "in", "a", "an", "to", "for",
    "on", "at", "by", "with", "from", "as", "is",
}

def extract_character_name(subject):
    """PSA Subjectから末尾の既知バリアント/レアリティ/イベント接尾辞を剥がして
    純粋なキャラクター名のみを返す。事実ベース: 知らない接尾辞は剥がさない。
    """
    if not subject:
        return subject
    # 末尾から除去する接尾辞パターン（長い順、優先度順）
    suffix_patterns = [
        r'SPECIAL\s+ALTERNATE\s+ART',
        r'ALTERNATE\s+ART',
        r'SPECIAL\s+ART',
        r'SECRET\s+RARE',
        r'MANGA\s+RARE',
        r'LEADER\s+RARE',
        r'LEGEND\s+RARE\+?',
        r'SUPER\s+RARE\+?',
        r'PARALLEL(?:\s+FOIL)?',
        r'\d+\s+PACKS\s+BATTLE[-\s]WINNER',
        r'BATTLE[-\s]WINNER',
        r'ONE\s+PIECE\s+DAY',
        r'BANDAI\s+CARD\s+GAME\s+FEST',
        r'CHAMPIONSHIP',
        # 周年記念 / ガイド付録 (例: "2ND ANV. COMPLETE GUIDE", "3RD ANNIVERSARY COMPLETE GUIDE")
        r'\d+(?:ND|ST|RD|TH)\s+ANV\.?\s+COMPLETE\s+GUIDE',
        r'\d+(?:ND|ST|RD|TH)\s+ANNIVERSARY\s+COMPLETE\s+GUIDE',
        r'\d+(?:ND|ST|RD|TH)\s+ANNIVERSARY',
        r'COMPLETE\s+GUIDE',
        # 2026-05-01: OP01-016 Nami "PROMOTION CARD SET 1" 末尾残存対応.
        r'PROMOTION\s+CARD\s+SET\s+\d+',
        r'PROMO',
        r'HOLO(?:FOIL)?',
        r'FOIL',
    ]
    result = subject
    # 複数接尾辞が連続する場合に備えて複数回適用
    changed = True
    while changed:
        changed = False
        for pat in suffix_patterns:
            new_result = re.sub(r'\s+' + pat + r'\s*$', '', result, flags=re.IGNORECASE)
            if new_result != result:
                result = new_result.strip()
                changed = True
                break
    return result

def extract_variant_from_subject(subject):
    """PSA Subject の末尾からバリアント情報のみを抽出して eBay Features 欄用に返す.
    純粋なレアリティ(Secret Rare, Super Rare等)は含まず、
    バリアント(Alternate Art, Parallel, Full Art)とプロモ系を返す.
    """
    if not subject:
        return ""
    s = subject.upper().strip()
    variant_map = [
        # variants (長い順)
        (r'SPECIAL\s+ALTERNATE\s+ART', 'Alternate Art'),
        (r'ALTERNATE\s+ART', 'Alternate Art'),
        (r'ALT\s+ART', 'Alternate Art'),
        (r'SPECIAL\s+ART', 'Special Art'),
        (r'MANGA\s+RARE', 'Manga'),
        (r'MANGA\s+ART', 'Manga'),
        (r'PARALLEL\s+FOIL', 'Parallel'),
        (r'PARALLEL', 'Parallel'),
        (r'FULL\s+ART', 'Full Art'),
        # Pokemon特有
        (r'MEGA\s+ATTACK\s+RARE', 'Mega Attack Rare'),
        (r'MEGA\s+ATTACK', 'Mega Attack Rare'),
        (r'MEGA\s+ULTRA\s+RARE', 'Mega Ultra Rare'),
        (r'BRIGHT\s+WORLD\s+RARE', 'Bright World Rare'),
        (r'SPECIAL\s+ART\s+RARE', 'Special Art Rare'),
        (r'ART\s+RARE', 'Art Rare'),
        # プロモ/イベント配布
        (r'\d+\s+PACKS\s+BATTLE[-\s]WINNER', 'Promo'),
        (r'BATTLE[-\s]WINNER', 'Promo'),
        (r'ONE\s+PIECE\s+DAY', 'Promo'),
        (r'BANDAI\s+CARD\s+GAME\s+FEST', 'Promo'),
        (r'\d+(?:ND|ST|RD|TH)\s+ANV\.?\s+COMPLETE\s+GUIDE', 'Promo'),
        (r'\d+(?:ND|ST|RD|TH)\s+ANNIVERSARY\s+COMPLETE\s+GUIDE', 'Promo'),
        (r'\d+(?:ND|ST|RD|TH)\s+ANNIVERSARY', 'Promo'),
        (r'COMPLETE\s+GUIDE', 'Promo'),
        (r'CHAMPIONSHIP', 'Promo'),
    ]
    for pat, label in variant_map:
        if re.search(r'(?:^|\s)' + pat + r'(?:\s|$)', s):
            return label
    return ""


def title_preserves_subject(title, subject):
    """タイトルがPSA Subject内の全ての実体トークンを保持しているか検証。
    トークン数(重複含む)もチェック: 'TONY TONY CHOPPER' → 'Tony'が2回必要。
    """
    if not subject:
        return True
    from collections import Counter
    # Subjectをトークン化（区切り: 空白/ハイフン/スラッシュ）
    raw_tokens = [t for t in re.split(r'[\s\-/]+', subject) if t]
    # 実体トークンのみ（長さ2以上、接続詞除外、数字のみ除外）
    connectors = {"of", "the", "and", "in", "a", "an", "to", "for", "on", "at"}
    subject_tokens = [
        t.lower().strip('.,;:')
        for t in raw_tokens
        if len(t) >= 2 and t.lower() not in connectors and not t.isdigit()
    ]
    if not subject_tokens:
        return True

    title_raw = re.split(r'[\s\-/]+', title)
    title_tokens = [t.lower().strip('.,;:') for t in title_raw]
    title_counts = Counter(title_tokens)
    subject_counts = Counter(subject_tokens)
    for tok, needed in subject_counts.items():
        if title_counts.get(tok, 0) < needed:
            return False
    return True

def strip_banned_words(title):
    """CLAUDE.md禁止ワードをタイトルから除去し、空白を正規化"""
    if not title:
        return title
    result = title
    for banned in BANNED_TITLE_WORDS:
        # 単語境界で除去（大文字小文字無視）
        pattern = r'(?i)(?<![A-Za-z])' + re.escape(banned) + r'(?![A-Za-z])'
        result = re.sub(pattern, '', result)
    # セットコード (2-4文字 + 2-3桁数字) をタイトルから除去
    # 例: OP06 / PRB02 / ST18 / EB02 / PBR02(typo) / PBB02(typo)
    # #004 のようなカード番号は "#" 付きなので対象外
    result = re.sub(
        r'(?<!#)\b[A-Z]{2,4}\d{2,3}\b',
        '', result
    )
    # 連続する同一単語を除去
    result = re.sub(r'\b(\w+)(\s+\1\b)+', r'\1', result, flags=re.IGNORECASE)
    # フィラー語の非連続重複を語幹ベースで除去
    # "Promo"/"Promos"/"Card"/"Cards"/"Foil"/"Holo"を同一視して1回だけ残す
    filler_stems = {"promo", "card", "foil", "holo"}
    tokens = result.split()
    seen_stems = set()
    deduped = []
    for tok in tokens:
        key = tok.lower().strip('.,;:').rstrip('s')
        if key in filler_stems:
            if key in seen_stems:
                continue
            seen_stems.add(key)
        deduped.append(tok)
    result = ' '.join(deduped)
    # 余分な空白を正規化
    result = re.sub(r'\s+', ' ', result).strip()
    return result

def pad_title(title, finish="", card_type="", set_name="", target_min=72, target_max=80):
    """短いタイトルを事実ベースのキーワードのみで埋める。
    eBayのKeyword Spamming Policy対策として:
    - 画像から確認できたFinish(Foil/Holo)のみ追加
    - 推測フィラー(Anime/Holo/Foilの盲目追加)はしない
    - 優先: 未使用のSet名語 → Card Type(Leader/Battle/Character Card) → "Card"
    - 埋まらない場合は短いままで返す(虚偽記載より安全)
    """
    if not title or len(title) >= target_min or len(title) > target_max:
        return title

    title_lower = title.lower()
    fillers = []

    # 事実のみポリシー: FinishはClaude視覚推論なので追加しない
    # (finish引数は後方互換のため受け取るが使用しない)

    def _title_stems():
        """タイトル内の単語の語幹(末尾s除去)セットを返す"""
        return {t.lower().rstrip('s').strip('.,;:') for t in title.split() if len(t) >= 3}

    def _is_safe(word):
        """禁止ワード/既存単語(語幹一致含む)でないか確認"""
        wl = word.lower()
        if wl in title_lower:
            return False
        # 語幹マッチ: "Promos" vs "Promo", "Cards" vs "Card"
        stem = wl.rstrip('s')
        if stem in _title_stems():
            return False
        for banned in BANNED_TITLE_WORDS:
            if wl == banned or banned in wl.split():
                return False
        return True

    # 2. Set名の未使用単語を追加（事実情報、純アルファベット＋ストップワード除外）
    # ハイフンも分割して個別評価。数字混じり(OP06等)は既にClaudeが使っている可能性が高いので除外
    if set_name:
        for raw_word in set_name.split():
            for sub in re.split(r'[-/]', raw_word):
                w = sub.strip()
                if (len(w) >= 4 and w.isalpha()
                        and w.lower() not in TITLE_STOPWORDS
                        and _is_safe(w) and w not in fillers):
                    fillers.append(w)

    # 3. Card Type（Leader Card/Battle Card/Character Card等、画像から判定済み）
    ct = (card_type or "").strip()
    if ct and ct.lower() not in title_lower and _is_safe(ct.split()[0] if ct else ""):
        if "card" in ct.lower():
            fillers.append(ct)

    # 4. 最終手段: "Card"（TCGカードは事実カードなのでスパムではない）
    if "card" not in title_lower:
        fillers.append("Card")

    for filler in fillers:
        candidate = f"{title} {filler}"
        if len(candidate) > target_max:
            continue
        title = candidate
        title_lower = title.lower()
        if len(title) >= target_min:
            break
    return title

def build_title(game, set_name, card_number, subject, finish=""):
    """事実ベースタイトル生成: PSAのSubject(キャラ名+rarity)をsmart_titlecaseして使用。
    一切の推論・改変を行わず、PSAが提供する事実のみを並べる。
    """
    # 2026-05-31: 実データ準拠 mapping (= iMakKeywords PDF Q1 2026 検索ランキング)
    # title = バイヤー通称 (= SEO 最大化)、 C:Game = eBay 正規値 (= dropdown hit) の別軸戦略.
    # 詳細: memory:official_x_ebay_filter_max_activation
    game_short = {
        "Pokémon TCG": "Pokemon",                       # Rank 1 (圧倒的最強)
        "Pokemon": "Pokemon",                            # 旧互換
        "Yu-Gi-Oh! TCG": "Yugioh",                       # Rank 19 (= ハイフン/space 無し最強)
        "One Piece CCG": "One Piece",                    # Rank 13 (= TCG suffix なしで節約)
        "One Piece Card Game": "One Piece",              # 旧互換
        "Dragon Ball Super Card Game": "Dragon Ball SCG",  # データ無、慣行略称
        "Gundam Card Game": "Gundam TCG",                # データ無、慣行略称 (= TCG が一般)
    }.get(game, game)

    prefix = "PSA 10"
    subject_tc = smart_titlecase(subject)
    # "Mega X EX Mega Attack" → "Mega X EX" + レアリティ部分を分離してタイトル末尾に
    # 非連続の"Mega"重複を防止
    mega_attack_match = re.search(r'\s+Mega\s+Attack(?:\s+Rare)?$', subject_tc, re.IGNORECASE)
    if mega_attack_match and subject_tc.lower().startswith('mega '):
        # "Mega Scrafty Ex Mega Attack" → subject部分="Mega Scrafty Ex", rarity部分="Mega Attack Rare"
        subject_tc = subject_tc[:mega_attack_match.start()]

    # セット名ありでフルタイトル試行
    title_full = f"{prefix} {game_short} {set_name} #{card_number} {subject_tc}".strip()
    title_full = re.sub(r'\s+', ' ', title_full)
    if len(title_full) <= 80:
        return pad_title(title_full, set_name=set_name)

    # セット名なしで試行
    base = f"{prefix} {game_short} #{card_number} {subject_tc}".strip()
    base = re.sub(r'\s+', ' ', base)
    if len(base) <= 80:
        return pad_title(base, set_name=set_name)

    # それでも長い場合はsubjectを後ろから1単語ずつ削除
    # 注: 削除してもPSAの事実のサブセットであり虚偽にはならない
    parts = subject_tc.split()
    while parts:
        candidate = f"{prefix} {game_short} #{card_number} {' '.join(parts)}"
        if len(candidate) <= 80:
            return pad_title(candidate, set_name=set_name)
        parts.pop()

    return f"{prefix} {game_short} #{card_number}"[:80]

def load_description():
    try:
        with open(DESCRIPTION_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except:
        return "PSA graded card shipped from Japan. Grade and cert number are as listed."


# 商品説明 Specs ブロックのヘルパは新コア(tcg_listing_fields)に集約=SSOT。旧コアも同一を使う
# (新コア override が新値で description を作り直す replace_tcg_specs も同モジュール)。
from tcg_listing_fields import build_tcg_specs_html, insert_tcg_specs  # noqa: E402,F401

def parse_psa_page(text):
    data = {}
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    for i, line in enumerate(lines):
        # "2025 GUNDAM JAPANESE DUAL IMPACT #055 GUNDAM GUSION REBAKE" パターン
        match = re.search(r'^(.+?)\s+#([\w-]+)\s+(.+)$', line)
        if match and any(x in line.upper() for x in ['GUNDAM', 'ONE PIECE', 'DRAGON BALL', 'POKEMON']):
            brand_raw = match.group(1).strip()
            card_number = match.group(2).strip()
            subject_raw = match.group(3).strip()
            # レアリティを除去
            subject = RARITY_PATTERN.sub('', subject_raw).strip()
            # 年号をBrandから除去（例："2025 GUNDAM..." → "GUNDAM..."）
            brand = re.sub(r'^\d{4}\s+', '', brand_raw).strip()
            data['Brand'] = brand
            data['CardNumber'] = card_number  # 文字列のまま保持（006等）
            data['Subject'] = subject

        # 2026-05-27 追加: PSA Japan label 経由 fallback (= DON!! CARD 等 #番号なし card 対応)
        # OP15 cert 156219827 等で発覚、 既存 #XXX regex に hit しない special card 救済
        if line == 'ブランド／タイトル' and i + 1 < len(lines):
            if not data.get('Brand'):
                brand_raw = lines[i + 1].strip()
                data['Brand'] = re.sub(r'^\d{4}\s+', '', brand_raw).strip()
        if line == 'サブジェクト' and i + 1 < len(lines):
            if not data.get('Subject'):
                data['Subject'] = RARITY_PATTERN.sub('', lines[i + 1].strip()).strip()
        if line == 'カード番号' and i + 1 < len(lines):
            if not data.get('CardNumber'):
                data['CardNumber'] = lines[i + 1].strip()

        if line == '発行年' and i + 1 < len(lines):
            try:
                data['Year'] = int(lines[i + 1])
            except:
                data['Year'] = 2025

    return data

PSA_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "psa_cache.json")


def _load_psa_cache():
    if os.path.exists(PSA_CACHE_PATH):
        try:
            with open(PSA_CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _save_psa_cache(cache):
    os.makedirs(os.path.dirname(PSA_CACHE_PATH), exist_ok=True)
    with open(PSA_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def get_psa_data(driver, cert_number):
    # キャッシュチェック
    cache = _load_psa_cache()
    if cert_number in cache:
        cached = cache[cert_number]
        if cached and cached.get('Subject'):
            # iMakeBayAPI 共有 cache にも投入 (= local cache hit でも、 共有 cache 未登録なら書込)
            try:
                import psa_api as _ihq_psa_api
                _ihq_psa_api.save_cache(cert_number, cached)
            except Exception:
                pass
            return cached

    url = f"https://www.psacard.com/ja-JP/cert/{cert_number}/psa"
    try:
        # 5/29: Cloudflare challenge 検知 + 自動 retry (= 最大 3 回、 30 sec 待ち)
        _CF_MARKERS = ("Cloudflare", "セキュリティ検証", "Ray ID", "challenge-platform")
        body = ""
        for _retry in range(3):
            driver.get(url)
            time.sleep(15)  # 5 → 15 sec (= bot 警戒度上昇対策)
            body = driver.find_element(By.TAG_NAME, "body").text
            if not any(_m in body for _m in _CF_MARKERS):
                break  # challenge 通った
            print(f"\n    🛡️ Cloudflare challenge 検知 (retry {_retry + 1}/3)、 30 sec 待機...")
            time.sleep(30)
        else:
            # 3 retry 全部 challenge = warmup driver の cookie 失効
            print(f"    ❌ Cloudflare challenge 抜けられず、 warmup driver の cookie refresh が必要")
            return None

        # カード画像URL取得 (= 表/裏 2 枚、 2026-06-01 ユーザー要望)
        # PicURL 構成: 表(front) | 裏(back) | 999.png (= 既存ダミー)
        card_image_urls = []  # = [front_url, back_url] 順序 (= PSA page DOM 表示順 = 表→裏想定)
        try:
            imgs = driver.find_elements(By.TAG_NAME, "img")
            for img in imgs:
                src = img.get_attribute("src") or ""
                if not src.startswith("http"):
                    continue
                if not any(x in src.lower() for x in ['cert', 'card', 'psa', 'grading']):
                    continue
                if src in card_image_urls:
                    continue
                card_image_urls.append(src)
                if len(card_image_urls) >= 2:
                    break
        except Exception as e:
            print(f"\n    画像取得エラー: {e}")

        data = parse_psa_page(body)
        if card_image_urls:
            data['CardImageUrl'] = card_image_urls[0]   # = 表面 (= 既存 title 生成等で使用)
            data['CardImageUrlFront'] = card_image_urls[0]
            if len(card_image_urls) >= 2:
                data['CardImageUrlBack'] = card_image_urls[1]
                print(f"    📷 PSA 画像 表+裏 取得 (2 枚)")
            else:
                print(f"    📷 PSA 画像 表のみ取得 (1 枚)")
        if not data.get('Subject'):
            print(f"\n    [DEBUG] {body[:400]}")
            return None

        # キャッシュに保存 (= ローカル既存)
        cache[cert_number] = data
        _save_psa_cache(cache)
        # iMakeBayAPI 共有 cache にも書込 (= 重複くん が cert 単位 read、 SoC + 内部 SSOT)
        try:
            import psa_api as _ihq_psa_api
            _ihq_psa_api.save_cache(cert_number, data)
        except Exception:
            pass  # fail-closed (= 共有 cache 失敗で既存 cycle 止めない)
        return data
    except Exception as e:
        print(f"    Error: {e}")
        return None


# ===== Dragon Ball / Gundam カードID構築 =====
# PSA Brand内のセット名 → Bandai TCG+ カード番号プレフィックス
ENERGY_MARKER_DB = {
    # Fusion World Energy Marker (E01 シリーズ)
    # Bandai TCG+ API のスコープ外 (Booster/Starter とは別カテゴリ管理)
    # → ハードコード対応。物理カードの色は PSA Subject に出ないため Color は空欄、
    #    eBay 出品時はユーザーが目視確認のうえ手動補完する運用
    f"E01-{i:02d}": {
        "card_name": "Energy Marker",
        "card_number": f"E01-{i:02d}",
        "card_type": "Energy Marker",
        "rarity": "Common",
        "color": "",  # 物理確認必須
        "power": "",
        "cost": "",
        "set_name": "Energy Marker Pack 01",
        "source": "hardcoded",
    } for i in range(1, 16)
}


DRAGONBALL_SET_PREFIX = {
    "AWAKENED PULSE": "FB01",
    "BLAZING AURA": "FB02",
    "RAGING ROAR": "FB03",
    "FUSION SURGE": "FB04",
    "RISING SPARK": "FB05",
    # Manga Booster
    "MANGA BOOSTER": "SB01",
    "MANGA BOOSTER 02": "SB02",
    # Starter
    "STARTER DECK": "FS",
}

GUNDAM_SET_PREFIX = {
    # 2026-04-24 修正: DUAL IMPACT を GD01 → GD02 に訂正（Bandai TCG+ 実DB検証済）
    # GD02-069=Zeta Gundam, GD02-072=Hyaku-Shiki 等が Dual Impact 収録と判明。
    # 旧マッピングで GD01 に誤誘導された結果、PSA "DUAL IMPACT" のカードが
    # 別カード（Strike Rouge, Launcher Strike Gundam 等）の Item Specifics を引いていた（SNAD直結）。
    "NEWTYPE RISING": "GD01",
    "DUAL IMPACT":    "GD02",
    # 以下は未検証: 実DB突き合わせしていない推測マッピング（次セッション要検証）
    "STEEL REQUIEM":     "GD02",
    "HEROIC BEGINNINGS": "GD02",
    "WINGS OF ADVANCE":  "GD03",
    "SEED STRIKE":       "GD03",
    "IRON BLOOM":        "GD04",
}


def _dragonball_card_id(brand, card_number):
    """PSA BrandとCardNumberからBandai TCG+用のcard_id(FB03-139形式)を構築.

    優先順位:
    1) card_number が prefix 含む完全形 (例: FS09-16, FP-024) → 直接構築
       - PSA cert の CardNumber 列は parse_psa_page (regex `#([\\w-]+)`) で完全形が入る
    2) Brand から prefix を引く (旧フォールバック、card_number が番号のみの稀ケース用)
    """
    if not card_number:
        return None
    # Priority 1: card_number 完全形 (FB##/SB##/FS##/GB##/FP/E## + ハイフン + 数字)
    m = re.match(r'^(FB\d+|SB\d+|FS\d+|GB\d+|FP|E\d+)-(\d+)$', card_number.upper())
    if m:
        prefix, num = m.group(1), m.group(2)
        # Bandai TCG+ API のID形式:
        #   FB/SB/GB (booster系): 3桁 zero-pad (FB01-039)
        #   FS (Starter Deck) / FP (Promo) / E## (Energy): zero-pad 無し (FS09-16, FP-024, E01-11)
        if prefix.startswith(("FB", "SB", "GB")):
            return f"{prefix}-{num.zfill(3)}"
        return f"{prefix}-{num}"
    # Priority 2: Brand から prefix 引く (フォールバック)
    if not brand:
        return None
    b = brand.upper()
    # 長いキーを優先 (MANGA BOOSTER 02 > MANGA BOOSTER の誤マッチ防止)
    for set_name in sorted(DRAGONBALL_SET_PREFIX.keys(), key=len, reverse=True):
        if set_name in b:
            return f"{DRAGONBALL_SET_PREFIX[set_name]}-{card_number.zfill(3)}"
    return None


def _gundam_card_id(brand, card_number):
    """PSA BrandとCardNumberからBandai TCG+用のcard_id(GD01-001形式)を構築"""
    if not brand or not card_number:
        return None
    b = brand.upper()
    for set_name, prefix in GUNDAM_SET_PREFIX.items():
        if set_name in b:
            return f"{prefix}-{card_number.zfill(3)}"
    m = re.match(r'(GD\d+)-?(\d+)', card_number)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(3)}"
    return None


# 2026-04-26: ONE PIECE Item Specifics 整形 = iMakCatalog ebay_filter_map に集約
# (旧 _onepiece_rarity_to_ebay / _ONEPIECE_SET_NAME_MAP / _onepiece_set_code_to_name は削除済)
# → iMakCatalog/ebay_filter_map/one_piece.yaml + integrations/psa_to_csv.py を参照


# 2026-04-26: DRAGON BALL SCG セット名 → eBay フィルタ表示用クリーンアップ
# Bandai TCG+ API は "BOOSTER PACK -AWAKENED PULSE- [FB01]" のような生表記を返すが
# eBay の C:Set フィルタは Title Case の短縮名 (例: "Awakened Pulse") を要求。
# 完全一致マップ + 汎用クリーンアップ (角括弧除去 + ハイフン区切り部分抽出 + Title Case) のフォールバック。
_DRAGONBALL_SET_NAME_MAP = {
    # Booster Pack
    "BOOSTER PACK -AWAKENED PULSE- [FB01]": "Awakened Pulse",
    "BOOSTER PACK -BLAZING AURA- [FB02]":   "Blazing Aura",
    "BOOSTER PACK -RAGING ROAR- [FB03]":    "Raging Roar",
    "BOOSTER PACK -FUSION SURGE- [FB04]":   "Fusion Surge",
    "BOOSTER PACK -RISING SPARK- [FB05]":   "Rising Spark",
    "BOOSTER PACK -PERFECT COMBINATION- [FB06]": "Perfect Combination",
    "BOOSTER PACK -ULTRA LIMIT- [FB07]":    "Ultra Limit",
    "BOOSTER PACK -SECRET OF EVOLUTION- [FB08]": "Secret of Evolution",
    "BOOSTER PACK -DESTINED RIVALS- [FB09]": "Destined Rivals",
    # Manga Booster
    "MANGA BOOSTER 02 [SB02]":              "Manga Booster 02",
    "MANGA BOOSTER 01 [SB01]":              "Manga Booster 01",
    "MANGA BOOSTER -CRITICAL BLOW- [SB02]": "Critical Blow",
    # Starter Deck
    "STARTER DECK SAIYAN GENESIS [FS01]":   "Starter Deck Saiyan Genesis",
    "STARTER DECK BUDOKAI WARRIORS [FS02]": "Starter Deck Budokai Warriors",
    "STARTER DECK PERFECTION [FS03]":       "Starter Deck Perfection",
    "STARTER DECK FRIEZA [FS04]":           "Starter Deck Frieza",
    "STARTER DECK ANDROIDS [FS05]":         "Starter Deck Androids",
    "STARTER DECK PIRATES [FS06]":          "Starter Deck Pirates",
    "STARTER DECK ULTIMATE WARRIORS [FS07]": "Starter Deck Ultimate Warriors",
    "STARTER DECK MAJIN BUU [FS08]":        "Starter Deck Majin Buu",
    "STARTER DECK EX SHALLOT [FS09]":       "Starter Deck EX Shallot",
}


def _strip_variant_from_character(name):
    """キャラ名からバリアント識別子を剥がす (Bandai TCG+ API は 'Son Goku (Mini) : DA' 等を返す).

    Character フィールドは「キャラクター」が本義なので、バリアント情報 (括弧書き、': XX' 接尾辞)
    を除去して純粋なキャラ名のみにする。
    例:
        'Son Goku (Mini) : DA' → 'Son Goku'
        'Vegito : SH'          → 'Vegito'
        'Boa Hancock'          → 'Boa Hancock' (変化なし)
        'Majin Buu : Kid'      → 'Majin Buu'
    """
    if not name:
        return name
    # 括弧 (...) を除去
    clean = re.sub(r'\s*\([^)]*\)\s*', ' ', name)
    # 「: XX」以降を除去
    clean = re.sub(r'\s*:\s*.+$', '', clean)
    return clean.strip()


def _strip_known_set_suffix(name, set_name):
    """character/card_name 末尾に残った「既知の set 名」を実 set 名で決定論的に除去する。

    Pokemon の character/card_name は PSA Subject を denylist で削って作るため、未登録の
    新 set 名が末尾に残る (例 'Togekiss V Legendary Heartbeat' / 'Corviknight Vmax Vmax Climax')。
    set 名は別途 catalog から確定済 (C:Set 列が持つ) ので、それを末尾から剥がせば denylist 漏れを根絶できる。
    例: ('Togekiss V Legendary Heartbeat', 'Legendary Heartbeat') → 'Togekiss V'
        ('Corviknight Vmax Vmax Climax',   'VMAX Climax')        → 'Corviknight Vmax'
    """
    if not name or not set_name:
        return name
    pat = r"\s+" + re.escape(set_name.strip()) + r"\s*$"
    cleaned = re.sub(pat, "", name, flags=re.IGNORECASE).strip()
    return cleaned or name  # 全消え (set名=name 異常) は元を維持


def _build_card_name(character_clean, subject, original_name=""):
    """eBay C:Card Name 値を構築 (キャラ名 + Subject 派生バリアント識別子).

    Args:
        character_clean: 純キャラ名 (バリアント剥離済)
        subject: PSA Subject (例: 'BOA HANCOCK ALTERNATE ART')
        original_name: bandai TCG+ から来た元の name (例: 'Son Goku (Mini) : DA')
                       これに括弧/: 接尾辞があれば優先採用

    Returns: 'Boa Hancock (Alternate Art)' 等
    """
    if not character_clean:
        return original_name or ""
    # original_name に括弧/: 接尾辞 (バリアント識別子) があれば優先採用
    if original_name and (re.search(r'\([^)]+\)', original_name) or ':' in original_name):
        return original_name
    if not subject:
        return character_clean
    su = subject.upper()
    # PSA Subject から派生バリアント識別子を抽出 (1個だけ)
    variants = []
    for kw, label in [
        ("SPECIAL ALTERNATE ART", "Special Alternate Art"),
        ("SPARKLE FOIL",          "Sparkle Foil"),
        ("ALTERNATE ART",         "Alternate Art"),
        ("ALT ART",               "Alternate Art"),
        ("SPECIAL ART",           "Special Art"),
        ("BLACK & WHITE",         "Black & White"),
        ("PARALLEL",              "Parallel"),
    ]:
        if kw in su:
            variants.append(label)
            break
    if variants:
        return f"{character_clean} ({variants[0]})"
    return character_clean


def _dragonball_set_name_to_ebay(raw_set_name):
    """Dragon Ball SCG セット名を eBay フィルタ用にクリーンアップ.
    1) 完全一致マップを最優先
    2) フォールバック: 角括弧除去 + Title Case 化
    """
    if not raw_set_name:
        return raw_set_name
    if raw_set_name in _DRAGONBALL_SET_NAME_MAP:
        return _DRAGONBALL_SET_NAME_MAP[raw_set_name]
    # フォールバック: [XX99] 角括弧部分を除去 + Title Case
    cleaned = re.sub(r'\s*\[[^\]]+\]\s*$', '', raw_set_name).strip()
    # ハイフンで囲まれた中身があれば抽出 (例: "BOOSTER PACK -XXX-" → "XXX")
    m = re.search(r'-([^-]+)-', cleaned)
    if m:
        cleaned = m.group(1).strip()
    return cleaned.title() if cleaned.isupper() else cleaned


# 2026-04-26: 旧 _onepiece_set_to_ebay 削除 (iMakCatalog adapter が代替)


# ===== Pokemon Item Specifics整形 =====
POKEMON_SET_NAME_MAP = {
    "M2A-MEGA DREAM EX": "M2a: High Class Pack: Mega Dream Ex",
    "M2A": "M2a: High Class Pack: Mega Dream Ex",
    # 2026-05-01 18:46 観測: PSA brand "POKEMON GO JAPANESE" → fallback で "Go Japanese"
    # になり eBay 公式フィルタ値 "Pokémon GO" と乖離. dict 経由で正規化.
    "GO JAPANESE": "Pokémon GO",
    # 今後追加
}


def _pokemon_set_name(brand):
    """PSAブランドからeBay用セット名を生成。
    例: 'POKEMON JAPANESE M2A-MEGA DREAM EX' → 'M2a: High Class Pack: Mega Dream Ex'
    """
    if not brand:
        return brand
    b = brand.upper()
    for prefix in ["POKEMON JAPANESE ", "POKEMON "]:
        if b.startswith(prefix):
            short = brand[len(prefix):]
            for key, ebay_name in POKEMON_SET_NAME_MAP.items():
                if key in short.upper():
                    return ebay_name
            return smart_titlecase(short)
    return brand


def _pokemon_card_name(subject):
    """PSA SubjectからCard Name (eBay用) を生成。
    例: 'MEGA SCRAFTY EX MEGA ATTACK' → 'Mega Scrafty EX'
         'FA/UMBREON VMAX EEVEE HEROES' → 'Umbreon Vmax'
         'HO-OH V INCANDESCENT ARCANA' → 'Ho-Oh V'

    2026-05-01: list 拡張で Pokemon set 名 + rarity prefix を吸収.
    refine_title が character を append する際の汚染源 (Card Name に set 名混入)
    を上流で解消し、title 二重化 + Fa/ 残存を防止する.
    """
    if not subject:
        return subject
    s = subject.strip()
    # patterns: rarity prefix (^FA/, ^AR/ etc.) + rarity suffix + set 名 suffix.
    # 既存挙動互換: 全て re.sub(IGNORECASE) で 1 ループ適用、順序は長い順.
    strip_patterns = [
        # Pokemon rarity prefix (PSA Subject 先頭の rarity 略号、'FA/UMBREON' 等)
        r'^(?:FA|AR|SAR|SR|UR|HR|MR|PR)/+',

        # Rarity suffix (既存)
        r'\s+MEGA\s+ATTACK\s+RARE$',
        r'\s+MEGA\s+ATTACK$',
        r'\s+MEGA\s+ULTRA\s+RARE$',
        r'\s+BRIGHT\s+WORLD\s+RARE$',
        r'\s+SPECIAL\s+ART\s+RARE$',
        r'\s+SPECIAL\s+ART$',
        r'\s+ART\s+RARE$',
        r'\s+ULTRA\s+RARE$',
        r'\s+RARE$',

        # 2026-05-01: Pokemon set 名 suffix (Subject 末尾の set 名残存対応).
        # Card Name/Character は character のみで set 名は C:Set 列が持つ → 重複解消.
        r'\s+INCANDESCENT\s+ARCANA$',
        r'\s+EEVEE\s+HEROES$',
        r'\s+SHINY\s+STAR\s+V$',
        r'\s+DARK\s+PHANTASMA$',
        r'\s+VSTAR\s+UNIVERSE$',
        r'\s+WILD\s+FORCE$',
        r'\s+SHINY\s+TREASURE\s+EX$',
        r'\s+MEGA\s+DREAM\s+EX$',
        r'\s+POKEMON\s+GO$',
        # 2026-05-01 18:46 観測: REMIX BOUT 追加 (cert 137607102 Psyduck Remix Bout 重複対応)
        r'\s+REMIX\s+BOUT$',
        # rarity 単語 suffix ('GENGAR EX SUPER' → 'GENGAR EX')
        r'\s+SUPER$',
    ]
    result = s
    for pat in strip_patterns:
        result = re.sub(pat, '', result, flags=re.IGNORECASE)
    return smart_titlecase(result.strip())


def _pokemon_character_name(subject):
    """PSA SubjectからCharacter名を生成。
    ポケモンカード: 'MEGA SCRAFTY EX MEGA ATTACK' → 'Scrafty'
    トレーナーカード: 'IRIS'S FIGHTING SPIRIT SPECIAL ART' → 'Iris'
    """
    card_name = _pokemon_card_name(subject)
    if not card_name:
        return card_name
    # ポケモンカード: Mega/EX除去
    name = re.sub(r'^Mega\s+', '', card_name, flags=re.IGNORECASE)
    name = re.sub(r'\s+EX$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+ex$', '', name)
    # トレーナーカード: "'s ..." パターン → 所有者名だけ抽出
    # "Iris's Fighting Spirit" → "Iris"
    poss_match = re.match(r"^(\w+)'s\s+", name)
    if poss_match:
        name = poss_match.group(1)
    return name.strip()


def _load_cert_overrides():
    """cert_overrides.json を読み込む (失敗時は空 dict)。
    キー '_README' は仕様メタなので除外して返す。
    """
    import os as _os
    p = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "cert_overrides.json")
    if not _os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if k != "_README"}
    except Exception as _e:
        print(f"⚠️ cert_overrides.json 読込失敗: {_e}")
        return {}


def _build_pic_url(data):
    """eBay CSV PicURL = 表 | 裏 | 999.png (= 2026-06-01 ユーザー要望).

    PSA cert page から取得した front/back 画像を順序保持で組立.
    取得失敗時は fallback (= 既存 PIC_URL のみ).
    """
    parts = []
    if data:
        f = data.get("CardImageUrlFront")
        b = data.get("CardImageUrlBack")
        if f:
            parts.append(f)
        if b and b != f:
            parts.append(b)
    parts.append(PIC_URL)
    return "|".join(parts)


# 2026-06-09: 短タイトル(<70)を catalog の実ファクトだけで補強 (year/rarity/set code)。
# 捏造しない: facts が無ければ伸ばさない。refine_title の後 (= 短縮されない最終段) で適用。
_RARITY_FULL_FOR_TITLE = {"AR": "Art Rare", "SR": "Super Rare", "SAR": "Special Art Rare"}
# catalog rarity short code → eBay Features 値 (TOPセラーは rarity descriptor を Features に入れる慣習)。
# Features が variant/PSA Subject から取れない時のフォールバック (= 実属性、捏造でない)。
_RARITY_TO_FEATURES = {
    "AR": "Art Rare", "SR": "Super Rare", "SAR": "Special Art Rare",
    "UR": "Ultra Rare", "HR": "Hyper Rare", "MA": "Mega Attack Rare",
    "RR": "Double Rare", "RRR": "Triple Rare", "SSR": "Shiny Super Rare",
}


def _pad_title_with_facts(title, year, rarity_short, set_code, target_min=70, max_chars=80):
    """short title を catalog 実ファクト (年/レアリティ全名/set code) で補強。
    TOPセラー頻出語 (2025 / Super Rare / M1S 等) と一致。値が無ければ足さない (捏造なし)。"""
    if not title or len(title) >= target_min:
        return title
    tl = title.lower()
    facts = []
    y = str(year).strip() if year is not None else ""
    if y.isdigit() and len(y) == 4 and y not in title:   # 実 PSA Year のみ (default 補完はしない)
        facts.append(y)
    rf = _RARITY_FULL_FOR_TITLE.get((rarity_short or "").upper().strip())
    if rf and rf.lower() not in tl:
        facts.append(rf)
    if set_code and set_code.lower() not in tl:
        facts.append(set_code)
    for f in facts:
        cand = f"{title} {f}"
        if len(cand) <= max_chars:
            title = cand
            tl = title.lower()
        if len(title) >= target_min:
            break
    return title


def build_row(cert_number, price, data, description, driver=None, catalog_misses=None):
    subject = data.get('Subject', 'Unknown')
    card_number = data.get('CardNumber', '')
    brand = data.get('Brand', '')
    year = data.get('Year', 2025)

    # ===== cert_overrides.json による特別処理 =====
    # 公式DB lookup が誤マッチ/未対応の cert に対する手動補完
    # 既存ロジックは触らず、overrides 由来の値を上書きで採用
    _OVERRIDES = _load_cert_overrides()
    _override = _OVERRIDES.get(str(cert_number))
    _override_applied = False
    if _override:
        if _override.get("skip"):
            msg = _override.get("skip_message", "overrides で skip 指定")
            print(f"    ⏭️ Skip (overrides): {msg}")
            return None
        if _override.get("skip_official_lookup"):
            _override_applied = True
            print(f"    📌 Override 適用: {_override.get('reason', '理由未記入')}")

    # ===== 画像主導カード特定 (新ルーチン、独立モジュール) =====
    # card_identifier.identify_from_image を試行。confidence high/medium なら
    # 既存 lookup の前に official_* を上書き (「特定」のみ、「推測」はしない)。
    # 失敗 (low/failed) 時は既存ロジック (Bandai名前検索 等) にフォールバック。
    # ロールバック: この import & if ブロックをコメントアウトすれば完全に元に戻る。
    _vision_result = None
    if data.get('CardImageUrl') and not _override_applied:
        try:
            from card_identifier import identify_from_image as _identify
            _vision_result = _identify(
                cert_number=cert_number,
                image_url=data.get('CardImageUrl', ''),
                psa_brand=brand,
                psa_subject=data.get('Subject', ''),
            )
        except Exception as _e:
            print(f"    ⚠️ card_identifier 呼出失敗: {type(_e).__name__}: {_e}")
            _vision_result = None
        # ===== カード特定推論エージェント (新ルーチン、独立) =====
        # Vision 結果を PSA cert (公式記録) で補正。card_number 数字不一致時は
        # PSA 信頼で合成 card_number 生成 (Vision 誤読の構造的防御)。
        # ロールバック: この try/except ブロックをコメントアウトで完全復元。
        try:
            from card_identification_agent import correct_vision_result_with_psa
            _vision_result = correct_vision_result_with_psa(_vision_result, data)
        except Exception as _e:
            print(f"    ⚠️ identification_agent 失敗: {type(_e).__name__}: {_e}")
            # _vision_result は元のまま、既存挙動継続

    card_number = str(card_number)  # ゼロ埋め保持
    # 2026-05-28 variant_meta 連動用 初期化 (= 各 franchise hit block で値設定、 末尾で連動)
    _catalog_pid_for_variant = None
    _catalog_category_for_variant = None
    game, set_name, franchise = detect_game_info(brand)

    # 2026-06-12: 遊戯王は現在 出品対象外 (ユーザー指示で当面 SKIP)。
    # 理由: catalog が日本版遊戯王を未収録 (= 候補が英語版のみで正カードに当たらない)。
    # 準備が整ったらユーザーが解除指示する。catalog 側の日本版収録は別途依頼済。
    if franchise == "Yu-Gi-Oh!":
        print(f"    ⏭️ Skip: 遊戯王は現在出品対象外 (cert {cert_number}, {subject})")
        return None

    # Character欄はPSA Subjectから接尾辞を剥がして純キャラ名のみに (fallback)
    character = smart_titlecase(extract_character_name(subject))

    # 公式データベースからItem Specificsを取得
    # 優先順位: 公式DB > Claude API > 空
    official_card_type = ""
    official_rarity = ""
    official_color = ""
    official_power = ""
    official_cost = ""
    official_attribute = ""
    official_card_number = card_number
    official_illustrator = ""
    official_finish = ""
    official_card_size = ""  # 2026-05-31: adapter から取得 (= 全 franchise block で set 試行)

    # overrides 適用時: 公式DB lookup を完全スキップして overrides の specs を直接採用
    if _override_applied:
        _ov_specs = _override.get("specs", {})
        official_card_type  = _ov_specs.get("card_type", "")
        official_rarity     = _ov_specs.get("rarity", "")
        official_color      = _ov_specs.get("color", "")
        official_power      = str(_ov_specs.get("power", "")) if _ov_specs.get("power") not in (None, "") else ""
        official_cost       = str(_ov_specs.get("cost", "")) if _ov_specs.get("cost") not in (None, "") else ""
        official_attribute  = _ov_specs.get("attribute", "")
        if _ov_specs.get("set_name"):
            set_name = _ov_specs["set_name"]
        if _ov_specs.get("card_number"):
            official_card_number = _ov_specs["card_number"]
        if _ov_specs.get("character"):
            character = _ov_specs["character"]
        # franchise 別分岐 (Pokemon等) をスキップしているので card_name 系を最低限初期化
        # Pokemon 経路: subject 由来の名前を試行、失敗時は character で代替
        if franchise == "Pokemon":
            game = "Pokémon TCG"
            try:
                card_name = _pokemon_card_name(subject) or character
            except Exception:
                card_name = character
        else:
            card_name = character
    elif franchise == "One Piece":
        # iMakCatalog DB lookup (Phase 1: bandai_jp.py から移行).
        # ID 完全一致のみ、フォールバック禁止 (PRB02-005 / ST16-005 事故再発防止).
        # eBay フィルタ値変換 (set_name / rarity) は adapter が ebay_filter_map で実行済み.
        bandai = catalog_psa.lookup_one_piece(brand, card_number, subject)
        # ===== iMakCatalog 戻り値の eBay US 向け正規化 (新ルーチン、独立) =====
        # JP→EN 翻訳 (キャラクター→Character / 赤→Red / モンキー・D・ルフィ→Monkey D. Luffy)
        # + ピリオド連結補正 (Monkey.D.Luffy → Monkey D. Luffy)
        # ロールバック: この try/except ブロックをコメントアウトで完全復元.
        try:
            from catalog_localization import localize_catalog_record
            bandai = localize_catalog_record(bandai)
        except Exception as _e:
            print(f"    ⚠️ catalog_localization 失敗: {type(_e).__name__}: {_e}")
            # bandai は元のまま、既存挙動継続
        if bandai:
            character = bandai.get("name_en") or character
            official_card_type = bandai.get("type_en", "")
            official_rarity = bandai.get("rarity_en", "")     # 既に eBay 形式 (SR/C/L→空)
            official_color = bandai.get("color_en", "")
            official_power = bandai.get("power", "")
            official_cost = bandai.get("life_or_cost", "")
            official_attribute = bandai.get("attribute_en", "")
            # Card Number: variant suffix (_p1 / _ST28 / _EB02_LF 等) を全部剥がす
            bandai_card_id = bandai.get("card_id", "")
            if bandai_card_id:
                official_card_number = re.sub(r'_.+$', '', bandai_card_id)
            # Set: adapter が ebay_filter_map で変換済み
            if bandai.get("set_name_ebay"):
                set_name = bandai["set_name_ebay"]
            # 2026-05-31: adapter 経由 finish / card_size を listing に反映
            # game = build_row line 502-505 で "One Piece CCG" (= eBay 正規値) 採用済
            # 検索 query 副作用は check_csv._normalize_game_short / market_gate に "One Piece CCG":"One Piece" 追加で吸収
            official_finish = bandai.get("finish") or ""
            official_card_size = bandai.get("card_size") or ""
        elif catalog_misses is not None:
            catalog_misses.append(("one_piece_tcg", f"{brand}-{card_number}"))
        # iMakCatalog miss → Vision に委ねる (fallback 構築は廃止、PSA Brand "P" + 番号
        # で誤った P-XXX を作ってしまい Vision の正値を遮断していた問題を解消)

    elif franchise == "Pokemon":
        # Pokemon共通（公式ヒット有無にかかわらず設定）
        game = "Pokémon TCG"
        set_name = _pokemon_set_name(brand)
        character = _pokemon_character_name(subject)
        card_name = _pokemon_card_name(subject)

        # iMakCatalog DB lookup (Phase 2b: pokemon_card_jp.fetch_card_with_subject から移行).
        # ID 完全一致のみ、フォールバック禁止 (Pokemon 13件全滅事故再発防止).
        pokemon = catalog_psa.lookup_pokemon(brand, card_number, subject)
        if pokemon:
            official_rarity = pokemon.get("rarity", "")
            official_power = pokemon.get("hp", "")
            # 2026-05-31: adapter 経由 finish / card_size を listing に反映 (game は rollback)
            official_finish = pokemon.get("finish") or ""
            official_card_size = pokemon.get("card_size") or ""
            # card_type: scraper が specs.card_type に Pokémon/Trainer/Energy を保存済
            official_card_type = pokemon.get("card_type", "")
            official_attribute = pokemon.get("type_en", "")
            official_illustrator = pokemon.get("illustrator") or ""
            if pokemon.get("card_number_full"):
                official_card_number = pokemon["card_number_full"]
            # set: adapter が ebay_filter_map で変換済み
            if pokemon.get("set_name_ebay"):
                set_name = pokemon["set_name_ebay"]
            # 2026-05-28 variant_meta 連動用 (= Features/Finish/Rarity 自動補完)
            _catalog_pid_for_variant = pokemon.get("card_id")
            _catalog_category_for_variant = "pokemon_tcg"
        elif catalog_misses is not None:
            catalog_misses.append(("pokemon_tcg", f"{brand}-{card_number}"))

        # 整合(先手): 確定した set 名を character/card_name 末尾から除去。
        # denylist 漏れ (Togekiss V Legendary Heartbeat / Corviknight Vmax Vmax Climax 型) の根本対策。
        character = _strip_known_set_suffix(character, set_name)
        card_name = _strip_known_set_suffix(card_name, set_name)

    elif franchise == "Dragon Ball":
        # Dragon Ball Fusion World — iMakCatalog DB lookup (Phase 2: bandai_tcg_plus から移行).
        # 例外パス: Energy Marker (E##-##) は Bandai TCG+ API 対象外なのでハードコード DB を維持.
        game = "Dragon Ball Super Card Game"
        db_card_id = _dragonball_card_id(brand, card_number)
        db_card = None
        if db_card_id and db_card_id in ENERGY_MARKER_DB:
            # Energy Marker は ENERGY_MARKER_DB (ハードコード) 経由
            db_card = ENERGY_MARKER_DB[db_card_id]
            print(f"    🎯 Energy Marker DB (hardcoded): {db_card_id}")
            print(f"    ⚠️ Color は物理カード確認後に手動補完してください")
            if db_card:
                official_card_type = db_card.get("card_type", "")
                official_rarity = db_card.get("rarity", "")
                official_color = db_card.get("color", "")
                official_power = db_card.get("power", "")
                official_cost = db_card.get("cost", "")
                official_card_number = db_card.get("card_number", card_number)
                if db_card.get("set_name"):
                    set_name = db_card["set_name"]
                if db_card.get("card_name"):
                    character = db_card["card_name"]
        else:
            # 通常カード: iMakCatalog DB lookup
            db_card = catalog_psa.lookup_dragonball(brand, card_number, subject)
            if db_card:
                official_card_type = db_card.get("card_type", "")
                official_rarity = db_card.get("rarity", "")     # 既に eBay 形式
                official_color = db_card.get("color", "")
                official_power = db_card.get("power", "")
                official_cost = db_card.get("cost", "")
                # variant suffix を剥がした card_number
                db_full_id = db_card.get("card_id", "")
                if db_full_id:
                    official_card_number = re.sub(r'_.+$', '', db_full_id)
                if db_card.get("set_name_ebay"):
                    set_name = db_card["set_name_ebay"]
                if db_card.get("card_name"):
                    character = db_card["card_name"]
                # 2026-05-31: adapter 経由 finish / card_size を listing に反映 (game は rollback)
                official_finish = db_card.get("finish") or ""
                official_card_size = db_card.get("card_size") or ""
            elif catalog_misses is not None:
                catalog_misses.append(("dragonball_scg", f"{brand}-{card_number}"))

    elif franchise == "Gundam":
        # iMakCatalog DB lookup (Phase 2: bandai_tcg_plus.fetch_card から移行).
        # ID 完全一致のみ + 名前検証. eBay フィルタ値変換は adapter で済.
        gd_card = catalog_psa.lookup_gundam(brand, card_number, subject)
        if gd_card:
            official_card_type = gd_card.get("card_type", "")
            official_rarity = gd_card.get("rarity", "")     # 既に eBay 形式
            official_color = gd_card.get("color", "")
            official_power = gd_card.get("power", "")
            official_cost = gd_card.get("cost", "")
            # variant suffix を剥がした card_number
            gd_card_id = gd_card.get("card_id", "")
            if gd_card_id:
                official_card_number = re.sub(r'_.+$', '', gd_card_id)
            if gd_card.get("set_name_ebay"):
                set_name = gd_card["set_name_ebay"]
            if gd_card.get("card_name"):
                character = gd_card["card_name"]
            # 2026-05-31: adapter 経由 finish / card_size を listing に反映 (game は rollback)
            official_finish = gd_card.get("finish") or ""
            official_card_size = gd_card.get("card_size") or ""
        elif catalog_misses is not None:
            catalog_misses.append(("gundam_tcg", f"{brand}-{card_number}"))

    elif franchise == "Yu-Gi-Oh!":
        ygo = catalog_psa.lookup_yugioh(brand, card_number, subject)
        if ygo:
            try:
                _raw_specs = ygo.get("specs")
                if isinstance(_raw_specs, str):
                    ygo_specs = json.loads(_raw_specs) if _raw_specs else {}
                else:
                    ygo_specs = _raw_specs or {}
            except Exception:
                ygo_specs = {}
            if ygo.get("name_en"):
                character = ygo["name_en"]
                card_name = ygo["name_en"]
            official_card_type = ygo_specs.get("type", "") or ygo_specs.get("humanReadableCardType", "")
            official_rarity = ygo_specs.get("primary_set_rarity", "")
            official_attribute = ygo_specs.get("attribute", "")
            atk_val = ygo_specs.get("atk")
            if atk_val is not None and atk_val != "":
                official_power = str(atk_val)
            primary_set = ygo_specs.get("primary_set_name", "")
            if primary_set:
                set_name = primary_set
            # 2026-05-31: adapter 経由 finish / card_size を listing に反映 (game は rollback)
            official_finish = ygo.get("finish") or ""
            official_card_size = ygo.get("card_size") or ""
        elif catalog_misses is not None:
            catalog_misses.append(("yugioh_tcg", f"{brand}-{card_number}"))

    # ===== 画像主導カード特定の結果を反映 (新ルーチン由来) =====
    # confidence high/medium の場合、既存 lookup 結果より優先で official_* を上書き。
    # set_name は既存 Canonical Map に通す (大文字/コード形式の正規化)。
    # ロールバック: この if ブロックをコメントアウトすれば既存挙動に完全復元。
    if _vision_result and _vision_result.get("confidence") in ("high", "medium"):
        v = _vision_result
        # 2026-04-26: Vision は **gap fill のみ** に変更.
        # iMakCatalog (公式 Bandai API) が既に提供したフィールドは Vision が上書きしない.
        # (旧挙動で OP14-034 Luffy の set が Vision キャッシュ '"The Three Captains"' に
        #  上書きされて Claude AI selfcheck が BLOCK した事例修正)
        # 公式 prefix 付き番号 (例: 'OP14-034') は authoritative なので Vision は上書きしない.
        # 一方 PSA raw 番号 (例: '019' = 数字のみ) は不完全なので Vision の prefix 付き
        # ('OP07-019' 等) で gap-fill する.
        if v.get("card_number") and (
            not official_card_number
            or (
                not re.match(r"[A-Z]", official_card_number)
                and "/" not in str(official_card_number)
            )
        ):
            official_card_number = v["card_number"]
        if v.get("character") and not character:
            character = v["character"]
        # 2026-06-08: set_name は Vision で生成しない (fail-closed / SSOT)。
        # catalog lookup の set_name_ebay が SSOT。catalog miss は catalog_misses で
        # skip + 自動依頼される。Vision の raw set 名を変換して埋めると
        # ①「参照のみ」に反する ②catalog 意図的空欄(JP限定)を上書きしてしまう → 廃止。
        if v.get("rarity") and not official_rarity:
            official_rarity = v["rarity"]
        if v.get("color") and not official_color:
            official_color = v["color"]
        if v.get("card_type") and not official_card_type:
            official_card_type = v["card_type"]
        if v.get("cost") not in (None, "") and official_cost in (None, ""):
            official_cost = str(v["cost"])
        if v.get("power") not in (None, "") and official_power in (None, ""):
            official_power = str(v["power"])
        # franchise も上書き (画像から判定可能)
        if v.get("franchise"):
            franchise = v["franchise"].replace(" TCG", "").replace(" Card Game", "").replace(" Super Card Game", "") if franchise == "" else franchise

    # Claude APIでタイトル・カード情報生成（画像あり）
    card_image_url = data.get('CardImageUrl')
    # card_number（PSA生値="004"）ではなく official_card_number（Bandai DB等で補完済="ST16-004"）を渡す。
    # セットprefix欠落→selfcheck弾きを防止（全ブランチ共通でofficial_card_numberは適切に設定済）
    # subject の variant suffix (BCGF World Tour 等) を Title 経路でも剥離.
    # Card Name/Character 経路 (line 1697 周辺) と同じ正規化を Title 入口にも適用し、
    # Subject → Claude prompt / build_title の二経路で suffix が混入する事故を防ぐ.
    try:
        from card_name_normalizer import normalize_card_name as _normalize
        subject_clean = _normalize(subject, franchise)
    except Exception as _e:
        print(f"    ⚠️ subject 正規化失敗、生 subject 使用: {type(_e).__name__}: {_e}")
        subject_clean = subject
    claude_result = generate_title_with_claude(game, set_name, official_card_number, subject_clean, franchise, card_image_url)
    claude_result = claude_result or {}

    # Item Specifics: 公式DB のみ採用 (2026-04-24 物理強制化、Claude フォールバック全廃)
    # グローバル CLAUDE.md「確証なきは空欄、公式サイトからの推定は不可」+ memory `enforce_in_python_not_prompt`
    # に従い、rarity/card_type/cost/power/attribute/finish 全てで claude_result を使わない。
    # 公式DB (bandai_jp / bandai_tcg_plus / pokemon_card_jp) がヒットしない場合は空欄で出品する。
    if franchise != "Pokemon":
        # 2026-04-26: Character = 純キャラ名 (バリアント識別子剥離)
        # Card Name = Character と同値 (eBay 慣習。バリアント情報は C:Features で表現)
        # ※ Subject由来のバリアント識別子を Card Name に詰め込むのは過剰 (検索性低下)
        character = _strip_variant_from_character(character)
        card_name = character
    rarity    = official_rarity      # Claude 追放
    features  = extract_variant_from_subject(subject)  # 関数ベース（PSA Subject パース、推論なし）
    card_type = official_card_type   # Claude 追放
    cost      = official_cost        # Claude 追放
    power     = official_power       # Claude 追放
    finish    = official_finish      # Claude 追放 + Subject キーワード判定も廃止
    attribute = official_color or official_attribute  # Claude 追放

    # 2026-04-24 Canonical Map (Phase 1): eBay フィルタ正規値へ無言整形
    # 2026-04-25 Phase 2: Card Type / Rarity 拡張、Leader Cost 空欄化、One Piece Set 補完
    _CANONICAL_FEATURES = {
        "Alternate Art": "Alternative Art",
        "Alt Art":       "Alternative Art",
        "Alt. Art":      "Alternative Art",
    }
    _CANONICAL_CARD_TYPE = {
        "Leader Card":    "Leader",
        "Character Card": "Character",
        "Event Card":     "Event",
        "Stage Card":     "Stage",
        "Battle Card":    "Battle",
        "Extra Card":     "Extra",
        "Don Card":       "DON",
    }
    # ONE PIECE rarity 略号 → eBay 正規綴り
    _CANONICAL_RARITY_ONEPIECE = {
        "C":   "Common",
        "UC":  "Uncommon",
        "R":   "Rare",
        "SR":  "Super Rare",
        "SEC": "Secret Rare",
        "L":   "Leader",
        "P":   "Promo",
        "SP":  "Special",
        "SP CARD": "Special",
    }
    # DRAGON BALL rarity 略号 → eBay 正規綴り
    # 2026-04-26: Bandai TCG+ API は SR/UC/PR★ 等の略号/特殊記号を返すが eBay フィルタ非対応
    _CANONICAL_RARITY_DRAGONBALL = {
        "C":    "Common",
        "UC":   "Uncommon",
        "R":    "Rare",
        "SR":   "Super Rare",
        "SCR":  "Secret Rare",
        "PR":   "Promo",
        "PR★":  "Promo",  # ★ は eBay フィルタ非対応
        "L":    "Leader",
    }
    if features in _CANONICAL_FEATURES:
        _new = _CANONICAL_FEATURES[features]
        print(f"    [AUTO-FIX] Features: {features!r} -> {_new!r} (Canonical Map)")
        features = _new
    if card_type in _CANONICAL_CARD_TYPE:
        _new = _CANONICAL_CARD_TYPE[card_type]
        print(f"    [AUTO-FIX] Card Type: {card_type!r} -> {_new!r} (Canonical Map)")
        card_type = _new
    # Rarity 正規化 (フランチャイズ別マップ)
    if franchise == "One Piece" and rarity:
        _ru = rarity.strip().upper()
        if _ru in _CANONICAL_RARITY_ONEPIECE:
            _new = _CANONICAL_RARITY_ONEPIECE[_ru]
            if _new != rarity:
                print(f"    [AUTO-FIX] Rarity: {rarity!r} -> {_new!r} (Canonical Map)")
            rarity = _new
    elif franchise == "Dragon Ball" and rarity:
        _ru = rarity.strip().upper()
        if _ru in _CANONICAL_RARITY_DRAGONBALL:
            _new = _CANONICAL_RARITY_DRAGONBALL[_ru]
            if _new != rarity:
                print(f"    [AUTO-FIX] Rarity: {rarity!r} -> {_new!r} (Canonical Map)")
            rarity = _new

    # 2026-04-25: Leader カードは Cost / Power が無い設計
    # 　Bandai 側で誤って数値が入って返ってくるケースあり (例: cert 149801531 Shanks Cost=5)
    # 　→ Leader 確定なら強制空欄化（公式仕様準拠）
    if card_type == "Leader":
        if cost not in ("", None):
            print(f"    [AUTO-FIX] Leader Cost: {cost!r} -> '' (Leader はコスト持たない仕様)")
            cost = ""

    # 2026-06-08: 出品は「参照のみ」化 (SSOT)。set_name は catalog lookup の
    # set_name_ebay (Catalog #1a で clean な eBay facet 名を確定保存済) をそのまま使う。
    # 旧: 出品の度に set_code_to_ebay_name / _dragonball_set_name_to_ebay で再変換していたが、
    #     保存値が既に clean なので no-op + 変換層のバグ伝播源 → 撤去。
    #     カタログに無い (=set_name_ebay 空) なら空欄のまま (fail-closed)。変換で埋め直さない。

    # One Piece Leader の rarity 空欄補完 (Canonical Map 適用後の値で判定)
    if not rarity and card_type == "Leader" and franchise == "One Piece":
        rarity = "Leader"
    card_number = official_card_number  # 公式の完全番号 (例: "231/193")

    # 2026-05-27: DON カード防御 — eBay 送信値 (= C:Card Number) は強制空欄維持
    # Catalog の DON-{set_code}-NNN は dedup 内部 KEY であって 公式 card_number ではない。
    # 誤って eBay に内部 KEY を送信しないよう、 DON!! Card 検出時に強制空欄化。
    # 5/27 ユーザー方針: 「カード番号じゃないけど KEY として使うから」
    if subject and "DON!!" in str(subject).upper():
        if card_number:
            print(f"    🔧 DON カード防御: card_number={card_number!r} → '' (= eBay 送信空欄維持、 KEY は内部 dedup 用のみ)")
        card_number = ""
        official_card_number = ""

    # 2026-05-27: Card Number 完全形補完 (= 重複くん Phase 1e 発見、 dedup 精度向上)
    # catalog miss 等で連番のみ ("060") のまま eBay 送信されてた listing が複数発覚 (= POC 3/5 件)。
    # 完全形 ("OP05-060") で送信すべきため、 PSA brand から set prefix 抽出 → 補完。
    # set_name 英語名 (= "Awakening of the New Era" 等) からは prefix 取れないため brand 優先。
    if card_number and re.match(r"^\d+$", str(card_number)):
        _brand_upper = (data.get('Brand') or '').upper()
        _m_prefix = re.search(r'\b(OP\d+|ST\d+|EB\d+|PRB\d+|RP|GD\d+|FB\d+|FS\d+|SB\d+)\b', _brand_upper)
        if _m_prefix:
            _prefix = _m_prefix.group(1)
            _zfilled = str(card_number).zfill(3)
            _completed = f"{_prefix}-{_zfilled}"
            print(f"    🔧 Card Number 完全形補完: {card_number!r} -> {_completed!r} (PSA brand={_prefix})")
            card_number = _completed
            official_card_number = _completed

    # 2026-05-27 撤回: SM-P 系 正規化 (= `001/SM-P` → `SM-P-001`) は SEO アレンジに該当、
    # 「Catalog = 公式 = 正 = KEY で統一」 新原則 (= 同日対話) で撤回。
    # 公式表記そのまま eBay 送信、 重複くんも Catalog 公式値で dedup。

    # タイトル: Claudeが有効なら使用、欠落/不正ならルールベース
    claude_title = claude_result.get('title') if claude_result else None
    if claude_title:
        title = strip_banned_words(claude_title)
        title = pad_title(title, card_type=card_type, set_name=set_name)
        title = strip_banned_words(title)
        # PSA Subjectのトークン保持を検証; 欠落があればルールベースに強制切替
        if not title_preserves_subject(title, subject_clean):
            print(f"    ⚠️ Claudeタイトルが PSA Subject を改変 → ルールベースに切替")
            print(f"       Claude: {title}")
            title = build_title(game, set_name, card_number, subject_clean)
        # 公式カード番号の保持を検証; Claudeが短縮した時（例: ST16-004 → 004）はルールベースに切替
        # Claudeはテンプレート"#[Num]"を番号だけと解釈することがあるため、物理的な文字列 contains で検証
        elif official_card_number and official_card_number not in title:
            print(f"    ⚠️ Claudeタイトルが card# {official_card_number} を短縮 → ルールベースに切替")
            print(f"       Claude: {title}")
            title = build_title(game, set_name, card_number, subject_clean)
        print(f"    ✨ Title: {title} ({len(title)}字)")
    else:
        title = build_title(game, set_name, card_number, subject_clean)
        print(f"    📐 Rule title: {title} ({len(title)}字)")

    # ===== タイトル生成エージェント (新ルーチン、独立) =====
    # Phase 1: NG語フィルタ (Pk Set → Tin 等の Error 240 回避) + technique→character 置換
    # Phase 2: iMakKeywords PDF 上位語スコアリング (検索ボリューム加味)
    # Phase 3: TOP seller タイトル分析 (sold_data xlsx 頻出語)
    # → 仮説 (variants) 生成 → 多角スコア → 最良案採用 (誤情報追加は厳格除外)
    # ロールバック: この try/except ブロックをコメントアウトで完全復元。
    try:
        from title_generation_agent import refine_title
        _agent_warnings = (_vision_result or {}).get("agent_warnings", [])
        title = refine_title(
            title,
            character=character,
            card_number=card_number,
            franchise=franchise,
            agent_warnings=_agent_warnings,
        )
    except Exception as _e:
        print(f"    ⚠️ title_generation_agent 失敗: {type(_e).__name__}: {_e}")
        # title は元のまま、既存挙動継続

    # 2026-06-09: 短タイトル(<70)を catalog 実ファクト(年/レアリティ/set code)で補強 (捏造なし、最終段)
    _pid_for_sc = _catalog_pid_for_variant or official_card_number or ""
    _m_sc = re.match(r"^([A-Za-z]+\d*[A-Za-z]?)-", str(_pid_for_sc))
    _set_code_title = _m_sc.group(1) if _m_sc else ""
    _title_before = title
    title = _pad_title_with_facts(title, data.get('Year'), official_rarity, _set_code_title)
    if title != _title_before:
        print(f"    🔧 タイトル補強(catalog事実): {len(_title_before)}字→{len(title)}字: {title}")

    # SKU (CustomLabel): A列 仕入元 URL から item ID 抽出 (tshirt_listing_rules 準拠)
    # 優先順: Mercari (m\d+) → SNKRDUNK (apparels/.*/used/\d+) → PSA cert# フォールバック
    # 無在庫運用で元ページへの即時逆引きと二重出品防止を両立するキー設計
    import re as _re_sku
    _supplier_url = data.get('_mercari_url', '')  # 変数名は互換性のため維持 (= 実体は supplier URL)
    _mid = _re_sku.search(r'/item/(m\d+)', _supplier_url)
    if _mid:
        custom_label = _mid.group(1)  # Mercari: m12345
    else:
        _snkr = _re_sku.search(r'snkrdunk\.com/apparels/\d+/used/(\d+)', _supplier_url)
        if _snkr:
            custom_label = _snkr.group(1)  # SNKRDUNK: 45549454 (= URL の listing instance ID そのまま、検索可)
        else:
            custom_label = f"PSA10-{cert_number}"
    store_cat_id = get_store_category(franchise)
    shipping = get_shipping_policy(price)

    # Card Size = "Standard" (= 市場標準。seller分析 Standard 24 / Japanese 4、catalog も Standard)。
    # 新コア(TCG_USE_NEW_GEN=1)は catalog card_size_ebay→Standard 既定で同値を出す。
    card_size = "Standard"
    # Manufacturerはゲームにより異なる
    manufacturer = "The Pokémon Company" if franchise == "Pokemon" else "Bandai"
    illustrator = official_illustrator or ""

    # セルフチェック（CSV出力前、PSA整合性の決定論検証のみ）
    # 誤出品防止は validate_row の error reject が担保
    # (catalog-miss は main() の新コア解決ゲートで別途 skip し入稿しない)。
    from listing_validator import validate_row
    tcg_specs = {"Brand": manufacturer, "Type": card_type, "Size": "N/A", "Color": attribute or "N/A",
                 "Game": game, "Set": set_name, "Rarity": rarity, "Card Number": card_number}
    # psa_card_number は validate_row の Rule 3 が「数字のみ」を前提にしているため、
    # line 1372 で official_card_number に上書き済の card_number ではなく PSA 生値を渡す。
    # （Bandai補完値を渡すと "ST16-004" vs "004" の false positive が発生する）
    _errors, _warnings = validate_row(
        title, tcg_specs, "", 183454, 2750, price, PIC_URL,
        psa_brand=brand, psa_card_number=data.get('CardNumber', ''),
    )
    for _w in _warnings:
        print(f"       ⚠️ {_w}")
    if _errors:
        print(f"    ❌ セルフチェック失敗 (#{cert_number}):")
        for _e in _errors:
            print(f"       ❌ {_e}")
        print(f"    → この商品はCSVに含めません")
        return None

    # ===== Card Name/Character の variant suffix 剥がし (新ルーチン、独立) =====
    # PSA Subject 由来の雑誌名/Anniversary略号/Pokemon prefix 等を除去し純キャラ名のみ.
    # ロールバック: この try/except ブロックをコメントアウトで完全復元.
    try:
        from card_name_normalizer import normalize_card_name
        character = normalize_card_name(character, franchise)
        card_name = normalize_card_name(card_name, franchise)
    except Exception as _e:
        print(f"    ⚠️ card_name_normalizer 失敗: {type(_e).__name__}: {_e}")
        # 元値維持、既存挙動継続

    # ===== iMakCatalog 参照サブルーチン (補助情報源、独立) =====
    # 既存 specs に空欄あれば catalog 値で補完. 矛盾あれば警告ログのみ (上書きしない).
    # catalog は隣セッションで開発中、正式運用合意は未済 (2026-04-27)
    # ロールバック: この try/except ブロックをコメントアウトで完全復元.
    try:
        from catalog_reference import reference_catalog_for_specs
        _ref_specs = {"cost": str(cost), "power": str(power), "color": attribute}
        _improved, _warnings = reference_catalog_for_specs(
            franchise=franchise, card_number=card_number,
            current_specs=_ref_specs,
            psa_brand=brand, psa_subject=data.get('Subject', ''),
        )
        # 補完値だけ反映 (警告は print 済、ここでは反映しない)
        cost = _improved.get("cost", cost) or cost
        power = _improved.get("power", power) or power
        attribute = _improved.get("color", attribute) or attribute
    except Exception as _e:
        print(f"    ⚠️ catalog_reference 失敗: {type(_e).__name__}: {_e}")
        # 元値維持、既存挙動継続

    # 2026-04-28 Bug #2 fix (defensive): catalog_reference 側でも Leader cost を skip するが、
    # 万一 Leader card_type で cost に値が残っている場合に備え、CSV 書き出し直前で再強制空欄化.
    # Fix A (catalog_reference) と二重防御 (案 C: A+B).
    if card_type == "Leader" and cost not in ("", None):
        print(f"    [AUTO-FIX] Leader Cost (post-catalog): {cost!r} -> '' (Leader はコスト持たない仕様)")
        cost = ""

    # 2026-05-28 variant_meta 連動 (= ① Phase A.1 Pokemon catalog で投入済の variant メタ活用)
    # PSA Subject から variant_code 抽出 → catalog 公式値で Features/Finish/Rarity 補完
    if _catalog_pid_for_variant and _catalog_category_for_variant:
        try:
            from integrations import variant_meta as _vm  # 既存 catalog_psa と同 import 経路
            _variant_code = _vm.extract_variant_alias(data.get('Subject', '') or '')
            if _variant_code:
                _meta = _vm.get_variant_meta(_catalog_pid_for_variant, _variant_code, _catalog_category_for_variant)
                if _meta:
                    if not features:
                        features = _meta.get("features", "")
                    # 2026-06-01: finish 投入禁止 (= SNAD クレーム直結リスク)
                    # memory:finish_only_blank_other_keep_processed
                    # variant_meta 経由の finish も削除、 listing 側で常に空欄
                    if _meta.get("rarity_ebay"):
                        rarity = _meta["rarity_ebay"]
                    print(f"    🎨 variant_meta 連動: {_variant_code} → features={features!r} rarity={rarity!r}")
        except Exception as _e:
            print(f"    ⚠️ variant_meta 連動失敗: {type(_e).__name__}: {_e}")

    # 2026-06-09: Features がまだ空なら catalog rarity から導出 (TOPセラーは rarity を Features に入れる)。
    # 実属性なので捏造でない。variant (Alt Art 等) が取れてる時は上書きしない。
    if not features:
        _feat = _RARITY_TO_FEATURES.get((official_rarity or "").upper().strip(), "")
        if _feat:
            features = _feat
            print(f"    🔧 Features 補完(catalog rarity {official_rarity!r}→{features!r})")

    # 商品説明に個別 Specifications ブロックを挿入 (listing の Item Specifics と同値を転記・空欄skip)
    description = insert_tcg_specs(description, build_tcg_specs_html([
        ("Card Name", card_name), ("Set", set_name), ("Card Number", card_number),
        ("Rarity", rarity), ("Card Type", card_type), ("Year", year), ("Language", "Japanese"),
    ]))

    return [
        "Add", 183454, title, _build_pic_url(data), price, 2750,
        275010, 275020, cert_number,
        get_schedule_time(), custom_label, description,
        "FixedPrice", "GTC", 1, LOCATION, 1,
        shipping, RETURN_POLICY, PAYMENT_POLICY,
        game, set_name, card_type, card_name, character, card_number,
        # Country of Origin: One Piece は card に made in japan 印字で日本製造が確実 → "Japan"
        # (2026-06-10 ユーザー指示・まず OP から)。他は "Does not apply"（製造国を特定できない
        # 場合の eBay AI 勝手な Japan 補完を明示的に塞ぐ＝従来方針）。
        rarity, features, manufacturer, "Japanese", year,
        ("Japan" if franchise == "One Piece" else "Does not apply"), franchise,
        "6+", "No", "No", "Card Stock", card_size, "No",
        finish, attribute, illustrator, cost, power, "",
        "", "",   # C:HP / C:Stage (旧コアは空・新コアが catalog hp_ebay/stage_ebay から充填)
        "Near Mint or Better", "10",
        "Professional Sports Authenticator (PSA)", "Yes",
        store_cat_id,
    ]

GSHEET_CREDS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..",
    "double-hold-421922-7c0d38d3f73d.json"
)


def load_targets_from_sheet_psa():
    """Porter/Ichibankuji/Reel と共用の出品管理スプシ (19kj8... gid=851100680)
    から PSA 出品対象を抽出。

    旧来の certs.txt 方式を廃止し、スプシ駆動に完全移行（2026-04-24）。
    全カテゴリ共通の入力パイプラインに統合。

    条件: I列(cert#)非空 AND B列(itemID)空 AND A列(URL)非空
    仕入値: N列(仕入れ価格円)優先、空なら F列(商品価格 "¥11,000" 形式) を parse

    Returns: (cert_numbers, cost_map, url_map, title_map)
    """
    import gspread as _gspread
    import re as _re
    from google.oauth2.service_account import Credentials as _Creds

    PSA_SHEET_ID = "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk"
    PSA_GID = 851100680

    if not os.path.exists(GSHEET_CREDS_FILE):
        print(f"❌ Google認証ファイルなし: {GSHEET_CREDS_FILE}")
        return [], {}, {}, {}

    creds = _Creds.from_service_account_file(
        GSHEET_CREDS_FILE,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = _gspread.authorize(creds)
    sh = gc.open_by_key(PSA_SHEET_ID)
    ws = sh.get_worksheet_by_id(PSA_GID)
    all_values = ws.get_all_values()

    cert_numbers = []
    cost_map = {}
    url_map = {}
    title_map = {}
    for row in all_values[1:]:  # header 除外
        url      = (row[0]  if len(row) > 0  else '').strip()  # A
        item_id  = (row[1]  if len(row) > 1  else '').strip()  # B (空=未処理)
        title    = (row[2]  if len(row) > 2  else '').strip()  # C
        sold     = (row[3]  if len(row) > 3  else '').strip()  # D 売り切れ ('○'=売切)
        price_f  = (row[5]  if len(row) > 5  else '').strip()  # F "¥11,000"
        cert     = (row[8]  if len(row) > 8  else '').strip()  # I cert#
        no_go    = (row[10] if len(row) > 10 else '').strip()  # K NO-GO sentinel (= 「出品見合せ（仕入高）」 等)
        cost_n   = (row[13] if len(row) > 13 else '').strip()  # N 仕入れ価格(円)
        category = (row[17] if len(row) > 17 else '').strip()  # R カテゴリ

        if not cert or item_id or not url:
            continue
        # 統合シートは TCG / Tシャツ / 一番くじ / Montbell 等の混在。R列='TCG' のみ PSA 対象
        # (他 listing スクリプトと同じ R 列フィルタ運用に合わせる)
        if category != 'TCG':
            continue
        # D 列 売り切れ '○' は drop-shipping 不可 (仕入れ確実でないため出品 NG)
        if sold:
            continue
        # K 列 NO-GO sentinel (= 過去 cycle 価格 NO-GO 除外で書込) → 抽出対象外
        if no_go:
            continue
        cert_numbers.append(cert)
        url_map[cert] = url
        title_map[cert] = title
        # 仕入値: N列優先、空なら F列(¥11,000 形式) を parse
        cost_src = cost_n or price_f
        if cost_src:
            m = _re.search(r'([\d,]+)', cost_src)
            if m:
                try:
                    cost_map[cert] = int(m.group(1).replace(',', ''))
                except ValueError:
                    pass
    return cert_numbers, cost_map, url_map, title_map


# profile は env で上書き可(RESTOCK 並走時に新規出品と別 profile にして Chrome 競合を避ける)。
# 未設定なら従来の本番 profile(新規出品は不変)。
_PSA_PROFILE_DIR = os.environ.get("PSA_PROFILE_DIR") or r"C:\Users\imax2\local_data\iMakHQ\chrome_profile_psa"
_psa_warmup_driver = None  # warmup で起動した uc.Chrome、 main の本処理に流用


def _psa_cloudflare_warmup():
    """PSA Cloudflare 対策 = uc.Chrome を visible で起動 + user 手動 突破.

    2026-05-26 実装。 通常 chrome 起動だと profile 衝突するため uc.Chrome を warmup から使う。
    driver は本処理に流用 (= 同 instance 維持で profile 衝突回避)。
    """
    global _psa_warmup_driver
    import tkinter as _tk
    from tkinter import messagebox as _mb

    TEST_URL = "https://www.psacard.com/cert/89631139"
    os.makedirs(_PSA_PROFILE_DIR, exist_ok=True)

    print("\n🔓 Cloudflare warmup: uc.Chrome 起動中...")
    try:
        options = uc.ChromeOptions()
        options.add_argument("--no-sandbox")
        options.add_argument(f"--user-data-dir={_PSA_PROFILE_DIR}")
        options.add_argument("--disable-features=CalculateNativeWinOcclusion")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        _psa_warmup_driver = uc.Chrome(options=options, version_main=detect_chrome_major())
        _psa_warmup_driver.get(TEST_URL)
    except Exception as _e:
        print(f"⚠️ uc.Chrome 起動失敗: {_e}, warmup skip → 本処理が新規起動試行")
        _psa_warmup_driver = None
        return

    _root = _tk.Tk()
    _root.withdraw()
    _root.attributes("-topmost", True)
    _mb.showinfo(
        "PSA Cloudflare チェック",
        "Chrome で PSA cert ページを開きました。\n\n"
        "1. Cloudflare チェック (= 「I'm not a robot」 等) があれば click\n"
        "2. PSA cert 詳細ページ (= グレード等) が見えれば成功\n"
        "3. **Chrome は閉じずに** この OK を押してください\n"
        "(= 同 driver で scrape 続行、 profile 衝突回避)",
    )
    _root.destroy()
    print("✅ Cloudflare warmup 完了、 psa_to_csv 続行\n")


def main():
    print("=== iMak Trading Japan - PSA → eBay CSV Generator ===\n")
    _psa_cloudflare_warmup()

    # RESTOCK入力モード (2026-06-18): env PSA_RESTOCK_INPUT=<json> 指定時は、新規スプシ抽出でなく
    # RESTOCK対象(出品済=B列itemID埋まり)の cert を json から取る。{certs:[..], cost:{cert:¥},
    # supply_url:{cert:url}, forced:{cert:KEY}}。生成は新規と完全同一(後段で Revise化)。
    # 未設定なら従来通り(本番不変)。
    _restock_input = os.environ.get("PSA_RESTOCK_INPUT")
    _restock_forced = {}
    if _restock_input:
        import json as _json
        _ri = _json.load(open(_restock_input, encoding="utf-8"))
        cert_numbers = [str(c).strip() for c in (_ri.get("certs") or []) if str(c).strip()]
        cost_map = {str(c): float(v) for c, v in (_ri.get("cost") or {}).items() if v}
        mercari_url_map = {str(c): u for c, u in (_ri.get("supply_url") or {}).items()}
        mercari_title_map = {}
        _restock_forced = {str(c): str(k) for c, k in (_ri.get("forced") or {}).items() if k}
        print(f"♻ RESTOCKモード: {len(cert_numbers)}件 Add生成 (forced KEY {len(_restock_forced)}件)")
    else:
        # 2026-04-24: certs.txt 廃止、スプシ駆動に完全移行
        # スプシ (19kj8... gid=851100680) の I列=cert# / B列=itemID空 / A列=URL で処理対象を抽出
        print("📊 スプシから PSA 出品対象を抽出中...")
        cert_numbers, cost_map, mercari_url_map, mercari_title_map = load_targets_from_sheet_psa()

    if not cert_numbers:
        print("処理対象なし（スプシに I列=cert# ありの未処理行が見つかりません）")
        if not _restock_input:
            input("Enterで終了...")
        return

    print(f"✓ {len(cert_numbers)}件の PSA 対象行を抽出（B列 itemID 空）")

    # 上から順でなくランダム抽出 (2026-06-10 ユーザー要望: 上位行に偏らず満遍なく出品)
    # 環境変数 PSA_NO_SHUFFLE=1 で従来の上から順に戻せる。RESTOCKは確定順を保つのでshuffleしない。
    if not _restock_input and os.environ.get("PSA_NO_SHUFFLE") != "1":
        import random
        random.shuffle(cert_numbers)

    # 一回 10 件まで固定 (Cloudflare bot 検出回避、2026-05-06)。RESTOCKは確定分を全部処理(制限skip)。
    # 残りは時間を置いて次回再走で順次処理
    PSA_BATCH_LIMIT = 10
    if not _restock_input and len(cert_numbers) > PSA_BATCH_LIMIT:
        print(f"⚠️ {len(cert_numbers)}件中 ランダム {PSA_BATCH_LIMIT} 件を処理 (残 {len(cert_numbers)-PSA_BATCH_LIMIT} 件は次回再走)")
        cert_numbers = cert_numbers[:PSA_BATCH_LIMIT]
        cost_map = {c: cost_map[c] for c in cert_numbers if c in cost_map}

    if cost_map:
        print(f"{len(cert_numbers)}件を処理します。（仕入値あり: {len(cost_map)}件）\n")
    else:
        print(f"{len(cert_numbers)}件を処理します。\n")

    # 2026-05-26: warmup phase で uc.Chrome 起動済の場合は流用 (= profile 衝突回避)
    if _psa_warmup_driver is not None:
        driver = _psa_warmup_driver
        print("🔁 warmup driver 流用 (= cookie 引き継ぎ + profile 衝突回避)")
    else:
        # fallback: warmup 失敗時 or 直接 CLI 実行時
        os.makedirs(_PSA_PROFILE_DIR, exist_ok=True)
        options = uc.ChromeOptions()
        options.add_argument("--no-sandbox")
        options.add_argument(f"--user-data-dir={_PSA_PROFILE_DIR}")
        options.add_argument("--disable-features=CalculateNativeWinOcclusion")
        options.add_argument("--window-size=800,600")
        options.add_argument("--window-position=100,100")
        driver = uc.Chrome(options=options, version_main=detect_chrome_major())
    try:
        driver.minimize_window()  # 起動後即最小化
    except Exception:
        pass  # 最小化失敗してもメイン処理に影響させない

    description = load_description()

    headers = [
        "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)",
        "*Category", "*Title", "PicURL", "*StartPrice", "ConditionID",
        "CD:Professional Grader - (ID: 27501)", "CD:Grade - (ID: 27502)",
        "CDA:Certification Number - (ID: 27503)", "ScheduleTime", "CustomLabel",
        "*Description", "*Format", "*Duration", "*Quantity", "*Location",
        "BestOfferEnabled", "ShippingProfileName", "ReturnProfileName", "PaymentProfileName",
        "C:Game", "C:Set", "C:Card Type", "C:Card Name", "C:Character", "C:Card Number",
        "C:Rarity", "C:Features", "C:Manufacturer", "C:Language", "C:Year Manufactured",
        "C:Country of Origin", "C:Franchise", "C:Age Level", "C:Autographed",
        "C:Vintage", "C:Material", "C:Card Size", "C:Customized",
        "C:Finish", "C:Attribute/MTG:Color", "C:Illustrator", "C:Cost", "C:Attack/Power", "C:Defense/Toughness",
        # C:HP / C:Stage は新コアが catalog hp_ebay/stage_ebay から充填 (2026-06-15 最大活用)。
        # 旧コアは空 (build_row が "" を出す)。catalog *_ebay 充填まで空欄 (回帰なし)。
        "C:HP", "C:Stage",
        "C:Card Condition", "C:Grade", "C:Professional Grader", "C:Graded", "StoreCategoryID",
    ]

    rows = [headers]
    errors = []
    catalog_misses = []  # iMakCatalog 未登録 (要 Catalog Claude 拡充依頼) — gshock_to_csv と同パターン
    # PSAデータ取得 → build_row（価格はデフォルト$100で仮生成）
    card_info = []  # (cert, data) を保持して後で価格更新

    # ===== verify→build (PSA_VERIFY_BEFORE_BUILD=1): 先に全 cert scrape → HTML目視確認 →
    #       確定したカードだけ CSV 生成 (= 確定してから作る)。既定 OFF=従来の build→確認。 =====
    _verify_mode = os.environ.get("PSA_VERIFY_BEFORE_BUILD") == "1"
    _prescraped = {}
    _confirmed_pids = {}
    _skipped_unconfirmed = []
    if _verify_mode:
        print("\n🔎 verify→build モード: 先に scrape → 目視確認 → 確定カードのみ生成")
        for cert in cert_numbers:
            print(f"取得中(確認用): #{cert}...", end="", flush=True)
            d = get_psa_data(driver, cert)
            _prescraped[cert] = d
            print(" ✓" if d else " 失敗")
        try:
            _tools = r"C:/dev/iMak/iMakHQ/tools"
            if _tools not in sys.path:
                sys.path.insert(0, _tools)
            from post_psa_review import run_pre_build_verify
            _confirmed_pids = run_pre_build_verify(cert_numbers, print)
        except Exception as _e:
            print(f"⚠️ pre-build verify 失敗 → 確定不能のため build 中止(誤出品回避): {type(_e).__name__}: {_e}")
            _confirmed_pids = {}

    for cert in cert_numbers:
        if _verify_mode:
            # 確定 (OK/CHOSEN) した cert のみ build。未確定/NONE/NG は出品しない (fail-closed)。
            if cert not in _confirmed_pids:
                print(f"スキップ(目視未確定): #{cert}")
                _skipped_unconfirmed.append(cert)
                card_info.append((cert, None))
                continue
            data = _prescraped.get(cert)
        else:
            print(f"取得中: #{cert}...", end="", flush=True)
            data = get_psa_data(driver, cert)

        if data:
            subject = data.get('Subject', 'Unknown')
            card_number = data.get('CardNumber', '')
            print(f" → #{card_number} {subject} ✓")
            # SKU にメルカリ item ID を使うため、URL を data に注入（tshirt_listing_rules 準拠）
            data['_mercari_url'] = mercari_url_map.get(cert, '')
            row = build_row(cert, DEFAULT_PRICE, data, description, driver=driver, catalog_misses=catalog_misses)
            if row is None:
                # selfcheck弾かれ → rows/card_info の後段ループで None参照クラッシュを防ぐためスキップ
                print(f"    ⚠️ Skipping #{cert}: selfcheck failed in build_row")
                errors.append(cert)
                card_info.append((cert, None))
                continue
            # 並行ビルド切替 (strangler): TCG_USE_NEW_GEN=1 の時だけ catalog 決定論値で上書き。
            # 既定 OFF=この分岐は no-op で旧挙動を完全維持 (本番不変)。
            # verify_mode 時は確定 product_id (forced_card_id) で再生成 = 人が選んだカードを権威に。
            try:
                from tcg_new_gen_override import env_enabled, apply_new_gen_override
                if env_enabled():
                    # RESTOCK は目視確定済の変種KEYを forced で権威採用(新規の verify→build と同思想)
                    _forced = _restock_forced.get(cert, "") or (_confirmed_pids.get(cert, "") if _verify_mode else "")
                    # ★catalog hit 判定 (新コア・全 franchise の決定論解決)。
                    #   miss = 公式データ無し → **入稿しない** (fail-closed / catalog_official_only)。
                    #   catalog-miss を弾く正規ゲートはここ1本。
                    from tcg_listing_fields import build_listing_fields as _blf
                    _gi = headers.index("C:Game") if "C:Game" in headers else None
                    _game = row[_gi] if (_gi is not None and _gi < len(row)) else ""
                    _chk, _cerr = _blf(str(cert), _game or "", forced_card_id=_forced)
                    if _cerr:
                        print(f"    ⏭️ Skip (catalog未登録→入稿しない・catalog依頼): #{cert} ({_cerr})")
                        errors.append(cert)
                        card_info.append((cert, None))
                        continue
                    row = apply_new_gen_override(row, headers, cert, forced_card_id=_forced)
            except Exception as _e:
                print(f"    ⚠️ new-gen override skip (#{cert}): {type(_e).__name__}: {_e}")
            apply_ebay_filter_to_row(row, headers, category="tcg")
            rows.append(row)
            card_info.append((cert, data))
        else:
            print(f" → 失敗")
            errors.append(cert)
            card_info.append((cert, None))

    if _verify_mode and _skipped_unconfirmed:
        print(f"\n🔎 目視未確定で出品見送り: {len(_skipped_unconfirmed)} 件 {_skipped_unconfirmed}")

    driver.quit()

    # ===== eBay API で市場価格を取得し StartPrice を更新 =====
    ebay_keys = load_ebay_keys()
    ebay_token = None
    if ebay_keys.get("AppID") and ebay_keys.get("AppSecret"):
        try:
            ebay_token = get_ebay_oauth_token(ebay_keys["AppID"], ebay_keys["AppSecret"])
            print(f"\n✓ eBay API接続OK — 市場価格を取得します")
        except Exception as e:
            print(f"\n⚠️ eBay API接続失敗: {e} → デフォルト価格$100を使用")
    else:
        print(f"\n⚠️ eBay APIキーなし → デフォルト価格$100を使用")

    # 利益計算パラメータ（SSOT: iMakeBayAPI/profit_params.py 経由で利益計算シートv2を参照）
    # sys.path はファイル冒頭で設定済のためここでは追加しない
    from profit_params import get_exchange_rate, get_category_params, get_net_ratio, _load
    PROFIT_CATEGORY = "TCG(PSA10)"
    _params = _load()
    EXCHANGE_RATE = _params["exchange_rate"]
    EBAY_FEE = get_category_params(PROFIT_CATEGORY)["fvf"]
    PROMO_RATE = _params["ad_rate"]
    PAYO_RATE = _params["payo_fee"]
    SHIPPING_JPY = get_category_params(PROFIT_CATEGORY)["shipping_jpy"]
    NET_RATIO = 1 - EBAY_FEE - PROMO_RATE - PAYO_RATE  # 目標利益を引かないNET（GATE判定で目標利益を別途差引）

    # 価格帯別パラメータ: SSOT 抽象化 (profit_params.get_tier_params 経由)
    # 旧: 関数内で TIER_PARAMS リスト + ローカル get_tier_params 定義 (6ファイル重複の1つ)
    # 新: yaml(global.yaml) の pricing_tiers が SSOT
    from profit_params import get_tier_params  # noqa: F401

    MARKET_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "market_log.csv")
    MARKET_LOG_HEADERS = [
        "日付", "証明番号", "ゲーム", "カード番号", "キャラ名", "セット",
        "仕入値", "出品数", "全体中央値", "TOP中央値",
        "目標価格", "損益分岐", "乖離率", "判定", "出品価格",
    ]
    market_log_rows = []  # ログ蓄積用

    price_col_idx = headers.index("*StartPrice")
    shipping_col_idx = headers.index("ShippingProfileName")
    cert_col_idx = headers.index("CDA:Certification Number - (ID: 27503)")
    skip_certs = set()  # NO-GO(乖離30%超)のcert番号

    if ebay_token:
        card_seq = 0  # ナンバリング用
        for i, (cert, data) in enumerate(card_info):
            if data is None:
                continue
            card_seq += 1
            actual_idx = None
            for ri in range(1, len(rows)):
                if str(rows[ri][cert_col_idx]) == str(cert):
                    actual_idx = ri
                    break
            if actual_idx is None:
                continue

            brand = data.get('Brand', '')
            game, set_name, franchise = detect_game_info(brand)
            character = smart_titlecase(extract_character_name(data.get('Subject', '')))
            # 2026-04-24 二重基準解消 (check_csv.py と統一):
            # market search には CSV に書かれた Bandai 補完済 card# を使う (例: "EB03-001")。
            # PSA 生値 (例: "001") を使うと全セットの Leader #001 を拾って median が不当に上振れる（Viviで $250 vs 実勢 $79）。
            card_number_raw = str(data.get('CardNumber', ''))  # PSA 生値（ログ/market_log 用に保持）
            card_number_full = str(rows[actual_idx][headers.index("C:Card Number")]).strip() or card_number_raw
            # 2026-04-29 Phase D 補完 (cache 共有不変条件 / dual_gate_disagreement.md):
            # character も CSV の C:Character (catalog localize 済) を使う。
            # 旧: extract_character_name(subject) は "Jewelry Bonney Weekly Shonen Jump '24-#35" 等
            #     未登録 suffix を残す → check_csv 側 query "Jewelry Bonney" と不一致 → cache miss
            character_full = str(rows[actual_idx][headers.index("C:Character")]).strip() or character
            cost_jpy = cost_map.get(cert)

            market = search_market_price(ebay_token, game, card_number_full, character_full)
            card_number = card_number_raw  # 後段ログ互換のため元の変数名維持
            today = datetime.now().strftime("%Y-%m-%d")

            if not market:
                # 競合0件: 目標利益確保価格と$100の高い方で先行出品
                if cost_jpy is not None:
                    tier_profit, _ = get_tier_params(100)  # $100帯のパラメータ
                    costs_jpy = cost_jpy + SHIPPING_JPY
                    min_price = costs_jpy / (EXCHANGE_RATE * (NET_RATIO - tier_profit))
                    min_price = max(min_price, 100)
                    min_price = round(min_price, 2)
                    min_price = int(min_price) + 0.98 if min_price > 10 else min_price
                else:
                    min_price = 100.00
                # CSVの価格を更新
                actual_idx = None
                for ri in range(1, len(rows)):
                    if str(rows[ri][cert_col_idx]) == str(cert):
                        actual_idx = ri
                        break
                if actual_idx:
                    rows[actual_idx][price_col_idx] = min_price
                    rows[actual_idx][shipping_col_idx] = get_shipping_policy(min_price)
                print(f"    [{card_seq}] #{card_number} {character}: 出品0件 → ${min_price}で先行出品")
                market_log_rows.append([
                    today, cert, game, card_number, character, set_name,
                    cost_jpy or "", 0, "", "", "", "", "", "先行出品", min_price,
                ])
                time.sleep(0.5)
                continue

            all_median = market["all_median"]
            top_median = market["top_median"]
            top_info = f" (TOP${top_median:.0f})" if top_median else ""
            total = market["total"]

            # 乖離率計算（仕入値がある場合）— V5 pricing_engine 経由（2026-05-19 V5 切替）
            if cost_jpy is not None:
                _, tier_gap_limit = get_tier_params(all_median)
                costs_jpy = cost_jpy + SHIPPING_JPY
                # V5 ロジック: pricing_engine が yaml v5_pricing から IFS 利益率 + 35% markup で計算
                from pricing_engine import compute_listing_price as _v5_compute
                _v5_res = _v5_compute(cost_jpy, 0, "TCG(PSA10)")
                target_usd = _v5_res["target_usd"]
                tier_profit = _v5_res["profit_target"]
                breakeven_usd = costs_jpy / (EXCHANGE_RATE * NET_RATIO)
                gap_pct = (target_usd - all_median) / all_median * 100 if all_median > 0 else 999
                gap_limit_pct = tier_gap_limit * 100

                # 2026-05-23: 価格 = 常に V7 スプシ logic (= target_usd) で固定。
                # market median は 参考情報として log 出力のみ、 価格決定には使わない。
                # 旧: GO branch で market×0.95 採用 → 高額カードで過剰利益 (例 Uta cost¥19500 → $664)
                # 新: 常に cost-plus IFS target_usd → 一貫した利益率
                price = round(target_usd, 2)
                price = int(price) + 0.98 if price > 10 else price

                # market 比較ラベル (= 参考のみ、 price には影響なし)
                if total <= MARKET_GATE_MIN_LISTINGS:
                    gate_label = "薄商い"
                    gate = f"ℹ️ V7 ${price} (出品{total}件≤{MARKET_GATE_MIN_LISTINGS}、median 参考程度)"
                elif gap_pct <= 0:
                    gate_label = "市場高"
                    gate = f"ℹ️ V7 ${price} (市場${all_median:.0f}> target、機会損失の可能性あり)"
                elif gap_pct <= gap_limit_pct:
                    gate_label = "適正"
                    gate = f"ℹ️ V7 ${price} (乖離{gap_pct:.0f}%≤許容{gap_limit_pct:.0f}%)"
                else:
                    gate_label = "⚠️乖離大"
                    gate = f"⚠️ V7 ${price} (target>市場${all_median:.0f}、乖離{gap_pct:.0f}%>許容{gap_limit_pct:.0f}% — 売れにくい可能性)"

                # ログ記録（全判定）
                market_log_rows.append([
                    today, cert, game, card_number, character, set_name,
                    cost_jpy, total, f"{all_median:.2f}", f"{top_median:.2f}" if top_median else "",
                    f"{target_usd:.2f}", f"{breakeven_usd:.2f}", f"{gap_pct:.0f}%",
                    gate_label, f"{price}" if price else "",
                ])

                if price is None:
                    print(f"    [{card_seq}] #{card_number} {character}: 出品{total}件 | "
                          f"中央値${all_median:.0f}{top_info} | {gate}")
                    time.sleep(0.5)
                    continue

                rows[actual_idx][price_col_idx] = price
                rows[actual_idx][shipping_col_idx] = get_shipping_policy(price)
                print(f"    [{card_seq}] #{card_number} {character}: 出品{total}件 | "
                      f"中央値${all_median:.0f}{top_info} | {gate}")
            else:
                # 仕入値なし → 全セラー中央値×95%
                price = round(all_median * 0.95, 2)
                price = int(price) + 0.98 if price > 10 else price
                rows[actual_idx][price_col_idx] = price
                rows[actual_idx][shipping_col_idx] = get_shipping_policy(price)
                print(f"    [{card_seq}] #{card_number} {character}: 出品{total}件 | "
                      f"中央値${all_median:.0f}{top_info} → ${price}")
                market_log_rows.append([
                    today, cert, game, card_number, character, set_name,
                    "", total, f"{all_median:.2f}", f"{top_median:.2f}" if top_median else "",
                    "", "", "", "仕入値なし", f"{price}",
                ])

            time.sleep(0.5)

    # NO-GOのカードをCSVから除外
    if skip_certs:
        rows = [rows[0]] + [
            r for r in rows[1:]
            if str(r[cert_col_idx]) not in skip_certs
        ]
        print(f"\n📋 NO-GO {len(skip_certs)}件をCSVから除外しました")

    # market_log.csv に追記
    if market_log_rows:
        log_exists = os.path.exists(MARKET_LOG_FILE)
        os.makedirs(os.path.dirname(MARKET_LOG_FILE), exist_ok=True)
        with open(MARKET_LOG_FILE, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            if not log_exists:
                writer.writerow(MARKET_LOG_HEADERS)
            writer.writerows(market_log_rows)
        print(f"📊 市場ログ: {MARKET_LOG_FILE} ({len(market_log_rows)}件追記)")

    # CSV出力先: iMakHQ/csv_output/tcg_upload_<timestamp>.csv （他カテゴリと命名規則統一）
    output_file = _gcop("tcg", "upload")
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        writer.writerows(rows)

    # Free Shipping 移行: post-processor で _free.csv 生成 (2026-05-18)
    # 既存 logic 触らず CSV のみ price+DDP 加算 & ShippingProfile=Free に置換
    try:
        from freeshipping_postprocess import transform_csv_to_freeshipping
        transform_csv_to_freeshipping(output_file)
    except Exception as _e:
        print(f"⚠️ Free Shipping post-process 失敗 (TCG): {type(_e).__name__}: {_e}")

    # Step 8 拡張: decision_log に config_version + 使用値を刻印
    try:
        from decision_log import log_csv_batch as _log_batch
        _log_batch(project="iMakTCG", category="TCG(PSA10)",
                   output_path=output_file, row_count=max(0, len(rows) - 1))
    except Exception as _e:
        print(f"⚠️ decision_log 失敗 (TCG): {type(_e).__name__}: {_e}")

    # 仕入値データをサイドカーJSONとして保存（check_csv.pyが参照）
    if cost_map:
        cost_file = output_file.replace(".csv", "_cost.json")
        with open(cost_file, "w", encoding="utf-8") as f:
            json.dump(cost_map, f, ensure_ascii=False, indent=2)
        print(f"仕入値データ: {cost_file}")

    print(f"\n完了！出力: {output_file}")

    # 生成時セルフ監査 (CSV監査くんを自動実行) — 監査項目を「待たず」生成で確認する。
    try:
        from listing_common import run_self_audit
        run_self_audit(output_file)
    except Exception as _e:
        print(f"⚠️ セルフ監査 失敗 (非致命): {type(_e).__name__}: {_e}")
    print(f"成功: {len(rows)-1}件 / 失敗: {len(errors)}件")
    if errors:
        print(f"失敗: {', '.join(errors)}")

    # eBay フィルタ validate サマリー (= 3 ケース処理 + Gemini 改善 B レポート)
    print_ebay_filter_report()

    # CSVチェッカー自動実行
    # Phase D (2026-04-29): subprocess.run → 関数呼出. 同一プロセスにすることで
    # market_gate の in-memory cache が共有され、median ブレ (psa_to_csv $140 vs
    # check_csv $115 等) が解消する. 詳細: memory dual_gate_disagreement.md
    if len(rows) > 1:
        print(f"\n{'═'*60}")
        print("  CSVチェックを開始します...")
        print(f"{'═'*60}\n")
        try:
            from check_csv import main as _check_csv_main
            _check_csv_main(output_file)
        except Exception as e:
            print(f"⚠️ チェッカー実行エラー: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

    # Catalog 未登録カード一覧 + 共有通知ファイル追記 (2026-05-09、gshock_to_csv と同パターン)
    if catalog_misses:
        notify_dir = "C:/dev/iMak_data/catalog"
        notify_path = f"{notify_dir}/missing_models.csv"
        try:
            os.makedirs(notify_dir, exist_ok=True)
            file_exists = os.path.exists(notify_path)
            with open(notify_path, "a", encoding="utf-8") as f:
                if not file_exists:
                    f.write("category,model,detected_at\n")
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                for category, model in catalog_misses:
                    f.write(f"{category},{model},{ts}\n")
        except Exception as _e:
            print(f"⚠️ missing_models.csv 書込失敗: {type(_e).__name__}: {_e}")

        print("\n" + "=" * 70)
        print(f"⚠️ Catalog 未登録カード {len(catalog_misses)} 件 (Catalog Claude に追加依頼してください)")
        print("=" * 70)
        for category, model in catalog_misses:
            print(f"  - [{category}] {model}")
        print(f"\n通知ファイル: {notify_path}")

    # 対話実行(出品くんパネル)では Enter 待ち。非対話(psa_restock_build 等の subprocess)では
    # stdin が無く EOFError → 以前は returncode=1 で落ち、RESTOCK の Add→Revise 変換が中断していた。
    # 非対話時は待たずに正常終了する。
    try:
        if sys.stdin and sys.stdin.isatty():
            input("\nEnterで終了...")
    except (EOFError, OSError):
        pass

if __name__ == "__main__":
    main()
