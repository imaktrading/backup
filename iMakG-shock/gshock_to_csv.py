#!/usr/bin/env python3
# iMak Trading Japan - CASIO公式URL → eBay CSV 自動生成スクリプト
# 必要: pip install selenium undetected-chromedriver requests

import csv
import re
import time
import requests
from datetime import datetime, timedelta

def get_schedule_time():
    future = datetime.utcnow() + timedelta(weeks=SCHEDULE_WEEKS)
    return future.strftime("%Y-%m-%d %H:%M:%S")
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

# 共通リスティング処理ライブラリ (2026-04-23 統合)
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "iMakeBayAPI"))
from listing_common import (
    normalize_title, audit_csv_row, CONDITION_MASTER,
    get_default_condition_description,
    extract_sku_from_url as _extract_sku_from_url,
)
# 動的価格決定 (2026-05-05 追加、Montbell パターン)
from profit_params import compute_min_price_usd
try:
    from pricing_engine import compute_listing_price as _compute_listing_price
except Exception:
    _compute_listing_price = None
try:
    from check_csv_core import fetch_ebay_market_median as _fetch_ebay_median
except Exception:
    _fetch_ebay_median = None

# Phase 3-B (2026-04-29): iMakCatalog adapter — catalog hit 時に Selenium scrape を skip.
# 失敗時 (iMakCatalog 未配置 / DB 未投入) は静かに None フォールバックして既存挙動を維持する.
try:
    _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                       "..", "iMakCatalog", "integrations"))
    from gshock_lookup import lookup_gshock as _catalog_lookup  # type: ignore
except Exception:
    _catalog_lookup = None

URLS_FILE = "gshock_urls.txt"
DESCRIPTION_FILE = "GSHOCK.txt"
DEFAULT_PRICE = 100.00     # F 列空 + URL ファイル駆動時の fallback
PROFIT_CATEGORY = "G-SHOCK"  # profit_params.categories キー
PRICE_FLOOR_USD = 50         # 最低価格保証 (Montbell と同じ運用)
EBAY_CATEGORY_GSHOCK = "31387"  # eBay Wristwatches カテゴリ
COST_JPY_FALLBACK = 5000     # 価格情報全空時の cost 推定値 (Montbell と同値)

# 統合 LOW スプシ (抽出くん管理、R='G-shock' の行を取込)
GSHOCK_SHEET_ID = "1jF9vggbfUCddjneROMO2GGN-jTAPRbq6Qe2cbgr37B0"
GSHOCK_GID = 851100680
GSHEET_CREDS = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "double-hold-421922-7c0d38d3f73d.json")
RETURN_POLICY = "customer1"
PAYMENT_POLICY = "SALE"
LOCATION = "Japan"
CATEGORY = 31387
SCHEDULE_WEEKS = 2
PIC_URL = "https://raw.githubusercontent.com/imaktrading/imaktrading.github.io/main/999.png"

# DDP送料テーブル（TCGと同じ）
SHIPPING_POLICIES = [
    (39, "<39"), (60, "40-60"), (100, "60-100"), (200, "100-200"),
    (300, "200-300"), (400, "300-400"), (500, "400-500"),
    (600, "500-600"), (800, "600-800"), (1000, "800-1000"),
]

def get_shipping_policy(price):
    for threshold, policy in SHIPPING_POLICIES:
        if price <= threshold:
            return policy
    return "800-1000"

STORE_CATEGORIES = {
    # DW-6900系（GM-6900含む）
    "DW6900": 41925816010, "DW9600": 41925816010,
    "GM6900": 41925816010, "GMD6900": 41925816010,
    # DW-5600系（GM-5600・GW-5000・GW-M5610含む）
    "DW5600": 41925784010, "GWB5600": 41925784010, "GWS5600": 41925784010,
    "GWM5610": 41925784010, "GWX5600": 41925784010, "GWX5700": 41925784010,
    "GM5600": 41925784010, "GMS5600": 41925784010, "GMD5600": 41925784010,
    "GW5000": 41925784010, "GW5600": 41925784010, "G5600": 41925784010,
    "DWE5600": 41925784010, "DWB5600": 41925784010,
    "GMW": 41925819010,  # FULL METAL → Master of G
    # GA-2100系
    "GA2100": 41925817010, "GA2110": 41925817010,
    # G-SQUAD
    "GBD": 41925821010, "GBA": 41925821010, "GBX": 41925821010,
    # G-STEEL
    "GST": 41925820010,
    # Master of G
    "GWG": 41925819010, "GPR": 41925819010, "GWN": 41925819010,
}

WATER_RESISTANCE_MAP = {"20気圧": "200 m (20 ATM)", "10気圧": "100 m (10 ATM)", "5気圧": "50 m (5 ATM)"}
BAND_MATERIAL_MAP = {"カーボン": "Resin", "樹脂": "Resin", "ステンレス": "Stainless Steel", "ナイロン": "Nylon", "レザー": "Leather", "布": "Canvas", "チタン": "Titanium", "シリコン": "Silicone", "ラバー": "Rubber", "ゴム": "Rubber"}
CASE_MATERIAL_MAP = {"チタン": "Titanium", "ステンレス": "Stainless Steel", "カーボン": "Carbon Fiber", "樹脂": "Resin"}
CRYSTAL_MAP = {"サファイアガラス": "Sapphire Crystal", "無機ガラス": "Mineral Crystal", "有機ガラス": "Acrylic", "強化ガラス": "Hardened Mineral Crystal"}
# eBay公式フィルタ正規値に揃える（2026-04-23 G-Shock検索フィルタから取得）
FEATURES_MAP = {
    "タフソーラー": "Solar Powered",
    "マルチバンド6": "Atomic/Radio Controlled",
    "Multiband": "Atomic/Radio Controlled",
    "電波": "Atomic/Radio Controlled",
    "Bluetooth": "Bluetooth",
    "GPS": "GPS",
    "ワールドタイム": "World Time",
    "アラーム": "Alarm",
    "タイマー": "Timer",
    "ストップウオッチ": "Chronograph",  # eBayは Chronograph
    "クロノグラフ": "Chronograph",
    "耐衝撃": "Shock-Resistant",  # ハイフン付き
    "耐磁": "Magnetic-Resistant",  # ハイフン付き
    "心拍": "Heart Rate Monitor",
    "高度計": "Altimeter",
    "高度測定": "Altimeter",
    "温度": "Thermometer",
    "ムーン": "Moon Phase",
    "カウントダウン": "Countdown",
    # 以下は eBay G-Shock フィルタリストに無いため除外（旧 Carbon Core Guard / Activity Tracker / Compass / Barometer / Tide Graph / Sunrise-Sunset / Vibration Alert / Flash Alert は記入しても検索ヒットせず空欄同等）
}
FEATURES_PRIORITY = [
    "GPS", "Bluetooth", "Solar Powered", "Atomic/Radio Controlled",
    "Shock-Resistant", "Water-Resistant", "Moon Phase", "World Time",
    "Chronograph", "Alarm", "Timer", "Backlight",
    "Date Indicator", "Day/Date", "Day Indicator",
    "12-Hour Dial", "24-Hour Dial", "LED Display", "Multifunction",
    "Magnetic-Resistant", "Heart Rate Monitor",
    "Altimeter", "Thermometer", "Mineral Crystal",
]
# 全G-Shock共通機能（必ず付与）
GSHOCK_COMMON_FEATURES = ["Shock-Resistant", "Water-Resistant", "Backlight", "Alarm"]
# デジタル機能（Display=Digital or Analog & Digital なら付与）
DIGITAL_COMMON_FEATURES = [
    "12-Hour Dial", "24-Hour Dial", "Date Indicator", "Day/Date",
    "Day Indicator", "LED Display", "Multifunction", "Timer",
    "World Time", "Chronograph",
]
MOVEMENT_MAP = {
    # eBay Movement フィルタは Mechanical Automatic / Mechanical Manual / Quartz の3択のみ
    # G-Shockは全部Quartz（Solar/Radio Controlled はFeatures側に記録）
    "タフソーラー": "Quartz",
    "マルチバンド6": "Quartz",
    "電波": "Quartz",
    "マルチバンド": "Quartz",
}

# Style: シリーズ別判定（eBay Watches Style 公式値: Casual/Classic/Diver/Dress/Formal/Luxury/Military/Pilot/Aviator/Skeleton/Sport）
def get_style_by_model(model_base):
    """モデル番号からeBay Style値を判定"""
    if not model_base:
        return "Sport"
    key = model_base.upper().replace("-", "")
    # Diver系（FROGMAN / 200m+耐水）
    if key.startswith("GWF") or key.startswith("GF8250"):
        return "Diver"
    # Military系（MUDMASTER/MUDMAN/RANGEMAN）
    if any(key.startswith(p) for p in ["GWG", "GG1000", "GG1035", "G9300", "GW9300", "GW9400", "GPR"]):
        return "Military"
    # Luxury系（MR-G）
    if key.startswith("MRG"):
        return "Luxury"
    # 残りは全部Sport
    return "Sport"

# eBay G-SHOCK Model フィルタ正規値マッピング（最重要）
# eBay公式フィルタは "G-SHOCK 5600" / "G-SHOCK GA-2100" / "G-SHOCK MUDMASTER" 等のシリーズ名
def get_ebay_model_filter(model_base):
    """モデル番号をeBayの Model フィルタ正規値（シリーズ名）にマッピング"""
    if not model_base:
        return ""
    key = model_base.upper().replace("-", "")

    # マスターオブG / 特殊シリーズ（最優先）
    series_map = [
        ("GWG", "G-SHOCK MUDMASTER"),
        ("GG1000", "G-SHOCK MUDMASTER"),
        ("GG1035", "G-SHOCK MUDMASTER"),
        ("G9300", "G-SHOCK MUDMAN"),
        ("GW9300", "G-SHOCK MUDMAN"),
        ("GWF", "G-SHOCK FROGMAN"),
        ("GF8250", "G-SHOCK FROGMAN"),
        ("GWN", "G-SHOCK GULFMASTER"),
        ("GN1000", "G-SHOCK GULFMASTER"),
        ("GW9400", "G-SHOCK RANGEMAN"),
        ("GPR", "G-SHOCK RANGEMAN"),
        ("GWA1100", "G-SHOCK GRAVITYMASTER"),
        ("GRB100", "G-SHOCK GRAVITYMASTER"),
        ("MRG", "G-SHOCK MR-G"),
        ("MTG", "G-SHOCK MT-G"),
        ("GST", "G-SHOCK G-STEEL"),
        ("GBX", "G-SHOCK G-LIDE"),
        ("GLX", "G-SHOCK G-LIDE"),
        ("BABYG", "Casio Baby-G"),
        ("BGA", "Casio Baby-G"),
        ("BGD", "Casio Baby-G"),
    ]
    for prefix, val in series_map:
        if key.startswith(prefix):
            return val

    # GA/GD/GBD系（プレフィックス + 数字判定）
    ga_gd_map = [
        ("GA2100", "G-SHOCK GA-2100"),
        ("GA2110", "G-SHOCK GA-2100"),
        ("GA2000", "G-SHOCK GA-2000"),
        ("GA100", "G-SHOCK GA-100"),
        ("GA110", "G-SHOCK GA-100"),
        ("GA120", "G-SHOCK GA-120"),
        ("GA140", "G-SHOCK GA-140"),
        ("GA150", "G-SHOCK GA-150"),
        ("GA200", "G-SHOCK GA-200"),
        ("GA300", "G-SHOCK GA-300"),
        ("GA400", "G-SHOCK GA-400"),
        ("GA700", "G-SHOCK GA-700"),
        ("GA710B", "G-SHOCK GA-710B"),
        ("GD100", "G-SHOCK GD-100"),
        ("GD110", "G-SHOCK GD-110"),
        ("GD120", "G-SHOCK GD-120"),
        ("GD400", "G-SHOCK GD-400"),
    ]
    for prefix, val in ga_gd_map:
        if key.startswith(prefix):
            return val

    # 5600系（Square。GMW-B5000=Full Metal Squareも含む）
    if "GMW" in key or any(p in key for p in ["5600", "5610", "5000"]):
        if "5700" not in key:
            return "G-SHOCK 5600"

    # 5700/5900/6900/7900/8900/9000/9052/9500
    digit_priority = ["5700", "5900", "6900", "7900", "8900", "9000", "9052", "9500"]
    for d in digit_priority:
        if d in key:
            return f"G-SHOCK {d}"

    return ""

# モデル番号末尾カラーコード → Band Color
BAND_COLOR_MAP = {
    "1": "Black", "1A": "Black", "1B": "Black", "1C": "Black", "1D": "Black",
    "2": "Blue", "2A": "Blue", "2B": "Blue",
    "3": "Green", "3A": "Green",
    "4": "Red", "4A": "Red", "4B": "Red",
    "5": "White", "5A": "White",
    "6": "Gold", "6A": "Gold",
    "7": "White", "7A": "White", "7B": "White",
    "8": "Orange", "8A": "Orange",
    "9": "Yellow", "9A": "Yellow",
}

# タフソーラー搭載シリーズ（モデル番号プレフィックスで判定）
# DW系はタフソーラー非搭載が多いので除外
TOUGH_SOLAR_PREFIXES = [
    "GW", "GBX", "GBD", "GBA", "GST", "GMW", "GWG", "GPR", "GWN",
    "GAS", "GAE", "GAB", "GAK",  # タフソーラーGA系のみ
]

# シリーズ別デフォルトWeight（g）
SERIES_WEIGHT = {
    "GWX5600": "56", "GWX5700": "56",
    "DW5600": "49", "GWB5600": "67", "GWS5600": "58", "GWM5610": "49",
    "DW6900": "58", "DW9600": "58",
    "GW6900": "63", "GM6900": "96",
    "GBX100": "66", "GBD200": "53", "GBD100": "46",
    "GA2100": "51", "GA100": "56", "GA700": "63",
    "GST": "81",
    "GMW": "159",
    "GM5600": "67", "GMS5600": "67",
    "GW5000": "67", "GW5600": "67",
    "GX56": "87", "GXW56": "87",
    "DW9052": "55",
}

# モデル別上書き設定（Claudeが毎回手動補完していた内容を全てここに集約）
# キー：モデル番号（JF/JR含む・なし両方登録）
MODEL_OVERRIDES = {
    # GBX-100 G-LIDE
    "GBX-100-1":   {"year": "2020", "weight": "66 g", "band_material": "Resin"},
    "GBX-100-1JF": {"year": "2020", "weight": "66 g", "band_material": "Resin"},
    # GWX-5600
    "GWX-5600C-4":   {"year": "2013", "weight": "56 g"},
    "GWX-5600C-4JF": {"year": "2013", "weight": "56 g"},
    # GWX-5700
    "GWX-5700CS-1":   {"year": "2018", "weight": "56 g"},
    "GWX-5700CS-1JF": {"year": "2018", "weight": "56 g"},
    # DW-6900JV（Joshua Vides）
    "DW-6900JV-1":   {"year": "2026"},
    "DW-6900JV-1JR": {"year": "2026"},
    # G-5600SFJ（Surfrider Foundation）
    "G-5600SFJ-9":   {"year": "2025", "weight": "51 g"},
    "G-5600SFJ-9JR": {"year": "2025", "weight": "51 g"},
    # GM-6900U
    "GM-6900U-1":   {"year": "2024"},
    "GM-6900U-1JF": {"year": "2024"},
    # GM-5600YRA（Fine Metallic Series）
    "GM-5600YRA-8":   {"year": "2026", "weight": "67 g", "band_material": "Silicone"},
    "GM-5600YRA-8JF": {"year": "2026", "weight": "67 g", "band_material": "Silicone"},
    # GM-5600BM
    "GM-5600BM-1":   {"year": "2023", "weight": "67 g"},
    "GM-5600BM-1JF": {"year": "2023", "weight": "67 g"},
    # GM-5600M
    "GM-5600M-1":   {"year": "2022", "weight": "67 g"},
    "GM-5600M-1JF": {"year": "2022", "weight": "67 g"},
    # GMW-B5000BT（Full Metal Bluetooth）
    "GMW-B5000BT-1":   {"year": "2023", "weight": "167 g", "band_material": "Stainless Steel", "band_strap": "Bracelet"},
    "GMW-B5000BT-1JF": {"year": "2023", "weight": "167 g", "band_material": "Stainless Steel", "band_strap": "Bracelet"},
    # GW-5000HS
    "GW-5000HS-1":   {"year": "2024", "weight": "67 g"},
    "GW-5000HS-1JF": {"year": "2024", "weight": "67 g"},
    "GW-5000HS-7":   {"year": "2024", "weight": "67 g"},
    "GW-5000HS-7JF": {"year": "2024", "weight": "67 g"},
    # GW-5000U
    "GW-5000U-1":   {"year": "2022", "weight": "74 g"},
    "GW-5000U-1JF": {"year": "2022", "weight": "74 g"},
    # GW-6900U
    "GW-6900U-1":   {"year": "2024", "weight": "74 g"},
    "GW-6900U-1JF": {"year": "2024", "weight": "74 g"},
}

# GMWシリーズはメタルバンド（Bracelet）
BRACELET_PREFIXES = ["GMW", "MRGG", "MTG"]

def get_band_strap(model):
    """Band/Strapを自動判定"""
    key = model.upper().replace("-", "")
    if any(key.startswith(p.replace("-", "")) for p in BRACELET_PREFIXES):
        return "Bracelet"
    return "Two-Piece Strap"

def get_band_material_by_model(model):
    """モデル番号からBand Materialを自動判定"""
    key = model.upper().replace("-", "")
    if any(key.startswith(p.replace("-", "")) for p in BRACELET_PREFIXES):
        return "Stainless Steel"
    return ""  # ブランクの場合はCASIOページから取得した値を使用

def get_band_color(model):
    """モデル番号末尾からBand Colorを判定"""
    # 末尾のカラーコードを抽出（例：GWX-5600C-4JF → 4、GBX-100-1 → 1）
    model_no_jf = re.sub(r'JF$', '', model)
    m = re.search(r'-(\w+)$', model_no_jf)
    if m:
        code = m.group(1).upper()
        for key, color in BAND_COLOR_MAP.items():
            if code == key.upper():
                return color
        # 数字部分だけで判定
        digits = re.sub(r'[A-Z]', '', code)
        if digits in BAND_COLOR_MAP:
            return BAND_COLOR_MAP[digits]
    return "Black"

def is_tough_solar(model):
    """タフソーラー搭載モデルか判定"""
    key = model.upper().replace("-", "")
    return any(key.startswith(p.upper().replace("-", "")) for p in TOUGH_SOLAR_PREFIXES)

def get_default_weight(model):
    """シリーズ別デフォルトWeightを取得"""
    key = model.upper().replace("-", "")
    for prefix, weight in SERIES_WEIGHT.items():
        if key.startswith(prefix.upper().replace("-", "")):
            return f"{weight} g"
    return ""

def trim_features(features_str, max_len=65):
    parts = [f.strip() for f in features_str.split(",")]
    sorted_parts = sorted(parts, key=lambda x: FEATURES_PRIORITY.index(x) if x in FEATURES_PRIORITY else 99)
    result = []
    for p in sorted_parts:
        candidate = ", ".join(result + [p])
        if len(candidate) <= max_len:
            result.append(p)
    return ", ".join(result)
SQUARE_MODELS = [
    "DW5600", "GWB5600", "GWS5600", "GWM5610",  # 5600系はSquare
    "GM5600", "GMS5600", "GW5000", "GWS5000",    # GM-5600・GW-5000もSquare
    "DWE5600", "DWB5600", "G5600",               # 派生モデル
    # DW6900はRound → リストから除外
]

def extract_model_from_url(url):
    m = re.search(r'product\.([A-Z0-9\-]+)', url)
    return m.group(1) if m else None


def build_casio_url(model):
    """型番から CASIO 公式 URL を生成 (scrape_casio fallback 用).

    catalog MISS 時のみ scrape_casio が呼ばれるが、その入力に CASIO URL が必要.
    スプシ駆動 (Amazon/メルカリ URL) の場合に本関数で CASIO URL を構築する.
    """
    return f"https://www.casio.com/jp/watches/gshock/product.{model}/"


def extract_model_from_text(text):
    """テキスト (タイトル/説明文) から CASIO 型番を抽出.

    パターン: GA-2100-1A1JF / DW-5600AKA-4JR / GMW-B5000BT-1 / GA-B010BEG-1AJF 等
    複数候補ある場合は最も長い (= 最も具体的な) フル型番を返す.

    制約:
    - 接頭 1-4 大文字 + ハイフン + 残りに数字を最低 1 文字含む
    - 末尾 JF/JR は optional (国内モデルサフィックス)
    - "G-SHOCK" 等の数字を含まない文字列を除外
    """
    if not text:
        return None
    # 接頭ハイフンの後に数字を 1 文字以上必須 ("G-SHOCK" を除外)
    matches = re.findall(r'\b([A-Z]{1,4}-(?=[A-Z0-9-]*\d)[A-Z0-9-]{3,18}(?:JF|JR)?)\b', text)
    # 最長 (= 最具体的) → ハイフン多 で優先
    matches.sort(key=lambda m: (-len(m), -m.count('-')))
    for m in matches:
        if '-' in m and len(m) >= 6:
            return m
    return None


def load_targets_from_low_sheet():
    """統合 LOW スプシから R='G-shock' AND B 列空 AND D 列空 の行を取込.

    Returns:
        [(url, model, price_jpy_str), ...] のリスト
        url: スプシ A 列の値 (Amazon/メルカリ等、build_row は無視するが scrape_casio
             fallback 時に CASIO URL を build_casio_url で別生成して使う).
        model: タイトル/説明から regex 抽出した CASIO 型番.
        price_jpy_str: F 列 (商品価格円) の生文字列 (例: "17600", "¥17,600", "").
                       空時は main() で COST_JPY_FALLBACK 適用.

    型番抽出失敗の行は SKIP (Precision 100% 原則).
    """
    if not _os.path.exists(GSHEET_CREDS):
        print(f"⚠️ Google認証ファイルなし: {GSHEET_CREDS} → スプシ取込スキップ")
        return []

    try:
        import gspread
        from google.oauth2.service_account import Credentials
        creds = Credentials.from_service_account_file(
            GSHEET_CREDS,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(GSHOCK_SHEET_ID)
        ws = sh.get_worksheet_by_id(GSHOCK_GID)
        all_values = ws.get_all_values()
    except Exception as e:
        print(f"⚠️ スプシ取込失敗: {type(e).__name__}: {e} → URL ファイル fallback")
        return []

    targets = []
    skipped_no_model = 0
    for row in all_values[1:]:
        url      = (row[0]  if len(row) > 0  else '').strip()  # A
        item_id  = (row[1]  if len(row) > 1  else '').strip()  # B (空=未処理)
        title_jp = (row[2]  if len(row) > 2  else '').strip()  # C
        sold     = (row[3]  if len(row) > 3  else '').strip()  # D 売り切れ
        price_f  = (row[5]  if len(row) > 5  else '').strip()  # F 商品価格 (仕入参考)
        desc     = (row[7]  if len(row) > 7  else '').strip()  # H 商品説明
        title_en = (row[8]  if len(row) > 8  else '').strip()  # I Title
        category = (row[17] if len(row) > 17 else '').strip()  # R カテゴリ

        # 仕様: R 列='G-shock' 必須 (抽出くん側で必ず埋める).
        # 他 listing スクリプト (Montbell/Tシャツ 等) と同じ運用.
        if not url or item_id or sold or category != 'G-shock':
            continue
        # タイトル/説明から CASIO 型番抽出
        text = title_jp + ' ' + title_en + ' ' + desc
        model = extract_model_from_text(text)
        if not model:
            skipped_no_model += 1
            continue
        targets.append((url, model, price_f))

    if skipped_no_model:
        print(f"⚠️ {skipped_no_model} 件は型番抽出失敗で SKIP (Precision 100% 原則)")
    return targets

def get_store_category(model):
    key = model.upper().replace("-", "")
    for prefix, cat_id in STORE_CATEGORIES.items():
        if key.startswith(prefix):
            return cat_id
    analog = ["GA", "GS", "GM", "GB", "GR"]
    for p in analog:
        if key.startswith(p):
            return 41927356010
    return 41925822010

def map_first(text, mapping, default=""):
    for key, val in mapping.items():
        if key in text:
            return val
    return default

def get_band_material(text):
    materials = []
    for key, val in BAND_MATERIAL_MAP.items():
        if key in text and val not in materials:
            materials.append(val)
    return ", ".join(materials) if materials else "Resin"

def get_display(text, model=""):
    """ディスプレイタイプ取得（モデル番号ベースのフォールバック付き）"""
    if "アナデジ" in text or "アナログ・デジタル" in text:
        return "Analog & Digital"
    elif "アナログ" in text:
        # GA系・GST系はアナデジが多いが、テキストにアナログが含まれる場合がある
        # モデル番号でデジタル確定モデルはDigitalを返す
        key = model.upper().replace("-", "")
        digital_prefixes = ["DW", "GW", "GX", "GBD", "GBX", "GMW"]
        if any(key.startswith(p) for p in digital_prefixes):
            return "Digital"
        return "Analog"
    return "Digital"

def get_band_width(text):
    """バンド幅取得"""
    m = re.search(r'バンド幅[^\d]*(\d+)\s*mm', text)
    if m: return f"{m.group(1)} mm"
    # 一般的なG-SHOCKのバンド幅はモデルによって16mm/20mm/22mm
    return ""

def get_features(text, display=""):
    """eBay公式フィルタ正規値で Features を生成。
    G-Shock共通機能 + デジタル共通機能 + ページ固有機能 を合体。"""
    features = []
    # 1. ページ本文から検出
    for key, val in FEATURES_MAP.items():
        if key in text and val not in features:
            features.append(val)
    # 2. 全G-Shock共通機能を強制付与
    for f in GSHOCK_COMMON_FEATURES:
        if f not in features:
            features.append(f)
    # 3. デジタル機能（Display=Digital or Analog & Digital なら付与）
    if "Digital" in display:
        for f in DIGITAL_COMMON_FEATURES:
            if f not in features:
                features.append(f)
    return ", ".join(features)

def get_case_size(s):
    m = re.search(r'[\d.]+\s*[×x]\s*([\d.]+)\s*[×x]', s)
    if m: return f"{m.group(1)} mm"
    m = re.search(r'([\d.]+)\s*mm', s)
    return f"{m.group(1)} mm" if m else ""

def get_thickness(s):
    m = re.search(r'[\d.]+\s*[×x]\s*[\d.]+\s*[×x]\s*([\d.]+)', s)
    return f"{m.group(1)} mm" if m else ""

def get_band_length(s):
    m = re.search(r'(\d+)[～〜~\-](\d+)\s*mm', s)
    return f"{m.group(1)}-{m.group(2)} mm" if m else ""

def get_weight(s):
    m = re.search(r'(\d+)\s*g', s)
    return f"{m.group(1)} g" if m else ""

def get_case_shape(model):
    key = model.upper().replace("-", "")
    return "Square" if any(key.startswith(s) for s in SQUARE_MODELS) else "Round"

def build_title(model_full, features, year, is_metal=False, display="Digital", band_color="Black"):
    """キーワード最適化タイトル生成（eBay 2026Q1 PDF準拠）
    狙うキーワード: casio g shock, mens watches, watch men, g shock watches men, casio watch men
    """
    base = f"CASIO G-Shock {model_full}"
    suffix = " New"

    # 特徴キーワード（優先度順に追加候補を構築）
    extra = []
    if is_metal:
        extra.append("Metal Covered")

    # 機能キーワード（文字数に余裕があれば追加）
    func_keywords = ["GPS", "Bluetooth", "Tough Solar"]
    for kw in func_keywords:
        if kw in features:
            extra.append(kw)

    # SEOキーワード: Mens + Display（"mens watches", "watch men" にマッチ）
    seo_part = f"Mens {display} Watch"

    # カラー（色で検索する人が多い）
    color = band_color if band_color else "Black"

    # 組み立て: CASIO G-Shock {型番} {特徴} Mens {Display} Watch {Color} New
    feat_str = " ".join(extra)
    if feat_str:
        title = f"{base} {feat_str} {seo_part} {color}{suffix}"
    else:
        title = f"{base} {seo_part} {color}{suffix}"

    # 80文字超過時は末尾の特徴キーワードから削る
    while len(title) > 80 and extra:
        extra.pop()
        feat_str = " ".join(extra)
        if feat_str:
            title = f"{base} {feat_str} {seo_part} {color}{suffix}"
        else:
            title = f"{base} {seo_part} {color}{suffix}"

    # まだ超過していればカラーを削除
    if len(title) > 80:
        title = f"{base} {seo_part}{suffix}"

    # 最終安全弁
    if len(title) > 80:
        title = title[:80].rsplit(' ', 1)[0]

    return title

def scrape_gcentral(model_base):
    """g-central.comからYear・Weight・Band Material等を取得"""
    # モデル番号からシリーズURLを生成（例：GW-6900U-1 → g-shock-gw-6900）
    series = re.sub(r'[-]?\d.*$', '', model_base).lower()  # GW-6900U-1 → gw
    # シリーズ番号を抽出
    series_num = re.search(r'(\d{3,4})', model_base)
    if not series_num:
        return {}
    url = f"https://www.g-central.com/specs/g-shock-{series}-{series_num.group(1)}/"
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return {}
        text = resp.text
        data = {}

        # Weight
        m = re.search(r'Weight[:\s]*(\d+)\s*gram', text, re.IGNORECASE)
        if m: data['weight'] = f"{m.group(1)} g"

        # Series Launch Year
        m = re.search(r'Series Launch Year[:\s]*(\d{4})', text, re.IGNORECASE)
        if m: data['year'] = m.group(1)

        # Dimensions → Case Size・Thickness
        m = re.search(r'Dimensions.*?(\d+\.?\d*)\s*x\s*(\d+\.?\d*)\s*x\s*(\d+\.?\d*)\s*mm', text, re.IGNORECASE)
        if m:
            if not data.get('case_size'): data['case_size'] = f"{m.group(2)} mm"
            if not data.get('case_thickness'): data['case_thickness'] = f"{m.group(3)} mm"

        # Band Material
        m = re.search(r'Band Material[:\s]*([^\n<]+)', text, re.IGNORECASE)
        if m:
            band_raw = m.group(1).strip()
            if 'stainless' in band_raw.lower(): data['band_material'] = 'Stainless Steel'
            elif 'nylon' in band_raw.lower(): data['band_material'] = 'Nylon'
            elif 'resin' in band_raw.lower(): data['band_material'] = 'Resin'
            elif 'silicone' in band_raw.lower(): data['band_material'] = 'Silicone'

        # Dial Color
        m = re.search(r'Dial Color[:\s]*([^\n<]+)', text, re.IGNORECASE)
        if m: data['dial_color'] = m.group(1).strip()[:20]

        return data
    except:
        return {}

def scrape_casiofanmag(model_base):
    """casiofanmag.comからYear・Weight等を取得"""
    # モデル番号からURL生成（例：GW-6900 → g-shock/gw-6900）
    series_match = re.search(r'^([A-Z]+-\d+)', model_base)
    if not series_match:
        return {}
    series = series_match.group(1).lower()
    url = f"https://casiofanmag.com/g-shock/{series}/"
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return {}
        text = resp.text
        data = {}

        # Weight
        m = re.search(r'Weight[:\s]*(\d+)\s*g', text, re.IGNORECASE)
        if m: data['weight'] = f"{m.group(1)} g"

        # Year（発売年）
        m = re.search(r'(\d{4})[^\d].*?release|release.*?(\d{4})', text, re.IGNORECASE)
        if m: data['year'] = m.group(1) or m.group(2)

        return data
    except:
        return {}


def _catalog_record_to_scrape_dict(record, fallback_model):
    """iMakCatalog の lookup_gshock 戻り値を scrape_casio 互換 dict に逆変換.

    Phase 3-B (2026-04-29): catalog hit 時に scrape_casio を skip して、
    build_row が要求する shape の data dict を組み立てる.
    キー名は scrape_casio 戻り値と完全一致 (build_row 改修不要).

    band_strap_override のみ条件付き: catalog の band_strap が
    "Two-Piece Strap" 以外のときだけセット (scrape_casio 側の挙動踏襲、
    build_row が data.get('band_strap_override', 'Two-Piece Strap') で読むため).
    """
    if not record:
        return None
    specs = record.get("specs") or {}
    product_id = record.get("product_id") or fallback_model
    data = {
        "model":             fallback_model,
        "model_official":    product_id,
        "model_base":        re.sub(r"(?:JF|JR)$", "", product_id),
        # build_row が参照する全 key (scrape_casio 戻り値と同名)
        "case_size":         specs.get("case_size", ""),
        "case_thickness":    specs.get("case_thickness", ""),
        "case_material":     specs.get("case_material", ""),
        "case_shape":        specs.get("case_shape", ""),
        "band_material":     specs.get("band_material", ""),
        "band_width":        specs.get("band_width", ""),
        "band_length":       specs.get("band_length", ""),
        "band_color":        specs.get("band_color", ""),
        "dial_color":        specs.get("dial_color", ""),
        "bezel_color":       specs.get("bezel_color", ""),
        "crystal":           specs.get("crystal", ""),
        "movement":          specs.get("movement", ""),
        "water_resistance":  specs.get("water_resistance", ""),
        "weight":            specs.get("weight", ""),
        "year":              specs.get("year", ""),
        "display":           specs.get("display", ""),
        # catalog 側 features は list の場合あり (Catalog Phase 2026-05-05 拡充以降).
        # build_row → trim_features() は string を期待 → list なら "," 結合で string 化.
        "features":          ", ".join(specs["features"]) if isinstance(specs.get("features"), list) else specs.get("features", ""),
        "is_metal":          bool(specs.get("is_metal", False)),
    }
    # band_strap_override: scrape_casio は "Two-Piece Strap" 以外の時のみセット
    band_strap = specs.get("band_strap")
    if band_strap and band_strap != "Two-Piece Strap":
        data["band_strap_override"] = band_strap
    return data


def scrape_casio(driver, url):
    try:
        driver.get(url)
        time.sleep(3)

        # ページを下までスクロールして遅延ロードを発火させる
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 2);")
        time.sleep(3)

        # 仕様セクションを直接要素で取得（dl/dt/dd構造）
        spec_text_parts = []
        try:
            # dt（ラベル）とdd（値）のペアを取得
            dts = driver.find_elements(By.TAG_NAME, "dt")
            dds = driver.find_elements(By.TAG_NAME, "dd")
            for dt, dd in zip(dts, dds):
                label = dt.text.strip()
                value = dd.text.strip()
                if label and value:
                    spec_text_parts.append(f"{label}\n{value}")
        except:
            pass

        # li要素からも取得
        try:
            lis = driver.find_elements(By.TAG_NAME, "li")
            for li in lis:
                t = li.text.strip()
                if t:
                    spec_text_parts.append(t)
        except:
            pass

        spec_from_elements = "\n".join(spec_text_parts)
        body = driver.find_element(By.TAG_NAME, "body").text

        # 仕様テーブルが出るまで最大10秒待機
        for _ in range(10):
            body = driver.find_element(By.TAG_NAME, "body").text
            if 'ケースサイズ' in body or '縦×横' in body:
                break
            time.sleep(1)

        # body.textに仕様がなければ要素テキストを使う
        if 'ケースサイズ' not in body and spec_from_elements:
            body = spec_from_elements + "\n" + body
        lines = [l.strip() for l in body.split('\n') if l.strip()]
        data = {'spec_text': body}
        model = extract_model_from_url(url)
        data['model'] = model
        data['model_base'] = re.sub(r'JF$', '', model) if model else model

        for i, line in enumerate(lines):
            nxt = lines[i+1] if i+1 < len(lines) else ""
            if any(kw in line for kw in ['ケースサイズ', '縦×横×厚さ', '縦 × 横 × 厚さ', '縦×横', 'ケース外径']):
                for j in range(i, min(i+5, len(lines))):
                    if re.search(r'\d+\.?\d*\s*[×x×]\s*\d+', lines[j]):
                        data['case_size'] = get_case_size(lines[j])
                        data['case_thickness'] = get_thickness(lines[j])
                        break
                    elif re.search(r'\d+\.?\d*\s*mm', lines[j]) and 'case_size' not in data:
                        data['case_size'] = get_case_size(lines[j])
                        break
            # サイズ数値が直接行に含まれる場合（ケースサイズラベルの次行）
            if 'case_size' not in data and re.search(r'^\d+\.?\d*\s*[×x×]\s*\d+\.?\d*\s*[×x×]\s*\d+\.?\d*\s*mm$', line):
                data['case_size'] = get_case_size(line)
                data['case_thickness'] = get_thickness(line)
            if '防水' in line:
                data['water_resistance'] = map_first(line, WATER_RESISTANCE_MAP, "200 m (20 ATM)")
            if 'バンド' in line and all(x not in line for x in ['サイズ', '素材', '装着']):
                data['band_material'] = get_band_material(line + nxt)
            if 'バンド装着可能サイズ' in line or '装着可能サイズ' in line:
                data['band_length'] = get_band_length(nxt)
            if 'ケース・ベゼル材質' in line:
                data['case_material'] = map_first(nxt, CASE_MATERIAL_MAP, "Resin")
            if 'ガラス' in line and all(x not in line for x in ['バックライト', 'LED']):
                data['crystal'] = map_first(line + nxt, CRYSTAL_MAP, "Mineral Glass")
            if '発売年月' in line:
                m = re.search(r'(\d{4})', nxt)
                if m: data['year'] = m.group(1)
            if '質量' in line:
                data['weight'] = get_weight(nxt or line)

        data.setdefault('water_resistance', '200 m (20 ATM)')
        data.setdefault('band_material', 'Resin')
        data.setdefault('case_material', 'Resin')
        data.setdefault('crystal', 'Mineral Glass')
        data.setdefault('case_size', '')
        data.setdefault('case_thickness', '')
        data.setdefault('band_length', '')
        data.setdefault('year', '')
        data['display'] = get_display(body, model)  # モデル番号も渡す
        data['features'] = get_features(body, data['display'])  # eBay正規値 + 共通機能自動補完
        data['movement'] = map_first(body, MOVEMENT_MAP, "Quartz")
        data['case_shape'] = get_case_shape(data['model_base'])
        data['band_width'] = get_band_width(body)

        # 正式型番取得（JR/JF付き）→ ページ本文から抽出
        official_model = model  # デフォルトはURLから
        # JF/JR付きで完全一致するパターンを先に試す
        model_jf_pattern = re.search(
            re.escape(model) + r'(?:JF|JR)\b', body
        )
        if model_jf_pattern:
            official_model = model_jf_pattern.group(0)
        else:
            # JF/JRなしでも本文に出てくる場合はそのまま
            model_pattern = re.search(re.escape(model), body)
            if model_pattern:
                official_model = model
        data['model_official'] = official_model
        data['model_base'] = re.sub(r'(?:JF|JR)$', '', official_model)

        # モデル番号ベースの自動補完
        model_base = data['model_base']

        # Weight
        if not data.get('weight'):
            data['weight'] = get_default_weight(model_base)

        # Tough Solar → eBay正規値 "Solar Powered"
        if is_tough_solar(model_base):
            if "Solar Powered" not in data['features']:
                data['features'] = "Solar Powered, " + data['features']
            if data['movement'] == "Quartz":
                data['movement'] = "Solar Quartz"

        # Band Color
        data['band_color'] = get_band_color(official_model)

        # Band/Strap・Band Materialをモデル番号で自動判定
        auto_band_strap = get_band_strap(official_model)
        auto_band_material = get_band_material_by_model(official_model)
        if auto_band_strap != "Two-Piece Strap":
            data['band_strap_override'] = auto_band_strap
        if auto_band_material:
            data['band_material'] = auto_band_material

        # MODEL_OVERRIDESを適用（Claudeが毎回補完していた内容）
        for key in [official_model, model_base]:
            if key in MODEL_OVERRIDES:
                overrides = MODEL_OVERRIDES[key]
                if overrides.get('year') and not data.get('year'):
                    data['year'] = overrides['year']
                if overrides.get('weight') and not data.get('weight'):
                    data['weight'] = overrides['weight']
                if overrides.get('band_material'):
                    data['band_material'] = overrides['band_material']
                if overrides.get('band_strap'):
                    data['band_strap_override'] = overrides['band_strap']
                break

        # g-central.comで不足項目を補完
        missing = not data.get('year') or not data.get('weight')
        if missing:
            print(f" [g-central補完中]", end="", flush=True)
            gc_data = scrape_gcentral(data['model_base'])
            if gc_data.get('year') and not data.get('year'):
                data['year'] = gc_data['year']
            if gc_data.get('weight') and not data.get('weight'):
                data['weight'] = gc_data['weight']
            if gc_data.get('case_size') and not data.get('case_size'):
                data['case_size'] = gc_data['case_size']
            if gc_data.get('case_thickness') and not data.get('case_thickness'):
                data['case_thickness'] = gc_data['case_thickness']
            if gc_data.get('band_material') and data.get('band_material') == 'Resin':
                data['band_material'] = gc_data['band_material']
            if gc_data.get('dial_color') and not data.get('dial_color'):
                data['dial_color'] = gc_data['dial_color']

        # まだ不足があればcasiofanmagで補完
        if not data.get('year') or not data.get('weight'):
            print(f" [casiofanmag補完中]", end="", flush=True)
            cfm_data = scrape_casiofanmag(data['model_base'])
            if cfm_data.get('year') and not data.get('year'):
                data['year'] = cfm_data['year']
            if cfm_data.get('weight') and not data.get('weight'):
                data['weight'] = cfm_data['weight']

        # Dial Color・Bezel Color → ページ本文から取得
        DIAL_COLOR_MAP = {
            "ブラック": "Black", "ホワイト": "White", "シルバー": "Silver",
            "ゴールド": "Gold", "ブルー": "Blue", "レッド": "Red",
            "グリーン": "Green", "イエロー": "Yellow", "オレンジ": "Orange",
            "グレー": "Gray", "ネイビー": "Navy", "カーキ": "Khaki",
        }
        dial_color = ""
        bezel_color = ""
        for i2, line in enumerate(lines):
            if '文字板色' in line or 'ダイアル' in line:
                nxt2 = lines[i2+1] if i2+1 < len(lines) else ""
                for jp, en in DIAL_COLOR_MAP.items():
                    if jp in nxt2 or jp in line:
                        dial_color = en
                        break
            if 'ベゼル色' in line or 'ベゼルカラー' in line:
                nxt2 = lines[i2+1] if i2+1 < len(lines) else ""
                for jp, en in DIAL_COLOR_MAP.items():
                    if jp in nxt2 or jp in line:
                        bezel_color = en
                        break
        data['dial_color'] = dial_color
        data['bezel_color'] = bezel_color

        # Metal Covered判定（GM系）
        key = model_base.upper().replace("-", "")
        data['is_metal'] = key.startswith("GM") or key.startswith("GMW")

        # HTMLソースからJSONデータを抽出（仕様テーブルが遅延ロードの場合の代替）
        if not data.get('case_size'):
            try:
                html_source = driver.page_source
                # JSON内のケースサイズパターンを探す
                patterns = [
                    r'"caseSize"[:\s]*"([^"]+)"',
                    r'"case_size"[:\s]*"([^"]+)"',
                    r'(\d+\.?\d*)\s*[×x×]\s*(\d+\.?\d*)\s*[×x×]\s*(\d+\.?\d*)\s*mm',
                ]
                for pat in patterns:
                    m = re.search(pat, html_source)
                    if m:
                        if len(m.groups()) == 3:
                            data['case_size'] = f"{m.group(2)} mm"
                            data['case_thickness'] = f"{m.group(3)} mm"
                        else:
                            raw = m.group(1)
                            data['case_size'] = get_case_size(raw)
                            data['case_thickness'] = get_thickness(raw)
                        break
            except:
                pass
            print(f"\n    [DEBUG] Case Size未取得 - サイズ関連行:")
            for line in lines:
                if any(kw in line for kw in ['mm', 'ケース', '縦', '横', '厚', 'サイズ', '×']):
                    print(f"      {line}")
            print(f"\n    [DEBUG] bodyテキスト先頭500字:")
            print(f"      {body[:500]}")

        return data
    except Exception as e:
        print(f"    Error: {e}")
        return None

def load_base_description():
    """GSHOCK.txtを読み込む"""
    try:
        with open(DESCRIPTION_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except:
        return None

def build_specs_html(data):
    """Specificationsブロック生成"""
    model = data.get('model_official', data.get('model_base', data.get('model', '')))
    features = trim_features(data.get('features', 'Shock Resist'))
    water = data.get('water_resistance', '200 m (20 ATM)')
    case_size = data.get('case_size', '')
    thickness = data.get('case_thickness', '')
    weight = data.get('weight', '')
    crystal = data.get('crystal', 'Mineral Glass')
    band_material = data.get('band_material', 'Resin')
    case_material = data.get('case_material', 'Resin')
    movement = data.get('movement', 'Quartz')
    band_length = data.get('band_length', '')
    year = data.get('year', '')
    display = data.get('display', 'Digital')

    specs = []
    specs.append(f"<li><b>Model:</b> {model}</li>")
    specs.append(f"<li><b>Movement:</b> {movement}</li>")
    specs.append(f"<li><b>Display:</b> {display}</li>")
    specs.append(f"<li><b>Water Resistance:</b> {water}</li>")
    specs.append(f"<li><b>Features:</b> {features}</li>")
    if case_size: specs.append(f"<li><b>Case Size:</b> {case_size}</li>")
    if thickness: specs.append(f"<li><b>Case Thickness:</b> {thickness}</li>")
    if weight: specs.append(f"<li><b>Weight:</b> {weight}</li>")
    specs.append(f"<li><b>Crystal:</b> {crystal}</li>")
    specs.append(f"<li><b>Case Material:</b> {case_material}</li>")
    specs.append(f"<li><b>Band Material:</b> {band_material}</li>")
    if band_length: specs.append(f"<li><b>Band Length:</b> {band_length}</li>")
    if year: specs.append(f"<li><b>Year:</b> {year}</li>")

    return f"""<p><span style="text-decoration: underline;"><strong><span style="vertical-align: inherit;"><span style="vertical-align: inherit;">Specifications</span></span></strong></span></p>
<ul>
{chr(10).join(specs)}
</ul>"""

def build_description(data, base_html):
    """GSHOCK.txtにSpecificationsブロックを挿入"""
    specs_html = build_specs_html(data)
    if not base_html:
        # GSHOCK.txtがない場合はシンプルなHTMLを生成
        return f"""<html><body><p><b>We handle genuine Japanese products.</b></p>
{specs_html}
<p>Thank you for your understanding and cooperation.</p>
</body></html>"""
    marker = '<p><span style="text-decoration: underline;"><strong>Shipping'
    if marker in base_html:
        return base_html.replace(marker, specs_html + '\n' + marker, 1)
    return base_html

def build_row(url, price, data, base_desc):
    model_full = data.get('model_base', data.get('model', ''))
    model_official = data.get('model_official', model_full)
    features = trim_features(data.get('features', 'Shock Resist'))
    year = data.get('year', '')
    band_color = data.get('band_color', 'Black')
    dial_color = data.get('dial_color', '')
    bezel_color = data.get('bezel_color', '')
    is_metal = data.get('is_metal', False)
    model_base = re.sub(r'JF$|JR$', '', model_full)
    bezel_material = "Stainless Steel" if is_metal else "Resin"
    case_shape = data.get('case_shape', 'Round')
    band_width = data.get('band_width', '')
    band_strap = data.get('band_strap_override', 'Two-Piece Strap')
    # Descriptionに最新値が反映されるようdataを更新してから生成
    data['features'] = features
    data['model_official'] = model_official
    display = data.get('display', 'Digital')
    title = build_title(model_official, features, year, is_metal, display, band_color)
    description = build_description(data, base_desc)

    # === Title整合性 + 70字パディング (listing_common.normalize_title) ===
    # G-Shock は新品扱い (CASIO公式仕入)
    _gs_specs = {
        'Color': band_color, 'Material': data.get('case_material', ''),
        'Year Manufactured': year,
    }
    title = normalize_title(
        title, is_new=True, item_specifics=_gs_specs,
        category="gshock", target_min=70, max_chars=80,
    )

    style = get_style_by_model(model_base)  # シリーズ別: Mudmaster→Military / Frogman→Diver / MR-G→Luxury / 他→Sport
    # Case Thickness: eBay フィルタは整数mm（5-20）。"12.4 mm" → "12 mm" に丸め
    case_thickness_raw = data.get('case_thickness', '')
    m_th = re.search(r'(\d+\.?\d*)', case_thickness_raw)
    case_thickness = f"{int(round(float(m_th.group(1))))} mm" if m_th else ""
    # Lug Width: G-Shock は一体型バンドのため Band Width と同値
    lug_width = band_width
    return [
        "Add", CATEGORY, title, PIC_URL, price, 1000,
        model_official, description,
        get_schedule_time(),
        "Casio", model_official,  # Brand=Casio (50K件、多数派プール)。Brand=G-SHOCK(9K)も独立値として存在するが少数派なのでCasio維持
        "Men", "Wristwatch", style,       # Department = Men, Style=シリーズ別判定
        data.get('display', 'Digital'),
        "Black",        # C:Case Color
        band_color,     # C:Band Color
        dial_color,     # C:Dial Color
        bezel_color,    # C:Bezel Color
        bezel_material, # C:Bezel Material
        "Fixed",        # C:Bezel Type (G-SHOCK標準=回転無し。25K件主流)
        "Logo",         # C:Dial Pattern (G-SHOCK文字盤はLogo中心。11K件主流)
        data.get('band_material', 'Resin'),
        data.get('case_material', 'Resin'),
        features,
        "Does not apply",   # C:Country of Origin
        data.get('movement', 'Quartz'),  # eBay有効値はQuartzのみ（Solar/RadioはFeatures側）
        data.get('water_resistance', '200 m (20 ATM)'),
        get_ebay_model_filter(model_base) or model_base, "No",  # C:Model = eBayシリーズフィルタ値（"G-SHOCK 5600"等）
        data.get('case_size', ''),
        data.get('crystal', 'Mineral Crystal'),
        year,
        case_shape,         # C:Case Shape
        case_shape,         # C:Watch Shape
        band_strap,         # C:Band/Strap（Bracelet or Two-Piece Strap）
        "Buckle",           # C:Closure
        "Solid",            # C:Caseback
        "Arabic Numerals",  # C:Indices
        band_width,         # C:Band Width
        lug_width,          # C:Lug Width (= Band Width, G-Shock一体型バンド)
        "No",               # C:Vintage
        "No",               # C:Handmade
        "Yes",              # C:With Original Box/Packaging
        "Yes",              # C:With Papers (新品 = 日本語マニュアル付属、英語版なしは Description に注記)
        "",                 # C:Manufacturer Warranty (国内保証は海外履行不可、空欄で Defect Rate 回避)
        data.get('band_length', ''),
        case_thickness,     # 整数mmに丸め
        data.get('weight', ''),
        "FixedPrice", "GTC", 1,
        1, LOCATION, 1,
        "Does not apply",
        get_shipping_policy(price), RETURN_POLICY, PAYMENT_POLICY,
        get_store_category(model_full),
    ]

def main():
    print("=== iMak Trading Japan - G-SHOCK CASIO URL → eBay CSV ===\n")
    # 2026-05-05: 入力経路を LOW スプシ駆動 (主) + URL ファイル (fallback) に拡張
    # memory: dropshipping_model_premise (抽出くん収集 → 出品くん自動連動)
    print("📊 LOW スプシから R='G-shock' 行を取込中...")
    sheet_targets = load_targets_from_low_sheet()  # [(url, model), ...]
    print(f"  スプシ取込: {len(sheet_targets)} 件")

    file_targets = []
    try:
        with open(URLS_FILE, "r", encoding="utf-8") as f:
            file_urls = [l.strip() for l in f if l.strip() and l.startswith("http")]
        for u in file_urls:
            m = extract_model_from_url(u)
            if m:
                file_targets.append((u, m, ""))  # URL ファイル経由は price_jpy 空 (cost fallback)
        print(f"  URL ファイル: {len(file_targets)} 件")
    except FileNotFoundError:
        print(f"  URL ファイル ({URLS_FILE}) なし → スプシのみ")

    targets = sheet_targets + file_targets
    if not targets:
        print(f"エラー: 処理対象なし (スプシも URL ファイルも空)")
        input("Enterで終了...")
        return

    print(f"\n合計 {len(targets)} 件を処理します。\n")
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    driver = uc.Chrome(options=options, version_main=146)
    base_desc = load_base_description()

    headers = [
        "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)",
        "*Category", "*Title", "PicURL", "*StartPrice", "ConditionID",
        "CustomLabel", "*Description",
        "ScheduleTime",
        "C:Brand", "C:MPN", "C:Department", "C:Type", "C:Style", "C:Display",
        "C:Case Color", "C:Band Color", "C:Dial Color", "C:Bezel Color", "C:Bezel Material",
        "C:Bezel Type", "C:Dial Pattern",
        "C:Band Material", "C:Case Material",
        "C:Features", "C:Country of Origin", "C:Movement",
        "C:Water Resistance", "C:Model", "C:Customized",
        "C:Case Size", "C:Crystal", "C:Year Manufactured",
        "C:Case Shape", "C:Watch Shape",
        "C:Band/Strap", "C:Closure", "C:Caseback", "C:Indices", "C:Band Width", "C:Lug Width",
        "C:Vintage", "C:Handmade",
        "C:With Original Box/Packaging", "C:With Papers", "C:Manufacturer Warranty",
        "C:Band Length", "C:Case Thickness", "C:Item Weight",
        "*Format", "*Duration", "*Quantity",
        "PayPalAccepted", "*Location", "BestOfferEnabled",
        "Product:UPC",
        "ShippingProfileName", "ReturnProfileName", "PaymentProfileName",
        "StoreCategoryID",
    ]

    rows = [headers]
    errors = []

    # ホワイトリスト検証（Pythonマッピングのバグ検出用、Claude無いのでリトライ不可）
    # 2026-05-05 専門化: 共有 whitelist_registry から gshock_whitelist (専用) に切替
    # memory: category_specialization_principle.md / no_modification_chain.md
    try:
        import sys as _sys
        import os as _os
        _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
        from gshock_whitelist import validate_and_normalize as _validate_specs
    except Exception:
        _validate_specs = None

    for url, model, price_jpy_str in targets:
        print(f"取得中: {model}...", end="", flush=True)
        # Phase 3-B (2026-04-29): catalog hit 経路 — Selenium scrape を skip.
        # catalog miss / 未投入 / 例外 → 既存 scrape_casio フォールバック (byte 互換).
        data = None
        if _catalog_lookup is not None:
            try:
                _cat_rec = _catalog_lookup(model)
                if _cat_rec:
                    data = _catalog_record_to_scrape_dict(_cat_rec, model)
                    if data:
                        print(" [catalog hit]", end="", flush=True)
            except Exception as _e:
                # catalog エラーは Selenium fallback (既存挙動維持)
                print(f" [catalog err: {type(_e).__name__}]", end="", flush=True)
                data = None
        if data is None:
            # スプシ駆動の場合 url が CASIO 公式形式でない (Amazon 等) → CASIO URL に変換
            scrape_url = url if 'casio.com' in url else build_casio_url(model)
            data = scrape_casio(driver, scrape_url)
        if data:
            print(f" → {data.get('case_size','?')} / {data.get('crystal','?')} / StoreCat:{get_store_category(data['model_base'])} ✓")
            # 動的価格決定 (2026-05-05 Montbell パターン適用)
            # F 列 (price_jpy_str) を仕入参考にして pricing_engine で算出
            cost_jpy = COST_JPY_FALLBACK
            if price_jpy_str:
                _ps = re.sub(r"[^0-9]", "", price_jpy_str)
                if _ps:
                    cost_jpy = int(_ps)
            try:
                min_price = compute_min_price_usd(cost_jpy, PROFIT_CATEGORY)
            except Exception:
                min_price = DEFAULT_PRICE
            price = max(min_price, PRICE_FLOOR_USD)
            price = round(price, 2)
            price = int(price) + 0.98 if price > 10 else price
            # eBay 中央値取得 (pricing_engine ALERT 判定用)
            ebay_median = 0.0
            if _fetch_ebay_median is not None:
                try:
                    ebay_median, _ebay_hits = _fetch_ebay_median(
                        keywords=f"Casio G-Shock {model}",
                        category_ids=EBAY_CATEGORY_GSHOCK,
                        condition_id="1000",
                    )
                    if ebay_median:
                        print(f"    📊 eBay {_ebay_hits}件 中央値${ebay_median:.0f}")
                except Exception as _eme:
                    pass
            # 価格 status 判定 (pricing_engine 相場乖離チェック)
            _price_status = "GO"
            if _compute_listing_price is not None:
                try:
                    _pr = _compute_listing_price(cost_jpy, ebay_median, PROFIT_CATEGORY)
                    _price_status = _pr.get("status", "GO")
                    if _price_status == "ALERT":
                        print(f"    ⚠️ 価格ALERT: {_pr.get('alert_msg', '')}")
                except Exception:
                    pass
            print(f"    💲 ${price} (仕入¥{cost_jpy})")
            row = build_row(url, price, data, base_desc)
            # SKU 上書き: 共通ルール (TCG/Tshirt/Montbell と同じ、URL ベース).
            # CASIO 公式 URL の場合は build_row の model_official (型番) をそのまま維持.
            # Amazon ASIN: /dp/XXXXXXXXXX (10 文字)
            # Mercari itemID: /item/m+数字
            # それ以外は extract_sku_from_url の末尾 12 文字 fallback
            if 'casio.com' not in url:
                _sku = None
                _am = re.search(r'/dp/([A-Z0-9]{10})', url)
                if _am:
                    _sku = _am.group(1)
                else:
                    _mm = re.search(r'/item/(m\d+)', url)
                    if _mm:
                        _sku = _mm.group(1)
                    else:
                        _sku = _extract_sku_from_url(url, category="gshock")
                if _sku:
                    row[6] = _sku  # CustomLabel

            # 検証＋正規化（C: プレフィックス列のみ抽出）
            if _validate_specs:
                specs_dict = {}
                for h, v in zip(headers, row):
                    if h.startswith("C:"):
                        specs_dict[h[2:]] = v  # "C:Brand" → "Brand"
                normalized, viol = _validate_specs(specs_dict)
                if viol:
                    print(f"    ⚠️ ホワイトリスト違反{len(viol)}件:")
                    for f, o, _e, r in viol:
                        print(f"       - {f}: '{o}' ({r})")
                # 正規化値で行を更新（自動修正可能な範囲）
                for i, h in enumerate(headers):
                    if h.startswith("C:") and h[2:] in normalized:
                        if row[i] != normalized[h[2:]]:
                            row[i] = normalized[h[2:]]

            # === 物理ゲート: audit_csv_row error なら HOLDキューへ隔離 ===
            # 注: gshock は DEFAULT_PRICE 固定運用のため price_status/median_usd はデフォルト値 (GO, 0)。
            #     将来 per-item dynamic pricing を導入したら fetch_ebay_market_median + compute_listing_price を結線。
            from listing_common import gate_row_or_hold as _gate
            _row_dict = dict(zip(headers, row))
            _allowed, _viol = _gate(_row_dict, category="gshock", sku=data.get("model_official", ""))
            if not _allowed:
                _errs = [f"{f}={i}" for f, i, s in _viol if s == "error"]
                print(f"    🟠 HOLD: {data.get('model_official','')} → {_errs}")
                errors.append(url)
                continue
            rows.append(row)
        else:
            print(f" → 失敗")
            errors.append(url)

    driver.quit()

    _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "iMakeBayAPI"))
    from listing_core import get_csv_output_path
    output_file = get_csv_output_path("gshock", "upload")
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        writer.writerows(rows)

    # Step 8 拡張: decision_log に config_version + 使用値を刻印
    try:
        from decision_log import log_csv_batch as _log_batch
        _log_batch(project="iMakG-shock", category="G-SHOCK",
                   output_path=output_file, row_count=max(0, len(rows) - 1))
    except Exception as _e:
        print(f"⚠️ decision_log 失敗 (G-shock): {type(_e).__name__}: {_e}")

    print(f"\n完了！出力: {output_file}")
    print(f"成功: {len(rows)-1}件 / 失敗: {len(errors)}件")

    print("\n=== タイトル確認 ===")
    for row in rows[1:]:
        t = row[2]
        s = "✅" if len(t) <= 80 and t.endswith("New") else "⚠️"
        print(f"  {s} ({len(t)}字) {t}")

    print("\n⚠️ 要手動確認：Case Color / Band Color / Department / Style")
    input("\nEnterで終了...")

if __name__ == "__main__":
    main()
