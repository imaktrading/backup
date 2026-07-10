"""iMakTCG/psa_to_csv.py 向けのアダプタ — 旧 bandai_jp.lookup_bandai_card の drop-in 置換.

設計原則:
  - **ID 完全一致 lookup のみ**. 名前検索フォールバック禁止 (= PRB02-005 事故再発防止)
  - 旧 bandai_jp.fetch_card 互換の dict を返す → psa_to_csv 側のコード変更を最小化
  - eBay フィルタ値変換 (set_name / rarity) は iMakCatalog.api.to_ebay_value で完結
    → psa_to_csv の `_onepiece_set_to_ebay` / `_onepiece_rarity_to_ebay` /
      `_extract_set_name_from_get_info` / `_ONEPIECE_SET_NAME_MAP` は不要 (削除推奨)

iMakTCG/psa_to_csv.py への適用例:

    # 削除する import:
    # import bandai_jp

    # 追加する import:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "iMakCatalog"))
    from integrations import psa_to_csv as catalog_psa

    # 変更する callsite (元: psa_to_csv.py:1528 周辺):
    # OLD:
    #   bandai = lookup_bandai_card(driver, brand, card_number, subject)
    # NEW:
    #   bandai = catalog_psa.lookup_one_piece(brand, card_number, subject)
    #   ※ driver 引数は不要 (DB 検索のみ、Selenium 不要)

    # 削除可: lookup_bandai_card / _onepiece_rarity_to_ebay /
    #         _onepiece_set_to_ebay / _onepiece_set_code_to_name /
    #         _extract_set_name_from_get_info / _ONEPIECE_SET_NAME_MAP
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Optional

# iMakCatalog/api.py を import
_CATALOG_ROOT = Path(__file__).resolve().parent.parent
if str(_CATALOG_ROOT) not in sys.path:
    sys.path.insert(0, str(_CATALOG_ROOT))
import api  # noqa: E402

CATEGORY = "one_piece_tcg"


# ============================================================================
# Set code → eBay 公式名 (旧 psa_to_csv._onepiece_set_code_to_name の置換)
# ============================================================================
def set_code_to_ebay_name(set_value: str) -> str:
    """set_code または set 全文を eBay 公式名に変換. 未収録は元の値をそのまま返す
    (旧 _onepiece_set_code_to_name の挙動を踏襲、Vision OCR 長文にも対応).

    検索順: set_code → set (full string) フィールド.

    例:
      'OP-13'                                       → 'Carrying On His Will'
      'BOOSTER PACK -WINGS OF THE CAPTAIN- [OP-06]' → 'Wings of the Captain'  (set_code 抽出)
      'PREMIUM BOOSTER -ONE PIECE CARD THE BEST-'   → 'Premium Booster One Piece The Best' (set 全文一致)
      'OP-99'                                       → 'OP-99'  (未登録)
      ''                                            → ''
    """
    if not set_value:
        return set_value
    # 1st: set_code 直接一致 (例: 'OP-13')
    ebay = api.to_ebay_value(CATEGORY, "set_code", set_value)
    if ebay:
        return ebay
    # 2nd: 文字列内に bracket [XX-NN] / 【XX-NN】 が含まれていれば抽出して set_code 引き
    import re
    m = re.search(r"[\[【]([A-Z][A-Z0-9-]*)[\]】]", set_value)
    if m:
        ebay = api.to_ebay_value(CATEGORY, "set_code", m.group(1))
        if ebay:
            return ebay
    # 3rd: set 全文一致 (Vision OCR 由来の長文等)
    ebay = api.to_ebay_value(CATEGORY, "set", set_value)
    if ebay:
        return ebay
    return set_value


# ============================================================================
# PSA Brand → 公式 set_code 抽出 (旧 psa_to_csv.extract_set_code_from_brand 移植)
# ============================================================================
def extract_set_code_from_brand(brand: str) -> Optional[str]:
    """PSA Brand 文字列から Bandai 公式 set_code を抽出.

    例:
      'ONE PIECE JAPANESE OP08-TWO LEGENDS'  → 'OP08'
      'ONE PIECE JAPANESE PRB02 PROMOS'      → 'PRB02'
      'ONE PIECE DAY 23 PROMOS'              → 'P'
    """
    if not brand:
        return None
    b = brand.upper()
    m = re.search(r"\b(OP\d+|ST\d+|EB\d+|PRB\d+)\b", b)
    if m:
        return m.group(1)
    # Bandai 海外 (US/EU) 限定 marketing 名 → Bandai 公式 set_code 正規化.
    # PSA brand に set_code 番号 (OP12 等) が含まれず marketing 名のみのケースを救済.
    # 2026-05-11: PSA cert #156485701 Vinsmoke Reiju #063 'ONE PIECE JAPANESE
    # ADMIRABLE COLLECTION VOL 1 ...' が catalog miss → OP12-063 (Legacy of the
    # Master 同名 SR 既存) と照合できず.
    marketing_name_to_set = [
        # (PSA brand regex, Bandai 公式 set_code)
        # Admirable Collection vol.1 = 原典番号を保持する多元再録 (4 promo card)。番号で原典set
        # が変わる (#063→OP12-063 / #068→OP06-068) ため brand 一律 OP12 は誤り(#068→OP12-068=Gin)。
        # → "P" にして promo fallback (番号+名前+ADMIRABLE edition keyword) に番号駆動で解決させる。
        # (2026-06-12 cert 151477459 Reiju #068 対応。旧 OP12 固定は 2026-05-11 #063 用だったが
        #  fallback でも #063→OP12-063 に解決するため回帰なし=実測確認済)
        (r"\bADMIRABLE COLLECTION VOL\.?\s*1\b",  "P"),
        (r"\bLEGACY OF THE MASTER\b",             "OP12"),  # OP-12 英語公式名
        (r"\bA FIST OF DIVINE SPEED\b",           "OP11"),  # OP-11 英語公式名
        (r"\bROYAL BLOOD\b",                      "OP10"),  # OP-10
        (r"\bTWO LEGENDS\b",                      "OP08"),
        (r"\bWINGS OF THE CAPTAIN\b",             "OP06"),
        (r"\b500 YEARS IN THE FUTURE\b",          "OP07"),
        (r"\bNEW EMPEROR\b",                      "OP09"),  # OP-09 新たなる皇帝
        (r"\bONE PIECE HEROINES EDITION\b",       "EB03"),
        (r"\bANIME 25TH COLLECTION\b",            "EB02"),
        (r"\bMEMORIAL COLLECTION\b",              "EB01"),
        (r"\bEGGHEAD CRISIS\b",                   "EB04"),
        (r"\bONE PIECE CARD THE BEST VOL\.?\s*2\b","PRB02"),
        (r"\bONE PIECE CARD THE BEST\b",          "PRB01"),
    ]
    for pat, code in marketing_name_to_set:
        if re.search(pat, b):
            return code
    promo_keywords = [
        "PROMOS", "PROMO", "ONE PIECE DAY", "BANDAI CARD GAME FEST",
        "ANNIVERSARY", "PREMIUM CARD COLLECTION", "CHAMPIONSHIP",
        # 2026-05-01: Mini-Tin Vol.2 Bonney(P-113)/Robin(P-111) 事故対応.
        # PSA brand 'MINI-TIN VOL.2 ROKUSHIRO' 等が認識されず PSA Subject にフォールバック →
        # C:Card Name 汚染 / P- prefix 欠落の連鎖.
        "MINI-TIN", "MINI TIN",
    ]
    if any(k in b for k in promo_keywords):
        return "P"
    return None


# ============================================================================
# PSA Subject ↔ DB record の名前検証 (= ID hit 後の sanity check、search fallback ではない)
# ============================================================================
_SUBJECT_STOPWORDS = {
    # PSA 上の修飾語・カテゴリ語 (キャラ名ではないので除外)
    "THE", "OF", "AND", "FOR", "WITH",
    "ALTERNATE", "ALT", "SPECIAL", "ART", "PARALLEL", "MANGA", "FOIL", "HOLO",
    "RARE", "PROMO", "PROMOS", "PURCHASE", "BONUS",
    "ONE", "PIECE", "CARD", "CARDS", "GAME", "TCG",
    "DAY", "FEST", "BANDAI", "PACKS", "BATTLE", "WINNER", "KING", "PIRATES",
    "ANNIVERSARY", "PREMIUM", "COLLECTION",
    "ICHIBAN", "KUJI", "WEEKLY", "SHONEN", "JUMP",
    "MINI", "TIN", "SET", "VOL", "EDITION",
    "PCC", "SP", "FA", "AR", "SR", "RR", "SAR",
    "JAPANESE", "JAPAN", "JPN", "JP",
}


def _subject_tokens(subject: str) -> set[str]:
    """PSA Subject から名前検証に使う有意トークンを抽出 (3文字以上、stopword/数字除外)."""
    if not subject:
        return set()
    raw = re.split(r"[\s/\-:：&]+", subject.upper())  # :／& も区切り (例 'TRUNKS:FUTURE'→TRUNKS,FUTURE)
    out: set[str] = set()
    for w in raw:
        w = w.strip(".,;:'’\"")
        if len(w) < 3 or w.isdigit():
            continue
        if w in _SUBJECT_STOPWORDS:
            continue
        out.add(w)
    return out


# JA-only record 用の補助マップ: 日本語キャラ名 → 想定 PSA Subject token 群.
# 使用箇所は **検証 (ID hit 後の sanity check) のみ**, lookup には使わない (CLAUDE.md の
# 「名前検索フォールバック禁止」とは目的が異なる).
# 不足キャラがあると false negative (= reject) になるが、selfcheck が下流で再チェックする.
_JA_CHAR_TO_EN_TOKENS: dict[str, set[str]] = {
    "モンキー・D・ルフィ":   {"MONKEY", "LUFFY"},
    "モンキー・Ｄ・ルフィ":   {"MONKEY", "LUFFY"},
    "ロロノア・ゾロ":         {"RORONOA", "ZORO"},
    "ナミ":                   {"NAMI"},
    "ウソップ":               {"USOPP"},
    "サンジ":                 {"SANJI"},
    "トニートニー・チョッパー": {"TONY", "CHOPPER"},
    "ニコ・ロビン":           {"NICO", "ROBIN"},
    "フランキー":             {"FRANKY"},
    "ブルック":               {"BROOK"},
    "ジンベエ":               {"JINBE"},
    "ヤマト":                 {"YAMATO"},
    "ウタ":                   {"UTA"},
    "シャンクス":             {"SHANKS"},
    "トラファルガー・ロー":   {"TRAFALGAR", "LAW"},
    "ポートガス・D・エース":  {"PORTGAS", "ACE"},
    "ボア・ハンコック":       {"BOA", "HANCOCK"},
    "ジュエリー・ボニー":     {"JEWELRY", "BONNEY"},
    "レベッカ":               {"REBECCA"},
    "カイドウ":               {"KAIDOU", "KAIDO"},
    "ビッグ・マム":           {"BIG", "MOM"},
    "マルコ":                 {"MARCO"},
    "エドワード・ニューゲート": {"EDWARD", "NEWGATE", "WHITEBEARD"},
    "ドンキホーテ・ドフラミンゴ": {"DONQUIXOTE", "DOFLAMINGO"},
    "ネフェルタリ・ビビ":     {"NEFELTARI", "VIVI"},
    "ビビ":                   {"VIVI"},
    "ペローナ":               {"PERONA"},
    "サボ":                   {"SABO"},
    "バルトロメオ":           {"BARTOLOMEO"},
    "クロコダイル":           {"CROCODILE"},
    "ジュラキュール・ミホーク": {"DRACULE", "MIHAWK"},
    "ミホーク":               {"MIHAWK"},
    "スモーカー":             {"SMOKER"},
    "クザン":                 {"KUZAN", "AOKIJI"},
    "ボルサリーノ":           {"BORSALINO", "KIZARU"},
    "サカズキ":               {"SAKAZUKI", "AKAINU"},
    "ガープ":                 {"GARP"},
    "センゴク":               {"SENGOKU"},
    "レイリー":               {"RAYLEIGH"},
    "ゴール・D・ロジャー":    {"ROGER"},
    "マーシャル・D・ティーチ": {"MARSHALL", "TEACH", "BLACKBEARD"},
    "ベポ":                   {"BEPO"},
    "バギー":                 {"BUGGY"},
    "エネル":                 {"ENEL", "ENERU"},
    "アーロン":               {"ARLONG"},
    "キッド":                 {"KID", "EUSTASS"},
    "ユースタス・キッド":     {"EUSTASS", "KID"},
    "シーザー":               {"CAESAR"},
    "ローラ":                 {"LOLA"},
    "カポネ":                 {"CAPONE", "BEGE"},
    "ウルージ":               {"UROUGE"},
    "ホーキンス":             {"HAWKINS"},
    "しらほし":               {"SHIRAHOSHI"},
    "コビー":                 {"KOBY"},
    "ローラ・ベイ":           {"ROLLER"},
    "カク":                   {"KAKU"},
    "モダ":                   {"MODA"},
    "アルファ":               {"ALPHA"},
    "ゼフ":                   {"ZEFF"},
    "リューマ":               {"RYUMA", "RYUUMA"},
}


def _record_name_matches_subject(record: dict, subject: str) -> bool:
    """ID hit した record の name (en + jp) が PSA Subject トークンと交差するか.

    交差しない場合 = 同じ ID が DB と PSA で別カードを指している ≒ Bonney 事件パターン.
    トークンが取れない (subject 空 or stopwords のみ) → 検証スキップで True.

    JA-only record (name フィールドが日本語) の場合、_JA_CHAR_TO_EN_TOKENS を介して
    PSA Subject トークンと照合する.
    """
    tokens = _subject_tokens(subject)
    if not tokens:
        return True
    name_en = (record.get("name") or "").upper()
    name_jp = record.get("name_jp") or ""
    # 1. EN/混在 name の直接一致 (record.name + record.name_en + name_jp を corpus に。
    #    DBSCG/Gundam 等 name列が日本語の record でも name_en で romaji subject と照合可。
    #    2026-06-10: SB02-001 トランクス:未来 / name_en='Trunks : Future' を 'TRUNKS' と照合)
    combined = name_en + " " + (record.get("name_en") or "").upper() + " " + name_jp.upper()
    if any(t in combined for t in tokens):
        return True
    # 2. JA-only record: 日本語名 → 想定 EN tokens に変換して照合
    expected = _JA_CHAR_TO_EN_TOKENS.get(name_jp, set())
    if expected & tokens:
        return True
    return False


# ============================================================================
# variant 候補 (PSA Subject ヒント → product_id suffix)
# ============================================================================
_VARIANT_HINT_TO_SUFFIXES = {
    "ALTERNATE ART":   ["p1", "p2", "p3", "p", "p4"],
    "ALT ART":         ["p1", "p2", "p3", "p"],
    "ALTERNATE":       ["p1", "p2", "p3", "p"],
    "PARALLEL":        ["p1", "p2", "p3", "p"],
    "SPECIAL ART":     ["p1", "p2", "p3", "p"],
    "SPECIAL CARD":    ["p1", "p2", "p"],
    "SPECIAL":         ["p1", "p2", "p3", "p"],
    "MANGA":           ["p1", "p2", "p"],
    "FOIL":            ["p1", "p"],
}


def _variant_candidates(subject: str) -> list[str]:
    """PSA Subject から variant suffix 候補を返す (探索順)."""
    if not subject:
        return []
    subj = subject.upper()
    seen: set[str] = set()
    out: list[str] = []
    for hint, suffixes in _VARIANT_HINT_TO_SUFFIXES.items():
        if hint in subj:
            for s in suffixes:
                if s not in seen:
                    seen.add(s)
                    out.append(s)
    return out


# ============================================================================
# 旧 bandai_jp.fetch_card 形式に変換
# ============================================================================
# Bandai TCG 共通 color JA→EN (One Piece / Dragon Ball で同一漢字).
# DB の specs.color は scrape 時期により JA/EN 混在 (緑 975件 / Green 370件 等) のため、
# eBay 出力 (color_en) は必ず英語へ正規化する. 既に英語の値は pass-through.
_TCG_COLOR_JA_TO_EN = {
    "赤": "Red", "緑": "Green", "青": "Blue",
    "紫": "Purple", "黒": "Black", "黄": "Yellow",
}


def _normalize_color_en(value: str) -> str:
    """specs.color (JA or EN, 複合は '/' or '／' 区切り) → eBay 英語表記.

    例: '緑' → 'Green' / '緑/黄' → 'Green/Yellow' / 'Green' → 'Green' (pass-through).
    map に無いトークンはそのまま残す (= 既存英語 or 未知値を壊さない fail-safe).
    """
    if not value:
        return ""
    parts = re.split(r"[/／]", value)
    return "/".join(_TCG_COLOR_JA_TO_EN.get(p.strip(), p.strip()) for p in parts if p.strip())


def _apply_ebay_fields(legacy: dict, record: dict, category: str) -> dict:
    """全 lookup helper 共通の eBay _ebay field 適用 (= Phase A-G 完了後 adapter 修正).

    2026-05-30 追加: catalog の specs に投入された `_ebay` 系新 field を listing で優先採用。
    既存 field との衝突は specs 値 > legacy/record 値 で resolve。

    ★ 副次目的: field 正規化 (Phase B、 大文字 → 小文字) で legacy の旧 key (= "Rarity"/"Color"/
    "Card Type") が空になった既存 field を、 新 lower-case key で fallback 補完。
    """
    specs = record.get("specs") or {}
    # === eBay 新 field ===
    # set_name_ebay 採用順位 (= category 別):
    #   Pokemon: specs.set_name_ebay 優先、 fallback で "" (= JP set_name は eBay 認識不能、 fallback NG)
    #   OPCG/Gundam/DBFW: record.set_name (= 既存 ebay_filter_map 経由で正規化済) 優先、 fallback で specs
    #   YGO: specs.set_name_ebay (= ygoprodeck set_name 由来) 優先、 fallback で record.set_name
    set_name_specs = specs.get("set_name_ebay")
    if category == "pokemon_tcg":
        legacy["set_name_ebay"] = set_name_specs or ""
    elif category in ("one_piece_tcg", "gundam_tcg", "dragonball_scg"):
        legacy["set_name_ebay"] = record.get("set_name") or set_name_specs or ""
    else:  # yugioh_tcg etc
        legacy["set_name_ebay"] = set_name_specs or record.get("set_name", "") or ""
    legacy["rarity_ebay"] = specs.get("rarity_ebay") or specs.get("rarity") or legacy.get("rarity", "")
    # 2026-05-30 Gemini 5/HQ ユーザー方針: character_name は 空欄 fallback (= 日本語混入禁止)
    legacy["character_name"] = specs.get("character_name") or ""
    legacy["features"] = specs.get("features") or []
    legacy["finish"] = specs.get("finish") or ""
    legacy["card_type_ebay"] = specs.get("card_type_ebay") or legacy.get("card_type", "") or legacy.get("type_en", "")
    legacy["card_size_ebay"] = specs.get("card_size_ebay") or "Standard"
    legacy["game_ebay"] = specs.get("game_ebay") or ""
    legacy["release_year"] = specs.get("release_year") or ""
    legacy["language_ebay"] = specs.get("language") or legacy.get("language") or ""

    # === 既存 field fallback (= Phase B 正規化で大文字 key 消失への対応) ===
    # 旧 specs.Rarity → specs.rarity に変わったので legacy.rarity_en も小文字経由で復旧
    if not legacy.get("rarity_en"):
        legacy["rarity_en"] = specs.get("rarity") or ""
    if not legacy.get("rarity"):
        legacy["rarity"] = specs.get("rarity") or ""
    if not legacy.get("color_en") and "color_en" in legacy:
        # specs.color は JA/EN 混在 → eBay 出力は英語へ正規化 (緑→Green 等)
        legacy["color_en"] = _normalize_color_en(specs.get("color_en") or specs.get("color") or "")
    if not legacy.get("color") and "color" in legacy:
        legacy["color"] = specs.get("color") or ""
    if not legacy.get("type_en") and "type_en" in legacy:
        # specs.card_type or specs.type_en (= Bandai TCG+ 系) を fallback、 Title Case 正規化
        ct = specs.get("card_type") or specs.get("type_en") or ""
        legacy["type_en"] = ct.title() if ct.isupper() else ct
    if not legacy.get("card_type") and "card_type" in legacy:
        ct = specs.get("card_type") or specs.get("type_en") or ""
        legacy["card_type"] = ct.title() if ct.isupper() else ct
    if "power" in legacy and not legacy.get("power"):
        legacy["power"] = specs.get("power") or ""
    if "life_or_cost" in legacy and not legacy.get("life_or_cost"):
        legacy["life_or_cost"] = specs.get("cost") or ""
    if "cost" in legacy and not legacy.get("cost"):
        legacy["cost"] = specs.get("cost") or specs.get("energy") or ""
    if "counter" in legacy and not legacy.get("counter"):
        legacy["counter"] = specs.get("counter") or ""
    if "attribute_en" in legacy and not legacy.get("attribute_en"):
        legacy["attribute_en"] = specs.get("attribute") or ""
    if "feature_jp" in legacy and not legacy.get("feature_jp"):
        legacy["feature_jp"] = specs.get("type_en") or specs.get("trait") or specs.get("special_trait") or ""

    # 2026-05-31: build_row 既存 logic は legacy field 名 (= rarity / finish / game / card_size)
    # を見るため、 新 _ebay 値で legacy 名も上書き (= build_row 触らず listing 反映)。
    legacy["rarity"] = specs.get("rarity_ebay") or legacy.get("rarity") or ""
    legacy["finish"] = specs.get("finish") or ""
    legacy["game"] = specs.get("game_ebay") or legacy.get("game") or ""
    legacy["card_size"] = specs.get("card_size_ebay") or "Standard"
    return legacy


def _to_legacy_dict(record: dict) -> dict:
    """iMakCatalog の lookup() result → 旧 bandai_jp 形式.

    psa_to_csv.py:1530 周辺がアクセスする全フィールドを満たす.

    新規追加 (旧形式に無い):
      - set_name_ebay   : eBay フィルタ表示値 (record.set_name と同じ、明示用)
      - card_text       : eBay description / 検索性向上で活用可
      - card_text_jp    : 日本語効果テキスト
      - language        : 'en' / 'ja' / 'both'
    """
    specs = record.get("specs") or {}
    legacy = {
        # 旧 bandai_jp 互換フィールド
        "card_id":       record.get("product_id", ""),
        "name_en":       record.get("name_en") or record.get("name", ""),
        "name_jp":       record.get("name_jp"),
        "type_en":       specs.get("Card Type", ""),
        "rarity_en":     specs.get("Rarity", ""),
        "color_en":      specs.get("Color", ""),
        "power":         specs.get("Power", ""),
        "life_or_cost":  specs.get("Cost/Life", ""),
        "counter":       specs.get("Counter+", ""),
        "attribute_en":  specs.get("Attribute", ""),
        "feature_jp":    specs.get("Type", ""),     # Bandai の "Type" = キャラ特徴 (例: "麦わらの一味")
        "get_info_jp":   record.get("set_name_official", ""),
        "image_file":    "",                          # 旧形式の互換用 (使われていない)
        # iMakCatalog 拡張フィールド (新規)
        "set_name_official": record.get("set_name_official", ""),
        "card_text":     specs.get("card_text", ""),
        "card_text_jp":  specs.get("card_text_jp", ""),
        "language":      record.get("language"),
        "card_set_id":   record.get("card_set_id"),
        "regulations":   specs.get("regulations", []),
        "legality":      specs.get("legality", {}),
        "illustrator":   specs.get("illustrator"),
        "images":        record.get("images", []),
    }
    return _apply_ebay_fields(legacy, record, "one_piece_tcg")


# ============================================================================
# メイン: lookup_one_piece
# ============================================================================
def lookup_one_piece(
    brand: str,
    card_number: str,
    subject: str = "",
    verbose: bool = True,
) -> Optional[dict]:
    """One Piece カードを iMakCatalog DB から ID 完全一致で lookup.

    手順:
      1) PSA Brand から set_code 抽出 → base product_id を組み立て (例: "OP06-022")
      2) base lookup
      3) None の場合のみ、PSA Subject の variant ヒント (ALTERNATE ART / PARALLEL 等)
         から候補 suffix を試行 (`OP06-022_p`, `_p1`, `_p2` ...)
      4) 全部 None なら → return None (= フォールバック禁止、psa_to_csv 側で空欄出品)

    Args:
        brand: PSA Brand 文字列 (例: 'ONE PIECE JAPANESE OP06-WINGS OF THE CAPTAIN')
        card_number: PSA card number (例: '022')
        subject: PSA Subject (例: 'MONKEY D LUFFY ALTERNATE ART') — variant 推測のみに使用
        verbose: True で stdout に進捗を出す (旧 bandai_jp.fetch_card 互換)

    Returns:
        旧 bandai_jp.fetch_card 互換 dict | None
    """
    if not card_number:
        return None
    set_code = extract_set_code_from_brand(brand)
    if not set_code:
        if verbose:
            print(f"    ⚠️ set_code 抽出失敗: brand={brand!r}")
        return None

    # 安全装置: promo brand (set_code='P') で subject トークン無し → ID 検証不能なので skip.
    # P-XXX は別キャラに当たることが多く (P-019=Bepo 等)、subject 検証無しに採用すると
    # 誤マッチの温床になる. Phase 1 booster (set_code='OP07' 等) は PSA brand が specific
    # なので subject 無しでも ID 一致を信頼する.
    if set_code == "P" and not _subject_tokens(subject):
        if verbose:
            print(f"    ⚠️ promo brand で PSA Subject トークン無し → 検証不能なので Skip "
                  f"(brand={brand!r}, subject={subject!r})")
        return None

    base_pid = f"{set_code}-{card_number}"

    # === Promo brand 特別処理 (2026-05-28 拡張) ===
    # set_code='P' (= PSA brand "PROMOS" 等) の場合、 step 2 (= variant suffix 試行) を
    # skip する: `P-NNN_p1` 等の variant は実態として存在せず、 noise になるため。
    # ただし step 1 (= base `P-NNN`) は維持: P-001 等の純 promo はそのまま hit。
    # base 名前不一致時は step 3 で _search_one_piece_promo_by_number に fallback。
    if set_code == "P":
        record = api.lookup(CATEGORY, base_pid)
        if record and not _record_name_matches_subject(record, subject):
            if verbose:
                print(f"    ⚠️ iMakCatalog ID hit {base_pid} ({record['name']}) "
                      f"だが PSA Subject {subject!r} と名前不一致 → reject")
            record = None
        if record is None:
            # step 3: 全 set 横断 _P_* variant 検索
            record = _search_one_piece_promo_by_number(
                card_number, subject, brand=brand, verbose=verbose
            )
        if record is None:
            if verbose:
                print(f"    ⚠️ iMakCatalog Promo 未一致: {base_pid} → Skip "
                      f"(subject={subject!r})")
            return None
        if verbose and "_" not in record["product_id"]:
            print(f"    🎯 iMakCatalog hit: {record['product_id']} {record['name']}")
        return _to_legacy_dict(record)

    # 1. base lookup + 名前検証 (Bonney→Bepo 事件防止)
    record = api.lookup(CATEGORY, base_pid)
    if record and not _record_name_matches_subject(record, subject):
        if verbose:
            print(f"    ⚠️ iMakCatalog ID hit {base_pid} ({record['name']}) "
                  f"だが PSA Subject {subject!r} と名前不一致 → reject")
        record = None

    # 2. variant 試行 (PSA Subject ヒント) — 同じ名前検証を適用
    if record is None:
        for suffix in _variant_candidates(subject):
            candidate_pid = f"{base_pid}_{suffix}"
            cand = api.lookup(CATEGORY, candidate_pid)
            if cand and _record_name_matches_subject(cand, subject):
                record = cand
                if verbose:
                    print(f"    🎯 iMakCatalog hit (variant): {candidate_pid}")
                break

    # 4. Reprint/SP Alt fallback: PSA brand に specific set あり (例: OP11) で base miss
    #    → 全 set_code に対して {番号}_{PSA_set_code} suffix を試行 + 名前検証
    #    例: PSA Brand 'OP11' + 番号 '057' + Subject 'SHIRAHOSHI' →
    #        OP11-057 (Pedro) reject 後、EB01-057_OP11 (Shirahoshi 再録 SP Alt) を救済
    if record is None and set_code != "P":
        record = _search_one_piece_reprint_by_number(
            card_number, subject, set_code, verbose=verbose
        )

    if record is None:
        if verbose:
            print(f"    ⚠️ iMakCatalog 未登録 or 名前不一致: {base_pid} → Skip "
                  f"(subject={subject!r})")
        return None

    if verbose and "_" not in record["product_id"]:
        # base hit のみログ (variant hit は既にログ済み)
        print(f"    🎯 iMakCatalog hit: {record['product_id']} "
              f"{record['name']} ({record['specs'].get('Card Type', '?')}, "
              f"rarity={record['specs'].get('Rarity', '?')!r})")

    return _to_legacy_dict(record)


def _search_one_piece_reprint_by_number(
    card_number: str,
    subject: str,
    psa_set_code: str,
    verbose: bool = True,
) -> Optional[dict]:
    """SP Alt / Reprint fallback: PSA brand に specific set ({psa_set_code}) があるが
    base `{psa_set_code}-{number}` が別キャラに当たるケースを救済.

    DB には product_id `{ORIGINAL_SET}-{number}_{REPRINT_SET}` 形式で再録版が保存されている.
    例: PSA 'OP11-057 Shirahoshi' → DB は EB01-057_OP11 (EB-01 Shirahoshi の OP-11 再録)

    安全装置:
      - PSA Subject から有意トークンが取れること必須 (旧『名前検索フォールバック』とは別)
      - 番号は完全一致
      - PSA set_code が record の suffix (_OP11 等) に含まれることを確認
    """
    if not _subject_tokens(subject):
        return None
    if not psa_set_code:
        return None

    psa_sc_up = psa_set_code.upper()
    conn = api._connect()
    try:
        rows = conn.execute(
            "SELECT * FROM products WHERE category = ? AND product_id LIKE ?",
            (CATEGORY, f"%-{card_number}_%"),
        ).fetchall()
    finally:
        conn.close()

    pat = re.compile(rf"^[A-Z]+\d*-{re.escape(card_number)}_(.+)$")
    candidates: list[dict] = []
    for r in rows:
        pid = r["product_id"]
        m = pat.match(pid)
        if not m:
            continue
        suffix = m.group(1)
        # PSA set_code (例 'OP11') が suffix のどこかに含まれることを要求
        # (suffix は 'OP11' / 'OP11_p' / 'OP11_LF' 等の形式)
        if psa_sc_up not in suffix.upper().split("_"):
            continue
        rec = api._row_to_dict(r)
        if _record_name_matches_subject(rec, subject):
            candidates.append(rec)

    if not candidates:
        return None

    # 同名 candidate が複数 → subject ヒントで base / SP Alt / parallel を選択
    subj_up = (subject or "").upper()
    wants_sp = any(k in subj_up for k in ("SPECIAL", "ALTERNATE", " SP", "ALT ART"))

    def _score(c: dict) -> int:
        pid = c.get("product_id", "")
        rarity = (c.get("specs") or {}).get("Rarity", "")
        s = 0
        # SP Alt ヒント時: '_SP' / '_dummy' suffix / rarity に 'SP' 含むものを優先
        if wants_sp:
            if "_SP" in pid:
                s += 200
            if "_dummy" in pid:
                s += 100
            if "SP" in (rarity or "").upper():
                s += 50
        else:
            # 通常: 短い product_id (base reprint) 優先
            s -= len(pid)
        return s

    candidates.sort(key=_score, reverse=True)
    chosen = candidates[0]
    if verbose:
        print(f"    🎯 iMakCatalog hit (reprint fallback): {chosen['product_id']} "
              f"{chosen['name']} (PSA set={psa_set_code} の再録版、{len(candidates)}件中"
              f"{', SP Alt 優先' if wants_sp else ''})")
    return chosen


def _search_one_piece_promo_by_number(
    card_number: str,
    subject: str,
    brand: str = "",
    verbose: bool = True,
) -> Optional[dict]:
    """Promo brand fallback: 番号 + 名前検証 + PSA brand 照合で 全 set_code を横断検索.

    PSA Brand に specific set code が無い (= set_code='P') 時、`P-{number}` lookup が
    別キャラに当たるケース (例: P-019 = Bepo, でも実カードは OP07-019_P = Bonney) を救済.

    2026-05-25 改修 (HQ 5/25 依頼、cert 146264696 事故対応):
      - brand 引数追加. PSA brand と Catalog set_name の token overlap を ranking 加点.
      - 同点 (= 最高 score の record が複数) なら **fail-closed reject** (= 人間判断待ち).
      - 例 cert 146264696: Subject 'TONY TONY CHOPPER' + brand 'PREMIUM CARD COLLECTION'
        → 旧 logic は EB01-006_P_treasure (EB-01 Memorial 由来 promo) を選択
        → 新 logic は brand 'PREMIUM CARD COLLECTION' と set_name 'Other Product Card'
          のいずれかが優先される ST01-006* 系を選ぶ (= 既存救済 (OP07-019, EB01-057) も維持)

    安全装置:
      - 番号は完全一致 (LIKE で曖昧検索しない)
      - 名前検証で PSA Subject トークンが record name と交差すること必須
      - 旧『名前検索フォールバック』(番号無視で名前検索) とは別物
      - **同点なら None 返却 (= fail-closed)**
    """
    # PSA Subject から有意な検証トークンが取れない → 救済しない (誤マッチ防止)
    if not _subject_tokens(subject):
        return None
    conn = api._connect()
    try:
        rows = conn.execute(
            "SELECT * FROM products WHERE category = ? AND product_id LIKE ?",
            (CATEGORY, f"%-{card_number}%"),
        ).fetchall()
    finally:
        conn.close()

    pat = re.compile(rf"^[A-Z]+\d*-{re.escape(card_number)}(_.+)?$")
    candidates: list[dict] = []
    for r in rows:
        pid = r["product_id"]
        if not pat.match(pid):
            continue
        if pid.startswith("P-") or pid == f"P-{card_number}":
            continue
        rec = api._row_to_dict(r)
        if _record_name_matches_subject(rec, subject):
            candidates.append(rec)

    if not candidates:
        return None

    # brand を upper case に正規化 (照合用)
    brand_upper = (brand or "").upper()
    # brand 主要 token (= set_name 照合用、3 文字以上の単語)
    brand_tokens = set()
    if brand_upper:
        for t in re.findall(r"[A-Z]+", brand_upper):
            if len(t) >= 3 and t not in {"ONE", "PIECE", "CARD", "JAPANESE", "GAME", "THE"}:
                brand_tokens.add(t)

    def _promo_score(rec: dict) -> int:
        pid = rec.get("product_id", "")
        sn = (rec.get("set_name_official") or "") or (rec.get("set_name") or "")
        sn_upper = sn.upper()
        # PSA は edition/event 語を brand と subject の **どちらにも** 置く
        # (例 brand='ONE PIECE JAPANESE PROMOS' / subject='KAYA STANDARD BATTLE WINNER')。
        # よって照合は brand+subject の合成 hay で行う (2026-06-10 HQ差し戻し: subject側未照合の是正)。
        hay = brand_upper + " " + (subject or "").upper()
        score = 0
        # _P / _P_* suffix (promo 版そのもの)
        if re.search(r"_P(_|$)", pid):
            score += 100
        # set_name が 'Promotion' / 'プロモーション' 含む
        if "PROMOTION" in sn_upper or "プロモーション" in sn:
            score += 50
        # base record (suffix 無し) → 低
        elif "_" not in pid:
            score += 10
        # PSA brand と set_name の token overlap (2026-05-25 追加)
        # 例: brand 'PREMIUM CARD COLLECTION' / set_name 'Other Product Card'
        #     → 'CARD' overlap だが PREMIUM keyword は別途加点
        # 1) brand keyword 直接 match (set_name に含まれる)
        for kw, weight in [
            ("MEMORIAL", 80),     # EB-01 Memorial Collection
            ("PREMIUM", 60),       # PRB-01 / PRB-02 / Premium Card Collection
            ("ANNIVERSARY", 60),
            ("STARTER", 60),
            ("MINI-TIN", 60), ("MINI TIN", 60),
            ("HEROINES", 60),     # EB-03
            ("ROMANCE DAWN", 50),
            ("WINGS OF THE CAPTAIN", 50),
            ("STORAGE BOX", 60),   # 合本 set
            ("ONE PIECE DAY", 50),
            ("BANDAI CARD GAME FEST", 50),
            ("DAY", 40), ("FEST", 40),
        ]:
            if kw in hay and kw in sn_upper:
                score += weight
        # 2) "PREMIUM CARD COLLECTION" 等 special promo → set_name 'Other Product Card' / 'Promotion Card' 優先
        if "PREMIUM CARD COLLECTION" in hay:
            if "OTHER PRODUCT" in sn_upper or "PROMOTION CARD" in sn_upper:
                score += 70
        # 3) "STORAGE BOX" がある = PRB01/PRB02 合本、set_name PRB 含む優先
        if "STORAGE BOX" in hay:
            if "PRB" in sn_upper or "PREMIUM BOOSTER" in sn_upper or "STARTER DECK" in sn_upper:
                score += 50
        # 4) "STARTER DECK" あり → set_name STARTER 優先
        if "STARTER DECK" in hay:
            if "STARTER DECK" in sn_upper:
                score += 70
        # 5) brand-token と set_name-token の overlap 数
        if brand_tokens:
            sn_tokens = set(re.findall(r"[A-Z]+", sn_upper))
            overlap = brand_tokens & sn_tokens
            if overlap:
                score += min(len(overlap) * 8, 40)
        # 6) brand "BEST SELECTION VOL.N" → 日本語 set_name 'ベストセレクション vol.N' を最優先
        #    (premium card collection は set_name が日本語のため英keyword照合で拾えず、
        #     _P/_P_* 系 'Promotion Card' に負けて本命が最下位になる問題を是正)
        #    HQ依頼 2026-06-09_psa_miss_setmap_promo_scoring.md (OP10-049 Sabo)
        #    HQ Step2 確定(2026-06-10): brand edition句 ↔ set_name_official edition句 の一般照合。
        #    「両方一致」必須 = 同番号の別edition(_p4=FILM RED 等)への暴発防止。ハードコード非依存。
        #    例: BEST SELECTION VOL.4↔ベストセレクション vol.4(Sabo) / 25TH ANNIVERSARY↔25周年(Chopper ST01-006_p1)
        #    2026-06-10 拡張(HQ greenlight unresolved17 (I)): edition/event の brand英↔official日 pair。
        #    照合は hay(brand+subject) で行う(edition/event語は subject 側のことが多い)。
        edition_hit = False
        m_bs = re.search(r"BEST\s*SELECTION\s*VOL\.?\s*(\d+)", hay)
        if m_bs and "ベストセレクション" in sn and re.search(rf"vol\.?\s*{m_bs.group(1)}\b", sn, re.IGNORECASE):
            edition_hit = True
        if re.search(r"25TH|25\s*周年", hay) and "25周年" in sn:
            edition_hit = True
        # 2026-07-02: "Nth ANNIVERSARY SET" edition (cert84400496 OTAMA #006 → OP01-006_p4).
        #   汎用promo(_P 'Promotion Card' score150)に本命(_p4 'Nst ANNIVERSARY SET')が
        #   負けて沈む問題を是正。**ordinal番号一致必須** = 1st/2nd/3rd の別anniversary set への
        #   暴発防止(番号違いなら発火せず、既存の keyword +60 のみ)。
        m_anniv = re.search(r"(\d+)\s*(?:ST|ND|RD|TH)\s*ANNIVERSARY", hay)
        if m_anniv and re.search(rf"\b{m_anniv.group(1)}\s*(?:st|nd|rd|th)\s*ANNIVERSARY", sn, re.IGNORECASE):
            edition_hit = True
        # edition/event pair (両方一致必須=暴発防止)。英keyword in hay かつ 日keyword in official。
        for en, jp in (
            ("FILM RED", "FILM RED"),
            ("ONE PIECE DAY", "ONE PIECE DAY"),
            ("PROMOTION CARD SET", "プロモーションカードセット"),
            ("STANDARD BATTLE", "スタンダードバトル"),
            ("EVENT PRIZE", "記念品"),
            # 2026-07-10 (cert85592405 Pudding #008 → ST07-008_GE): プレミアムカードコレクション
            #   -GIRLS EDITION- 収録 parallel。official set_name に 'GIRLS EDITION' を持つ変種のみ +250。
            #   両側一致必須なので base ST07-008/他promo(_P 等)には発火しない。
            ("GIRLS EDITION", "GIRLS EDITION"),
            # 2026-06-12 収録: ADMIRABLE COLLECTION vol.N 封入 promo (cert 151477459 Reiju #068
            #   → OP06-068_AC01)。official set_name に "Admirable Collection" を持つ変種のみ +250。
            #   両側一致必須なので別 #068 変種(PRB01/p1 等)には発火しない。
            ("ADMIRABLE COLLECTION", "ADMIRABLE COLLECTION"),
            # 2026-06-12 REVIEW: nth ANNIVERSARY COMPLETE GUIDE 収録特典 promo.
            #   official は英語表記 "Nth ANNIVERSARY COMPLETE GUIDE" を含むため en=jp 同句で
            #   両側一致照合。PSA brand は "ANV." 略記なので distinctive token "COMPLETE GUIDE"
            #   で照合する。例 cert 148642488 ZORO 2ND ANV. COMPLETE GUIDE #067 → OP05-067_p2
            #   (#067 候補中 official に COMPLETE GUIDE を持つのは _p2 のみ = 一意特定)。
            ("COMPLETE GUIDE", "COMPLETE GUIDE"),
        ):
            if en in hay and (jp in sn or jp in sn_upper):
                edition_hit = True
        # UTA は短語のため \bUTA\b 限定 + official 'ウタ'
        if re.search(r"\bUTA\b", hay) and "ウタ" in sn:
            edition_hit = True
        if edition_hit:
            score += 250  # edition 一意特定 = 汎用promo(_P 220)を上回る最優先
        # qualifier: 同一edition内の別variantを分離(+30)。WINNER↔優勝 / PREMIUM CARD COLLECTION↔プレミアムカードコレクション
        #   (例 FILM RED で _p5=プレミアムカードコレクション と _p3=入場者特典 を分離)
        if "WINNER" in hay and "優勝" in sn:
            score += 30
        if "PREMIUM CARD COLL" in hay and "プレミアムカードコレクション" in sn:
            score += 30
        # 8) cross-set 誤選択防止: brand が MEMORIAL/EB を明示しないのに EB(Memorial由来)
        #    promo が原典set(ST/OP)の promo と同点になる誤マッチ (Chopper EB01-006_P_treasure)
        #    → EB由来 promo を減点し原典set promo を優先 (誤マッチ防止、原典優先)
        if "MEMORIAL" not in hay and re.match(r"^EB\d", pid) and "_P" in pid:
            score -= 40
        return score

    scored = [(_promo_score(c), c) for c in candidates]
    scored.sort(key=lambda x: x[0], reverse=True)
    top_score = scored[0][0]
    top_n = sum(1 for s, _ in scored if s == top_score)

    # 同点 reject (= fail-closed、人間判断待ち)
    if top_n > 1:
        if verbose:
            print(f"    ⚠️ promo fallback 同点 top {top_n} 件 ({len(candidates)} 候補中) "
                  f"→ fail-closed reject (brand={brand!r}, subject={subject!r})")
            for s, c in scored[:5]:
                print(f"        score={s} pid={c['product_id']} set={c.get('set_name_official', '')[:50]!r}")
        return None

    chosen = scored[0][1]
    if verbose:
        pid = chosen["product_id"]
        print(f"    🎯 iMakCatalog hit (promo fallback): {pid} "
              f"{chosen['name']} (Subject='{subject}' brand={brand!r} と一致, "
              f"{len(candidates)}件中 score={top_score})")
    return chosen


# ============================================================================
# ============================================================================
# Gundam Card Game (game_id=16/15)
# ============================================================================
# ============================================================================
GUNDAM_CATEGORY = "gundam_tcg"


def extract_set_code_from_brand_gundam(brand: str) -> Optional[str]:
    """PSA Brand → Gundam 公式 set_code 抽出.
    例:
      'GUNDAM JAPANESE GD01-NEWTYPE RISING' → 'GD01'
      'GUNDAM CARD GAME ST01 EXTRA STARTER' → 'ST01'
    """
    if not brand:
        return None
    b = brand.upper()
    m = re.search(r"\b(GD\d+|ST\d+|EX\d+)\b", b)
    if m:
        return m.group(1)
    # set 名キーワード逆引き (PSA brand が code token を持たず literal英名のみのケース)
    #   2026-06-10 HQ依頼 db_gundam_setmap (SwSh set-map と同型)。真値=公式弾名。
    for kw, code in (
        # Booster (GD)
        ("NEWTYPE RISING", "GD01"),
        ("DUAL IMPACT", "GD02"),
        ("STEEL REQUIEM", "GD03"),
        ("PHANTOM ARIA", "GD04"),
        # Starter Deck (ST) — 公式英名(catalog set_name_official 一致)。番号衝突(OP ST04-013等)は
        #   resolver の brand→category 検出で分離済。2026-06-10 HQ差し戻し(252 SEED STRIKE)。
        ("HEROIC BEGINNINGS", "ST01"),
        ("WINGS OF ADVANCE", "ST02"),
        ("ZEON'S RUSH", "ST03"), ("ZEONS RUSH", "ST03"),
        ("SEED STRIKE", "ST04"),
        ("IRON BLOOM", "ST05"),
        ("CLAN UNITY", "ST06"),
        ("CELESTIAL DRIVE", "ST07"),
        ("FLASH OF RADIANCE", "ST08"),
        ("DESTINY IGNITION", "ST09"),
    ):
        if kw in b:
            return code
    # Resource Promo は専用 prefix 'RP' (= catalog product_id 'RP-009' 等).
    # PSA brand 'GUNDAM JAPANESE RESOURCE PROMOS' → 'P' に潰すと P-009 を探して miss するため先に分岐.
    if "RESOURCE" in b:
        return "RP"
    # 2026-07-10 (cert154708676): PB01 プレミアムグッズセット -新機動戦記ガンダムW- は ST02(Wings of
    #   Advance)の Wing カードを同番号で再録(parallel C+)。#010 Heero Yuy → ST02-010(_PB01 variant)。
    #   lookup_gundam 側で brand=PREMIUM GOODS 時に _PB01 variant を優先。
    if "PREMIUM GOODS" in b and ("GUNDAM W" in b or "WING" in b):
        return "ST02"
    if any(k in b for k in ("PROMO", "PROMOS", "ANNIVERSARY", "CHAMPIONSHIP")):
        return "P"
    return None


# Gundam variant suffix 候補 (PSA Subject ヒント)
_GUNDAM_VARIANT_HINT_TO_SUFFIXES: dict[str, list[str]] = {
    "ALTERNATE ART":  ["para", "SP"],
    "ALT ART":        ["para", "SP"],
    "PARALLEL":       ["para"],
    "SPECIAL ART":    ["SP", "para"],
    "SPECIAL":        ["SP"],
    "FOIL":           ["para"],
}


def _variant_candidates_gundam(subject: str) -> list[str]:
    if not subject:
        return []
    subj = subject.upper()
    seen: set[str] = set()
    out: list[str] = []
    for hint, suffixes in _GUNDAM_VARIANT_HINT_TO_SUFFIXES.items():
        if hint in subj:
            for s in suffixes:
                if s not in seen:
                    seen.add(s)
                    out.append(s)
    return out


def _to_legacy_dict_gundam(record: dict) -> dict:
    """Gundam 用 record → psa_to_csv 互換 dict."""
    specs = record.get("specs") or {}
    legacy = {
        # 旧 bandai_tcg_plus.fetch_card(game='gundam') 互換
        "card_name":     record.get("name", ""),
        "card_id":       record.get("product_id", ""),
        "card_number":   record.get("product_id", "").split("_")[0],  # variant 剥がし
        "name_en":       record.get("name_en") or record.get("name", ""),
        "name_jp":       record.get("name_jp"),
        "card_type":     specs.get("Card Type", ""),
        "type_en":       specs.get("Card Type", ""),
        "rarity":        specs.get("Rarity", ""),
        "rarity_en":     specs.get("Rarity", ""),
        "color":         specs.get("Color", ""),
        "color_en":      specs.get("Color", ""),
        "power":         specs.get("AP", ""),     # Gundam: AP = Attack Power (One Piece の Power 相当)
        "hp":            specs.get("HP", ""),     # Gundam 固有
        "cost":          specs.get("Cost", ""),
        "level":         specs.get("Lv. (Level)", ""),
        "trait":         specs.get("Trait", ""),
        "feature_jp":    specs.get("Trait", ""),  # 旧形式互換
        "link_requirement": specs.get("Link Requirement", ""),
        "source_title":  specs.get("Source Title", ""),
        "zone":          specs.get("Zone", ""),
        "set_name":      record.get("set_name", ""),
        "set_name_official": record.get("set_name_official", ""),
        "get_info_jp":   record.get("set_name_official", ""),
        "card_text":     specs.get("card_text", ""),
        "card_text_jp":  specs.get("card_text_jp", ""),
        "language":      record.get("language"),
        "card_set_id":   record.get("card_set_id"),
        "regulations":   specs.get("regulations", []),
        "legality":      specs.get("legality", {}),
        "illustrator":   specs.get("illustrator"),
        "images":        record.get("images", []),
    }
    return _apply_ebay_fields(legacy, record, "gundam_tcg")


def lookup_gundam(
    brand: str,
    card_number: str,
    subject: str = "",
    verbose: bool = True,
) -> Optional[dict]:
    """Gundam Card Game カードを iMakCatalog DB から ID 完全一致で lookup."""
    if not card_number:
        return None
    set_code = extract_set_code_from_brand_gundam(brand)
    if not set_code:
        if verbose:
            print(f"    ⚠️ Gundam set_code 抽出失敗: brand={brand!r}")
        return None

    base_pid = f"{set_code}-{card_number}"

    # 2026-07-10: PB01 プレミアムグッズセット由来 cert は base(starter deck print)でなく
    #   _PB01 parallel record を優先 (set_name が premium goods = C:Set 正確化)。
    record = None
    if "PREMIUM GOODS" in (brand or "").upper():
        cand = api.lookup(GUNDAM_CATEGORY, f"{base_pid}_PB01")
        if cand and _record_name_matches_subject(cand, subject):
            record = cand
            if verbose:
                print(f"    🎯 iMakCatalog (Gundam) hit (PB01 premium goods): {base_pid}_PB01")

    if record is None:
        record = api.lookup(GUNDAM_CATEGORY, base_pid)
    if record and not _record_name_matches_subject(record, subject):
        if verbose:
            print(f"    ⚠️ iMakCatalog (Gundam) ID hit {base_pid} ({record['name']}) "
                  f"だが PSA Subject {subject!r} と名前不一致 → reject")
        record = None

    if record is None:
        for suffix in _variant_candidates_gundam(subject):
            cand = api.lookup(GUNDAM_CATEGORY, f"{base_pid}_{suffix}")
            if cand and _record_name_matches_subject(cand, subject):
                record = cand
                if verbose:
                    print(f"    🎯 iMakCatalog (Gundam) hit (variant): {base_pid}_{suffix}")
                break

    if record is None:
        if verbose:
            print(f"    ⚠️ iMakCatalog (Gundam) 未登録 or 名前不一致: {base_pid} → Skip "
                  f"(subject={subject!r})")
        return None

    if verbose and "_" not in record["product_id"]:
        print(f"    🎯 iMakCatalog (Gundam) hit: {record['product_id']} "
              f"{record['name']} ({record['specs'].get('Card Type', '?')}, "
              f"rarity={record['specs'].get('Rarity', '?')!r})")

    return _to_legacy_dict_gundam(record)


def set_code_to_ebay_name_gundam(set_value: str) -> str:
    """Gundam 用 set_code/set 文字列 → eBay 公式名."""
    if not set_value:
        return set_value
    ebay = api.to_ebay_value(GUNDAM_CATEGORY, "set_code", set_value)
    if ebay:
        return ebay
    m = re.search(r"[\[【]([A-Z][A-Z0-9-]*)[\]】]", set_value)
    if m:
        ebay = api.to_ebay_value(GUNDAM_CATEGORY, "set_code", m.group(1))
        if ebay:
            return ebay
    ebay = api.to_ebay_value(GUNDAM_CATEGORY, "set", set_value)
    return ebay if ebay else set_value


# ============================================================================
# ============================================================================
# Dragon Ball Super Card Game (Fusion World) (game_id=10/11)
# ============================================================================
# ============================================================================
DRAGONBALL_CATEGORY = "dragonball_scg"


def extract_set_code_from_brand_dragonball(brand: str) -> Optional[str]:
    """PSA Brand → DBSCG 公式 set_code 抽出.
    例:
      'DRAGON BALL SUPER FUSION WORLD JAPANESE FB02 BLAZING AURA' → 'FB02'
      'DRAGON BALL FUSION WORLD JAPANESE FS04 STARTER FRIEZA'      → 'FS04'
    """
    if not brand:
        return None
    b = brand.upper()
    m = re.search(r"\b(FB\d+|FS\d+|SB\d+|FP\d+)\b", b)
    if m:
        return m.group(1)
    # set 名キーワード逆引き (literal名のみで code token 無し)。2026-06-10 HQ依頼 db_gundam_setmap。
    #   MANGA BOOSTER NN → SBNN / ENERGY MARKER PACK NN → E0N (catalog: SB01/SB02, E01-E03)。
    m2 = re.search(r"MANGA\s*BOOSTER\s*(\d+)", b)
    if m2:
        return f"SB{int(m2.group(1)):02d}"
    m3 = re.search(r"ENERGY\s*MARKER\s*PACK\s*(\d+)", b)
    if m3:
        return f"E{int(m3.group(1)):02d}"
    if any(k in b for k in ("PROMO", "PROMOS", "TOURNAMENT", "CHAMPIONSHIP")):
        return "FP"  # DBSCG promo prefix (要確認)
    return None


# DBSCG variant suffix 候補
_DRAGONBALL_VARIANT_HINT_TO_SUFFIXES: dict[str, list[str]] = {
    "ALTERNATE ART":  ["Leader_F_PARA", "PARA", "Leader_F_SUPERPARA"],
    "ALT ART":        ["Leader_F_PARA", "PARA"],
    "PARALLEL":       ["PARA", "Leader_F_PARA"],
    "SUPER PARALLEL": ["SUPERPARA", "Leader_F_SUPERPARA"],
    "SPECIAL":        ["SUPERPARA", "PARA"],
    "FOIL":           ["Leader_F", "PARA"],
}


def _variant_candidates_dragonball(subject: str) -> list[str]:
    if not subject:
        return []
    subj = subject.upper()
    seen: set[str] = set()
    out: list[str] = []
    for hint, suffixes in _DRAGONBALL_VARIANT_HINT_TO_SUFFIXES.items():
        if hint in subj:
            for s in suffixes:
                if s not in seen:
                    seen.add(s)
                    out.append(s)
    return out


def _to_legacy_dict_dragonball(record: dict) -> dict:
    """DBSCG 用 record → psa_to_csv 互換 dict."""
    specs = record.get("specs") or {}
    legacy = {
        # 旧 bandai_tcg_plus.fetch_card(game='dragonball') 互換
        "card_name":     record.get("name", ""),
        "card_id":       record.get("product_id", ""),
        "card_number":   record.get("product_id", "").split("_")[0],
        "name_en":       record.get("name_en") or record.get("name", ""),
        "name_jp":       record.get("name_jp"),
        "card_type":     specs.get("Type", ""),         # DBSCG: 'Type' = card type
        "type_en":       specs.get("Type", ""),
        "rarity":        specs.get("Rarity", ""),
        "rarity_en":     specs.get("Rarity", ""),
        "color":         specs.get("Color", ""),
        "color_en":      specs.get("Color", ""),
        "power":         specs.get("Power", ""),
        "cost":          specs.get("Energy", ""),       # DBSCG: 'Energy' = cost
        "specified_cost": specs.get("Specified Cost", ""),
        "combo_power":   specs.get("Combo power", ""),
        "special_trait": specs.get("Special Trait", ""),
        "feature_jp":    specs.get("Special Trait", ""),
        "set_name":      record.get("set_name", ""),
        "set_name_official": record.get("set_name_official", ""),
        "get_info_jp":   record.get("set_name_official", ""),
        "card_text":     specs.get("card_text", ""),
        "card_text_jp":  specs.get("card_text_jp", ""),
        "language":      record.get("language"),
        "card_set_id":   record.get("card_set_id"),
        "regulations":   specs.get("regulations", []),
        "legality":      specs.get("legality", {}),
        "illustrator":   specs.get("illustrator"),
        "images":        record.get("images", []),
    }
    return _apply_ebay_fields(legacy, record, "dragonball_scg")


def lookup_dragonball(
    brand: str,
    card_number: str,
    subject: str = "",
    verbose: bool = True,
) -> Optional[dict]:
    """Dragon Ball SCG カードを iMakCatalog DB から ID 完全一致で lookup."""
    if not card_number:
        return None
    # card_number が既に set-prefix 込みの full product_id 形 (e.g. 'FS02-04' / 'FB02-001' /
    # 'E01-02'=Energy Marker / 'E-04' / 'FP-024') の場合、それ自体で exact lookup を試す.
    # alt-art 等は _p1 variant を優先 (E01-02 ALTERNATE ART → E01-02_p1).
    if re.match(r"^[A-Z]{1,3}\d*-\w", card_number, re.IGNORECASE):
        full_candidates = [f"{card_number}_{suf}" for suf in _variant_candidates(subject)]
        full_candidates.append(card_number)   # base は最後 (variant 優先)
        for pid in full_candidates:
            record = api.lookup(DRAGONBALL_CATEGORY, pid)
            if record and _record_name_matches_subject(record, subject):
                if verbose:
                    print(f"    🎯 iMakCatalog (DBSCG) hit (full pid in card_number): {pid}")
                return _to_legacy_dict_dragonball(record)
        # fall through to normal logic for further attempts

    set_code = extract_set_code_from_brand_dragonball(brand)
    if not set_code:
        if verbose:
            print(f"    ⚠️ DBSCG set_code 抽出失敗: brand={brand!r}")
        return None

    # card_number が既に set_code prefix を含む場合の二重接頭辞回避.
    #   例: set_code='E01', card_number='E01-02' → base_pid='E01-E01-02' (誤) を防ぐ.
    #   PSA CardNumber 欄に "E01-02"/"E-04" 等の full pid 形が入る Energy Marker 系。
    if card_number.upper().startswith(set_code.upper() + "-"):
        base_pid = card_number
    else:
        base_pid = f"{set_code}-{card_number}"

    record = api.lookup(DRAGONBALL_CATEGORY, base_pid)
    if record and not _record_name_matches_subject(record, subject):
        if verbose:
            print(f"    ⚠️ iMakCatalog (DBSCG) ID hit {base_pid} ({record['name']}) "
                  f"だが PSA Subject {subject!r} と名前不一致 → reject")
        record = None

    if record is None:
        for suffix in _variant_candidates_dragonball(subject):
            cand = api.lookup(DRAGONBALL_CATEGORY, f"{base_pid}_{suffix}")
            if cand and _record_name_matches_subject(cand, subject):
                record = cand
                if verbose:
                    print(f"    🎯 iMakCatalog (DBSCG) hit (variant): {base_pid}_{suffix}")
                break

    if record is None:
        if verbose:
            print(f"    ⚠️ iMakCatalog (DBSCG) 未登録 or 名前不一致: {base_pid} → Skip "
                  f"(subject={subject!r})")
        return None

    if verbose and "_" not in record["product_id"]:
        print(f"    🎯 iMakCatalog (DBSCG) hit: {record['product_id']} "
              f"{record['name']} ({record['specs'].get('Type', '?')}, "
              f"rarity={record['specs'].get('Rarity', '?')!r})")

    return _to_legacy_dict_dragonball(record)


def set_code_to_ebay_name_dragonball(set_value: str) -> str:
    """DBSCG 用 set_code/set 文字列 → eBay 公式名."""
    if not set_value:
        return set_value
    ebay = api.to_ebay_value(DRAGONBALL_CATEGORY, "set_code", set_value)
    if ebay:
        return ebay
    m = re.search(r"[\[【]([A-Z][A-Z0-9-]*)[\]】]", set_value)
    if m:
        ebay = api.to_ebay_value(DRAGONBALL_CATEGORY, "set_code", m.group(1))
        if ebay:
            return ebay
    ebay = api.to_ebay_value(DRAGONBALL_CATEGORY, "set", set_value)
    return ebay if ebay else set_value


# ============================================================================
# ============================================================================
# Pokemon TCG (Japanese, pokemon-card.com)
# ============================================================================
# ============================================================================
POKEMON_CATEGORY = "pokemon_tcg"


# PSA Brand に set_code が含まれず set 名のみの場合の逆引きマップ.
# 出典: 各 set の公式日本語名 + 対応 set_code (image_url 由来).
# 新弾追加時は本マップにも追記.
_POKEMON_SET_NAME_TO_CODE: dict[str, str] = {
    # --- 2026-06-07 追加: PSA英語セット名→code 解決漏れ (既存カードを未収録誤判定していた根治) ---
    #     HQ依頼 requests/2026-06-07_psa_adapter_pokemon_setcode_resolution.md
    #     キーワード in 判定なので英語セット名そのままで可。BW3/BW8/XY11 は2デッキ混在で
    #     code 一意でない (番号で本体に当たればOK、外れたら subject 名照合に委ねる)。
    "ALTER GENESIS":               "SM12",
    "VMAX RISING":                 "S1a",
    "REMIX BOUT":                  "SM11a",
    "DREAM LEAGUE":                "SM11b",
    "FACING A NEW TRIAL":          "SM2p",
    "DARKNESS THAT CONSUMES LIGHT": "SM3N",
    "AWAKENED HEROES":             "SM4S",
    "DRAGON STORM":                "SM6a",
    "THUNDERCLAP SPARK":           "SM7a",
    "FAIRY RISE":                  "SM7b",
    "DARK ORDER":                  "SM8a",
    "NIGHT UNISON":                "SM9a",
    "FULL METAL WALL":             "SM9b",
    "PSYCHO DRIVE":                "BW3",
    "HAIL BLIZZARD":               "BW3",
    "SPIRAL FORCE":                "BW8",
    "THUNDER KNUCKLE":             "BW8",
    "FEVER-BURST FIGHTER":         "XY11",
    "CRUEL TRAITOR":               "XY11",
    "PEERLESS FIGHTERS":           "S5a",   # 双璧のファイター(英 Battle Styles)の PSA literal表記
    "PEERLESS FIGHTER":            "S5a",
    "FUSION ARTS":                 "S8",    # フュージョンアーツ(英 Fusion Strike)の PSA表記
    "REBELLION CRASH":             "S2",    # 反逆クラッシュ(英 Rebel Clash)の PSA表記
    # --- SwSh全弾 体系整備 (2026-06-10, HQ依頼: もぐら叩き終了。日本語セット名の PSA literal英名) ---
    #     真値: Bulbapedia/PSA/StockX 裏取り。SWORD/SHIELD(S1W/S1H)は era名"SWORD & SHIELD"と
    #     衝突する(全SwSh brandが含む)ため bare "SWORD"/"SHIELD" 単独 key は禁止。
    #     2026-06-21 HQ承認: base Sword/Shield は **era名込みの限定フレーズ** key で安全に解決
    #     (他SwSh brand "SWORD & SHIELD <expansion>" には部分一致しない)。cert S1W-066 ウッウV 実在。
    "SWORD & SHIELD SWORD":        "S1W",   # 拡張パック「ソード」 base set
    "SWORD & SHIELD SHIELD":       "S1H",   # 拡張パック「シールド」 base set
    "INFINITY ZONE":               "S3",    # ムゲンゾーン (英 Darkness Ablaze)
    "EXPLOSIVE WALKER":            "S2a",   # 爆炎ウォーカー
    "LEGENDARY HEARTBEAT":         "S3a",   # 伝説の鼓動
    "ASTONISHING VOLT TACKLE":     "S4",    # 仰天のボルテッカー (英 Vivid Voltage)
    "SINGLE STRIKE MASTER":        "S5I",   # 一撃マスター (英 Battle Styles 系)
    "RAPID STRIKE MASTER":         "S5R",   # 連撃マスター
    "SILVER LANCE":                "S6H",   # 白銀のランス (英 Chilling Reign 系)
    "JET-BLACK SPIRIT":            "S6K",   # 漆黒のガイスト (英 Chilling Reign) ※HQ実機確定 cert143730283
    "SKYSCRAPING PERFECT":         "S7D",   # 摩天パーフェクト (PERFECT/PERFECTION 両表記を包含)
    "BLUE SKY STREAM":             "S7R",   # 蒼空ストリーム (英 Evolving Skies)
    "POKEMON GO":                  "S10b",  # Pokémon GO
    # Sword & Shield
    # 2026-06-12 REVIEW (cert 142931332 PIKACHU V 25TH ANNIV GOLDEN BOX #005):
    #   25周年ゴールデンボックスは S8a の通常弾でなく専用サブセット "S8a-G" (全15枚).
    #   plain S8a-005=Lugia と衝突するため GOLDEN BOX は必ず S8a-G に振る。
    #   "25TH ANNIVERSARY COLLECTION" (=S8a) より前に置き、both含む brand でも GOLDEN BOX を優先。
    #   S8a-G prefix は golden box 専用のため番号一致=必ず golden box カード (over-fire 不能)。
    #   注: PSA が "GOLDEN BOX" を subject 側に置く cert では brand 単独参照の本 path は no-op
    #       (fail-closed)。その場合は raw cert で要確認。
    "GOLDEN BOX":                  "S8a-G",
    # 2026-06-12 (cert 77429277 Shining Magikarp): プロモカードパック 25th ANNIVERSARY edition = S8a-P.
    #   HQ raw dump 確認: brand = "POKEMON JAPANESE PROMO CARD PACK 25TH ANNIVERSARY EDITION"
    #   (= brand 側にあるので本 brand-path で配線可。Pikachu Golden Box の subject 側問題とは別)。
    #   "25TH ANNIVERSARY COLLECTION"(=S8a) より前に置き、長い方を優先 substring match。
    "PROMO CARD PACK 25TH ANNIVERSARY EDITION": "S8a-P",
    "25TH ANNIVERSARY COLLECTION": "S8a",
    "VSTAR UNIVERSE":              "S12a",
    "VMAX CLIMAX":                 "S8b",
    "SHINY STAR V":                "S4a",
    "EEVEE HEROES":                "S6a",
    "STAR BIRTH":                  "S9",
    "BATTLE REGION":               "S9a",
    "TIME GAZER":                  "S10D",
    "SPACE JUGGLER":               "S10P",
    "DARK PHANTASMA":              "S10a",
    "LOST ABYSS":                  "S11",
    "INCANDESCENT ARCANA":         "S11a",
    "PARADIGM TRIGGER":            "S12",
    # Scarlet & Violet
    "SHINY TREASURE EX":           "SV4a",
    "TERASTAL FESTIVAL EX":        "SV8a",
    "POKEMON 151":                 "SV2a",
    "RULER OF THE BLACK FLAME":    "SV3",
    "RAGING SURF":                 "SV3a",
    "FUTURE FLASH":                "SV4",
    "WILD FORCE":                  "SV5K",
    "CYBER JUDGE":                 "SV5M",
    "CRIMSON HAZE":                "SV5a",
    "MASK OF CHANGE":              "SV6",
    "NIGHT WANDERER":              "SV6a",
    "STELLAR MIRACLE":             "SV7",
    "PARADISE DRAGONA":            "SV7a",
    "SUPER ELECTRIC BREAKER":      "SV8",
    "BATTLE PARTNERS":             "SV9",
    "HEAT WAVE ARENA":             "SV9a",
    "ROCKET GANG":                 "SV10",
    "BLACK BOLT":                  "SV11B",
    "WHITE FLARE":                 "SV11W",
    # Mega
    "MEGA DREAM EX":               "M2a",
    # Sun & Moon
    "TAG ALL STARS":               "SM12a",
    "TAG TEAM":                    "SM12a",
    "ALTER GENESIS":               "SM12",   # オルタージェネシス (PSA: 'SUN & MOON ALTER GENESIS')
    "GX ULTRA SHINY":              "SM8b",
    "ULTRA SHINY GX":              "SM8b",   # PSA 語順違い ('...ULTRA SHINY GX'), cert74118843 Articuno GX 214 (2026-06-10)
    "GX BATTLE BOOST":             "SM4p",
    "THE BEST OF XY":              "XY",
    # --- 2026-06-15 TCG resolver gap batch (catalog 実在裏取り済・索引のみ追加) ---
    "MIRACLE TWINS":               "SM11",   # ミラクルツイン (SM11-069=Dragonite-GX 実在)
    "SKY-SPLITTING CHARISMA":      "SM7",    # 裂空のカリスマ (SM7-103=Tate & Liza 実在)
    "AMAZING VOLT TACKLE":         "S4",     # 仰天のボルテッカー (S4-030=Pikachu V / S4-108=Aegislash V 実在)
    # --- 2026-06-19 HQ cert dump 確証済 (psa_3unresolved_raw_cert_request_response) ---
    "EXTRA REGULATION BOX":        "BW",     # エクストラレギュレーションBOX(2019). cert140362929 Zoroark 014=BW-014 実在(公式収録確認, BW-001..048=本BOX)
    "EMERALD BREAK":               "XY6-B",  # エメラルドブレイク[XY6]. cert119816956 Gallade-EX 030=XY6-B-030 実在(base #001-078 は catalog で XY6-B-NNN 体系)。※高番EX #079+ は XY6-NNN のため本索引では解決せず=fail-closed(誤解決はしない)
    "NATIONAL BEGINNING":          "HSZm",   # BLACK & WHITE NATIONAL BEGINNING=BWはじめてセット全国図鑑版. cert145542066 Voltorb 014=HSZm-014 実在
    # --- 2026-06-26 HQ PSA NG followup: EXPANSION 20TH ANNIVERSARY → CP6 (cert135877490 Haunter #046=CP6-046実在) ---
    #   注: catalog は同セットを CP6-NNN(91枚, PSA番号一致) と 20th-NNN(74枚, 別番号=Tauros#046) の二重コードで保持。
    #   PSA brand 'EXPANSION 20TH ANNIVERSARY' の印刷番号は CP6 体系と一致するため CP6 を採用("25TH ANNIVERSARY COLLECTION"=S8a と非衝突)。
    "20TH ANNIVERSARY":            "CP6",
    # --- 2026-06-22 pdca/auto_add 索引不備 5件 (catalog 実在を実機確認・cardは存在、索引のみ欠落) ---
    "BANDIT RING":                 "XY7-B",  # バンデットリング[XY7]. XY7-B-061 Meowth 実在
    "PHANTOM GATE":                "XY4",    # ファントムゲート[XY4]. XY4-089 Manectric-EX 実在
    "PREMIUM CHAMPION PACK":       "CP4",    # プレミアムチャンピオンパック(CP4). CP4-054 Wobbuffet 実在
    "RED FLASH":                   "XY8-Br", # 赤い閃光[XY8](青い衝撃=XY8-Bb と対). XY8-Br-056 Houndoom Spirit Link 実在
    "BLUE SHOCK":                  "XY8-Bb", # 青い衝撃[XY8](赤い閃光=XY8-Br と対). XY8-Bb-001..064 実在(set索引). 注: FA secret #061(M Glalie EX)は未scrape=別途catalog_add
    "DOUBLE BLAZE":                "SM10",   # ダブルブレイズ[SM10]. SM10-033 Gengar 実在(cert 2026-06-27)
    "TAG BOLT":                    "SM9",    # タッグボルト[SM9]. SM9-038 Gengar & Mimikyu-GX 実在(cert 2026-06-30)
    "ULTRADIMENSIONAL BEASTS":     "SM4A",   # 超次元の暴獣[SM4A]. SM4A-051 Gyarados-GX 実在
    # --- 2026-06-10 PSA脱落6件 set-map (records 実在・索引のみ。真値=catalog set_name 裏取り) ---
    "SKY LEGEND":                  "SM10b",  # スカイレジェンド (cert109940063 Lillie 053=SM10b-053 実在)
    # ⚠️ 順序大事: より具体的な "...BATTLE COLLECTION" を plain "START DECK 100" より先に置く。
    #   スタートデッキ100(SI, /414) と スタートデッキ100バトルコレクション(MC, /742) は別set。
    #   両者とも #227 が存在し番号衝突する (SI-227=カバルドン / MC-227=ピカチュウex)。
    #   PSA brand "MC-START DECK 100 BATTLE COLLECTION" は MC に解決させる
    #   (公式裏取り 2026-06-15 card/48943 ピカチュウex 227/742, card/48717 規制マーク=MC)。
    "START DECK 100 BATTLE COLLECTION": "MC",  # スタートデッキ100バトルコレクション (cert149832553 Pikachu ex 227=MC-227)
    "START DECK 100":              "SI",     # スタートデッキ100 (cert139561995 Pikachu 127=SI-127 実在)
    # --- 2026-06-11 High-Class Deck (SwSh ハイクラスデッキ) — records 実在・索引のみ ---
    "GENGAR VMAX HIGH-CLASS DECK":   "SGG",  # ゲンガーVMAXハイクラスデッキ (cert139761896 #002=SGG-002 実在)
    "INTELEON VMAX HIGH-CLASS DECK": "SGI",  # インテレオンVMAXハイクラスデッキ (SGI-* 実在・先回り)
    # --- 2026-06-11 Gap-A 先回り: SM期拡張 (records実在・set_name裏取り。unique名のみ=誤マッチ非対称安全) ---
    #     keyword は distinctive 一意名。最悪 PSA literal 相違でも no-op skip(誤set解決にならない)。
    #     paired sub-set(Collection/Ultra の Sun/Moon)は Sun≠Moon で各々一意のため個別に可。
    "SHINING LEGENDS":   "SM3p",   # ひかる伝説
    "CHAMPION ROAD":     "SM6b",   # チャンピオンロード
    # --- 2026-07-10 resolver mapping gap 解消 (records実在・set一意) ---
    "SOULSILVER COLLECTION": "L1-Bss",  # ソウルシルバーコレクション (L1-Bss-021=ニョロトノ 実在)
    "HEARTGOLD COLLECTION":  "L1-Bhg",  # ハートゴールドコレクション (L1-Bhg-001=ビードル 実在)
    "POKEKYUN COLLECTION":   "CP3",     # ポケキュンコレクション (CP3-032=ミツル 実在)
    "DREAM SHINE COLLECTION": "CP5",    # 幻・伝説ドリームキラコレクション (CP5-014=ケルディオ 実在)
    "GG END":            "SM10a",  # ジージーエンド
    "DETECTIVE PIKACHU": "SMP2",   # 名探偵ピカチュウ (スペシャルパック)
    "ULTRA MOON":        "SM5M",   # ウルトラムーン
    "ULTRA SUN":         "SM5S",   # ウルトラサン
    "ULTRA FORCE":       "SM5p",   # ウルトラフォース
    "COLLECTION MOON":   "SM1M",   # コレクション ムーン
    "COLLECTION SUN":    "SM1S",   # コレクション サン
}


def extract_set_code_from_brand_pokemon(brand: str) -> Optional[str]:
    """PSA Brand → Pokemon 公式 set_code 抽出.

    Pokemon set codes は多様で混在 (M2a, S8a, S9a, SV1, SV2a, sv5K 等).
    大文字小文字も微妙 (公式 image_url='M2a', PSA brand='M2A').

    抽出順:
      1) Brand に set_code 文字列が直接含まれる (例: 'M2A', 'SV8A') → 末尾英字小文字化
      2) Brand に set 名キーワードが含まれる (例: '25TH ANNIVERSARY COLLECTION' → 'S8a')
      3) PROMO/PROMOS/JUMBO → 'P'
      4) None
    """
    if not brand:
        return None
    b = brand.upper()
    # 0a) McDONALD'S Promo は番号衝突のため M-P/SMP-* 等の通常 promo lookup を skip.
    #     catalog に McDONALD'S 専用 set_code (MCD-*) 投入は未対応のため None 返却.
    #     誤マッチ防止: 例 M-P-020 = ウエートレス を Pikachu McDonald's #020 と
    #     誤って結びつけることを防ぐ.
    if re.search(r"\bMC?DONALDS?(?:'?S)?\b", b):
        return None
    # 0b) PSA promo brand 表記 → catalog の set_code に正規化
    #    PSA は規制ロゴ (e.g. 'MP1.gif', 'SP1.gif') から brand 生成しているため
    #    catalog の image_url 由来 set_code (M-P / S-P / SV-P) と乖離.
    #    例: PSA brand 'MP1' → catalog set_code 'M-P' (Mega Promo, ピカチュウex 49592 等)
    #    実証: 2026-05-09 missing_models.csv に MP1-006 (Pikachu ex コロチャオ) 通知 →
    #          catalog 内 M-P-006 (=card 49592) と確認済
    #    順序大事: より具体的な pattern を先に置く (SVP1 が SP1 と SV1 に matches を防ぐ)
    psa_promo_to_catalog = [
        # --- dash 抜き連番 (規制ロゴ filename 由来) ---
        (r"\bSVP\d+\b",       "SV-P"),  # Scarlet & Violet Promo
        (r"\bSP\d+\b",        "S-P"),   # Sword & Shield Promo
        (r"\bMP\d+\b",        "M-P"),   # Mega Promo
        # --- dash 入り直接表記 (PSA brand に "M-P" / "S-P" / "SV-P" がそのまま含まれる) ---
        (r"\bSV-P\b",         "SV-P"),
        (r"\bS-P\b",          "S-P"),
        (r"\bM-P\b",          "M-P"),
        # --- set 名キーワード ---
        (r"\bSM\s+PROMOS?\b", "SM-P"),  # Sun & Moon Promo (PSA: 'SM PROMO'). 2026-06-11 Gap-B: catalog を SM-P-NNN 正順統一したため SMP→SM-P
        (r"\bXY\s+PROMOS?\b", "XYP"),   # X & Y Promo
        (r"\bBW\s+PROMOS?\b", "BWP"),   # Black & White Promo
        (r"\bDP\s+PROMOS?\b", "DPP"),   # Diamond & Pearl Promo
        # --- space区切り promo (dash/digit無し) 2026-06-10: 'S PROMO' が generic PROMO→'P' に落ち
        #     P-288 を誤引きして脱落していた根治。SV を S より先に置く (語順衝突防止)。
        #     SM/XY/BW は上で処理済 ('S\s+PROMO' は 'SM PROMO' に非マッチ=S直後がM) ので安全。
        (r"\bSV\s+PROMOS?\b", "SV-P"),  # Scarlet & Violet Promo (PSA: 'SV PROMO')
        (r"\bS\s+PROMOS?\b",  "S-P"),   # Sword & Shield Promo (PSA: 'S PROMO') cert131214875/126900241
    ]
    for pattern, code in psa_promo_to_catalog:
        if re.search(pattern, b):
            return code
    # 0c) 数字を持たない starter/special set code (= digit 正規表現で取れない).
    #    PSA brand に code が dash 付きで明示されるパターンのみ安全に拾う.
    #    例: 'POKEMON JAPANESE MBD-MEGA STARTER SET MEGA DIANCIE EX' → 'MBD' (catalog: MBD-022 メロエッタ等)
    #    新 starter set 追加時はここに 1 行追記 (誤マッチ防止に \b...\b で token 限定)。
    letter_only_codes = [
        (r"\bMBD\b", "MBD"),   # メガブレイブ Mega Diancie EX スターターセット
    ]
    for pattern, code in letter_only_codes:
        if re.search(pattern, b):
            return code
    # 1) Standard alphanumeric set codes
    m = re.search(r"\b(SV[0-9]+[A-Z]?|S[0-9]+[A-Z]?|M[0-9]+[A-Z]?|SM[0-9]+|XY[0-9]+|BW[0-9]+|HGSS[0-9]?|DP[0-9]+)\b", b)
    if m:
        code = m.group(1)
        m2 = re.match(r"^([A-Z]+\d+)([A-Z])$", code)
        if m2:
            return m2.group(1) + m2.group(2).lower()
        return code
    # 2) Set name キーワードからの逆引き
    for keyword, code in _POKEMON_SET_NAME_TO_CODE.items():
        if keyword in b:
            return code
    # 3) Promo prefix
    if any(k in b for k in ("PROMO", "PROMOS", "JUMBO")):
        return "P"
    return None


def _to_legacy_dict_pokemon(record: dict) -> dict:
    """Pokemon 用 record → psa_to_csv 互換 dict.

    旧 pokemon_card_jp.fetch_card 互換フィールド + iMakCatalog 拡張.
    """
    specs = record.get("specs") or {}
    # variant suffix を剥がした card_number (e.g., 'M2a-240' → '240')
    # multi-segment set_code 対応 (M-P-006 / SV-P-XXX / S-P-XXX) — 末尾 -<digits> で分割
    pid = record.get("product_id", "")
    _parts = pid.rsplit("-", 1)
    if len(_parts) == 2 and _parts[1].isdigit():
        set_code_part = _parts[0]
        card_number_only = _parts[1]
    elif "-" in pid:
        set_code_part, card_number_only = pid.split("-", 1)
    else:
        set_code_part, card_number_only = "", pid

    legacy = {
        # 旧 pokemon_card_jp 互換
        "name_jp":            record.get("name", ""),
        # 2026-05-11: name_en バルク翻訳 (21,855 件) 投入後、catalog 側 name_en を優先.
        # なければ name (日本語) にフォールバック.
        "name_en":            record.get("name_en") or record.get("name", ""),
        "card_number":        card_number_only,
        "card_number_full":   specs.get("card_number_text", card_number_only),
        "card_number_total":  specs.get("card_number_total", ""),
        "set_code":           set_code_part,
        "rarity_jp":          specs.get("rarity", ""),
        "rarity_en":          specs.get("rarity", ""),
        "rarity":             specs.get("rarity", ""),
        "type_jp":            specs.get("type_jp", ""),
        "type_en":            specs.get("type_en", ""),
        "hp":                 specs.get("hp", ""),
        "stage":              specs.get("stage", ""),
        "weakness":           specs.get("weakness", ""),
        "resistance":         specs.get("resistance", ""),
        "retreat":            specs.get("retreat", ""),
        "regulation":         specs.get("regulation", ""),
        "illustrator":        specs.get("illustrator"),
        "card_type":          specs.get("card_type", ""),    # Pokémon / Trainer / Energy
        # iMakCatalog 拡張
        "card_id":            pid,
        "set_name":           record.get("set_name", ""),
        "set_name_official":  record.get("set_name_official", ""),
        "language":           record.get("language"),
        "images":             record.get("images", []),
    }
    return _apply_ebay_fields(legacy, record, "pokemon_tcg")


# Pokemon Promo set codes (FA/Promo の hint で優先選択する候補)
# 各シリーズの promo 系を網羅:
#   S-P (Sword & Shield Promo), SV-P (Scarlet & Violet Promo), M-P (Mega Promo),
#   SMP (Sun & Moon Promo), XYP (X & Y Promo), BWP (Black & White Promo),
#   DPP (Diamond & Pearl Promo), SVD/SVM (SV special promo)
_POKEMON_PROMO_SET_CODES = ("S-P", "SV-P", "M-P", "SM-P", "XYP", "BWP", "DPP", "SVD", "SVM", "SC")


def _is_pokemon_promo_hint(subject: str) -> bool:
    """PSA Subject に FA / Full Art / Promo / Jumbo 等の promo 系ヒントがあるか.

    注意: 'ANNIVERSARY' に 'SAR' が部分一致するため SAR / AR は word boundary で照合.
    """
    if not subject:
        return False
    subj = subject.upper()
    # 部分一致 OK: FA/, FULL ART, PROMO, JUMBO, SPECIAL ART, JUMBO
    if any(k in subj for k in ("FA/", "FULL ART", "PROMO", "JUMBO", "SPECIAL ART")):
        return True
    # word boundary 必須: SAR, AR (ANNIVERSARY を誤検出しないため)
    if re.search(r"\b(SAR|AR)\b", subj):
        return True
    return False


def _name_matches_pokemon_subject(record: dict, subject: str) -> bool:
    """Pokemon 用名前検証. PSA Subject は英語、record.name は日本語なので
    JA→EN dict + 部分一致で緩めに照合.
    """
    if not subject:
        return True
    subj_up = subject.upper()
    name_jp = record.get("name_jp") or record.get("name") or ""
    # 簡易: PSA 英語 token と record 日本語名の交差を JA→EN dict で見る
    # フル実装は複雑なので、当面 name に PSA Subject の主要トークンを部分一致
    # でチェック (例: 'PIKACHU' subject ↔ 'ピカチュウ' name は照合できないが、
    # 'CHARIZARD' subject ↔ 'リザードン' は dict 必要 → 当面 OK と判定)
    # 安全側: name_jp が空 or unknown → True (rejection しない)
    return True   # Pokemon は ID 一致を信頼、name 検証は将来の拡張


def _set_code_lookup_variants(set_code: str) -> list[str]:
    """Pokemon set_code の lookup 候補リスト (大文字小文字 + 0↔O 取り違え正規化).

    PSA brand は数字0/英字O を取り違える (例 PSA「SV0M」=数字0、公式 catalog「SVOM」=英字O。
    Marnie set 全体 SVOM-001〜020 に影響). ID 完全一致 lookup 専用なので、誤候補は単に
    ヒットせず fail-closed. 元の set_code を最優先で試す (順序保持・重複除去).
    """
    if not set_code:
        return []
    seen: list[str] = []

    def _add(c: str):
        if c and c not in seen:
            seen.append(c)

    up = set_code.upper()
    ordered_bases = [set_code, up]
    if "0" in up:
        ordered_bases.append(up.replace("0", "O"))   # 数字0 → 英字O (SV0M → SVOM)
    if "O" in up:
        ordered_bases.append(up.replace("O", "0"))   # 英字O → 数字0 (逆方向救済)
    for b in ordered_bases:
        _add(b)
        _add(b.upper())
        _add(b.lower())
    return seen


def lookup_pokemon(
    brand: str,
    card_number: str,
    subject: str = "",
    verbose: bool = True,
) -> Optional[dict]:
    """Pokemon カードを iMakCatalog DB から ID 完全一致で lookup.

    手順:
      1) PSA Brand から set_code 抽出
      2) PSA Subject に FA/Promo ヒントあり → 先に promo set codes (S-P, SV-P 等) で試行
      3) base lookup `{set_code}-{card_number}`
      4) set_code 表記揺れ対応 (大文字/小文字)
    """
    if not card_number:
        return None
    # PSA card# は "NNN/TTT"(分母=set 総数)形式のことがある (例 '005/015')。
    # Pokemon の product_id は分子のみ (S8a-G-005) なので分母を除去して正規化。
    card_number = card_number.split("/")[0].strip()
    set_code = extract_set_code_from_brand_pokemon(brand)

    # 2026-06-13: subject 側 "GOLDEN BOX" 検出 (cert142931332 PIKACHU V 25TH ANNIV-GOLDEN BOX #005).
    #   25周年ゴールデンボックスは日本専用 subset S8a-G。PSA が "GOLDEN BOX" を **Subject 側**に
    #   置く cert では brand-path (_POKEMON_SET_NAME_TO_CODE "GOLDEN BOX":"S8a-G") が no-op に
    #   なり、brand からは "P"(promo) 等の別 set_code が出る。→ subject から直接 S8a-G に上書き。
    #   言語 gate: catalog S8a-G-* は日本語 record のため、brand が日本語 (JAPANESE/JPN) と
    #   明示されるときのみ適用。ASIA/KOREAN/CHINESE 版を日本語 record へ誤解決させない (fail-closed)。
    #   S8a-G prefix は golden box 専用 = 番号一致なら必ず golden box カード (over-fire 不能)。
    #   2026-07-05 (HQ依頼 cert142931332): 25th Golden Box は**日本専用 subset**(他言語版なし)。
    #   PSA が日本版 Golden Box を "POKEMON ASIA 25TH ANNIVERSARY PROMO" と誤ラベルする実例あり
    #   (subject に GOLDEN BOX は残る)。Golden Box に外国語版が存在しない以上、subject=GOLDEN BOX の
    #   ASIA brand は日本版 S8a-G で確定 → language gate に "ASIA 25TH ANNIVERSARY" を追加許可。
    #   誤resolve不能の根拠: (a) S8a-G は golden box 15枚専用 prefix、(b) ID完全一致(S8a-G-###実在時のみ)、
    #   (c) subject に GOLDEN BOX 必須。promo pack(S8a-P Dark Gyarados 等)は subject に GOLDEN BOX 無=不発。
    _gb_brand_ok = bool(re.search(r"\b(JAPAN(?:ESE)?|JPN)\b", (brand or "").upper())) or \
        ("ASIA 25TH ANNIVERSARY" in (brand or "").upper())
    if "GOLDEN BOX" in (subject or "").upper() and _gb_brand_ok:
        if verbose and set_code != "S8a-G":
            print(f"    🔁 Pokemon subject-path: 'GOLDEN BOX'+JP/ASIA brand → set_code "
                  f"{set_code!r}→'S8a-G' (brand={brand!r}, subject={subject!r})")
        set_code = "S8a-G"

    if not set_code:
        if verbose:
            print(f"    ⚠️ Pokemon set_code 抽出失敗: brand={brand!r}")
        return None

    base_pid = f"{set_code}-{card_number}"

    # 1. base lookup を先に行って、その record の name を「正しいキャラ」として確定.
    #    set_code は 大文字小文字 + 0↔O 取り違え (PSA brand「SV0M」=数字0 vs 公式 catalog
    #    「SVOM」=英字O) を正規化候補で試行. ID 完全一致のみなので誤候補は無害 (fail-closed).
    # card_number は 0埋め揺れも吸収 (PSA「7」 vs catalog「007」。例 SMP2-7 → SMP2-007).
    cn_variants = [card_number]
    if card_number.isdigit() and len(card_number) < 3:
        cn_variants.append(card_number.zfill(3))
    record = None
    for sc in _set_code_lookup_variants(set_code):
        for cn in cn_variants:
            record = api.lookup(POKEMON_CATEGORY, f"{sc}-{cn}")
            if record is not None:
                break
        if record is not None:
            break

    # 2. FA/Promo ヒントあり + base hit あり → promo set codes に **同名の record** があれば乗り換え
    #    (ANNIVERSARY の 'SAR' 部分一致や、無関係な S-P-XXX への誤マッチを防ぐ)
    if record is not None and _is_pokemon_promo_hint(subject):
        base_name_jp = record.get("name_jp") or record.get("name") or ""
        for promo_set in _POKEMON_PROMO_SET_CODES:
            promo_pid = f"{promo_set}-{card_number}"
            cand = api.lookup(POKEMON_CATEGORY, promo_pid)
            if not cand:
                continue
            cand_name_jp = cand.get("name_jp") or cand.get("name") or ""
            # 完全一致 (キャラ名同じ) のみ promo に切替
            if cand_name_jp == base_name_jp:
                record = cand
                if verbose:
                    print(f"    🎯 iMakCatalog (Pokemon) FA/promo upgrade: "
                          f"{base_pid} → {promo_pid} ({cand['name']}, subject FA hint)")
                break

    if record is None:
        if verbose:
            print(f"    ⚠️ iMakCatalog (Pokemon) 未登録: {base_pid} → Skip "
                  f"(subject={subject!r})")
        return None

    if verbose and record["product_id"] != "":
        # promo hit はすでにログ済 → base hit のみログ
        if not record["product_id"].startswith(tuple(f"{p}-" for p in _POKEMON_PROMO_SET_CODES)):
            print(f"    🎯 iMakCatalog (Pokemon) hit: {record['product_id']} "
                  f"{record['name']} (rarity={record['specs'].get('rarity', '?')!r}, "
                  f"hp={record['specs'].get('hp', '?')!r})")

    return _to_legacy_dict_pokemon(record)


def set_code_to_ebay_name_pokemon(set_value: str) -> str:
    """Pokemon 用 set_code/set 文字列 → eBay 公式名.

    Pokemon set_code は大文字小文字混在 (公式 image_url='M2a', PSA brand='M2A') のため
    複数表記を試行する.
    """
    if not set_value:
        return set_value
    candidates: list[str] = [set_value]
    # 末尾英字を小文字化したバリアント (例: 'M2A' → 'M2a')
    m_norm = re.match(r"^([A-Z]+\d+)([A-Z])$", set_value)
    if m_norm:
        candidates.append(m_norm.group(1) + m_norm.group(2).lower())
    # 末尾英字を大文字化 (逆方向)
    m_norm = re.match(r"^([A-Z]+\d+)([a-z])$", set_value)
    if m_norm:
        candidates.append(m_norm.group(1) + m_norm.group(2).upper())
    # 全大文字 / 全小文字
    if set_value != set_value.upper():
        candidates.append(set_value.upper())
    if set_value != set_value.lower():
        candidates.append(set_value.lower())

    for c in candidates:
        ebay = api.to_ebay_value(POKEMON_CATEGORY, "set_code", c)
        if ebay:
            return ebay
    # set 全文一致 fallback
    ebay = api.to_ebay_value(POKEMON_CATEGORY, "set", set_value)
    return ebay if ebay else set_value


# ============================================================================
# JA→EN character dict 拡張 (DBSCG 用キャラクター追加 — Phase 2 で必要に応じて拡充)
# ============================================================================
# 注: lookup_one_piece と共通の _record_name_matches_subject を使うため、
#     _JA_CHAR_TO_EN_TOKENS に DBSCG キャラを追加 (Goku/Vegeta 等) する形で拡張する.
_JA_CHAR_TO_EN_TOKENS.update({
    # Dragon Ball — JA-only プロモ向け
    "孫悟空":         {"GOKU", "SON"},
    "ベジータ":       {"VEGETA"},
    "孫悟飯":         {"GOHAN", "SON"},
    "ピッコロ":       {"PICCOLO"},
    "トランクス":     {"TRUNKS"},
    "クリリン":       {"KRILLIN"},
    "フリーザ":       {"FRIEZA"},
    "セル":           {"CELL"},
    "魔人ブウ":       {"MAJIN", "BUU"},
    "ブロリー":       {"BROLY"},
    "ゴジータ":       {"GOGETA"},
    "ベジット":       {"VEGITO"},
    "悟天":           {"GOTEN"},
    "亀仙人":         {"ROSHI", "MASTER"},
    "ヤムチャ":       {"YAMCHA"},
    "天津飯":         {"TIEN", "SHINHAN"},
    "チャオズ":       {"CHIAOTZU"},
    "餃子":           {"CHIAOTZU"},
    "ナッパ":         {"NAPPA"},
    "ラディッツ":     {"RADITZ"},
    "ザマス":         {"ZAMASU"},
    "ビルス":         {"BEERUS"},
    "ウイス":         {"WHIS"},
    "ジレン":         {"JIREN"},
    "シャロット":     {"SHALLOT"},

    # Gundam — JA-only プロモ向け (mecha + pilot)
    "アムロ・レイ":          {"AMURO", "RAY"},
    "シャア・アズナブル":    {"CHAR", "AZNABLE"},
    "ガンダム":              {"GUNDAM"},
    "ザク":                  {"ZAKU"},
    "ユニコーンガンダム":    {"UNICORN"},
    "バナージ・リンクス":    {"BANAGHER", "LINKS"},
    "刹那・F・セイエイ":     {"SETSUNA"},
    "ロックオン・ストラトス": {"LOCKON", "STRATOS"},
    "三日月・オーガス":      {"MIKAZUKI", "AUGUS"},
    "ガンダムバルバトス":    {"BARBATOS"},
    "ストライクガンダム":    {"STRIKE"},
    "フリーダムガンダム":    {"FREEDOM"},
    "キラ・ヤマト":          {"KIRA", "YAMATO"},
    "リソース":              {"RESOURCE"},   # Resource Promo (RP-009 等、PSA Subject 'RESOURCE ...')
})


# ============================================================================
# ============================================================================
# Yu-Gi-Oh! TCG (game = yugioh_tcg, source = ygoprodeck)
# ============================================================================
# ============================================================================
YUGIOH_CATEGORY = "yugioh_tcg"


def lookup_yugioh(
    brand: str,
    card_number: str,
    subject: str = "",
    verbose: bool = True,
) -> Optional[dict]:
    """Yu-Gi-Oh! card を catalog から名前 fuzzy match で lookup.

    YGO は Konami official ID が numeric (= 例 '89631139' Blue-Eyes WD).
    catalog の product_id は Konami ID だが、 PSA brand には Konami ID 含まれず、
    JP set code + JP card number 表記 (= 'MAGO-JP001' 等).

    戦略 (= 2026-05-26 設計):
      C 案 primary: PSA subject 名で catalog name_en LIKE 検索 → token 一致 verify
      A 案 secondary: PSA brand に set keyword (Legend of Blue Eyes 等) 含む時
                       → catalog primary_set_name 部分一致で絞り込み
      同名複数 hit → fail-closed reject (= missing_models.csv 通知)

    YGO は同名カード = 同 Konami ID (errata 除く) のため fuzzy match の信頼性高い.

    Args:
        brand: PSA brand 文字列 (例: 'YU-GI-OH! JAPANESE LB-01 LEGEND OF BLUE EYES')
        card_number: PSA card number (例: '001', 'LB-01-J001')
        subject: PSA Subject (例: 'BLUE-EYES WHITE DRAGON')
        verbose: True で stdout 進捗.

    Returns:
        catalog record dict (api.lookup() 戻り値) | None.
    """
    if not subject or not subject.strip():
        if verbose:
            print(f"    ⚠️ YGO: PSA subject 空、 fuzzy match 不可 → Skip")
        return None

    # subject 正規化: 大文字、 noise 除去 (= 'PSA 10' / 'ALT ART' 等)
    subj_upper = subject.upper().strip()
    # PSA 修飾語除去
    subj_clean = re.sub(r"\b(PSA|GEM|MINT|ALT|ART|ALTERNATE|SECRET|ULTRA|RARE|COMMON|UNCOMMON|FOIL|HOLO|PROMO|JAPANESE|JP|EN|ENGLISH)\b", " ", subj_upper)
    subj_clean = re.sub(r"\s+", " ", subj_clean).strip()
    if not subj_clean:
        if verbose:
            print(f"    ⚠️ YGO: subject 正規化後 空、 fuzzy match 不可 → Skip")
        return None

    # name_en LIKE 検索 (= catalog の全 YGO entry をスキャン、 token 一致)
    conn = api._connect()
    try:
        # tokens 抽出 (= 3 文字以上の単語)
        tokens = [t for t in re.split(r"[\s\-,.:'\"\(\)\[\]]+", subj_clean) if len(t) >= 3]
        if not tokens:
            return None
        # SQL LIKE で 最も特徴的な token (= 最長) で 1 次絞り込み
        anchor = sorted(tokens, key=len, reverse=True)[0]
        rows = conn.execute(
            "SELECT * FROM products WHERE category = ? AND UPPER(name_en) LIKE ?",
            (YUGIOH_CATEGORY, f"%{anchor}%"),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        if verbose:
            print(f"    ⚠️ YGO: catalog name_en に {anchor!r} を含む entry なし → Skip")
        return None

    # name_en と subject の **完全 token set 一致** のみ採用
    # (= 派生カード 'Malefic Blue-Eyes...' / 'Alternative...' を除外).
    # stopword (THE / OF / AND / 等) 除去後の set 等価で判定.
    _stopwords = {"THE", "OF", "AND", "A", "AN", "TO", "IN", "ON", "FOR", "WITH",
                   "OR", "AT", "BY"}
    def _name_token_set(s: str) -> set:
        return {t for t in re.findall(r"[A-Z0-9]+", (s or "").upper())
                if len(t) >= 2 and t not in _stopwords}
    subj_tokens_set = _name_token_set(subj_clean)
    matches: list = []
    for r in rows:
        name_tokens = _name_token_set(r["name_en"])
        if name_tokens and name_tokens == subj_tokens_set:
            matches.append(r)

    if not matches:
        if verbose:
            print(f"    ⚠️ YGO: subject tokens {sorted(subj_tokens_set)} と完全一致する "
                  f"name_en なし (anchor={anchor!r} candidates={len(rows)}) → Skip")
        return None

    # 同名複数 hit の場合: PSA brand に primary_set_name 部分一致あるか試行
    if len(matches) > 1:
        brand_upper = (brand or "").upper()
        narrow: list = []
        for r in matches:
            s = json.loads(r["specs"]) if r["specs"] else {}
            primary_set = (s.get("primary_set_name") or "").upper()
            if primary_set and primary_set in brand_upper:
                narrow.append(r)
        if len(narrow) == 1:
            matches = narrow
        elif len(narrow) > 1:
            matches = narrow  # まだ複数 → 下で fail-closed

    # 2026-05-30 Phase G FULL expansion 対応: 同名 hit 多数 (= 1 passcode × 多 variant) の場合、
    # base passcode (= numeric product_id) を優先採用。 variant 別 entry は別ロジックで対応。
    if len(matches) > 1:
        base_only = [m for m in matches if str(m["product_id"]).isdigit()]
        if len(base_only) == 1:
            matches = base_only

    if len(matches) == 1:
        record = api._row_to_dict(matches[0])
        if verbose:
            print(f"    🎯 iMakCatalog (YGO) hit: {record['product_id']} "
                  f"{record['name_en']!r} (Subject={subject!r} fuzzy match)")
        # eBay _ebay 系 field 適用 (= 2026-05-30 adapter 修正)
        return _apply_ebay_fields(dict(record), record, "yugioh_tcg")

    # 同名複数 (= errata 等) → fail-closed reject
    if verbose:
        print(f"    ⚠️ YGO: 同名 hit {len(matches)} 件、 fail-closed reject "
              f"(brand={brand!r}, subject={subject!r})")
        for r in matches[:5]:
            print(f"        - {r['product_id']}: {r['name_en']!r}")
    return None


# ============================================================================
# DON Card lookup (= ONE PIECE TCG special、 公式 card_number 不在)
# ============================================================================
def lookup_don(
    brand: str,
    subject: str,
    image_url: Optional[str] = None,
    verbose: bool = True,
) -> Optional[dict]:
    """DON カードを catalog から psa_subject_hint match で lookup.

    重要 = 公式 card_number 不在のため product_id は **Catalog 内部 dedup KEY**:
      - 形式: 'DON-{set_code}-{NNN}' (= 例 'DON-OP15-002')
      - eBay `C:Card Number` 列には **送信しない** (= caller 責務)
      - スプシ AI 列 (= dedup index) で使用

    戦略 (= 2026-05-27 設計、 2026-05-28 image_url 拡張):
      1) subject に 'DON' 含むか確認、 なければ None (= 非 DON card)
      2) brand から set_code 抽出 (= 例 'OP15') → catalog DON-OP15-* 候補絞り込み
      3) brand から抽出不能なら DON-* 全件を候補に
      4) 各候補の specs.psa_subject_hint keyword list を subject に対して scoring
      5) 最高 score の unique 1 件 → return
      6) tie + image_url あり → image hash disambiguate (= variants[].image_phash)
      7) tie + image_url 無し OR image disambiguate 失敗 → None (fail-closed)

    Args:
        brand: PSA Brand (例: 'ONE PIECE JAPANESE OP-15 ADVENTURE ON KAMIS ISLAND')
        subject: PSA Subject (例: 'DON!! CARD ALTERNATE ART GOLD')
        image_url: listing 画像 URL (= 2026-05-28 追加、 tie 時 disambiguate 用)
        verbose: True で stdout 進捗.

    Returns:
        record dict (内部 KEY 含む) | None (= fail-closed)
    """
    subj_upper = (subject or "").upper()
    if "DON" not in subj_upper:
        return None  # 非 DON card

    # 1) brand → set_code (= 'OP15' etc.)
    set_code_brand = extract_set_code_from_brand(brand)
    # extract_set_code_from_brand は 'OP-15' (dash 付) を取りこぼすため、 DON 専用 fallback:
    if not set_code_brand:
        m = re.search(r"\b(OP|ST|EB|PRB)\s*-\s*(\d+)\b", (brand or "").upper())
        if m:
            set_code_brand = f"{m.group(1)}{m.group(2)}"
    # extract_set_code_from_brand は 'OP15' / 'PRB02' / 'P' / None を返す
    # DON catalog の set_code は 'OP15' (booster), 'PRB01' (premium), 'STORAGE',
    # 'EVENT', 'KUMAMON' 等. PSA brand から直接判明するのは booster/PRB のみ.

    # 2) 候補絞り込み
    conn = api._connect()
    try:
        if set_code_brand and set_code_brand != "P":
            # 例 set_code_brand='OP15' → DON-OP15-* 候補
            rows = conn.execute(
                "SELECT id, product_id, name, name_jp, set_name, set_name_official, "
                "specs, images, source, source_url, created_at, updated_at, "
                "card_set_id, language, name_en, name_en_source "
                "FROM products WHERE category=? AND product_id LIKE ?",
                (CATEGORY, f"DON-{set_code_brand}-%"),
            ).fetchall()
        else:
            # brand から set_code 取れない (= promo / event etc.) → 全 DON 候補
            rows = conn.execute(
                "SELECT id, product_id, name, name_jp, set_name, set_name_official, "
                "specs, images, source, source_url, created_at, updated_at, "
                "card_set_id, language, name_en, name_en_source "
                "FROM products WHERE category=? AND product_id LIKE 'DON-%'",
                (CATEGORY,),
            ).fetchall()
    finally:
        conn.close()

    if not rows:
        if verbose:
            print(f"    ⚠️ DON: catalog 候補 0 件 "
                  f"(brand={brand!r}, set_code_brand={set_code_brand!r})")
        return None

    # 3) 各候補を hint keyword で scoring
    best_score = 0
    best_records: list[dict] = []
    for r in rows:
        try:
            specs = json.loads(r["specs"])
        except Exception:
            specs = {}
        hints = specs.get("psa_subject_hint") or []
        if not hints:
            continue
        score = sum(1 for h in hints if isinstance(h, str) and h.upper() in subj_upper)
        if score > best_score:
            best_score = score
            best_records = [r]
        elif score == best_score and score > 0:
            best_records.append(r)

    # 4) unique 1 件のみ採用、 tie / score=0 → step 5 image disambiguate
    if len(best_records) == 1 and best_score > 0:
        record = api._row_to_dict(best_records[0])
        if verbose:
            print(f"    🎯 iMakCatalog (DON) hit: {record['product_id']} "
                  f"(score={best_score}, brand={brand!r}, subject={subject!r})")
        return record

    # 5) tie + image_url 提供 → image hash disambiguate (2026-05-28 拡張)
    if image_url and len(best_records) > 1:
        if verbose:
            print(f"    ⏳ DON tie (= {len(best_records)} 件)、 image hash disambiguate 試行 "
                  f"(image_url={image_url[:60]}...)")
        disambiguated = _disambiguate_don_by_image(
            best_records, image_url, threshold=10, verbose=verbose
        )
        if disambiguated is not None:
            return disambiguated

    if verbose:
        print(f"    ⚠️ DON: 一意特定不能 (score={best_score}, "
              f"tie={len(best_records)}, total_candidates={len(rows)}); "
              f"brand={brand!r} subject={subject!r}")
        for r in best_records[:5]:
            print(f"        - {r['product_id']}")
    return None


def _disambiguate_don_by_image(
    candidates: list,
    image_url: str,
    threshold: int = 10,
    verbose: bool = True,
) -> Optional[dict]:
    """tie 候補から listing 画像 hash で 1 件特定.

    重複くん `dedupe/image_hash.py::compute_phash` / `identify_variant_by_image` と
    同 logic (= imagehash.phash 4.3.2 + Pillow 12.2.0)。

    Args:
        candidates: tie 状態の sqlite Row list (= best_records)
        image_url: listing 画像 URL
        threshold: hamming distance 上限 (= 5/27 POC 確定 10 bits)
        verbose: True で stdout 進捗

    Returns:
        unique 特定 record dict | None (= fail-closed)
    """
    try:
        import imagehash  # type: ignore
        from PIL import Image  # type: ignore
        import io
        # listing 画像 fetch + hash
        resp = api._connect  # placeholder
        import requests as _requests  # local import で起動時 import 影響軽減
        r = _requests.get(image_url, timeout=15)
        if r.status_code != 200:
            if verbose:
                print(f"    ⚠️ DON image_url fetch HTTP {r.status_code} → fail-closed")
            return None
        img = Image.open(io.BytesIO(r.content))
        listing_hash = imagehash.phash(img)
    except Exception as e:
        if verbose:
            print(f"    ⚠️ DON image_url fetch/parse 失敗: {e} → fail-closed")
        return None

    best_record, best_dist, tied = None, threshold + 1, False
    for r in candidates:
        try:
            variants = json.loads(r["variants"]) if r["variants"] else None
        except Exception:
            continue
        if not isinstance(variants, dict):
            continue
        # variants は {"default": {"image_phash": "..."}} 構造想定
        # multi-variant 対応のため、 各 variant_code の image_phash を全部試す
        for code, meta in variants.items():
            if not isinstance(meta, dict):
                continue
            stored = meta.get("image_phash")
            if not stored:
                continue
            try:
                stored_hash = imagehash.hex_to_hash(stored)
            except Exception:
                continue
            dist = listing_hash - stored_hash
            if dist < best_dist:
                best_dist = dist
                best_record = r
                tied = False
            elif dist == best_dist and best_record is not None and best_record["id"] != r["id"]:
                tied = True

    if best_record is None or tied or best_dist > threshold:
        if verbose:
            print(f"    ⚠️ DON image hash disambiguate 不能 "
                  f"(best_dist={best_dist}, tied={tied}, threshold={threshold})")
        return None

    record = api._row_to_dict(best_record)
    if verbose:
        print(f"    🎯 iMakCatalog (DON image) hit: {record['product_id']} "
              f"(hamming={best_dist}, threshold={threshold})")
    return record
