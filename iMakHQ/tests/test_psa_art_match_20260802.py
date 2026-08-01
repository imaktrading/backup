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


def test_match_pct_is_parsed_and_clamped():
    assert A.parse_verdict('{"verdict":"same","match_pct":93}')["match_pct"] == 93
    # 不正値は None (= 「%不明」表示)。0 に丸めると「0%一致」と誤読される
    assert A.parse_verdict('{"verdict":"same","match_pct":"abc"}')["match_pct"] is None
    assert A.parse_verdict('{"verdict":"same"}')["match_pct"] is None
    assert A.parse_verdict('{"verdict":"same","match_pct":420}')["match_pct"] == 100
    assert A.parse_verdict('{"verdict":"same","match_pct":-5}')["match_pct"] == 0


def test_pct_is_attached_to_candidates():
    keep, _ = A.annotate_candidates("ref", [{"url": "u"}], client=_FakeClient(
        '{"verdict":"same","match_pct":88,"reason":"構図一致"}'), fetch=_fetch_ok, cache={})
    assert keep[0]["art_pct"] == 88 and keep[0]["art_reason"] == "構図一致"


def test_ui_shows_art_badges():
    import psa_resource_confirm as prc
    h = prc.build_restock_html([{
        "idx": 0, "title": "t", "card_no": "OP09-050", "ebay_url": "https://x",
        "ref_image": "https://img/a.jpg",
        "candidates": [{"channel": "mercari", "url": "https://jp.mercari.com/item/m1",
                        "price": 100, "art": "same", "art_pct": 93,
                        "art_reason": "構図一致"},
                       {"channel": "mercari", "url": "https://jp.mercari.com/item/m2",
                        "price": 200, "art": "unsure", "art_pct": 58,
                        "art_reason": "反射で見えない"}]}])
    # ユーザー要求(2026-08-02): 判断材料は **HTML本文に出す**。tooltip は出ていないのと同じ
    assert "一致度 93%" in h and "一致度 58%(要目視)" in h
    assert "構図一致" in h and "反射で見えない" in h, "判断理由が本文に出ていない"
    assert "採用の根拠にはせず" in h, "一致度を根拠にしない旨の注意が無い"


def test_uniform_variant_badge_is_replaced_by_one_line():
    """全候補が同じ変種判定なら候補ごとのバッジは出さない。

    実例 (itemID 358600821598 / OP09-050 ナミ): 8候補すべて「⚠️変種未確認」= 見分けに
    使えないのに全部に警告が付き、警告として死んでいた。
    """
    import psa_resource_confirm as prc
    h = prc.build_restock_html([{
        "idx": 0, "title": "t", "card_no": "OP09-050", "ebay_url": "https://x",
        "ref_image": "https://img/a.jpg",
        "candidates": [{"channel": "mercari", "url": "https://jp.mercari.com/item/m1",
                        "price": 100, "variant_ok": False},
                       {"channel": "mercari", "url": "https://jp.mercari.com/item/m2",
                        "price": 200, "variant_ok": False}]}])
    assert "⚠️変種未確認" not in h, "見分けに使えないバッジが候補ごとに出ている"
    assert "裏取りできず" in h and "判断材料になりません" in h


def test_mixed_variant_badges_are_kept():
    """差がある時は従来どおり候補ごとに出す (情報として機能する)。"""
    import psa_resource_confirm as prc
    h = prc.build_restock_html([{
        "idx": 0, "title": "t", "card_no": "OP09-050", "ebay_url": "https://x",
        "ref_image": "https://img/a.jpg",
        "candidates": [{"channel": "mercari", "url": "https://jp.mercari.com/item/m1",
                        "price": 100, "variant_ok": True},
                       {"channel": "mercari", "url": "https://jp.mercari.com/item/m2",
                        "price": 200, "variant_ok": False}]}])
    assert "✅変種一致" in h and "⚠️変種未確認" in h


# ============================================================================
# 3軸判定 (絵柄 / 変種 / 配布) — ユーザー指示 2026-08-02
#   「①一致度だけでなく ②変種・配布の確認 ③拡大して見る もできるでしょ」
# ============================================================================
_FULL = ('{"verdict":"same","match_pct":91,'
         '"art":"same","art_reason":"構図一致",'
         '"variant":"same","variant_reason":"箔の反射あり",'
         '"dist":"same","dist_reason":"新たなる皇帝と記載",'
         '"reason":"3軸とも一致"}')


def test_three_axes_are_parsed():
    d = A.parse_verdict(_FULL)
    assert (d["art"], d["variant"], d["dist"]) == ("same", "same", "same")
    assert d["variant_reason"] == "箔の反射あり" and d["dist_reason"] == "新たなる皇帝と記載"


def test_unknown_axis_when_missing_or_invalid():
    d = A.parse_verdict('{"verdict":"same","art":"maybe"}')
    assert d["art"] == "unknown" and d["variant"] == "unknown" and d["dist"] == "unknown"
    for a in A.AXES:
        assert A.parse_verdict("broken")[a] == "unknown"


def test_dropped_when_art_or_dist_differs():
    assert "絵柄が別" in A.drop_reason({"art": "different", "art_reason": "別構図"})
    assert "配布が別" in A.drop_reason(
        {"art": "same", "dist": "different", "dist_reason": "キャンペーン版"})


def test_variant_mismatch_is_kept_not_dropped():
    """変種違いは写真で見誤りやすいので省かない。印を付けて人に見せる。"""
    res = {"art": "same", "variant": "different", "dist": "same", "verdict": "unsure"}
    assert A.drop_reason(res) == ""
    keep, drop = A.annotate_candidates("ref", [{"url": "u"}], client=_FakeClient(
        '{"verdict":"unsure","match_pct":70,"art":"same","variant":"different",'
        '"variant_reason":"箔が見えない","dist":"same"}'), fetch=_fetch_ok, cache={})
    assert (len(keep), len(drop)) == (1, 0)
    assert keep[0]["ax_variant"] == "different" and keep[0]["ax_variant_reason"] == "箔が見えない"


def test_reference_facts_and_title_go_into_prompt():
    p = A.build_prompt({"number": "OP09-050", "variety": "ALTERNATE ART",
                        "set_name": "BOOSTER -EMPERORS IN THE NEW WORLD- [OP-09]"},
                       "【PSA10】ナミ OP09-050 新たなる皇帝")
    assert "OP09-050" in p and "ALTERNATE ART" in p and "EMPERORS" in p
    assert "新たなる皇帝" in p
    assert "『無い』と解釈しない" in p, "書いていない=無い と誤読させない指示が要る"


def test_extra_photo_urls_for_mercari_only():
    u = "https://static.mercdn.net/item/detail/orig/photos/m61591955291_1.jpg"
    assert A.extra_photo_urls(u) == [
        "https://static.mercdn.net/item/detail/orig/photos/m61591955291_2.jpg"]
    assert A.extra_photo_urls("https://cdn.snkrdunk.com/x.webp") == []
    assert A.extra_photo_urls("") == []


def test_old_cache_entries_are_reused_after_prompt_change():
    """質問を変えても、判定済みの分を捨てない (APIが使えない時に効く)。"""
    old_key = A._cache_key("ref", "u", "", version=A.PROMPT_VERSION - 1)
    cache = {old_key: {"verdict": "different", "match_pct": 5, "reason": "別構図"}}
    keep, drop = A.annotate_candidates("ref", [{"url": "u"}], client=None,
                                       fetch=_fetch_ok, cache=cache, api_key="")
    assert (len(keep), len(drop)) == (0, 1), "旧判定が引き継がれていない"
    assert drop[0]["art_pct"] == 5
    assert drop[0]["ax_art"] == "unknown", "旧形式に無い軸は unknown(=目視)"


def test_ui_shows_three_axis_rows():
    import psa_resource_confirm as prc
    h = prc.build_restock_html([{
        "idx": 0, "title": "t", "card_no": "OP09-050", "ebay_url": "https://x",
        "ref_image": "https://img/a.jpg",
        "candidates": [{"channel": "mercari", "url": "https://jp.mercari.com/item/m1",
                        "price": 100, "art": "same", "art_pct": 91, "art_reason": "総合一致",
                        "ax_art": "same", "ax_art_reason": "構図一致",
                        "ax_variant": "different", "ax_variant_reason": "箔が見えない",
                        "ax_dist": "unknown", "ax_dist_reason": ""}]}])
    assert "絵柄: 一致" in h and "構図一致" in h
    assert "変種: 不一致" in h and "箔が見えない" in h
    assert "配布: 材料なし→目視" in h
    assert "変種の不一致は省きません" in h
