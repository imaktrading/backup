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
import bandai_jp
import pokemon_card_jp
import bandai_tcg_plus

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# iMakeBayAPI の共通モジュール（listing_validator, profit_params, listing_common 等）を import 可能にする
# build_row() 等で動的 import されるため、モジュールロード時にパスを通しておく必要あり
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "iMakeBayAPI"))
from listing_core import get_csv_output_path as _gcop  # CSV出力先の中央集約用 (iMakHQ/csv_output/<project>_upload_<ts>.csv)

# ===== 設定 =====
CERTS_FILE = "certs.txt"
DESCRIPTION_FILE = "PSA10.txt"
DEFAULT_PRICE = 100.00
SCHEDULE_WEEKS = 2

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
    resp = requests.post(
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
    価格基準: 全セラー中央値（TOPセラーは参考表示のみ）"""
    game_short = {
        "Dragon Ball Super Card Game": "Dragon Ball",
        "One Piece Card Game": "One Piece",
        "Gundam CCG": "Gundam",
        "Pokemon": "Pokemon",
        "Pokémon TCG": "Pokemon",
    }.get(game, game)
    # カード番号から分母を除去（"231/193" → "231"）eBay検索では不要
    card_number = card_number.split("/")[0] if "/" in card_number else card_number

    query = f"PSA 10 {game_short} #{card_number} {character}"
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    params = {
        "q": query,
        "filter": (
            "buyingOptions:{FIXED_PRICE},"
            "conditionIds:{2750},"
            "categoryIds:{183454}"
        ),
        "sort": "price",
        "limit": 50,
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        if resp.status_code != 200:
            return None
        data = resp.json()
        items = data.get("itemSummaries", [])
        total = data.get("total", 0)  # 市場全体の出品数
        if not items:
            return None

        top_prices = []
        all_prices = []
        for item in items:
            try:
                price = float(item.get("price", {}).get("value", 0))
                if price <= 0:
                    continue
            except (ValueError, TypeError):
                continue
            all_prices.append(price)
            seller = item.get("seller", {})
            score = seller.get("feedbackScore", 0)
            pct_str = seller.get("feedbackPercentage", "0")
            try:
                pct = float(pct_str)
            except (ValueError, TypeError):
                pct = 0
            if score >= TOP_SELLER_MIN_FEEDBACK and pct >= TOP_SELLER_MIN_PERCENTAGE:
                top_prices.append(price)

        if not all_prices:
            return None

        all_sorted = sorted(all_prices)
        all_median = all_sorted[len(all_sorted) // 2]

        top_median = None
        if top_prices:
            top_sorted = sorted(top_prices)
            top_median = top_sorted[len(top_sorted) // 2]

        return {
            "all_median": all_median,
            "all_count": len(all_prices),
            "top_median": top_median,
            "top_count": len(top_prices),
            "total": total,  # 市場全体の出品数
            "items": items,  # アイテム詳細取得用
        }
    except Exception as e:
        print(f"    ⚠️ eBay API: {e}")
        return None

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
    for threshold, policy in SHIPPING_POLICIES:
        if price <= threshold:
            return policy
    return "800-1000"

def get_schedule_time():
    future = datetime.utcnow() + timedelta(weeks=SCHEDULE_WEEKS)
    return future.strftime("%Y-%m-%d %H:%M:%S")

def get_store_category(franchise):
    for key, cat_id in STORE_CATEGORIES.items():
        if key.lower() in franchise.lower():
            return cat_id
    return 42054516010

def extract_set_code_from_brand(brand):
    """PSA Brand から Bandai 公式 set_code を抽出.
    例: 'ONE PIECE JAPANESE OP08-TWO LEGENDS' → 'OP08'
    プロモ/イベントなら 'P' を返す (Bandai promo prefix)
    """
    if not brand:
        return None
    b = brand.upper()
    # 標準セットコード (OP01-OP99, ST01-ST99, EB01-EB99, PRB01-PRB99)
    m = re.search(r'\b(OP\d+|ST\d+|EB\d+|PRB\d+)\b', b)
    if m:
        return m.group(1)
    # プロモ判定
    promo_keywords = [
        "PROMOS", "PROMO", "ONE PIECE DAY", "BANDAI CARD GAME FEST",
        "ANNIVERSARY", "PREMIUM CARD COLLECTION", "CHAMPIONSHIP",
    ]
    if any(k in b for k in promo_keywords):
        return "P"
    return None


def _extract_set_name_from_get_info(get_info_jp):
    """Bandai JP の get_info(入手情報) から eBay 用セット名を生成.
    例: 'ブースターパック 二つの伝説【OP-08】' → 'Two Legends'
        'ONE PIECE DAY 23 来場特典' → 'Promo Cards'
        'パラレルの覇者【OP-06】' → 'Wings of the Captain' ← 日本語未翻訳は難しい
    マッピング辞書 + 簡易正規化。未知はそのまま日本語を返す.
    """
    if not get_info_jp:
        return ""
    info = get_info_jp.strip()
    # 既知セットマッピング (日本語名の一部 → 英語正式名)
    set_map_jp_to_en = {
        "パラレルの覇者": "Wings of the Captain",  # OP-06
        "二つの伝説": "Two Legends",  # OP-08
        "新時代の主役": "Awakening of the New Era",  # OP-05
        "謀略の王国": "Kingdoms of Intrigue",  # OP-04
        "強大な敵": "Pillars of Strength",  # OP-03
        "頂上決戦": "Paramount War",  # OP-02
        "ROMANCE DAWN": "Romance Dawn",  # OP-01
        "500年後の未来": "500 Years in the Future",  # OP-07
        "新たなる皇帝": "Emperors in the New World",  # OP-09
        "ロイヤル・ブラッドライン": "Royal Bloodlines",  # OP-10
        "記憶の断片": "Memorial Collection",  # EB-01
        "Anime 25th collection": "Anime 25th Collection",  # EB-02
        "Anime 25th Collection": "Anime 25th Collection",
        "ONE PIECE CARD THE BEST": "Premium Booster -The Best-",  # PRB-01
        "プレミアムブースター": "Premium Booster",
        "ONE PIECE DAY": "Promo Cards",
        "ONE PIECE CARD GAME": "Promo Cards",
        "BANDAI CARD GAME FEST": "Promo Cards",
        "プロモ": "Promo Cards",
        "来場特典": "Promo Cards",
        "タイアップ": "Promo Cards",
        "キャンペーン": "Promo Cards",
        "ガイド": "Promo Cards",
    }
    for jp, en in set_map_jp_to_en.items():
        if jp in info:
            return en
    # マッピング無しなら空 (fallback)
    return ""


def lookup_bandai_card(driver, brand, card_number, subject):
    """Bandai JP 公式からカード情報を取得. PSA Subjectとのマッチ検証付き."""
    if not card_number:
        return None
    set_code = extract_set_code_from_brand(brand)

    cards = []
    if set_code:
        card_id = f"{set_code}-{card_number}"
        try:
            cards = bandai_jp.fetch_card(driver, card_id)
        except Exception as e:
            print(f"    ⚠️ Bandai JP fetch エラー: {e}")
            cards = []
    else:
        card_id = "(set_code抽出失敗)"

    # PSA Subjectとの名前検証: Subject内の実体トークンが
    # Bandai name_en または name_jp(翻訳済み)に含まれるか
    subject_tokens = [
        w.upper().strip('.,;:') for w in re.split(r'[\s/]+', subject)
        if len(w) >= 3 and not w.isdigit()
    ]
    # 接続詞/一般語除外
    stopwords = {"THE", "OF", "AND", "FOR", "ALTERNATE", "SPECIAL", "ART",
                 "RARE", "PARALLEL", "MANGA", "FOIL", "HOLO", "PROMO",
                 "ONE", "PIECE", "DAY", "FEST", "BANDAI", "CARD", "GAME",
                 "PACKS", "BATTLE", "WINNER", "KING", "PIRATES",
                 "ANNIVERSARY", "PREMIUM", "COLLECTION"}
    name_tokens = [t for t in subject_tokens if t not in stopwords]

    def card_name_matches(card):
        en = (card.get("name_en") or "").upper()
        jp = card.get("name_jp") or ""
        combined = en + " " + jp
        if not name_tokens:
            return True  # トークン無しなら検証スキップ
        return any(t in combined.upper() for t in name_tokens)

    def card_number_matches(card):
        """Bandai card_id の番号部分が PSA card_number と一致するか."""
        cid = card.get("card_id", "")
        m = re.match(r'^[A-Z]+\d*-(\d+)', cid)
        if not m:
            return False
        return m.group(1).lstrip("0") == card_number.lstrip("0")

    def is_valid_match(card):
        return card_name_matches(card) and card_number_matches(card)

    valid = [c for c in cards if is_valid_match(c)]
    if not valid:
        print(f"    ⚠️ Bandai JP ID={card_id} 一致せず → 名前検索フォールバック")
        # キャラ名から逆引き検索
        character = smart_titlecase(extract_character_name(subject))
        try:
            name_cards = bandai_jp.search_by_name(driver, character, card_number)
        except Exception as e:
            print(f"    ⚠️ Bandai JP name search エラー: {e}")
            name_cards = []
        valid = [c for c in name_cards if is_valid_match(c)]
        if not valid:
            print(f"    ⚠️ Bandai JP 名前検索でも一致せず (キャラ={character!r}) → PSAフォールバック")
            return None

    best = bandai_jp.select_best_variant(valid, subject, psa_set_hint=set_code or "")
    if best:
        print(f"    🎯 Bandai JP hit: {best.get('card_id')} {best.get('name_en')} "
              f"({best.get('type_en')}, rarity={best.get('rarity_en')!r})")
    return best


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
        return "Gundam CCG", "Dual Impact", "Gundam"
    elif "NEWTYPE RISING" in brand_upper:
        return "Gundam CCG", "Newtype Rising", "Gundam"
    elif "STEEL REQUIEM" in brand_upper:
        return "Gundam CCG", "Steel Requiem", "Gundam"
    elif "HEROIC BEGINNINGS" in brand_upper:
        return "Gundam CCG", "Heroic Beginnings", "Gundam"
    elif "WINGS OF ADVANCE" in brand_upper:
        return "Gundam CCG", "Wings of Advance", "Gundam"
    elif "ZEON" in brand_upper:
        return "Gundam CCG", "Zeon's Rush", "Gundam"
    elif "SEED STRIKE" in brand_upper:
        return "Gundam CCG", "SEED Strike", "Gundam"
    elif "IRON BLOOM" in brand_upper:
        return "Gundam CCG", "Iron Bloom", "Gundam"
    elif "GUNDAM" in brand_upper and ("EX BASE" in brand_upper or "PROMOS" in brand_upper):
        return "Gundam CCG", "Edition Beta Promos", "Gundam"
    elif "GUNDAM" in brand_upper:
        return "Gundam CCG", brand, "Gundam"
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
        # Game名: eBay慣行は "One Piece Card Game" (公式名)
        # TOPセラーで "One Piece CCG" も見られるが、公式名を優先
        return "One Piece Card Game", short_set, "One Piece"
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
- Game short names: "One Piece TCG" / "Dragon Ball SCG" / "Gundam CCG" / "Pokemon"
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

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
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
                model="claude-sonnet-4-20250514",
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
    "japanese", "japan", "gem mt", "gem-mt", "gemmt",
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
    game_short = {
        "Dragon Ball Super Card Game": "Dragon Ball SCG",
        "One Piece Card Game": "One Piece TCG",
        "Gundam CCG": "Gundam CCG",
        "Pokemon": "Pokemon",
        "Pokémon TCG": "Pokemon",
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
            return cached

    url = f"https://www.psacard.com/ja-JP/cert/{cert_number}/psa"
    try:
        driver.get(url)
        time.sleep(5)
        body = driver.find_element(By.TAG_NAME, "body").text

        # カード画像URL取得
        card_image_url = None
        try:
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            imgs = driver.find_elements(By.TAG_NAME, "img")
            for img in imgs:
                src = img.get_attribute("src") or ""
                if any(x in src.lower() for x in ['cert', 'card', 'psa', 'grading']) and src.startswith("http"):
                    card_image_url = src
                    break
        except Exception as e:
            print(f"\n    画像取得エラー: {e}")

        data = parse_psa_page(body)
        if card_image_url:
            data['CardImageUrl'] = card_image_url
        if not data.get('Subject'):
            print(f"\n    [DEBUG] {body[:400]}")
            return None

        # キャッシュに保存
        cache[cert_number] = data
        _save_psa_cache(cache)
        return data
    except Exception as e:
        print(f"    Error: {e}")
        return None


# ===== Dragon Ball / Gundam カードID構築 =====
# PSA Brand内のセット名 → Bandai TCG+ カード番号プレフィックス
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
    """PSA BrandとCardNumberからBandai TCG+用のcard_id(FB03-139形式)を構築"""
    if not brand or not card_number:
        return None
    b = brand.upper()
    for set_name, prefix in DRAGONBALL_SET_PREFIX.items():
        if set_name in b:
            return f"{prefix}-{card_number.zfill(3)}"
    # プレフィックスが見つからなければ、card_numberにFBが含まれるか確認
    m = re.match(r'(FB\d+|SB\d+|FS\d+)-?(\d+)', card_number)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(3)}"
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


# ===== One Piece Item Specifics整形 =====
def _onepiece_rarity_to_ebay(rarity):
    """Bandai公式のrarity_en → eBay慣行の略称に変換"""
    mapping = {
        "Secret Rare": "SEC",
        "Special": "SEC",      # Bandai "Special" = eBay "SEC" (パラレル系)
        "Super Rare": "SR",
        "Rare": "R",
        "Uncommon": "UC",
        "Common": "C",
        "Promo": "Promo",
    }
    return mapping.get(rarity, rarity)


def _onepiece_set_to_ebay(get_info_jp, card_id=""):
    """Bandai公式データ → eBay慣行のセットコードに変換。
    card_idが最も正確（カードが実際に収録されているセット）なので優先。
    例: card_id='OP10-119' → 'OP-10'
        card_id='ST02-007' → 'ST-02'
        get_info_jp='ブースターパック 王族の血統【OP-10】' → 'OP-10'
    """
    set_code = ""

    # card_idから抽出（最優先 — カードが実際に属するセット）
    if card_id:
        # _p1等のバリアント識別子を除去してから
        clean_id = re.sub(r'_[a-z]\d*$', '', card_id)
        id_match = re.match(r'([A-Z]+)(\d+)-', clean_id)
        if id_match:
            prefix = id_match.group(1)
            num = id_match.group(2)
            set_code = f"{prefix}-{num}"

    # card_idから取れなければget_info_jpから
    if not set_code and get_info_jp:
        code_match = re.search(r'【([A-Z]+-\d+)】', get_info_jp)
        if code_match:
            set_code = code_match.group(1)

    return set_code


# ===== Pokemon Item Specifics整形 =====
POKEMON_SET_NAME_MAP = {
    "M2A-MEGA DREAM EX": "M2a: High Class Pack: Mega Dream Ex",
    "M2A": "M2a: High Class Pack: Mega Dream Ex",
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
    """
    if not subject:
        return subject
    s = subject.strip()
    rarity_suffixes = [
        r'\s+MEGA\s+ATTACK\s+RARE$',
        r'\s+MEGA\s+ATTACK$',
        r'\s+MEGA\s+ULTRA\s+RARE$',
        r'\s+BRIGHT\s+WORLD\s+RARE$',
        r'\s+SPECIAL\s+ART\s+RARE$',
        r'\s+SPECIAL\s+ART$',
        r'\s+ART\s+RARE$',
        r'\s+ULTRA\s+RARE$',
        r'\s+RARE$',
    ]
    result = s
    for pat in rarity_suffixes:
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


def build_row(cert_number, price, data, description, driver=None):
    subject = data.get('Subject', 'Unknown')
    card_number = data.get('CardNumber', '')
    brand = data.get('Brand', '')
    year = data.get('Year', 2025)

    card_number = str(card_number)  # ゼロ埋め保持
    game, set_name, franchise = detect_game_info(brand)
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

    if driver and franchise == "One Piece":
        # Bandai JP 公式 (One Piece)
        bandai = lookup_bandai_card(driver, brand, card_number, subject)
        if bandai:
            character = bandai.get("name_en") or character
            set_name_bandai = _extract_set_name_from_get_info(bandai.get("get_info_jp", ""))
            if set_name_bandai:
                set_name = set_name_bandai
            official_card_type = bandai.get("type_en", "")
            official_rarity = bandai.get("rarity_en", "")
            official_color = bandai.get("color_en", "")
            official_power = bandai.get("power", "")
            official_cost = bandai.get("life_or_cost", "")
            official_attribute = bandai.get("attribute_en", "")
            # Card Number: Bandai card_id (例: OP10-119_p3) → パラレル識別子を除去
            bandai_card_id = bandai.get("card_id", "")
            if bandai_card_id:
                # _p1, _p2, _p3, _r1 等のバリアント識別子を除去
                official_card_number = re.sub(r'_[a-z]\d*$', '', bandai_card_id)
            # Rarity: Bandai公式表記 → eBay略称に変換
            official_rarity = _onepiece_rarity_to_ebay(official_rarity)
            # Set名: get_info_jp からセットコード表記に変換
            bandai_set_info = bandai.get("get_info_jp", "")
            ebay_set = _onepiece_set_to_ebay(bandai_set_info, bandai_card_id)
            if ebay_set:
                set_name = ebay_set
        else:
            # Bandai公式でヒットしない場合: PSA BrandからセットIDを推定してCard Numberに付与
            set_code = extract_set_code_from_brand(brand)
            if set_code and not re.match(r'[A-Z]', card_number):
                official_card_number = f"{set_code}-{card_number}"

    elif driver and franchise == "Pokemon":
        # Pokemon共通（公式ヒット有無にかかわらず設定）
        game = "Pokémon TCG"
        set_name = _pokemon_set_name(brand)
        character = _pokemon_character_name(subject)
        card_name = _pokemon_card_name(subject)

        # Pokemon公式 (pokemon-card.com)
        pokemon = pokemon_card_jp.fetch_card_with_subject(driver, brand, card_number, subject)
        if pokemon:
            print(f"    🎯 Pokemon公式: {pokemon.get('name_jp', '')} "
                  f"(rarity={pokemon.get('rarity_en', '')!r}, "
                  f"number={pokemon.get('card_number_full', '')!r})")
            official_rarity = pokemon.get("rarity_en", "")
            official_power = pokemon.get("hp", "")
            # Card Type: HPがあればポケモン、なければトレーナー
            if pokemon.get("hp"):
                official_card_type = "Pokémon"
            else:
                official_card_type = "Trainer"
            official_attribute = pokemon.get("type_en", "")
            official_illustrator = pokemon.get("illustrator", "")
            if pokemon.get("card_number_full"):
                official_card_number = pokemon["card_number_full"]

    elif franchise == "Dragon Ball":
        # Dragon Ball Fusion World 公式 (Bandai TCG+ API)
        game = "Dragon Ball Super Card Game"
        # PSA Brandからカード番号を抽出 (例: "DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE BLAZING AURA" + CardNumber "139")
        # detect_game_infoで既にset_nameが設定されている
        # card_idを構築: セット名から推定 (例: set="Blazing Aura" → FB03)
        db_card_id = _dragonball_card_id(brand, card_number)
        if db_card_id:
            db_card = bandai_tcg_plus.fetch_card(db_card_id, game="dragonball")
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

    elif franchise == "Gundam":
        # Gundam Card Game 公式 (Bandai TCG+ API)
        gd_card_id = _gundam_card_id(brand, card_number)
        if gd_card_id:
            gd_card = bandai_tcg_plus.fetch_card(gd_card_id, game="gundam")
            if gd_card:
                official_card_type = gd_card.get("card_type", "")
                official_rarity = gd_card.get("rarity", "")
                official_color = gd_card.get("color", "")
                official_power = gd_card.get("power", "")
                official_cost = gd_card.get("cost", "")
                official_card_number = gd_card.get("card_number", card_number)
                if gd_card.get("set_name"):
                    set_name = gd_card["set_name"]
                if gd_card.get("card_name"):
                    character = gd_card["card_name"]

    # Claude APIでタイトル・カード情報生成（画像あり）
    card_image_url = data.get('CardImageUrl')
    # card_number（PSA生値="004"）ではなく official_card_number（Bandai DB等で補完済="ST16-004"）を渡す。
    # セットprefix欠落→selfcheck弾きを防止（全ブランチ共通でofficial_card_numberは適切に設定済）
    claude_result = generate_title_with_claude(game, set_name, official_card_number, subject, franchise, card_image_url)
    claude_result = claude_result or {}

    # Item Specifics: 公式DB のみ採用 (2026-04-24 物理強制化、Claude フォールバック全廃)
    # グローバル CLAUDE.md「確証なきは空欄、公式サイトからの推定は不可」+ memory `enforce_in_python_not_prompt`
    # に従い、rarity/card_type/cost/power/attribute/finish 全てで claude_result を使わない。
    # 公式DB (bandai_jp / bandai_tcg_plus / pokemon_card_jp) がヒットしない場合は空欄で出品する。
    if franchise != "Pokemon":
        card_name = character
    rarity    = official_rarity      # Claude 追放
    features  = extract_variant_from_subject(subject)  # 関数ベース（PSA Subject パース、推論なし）
    card_type = official_card_type   # Claude 追放
    cost      = official_cost        # Claude 追放
    power     = official_power       # Claude 追放
    finish    = official_finish      # Claude 追放 + Subject キーワード判定も廃止
    attribute = official_color or official_attribute  # Claude 追放

    # 2026-04-24 Canonical Map (Phase 1): eBay フィルタ正規値へ無言整形
    # Gemini 監査済: 綴り揺れ/Bandai略称のみ対象、Game name 等の3派閥共存語は含めない
    _CANONICAL_FEATURES = {
        "Alternate Art": "Alternative Art",  # eBay Features 正規綴り
        "Alt Art":       "Alternative Art",
        "Alt. Art":      "Alternative Art",
    }
    _CANONICAL_CARD_TYPE = {
        "Leader Card":   "Leader",           # eBay TOPセラー慣習（"Card"無し）
    }
    if features in _CANONICAL_FEATURES:
        _new = _CANONICAL_FEATURES[features]
        print(f"    [AUTO-FIX] Features: {features!r} -> {_new!r} (Canonical Map)")
        features = _new
    if card_type in _CANONICAL_CARD_TYPE:
        _new = _CANONICAL_CARD_TYPE[card_type]
        print(f"    [AUTO-FIX] Card Type: {card_type!r} -> {_new!r} (Canonical Map)")
        card_type = _new

    # One Piece Leader の rarity 空欄補完 (Canonical Map 適用後の値で判定)
    # Bandai は「Leader=カードタイプであってレアリティではない」設計で空欄を返すが、
    # eBay バイヤーは Rarity フィルタで "Leader" を検索する慣習あり（機会損失防止）
    if not rarity and card_type == "Leader" and franchise == "One Piece":
        rarity = "Leader"
    card_number = official_card_number  # 公式の完全番号 (例: "231/193")

    # タイトル: Claudeが有効なら使用、欠落/不正ならルールベース
    claude_title = claude_result.get('title') if claude_result else None
    if claude_title:
        title = strip_banned_words(claude_title)
        title = pad_title(title, card_type=card_type, set_name=set_name)
        title = strip_banned_words(title)
        # PSA Subjectのトークン保持を検証; 欠落があればルールベースに強制切替
        if not title_preserves_subject(title, subject):
            print(f"    ⚠️ Claudeタイトルが PSA Subject を改変 → ルールベースに切替")
            print(f"       Claude: {title}")
            title = build_title(game, set_name, card_number, subject)
        # 公式カード番号の保持を検証; Claudeが短縮した時（例: ST16-004 → 004）はルールベースに切替
        # Claudeはテンプレート"#[Num]"を番号だけと解釈することがあるため、物理的な文字列 contains で検証
        elif official_card_number and official_card_number not in title:
            print(f"    ⚠️ Claudeタイトルが card# {official_card_number} を短縮 → ルールベースに切替")
            print(f"       Claude: {title}")
            title = build_title(game, set_name, card_number, subject)
        print(f"    ✨ Title: {title} ({len(title)}字)")
    else:
        title = build_title(game, set_name, card_number, subject)
        print(f"    📐 Rule title: {title} ({len(title)}字)")
    # SKU (CustomLabel): メルカリ item ID 形式 `m\d+` を最優先（tshirt_listing_rules 準拠）。
    # 無在庫運用でメルカリ元ページへの即時逆引きと二重出品防止を両立するキー設計。
    # URL 無し / 抽出失敗時のみ PSA cert# ベースにフォールバック。
    import re as _re_sku
    _mercari_url = data.get('_mercari_url', '')
    _mid = _re_sku.search(r'/item/(m\d+)', _mercari_url)
    custom_label = _mid.group(1) if _mid else f"PSA10-{cert_number}"
    store_cat_id = get_store_category(franchise)
    shipping = get_shipping_policy(price)

    card_size = "Standard" if franchise == "One Piece" else "Japanese"
    # Manufacturerはゲームにより異なる
    manufacturer = "The Pokémon Company" if franchise == "Pokemon" else "Bandai"
    illustrator = official_illustrator or ""

    # セルフチェック（CSV出力前、PSA整合性 + 3AI議論）
    from listing_validator import validate_and_report
    tcg_specs = {"Brand": manufacturer, "Type": card_type, "Size": "N/A", "Color": attribute or "N/A",
                 "Game": game, "Set": set_name, "Rarity": rarity, "Card Number": card_number}
    # psa_card_number は listing_validator の Rule 3 が「数字のみ」を前提にしているため、
    # line 1372 で official_card_number に上書き済の card_number ではなく PSA 生値を渡す。
    # （Bandai補完値を渡すと "ST16-004" vs "004" の false positive が発生する）
    if not validate_and_report(
        cert_number, title, tcg_specs, "", 183454, 2750, price, PIC_URL,
        psa_brand=brand, psa_card_number=data.get('CardNumber', '')
    ):
        return None

    return [
        "Add", 183454, title, PIC_URL, price, 2750,
        275010, 275020, cert_number,
        get_schedule_time(), custom_label, description,
        "FixedPrice", "GTC", 1, LOCATION, 1,
        shipping, RETURN_POLICY, PAYMENT_POLICY,
        game, set_name, card_type, card_name, character, card_number,
        # Country of Origin: "Does not apply" 固定（tshirt_listing_rules 準拠）。
        # 画像/公式DBで製造国を100%特定できない限り、eBay AI の勝手な Japan 補完を明示的に塞ぐ
        rarity, features, manufacturer, "Japanese", year, "Does not apply", franchise,
        "6+", "No", "No", "Card Stock", card_size, "No",
        finish, attribute, illustrator, cost, power, "",
        "Near Mint or Better", "10",
        "Professional Sports Authenticator (PSA)", "Yes",
        store_cat_id,
    ]

GSHEET_CREDS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..",
    "double-hold-421922-7c0d38d3f73d.json"
)
GSHEET_TCG_ID = "1RbGaiQxhYDd7s8nqT0jHeh7sQ6FJNCVnVxkEJLFmz9s"


def _append_to_spreadsheet(cert_numbers, url_map, title_map, skip_certs):
    """出品したカードのメルカリURL+タイトルをスプシに追記"""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        print("⚠️ gspread未インストール。スプシ追記スキップ。")
        return

    if not os.path.exists(GSHEET_CREDS_FILE):
        print("⚠️ Google認証ファイルなし。スプシ追記スキップ。")
        return

    # 出品されたカード（NO-GO除外・失敗除外）のみ
    items_to_add = []
    for cert in cert_numbers:
        if cert in skip_certs:
            continue
        url = url_map.get(cert, "")
        title = title_map.get(cert, "")
        if url:
            items_to_add.append((url, title))

    if not items_to_add:
        return

    try:
        creds = Credentials.from_service_account_file(
            GSHEET_CREDS_FILE,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(GSHEET_TCG_ID)
        ws = sh.sheet1

        # 最終行を取得
        all_values = ws.get_all_values()
        next_row = len(all_values) + 1

        for i, (url, title) in enumerate(items_to_add):
            row = next_row + i
            ws.update(values=[[url]], range_name=f"A{row}")
            if title:
                ws.update(values=[[title]], range_name=f"C{row}")

        print(f"📝 スプシ追記: {len(items_to_add)}件 (行{next_row}〜)")
    except Exception as e:
        print(f"⚠️ スプシ追記エラー: {e}")


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
        url     = (row[0]  if len(row) > 0  else '').strip()  # A
        item_id = (row[1]  if len(row) > 1  else '').strip()  # B (空=未処理)
        title   = (row[2]  if len(row) > 2  else '').strip()  # C
        price_f = (row[5]  if len(row) > 5  else '').strip()  # F "¥11,000"
        cert    = (row[8]  if len(row) > 8  else '').strip()  # I cert#
        cost_n  = (row[13] if len(row) > 13 else '').strip()  # N 仕入れ価格(円)

        if not cert or item_id or not url:
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


def main():
    print("=== iMak Trading Japan - PSA → eBay CSV Generator ===\n")

    # 2026-04-24: certs.txt 廃止、スプシ駆動に完全移行
    # スプシ (19kj8... gid=851100680) の I列=cert# / B列=itemID空 / A列=URL で処理対象を抽出
    print("📊 スプシから PSA 出品対象を抽出中...")
    cert_numbers, cost_map, mercari_url_map, mercari_title_map = load_targets_from_sheet_psa()

    if not cert_numbers:
        print("処理対象なし（スプシに I列=cert# ありの未処理行が見つかりません）")
        input("Enterで終了...")
        return

    print(f"✓ {len(cert_numbers)}件の PSA 対象行を抽出（B列 itemID 空）")

    if cost_map:
        print(f"{len(cert_numbers)}件を処理します。（仕入値あり: {len(cost_map)}件）\n")
    else:
        print(f"{len(cert_numbers)}件を処理します。\n")

    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    driver = uc.Chrome(options=options, version_main=146)

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
        "C:Card Condition", "C:Grade", "C:Professional Grader", "C:Graded", "StoreCategoryID",
    ]

    rows = [headers]
    errors = []
    # PSAデータ取得 → build_row（価格はデフォルト$100で仮生成）
    card_info = []  # (cert, data) を保持して後で価格更新
    for cert in cert_numbers:
        print(f"取得中: #{cert}...", end="", flush=True)
        data = get_psa_data(driver, cert)

        if data:
            subject = data.get('Subject', 'Unknown')
            card_number = data.get('CardNumber', '')
            print(f" → #{card_number} {subject} ✓")
            # SKU にメルカリ item ID を使うため、URL を data に注入（tshirt_listing_rules 準拠）
            data['_mercari_url'] = mercari_url_map.get(cert, '')
            row = build_row(cert, DEFAULT_PRICE, data, description, driver=driver)
            if row is None:
                # selfcheck弾かれ → rows/card_info の後段ループで None参照クラッシュを防ぐためスキップ
                print(f"    ⚠️ Skipping #{cert}: selfcheck failed in build_row")
                errors.append(cert)
                card_info.append((cert, None))
                continue
            rows.append(row)
            card_info.append((cert, data))
        else:
            print(f" → 失敗")
            errors.append(cert)
            card_info.append((cert, None))

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

    # 価格帯別パラメータ（GATE判定パラメータ検討.xlsx確定値）
    # (中央値上限, 目標利益率, 許容乖離率)
    TIER_PARAMS = [
        (39,   0.25, 0.50),   # $0-39:   利益25%, 乖離50%まで
        (60,   0.25, 0.50),   # $40-60:  利益25%, 乖離50%まで
        (100,  0.20, 0.50),   # $60-100: 利益20%, 乖離50%まで
        (200,  0.15, 0.50),   # $100-200:利益15%, 乖離50%まで
        (300,  0.10, 0.40),   # $200-300:利益10%, 乖離40%まで
        (400,  0.10, 0.25),   # $300-400:利益10%, 乖離25%まで
        (500,  0.10, 0.20),   # $400-500:利益10%, 乖離20%まで
        (600,  0.10, 0.15),   # $500-600:利益10%, 乖離15%まで
        (800,  0.10, 0.10),   # $600-800:利益10%, 乖離10%まで
        (9999, 0.10, 0.10),   # $800+:   利益10%, 乖離10%まで
    ]

    def get_tier_params(median_usd):
        for threshold, profit_target, gap_limit in TIER_PARAMS:
            if median_usd <= threshold:
                return profit_target, gap_limit
        return 0.10, 0.10  # fallback

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
            cost_jpy = cost_map.get(cert)

            market = search_market_price(ebay_token, game, card_number_full, character)
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

            # 乖離率計算（仕入値がある場合）— 価格帯別パラメータ適用
            if cost_jpy is not None:
                tier_profit, tier_gap_limit = get_tier_params(all_median)
                costs_jpy = cost_jpy + SHIPPING_JPY
                target_usd = costs_jpy / (EXCHANGE_RATE * (NET_RATIO - tier_profit))
                breakeven_usd = costs_jpy / (EXCHANGE_RATE * NET_RATIO)
                gap_pct = (target_usd - all_median) / all_median * 100 if all_median > 0 else 999
                gap_limit_pct = tier_gap_limit * 100

                if gap_pct <= 0:
                    # GO: 市場が目標を上回る → 中央値×95%で出品
                    price = round(all_median * 0.95, 2)
                    price = int(price) + 0.98 if price > 10 else price
                    gate_label = "GO"
                    gate = f"✅ GO ${price} (利益{tier_profit:.0%}内)"
                elif gap_pct <= gap_limit_pct:
                    # 保留: 許容乖離内 → 目標価格で出品して待つ
                    price = round(target_usd, 2)
                    price = int(price) + 0.98 if price > 10 else price
                    gate_label = "保留"
                    gate = f"🟡 保留 (乖離{gap_pct:.0f}%/許容{gap_limit_pct:.0f}% → ${price}で出品)"
                else:
                    # NO-GO: 許容乖離超過 → CSV除外
                    nogo_price = round(target_usd, 2)
                    nogo_price = int(nogo_price) + 0.98 if nogo_price > 10 else nogo_price
                    price = None
                    gate_label = "NO-GO"
                    diff = nogo_price - all_median
                    gate = f"❌ NO-GO ${nogo_price} +${diff:.0f} 乖離{gap_pct:.0f}% > 許容{gap_limit_pct:.0f}% → CSV除外"
                    skip_certs.add(cert)

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

    # 仕入値データをサイドカーJSONとして保存（check_csv.pyが参照）
    if cost_map:
        cost_file = output_file.replace(".csv", "_cost.json")
        with open(cost_file, "w", encoding="utf-8") as f:
            json.dump(cost_map, f, ensure_ascii=False, indent=2)
        print(f"仕入値データ: {cost_file}")

    print(f"\n完了！出力: {output_file}")
    print(f"成功: {len(rows)-1}件 / 失敗: {len(errors)}件")
    if errors:
        print(f"失敗: {', '.join(errors)}")

    # スプシに自動追記（メルカリURL + タイトル）
    if mercari_url_map:
        _append_to_spreadsheet(cert_numbers, mercari_url_map, mercari_title_map, skip_certs)

    # CSVチェッカー自動実行
    if len(rows) > 1:
        print(f"\n{'═'*60}")
        print("  CSVチェックを開始します...")
        print(f"{'═'*60}\n")
        try:
            subprocess.run(
                [sys.executable, "check_csv.py", output_file],
                cwd=os.path.dirname(os.path.abspath(__file__)),
            )
        except Exception as e:
            print(f"⚠️ チェッカー実行エラー: {e}")

    input("\nEnterで終了...")

if __name__ == "__main__":
    main()
