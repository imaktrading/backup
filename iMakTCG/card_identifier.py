"""card_identifier - PSA cert カード画像主導でカード特定する独立モジュール.

設計原則 (修正連鎖を生まないため):
  - 既存ロジック (bandai_jp / pokemon_card_jp / listing_validator 等) を一切修正しない
  - 単一関数 identify_from_image() のみ提供、呼出側はオプションで使う
  - 失敗時は confidence='low' or 'failed' を返し、呼出側がフォールバックを判断
  - Claude Vision API (anthropic SDK) を使用、cert# キーで JSON キャッシュ

「特定」と「推測」の区別 (memory `finish_must_be_deterministic` 準拠):
  - 「特定」 = カード上に印刷されている文字/シンボルを読み取る (card_number, character, set, rarity 等)
    → これは正確 (画像が読めれば誤りなし)
  - 「推測」 = 見た目から類推する (Holo/Non-Foil の光沢判定 等)
    → これは禁止 (SNAD クレーム直結)
  - 本モジュールは「特定」のみ実行、Finish は常に空欄返却

使用例:
    from card_identifier import identify_from_image
    result = identify_from_image(
        cert_number="143570665",
        image_url="https://www.psacard.com/cert/143570665/images/...",
        psa_brand="ONE PIECE JAPANESE PRB02-PREMIUM BOOSTER",
        psa_subject="MONKEY D. LUFFY SPARKLE FOIL",
    )
    # result["confidence"] in ("high", "medium", "low", "failed")
    # result["card_number"] = "PRB02-005" (画像から読み取った正式番号)
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.request
from pathlib import Path

# ============================================================================
# 設定
# ============================================================================
SCRIPT_DIR = Path(__file__).resolve().parent
CACHE_PATH = SCRIPT_DIR / "data" / "card_identifier_cache.json"
CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

# Claude API キー (psa_to_csv.py と同パス・同方式で読込)
_API_KEY_FILE = SCRIPT_DIR / "API key.txt"
try:
    with open(_API_KEY_FILE, "r", encoding="utf-8") as f:
        ANTHROPIC_API_KEY = f.read().strip()
except FileNotFoundError:
    ANTHROPIC_API_KEY = None

CLAUDE_MODEL = "claude-sonnet-4-20250514"  # psa_to_csv.py と統一


# ============================================================================
# キャッシュ
# ============================================================================
def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            with open(CACHE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


# ============================================================================
# 内部ヘルパー
# ============================================================================
def _empty_result(reason: str = "") -> dict:
    return {
        "confidence": "failed",
        "franchise": "",
        "card_number": "",
        "character": "",
        "set_name": "",
        "rarity": "",
        "color": "",
        "card_type": "",
        "cost": None,
        "power": None,
        "warnings": [reason] if reason else [],
        "raw_response": "",
    }


def _fetch_image_b64(image_url: str):
    """画像URLをBase64化."""
    try:
        with urllib.request.urlopen(image_url, timeout=10) as response:
            data = response.read()
        return base64.b64encode(data).decode("utf-8")
    except Exception:
        return None


def _detect_image_media_type(url: str) -> str:
    u = url.lower()
    if u.endswith(".png"):
        return "image/png"
    if u.endswith(".webp"):
        return "image/webp"
    return "image/jpeg"


# ============================================================================
# 公開 API
# ============================================================================
def identify_from_image(
    cert_number, image_url: str, psa_brand: str = "", psa_subject: str = ""
) -> dict:
    """PSA cert画像 + 補助情報 → 構造化カード情報を返す.

    Args:
        cert_number: PSA cert 番号 (キャッシュキー)
        image_url:   画像URL (PSA cert ページから取得済の URL)
        psa_brand:   PSA Brand 文字列 (補助、Vision はクロス参照に使うがソースオブトゥルースじゃない)
        psa_subject: PSA Subject 文字列 (同上)

    Returns:
        {
            "confidence": "high" | "medium" | "low" | "failed",
            "franchise": "One Piece TCG" | "Pokemon TCG" | "Gundam Card Game" |
                         "Dragon Ball Super Card Game" | "",
            "card_number": str,    # 画像から読み取った正式番号 (例: "OP06-091SP", "PRB02-005")
            "character":   str,
            "set_name":    str,    # 英語セット名 (Vision が知ってれば)
            "rarity":      str,    # フル英語名 (例: "Secret Rare", "Promo")
            "color":       str,
            "cost":        str | None,
            "power":       str | None,
            "warnings":    list[str],
            "raw_response": str,   # Claude raw レスポンス (デバッグ用)
        }
    """
    cert_key = str(cert_number)

    # キャッシュ確認
    cache = _load_cache()
    if cert_key in cache:
        cached = cache[cert_key]
        if cached:
            print(
                f"    🖼️ 画像特定 (キャッシュ): {cached.get('card_number', '?')} "
                f"/ {cached.get('character', '?')} (confidence={cached.get('confidence', '?')})"
            )
            return cached

    if not ANTHROPIC_API_KEY:
        return _empty_result("Anthropic API key 未設定 (API key.txt が見つからない)")
    if not image_url:
        return _empty_result("image_url 未指定")

    image_b64 = _fetch_image_b64(image_url)
    if not image_b64:
        return _empty_result(f"画像取得失敗: {image_url[:80]}")

    media_type = _detect_image_media_type(image_url)

    prompt = f"""You are a TCG card identification specialist.

Look at this PSA-graded card image and identify the card by reading PRINTED text and visual markers.

ASSISTING INFO from PSA label (cross-reference only, NOT source of truth):
- PSA Brand: {psa_brand}
- PSA Subject: {psa_subject}

IDENTIFICATION RULES:
1. READ the printed card_number from the card itself
   (e.g., "OP06-091", "FB01-039", "PRB02-005", "P-112", "OP06-091SP")
2. READ the printed character name (top of card area)
3. READ the set indicator (bottom right corner symbol/text)
4. READ the rarity marker (printed letter/symbol on card: SR/SEC/UC/R/C/L/SP/Promo/Art Rare 等)
5. IDENTIFY the franchise from card design: One Piece TCG / Pokemon TCG /
   Gundam Card Game / Dragon Ball Super Card Game
6. IDENTIFY the color from card frame (Red/Blue/Green/Yellow/Black/Purple/Multi-Color)
7. READ printed cost/power numbers if visible (top-left for One Piece, top-right HP for Pokemon)
8. IDENTIFY the card_type from card layout:
   - One Piece TCG: "Character" | "Leader" | "Event" | "Stage" | "Don"
     (Leader カードは大型枠 + ライフ表示、Character は通常枠)
   - Pokemon TCG: "Pokémon" | "Pokémon V" | "Pokémon ex" | "Pokémon VMAX" | "Pokémon VSTAR" | "Trainer" | "Energy"
     (HP表示あれば Pokémon 系、なければ Trainer/Energy)
   - Dragon Ball SCG: "Battle" | "Leader" | "Extra" | "Energy Marker"
   - Gundam Card Game: "Unit" | "Pilot" | "Command" | "Base" | "Resource"

CRITICAL CONSTRAINTS:
- Only return values that are CLEARLY PRINTED on the card. Do NOT guess.
- Do NOT determine Finish (Holo/Non-Foil) - this is forbidden, returned as empty.
- If a value is not clearly readable, return empty string.
- If the printed card_number conflicts with PSA Subject card_number, TRUST THE PRINTED CARD.

OUTPUT FORMAT REQUIREMENTS (CRITICAL):
- ALL string values MUST be in English (eBay listings are English-language).
- character: ALWAYS English (e.g., "Monkey D. Luffy" NOT "モンキー・D・ルフィ",
              "Trafalgar Law" NOT "トラファルガー・ロー", "Nami" NOT "ナミ")
- set_name: ALWAYS Title Case English (e.g., "Romance Dawn" NOT "ROMANCE DAWN" or "ロマンスドーン",
              "Straw Hat Crew" NOT "STRAW HAT CREW", "Carrying On His Will" NOT "OP13" or "受け継がれる意志")
- rarity: ALWAYS full English name (e.g., "Super Rare" NOT "SR", "Secret Rare" NOT "SEC",
              "Common" NOT "C", "Uncommon" NOT "UC")
- color: English (e.g., "Red", "Blue", "Green", "Yellow", "Black", "Purple", "Multi-Color")
- card_type: English (Character/Leader/Pokémon/Trainer/Battle/etc per franchise list above)
- If the card text is in Japanese (which is normal for these PSA-graded cards),
  TRANSLATE to standard English equivalents used in eBay listings.

CONFIDENCE SCORING (be strict):
- "high":   card_number AND character AND set_name all clearly readable, no conflicts with PSA Subject
- "medium": card_number readable with high certainty, some other values unclear
- "low":    card_number cannot be read clearly, OR multiple values conflict with PSA Subject
- "failed": image is unreadable, blurry, or no card visible

Return ONLY valid JSON, no other text:
{{
  "confidence": "high",
  "franchise": "One Piece TCG",
  "card_number": "OP06-091SP",
  "character": "Rebecca",
  "set_name": "Wings of the Captain",
  "rarity": "Secret Rare",
  "color": "Red",
  "card_type": "Character",
  "cost": "4",
  "power": "5000",
  "warnings": []
}}
"""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        raw = message.content[0].text
        # JSON 抽出 (前後の余計な文字列対策)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return _empty_result(f"JSON抽出失敗: {raw[:200]}")
        result = json.loads(m.group(0))
        # 出力スキーマを正規化 (キー漏れ対策)
        normalized = _empty_result()
        normalized.update({k: v for k, v in result.items() if k in normalized})
        normalized["warnings"] = result.get("warnings", []) or []
        normalized["raw_response"] = raw
        # Finish は常に空 (推測禁止ポリシー、本モジュールは特定のみ実行)
        # キャッシュ保存
        cache[cert_key] = normalized
        _save_cache(cache)
        print(
            f"    🖼️ 画像特定: {normalized.get('card_number', '?')} "
            f"/ {normalized.get('character', '?')} "
            f"(confidence={normalized.get('confidence', '?')})"
        )
        return normalized
    except Exception as e:
        return _empty_result(f"Vision API例外: {type(e).__name__}: {e}")


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python card_identifier.py <cert_number> <image_url> [psa_brand] [psa_subject]")
        sys.exit(1)
    cert = sys.argv[1]
    url = sys.argv[2]
    brand = sys.argv[3] if len(sys.argv) > 3 else ""
    subject = sys.argv[4] if len(sys.argv) > 4 else ""
    result = identify_from_image(cert, url, brand, subject)
    print(json.dumps(result, ensure_ascii=False, indent=2))
