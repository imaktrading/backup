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
import re
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
    "card_size_ebay":  "C:Card Size",
}
# eBay 正規化フィールド (catalog SSOT)。col → 候補 spec key 優先順 (先頭の非空を採用)。
# 方針: 値の正しさ・eBay語彙への正規化は **catalog 側 (`*_ebay`)** が持つ。generator は copy のみ。
#   - color/attribute/stage は値が日本語 (緑/赤/たね) → catalog `*_ebay` でのみ供給 (raw は使わない)。
#   - power は DragonBall が "15000 / (裏)20000" と不正 → catalog `attack_power_ebay` で正規化。
#   - cost はどのゲームも clean な整数なので raw 直結も許容 (即活用)。
# = catalog が *_ebay を埋めれば自動で流れる (forward-compatible)。未充填なら空欄 (回帰なし)。
_MULTI_SPEC_TO_COL = {
    "C:Cost":                 ["cost_ebay", "cost"],
    "C:Attack/Power":         ["attack_power_ebay"],
    "C:Defense/Toughness":    ["defense_toughness_ebay"],
    "C:Attribute/MTG:Color":  ["color_ebay"],
    "C:HP":                   ["hp_ebay"],
    "C:Stage":                ["stage_ebay"],
}
# Card Size の fallback。catalog 全件 'Standard'(2026-06-15 実機: sample500/500=Standard)。
# TOP セラー集計でも JP Pokemon PSA10 は Standard が市場標準 (Standard24/Japanese4)。
# = 推測でなく確証ある既定値 (旧コアの "Japanese" ハードコード誤りを是正)。
_CARD_SIZE_DEFAULT = "Standard"
# eBay TCG (cat 183454) Features 正規値 (公式フィルタ・2026-06-14 実機取得)。
# FREE_TEXT だが正規値に絞ることで検索フィルタにヒットさせる (official_x_ebay_filter_max_activation)。
_EBAY_TCG_FEATURES_VALID = frozenset([
    "1st Edition", "Altered/Custom Art", "Alternative Art", "Borderless", "Box Topper",
    "Chase", "Collectors Edition", "Demo Card", "Digital", "Duel Terminal Card",
    "Duelist Pack", "Exclusive", "Extended Art", "Full Art", "Judge Gift", "Limited Edition",
    "Miscut", "Misprint", "Participation Card", "Prerelease", "Prize Card", "Promo",
    "Reprint", "Sell Sheet", "Serial Numbered", "Shadowless", "Showcase", "Sketch",
    "Special Edition", "Speed Duel Starter Deck", "Split Card", "Stamped", "Starter Deck",
    "Starter Pack", "Structure Deck", "Timeshifted", "Unique Art", "Unlimited", "Unreleased",
])
# catalog の生 feature 値 (小文字) → eBay TCG facet 値。None = drop。
# rarity/type 語 (Ultra Rare/Secret/Leader Card) は feature でないので drop。
# 'Art Card' は facet に無く意味が確証できないため drop (fail-closed=推測で 'Full Art' 化しない)。
_TCG_FEATURE_MAP = {
    "alt art": "Alternative Art", "alternative art": "Alternative Art",
    "full art": "Full Art", "promo": "Promo", "limited edition": "Limited Edition",
    "extended art": "Extended Art", "unique art": "Unique Art", "borderless": "Borderless",
    "1st edition": "1st Edition",
    # 明示 drop (feature でない / facet に無い)
    "ultra rare": None, "secret": None, "leader card": None, "art card": None,
    "special art": None, "rare": None, "common": None, "uncommon": None,
}


def normalize_tcg_features(feats):
    """catalog の生 feature(list/str)を eBay TCG facet 正規値の list に正規化。

    純関数。facet 一致はそのまま採用 / 既知の生値はマップ / 不明・rarity語は drop (推測しない)。
    """
    if isinstance(feats, str):
        items = [feats]
    elif isinstance(feats, list):
        items = feats
    else:
        return []
    out = []
    for raw in items:
        tok = str(raw).strip()
        if not tok:
            continue
        if tok in _EBAY_TCG_FEATURES_VALID:        # 既に facet 正規値
            if tok not in out:
                out.append(tok)
            continue
        mapped = _TCG_FEATURE_MAP.get(tok.lower(), "")
        if mapped and mapped not in out:           # None/"" は drop
            out.append(mapped)
    return out


# Item Specifics 列 (空欄でも列は出す)
_ALL_COLS = [
    "C:Game", "C:Set", "C:Card Type", "C:Card Name", "C:Character",
    "C:Card Number", "C:Rarity", "C:Features", "C:Finish", "C:Illustrator",
    "C:Language", "C:Year Manufactured", "C:Card Size",
    # eBay 正規化フィールド (catalog *_ebay 由来。CSV列は既存 / C:HP・C:Stage は psa_to_csv 追加待ち)
    "C:Cost", "C:Attack/Power", "C:Defense/Toughness", "C:Attribute/MTG:Color",
    "C:HP", "C:Stage",
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


def build_listing_fields(cert: str, game_hint: str = "", forced_card_id: str = ""):
    """cert → eBay Item Specifics dict (catalog 決定論コピー・未知は空欄)。

    forced_card_id: 指定時は cert→card_id の自動解決を **スキップ**し、その card_id で生成する
      (= 人が HTML 目視確認で確定/選び直した product_id を権威として採用。verify→build フロー用)。
    Returns: (fields: dict[C:列→値], err: str|None)。err 時 fields は {}。
    """
    if forced_card_id:
        # 人が確定した card_id を直接採用 (Vision/自動解決を経由しない)
        specs = _catalog_specs(forced_card_id)
        if specs is None:
            return {}, f"forced card_id {forced_card_id} が catalog に無い"
        fields = map_specs_to_fields(specs, _psa_year(cert))
        fields["_card_id"] = forced_card_id
        return fields, None

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

    # 1b) eBay 正規化フィールド (候補 key 優先順・先頭の非空を採用)。値は catalog が正規化済 (SSOT)。
    for col, keys in _MULTI_SPEC_TO_COL.items():
        if fields.get(col):
            continue
        for k in keys:
            v = specs.get(k)
            if v not in (None, "", [], {}):
                fields[col] = str(v).strip()
                break

    # 2) Card Name ← name_en (公式カード名SSOT) / Character ← character_name。
    #    旧 Subject 汚染は断つ (PSA Subject を混ぜない)。
    #    name_en≠character_name の時は catalog 内部不整合 (例 romaji修正漏れ Kai/Irida) =
    #    そのまま出して監査で検出させる (papering over しない)。
    name_en = (specs.get("_name_en") or "").strip()
    char_nm = (specs.get("character_name") or "").strip()
    fields["C:Card Name"] = name_en or char_nm
    fields["C:Character"] = char_nm or name_en

    # 3) Features は eBay TCG facet 正規値に正規化 (生値 'Art Card' 等は drop)。
    norm_feats = normalize_tcg_features(specs.get("features"))
    if norm_feats:
        fields["C:Features"] = ", ".join(norm_feats)

    # 4) Language (catalog language=ja → eBay 'Japanese')
    lang = (specs.get("language") or specs.get("_language") or "").strip().lower()
    if lang in ("ja", "jp", "japanese"):
        fields["C:Language"] = "Japanese"
    elif specs.get("language"):
        fields["C:Language"] = str(specs.get("language")).strip()

    # 5) Year は PSA cert を信頼 (鑑定ラベルの発行年)。catalog に無くても PSA 由来は確証。
    if year:
        fields["C:Year Manufactured"] = str(year).strip()

    # 6) Card Size: catalog card_size_ebay をコピー / 無ければ確証ある既定 'Standard'
    #    (= 旧コアの "Japanese" ハードコード誤りを是正。推測でなく市場標準・catalog全件Standard)。
    if not fields["C:Card Size"]:
        fields["C:Card Size"] = _CARD_SIZE_DEFAULT

    # ★ rarity は rarity_ebay が無ければ空欄のまま (推測しない = #1 修正)
    # ★ Card Name/Character に PSA Subject を混ぜない (= #4 修正)
    return fields


# ============================================================================
# タイトル生成 (catalog 値から決定論で組む。LLM/Subject を混ぜない)
# ============================================================================
_GAME_TITLE_WORD = {
    "Pokémon TCG": "Pokemon", "Pokemon TCG": "Pokemon",
    "One Piece Card Game": "One Piece", "Yu-Gi-Oh! TCG": "Yu-Gi-Oh",
    "Dragon Ball Super Card Game": "Dragon Ball", "Gundam Card Game": "Gundam",
}
_TITLE_MAX = 80


def build_title_from_fields(fields: dict, grade: str = "10") -> str:
    """catalog 由来 fields から eBay タイトルを決定論で組む (≤80字)。

    方針: 公式事実のみを並べる。LLM/PSA Subject 由来の推測語を入れない。
    日本版は 'Japanese' 明記 (= 正確性・検索性)。
    優先度順に並べ、80字超は末尾の任意要素 (Year→Rarity→Features) から落とす
    (Set/番号/Character/Japanese/PSA10 は死守 = カード同定に必須)。
    """
    game = _GAME_TITLE_WORD.get(fields.get("C:Game", ""), "")
    core = ["PSA", str(grade)]
    if game:
        core.append(game)
    if fields.get("C:Language") == "Japanese":
        core.append("Japanese")
    if fields.get("C:Set"):
        core.append(fields["C:Set"])
    num = fields.get("C:Card Number", "")
    if num:
        core.append(f"#{num}")
    if fields.get("C:Character"):
        core.append(fields["C:Character"])

    # 任意 (末尾から落とせる) — 高情報順
    optional = []
    if fields.get("C:Rarity"):
        optional.append(fields["C:Rarity"])
    if fields.get("C:Features"):
        # "Art Card" 等。Rarity と語が被るなら足さない
        feat = fields["C:Features"]
        if feat.lower() not in " ".join(core + optional).lower():
            optional.append(feat)
    if fields.get("C:Year Manufactured"):
        optional.append(fields["C:Year Manufactured"])

    def _assemble(opts):
        toks = core + opts
        # 重複語 dedupe (大小無視・既出 token は落とす)
        seen, out = set(), []
        for t in toks:
            key = t.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(t)
        return " ".join(out)

    # Year→Features→Rarity の順に落として 80字に収める
    for drop in range(len(optional) + 1):
        opts = optional[: len(optional) - drop] if drop else optional
        title = _assemble(opts)
        if len(title) <= _TITLE_MAX:
            return title
    # core だけでも超える場合は素直に truncate (語境界)
    title = _assemble([])
    if len(title) > _TITLE_MAX:
        parts = title.split()
        while parts and len(" ".join(parts)) > _TITLE_MAX:
            parts.pop()
        title = " ".join(parts)
    return title


# ============================================================================
# 商品説明 個別 Specifications ブロック (旧コア build_row / 新コア override 共有 = SSOT)
# ============================================================================
_TCG_SPECS_MARKER = '<p><span style="text-decoration: underline;"><strong>About Color</strong>'
_SPECS_BLOCK_RE = re.compile(
    r'<p><span style="text-decoration: underline;"><strong>Specifications</strong>'
    r"</span></p>\s*<ul>.*?</ul>\s*", re.DOTALL)


def build_tcg_specs_html(specs):
    """[(label, value)] → Specifications HTML。値が空の項目は出さない・全空なら空文字 (純関数)。
    値は listing の Item Specifics と同じものを転記するだけ = 推測なし・出品の正確性原則。"""
    rows = []
    for label, value in specs:
        v = ("" if value is None else str(value)).strip()
        if v:
            rows.append(f"<li><b>{label}:</b> {v}</li>")
    if not rows:
        return ""
    return ('<p><span style="text-decoration: underline;"><strong>Specifications</strong>'
            "</span></p>\n<ul>\n" + "\n".join(rows) + "\n</ul>\n")


def insert_tcg_specs(description, specs_html):
    """About Color セクション直前に挿入。specs空/マーカー無しは description 不変 (fail-safe)。"""
    if not specs_html or _TCG_SPECS_MARKER not in description:
        return description
    return description.replace(_TCG_SPECS_MARKER, specs_html + _TCG_SPECS_MARKER, 1)


def replace_tcg_specs(description, specs_html):
    """既存 Specs ブロックを除去してから specs_html を挿入 (新コア override で旧値→新値に作り直す)。"""
    return insert_tcg_specs(_SPECS_BLOCK_RE.sub("", description), specs_html)


def specs_pairs_from_fields(fields):
    """新コア fields(dict) から Specs の [(label, value)] を作る (旧コア build_row と同項目)。"""
    return [
        ("Card Name", fields.get("C:Card Name", "")),
        ("Set", fields.get("C:Set", "")),
        ("Card Number", fields.get("C:Card Number", "")),
        ("Rarity", fields.get("C:Rarity", "")),
        ("Card Type", fields.get("C:Card Type", "")),
        ("Year", fields.get("C:Year Manufactured", "")),
        # Language は C:Language をそのまま転記 (空なら build_tcg_specs_html が行ごと省く)。
        # 旧: `or "Japanese"` で無条件 Japanese 埋め → 英語カードで誤表示 (Gemini DISPUTE 2026-06-15)。
        # fail-closed: 確証ない言語を Japanese と断定しない (Item Specifics の C:Language と一致)。
        ("Language", fields.get("C:Language", "")),
    ]


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
        title = build_title_from_fields(f)
        print(f"=== {cert} {label} → {f.get('_card_id')}")
        print(f"   TITLE({len(title)}字): {title}")
        print(f"   C:Set={f['C:Set']!r} C:Character={f['C:Character']!r} C:Rarity={f['C:Rarity']!r}")
