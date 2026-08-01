# -*- coding: utf-8 -*-
"""絵柄の事前判定 (psa_art_match) の振る舞い固定 (2026-08-02)。

ユーザー指示: 「明らかに違うとわかったものは省いてね。自信が無いものは出して目視で落とすけど。」
= different だけ省く / same・unsure は出す / **判定できない事情は全部 unsure に倒す**。
判定不能を理由に候補を捨てると、使える仕入元を黙って失う (fail-OPEN の逆で機会損失)。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import psa_art_match as A


class _FakeClient:
    """anthropic client の最小 stub (messages.create → content[0].text)。"""

    def __init__(self, text):
        self.text = text
        self.messages = self
        self.calls = 0

    def create(self, **kw):
        self.calls += 1
        block = type("B", (), {"text": self.text})()
        return type("R", (), {"content": [block]})()


def _fetch_ok(_u):
    return b"\x89PNG\r\n\x1a\n" + b"x" * 20, "image/png"


def test_parse_verdict_accepts_plain_and_fenced_json():
    assert A.parse_verdict('{"verdict":"same","reason":"一致"}')["verdict"] == "same"
    got = A.parse_verdict('```json\n{"verdict":"different","reason":"別構図"}\n```')
    assert got["verdict"] == "different" and got["reason"] == "別構図"


def test_parse_verdict_falls_back_to_unsure():
    # 壊れた出力・未知の判定値で候補を捨てない
    for bad in ("", "not json", '{"verdict":"maybe"}', None):
        assert A.parse_verdict(bad)["verdict"] == "unsure"


def test_only_different_is_dropped():
    cands = [{"url": "u1"}, {"url": "u2"}, {"url": "u3"}]

    keep, drop = A.annotate_candidates("ref", cands, client=_FakeClient(
        '{"verdict":"different","reason":"別構図"}'), fetch=_fetch_ok, cache={})
    assert (len(keep), len(drop)) == (0, 3)
    assert drop[0]["art_reason"] == "別構図", "省いた理由が残らないと検算できない"

    keep, drop = A.annotate_candidates("ref", cands, client=_FakeClient(
        '{"verdict":"unsure","reason":"不明瞭"}'), fetch=_fetch_ok, cache={})
    assert (len(keep), len(drop)) == (3, 0) and keep[0]["art"] == "unsure"

    keep, drop = A.annotate_candidates("ref", cands, client=_FakeClient(
        '{"verdict":"same","reason":"一致"}'), fetch=_fetch_ok, cache={})
    assert (len(keep), len(drop)) == (3, 0) and keep[0]["art"] == "same"


def test_image_fetch_failure_keeps_candidate():
    keep, drop = A.annotate_candidates(
        "ref", [{"url": "u"}], client=_FakeClient('{"verdict":"different"}'),
        fetch=lambda _u: (None, None), cache={})
    assert (len(keep), len(drop)) == (1, 0) and keep[0]["art"] == "unsure"


def test_api_exception_keeps_candidate():
    class Boom:
        def __init__(self):
            self.messages = self

        def create(self, **kw):
            raise RuntimeError("boom")

    keep, drop = A.annotate_candidates("ref", [{"url": "u"}], client=Boom(),
                                       fetch=_fetch_ok, cache={})
    assert (len(keep), len(drop)) == (1, 0) and keep[0]["art"] == "unsure"


def test_missing_url_is_unsure():
    assert A.compare_art("", "u")["verdict"] == "unsure"
    assert A.compare_art("ref", "")["verdict"] == "unsure"


def test_cache_prevents_repeat_calls():
    cli = _FakeClient('{"verdict":"same","reason":"一致"}')
    cache = {}
    for _ in range(3):
        A.annotate_candidates("ref", [{"url": "u"}], client=cli, fetch=_fetch_ok, cache=cache)
    assert cli.calls == 1, f"同じ組を{cli.calls}回問い合わせている(キャッシュが効いていない)"


def test_candidate_order_is_preserved():
    cands = [{"url": f"u{i}"} for i in range(5)]
    keep, _ = A.annotate_candidates("ref", cands, client=_FakeClient('{"verdict":"same"}'),
                                    fetch=_fetch_ok, cache={})
    assert [c["url"] for c in keep] == [c["url"] for c in cands]


def test_original_candidate_dicts_are_not_mutated():
    cands = [{"url": "u"}]
    A.annotate_candidates("ref", cands, client=_FakeClient('{"verdict":"same"}'),
                          fetch=_fetch_ok, cache={})
    assert "art" not in cands[0], "呼出側の候補 dict を書き換えている"


def test_ui_shows_art_badges():
    import psa_resource_confirm as prc
    h = prc.build_restock_html([{
        "idx": 0, "title": "t", "card_no": "OP09-050", "ebay_url": "https://x",
        "ref_image": "https://img/a.jpg",
        "candidates": [{"channel": "mercari", "url": "https://jp.mercari.com/item/m1",
                        "price": 100, "art": "same", "art_reason": "一致"},
                       {"channel": "mercari", "url": "https://jp.mercari.com/item/m2",
                        "price": 200, "art": "unsure", "art_reason": "不明瞭"}]}])
    assert "🖼️絵柄一致" in h and "🖼️絵柄は要目視" in h
    assert "採用の根拠にはしないでください" in h, "same を根拠にしない旨の注意が無い"
