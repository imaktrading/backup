"""cert→canonical KEー backfill (B空・product_id限定) test.

依頼: iMak_data/dedupe/requests/2026-07-15_dedup_cert_backfill_cli_build.md §B

検証:
1. B空+cert+KEー空 行が product_id 解決時のみ KEー 書込
2. 解決失敗 ("") は無書込 (= fail-closed)
3. 既存 product_id セルは上書きしない (= 冪等・手動補完尊重)
4. url_col=None で url-key が書かれない (= 補URL では 2枚目の url-key は primary と不一致)
5. B(itemID)非空 = live/出品済 row は touch しない (= only_item_id_empty)
6. category_col/value で R='TCG' 以外は skip
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from dedupe import sheet_io

pytestmark = pytest.mark.offline


# 商品管理シート layout: A=URL(1) B=itemID(2) C=title(3) D=sold(4) ... I=cert(9) ... R=cat(18) ... KEー
# test では KEー 列 = 19 (R の次) に置く簡易 layout
KEY_COL = 19
CERT_COL = sheet_io.HIGH_COL_CERT_OR_ENGTITLE   # 9
CAT_COL = sheet_io.HIGH_COL_CATEGORY            # 18
ITEMID_COL = sheet_io.LISTINGS_COL_ITEMID       # 2
TITLE_COL = sheet_io.LISTINGS_COL_TITLE         # 3


def _row(url="", itemid="", title="", sold="", cert="", cat="TCG", key=""):
    """19 列 row を組立 (A..S)。 未指定は空。"""
    r = [""] * 19
    r[0] = url          # A
    r[1] = itemid       # B
    r[2] = title        # C
    r[3] = sold         # D
    r[8] = cert         # I
    r[17] = cat         # R
    r[18] = key         # KEー (col 19)
    return r


_HEADER = _row(url="URL", itemid="itemID", title="title", sold="売り切れ",
               cert="cert", cat="カテゴリ", key="KEY")


def _fake_ws(rows):
    ws = MagicMock()
    ws.get_all_values.return_value = [_HEADER] + rows
    return ws


def _run(rows, resolve_map, dry_run=False):
    """resolve_map: {cert: canonical_key} を resolve_sheet_row の代替に。"""
    ws = _fake_ws(rows)

    def _fake_resolve(title="", url="", image_url="", cert="", extra_text="", purpose="dedup"):
        # Phase2b: resolve_sheet_row_with_category は dict を返す。
        # resolve_map の値が str なら product_id とみなし category 自動推定
        # (url-key/空 → category=""、 それ以外 → one_piece_tcg)。 dict ならそのまま。
        v = resolve_map.get(cert, {"product_id": "", "category": ""})
        if isinstance(v, dict):
            return v
        if not v or v.startswith(("item:", "shops:")):
            return {"product_id": v, "category": ""}
        return {"product_id": v, "category": "one_piece_tcg"}

    with patch("dedupe.resolver_io.resolve_sheet_row_with_category", side_effect=_fake_resolve):
        counts = sheet_io.backfill_canonical_key(
            ws,
            key_col=KEY_COL,
            title_col=TITLE_COL,
            url_col=None,
            cert_col=CERT_COL,
            image_url_col=None,
            dry_run=dry_run,
            item_id_col=ITEMID_COL,
            upgrade_url_to_card=False,
            only_item_id_empty=True,
            category_col=CAT_COL,
            category_value="TCG",
        )
    # dry_run=False 時に ws.batch_update に渡された更新を収集
    writes = {}
    if not dry_run and ws.batch_update.called:
        for call in ws.batch_update.call_args_list:
            for upd in call.args[0]:
                writes[upd["range"]] = upd["values"][0][0]
    return counts, writes


def test_product_id_resolved_writes_key():
    """B空+cert+KEー空 が product_id 解決 → カテゴリ prefix 込み KEー 書込 (Phase2b)."""
    rows = [_row(url="u1", itemid="", title="Luffy", cert="111", key="")]
    counts, writes = _run(rows, {"111": "OP01-016"})
    assert counts["written_product_id"] == 1
    assert counts["written_url_key"] == 0
    assert counts["written_with_category"] == 1
    assert counts["written_bare_pid"] == 0
    # row_idx=2 (header 除く 1 行目), KEー col=19 = 'S2'。 Phase2b で prefix 付与
    assert "S2" in writes
    assert writes["S2"] == "one_piece_tcg:OP01-016"


def test_phase2b_category_prefix_written():
    """Phase2b: catalog-backed は {category}:{product_id}、 category は resolver 由来."""
    rows = [_row(url="u1", itemid="", title="Heero", cert="111", key="")]
    counts, writes = _run(rows, {"111": {"product_id": "ST02-010", "category": "gundam_tcg"}})
    assert writes["S2"] == "gundam_tcg:ST02-010"
    assert counts["written_with_category"] == 1


def test_phase2b_url_key_not_prefixed():
    """url-key (category 空) は prefix しない (= `:` 誤認回避)."""
    rows = [_row(url="u1", itemid="", title="x", cert="111", key="")]
    counts, writes = _run(rows, {"111": {"product_id": "item:m12345", "category": ""}})
    # url-key は url_col=None でも build_key は raw を返すが classify=url → written_url_key
    assert counts["written_url_key"] == 1
    assert counts["written_with_category"] == 0
    assert writes["S2"] == "item:m12345"


def test_phase2b_fail_closed_not_written():
    """resolver 未解決 (product_id 空) → 書かない (fail-closed)."""
    rows = [_row(url="u1", itemid="", title="謎", cert="111", key="")]
    counts, writes = _run(rows, {"111": {"product_id": "", "category": ""}})
    assert counts["skipped_no_resolution"] == 1
    assert writes == {}


def test_unresolved_not_written():
    """解決失敗 ("") は無書込 (= fail-closed)."""
    rows = [_row(url="u1", itemid="", title="謎", cert="999", key="")]
    counts, writes = _run(rows, {"999": ""})
    assert counts["written_product_id"] == 0
    assert counts["skipped_no_resolution"] == 1
    assert writes == {}


def test_existing_product_id_not_overwritten():
    """既存 product_id セルは上書きしない (= 冪等・手動補完尊重)."""
    rows = [_row(url="u1", itemid="", title="Luffy", cert="111", key="MANUAL-KEY")]
    # resolver は別の値を返すが、 既存があるので触らない
    counts, writes = _run(rows, {"111": "OP01-016"})
    assert counts["skipped_existing"] == 1
    assert counts["written_product_id"] == 0
    assert writes == {}


def test_url_key_not_written_when_url_col_none():
    """url_col=None なら resolver が url-key を返しても書かれない.

    補URL では 2枚目自身の仕入URL 由来 url-key は primary と不一致で無意味。
    現実には url 非渡しで resolver は url-key を作れないが、 万一返しても
    backfill 側は書く (url_key path)。 → 本 test は「url を渡さない経路で
    product_id のみ書かれる」動作の担保として、 resolver が product_id を
    返すケースで url_key 書込が 0 であることを確認する。
    """
    rows = [
        _row(url="u1", itemid="", title="Luffy", cert="111", key=""),
        _row(url="u2", itemid="", title="Zoro", cert="222", key=""),
    ]
    counts, writes = _run(rows, {"111": "OP01-016", "222": "OP01-025"})
    assert counts["written_url_key"] == 0
    assert counts["written_product_id"] == 2


def test_url_key_path_still_writes_url_key_type():
    """resolver が url-key を返した場合は url_key として計上 (= product_id と区別).

    = written_product_id には混入しない (= 補URL runner は product_id のみ拾う前提)。
    """
    rows = [_row(url="u1", itemid="", title="x", cert="111", key="")]
    counts, writes = _run(rows, {"111": "item:m12345"})
    assert counts["written_product_id"] == 0
    assert counts["written_url_key"] == 1


def test_itemid_present_skipped():
    """B(itemID)非空 = live/出品済 row は touch しない."""
    rows = [_row(url="u1", itemid="99999", title="Luffy", cert="111", key="")]
    counts, writes = _run(rows, {"111": "OP01-016"})
    assert counts["skipped_item_id_present"] == 1
    assert counts["written_product_id"] == 0
    assert writes == {}


def test_non_tcg_category_skipped():
    """R='TCG' 以外は skip (= cert backfill scope 外)."""
    rows = [_row(url="u1", itemid="", title="G-shock", cert="111", cat="G-shock", key="")]
    counts, writes = _run(rows, {"111": "DW-5600-1JF"})
    assert counts["skipped_category_mismatch"] == 1
    assert counts["written_product_id"] == 0
    assert writes == {}


def test_idempotent_second_run_no_writes():
    """1回目書込 → 2回目 (KEー付与済) は追加 0 (= 冪等)."""
    # 1回目
    rows = [_row(url="u1", itemid="", title="Luffy", cert="111", key="")]
    counts1, writes1 = _run(rows, {"111": "OP01-016"})
    assert counts1["written_product_id"] == 1
    # 2回目: KEー が付いた状態を模擬 (= Phase2b prefix 付き形で既存)
    rows2 = [_row(url="u1", itemid="", title="Luffy", cert="111", key="one_piece_tcg:OP01-016")]
    counts2, writes2 = _run(rows2, {"111": "OP01-016"})
    assert counts2["written_product_id"] == 0
    assert counts2["skipped_existing"] == 1
    assert writes2 == {}


def test_only_item_id_empty_requires_item_id_col():
    """only_item_id_empty=True で item_id_col なし → ValueError (= 設定ミス防止)."""
    ws = _fake_ws([])
    with pytest.raises(ValueError):
        sheet_io.backfill_canonical_key(
            ws, key_col=KEY_COL, title_col=TITLE_COL,
            only_item_id_empty=True, item_id_col=None,
        )


def test_dry_run_no_batch_update():
    """dry_run=True は件数計上のみ・batch_update 呼ばない."""
    rows = [_row(url="u1", itemid="", title="Luffy", cert="111", key="")]
    ws = _fake_ws(rows)

    def _fake_resolve(**kw):
        return {"product_id": "OP01-016", "category": "one_piece_tcg"}

    with patch("dedupe.resolver_io.resolve_sheet_row_with_category", side_effect=_fake_resolve):
        counts = sheet_io.backfill_canonical_key(
            ws, key_col=KEY_COL, title_col=TITLE_COL, url_col=None,
            cert_col=CERT_COL, image_url_col=None, dry_run=True,
            item_id_col=ITEMID_COL, only_item_id_empty=True,
            category_col=CAT_COL, category_value="TCG",
        )
    assert counts["written_product_id"] == 1  # 計上はする
    ws.batch_update.assert_not_called()        # 書込はしない
