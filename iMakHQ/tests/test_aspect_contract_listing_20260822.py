# -*- coding: utf-8 -*-
"""出品くんを「カタログの表を写すだけ」にした回帰テスト (2026-08-22)。

契約: `iMakCatalog/ebay_filter_map/_contract_aspects.yaml` (Catalog が唯一の表を持つ)
経緯: catalog/requests/2026-08-22_aspect_contract_hq_reply_response.md

守るもの:
  1. 出さないと決めた5列が CSV ヘッダに無い (Franchise/Autographed/Vintage/Material/Customized)
  2. ヘッダと行の要素数が一致する (列を消す時に行を消し忘れる事故の検出)
  3. 出品側の自前変換表が復活していない (Canonical Map / rarity→Features 補完 / Leader cost)
  4. C:Features は catalog の features_ebay だけから作る (レアリティ語を入れない)
  5. 新コアが空の時に旧値で埋め戻さない列に C:Features が入っている
     (= 8/22 に 'Art Rare' / 'Super Rare' が 4件 eBay に出た事故の再発防止)
"""
import ast
import io
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TCG = os.path.join(_ROOT, "iMakTCG")
if _TCG not in sys.path:
    sys.path.insert(0, _TCG)

DROPPED = ["C:Franchise", "C:Autographed", "C:Vintage", "C:Material", "C:Customized"]
GENERATORS = ["psa_to_csv.py", "psa_restock_csv.py"]

# ★2026-08-28→2026-09-01: 8/22 の契約変更を TCG にだけ入れて G-shock に入れず、6日後の
#   初走行で G-shock が全行除外された…と思われたが、真因は表を TCG 以外にも当てていた側
#   (csv_auditor.py) にあった。表は TCG (183454) 専用と 8/31 にカタログが宣言し、
#   load_contract(ebay_category=...) で category を絞るようにしたため、DROPPED 列を
#   G-shock/一番くじの generator から落とす必要はない (表がそもそも当たらない)。
#   ALL_GENERATORS は TCG だけに戻す。
#   出典: hq/requests/2026-08-28_act_code_proposals_gshock_response_question_response.md
ALL_GENERATORS = [("iMakTCG", g) for g in GENERATORS]
# headers/build_row(list) 形ではなく build_row が dict を返す generator
_DICT_ROW_GENERATORS = {("iMak_ichibankuji", "ichibankuji_to_csv.py")}


def _source(name, proj="iMakTCG"):
    return io.open(os.path.join(_ROOT, proj, name), encoding="utf-8").read()


def _dict_row_keys(src):
    """build_row が dict を返す generator の CSV 列名 (= dict のキー) を取る。"""
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == "build_row":
            for m in ast.walk(n):
                if isinstance(m, ast.Return) and isinstance(m.value, ast.Dict):
                    return [k.value for k in m.value.keys if isinstance(k, ast.Constant)]
    return None


def _csv_columns(proj, gen):
    """generator が出す CSV の列名一覧 (list 形 / dict 形 どちらも)。"""
    src = _source(gen, proj)
    if (proj, gen) in _DICT_ROW_GENERATORS:
        return _dict_row_keys(src)
    return _headers_and_row(src)[0]


def _headers_and_row(src):
    tree = ast.parse(src)
    headers = None
    for n in ast.walk(tree):
        if (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "headers"
                and isinstance(n.value, ast.List)):
            headers = [e.value for e in n.value.elts if isinstance(e, ast.Constant)]
    row = None
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == "build_row":
            for m in ast.walk(n):
                if isinstance(m, ast.Return) and isinstance(m.value, ast.List):
                    row = m.value.elts
    return headers, row


@pytest.mark.parametrize("gen", GENERATORS)
def test_dropped_columns_are_gone(gen):
    headers, _ = _headers_and_row(_source(gen))
    assert headers, f"{gen}: headers が見つからない"
    for col in DROPPED:
        assert col not in headers, f"{gen}: {col} は 2026-08-22 契約で出さない列"


@pytest.mark.parametrize("gen", GENERATORS)
def test_headers_and_row_have_same_length(gen):
    headers, row = _headers_and_row(_source(gen))
    assert headers and row, f"{gen}: headers / build_row の return が見つからない"
    assert len(headers) == len(row), (
        f"{gen}: ヘッダ {len(headers)} 列 vs 行 {len(row)} 値 — 列と値がずれている")


@pytest.mark.parametrize("gen", GENERATORS)
def test_no_self_made_value_tables(gen):
    src = _source(gen)
    for banned in ("_CANONICAL_RARITY_ONEPIECE", "_CANONICAL_CARD_TYPE",
                   "_CANONICAL_FEATURES", "[AUTO-FIX] Leader Cost",
                   "_RARITY_FEATURES_LOOKUP.get"):
        assert banned not in src, (
            f"{gen}: {banned} が復活している。値の判断は catalog が持つ (2026-08-22 契約)")


def test_features_come_from_catalog_features_ebay_only():
    src = _source("tcg_listing_fields.py")
    assert 'specs.get("features_ebay")' in src, "Features は catalog の features_ebay から取る"
    assert 'normalize_tcg_features(specs.get("features"))' not in src, (
        "生 features を出品側の表で正規化するのは 2026-08-22 契約で廃止")


def test_features_are_authoritative_even_when_empty():
    # ★2026-08-26: 列を1つずつ足す運用をやめ、契約表から決めるようにした
    #   (2026-08-25_act_code_proposals_tcg.md 提案4)。ここは AST ではなく
    #   **実際に使われる集合** を見る (足し忘れを構造ごと検出する)。
    import tcg_new_gen_override as O
    always = O.always_overwrite_cols()
    assert always, "カタログ権威の列が空 (契約表も退避値も読めていない)"
    for col in ("C:Features", "C:Rarity", "C:Manufacturer", "C:Country of Origin"):
        assert col in always, (
            f"{col} が value-only のままだと、catalog が空の時に旧コアの値が残る "
            "(2026-08-22 に C:Features='Art Rare' が 4件 eBay に出た)")


# =============================================================================
# 2026-08-23 追記: カタログ回答を受けた2件
#   - C:Speciality (ポケモンの EX/V/GX/VMAX 等) の列を足した
#   - catalog_audit の空欄カウントから暫定キー (cardID-*) を外した
# 出典: catalog/requests/2026-08-23_set_name_layer_and_cardid_rows_response.md
# =============================================================================

def test_speciality_column_exists_and_reads_catalog():
    for gen in GENERATORS:
        headers, row = _headers_and_row(_source(gen))
        assert "C:Speciality" in headers, f"{gen}: C:Speciality の列が無い (契約 emit=true)"
        assert len(headers) == len(row), f"{gen}: 列と値がずれている"
    src = _source("tcg_listing_fields.py")
    assert '"speciality_ebay":' in src, "Speciality は catalog の speciality_ebay から読む"


def test_provisional_cardid_rows_are_excluded_from_blank_count():
    tools = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
    src = io.open(os.path.join(tools, "catalog_audit.py"), encoding="utf-8").read()
    assert '_PROVISIONAL_PID_PREFIX = "cardID"' in src, "暫定キーの定義が消えている"
    assert "startswith(_PROVISIONAL_PID_PREFIX)" in src, \
        "cardID-* を母数から外していない (カタログ回答 2026-08-23: 無いものとして扱う)"


# =============================================================================
# 2026-08-28 追記: 契約の照合を TCG 以外の generator にも掛ける
#   出典: hq/requests/2026-08-28_act_code_proposals_gshock_response.md 提案1・2
# =============================================================================

@pytest.mark.parametrize("proj,gen", ALL_GENERATORS)
def test_dropped_columns_are_gone_all_generators(proj, gen):
    cols = _csv_columns(proj, gen)
    assert cols, f"{proj}/{gen}: CSV の列名が取れない"
    for col in DROPPED:
        assert col not in cols, (
            f"{proj}/{gen}: {col} は 2026-08-22 契約で出さない列 "
            "(値が入っていると監査くんが全行除外する)")


@pytest.mark.parametrize("proj,gen", [pair for pair in ALL_GENERATORS
                                      if pair not in _DICT_ROW_GENERATORS])
def test_headers_and_row_have_same_length_all_generators(proj, gen):
    headers, row = _headers_and_row(_source(gen, proj))
    assert headers and row, f"{proj}/{gen}: headers / build_row の return が見つからない"
    assert len(headers) == len(row), (
        f"{proj}/{gen}: ヘッダ {len(headers)} 列 vs 行 {len(row)} 値 — 列と値がずれている")
