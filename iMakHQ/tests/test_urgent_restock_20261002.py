"""売り切れに変わった出品の次の仕入元を、翌日を待たずに探す (総点検15・2026-10-02)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import kagoya_offload as K  # noqa: E402


def _cell(r, i):
    return r[i] if i < len(r) else ""


COLS = (1, 3, 4, 5, 6)   # B=itemID, D=売り切れ, カテゴリ, 証明番号, KEY


def test_newly_sold_picks_only_new_psa_sold_rows():
    rows = [
        ["u", "111", "t", "○", "TCG", "12345", "k"],     # 新しく売り切れ
        ["u", "222", "t", "○", "TCG", "12345", "k"],     # 前回もう見た
        ["u", "333", "t", "", "TCG", "12345", "k"],      # 売り切れでない
        ["u", "444", "t", "○", "G-shock", "", "k"],      # PSA でない
        ["u", "9999", "t", "○", "TCG", "1", "k"],        # 出品しない印
        ["u", "", "t", "○", "TCG", "1", "k"],            # itemID 無し
        ["u", "555", "t", "○", "TCG", "abc", "k"],       # 証明番号が数字でない
    ]
    got = K.newly_sold(rows, {"222"}, _cell, COLS)
    assert [r[1] for r in got] == ["111"]


def test_merge_changed_writes_only_server_changes():
    """一番くじを KAGOYA で回した結果は、サーバーで変わった項目だけ家に書く (2026-10-02)。"""
    base = {"a": 1, "b": 2, "c": 3}
    srv = {"a": 1, "b": 20, "d": 4}          # b が変わり d が足され c が消えた
    home = {"a": 9, "b": 2, "c": 3, "e": 5}  # 家では昼に a を書き換え e を足した
    out = K.merge_changed(base, srv, home)
    assert out == {"a": 9, "b": 20, "c": 3, "d": 4, "e": 5}
    assert K.merge_changed({}, {}, {"x": 1}) == {"x": 1}
