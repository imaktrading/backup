"""tests/test_psa_cert - PSA cert 照合ゲートのオフラインテスト (2026-08-17).

メルカリ PSA10 出品を新規出品候補として拾うには 「どのカードか」 の確証が要る。
Vision がスラブラベルから読んだ cert を PSA 公式で引き、 **ラベル項目の多信号一致**で
1 桁誤読 (= 実在する別カードに当たるケース) を落とす、 という設計の検証。

ネットワークは叩かない (parse_cert_html / match_signals / verify は fetch を monkeypatch)。
"""
from __future__ import annotations

import pytest

from scrapers import psa_cert as P
from scrapers import psa_slab_vision as V

pytestmark = pytest.mark.offline


# 実ページ (cert 153420191) の項目テーブル構造を再現した最小 HTML
REAL_HTML = """
<html><body>
<script>var x = "Subject";</script>
<p>the requested certification number is defined as the following:</p>
<h1>#153420191</h1>
<div>2025 ONE PIECE JAPANESE LET&#x27;S START CAMPAIGN PROMOTION PACK #077 PERONA</div>
<dl>
  <dt>Cert Number</dt><dd>153420191</dd>
  <dt>Item Grade</dt><dd>GEM MT 10</dd>
  <dt>Year</dt><dd>2025</dd>
  <dt>Brand/Title</dt><dd>ONE PIECE JAPANESE LET&#x27;S START CAMPAIGN PROMOTION PACK</dd>
  <dt>Subject</dt><dd>PERONA</dd>
  <dt>Card Number</dt><dd>077</dd>
  <dt>Category</dt><dd>TCG Cards</dd>
  <dt>Variety/Pedigree</dt><dd>LET&#x27;S START CP PR PCK-ALT ART</dd>
</dl>
</body></html>
"""

VISION_OK = {
    "cert": "153420191",
    "grade": "GEM MT 10",
    "label": "2025 ONE PIECE JAPANESE LET'S START CAMPAIGN PROMOTION PACK PERONA",
    "card_number": "077",
    "year": "2025",
}


def _info(**over):
    base = P.parse_cert_html(REAL_HTML)
    base.update(over)
    return base


def _stub_fetch(monkeypatch, *, exists=True, status=200, info=None):
    def fake(cert, **kw):
        return {"status": status, "exists": exists,
                "info": info if info is not None else _info(), "error": None}
    monkeypatch.setattr(P, "fetch_cert", fake)


# --------------------------------------------------------------------------
# parse_cert_html
# --------------------------------------------------------------------------

def test_parse_extracts_all_fields():
    info = P.parse_cert_html(REAL_HTML)
    assert info["cert"] == "153420191"
    assert info["grade"] == "GEM MT 10"
    assert info["subject"] == "PERONA"
    assert info["card_number"] == "077"
    assert info["year"] == "2025"
    assert info["brand"].startswith("ONE PIECE JAPANESE")


def test_parse_unescapes_html_entities():
    # &#x27; がそのまま残ると brand 突合が壊れる
    assert "'" in P.parse_cert_html(REAL_HTML)["brand"]
    assert "&#x27;" not in P.parse_cert_html(REAL_HTML)["brand"]


def test_parse_ignores_script_contents():
    # <script> 内の "Subject" を項目ラベルと誤認しない
    assert P.parse_cert_html(REAL_HTML)["subject"] == "PERONA"


def test_parse_empty_html_returns_empty():
    assert P.parse_cert_html("") == {}


def test_parse_skips_field_when_value_is_another_label():
    # テーブルが崩れて 値の位置に別ラベルが来た場合は取り込まない (誤値混入防止)
    broken = "<dl><dt>Subject</dt><dt>Card Number</dt><dd>077</dd></dl>"
    assert "subject" not in P.parse_cert_html(broken)


# --------------------------------------------------------------------------
# match_signals — 1 桁誤読の検出
# --------------------------------------------------------------------------

def test_match_all_signals_agree():
    m = P.match_signals(VISION_OK, _info())
    assert m["count"] == 4
    assert set(m["signals"]) == {"subject", "brand", "card_number", "year"}


def test_match_fails_for_different_card():
    # cert 1 桁誤読 → 実在する 別カード のページに当たった状況
    other = _info(subject="LUFFY", brand="POKEMON JAPANESE SV2A 151",
                  card_number="025", year="2023")
    m = P.match_signals(VISION_OK, other)
    assert m["count"] == 0


def test_match_brand_needs_two_token_overlap():
    # "ONE PIECE" が 1 語だけ重なる程度では brand 一致にしない (識別力が無いため)
    info = _info(brand="ONE OK ROCK MEMORABILIA", subject="ZZZ",
                 card_number="999", year="1999")
    assert "brand" not in P.match_signals(VISION_OK, info)["signals"]


def test_match_card_number_normalizes_zero_padding():
    v = dict(VISION_OK, label="", year="")
    assert "card_number" in P.match_signals(v, _info(card_number="#77"))["signals"]


def test_match_empty_vision_yields_no_signals():
    empty = {"cert": "153420191", "grade": "", "label": "", "card_number": "", "year": ""}
    assert P.match_signals(empty, _info())["count"] == 0


# --------------------------------------------------------------------------
# verify — fail-closed ゲート
# --------------------------------------------------------------------------

def test_verify_ok(monkeypatch):
    _stub_fetch(monkeypatch)
    assert P.verify(VISION_OK)["ok"] is True


def test_verify_rejects_unreadable_cert(monkeypatch):
    _stub_fetch(monkeypatch)
    r = P.verify(dict(VISION_OK, cert=""))
    assert r["ok"] is False and r["reason"] == "cert_unreadable"


def test_verify_rejects_short_cert(monkeypatch):
    _stub_fetch(monkeypatch)
    assert P.verify(dict(VISION_OK, cert="1234"))["reason"] == "cert_unreadable"


def test_verify_rejects_404(monkeypatch):
    _stub_fetch(monkeypatch, exists=False, status=404, info={})
    assert P.verify(VISION_OK)["reason"] == "cert_not_found"


def test_verify_rejects_when_psa_unreachable(monkeypatch):
    # 429 等で確認できなかった時は 「正しい」 ではなく reject (fail-closed の核心)
    _stub_fetch(monkeypatch, exists=False, status=None, info={})
    r = P.verify(VISION_OK)
    assert r["ok"] is False and r["reason"] == "psa_unreachable"


def test_verify_rejects_non_psa10(monkeypatch):
    _stub_fetch(monkeypatch, info=_info(grade="MINT 9"))
    r = P.verify(VISION_OK)
    assert r["ok"] is False and r["reason"].startswith("grade_not_psa10")


def test_verify_rejects_label_mismatch(monkeypatch):
    _stub_fetch(monkeypatch, info=_info(subject="LUFFY", brand="POKEMON SV2A 151",
                                        card_number="025", year="2023"))
    r = P.verify(VISION_OK)
    assert r["ok"] is False and r["reason"].startswith("label_mismatch")


def test_verify_min_signals_is_configurable(monkeypatch):
    # 年だけ一致 (1 系統) は既定では不合格、 min_signals=1 なら通る
    info = _info(subject="LUFFY", brand="POKEMON SV2A 151", card_number="025")
    _stub_fetch(monkeypatch, info=info)
    assert P.verify(VISION_OK)["ok"] is False
    assert P.verify(VISION_OK, min_signals=1)["ok"] is True


# --------------------------------------------------------------------------
# local_gate — 通信なしの事前ゲート (公式照会は 1 cert 1 回に抑えたい)
# --------------------------------------------------------------------------

def test_title_cert_conflict_detects_mismatch():
    # 出品者がタイトルに入れた末尾4桁 (9712) と Vision の読み (0191) が食い違う
    assert P.title_cert_conflict("153420191", "PSA10 ジュエリー・ボニー #100 9712") is True


def test_title_cert_conflict_accepts_match():
    assert P.title_cert_conflict("153429712", "PSA10 ジュエリー・ボニー #100 9712") is False


def test_title_cert_conflict_no_digits_is_not_conflict():
    # 末尾4桁を書かない出品者も普通にいる = 判定材料が無いだけ
    assert P.title_cert_conflict("153420191", "PSA10 シャンクス") is False


def test_title_cert_conflict_matches_inside_longer_number():
    # 全桁を書く出品者もいる
    assert P.title_cert_conflict("153420191", "PSA10 ルフィ 153420191") is False


def test_local_gate_ok():
    assert P.local_gate(VISION_OK, "PSA10 ペローナ 0191")["ok"] is True


def test_local_gate_rejects_unreadable_cert():
    assert P.local_gate(dict(VISION_OK, cert=""), "")["reason"] == "cert_unreadable"


def test_local_gate_rejects_non_psa10_label():
    r = P.local_gate(dict(VISION_OK, grade="MINT 9"), "")
    assert r["ok"] is False and r["reason"].startswith("grade_not_psa10")


def test_local_gate_passes_when_grade_unread():
    # グレードが読めなかっただけなら 公式照会に回す (そこで確定する)
    assert P.local_gate(dict(VISION_OK, grade=""), "")["ok"] is True


def test_local_gate_rejects_title_conflict():
    r = P.local_gate(VISION_OK, "PSA10 ジュエリー・ボニー #100 9712")
    assert r["ok"] is False and r["reason"] == "title_cert_conflict"


def test_fetch_cert_rejects_bad_format_without_network():
    r = P.fetch_cert("abc")
    assert r["exists"] is False and r["error"] == "bad_cert_format"


# --------------------------------------------------------------------------
# psa_slab_vision.parse_response
# --------------------------------------------------------------------------

def test_vision_parse_normal():
    got = V.parse_response(
        '{"cert":"153420191","grade":"GEM MT 10","label":"2025 ONE PIECE PERONA",'
        '"card_number":"077","year":"2025"}')
    assert got["cert"] == "153420191"
    assert got["label"] == "2025 ONE PIECE PERONA"


def test_vision_parse_none_markers_become_empty():
    got = V.parse_response('{"cert":"NONE","grade":"NONE","label":"NONE",'
                           '"card_number":"NONE","year":"NONE"}')
    assert all(v == "" for v in got.values())


def test_vision_parse_drops_bad_cert_length():
    got = V.parse_response('{"cert":"12345","grade":"GEM MT 10","label":"X",'
                           '"card_number":"1","year":"2025"}')
    assert got["cert"] == ""
    assert got["grade"] == "GEM MT 10"  # 他項目は残す


def test_vision_parse_tolerates_surrounding_text():
    got = V.parse_response('はい。 {"cert":"153420191","grade":"GEM MT 10"} 以上')
    assert got["cert"] == "153420191"


def test_vision_parse_broken_json_returns_all_empty():
    got = V.parse_response("{cert: 153420191")
    assert all(got[k] == "" for k in ("cert", "grade", "label", "card_number", "year"))
    assert got["error"] == ""  # 応答は届いている = 障害ではない


def test_vision_read_slab_without_images_skips_api():
    # 画像が無ければ API を呼ばずに空 (課金と待ちの無駄打ちを避ける)
    assert V.read_slab([])["error"] == V.ERR_NO_IMAGE
    assert V.read_slab(["not-a-url"])["error"] == V.ERR_NO_IMAGE


def test_vision_api_failure_is_reported_not_silent():
    """API 障害 (残高切れ等) を 「写真が不鮮明」 と同じ空 dict で返さない.

    2026-08-17: 残高切れ時に 12 件全部が 「ラベル不鮮明」 として静かに落ち、
    障害だと気づけなかった。 error を立てて 呼出側が別枠で数えられるようにする。
    """
    class BoomClient:
        class messages:  # noqa: N801 - anthropic client の形に合わせる
            @staticmethod
            def create(**kw):
                raise RuntimeError("credit balance is too low")

    got = V.read_slab(["https://example.com/a.jpg"], client=BoomClient())
    assert got["cert"] == ""
    assert got["error"].startswith(V.ERR_API)
    assert "RuntimeError" in got["error"]


def test_vision_no_client_is_reported():
    import scrapers.psa_slab_vision as mod

    orig = mod._get_client
    mod._get_client = lambda: None
    try:
        assert mod.read_slab(["https://example.com/a.jpg"])["error"] == V.ERR_NO_CLIENT
    finally:
        mod._get_client = orig
