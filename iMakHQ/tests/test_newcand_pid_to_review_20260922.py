"""新規候補の目視で決めたカードを、鑑定番号ごとに PSA 新規の目視の期待値として渡す (2026-09-22)。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import psa_label_learned as L                                  # noqa: E402

SRC = lambda n: open(os.path.join(HERE, "..", "tools", n), encoding="utf-8").read()  # noqa: E731


def test_cert_pid_round_trip(tmp_path):
    p = str(tmp_path / "c.json")
    assert L.remember_cert_pids([("149064738", "one_piece_tcg:ST29-001_p1"), ("", "x"), ("1", "")],
                                path=p) == 1
    assert L.expected_pid_for_cert("149064738", path=p) == "ST29-001_p1"
    assert L.expected_pid_for_cert("999", path=p) == ""


def test_newcand_records_after_append():
    s = SRC("newcand_confirm.py")
    i = s.index("sheet_io.append_product_rows(rows)")
    assert "_PLL.remember_cert_pids(" in s[i:i + 900]


def test_review_prefers_human_pick_in_both_builders():
    s = SRC("post_psa_review.py")
    assert s.count("_cert_expected(cert) or _catalog_lookup_expected(") == 2
