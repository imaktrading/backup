"""同一 item_id 複数行 (仕入元違い) の乖離判定 regression test.

★ 2026-08-13 制定。実害: 同じ eBay listing を 2 行 (別々の仕入元 URL) で管理している商品で、
片方の仕入元が売切 (D=○) になると、もう片方に在庫があっても「売切なのに eBay で買える
= 要対応」として毎日 MISMATCH を報告していた。3 件が 08-09〜08-13 の 5 日連続で鳴り続け、
対処のしようがない (実際は正常) ため alert 自体が無視される状態になっていた。

仕様:
- 同一 item_id に **URL を持ち D が売切でない行** があれば、その item_id の売切行は乖離に数えない
  (別の仕入元から仕入できる = eBay active は正しい)。
- ただし silent drop はしない: suppressed として結果と log に残す。
- URL 空 + D 空欄 の行は「未設定」であって在庫ではない → 抑止根拠にしない (fail-OPEN 防止)。
- 全行が売切なら従来どおり乖離 (= 取下げ漏れ) として報告する。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _row(idx, iid, url, sold):
    return {"row_index": idx, "item_id": iid, "url": url, "current_sold": sold, "title": "t"}


def _run(rows, qty_map):
    import reverse_audit as ra

    class _WS:
        pass

    with patch.object(ra, "open_sheet_by_id", lambda *a, **k: object()), \
         patch.object(ra, "get_listings_worksheet", lambda *a, **k: _WS()), \
         patch.object(ra, "read_listings_rows", lambda ws, **k: rows.pop(0) if rows else []):
        return ra.run_reverse_audit(qty_map=qty_map, write_log=False)


@pytest.mark.offline
def test_other_row_in_stock_is_not_mismatch():
    """別行の仕入元に在庫あり → 乖離に数えず suppressed に記録."""
    high = [_row(1405, "358870181858", "https://jp.mercari.com/shops/product/SOLD", "○"),
            _row(1309, "358870181858", "https://jp.mercari.com/shops/product/ALIVE", "")]
    res = _run([high, []], {"358870181858": 1})
    assert res["mismatch_count"] == 0
    assert len(res["suppressed"]) == 1
    assert res["suppressed"][0]["suppressed_reason"] == "other_row_in_stock"


@pytest.mark.offline
def test_all_rows_sold_is_still_mismatch():
    """全行売切なのに eBay qty>0 → 従来どおり乖離 (取下げ漏れ = fail-OPEN)."""
    high = [_row(1405, "IID", "https://jp.mercari.com/item/a", "○"),
            _row(1309, "IID", "https://jp.mercari.com/item/b", "○")]
    res = _run([high, []], {"IID": 1})
    assert res["mismatch_count"] == 2
    assert res["suppressed"] == []


@pytest.mark.offline
def test_url_less_blank_row_does_not_suppress():
    """URL 空 + D 空欄 は「未設定」= 在庫ではない → 抑止根拠にしない (fail-OPEN 防止)."""
    high = [_row(616, "IID", "https://jp.mercari.com/item/a", "○"),
            _row(900, "IID", "", "")]
    res = _run([high, []], {"IID": 1})
    assert res["mismatch_count"] == 1
    assert res["suppressed"] == []


@pytest.mark.offline
def test_single_row_sold_still_mismatch():
    high = [_row(10, "IID", "https://jp.mercari.com/item/a", "○")]
    res = _run([high, []], {"IID": 2})
    assert res["mismatch_count"] == 1
