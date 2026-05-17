"""tests/test_sheet_writer_snkrdunk_aux - AC-AG 列投入ロジック offline tests."""
from __future__ import annotations

import pytest

from sheet_writer_snkrdunk_aux import (
    AUX_URL_COLUMNS,
    AUX_URL_LETTERS,
    COL_AUX_URL_1,
    COL_AUX_URL_2,
    COL_AUX_URL_3,
    COL_AUX_URL_4,
    COL_AUX_URL_5,
    _col_letter,
    apply_aux_url_inserts,
    find_empty_aux_columns,
    get_existing_aux_urls,
    insert_aux_urls_for_row,
    plan_aux_url_inserts,
)


pytestmark = pytest.mark.offline


# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------
class TestConstants:
    def test_aux_columns(self):
        # AC=29 / AD=30 / AE=31 / AF=32 / AG=33
        assert COL_AUX_URL_1 == 29
        assert COL_AUX_URL_2 == 30
        assert COL_AUX_URL_3 == 31
        assert COL_AUX_URL_4 == 32
        assert COL_AUX_URL_5 == 33
        assert AUX_URL_COLUMNS == (29, 30, 31, 32, 33)
        assert AUX_URL_LETTERS == ("AC", "AD", "AE", "AF", "AG")


# --------------------------------------------------------------------------
# _col_letter
# --------------------------------------------------------------------------
class TestColLetter:
    @pytest.mark.parametrize("col,expected", [
        (1, "A"), (26, "Z"),
        (27, "AA"), (28, "AB"),
        (29, "AC"), (30, "AD"), (31, "AE"), (32, "AF"), (33, "AG"),
    ])
    def test_basic_conversion(self, col, expected):
        assert _col_letter(col) == expected


# --------------------------------------------------------------------------
# find_empty_aux_columns
# --------------------------------------------------------------------------
def _row_with_aux_urls(urls_by_col: dict[int, str]) -> list[str]:
    """AC-AG 列に指定 URL を持つ row_values (33 列分) を構築."""
    row = [""] * 33
    for col, url in urls_by_col.items():
        row[col - 1] = url
    return row


class TestFindEmptyAuxColumns:
    def test_all_empty(self):
        row = [""] * 33
        assert find_empty_aux_columns(row) == [29, 30, 31, 32, 33]

    def test_some_filled(self):
        row = _row_with_aux_urls({
            COL_AUX_URL_1: "https://existing.com/1",
            COL_AUX_URL_3: "https://existing.com/3",
        })
        # AC, AE 埋、AD/AF/AG 空 → 空き列 = [30, 32, 33]
        assert find_empty_aux_columns(row) == [30, 32, 33]

    def test_all_filled(self):
        row = _row_with_aux_urls({
            COL_AUX_URL_1: "u1", COL_AUX_URL_2: "u2", COL_AUX_URL_3: "u3",
            COL_AUX_URL_4: "u4", COL_AUX_URL_5: "u5",
        })
        assert find_empty_aux_columns(row) == []

    def test_row_shorter_than_ac(self):
        # row が AC (col 29) より短い → 全て空欄扱い
        row = [""] * 10  # A〜J まで
        assert find_empty_aux_columns(row) == [29, 30, 31, 32, 33]

    def test_whitespace_treated_as_empty(self):
        row = _row_with_aux_urls({
            COL_AUX_URL_1: "  ",  # 空白のみ
            COL_AUX_URL_2: "\n",
            COL_AUX_URL_3: "https://example.com/3",
        })
        # AC (空白) / AD (空白) は空欄扱い、AE のみ埋
        assert find_empty_aux_columns(row) == [29, 30, 32, 33]


# --------------------------------------------------------------------------
# get_existing_aux_urls
# --------------------------------------------------------------------------
class TestGetExistingAuxUrls:
    def test_basic(self):
        row = _row_with_aux_urls({
            COL_AUX_URL_1: "https://a.com/1",
            COL_AUX_URL_3: "https://a.com/3",
        })
        urls = get_existing_aux_urls(row)
        assert urls == {"https://a.com/1", "https://a.com/3"}

    def test_empty_row(self):
        assert get_existing_aux_urls([""] * 33) == set()

    def test_short_row(self):
        assert get_existing_aux_urls([""] * 10) == set()


# --------------------------------------------------------------------------
# plan_aux_url_inserts
# --------------------------------------------------------------------------
class TestPlanAuxUrlInserts:
    def test_all_empty_inserts_all_candidates(self):
        row = [""] * 33
        candidates = ["https://a.com/1", "https://a.com/2", "https://a.com/3"]
        plans = plan_aux_url_inserts(row, candidates)
        assert plans == [
            (29, "https://a.com/1"),
            (30, "https://a.com/2"),
            (31, "https://a.com/3"),
        ]

    def test_overflow_drops_extras(self):
        row = [""] * 33
        candidates = [f"https://a.com/{i}" for i in range(1, 8)]  # 7 件
        plans = plan_aux_url_inserts(row, candidates)
        # 5 列分のみ採用
        assert len(plans) == 5
        assert [p[1] for p in plans] == [f"https://a.com/{i}" for i in range(1, 6)]

    def test_skips_existing_url(self):
        row = _row_with_aux_urls({
            COL_AUX_URL_1: "https://a.com/1",
            COL_AUX_URL_2: "https://a.com/2",
        })
        candidates = [
            "https://a.com/1",  # 既出
            "https://a.com/3",  # 新規
            "https://a.com/2",  # 既出
            "https://a.com/4",  # 新規
        ]
        plans = plan_aux_url_inserts(row, candidates)
        # AE / AF に新規 2 件投入
        assert plans == [
            (31, "https://a.com/3"),
            (32, "https://a.com/4"),
        ]

    def test_skips_batch_duplicates(self):
        row = [""] * 33
        candidates = [
            "https://a.com/1",
            "https://a.com/1",  # 重複
            "https://a.com/2",
        ]
        plans = plan_aux_url_inserts(row, candidates)
        assert plans == [
            (29, "https://a.com/1"),
            (30, "https://a.com/2"),
        ]

    def test_all_filled_no_insertion(self):
        row = _row_with_aux_urls({c: f"u{i+1}" for i, c in enumerate(AUX_URL_COLUMNS)})
        plans = plan_aux_url_inserts(row, ["https://new.com/1"])
        assert plans == []

    def test_left_packing(self):
        # AC 埋、AD 空、AE 埋、AF 空、AG 空 → 投入は AD, AF, AG の順
        row = _row_with_aux_urls({
            COL_AUX_URL_1: "u1",
            COL_AUX_URL_3: "u3",
        })
        candidates = ["new1", "new2", "new3"]
        plans = plan_aux_url_inserts(row, candidates)
        assert plans == [
            (30, "new1"),  # AD
            (32, "new2"),  # AF
            (33, "new3"),  # AG
        ]

    def test_empty_candidates(self):
        assert plan_aux_url_inserts([""] * 33, []) == []

    def test_whitespace_candidates_skipped(self):
        plans = plan_aux_url_inserts([""] * 33, ["", "  ", "https://a.com/1"])
        assert plans == [(29, "https://a.com/1")]


# --------------------------------------------------------------------------
# apply_aux_url_inserts + insert_aux_urls_for_row (mock ws)
# --------------------------------------------------------------------------
class _MockWorksheet:
    """batch_update のみ実装する最小モック."""

    def __init__(self):
        self.batch_update_calls: list[tuple] = []
        self.update_calls: list[tuple] = []

    def batch_update(self, data, value_input_option=None):  # noqa: ARG002
        self.batch_update_calls.append((data, value_input_option))

    def update(self, *args, **kwargs):  # noqa: ARG002
        self.update_calls.append((args, kwargs))


class TestApplyAuxUrlInserts:
    def test_basic_insertion(self):
        ws = _MockWorksheet()
        plans = [(29, "url1"), (31, "url2")]
        count = apply_aux_url_inserts(ws, row_index=245, plans=plans)
        assert count == 2
        assert len(ws.batch_update_calls) == 1
        batch_data = ws.batch_update_calls[0][0]
        # AC245 + AE245 への書込
        assert batch_data[0]["range"] == "AC245"
        assert batch_data[0]["values"] == [["url1"]]
        assert batch_data[1]["range"] == "AE245"
        assert batch_data[1]["values"] == [["url2"]]

    def test_empty_plans_no_call(self):
        ws = _MockWorksheet()
        count = apply_aux_url_inserts(ws, row_index=10, plans=[])
        assert count == 0
        assert ws.batch_update_calls == []


class TestInsertAuxUrlsForRow:
    def test_full_flow_empty_row(self):
        ws = _MockWorksheet()
        row_values = [""] * 33
        candidates = ["new1", "new2"]
        result = insert_aux_urls_for_row(ws, row_index=100, row_values=row_values, candidate_urls=candidates)
        assert result["inserted"] == 2
        assert result["skipped_existing"] == 0
        assert result["skipped_overflow"] == 0
        assert result["plans"] == [("AC", "new1"), ("AD", "new2")]

    def test_full_flow_with_existing(self):
        ws = _MockWorksheet()
        row_values = _row_with_aux_urls({
            COL_AUX_URL_1: "existing",
        })
        candidates = ["existing", "new1"]  # 1 件既出、1 件新規
        result = insert_aux_urls_for_row(ws, row_index=100, row_values=row_values, candidate_urls=candidates)
        assert result["inserted"] == 1
        assert result["skipped_existing"] == 1
        assert result["plans"] == [("AD", "new1")]

    def test_overflow_when_5_filled(self):
        ws = _MockWorksheet()
        row_values = _row_with_aux_urls({c: f"u{i+1}" for i, c in enumerate(AUX_URL_COLUMNS)})
        result = insert_aux_urls_for_row(ws, row_index=100, row_values=row_values, candidate_urls=["new1", "new2"])
        assert result["inserted"] == 0
        assert result["skipped_overflow"] == 2
        assert ws.batch_update_calls == []

    def test_does_not_call_update(self):
        # 既存行を直接 update しない (= batch_update 経由のみ)
        ws = _MockWorksheet()
        insert_aux_urls_for_row(ws, row_index=100, row_values=[""] * 33, candidate_urls=["url1"])
        assert ws.update_calls == []
