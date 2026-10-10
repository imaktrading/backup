"""写真の読み取りは「セルフチェックで落ちた分だけ」(2026-10-10・ユーザー「落ちた分だけ、読めば？」→「直して」)。

実測: 200件の突き合わせで 190件は写真を読んでも読まなくても出品行が同じ。
違いは Type 空でセルフチェックに落ちる 8件だけ (写真が Type を埋めて通していた)。
直した後の同じ200件: 出品行 200/200 同じ・API を呼ぶのは 12件 (番号なし DON!! 3 + 読み直し 9)。
"""
import sys

sys.path.insert(0, r"C:/dev/iMak/iMakTCG")
import psa_to_csv as P


def _fake_build(results):
    calls = []

    def build(cert, price, data, desc, driver=None, catalog_misses=None, pid_by_cert=None, vision="on"):
        calls.append(vision)
        catalog_misses.append(("x", vision))
        return results[vision]
    return build, calls


def test_通れば読まない():
    build, calls = _fake_build({"auto": ["row"]})
    assert P.build_row_lazy_vision("1", 100, {}, "", catalog_misses=[], _build=build) == ["row"]
    assert calls == ["auto"]


def test_落ちたら読んで作り直し_1回目の積みは消す():
    build, calls = _fake_build({"auto": P.RETRY_WITH_VISION, "on": ["row2"]})
    misses = [("前から", "")]
    assert P.build_row_lazy_vision("1", 100, {}, "", catalog_misses=misses, _build=build) == ["row2"]
    assert calls == ["auto", "on"]
    assert misses == [("前から", ""), ("x", "on")]


def test_読み直しても落ちたら_None():
    build, _ = _fake_build({"auto": P.RETRY_WITH_VISION, "on": None})
    assert P.build_row_lazy_vision("1", 100, {}, "", catalog_misses=[], _build=build) is None


def test_本番の呼び出しは読み直し付き():
    src = open(r"C:/dev/iMak/iMakTCG/psa_to_csv.py", encoding="utf-8").read()
    assert "row = build_row_lazy_vision(cert, DEFAULT_PRICE" in src
    assert "🖼️ 写真の読み取り: API" in src
