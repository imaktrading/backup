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


def test_flag_new_candidates_idempotent_diff():
    """FLG(Q列): LOW未収載型番だけ '新規'、収載済はクリア、現値一致は書かない."""
    from run_gshock_merge import _flag_new_candidates, COL_KEY_SRC, COL_FLG, FLG_NEW

    def mkrow(model, flg=""):
        r = [""] * 40
        r[COL_KEY_SRC - 1] = model
        r[COL_FLG - 1] = flg
        return r

    class _Ws:
        def __init__(self): self.calls = []
        def batch_update(self, u, value_input_option=None): self.calls.append(u)

    header = [""] * 40
    yvals = [header,
             mkrow("NEW-1AJF"),               # 未収載・未フラグ → 立てる
             mkrow("OLD-1AJF", FLG_NEW),      # 収載済だが誤フラグ残 → クリア
             mkrow("NEW-2AJF", FLG_NEW),      # 未収載・既フラグ → 変更なし(冪等)
             mkrow("OLD-2AJF")]               # 収載済・空 → 変更なし
    ws = _Ws()
    n = _flag_new_candidates(ws, yvals, {"NEW-1AJF", "NEW-2AJF"}, dry_run=False)
    # 書込は row2(立てる) と row3(クリア) の 2 セルのみ
    assert n == 2
    ranges = [u["range"] for call in ws.calls for u in call]
    assert f"Q2" in ranges and f"Q3" in ranges
    assert "Q4" not in ranges and "Q5" not in ranges  # 冪等 skip
