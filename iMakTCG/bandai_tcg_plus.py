#!/usr/bin/env python3
"""Bandai TCG+ API カードデータ取得モジュール.

Dragon Ball Fusion World / Gundam Card Game のカード情報を
Bandai TCG+ API (api.bandai-tcg-plus.com) から取得する。
Selenium不要 — requestsだけで完結。

使用例:
    card = fetch_card("FB03-139", game="dragonball")
    card = fetch_card("DI-055", game="gundam")
"""
import json
import os
import requests
import time
from pathlib import Path

CACHE_PATH = Path(__file__).parent / "data" / "bandai_tcg_plus_cache.json"
CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

API_BASE = "https://api.bandai-tcg-plus.com/api"

# ゲーム名 → game_title_id マッピング
GAME_IDS = {
    "dragonball": 10,     # DBSCG Fusion World (EN)
    "dragonball_ja": 11,  # DBSCG Fusion World (JA)
    "gundam": 16,         # Gundam Card Game (EN)
    "gundam_ja": 15,      # Gundam Card Game (JA)
    "onepiece": 4,        # One Piece Card Game (EN)
    "onepiece_ja": 8,     # One Piece Card Game (JA)
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


def search_cards(card_number, game="dragonball"):
    """カード番号で検索してリストを返す。
    Args:
        card_number: "FB03-139", "DI-055" 等
        game: "dragonball", "gundam", "onepiece" 等
    Returns:
        list of card summaries
    """
    game_id = GAME_IDS.get(game, 10)
    url = f"{API_BASE}/user/card/list"
    params = {
        "game_title_id": game_id,
        "limit": 30,
        "offset": 0,
        "card_param": card_number,
        "reverse_card": 0,
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data.get("success", {}).get("cards", [])
    except Exception as e:
        print(f"    ⚠️ Bandai TCG+ API error: {e}")
        return []


def get_card_detail(card_api_id, game="dragonball"):
    """カードAPIのIDで詳細情報を取得。
    Args:
        card_api_id: APIから返される数値ID (例: 73409)
        game: ゲーム名
    Returns:
        dict with full card data
    """
    game_id = GAME_IDS.get(game, 10)
    url = f"{API_BASE}/user/card/{card_api_id}"
    params = {
        "game_title_id": game_id,
        "language_code": "EN",
        "app_version": "9.9.9",
        "country_code": "US",
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            return None
        return resp.json().get("success", {}).get("card", {})
    except Exception as e:
        print(f"    ⚠️ Bandai TCG+ detail error: {e}")
        return None


def fetch_card(card_number, game="dragonball"):
    """カード番号からItem Specifics用のデータを取得。キャッシュ付き。
    Args:
        card_number: "FB03-139" 等
        game: "dragonball" or "gundam"
    Returns:
        dict with: card_name, card_number, card_type, rarity, color, power, cost, set_name, special_trait
        or None if not found
    """
    cache_key = f"{game}_{card_number}"
    cache = _load_cache()
    if cache_key in cache:
        cached = cache[cache_key]
        if cached:
            print(f"    🎯 Bandai TCG+ (キャッシュ): {cached.get('card_name', '')}")
        return cached

    # 1) 検索
    cards = search_cards(card_number, game)
    if not cards:
        cache[cache_key] = None
        _save_cache(cache)
        return None

    # 2) カード番号のセットコードに一致するカードを優先選択
    # FB04-095 → セットコード "FB04" を含むset_nameのカードを探す
    import re as _re
    set_prefix_match = _re.match(r'([A-Z]+\d+)', card_number)
    set_prefix = set_prefix_match.group(1) if set_prefix_match else ""

    card_api_id = None
    if set_prefix and len(cards) > 1:
        # 2026-04-24 修正: card_number 完全一致を最優先（誤ヒット防止）
        # 旧: セット名に [GD01] 等が含まれる最初のカードを採用 → 同セット内の別カードに誤ヒット
        # 新: card_number が要求と完全一致するカードを最優先、無ければセット一致にフォールバック
        exact_match_id = None
        prefix_match_id = None
        prefix_match_set = ""
        for card in cards:
            cid = card.get("id")
            if not cid:
                continue
            detail_check = get_card_detail(cid, game)
            if not detail_check:
                continue
            detail_card_number = detail_check.get("card_number", "").strip()
            card_set = detail_check.get("card_set", "")
            # Priority 1: card_number 完全一致
            if detail_card_number == card_number:
                exact_match_id = cid
                print(f"    📌 card# 完全一致: {detail_card_number}")
                break
            # Priority 2: セット prefix 一致（最初の1件をフォールバックに保持）
            if prefix_match_id is None and f"[{set_prefix}]" in card_set:
                prefix_match_id = cid
                prefix_match_set = card_set[:40]
            time.sleep(0.2)
        card_api_id = exact_match_id or prefix_match_id
        if not exact_match_id and prefix_match_id:
            print(f"    ⚠️ card# 完全一致なし、セット [{set_prefix}] 一致で代替: {prefix_match_set}")
    if not card_api_id:
        card_api_id = cards[0].get("id")
    if not card_api_id:
        cache[cache_key] = None
        _save_cache(cache)
        return None

    detail = get_card_detail(card_api_id, game)
    if not detail:
        cache[cache_key] = None
        _save_cache(cache)
        return None

    # 3) card_config からフィールドを抽出
    config = {}
    for item in detail.get("card_config", []):
        name = item.get("config_name", "")
        value = item.get("value", "")
        if name and value:
            config[name] = value

    # 2026-04-24: Gundam は config キー名が異なる
    #   Dragon Ball: "Type"="Battle", "Rarity"="UC"
    #   Gundam:      "Card Type"="UNIT", "Rarity"="U", "AP"="3", "HP"="4"
    # 値の eBay 正規化:
    #   Gundam "UNIT"→"Unit Card", "COMMAND"→"Command Card" 等（eBay フィルタ値と一致させる）
    GUNDAM_TYPE_MAP = {
        "UNIT": "Unit Card",
        "COMMAND": "Command Card",
        "PILOT": "Pilot Card",
        "BASE": "Base Card",
        "RESOURCE": "Resource Card",
    }
    # Rarity も同様に Bandai の短縮コード → eBay フィルタ標準値
    # PSAラベルは "RARE+" 等 + 付きだが、eBay Item Specifics フィルタは + 無しが正規
    GUNDAM_RARITY_MAP = {
        "C":  "Common",
        "U":  "Uncommon",
        "R":  "Rare",
        "SR": "Super Rare",
        "LR": "Legend Rare",
    }
    raw_card_type = config.get("Type") or config.get("Card Type", "")
    if game == "gundam" and raw_card_type.upper() in GUNDAM_TYPE_MAP:
        card_type_norm = GUNDAM_TYPE_MAP[raw_card_type.upper()]
    else:
        card_type_norm = raw_card_type

    raw_rarity = config.get("Rarity", "")
    if game == "gundam" and raw_rarity.upper() in GUNDAM_RARITY_MAP:
        rarity_norm = GUNDAM_RARITY_MAP[raw_rarity.upper()]
    else:
        rarity_norm = raw_rarity

    result = {
        "source": "bandai-tcg-plus",
        "card_name": detail.get("card_name", ""),
        "card_number": detail.get("card_number", ""),
        "set_name": detail.get("card_set", ""),
        "card_type": card_type_norm,
        "rarity": rarity_norm,
        "color": config.get("Color", ""),
        "power": config.get("Power") or config.get("AP", ""),  # Gundam は AP = Attack Power
        "cost": config.get("Energy", config.get("Cost", "")),
        "special_trait": config.get("Special Trait", config.get("Trait", "")),
        "combo_power": config.get("Combo power", ""),
    }

    print(f"    🎯 Bandai TCG+: {result['card_name']} "
          f"({result['card_type']}, rarity={result['rarity']!r}, color={result['color']!r})")

    cache[cache_key] = result
    _save_cache(cache)
    return result
