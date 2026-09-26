"""補URL の書込口: 書く直前に「その行が今も同じ出品か」を確かめる (2026-09-27)。

行はシートの手作業や他の担当で日々ずれる (実例: 9/10 に行1320 の出品が 9/26 には行1318)。
読んでから書くまでにずれると、別の出品に補URL を書く。書込口 1か所で止める。
"""
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "iMakHQ", "tools"))
import sheet_io  # noqa: E402


def _row(a, b):
    r = [""] * 40
    r[0], r[1] = a, b
    return r


SHEET = [["h"] * 40, _row("https://m/1", "111"), _row("https://m/2", ""), _row("https://m/3", "333")]


def test_rows_moved_by_itemid():
    assert sheet_io.rows_moved({2: "111", 4: "333"}, SHEET) == []
    assert sheet_io.rows_moved({2: "999"}, SHEET) == [2]          # 別の出品になっている
    assert sheet_io.rows_moved({2: ""}, SHEET) == [2]             # 予定が空 = 誰の行か分からない
    assert sheet_io.rows_moved({9: "111"}, SHEET) == [9]          # 行が無い


def test_rows_moved_by_supply_url_for_unlisted_row():
    assert sheet_io.rows_moved({3: ("A", "https://m/2")}, SHEET) == []
    assert sheet_io.rows_moved({3: ("A", "https://m/X")}, SHEET) == [3]


class _WS:
    def __init__(self, rows):
        self.rows, self.sent = rows, []

    def get_all_values(self):
        return self.rows

    def batch_update(self, reqs, value_input_option=None):
        self.sent.extend(reqs)


def test_write_skips_moved_rows(monkeypatch):
    ws = _WS(SHEET)
    monkeypatch.setattr(sheet_io, "_product_ws", lambda: ws)
    n = sheet_io.write_aux_urls({2: ["u"], 4: ["v"]}, expect_iid={2: "111", 4: "999"})
    assert n == 1 and [r["range"] for r in ws.sent] == ["AC2:AG2"]


def test_write_stops_when_sheet_unreadable(monkeypatch):
    class _Bad(_WS):
        def get_all_values(self):
            raise RuntimeError("x")
    ws = _Bad(SHEET)
    monkeypatch.setattr(sheet_io, "_product_ws", lambda: ws)
    assert sheet_io.write_aux_urls({2: ["u"]}, expect_iid={2: "111"}) == 0 and ws.sent == []


def test_kuji_restock_skips_moved_rows(monkeypatch):
    """一番くじは A/B/D/M/I も行番号で書く。行がずれていたらその行は丸ごと書かない。"""
    import ichibankuji_restock as K
    ws = _WS(SHEET)
    monkeypatch.setattr(K.sheet_io, "_product_ws", lambda: ws)
    n = K.write_restock({2: {"a": "https://new", "b": "111", "cost": 0},
                         4: {"a": "https://new", "b": "555", "was": "999", "cost": 0}})
    assert n == 1
    assert {r["range"][1:] for r in ws.sent} == {"2"}


def test_every_caller_passes_expect_iid():
    """expect_iid は必須引数。全部の呼び出しが渡していること (渡し忘れは TypeError で落ちる)。"""
    calls = []
    for base in ("iMakHQ", "iMakMercari"):
        for dp, _dn, fs in os.walk(os.path.join(ROOT, base)):
            if "tests" in dp:
                continue
            for f in fs:
                if not f.endswith(".py"):
                    continue
                src = open(os.path.join(dp, f), encoding="utf-8", errors="ignore").read()
                for m in re.finditer(r"write_aux_urls\(", src):
                    line = src[src.rfind("\n", 0, m.start()) + 1:m.start()]
                    if line.lstrip().startswith(("def ", "#")) or "`" in line or "→" in line:
                        continue
                    calls.append((f, src[m.start():m.start() + 250]))
    assert len(calls) >= 7
    for f, body in calls:
        assert "expect_iid" in body, f
