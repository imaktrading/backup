"""新規目視: 画像が無い **英語版** の候補だけ出さない。日本語版は画像が無くても出す (2026-10-05 ユーザー指示)。

ユーザー「出す必要のない英語版だけ出さないやで。日本語版は、画像がなくても出してや。画像なしのエラーが分からないから」
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import post_psa_review as P  # noqa: E402


def test_is_english_row():
    assert P.is_english_row("en", None)
    assert P.is_english_row(None, None)            # bandai_tcg_plus の英語版 (言語空・日本語名なし)
    assert not P.is_english_row("ja", None)
    assert not P.is_english_row(None, "ヴィンスモーク・レイジュ")


def test_drop_only_english_without_image(monkeypatch):
    monkeypatch.setattr(P, "_english_pids", lambda cat, pids: {"P-006_dummy"} & set(pids))
    cands = [("P-006", "https://example.com/p006.png", "Vジャンプ"),
             ("P-006_dummy", "", "Promotion Card"),                     # 英語版・画像なし → 外す
             ("OP06-068_AC01", "", "Admirable Collection vol.1")]        # 日本語版・画像なし → 残す
    assert [c[0] for c in P.drop_no_image(cands, "one_piece_tcg")] == ["P-006", "OP06-068_AC01"]


def test_real_catalog_rows():
    """実カタログ: 英語版の P-006_dummy は外れ、日本語版の OP06-068_AC01 は残る。"""
    if not P.CATALOG_DB.exists():
        return
    got = P._english_pids("one_piece_tcg", ["P-006_dummy", "OP06-068_AC01"])
    assert got == {"P-006_dummy"}


def test_empty():
    assert P.drop_no_image(None) == [] and P.drop_no_image([]) == []
