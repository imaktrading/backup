"""仕入元 URL の「カード B と同じ/違う」を、画面をまたいで使う (2026-09-24)。
ユーザー「A が目視で B と確定したら、どの処理で出てきても B として扱う。でないと永遠に繰り返す」。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import psa_label_learned as P                                  # noqa: E402

SRC = lambda n: open(os.path.join(HERE, "..", "tools", n), encoding="utf-8").read()  # noqa: E731


def test_verdict_round_trip_is_per_card(tmp_path):
    p = str(tmp_path / "u.json")
    assert P.remember_url_verdicts([("pokemon_tcg:SV4a-237", "https://jp.mercari.com/item/m1?x=1", "diff", "補URL③"),
                                    ("SV4a-237", "https://jp.mercari.com/item/m2", "same", "再仕入れ①"),
                                    ("SV4a-237", "", "diff", "x")], path=p) == 2
    d = P.load(p)
    assert P.url_verdict("SV4a-237", "https://jp.mercari.com/item/m1", d) == "diff"
    assert P.url_verdict("SV4a-237", "https://jp.mercari.com/item/m2/", d) == "same"
    assert P.url_verdict("OTHER-001", "https://jp.mercari.com/item/m1", d) == ""   # 別カードには効かない


def test_every_candidate_path_reads_and_both_confirm_screens_write():
    g, h = SRC("psa_resource_gate.py"), SRC("psa_hoju_fill.py")
    assert 'url_verdict(card_pid, x.get("url"), _uv) != "diff"' in g           # 候補を出す共通の関数
    assert "card_pid=mp.split_key(r.get(\"key\"))[1]" in g                     # 再仕入れ①
    assert "card_pid=mp.split_key(t.get(\"key\"))[1]" in h                     # 補URL③
    assert 'url_verdict(_pidp, _p["url"], _uvp) == "diff"' in h                # 目視待ちを混ぜる所
    assert '"same", "再仕入れ①"' in g and '"diff", "再仕入れ①"' in g
    assert '"same", "補URL③"' in h and '"diff", "補URL③"' in h


def test_url_same_pid_only_when_unique(tmp_path):
    p = str(tmp_path / "u.json")
    u1, u2, u3 = ("https://jp.mercari.com/item/m%d" % i for i in (1, 2, 3))
    P.remember_url_verdicts([("A-1", u1, "same", "x"), ("B-1", u2, "same", "x"),
                             ("C-1", u2, "same", "y"), ("A-1", u3, "diff", "x")], path=p)
    d = P.load(p)
    assert P.url_same_pid(u1, d) == "A-1"
    assert P.url_same_pid(u2, d) == ""        # 割れている = 使わない
    assert P.url_same_pid(u3, d) == ""


def test_newcand_reads_and_writes():
    s = SRC("newcand_confirm.py")
    assert "_sp = _url_same(p[\"url\"])" in s
    assert '"same", "新規候補")' in s


def test_fake_urls_are_not_recorded(tmp_path):
    """試験の架空 URL (https://m/0) が本物の台帳に入っていた (2026-09-24)。ドメインの無い URL は入れない。"""
    p = str(tmp_path / "u.json")
    assert P.remember_url_verdicts([("A-1", "https://m/0", "same", "x"),
                                    ("A-1", "https://jp.mercari.com/item/m1", "same", "x")], path=p) == 1
