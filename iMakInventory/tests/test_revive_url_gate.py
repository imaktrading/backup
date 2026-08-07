"""復活 (qty=1) URL 白/黒リスト gate の regression test (2026-08-07 revive_qty1_impl §2).

依頼書 完了条件 2 「誤復活の回帰テスト (メルカリ個人/ラクマ/スニダン)」 の直接テスト。

`is_restockable_url` / `is_one_off_url` / apply_gates() の URL 白リスト gate が
「在庫数を持つ仕入元」だけを復活対象にすること (fail-closed) を担保する。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sheet_updater import is_restockable_url, is_one_off_url  # noqa: E402


# ============================================================================
# 「在庫数を持つ仕入元」= True になる URL 群
# ============================================================================
def test_amazon_url_is_restockable():
    assert is_restockable_url("https://www.amazon.co.jp/dp/B0BNHJJSZ6") is True
    assert is_restockable_url("amazon.co.jp/dp/B0BNHJJSZ6") is True


def test_yodobashi_url_is_restockable():
    assert is_restockable_url("https://www.yodobashi.com/product/100000001007829398/") is True


def test_mercari_shops_is_restockable():
    assert is_restockable_url(
        "https://jp.mercari.com/shops/product/2JSDt2MXNwo8qctznkcHSr") is True


def test_official_domains_are_restockable():
    assert is_restockable_url("https://www.uniqlo.com/jp/ja/products/E469121") is True
    assert is_restockable_url("https://webshop.montbell.jp/goods/disp.php?product_id=1123456") is True
    assert is_restockable_url("https://workman.jp/shop/g/g2300099999999") is True
    assert is_restockable_url("https://www.gu-global.com/jp/ja/products/E362000-000") is True


# ============================================================================
# 1点もの (= 復活が原理的にありえない) = False になる URL 群
# ============================================================================
def test_mercari_personal_item_is_not_restockable():
    assert is_restockable_url("https://jp.mercari.com/item/m12345678901") is False


def test_rakuma_fril_is_not_restockable():
    assert is_restockable_url("https://item.fril.jp/abc123def456") is False


def test_snkrdunk_is_not_restockable():
    assert is_restockable_url("https://snkrdunk.com/products/12345") is False


def test_yahoo_auc_is_not_restockable():
    assert is_restockable_url("https://page.auctions.yahoo.co.jp/jp/auction/x123") is False


def test_paypay_flea_is_not_restockable():
    assert is_restockable_url(
        "https://paypayfleamarket.yahoo.co.jp/item/z123") is False


# ============================================================================
# fail-closed: 未知ドメイン / 空 / 不正 → 全て False (復活しない)
# ============================================================================
def test_unknown_domain_is_not_restockable():
    assert is_restockable_url("https://example.com/foo") is False


def test_empty_url_is_not_restockable():
    assert is_restockable_url("") is False
    assert is_restockable_url(None) is False


# ============================================================================
# is_one_off_url の対称テスト (1点もの群だけ True)
# ============================================================================
def test_is_one_off_mercari_personal_only():
    assert is_one_off_url("https://jp.mercari.com/item/m12345678901") is True
    # SHOPS は 1点ものではない
    assert is_one_off_url(
        "https://jp.mercari.com/shops/product/2JSDt2MXNwo8qctznkcHSr") is False


def test_is_one_off_other_marketplaces():
    assert is_one_off_url("https://item.fril.jp/abc123") is True
    assert is_one_off_url("https://snkrdunk.com/products/12345") is True
    assert is_one_off_url("https://page.auctions.yahoo.co.jp/jp/auction/x1") is True
    assert is_one_off_url("https://paypayfleamarket.yahoo.co.jp/item/z1") is True


def test_is_one_off_restockable_sources_are_false():
    """在庫数を持つ源は 1点ものではない (対称: restockable と one_off は排他)。"""
    assert is_one_off_url("https://www.amazon.co.jp/dp/B0BNHJJSZ6") is False
    assert is_one_off_url("https://www.yodobashi.com/product/100000001007829398/") is False
    assert is_one_off_url("https://www.uniqlo.com/jp/ja/products/E469121") is False
    assert is_one_off_url("") is False


# ============================================================================
# apply_gates 経由の URL 白リスト gate: 1点もの行が deferred へ落ちること
# ============================================================================
def test_apply_gates_url_whitelist_excludes_one_off():
    """apply_gates() で is_restockable_url=False の候補が deferred に落ちる (BAN 直撃防止)。"""
    from ebay_actions.revive_csv_generator import apply_gates  # noqa: PLC0415
    from datetime import datetime  # noqa: PLC0415

    candidates = [
        # 個人メルカリ (1点もの) → URL 白リスト gate で reject
        {"row_index": 10, "url": "https://jp.mercari.com/item/m12345678901",
         "item_id": "IID_MERCARI_PERSONAL", "title": "個人メルカリ",
         "current_sold": "", "err_flag_prev": "", "checked_at": "",
         "sheet_label": "HIGH", "key_number": "", "category": "TCG",
         "price": "5000", "current_m_jpy_str": "5000"},
        # スニダン → reject
        {"row_index": 11, "url": "https://snkrdunk.com/products/999",
         "item_id": "IID_SNKRDUNK", "title": "スニダン",
         "current_sold": "", "err_flag_prev": "", "checked_at": "",
         "sheet_label": "HIGH", "key_number": "", "category": "TCG",
         "price": "8000", "current_m_jpy_str": "8000"},
        # ラクマ → reject
        {"row_index": 12, "url": "https://item.fril.jp/xyz",
         "item_id": "IID_FRIL", "title": "ラクマ",
         "current_sold": "", "err_flag_prev": "", "checked_at": "",
         "sheet_label": "HIGH", "key_number": "", "category": "TCG",
         "price": "3000", "current_m_jpy_str": "3000"},
    ]

    allowed, deferred, price_hold = apply_gates(
        candidates=candidates,
        sheet_key_maps={"HIGH": {}},
        cycle_started_at=datetime.now(),
        active_qty_map={},
        fetch_price_fn=lambda iid: (100.0, 0),
        compute_fn=lambda cost, med, cat: {"price": 50.0},
    )
    assert len(allowed) == 0, "1点もの URL が復活 allowed に混入した (BAN 直撃)"
    assert len(deferred) == 3
    for d in deferred:
        assert d["skip_reason"] == "url_not_restockable"
        assert d["gate"] == "url_whitelist"
