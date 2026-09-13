# -*- coding: utf-8 -*-
"""UT のボタン構成を PSA と揃える (2026-09-13 ユーザー「枠組みだけ作っておいて」)。

PSA は 補URL が 4ボタン (①当日分 / ②夜に探す / ③補充 / ③入れ替え)。UT は ②③ の2つしか
無く、**出した直後に予備を探す口**と**足りている札を安い仕入元に替える口**が無かった。

★入れ替えは今 対象0件 (出品中の Tシャツ35件は全部 補URL 0本)。枠だけ先に用意して、
  ①② で溜まってから効く。使い道が無いうちに作るのは「揃っている形」を保つため。
"""
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "iMakHQ" / "tools", ROOT / "iMakMercari", ROOT / "iMakeBayAPI"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

CP = ROOT / "iMakHQ" / "control_panel.py"


def _labels():
    return re.findall(r'"label": "([^"]+)"', io.open(CP, encoding="utf-8").read())


def test_ut_has_the_same_four_aux_buttons_as_psa():
    got = _labels()
    for step in ("① 当日分", "② 夜に探す", "③ 補充", "③ 入れ替え"):
        assert any(l.startswith("🆕 UT") or l.startswith("🔎 UT") or l.startswith("🩹 UT")
                   or l.startswith("💱 UT") for l in got if step in l), step


def test_supply_and_swap_are_separate_ranges():
    """混ざると、仕入元が1本も無い出品の補充が『足りている札の値下げ』に埋もれる。"""
    src = io.open(CP, encoding="utf-8").read()
    i = src.index('"label": "🩹 UT 補URL ③ 補充"')
    j = src.index('"label": "💱 UT 補URL ③ 入れ替え"')
    assert '"--max-backups=4"' in src[i:i + 900]
    assert '"--min-backups=4"' in src[j:j + 900]


def test_counts_are_split_the_same_way():
    import ut_hoju_fill as U
    keys = U.count_workload.__doc__
    rows = [[""] * 40]

    def row(iid, aux):
        import sheet_io
        r = [""] * 40
        r[0] = "https://jp.mercari.com/item/m12345678901"
        r[sheet_io.PRODUCT_COL_ITEMID] = iid
        r[2] = "UNIQLO UT テスト L"
        r[sheet_io.PRODUCT_COL_CATEGORY] = "Tシャツ"
        for k in range(aux):
            r[sheet_io.PRODUCT_COL_AUX_START + k] = f"https://jp.mercari.com/item/m8888888888{k}"
        return r

    rows += [row("358000000001", 0), row("358000000002", 4), row("358000000003", 5)]
    fill = {t["itemID"] for t in U.select_targets(rows, min_backups=0, max_backups=U.AUX_MAX - 1)}
    swap = {t["itemID"] for t in U.select_targets(rows, min_backups=U.AUX_MAX - 1,
                                                  max_backups=U.AUX_MAX + 1)}
    assert fill == {"358000000001"}, fill
    assert swap == {"358000000002", "358000000003"}, swap
    assert keys is not None


def test_cli_accepts_the_range_flags():
    src = io.open(ROOT / "iMakHQ" / "tools" / "ut_hoju_fill.py", encoding="utf-8").read()
    i = src.index("def main(")
    body = src[i:src.index("\nif __name__", i)]
    assert "--min-backups=" in body and "--max-backups=" in body
