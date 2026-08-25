#!/usr/bin/env python3
"""set_name_ebay 内部整合監査 (Catalog SSOT) — 2026-06-13 新設 (HQ greenlight).

set_name_ebay の系統的誤り (JP限定ハイクラスパックを英語版 main set 名に誤map 等。
例 S8b VMAXクライマックス→"Brilliant Stars"=英S9=別set) を catalog 内部で検出する。
HQ 照合ツール(出力CSV側) と二重で守る (= dual_gate)。

検査:
  1. era整合      : set_code の era (S/SM/SV/XY/BW…) と set_name_ebay の era接頭
                    ("Sword & Shield—" 等) の不一致を flag (= 別era set名への誤map)。
  2. set_code一貫性: 同一 set_code 内で set_name_ebay が複数値に割れている flag。
  3. source棚卸し  : set_name_ebay_source='(none)' (= 由来不明・未検証) を set_code 単位で
                    集計リスト化 (= S8b級の潜在誤りの母数。件数降順)。
  4. name整合      : name_en ≠ specs.character_name (両方非空) を flag
                    (= romaji name_en 修正時の character_name 同期漏れ等。eBay C:Character は
                    character_name 由来のため不整合=誤出品。2026-06-13 HQ依頼で追加)。
  5. empty棚卸し   : set_name_ebay='' (fail_closed_no_map / 単純空欄) の絶対数を category 別に集計。
                    2026-08-11 依頼 (op03_001_p2_set_name_ebay_empty_response.md §段3) で追加。
                    「214→423 に増えたのを誰も見ていなかった」の再発防止。
                    ★0 になっても出し続ける (0 が続く証跡が再発しないことの唯一の証拠)。
  6. canonical ズレ検知: specs.set_name_ebay ≠ 今その場で yaml/filter_map から計算した canonical値
                    の行数を category 別に絶対数で集計。
                    2026-08-12 依頼 (_ssot_contract_master_coverage_and_leaf_check_response_question_response.md)
                    契約 v1.2 §1-5 の「導出化 = restamp + ズレ検知」を実現する検出面。
                    可視化のみ (gate にしない)。★0 になっても出し続ける (§5 と同じ規約)。
                    定義: derive_set_name_ebay(cat, set_name_official, product_id) が
                    非-None を返し、それが stored (specs.set_name_ebay) と異なる行だけを数える
                    (= state (a) canonical のズレ)。state (b) 自由文字列 (filter_map 未収載) と
                    state (c) 空 は drift 対象外 (契約 v1.2 §1-3 の 3 状態を尊重)。

使い方:
  python iMakCatalog/tools/set_name_integrity_audit.py                # pokemon (既定)
  python iMakCatalog/tools/set_name_integrity_audit.py --cat all      # 全カテゴリ
  python iMakCatalog/tools/set_name_integrity_audit.py --out audit.md # md 出力
"""
import argparse
import datetime as _dt
import json
import re
import sqlite3
import sys
from collections import defaultdict
from typing import NamedTuple
from pathlib import Path

DB_PATH = "C:/dev/iMak_data/catalog/products.sqlite"

# 完走マーカー (途中で死んだ = マーカーが出ない = ログ検知できる).
# prune_daily.log と同型の「=== ... ===」規約に合わせる (2026-07-31 daily cron 化).
_START_MARK = "=== set_name integrity audit START"
_RARITY_WORDS = ("rare", "common", "uncommon", "promo", "holo", "secret", "foil",
                 "print", "gold", "silver", "bronze", "token", "land", "special",
                 "legend", "mythic", "fabled", "majestic", "enchanted", "leader",
                 "master ball", "shiny", "starlight", "prismatic", "parallel")


def _looks_like_rarity(v):
    """レアリティ語を含むか。含まなければ そもそもレアリティでない 疑い."""
    s = (v or "").strip().lower()
    if not s:
        return True
    return any(w in s for w in _RARITY_WORDS)


_END_MARK = "=== set_name integrity audit COMPLETE"

_ERAS = ["Scarlet & Violet", "Sword & Shield", "Sun & Moon", "Black & White", "XY"]

# §6 canonical ズレ検知用 (api.derive_set_name_ebay と同じ 3 段 fallback を local に実装.
#   api を import して api._DB_PATH に依存させると in-memory temp DB のテストが動かない.
#   ロジック本体は api.derive_set_name_ebay と同順で保つ — 変更する場合は両方同時修正.)
_SET_CODE_BRACKET_RE = re.compile(r"[\[【]([A-Z][A-Z0-9-]*)[\]】]")


def _fmap_lookup(conn, category: str, field: str, source_value):
    if not source_value:
        return None
    row = conn.execute(
        "SELECT ebay_value FROM ebay_filter_map "
        "WHERE category=? AND field=? AND source_value=?",
        (category, field, source_value),
    ).fetchone()
    return row["ebay_value"] if row else None


def _derive_set_name_ebay(conn, category: str, set_name_official, product_id):
    """derive_set_name_ebay と同順 (①set_official ②[CODE] ③pid prefix) — 無ければ None."""
    if set_name_official:
        v = _fmap_lookup(conn, category, "set", set_name_official)
        if v:
            return v
        m = _SET_CODE_BRACKET_RE.search(set_name_official)
        if m:
            v = _fmap_lookup(conn, category, "set_code", m.group(1))
            if v:
                return v
    if product_id and "-" in product_id:
        pref = product_id.split("-", 1)[0]
        for cand in {pref, pref.upper(), pref.lower()}:
            v = _fmap_lookup(conn, category, "set_code", cand)
            if v:
                return v
    return None


# api._RARITY_VARIANT_MARK_RE と同じ (★=dragonball / +=gundam の刷り違いマーカー)
_RARITY_STAR_RE = re.compile(r"[★☆+]+\s*$")


def _rarity_lookup_keys(rarity_raw):
    """api.rarity_lookup_keys と同じ (①マーカー除去した生値 ②'<基底> SP' なら基底).

    HQ 裁定 2026-08-18 (2026-08-13_rarity_17rows_naming_decision_req_response.md)。
    api を import しない理由は上の §6 と同じ (in-memory temp DB のテスト)。
    ★変更する場合は api.rarity_lookup_keys と両方同時に直す
      (tests/test_rarity_sp_composite_20260818.py が両者の一致を毎回検査する)。
    """
    if not rarity_raw:
        return []
    base = _RARITY_STAR_RE.sub("", str(rarity_raw).strip()).strip()
    if not base:
        return []
    keys = [base]
    toks = base.split()
    if len(toks) == 2 and sum(1 for t in toks if t.upper() == "SP") == 1:
        keys.append(next(t for t in toks if t.upper() != "SP"))
    return keys


def _derive_rarity_ebay(conn, category: str, rarity_raw):
    """api.derive_rarity_ebay と同順 (候補キーを順に filter_map) — 無ければ None."""
    for key in _rarity_lookup_keys(rarity_raw):
        v = _fmap_lookup(conn, category, "rarity", key)
        if v:
            return v
    return None


class AuditResult(NamedTuple):
    """audit() の戻り。**位置ではなく名前で参照する**.

    2026-08-23: §0c を足した時、`res[-1]` / `res[-2]` で受けていた test が3本壊れた。
    節を足すたびに末尾がずれるため、以後は名前で受ける (位置互換も維持している)。
    """
    era_mismatch: list
    inconsistent: list
    none_list: list
    name_desync: list
    empty_by_cat: dict
    drift_by_cat: dict
    rarity_by_cat: dict
    not_rarity: dict
    prefix_mismatch: list
    unregistered: dict
    code_value_mismatch: list
    stage_on_non_pokemon: list
    card_type_unknown: list
    const_violation: list
    card_number_mismatch: list
    type_forbidden: list
    name_en_collision: list


# 弾番号つき eBay 値の接頭辞 (Sv4k: / Swsh06: / Sm3h: …)
_PREFIX_RE = re.compile(r"^([A-Za-z]+[0-9][0-9A-Za-z]*)\s*:")


_MASTER_PATH = Path(r"C:/dev/iMak_data/catalog/_input/ebay_aspects_183454_latest.json")
_ALLOW_PATH = Path(__file__).resolve().parent.parent / "ebay_filter_map" / "_free_text_set_values.yaml"
_GAME_OF = {"pokemon_tcg": "Pokémon TCG", "one_piece_tcg": "One Piece CCG",
            "dragonball_scg": "Dragon Ball Super Card Game", "gundam_tcg": None}


def _load_allowed():
    """① eBay master の値 と ② 自由入力の登録簿 を category 別に読む."""
    master, allow = {}, {}
    try:
        by_game = json.loads(_MASTER_PATH.read_text(encoding="utf-8"))["aspects"]["Set"]["by_game"]
    except Exception:
        by_game = {}
    for cat, game in _GAME_OF.items():
        master[cat] = set(by_game.get(game or "", []))
    try:
        import yaml
        doc = yaml.safe_load(_ALLOW_PATH.read_text(encoding="utf-8")) or {}
        for e in doc.get("values") or []:
            allow.setdefault(e.get("category"), set()).add(e.get("value"))
    except Exception:
        pass
    return master, allow


# 13. その種別が持ち得ない項目 (2026-08-25 制定)。
#   「Trainer に HP は無い」のように **外の正解表が要らない**面。Stage の §9 と同じ形。
#   実測で見つけた誤り: ポケモン Trainer-Item の hp 43行 (化石の効果文 "HP60" を拾っていた) /
#   ワンピ Leader の cost 105行 (Leader はライフを持つ。8/22 の修正が variant を取りこぼし)。
#   ★「一部だけ持っている」は正常なこともある (ガンダムの Pilot は AP/HP 修正を持つ個体が在る)
#     ので、**0 でなければならない組み合わせだけ**を書く。
_TYPE_FORBIDDEN = {
    ("pokemon_tcg", "Trainer-Item"): ("hp", "hp_ebay"),
    ("pokemon_tcg", "Trainer-Supporter"): ("hp", "hp_ebay"),
    ("pokemon_tcg", "Trainer-Stadium"): ("hp", "hp_ebay"),
    ("pokemon_tcg", "Energy-Basic"): ("hp", "hp_ebay", "attack_power_ebay"),
    ("pokemon_tcg", "Energy-Special"): ("hp", "hp_ebay", "attack_power_ebay"),
    ("one_piece_tcg", "Leader"): ("cost",),
    ("one_piece_tcg", "DON!! Card"): ("cost", "attack_power_ebay"),
    ("dragonball_scg", "Energy Marker"): ("cost", "attack_power_ebay"),
}


def _load_card_types():
    """eBay の Card Type の値表を category 別に読む (Game 別)。

    2026-08-25 実測: 値表を持つのは **Pokémon TCG だけ** (11値)。
    ワンピ / ガンダム / DBSCG は eBay 側に一覧が無いので自由入力 = 照合しない。
    """
    try:
        node = json.loads(_MASTER_PATH.read_text(encoding="utf-8"))["aspects"]["Card Type"]
        by_game = node.get("by_game") or {}
    except Exception:
        by_game = {}
    return {cat: set(by_game.get(game or "") or []) for cat, game in _GAME_OF.items()}


def _norm_code(c: str) -> str:
    """弾コードを比べる形に揃える (大小 + 0埋めの違いは同じものとして扱う).

    `SV3` と `SV03` / `CP4` と `Cp4` は同じ弾。別セットかどうかだけを見たいので潰す。
    """
    c = (c or "").upper()
    return re.sub(r"^([A-Z]+)0+(?=[0-9])", lambda m: m.group(1), c)


# §0d — 同じ英名を複数の日本語名が使っている (2026-08-24 常設)
#   別人の英名は必ず本人の行と衝突するので、この1本で発生源が塞がる。
#   オルティガ (`Arven` ← {ペパー, オルティガ}) はこの向きでしか掛からない
#   (逆向き = 同じ日本語名が複数の英名を持つ、では 3行とも `Arven` で揃っていて出ない)。
#   ★WARN のみ。**自動修正しない**。表記ゆれの同一人物を誤って直す方が害が大きい
#     (回答書 2026-08-24_hq_ortega_is_not_arven_response.md §2)。
_JP_VARIANT_NOISE = re.compile(r"[\[［(（].*?[\]］)）]|[☆★♂♀\s]+")


def jp_name_key(name_jp: str) -> str:
    """表記ゆれの同一人物を1つに畳む (`ナッシー[Exeggutor]` / `シャワーズ☆` → 本体)."""
    return _JP_VARIANT_NOISE.sub("", name_jp or "")


def setcode_era(sc: str):
    sc = sc or ""
    if sc.startswith("SV"):
        return "Scarlet & Violet"
    if sc.startswith("SM"):
        return "Sun & Moon"
    if sc.startswith("XY"):
        return "XY"
    if sc.startswith("BW"):
        return "Black & White"
    if re.match(r"^S\d", sc):
        return "Sword & Shield"
    return None  # legacy(DP/L/M…) や promo は era 判定対象外


def ebay_era(name: str):
    name = name or ""
    for era in _ERAS:
        if name.startswith(era + "—") or name.startswith(era + " "):
            return era
    return None


def setcode_of(product_id: str, specs: dict) -> str:
    return specs.get("set_code") or (product_id.split("-")[0] if product_id else "")


def names_own_setcode(value: str, set_code: str) -> bool:
    """焼いてある値が **その弾自身の名前で始まっている** か (`S8a-P: …` は S8a の別商品).

    §0c の唯一の除外。`_PREFIX_RE` は `S8a-P:` (弾コードに '-' を含む形) を拾えないので、
    値の頭を弾コードと直接比べる。`Noble Victories` は `BW2` で始まらないので除外されない。

    ★product_id 側を細かく切る形 (`BW2-B-001` -> `BW2B`) は**採らない**。`-B-` が別商品を
      意味するとは限らず、2026-08-23 に実測したら L3/BW2/BW4/BW7 の 279行を取りこぼした。
    """
    v, sc = (value or "").upper(), (set_code or "").upper()
    return bool(sc) and v.startswith(sc)


def audit(categories):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # name_jp は §0d でしか使わない。**列が無い DB でも落とさない**
    # (test の最小 fixture は products を 5列だけで作る。2026-08-24 にここで 14本落とした)
    _cols = {r[1] for r in conn.execute("PRAGMA table_info(products)")}
    _jp = "name_jp" if "name_jp" in _cols else "'' AS name_jp"
    q = (f"SELECT category, product_id, name_en, {_jp}, set_name_official, specs "
         f"FROM products")
    if categories:
        ph = ",".join("?" for _ in categories)
        q += f" WHERE category IN ({ph})"
        rows = conn.execute(q, categories).fetchall()
    else:
        rows = conn.execute(q).fetchall()

    # set_code -> {set_name_ebay -> count}, set_code -> source set, set_code -> category
    by_code = defaultdict(lambda: defaultdict(int))
    code_src = defaultdict(set)
    code_cat = {}
    none_src = defaultdict(lambda: defaultdict(int))  # source=(none) 棚卸し
    era_mismatch = []  # (set_code, ebay, sc_era, ebay_era, count)
    name_desync = []  # (product_id, name_en, character_name)
    # 5. empty棚卸し: category -> {'fail_closed_no_map': N, 'blank': M, 'total_empty': N+M}
    empty_by_cat = defaultdict(lambda: {"fail_closed_no_map": 0, "blank": 0, "total_empty": 0})
    # 6. canonical ズレ検知: category -> drift 件数 (state (a) canonical のみ)
    drift_by_cat = defaultdict(int)
    # 7. rarity 生値焼き付き検知 (2026-08-13): category -> {raw_stamped, map_drift}
    #    raw_stamped = specs.rarity_ebay が公式生コードのまま (変換されていない) 行。
    #      2026-08-13 の実害 (rarity_ebay='L★' → 禁止文字除去で 'L' 1文字) と同型で、
    #      'U' / 'SPカード' / 'LR+' のような値が C:Rarity に出るのを毎日可視化する。
    #    map_drift = filter_map から今その場で計算した値 ≠ stored (契約 v1.2 §1-5 のズレ検知)。
    #      yaml 側が旧短縮コードのまま (pokemon/one_piece/gundam) なら大量に出る = yaml 未同期の指標。
    not_rarity = defaultdict(int)
    rarity_by_cat = defaultdict(lambda: {"raw_stamped": 0, "map_drift": 0, "unmapped": 0,
                                     "accepted_blank": 0})

    # 8. 弾コード食い違い検知 (2026-08-23 / HQ 提供の条件をそのまま常設化)
    #    eBay 値の頭に付く弾番号 (例 'Sv4k:') は **その商品の弾コードと一致するはず**。
    #    食い違い = 別セットの名前が入っている。2026-08-22 に SV4K/SV4M/SV9 の 322枚で発生。
    #    ★これは §6 の canonical ズレ検知では捕まらない: 変換表そのものが誤っていると
    #      「今その場で計算した値」も同じ誤りになるため一致してしまう。
    prefix_mismatch = []          # (product_id, set_code, set_name_ebay)
    # 0b. 未登録値の検知 (2026-08-23)
    #    set_name_ebay に入ってよいのは ① eBay master に在る値 か
    #    ② `_free_text_set_values.yaml` に登録した値 だけ。どちらでもない = 未登録。
    #    ★「Swsh で始まる値」のような**見た目の条件**での確認は、条件を思いつけるかに
    #      依存するので必ず漏れる (2026-08-23 に実際に漏れて 1,729行が誤った値のまま出ていた)。
    #      許可された値の一覧と突き合わせる形にして、思いつきに依存させない。
    unregistered = defaultdict(lambda: defaultdict(int))   # category -> value -> count
    # 0c. 別セットの名前 (弾番号が付いていない形) の検知 (2026-08-23)
    #    §0 は **値の頭に弾番号が付いている時しか**比べられない (`Sv4k:` 等)。
    #    `Roaring Skies` / `Sun & Moon` / `Triumphant` のような英語版セット名は弾番号が
    #    無いので §0 を素通りし、eBay の一覧に実在する値なので §0b も通る。
    #    → 「eBay master に **その商品の弾コードで始まる値が在る**のに、焼いてある値が
    #      それでない」を見る。実測 2026-08-23: pokemon_tcg で 1,798行 (日本語版の刷りに
    #      英語版セット名が載っている = ルール③違反)。
    #    除外は2つだけ (どちらも「同じ弾の別商品」で誤りではない):
    #      - 値の頭が弾コードの細分 (`S8a-P:` は S8a の promo pack) → 同じ弾扱い
    #      - `_free_text_set_values.yaml` に登録済の自由入力 (`25th Anniversary Golden Box`)
    code_value_mismatch = []      # (product_id, set_code, stored, [その弾の master 値])
    # 9. 進化段階を持たない種別に stage が入っていないか (2026-08-23 追加)
    #    取り込みが **ページ全文** から進化段階の語を探していたため、トレーナーズ/
    #    エネルギーで効果テキストやセット名に当たっていた (2,366行)。
    #    `<span class="type">` にアンカーして取り直したので、以後は 0 で維持する。
    stage_on_non_pokemon = []     # (product_id, card_type_ebay, stage)
    # 10. Card Type が eBay の値表に無い (2026-08-25 追加)
    #    Set と同じ「一覧と突き合わせる」形。値表を持つのは Pokémon TCG だけ。
    #    実害: 取り込みがカード名に「エネルギー」が入るかで種別を決めていたため、
    #    グッズの「エネルギー回収」等が Energy になり、`Energy` は eBay に無い値だった。
    card_type_unknown = []        # (product_id, card_type_ebay)
    # 11. 定数項目の点検 (2026-08-25 追加)
    #    Game / Manufacturer / Card Size は **category ごとに1値**しか取らない。
    #    2値以上に割れる = 取り込みの取りこぼしか誤り。空欄も同じ。
    #    実測 2026-08-25: card_size_ebay だけ 2,859行が空だった (値は Standard の1種類のみ)。
    const_split = defaultdict(lambda: defaultdict(int))   # (cat,key) -> value -> count
    # 12. 券面番号と product_id の食い違い (2026-08-25 追加)
    #    `card_number_text` は券面に刷ってある番号。ゲームで書式が違う
    #    (ポケモン '001/083' / ワンピ 'EB02-003') ので、**数字部分**で比べる。
    #    product_id の末尾番号が券面のどれかの数字と一致しない = どちらかが誤り。
    #    ★`cardID-*` は券面番号を持たない暫定キーなので対象外 (別件のバックログ)。
    card_number_mismatch = []     # (product_id, card_number_text)
    type_forbidden = []           # (product_id, card_type_ebay, key, 値)
    _ctype_ok = _load_card_types()
    # 0d. 同じ英名を複数の日本語名が使っている (2026-08-24)
    name_en_collision = []        # (category, name_en, {name_jp: count})
    _en_to_jp = defaultdict(lambda: defaultdict(int))   # (category, name_en) -> {name_jp: n}
    _master, _allow = _load_allowed()
    # 弾コード -> その弾の eBay 値 (category 別)
    _by_code = defaultdict(lambda: defaultdict(set))
    for _cat, _vals in _master.items():
        for _v in _vals:
            _m = _PREFIX_RE.match(_v)
            if _m:
                _by_code[_cat][_norm_code(_m.group(1))].add(_v)
    tmp_era = defaultdict(int)  # (set_code,ebay) count for era check
    for r in rows:
        s = json.loads(r["specs"])
        sc = setcode_of(r["product_id"], s)
        e = s.get("set_name_ebay") or ""
        src = s.get("set_name_ebay_source") or "(none)"
        by_code[sc][e] += 1
        code_src[sc].add(src)
        code_cat[sc] = r["category"]
        if e:
            tmp_era[(sc, e)] += 1
            if src == "(none)":
                none_src[sc][e] += 1
        else:
            # empty 側の内訳: fail_closed_no_map か、それ以外 (blank)
            bucket = empty_by_cat[r["category"]]
            if src == "fail_closed_no_map":
                bucket["fail_closed_no_map"] += 1
            else:
                bucket["blank"] += 1
            bucket["total_empty"] += 1
        # 4. name_en ↔ character_name 整合 (両方非空で不一致)
        #    接頭辞一致 ("Pikachu V" vs "Pikachu" の V/VMAX/ex 接尾差) は正当として除外し、
        #    真の名前相違 (romaji 同期漏れ等) のみ flag。
        cn = s.get("character_name")
        ne = r["name_en"]
        if ne and cn and ne != cn \
                and not ne.startswith(cn) and not cn.startswith(ne):
            name_desync.append((r["product_id"], ne, cn))
        # 6. canonical ズレ検知: 今その場で filter_map から計算し、stored と比較.
        #    computed が非-None (= state (a) canonical に該当) かつ stored != computed の行のみ数える.
        #    computed=None のケース (state (b) 自由文字列 / state (c) 空) は drift 対象外.
        computed = _derive_set_name_ebay(conn, r["category"], r["set_name_official"],
                                          r["product_id"])
        if computed is not None and computed != e:
            drift_by_cat[r["category"]] += 1
        if e and e not in _master.get(r["category"], set())                 and e not in _allow.get(r["category"], set()):
            unregistered[r["category"]][e] += 1
        m_pref = _PREFIX_RE.match(e)
        pre_n, sc_n = _norm_code(m_pref.group(1)) if m_pref else "", _norm_code(sc)
        # 片方がもう片方の頭になっているのは同じ弾 (CS1t / CS1p / CS1m は同じ `Cs1:` を共有)。
        same = pre_n and (sc_n.startswith(pre_n) or pre_n.startswith(sc_n))
        if m_pref and sc and not same:
            # Swsh 系は英語セット番号 (日本の2セットが英語版1セットに併合される)。
            # 2026-08-18 の HQ 裁定どおりなので対象外。
            # `cardID-*` は弾コードを持たない暫定キー (別件のバックログ)。ここでは見ない。
            if not m_pref.group(1).upper().startswith("SWSH")                     and not str(r["product_id"] or "").startswith("cardID-"):
                prefix_mismatch.append((r["product_id"], sc, e))
        # 0c. その弾の値が eBay に在るのに、別の値が焼いてある
        #    ★自由入力の登録簿 (`_free_text_set_values.yaml`) は **免罪符にしない**。
        #      登録簿はルール② (eBay に値が無い弾) のためのもので、値が在る弾に登録が
        #      あるなら、その登録自体が誤り (実測 2026-08-23: `Mask of Change` /
        #      `Rocket Gang's Glory` / `20th Anniversary` の3値が該当し、356行を隠していた)。
        _cand = _by_code.get(r["category"], {}).get(sc_n) if (e and sc_n) else None
        if _cand and e not in _cand and not names_own_setcode(e, sc):
            code_value_mismatch.append((r["product_id"], sc, e, sorted(_cand)))
        # 7. rarity 生値焼き付き / map ズレ (computed=None は filter_map 未登録 = 別問題)
        r_raw, r_stored = s.get("rarity"), s.get("rarity_ebay")
        # yugioh は生値が既に英語 canonical ("Secret Rare" 等) で passthrough が正 → 対象外
        if r_raw and r_stored and r["category"] != "yugioh_tcg" \
                and str(r_raw).strip() == str(r_stored).strip():
            rarity_by_cat[r["category"]]["raw_stamped"] += 1
        computed_rarity = _derive_rarity_ebay(conn, r["category"], r_raw)
        if computed_rarity is not None and computed_rarity != r_stored:
            rarity_by_cat[r["category"]]["map_drift"] += 1
        # unmapped = 生 rarity はあるのに変換先が無く、**stored も空** (= そのカードが出品されない)。
        #   fail-closed なので誤出品はしないが、放置すると永久に出ないので残件として毎日出す。
        #   個別に値を入れた行 (filter_map で表せない = カード名依存の LEGEND / Gold Star 等) は
        #   stored が埋まっているので対象外。
        if r_raw and not r_stored and computed_rarity is None and r["category"] != "yugioh_tcg":
            # 「出さないと決めた」行 (HQ 判断 2026-08-16) は残件ではないので別枠。
            # これで unmapped は **新規に出た未変換だけ** を意味する = 増えたら合図。
            if s.get("rarity_ebay_status"):
                rarity_by_cat[r["category"]]["accepted_blank"] += 1
            else:
                rarity_by_cat[r["category"]]["unmapped"] += 1
        # 8. レアリティでない値が C:Rarity に出ていないか (2026-08-21 追加)
        #    遊戯王は「生値が canonical だから passthrough で正」として §7 から除外して
        #    いたが、その前提で 2 / New / European debut / force-SMW のような
        #    レアリティですらない値が 118行 流れていた。
        if r_stored and not _looks_like_rarity(r_stored):
            not_rarity[(r["category"], r_stored)] += 1

        # 0d. 同じ英名を複数の日本語名が使っていないか (別人の英名が混ざっている合図)
        if (r["name_en"] or "").strip() and (r["name_jp"] or "").strip():
            _en_to_jp[(r["category"], r["name_en"].strip())][r["name_jp"].strip()] += 1

        # 9. 進化段階を持たない種別に stage が入っている (ポケモンのみ)
        if r["category"] == "pokemon_tcg":
            _ct = s.get("card_type_ebay")
            if _ct in ("Trainer", "Energy") and (s.get("stage") or s.get("stage_ebay")):
                stage_on_non_pokemon.append(
                    (r["product_id"], _ct, s.get("stage") or s.get("stage_ebay")))

        # 10. Card Type が eBay の値表に無い (値表を持つ category のみ)
        # 13. その種別が持ち得ない項目
        _keys = _TYPE_FORBIDDEN.get((r["category"], s.get("card_type_ebay")))
        if _keys:
            for _k in _keys:
                if s.get(_k) not in (None, "", []):
                    type_forbidden.append(
                        (r["product_id"], s.get("card_type_ebay"), _k, s.get(_k)))

        # 12. 券面番号 vs product_id
        _cnt = (s.get("card_number_text") or "").strip()
        _base = (r["product_id"] or "").split("_", 1)[0]
        if _cnt and _base and not _base.startswith("cardID"):
            _m1 = re.findall(r"\d+", _base)
            if _m1:
                _want = _m1[-1].lstrip("0") or "0"
                _got = {x.lstrip("0") or "0" for x in re.findall(r"\d+", _cnt)}
                if _want not in _got:
                    card_number_mismatch.append((r["product_id"], _cnt))

        for _k in ("game_ebay", "manufacturer_ebay", "card_size_ebay",
                   "language", "country_of_origin_ebay"):
            const_split[(r["category"], _k)][s.get(_k) or "(空)"] += 1

        _ok = _ctype_ok.get(r["category"]) or set()
        _ctv = s.get("card_type_ebay")
        if _ok and _ctv and _ctv not in _ok:
            card_type_unknown.append((r["product_id"], _ctv))

    conn.close()

    # 1. era mismatch
    for (sc, e), cnt in tmp_era.items():
        sce, ee = setcode_era(sc), ebay_era(e)
        if sce and ee and sce != ee:
            era_mismatch.append((sc, e, sce, ee, cnt))
    era_mismatch.sort(key=lambda x: -x[4])

    # 2. set_code 一貫性 (set_name_ebay が空でない値が2種以上)
    inconsistent = []
    for sc, d in by_code.items():
        vals = {k: v for k, v in d.items() if k}
        if len(vals) >= 2:
            inconsistent.append((sc, dict(vals)))
    inconsistent.sort(key=lambda x: -sum(x[1].values()))

    # 3. source=(none) 棚卸し (set_code 単位・件数降順)
    none_list = []
    for sc, d in none_src.items():
        total = sum(d.values())
        # 単一値のものだけ (複数値は #2 で別途出る)
        val = max(d.items(), key=lambda kv: kv[1])[0] if d else ""
        none_list.append((sc, val, total, code_cat.get(sc, "")))
    none_list.sort(key=lambda x: -x[2])
    name_desync.sort(key=lambda x: x[0])

    # 0d. 表記ゆれを畳んでも2人以上残る英名だけを出す (同一人物の書き方違いは誤りではない)
    for (cat, en), jps in _en_to_jp.items():
        if len({jp_name_key(j) for j in jps}) >= 2:
            name_en_collision.append((cat, en, dict(jps)))
    name_en_collision.sort(key=lambda x: -sum(x[2].values()))

    const_violation = []          # (category, key, {値: 件数})
    for (cat_, key_), vals in const_split.items():
        if len(vals) > 1:
            const_violation.append((cat_, key_, dict(vals)))
    const_violation.sort(key=lambda x: -sum(x[2].values()))

    return AuditResult(
        era_mismatch, inconsistent, none_list, name_desync,
        dict(empty_by_cat), dict(drift_by_cat), dict(rarity_by_cat), dict(not_rarity),
        prefix_mismatch, {k: dict(v) for k, v in unregistered.items()},
        code_value_mismatch, stage_on_non_pokemon, card_type_unknown,
        const_violation, card_number_mismatch, type_forbidden,
        name_en_collision)


def render(era_mismatch, inconsistent, none_list, name_desync, empty_by_cat,
           drift_by_cat, rarity_by_cat, not_rarity, prefix_mismatch, unregistered,
           code_value_mismatch, categories, name_en_collision=()):
    out = []
    NL = chr(10)
    out.append(f"## 0d. 同じ英名を複数の日本語名が使っている — "
               f"{len(name_en_collision)} 組 / "
               f"{sum(sum(v.values()) for _, _, v in name_en_collision)} 行" + NL)
    out.append("別人の英名が入っていると、必ず本人の行と衝突してここに出る "
               "(`Arven` ← {ペパー, オルティガ} = 2026-08-24 のオルティガ)。"
               "**WARN のみ・自動修正しない**。表記ゆれの同一人物 (`ナッシー[Exeggutor]`) は "
               "畳んでから比べているので出ない。" + NL)
    if not name_en_collision:
        out.append("(なし)" + NL)
    for cat, en, jps in list(name_en_collision)[:40]:
        _s = ", ".join(f"{j}:{n}" for j, n in sorted(jps.items(), key=lambda kv: -kv[1]))
        out.append(f"- ⚠️ [{cat}] `{en}` <- {{{_s}}}" + NL)
    if len(name_en_collision) > 40:
        out.append(f"- … 他 {len(name_en_collision) - 40} 組" + NL)
    out.append(NL)
    out.append(f"## 0. 弾コード食い違い (別セットの名前) — {len(prefix_mismatch)} 件" + NL)
    out.append("eBay 値の頭の弾番号 (例 `Sv4k:`) と商品の弾コードが違う行。"
               "**0件で維持する**。変換表が誤っていると §6 では捕まらないので、この面で見る。" + NL)
    if not prefix_mismatch:
        out.append("(なし)" + NL)
    for pid, sc, e in prefix_mismatch[:40]:
        out.append(f"- ⚠️ `{pid}` (弾={sc}) → `{e}`" + NL)
    if len(prefix_mismatch) > 40:
        out.append(f"- … 他 {len(prefix_mismatch) - 40} 件" + NL)
    out.append(NL)
    out.append(f"## 0c. 別セットの名前 (弾番号が付いていない形) — {len(code_value_mismatch)} 行" + NL)
    out.append("eBay に **その弾自身の値が在る**のに、別の値が焼いてある行。"
               "`Sun & Moon` / `Triumphant` のような英語版セット名は弾番号が無いので "
               "§0 を素通りし、eBay に実在する値なので §0b も通る。**0件で維持する**。" + NL)
    if not code_value_mismatch:
        out.append("(なし)" + NL)
    else:
        _agg = defaultdict(int)
        _cand_of = {}
        for pid, sc, e, cand in code_value_mismatch:
            _agg[(sc, e)] += 1
            _cand_of[(sc, e)] = cand
        for (sc, e), n in sorted(_agg.items(), key=lambda kv: -kv[1])[:40]:
            out.append(f"- ⚠️ 弾={sc} `{e}` {n}行 → eBay に在る値: {_cand_of[(sc, e)]}" + NL)
        if len(_agg) > 40:
            out.append(f"- … 他 {len(_agg) - 40} 組" + NL)
    out.append(NL)
    n_unreg = sum(sum(v.values()) for v in (unregistered or {}).values())
    out.append(f"## 0b. 未登録のセット名 — {n_unreg} 行" + NL)
    out.append("set_name_ebay に入ってよいのは ① eBay master に在る値 か "
               "② `_free_text_set_values.yaml` に登録した値 だけ。"
               "**0件で維持する**。新しい誤った値は登録されていないので必ずここに出る。" + NL)
    if not n_unreg:
        out.append("(なし)" + NL)
    for _c, _vals in (unregistered or {}).items():
        for _v, _n in sorted(_vals.items(), key=lambda x: -x[1])[:20]:
            out.append(f"- ⚠️ {_c}: `{_v}` × {_n}件" + NL)
    out.append(NL)
    cat_s = ",".join(categories) if categories else "all"
    out.append(f"# set_name_ebay integrity audit (cat={cat_s})\n")
    out.append(f"## 1. era 不一致 (別era set名への誤map疑い) — {len(era_mismatch)} 件\n")
    if not era_mismatch:
        out.append("(なし)\n")
    for sc, e, sce, ee, cnt in era_mismatch:
        out.append(f"- ⚠️ `{sc}` ({sce}) → set_name_ebay=`{e}` ({ee}) × {cnt}件\n")

    out.append(f"\n## 2. set_code 内 set_name_ebay 不統一 — {len(inconsistent)} 件\n")
    if not inconsistent:
        out.append("(なし)\n")
    for sc, vals in inconsistent[:40]:
        out.append(f"- `{sc}`: {vals}\n")

    out.append(
        f"\n## 3. source=(none) 棚卸し (由来不明=未検証, set_code単位) — "
        f"{len(none_list)} set_code / 計 {sum(x[2] for x in none_list)} 件\n"
    )
    out.append("| set_code | set_name_ebay | 件数 | category |\n|---|---|---|---|\n")
    for sc, val, cnt, cat in none_list[:120]:
        out.append(f"| {sc} | {val} | {cnt} | {cat} |\n")

    out.append(
        f"\n## 4. name_en ≠ character_name (eBay C:Character 不整合) — "
        f"{len(name_desync)} 件\n"
    )
    if not name_desync:
        out.append("(なし)\n")
    for pid, ne, cn in name_desync[:60]:
        out.append(f"- `{pid}`: name_en=`{ne}` ≠ character_name=`{cn}`\n")

    # 5. empty 棚卸し (fail_closed_no_map + 単純空欄) を category 別に絶対数で。
    #    ★ 0 になっても出し続ける (0 が続いている証跡が再発しないことの唯一の証拠)。
    total_empty = sum(v["total_empty"] for v in empty_by_cat.values())
    total_fail_closed = sum(v["fail_closed_no_map"] for v in empty_by_cat.values())
    out.append(
        f"\n## 5. set_name_ebay 空欄 棚卸し (絶対数・毎日出す) — "
        f"合計 {total_empty} 件 (うち fail_closed_no_map {total_fail_closed})\n"
    )
    if not empty_by_cat:
        out.append("(全カテゴリで空欄ゼロ)\n")
    else:
        out.append("| category | fail_closed_no_map | blank(other) | total_empty |\n")
        out.append("|---|---:|---:|---:|\n")
        for cat in sorted(empty_by_cat.keys()):
            v = empty_by_cat[cat]
            out.append(
                f"| {cat} | {v['fail_closed_no_map']} | {v['blank']} | {v['total_empty']} |\n"
            )

    # 6. canonical ズレ検知 (specs.set_name_ebay ≠ 今その場で filter_map から計算した canonical)
    #    契約 v1.2 §1-5 (導出化=restamp+ズレ検知) の検出面。可視化のみ・gate にしない。
    #    ★ 0 になっても出し続ける (§5 と同じ規約)。
    #    state (a) canonical のズレのみ数える (computed が None = state (b)/(c) は除外)。
    total_drift = sum(drift_by_cat.values())
    out.append(
        f"\n## 6. canonical ズレ検知 (絶対数・毎日出す) — "
        f"合計 {total_drift} 件\n"
    )
    out.append(
        "定義: derive_set_name_ebay(cat, set_name_official, product_id) が非-None で、"
        "stored (specs.set_name_ebay) と異なる行 (= state (a) canonical のズレ)。"
        "state (b) 自由文字列 / state (c) 空 は drift 対象外 (契約 v1.2 §1-3)。"
        "★ gate にはしない (可視化のみ)。0 になっても出し続ける。\n"
    )
    if not drift_by_cat:
        out.append("(全カテゴリで drift ゼロ)\n")
    else:
        out.append("| category | drift |\n|---|---:|\n")
        for cat in sorted(drift_by_cat.keys()):
            out.append(f"| {cat} | {drift_by_cat[cat]} |\n")

    # 7. rarity 生値焼き付き検知 (2026-08-13 追加)
    #    2026-08-13 の実害 (cert158452539: rarity_ebay='L★' → 禁止文字除去で 'L' の1文字) と
    #    同型の値が C:Rarity に出ていないかを毎日可視化。§6 と同じく可視化のみ・gate にしない。
    total_raw = sum(v["raw_stamped"] for v in rarity_by_cat.values())
    total_md = sum(v["map_drift"] for v in rarity_by_cat.values())
    total_un = sum(v["unmapped"] for v in rarity_by_cat.values())
    total_ab = sum(v["accepted_blank"] for v in rarity_by_cat.values())
    out.append(
        f"\n## 7. rarity 生値焼き付き検知 (絶対数・毎日出す) — "
        f"raw_stamped {total_raw} / map_drift {total_md} / unmapped {total_un} "
        f"/ accepted_blank {total_ab} 件\n"
    )
    total_nr = sum(not_rarity.values())
    out.append(
        f"\n## 8. レアリティでない値の検知 (絶対数・毎日出す) — {total_nr} 件\n"
    )
    out.append(
        "- レアリティ語を1つも含まない specs.rarity_ebay。2 / New / European debut のような、"
        "そもそもレアリティでない値が C:Rarity に出ていないか。\n"
        "- 2026-08-21 に遊戯王で 118行 発見 (取り込み元の生値を passthrough していた)。"
        "1 でも増えたら取り込み側の穴。\n"
    )
    if not_rarity:
        out.append("| category | 値 | 件数 |\n|---|---|--:|\n")
        for (cat, v), n in sorted(not_rarity.items(), key=lambda x: -x[1])[:20]:
            out.append(f"| {cat} | `{v}` | {n} |\n")
    else:
        out.append("(なし)\n")
    out.append(
        "- **raw_stamped** = specs.rarity_ebay が公式生コードのまま (= 変換されていない)。"
        "'U' / 'LR+' / 'SPカード' 等がそのまま C:Rarity に出る = 2026-08-13 実害と同型。**要対応**。\n"
        "- **map_drift** = derive_rarity_ebay(cat, specs.rarity) ≠ stored。"
        "yaml/filter_map が旧短縮コードのままだと大量に出る (= yaml 未同期の指標)。\n"
        "- **unmapped** = 生 rarity は有るが変換先が無く stored も空 (= そのカードが出品されない)。"
        "fail-closed なので誤出品はしない。**1 でも増えたら新規の未変換が出た合図**。\n"
        "- **accepted_blank** = 出さないと決めた行 (specs.rarity_ebay_status 有り)。残件ではない。"
        "HQ 判断 2026-08-16 (requests/2026-08-16_rarity_absent_switch_response.md §③④)。\n"
        "★ / + は公式 rarity 語彙に無い刷り違いマーカーなので落としてから引く"
        "(公式 dbs-cardgame.com/fw = L/C/UC/R/SR/SCR/PR の 7 値, gundam-gcg.com = "
        "C/U/R/LR/LKC/LKU/LKR/P の 8 値, いずれも 2026-08-13 実取得)。\n"
    )
    if not rarity_by_cat:
        out.append("(全カテゴリでゼロ)\n")
    else:
        out.append("| category | raw_stamped | map_drift | unmapped | accepted_blank |\n"
                   "|---|---:|---:|---:|---:|\n")
        for cat in sorted(rarity_by_cat.keys()):
            v = rarity_by_cat[cat]
            out.append(f"| {cat} | {v['raw_stamped']} | {v['map_drift']} | {v['unmapped']} "
                       f"| {v['accepted_blank']} |\n")
    return "".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cat", default="pokemon_tcg",
                    help="category (pokemon_tcg 既定 / 'all' で全カテゴリ)")
    ap.add_argument("--out", default=None, help="md 出力先 (省略時 stdout)")
    args = ap.parse_args()
    categories = None if args.cat == "all" else [args.cat]

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    cat_s = ",".join(categories) if categories else "all"
    ts = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{_START_MARK} {ts} (cat={cat_s}) ===")

    # ★位置で受けない (節を足すたびにずれる。2026-08-23 / 08-25 に実際にずれた)
    res = audit(categories)
    (era_mismatch, inconsistent, none_list, name_desync,
     empty_by_cat, drift_by_cat, rarity_by_cat, not_rarity,
     prefix_mismatch, unregistered, code_value_mismatch,
     stage_on_non_pokemon, card_type_unknown, const_violation,
     card_number_mismatch, type_forbidden, name_en_collision) = (
        res.era_mismatch, res.inconsistent, res.none_list, res.name_desync,
        res.empty_by_cat, res.drift_by_cat, res.rarity_by_cat, res.not_rarity,
        res.prefix_mismatch, res.unregistered, res.code_value_mismatch,
        res.stage_on_non_pokemon, res.card_type_unknown, res.const_violation,
        res.card_number_mismatch, res.type_forbidden, res.name_en_collision)
    report = render(era_mismatch, inconsistent, none_list, name_desync,
                    empty_by_cat, drift_by_cat, rarity_by_cat, not_rarity,
                    prefix_mismatch, unregistered, code_value_mismatch,
                    categories or [], name_en_collision)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"wrote {args.out}")
    else:
        print(report)

    # ── base→_pN name 誤伝播の継続検出 (2026-08-01 name-guard, WARN のみ・自動修正なし) ──
    #   name_jp≠base なのに name_en/character_name が base と一致する _pN = 別カードに別キャラ名。
    #   これが >0 は name_guard.propagate_name_fields を通さない別経路の再混入。
    import os as _os
    sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from name_guard import find_variant_name_violations, find_facet_n1_candidates  # noqa: E402
    _conn = sqlite3.connect(str(DB_PATH))
    _cats = categories or ["pokemon_tcg", "one_piece_tcg", "gundam_tcg",
                           "dragonball_scg", "yugioh_tcg"]
    name_viol = []
    for _cat in _cats:
        name_viol += find_variant_name_violations(_conn, _cat)
    if name_viol:
        print(f"\n⚠️ [name-guard] base→_pN 名前誤伝播 {len(name_viol)} 件 (WARN, 自動修正なし):")
        for v in name_viol[:20]:
            print(f"    {v['product_id']}: name_jp={v['name_jp']!r} ≠ base={v['base_name_jp']!r} "
                  f"だが name_en/char が base と一致 (name_en={v['name_en']!r})")

    # set_name_ebay N:1 誤マップ候補 (WARN のみ・自動修正なし。allowlist=facet_n1_allowlist.yaml)
    facet_n1 = []
    for _cat in _cats:
        facet_n1 += [{**x, "category": _cat} for x in find_facet_n1_candidates(_conn, _cat)]
    _conn.close()
    if facet_n1:
        print(f"\n⚠️ [facet-N:1] allowlist 外の N:1 誤マップ候補 {len(facet_n1)} facet "
              f"(WARN・自動修正なし・一括null禁止。per-facet で窓口 GO 要):")
        for x in facet_n1[:30]:
            print(f"    {x['set_name_ebay']!r} <- stranger {list(x['strangers'].items())[:4]}")

    # 完走マーカー (末尾に必ず出す。ログの grep でこれが無ければ途中死亡).
    print(
        f"{_END_MARK}: era={len(era_mismatch)} inconsistent={len(inconsistent)} "
        f"none_src={len(none_list)} name_desync={len(name_desync)} "
        f"name_propagate_viol={len(name_viol)} facet_n1_candidates={len(facet_n1)} "
        f"canonical_drift={sum(drift_by_cat.values())} "
        f"code_value_mismatch={len(code_value_mismatch)} "
        f"stage_on_non_pokemon={len(stage_on_non_pokemon)} "
        f"card_type_unknown={len(card_type_unknown)} "
        f"const_violation={len(const_violation)} "
        f"card_number_mismatch={len(card_number_mismatch)} "
        f"type_forbidden={len(type_forbidden)} "
        f"name_en_collision={len(name_en_collision)} "
        f"rarity_raw_stamped={sum(v['raw_stamped'] for v in rarity_by_cat.values())} "
        f"rarity_map_drift={sum(v['map_drift'] for v in rarity_by_cat.values())} "
        f"rarity_unmapped={sum(v['unmapped'] for v in rarity_by_cat.values())} "
        f"rarity_accepted_blank={sum(v['accepted_blank'] for v in rarity_by_cat.values())} "
        f"not_a_rarity={sum(not_rarity.values())} ==="
    )


if __name__ == "__main__":
    main()
