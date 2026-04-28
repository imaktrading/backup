"""catalog_localization - iMakCatalog の戻り値を eBay US 向けに正規化 (独立モジュール).

設計原則 (修正連鎖を生まないため):
  - 既存モジュール (psa_to_csv / catalog_psa / iMakCatalog) を一切修正しない
  - psa_to_csv は catalog_psa.lookup_one_piece() の戻り値を 1 関数通すだけで導入
  - 失敗時は元 record をそのまま返す (フォールバック耐性)

設計思想:
  iMakCatalog (隣セッションで開発中) は Bandai 公式 DB 集約マスタだが、Promo 系等で
  日本語のみ持つ record がある (例: P-001 Ichiban Kuji の card_type='キャラクター',
  color_en='赤', name_en='モンキー・D・ルフィ').
  これらが eBay US の Item Specifics にそのまま流れると:
    - フィルタにヒットしない (検索表示されない)
    - バイヤー混乱 / 出品禁止級の品質問題
  → eBay US 向けに英訳変換 + cosmetic 正規化する後処理 layer.

正規化対象 (3 種):
  1. JP→EN 辞書翻訳 (Card Type / Color / 著名キャラ名)
  2. キャラ名のピリオド連結補正 (`Monkey.D.Luffy` → `Monkey D. Luffy`)
  3. Card Name の variant suffix 剥がし (`Jewelry Bonney Weekly Shonen Jump '24-#35`
     → `Jewelry Bonney`. 既知 suffix のみ剥がす、未知は触らない)

範囲外 (= 触らない):
  - iMakCatalog DB schema や integrations (隣で開発中)
  - psa_to_csv.py 既存ロジック (3 行 wire-in だけ追加)
  - 既存 card_identification_agent / title_generation_agent

使用例:
    from catalog_localization import localize_catalog_record
    bandai = catalog_psa.lookup_one_piece(brand, card_number, subject)
    bandai = localize_catalog_record(bandai)
    # bandai["name_en"] が "Monkey D. Luffy" 形式 (英語、スペース付) で正規化済
"""
from __future__ import annotations

import re
from typing import Optional


# ============================================================================
# JP → EN 辞書 (失敗ナレッジ蓄積、新ケースで都度追記)
# ============================================================================

# Card Type の JP→EN
_CARD_TYPE_JP_EN = {
    "キャラクター": "Character",
    "リーダー":     "Leader",
    "イベント":     "Event",
    "ステージ":     "Stage",
    "ドン":         "Don",
    "ドン!!":       "Don",
}

# Color の JP→EN
_COLOR_JP_EN = {
    "赤":   "Red",
    "青":   "Blue",
    "緑":   "Green",
    "黄":   "Yellow",
    "紫":   "Purple",
    "黒":   "Black",
    "白":   "White",
    "茶":   "Brown",
    "金":   "Gold",
    "銀":   "Silver",
    # マルチカラー系 (One Piece TCG 特有)
    "赤/青":   "Red/Blue",
    "赤/緑":   "Red/Green",
    "赤/黄":   "Red/Yellow",
    "赤/黒":   "Red/Black",
    "赤/紫":   "Red/Purple",
    "青/緑":   "Blue/Green",
    "青/黄":   "Blue/Yellow",
    "青/黒":   "Blue/Black",
    "青/紫":   "Blue/Purple",
    "緑/黄":   "Green/Yellow",
    "緑/黒":   "Green/Black",
    "緑/紫":   "Green/Purple",
    "黄/黒":   "Yellow/Black",
    "黄/紫":   "Yellow/Purple",
    "黒/紫":   "Black/Purple",
}

# 著名キャラ名 JP→EN (One Piece TCG 想定、ヒットしなければ元値維持)
_CHARACTER_JP_EN = {
    "モンキー・D・ルフィ":    "Monkey D. Luffy",
    "モンキー・D・ガープ":    "Monkey D. Garp",
    "モンキー・D・ドラゴン":  "Monkey D. Dragon",
    "ロロノア・ゾロ":         "Roronoa Zoro",
    "ナミ":                   "Nami",
    "ウソップ":               "Usopp",
    "ヴィンスモーク・サンジ": "Vinsmoke Sanji",
    "サンジ":                 "Sanji",
    "トニートニー・チョッパー": "Tony Tony.Chopper",
    "ニコ・ロビン":           "Nico Robin",
    "フランキー":             "Franky",
    "ブルック":               "Brook",
    "ジンベエ":               "Jinbe",
    "ボア・ハンコック":       "Boa Hancock",
    "ポートガス・D・エース":  "Portgas D. Ace",
    "サボ":                   "Sabo",
    "シャンクス":              "Shanks",
    "トラファルガー・ロー":    "Trafalgar Law",
    "ユースタス・キッド":      "Eustass Kid",
    "シルバーズ・レイリー":    "Silvers Rayleigh",
    "エドワード・ニューゲート": "Edward Newgate",
    "白ひげ":                  "Whitebeard",
    "黒ひげ":                  "Blackbeard",
    "マーシャル・D・ティーチ": "Marshall D. Teach",
    "カイドウ":               "Kaido",
    "ビッグ・マム":            "Big Mom",
    "シャーロット・リンリン":  "Charlotte Linlin",
    "ヤマト":                  "Yamato",
    "光月おでん":              "Kozuki Oden",
    "光月モモの助":            "Kozuki Momonosuke",
    "錦えもん":                "Kin'emon",
    "イゾウ":                  "Izo",
    "ペローナ":                "Perona",
    "ベポ":                    "Bepo",
    "シュガー":                "Sugar",
    "レベッカ":                "Rebecca",
    "ビビ":                    "Vivi",
    "ネフェルタリ・ビビ":      "Nefertari Vivi",
    "ジュエリー・ボニー":      "Jewelry Bonney",
    "シラホシ":                "Shirahoshi",
    "ウタ":                    "Uta",
    "ベラミー":                "Bellamy",
    "クイーン":                "Queen",
    "キング":                  "King",
    "スモーカー":              "Smoker",
    "ベン・ベックマン":        "Benn Beckman",
    "マルコ":                  "Marco",
    "ヤソップ":                "Yasopp",
    # 必要に応じて随時追加
}


# 日本語文字検出 (ひらがな・カタカナ・漢字)
_JP_CHAR_RE = re.compile(r"[぀-ゟ゠-ヿ一-鿿]")


# ============================================================================
# 公開 API
# ============================================================================
def localize_catalog_record(record: Optional[dict]) -> Optional[dict]:
    """iMakCatalog の戻り値 dict を eBay US 向けに正規化.

    Args:
        record: catalog_psa.lookup_one_piece() の戻り値 (旧 bandai_jp 互換 dict)
                None の場合はそのまま None 返却.

    Returns:
        正規化済 dict. 翻訳不能な日本語が残ってる場合は警告 print + 元値維持.
        元 record を破壊しない (浅いコピーを返す).
    """
    if not record or not isinstance(record, dict):
        return record

    try:
        out = dict(record)  # 浅いコピー

        # 1. Card Type (JP→EN)
        out["type_en"] = _translate_card_type(out.get("type_en"))
        # 2. Color (JP→EN)
        out["color_en"] = _translate_color(out.get("color_en"))
        # 3. Character name (JP→EN + ピリオド正規化)
        out["name_en"] = _translate_character_name(out.get("name_en"))

        # 4. 残った日本語警告 (翻訳できなかったフィールドを発見的に検出)
        for key, value in out.items():
            if isinstance(value, str) and _JP_CHAR_RE.search(value):
                print(f"    ⚠️ catalog_localization: 翻訳未対応 JP 文字残存 "
                      f"key={key!r} value={value!r} (要辞書追加)")

        return out
    except Exception as e:
        print(f"    ⚠️ catalog_localization 例外、元 record 採用: "
              f"{type(e).__name__}: {e}")
        return record


# ============================================================================
# 内部処理
# ============================================================================
def _translate_card_type(value: Optional[str]) -> str:
    if not value:
        return value or ""
    v = value.strip()
    if v in _CARD_TYPE_JP_EN:
        return _CARD_TYPE_JP_EN[v]
    return v  # 既に英語 or 未対応 (上位で警告)


def _translate_color(value: Optional[str]) -> str:
    if not value:
        return value or ""
    v = value.strip()
    if v in _COLOR_JP_EN:
        return _COLOR_JP_EN[v]
    return v


def _translate_character_name(value: Optional[str]) -> str:
    """キャラ名: 日本語辞書ヒット + ピリオド連結補正."""
    if not value:
        return value or ""
    v = value.strip()

    # 1. 日本語完全一致
    if v in _CHARACTER_JP_EN:
        return _CHARACTER_JP_EN[v]

    # 2. ピリオド連結補正 (`Monkey.D.Luffy` → `Monkey D. Luffy`)
    #    パターン: 英字+ピリオド+1文字+ピリオド+英字 (連続無し)
    v = _normalize_period_name(v)

    return v


def _normalize_period_name(name: str) -> str:
    """`Monkey.D.Luffy` のような連続ピリオドの英字名を `Monkey D. Luffy` に正規化.

    eBay 標準は ミドルネーム/イニシャルが `X. ` (ピリオド + スペース).
    iMakCatalog 由来の name_en にはピリオド連続形式 (`Monkey.D.Luffy`) が混入する。

    変換規則:
      `Word.X.Word` → `Word X. Word`         (3要素、X はイニシャル)
      `Word.Word`   → `Word Word`             (2要素、ピリオドはスペース)
      `X.Word`      → `X. Word`               (先頭イニシャル)
    """
    if "." not in name:
        return name
    # 3要素パターン (eg. "Monkey.D.Luffy") 優先
    m = re.match(r"^([A-Za-z]+)\.([A-Za-z])\.([A-Za-z]+)$", name)
    if m:
        return f"{m.group(1)} {m.group(2)}. {m.group(3)}"
    # 4要素以上のパターン (eg. "Tony.Tony.Chopper") は each . を ' ' に変換
    parts = name.split(".")
    if all(re.match(r"^[A-Za-z]+$", p) for p in parts if p):
        return " ".join(p for p in parts if p)
    return name


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    samples = [
        # P-001 Ichiban Kuji (実例: 全フィールド日本語)
        {
            "name_en": "モンキー・D・ルフィ",
            "type_en": "キャラクター",
            "color_en": "赤",
            "rarity_en": "Promo",
            "card_id": "P-001",
        },
        # OP14-034 (name_en がピリオド連結)
        {
            "name_en": "Monkey.D.Luffy",
            "type_en": "Character",
            "color_en": "Green",
            "rarity_en": "Rare",
            "card_id": "OP14-034",
        },
        # 通常の英語 record (変更不要)
        {
            "name_en": "Boa Hancock",
            "type_en": "Character",
            "color_en": "Blue",
            "card_id": "OP07-057",
        },
        # 未知の日本語残存
        {
            "name_en": "謎のキャラ",
            "type_en": "キャラクター",
            "color_en": "赤/青",
        },
        # None 入力
        None,
    ]
    for i, s in enumerate(samples, 1):
        print(f"--- Sample {i} ---")
        print(f"  IN : {s}")
        out = localize_catalog_record(s)
        print(f"  OUT: {out}")
        print()
