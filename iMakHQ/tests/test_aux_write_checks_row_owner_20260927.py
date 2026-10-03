"""シートの書込口: 行番号で書く前に、その出品の **今の行** を探し直す (2026-09-27)。

行はシートの手作業や他の担当で日々ずれる (実例: 9/10 に行1320 の出品が 9/26 には行1318)。
前に読んだ行番号のまま書くと別の出品の行を書き換える。飛ばすだけだと本来の書込が残らないので、
目印 (itemID / 鑑定番号 / 未出品なら仕入元URL) で今の行を探し、そこに書く。
見つからない・2行ある・2件が同じ行に当たる時だけ書かない。
"""
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "iMakHQ", "tools"))
import sheet_io  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_aux_log(monkeypatch, tmp_path):
    """★2026-10-04: 本物の補URL 記録 (review_logs/aux_url_log.jsonl) に「行2/4・url u」を書いていた
    (コミットのたびに2行・計359行)。記録先を一時フォルダに向ける。"""
    import aux_url_log
    monkeypatch.setattr(aux_url_log, "LOG_PATH", str(tmp_path / "aux_url_log.jsonl"))


def _row(a, b):
    r = [""] * 40
    r[0], r[1] = a, b
    return r


# 行2: 111 / 行3: 未出品 (A=m/2) / 行4: 333
SHEET = [["h"] * 40, _row("https://m/1", "111"), _row("https://m/2", ""), _row("https://m/3", "333")]


def test_rows_moved_by_itemid():
    assert sheet_io.rows_moved({2: "111", 4: "333"}, SHEET) == []
    assert sheet_io.rows_moved({2: "999"}, SHEET) == [2]
    assert sheet_io.rows_moved({2: ""}, SHEET) == [2]
    assert sheet_io.rows_moved({9: "111"}, SHEET) == [9]


def test_find_current_row():
    rows = [list(r) for r in SHEET]
    assert sheet_io.find_current_row("333", rows, 2) == 4                      # ずれた → 今の行
    assert sheet_io.find_current_row("111", rows, 2) == 2                      # そのまま
    assert sheet_io.find_current_row("999", rows, 2) is None                   # 無い
    assert sheet_io.find_current_row(("A", "https://m/2"), rows, 9) == 3       # 未出品は A列で
    assert sheet_io.find_current_row(("A", "https://m/1"), rows, 2) is None    # 出品済みの行は A で当てない
    rows.append(_row("https://m/9", "333"))
    assert sheet_io.find_current_row("333", rows, 2) is None                   # 2行ある → 書かない


class _WS:
    def __init__(self, rows):
        self.rows, self.sent = rows, []

    def get_all_values(self):
        return self.rows

    def col_values(self, n):
        return [(r[n - 1] if len(r) >= n else "") for r in self.rows]

    def batch_update(self, reqs, value_input_option=None):
        self.sent.extend(reqs)


def test_aux_write_relocates_shifted_row(monkeypatch):
    """補URL: 行2 に居たはずの 333 が今は行4 → 行4 に書く。"""
    ws = _WS(SHEET)
    monkeypatch.setattr(sheet_io, "_product_ws", lambda: ws)
    n = sheet_io.write_aux_urls({2: ["u"]}, expect_iid={2: "333"})
    assert n == 1 and [r["range"] for r in ws.sent] == ["AC4:AG4"]
    assert sheet_io.current_row(2) == 4


def test_aux_write_skips_not_found_and_same_target(monkeypatch):
    ws = _WS(SHEET)
    monkeypatch.setattr(sheet_io, "_product_ws", lambda: ws)
    n = sheet_io.write_aux_urls({2: ["u"], 4: ["v"]}, expect_iid={2: "111", 4: "999"})
    assert n == 1 and [r["range"] for r in ws.sent] == ["AC2:AG2"]
    assert sheet_io.write_aux_urls({2: ["u"], 3: ["v"]}, expect_iid={2: "333", 3: "333"}) == 0


def test_aux_write_stops_when_sheet_unreadable(monkeypatch):
    class _Bad(_WS):
        def get_all_values(self):
            raise RuntimeError("x")
    ws = _Bad(SHEET)
    monkeypatch.setattr(sheet_io, "_product_ws", lambda: ws)
    assert sheet_io.write_aux_urls({2: ["u"]}, expect_iid={2: "111"}) == 0 and ws.sent == []


def test_kuji_restock_relocates(monkeypatch):
    """一番くじは A/B/D/M/I も行番号で書く。ずれていたら今の行へ、見つからなければ書かない。"""
    import ichibankuji_restock as K
    ws = _WS(SHEET)
    monkeypatch.setattr(K.sheet_io, "_product_ws", lambda: ws)
    n = K.write_restock({2: {"a": "https://new", "b": "333", "cost": 0},              # 333 は今 行4
                         3: {"a": "https://new", "b": "555", "was": "999", "cost": 0}})  # 無い
    assert n == 1
    assert {r["range"][1:] for r in ws.sent} == {"4"}


def test_write_keys_relocates(monkeypatch):
    """KEY 書込 (PSA 再仕入れの目視の後) も、今の行を探して書く。"""
    ws = _WS(SHEET)
    monkeypatch.setattr(sheet_io, "_product_ws", lambda: ws)
    n = sheet_io.write_keys({"111": 2, "333": 3}, {"111": "K1", "333": "K3"})    # 333 は今 行4
    assert n == 2 and sorted(r["range"] for r in ws.sent) == ["AI2", "AI4"]
    assert sheet_io.write_keys({"999": 2}, {"999": "K"}) == 0


def test_write_keys_by_cert_for_unlisted_rows(monkeypatch):
    """psa_to_csv は出品前の行 (itemID 無し) に 鑑定番号 をキーにして KEY を書く。I列で探す。"""
    rows = [list(r) for r in SHEET]
    rows[2][8] = "150000001"
    ws = _WS(rows)
    monkeypatch.setattr(sheet_io, "_product_ws", lambda: ws)
    n = sheet_io.write_keys({"150000001": 3, "150000002": 3}, {"150000001": "K", "150000002": "K"})
    assert n == 1 and [r["range"] for r in ws.sent] == ["AI3"]


def test_restock_reactivate_relocates(monkeypatch):
    """再仕入れの書戻し (A/D/M。UT は目視 最大3時間の後) も同じ。"""
    ws = _WS(SHEET)
    monkeypatch.setattr(sheet_io, "_product_ws", lambda: ws)
    n = sheet_io.restock_reactivate_master({"111": 2, "333": 2}, {"111": "https://a", "333": "https://b"})
    assert n == 2
    assert {"range": "A2", "values": [["https://a"]]} in ws.sent
    assert {"range": "A4", "values": [["https://b"]]} in ws.sent


def test_row_check_stops_when_unreadable(monkeypatch):
    class _Bad(_WS):
        def col_values(self, n):
            raise RuntimeError("x")
    ws = _Bad(SHEET)
    monkeypatch.setattr(sheet_io, "_product_ws", lambda: ws)
    assert sheet_io.write_keys({"111": 2}, {"111": "K"}) == 0 and ws.sent == []


def test_cull_from_backup_relocates_by_supply_url():
    src = open(os.path.join(ROOT, "iMakHQ", "tools", "cull_writeback.py"), encoding="utf-8").read()
    assert '_si.find_current_row(("A", url), vals, r0)' in src
    assert "if n not in _targets:" in src


def test_kuji_size_write_relocates_by_supply_url():
    src = open(os.path.join(ROOT, "iMak_ichibankuji", "ichibankuji_to_csv.py"), encoding="utf-8").read()
    assert "_si.find_current_row((\"A\", t['mercari_url'])" in src
    assert 'ws.update_acell(f"AB{_r1}"' in src


def test_read_back_uses_actual_row():
    for f in ("psa_hoju_fill.py", "hoju_url_from_dupes.py"):
        src = open(os.path.join(ROOT, "iMakHQ", "tools", f), encoding="utf-8").read()
        assert "current_row(row)" in src, f


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
