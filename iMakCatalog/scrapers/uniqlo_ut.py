"""Uniqlo UT (グラフィック T シャツ) catalog scraper.

設計背景 (2026-05-05):
  Uniqlo UT は collab IP (アニメ/漫画/ブランド) の限定 T シャツが主力.
  HQ の tshirt_listing.py が AI で毎回タイトル翻訳 → 不安定.
  catalog 側で公式 API から structured data を事前取得し、HQ は lookup() で
  確定値 (商品名 / colors / sizes / 価格 / 画像) を取るだけにする.

データソース:
  Uniqlo Commerce API (公式・公開):
    https://www.uniqlo.com/jp/api/commerce/v5/ja/products?q=UT&limit=N&offset=N
  Selenium 不要、Akamai 関係なし、JSON で structured data.
  欠点: 廃盤は API から消滅 → 過去発掘は別経路 (eBay 履歴 / Wayback) 要.

実行:
  python iMakCatalog/scrapers/uniqlo_ut.py --update             # active 全件 (332+ 件)
  python iMakCatalog/scrapers/uniqlo_ut.py --discover            # active 件数のみ確認
  python iMakCatalog/scrapers/uniqlo_ut.py --lookup 485482       # l1Id 個別 fetch (廃盤救済)
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Optional

# sys.path: iMakCatalog/api を見せる
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CATALOG_ROOT = Path(__file__).resolve().parent.parent
for p in (_CATALOG_ROOT,):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

CATEGORY = "uniqlo_ut"
SOURCE = "uniqlo_official_api"

UNIQLO_API_BASE = "https://www.uniqlo.com/jp/api/commerce/v5/ja/products"
UNIQLO_API_LOOKUP = "https://www.uniqlo.com/jp/api/commerce/v5/ja/products/{l1id}"
UNIQLO_PRODUCT_URL = "https://www.uniqlo.com/jp/ja/products/E{l1id}-000/00"

# ============================================================================
# eBay フィルタ正規値 mapping (tshirt_ebay_filter_items.txt 由来)
# ============================================================================

# Uniqlo filterCode → eBay 16色 enum
_COLOR_FILTER_MAP = {
    "WHITE":      "White",
    "BLACK":      "Black",
    "RED":        "Red",
    "BLUE":       "Blue",
    "NAVY":       "Blue",
    "GREEN":      "Green",
    "OLIVE":      "Green",
    "YELLOW":     "Yellow",
    "ORANGE":     "Orange",
    "PINK":       "Pink",
    "PURPLE":     "Purple",
    "BROWN":      "Brown",
    "GRAY":       "Gray",
    "GREY":       "Gray",
    "BEIGE":      "Beige",
    "SILVER":     "Silver",
    "GOLD":       "Gold",
    "IVORY":      "Ivory",
    "MULTICOLOR": "Multicolor",
}

# size 正規化 (Uniqlo "XXL" / "XXXL" → eBay "2XL" / "3XL")
_SIZE_NORMALIZE = {
    "XXL":  "2XL",
    "XXXL": "3XL",
    "XXXXL":"4XL",
}

# 商品名 / 日本語キーワード → eBay Theme (multi: カンマ区切りリストとして格納)
# tshirt_ebay_filter_items.txt 由来 18 値
_THEME_KEYWORDS = [
    # IP / collab keyword → theme
    (["アニメ", "ANIME", "マンガ", "MANGA", "少年ジャンプ", "週刊少年", "Shueisha"], "Anime"),
    (["ポケモン", "POKEMON", "Pokémon"], "Anime"),
    (["ドラゴンボール", "DRAGON BALL", "DRAGONBALL"], "Anime"),
    (["ワンピース", "ONE PIECE"], "Anime"),
    (["ナルト", "NARUTO", "BORUTO"], "Anime"),
    (["呪術廻戦", "JUJUTSU", "Kaisen"], "Anime"),
    (["鬼滅", "DEMON SLAYER"], "Anime"),
    (["ハンターハンター", "HUNTER", "HxH"], "Anime"),
    (["進撃", "ATTACK ON TITAN"], "Anime"),
    (["BLEACH", "ブリーチ"], "Anime"),
    (["BERSERK", "ベルセルク"], "Anime"),
    (["攻殻機動隊", "GHOST IN THE SHELL"], "Anime"),
    (["DANDADAN", "ダンダダン"], "Anime"),
    (["カイジュウ", "怪獣 8", "KAIJU"], "Anime"),
    (["ファイナルファンタジー", "FINAL FANTASY"], "Video Games"),
    (["ドラゴンクエスト", "ドラクエ", "DRAGON QUEST"], "Video Games"),
    (["マリオ", "MARIO"], "Video Games"),
    (["ゼルダ", "ZELDA"], "Video Games"),
    (["ストリートファイター", "STREET FIGHTER"], "Video Games"),
    (["MINECRAFT", "マインクラフト"], "Video Games"),
    (["ディズニー", "DISNEY", "MICKEY", "MINNIE", "DONALD"], "Cartoon"),
    (["スヌーピー", "SNOOPY", "PEANUTS", "ピーナッツ"], "Cartoon"),
    (["セサミ", "SESAME"], "Cartoon"),
    (["ミッフィー", "MIFFY"], "Cartoon"),
    (["サンリオ", "SANRIO", "HELLO KITTY", "ハローキティ"], "Cartoon"),
    (["mofusand", "もふさんど"], "Cartoon"),
    (["モンチッチ", "MONCHHICHI"], "Cartoon"),
    (["POP MART", "POPMART", "ポップマート"], "Cartoon"),
    (["ちいかわ", "CHIIKAWA"], "Cartoon"),
    (["マーベル", "MARVEL", "SPIDER", "X-MEN", "AVENGERS"], "Comics"),
    (["DC", "BATMAN", "SUPERMAN"], "Comics"),
    (["スター・ウォーズ", "スターウォーズ", "STAR WARS"], "Movie"),
    (["JURASSIC", "ジュラシック"], "Movie"),
    (["ハリー・ポッター", "ハリーポッター", "HARRY POTTER"], "Movie"),
    (["KAWS", "BANKSY", "ANDY WARHOL", "ウォーホル"], "Retro"),
    (["バスキア", "BASQUIAT", "Jean-Michel"], "Retro"),
    (["ジェイソン・ポラン", "Jason Polan", "ジェイソンポラン"], "Retro"),
    (["長場雄", "Yu Nagaba"], "Retro"),
    (["浮世絵", "UKIYO-E", "UKIYOE", "Hokusai", "北斎"], "Retro"),
    (["テート美術館", "TATE"], "Retro"),
    (["ボストン美術館", "Boston Museum", "MFA"], "Retro"),
    (["ルーヴル", "ルーブル", "LOUVRE"], "Retro"),
    (["MOMA", "メトロポリタン", "MET MUSEUM"], "Retro"),
    (["美術館", "MUSEUM"], "Retro"),
    (["エリオット・アーウィット", "Erwitt"], "Retro"),
    (["MUSIC", "ロック", "ROCK", "BAND", "METAL"], "Music"),
    (["BABYMONSTER", "BTS", "TWICE", "K-POP", "K POP", "ITZY", "BLACKPINK", "NewJeans"], "Music"),
    (["FUNNY", "JOKE", "QUOTE"], "Funny"),
    (["NATURE", "FLORAL", "BOTANICAL"], "Nature"),
    (["SPORT", "SPORTS", "サッカー", "FOOTBALL", "BASEBALL"], "Sports"),
    (["SPACE", "GALAXY", "宇宙"], "Space"),
    # MAGIC FOR ALL — UT 主力ライン (UNIQLO オリジナル graphic、特定 IP 無し → "Funny" or generic)
    (["MAGIC FOR ALL", "MAGIC FOR ALL ICONS", "マジック フォー オール"], "Funny"),
    (["ミッキー", "MICKEY", "ピクサー", "PIXAR"], "Cartoon"),
    (["パワパフ", "POWERPUFF"], "Cartoon"),
    (["ケアベア", "CARE BEARS"], "Cartoon"),
    (["はらぺこあおむし", "HUNGRY CATERPILLAR"], "Cartoon"),
    (["パンどろぼう", "せな けいこ", "レオ・レオニ", "LEO LIONNI", "絵本"], "Cartoon"),
    (["たまごっち", "TAMAGOTCHI"], "Video Games"),
    (["キース・ヘリング", "キース・へリング", "KEITH HARING"], "Retro"),
    (["和柄", "和風", "JAPANESE PATTERN"], "Retro"),
    (["ミュージカル", "MUSICAL"], "Music"),
    (["TOYOTA", "トヨタ"], "Cars"),
    (["ザ・ブランズ", "THE BRANDS"], "Retro"),
    (["チアフル", "CHEERFUL CHARACTERS"], "Cartoon"),
]

# 商品名 → Character Family (シリーズ名) と Character (個別キャラ)
# 主要 IP のみ (高頻度 collab). 不明なら空.
_CHARACTER_FAMILY_MAP = [
    (r"ポケモン|POKEMON|Pokémon",         "Pokemon"),
    (r"ドラゴンボール|DRAGON\s*BALL",     "Dragon Ball"),
    (r"ワンピース|ONE\s*PIECE",           "One Piece"),
    (r"ナルト|NARUTO",                    "Naruto"),
    (r"呪術廻戦|JUJUTSU\s*KAISEN",        "Jujutsu Kaisen"),
    (r"鬼滅|DEMON\s*SLAYER",              "Demon Slayer"),
    (r"ハンター[×x・]\s*ハンター|HUNTER\s*[×x]\s*HUNTER", "Hunter x Hunter"),
    (r"進撃|ATTACK\s*ON\s*TITAN",         "Attack on Titan"),
    (r"BLEACH|ブリーチ",                  "Bleach"),
    (r"BERSERK|ベルセルク",               "Berserk"),
    (r"攻殻機動隊|GHOST\s*IN\s*THE\s*SHELL", "Ghost in the Shell"),
    (r"ファイナルファンタジー|FINAL\s*FANTASY", "Final Fantasy"),
    (r"ドラゴンクエスト|ドラクエ|DRAGON\s*QUEST", "Dragon Quest"),
    (r"スーパーマリオ|SUPER\s*MARIO|マリオ\s*ブラザーズ", "Super Mario"),
    (r"ゼルダ|ZELDA",                     "Zelda"),
    (r"ストリートファイター|STREET\s*FIGHTER", "Street Fighter"),
    (r"MINECRAFT|マインクラフト",         "Minecraft"),
    (r"ディズニー|DISNEY",                "Disney"),
    (r"スヌーピー|SNOOPY|PEANUTS|ピーナッツ", "Peanuts"),
    (r"セサミ|SESAME",                    "Sesame Street"),
    (r"ミッフィー|MIFFY",                 "Miffy"),
    (r"サンリオ|SANRIO|ハローキティ|HELLO\s*KITTY", "Sanrio"),
    (r"mofusand|もふさんど|モフサンド",   "Mofusand"),
    (r"モンチッチ|MONCHHICHI",            "Monchhichi"),
    (r"POP\s*MART|POPMART|ポップマート",  "Pop Mart"),
    (r"ちいかわ|CHIIKAWA",                "Chiikawa"),
    (r"マーベル|MARVEL",                  "Marvel"),
    (r"スパイダーマン|SPIDER[\s-]*MAN",   "Marvel"),
    (r"X[\s-]*MEN|エックスメン",          "Marvel"),
    (r"AVENGERS|アベンジャーズ",          "Marvel"),
    (r"BATMAN|バットマン",                "DC Comics"),
    (r"SUPERMAN|スーパーマン",            "DC Comics"),
    (r"スター[\s・]*ウォーズ|STAR\s*WARS","Star Wars"),
    (r"JURASSIC|ジュラシック",            "Jurassic Park"),
    (r"ハリー[\s・]*ポッター|HARRY\s*POTTER", "Harry Potter"),
    (r"KAWS",                             "KAWS"),
    (r"BANKSY",                           "Banksy"),
    (r"ANDY\s*WARHOL|ウォーホル",         "Andy Warhol"),
    (r"バスキア|BASQUIAT|Jean-Michel",    "Jean-Michel Basquiat"),
    (r"ジェイソン[\s・]*ポラン|Jason\s*Polan", "Jason Polan"),
    (r"長場雄|Yu\s*Nagaba",               "Yu Nagaba"),
    (r"エリオット[\s・]*アーウィット|Elliott\s*Erwitt", "Elliott Erwitt"),
    (r"浮世絵|UKIYO-?E|北斎|HOKUSAI",     "Ukiyo-e"),
    (r"テート美術館|TATE",                "Tate"),
    (r"ボストン美術館|Boston\s*Museum",   "Boston Museum of Fine Arts"),
    (r"ルーヴル|ルーブル|LOUVRE",         "Louvre"),
    (r"MOMA|MoMA",                        "MoMA"),
    (r"メトロポリタン|MET\s*MUSEUM",      "Metropolitan Museum"),
    (r"BABYMONSTER",                      "BABYMONSTER"),
    (r"BLACKPINK",                        "BLACKPINK"),
    (r"BTS|防弾少年団",                   "BTS"),
    (r"NewJeans",                         "NewJeans"),
    (r"カイジュウ|怪獣\s*8|KAIJU\s*NO",   "Kaiju No. 8"),
    (r"DANDADAN|ダンダダン",              "Dandadan"),
    (r"MAGIC\s*FOR\s*ALL|マジック\s*フォー\s*オール", "Magic for All"),
    (r"ミッキー|MICKEY|ピクサー|PIXAR",   "Disney"),
    (r"パワパフ|POWERPUFF",               "Powerpuff Girls"),
    (r"ケアベア|CARE\s*BEARS",            "Care Bears"),
    (r"はらぺこあおむし|HUNGRY\s*CATERPILLAR", "The Very Hungry Caterpillar"),
    (r"パンどろぼう",                     "Pan-dorobou"),
    (r"せな\s*けいこ",                    "Keiko Sena"),
    (r"レオ[\s・]*レオニ|LEO\s*LIONNI",   "Leo Lionni"),
    (r"絵本コレクション",                 "Picture Book Collection"),
    (r"たまごっち|TAMAGOTCHI",            "Tamagotchi"),
    (r"キース[\s・]*[ヘへ]リング|KEITH\s*HARING", "Keith Haring"),
    (r"和柄|和風",                        "Japanese Traditional Pattern"),
    (r"ミュージカル|MUSICAL",             "Musical Icons"),
    (r"TOYOTA|トヨタ",                    "Toyota"),
    (r"ザ[\s・]*ブランズ|THE\s*BRANDS",   "The Brands"),
    (r"チアフル|CHEERFUL\s*CHARACTERS",   "Cheerful Characters"),
]

# Character (個別キャラ) — 高頻度のみ
_CHARACTER_MAP = [
    (r"ピカチュウ|PIKACHU",       "Pikachu"),
    (r"イーブイ|EEVEE",           "Eevee"),
    (r"ゲンガー|GENGAR",          "Gengar"),
    (r"ミュウツー|MEWTWO",        "Mewtwo"),
    (r"悟空|GOKU",                "Goku"),
    (r"ベジータ|VEGETA",          "Vegeta"),
    (r"クリリン|KRILLIN",         "Krillin"),
    (r"ピッコロ|PICCOLO",         "Piccolo"),
    (r"ルフィ|LUFFY",             "Luffy"),
    (r"ゾロ|ZORO",                "Zoro"),
    (r"ナミ|NAMI",                "Nami"),
    (r"サンジ|SANJI",             "Sanji"),
    (r"エース|ACE",               "Ace"),
    (r"ナルト|NARUTO",            "Naruto"),
    (r"サスケ|SASUKE",            "Sasuke"),
    (r"カカシ|KAKASHI",           "Kakashi"),
    (r"ミッキー|MICKEY",          "Mickey Mouse"),
    (r"ミニー|MINNIE",            "Minnie Mouse"),
    (r"ドナルド|DONALD",          "Donald Duck"),
    (r"スパイダーマン|SPIDER[\s-]*MAN", "Spider-Man"),
    (r"バットマン|BATMAN",        "Batman"),
    (r"スーパーマン|SUPERMAN",    "Superman"),
    (r"マリオ|MARIO",             "Mario"),
    (r"ルイージ|LUIGI",           "Luigi"),
    (r"スヌーピー|SNOOPY",        "Snoopy"),
    (r"ウッドストック|WOODSTOCK", "Woodstock"),
]


def _normalize_color_filter(filter_code: str) -> str:
    """Uniqlo filterCode → eBay 16色 enum. 不明なら 'Multicolor'."""
    if not filter_code:
        return "Multicolor"
    return _COLOR_FILTER_MAP.get(filter_code.upper(), "Multicolor")


def _normalize_size(size_name: str) -> str:
    """size XXL → 2XL 等の eBay 正規化."""
    if not size_name:
        return ""
    return _SIZE_NORMALIZE.get(size_name.upper(), size_name.upper())


def _derive_themes(name: str) -> list:
    """商品名から eBay Theme list (multi=True) を推定."""
    if not name:
        return []
    n = name.upper()
    themes: list = []
    for keywords, theme in _THEME_KEYWORDS:
        if any(kw.upper() in n for kw in keywords):
            if theme not in themes:
                themes.append(theme)
    return themes


def _derive_character_family(name: str) -> str:
    """商品名から Character Family (シリーズ名) を推定."""
    if not name:
        return ""
    for pattern, family in _CHARACTER_FAMILY_MAP:
        if re.search(pattern, name, re.IGNORECASE):
            return family
    return ""


def _derive_character(name: str) -> str:
    """商品名から個別 Character 名を推定. 複数該当なら最初のみ."""
    if not name:
        return ""
    for pattern, char in _CHARACTER_MAP:
        if re.search(pattern, name, re.IGNORECASE):
            return char
    return ""


# ============================================================================
# API call helpers
# ============================================================================
def _api_search(query: str = "UT", limit: int = 100, offset: int = 0) -> dict:
    """Commerce API 検索 endpoint. UT 全 active を取得するための主経路."""
    import requests  # type: ignore
    params = {"q": query, "limit": limit, "offset": offset}
    r = requests.get(
        UNIQLO_API_BASE,
        params=params,
        headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ja-JP"},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def _api_lookup_by_l1id(l1id: str) -> Optional[dict]:
    """個別 l1Id で API lookup (廃盤救済用、active 残ってれば取れる)."""
    import requests  # type: ignore
    url = UNIQLO_API_LOOKUP.format(l1id=l1id)
    try:
        r = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ja-JP"},
            timeout=15,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        if data.get("status") == "ok":
            return data.get("result")
        return None
    except Exception:
        return None


# ============================================================================
# API response → catalog dict 整形
# ============================================================================
def _parse_item(item: dict) -> dict:
    """API search の 1 item を catalog upsert 形式に整形.

    重要 field:
      productId: 'E485482-000' (catalog product_id)
      l1Id:      '485482'      (商品コード 6 桁)
      name:      "マジック フォー オール アイコンズ UT/リラックスフィット"
      genderName: 'MEN' / 'WOMEN' / 'BOYS' / etc.
      colors:    [{code, displayCode, name, filterCode}]
      sizes:     [{code, displayCode, name}]
      prices:    {base: {value: 1490, currency: {code, symbol}}, promo: {...}}
      images:    {main: {01: {image: URL, model: [...]}}, chip: {...}}
      promotionText: プロモテキスト
    """
    pid = (item.get("productId") or "").strip()
    l1id = str(item.get("l1Id") or "").strip()
    if not pid:
        return {}

    name_jp = (item.get("name") or "").strip()
    gender = (item.get("genderName") or "").strip()  # MEN/WOMEN/BOYS/GIRLS/BABY

    # colors: 各 color の name + filter + eBay 正規化
    color_variants = []
    color_ebay_set: list = []
    for c in (item.get("colors") or []):
        ebay = _normalize_color_filter(c.get("filterCode") or "")
        color_variants.append({
            "code": c.get("code"),
            "displayCode": c.get("displayCode"),
            "name": c.get("name"),                 # 英語 (例: "OFF WHITE")
            "filter": c.get("filterCode"),         # eBay フィルタ raw ('WHITE' 等)
            "ebay_color": ebay,                    # eBay 16色 enum
        })
        if ebay not in color_ebay_set:
            color_ebay_set.append(ebay)

    # sizes: list of "S"/"M"/"L"/"XL"/etc. + eBay 正規化 (XXL → 2XL)
    size_variants = []
    size_ebay_set: list = []
    for s in (item.get("sizes") or []):
        raw = s.get("name") or ""
        norm = _normalize_size(raw)
        size_variants.append({
            "code": s.get("code"),
            "name": raw,
            "ebay_size": norm,
        })
        if norm and norm not in size_ebay_set:
            size_ebay_set.append(norm)

    # prices: 税込価格
    prices = item.get("prices") or {}
    base_price = (((prices.get("base") or {}).get("value")) or "")
    promo_price = (((prices.get("promo") or {}).get("value")) or "")

    # images: main の 01 (基本色) を採用
    image_urls = []
    main_imgs = ((item.get("images") or {}).get("main") or {})
    for color_code in sorted(main_imgs.keys()):
        img = main_imgs[color_code]
        if isinstance(img, dict):
            url = img.get("image") or ""
            if url and url not in image_urls:
                image_urls.append(url)

    # collab/IP 推定: 商品名から抽出 (UT は collab name が name に入る)
    collab = _extract_collab_from_name(name_jp)

    # eBay フィルタ項目 (tshirt_ebay_filter_items.txt 由来 15 項目)
    themes = _derive_themes(name_jp)
    character_family = _derive_character_family(name_jp)
    character = _derive_character(name_jp)

    return {
        "product_id": pid,
        "name_jp": name_jp,
        "name": name_jp,                # name_en は別途翻訳パイプで設定
        "specs": {
            # === Uniqlo API 由来 ===
            "l1_id":               l1id,
            "gender":              gender,
            "collab":              collab,           # 推定 (例: "Pokemon", "Naruto")
            "color_variants":      color_variants,
            "size_variants":       size_variants,
            "image_urls":          image_urls,
            "price_jpy_base":      base_price,
            "price_jpy_promo":     promo_price,
            "promotion_text":      (item.get("promotionText") or ""),
            "rating":              ((item.get("rating") or {}).get("average")),

            # === eBay Item Specifics 固定値 ===
            "brand":               "Uniqlo",
            "type":                "T-Shirt",
            "size_type":           "Regular",
            "closure":             "Pullover",
            "neckline":            "Crew Neck",
            "sleeve_length":       "Short Sleeve",
            "fit":                 "Regular",
            "vintage":             "No",
            "personalize":         "No",
            "handmade":            "No",
            "style":               "Graphic Tee",        # UT 大半
            "pattern":             "Graphic Print",      # UT 大半
            "country_of_origin":   "Does not apply",     # 不明 default (eBay AI 補完防止)

            # === eBay Item Specifics 商品ごと変動 ===
            "department":          _gender_to_dept(gender),
            "ebay_colors":         color_ebay_set,       # 16色 enum list (multi)
            "ebay_sizes":          size_ebay_set,        # XS-2XL list (multi)
            "themes":              themes,               # 18 値から multi
            "character_family":    character_family,
            "character":           character,
            "material":            "",                   # 公式 API には無し、Vision で取得 path
            "year_manufactured":   "",                   # vintage の場合のみ後で setting

            # === 内部参照用 ===
            "category_line":       "UT",

            # === Phase 2 拡張枠 (現状 null) ===
            "ebay_search_volume":     None,
            "ebay_median_price_usd":  None,
            "ebay_sell_through_rate": None,
        },
        "images": image_urls,
    }


def _extract_collab_from_name(name_jp: str) -> str:
    """商品名から collab / IP 名を推定. 厳密マッチではなく、典型パターンのみ."""
    if not name_jp:
        return ""
    # 典型パターン: "<COLLAB> UT/<fit>" もしくは "<COLLAB> UT グラフィック T..."
    m = re.match(r"^(.+?)\s*UT(?:[/／]|\s*グラフィック|\s*$)", name_jp)
    if m:
        return m.group(1).strip()
    return ""


def _gender_to_dept(gender: str) -> str:
    """API genderName → eBay department 文字列."""
    g = (gender or "").upper()
    return {
        "MEN":   "Men",
        "WOMEN": "Women",
        "BOYS":  "Boys",
        "GIRLS": "Girls",
        "BABY":  "Baby",
        "KIDS":  "Unisex Kids",
    }.get(g, "Unisex Adults")


# ============================================================================
# 公開 API
# ============================================================================
def fetch_all_active(query: str = "UT", page_size: int = 100) -> list:
    """Commerce API 検索 endpoint で active UT 全件を pagination で取得.

    Returns:
        list of raw item dicts.
    """
    items: list = []
    offset = 0
    total = None
    while True:
        data = _api_search(query=query, limit=page_size, offset=offset)
        result = data.get("result") or {}
        page_items = result.get("items") or []
        items.extend(page_items)
        pagination = result.get("pagination") or {}
        if total is None:
            total = int(pagination.get("total", 0))
            print(f"  total: {total} items")
        offset += len(page_items)
        if not page_items or offset >= total:
            break
        time.sleep(0.5)
    return items


def update_all_active() -> dict:
    """Active UT 全件 catalog upsert.

    Returns:
        {"fetched": int, "upserted": int, "errors": list}
    """
    import api  # type: ignore
    print("=== Uniqlo UT active 全件 fetch ===")
    raw_items = fetch_all_active()
    print(f"  fetched {len(raw_items)} raw items")
    upserted = 0
    errors: list = []
    for item in raw_items:
        try:
            parsed = _parse_item(item)
            if not parsed.get("product_id"):
                continue
            api.upsert(
                category=CATEGORY,
                product_id=parsed["product_id"],
                name=parsed["name"],
                name_jp=parsed["name_jp"],
                specs=parsed["specs"],
                images=parsed["images"],
                source=SOURCE,
                source_url=UNIQLO_PRODUCT_URL.format(l1id=parsed["specs"]["l1_id"]),
            )
            upserted += 1
        except Exception as e:
            errors.append({"product_id": item.get("productId"),
                           "error": f"{type(e).__name__}: {e}"})
    print(f"  upserted: {upserted}/{len(raw_items)}, errors: {len(errors)}")
    return {"fetched": len(raw_items), "upserted": upserted, "errors": errors}


def sweep_historical(l1id_start: int, l1id_end: int,
                      step: int = 1, pacing: float = 0.4) -> dict:
    """l1Id 連番 sweep で 過去 UT 廃盤救済.

    Active 範囲外でも個別 lookup endpoint には残存することがある
    (Active 332 件以外に検索 index 抜け 廃盤 UT が稀に残る).

    Args:
        l1id_start, l1id_end: スキャン範囲 (両端含む).
        step: スキャン step (1 = 全件、5 = 5 件ごと等).
        pacing: 各 API call 間隔 (rate limit 緩和).

    Returns:
        {"scanned": int, "api_hits": int, "ut_upserted": int}
    """
    import api  # type: ignore
    print(f"=== sweep {l1id_start} - {l1id_end} (step={step}, pacing={pacing}s) ===")
    scanned = 0
    api_hits = 0
    ut_upserted = 0
    progress_interval = max(50, (l1id_end - l1id_start) // step // 50)

    for l1id in range(l1id_start, l1id_end + 1, step):
        scanned += 1
        result = _api_lookup_by_l1id(str(l1id))
        if result:
            api_hits += 1
            name = result.get("name") or ""
            # UT product のみ upsert (name に 'UT' 含む)
            if "UT" in name.upper():
                # 既存 catalog にあれば skip
                pid = f"E{l1id}-000"
                existing = api.lookup(CATEGORY, pid)
                if not existing:
                    item_like = {
                        "productId": pid,
                        "l1Id": str(l1id),
                        "name": name,
                        "genderName": result.get("genderName") or "",
                        "colors": result.get("colors") or [],
                        "sizes": result.get("sizes") or [],
                        "prices": result.get("prices") or {},
                        "images": result.get("images") or {},
                        "promotionText": result.get("promotionText") or "",
                        "rating": result.get("rating") or {},
                    }
                    parsed = _parse_item(item_like)
                    if parsed.get("product_id"):
                        api.upsert(
                            category=CATEGORY,
                            product_id=parsed["product_id"],
                            name=parsed["name"],
                            name_jp=parsed["name_jp"],
                            specs=parsed["specs"],
                            images=parsed["images"],
                            source="uniqlo_official_api_sweep",
                            source_url=UNIQLO_PRODUCT_URL.format(l1id=l1id),
                        )
                        ut_upserted += 1
                        print(f"  +{ut_upserted}: {l1id} {name[:60]}")
        if scanned % progress_interval == 0:
            print(f"  [{scanned}/{(l1id_end - l1id_start) // step + 1}] api_hits={api_hits} ut={ut_upserted}")
        time.sleep(pacing)

    print(f"\n=== sweep 完了 ===")
    print(f"  scanned: {scanned}")
    print(f"  api hits (any product): {api_hits}")
    print(f"  UT upserted: {ut_upserted}")
    return {"scanned": scanned, "api_hits": api_hits, "ut_upserted": ut_upserted}


def _DELETED_import_historical_from_ebay_csvs() -> dict:
    """[DELETED 2026-05-05] eBay 出品 title から過去 UT を catalog 化する関数.

    catalog 原則違反のため削除:
    - 合成 product_id (HIST-<hash>) は公式 l1Id でない → ID-strict 違反
    - eBay seller 記述 title からの parse → 推測ベース (非公式値)
    - source='ebay_listing_history' を catalog に混在させると
      "公式 source of truth" の役割が壊れる

    過去 UT 情報を持ちたい場合は catalog 外 (iMakHQ sold history 等) で
    metadata 層として管理する. 本関数は呼び出されると例外を上げる.
    """
    raise RuntimeError(
        "import_historical_from_ebay_csvs は catalog 原則違反のため削除済 "
        "(2026-05-05). 過去 UT 情報は catalog 外で管理する."
    )
    import csv as _csv
    import glob
    import hashlib
    import api  # type: ignore
    try:
        import openpyxl  # type: ignore
    except ImportError:
        openpyxl = None

    # === 収集 ===
    titles: list = []
    # 1. sold xlsx
    if openpyxl:
        sold_files = glob.glob(
            "C:/dev/iMak/iMakeBayAPI/sold_data/UNIQLO UT_sold_*.xlsx"
        )
        for fp in sold_files:
            try:
                wb = openpyxl.load_workbook(fp, read_only=True)
                ws = wb.active
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i == 0:
                        continue
                    if row and len(row) > 1 and row[1]:
                        titles.append(str(row[1]))
                wb.close()
            except Exception:
                pass
    # 2. listing csvs
    listing_files = sorted(
        glob.glob("C:/dev/iMak/iMakHQ/csv_output/tshirt_upload_*.csv") +
        glob.glob("C:/dev/iMak/iMakMercari/ebay_tshirt_*.csv")
    )
    for fp in listing_files:
        try:
            with open(fp, encoding="utf-8") as f:
                for r in _csv.DictReader(f):
                    t = r.get("*Title") or r.get("Title") or ""
                    if t and ("UT" in t.upper() or "UNIQLO" in t.upper()):
                        titles.append(t)
        except Exception:
            pass

    unique_titles = sorted(set(titles))
    print(f"=== historical UT titles: {len(unique_titles)} unique (raw {len(titles)}) ===")

    # === Title parser ===
    def parse_title(t: str) -> dict:
        """eBay Title から catalog field を抽出.

        Pattern 例:
          "UNIQLO UT Pokemon Gardevoir T-Shirt White US L (JP XL) NWT Japan"
          "Jujutsu Kaisen UNIQLO Manga UT T-Shirts Shueisha 100th Japan WHITE Pre Mid April"
        """
        # 商品 core 抽出: prefix 'UNIQLO ' / 'UT ' を剥がし、suffix " US X (JP Y) ..." を切る
        core = t
        # remove suffix: ' US <size> (JP <size>)' から末尾まで
        m = re.search(r"\s+(?:Size\s+)?US\s+\d?[A-Z]+\s*\(JP\s+\d?[A-Z]+\)", core)
        if m:
            core = core[: m.start()]
        # remove suffix: ' NWT', ' Pre-owned', ' NEW', ' JAPAN', ' Japan'
        for suf in [r"\s+(?:NWT|Pre-owned|Brand new|Pre owned)\s*Japan?$",
                    r"\s+Pre Mid.*$", r"\s+Japan$", r"\s+JAPAN.*$"]:
            core = re.sub(suf, "", core, flags=re.IGNORECASE).strip()
        # color 抽出 (末尾に Color or 末尾語が color)
        color = ""
        color_re = (r"\b(Black|White|Red|Blue|Green|Yellow|Orange|Pink|"
                    r"Purple|Brown|Gray|Grey|Beige|Silver|Gold|Ivory|Navy|"
                    r"Olive|Multicolor)\b")
        cm = re.search(color_re, core, re.IGNORECASE)
        if cm:
            raw_c = cm.group(1).upper()
            color = _normalize_color_filter(raw_c)
            # name から color を削る
            core = re.sub(rf"\s*{cm.group(1)}\s*", " ", core, flags=re.I).strip()

        # size 抽出 (US X (JP Y) を以前消したけど、size 単独 'XL' や 'Size XL' もある)
        size = ""
        sm = re.search(r"\b(?:Size\s+)?(XS|S|M|L|XL|XXL|XXXL|2XL|3XL)\b\s*$", core)
        if sm:
            size = _normalize_size(sm.group(1))
            core = re.sub(rf"\s*(?:Size\s+)?{sm.group(1)}\s*$", "", core).strip()

        # core cleanup: remove "UNIQLO " "UT " "T-Shirt" etc.
        clean = core
        for kw in ["UNIQLO", "UT", "T-Shirt", "TShirt", "T Shirt", "T-Shirts",
                  "Tee", "TEE", "Sweat Shirt", "Sweatshirt", "Shirt",
                  "Graphic", "Manga", "Anime"]:
            clean = re.sub(rf"\b{re.escape(kw)}\b", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s+", " ", clean).strip(" -|,")

        return {
            "name_en_raw": t,
            "name_en":     clean,
            "color":       color or "Multicolor",
            "size":        size or "",
        }

    upserted = 0
    for t in unique_titles:
        parsed = parse_title(t)
        # 合成 product_id: title の SHA1 先頭 8 文字 + HIST prefix
        h = hashlib.sha1(t.encode("utf-8")).hexdigest()[:8].upper()
        pid = f"HIST-{h}"

        # character / family / theme は既存 helper 流用 (英語 + 日本語両対応)
        themes = _derive_themes(t)
        family = _derive_character_family(t)
        character = _derive_character(t)

        api.upsert(
            category=CATEGORY,
            product_id=pid,
            name=parsed["name_en"],
            name_jp="",
            name_en=parsed["name_en"],
            name_en_source="ebay_listing_history",
            specs={
                # === 固定値 (T-Shirt 共通) ===
                "brand":               "Uniqlo",
                "type":                "T-Shirt",
                "size_type":           "Regular",
                "closure":             "Pullover",
                "neckline":            "Crew Neck",
                "sleeve_length":       "Short Sleeve",
                "fit":                 "Regular",
                "vintage":             "No",
                "personalize":         "No",
                "handmade":            "No",
                "style":               "Graphic Tee",
                "pattern":             "Graphic Print",
                "country_of_origin":   "Does not apply",
                "category_line":       "UT",
                "department":          "Unisex Adults",   # eBay listing は Unisex 扱いが多い
                # === 変動 ===
                "themes":              themes,
                "character_family":    family,
                "character":           character,
                "ebay_colors":         [parsed["color"]],
                "ebay_sizes":          [parsed["size"]] if parsed["size"] else [],
                "color_variants":      [],
                "size_variants":       [],
                "image_urls":          [],
                "price_jpy_base":      "",
                "price_jpy_promo":     "",
                # === Historical 由来マーカー ===
                "is_historical":       True,
                "source_title":        t[:200],
            },
            images=[],
            source="ebay_listing_history",
            source_url="",
        )
        upserted += 1

    print(f"  upserted: {upserted}")
    return {"unique_titles": len(unique_titles), "upserted": upserted}


def reprocess_in_place() -> dict:
    """既存 catalog の spec を **API 再 fetch せず** に再 derive.

    sweep 等の background 処理と競合させずに、
    name_jp / colors / sizes 等から themes/character/固定値を補完する.
    """
    import api  # type: ignore
    import sqlite3
    import json as _json

    conn = sqlite3.connect(str(api._DB_PATH))
    cur = conn.cursor()
    cur.execute(
        "SELECT product_id, name_jp, specs FROM products WHERE category = ? ORDER BY product_id",
        (CATEGORY,),
    )
    rows = cur.fetchall()
    print(f"=== in-place reprocess target: {len(rows)} records ===")
    updated = 0
    for pid, name_jp, specs_json in rows:
        try:
            old = _json.loads(specs_json or "{}")
        except Exception:
            continue
        new_spec = dict(old)

        # 固定値 (商品共通)
        new_spec.setdefault("brand", "Uniqlo")
        new_spec.setdefault("type", "T-Shirt")
        new_spec.setdefault("size_type", "Regular")
        new_spec.setdefault("closure", "Pullover")
        new_spec.setdefault("neckline", "Crew Neck")
        new_spec.setdefault("sleeve_length", "Short Sleeve")
        new_spec.setdefault("fit", "Regular")
        new_spec.setdefault("vintage", "No")
        new_spec.setdefault("personalize", "No")
        new_spec.setdefault("handmade", "No")
        new_spec.setdefault("style", "Graphic Tee")
        new_spec.setdefault("pattern", "Graphic Print")
        new_spec.setdefault("country_of_origin", "Does not apply")
        new_spec.setdefault("category_line", "UT")
        new_spec.setdefault("material", "")
        new_spec.setdefault("year_manufactured", "")

        # ebay_colors: 既存 color_variants から filter → 16色 enum
        color_ebay_set: list = []
        for c in (new_spec.get("color_variants") or []):
            ebay = _normalize_color_filter(c.get("filter") or "")
            if ebay not in color_ebay_set:
                color_ebay_set.append(ebay)
            # 各 variant に ebay_color 追加 (なければ)
            if "ebay_color" not in c:
                c["ebay_color"] = ebay
        new_spec["ebay_colors"] = color_ebay_set

        # ebay_sizes: 既存 size_variants から正規化
        size_ebay_set: list = []
        for s in (new_spec.get("size_variants") or []):
            norm = _normalize_size(s.get("name") or "")
            if norm and norm not in size_ebay_set:
                size_ebay_set.append(norm)
            if "ebay_size" not in s:
                s["ebay_size"] = norm
        new_spec["ebay_sizes"] = size_ebay_set

        # themes / character / character_family を name_jp から derive
        name = name_jp or new_spec.get("collab", "") or ""
        new_spec["themes"] = _derive_themes(name)
        new_spec["character_family"] = _derive_character_family(name)
        new_spec["character"] = _derive_character(name)

        # department: 既存 gender が UPPER のみなら正規化
        if not new_spec.get("department"):
            new_spec["department"] = _gender_to_dept(new_spec.get("gender", ""))

        if new_spec != old:
            cur.execute(
                "UPDATE products SET specs = ? WHERE category = ? AND product_id = ?",
                (_json.dumps(new_spec, ensure_ascii=False), CATEGORY, pid),
            )
            updated += 1
    conn.commit()
    conn.close()
    print(f"  updated: {updated}/{len(rows)}")
    return {"target": len(rows), "updated": updated}


def reprocess_all_active() -> dict:
    """既存 catalog の全 active UT record を最新 _parse_item で再生成.

    新しい spec field を追加した時に、過去取得した record も
    最新フォーマットに揃えるための保守運用関数.
    既存 record の l1Id を取得 → API で再 fetch → _parse_item → upsert.

    Returns:
        {"target": int, "reprocessed": int, "errors": int}
    """
    import api  # type: ignore
    import sqlite3
    import json as _json

    conn = sqlite3.connect(str(api._DB_PATH))
    cur = conn.cursor()
    cur.execute(
        "SELECT product_id, specs FROM products WHERE category = ? ORDER BY product_id",
        (CATEGORY,),
    )
    rows = cur.fetchall()
    conn.close()
    print(f"=== reprocess target: {len(rows)} records ===")
    reprocessed = 0
    errors = 0
    for i, (pid, specs_json) in enumerate(rows, 1):
        try:
            specs = _json.loads(specs_json or "{}")
            l1id = specs.get("l1_id")
            if not l1id:
                # productId 'E485482-000' から l1id 抽出
                m = re.match(r"E?(\d+)", pid)
                if not m:
                    continue
                l1id = m.group(1)
            result = _api_lookup_by_l1id(str(l1id))
            if not result:
                continue
            item_like = {
                "productId": pid,
                "l1Id": str(l1id),
                "name": result.get("name") or "",
                "genderName": result.get("genderName") or "",
                "colors": result.get("colors") or [],
                "sizes": result.get("sizes") or [],
                "prices": result.get("prices") or {},
                "images": result.get("images") or {},
                "promotionText": result.get("promotionText") or "",
                "rating": result.get("rating") or {},
            }
            parsed = _parse_item(item_like)
            if not parsed.get("product_id"):
                continue
            api.upsert(
                category=CATEGORY,
                product_id=parsed["product_id"],
                name=parsed["name"],
                name_jp=parsed["name_jp"],
                specs=parsed["specs"],
                images=parsed["images"],
                source="uniqlo_official_api",
                source_url=UNIQLO_PRODUCT_URL.format(l1id=l1id),
            )
            reprocessed += 1
            if i % 50 == 0:
                print(f"  [{i}/{len(rows)}] reprocessed={reprocessed}")
            time.sleep(0.3)
        except Exception as e:
            errors += 1
    print(f"=== 完了 ===")
    print(f"  target: {len(rows)}")
    print(f"  reprocessed: {reprocessed}")
    print(f"  errors: {errors}")
    return {"target": len(rows), "reprocessed": reprocessed, "errors": errors}


def lookup_by_l1id(l1id: str) -> bool:
    """個別 l1Id を API lookup → catalog upsert (廃盤救済).

    Returns:
        True (upsert 成功) / False (廃盤 = API "nok" / 通信エラー)
    """
    import api  # type: ignore
    result = _api_lookup_by_l1id(l1id)
    if not result:
        print(f"  {l1id}: not found / discontinued")
        return False
    # /products/{l1id} のレスポンスは異なる構造 (l2s 配下)
    # 簡易: 検索 API の item 形式に近い field を採取
    # この経路は廃盤救済の少数件用、簡易実装で十分
    name = result.get("name") or ""
    print(f"  {l1id}: {name[:60]}")
    # search-style item を作る (主要 field を埋める)
    item_like = {
        "productId": f"E{l1id}-000",
        "l1Id": l1id,
        "name": name,
        "genderName": result.get("genderName") or "",
        "colors": result.get("colors") or [],
        "sizes": result.get("sizes") or [],
        "prices": result.get("prices") or {},
        "images": result.get("images") or {},
        "promotionText": result.get("promotionText") or "",
        "rating": result.get("rating") or {},
    }
    parsed = _parse_item(item_like)
    if not parsed.get("product_id"):
        return False
    api.upsert(
        category=CATEGORY,
        product_id=parsed["product_id"],
        name=parsed["name"],
        name_jp=parsed["name_jp"],
        specs=parsed["specs"],
        images=parsed["images"],
        source=SOURCE,
        source_url=UNIQLO_PRODUCT_URL.format(l1id=l1id),
    )
    return True


# ============================================================================
# CLI
# ============================================================================
def _cli():
    args = sys.argv[1:]
    if not args:
        print("Usage:")
        print("  python iMakCatalog/scrapers/uniqlo_ut.py --update         # active 全件 catalog 化")
        print("  python iMakCatalog/scrapers/uniqlo_ut.py --discover        # active 件数のみ確認")
        print("  python iMakCatalog/scrapers/uniqlo_ut.py --lookup 485482   # 個別 l1Id 取得")
        sys.exit(1)
    if args[0] == "--update":
        update_all_active()
    elif args[0] == "--discover":
        data = _api_search(query="UT", limit=1, offset=0)
        total = ((data.get("result") or {}).get("pagination") or {}).get("total", 0)
        print(f"  active UT total: {total}")
    elif args[0] == "--lookup" and len(args) >= 2:
        lookup_by_l1id(args[1])
    elif args[0] == "--sweep" and len(args) >= 3:
        sweep_historical(int(args[1]), int(args[2]))
    elif args[0] == "--reprocess":
        reprocess_all_active()
    elif args[0] == "--reprocess-inplace":
        reprocess_in_place()
    elif args[0] == "--import-historical":
        # [DELETED] catalog 原則違反、削除済
        print("⚠️ --import-historical は削除済 (catalog 原則違反). "
              "過去 UT 情報は catalog 外で管理してください.")
        sys.exit(1)
    else:
        print(f"⚠️ 不明な引数: {args}")
        sys.exit(1)


if __name__ == "__main__":
    _cli()
