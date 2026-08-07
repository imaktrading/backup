"""run_check_csv_canonical の ActiveList 切替 + ledger 書出 test (= 2026-08-07).

依頼書: `..._live_definition_must_be_ebay_not_sold_column_response.md`
- Q3: cache 無し/古い/壊れ → 非ゼロ exit で入稿停止 (CSV 触らない)
- お願い #2: 除外した行は台帳 (`<csv>.removed.json`) に残す
- お願い #3: cache mock、 eBay 叩かない

eBay も Google Sheets も叩かない (= 全 mock)。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dedupe import checker, sheet_io
from dedupe.sheet_io import LiveCacheError

pytestmark = pytest.mark.offline


def _write_csv(path: Path, rows: list) -> None:
    fieldnames = list(rows[0].keys()) if rows else ["*Title"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_NONNUMERIC)
        w.writeheader()
        w.writerows(rows)


class TestFailClosedWhenCacheMissing:
    def test_missing_cache_returns_nonzero_and_does_not_touch_csv(self, tmp_path):
        """cache が LiveCacheError で落ちた場合、 非ゼロ exit + CSV 未書換."""
        path = tmp_path / "in.csv"
        original = [{"*Title": "row1", "C:Card Number": "001"}]
        _write_csv(path, original)
        original_bytes = path.read_bytes()

        with patch(
            "dedupe.sheet_io.load_live_itemid_set",
            side_effect=LiveCacheError("mock: cache missing"),
        ):
            rc = checker.run_check_csv_canonical(csv_path=str(path), dry_run=False)

        # 非ゼロ exit (= 入稿停止 signal)
        assert rc != 0
        # CSV 未書換 (= fail-closed の実効)
        assert path.read_bytes() == original_bytes
        # ledger file も作らない
        assert not (tmp_path / "in.csv.removed.json").exists()
        # .bak も作らない
        assert not (tmp_path / "in.csv.bak").exists()

    def test_stale_cache_returns_nonzero(self, tmp_path):
        """stale cache 由来 LiveCacheError も同じく非ゼロ exit."""
        path = tmp_path / "in.csv"
        _write_csv(path, [{"*Title": "row1", "C:Card Number": "001"}])

        with patch(
            "dedupe.sheet_io.load_live_itemid_set",
            side_effect=LiveCacheError("mock: cache > 6h old"),
        ):
            rc = checker.run_check_csv_canonical(csv_path=str(path), dry_run=True)
        assert rc != 0


class TestLedgerWrittenOnRemoval:
    def test_removed_rows_ledger_json_written_next_to_csv(self, tmp_path):
        """removed>0 なら `<csv>.removed.json` に台帳を書出."""
        path = tmp_path / "in.csv"
        _write_csv(path, [
            {"*Title": "dup row", "C:Card Number": "OP07-109"},
            {"*Title": "new row", "C:Card Number": "OP99-001"},
        ])

        # HIGH ws: KEY 列にひとつ既存 KEY
        ws_high = MagicMock()
        ws_high.get_all_values.return_value = [
            ["URL", "itemID", "title", "sold", "KEY"],
            ["u", "358510552338", "existing", "○", "one_piece_tcg:OP07-109"],
        ]
        # LOW ws: 空
        ws_low = MagicMock()
        ws_low.get_all_values.return_value = [
            ["URL", "itemID", "title", "sold", "KEY"],
        ]

        def _open(sid, client=None):
            m = MagicMock()
            if sid == sheet_io.HIGH_SHEET_ID:
                m.worksheet.return_value = ws_high
            else:
                m.worksheet.return_value = ws_low
            return m

        live_set = frozenset({"358510552338"})

        # csv 内の 1 行目 KEY を one_piece_tcg:OP07-109 に解決 (= 除外対象)
        # 2 行目 は解決不能 (= keep)
        def _resolve(row, purpose="dedup"):
            t = row.get("*Title", "")
            if "dup" in t:
                return {"product_id": "OP07-109", "category": "one_piece_tcg"}
            return {"product_id": "", "category": ""}

        with patch("dedupe.sheet_io.load_live_itemid_set", return_value=live_set), \
             patch("dedupe.sheet_io.authorize_client", return_value=MagicMock()), \
             patch("dedupe.sheet_io.open_spreadsheet", side_effect=_open), \
             patch("dedupe.sheet_io.find_canonical_key_column", return_value=5), \
             patch("dedupe.resolver_io.resolve_csv_row_with_category", side_effect=_resolve):
            rc = checker.run_check_csv_canonical(csv_path=str(path), dry_run=False)

        assert rc == 0
        ledger_path = tmp_path / "in.csv.removed.json"
        assert ledger_path.exists(), "removed>0 なら台帳 JSON が書かれること"
        data = json.loads(ledger_path.read_text(encoding="utf-8"))
        assert data["removed"] == 1
        assert data["total"] == 2
        assert data["kept"] == 1
        assert "one_piece_tcg:OP07-109" in data["removed_canonical_keys"]
        assert data["existing_set_source"].startswith("HQ live_listings_cache")
        assert data["live_itemid_count"] == 1

    def test_no_ledger_when_zero_removed(self, tmp_path):
        """removed==0 なら台帳 file 不要 (= noise 減らす)."""
        path = tmp_path / "in.csv"
        _write_csv(path, [{"*Title": "new row", "C:Card Number": "OP99-001"}])

        ws_empty = MagicMock()
        ws_empty.get_all_values.return_value = [
            ["URL", "itemID", "title", "sold", "KEY"],
        ]

        def _open(sid, client=None):
            m = MagicMock()
            m.worksheet.return_value = ws_empty
            return m

        with patch(
            "dedupe.sheet_io.load_live_itemid_set",
            return_value=frozenset({"999999"}),
        ), patch(
            "dedupe.sheet_io.authorize_client", return_value=MagicMock()
        ), patch(
            "dedupe.sheet_io.open_spreadsheet", side_effect=_open
        ), patch(
            "dedupe.sheet_io.find_canonical_key_column", return_value=5
        ), patch(
            "dedupe.resolver_io.resolve_csv_row_with_category",
            return_value={"product_id": "OP99-001", "category": "one_piece_tcg"},
        ):
            rc = checker.run_check_csv_canonical(csv_path=str(path), dry_run=False)

        assert rc == 0
        assert not (tmp_path / "in.csv.removed.json").exists()

    def test_no_ledger_in_dry_run(self, tmp_path):
        """dry_run=True 時は台帳も CSV も書き換えない."""
        path = tmp_path / "in.csv"
        _write_csv(path, [{"*Title": "dup row", "C:Card Number": "OP07-109"}])
        original = path.read_bytes()

        ws_high = MagicMock()
        ws_high.get_all_values.return_value = [
            ["URL", "itemID", "title", "sold", "KEY"],
            ["u", "358510552338", "t", "○", "one_piece_tcg:OP07-109"],
        ]
        ws_low = MagicMock()
        ws_low.get_all_values.return_value = [
            ["URL", "itemID", "title", "sold", "KEY"],
        ]

        def _open(sid, client=None):
            m = MagicMock()
            m.worksheet.return_value = ws_high if sid == sheet_io.HIGH_SHEET_ID else ws_low
            return m

        with patch(
            "dedupe.sheet_io.load_live_itemid_set",
            return_value=frozenset({"358510552338"}),
        ), patch(
            "dedupe.sheet_io.authorize_client", return_value=MagicMock()
        ), patch(
            "dedupe.sheet_io.open_spreadsheet", side_effect=_open
        ), patch(
            "dedupe.sheet_io.find_canonical_key_column", return_value=5
        ), patch(
            "dedupe.resolver_io.resolve_csv_row_with_category",
            return_value={"product_id": "OP07-109", "category": "one_piece_tcg"},
        ):
            rc = checker.run_check_csv_canonical(csv_path=str(path), dry_run=True)

        assert rc == 0
        # CSV 未書換
        assert path.read_bytes() == original
        # 台帳も書かない
        assert not (tmp_path / "in.csv.removed.json").exists()


class TestKeyExactOnlyNoTokenMatch:
    """お願い #1: t: (タイトル token) 一致で落とさないこと。 KEY 完全一致のみ物理除外.

    csv_check.check_csv_canonical の設計 (= 既存) を run_check_csv_canonical 経由でも
    保持していることの回帰確認。 別カード (OP05-119 vs OP05-119_PRB01_1) は除外されない。
    """

    def test_only_exact_key_match_removes(self, tmp_path):
        path = tmp_path / "in.csv"
        _write_csv(path, [
            {"*Title": "PRB reprint", "C:Card Number": "OP05-119"},  # → OP05-119_PRB01_1
            {"*Title": "english p8", "C:Card Number": "OP05-119"},  # → OP05-119_p8
            {"*Title": "same as existing", "C:Card Number": "OP05-119"},  # → OP05-119
        ])

        ws_high = MagicMock()
        ws_high.get_all_values.return_value = [
            ["URL", "itemID", "title", "sold", "KEY"],
            ["u", "358500001", "existing awakening", "", "one_piece_tcg:OP05-119"],
        ]
        ws_low = MagicMock()
        ws_low.get_all_values.return_value = [
            ["URL", "itemID", "title", "sold", "KEY"],
        ]

        def _open(sid, client=None):
            m = MagicMock()
            m.worksheet.return_value = ws_high if sid == sheet_io.HIGH_SHEET_ID else ws_low
            return m

        # resolver: 3 行それぞれ異なる canonical KEY
        it = iter([
            {"product_id": "OP05-119_PRB01_1", "category": "one_piece_tcg"},
            {"product_id": "OP05-119_p8", "category": "one_piece_tcg"},
            {"product_id": "OP05-119", "category": "one_piece_tcg"},
        ])

        def _resolve(row, purpose="dedup"):
            return next(it)

        with patch(
            "dedupe.sheet_io.load_live_itemid_set",
            return_value=frozenset({"358500001"}),
        ), patch(
            "dedupe.sheet_io.authorize_client", return_value=MagicMock()
        ), patch(
            "dedupe.sheet_io.open_spreadsheet", side_effect=_open
        ), patch(
            "dedupe.sheet_io.find_canonical_key_column", return_value=5
        ), patch(
            "dedupe.resolver_io.resolve_csv_row_with_category", side_effect=_resolve
        ):
            rc = checker.run_check_csv_canonical(csv_path=str(path), dry_run=False)

        assert rc == 0
        ledger_path = tmp_path / "in.csv.removed.json"
        assert ledger_path.exists()
        data = json.loads(ledger_path.read_text(encoding="utf-8"))
        # 3 行中、 完全一致 (OP05-119) 1 件のみ除外。
        # _PRB01_1 / _p8 は別カードなので落ちてはいけない (お願い #1)。
        assert data["removed"] == 1
        assert data["kept"] == 2
        assert data["removed_canonical_keys"] == ["one_piece_tcg:OP05-119"]


class TestSoldColIgnored:
    """D 列 (= sold) は live 判定に使わなくなった (= 2026-08-07 是正).

    D='○' でも itemID が live cache にあれば existing set に含まれ、
    重複が正しく除外される。 これが本件依頼の核。
    """

    def test_sold_marked_existing_still_blocks_duplicate(self, tmp_path):
        """既存 row D='○' でも live cache にあれば新規 candidate を除外."""
        path = tmp_path / "in.csv"
        _write_csv(path, [
            {"*Title": "dup candidate", "C:Card Number": "OP05-098_P"},
        ])

        ws_high = MagicMock()
        ws_high.get_all_values.return_value = [
            ["URL", "itemID", "title", "sold", "KEY"],
            # 既存 row: D='○' (= 仕入元売切) だが itemID は live cache に居る
            ["u", "358833464170", "existing", "○", "one_piece_tcg:OP05-098_P"],
        ]
        ws_low = MagicMock()
        ws_low.get_all_values.return_value = [
            ["URL", "itemID", "title", "sold", "KEY"],
        ]

        def _open(sid, client=None):
            m = MagicMock()
            m.worksheet.return_value = ws_high if sid == sheet_io.HIGH_SHEET_ID else ws_low
            return m

        with patch(
            "dedupe.sheet_io.load_live_itemid_set",
            return_value=frozenset({"358833464170"}),
        ), patch(
            "dedupe.sheet_io.authorize_client", return_value=MagicMock()
        ), patch(
            "dedupe.sheet_io.open_spreadsheet", side_effect=_open
        ), patch(
            "dedupe.sheet_io.find_canonical_key_column", return_value=5
        ), patch(
            "dedupe.resolver_io.resolve_csv_row_with_category",
            return_value={"product_id": "OP05-098_P", "category": "one_piece_tcg"},
        ):
            rc = checker.run_check_csv_canonical(csv_path=str(path), dry_run=False)

        assert rc == 0
        ledger_path = tmp_path / "in.csv.removed.json"
        assert ledger_path.exists()
        data = json.loads(ledger_path.read_text(encoding="utf-8"))
        assert data["removed"] == 1  # ★ 本件 8/04 の症状が新 filter で拾える
        assert data["removed_canonical_keys"] == ["one_piece_tcg:OP05-098_P"]
