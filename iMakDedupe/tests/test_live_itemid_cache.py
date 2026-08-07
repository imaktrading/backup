"""HQ live_listings_cache 読込 の単体 test (= 2026-08-07 制定).

依頼書 `..._live_definition_must_be_ebay_not_sold_column_response.md` 実装。

対象:
- `sheet_io.load_live_itemid_set()` — cache 無し/古い/壊れ で LiveCacheError
- `sheet_io.read_canonical_keys_by_live_itemids()` — 新 live filter (D 列不使用)

eBay を叩かない (= cache mock で完結)。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dedupe import sheet_io
from dedupe.sheet_io import LiveCacheError

pytestmark = pytest.mark.offline


# ---------------------------------------------------------------------------
# load_live_itemid_set
# ---------------------------------------------------------------------------


def _write_cache(tmp_path: Path, data) -> Path:
    p = tmp_path / "live_listings_cache.json"
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f)
    return p


class TestLoadLiveItemidSetErrors:
    def test_file_not_found_raises(self, tmp_path):
        missing = tmp_path / "nope.json"
        with pytest.raises(LiveCacheError, match="not found"):
            sheet_io.load_live_itemid_set(cache_path=str(missing))

    def test_invalid_json_raises(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(LiveCacheError, match="読込 error|JSON"):
            sheet_io.load_live_itemid_set(cache_path=str(p))

    def test_empty_dict_raises(self, tmp_path):
        p = _write_cache(tmp_path, {})
        with pytest.raises(LiveCacheError, match="空|非 dict"):
            sheet_io.load_live_itemid_set(cache_path=str(p))

    def test_missing_generated_at_raises(self, tmp_path):
        p = _write_cache(tmp_path, {"titles": {"1": "t"}})
        with pytest.raises(LiveCacheError, match="generated_at"):
            sheet_io.load_live_itemid_set(cache_path=str(p))

    def test_unparseable_generated_at_raises(self, tmp_path):
        p = _write_cache(tmp_path, {
            "generated_at": "not-a-date",
            "titles": {"1": "t"},
        })
        with pytest.raises(LiveCacheError, match="parse 不能"):
            sheet_io.load_live_itemid_set(cache_path=str(p))

    def test_stale_cache_raises_over_6h(self, tmp_path):
        now = datetime(2026, 8, 7, 12, 0, 0)
        old = now - timedelta(hours=6, minutes=1)  # 6h 超え
        p = _write_cache(tmp_path, {
            "generated_at": old.isoformat(),
            "titles": {"358410000000": "sample"},
        })
        with pytest.raises(LiveCacheError, match="古い"):
            sheet_io.load_live_itemid_set(cache_path=str(p), now=now)

    def test_stale_boundary_within_6h_ok(self, tmp_path):
        """6h 丁度 (= 境界) は OK (通す)."""
        now = datetime(2026, 8, 7, 12, 0, 0)
        old = now - timedelta(hours=6)
        p = _write_cache(tmp_path, {
            "generated_at": old.isoformat(),
            "titles": {"358410000000": "sample"},
        })
        out = sheet_io.load_live_itemid_set(cache_path=str(p), now=now)
        assert "358410000000" in out

    def test_empty_titles_raises(self, tmp_path):
        p = _write_cache(tmp_path, {
            "generated_at": datetime.now().isoformat(),
            "titles": {},
        })
        with pytest.raises(LiveCacheError, match="titles 空"):
            sheet_io.load_live_itemid_set(cache_path=str(p))

    def test_titles_not_dict_raises(self, tmp_path):
        p = _write_cache(tmp_path, {
            "generated_at": datetime.now().isoformat(),
            "titles": ["not", "a", "dict"],
        })
        with pytest.raises(LiveCacheError, match="titles"):
            sheet_io.load_live_itemid_set(cache_path=str(p))


class TestLoadLiveItemidSetSuccess:
    def test_returns_union_of_titles_and_skus(self, tmp_path):
        now = datetime(2026, 8, 7, 12, 0, 0)
        p = _write_cache(tmp_path, {
            "generated_at": now.isoformat(),
            "titles": {"358001": "titleA", "358002": "titleB"},
            "skus": {"358001": "SKU1", "358003": "SKU3"},
        })
        out = sheet_io.load_live_itemid_set(cache_path=str(p), now=now)
        assert isinstance(out, frozenset)
        assert out == frozenset({"358001", "358002", "358003"})

    def test_titles_only_no_skus_ok(self, tmp_path):
        now = datetime(2026, 8, 7, 12, 0, 0)
        p = _write_cache(tmp_path, {
            "generated_at": now.isoformat(),
            "titles": {"358001": "titleA"},
        })
        out = sheet_io.load_live_itemid_set(cache_path=str(p), now=now)
        assert out == frozenset({"358001"})

    def test_keys_normalized_to_str(self, tmp_path):
        """schema 上は string key だが int が入っていても str 化される."""
        now = datetime(2026, 8, 7, 12, 0, 0)
        p = _write_cache(tmp_path, {
            "generated_at": now.isoformat(),
            "titles": {"358001": "titleA"},
            "skus": {"358001": "SKU"},
        })
        out = sheet_io.load_live_itemid_set(cache_path=str(p), now=now)
        assert all(isinstance(x, str) for x in out)

    def test_custom_max_age_hours(self, tmp_path):
        """呼出側で閾値を上書き可能 (= 12h 許容).
        6h では stale 判定になるが、 12h なら通す。
        """
        now = datetime(2026, 8, 7, 12, 0, 0)
        old = now - timedelta(hours=10)
        p = _write_cache(tmp_path, {
            "generated_at": old.isoformat(),
            "titles": {"358001": "titleA"},
        })
        # 6h では stale
        with pytest.raises(LiveCacheError, match="古い"):
            sheet_io.load_live_itemid_set(cache_path=str(p), max_age_hours=6.0, now=now)
        # 12h では OK
        out = sheet_io.load_live_itemid_set(cache_path=str(p), max_age_hours=12.0, now=now)
        assert "358001" in out


# ---------------------------------------------------------------------------
# read_canonical_keys_by_live_itemids
# ---------------------------------------------------------------------------


def _ws(values):
    ws = MagicMock()
    ws.get_all_values.return_value = values
    return ws


HEADER = ["URL", "itemID", "title", "売り切れ", "KEY"]


def _row(url="", item_id="", title="", sold="", key=""):
    return [url, item_id, title, sold, key]


class TestReadCanonicalKeysByLiveItemids:
    def test_include_key_when_itemid_is_live(self):
        """itemID が live set にあれば KEY を返す (D 列は無視)."""
        ws = _ws([
            HEADER,
            _row(item_id="358001", sold="", key="op:OP01-001"),
            _row(item_id="358002", sold="", key="op:OP01-002"),
        ])
        live = frozenset({"358001", "358002"})
        out = sheet_io.read_canonical_keys_by_live_itemids(
            ws, key_col=5, item_id_col=2, live_itemid_set=live
        )
        assert out == ["op:OP01-001", "op:OP01-002"]

    def test_exclude_when_itemid_not_in_live(self):
        """itemID が live set に無い row は skip (eBay で既に終了)."""
        ws = _ws([
            HEADER,
            _row(item_id="358001", sold="", key="op:OP01-001"),  # live
            _row(item_id="358999", sold="", key="op:OP01-999"),  # ★ live set 外
            _row(item_id="358002", sold="", key="op:OP01-002"),  # live
        ])
        live = frozenset({"358001", "358002"})
        out = sheet_io.read_canonical_keys_by_live_itemids(
            ws, key_col=5, item_id_col=2, live_itemid_set=live
        )
        assert out == ["op:OP01-001", "op:OP01-002"]

    def test_include_key_even_when_sold_d_col_marked(self):
        """★本件の核: D 列 = '○' (仕入元売切) でも itemID が live set に居れば KEY を含める.

        旧 D 列 filter だと 660+ 行が誤脱落 → 重複素通し。
        新 filter は itemID の live set 突合だけ = D 列を無視。
        """
        ws = _ws([
            HEADER,
            _row(item_id="358001", sold="○", key="op:OP05-098_P"),  # ★ D='○' でも live
        ])
        live = frozenset({"358001"})
        out = sheet_io.read_canonical_keys_by_live_itemids(
            ws, key_col=5, item_id_col=2, live_itemid_set=live
        )
        assert out == ["op:OP05-098_P"]

    def test_exclude_when_itemid_empty(self):
        """itemID 空 (= 未出品/orphan) は skip."""
        ws = _ws([
            HEADER,
            _row(item_id="", sold="", key="op:OP01-005"),  # 未出品
            _row(item_id="358001", sold="", key="op:OP01-001"),
        ])
        live = frozenset({"358001"})
        out = sheet_io.read_canonical_keys_by_live_itemids(
            ws, key_col=5, item_id_col=2, live_itemid_set=live
        )
        assert out == ["op:OP01-001"]

    def test_empty_ws_returns_empty_list(self):
        ws = _ws([])
        out = sheet_io.read_canonical_keys_by_live_itemids(
            ws, key_col=5, item_id_col=2, live_itemid_set=frozenset()
        )
        assert out == []

    def test_header_only_returns_empty_list(self):
        ws = _ws([HEADER])
        out = sheet_io.read_canonical_keys_by_live_itemids(
            ws, key_col=5, item_id_col=2, live_itemid_set=frozenset({"358001"})
        )
        assert out == []

    def test_empty_key_cell_included_as_empty_string(self):
        """KEY 空 row でも item_id が live なら "" が入る (呼出側で filter する既存挙動と揃える)."""
        ws = _ws([
            HEADER,
            _row(item_id="358001", key=""),
        ])
        live = frozenset({"358001"})
        out = sheet_io.read_canonical_keys_by_live_itemids(
            ws, key_col=5, item_id_col=2, live_itemid_set=live
        )
        assert out == [""]


# ---------------------------------------------------------------------------
# regression: 依頼書 §3 「症状」の 2 件 (OP07-109 / OP05-098_P) が
# 新 filter で真の重複として拾える
# ---------------------------------------------------------------------------


class TestRegression20260803to20260804SymptomCases:
    def test_op07_109_case(self):
        """8/03: cert 157208448 `one_piece_tcg:OP07-109`.
        既存 live itemID `358510552338` KEY 同一 → 除外されるべき。
        旧 D='○' filter だと既存 set から脱落 → 素通り。
        新 filter は itemID が live set にあれば KEY を含める → 除外される。
        """
        ws = _ws([
            HEADER,
            _row(item_id="358510552338", sold="○", key="one_piece_tcg:OP07-109"),
        ])
        live = frozenset({"358510552338"})  # cache 側で live 保証
        out = sheet_io.read_canonical_keys_by_live_itemids(
            ws, key_col=5, item_id_col=2, live_itemid_set=live
        )
        assert "one_piece_tcg:OP07-109" in out

    def test_op05_098_p_case(self):
        """8/04: cert 152976724 `one_piece_tcg:OP05-098_P`.
        既存 live itemID `358833464170` KEY 同一 (D='○'). 新 filter で拾えるか.
        """
        ws = _ws([
            HEADER,
            _row(item_id="358833464170", sold="○", key="one_piece_tcg:OP05-098_P"),
        ])
        live = frozenset({"358833464170"})
        out = sheet_io.read_canonical_keys_by_live_itemids(
            ws, key_col=5, item_id_col=2, live_itemid_set=live
        )
        assert "one_piece_tcg:OP05-098_P" in out
