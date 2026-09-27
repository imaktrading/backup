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


class _WSB(_WS):
    def col_values(self, n):
        return [(r[n - 1] if len(r) >= n else "") for r in self.rows]


def test_write_keys_skips_moved_rows(monkeypatch):
    """KEY 書込 (PSA 再仕入れの目視の後) も、行の itemID を確かめてから書く。"""
    ws = _WSB(SHEET)
    monkeypatch.setattr(sheet_io, "_product_ws", lambda: ws)
    n = sheet_io.write_keys({"111": 2, "333": 3}, {"111": "K1", "333": "K3"})   # 333 は今 行4
    assert n == 1 and [r["range"] for r in ws.sent] == ["AI2"]


def test_write_keys_by_cert_for_unlisted_rows(monkeypatch):
    """psa_to_csv は出品前の行 (itemID 無し) に 鑑定番号 をキーにして KEY を書く。I列で確かめる。"""
    rows = [list(r) for r in SHEET]
    rows[2][8] = "150000001"                     # 行3: itemID 空 / 鑑定番号あり
    ws = _WSB(rows)
    monkeypatch.setattr(sheet_io, "_product_ws", lambda: ws)
    n = sheet_io.write_keys({"150000001": 3, "150000002": 3}, {"150000001": "K", "150000002": "K"})
    assert n == 1 and [r["range"] for r in ws.sent] == ["AI3"]


def test_restock_reactivate_skips_moved_rows(monkeypatch):
    """再仕入れの書戻し (A/D/M。UT は目視 最大3時間の後) も同じ。"""
    ws = _WSB(SHEET)
    monkeypatch.setattr(sheet_io, "_product_ws", lambda: ws)
    n = sheet_io.restock_reactivate_master({"111": 2, "333": 2}, {"111": "https://a", "333": "https://b"})
    assert n == 1 and all(r["range"].endswith("2") for r in ws.sent)
    assert {"range": "A2", "values": [["https://a"]]} in ws.sent


def test_row_check_stops_when_unreadable(monkeypatch):
    class _Bad(_WS):
        def col_values(self, n):
            raise RuntimeError("x")
    ws = _Bad(SHEET)
    monkeypatch.setattr(sheet_io, "_product_ws", lambda: ws)
    assert sheet_io.write_keys({"111": 2}, {"111": "K"}) == 0 and ws.sent == []


def test_cull_from_backup_checks_supply_url():
    """取下げの書戻しを控えからやり直す時、控えの行番号を A列 (仕入元URL) で確かめる。"""
    src = open(os.path.join(ROOT, "iMakHQ", "tools", "cull_writeback.py"), encoding="utf-8").read()
    i = src.index("if (cfg[\"label\"], n) not in by_row:")
    assert "_a_now != a_of[(cfg[\"label\"], n)]" in src[i:i + 700]


def test_kuji_size_write_checks_supply_url():
    """一番くじのサイズ (AB列) は再スクレイプの後に書くので、A列が同じ時だけ書く。"""
    src = open(os.path.join(ROOT, "iMak_ichibankuji", "ichibankuji_to_csv.py"), encoding="utf-8").read()
    i = src.index('ws.update_acell(f"AB{t[\'sheet_row\']}"')
    assert "_a_now == t['mercari_url'].strip()" in src[i - 400:i]


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
