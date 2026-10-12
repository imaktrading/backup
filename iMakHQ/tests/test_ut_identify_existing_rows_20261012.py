"""UT 目視: 在る行を「カタログに無い」と依頼しない (2026-10-12・B-20261012-005)。

- 同じメルカリの出品を前に依頼していたら書かない (m26495721051 ヤムチャは 9/13 に依頼済みで 10/12 に2回目)
- 依頼書に「目視で出した候補」を書く (在る物を「無い」と言い切らない)
- 括弧【】で囲んだ作品名も当て語にする (「【推しの子】 UT」が候補に1件も出なかった・9/16 の「実は在った」)
"""
import os
import sys
import tempfile

sys.path.insert(0, r"C:/dev/iMak/iMakHQ/tools")
import ut_identify as U


def test_前の依頼を引く():
    d = tempfile.mkdtemp()
    open(os.path.join(d, "2026-09-13_ut_not_in_catalog.md"), "w", encoding="utf-8").write(
        "| x | https://jp.mercari.com/item/m26495721051 |")
    assert U.past_requests("https://jp.mercari.com/item/m26495721051", d) == ["2026-09-13_ut_not_in_catalog.md"]
    assert U.past_requests("https://jp.mercari.com/item/m99999999999", d) == []


def test_依頼書に目視で出した候補を書く():
    md = U.request_md([{"url": "https://jp.mercari.com/item/m1", "title": "t", "shown": ["E410898-000"]}])
    assert "目視で出した候補 (違うと判断): E410898-000" in md
    assert "カタログに候補が無かった**行" not in md


def test_括弧で囲んだ作品名も当て語にする():
    toks = U._tokens({"name": "【推しの子】 UT（半袖・レギュラーフィット）"})
    assert "推しの子" in toks
