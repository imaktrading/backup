"""tcg_listing_fields — catalog(SSOT) から eBay Item Specifics を決定論生成する新生成コア。

並行ビルド (2026-06-13・旧 psa_to_csv は不変)。
目的: 出品の Item Specifics を **catalog の specs eBay 正規フィールドのコピー**で作る。
  catalog には既に set_name_ebay/rarity_ebay/character_name/game_ebay/card_type_ebay/
  finish/features/illustrator/language/card_number_text が揃っている (HQ実機確認 2026-06-13)。
  旧生成が踏んだ2バグを構造的に潰す:
    - #1 rarity 推測: catalog に rarity_ebay 無→ **空欄** (推測 'Common' を入れない)。
    - #4 Subject 汚染: Card Name/Character は **catalog character_name のみ** (PSA Subject を混ぜない)。
  確証なき値は空欄 (fail-closed / Precision100% 方針)。

旧との違い: 旧は PSA Subject 由来のバリアント語を Card Name/Character に足し、rarity を既定で埋めた。
本モジュールは catalog 値のコピーに徹し、足さない・推測しない。

検証: build_listing_fields() の出力を tcg_catalog_audit で照合 → 0 不一致 が期待値。
"""
from __future__ import annotations
import json
import os
import sqlite3
import sys
from pathlib import Path

# 共有プラミングは監査ツールから再利用 (DRY)
_TOOLS = r"C:/dev/iMak/iMakHQ/tools"
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
from tcg_catalog_audit import _resolve_card_id, _detect_franchise, PSA_CACHE_DIR, CATALOG_DB  # noqa: E402

# catalog specs key → eBay CSV 列名 (値はそのままコピー)
_SPEC_TO_COL = {
    "game_ebay":       "C:Game",
    "set_name_ebay":   "C:Set",
    "card_type_ebay":  "C:Card Type",
    "character_name":  "C:Character",
    "card_number_text": "C:Card Number",
    "rarity_ebay":     "C:Rarity",
    "finish":          "C:Finish",
    "illustrator":     "C:Illustrator",
}
# Item Specifics 列 (空欄でも列は出す)
_ALL_COLS = [
    "C:Game", "C:Set", "C:Card Type", "C:Card Name", "C:Character",
    "C:Card Number", "C:Rarity", "C:Features", "C:Finish", "C:Illustrator",
    "C:Language", "C:Year Manufactured",
]


def _catalog_specs(card_id: str):
    con = sqlite3.connect(CATALOG_DB)
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT name_en, language, specs FROM products WHERE product_id=?", (card_id,)).fetchone()
    con.close()
    if not row:
        return None
    try:
        specs = json.loads(row["specs"] or "{}")
    except Exception:
        specs = {}
    specs["_name_en"] = row["name_en"] or ""
    specs["_language"] = row["language"] or ""
    return specs


def _psa_year(cert: str):
    p = os.path.join(PSA_CACHE_DIR, f"{cert}.json")
    if not os.path.exists(p):
        return ""
    try:
        return str(json.load(open(p, encoding="utf-8")).get("Year") or "")
    except Exception:
        return ""


def build_listing_fields(cert: str, game_hint: str = ""):
    """cert → eBay Item Specifics dict (catalog 決定論コピー・未知は空欄)。

    Returns: (fields: dict[C:列→値], err: str|None)。err 時 fields は {}。
    """
    franchise = _detect_franchise(game_hint, "")
    if not franchise:
        # game_hint 無→ PSA cache の Brand から判定
        p = os.path.join(PSA_CACHE_DIR, f"{cert}.json")
        if os.path.exists(p):
            try:
                brand = json.load(open(p, encoding="utf-8")).get("Brand") or ""
                franchise = _detect_franchise("", brand)
            except Exception:
                pass
    if not franchise:
        return {}, "franchise 判定不能"

    card_id, err = _resolve_card_id(cert, franchise)
    if err:
        return {}, f"catalog 解決不能 ({err})"
    specs = _catalog_specs(card_id)
    if specs is None:
        return {}, f"card_id {card_id} が catalog に無い"

    fields = map_specs_to_fields(specs, _psa_year(cert))
    fields["_card_id"] = card_id
    return fields, None


def map_specs_to_fields(specs: dict, year: str = ""):
    """catalog specs(+_name_en/_language 注入済) → eBay Item Specifics dict。

    純関数 (DB/network 不要=テスト可能)。確証なき値は空欄 (fail-closed)。
    """
    fields = {c: "" for c in _ALL_COLS}

    # 1) catalog specs eBay フィールドを素直にコピー (未知は空欄のまま)
    for skey, col in _SPEC_TO_COL.items():
        v = specs.get(skey)
        if v:
            fields[col] = str(v).strip()

    # 2) Card Name ← name_en (公式カード名SSOT) / Character ← character_name。
    #    旧 Subject 汚染は断つ (PSA Subject を混ぜない)。
    #    name_en≠character_name の時は catalog 内部不整合 (例 romaji修正漏れ Kai/Irida) =
    #    そのまま出して監査で検出させる (papering over しない)。
    name_en = (specs.get("_name_en") or "").strip()
    char_nm = (specs.get("character_name") or "").strip()
    fields["C:Card Name"] = name_en or char_nm
    fields["C:Character"] = char_nm or name_en

    # 3) Features (list → ", " 連結。無→空欄)
    feats = specs.get("features")
    if isinstance(feats, list) and feats:
        fields["C:Features"] = ", ".join(str(f).strip() for f in feats if str(f).strip())
    elif isinstance(feats, str) and feats.strip():
        fields["C:Features"] = feats.strip()

    # 4) Language (catalog language=ja → eBay 'Japanese')
    lang = (specs.get("language") or specs.get("_language") or "").strip().lower()
    if lang in ("ja", "jp", "japanese"):
        fields["C:Language"] = "Japanese"
    elif specs.get("language"):
        fields["C:Language"] = str(specs.get("language")).strip()

    # 5) Year は PSA cert を信頼 (鑑定ラベルの発行年)。catalog に無くても PSA 由来は確証。
    if year:
        fields["C:Year Manufactured"] = str(year).strip()

    # ★ rarity は rarity_ebay が無ければ空欄のまま (推測しない = #1 修正)
    # ★ Card Name/Character に PSA Subject を混ぜない (= #4 修正)
    return fields


if __name__ == "__main__":
    # 動作確認: 今日の8 cert を catalog 決定論生成
    sys.stdout.reconfigure(encoding="utf-8")
    cases = [("131352422", "SVOM-020"), ("144241845", "SV11W-137"), ("137844371", "SV4M-090"),
             ("143595928", "S8b-118"), ("145541729", "SV1V-089"), ("76561938", "S11a-074"),
             ("145542092", "SV10-101"), ("113783004", "S10P-077")]
    for cert, label in cases:
        f, err = build_listing_fields(cert, "Pokémon TCG")
        if err:
            print(f"{cert} {label}: ERR {err}"); continue
        print(f"=== {cert} {label} → {f.get('_card_id')}")
        for c in _ALL_COLS:
            print(f"   {c}={f[c]!r}")
