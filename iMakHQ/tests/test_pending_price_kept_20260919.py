"""目視待ちに積む時、その時の値段も残すこと (2026-09-19)。

ユーザー「売り切れでもないのに、価格とか取得できていない仕入候補がある」。
積む時に値段を持たず、画面で **今の検索キャッシュ** から引き直していたので、
数日前に積んだ物は値段が空のまま目視に出ていた
(実測: 目視待ち455本のうち257本 = mercari 223 / snkrdunk 34 が空)。
"""
import sys

sys.path.insert(0, r"C:/dev/iMak/iMakHQ/tools")
import aux_pending as A


def test_積む時に値段を残す():
    rows = A.build_rows({1: ["https://a"]}, "テスト", price_of={"https://a": 1234})
    assert rows[0]["price"] == 1234


def test_値段が分からなければ空で積む():
    rows = A.build_rows({1: ["https://a"]}, "テスト", price_of={})
    assert rows[0]["price"] is None


def test_画面は積んだ時の値段を先に使う():
    src = open(r"C:/dev/iMak/iMakHQ/tools/psa_hoju_fill.py", encoding="utf-8").read()
    body = src.split("_sdp, _sdi = _sd_info.get")[1][:600]
    assert '_pp = _r.get("price")' in body
    assert body.index('_r.get("price")') < body.index("_price_of.get")


def test_値段が無い候補はその旨を画面に出す():
    src = open(r"C:/dev/iMak/iMakHQ/tools/psa_hoju_fill.py", encoding="utf-8").read()
    assert "値段が取れていません" in src
