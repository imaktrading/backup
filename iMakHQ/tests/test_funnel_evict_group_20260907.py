"""在庫あり行に「落とすグループ」を出す (2026-09-07 ユーザー要望).

判定は棚 (`shelf_evict`) の関数をそのまま呼ぶこと。ここで作り直すと、
ボタンが落とす順と表の見え方が食い違う (= 第二 SSOT)。
"""
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import listing_funnel as lf  # noqa: E402
import shelf_evict as se  # noqa: E402


def _row(title, age, sold=0, qty=1):
    return {"item_id": "1", "title": title, "qty": qty, "age_days": age,
            "sold_qty": sold, "sales90": 0, "watch": 0}


def test_column_exists_and_url_stays_last():
    assert "落とすグループ" in lf.FUNNEL_COLS
    assert lf.FUNNEL_COLS[-1] == "ebay_url"   # 在庫なしタブは末尾に「状態」を足す


def test_groups_follow_shelf_evict_order():
    assert lf.evict_group(_row("PSA 10 Gundam CCG", 60)).startswith("落とす1")
    assert lf.evict_group(_row("PSA 10 Dragon Ball", 60)).startswith("落とす1")
    assert lf.evict_group(_row("PSA 10 One Piece", 60)).startswith("落とす2")
    assert lf.evict_group(_row("CASIO G-Shock GA-2100", 60)).startswith("落とす3")
    assert lf.evict_group(_row("PSA 10 Pokemon SV5a", 60)).startswith("落とす4")


def test_not_candidates():
    assert lf.evict_group(_row("PSA 10 Pokemon SV5a", 60, sold=1)) == lf._EVICT_KEEP_SOLD
    assert lf.evict_group(_row("PSA 10 Pokemon SV5a", 10)) == lf._EVICT_WAIT
    assert lf.evict_group(_row("UNIQLO UT Tee", 999)) == lf._EVICT_OUT
    assert lf.evict_group(_row("PSA 10 Pokemon SV5a", 60, qty=0)) == ""


def test_age_limit_comes_from_shelf_evict():
    """棚の日数を変えたら表も一緒に動くこと (二重定義していない証拠)."""
    limit = se.STALE_MAX_AGE["TCG"]
    assert lf.evict_group(_row("PSA 10 Pokemon", limit)) == lf._EVICT_WAIT
    assert lf.evict_group(_row("PSA 10 Pokemon", limit + 1)).startswith("落とす")


def test_vals_line_up_with_cols():
    vals = lf._funnel_vals({"item_id": "1", "title": "PSA 10 Gundam", "site": "US",
                            "price": 1.0, "trend_price": 0, "qty": 1, "sold_qty": 0,
                            "watch": 0, "impr": 0.0, "ctr": 0.0, "age_days": 60})
    assert len(vals) == len(lf.FUNNEL_COLS)
    assert dict(zip(lf.FUNNEL_COLS, vals))["落とすグループ"].startswith("落とす1")
