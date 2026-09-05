# -*- coding: utf-8 -*-
"""取下げボタンに「いくら出品枠が空くか」を出す (2026-09-04 ユーザー要望)。

> 取下げは、金額開かないのかな

eBay の出品枠は **今 売れる状態にある出品の総額** で決まる (件数ではない)。
同じ日に「リストックしてもリミット残が減る」を確認したとおり。
なので「何件落とせるか」より「いくら空くか」が判断材料になる。棚ボタンと同じ考え方。

eBay は1回も叩かない。材料は funnel CSV (ローカル) と 済み台帳だけ
(2026-08-24 に表示目的の取得で取下げが5時間止まった実害があるため)。
"""
import io as _io
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TOOLS = os.path.join(_ROOT, "iMakHQ", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import cull_end as C                                           # noqa: E402


def _funnel(tmp_path, rows):
    p = tmp_path / "funnel_20260904.csv"
    cols = ["item_id", "title", "price", "age_days", "flags", "site"]
    lines = [",".join(cols)]
    for r in rows:
        lines.append(",".join(str(r.get(c, "")) for c in cols))
    p.write_text(chr(10).join(lines), encoding="utf-8")
    return str(tmp_path)


def _row(iid, price):
    return {"item_id": iid, "title": "t" + iid, "price": price,
            "age_days": 60, "flags": "CULL", "site": "US"}


def test_shows_how_much_room_it_frees(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "load_done", lambda: set())
    d = _funnel(tmp_path, [_row("1", 150), _row("2", 220.5), _row("3", 100)])
    got = C.count_workload(funnel_dir=d)
    assert got["next"] == 3
    assert got["usd_next"] == 470.5
    assert got["usd_remaining"] == 470.5


def test_a_bad_price_does_not_break_the_count(tmp_path, monkeypatch):
    """価格が読めない行があっても件数は出す (金額だけ その行を飛ばす)。"""
    monkeypatch.setattr(C, "load_done", lambda: set())
    d = _funnel(tmp_path, [_row("1", 150), _row("2", ""), _row("3", "n/a")])
    got = C.count_workload(funnel_dir=d)
    assert got["next"] == 3 and got["usd_next"] == 150.0


def test_the_panel_shows_the_amount():
    s = _io.open(os.path.join(_ROOT, "iMakHQ", "control_panel.py"),
                 encoding="utf-8").read()
    i = s.index("ce_txt = (")            # ★2026-09-06 文言統一で目印を変更
    assert 'ce.get("usd_next")' in s[i:i + 700], "取下げのヒントに金額を出していない"


def test_still_never_calls_ebay():
    """表示のために API 枠を使わない (2026-08-24 の実害)。"""
    src = _io.open(os.path.join(_TOOLS, "cull_end.py"), encoding="utf-8").read()
    i = src.index("def count_workload")
    j = src.index(chr(10) + "def ", i + 10)
    body = src[i:j]
    for bad in ("fetch_listing_qty", "GetItem", "end_on_ebay", "requests."):
        assert bad not in body, "count_workload が " + bad + " を呼んでいる"
