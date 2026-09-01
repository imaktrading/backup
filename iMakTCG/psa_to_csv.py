#!/usr/bin/env python3
# iMak Trading Japan - PSA Cert → eBay CSV 自動生成スクリプト
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
PSA_IMAGE_OVERRIDE_PATH = r"C:/dev/iMak_data/dedupe/psa_image_override.json"
PSA_IMAGE_OVERRIDE_PATH = r"C:/dev/iMak_data/dedupe/psa_image_override.json"
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

# eBay PicURL 制約 (ErrorCode 20002): 1本 500 字以内 / 全体 3975 字以内。
_PIC_URL_MAX_LEN = 500
# 本物の PSA カード画像 CDN (psa_cache CardImageUrl と一致)。
_PSA_CARD_CDN = "d1htnxwo4o0jhw.cloudfront.net"
# 画像でない host (トラッキング/解析ビーコン) と装飾/プレースホルダ。DOM に紛れる gomi を弾く。
# 2026-07-24: bat.bing.com ビーコン(582字)と table-image-ink プレースホルダが PicURL に混入し
# ErrorCode 20002 で入稿失敗 (cert 55542036 Vaporeon)。従来 filter ['cert','card','psa','grading']
# はビーコンURL内に埋め込まれた psacard.com/cert を拾って誤通過していた。
_PIC_TRACKER_HOSTS = ("bat.bing", "bing.com", "google-analytics", "googletagmanager",
                      "doubleclick", "facebook.com", "/action/", "gtm=", "/collect?")
_PIC_PLACEHOLDER = ("table-image", "placeholder", "spacer", "blank.", "sprite", "/logo")


def _is_real_card_image(src):
    """DOM から拾った img src が「本物の PSA カード画像」か判定 (トラッキング/装飾を除外)。純関数."""
    s = (src or "").strip().lower()
    if not s.startswith("http"):
        return False
    if len(src) > _PIC_URL_MAX_LEN:      # eBay 制約超 = そもそも載せられない
        return False
    path = s.split("?", 1)[0]
    if _PSA_CARD_CDN in s and "/cert/" in path:   # = 確実に本物のカード画像
        return True
    if any(h in s for h in _PIC_TRACKER_HOSTS):   # トラッキング/ビーコン host は明確に除外
        return False
    if any(p in path for p in _PIC_PLACEHOLDER):  # プレースホルダ/装飾を除外
        return False
    # 汎用: 画像拡張子で終わる + 従来キーワードを含むものだけ許可 (query 付きは path で判定)
    is_img = path.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif"))
    has_kw = any(x in s for x in ("cert", "card", "psa", "grading"))
    return is_img and has_kw


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
    # 2026-08-22 契約: Franchise / Autographed / Vintage / Material / Customized は出さない
    # (Franchise の eBay 37値は Disney Lorcana の作品名だけで TCG に該当なし。他4つは根拠の
    #  ある値が無く、固定値で埋めると足りないことが見えなくなる)
    "Card Size": "C:Card Size",
    # 2026-08-22 契約: Finish は出さない (現物を見ないと決まらない)
    "Attribute/MTG:Color": "C:Attribute/MTG:Color",
    "Illustrator": "C:Illustrator",
    "Cost": "C:Cost",
    "Attack/Power": "C:Attack/Power",
    "Defense/Toughness": "C:Defense/Toughness",
    "HP": "C:HP",
    "Stage": "C:Stage",
    "Card Condition": "C:Card Condition",
    "Speciality": "C:Speciality",
}

# TOPセラーの値で上書きしない項目（PSA/システムが決める値）
SPEC_NO_OVERRIDE = {
    "C:Grade", "C:Professional Grader", "C:Graded",
    "C:Manufacturer", "C:Language", "C:Country of Origin",
    "C:Year Manufactured",
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

def pokemon_out_of_scope(franchise, brand):
    """catalog が構造的に収録しない Pokemon サブセット = out-of-scope skip 対象 (純関数, test可)。

    現状: FAMILY POKEMON CARD GAME (はじめての〜) のみ。catalog 収録0件を実機確認済
    (2026-07-01 Pokemon 22006件中 Family 0件)。seen×18 で永久 recurring 化していたのを止める。
    ※XY期は catalog に173件あるので含めない (丸ごと除外すると出せるカードを殺す=K3不採用)。
    ★2026-07-26: BLACK DECK KIT を除外リストから外した。2026-06-27 時点は catalog 0件だったが
    その後 catalog に BDK-005/006 (わるいマグカルゴ/わるいヘルガー) が収録された (cert 138056958=
    BDK-006 が hit するのに本 skip で殺されていた)。ハードコード除外でなく catalog 有無で判定させる
    (catalog hit→出品 / no-hit→下流の catalog欠 fail-closed skip)= SSOT 原則。
    新サブセットを足す時も「catalog 0件」を実機確認してから追加する (誤除外=recall損 防止)。
    """
    if franchise != "Pokemon":
        return False
    b = (brand or "").upper()
    return "FAMILY POKEMON CARD GAME" in b


def is_out_of_scope_language(brand):
    """非日本語版(ASIA/KOREAN/CHINESE)は当店catalog(日本版)の対象外=fail-closed skip (純関数, test可)。

    PSA brand は日本版が '... JAPANESE ...'。ASIA/KOREAN/CHINESE 版は別商品で日本版 record へ
    解決しない(Catalog 2026-07-01 ruling)。従来はこれらが resolver 未解決 → missing_models に
    積まれ「catalog_add」として永久 recurring 化していた(例 POKEMON ASIA 25TH ANNIVERSARY、
    seen×21)。catalog に足しても当店は日本版のみ扱うため埋まらない → 早期 skip で汚染を止める。
    JAPANESE を含む brand は誤検出防止で対象外にしない(2026-07-02、won't-fix でなく監査/生成
    ルールを賢くする方針)。
    """
    toks = set((brand or "").upper().replace("-", " ").split())
    if "JAPANESE" in toks:
        return False
    return bool(toks & {"ASIA", "ASIAN", "KOREAN", "CHINESE"})


def should_skip_out_of_scope_language(brand, franchise, card_number, subject,
                                       lookup_pokemon_fn=None):
    """is_out_of_scope_language の catalog-aware 版 (純関数, test可)。

    非日本語 brand でも **日本版 catalog に解決できる Pokemon カードは skip しない**。
    PSA が日本版 25th Anniversary Golden Box(S8a-G) 等を "POKEMON ASIA 25TH ANNIVERSARY"
    と誤ラベルする例があり(cert 142931332 = S8a-G-005 Pikachu V)、brand 文字列だけの skip は
    false-positive(recall 損)になる。catalog 解決可否で最終判断 = fail-closed 維持(解決不能は skip)。
    lookup_pokemon_fn は test 用の注入口(未指定時は catalog_psa.lookup_pokemon)。
    """
    if not is_out_of_scope_language(brand):
        return False
    if franchise == "Pokemon":
        fn = lookup_pokemon_fn or catalog_psa.lookup_pokemon
        try:
            if fn(brand, card_number, subject):
                return False  # 日本版 catalog 解決 → 出品継続
        except Exception:
            pass
    return True


def is_unidentifiable_don_card(subject, card_number):
    """番号なしの DON!! カードは変種特定不能 → 出品対象外 skip (純関数, test可)。

    One Piece の DON!! カードは、番号(DON-PRB01-027 等)があれば正常に出品できるが、PSA データで
    card番号が欠落(#None)している個体は「どの DON 変種か」特定できず catalog key 付与も正しい出品も
    できない(fail-closed)。Catalog も無番=収録却下と判定済(2026-07-02)。番号有り DON は skip しない。
    ※入力データ(PSA)が構造的に特定不能なケースであり、システム欠陥の握りつぶしではない
    (=処理境界の定義。Gemini 諮問結論。number 有りは対象外にしないので listable な DON は殺さない)。
    """
    subj = (subject or "").upper()
    num = (card_number or "").strip()
    return "DON!!" in subj and not num


# 目視で確定した cert → product_id の台帳。post_psa_review が書き、**ここが読む**。
# ★2026-08-09 発見: 601件(うち593件が product_id 付き)が保存されているのに、
#   同定側が誰も読んでいなかった。出せなかった DON!! 14件のうち **13件は既に人が
#   選び終わっていて、catalog にも実在**していた (cert149436895→DON-PRB02-001 等)。
#   同定を毎回ゼロからやり直す設計だったため、人の答えがその回限りで捨てられていた。
#   memory: listing_data_is_permanent_asset (目視・探索の高コスト情報は資産化する)
VERIFIED_CERTS_PATH = r"C:/dev/iMak_data/dedupe/verified_certs.json"
_VERIFIED_CHOICES = ("CHOSEN", "OK")


def confirmed_product_id(cert, path=VERIFIED_CERTS_PATH):
    """目視で確定済みの product_id を返す。無ければ None (純関数寄り, test可)。

    fail-closed:
      - choice が CHOSEN / OK 以外 (NONE / NG 等) は **採用しない**
      - product_id 空は None
      - ファイルが読めない / 壊れている も None (推測しない)
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f) or {}
    except Exception:
        return None
    rec = data.get(str(cert))
    if not isinstance(rec, dict):
        return None
    if (rec.get("choice") or "").upper() not in _VERIFIED_CHOICES:
        return None
    pid = (rec.get("product_id") or "").strip()
    return pid or None


def confirmed_catalog_record(cert, category, path=VERIFIED_CERTS_PATH, lookup_fn=None):
    """確定済み product_id を catalog で引き直したレコード。引けなければ None。

    ★台帳を**そのまま信じない**。catalog に実在する時だけ返す (ID完全一致 lookup のみ)。
      台帳は人の入力なので、catalog 側で消えた/変わった ID を掴んだまま出品しない。
    """
    pid = confirmed_product_id(cert, path)
    if not pid:
        return None
    fn = lookup_fn
    if fn is None:
        try:
            import api as _api                          # catalog の公開 API
            fn = _api.lookup
        except Exception:
            return None
    try:
        return fn(category, pid) or None
    except Exception:
        return None


def don_treatment_subject(subject, card_number, vision_result):
    """番号なし DON!! に Vision の treatment を連結した subject を返す (純関数, test可)。

    Catalog 回答 (2026-07-10): catalog は DON を `DON-{set_code}-{NNN}` + `psa_subject_hint` で
    識別可能 (265件収録)。**真因は生成器が treatment を渡していないこと**。treatment は
    card_identifier(Vision) の `rarity` 欄に入る (例 'Alternate Art Gold')。
    実測: lookup_don(subject='DON!! CARD ALTERNATE ART GOLD') → DON-EB04-002 / 'DON!! CARD' → None。

    戻り: 連結後 subject。DON!!でない / 番号有り / treatment 無し → None (= 連結不可)。
    treatment 無しの DON は従来どおり fail-closed skip (推測で出さない)。
    """
    if not is_unidentifiable_don_card(subject, card_number):
        return None
    treat = ((vision_result or {}).get("rarity") or "").strip()
    if not treat:
        return None
    return f"{subject} {treat}"


def don_lookup_subject(subject, subj_try):
    """DON lookup に渡す subject を選ぶ純関数(2026-07-25)。

    treatment 連結版(subj_try = don_treatment_subject の戻り)が有ればそれを使い、無ければ
    原 subject を返す。★PRB02 Buggy/Shanks は Vision で rarity(treatment) が空でも
    vision_character 単独で解決できる(Catalog POC f6834e1) → treatment 空(subj_try=None)でも
    原 subject で lookup_don を試すための subject 選択。従来は subj_try 無=即skip だった欠陥の根治。
    """
    return subj_try or subject


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
    elif "DRAGON BALL HEROES" in brand_upper:
        # Super Dragon Ball Heroes はアーケード専用カード(別商品ライン)。catalog は
        # Dragon Ball Super Card Game (SCG) のみ収録 → Heroes はスコープ外。
        # franchise を専用値で返し、caller (build_row) で fail-closed skip させる。
        # (2026-06-27 K4: "DRAGON BALL" の総称分岐が Heroes を SCG に誤分類し missing_models を
        #  汚染していた=seen×3の再発。Yu-Gi-Oh! と同じ out-of-scope skip パターンで根治)
        return "Dragon Ball Heroes", brand, "Dragon Ball Heroes"
    elif "ITAJAGA" in brand_upper or "イタジャガ" in brand:
        # ITAJAGA(イタジャガ)= カルビースナック封入の食玩プロモ。公式TCGカタログ(SCG)対象外。
        # Brand="ITAJAGA DRAGON BALL VOL.N" が下の "DRAGON BALL" 分岐で dragonball_scg に誤分類され
        # → auto_catalog_add 空撃ち + missing_models 居座り(seen×9-10・7/16以来)で recurring_missing を
        # 汚染していた。Dragon Ball Heroes と同じ out-of-scope skip パターンで根治(2026-07-25・Catalog要求)。
        # franchise を専用値で返し、build_row で fail-closed skip させる(= dragonball_scg 照会も miss登録もしない)。
        return "Itajaga", brand, "Itajaga"
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


# franchise (detect_game_info の第3戻り値) → catalog category key。
# build_row 内の各 elif ブロックが _record_canonical_pid に渡す文字列リテラルと同じ対応。
FRANCHISE_TO_CATALOG_CATEGORY = {
    "One Piece": "one_piece_tcg",
    "Pokemon": "pokemon_tcg",
    "Dragon Ball": "dragonball_scg",
    "Gundam": "gundam_tcg",
    "Yu-Gi-Oh!": "yugioh_tcg",
}


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
- Start with "PSA " + the grade you actually read on the label (usually "PSA 10"; if the label
  says MINT 9 write "PSA 9"). NEVER write a grade you did not see on the label.
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
  "psa_grade": "The grade number printed on the PSA label in the image (right side). 'GEM MT 10' → '10', 'MINT 9' → '9', 'NM-MT 8' → '8'. Read it from the image, do NOT assume 10. Blank only if the label is unreadable.",
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

def psa_image_substitute(cert):
    """PSA に画像が無い cert → **代わりに使う cert** (無ければ "")。

    ★PSA 側に画像が存在しない個体があり、何度走っても取れない (実例 102629645)。
      同じカードの別 cert の画像を使う。商品説明に「証明番号が異なる個体が届くことが
      ある」と明記しているので齟齬は生じない (2026-08-14 ユーザー確定)。
    """
    try:
        with open(PSA_IMAGE_OVERRIDE_PATH, encoding="utf-8") as f:
            m = json.load(f) or {}
    except Exception:
        return ""
    v = m.get(str(cert or "").strip()) or {}
    return str(v.get("from_cert") or "").strip()


def load_description():
    """商品説明テンプレを読む。**読めなければ例外で止める** (2026-08-13)。

    ★以前は読取失敗を握りつぶして 1行の代用文を返していた。呼び手は本物か代用文か
      区別できないため、**その走行の全カードの説明が72字の1行**になり、そのまま
      「入稿OK」まで通った (2026-08-12 19:43 の走行、6件)。ユーザーが目視で発見。
      黙って代用するくらいなら **止めて気づかせる** 方が安全 (fail-closed)。
    ★パスは **このスクリプトの場所を基準にした絶対パス**。相対パスだと実行時の
      カレントディレクトリ次第で開けなくなる (読めなかった原因の第一候補)。
    """
    path = DESCRIPTION_FILE
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            body = f.read()
    except OSError as e:
        raise RuntimeError(
            f"商品説明テンプレを読めません: {path} ({type(e).__name__}: {e}) "
            f"  → 代用文で出品すると全カードの説明が1行になるため、ここで止めます。"
        ) from e
    if len(body) < 2000:
        raise RuntimeError(
            f"商品説明テンプレが短すぎます: {path} ({len(body)}字) "
            f"  → 壊れている疑い。通常は 13,000字前後。ここで止めます。"
        )
    return body


# 商品説明 Specs ブロックのヘルパは新コア(tcg_listing_fields)に集約=SSOT。旧コアも同一を使う
# (新コア override が新値で description を作り直す replace_tcg_specs も同モジュール)。
from tcg_listing_fields import build_tcg_specs_html, insert_tcg_specs  # noqa: E402,F401

PSA_IMG_HOST = "d1htnxwo4o0jhw.cloudfront.net"


def psa_large_variant(url):
    """PSA 画像 URL の `/small/`(380x640) を `/large/`(1140x1920) にする (純関数)。

    ★なぜ効くか (2026-07-27 に判明):
      - **eBay 商品画像(PicURL)**: 380px ではズームが効かず、PSA スラブの状態が見えない
        (eBay はズームに 1600px 以上を推奨)。高額カードほど購入判断されにくい。
      - **Vision の同定**: ★(パラレル)1個や card_number の細部が潰れる。実際 Perona
        OP01-077_p4/p5 は /small/ では判別不能、/large/ で ★ が読めて確定できた。
      - psa_cache / viewer / PicURL は同じ URL を共有するので、**取得時点で上げれば全部効く**。
    対象外(別ホスト / 既に large)は None。
    """
    if not url or PSA_IMG_HOST not in url or "/small/" not in url:
        return None
    return url.replace("/small/", "/large/")


def upgrade_psa_images(urls, exists):
    """PSA 画像 URL list を /large/ に上げる。`exists(url)->bool` が False なら元のまま。

    /large/ が無い cert がありうるので **実在確認できた時だけ**差し替える
    (PicURL が 404 だと eBay 側で画像なし = さらに悪い)。純関数 (存在確認は注入)。
    """
    out = []
    for u in urls or []:
        big = psa_large_variant(u)
        out.append(big if (big and exists(big)) else u)
    return out


def _url_exists(url, timeout=8):
    """HEAD で 200 か確認 (I/O)。失敗は False (= 元URL を使う fail-safe)。"""
    try:
        import urllib.request
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


_SUPPLIER_NON_PSA10 = re.compile(r"PSA\s*[・･]?\s*([1-9])(?![0-9])", re.IGNORECASE)
# PSA 以外の鑑定会社。当店は **PSA10 のみ**を出すので、仕入元が他社と明記していたら入口で落とす。
# ★2026-08-23 ユーザー規定「PSA10のみの出品」。番号だけ入力されると PSA のサイトを引いてしまい、
#   たまたま同じ番号の別カードが返ると **別カードとして出品**される (最も危険な型)。
#   BGS/CGC は数字グレードを併記するので `PSA n` の正規表現では拾えない。
_SUPPLIER_OTHER_GRADER = re.compile(
    r"(?<![A-Za-z])(BGS|CGC|SGC|ARS|AGS|HGA|GRAAD|TAG)(?![A-Za-z])", re.IGNORECASE)
_SUPPLIER_PSA10 = re.compile(r"PSA\s*[・･]?\s*10(?![0-9])", re.IGNORECASE)


def supplier_grade_hint(supplier_title):
    """仕入元タイトル(商品管理シート C列)から「PSA10 でない」根拠を拾う (純関数)。

    ★これが 2026-07-27 の誤出品 6件を実際に発見した信号。
      例: 「【PSA9・ワンオーナー】バギー 金ドン スーパーパラレルドン ワンピースカード」
    `PSA10` は 10 なので拾わない (`[1-9](?![0-9])` で 1 桁のみ)。
    戻り: '9' 等のグレード / 'CGC' 等の他社名 / どちらも無ければ None。
    """
    if not supplier_title:
        return None
    t = str(supplier_title)
    m = _SUPPLIER_NON_PSA10.search(t)
    if m:
        return m.group(1)
    # 他社名は「PSA10 と書かれていない時」だけ根拠にする。
    # 「PSA10 CGCカードローダー付き」のように **付属品として他社名が出る**ことがあり、
    # そこで落とすと本物の PSA10 を1枠捨てることになる (グレードは後段で PSA ページから確かめる)。
    if _SUPPLIER_PSA10.search(t):
        return None
    m2 = _SUPPLIER_OTHER_GRADER.search(t)
    return m2.group(1).upper() if m2 else None


# 仕入元が「1枚ではない」と書いている表現 (2026-08-23 ユーザー確認事項)。
#   実データ 1,777行に当てて調整済。まとめ売り・連番スラブは、1枚だけ買うことができない
#   (買うと全部付いてくる = 仕入値が想定と違う / 1つの出品しか作れないのに複数枚を抱える)。
_SUPPLY_LOT = re.compile(
    r"(まとめ売り|まとめて|セット売り|連番"
    r"|(?<![0-9])([2-9]|[1-9][0-9])\s*枚)")
# 「世界に4枚」「現存3枚」等は **希少さの自慢**であって出品枚数ではない。
#   実データで唯一の誤検出がこれ (【8/8時点世界に4枚！】【PSA10】ロロノア・ゾロ)。
_SUPPLY_LOT_NOT = re.compile(r"(世界|現存|全国|残り|人気|限定|中)[^、。]{0,8}$")


def supply_lot_hint(supplier_title):
    """仕入元タイトルが「複数枚まとめ」と言っているか (純関数)。

    戻り: 根拠になった語 ('連番' '3枚' 等) / 単品と読めるなら None。
    """
    if not supplier_title:
        return None
    t = str(supplier_title)
    for m in _SUPPLY_LOT.finditer(t):
        if _SUPPLY_LOT_NOT.search(t[:m.start()]):
            continue                      # 「世界に4枚」= 枚数の自慢。出品枚数ではない
        return m.group(0)
    return None


def multi_card_certs(title_map):
    """{cert: 仕入元タイトル} → まとめ売りと読める cert の {cert: 根拠語} (純関数)。"""
    out = {}
    for cert, title in (title_map or {}).items():
        g = supply_lot_hint(title)
        if g:
            out[str(cert)] = g
    return out


def non_psa10_certs(title_map):
    """{cert: 仕入元タイトル} → PSA10 でないと **仕入元が明記している** cert の {cert: grade}。

    ★なぜ LLM タイトル側の gate だけでは不足か:
      Claude への prompt が `Start with "PSA 10"` と**指示している**ため、PSA9 でも
      素直に "PSA 10" と書いてしまう可能性が高い(今回はたまたま Claude が実物を優先して
      "PSA 9" と書いたので気づけただけ)。**仕入元表記は決定論的で、これが本命の gate**。
    純関数。
    """
    out = {}
    for cert, title in (title_map or {}).items():
        g = supplier_grade_hint(title)
        if g:
            out[str(cert)] = g
    return out


# PSA cache の「写真がある」を表す key。どれか1つでも URL があれば照合できる。
_PSA_IMAGE_KEYS = ("CardImageUrl", "CardImageUrlFront", "CardImageUrlBack")


def has_psa_photo(meta) -> bool:
    """PSA cache 1件に写真 URL があるか (純関数)。"""
    if not isinstance(meta, dict):
        return False
    return any(str(meta.get(k) or "").strip() for k in _PSA_IMAGE_KEYS)


def no_psa_photo_certs(certs, cache, substitute_fn=None):
    """**PSA 側に写真が無い** cert の {cert: 理由} (純関数)。

    ★2026-08-28: PSA が写真を残していない個体があり、何度取り直しても増えない。
      実測 psa_cache.json 1,308件のうち写真ゼロは **5件** (0.4%) で、いずれも 2020年前後の
      古い cert。この個体は目視で現物と照合できないので枠を食う前に落とす。
      **プログラムの不具合ではない**ので program_fix には積まない (狼少年になる)。
      依頼書: hq/requests/2026-08-28_act_code_proposals_tcg.md 提案1

    判定できないもの (cache に無い) は **含めない** = 落とさない (fail-closed の向きを守る)。
    代替画像 (psa_image_override.json) が在る cert も落とさない (写真は手に入る)。
    """
    sub = substitute_fn if substitute_fn is not None else psa_image_substitute
    out = {}
    for cert in (certs or []):
        c = str(cert)
        meta = (cache or {}).get(c)
        if not isinstance(meta, dict) or not meta:
            continue                      # cache 無し = 判定不能 → 触らない
        if has_psa_photo(meta):
            continue
        try:
            if sub(c):
                continue                  # 別 cert から借りられる
        except Exception:                                      # noqa: BLE001
            pass
        out[c] = "PSA に写真が無い個体 (取り直しても増えない)"
    return out


def detected_grade_from_title(title):
    """LLM が現物ラベルから読んだタイトル冒頭の "PSA <n>" から グレードを取る (純関数)。

    ★2026-07-27 事故: PSA **9** の Dragon Ball E-60 が **PSA 10 として** CSV 化された。
      - Claude は画像から正しく `PSA 9 Dragon Ball SCG ...` を生成していた
      - しかし build_title は `prefix = "PSA 10"` 固定、C:Grade も "10" 固定、
        さらに新コア override が C:Grade を読んで `PSA 10 ...` にタイトルを再生成
      → パイプライン全体が **PSA10 限定運用**の前提で、非PSA10 が混ざると全部 10 に化ける。
      価格も "PSA 10" で市場検索するため相場($8,450)を誤って引き、GO 判定まで出ていた。
    戻り: 数値文字列 ('9'/'10') / 取れなければ None。
    """
    if not title:
        return None
    m = re.match(r"\s*PSA\s+(\d{1,2})\b", str(title), re.IGNORECASE)
    return m.group(1) if m else None


def is_psa10_confirmed(title, psa_grade=None):
    """**PSA10 だと確かめられた時だけ True** (純関数)。

    ★2026-08-23 ユーザー規定「PSA10のみの出品と規定したらいい」。
      それまでは「10 でないと読めた時だけ止める / 読めなければ通す」だった (fail-open)。
      グレードが読めない個体は素通りしていて、タイトル・C:Grade・相場が全部 "10" 固定の
      このパイプラインでは **グレード誤表示のまま出る**。読めないものは出さないに反転する。

    判定材料 (どちらかが '10' と言えば確定。片方でも '10 以外' なら不可):
      1. `psa_grade` = PSA のページの Item Grade (一次情報)。無ければラベル画像の読み
      2. `title` 冒頭の `PSA <n>` (副次。こちらの生成物なので単独では根拠にしない)
    どちらも読めなければ False = 出さない。
    """
    grades = [str(psa_grade or "").strip(), detected_grade_from_title(title) or ""]
    if any(g and g != "10" for g in grades):
        return False
    # ★タイトルは自分で組んだ文字列なので、単独では「確かめた」ことにしない。
    #   現物由来 (PSAページ / ラベル画像) の psa_grade が 10 と言った時だけ確定。
    return str(psa_grade or "").strip() == "10"


def is_psa10_or_unknown(title, psa_grade=None):
    """[旧仕様・2026-08-23 に廃止] 読めなければ通していた頃の判定。

    残してあるのは、どこかで呼ばれていた時に **黙って挙動が変わらない**ようにするため。
    新しい規定は `is_psa10_confirmed`。
    """
    raise RuntimeError(
        "is_psa10_or_unknown は廃止 (2026-08-23 ユーザー規定: PSA10 のみ出品)。"
        "is_psa10_confirmed を使うこと")


# PSA cert ページの「項目名 → 次の行が値」形式 (2026-08-23 実取得で確認 / cert158363091)。
#   Item Grade        GEM MT 10
#   Variety/Pedigree  ALTERNATE ART
#   Label Type        W/ FUGITIVE INK TECHNOLOGY
#   PSA POPULATION    836   /   PSA POP HIGHER   0
# ★グレードは従来 **Claude にラベル画像を読ませて**いた (推測)。ページに書いてあるので
#   そちらを一次情報として使う (2026-08-23 ユーザー承認)。
#
# ★2026-08-23 修正: **出品くんが見に行くのは日本語ページ** (`/ja-JP/cert/...`)。
#   英語の見出しだけを書いていたので一度も一致せず、グレードは常に空だった
#   (実測: 保存済 1,203件すべて Grade 無し / 実際に取り直しても空)。
#   日本語ページの実物 (cert158363091 を 2026-08-23 に取得):
#       グレード / GEM MT 10
#       ラベルタイプ / フュージティブインク技術搭載
#       バラエティ / ALTERNATE ART
#       グレーディング枚数 / 836      より高評価のグレーディング枚数 / 0
#   英語見出しも残す (URL を英語に戻しても動くように)。
_PSA_PAGE_FIELDS = {
    "グレード":            "Grade",
    "Item Grade":          "Grade",
    "バラエティ":          "Variety",
    "Variety/Pedigree":    "Variety",
    "ラベルタイプ":        "LabelType",
    "Label Type":          "LabelType",
    "グレーディング枚数":  "Population",
    "PSA POPULATION":      "Population",
    "より高評価のグレーディング枚数": "PopHigher",
    "PSA POP HIGHER":      "PopHigher",
}


def _value_after_label(lines, label):
    """`label` と完全一致する行の次の行を返す (無ければ "")。純関数。"""
    lab = label.strip().lower()
    for i, line in enumerate(lines):
        if line.strip().lower() == lab and i + 1 < len(lines):
            return lines[i + 1].strip()
    return ""


def grade_number(item_grade):
    """'GEM MT 10' → '10' / 'MINT 9' → '9' / 読めなければ '' (純関数)。"""
    m = re.search(r"(\d+(?:\.\d+)?)\s*$", str(item_grade or "").strip())
    return m.group(1) if m else ""


def parse_psa_page(text):
    data = {}
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    # ページに明記されている項目 (グレード / 版 / ラベル種別 / POP) をそのまま拾う
    for _label, _key in _PSA_PAGE_FIELDS.items():
        _v = _value_after_label(lines, _label)
        if _v:
            data[_key] = _v

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


def _apply_image_substitute(driver, cert_number, data, cache):
    """画像が無い cert に **同じカードの別 cert の画像**を当てる (I/O)。

    対応表: iMak_data/dedupe/psa_image_override.json。表に無ければ何もしない。
    ★scrape 経路と **キャッシュ hit 経路の両方**から呼ぶこと (2026-08-15)。
      片方だけだと、既にキャッシュに居る cert (= まさに画像が無いもの) が素通りする。
    """
    sub = psa_image_substitute(cert_number)
    if not sub:
        return data
    sd = (cache or {}).get(sub)
    if not (sd and sd.get('CardImageUrlFront')) and driver is not None:
        sd = get_psa_data(driver, sub)
    if sd and sd.get('CardImageUrlFront'):
        data = dict(data)
        data['CardImageUrl'] = sd.get('CardImageUrl')
        data['CardImageUrlFront'] = sd['CardImageUrlFront']
        data['CardImageUrlBack'] = sd.get('CardImageUrlBack')
        data['CardImageFromCert'] = sub
        print(f"    📷 画像は cert {sub} から借用 (この cert は PSA に画像が無い)", flush=True)
    else:
        print(f"    ⚠️ 代替画像 cert {sub} からも取れず", flush=True)
    return data


def _upgrade_cached_images(cert_number, cached, cache):
    """キャッシュ済の PSA 画像 URL を /large/ に上げて書き戻す。

    上げられなければ元のまま (404 を PicURL に載せない)。純粋な関数ではないが、
    差し替えの判断自体は `upgrade_psa_images` (純関数) が持つ。
    """
    keys = ("CardImageUrl", "CardImageUrlFront", "CardImageUrlBack")
    urls = [cached.get(k) or "" for k in keys]
    if not any("/small/" in u for u in urls):
        return cached
    upgraded = upgrade_psa_images(urls, _url_exists)
    if upgraded == urls:
        return cached
    cached = dict(cached)
    for k, u in zip(keys, upgraded):
        if u:
            cached[k] = u
    try:
        cache[cert_number] = cached
        _save_psa_cache(cache)
    except Exception:                                          # noqa: BLE001
        pass
    return cached


# ★2026-08-26: **Chrome のセッションが死んだら作り直す**。
#   実害: 8/26 の走行で 3件目の途中で `invalid session id` になり、そこから先の 13件が
#   1件ずつ同じエラーで空振りした (20件中 出品できたのは 1件)。セッションが死んだ後は
#   何度呼んでも回復しないので、**気づいて作り直す**しかない。
_DEAD_SESSION_MARKERS = ("invalid session id", "no such window", "chrome not reachable",
                         "disconnected", "target window already closed",
                         "session deleted", "browser has closed")


def is_dead_session(exc):
    """その例外は「ブラウザが死んだ」か (純関数, test可)。"""
    m = f"{type(exc).__name__}: {exc}".lower()
    return any(k in m for k in _DEAD_SESSION_MARKERS)


def restart_psa_driver(old=None):
    """PSA 用の Chrome を作り直して返す。失敗したら例外を投げる (呼び手が止める)。"""
    global _psa_warmup_driver
    try:
        if old is not None:
            old.quit()
    except Exception:
        pass
    os.makedirs(_PSA_PROFILE_DIR, exist_ok=True)
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument(f"--user-data-dir={_PSA_PROFILE_DIR}")
    options.add_argument("--disable-features=CalculateNativeWinOcclusion")
    options.add_argument("--window-size=800,600")
    options.add_argument("--window-position=100,100")
    d = uc.Chrome(options=options, version_main=detect_chrome_major())
    try:
        d.minimize_window()
    except Exception:
        pass
    _psa_warmup_driver = d
    return d


def get_psa_data(driver, cert_number):
    # キャッシュチェック
    cache = _load_psa_cache()
    if cert_number in cache:
        cached = cache[cert_number]
        # ★2026-08-23: **グレードが入っていない保存分は取り直す**。
        #   「PSA10 のみ出品」を規定した以上、グレードは必須項目。8/23 朝に
        #   「グレードは PSA のページから読む」を入れたが、保存済の cert は早期 return で
        #   素通りしていて、その日出した9件すべてグレード未取得だった (= 規定が効かない)。
        #   1 cert につき一度だけ取り直せば、以降は保存分で足りる。
        if cached and cached.get('Subject') and 'Grade' not in cached:
            print(f"    ↻ グレード未取得のため PSA を取り直します (#{cert_number})")
        elif cached and cached.get('Subject'):
            # ★2026-08-15: **キャッシュ hit でも代替画像を当てる**。
            #   前回 (8/14) は scrape 経路にだけ入れたので、既にキャッシュにある cert
            #   (= まさに画像が無い 102629645) は早期 return で素通りし、3日連続で
            #   「PSA 画像が1枚も無い」で除外され続けた。画像が無いのは PSA 側の事情なので
            #   キャッシュを消しても直らない。読み出し口で当てるのが正しい。
            if not cached.get('CardImageUrlFront'):
                cached = _apply_image_substitute(driver, cert_number, cached, cache)
            # ★2026-08-21: /large/ 化が **scrape 経路にしか入っていなかった**。
            #   8/14 以前にキャッシュされた cert は /small/(380x640) のまま PicURL に載り、
            #   eBay のズーム (1600px 以上が必要) が効かない。高額行ほど効く
            #   (実例 2026-08-20: cert140936782 ジラーチGX $781.98)。
            #   読み出し口で上げて **キャッシュに書き戻す** = 次回から HEAD も飛ばない。
            cached = _upgrade_cached_images(cert_number, cached, cache)
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
                if not _is_real_card_image(src):   # トラッキングビーコン/プレースホルダ/長すぎURL を除外
                    continue
                if src in card_image_urls:
                    continue
                card_image_urls.append(src)
                if len(card_image_urls) >= 2:
                    break
        except Exception as e:
            print(f"\n    画像取得エラー: {e}")

        data = parse_psa_page(body)
        # ★取りに行った事実を残す。ページに Item Grade が無い個体で
        #   「未取得だから取り直す」が毎回起きて無限に叩きに行くのを防ぐ。
        #   空のまま = グレード不明 → PSA10 と確かめられないので出品はしない。
        data.setdefault('Grade', '')
        if card_image_urls:
            # ★取得時点で /large/(1140x1920) に上げる。PicURL(eBay商品画像)・Vision同定・
            #   psa_cache・viewer が同じ URL を共有するので、ここ1箇所で全部に効く。
            #   実在確認できた分だけ差し替え (404 を PicURL に載せない)。
            card_image_urls = upgrade_psa_images(card_image_urls, _url_exists)
            data['CardImageUrl'] = card_image_urls[0]   # = 表面 (= 既存 title 生成等で使用)
            if len(card_image_urls) >= 2:
                # 2枚取れた時だけ順序(表→裏)を信用する。実サンプルで [0]=表面を確認済。
                data['CardImageUrlFront'] = card_image_urls[0]
                data['CardImageUrlBack'] = card_image_urls[1]
                # ★2026-08-13: 1件ごとに2〜3行使っていたので、呼び手の行末に足す
                print(" 📷2", end="", flush=True)
            else:
                # ★2026-07-28: **1枚しか拾えなかった時は表面と断定しない**(fail-closed)。
                # 実例 cert 150712284: 1枚だけ取れた画像が **裏面**(青いカード裏)だったのに
                # Front として記録され、eBay 商品画像も Vision 同定も裏面を見ていた。
                # Front を空にすることで build_pic_url が載せず、目視で気づける。
                data['CardImageUrlUnknownSide'] = card_image_urls[0]
                print(f"    ⚠️ PSA 画像 1 枚のみ = 表裏不明 → 商品画像に使わない (面確定できず)")
        # ★2026-08-14: **PSA に画像が無い個体**がある (実例 cert 102629645 ボア・ハンコック
        #   OP07-038 = 文字情報は取れるのに画像URLが1つも無い)。取得失敗ではなく PSA 側に
        #   無いので、次回走っても永久に取れず、毎回1枠を食って除外されていた (2日連続)。
        #   → **同じカードの別 cert の画像**を代わりに使う (ユーザー確定)。商品説明に
        #     「証明番号が異なる個体が届くことがある」と明記済なので齟齬は生じない。
        #   対応表: iMak_data/dedupe/psa_image_override.json  {cert: {"from_cert": "…"}}
        if not data.get('CardImageUrlFront'):
            data = _apply_image_substitute(driver, cert_number, data, cache)

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
        if is_dead_session(e):
            raise                      # 呼び手が Chrome を作り直して やり直す
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


# ★2026-08-21: この6表は psa_to_csv.py / psa_restock_csv.py に **同じ内容で2本**あった。
#   片方だけ直せば即ズレるので1本化した。実体は tcg_set_rarity_maps.py。
from tcg_set_rarity_maps import (  # noqa: E402,F401
    _DRAGONBALL_SET_NAME_MAP, _RARITY_FULL_FOR_TITLE, _RARITY_TO_FEATURES,
    DRAGONBALL_SET_PREFIX, GUNDAM_SET_PREFIX, POKEMON_SET_NAME_MAP)



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
        # 最終防波堤: 500字超 or 非画像URL は載せない (ErrorCode 20002 の二重ガード)。
        if f and _is_real_card_image(f):
            parts.append(f)
        if b and b != f and _is_real_card_image(b):
            parts.append(b)
    parts.append(PIC_URL)   # 999.png ダミーは常に末尾 (front/back が無くても最低1本)
    return "|".join(parts)


# 2026-06-09: 短タイトル(<70)を catalog の実ファクトだけで補強 (year/rarity/set code)。
# 捏造しない: facts が無ければ伸ばさない。refine_title の後 (= 短縮されない最終段) で適用。
# catalog rarity short code → eBay Features 値 (TOPセラーは rarity descriptor を Features に入れる慣習)。
# Features が variant/PSA Subject から取れない時のフォールバック (= 実属性、捏造でない)。
# ★2026-08-19: 上の表のキーは**略号**だが、Pokemon の official_rarity は lookup_pokemon が
#   既に eBay 綴りに展開して返す (`'Special Art Rare'`)。そのため Pokemon では 100% 空振りし、
#   直近12CSV の Pokemon 23行中18行が C:Features 空だった (One Piece は略号のままなので当たる)。
#   `'SPECIAL ART RARE': …` を手で足すと**表が2つに増えて片方だけ更新される**ので、
#   値側もキーにした派生辞書を1本だけ作る (SSOT は上の表のまま)。
#   回答書: hq/requests/2026-08-19_act_code_proposals_tcg_response.md の 8
_RARITY_FEATURES_LOOKUP = {
    **_RARITY_TO_FEATURES,
    **{v.upper(): v for v in _RARITY_TO_FEATURES.values()},
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


def build_row(cert_number, price, data, description, driver=None, catalog_misses=None, pid_by_cert=None):
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
    # 2026-08-09 canonical product_id sidecar 用 (= build_row 内で catalog が返した card_id を
    # ここに集める。CSV には列を足さず、caller が並置 JSON に書く。呼出元が dict を渡さない場合は
    # no-op)。詳細: 2026-08-09_rarity_exclusion_needs_canonical_product_id_response.md
    def _record_canonical_pid(pid, category=""):
        """sidecar に載せる canonical PID を控える。

        ★2026-08-23: **category を前置きして `{category}:{product_id}` で控える**。
        product_id だけだとワンピ↔ガンダムで同じ ID が両方に在り (283件)、後段が
        別ゲームの行を引く。実害: cert154825163 (ワンピ) が `ST02-001` として控えられ、
        Item Specifics とタイトルが Gundam Wing Gundam になって出品された。
        枝番 (_p1 / _OTHER PRODUCT CARD_En 等) も落とさずそのまま持つ。
        """
        if pid_by_cert is not None and pid:
            pid = str(pid)
            if category and ":" not in pid:
                pid = f"{category}:{pid}"
            pid_by_cert[str(cert_number)] = pid
    game, set_name, franchise = detect_game_info(brand)

    # 2026-08-29 提案2: selfcheck 失敗時に「catalog を引けたのか」を言えるようにする
    # (①カタログの欠落 / ②出品くんの引き方 の判定をその場で付けるため)。
    # 各 franchise の分岐が hit/miss を判定した時に更新する (下の各 elif ブロック)。
    _catalog_hit = False
    _catalog_pid = ""

    # 2026-07-30: 共通ヘルパ tcg_scope.is_out_of_scope に SSOT 集約。
    # 従来は build_row 内に 4 分岐 (Yu-Gi-Oh!/Heroes/Itajaga/Pokemon FAMILY) が個別 return None、
    # 加えて post_psa_review._route_none_to_catalog が同じ真理表を持たず missing_models.csv に
    # SCG 対象外を毎日書き込んでいた (2026-07-29 Advisor 発覚)。片方だけ塞ぐと次に scope を
    # 変えた時にまた乖離するので、両方から 1 か所を呼ぶ形に統一。DIVERS も本 helper で新規除外。
    # ★2026-08-19: 言語ゲートが tcg_scope に入った (非日本語 Pokemon)。build_row は
    #   従来どおり catalog-aware にする = 日本版 catalog に解決できるなら skip しない。
    #   これを渡さないと cert142931332 (POKEMON ASIA 25TH ANNIVERSARY PROMO = 日本版
    #   S8a-G-005) が下の should_skip_out_of_scope_language の逃がし口に届かず落ちる。
    from tcg_scope import is_out_of_scope as _is_out_of_scope

    def _catalog_resolves_ja():
        try:
            return bool(catalog_psa.lookup_pokemon(brand, card_number, subject))
        except Exception:
            return False

    _oos, _oos_reason = _is_out_of_scope(franchise, brand,
                                         catalog_resolves=_catalog_resolves_ja)
    if _oos:
        print(f"    ⏭️ Skip: {_oos_reason} (cert {cert_number}, {subject})")
        return None

    # 非日本語版(ASIA/KOREAN/CHINESE)は当店=日本版のみ扱い → 対象外 skip。
    # catalog に足しても埋まらず missing_models を永久汚染するのを止める(2026-07-02)。
    # 2026-07-05: catalog-aware 化。PSA が日本版 25th Anniversary Golden Box(S8a-G) 等を
    # "POKEMON ASIA 25TH ANNIVERSARY" と誤ラベルする例がある(cert 142931332 = 日本版
    # S8a-G-005 Pikachu V が誤 skip されていた)。brand 文字列だけで撥ねず、日本版 catalog に
    # 解決できる Pokemon カードは出品する(false-positive skip = recall 損の防止)。解決できなければ
    # 従来通り fail-closed skip(誤出品防止は維持)。
    if should_skip_out_of_scope_language(brand, franchise, card_number, subject):
        print(f"    ⏭️ Skip: 非日本語版(ASIA/KOREAN/CHINESE)=日本版catalog未解決 (cert {cert_number}, brand='{brand}')")
        return None

    # 番号なし DON!! カード: 従来は無条件 skip だったが、Catalog 回答(2026-07-10)より
    # 「catalog は set+treatment で識別可能。真因は生成器が treatment を渡してないこと」= HQ の宿題。
    # → Vision が拾った treatment(rarity 欄)を subject に連結して catalog に問い、
    #   **実際に解決できた時だけ出品**(fail-closed 維持: 解決不能なら従来どおり skip)。
    _don_record = None
    if is_unidentifiable_don_card(subject, card_number):
        # 解決の手がかりは2系統: treatment(Vision rarity を subject に連結) or character(Vision)。
        # ★2026-07-25: PRB02 Buggy/Shanks 等は rarity(treatment) が Vision で空でも character 単独で
        #   一意解決できる(Catalog POC f6834e1: lookup_don の vision_character 一致 step)。→ treatment 空でも
        #   character が有れば lookup_don を試す(従来は treatment 空=即skip で character 経路に到達しなかった)。
        _subj_try = don_treatment_subject(subject, card_number, _vision_result)   # treatment付subject or None
        _vc = ((_vision_result or {}).get("character") or "").strip()
        _q_subj = don_lookup_subject(subject, _subj_try)   # treatment有れば連結subject、無ければ原subject
        _don_hit = None
        if _subj_try or _vc:
            try:
                # ★lookup_one_piece は番号空の DON を lookup_don に回さない(=None)。lookup_don を直接呼ぶ
                #   (2026-07-15)。vision_character 一致で同set内の複数キャラ Gold DON を1件に解決(tie解消)。
                _don_hit = catalog_psa.lookup_don(brand, _q_subj, vision_character=_vc or None)
            except Exception as _e_don:
                print(f"    ⚠️ DON lookup 失敗: {type(_e_don).__name__}: {_e_don}")
        if not _don_hit:
            # ★resolver が外した時だけ、**過去に人が確定した product_id** を使う (2026-08-09)。
            #   順番が大事: resolver を先に試し、それでも駄目な時の最後の手段にする
            #   (台帳を先に見ると、catalog が直った後も古い人の判断で上書きしてしまう)。
            _don_hit = confirmed_catalog_record(cert_number, "one_piece_tcg")
            if _don_hit:
                print(f"    🎯 DON: 目視確定済みの product_id を再利用 "
                      f"(cert {cert_number} → {_don_hit.get('product_id')})")
        if _don_hit:
            subject = _q_subj
            _don_record = _don_hit   # 本流(lookup_one_piece)は DON を解決できないので record を持ち回る
            print(f"    🎯 DON: catalog 解決 (cert {cert_number}, subject='{subject}', vision_character='{_vc or '無'}')")
        else:
            print(f"    ⏭️ Skip: reason=no_card_number_don DON!!カード番号欠落=変種特定不能 "
                  f"(cert {cert_number}, subject='{subject}', treatment={'有' if _subj_try else '無'}, "
                  f"character={_vc or '無'})")
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
        # 番号なし DON!!: lookup_one_piece は DON を解決しない(None)。上で lookup_don が
        # treatment 連結で解決済なら、その record を本流に流す(2026-07-15)。
        if not bandai and _don_record:
            bandai = _don_record
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
            _catalog_hit = True
            _catalog_pid = bandai.get("card_id") or bandai.get("product_id") or ""
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
                _record_canonical_pid(bandai_card_id, "one_piece_tcg")
            elif bandai.get("product_id"):
                # confirmed_catalog_record (_don_record → bandai 経路) は raw api.lookup 由来で
                # card_id ではなく product_id を持つ。sidecar には両方拾う。
                _record_canonical_pid(bandai.get("product_id"), "one_piece_tcg")
            # Set: adapter が ebay_filter_map で変換済み
            if bandai.get("set_name_ebay"):
                set_name = bandai["set_name_ebay"]
            # 2026-05-31: adapter 経由 finish / card_size を listing に反映
            # game = build_row line 502-505 で "One Piece CCG" (= eBay 正規値) 採用済
            # 検索 query 副作用は check_csv._normalize_game_short / market_gate に "One Piece CCG":"One Piece" 追加で吸収
            official_finish = bandai.get("finish") or ""
            official_card_size = bandai.get("card_size") or ""
        elif catalog_misses is not None:
            catalog_misses.append(("one_piece_tcg",
                                   missing_model_text(cert_number, brand, subject, card_number),
                                   subject, str(cert_number), brand))
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
            _catalog_hit = True
            _catalog_pid = pokemon.get("card_id") or pokemon.get("product_id") or ""
            official_rarity = pokemon.get("rarity", "")
            # ★2026-08-26 撤去: `official_power = pokemon.get("hp")`。
            #   HP を C:Attack/Power に写していたので、catalog の attack_power_ebay が
            #   空のポケモン行で **C:HP と同じ数字**が C:Attack/Power に出ていた
            #   (8/25 の入稿 17行中 6行)。HP は C:HP が持っている。
            #   依頼書: hq/requests/2026-08-25_act_code_proposals_tcg.md 提案1
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
            _record_canonical_pid(_catalog_pid_for_variant or pokemon.get("product_id"),
                                  "pokemon_tcg")
        elif catalog_misses is not None:
            catalog_misses.append(("pokemon_tcg",
                                   missing_model_text(cert_number, brand, subject, card_number),
                                   subject, str(cert_number), brand))

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
            _record_canonical_pid(db_card_id, "dragonball_scg")
            if db_card:
                _catalog_hit = True
                _catalog_pid = db_card_id
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
                _catalog_hit = True
                _catalog_pid = db_card.get("card_id") or db_card.get("product_id") or ""
                official_card_type = db_card.get("card_type", "")
                official_rarity = db_card.get("rarity", "")     # 既に eBay 形式
                official_color = db_card.get("color", "")
                official_power = db_card.get("power", "")
                official_cost = db_card.get("cost", "")
                # variant suffix を剥がした card_number
                db_full_id = db_card.get("card_id", "")
                if db_full_id:
                    official_card_number = re.sub(r'_.+$', '', db_full_id)
                    _record_canonical_pid(db_full_id, "dragonball_scg")
                elif db_card.get("product_id"):
                    _record_canonical_pid(db_card.get("product_id"), "dragonball_scg")
                if db_card.get("set_name_ebay"):
                    set_name = db_card["set_name_ebay"]
                if db_card.get("card_name"):
                    character = db_card["card_name"]
                # 2026-05-31: adapter 経由 finish / card_size を listing に反映 (game は rollback)
                official_finish = db_card.get("finish") or ""
                official_card_size = db_card.get("card_size") or ""
            elif catalog_misses is not None:
                catalog_misses.append(("dragonball_scg",
                                       missing_model_text(cert_number, brand, subject, card_number),
                                       subject, str(cert_number), brand))

    elif franchise == "Gundam":
        # iMakCatalog DB lookup (Phase 2: bandai_tcg_plus.fetch_card から移行).
        # ID 完全一致のみ + 名前検証. eBay フィルタ値変換は adapter で済.
        gd_card = catalog_psa.lookup_gundam(brand, card_number, subject)
        if gd_card:
            _catalog_hit = True
            _catalog_pid = gd_card.get("card_id") or gd_card.get("product_id") or ""
            official_card_type = gd_card.get("card_type", "")
            official_rarity = gd_card.get("rarity", "")     # 既に eBay 形式
            official_color = gd_card.get("color", "")
            official_power = gd_card.get("power", "")
            official_cost = gd_card.get("cost", "")
            # variant suffix を剥がした card_number
            gd_card_id = gd_card.get("card_id", "")
            if gd_card_id:
                official_card_number = re.sub(r'_.+$', '', gd_card_id)
                _record_canonical_pid(gd_card_id, "gundam_tcg")
            elif gd_card.get("product_id"):
                _record_canonical_pid(gd_card.get("product_id"), "gundam_tcg")
            if gd_card.get("set_name_ebay"):
                set_name = gd_card["set_name_ebay"]
            if gd_card.get("card_name"):
                character = gd_card["card_name"]
            # 2026-05-31: adapter 経由 finish / card_size を listing に反映 (game は rollback)
            official_finish = gd_card.get("finish") or ""
            official_card_size = gd_card.get("card_size") or ""
        elif catalog_misses is not None:
            catalog_misses.append(("gundam_tcg",
                                   missing_model_text(cert_number, brand, subject, card_number),
                                   subject, str(cert_number), brand))

    elif franchise == "Yu-Gi-Oh!":
        ygo = catalog_psa.lookup_yugioh(brand, card_number, subject)
        if ygo:
            _catalog_hit = True
            _catalog_pid = ygo.get("card_id") or ygo.get("product_id") or ""
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
            catalog_misses.append(("yugioh_tcg",
                                   missing_model_text(cert_number, brand, subject, card_number),
                                   subject, str(cert_number), brand))

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
        # ★2026-08-26 撤去: Vision が読んだ色での official_color 補完。
        #   契約 (_contract_aspects.yaml) の Attribute/MTG:Color は `specs.color_ebay` だけ。
        #   catalog が色を持たない Trainer / Energy 行 (実測 3,998行) に Vision の色が
        #   載っていた。8/25 は日本語 ('サポート') だったので日本語ガードが空欄化して
        #   助かっただけで、card_identifier_cache には 'Purple' 等の英語も入っている。
        #   依頼書: hq/requests/2026-08-25_act_code_proposals_tcg.md 提案3
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
    # ★2026-08-23: 本番 (TCG_USE_NEW_GEN=1) はタイトルを新コアが catalog 値で作り直すため、
    #   ここで作った Claude タイトルは捨てられていた (8/22 の走行で 19件中 19件)。
    #   グレードは PSA ページ本文の `Item Grade` から読めるので、画像を読む必要も無い。
    #   → 新コア有効 かつ グレードが読めた時は **API を呼ばない**。
    #   読めなかった時だけ従来どおり画像でラベルを確認する (fail-closed 維持)。
    _page_grade = grade_number(data.get("Grade"))
    if os.environ.get("TCG_USE_NEW_GEN") == "1" and _page_grade:
        claude_result = {}
    else:
        claude_result = generate_title_with_claude(
            game, set_name, official_card_number, subject_clean, franchise, card_image_url) or {}

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
    # ★2026-07-28: catalog に finish が無い時だけ、**PSA ラベルに明記された分**を転記する。
    # 推測は一切しない(画像の光り方・rarity からの類推は従来どおり禁止)。ラベル記載は
    # PSA が現物を鑑定して打った一次情報なので「確認できた事実」に当たる。
    # 実測: 823 cert 中 32件(3.9%)にのみ明記あり。残りは従来どおり空欄。
    finish    = official_finish      # Claude 追放 + Subject キーワード判定も廃止
    # 2026-08-22 撤去: PSA ラベル文字列からの Finish 転記。契約では Finish を出さない
    # (現物を見ないと決まらない)。catalog の finish が在る時だけ出す。
    attribute = official_color or official_attribute  # Claude 追放

    # 2026-08-22 撤去: Canonical Map (SR→Super Rare / Leader Card→Leader /
    # Alternate Art→Alternative Art)。catalog が rarity_ebay / card_type_ebay /
    # features_ebay に eBay の綴りを持っている。出品側で書き換えると二重定義になり、
    # catalog が綴りを直しても出品に届かない。契約: _contract_aspects.yaml

    # 2026-04-25: Leader カードは Cost / Power が無い設計
    # 　Bandai 側で誤って数値が入って返ってくるケースあり (例: cert 149801531 Shanks Cost=5)
    # 　→ Leader 確定なら強制空欄化（公式仕様準拠）
    # 2026-08-22 撤去: Leader の cost 強制空欄。catalog が Leader 503行の cost を life へ移した
    # (公式の Leader にコストは無い) ので、出品側で消す必要が無くなった。

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
    # ★PSA10 以外は出品しない (2026-07-27 事故: PSA9 が PSA10 として出かかった)。
    #   タイトル/CustomLabel/C:Grade/市場検索が全て PSA10 固定なので、非PSA10 は
    #   グレード誤表示 + 相場誤参照 になる。現物ラベルを読めた時だけ確実に止める。
    # PSA ページに書いてある値を最優先 (一次情報)。無ければ従来どおり画像判定の値。
    _vision_grade = _page_grade or ((claude_result or {}).get('psa_grade') if claude_result else None)
    if not is_psa10_confirmed(claude_title, _vision_grade):
        _g = (str(_vision_grade or "").strip() or detected_grade_from_title(claude_title))
        _src = "PSAページ" if _page_grade else ("ラベル画像" if _vision_grade else "")
        if _g and _g != "10":
            print(f"    🚫 PSA{_g} を検出({_src}) → **出品しない** (PSA10 のみ出品する規定。"
                  f"グレード誤表示 + PSA10 相場の誤参照になるため)")
        else:
            # ★読めなかった分も必ず理由を出す。黙って落とすと「なぜ減ったか」が分からない
            print(f"    🚫 グレードを確かめられなかった → **出品しない** "
                  f"(PSA10 のみ出品する規定・2026-08-23)。PSA ページの Item Grade が読めていません")
        return None
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
        # ★2026-08-29 提案2: 「必須Item Specific が空」等の failure に catalog 到達可否を付記。
        #   「引けなかった」=②出品くん / 「引けたが値が無い」=①カタログ、とその場で判定が付く。
        _annotated_errors = [annotate_selfcheck_error(str(_e), _catalog_hit, _catalog_pid, brand)
                             for _e in _errors]
        print(f"    ❌ セルフチェック失敗 (#{cert_number}):")
        for _e in _annotated_errors:
            print(f"       ❌ {_e}")
        print(f"    → この商品はCSVに含めません")
        # ★2026-08-18: ここで落ちた分は **ログに出るだけ** で誰にも届いていなかった。
        #   タイトル生成の不具合で毎回同じカードが落ちていても、人がログを読むまで
        #   分からない (cert151235549 ヤマトが実際にそうだった)。症状で dedup して積む。
        # ★2026-08-29 提案3: dkey に真因キー (catalog_reach_label) を含める。cert/brand は
        #   evidence (本文) 側だけに置く — dkey に入れると1枚1行に割れてしまう。
        _queue_finding("tcg", f"selfcheck:{str(_errors[0])[:60]}|{catalog_reach_label(_catalog_hit)}",
                       "program_fix",
                       f"#{cert_number}: {' / '.join(_annotated_errors)[:100]}",
                       layer="code", finding_type="program_fix")
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

    # 2026-08-22 撤去: 「Features が空なら rarity から埋める」。レアリティ語は Features では
    # ないので、8/22 の入稿で C:Features='Art Rare' / 'Super Rare' が 4件 eBay に出た(手で修正済)。
    # Features は catalog の features_ebay だけ。空なら空欄。

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
        rarity, features, manufacturer, "Japanese", year,
        # Country of Origin は catalog の country_of_origin_ebay が SSOT (2026-08-22 契約)。
        # 旧は「One Piece なら Japan」の自前ルール。新コアが解決できない行は空欄で出す。
        "",
        # Age Level 列は出力しない (2026-06-29 CPSC対応): PSA鑑定品=コレクター市場=非児童製品。
        card_size,
        attribute, illustrator, cost, power, "",
        "", "", "",   # C:HP / C:Stage / C:Speciality (旧コアは空・新コアが catalog hp_ebay/stage_ebay から充填)
        "Near Mint or Better", "10",
        "Professional Sports Authenticator (PSA)", "Yes",
        store_cat_id,
    ]

GSHEET_CREDS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..",
    "double-hold-421922-7c0d38d3f73d.json"
)


def _psa_cost_from_row(cost_n, price_m, price_f):
    """仕入¥ を N(SSOT)→ M(現在価格)→ F(取得時価格) の優先で決める。純関数(test可)。

    2026-07-24 根治: 従来 `N or F` で、N列(#REF!/空)の時に F列(=取得時の古い価格)へ
    フォールバックし、値下がりした品を過大 pricing していた(DON!! 出品時 F¥23,000 を拾い
    $279.98。実際は現価格 M¥14,000 → $184.98)。

    2026-08-02 統合: listing_common.pick_cost_jpy の thin wrapper に置換。
    N→M→F 優先は 5 listing scripts + offer_calc と 1 定義に集約 (三様問題の解消)。
    """
    from listing_common import pick_cost_jpy
    row = [""] * 14
    row[5] = "" if price_f is None else str(price_f)
    row[12] = "" if price_m is None else str(price_m)
    row[13] = "" if cost_n is None else str(cost_n)
    s = pick_cost_jpy(row)
    return int(s) if s else None


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

    # 出品済(itemID非空の同KEY行が在る)カードの集合。2枚目(itemID空・同KEY)を抽出段階で除外し、
    # viewer 毎回再表示の浪費を防ぐ(dedup は CSV 段階で消すが抽出=目視は止めないため。2026-06-26)。
    try:
        import sys as _sys
        _hq_tools = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "iMakHQ", "tools")
        if _hq_tools not in _sys.path:
            _sys.path.insert(0, _hq_tools)
        from sheet_io import (listed_key_forms as _listed_key_forms,
                              listed_certs as _listed_certs,
                              live_listed_certs as _live_certs,
                              already_listed_reason as _already_listed,
                              zero_qty_ghost_certs as _ghost_certs,
                              PRODUCT_COL_KEY as _KEY_COL)
        _listed = _listed_key_forms(all_values)
        # 出品済 cert は2つの根拠を union する。片方だけでは漏れる:
        #   シートB列 … 書き戻し漏れがある (実測 live PSA10 638件中 36件が空)
        #   live SKU  … dup_guard の cache 経由 (eBay は叩かない)。ただし `PSA10-<cert>`
        #               形式の出品しか cert を持たないので補完は部分的 (実測 +1件)
        _listed_cert = _listed_certs(all_values) | _live_certs()
    except Exception as _e_lk:
        print(f"  ⚠️ 出品済KEY算出失敗(抽出スキップ無効化して継続): {type(_e_lk).__name__}")
        _listed, _listed_cert, _KEY_COL = set(), set(), 34
        def _already_listed(cert, key, certs, keys):  # noqa: E306  (fallback: 従来どおり素通り)
            return ""

    cert_numbers = []
    cost_map = {}
    url_map = {}
    title_map = {}
    _skipped_listed = 0
    _skipped_cert = []
    _skipped_nocost = []
    for row in all_values[1:]:  # header 除外
        url      = (row[0]  if len(row) > 0  else '').strip()  # A
        item_id  = (row[1]  if len(row) > 1  else '').strip()  # B (空=未処理)
        title    = (row[2]  if len(row) > 2  else '').strip()  # C
        sold     = (row[3]  if len(row) > 3  else '').strip()  # D 売り切れ ('○'=売切)
        price_f  = (row[5]  if len(row) > 5  else '').strip()  # F "¥11,000"
        cert     = (row[8]  if len(row) > 8  else '').strip()  # I cert#
        no_go    = (row[10] if len(row) > 10 else '').strip()  # K NO-GO sentinel (= 「出品見合せ（仕入高）」 等)
        price_m  = (row[12] if len(row) > 12 else '').strip()  # M 現在価格(円) = 監視くん更新の最新
        cost_n   = (row[13] if len(row) > 13 else '').strip()  # N 仕入れ価格(円) = SSOT (M or F)−K
        category = (row[17] if len(row) > 17 else '').strip()  # R カテゴリ
        key_v    = (row[_KEY_COL] if len(row) > _KEY_COL else '').strip()  # AI canonical KEY

        if not cert or item_id or not url:
            continue
        # 統合シートは TCG / Tシャツ / 一番くじ / Montbell 等の混在。R列='TCG' のみ PSA 対象
        # (他 listing スクリプトと同じ R 列フィルタ運用に合わせる)
        if category != 'TCG':
            continue
        # ★2026-08-03: 二重出品ガード。cert 一致 = **同一の現物**が既に出品中 → 絶対に出さない
        #   (現物は1枚しかないので片方は必ず履行できない)。KEY 一致 = 同じカードの2枚目 → 従来どおり止める。
        #   旧実装は `key_v and key_v in _listed` の **fail-OPEN** で、KEY 未記入 / KEY 表記揺れ
        #   (`FB08-121_p1` vs `dragonball_scg:FB08-121_PARA`) の行が素通りしていた。
        #   実害: 2026-08-03 の CSV に既出品の cert 152687775 / 158452544 が入った (シート実測 同型24件)。
        #   ★必ず **カテゴリ判定の後**に置くこと。I列は PSA cert 専用ではなく montbell は型番を
        #   入れており (`1103247` が3行で共有)、前に置くと在庫のある別商品まで止める。
        _dup = _already_listed(cert, key_v, _listed_cert, _listed)
        if _dup == "cert":
            _skipped_cert.append(cert)
            continue
        if _dup:
            _skipped_listed += 1
            continue
        # D 列 売り切れ '○' は drop-shipping 不可 (仕入れ確実でないため出品 NG)
        if sold:
            continue
        # K 列 NO-GO sentinel (= 過去 cycle 価格 NO-GO 除外で書込) → 抽出対象外
        if no_go:
            continue
        # 仕入値: N(SSOT)→ M(現在価格)→ F(取得時) の優先。N#REF!/空でも M(最新)を拾う。
        _cost = _psa_cost_from_row(cost_n, price_m, price_f)
        # ★2026-08-13: 仕入値が1つも無い行は **出品しない** (fail-closed)。
        #   従来は cost なしでも通り、価格が $100 固定になっていた
        #   (`_cost_plus_price(None)` → 100.00)。¥40,000 のカードが $100 で出れば大赤字。
        #   実測: 未出品 356行のうち価格が1つも無い行は **0件** = 正常運用では影響しない。
        #   手で行を足した時 (新規出品候補からの転記等) の取りこぼしを止めるためのガード。
        if _cost is None:
            _skipped_nocost.append(cert)
            continue
        cert_numbers.append(cert)
        url_map[cert] = url
        title_map[cert] = title
        cost_map[cert] = _cost
    if _skipped_nocost:
        print(f"  🚫 仕入値なしガード: F/M/N が全て空 → 除外 {len(_skipped_nocost)}件 "
              f"→ {_skipped_nocost[:8]}{' …' if len(_skipped_nocost) > 8 else ''}")
        print(f"     (価格が無いと $100 固定で値付けされる = 赤字出品になるため出さない)")
    if _skipped_cert:
        # ★2026-08-31 (catalog 依頼 cert152976751): 「itemID 非空 = 出品済」だけでは、
        #   **取り下げ済み・器だけ残っている(qty=0)**行と、まだ生きている行を区別できない。
        #   qty=0 の方は毎回黙って落とされ続け、目視で8回 OK と答えても何も起きなかった。
        #   funnel の qty で分け、qty=0 は別の理由名で記録 + 別行で目立たせる (silent 禁止)。
        _ghost = _ghost_certs(all_values, _skipped_cert, _latest_funnel_qty_map())
        _live_skip = [c for c in _skipped_cert if c not in _ghost]
        if _live_skip:
            print(f"  🚫 二重出品ガード: 同一cert が既に出品済 → 除外 {len(_live_skip)}件 "
                  f"→ {_live_skip[:8]}{' …' if len(_live_skip) > 8 else ''}")
            print(f"     (同じ cert = 同じ現物。二度出すと片方は必ず履行できない)")
            # ★2026-08-07 重複くん要望: 抽出段で落とした cert を **後から追える形**で残す。
            #   抽出段は「目視削減の前段」であって判定の権威ではない。権威は重複くん。
            #   痕跡が無いと重複くんが「本来自分が捕まえるべきだった件」を audit できない。
            record_cert_skips("same_cert_already_listed", _live_skip)
        if _ghost:
            print(f"  ⚠️ 要対応: 出品の器はあるが在庫0 (取下げ済) → 除外 {len(_ghost)}件 "
                  f"→ {sorted(_ghost)[:8]}{' …' if len(_ghost) > 8 else ''}")
            print(f"     (RESTOCK で数量を戻すか、器を終了して出し直すかの判断が必要。"
                  f"status_now.py に出ます)")
            record_cert_skips("same_cert_zero_qty_ghost", sorted(_ghost))
    if _skipped_listed:
        print(f"  ⏭️ 既出品(同KEYが出品済)の2枚目を除外: {_skipped_listed}件 "
              f"(viewer毎回再表示の浪費防止。dedupと二重ではなく抽出段階で先に止める)")
    return cert_numbers, cost_map, url_map, title_map


CERT_SKIP_LEDGER = r"C:\dev\iMak_data\hq\extract_cert_skips.jsonl"
FUNNEL_DIR_FOR_GHOST_CHECK = os.path.normpath(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "iMakHQ", "funnel_output"))


def _latest_funnel_qty_map(funnel_dir=None):
    """最新 funnel CSV の {itemID: qty} (読めなければ空)。cert152976751 対応 (2026-08-31)。

    eBay は叩かない (funnel は cull_end / shelf_evict と同じローカル CSV)。
    ゴースト判定 (器はあるが在庫0) のためだけに使う。読めない/無い時は
    空を返し、呼出側は fail-closed (= 従来どおり「まだ生きている」扱い) に倒れる。
    """
    import csv as _csv
    import glob as _glob
    out = {}
    try:
        fs = _glob.glob(os.path.join(funnel_dir or FUNNEL_DIR_FOR_GHOST_CHECK, "funnel_*.csv"))
        if not fs:
            return out
        src = max(fs, key=os.path.getmtime)
        with open(src, encoding="utf-8") as f:
            for r in _csv.DictReader(f):
                iid = (r.get("item_id") or "").strip()
                if not iid:
                    continue
                try:
                    out[iid] = float(str(r.get("qty") or 0).replace(",", ""))
                except ValueError:
                    continue
    except OSError:
        return {}
    return out


def record_cert_skips(reason, certs, detail=None, path=None, now=None, print_fn=print):
    """枠を選ぶ前に落とした cert を **後から追える形**で残す (2026-08-07 / 2026-08-24 拡張)。

    ★なぜ: 抽出段は「目視を減らすための前段」であって判定の権威ではない。痕跡が無いと
      「出せるはずなのに目視に出てこない」を誰も追えず、そのたびに人が往復する
      (2026-08-24 重複くん依頼: cert168544559 が出てこない件の問合せ)。
    detail: {cert: 根拠} を渡すと一緒に残す (例 {"86028605": "2枚"})。
    書けなくても抽出は止めない (痕跡は補助であって本処理ではない)。
    """
    certs = [str(c) for c in (certs or [])]
    if not certs:
        return False
    import json as _json
    from datetime import datetime as _dt
    path = path or CERT_SKIP_LEDGER
    rec = {"ts": (now or _dt.now()).isoformat(timespec="seconds"),
           "stage": "psa_to_csv.extract", "reason": reason, "certs": certs}
    if detail:
        keep = set(certs)
        rec["detail"] = {str(k): v for k, v in detail.items() if str(k) in keep}
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(_json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except Exception as e:                                     # noqa: BLE001
        print_fn(f"     ⚠️ 除外痕跡の記録に失敗(続行): {type(e).__name__}")
        return False


_PSA_PROFILE_DIR = r"C:\Users\imax2\local_data\iMakHQ\chrome_profile_psa"
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


def keep_for_vision(res, meta=None):
    """preflight が引けなくても **Vision なら決まる見込み**がある cert か (純関数)。

    ★2026-08-28: 番号なし DON!! (`cert156843873` 等) が毎回「枠を選ぶ前に除外 [GAP]」で
      落ちていた。PSA が番号もキャラ名も出さないので文字情報だけでは原理的に決まらない
      (実測 `lookup_don(brand,'DON!! CARD')` → score=0 / 候補267件)。
      だが PSA 写真があれば Vision が色とキャラを読めて、
      `lookup_don(vision_character=...)` で解ける経路が既に在る (psa_to_csv:2276)。
      今の順序では **Vision に届く前に**落ちていた。
      写真が無ければ Vision も使えないので従来どおり落とす (fail-closed)。
      依頼書: hq/requests/2026-08-28_act_code_proposals_tcg.md 提案3
    """
    r = res or {}
    if r.get("status") != "GAP":
        return False
    if not is_unidentifiable_don_card(r.get("subject") or "", r.get("num") or ""):
        return False
    return has_psa_photo(meta)


def gap_queue_target(res):
    """preflight が GAP と言った cert の **積み先** を決める (純関数)。

    ★2026-08-28: GAP を「catalog 未収録」と断定してカタログへ送っていたため、
      今日カタログに飛んだ層A 6行が **6行とも誤り** (全部 catalog に実在) だった。
      名前で catalog を引いて **行が無いことを確かめた時だけ** カタログへ送る。
      確かめられていない分は「引き方 (②)」の課題なので HQ 側のキューに積む。
      依頼書: hq/requests/2026-08-28_act_code_proposals_tcg.md 提案2

    戻り: (target_field, layer, finding_type, evidence の頭)
    """
    if (res or {}).get("name_checked"):
        return ("catalog_add", "A", "catalog_gap", "今日も除外")
    return ("program_fix", "code", "program_fix", "引けないが未収録とは確認できていない")


def _queue_finding(category, item_id, field, evidence, *, layer="A",
                   finding_type="catalog_gap", identity="", reopen_closed=False,
                   catalog_state=""):
    """弾いた理由を改善キューに積む (= 次の監査で依頼/残務に流れる)。

    ★2026-08-18: 出品くんが弾いたもののうち、**画像が無い / 自己チェックで落ちた** は
      どこにも記録されず、ログに出るだけで消えていた。
      実害 (cert151235549 ヤマト): タイトル生成の不具合で毎回落ちていたが、
      人がログを読むまで誰も知らなかった。同じカードが毎日静かに落ち続ける。
      弾くのは正しい。**弾いた事実を誰かに渡していない**のが問題。
    失敗しても出品を止めない (記録は出品より優先しない)。
    """
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "..", "iMakHQ", "tools"))
        import pdca_store as _pdca
        con = _pdca.connect()
        _pdca.upsert_improvement(con, category, item_id, field, "",
                                 evidence=str(evidence)[:120], source="generator",
                                 layer=layer, finding_type=finding_type,
                                 identity=identity,
                                 ts=datetime.now().strftime("%Y-%m-%d"),
                                 reopen_closed=reopen_closed,
                                 catalog_state=catalog_state)
        con.commit()
        con.close()
        return True
    except Exception as e:                                     # noqa: BLE001
        print(f"    ⚠️ 記録できず (出品は継続): {type(e).__name__}: {e}")
        return False


def catalog_reach_label(catalog_hit):
    """selfcheck 失敗時の catalog 到達可否ラベル (純関数)。

    ★2026-08-29 提案2: 「引けなかった」=②出品くんの引き方 / 「引けたが値が無い」=①カタログ、
    とその場で 1丁目1番地の判定が付くようにする。brand/cert 等の可変部を含めない
    (提案3: dkey にそのまま使うと brand が cert ごとに違うため1枚1行に割れてしまう)。
    出典: hq/requests/2026-08-29_act_code_proposals_tcg_response.md 提案2・3
    """
    return "catalog=引けたが値空" if catalog_hit else "catalog=引けず"


def annotate_selfcheck_error(error_msg, catalog_hit, catalog_pid, brand):
    """selfcheck エラー文に catalog 到達可否を付記する (純関数)。

    可変部 (brand/pid) はここ (人が読むログ本文) にだけ入れる。dkey には
    `catalog_reach_label` の固定ラベルだけを使う (2026-08-29 提案2の条件)。
    """
    label = catalog_reach_label(catalog_hit)
    detail = f"pid={catalog_pid}" if catalog_hit else f"brand={brand!r}"
    return f"{error_msg} [{label}: {detail}]"


def missing_model_text(cert_number, brand, subject, card_number):
    """missing_models.csv の model 列を書式統一する (純関数)。

    ★2026-09-01: 従来は `f"{brand}-{card_number}"` で cert を持たなかったため、
    `pdca_store.normalize_item_key` の cert 抽出も `parse_missing_model_identity` の
    identity 抽出も素通りしていた。結果、同じカードが cert 有り(post_psa_review 由来)/
    cert 無し(psa_to_csv 由来)の2書式で pdca queue に別行として乗り、片方を close しても
    もう片方が翌日また Catalog に届く事故が起きた (queue 590/622, ONE PIECE ENCORE PACK-004)。
    `post_psa_review._route_none_to_catalog` と同じ書式 `cert{N} {brand} [{subject}] #{cardno}
    (...)` に揃えることで、どちらの経路でも同じ cert キーに畳まれ、identity も自動で埋まる。
    出典: hq/requests/2026-09-01_act_code_proposals_tcg_response.md 提案2
    """
    model = (f"cert{cert_number} {brand} [{subject}] #{card_number} "
             f"(missing_models: catalog未登録)").replace(",", " ")
    return " ".join(model.split())


def gate_catalog_misses(catalog_misses, csv_certs, pids_by_subject_fn):
    """`build_row` の catalog_misses (ID lookup miss) を missing_models 行き / program 行きに振り分ける。

    ★2026-08-31: `catalog_misses` は preflight の名前引きゲート (`gap_queue_target`,
      2026-08-28) を一度も通らず missing_models.csv に直書きしていた。実害:
      cert84299672 (ONE PIECE ENCORE PACK-004) は **同じ走行の入稿CSVに正しい値で載っている**
      のに「catalog 未登録」と記録された。
      出典: hq/requests/2026-08-31_act_code_proposals_tcg_response.md 提案1 (純関数, test可)

    1. その cert が **同じ走行の CSV に載っている** (= 出品できた=引けている) → 両方から除外
    2. 残りを subject 名だけで引き、**行が見つかれば** missing_models に書かず program 行き
       (②「引き方」の課題。ID抽出/正規化のバグ疑い)
    3. 名前でも見つからなければ (=空 token 等で確かめられない場合も含む) 従来どおり missing_models へ
       (= 「未収録」と新たに断定するわけではなく、これまでと同じ記録のまま)

    戻り: (missing:[(category,model)], program:[(category,model,subject,cert,hits)])
    """
    missing, program = [], []
    for m in catalog_misses:
        category, model, subject, cert, brand = m
        if cert and cert in csv_certs:
            continue
        hits = []
        try:
            hits = pids_by_subject_fn(category, subject, brand) or []
        except Exception:                                      # noqa: BLE001
            hits = []
        if hits:
            program.append((category, model, subject, cert, hits))
        else:
            missing.append((category, model))
    return missing, program


def _gate_catalog_misses_io(catalog_misses, csv_certs):
    """`gate_catalog_misses` の I/O 版 (catalog DB を開いて subject 名検索を実行)。

    DB を開けない等の失敗時は **ゲートせず従来どおり全件 missing_models へ** (fail-closed
    = 出品を止めない側優先。ここは「記録の粗さ」の話で、判定不能を握り潰しに倒さない)。
    """
    if not catalog_misses:
        return [], []
    try:
        import sqlite3 as _sq3
        _dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "iMakHQ", "tools")
        if _dir not in sys.path:
            sys.path.insert(0, _dir)
        import psa_preflight as _pf
        con = _sq3.connect(_pf.CATALOG_DB)
        cur = con.cursor()

        def _lookup(category, subject, brand):
            return _pf.pids_by_subject(cur, category, subject, brand)

        missing, program = gate_catalog_misses(catalog_misses, csv_certs, _lookup)
        con.close()
        return missing, program
    except Exception as e:                                     # noqa: BLE001
        print(f"    ⚠️ catalog_misses ゲート失敗 (従来どおり missing_models へ): {type(e).__name__}: {e}")
        return [(c, m) for c, m, *_ in catalog_misses], []


def _keys_for_dropped_dupes(sheet_rows, certs, cls, cert_col=8, key_col=34):
    """枠の前で落とす重複 cert → シートに書くべき ({join: row}, {join: KEY})。純関数.

    ★2026-08-18: KEY を書く処理は「その日のCSVに載った行」しか見ない。枠の前で落とすと
      KEY が空のまま残り、補URL追記が拾えず **生きた仕入元を1本捨てる**。
      落とす前にここで KEY を作って書く。
      既に KEY がある行は触らない (人が確定した値を上書きしない)。
      product_id を引けない cert も書かない (推測で埋めない)。
    """
    row_by_cert = {}
    for n, r in enumerate(sheet_rows[1:], start=2):
        c = (r[cert_col].strip() if len(r) > cert_col else "")
        if c and c not in row_by_cert:
            row_by_cert[c] = (n, (r[key_col].strip() if len(r) > key_col else ""))
    rows, keys = {}, {}
    for cert in certs:
        rec = (cls or {}).get(cert) or {}
        pid, cat = rec.get("product_id"), rec.get("category")
        hit = row_by_cert.get(str(cert))
        if not (pid and cat and hit) or hit[1]:
            continue                       # 引けない / 行が無い / 既にKEYあり → 触らない
        rows[cert], keys[cert] = hit[0], f"{cat}:{pid}"
    return rows, keys


def main():
    print("=== iMak Trading Japan - PSA → eBay CSV Generator ===\n")
    _psa_cloudflare_warmup()

    # 2026-04-24: certs.txt 廃止、スプシ駆動に完全移行
    # スプシ (19kj8... gid=851100680) の I列=cert# / B列=itemID空 / A列=URL で処理対象を抽出
    print("📊 スプシから PSA 出品対象を抽出中...")
    cert_numbers, cost_map, mercari_url_map, mercari_title_map = load_targets_from_sheet_psa()

    if not cert_numbers:
        print("処理対象なし（スプシに I列=cert# ありの未処理行が見つかりません）")
        input("Enterで終了...")
        return

    print(f"✓ {len(cert_numbers)}件の PSA 対象行を抽出（B列 itemID 空）")

    # ★PSA10 以外を入口で落とす (2026-07-27 誤出品事故の本命 gate)。
    #   本 pipeline は PSA10 限定運用 (title/C:Grade/相場すべて "10" 固定) なので、
    #   PSA9 等が混ざると **グレード誤表示のまま出品** される (実害 live 6件・全て END 済)。
    #   仕入元タイトルの "PSA9" 表記は決定論的で、実際にこの6件を発見した信号。
    _non10 = non_psa10_certs(mercari_title_map)
    if _non10:
        _hit = [c for c in cert_numbers if str(c) in _non10]
        if _hit:
            print(f"  🚫 PSA10以外(仕入元表記)を除外: {len(_hit)}件 "
                  f"→ {[f'#{c}=PSA{_non10[str(c)]}' for c in _hit]}")
            print("     (本 pipeline は PSA10 限定運用。グレード誤表示 + PSA10相場の誤参照になるため)")
            record_cert_skips("not_psa10_by_supply_title", _hit, detail=_non10)
            cert_numbers = [c for c in cert_numbers if str(c) not in _non10]

    # ★まとめ売り / 連番スラブ は出さない (2026-08-23 ユーザー確認)。
    #   1枚だけ買えないので、売れても仕入値が想定と違う (全部付いてくる) し、
    #   出品は1つしか作れないのに現物は複数枚になる。単品で出ている個体を待つ。
    _lots = multi_card_certs(mercari_title_map)
    if _lots:
        _hit = [c for c in cert_numbers if str(c) in _lots]
        if _hit:
            print(f"  🚫 まとめ売り/連番を除外: {len(_hit)}件 "
                  f"→ {[f'#{c}({_lots[str(c)]})' for c in _hit]}")
            print("     (1枚だけ買えない = 仕入値が想定と違う。単品の個体を待つ)")
            record_cert_skips("multi_card_lot_by_supply_title", _hit, detail=_lots)
            cert_numbers = [c for c in cert_numbers if str(c) not in _lots]

    # ★PSA に写真が無い個体を落とす (2026-08-28)。
    #   写真が無いと目視で現物と照合できず、必ず「該当なし」になって枠を1つ潰す。
    #   PSA 側の事情で取り直しても増えない (実測 1,308件中5件・2020年前後の古い cert)。
    #   代替画像が用意されている cert は落とさない。
    #   依頼書: hq/requests/2026-08-28_act_code_proposals_tcg.md 提案1
    _nophoto = no_psa_photo_certs(cert_numbers, _load_psa_cache())
    if _nophoto:
        print(f"  🚫 PSA に写真が無い個体を除外: {len(_nophoto)}件 → {sorted(_nophoto)[:6]}")
        print("     (照合できないので目視に出しても必ず『該当なし』になる。"
              "プログラムの不具合ではないので修正依頼にはしない)")
        record_cert_skips("no_psa_photo", list(_nophoto), detail=_nophoto)
        cert_numbers = [c for c in cert_numbers if str(c) not in _nophoto]

    # 目視済(NONE/NG=識別不能)cert を cooldown 期間スキップ (2026-06-23 再表示防止)
    # post_psa_review が NONE/NG 判定を skip 台帳に記録 → 一定期間 再出題しない。
    # catalog 宿題は依頼書で別途追跡(埋もれない)。cooldown 経過後は再浮上(catalog修正済なら出品可)。
    try:
        import datetime as _dt2
        from tcg_batch_select import load_review_skips, active_review_skips
        _skips = active_review_skips(load_review_skips(), _dt2.datetime.now())
        if _skips:
            _b = len(cert_numbers)
            cert_numbers = [c for c in cert_numbers if c not in _skips]
            if _b != len(cert_numbers):
                from tcg_batch_select import REVIEW_SKIP_COOLDOWN_DAYS as _CD
                print(f"  ⏭️ 目視済(NONE/NG, {_CD}日以内)を除外: {_b-len(cert_numbers)}件 "
                      f"(catalog宿題は依頼書で追跡。cooldown後に再浮上)")
    except Exception as _e2:
        print(f"  ⚠️ 目視済スキップ読込失敗(無視して継続): {type(_e2).__name__}: {_e2}")

    # ★2026-08-11: **枠を選ぶ前に** catalog で解決できない cert を落とす (Advisor 依頼)。
    #   従来は 10件に絞ってから GAP/対象外が落ちていたので、**枠を食ってから消えて**
    #   入稿が 2〜6件に張り付いていた。判定は psa_preflight.classify (出品と同一 resolver)。
    #   落とすのは GAP (catalog 未収録) と OUT-OF-SCOPE (参入しないゲーム) だけ。
    #   ★判定できないもの (PSA cache 無し / 例外) は **落とさない**。
    #     「読めなかった」を「対象外」に倒すと出品機会を静かに失う (fail-closed の向きが逆)。
    try:
        import sqlite3 as _sq3
        _pf_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "iMakHQ", "tools")
        if _pf_dir not in sys.path:
            sys.path.insert(0, _pf_dir)
        import psa_preflight as _pf
        _con = _sq3.connect(_pf.CATALOG_DB)
        _drop, _kept, _unknown, _cls = {}, [], 0, {}
        _vision_keep = []          # 文字では決まらないが写真なら決まる (番号なし DON!!)
        for _c in cert_numbers:
            _f = _pf.PSA_CERTS_DIR / f"{_c}.json"
            if not _f.exists():
                _kept.append(_c); _unknown += 1; continue      # cache 無し = 判定不能 → 残す
            try:
                _meta = json.loads(_f.read_text(encoding="utf-8"))
                _r = _pf.classify(str(_c), _meta, _con)
                _st = _r.get("status")
                _cls[_c] = _r
            except Exception:
                _kept.append(_c); _unknown += 1; continue      # 例外も残す
            if _st in ("GAP", "OUT-OF-SCOPE"):
                # ★番号なし DON!! は文字では決まらないが写真なら決まる → Vision まで残す
                #   (2026-08-28 提案3)。ここで落とすと Vision に一度も届かない。
                if keep_for_vision(_r, _meta):
                    _kept.append(_c)
                    _vision_keep.append(_c)
                    continue
                _drop.setdefault(_st, []).append(_c)
                # ★2026-08-26: **今日また落ちた**という観測をキューに積む。クローズ済でも
                #   pending に戻す (閉じたのに直っていない、を見えるようにする)。
                #   OUT-OF-SCOPE は「参入しない」と決めた分なので積まない。
                #   依頼書: hq/requests/2026-08-26_act_code_proposals_tcg.md 提案4 (付随)
                if _st == "GAP":
                    _fld, _lyr, _ft, _pre = gap_queue_target(_r)
                    _queue_finding(_r.get("category") or "tcg", f"cert{_c}", _fld,
                                   f"{_pre}: {_r.get('reason', 'GAP')}"[:120],
                                   layer=_lyr, finding_type=_ft,
                                   identity=f"{_r.get('brand', '')} #{_r.get('num', '')}"[:200],
                                   reopen_closed=True,
                                   # 閉じた時と **カタログの見え方が同じ**なら送り直さない
                                   # (同じ状態で聞き直しても答えは前回と同じ「不要」)
                                   catalog_state=f"{_st}|{_r.get('reason', '')}"[:200])
                continue
            # ★2026-08-11: **catalog に画像が無いカードは目視で照合できず必ず落ちる**。
            #   枠を食ってから消えるので先に除く (2026-08-10 実走: 10件中2件がこれで脱落)。
            #   画像の有無は catalog の事実なので、判定できた時だけ落とす (取れなければ残す)。
            _pid = _r.get("product_id") if isinstance(_r, dict) else None
            if _pid:
                try:
                    _row = _con.execute(
                        "SELECT images FROM products WHERE category=? AND product_id=?",
                        (_r.get("category"), _pid)).fetchone()
                    if _row is not None and len(json.loads(_row[0] or "[]")) == 0:
                        _drop.setdefault("NO-IMAGE", []).append(_c)
                        # ★画像が無いのは catalog の欠落。黙って落とすと **誰も足さない**ので
                        #   依頼キューに積む (次の監査で catalog へ集約発行される)。
                        _queue_finding(_r.get("category"), f"PSA10-{_c}", "images",
                                       "catalog に画像が無く目視できないので出品できない",
                                       identity=f"{_pid} | (画像なし) | {_r.get('category')}")
                        continue
                except Exception:
                    pass                       # 読めなければ落とさない
            _kept.append(_c)
        # ★2026-08-11: **live に同じカードが既にある cert** も枠の前で落とす。
        #   後段の重複くん excluder が CSV から物理除外するので、枠に入れても必ず消える
        #   (2026-08-10 実走: CSV 7件 → 重複除外 2件)。判定は dup_guard の live index
        #   (= eBay ActiveList と突合済) を使い、出品側と同じ canonical KEY で見る。
        try:
            sys.path.insert(0, _pf_dir)
            import dup_guard as _dg
            import sheet_io as _si
            _sheet_rows_for_dedupe = _si._product_ws().get_all_values()
            # ★2026-08-11: **古い cache を live の根拠にしない**。
            #   初版は _load_live_cache() を素で読み、24.5時間前の cache で判定していたため
            #   5件を1件も検出できなかった (後段の excluder が拾って枠が5つ無駄になった)。
            #   8/09 に excluder で直したのと同じ穴。取り直す担当をここにも置く。
            _titles, _skus, _fresh_ok = _dg.ensure_fresh_live_cache()
            _titles = _titles or {}
            _active = set(_titles.keys()) if _fresh_ok else set()
            if _active:
                _idx, _ = _dg.live_card_index(_sheet_rows_for_dedupe, _titles, _active)
                _dup = []
                for _c in list(_kept):
                    _r2 = _cls.get(_c)
                    if not _r2 or not _r2.get("product_id"):
                        continue                       # KEY を作れない = 判定不能 → 残す
                    _k = _dg.group_key(f"{_r2.get('category')}:{_r2['product_id']}")
                    if _k in _idx:
                        _dup.append(_c); _kept.remove(_c)
                if _dup:
                    _drop["LIVE-DUP"] = _dup
                    # ★2026-08-18: 落とす前に **KEY をシートに書く**。
                    #   KEY を書く処理は「その日のCSVに載った行」しか見ないので、枠の前で
                    #   落とすと KEY が永久に空のまま残る。KEY が空だと補URL追記
                    #   (hoju_url_from_dupes) が拾えず、**生きた仕入元を1本捨てる**。
                    #   = 早く落とすほど供給が痩せる。夜間の PSA 先貯めで早期除外が
                    #   増えるので、ここを塞いでおかないと逆効果になる。
                    #   実測 2026-08-18: 前段で落ちた cert153574704 の行は KEY 空のまま、
                    #   後段で落ちた5件は KEY が入り補URLに回っていた (同じ重複なのに差が出た)。
                    try:
                        _krows, _kkeys = _keys_for_dropped_dupes(
                            _sheet_rows_for_dedupe, _dup, _cls)
                        if _kkeys:
                            _si.write_keys(_krows, _kkeys)
                            print(f"  🔗 補URL に回すため KEY を先に書込: {len(_kkeys)}件")
                    except Exception as _ke:                   # noqa: BLE001
                        print(f"  ⚠️ KEY 先行書込 skip: {type(_ke).__name__}: {_ke}")
            else:
                print("  ℹ️ live cache を新鮮化できず → 重複の前置きは skip "
                      "(古い cache を live の根拠にしない = 誤除外も見逃しも作らない)")
        except Exception as _de:
            print(f"  ⚠️ 重複の前置き skip: {type(_de).__name__}: {_de}")
        _con.close()
        if _drop:
            for _st, _cs in _drop.items():
                _label = {"GAP": "catalog に行が無い(未収録の疑い)",
                          "OUT-OF-SCOPE": "参入しないゲーム",
                          "NO-IMAGE": "catalogに画像が無く目視不能",
                          "LIVE-DUP": "同じカードが既に出品中(後段で必ず除外される)"}.get(_st, _st)
                print(f"  ⏭️ 枠を選ぶ前に除外 [{_st}={_label}]: {len(_cs)}件 → {_cs[:6]}")
            print(f"     (従来は10件に絞った後で落ちていた分。GAP は missing_models 経由で catalog へ)")
            cert_numbers = _kept
            cost_map = {c: cost_map[c] for c in cert_numbers if c in cost_map}
        if _vision_keep:
            print(f"  🔍 番号なし DON!! は **落とさず Vision に回す**: {len(_vision_keep)}件 "
                  f"→ {_vision_keep[:6]}")
            print("     (PSA が番号もキャラ名も出さないので文字では決まらない。写真から色/キャラを読む)")
        if _unknown:
            print(f"  ℹ️ preflight 判定不能 {_unknown}件は **落とさず**残置 (cache無/例外)")
    except Exception as _pfe:
        print(f"  ⚠️ preflight 前置き skip (従来動作で継続): {type(_pfe).__name__}: {_pfe}")

    # 一回 15 件まで固定 (Cloudflare bot 検出回避、2026-05-06 / 2026-08-11 に 10→15)
    # ★上げたのは **上の preflight で無駄玉を先に落とした後**だから (先に上げると無駄玉が15件になる)
    # 残りは時間を置いて次回再走で順次処理
    # ★2026-08-18: 🤖自動 だけ 20 件にする (ユーザー指示)。値は **外から注入** し、
    #   コードに「自動なら〜」の分岐を作らない。手動 (PSA TCG) は既定の 15 のまま。
    #   上げすぎると Cloudflare の bot 検出に触れるので、既定値は動かさない。
    try:
        PSA_BATCH_LIMIT = max(1, int(os.environ.get("PSA_BATCH_LIMIT") or 15))
    except ValueError:
        PSA_BATCH_LIMIT = 15
    if len(cert_numbers) > PSA_BATCH_LIMIT:
        # franchise 均等サンプリング (2026-06-23 ユーザー要望: Pokemon/One Piece/Dragon Ball 均等)
        # 在庫は Pokemon 大半 → 従来の全体 shuffle だと Pokemon ばかり選ばれ OP/DB が滞留。
        # C列タイトルで franchise 推定 → round-robin で均等に。PSA_NO_SHUFFLE=1 で従来の上から順。
        total = len(cert_numbers)
        if os.environ.get("PSA_NO_SHUFFLE") == "1":
            cert_numbers = cert_numbers[:PSA_BATCH_LIMIT]
        else:
            import collections as _collections
            from tcg_batch_select import balanced_sample, classify_franchise
            cert_numbers = balanced_sample(cert_numbers, mercari_title_map, PSA_BATCH_LIMIT)
            _dist = _collections.Counter(classify_franchise(mercari_title_map.get(c, "")) for c in cert_numbers)
            print(f"⚠️ {total}件中 franchise均等 {PSA_BATCH_LIMIT} 件を処理 "
                  f"(内訳 {dict(_dist)} / 残 {total-PSA_BATCH_LIMIT} 件は次回再走)")
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
        # Franchise / Autographed / Vintage / Material / Customized は 2026-08-22 契約で廃止
        "C:Country of Origin", "C:Card Size",
        "C:Attribute/MTG:Color", "C:Illustrator", "C:Cost", "C:Attack/Power", "C:Defense/Toughness",
        # C:HP / C:Stage は新コアが catalog hp_ebay/stage_ebay から充填 (2026-06-15 最大活用)。
        # 旧コアは空 (build_row が "" を出す)。catalog *_ebay 充填まで空欄 (回帰なし)。
        "C:HP", "C:Stage",
        # C:Speciality = ポケモンの EX/V/GX/VMAX 等 (catalog speciality_ebay)。
        # 旧コアは空、新コアが充填 (2026-08-23 契約 emit=true)。
        "C:Speciality",
        "C:Card Condition", "C:Grade", "C:Professional Grader", "C:Graded", "StoreCategoryID",
    ]

    rows = [headers]
    errors = []
    catalog_misses = []  # iMakCatalog 未登録 (要 Catalog Claude 拡充依頼) — gshock_to_csv と同パターン
    # 2026-08-09 canonical product_id sidecar: build_row が catalog 由来の card_id をここに集める。
    # CSV には列を足さず、生成末尾で `<basename>.canonical.json` として並置する。
    # 詳細: 2026-08-09_rarity_exclusion_needs_canonical_product_id_response.md
    pid_by_cert = {}
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
            try:
                d = get_psa_data(driver, cert)
            except Exception as _e:
                if not is_dead_session(_e):
                    print(f" 失敗 ({type(_e).__name__})")
                    _prescraped[cert] = None
                    continue
                # ★ブラウザが死んだ → 作り直して この cert からやり直す。
                #   ここで作り直さないと、残り全部が同じエラーで空振りする (8/26 に13件)。
                print(" ⟳ Chrome が落ちたので起動し直します...", flush=True)
                try:
                    driver = restart_psa_driver(driver)
                    d = get_psa_data(driver, cert)
                except Exception as _e2:
                    print(f" ✗ 起動し直しても取れません ({type(_e2).__name__}) → 以降は中止")
                    _prescraped[cert] = None
                    break
            _prescraped[cert] = d
            print(" ✓" if d else " 失敗")
        # ★2026-09-01: **scrape が済んだ直後に、もう一度 重複を見る**。
        #   枠を選ぶ前の LIVE-DUP は「まだ一度も scrape していない cert」を判定できない
        #   (PSA の per-cert json が無い = 判定不能で残置)。その分は目視にも生成にも回った上で、
        #   最後に重複くんが物理除外していた。
        #   実測 2026-09-01: 18件生成 → 6件が live 重複で除外 (目視19件のうち6件も無駄)。
        #   **判定の基準は後段の除外と同じ**なので、ここで落としても出品は1件も減らない。
        #   減るのは 目視の手間 と 生成の課金だけ。
        try:
            _tools0 = r"C:/dev/iMak/iMakHQ/tools"
            if _tools0 not in sys.path:
                sys.path.insert(0, _tools0)
            import dup_guard as _dg2
            import psa_preflight as _pf2
            import sheet_io as _si2
            import sqlite3 as _sq32
            _t2, _s2, _fresh2 = _dg2.ensure_fresh_live_cache()
            _t2 = _t2 or {}
            if _fresh2 and _t2:
                _rows2 = _si2._product_ws().get_all_values()
                _idx2, _ = _dg2.live_card_index(_rows2, _t2, set(_t2.keys()))
                _con2 = _sq32.connect(_pf2.CATALOG_DB)
                _dup2, _cls2 = [], {}
                for _c2 in list(cert_numbers):
                    if not _prescraped.get(_c2):
                        continue
                    _f2 = _pf2.PSA_CERTS_DIR / (str(_c2) + '.json')
                    if not _f2.exists():
                        continue
                    try:
                        _r3 = _pf2.classify(str(_c2), json.loads(_f2.read_text(encoding='utf-8')), _con2)
                    except Exception:
                        continue
                    _pid2 = _r3.get('product_id') if isinstance(_r3, dict) else None
                    if not _pid2:
                        continue
                    _cls2[_c2] = _r3
                    if _dg2.group_key(str(_r3.get('category')) + ':' + str(_pid2)) in _idx2:
                        _dup2.append(_c2)
                _con2.close()
                if _dup2:
                    # 落とす前に KEY をシートへ (補URL に回すため。枠前の LIVE-DUP と同じ理由)
                    try:
                        _kr2, _kk2 = _keys_for_dropped_dupes(_rows2, _dup2, _cls2)
                        if _kk2:
                            _si2.write_keys(_kr2, _kk2)
                            print(f'  🔗 補URL に回すため KEY を先に書込: {len(_kk2)}件')
                    except Exception as _ke2:
                        print(f'  ⚠️ KEY 先行書込 skip: {type(_ke2).__name__}: {_ke2}')
                    cert_numbers = [_c for _c in cert_numbers if _c not in set(_dup2)]
                    print(f'  ⏭️ scrape後に除外 [LIVE-DUP=同じカードが既に出品中]: {len(_dup2)}件 '
                          f'→ {_dup2}')
                    print('     (目視にも生成にも回さない。基準は後段の重複除外と同じなので出品は減らない)')
        except Exception as _de2:
            print(f'  ⚠️ scrape後の重複チェック skip: {type(_de2).__name__}: {_de2}')

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
            row = build_row(cert, DEFAULT_PRICE, data, description, driver=driver, catalog_misses=catalog_misses, pid_by_cert=pid_by_cert)
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
                    _forced = _confirmed_pids.get(cert, "") if _verify_mode else ""
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
                    # promo系だが配布元名 未確定 → 黙って generic で出さず build時にもフラグ
                    # (レビューを通らない経路=verify無効/timeout でも「気づかない」を消す。出品はブロックしない)
                    if _chk.get("_promo_needs_review"):
                        print(f"    🏷️ 注意 #{cert}: プロモ系だが配布元名 未確定(promo override 無)"
                              f" → generic タイトルで出品。PSA Review の promo欄で確定すると次回反映")
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

    # ===== StartPrice を決める =====
    # 価格は cost-plus (pricing_engine) が SSOT。相場は 2026-08-13 に停止 (global.yaml
    # market_lookup.enabled=false)。停止理由と実測は yaml のコメント参照。
    try:
        from config_loader import is_market_lookup_enabled as _mkt_on
        _market_lookup = _mkt_on()
    except Exception:
        _market_lookup = False

    ebay_keys = load_ebay_keys() if _market_lookup else {}
    ebay_token = None
    if not _market_lookup:
        print("\n💲 価格: cost-plus のみ (相場取得は停止中 — global.yaml market_lookup)")
    elif ebay_keys.get("AppID") and ebay_keys.get("AppSecret"):
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

    def _cost_plus_price(cost_jpy):
        """相場を見ずに価格を出す = 相場ありの時と**同じ式** (cost-plus / pricing_engine)。

        相場ありの経路 (下の market 分岐) も price は target_usd で決めており、
        median は表示にしか使っていない。ここはその式だけを取り出したもの。
        仕入値が無い時だけ $100 (旧「競合0件 & 仕入値なし」と同値)。
        """
        if cost_jpy is None:
            return 100.00
        from pricing_engine import compute_listing_price as _pe
        p = round(_pe(cost_jpy, 0, "TCG(PSA10)")["target_usd"], 2)
        return int(p) + 0.98 if p > 10 else p

    if not _market_lookup:
        # 相場停止時: cost-plus だけで値付け (eBay API を1回も叩かない)
        for _cert, _data in card_info:
            if _data is None:
                continue
            _idx = next((ri for ri in range(1, len(rows))
                         if str(rows[ri][cert_col_idx]) == str(_cert)), None)
            if _idx is None:
                continue
            _price = _cost_plus_price(cost_map.get(_cert))
            rows[_idx][price_col_idx] = _price
            rows[_idx][shipping_col_idx] = get_shipping_policy(_price)
            print(f"    #{_cert}: ${_price}")

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
                # 競合0件: V8/V9 SSOT 価格 (pricing_engine) と $100 の高い方で先行出品
                # (2026-07-23: 旧レガシー式 [tier(100)+定数比率のインライン計算] は SSOT と
                #  数ドルずれる [実害: DON-EB04-002 $186.98 vs V9 $190.98] ため廃止。
                #  通常経路 (line 2811 付近) と同じエンジンに統一)
                if cost_jpy is not None:
                    from pricing_engine import compute_listing_price as _pe_compute
                    _pr = _pe_compute(cost_jpy, 0, "TCG(PSA10)")
                    min_price = round(_pr["target_usd"], 2)
                    min_price = int(min_price) + 0.98 if min_price > 10 else min_price
                    if min_price < 100:
                        min_price = 100.98
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

    # 2026-08-09 canonical product_id sidecar (CSV に列を足さず並置 JSON)。
    # 目的: rarity 除外や後段監査で「印刷番号 (101/184)」でなく canonical PID (S8b-101) で
    # 判定できるようにする。個別 prefix 追加の後追いを止めて発生源を直す
    # (2026-08-09_rarity_exclusion_needs_canonical_product_id_response.md)。
    try:
        from canonical_pid_sidecar import write_sidecar as _write_pid_sidecar
        _certs_in_csv = {str(r[cert_col_idx]) for r in rows[1:]}
        # ★2026-08-31 提案2: recorded (build_row lookup) が空でも category を落とさないため、
        #   CSV 行が持つ確定値 (PSA Brand → franchise) から category を渡す。
        _category_by_cert = {}
        for _c, _d in card_info:
            _brand = (_d or {}).get("Brand", "") if _d else ""
            if not _brand:
                continue
            _fr = detect_game_info(_brand)[2]
            _cat = FRANCHISE_TO_CATALOG_CATEGORY.get(_fr)
            if _cat:
                _category_by_cert[str(_c)] = _cat
        _sidecar_path = _write_pid_sidecar(
            output_file,
            pid_by_cert,
            certs_in_csv=_certs_in_csv,
            confirmed_pids=(_confirmed_pids if _verify_mode else None),
            category_by_cert=_category_by_cert,
        )
        print(f"canonical PID sidecar: {_sidecar_path} ({len(pid_by_cert)} 件 tracked)")
    except Exception as _e:
        print(f"⚠️ canonical PID sidecar 失敗 (非致命): {type(_e).__name__}: {_e}")

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
    # ★2026-08-13: 画面には**要点だけ**出す (brief)。走行の最後に同じ監査が本番で
    #   もう一度走るので、ここで全文を出すと同じ内容が二重に画面を埋めていた。
    #   呼び出し自体は残す = 生成器を単独で回した時にも監査が効く (fail-closed)。
    try:
        from listing_common import run_self_audit
        run_self_audit(output_file, brief=True)
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

    # ★2026-08-31: missing_models へ書く直前に1回ゲートを通す。
    #   出品できた(=CSVに載った) cert / 名前で catalog に行が見つかる cert は
    #   「未収録」ではなく「引き方(②)」の課題 → program_fix キューへ回す。
    #   出典: hq/requests/2026-08-31_act_code_proposals_tcg_response.md 提案1
    if catalog_misses:
        _csv_certs = {str(r[cert_col_idx]) for r in rows[1:] if len(r) > cert_col_idx}
        catalog_misses, _program_misses = _gate_catalog_misses_io(catalog_misses, _csv_certs)
        if _program_misses:
            print(f"  📎 名前候補あり (未収録と断定せず program_fix キューへ): {len(_program_misses)}件")
            for category, model, subject, cert, hits in _program_misses:
                _queue_finding(category, f"cert{cert}" if cert else model, "program_fix",
                               f"引けないが未収録とは確認できていない(名前候補あり): "
                               f"{model} subject={subject!r} candidates={hits[:3]}"[:200],
                               layer="code", finding_type="program_fix", identity=subject[:200])

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

    # ★2026-07-31: 出品くん(control_panel)からの起動は stdin が無く、ここで EOFError → returncode=1。
    #   直前の「Catalog 未登録カード一覧」が表示されないまま落ちていた (毎走行で発生)。
    #   対話起動 (人が直接叩いた時) だけ待つ。
    if sys.stdin and sys.stdin.isatty():
        try:
            input("\nEnterで終了...")
        except EOFError:
            pass

if __name__ == "__main__":
    main()
