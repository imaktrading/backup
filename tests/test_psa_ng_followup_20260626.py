# -*- coding: utf-8 -*-
"""PSA NG 後追い修正 回帰テスト (2026-06-26)。

① viewer 候補生成: auto-pick が変種フルpid (ST03-013_PRB01_1) でも base まで削って
   兄弟変種を surface する (Boa Hancock PRB01 Alt Art が選べなかった件)。base prefix 導出を検証。
② 抽出スキップ: 出品済(itemID非空の同KEY行が在る)カードの2枚目(itemID空・同KEY)を
   抽出段階で除外する listed_keys 純関数 (Delibird M1S-074 毎回再表示の件)。

(pre-commit が collect する tests/ に配置)
"""
import os
import sys

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_ROOT, "iMakHQ", "tools"))

from sheet_io import listed_keys, PRODUCT_COL_ITEMID, PRODUCT_COL_KEY  # noqa: E402


def _row(itemid="", key=""):
    """B(1)=itemid, AI(34)=key の疎な行を作る。"""
    r = [""] * 35
    r[PRODUCT_COL_ITEMID] = itemid
    r[PRODUCT_COL_KEY] = key
    return r


# ============================ ② listed_keys ============================

def test_listed_keys_marks_card_with_any_itemid_filled_row():
    """同KEYで itemID 埋め行が1つでも在れば「出品済」。"""
    rows = [
        ["header"],
        _row(itemid="v1|123", key="M1S-074"),   # 出品済(1枚目)
        _row(itemid="",       key="M1S-074"),   # 2枚目(itemID空・同KEY) = Delibird 型
        _row(itemid="",       key="XY-139"),    # 未出品(itemID空のみ)
    ]
    lk = listed_keys(rows)
    assert "M1S-074" in lk          # itemID埋め行が在る → 出品済
    assert "XY-139" not in lk       # itemID埋め行が無い → 未出品(初回は抽出されるべき)


def test_listed_keys_skips_url_keys_and_blanks():
    rows = [
        ["header"],
        _row(itemid="v1|9", key="item:12345"),    # url-key は除外
        _row(itemid="v1|8", key="shops:abc"),     # url-key は除外
        _row(itemid="v1|7", key=""),              # KEY空は除外
    ]
    assert listed_keys(rows) == set()


def test_listed_keys_extraction_skip_semantics():
    """抽出ループ相当: B空 かつ KEY が listed なら除外、未listed/KEY空は通す。"""
    rows = [
        ["header"],
        _row(itemid="v1|123", key="M1S-074"),   # 出品済1枚目
        _row(itemid="",       key="M1S-074"),   # ← これは除外されるべき
        _row(itemid="",       key="OP01-013"),  # 未出品 → 通す
        _row(itemid="",       key=""),          # KEY未記入 → 安全側で通す
    ]
    lk = listed_keys(rows)
    extracted = []
    for r in rows[1:]:
        item_id = r[PRODUCT_COL_ITEMID].strip()
        key_v = r[PRODUCT_COL_KEY].strip()
        if item_id:           # B非空 = 既処理 → 抽出対象外(従来挙動)
            continue
        if key_v and key_v in lk:   # 出品済の2枚目 → 除外(本fix)
            continue
        extracted.append(key_v)
    assert extracted == ["OP01-013", ""]   # M1S-074 2枚目は除外、未出品とKEY空は残る


# ============================ ① base prefix 導出 ============================

def _base_prefix(expected_product_id):
    """post_psa_review._get_candidates の優先度1 prefix 導出と同一ロジック。"""
    return expected_product_id.rsplit("_", 1)[0] if "_" in expected_product_id else expected_product_id


def test_base_prefix_strips_variant_suffix_for_reprint():
    # 変種suffix付き reprint → base まで削れて兄弟変種(_1.._5)が prefix hit する
    assert _base_prefix("ST03-013_PRB01_1") == "ST03-013_PRB01"
    assert _base_prefix("OP13-108_p2") == "OP13-108"


def test_base_prefix_keeps_plain_pokemon_pid():
    # underscore 無し(Pokemon ハイフンpid)は据え置き = 従来挙動温存
    assert _base_prefix("M1S-074") == "M1S-074"
    assert _base_prefix("XY-139") == "XY-139"
