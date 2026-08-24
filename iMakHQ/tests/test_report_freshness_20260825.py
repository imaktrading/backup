# -*- coding: utf-8 -*-
"""レポート鮮度が一度も更新されていなかった (2026-08-25)。

> レポート鮮度が更新されないんだけど

原因: レポートは **日付フォルダの中**に置かれている
(`seller_hub/reports/20260823/eBay-all-active-listings-report-2026-08-23-*.csv`) のに、
鮮度の計算は `reports/` **直下だけ** を glob していた。4種とも 0件 = 常に「✗無し」で、
worst=999 の赤いまま動かなかった。

実測 (2026-08-25): 直下 0件 / 再帰 active 4・orders 7・unsold 6・quality 6。

★日付は **ファイル名から読む**。mtime はフォルダに置き直すと更新され、実態より新しく
  見えてしまう (古いレポートで判断する事故のもと)。この方針は変えない。
"""
import datetime
import os
import re
import sys

import pytest

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HQ not in sys.path:
    sys.path.insert(0, _HQ)

_SRC = open(os.path.join(_HQ, "control_panel.py"), encoding="utf-8").read()


# ── 配線 (これが抜けていた) ────────────────────────────────────────
def test_reports_are_searched_recursively():
    """日付フォルダに入れても拾えること。"""
    assert 'os.path.join(REPORTS_DIR, "**", pat), recursive=True' in _SRC, \
        "直下しか見ていない (日付フォルダの中のレポートが見つからない)"


def test_mtime_is_still_not_the_source_of_truth():
    """置き直しで新しく見える mtime を日付の根拠にしない、は維持する。"""
    assert "mtime はフォルダに" in _SRC or "mtime はフォルダ" in _SRC


# ── ファイル名から日付を読む (既存仕様の固定) ──────────────────────
def _file_report_date(path):
    """control_panel の同名関数と同じ規則 (テスト用に写した純関数)。"""
    b = os.path.basename(path)
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", b)
    if m:
        return datetime.date(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r"(\d{2})_(\d{2})_(\d{4})", b)
    if m:
        return datetime.date(int(m[3]), int(m[1]), int(m[2]))
    return None


@pytest.mark.parametrize("name,want", [
    ("eBay-all-active-listings-report-2026-08-23-12340861100.csv",
     datetime.date(2026, 8, 23)),
    ("ebay-all-orders-report-2026-07-23-12333943648.csv",
     datetime.date(2026, 7, 23)),
    ("eBay-unsold-listings-report-2026-06-03-11311100249.csv",
     datetime.date(2026, 6, 3)),
    # quality だけ MM_DD_YYYY
    ("Listing quality report for imax-64 - US - 08_19_2026 07-30 PST.xlsx",
     datetime.date(2026, 8, 19)),
    ("Listing quality report for imax-64 - US - 05_26_2026 07-32 PST.xlsx",
     datetime.date(2026, 5, 26)),
])
def test_date_comes_from_the_filename(name, want):
    assert _file_report_date(name) == want


def test_newest_wins_across_folders(tmp_path):
    """複数の日付フォルダに同じ種類が在る時、いちばん新しい日付で判定する。"""
    import glob
    for day in ("20260604", "20260723", "20260823"):
        d = tmp_path / day
        d.mkdir()
        (d / f"eBay-all-active-listings-report-{day[:4]}-{day[4:6]}-{day[6:]}-1.csv").write_text("x")
    fs = glob.glob(os.path.join(str(tmp_path), "**",
                                "eBay-all-active-listings-report*"), recursive=True)
    assert len(fs) == 3
    assert max(_file_report_date(p) for p in fs) == datetime.date(2026, 8, 23)


def test_real_reports_are_found_now():
    """実機のレポート置き場で、4種とも見つかること (0件なら鮮度は出せない)。"""
    import glob
    root = r"C:/dev/iMak_data/seller_hub/reports"
    if not os.path.isdir(root):
        pytest.skip("レポート置き場が無い環境")
    for pat in ("eBay-all-active-listings-report*", "ebay-all-orders-report*",
                "eBay-unsold-listings-report*", "Listing quality report*"):
        fs = glob.glob(os.path.join(root, "**", pat), recursive=True)
        assert fs, f"{pat} が1件も見つからない"


# ── レポートを読む側も全部 日付フォルダ対応 (2026-08-25) ───────────
# ユーザー「今後も日付フォルダを作って入れていくけど、対応できる？」
# 鮮度の表示だけ直しても、**読む側**が直下しか見ていなければ分析が動かない。
# 実際 funnel の入力も 0件で、funnel CSV が 7/23 のまま古かった。


def _read(rel):
    return open(os.path.join(os.path.dirname(_HQ), rel), encoding="utf-8").read()


def test_funnel_finds_reports_in_dated_folders():
    src = _read("iMakHQ/tools/listing_funnel.py")
    assert 'glob.glob(os.path.join(data_dir, "**", pattern), recursive=True)' in src


def test_funnel_picks_by_filename_date_not_mtime():
    """置き直しで新しく見える mtime を「最新」の根拠にしない。"""
    src = _read("iMakHQ/tools/listing_funnel.py")
    assert "_report_date_or_none(p) or datetime.date.min" in src


def test_demand_winners_finds_reports_in_dated_folders():
    src = _read("iMakHQ/tools/demand_winners.py")
    assert '"**", "*orders*.csv"' in src and "recursive=True" in src


def test_funnel_actually_resolves_all_four_inputs():
    """実機で4種とも1本に決まること (どれか None だとファネルが止まる)。"""
    import sys as _sys
    tools = os.path.join(_HQ, "tools")
    if tools not in _sys.path:
        _sys.path.insert(0, tools)
    import listing_funnel as F
    if not os.path.isdir(F.DEFAULT_DATA_DIR):
        pytest.skip("レポート置き場が無い環境")
    for pat in ("*all-active-listings*.csv", "*all-orders*.csv",
                "*unsold-listings*.csv", "Listing quality report*"):
        assert F.find_file(F.DEFAULT_DATA_DIR, pat), pat


def test_newest_folder_wins_even_if_old_file_touched_later(tmp_path):
    """古いフォルダのファイルを触っても、日付が新しい方が選ばれること。"""
    import sys as _sys
    import time
    tools = os.path.join(_HQ, "tools")
    if tools not in _sys.path:
        _sys.path.insert(0, tools)
    import listing_funnel as F
    old = tmp_path / "20260604"
    new = tmp_path / "20260823"
    old.mkdir()
    new.mkdir()
    p_new = new / "eBay-all-active-listings-report-2026-08-23-1.csv"
    p_old = old / "eBay-all-active-listings-report-2026-06-04-1.csv"
    p_new.write_text("x")
    p_old.write_text("x")
    time.sleep(0.01)
    os.utime(str(p_old), None)                    # 古い方を「今」触る
    got = F.find_file(str(tmp_path), "*all-active-listings*.csv")
    assert os.path.basename(got) == p_new.name, got
