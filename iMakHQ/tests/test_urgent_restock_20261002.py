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
