"""目視で選び直したカードを PSA ラベルごとに覚え、次の別の鑑定品で期待値にする (2026-09-22)。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import psa_label_learned as L                                  # noqa: E402

T = {"111": {"category": "pokemon_tcg", "brand": "POKEMON JAPANESE XY9 BREAK",
             "card_number": "019", "subject": "M GYARADOS EX"}}


def test_chosen_is_remembered_by_label_not_cert(tmp_path):
    p = str(tmp_path / "l.json")
    n = L.record_chosen([{"cert": "111", "choice": "CHOSEN", "selected_pid": "XY9-B-019"}], T, path=p)
    assert n == 1
    # 別の鑑定品 (cert 違い) でも、ラベルが同じなら引ける。大文字小文字・空白は吸収
    key = L.label_key("pokemon_tcg", "pokemon japanese  xy9 break", "019", "m gyarados ex")
    assert L.learned_pid(L.load(p), key) == "XY9-B-019"


def test_ok_and_none_are_not_learned(tmp_path):
    p = str(tmp_path / "l.json")
    assert L.record_chosen([{"cert": "111", "choice": "OK", "expected": "X"},
                            {"cert": "111", "choice": "NONE"}], T, path=p) == 0


def test_split_picks_are_not_used():
    d = {}
    k = L.label_key("c", "b", "1", "s")
    L.remember(d, k, "A-001")
    L.remember(d, k, "A-001_p1")
    assert L.learned_pid(d, k) is None


def test_wired_into_review():
    src = open(os.path.join(HERE, "..", "tools", "post_psa_review.py"), encoding="utf-8").read()
    assert "_PLL.learned_pid(" in src and "_PLL.record_chosen(results, _TARGETS_BY_CERT)" in src
