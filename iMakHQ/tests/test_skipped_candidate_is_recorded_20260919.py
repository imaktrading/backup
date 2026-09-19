"""「見送り」にした候補も記録し、値段が下がるまで再表示しない (2026-09-19)。

実害 (ユーザー「以前目視したのに再び現れている」): 出品を確定した時に、
チェックを外しただけの候補は **どこにも記録が残らず**、次回また同じ候補が並んでいた。
記録されていたのは「違う」だけ。
"""
import sys

sys.path.insert(0, r"C:/dev/iMak/iMakHQ/tools")
import psa_hoju_fill as H

ROWS = [H.NG_CAND_HEADER,
        ["iid1", "c", "https://a", "t", "2026-09-18", "名前", "5000", "見送り"],
        ["iid1", "c", "https://b", "t", "2026-09-18", "名前", "3000", "違う"],
        ["iid1", "c", "https://c", "t", "2026-09-01", "名前", "1000"]]   # 古い行 = 違う


def test_違うと見送りを分けて読む():
    assert H._ng_urls_by_iid(ROWS) == {"iid1": {"https://b", "https://c"}}
    assert H.skipped_by_iid(ROWS) == {"iid1": {"https://a": 5000}}


def test_同じ値段なら出さない():
    keep, drop = H.filter_candidates_skipped([{"url": "https://a", "price": 5000}],
                                             {"https://a": 5000})
    assert keep == [] and len(drop) == 1


def test_安くなったら再び出す():
    keep, drop = H.filter_candidates_skipped([{"url": "https://a", "price": 4000}],
                                             {"https://a": 5000})
    assert len(keep) == 1 and drop == []


def test_見送っていない候補は素通し():
    c = [{"url": "https://z", "price": 100}]
    assert H.filter_candidates_skipped(c, {"https://a": 5000}) == (c, [])


def test_確定時に外した候補を記録する():
    """出品を確定した走行でも、外した候補は台帳に積む (コードの形で見張る)。"""
    src = open(r"C:/dev/iMak/iMakHQ/tools/psa_hoju_fill.py", encoding="utf-8").read()
    assert '"見送り"]' in src            # 理由つきで積んでいる
    assert "_sk_new" in src
    assert "filter_candidates_skipped(cands" in src
