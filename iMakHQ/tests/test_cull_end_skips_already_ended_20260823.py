"""CULL の段階 End が「既に終了済み」を除外する (2026-08-23).

実害: funnel CSV は静的なので、qty だけ見ると終了済みも「qty=0」で通ってしまい、
毎回 同じ上位N件が選ばれて **2回目以降ずっと進まない**。
1回目に End した33件が、2回目の CSV にそのまま載っていた。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import cull_end as C  # noqa: E402


def _rows(*ids):
    return [{"item_id": i, "title": "t", "price": "100", "age_days": "99"} for i in ids]


def _qty0(_i):
    return 0


def test_already_ended_is_excluded():
    """★本命: 終了済みは End 対象にしない."""
    picked = _rows("A", "B")
    kept, revived, ended, failed = C.verify_oos(
        picked, _qty0, status_fn=lambda i: "Completed" if i == "A" else "Active")
    assert [r["item_id"] for r in ended] == ["A"]
    assert [r["item_id"] for r in kept] == ["B"]


def test_restocked_is_still_excluded():
    """在庫が戻ったものを取り下げない (2026-06-28 の守りを壊さない)."""
    kept, revived, ended, failed = C.verify_oos(
        _rows("A"), lambda _i: 3, status_fn=lambda _i: "Active")
    assert [r["item_id"] for r in revived] == ["A"]
    assert kept == []


def test_unknown_status_is_not_ended():
    """状態が分からない時は触らない (fail-closed)."""
    kept, revived, ended, failed = C.verify_oos(
        _rows("A"), _qty0, status_fn=lambda _i: None)
    assert [r["item_id"] for r in failed] == ["A"]
    assert kept == [] and ended == []


def test_status_fn_error_is_not_ended():
    def boom(_i):
        raise RuntimeError("network")
    kept, revived, ended, failed = C.verify_oos(_rows("A"), _qty0, status_fn=boom)
    assert [r["item_id"] for r in failed] == ["A"]
    assert kept == []


def test_qty_unknown_is_not_ended():
    kept, revived, ended, failed = C.verify_oos(
        _rows("A"), lambda _i: None, status_fn=lambda _i: "Active")
    assert [r["item_id"] for r in failed] == ["A"]
    assert kept == []


def test_status_fn_optional_keeps_old_behaviour():
    """status_fn を渡さない呼び方でも壊れない."""
    kept, revived, ended, failed = C.verify_oos(_rows("A"), _qty0)
    assert [r["item_id"] for r in kept] == ["A"]
    assert ended == []


def test_main_passes_status_fn():
    src = open(os.path.join(os.path.dirname(__file__), "..", "tools", "cull_end.py"),
               encoding="utf-8").read()
    assert "fetch_listing_status" in src, "main() が状態確認を渡していない"
    assert "既に終了済みで除外" in src, "除外件数を出していない (silent drop)"


def test_cap_is_the_single_source():
    """パネル側が件数を書き写していないこと (片方だけ変わるとズレる)."""
    panel = open(os.path.join(os.path.dirname(__file__), "..", "control_panel.py"),
                 encoding="utf-8").read()
    assert "_ce.CAP" in panel, "パネルが cull_end.CAP を見ていない"


# ---- live モード: レポート無しで最新の CULL を出す (2026-08-23) ----
# funnel は Seller Hub のレポートを手で落とさないと更新できず 7/23 のままだった。
# CULL の材料は ActiveList から全部取れる。eBay は 0 の要素を省くので「無い = 0」。

def _live(*items):
    return lambda: list(items)


def _it(i, avail=0, sold=0, watch=0, age=99, price=200.0):
    return {"item_id": i, "avail": avail, "sold": sold, "watch": watch,
            "age_days": age, "price": price, "title": "t"}


def test_live_picks_only_dead_ones():
    rows = C.rows_from_live(_live(
        _it("dead"),
        _it("buyable", avail=2),
        _it("sold_before", sold=1),
        _it("watched", watch=3)))
    assert [r["item_id"] for r in rows] == ["dead"]
    assert rows[0]["flags"] == "CULL"


def test_live_rows_feed_select_unchanged():
    """live の行が既存の select() にそのまま通ること (下流を作り直さない)。

    ★2026-08-31: MIN_AGE を 14→1 に変更 (在庫0の間は待っても表示が増えないので、
      既知の若さでは待たない)。age=5 も既知なのでもう対象に入る。
      並び順は別ロジック (2026-08-24 制定「今月出品分を先に」): today=1/15 時点で
      age=5 の "b" は今月出品 (1/10) → 先頭、age=99 の "a" は前月以前 → その後。
    """
    import datetime
    rows = C.rows_from_live(_live(_it("a", age=99), _it("b", age=5)))
    cull, eligible, picked = C.select(rows, today=datetime.date(2030, 1, 15))
    assert len(cull) == 2
    assert [r["item_id"] for r in eligible] == ["b", "a"], "age=5 (既知) がもう待たされていない"


def test_live_missing_fields_mean_zero():
    """QuantitySold / WatchCount が無い = 0 (eBay は 0 を省く)。"""
    rows = C.rows_from_live(_live(_it("x", sold=0, watch=0)))
    assert len(rows) == 1
