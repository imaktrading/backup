#!/usr/bin/env python3
"""Bandai Japan 公式 One Piece Card Game カードデータ取得モジュール.

- `https://www.onepiece-cardgame.com/cardlist/?freewords={card_id}` を叩いて
  HTML を解析し、カード情報を返す
- ローカル JSON キャッシュで重複アクセスを回避
- Selenium を既存 driver と共有可能
"""
import json
import os
import re
import time
from pathlib import Path

CACHE_PATH = Path(__file__).parent / "data" / "bandai_jp_cache.json"
CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

# 日本語キャラ名 → 英名マッピング (必要に応じて拡張)
CHARACTER_JP_TO_EN = {
    "モンキー・D・ルフィ": "Monkey D. Luffy",
    "ロロノア・ゾロ": "Roronoa Zoro",
    "ナミ": "Nami",
    "ウソップ": "Usopp",
    "サンジ": "Sanji",
    "トニートニー・チョッパー": "Tony Tony Chopper",
    "ニコ・ロビン": "Nico Robin",
    "フランキー": "Franky",
    "ブルック": "Brook",
    "ジンベエ": "Jinbe",
    "ヤマト": "Yamato",
    "ウタ": "Uta",
    "シャンクス": "Shanks",
    "トラファルガー・ロー": "Trafalgar Law",
    "ポートガス・D・エース": "Portgas D. Ace",
    "ボア・ハンコック": "Boa Hancock",
    "ジュエリー・ボニー": "Jewelry Bonney",
    "レベッカ": "Rebecca",
    "お菊": "O-Kiku",
    "お玉": "O-Tama",
    "おナミ": "O-Nami",
    "ルフィ太郎": "Luffy-Tarou",
    "ゾロ十郎": "Zoro-Juurou",
    "サンジ五郎": "Sanji-Gorou",
    "ウソ八": "Uso-Hachi",
    "モンキー・D・ルフィ／海賊王": "Monkey D. Luffy / King of the Pirates",
    "カイドウ": "Kaido",
    "ビッグ・マム": "Big Mom",
    "マルコ": "Marco",
    "エドワード・ニューゲート": "Edward Newgate",
    "ドンキホーテ・ドフラミンゴ": "Donquixote Doflamingo",
    "ネフェルタリ・ビビ": "Nefeltari Vivi",
    "ビビ": "Vivi",
    "ペローナ": "Perona",
    "サボ": "Sabo",
    "バルトロメオ": "Bartolomeo",
    "クロコダイル": "Crocodile",
    "ジュラキュール・ミホーク": "Dracule Mihawk",
    "ミホーク": "Mihawk",
    "スモーカー": "Smoker",
    "クザン": "Kuzan",
    "ボルサリーノ": "Borsalino",
    "サカズキ": "Sakazuki",
    "ガープ": "Garp",
    "センゴク": "Sengoku",
    "レイリー": "Rayleigh",
    "ゴール・D・ロジャー": "Gol D. Roger",
    "マーシャル・D・ティーチ": "Marshall D. Teach",
    "ベポ": "Bepo",
    "バギー": "Buggy",
    "エネル": "Enel",
    "アーロン": "Arlong",
    "キッド": "Eustass Kid",
    "ユースタス・キッド": "Eustass Kid",
    "シーザー": "Caesar Clown",
    "ローラ": "Lola",
    "カポネ": "Capone Bege",
    "ウルージ": "Urouge",
    "ホーキンス": "Basil Hawkins",
}

# 日本語カードタイプ → 英名
TYPE_JP_TO_EN = {
    "LEADER": "Leader Card",
    "CHARACTER": "Character Card",
    "EVENT": "Event Card",
    "STAGE": "Stage Card",
    "DON!! CARD": "DON!! Card",
}

# 日本語色 → 英名
COLOR_JP_TO_EN = {
    "赤": "Red", "青": "Blue", "緑": "Green",
    "紫": "Purple", "黒": "Black", "黄": "Yellow",
}

# 日本語属性 → 英名
ATTRIBUTE_JP_TO_EN = {
    "斬": "Slash", "打": "Strike", "射": "Ranged",
    "特": "Special", "知": "Wisdom",
}

# レアリティコード → 英語
# 注: "L" は Leader Card の型を示すコードで、レアリティではない → 空文字を返す
RARITY_CODE_TO_EN = {
    "L": "",  # Leader is card type, not rarity
    "C": "Common", "UC": "Uncommon",
    "R": "Rare", "SR": "Super Rare", "SEC": "Secret Rare",
    "SP CARD": "Special", "SP": "Special",
    "SPカード": "Special", "SP カード": "Special",
    "P": "Promo", "TR": "Treasure Rare",
    "DON!!": "DON!!", "DON": "DON!!",
}


def _load_cache():
    if CACHE_PATH.exists():
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_cache(cache):
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


_cache = _load_cache()


def _parse_card_element(card_html):
    """modalCol 1 要素分の HTML から構造化データを抽出."""
    from html.parser import HTMLParser

    # シンプルな正規表現抽出（HTMLは単純構造）
    def extract(pattern, text, default=""):
        m = re.search(pattern, text, re.DOTALL)
        return m.group(1).strip() if m else default

    def strip_tags(s):
        return re.sub(r"<[^>]+>", "", s).strip()

    data = {}
    data["card_id"] = extract(r'id="([^"]+)"', card_html)
    # infoCol: OP06-022 | L | LEADER
    info_col = extract(r'<div class="infoCol">(.*?)</div>', card_html)
    spans = re.findall(r"<span>([^<]+)</span>", info_col)
    if len(spans) >= 3:
        data["set_code_num"] = spans[0].strip()
        data["rarity_code"] = spans[1].strip()
        data["type_jp"] = spans[2].strip()
    data["name_jp"] = strip_tags(extract(r'<div class="cardName">(.*?)</div>', card_html))
    # backColの各セクション
    def grab(section):
        raw = extract(
            r'<div class="' + section + r'">.*?</h3>(.*?)</div>',
            card_html,
        )
        return strip_tags(raw)

    data["life_or_cost"] = grab("cost")
    data["attribute_jp"] = grab("attribute")
    data["power"] = grab("power")
    data["counter"] = grab("counter")
    data["color_jp"] = grab("color")
    data["block"] = grab("block")
    data["feature_jp"] = grab("feature")
    data["text_jp"] = grab("text")
    data["get_info_jp"] = grab("getInfo")
    # img src
    img_match = re.search(
        r'<img[^>]+data-src="(?:\.\./)?(?:images/)?cardlist/card/([^"?]+)', card_html
    )
    data["image_file"] = img_match.group(1) if img_match else ""
    return data


def _translate(data):
    """日本語フィールドを英語に翻訳して新しいキーを追加."""
    name_jp = data.get("name_jp", "")
    # 末尾の括弧バリアント情報を保持して翻訳
    base_name = re.sub(r"[（(].*?[)）]\s*$", "", name_jp).strip()
    variant = re.search(r"[（(]([^)）]+)[)）]\s*$", name_jp)
    en_base = CHARACTER_JP_TO_EN.get(base_name, base_name)
    if variant:
        data["name_en"] = f"{en_base} ({variant.group(1)})"
    else:
        data["name_en"] = en_base

    data["type_en"] = TYPE_JP_TO_EN.get(data.get("type_jp", ""), data.get("type_jp", ""))
    data["rarity_en"] = RARITY_CODE_TO_EN.get(
        data.get("rarity_code", ""), data.get("rarity_code", "")
    )

    # 色 "緑/黄" → "Green Yellow"
    color_jp = data.get("color_jp", "")
    colors = [COLOR_JP_TO_EN.get(c.strip(), c.strip()) for c in re.split(r"[/／]", color_jp) if c.strip()]
    data["color_en"] = " ".join(colors)

    # 属性 "打" → "Strike"
    data["attribute_en"] = ATTRIBUTE_JP_TO_EN.get(
        data.get("attribute_jp", ""), data.get("attribute_jp", "")
    )
    return data


def _scrape_url(driver, url):
    """与えられた検索URLから結果カードを抽出して返す"""
    driver.get(url)
    time.sleep(5)
    html = driver.page_source
    pattern = re.compile(r'<dl class="modalCol"[^>]*>.*?</dl>', re.DOTALL)
    elements = pattern.findall(html)
    cards = []
    for el in elements:
        parsed = _parse_card_element(el)
        if parsed.get("card_id"):
            _translate(parsed)
            cards.append(parsed)
    return cards


def fetch_card(driver, card_id, force_refresh=False):
    """card_id (例: 'OP06-022') で Bandai JP からカードデータを取得.
    同じ card_id に複数バリアント (通常/Alt Art/SP) がある場合は全部返す.
    """
    if not force_refresh and card_id in _cache:
        return _cache[card_id]
    url = f"https://www.onepiece-cardgame.com/cardlist/?freewords={card_id}"
    cards = _scrape_url(driver, url)
    _cache[card_id] = cards
    _save_cache(_cache)
    return cards


def _en_to_jp_name(name_en):
    """英名から日本語名を引く。フル名→短縮形の順にフォールバック。"""
    if not name_en:
        return None
    upper = name_en.upper().strip()
    # 逆引きマップ(完全一致)
    for jp, en in CHARACTER_JP_TO_EN.items():
        if en.upper() == upper:
            return jp
    # '/' で区切られていれば最初の部分で再試行
    if "/" in upper:
        first = upper.split("/")[0].strip()
        for jp, en in CHARACTER_JP_TO_EN.items():
            if en.upper() == first:
                return jp
        # 一般的なショートネーム群（主要キャラの姓のみ等）
        short_aliases = {
            "LUFFY": "ルフィ",
            "ZORO": "ゾロ",
            "NAMI": "ナミ",
            "SANJI": "サンジ",
            "ROBIN": "ロビン",
            "FRANKY": "フランキー",
            "BROOK": "ブルック",
            "JINBE": "ジンベエ",
            "CHOPPER": "チョッパー",
            "USOPP": "ウソップ",
            "ACE": "エース",
            "LAW": "ロー",
        }
        if first in short_aliases:
            return short_aliases[first]
    return None


def search_by_name(driver, name_en, card_number=""):
    """英語キャラ名から日本語名を引き、Bandai JPで検索.
    card_numberも指定すると結果を絞り込み可能.
    """
    name_jp = _en_to_jp_name(name_en)
    if not name_jp:
        return []
    cache_key = f"__name__{name_jp}__{card_number}"
    if cache_key in _cache:
        return _cache[cache_key]

    query = name_jp
    if card_number:
        query += f" {card_number}"
    import urllib.parse
    url = f"https://www.onepiece-cardgame.com/cardlist/?freewords={urllib.parse.quote(query)}"
    cards = _scrape_url(driver, url)
    _cache[cache_key] = cards
    _save_cache(_cache)
    return cards


def select_best_variant(cards, psa_subject, psa_set_hint=""):
    """複数バリアントから PSA Subject に最もマッチするものを選択.
    判定材料:
      1. get_info (入手情報) が PSA Subject のイベント/プロモキーワードと一致
      2. psa_set_hint (例: 'PRB02') が get_info に含まれる
      3. PSA subject 'SPECIAL' → rarity='Special' を優先
      4. PSA subject 'ALTERNATE ART' → card_id の _p suffix を優先
    """
    if not cards:
        return None
    if len(cards) == 1:
        return cards[0]

    psa_upper = psa_subject.upper() if psa_subject else ""
    set_hint_upper = psa_set_hint.upper() if psa_set_hint else ""

    event_keywords = {
        "ONE PIECE DAY": ["ONE PIECE DAY"],
        "BANDAI CARD GAME FEST": ["BANDAI CARD GAME FEST", "CARD GAME FEST"],
        "CHAMPIONSHIP": ["CHAMPIONSHIP", "選手権", "大会"],
        "8 PACKS BATTLE-WINNER": ["バトルウィナー", "BATTLE WINNER", "8パック"],
        "BATTLE-WINNER": ["バトルウィナー", "BATTLE WINNER"],
        "PREMIUM CARD COLLECTION": ["プレミアムカードコレクション", "PREMIUM CARD COLLECTION"],
        "25TH ANNIVERSARY": ["25TH", "25周年", "ANNIVERSARY"],
        "3RD ANNIVERSARY": ["3RD", "3周年"],
        "2ND ANV": ["2ND", "2周年"],
        "COMPLETE GUIDE": ["COMPLETE GUIDE", "コンプリートガイド", "ガイド"],
    }

    def score(card):
        s = 0
        get_info = card.get("get_info_jp", "").upper()
        card_id = card.get("card_id", "")
        rarity_en = (card.get("rarity_en") or "").upper()

        # 1. PSA brand set hint が get_info に含まれる (例: PRB02 → PRB-02)
        if set_hint_upper:
            # PRB02 → PRB-02 / PRB-02 形式で検索
            m = re.match(r'^([A-Z]+)(\d+)$', set_hint_upper)
            if m:
                formatted = f"{m.group(1)}-{m.group(2).zfill(2)}"  # "PRB-02"
                if formatted in get_info:
                    s += 200
            if set_hint_upper in get_info:
                s += 150

        # 2. イベント/プロモキーワードマッチ
        for psa_kw, info_kws in event_keywords.items():
            if psa_kw in psa_upper:
                for ikw in info_kws:
                    if ikw.upper() in get_info:
                        s += 100
                        break

        # 3. SPECIAL ALTERNATE ART / SPECIAL ART → rarity='Special' 優先
        if "SPECIAL" in psa_upper and rarity_en == "SPECIAL":
            s += 80

        # 4. ALTERNATE ART → _p suffix 優先
        is_alt = any(kw in psa_upper for kw in ["ALTERNATE ART", "SPECIAL ART", "ALT ART"])
        has_variant_suffix = bool(re.search(r"_p\d+$", card_id))
        if is_alt and has_variant_suffix:
            s += 50
        if not is_alt and not has_variant_suffix:
            s += 10  # 通常バージョン優先
        return s

    return max(cards, key=score)
