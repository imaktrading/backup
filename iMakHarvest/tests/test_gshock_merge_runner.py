"""run_gshock_merge / build_yodobashi_snapshot の純粋ヘルパ検証 (列マッピング等)."""
import pytest

pytestmark = pytest.mark.offline


def test_col_letter_ac_ag_mapping():
    """AC-AG(29-33) の列letter が正しい (= 補URL書込先の安全 crit)."""
    from run_gshock_merge import _col_letter
    assert _col_letter(29) == "AC"
    assert _col_letter(30) == "AD"
    assert _col_letter(31) == "AE"
    assert _col_letter(32) == "AF"
    assert _col_letter(33) == "AG"
    assert _col_letter(35) == "AI"  # KEY
    assert _col_letter(1) == "A"
    assert _col_letter(4) == "D"    # 触ってはいけない列


def test_has_yodobashi_detects_url_in_scanned_cols():
    from build_yodobashi_snapshot import _has_yodobashi, COL_SUPP_START
    # A列にヨドバシ
    row_a = ["https://www.yodobashi.com/product/1/"] + [""] * 40
    assert _has_yodobashi(row_a) is True
    # AC列(29)にヨドバシ
    row_ac = [""] * 40
    row_ac[COL_SUPP_START - 1] = "https://www.yodobashi.com/product/2/"
    assert _has_yodobashi(row_ac) is True
    # Amazon のみ → False
    row_amz = ["https://www.amazon.co.jp/dp/B0X"] + [""] * 40
    assert _has_yodobashi(row_amz) is False
