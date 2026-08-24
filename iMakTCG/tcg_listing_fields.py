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
    # 2026-08-22 契約 (_contract_aspects.yaml): 値と eBay 語彙への正規化は catalog が持つ。
    # 出品くんは写すだけ (旧: Manufacturer は franchise 判定のハードコード、
    #  Country of Origin は「One Piece なら Japan」の自前ルールだった)。
    "manufacturer_ebay":      "C:Manufacturer",
    "country_of_origin_ebay": "C:Country of Origin",
    # ポケモンのカード種別の接尾語 (EX/V/GX/VMAX 等・eBay の12値に一致するものだけ)。
    # 2026-08-23 カタログ回答: ポケモン 2,324行。他ゲームには該当が無く空欄。
    "speciality_ebay":        "C:Speciality",
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
    "C:Manufacturer", "C:Country of Origin", "C:Speciality",
    # eBay 正規化フィールド (catalog *_ebay 由来。CSV列は既存 / C:HP・C:Stage は psa_to_csv 追加待ち)
    "C:Cost", "C:Attack/Power", "C:Defense/Toughness", "C:Attribute/MTG:Color",
    "C:HP", "C:Stage",
]


def _split_category(card_id: str):
    """`one_piece_tcg:ST02-001_x` → ("one_piece_tcg", "ST02-001_x")。前置きが無ければ ("", pid)。

    KEY 列 / sidecar は `{category}:{product_id}` 形式。catalog を引く時にこの前半を
    捨てると別ゲームの行が返るので、必ずここで分けて両方を持ち回る。
    """
    s = (card_id or "").strip()
    if ":" in s:
        cat, _, pid = s.partition(":")
        if cat and pid:
            return cat.strip(), pid.strip()
    return "", s


def _catalog_specs(card_id: str, category: str = ""):
    """catalog の1行を引く。**category を必ず添えて引く** (2026-08-23)。

    product_id はカタログ全体では一意でない。ワンピとガンダムは採番規則が同じで、
    `ST02-001` `EB01-003` のように **283 件が両方に実在**する。category を付けずに
    `WHERE product_id=?` で引くと先に入っている行 (= 別ゲームの別カード) が返り、
    その値がそのまま Item Specifics とタイトルになる。

    実害 2026-08-23: cert154825163 (ワンピ Eustass "Captain" Kid) が
    `ST02-001` で引かれ **Gundam / Wing Gundam** として出品された (ItemID 820036000051)。

    category が空で、その product_id が複数カテゴリに在る時は **どれかを選ばない**。
    None を返して呼出側に解決不能として扱わせる (fail-closed)。
    """
    con = sqlite3.connect(CATALOG_DB)
    con.row_factory = sqlite3.Row
    if category:
        rows = con.execute(
            "SELECT name_en, language, specs FROM products "
            "WHERE product_id=? AND category=?", (card_id, category)).fetchall()
    else:
        rows = con.execute(
            "SELECT name_en, language, specs FROM products "
            "WHERE product_id=?", (card_id,)).fetchall()
    con.close()
    if not rows:
        return None
    if len(rows) > 1:
        # category 無しで複数カテゴリに当たった = どちらのゲームか決められない
        return None
    row = rows[0]
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
    # ★どの経路でも先に「どのゲームか」を確定させる。product_id だけで catalog を引くと
    #   ワンピ↔ガンダムで別カードが返る (_catalog_specs の docstring)。
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

    if forced_card_id:
        # 人が確定した card_id を直接採用 (Vision/自動解決を経由しない)。
        # ただし **どのゲームかは PSA/row 由来で押さえたまま**引く。
        cat, pid = _split_category(forced_card_id)
        specs = _catalog_specs(pid, cat or franchise or "")
        if specs is None:
            return {}, (f"forced card_id {forced_card_id} が catalog に無い"
                        if (cat or franchise)
                        else f"forced card_id {forced_card_id} がどのゲームか決まらない")
        fields = map_specs_to_fields(specs, _psa_year(cert))
        fields["_card_id"] = pid
        _fill_game_fallback(fields, game_hint)
        _attach_promo(fields, specs, pid)
        return fields, None

    if not franchise:
        return {}, "franchise 判定不能"

    card_id, err = _resolve_card_id(cert, franchise)
    if err:
        return {}, f"catalog 解決不能 ({err})"
    specs = _catalog_specs(card_id, franchise)
    if specs is None:
        return {}, f"card_id {card_id} が catalog に無い"

    fields = map_specs_to_fields(specs, _psa_year(cert))
    fields["_card_id"] = card_id
    _fill_game_fallback(fields, game_hint)
    _attach_promo(fields, specs, card_id)
    return fields, None


def _fill_game_fallback(fields, game_hint):
    """catalog game_ebay 空で C:Game が落ちると **タイトルからゲーム語(Pokemon等)が消える**
    (2026-06-25 XY-140 Hex Maniac: game_ebay=None でタイトル 'Pokemon' 抜け)。catalog が空の時のみ
    row/PSA 由来の game_hint を C:Game に補完(card 同定は変えず、ゲーム語だけ救う)。純関数。
    """
    if not (fields.get("C:Game") or "").strip() and (game_hint or "").strip():
        fields["C:Game"] = game_hint.strip()
    return fields


def _attach_promo(fields: dict, specs: dict, card_id: str):
    """プロモ系カードに 確定済 promo 名 / 検出フラグ を注入 (catalog外 per-card override)。

    promo 名は PSA Subject 由来=非公式のため catalog でなく tcg_promo_store に保存
    (catalog_official_only)。タイトル付与は build_title_from_fields が _promo を読む。
    """
    try:
        from tcg_promo_store import is_promo_variant, get_promo, needs_review
        fields["_is_promo"] = is_promo_variant(specs)
        fields["_promo"] = get_promo(card_id)
        fields["_promo_needs_review"] = needs_review(specs, card_id)
    except Exception:
        fields["_is_promo"], fields["_promo"], fields["_promo_needs_review"] = False, "", False


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

    # 3) Features は catalog の features_ebay を写すだけ (2026-08-22 契約)。
    #    生の features を出品側の表で正規化するのは廃止 (= 語彙の判断は catalog が持つ)。
    #    空なら **空欄で出す**。旧値で埋め戻さない (埋めると catalog の穴が見えなくなる &
    #    レアリティ語が Features に載る事故が 2026-08-22 に 4件出た)。
    _fe = specs.get("features_ebay")
    _vals = ([str(v).strip() for v in _fe if str(v).strip()] if isinstance(_fe, list)
             else ([str(_fe).strip()] if _fe else []))
    #    ★2026-08-25: 区切りは **縦棒 `|`** (eBay 入稿CSVの複数値の区切り)。
    #    読点で繋いでいた間、eBay 側は 1値の自由文として持っていた (実測: GetItem 820035999901
    #    → <Value>Promo, Alternative Art</Value>)。Features は cardinality=MULTI なので
    #    2値に分けないと買い手の絞り込み (正規値39個) に当たらない。
    if _vals:
        fields["C:Features"] = "|".join(_vals)

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


def _game_word(c_game):
    """C:Game(catalog値, 表記揺れあり)→ タイトル用ゲーム名。完全一致→部分一致で頑健化。

    2026-06-21 是正: catalog の C:Game が 'One Piece CCG' なのに _GAME_TITLE_WORD のキーは
    'One Piece Card Game' のみで照合空振り → タイトルからゲーム名 'One Piece' が落ちる bug。
    完全一致で取れなければゲーム名の部分一致で拾う(Pokemon 等の既存挙動は不変)。
    """
    exact = _GAME_TITLE_WORD.get(c_game or "", "")
    if exact:
        return exact
    g = (c_game or "").lower()
    for needle, word in (("pokémon", "Pokemon"), ("pokemon", "Pokemon"),
                         ("one piece", "One Piece"), ("yu-gi-oh", "Yu-Gi-Oh"),
                         ("yugioh", "Yu-Gi-Oh"), ("dragon ball", "Dragon Ball"),
                         ("gundam", "Gundam")):
        if needle in g:
            return word
    return ""


def build_title_from_fields(fields: dict, grade: str = "10") -> str:
    """catalog 由来 fields から eBay タイトルを決定論で組む (≤80字)。

    方針: 公式事実のみを並べる。LLM/PSA Subject 由来の推測語を入れない。
    日本版は 'Japanese' 明記 (= 正確性・検索性)。
    優先度順に並べ、80字超は末尾の任意要素 (Year→Rarity→Features) から落とす
    (Set/番号/Character/Japanese/PSA10 は死守 = カード同定に必須)。
    """
    game = _game_word(fields.get("C:Game", ""))
    # ★promo: generic な Set "Promo Cards" は具体的な配布元名 (Ichiban Kuji Purchase Bonus 等)
    #   に **置換** する (冗長を消し 80字枠を確保。C:Set 項目自体は filter 用に不変=タイトル表記のみ)。
    promo = (fields.get("_promo") or "").strip()
    cset = fields.get("C:Set", "")
    _use_promo_as_set = bool(promo) and cset.strip().lower() in ("promo cards", "promo")
    set_full = (promo if _use_promo_as_set else cset) if cset else ""
    num = fields.get("C:Card Number", "")
    lang_ja = fields.get("C:Language") == "Japanese"
    chara = fields.get("C:Character", "")

    def _core_tokens(set_disp):
        core = ["PSA", str(grade)]
        if game:
            core.append(game)
        if lang_ja:
            core.append("Japanese")
        if set_disp:
            core.append(set_disp)
        if num:
            core.append(f"#{num}")
        if chara:
            core.append(chara)
        return core

    core = _core_tokens(set_full)

    # 任意 (末尾から落とせる) — 高情報順。
    # ★ワード単位の重複ガード: 任意要素(Rarity/Features)の有意語が既存タイトルに在れば足さない。
    #   例: Set"Super Electric Breaker" + Rarity"Super Rare" → "super"被り → Rarity を足さない
    #   (= 旧: フレーズ単位 dedup で語跨ぎ重複を取れず "Super" 2回になっていた)。
    #   core(Set/Character/番号=同定語)は触らない (例 "Mega Brave"+"Mega Venusaur" は正当な重複)。
    def _word_overlap(candidate, existing_text):
        ex = set(existing_text.lower().split())
        return any(len(w) >= 4 and w in ex for w in candidate.lower().split())

    optional = []
    core_text = " ".join(core)
    # ★promo 配布元説明: Set 置換で core に入れた場合(_use_promo_as_set)は二重付与しない。
    #   Set が generic でない(具体的set名がある)時のみ optional 先頭 = 80字超で最後まで残す。
    if promo and not _use_promo_as_set and not _word_overlap(promo, core_text):
        optional.append(promo)
    if fields.get("C:Rarity") and not _word_overlap(fields["C:Rarity"], core_text):
        optional.append(fields["C:Rarity"])
    if fields.get("C:Features"):
        # ★2026-08-25: タイトルに入れるのは **先頭1値だけ**。join 済み文字列をそのまま足していた
        #   ため 'Common Promo, Alternative Art 2026' のように読点がタイトルに出ていた
        #   (実測: itemID 820035999901 + eBaymag ミラー3件)。Item Specifics 側は全値のまま残す。
        feat = fields["C:Features"].split("|")[0].strip()
        if feat and not _word_overlap(feat, " ".join(core + optional)):
            optional.append(feat)
    if fields.get("C:Year Manufactured"):
        optional.append(fields["C:Year Manufactured"])

    def _assemble(toks):
        # 重複語 dedupe (大小無視・既出 token は落とす)
        seen, out = set(), []
        for t in toks:
            key = t.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(t)
        return " ".join(out)

    # ★Set 短縮候補 (2026-07-23): カード名(Character)/番号は絶対に切らない。
    #   80字超は「任意要素を落とす」→ それでも超えるなら「Set 名を短縮」の順で吸収する。
    #   短縮は ①ダッシュ区切りの後半だけ残す (例 'Sun & Moon—Unbroken Bonds'→'Unbroken Bonds')
    #   ②前方の語を1つずつ落とす。旧実装は末尾語 pop で Character が切れていた
    #   (実害: 'Reshiram &' 止まりタイトル 2026-07-23 run)。
    set_variants = [set_full]
    if set_full:
        tail = re.split(r"[—–―]", set_full)[-1].strip()
        if tail and tail != set_full:
            set_variants.append(tail)
        base_words = set_variants[-1].split()
        for i in range(1, len(base_words)):
            set_variants.append(" ".join(base_words[i:]))

    # 各 Set 候補 × (Year→Features→Rarity の順に落とす) で最初に 80字へ収まる組を採用。
    # 全部収まる通常ケースは 1 周目 (= フル Set + 全 optional) で従来と同一結果。
    for set_disp in set_variants:
        ctoks = _core_tokens(set_disp)
        for drop in range(len(optional) + 1):
            opts = optional[: len(optional) - drop] if drop else optional
            title = _assemble(ctoks + opts)
            if len(title) <= _TITLE_MAX:
                return title
    # 最終手段 (Set を最短化しても core が超過): 従来の語境界 truncate
    title = _assemble(_core_tokens(set_variants[-1] if set_variants else ""))
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
