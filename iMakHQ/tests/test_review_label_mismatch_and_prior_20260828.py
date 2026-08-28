# -*- coding: utf-8 -*-
"""目視画面: ラベルと違う候補に印を付ける / 既決は前回の答えを既定選択で下に (2026-08-28)。

依頼2件を1回で直したもの (同じ画面を2回いじらない):
  - hq/requests/2026-08-27_flag_candidates_whose_set_contradicts_psa_label_response.md
    cert151301749 は PSA ラベルが `3RD ANNIVERSARY SET` なのに候補が
    `OP12-079` (BOOSTER PACK -LEGACY OF THE MASTER-) で、文字は食い違っているのに
    画面上は同じ重みで並んでいた。⚠ を出すだけで **候補からは消さない**。
  - hq/requests/2026-08-27_build_review_dedup_verified_and_presort_response.md
    既決の cert が毎回まっさらで聞き直されていた。既定では出さない (split_verified)。
    再確認 (PSA_REVIEW_ALL=1) で出す時は前回の答えを既定選択にして下に置く。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "tools")))

import post_psa_review as pr      # noqa: E402

# cert151301749 の実データ (2026-08-28 実機で取得)
BRAND_3RD = "ONE PIECE JAPANESE 3RD ANNIVERSARY SET"
CAND_HIT = ("OP12-079_AN03", "", "3rd ANNIVERSARY SET")
CAND_MISS = ("OP12-079", "", "BOOSTER PACK -LEGACY OF THE MASTER- [OP-12]")


def _target(**kw):
    t = {"cert": "151301749", "category": "one_piece_tcg", "brand": BRAND_3RD,
         "subject": "LUFFY/KING OF PIRATES", "card_number": "079",
         "csv_expected": "OP12-079_AN03", "supply_image_url": "",
         "cert_image_url": "", "cert_image_url_back": "",
         "candidates": [CAND_MISS, CAND_HIT], "is_promo": False, "promo_proposed": ""}
    t.update(kw)
    return t


# ------------------------------------------------ ラベルとセット名の食い違い

def test_contradicting_set_is_flagged():
    assert pr.set_matches_psa_label(BRAND_3RD, CAND_MISS[2]) is False


def test_matching_set_is_not_flagged():
    assert pr.set_matches_psa_label(BRAND_3RD, CAND_HIT[2]) is True


def test_japanese_only_set_name_is_undecidable():
    """日本語だけのセット名は英字で突き合わせられない → 印を出さない (狼少年にしない)。"""
    assert pr.set_matches_psa_label(BRAND_3RD, "限定商品収録カード") is None


def test_generic_only_set_name_is_undecidable():
    assert pr.set_matches_psa_label(BRAND_3RD, "Other Product Card") is None


def test_generic_only_brand_is_undecidable():
    """`ONE PIECE JAPANESE PROMOS` は何も言っていない → 全候補に印を出さない。"""
    assert pr.set_matches_psa_label("ONE PIECE JAPANESE PROMOS",
                                    "EXTRA BOOSTER -Anime 25th Collection- [EB-02]") is None


def test_shared_generic_word_is_not_a_match():
    """`BOOSTER` のような どこにでも在る語で「一致」と言わない。"""
    assert pr.set_matches_psa_label(
        "ONE PIECE JAPANESE PREMIUM BOOSTER -ONE PIECE CARD THE BEST- STORAGE BOX SET",
        "EXTRA BOOSTER -ONE PIECE HEROINES EDITION- [EB-03]") is False


def test_real_storage_box_set_matches():
    assert pr.set_matches_psa_label(
        "ONE PIECE JAPANESE PREMIUM BOOSTER -ONE PIECE CARD THE BEST- STORAGE BOX SET",
        "プレミアムブースター ONE PIECE CARD THE BEST ストレージボックスセット") is True


def test_html_marks_the_contradicting_candidate_and_keeps_it(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "HTML_OUTPUT", tmp_path / "review.html")
    monkeypatch.setattr(pr, "_find_expected_image", lambda *a, **k: "")
    pr._generate_html([_target()])
    html = (tmp_path / "review.html").read_text(encoding="utf-8")
    assert html.count("⚠ ラベルと違う商品") == 1, "食い違う候補だけに印"
    assert "OP12-079_AN03" in html and ">OP12-079<" in html, "候補は消さない"


# ------------------------------------------------ 既決の扱い (再掲を止める)

VC = {"152976751": {"choice": "OK", "product_id": "SB02-060_p1",
                    "verified_at": "2026-07-14T10:00:00"}}


def test_decided_cert_does_not_reach_the_viewer():
    """既定では既決 cert を目視画面に出さない (再掲7件の本体)。"""
    confirmed, viewer = pr.split_verified(["152976751", "999999999"], VC)
    assert confirmed == {"152976751": "SB02-060_p1"}
    assert viewer == ["999999999"]


def test_prior_choices_reads_the_previous_answer():
    got = pr.prior_choices(["152976751", "999999999"], VC)
    assert got == {"152976751": {"choice": "OK", "product_id": "SB02-060_p1",
                                 "verified_at": "2026-07-14"}}


def test_prior_answer_prefers_a_candidate_row():
    t = _target(cert="152976751", csv_expected="SB02-060",
                candidates=[("SB02-060", "", ""), ("SB02-060_p1", "", "")])
    got = pr.prior_answer_for(t, pr.prior_choices(["152976751"], VC))
    assert got["choice"] == "CHOSEN" and got["product_id"] == "SB02-060_p1"


def test_prior_answer_falls_back_to_ok_on_expected():
    t = _target(cert="152976751", csv_expected="SB02-060_p1",
                candidates=[("SB02-060", "", "")])
    got = pr.prior_answer_for(t, pr.prior_choices(["152976751"], VC))
    assert got["choice"] == "OK"


def test_prior_answer_is_none_when_pid_is_unknown_here():
    """前回の pid が今回の候補にも期待値にも無いなら既定選択にしない (fail-closed)。"""
    t = _target(cert="152976751", csv_expected="OP12-079_AN03")
    assert pr.prior_answer_for(t, pr.prior_choices(["152976751"], VC)) is None


def test_decided_targets_go_to_the_bottom():
    first = _target(cert="A")
    decided = _target(cert="B", prior_choice={"choice": "OK", "product_id": "X"})
    fresh = _target(cert="C")
    assert [t["cert"] for t in pr.sort_targets_prior_last([decided, first, fresh])] \
        == ["A", "C", "B"], "初見が上・既決が下 (同じ組の中では元の順)"


def test_html_preselects_the_previous_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "HTML_OUTPUT", tmp_path / "review.html")
    monkeypatch.setattr(pr, "_find_expected_image", lambda *a, **k: "")
    t = _target(prior_choice={"choice": "CHOSEN", "product_id": "OP12-079_AN03",
                              "verified_at": "2026-07-14"})
    pr._generate_html([t])
    html = (tmp_path / "review.html").read_text(encoding="utf-8")
    assert "前に決めた答え" in html
    assert '"OP12-079_AN03"' in html and "var PRIOR" in html
    assert 'selectCand(pc, p.product_id)' in html, "既定選択を復元する経路が在る"


def test_html_has_no_prior_block_for_fresh_targets(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "HTML_OUTPUT", tmp_path / "review.html")
    monkeypatch.setattr(pr, "_find_expected_image", lambda *a, **k: "")
    pr._generate_html([_target()])
    html = (tmp_path / "review.html").read_text(encoding="utf-8")
    assert "前に決めた答え" not in html
    assert "var PRIOR = {};" in html
