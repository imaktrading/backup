"""snkrdunk_op_catalog / run_harvest_snkrdunk_op のテスト (= ネットワークなし)."""
import pytest

from scrapers import snkrdunk_op_catalog as OP


# --- One Piece productNumber 判定 ---

@pytest.mark.parametrize("pn,expected", [
    ("OP02-059", True), ("OP12-001", True), ("ST01-001", True),
    ("EB01-029", True), ("PRB01-001", True), ("P-018", True),
    ("op02-059", True),                       # 小文字も可
    ("pkmn-tcg-SM-P-288", False),             # Pokemon は除外
    ("pkmn-tcg-1811", False),
    ("", False), (None, False),
    ("OP2-59", False),                        # 桁数不一致は除外 (fail-closed)
])
def test_is_one_piece_pn(pn, expected):
    assert OP.is_one_piece_pn(pn) is expected


# --- extract_psa10_under: PSA10 + 出品中 + price<cap のみ、 price 昇順 ---

class _FakeResp:
    def __init__(self, items):
        self.status_code = 200
        self._items = items
    def json(self):
        return {"apparelUsedItems": self._items}


class _FakeSession:
    """1 頁目だけ items を返し、 2 頁目以降は空 (= pagination 終了)."""
    def __init__(self, items):
        self._items = items
        self.calls = 0
    def get(self, url, params=None, timeout=None):
        self.calls += 1
        if params and params.get("page", 1) == 1:
            return _FakeResp(self._items)
        return _FakeResp([])


def test_extract_psa10_under_filters_and_sorts():
    items = [
        {"id": 1, "price": 60000, "status": 0, "displayShortConditionTitle": "PSA10"},
        {"id": 2, "price": 38500, "status": 0, "displayShortConditionTitle": "PSA10"},
        {"id": 3, "price": 150000, "status": 0, "displayShortConditionTitle": "PSA10"},  # cap超
        {"id": 4, "price": 20000, "status": 1, "displayShortConditionTitle": "PSA10"},   # 売切
        {"id": 5, "price": 25000, "status": 0, "displayShortConditionTitle": "PSA9"},    # PSA9
        {"id": 6, "price": 45999, "status": 0, "displayShortConditionTitle": "PSA10"},
    ]
    res = OP.extract_psa10_under(_FakeSession(items), model_id=102461, price_cap=100000)
    assert [r["instance_id"] for r in res] == [2, 6, 1]      # 38500 < 45999 < 60000
    assert all(r["price"] < 100000 for r in res)
    assert res[0]["url"].endswith("/apparels/102461/used/2")


def test_extract_psa10_under_empty_when_none_match():
    items = [{"id": 9, "price": 5000, "status": 0, "displayShortConditionTitle": "PSA9"}]
    assert OP.extract_psa10_under(_FakeSession(items), 1, 100000) == []


# --- _build_row (entrypoint) ---

def test_build_row():
    import run_harvest_snkrdunk_op as R
    card = {
        "model_id": 102461, "card_id": "OP02-059", "name": "Boa Hancock UC-P",
        "psa10": [
            {"instance_id": 2, "price": 38500, "url": "https://snkrdunk.com/apparels/102461/used/2"},
            {"instance_id": 6, "price": 45999, "url": "https://snkrdunk.com/apparels/102461/used/6"},
        ],
    }
    row = R._build_row(card, is_supplement=True)
    assert row[R.C_URL - 1] == "https://snkrdunk.com/apparels/102461/used/2"  # 最安
    assert row[R.C_TITLE - 1] == "Boa Hancock UC-P"
    assert row[R.C_PRICE - 1] == 38500
    assert row[R.C_FLG - 1] == "補"
    assert row[R.C_KEY - 1] == "OP02-059"
    assert row[R.C_AUX - 1] == "https://snkrdunk.com/apparels/102461/used/2"      # aux1
    assert row[R.C_AUX] == "https://snkrdunk.com/apparels/102461/used/6"          # aux2
    assert len(row) == R.NCOLS


def test_build_row_new_candidate_no_flag():
    card = {"model_id": 1, "card_id": "OP12-001", "name": "x",
            "psa10": [{"instance_id": 1, "price": 9999, "url": "u"}]}
    import run_harvest_snkrdunk_op as R
    row = R._build_row(card, is_supplement=False)
    assert row[R.C_FLG - 1] == ""
