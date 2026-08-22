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

_TCG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "iMakTCG")
if _TCG not in sys.path:
    sys.path.insert(0, _TCG)

DROPPED = ["C:Franchise", "C:Autographed", "C:Vintage", "C:Material", "C:Customized"]
GENERATORS = ["psa_to_csv.py", "psa_restock_csv.py"]


def _source(name):
    return io.open(os.path.join(_TCG, name), encoding="utf-8").read()


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
    src = _source("tcg_new_gen_override.py")
    tree = ast.parse(src)
    always = None
    for n in ast.walk(tree):
        if (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_ALWAYS_OVERWRITE"
                and isinstance(n.value, ast.Set)):
            always = {e.value for e in n.value.elts if isinstance(e, ast.Constant)}
    assert always, "_ALWAYS_OVERWRITE が見つからない"
    for col in ("C:Features", "C:Rarity", "C:Manufacturer", "C:Country of Origin"):
        assert col in always, (
            f"{col} が value-only のままだと、catalog が空の時に旧コアの値が残る "
            "(2026-08-22 に C:Features='Art Rare' が 4件 eBay に出た)")
