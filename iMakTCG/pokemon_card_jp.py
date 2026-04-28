#!/usr/bin/env python3
"""Pokemon公式カードデータベース (pokemon-card.com) 取得モジュール.

- pokemon-card.com/card-search/ をSeleniumで検索 → 画像URLからカードIDを特定
- details.php/card/{id} で詳細取得（サーバーサイドHTML）
- ローカルJSONキャッシュで重複アクセスを回避

検索ロジック:
  PSAラベルの英語名 → 日本語名に変換 → pokemon-card.comで検索
  → 画像パスのセットコード(M2a等)とカード番号でマッチング
"""
import json
import os
import re
import time
from pathlib import Path

CACHE_PATH = Path(__file__).parent / "data" / "pokemon_card_cache.json"
CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

# PSA英語名 → 日本語名マッピング（必要に応じて拡張）
# PSA Subject: "MEGA SCRAFTY EX" → 検索キーワード: "ズルズキン"
# "MEGA" は日本語名ではカード名に含まれる（メガズルズキンex）ので、ベースポケモン名で検索
# トレーナーカード英語名 → 日本語名マッピング
# PSA Subject: "IRIS'S FIGHTING SPIRIT SPECIAL ART" → 検索: "アイリスの闘志"
TRAINER_EN_TO_JP = {
    "IRIS'S FIGHTING SPIRIT": "アイリスの闘志",
    "N'S RESOLVE": "Nの覚悟",
    "BOSS'S ORDERS": "ボスの指令",
    "PROFESSOR'S RESEARCH": "博士のリサーチ",
    "CYNTHIA'S AMBITION": "シロナの覇気",
    "IRIDA": "カイ",
    "MELANIE": "メラニー",
    "PENNY": "ボタン",
    "IONO": "ナンジャモ",
    "ARVEN": "ペパー",
    "NEMONA": "ネモ",
    "CRISPIN": "アカマツ",
    "LACEY": "スグリ",
    # 2026-04-26 追加 (FA/ プレフィックス除去後の名前で辞書参照)
    "ELESA'S SPARKLE":     "カミツレのきらめき",
    "ELESA":               "カミツレ",
    "LILLIE'S RIBOMBEE":   "リーリエのアブリボン",
    "LILLIE":              "リーリエ",
    # 今後追加
}

POKEMON_EN_TO_JP = {
    # M2a: Mega Dream EX 収録ポケモン
    "SCRAFTY": "ズルズキン",
    "EELEKTROSS": "シビルドン",
    "HAWLUCHA": "ルチャブル",
    "GARDEVOIR": "サーナイト",
    "LUCARIO": "ルカリオ",
    "TYRANITAR": "バンギラス",
    "SABLEYE": "ヤミラミ",
    "ALTARIA": "チルタリス",
    "GALLADE": "エルレイド",
    "LATIOS": "ラティオス",
    "LATIAS": "ラティアス",
    "RAYQUAZA": "レックウザ",
    "MEWTWO": "ミュウツー",
    "MEW": "ミュウ",
    "CHARIZARD": "リザードン",
    "BLASTOISE": "カメックス",
    "VENUSAUR": "フシギバナ",
    "PIKACHU": "ピカチュウ",
    "FLYING PIKACHU V": "ピカチュウV",
    "FLYING PIKACHU": "ピカチュウ",
    "PIKACHU V": "ピカチュウV",
    "PIKACHU VMAX": "ピカチュウVMAX",
    "GENGAR": "ゲンガー",
    "ALAKAZAM": "フーディン",
    "STEELIX": "ハガネール",
    "SLOWBRO": "ヤドラン",
    "PIDGEOT": "ピジョット",
    "BEEDRILL": "スピアー",
    "LOPUNNY": "ミミロップ",
    "AUDINO": "タブンネ",
    "DIANCIE": "ディアンシー",
    "MANECTRIC": "ライボルト",
    "CAMERUPT": "バクーダ",
    "SHARPEDO": "サメハダー",
    "GLALIE": "オニゴーリ",
    "ABSOL": "アブソル",
    "AGGRON": "ボスゴドラ",
    "HOUNDOOM": "ヘルガー",
    "AMPHAROS": "デンリュウ",
    "HERACROSS": "ヘラクロス",
    "KANGASKHAN": "ガルーラ",
    "GYARADOS": "ギャラドス",
    "SCEPTILE": "ジュカイン",
    "BLAZIKEN": "バシャーモ",
    "SWAMPERT": "ラグラージ",
    # 汎用 — 人気・PSA鑑定頻出ポケモン
    "DRAGONITE": "カイリュー",
    "MACHAMP": "カイリキー",
    "ARCANINE": "ウインディ",
    "NINETALES": "キュウコン",
    "EXEGGUTOR": "ナッシー",
    "LAPRAS": "ラプラス",
    "EEVEE": "イーブイ",
    "SNORLAX": "カビゴン",
    "UMBREON": "ブラッキー",
    "ESPEON": "エーフィ",
    "VAPOREON": "シャワーズ",
    "JOLTEON": "サンダース",
    "FLAREON": "ブースター",
    "GLACEON": "グレイシア",
    "LEAFEON": "リーフィア",
    "SYLVEON": "ニンフィア",
    "MOLTRES": "ファイヤー",
    "ZAPDOS": "サンダー",
    "ARTICUNO": "フリーザー",
    "LUGIA": "ルギア",
    "HO-OH": "ホウオウ",
    "CELEBI": "セレビィ",
    "ENTEI": "エンテイ",
    "SUICUNE": "スイクン",
    "RAIKOU": "ライコウ",
    "GROUDON": "グラードン",
    "KYOGRE": "カイオーガ",
    "DIALGA": "ディアルガ",
    "PALKIA": "パルキア",
    "GIRATINA": "ギラティナ",
    "ARCEUS": "アルセウス",
    "RESHIRAM": "レシラム",
    "ZEKROM": "ゼクロム",
    "KYUREM": "キュレム",
    "XERNEAS": "ゼルネアス",
    "YVELTAL": "イベルタル",
    "ZACIAN": "ザシアン",
    "ZAMAZENTA": "ザマゼンタ",
    "CALYREX": "バドレックス",
    "MIRAIDON": "ミライドン",
    "KORAIDON": "コライドン",
    "TERAPAGOS": "テラパゴス",
    "PECHARUNT": "モモワロウ",
}

# PSAセット名からpokemon-card.comのセットコードを推定
SET_CODE_MAP = {
    "M2A-MEGA DREAM EX": "M2a",
    "M2A": "M2a",
    # 今後追加
}

# 日本語レアリティ → 英語
RARITY_JP_TO_EN = {
    "C": "Common", "U": "Uncommon", "R": "Rare", "RR": "Double Rare",
    "RRR": "Triple Rare", "SR": "Special Rare", "SAR": "Special Art Rare",
    "UR": "Ultra Rare", "AR": "Art Rare", "HR": "Hyper Rare",
    "MA": "Mega Attack Rare", "MUR": "Mega Ultra Rare",
}

# 日本語タイプ → 英語
TYPE_JP_TO_EN = {
    "草": "Grass", "炎": "Fire", "水": "Water", "雷": "Lightning",
    "超": "Psychic", "闘": "Fighting", "悪": "Darkness", "鋼": "Steel",
    "フェアリー": "Fairy", "ドラゴン": "Dragon", "無色": "Colorless",
}


def _load_cache():
    if CACHE_PATH.exists():
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _save_cache(cache):
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _extract_pokemon_name_jp(subject):
    """PSA Subjectからカード名を抽出し日本語に変換。
    ポケモンカード: 'MEGA SCRAFTY EX MEGA ATTACK' → 'ズルズキン'
    トレーナーカード: 'IRIS'S FIGHTING SPIRIT SPECIAL ART' → 'アイリスの闘志'
    プロモ系:        'FA/PIKACHU 25TH ANNIVERSARY COLL.' → 'ピカチュウ'
    """
    s = subject.upper().strip()

    # ① レアリティ接頭辞 (FA/ AR/ SR/ SAR/ UR/ HR/) を除去
    #    PSA は Full Art / Art Rare / Special Art Rare 等を "FA/" 形式で前置
    s = re.sub(r'^(FA|AR|SR|SAR|SSR|UR|HR|CHR|CSR)/', '', s).strip()

    # ② 末尾のセット名/コレクション名キーワードを除去
    #    "25TH ANNIVERSARY COLL." / "VSTAR UNIVERSE" / "SPACE JUGGLER" / "BATTLE PARTNERS" 等
    set_suffixes = [
        r'\s+25TH\s+ANNIVERSARY\s+COLL\.?$',
        r'\s+25TH\s+ANNIVERSARY$',
        r'\s+VSTAR\s+UNIVERSE$',
        r'\s+SPACE\s+JUGGLER$',
        r'\s+BATTLE\s+PARTNERS$',
        r'\s+MEGA\s+DREAM$',
        r'\s+CHARIZARD\s+EX\s+SET$',
        r'\s+CROWN\s+ZENITH$',
        r'\s+SHINY\s+TREASURE$',
        r'\s+TERASTAL\s+FEST(?:IVAL)?$',
    ]
    card_name = s
    for pat in set_suffixes:
        card_name = re.sub(pat, '', card_name)

    # ③ レアリティ接尾辞を除去
    rarity_suffixes = [
        r'\s+MEGA\s+ATTACK\s+RARE$', r'\s+MEGA\s+ATTACK$',
        r'\s+SPECIAL\s+ART\s+RARE$', r'\s+SPECIAL\s+ART$',
        r'\s+ART\s+RARE$', r'\s+ART$',
        r'\s+ULTRA\s+RARE$',
        r'\s+MEGA\s+ULTRA\s+RARE$', r'\s+BRIGHT\s+WORLD\s+RARE$',
        r'\s+RARE$',
    ]
    for pat in rarity_suffixes:
        card_name = re.sub(pat, '', card_name)
    card_name = card_name.strip()

    # ④ トレーナーカード辞書を先にチェック (完全一致)
    for en, jp in TRAINER_EN_TO_JP.items():
        if en.upper() == card_name:
            return jp

    # ⑤ ポケモンカード EX/V系: "MEGA {NAME} EX" / "{NAME} V" / "FLYING {NAME} V" 等
    #    まず "FLYING {NAME} V" のような複合キャラ名を辞書で完全一致チェック
    if card_name in POKEMON_EN_TO_JP:
        return POKEMON_EN_TO_JP[card_name]

    # ⑥ "MEGA {NAME} EX" → NAME部分を抽出
    m = re.match(r'(?:MEGA\s+)?(\w+(?:\s+\w+)?)\s+EX\b', card_name)
    if m:
        name = m.group(1).strip()
    elif ' ' in card_name:
        # 複数単語の場合、最後の単語を捨てて短縮 ("FLYING PIKACHU V" → "FLYING PIKACHU")
        # その短縮形が辞書にあれば採用
        parts = card_name.split()
        for n in range(len(parts), 0, -1):
            cand = ' '.join(parts[:n])
            if cand in POKEMON_EN_TO_JP:
                return POKEMON_EN_TO_JP[cand]
        name = parts[0]
    else:
        name = card_name

    return POKEMON_EN_TO_JP.get(name, None)


def _get_set_code(brand):
    """PSAブランドからpokemon-card.comのセットコードを取得"""
    if not brand:
        return None
    b = brand.upper()
    for key, code in SET_CODE_MAP.items():
        if key in b:
            return code
    return None


def fetch_card(driver, brand, card_number):
    """Pokemon公式サイトからカード情報を取得。

    Args:
        driver: Selenium WebDriverインスタンス
        brand: PSAラベルのBrand (例: "POKEMON JAPANESE M2A-MEGA DREAM EX")
        card_number: カード番号 (例: "231")

    Returns:
        dict with card data, or None
    """
    cache_key = f"pokemon_{brand}_{card_number}"
    cache = _load_cache()
    if cache_key in cache:
        cached = cache[cache_key]
        if cached is not None:
            print(f"    🎯 Pokemon公式 (キャッシュ): {cached.get('name_jp', '')}")
        return cached

    from selenium.webdriver.common.by import By

    # 1) PSA Subjectの英語名 → 日本語名に変換
    # brand からは subject が取れないので、card_number で後でマッチする
    # まずは brand から set_code を取得
    set_code = _get_set_code(brand)

    # brand からポケモン名のヒントを探す（M2A-MEGA DREAM EXなどセット名しかない）
    # → PSA Subject は呼び出し元から渡されないので、検索はセット全体から行う
    # 日本語名が分からない場合はセットコード + カード番号で検索

    # 2) pokemon-card.comで検索
    # まずカード番号で検索（レギュレーション制限なし）
    from urllib.parse import quote
    search_url = (
        f"https://www.pokemon-card.com/card-search/index.php"
        f"?keyword={quote(card_number)}&regulation_sidebar_form=all"
    )
    try:
        driver.get(search_url)
        time.sleep(6)

        source = driver.page_source
        body = driver.find_element(By.TAG_NAME, "body").text

        if "見つかりませんでした" in body:
            print(f"    ⚠️ Pokemon公式: 番号{card_number}で検索結果なし")
            cache[cache_key] = None
            _save_cache(cache)
            return None

        # 画像パスからカードIDとセットコードを抽出
        imgs = re.findall(
            r'data-src="(/assets/images/card_images/large/([^/]+)/(\d+)_[^"]+)"',
            source
        )

        if not imgs:
            print(f"    ⚠️ Pokemon公式: カード画像が見つかりません")
            cache[cache_key] = None
            _save_cache(cache)
            return None

        # セットコードでフィルタ（分かっている場合）
        target_id = None
        if set_code:
            for img_path, img_set, img_id in imgs:
                if img_set == set_code:
                    target_id = img_id.lstrip("0")
                    break

        # セットコードでマッチしなかった場合、最初の結果を使う
        if not target_id and imgs:
            target_id = imgs[0][2].lstrip("0")

        if not target_id:
            print(f"    ⚠️ Pokemon公式: カードID特定失敗")
            cache[cache_key] = None
            _save_cache(cache)
            return None

        # 3) 詳細ページを取得
        detail_url = f"https://www.pokemon-card.com/card-search/details.php/card/{target_id}"
        result = _parse_detail_page(driver, detail_url, card_number)

        if result:
            # セットコードを付加
            result["set_code"] = set_code or ""
            cache[cache_key] = result
            _save_cache(cache)
        else:
            cache[cache_key] = None
            _save_cache(cache)

        return result

    except Exception as e:
        print(f"    ⚠️ Pokemon公式取得エラー: {e}")
        return None


def fetch_card_with_subject(driver, brand, card_number, subject):
    """PSA Subject（英語名）を使ってPokemon公式から検索。
    subject を日本語名に変換して検索精度を上げる。

    Args:
        driver: Selenium WebDriver
        brand: PSAのBrand (例: "POKEMON JAPANESE M2A-MEGA DREAM EX")
        card_number: カード番号 (例: "231")
        subject: PSAのSubject (例: "MEGA SCRAFTY EX MEGA ATTACK")
    """
    cache_key = f"pokemon_{brand}_{card_number}"
    cache = _load_cache()
    if cache_key in cache:
        cached = cache[cache_key]
        if cached is not None:
            print(f"    🎯 Pokemon公式 (キャッシュ): {cached.get('name_jp', '')}")
        return cached

    from selenium.webdriver.common.by import By
    from urllib.parse import quote

    set_code = _get_set_code(brand)
    jp_name = _extract_pokemon_name_jp(subject)

    if jp_name:
        # 日本語名で検索
        search_keyword = jp_name
    else:
        # 日本語名がマッピングにない → カード番号だけで検索
        search_keyword = card_number
        print(f"    ⚠️ Pokemon英名→和名マッピングなし: {subject} → 番号検索にフォールバック")

    search_url = (
        f"https://www.pokemon-card.com/card-search/index.php"
        f"?keyword={quote(search_keyword)}&regulation_sidebar_form=all"
    )

    try:
        driver.get(search_url)
        time.sleep(6)

        source = driver.page_source
        body = driver.find_element(By.TAG_NAME, "body").text

        if "見つかりませんでした" in body:
            print(f"    ⚠️ Pokemon公式: 「{search_keyword}」検索結果なし")
            cache[cache_key] = None
            _save_cache(cache)
            return None

        # 画像パスからカードIDとセットコードを抽出
        imgs = re.findall(
            r'data-src="(/assets/images/card_images/large/([^/]+)/(\d+)_[^"]+)"',
            source
        )

        if not imgs:
            cache[cache_key] = None
            _save_cache(cache)
            return None

        # セットコード + 詳細ページのカード番号でマッチング
        target_id = None

        # まずセットコードが一致するカードの詳細を確認
        candidates = []
        for img_path, img_set, img_id in imgs:
            if set_code and img_set == set_code:
                candidates.append(img_id.lstrip("0"))
            elif not set_code:
                candidates.append(img_id.lstrip("0"))

        if not candidates:
            # セットコード一致なし → 全候補から
            candidates = [img_id.lstrip("0") for _, _, img_id in imgs]

        # 各候補の詳細ページでカード番号をマッチ
        for cid in candidates[:5]:  # 最大5件チェック
            detail_url = f"https://www.pokemon-card.com/card-search/details.php/card/{cid}"
            driver.get(detail_url)
            time.sleep(2)
            detail_body = driver.find_element(By.TAG_NAME, "body").text

            # カード番号の一致を確認 (例: "231 / 193" or "231/193")
            num_match = re.search(r'(\d+)\s*/\s*\d+', detail_body)
            if num_match and num_match.group(1) == card_number:
                target_id = cid
                break

        if not target_id:
            # 番号マッチしない場合、セットコード一致の最初を使う
            if candidates:
                target_id = candidates[0]
            else:
                cache[cache_key] = None
                _save_cache(cache)
                return None

        # 詳細ページを解析
        detail_url = f"https://www.pokemon-card.com/card-search/details.php/card/{target_id}"
        result = _parse_detail_page(driver, detail_url, card_number)

        if result:
            result["set_code"] = set_code or ""
            cache[cache_key] = result
            _save_cache(cache)
        else:
            cache[cache_key] = None
            _save_cache(cache)

        return result

    except Exception as e:
        print(f"    ⚠️ Pokemon公式取得エラー: {e}")
        return None


def _parse_detail_page(driver, url, expected_number):
    """カード詳細ページ（details.php）を解析"""
    try:
        driver.get(url)
        time.sleep(2)

        from selenium.webdriver.common.by import By
        body = driver.find_element(By.TAG_NAME, "body").text
        source = driver.page_source

        result = {
            "source": "pokemon-card.com",
            "url": url,
        }

        lines = body.split("\n")

        # カード名（最初の行）
        if lines:
            result["name_jp"] = lines[0].strip()

        # カード番号（"231 / 193" 形式）
        num_match = re.search(r'(\d+)\s*/\s*(\d+)', body)
        if num_match:
            result["card_number_full"] = f"{num_match.group(1)}/{num_match.group(2)}"

        # イラストレーター
        for i, line in enumerate(lines):
            if "イラストレーター" in line and i + 1 < len(lines):
                result["illustrator"] = lines[i + 1].strip()
                break

        # HP
        hp_match = re.search(r'HP\s*(\d+)', body)
        if hp_match:
            result["hp"] = hp_match.group(1)

        # タイプ（imgタグのaltやsrcから取得）
        type_imgs = re.findall(r'<img[^>]*src="[^"]*card/type/([^"]+)"', source)
        for type_file in type_imgs:
            # icon_grass.png → Grass
            type_match = re.search(r'icon_(\w+)', type_file)
            if type_match:
                type_key = type_match.group(1)
                type_map = {
                    "grass": "Grass", "fire": "Fire", "water": "Water",
                    "lightning": "Lightning", "psychic": "Psychic",
                    "fighting": "Fighting", "darkness": "Darkness",
                    "metal": "Steel", "fairy": "Fairy", "dragon": "Dragon",
                    "colorless": "Colorless",
                }
                if type_key in type_map:
                    result["type_en"] = type_map[type_key]
                    break

        # レアリティ（アイコン画像のファイル名から取得）
        # 例: /assets/images/card/rarity/ic_rare_ma.gif → MA
        rarity_match = re.search(r'rarity/ic_rare_(\w+)\.gif', source)
        if rarity_match:
            rarity_code = rarity_match.group(1).upper()
            result["rarity_code"] = rarity_code
            result["rarity_en"] = RARITY_JP_TO_EN.get(rarity_code, rarity_code)

        # セット名（「ハイクラスパック 「MEGAドリームex」」形式）
        # bodyテキストの最後の方にある
        for line in reversed(lines):
            line = line.strip()
            if line and "パック" in line or "コレクション" in line or "BOX" in line:
                result["set_jp"] = line
                break
            if "「" in line and "」" in line:
                result["set_jp"] = line
                break

        # 弱点
        weakness_match = re.search(r'弱点\n(.+)', body)
        if weakness_match:
            result["weakness"] = weakness_match.group(1).strip()

        # にげるコスト
        retreat_match = re.search(r'にげる\n(.+)', body)
        if retreat_match:
            result["retreat"] = retreat_match.group(1).strip()

        return result

    except Exception as e:
        print(f"    ⚠️ Pokemon詳細解析エラー: {e}")
        return None
