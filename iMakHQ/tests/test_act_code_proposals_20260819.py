# -*- coding: utf-8 -*-
"""2026-08-19 回答書 `2026-08-19_act_code_proposals_tcg_response.md` の実装 回帰テスト.

判定 (1丁目1番地): **全件 ②出品くん側**。catalog のデータは正しい。

対象 (回答書の番号):
  1  F  … newcand_confirm.catalog_variants が実在しない specs キーを引いていた
  2  G+I+P3 … scope gate が 非日本語Pokemon / ウエハース / Web期 を全部通していた
  3  ③ … 兄弟 variant が在るのに目視の候補欄が開かない
  4  ② … _PID_OK を握り潰さず missing_models に流す
  5  C  … title / category が空のまま catalog 依頼を起票しない
  6  ④+P5 … --log 無しでも生成ログを見る (探索関数を ai_degraded と共有)
  7  P1 … missing_models の読み側を utf-8-sig に
  8  P2 … rarity 逆引きを派生辞書1本で (Pokemon は展開済み綴りで来る)
  9  P4 … 推奨Item Specifics も必須側と同じ card-aware に
"""
import csv
import importlib.util
import os
import re
import sqlite3
import sys

import pytest

_HERE = os.path.dirname(__file__)
_TOOLS = os.path.join(_HERE, "..", "tools")
_TCG = os.path.normpath(os.path.join(_HERE, "..", "..", "iMakTCG"))
sys.path.insert(0, _TOOLS)
sys.path.insert(0, _TCG)


def _load(name, path):
    """独立 module として読み込む (import 副作用を他テストに漏らさない)。"""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read(name):
    for base in (_TOOLS, _TCG):
        p = os.path.join(base, name)
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                return f.read()
    raise FileNotFoundError(name)


# =============================================================================
# 1. F: catalog_variants が実在するキー (card_number_text) を引く
# =============================================================================

def _mini_catalog(tmp_path):
    """products 最小 fixture。specs は catalog 実物と同じ `card_number_text` を持つ。"""
    db = tmp_path / "products.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE products (product_id TEXT, category TEXT, name TEXT, "
                "name_en TEXT, images TEXT, language TEXT, specs TEXT)")
    con.executemany(
        "INSERT INTO products VALUES (?,?,?,?,?,?,?)",
        [("S12a-214", "pokemon_tcg", "シママ", "Simisear", "", "ja",
          '{"card_number_text": "214/172", "rarity": "SAR"}'),
         ("S12a-215", "pokemon_tcg", "スイクン", "Suicune", "", "ja",
          '{"card_number_text": "215/172"}'),
         # 前方一致だと誤って当たる別カード (完全一致なら当たらない)
         ("S12a-999", "pokemon_tcg", "別カード", "Other", "", "ja",
          '{"card_number_text": "214/1720"}')])
    con.commit()
    con.close()
    return str(db)


def test_catalog_variants_uses_card_number_text(tmp_path):
    """印刷番号 (214/172) で候補が引ける。旧実装は `card_number` を引いて常に0件だった。"""
    nc = _load("newcand_confirm_t1", os.path.join(_TOOLS, "newcand_confirm.py"))
    cands = nc.catalog_variants("214/172", db=_mini_catalog(tmp_path))
    pids = [c["pid"] if isinstance(c, dict) else c[0] for c in cands]
    assert pids == ["S12a-214"], f"card_number_text で1件に解決できていない: {pids}"


def test_catalog_variants_no_longer_queries_dead_key():
    """死にキー `card_number` を引く SQL が残っていないこと (実測 DB 0件)。"""
    src = _read("newcand_confirm.py")
    assert '"card_number": ' not in src, "実在しない specs キー card_number をまだ引いている"
    assert "card_number_text" in src


# =============================================================================
# 2. G+I+P3: scope gate (非日本語Pokemon / ウエハース / Web期)
# =============================================================================

@pytest.mark.parametrize("franchise,brand", [
    ("Pokemon", "POKEMON SWORD AND SHIELD CROWN ZENITH"),       # G: 英語版 (catalog en=0件)
    ("Pokemon", "POKEMON KOREAN SV7-STELLAR MIRACLE"),          # G: 韓国版
    ("One Piece", "ONE PIECE WAFERS JAPANESE 20TH ANNIVERSARY"),  # I: 食玩
    ("Pokemon", "POKEMON JAPANESE WEB"),                          # P3: Web期
])
def test_scope_gate_blocks_new_cases(franchise, brand):
    from tcg_scope import is_out_of_scope
    oos, reason = is_out_of_scope(franchise, brand)
    assert oos, f"scope gate を素通りしている: {brand!r}"
    assert reason


@pytest.mark.parametrize("franchise,brand", [
    # catalog が **持っている**ものは1件も止めない (出品数を変えない)
    ("Pokemon", "POKEMON JAPANESE SV4A SHINY TREASURE EX"),
    ("One Piece", "ONE PIECE JAPANESE OP08-TWO LEGENDS"),
    # one_piece_tcg は en 1,710件 (うち ROMANCE DAWN 153件) を持つので英語版でも止めない
    ("One Piece", "ONE PIECE ENGLISH ROMANCE DAWN"),
    ("One Piece", "ONE PIECE JAPANESE ENGLISH VERSION 2ND ANNIVERSARY SET"),
    ("Dragon Ball", "DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE AWAKENED PULSE"),
])
def test_scope_gate_keeps_listable_brands(franchise, brand):
    from tcg_scope import is_out_of_scope
    assert not is_out_of_scope(franchise, brand)[0], f"出品できる brand を止めている: {brand!r}"


def test_scope_gate_language_rule_has_catalog_escape():
    """PSA の誤ラベル (日本版を ASIA と書く) は catalog 解決で救う = recall 損を出さない。

    実例 cert142931332 `POKEMON ASIA 25TH ANNIVERSARY PROMO` = 日本版 S8a-G-005。
    """
    from tcg_scope import is_out_of_scope
    brand = "POKEMON ASIA 25TH ANNIVERSARY PROMO"
    assert is_out_of_scope("Pokemon", brand)[0]
    assert not is_out_of_scope("Pokemon", brand, catalog_resolves=lambda: True)[0]


def test_build_row_passes_catalog_escape():
    """build_row が逃がし口を渡していること (渡し忘れると日本版が落ちる)。"""
    src = _read("psa_to_csv.py")
    assert re.search(r"_is_out_of_scope\(\s*franchise,\s*brand,\s*\n?\s*catalog_resolves=", src), \
        "build_row が catalog_resolves を渡していない (誤ラベル日本版が skip される)"


def test_word_boundary_web_only():
    """`WEB` は語として見る (`WEBBED` 等を巻き込まない)。"""
    from tcg_scope import is_out_of_scope
    assert not is_out_of_scope("Pokemon", "POKEMON JAPANESE WEBBED WONDERS")[0]


# =============================================================================
# 3. ③: 兄弟 variant が在るなら候補欄を開く
# =============================================================================

def test_has_sibling_variants_opens_on_base_underscore():
    ppr = _load("post_psa_review_t3", os.path.join(_TOOLS, "post_psa_review.py"))
    # 期待値が base、兄弟が `_p1`
    assert ppr.has_sibling_variants("EB02-003", ["EB02-003", "EB02-003_p1", "EB02-003_p2"])
    # 期待値が変種、base が別に在る
    assert ppr.has_sibling_variants("EB02-003_p1", ["EB02-003", "EB02-003_p1"])
    # 兄弟が無ければ従来どおり閉じる
    assert not ppr.has_sibling_variants("EB02-003", ["EB02-003"])
    assert not ppr.has_sibling_variants("S12a-214", ["S12a-214", "S12a-215"])
    assert not ppr.has_sibling_variants("", ["EB02-003_p1"])


def test_is_open_uses_sibling_check_not_wordlist():
    """開く条件が語リスト (ALTERNATE ART 等) になっていないこと。"""
    src = _read("post_psa_review.py")
    m = re.search(r"is_open = .*?\n(?:.*?\n){0,2}", src)
    assert m and "has_sibling_variants" in m.group(0), "is_open が兄弟 variant を見ていない"
    # 開く判定そのものが絵柄の語を見ていないこと (載っていない語で必ず同じ穴が開く)
    body = m.group(0).upper()
    for word in ("ALTERNATE ART", "PARALLEL", "PROMO", "1ST ED"):
        assert word not in body, f"is_open が絵柄の語リストで判定している: {word}"


# =============================================================================
# 4. ②: _PID_OK を握り潰さず missing_models に流す
# =============================================================================

def _catalog_with_pid(tmp_path, images="http://x/a.png"):
    db = tmp_path / "cat.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE products (product_id TEXT, category TEXT, images TEXT)")
    con.execute("INSERT INTO products VALUES ('EB02-003','one_piece_tcg',?)", (images,))
    con.commit()
    con.close()
    return str(db)


def test_pid_ok_now_writes_missing_models(tmp_path, monkeypatch):
    """catalog に行も画像も在るのに人が NONE → variant 欠落の疑いとして必ず流す。"""
    ppr = _load("post_psa_review_t4", os.path.join(_TOOLS, "post_psa_review.py"))
    monkeypatch.setattr(ppr, "_get_psa_cache",
                        lambda cert: {"Brand": "ONE PIECE JAPANESE EB02",
                                      "Subject": "CHOPPER", "CardNumber": "003"})
    missing = tmp_path / "missing_models.csv"
    vd = tmp_path / "viewer_disagreement.log"
    n = ppr._route_none_to_catalog(
        [{"cert": "168157614", "category": "one_piece_tcg", "expected": "EB02-003"}],
        missing_path=str(missing), trigger_request=False,
        viewer_disagreement_path=str(vd), catalog_db=_catalog_with_pid(tmp_path))
    assert n == 1, "_PID_OK が握り潰されている (以前の continue が残っている)"
    body = missing.read_text(encoding="utf-8")
    assert "variant欠落の疑い" in body, f"理由が書き分けられていない: {body}"
    assert vd.exists(), "経緯用の viewer_disagreement.log は残す"


def test_variant_gap_row_survives_watcher_precheck():
    """watcher の catalog実在 pre-check が variant欠落行を握り潰さないこと。"""
    acar = _load("auto_catalog_add_request_t4",
                 os.path.join(_TOOLS, "auto_catalog_add_request.py"))
    model = ("cert168157614 ONE PIECE JAPANESE EB02 [CHOPPER] #003 "
             "(catalog EB02-003 は在る(画像あり)が人が現物と別絵柄と判断 variant欠落の疑い)")
    new_by_cat = {"one_piece_tcg": [{"category": "one_piece_tcg", "model": model,
                                     "detected_at": "2026-08-19 00:00:00"}]}
    removed = acar._filter_catalog_present(new_by_cat, None)
    assert removed == 0, "variant欠落行が catalog実在 pre-check で落ちている"
    assert new_by_cat["one_piece_tcg"]


# =============================================================================
# 5. C: 入口検査 (title / category 空 / 別カテゴリ URL)
# =============================================================================

_ACAR = None


def _acar():
    global _ACAR
    if _ACAR is None:
        _ACAR = _load("auto_catalog_add_request_t5",
                      os.path.join(_TOOLS, "auto_catalog_add_request.py"))
    return _ACAR


@pytest.mark.parametrize("category,model", [
    # 2026-08-17 に実際に出た依頼書 (カテゴリ欄が空・本文が「`` カテゴリの…」)
    ("", "番号不明  (捨てた仕入候補の目視 2026-08-17 / https://jp.mercari.com/item/m62052158191)"),
    ("one_piece_tcg", "番号不明  (捨てた仕入候補の目視 2026-08-17 / https://jp.mercari.com/item/m53731037142)"),
    ("tcg", "OP05-002 (捨てた仕入候補の目視 2026-08-14 / https://snkrdunk.com/apparels/12345)"),
])
def test_entry_check_rejects(category, model):
    assert _acar().reject_reason(category, model), f"起票してはいけない行を通している: {model!r}"


@pytest.mark.parametrize("category,model", [
    ("one_piece_tcg", "OP05-002 モンキー・D・ルフィ (捨てた仕入候補の目視 2026-08-19 / https://jp.mercari.com/item/m1)"),
    ("pokemon_tcg", "cert152136358 POKEMON JAPANESE SV4A [PIKACHU] #014 (auto候補SV4A-014=該当なし 要調査)"),
    ("one_piece_tcg", "ONE PIECE JAPANESE 3RD ANNIVERSARY SET-118"),
    # TCG 以外なら apparels URL は正当
    ("uniqlo_ut", "UT-001 ワンピース Tシャツ (https://snkrdunk.com/apparels/12345)"),
])
def test_entry_check_passes(category, model):
    assert _acar().reject_reason(category, model) is None, f"正当な行を弾いている: {model!r}"


def test_entry_check_logs_and_drops(tmp_path):
    """silent drop しない: 落とした行は理由付きで log に残る。"""
    acar = _acar()
    log = tmp_path / "missing_models_rejected.log"
    cat = "one_piece_tcg"
    model = "番号不明  (捨てた仕入候補の目視 2026-08-17 / https://jp.mercari.com/item/m620)"
    new_by_cat = {cat: [{"category": cat, "model": model, "detected_at": "2026-08-17 00:00:00"}]}
    unique = {(cat, model): new_by_cat[cat][0]}
    removed = acar._filter_invalid_entries(new_by_cat, unique, log_path=log)
    assert removed == 1
    assert new_by_cat == {} and unique == {}
    assert "タイトル空" in log.read_text(encoding="utf-8")


def test_main_runs_entry_check():
    src = _read("auto_catalog_add_request.py")
    assert "_filter_invalid_entries(new_by_cat, unique)" in src, \
        "main() が入口検査を呼んでいない"


# =============================================================================
# 6. ④+P5: --log 無しでも生成ログを見る (探索関数の共有)
# =============================================================================

def test_scan_log_finds_generation_log_without_log_flag(tmp_path):
    ca = _load("csv_auditor_t6", os.path.join(_TOOLS, "csv_auditor.py"))
    run_logs = tmp_path / "run_logs"
    run_logs.mkdir()
    csv_path = str(tmp_path / "tcg_20260819.csv")
    (run_logs / "gen.log").write_text(
        "出力: " + os.path.basename(csv_path) + "\nmissing_models に追記\n❌ Traceback\n",
        encoding="utf-8")
    sig = ca._scan_log("", csv_path, str(run_logs))
    assert sig, "--log 無しだと生成ログを見ていない (digest の logシグナルが恒久的に空)"
    assert any("catalog miss" in s for s in sig)
    assert any("error" in s for s in sig)


def test_scan_log_and_ai_degraded_share_one_finder():
    src = _read("csv_auditor.py")
    assert src.count("generation_logs_for(csv_path, run_logs_dir)") == 1, \
        "ログ探索が2箇所に分かれている (片方だけズレる)"
    assert "read_run_logs" in src
    assert "_scan_log(log_path, csv_path)" in src, "呼出側が csv_path を渡していない"


# =============================================================================
# 7. P1: missing_models の読み側を utf-8-sig に
# =============================================================================

def test_missing_models_read_tolerates_bom(tmp_path, monkeypatch):
    acar = _acar()
    p = tmp_path / "missing_models.csv"
    p.write_text("category,model,detected_at\n"
                 "one_piece_tcg,OP05-002 ルフィ,2026-08-19 00:00:00\n",
                 encoding="utf-8-sig")
    with p.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["category"] == "one_piece_tcg"   # BOM が残ると KeyError になる
    src = _read("auto_catalog_add_request.py")
    assert 'MISSING_CSV.open(encoding="utf-8-sig")' in src
    assert 'PROCESSED_CSV.open(encoding="utf-8-sig")' in src
    # 書く側は触らない (BOM を新規に増やさない)
    assert 'MISSING_CSV.open("w", encoding="utf-8", newline="")' in src


# =============================================================================
# 8. P2: rarity 逆引きは派生辞書1本 (表を2つにしない)
# =============================================================================

def test_rarity_features_lookup_accepts_both_spellings():
    mod = _load("psa_to_csv_t8", os.path.join(_TCG, "psa_to_csv.py"))
    lut = mod._RARITY_FEATURES_LOOKUP
    assert lut["SAR"] == "Special Art Rare"                 # One Piece = 略号
    assert lut["SPECIAL ART RARE"] == "Special Art Rare"    # Pokemon = 展開済
    assert lut["ULTRA RARE"] == "Ultra Rare"
    assert lut["ART RARE"] == "Art Rare"
    # 派生元は1つだけ (手で綴りを足していない = 片方だけ更新される事故を防ぐ)
    for k, v in mod._RARITY_TO_FEATURES.items():
        assert lut[k] == v and lut[v.upper()] == v


def test_features_fallback_uses_derived_lookup():
    src = _read("psa_to_csv.py")
    assert "_RARITY_FEATURES_LOOKUP.get((official_rarity" in src, \
        "Features 補完がまだ略号だけの表を引いている (Pokemon で100%空振り)"


# =============================================================================
# 9. P4: 推奨Item Specifics も card-aware
# =============================================================================

def _check_csv():
    """★`check_csv.py` は 4 プロジェクトに同名で在る (TCG/G-shock/Mercari/一番くじ)。
    `import check_csv` だと走行順で別プロジェクトのものを掴むので、**パス指定で読む**。"""
    return _load("check_csv_tcg_t9", os.path.join(_TCG, "check_csv.py"))


def test_recommended_specifics_drops_finish_always():
    cc = _check_csv()
    for game in ("Pokemon", "One Piece Card Game", ""):
        assert "C:Finish" not in cc.recommended_specifics_for_card("OP05-002", "Character", game), \
            "C:Finish は generator が投入禁止 = 警告が原理的に無意味"


def test_recommended_specifics_drops_pokemon_only_fields():
    cc = _check_csv()
    poke = cc.recommended_specifics_for_card("S12a-214", "Pokémon", "Pokemon")
    assert "C:Cost" not in poke and "C:Attribute/MTG:Color" not in poke
    op = cc.recommended_specifics_for_card("OP05-002", "Character", "One Piece Card Game")
    assert "C:Cost" in op and "C:Attribute/MTG:Color" in op, "One Piece からは落とさない"
    # C:Features は残す (P2 の実害はここで拾う)
    assert "C:Features" in poke and "C:Features" in op


def test_recommended_specifics_keeps_warning_when_game_unknown():
    """canonical 値が引けない時は Pokemon 除外を効かせない (判定不能で警告を消さない)。"""
    cc = _check_csv()
    unknown = cc.recommended_specifics_for_card("S12a-214", "", "")
    assert "C:Cost" in unknown


def test_check_csv_routes_through_helper():
    src = _read("check_csv.py")
    assert "recommended_specifics_for_card(_card_key" in src, \
        "check_csv が推奨側を helper 経由にしていない"
