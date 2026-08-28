# -*- coding: utf-8 -*-
"""PSA に写真が無い cert の扱い (2026-08-28)。

依頼書: hq/requests/2026-08-28_act_code_proposals_tcg.md 提案1
  - 枠を選ぶ前に落とす (照合できないので目視に出しても必ず「該当なし」になる)
  - **program修正依頼にはしない** (PSA 側の事情で直すコードが無い)
  - 目視画面には「写真が無い」と出す (黙って列を出さないと人が別絵柄と誤判断する)
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "iMakTCG"))

import csv_auditor as A                                            # noqa: E402
import post_psa_review as R                                        # noqa: E402


def _tcg():
    import psa_to_csv as T
    return T


# ---- 抽出段: 写真ゼロの cert を落とす ----

def test_no_photo_cert_is_dropped():
    T = _tcg()
    cache = {"63355290": {"Subject": "SUICUNE", "CardImageUrl": None},
             "151301749": {"Subject": "LUFFY", "CardImageUrl": "http://x/a.jpg"}}
    got = T.no_psa_photo_certs(["63355290", "151301749"], cache, substitute_fn=lambda c: "")
    assert list(got) == ["63355290"]


def test_cert_with_only_back_photo_is_kept():
    T = _tcg()
    cache = {"1": {"Subject": "X", "CardImageUrlBack": "http://x/b.jpg"}}
    assert T.no_psa_photo_certs(["1"], cache, substitute_fn=lambda c: "") == {}


def test_cert_with_substitute_image_is_kept():
    """代替画像 (psa_image_override.json) が在る cert は写真が手に入るので落とさない。"""
    T = _tcg()
    cache = {"102629645": {"Subject": "BOA", "CardImageUrl": None}}
    got = T.no_psa_photo_certs(["102629645"], cache,
                               substitute_fn=lambda c: "149777037")
    assert got == {}


def test_unknown_cert_is_not_dropped():
    """cache に無い = 判定不能。落とさない (fail-closed の向き)。"""
    T = _tcg()
    assert T.no_psa_photo_certs(["999"], {}, substitute_fn=lambda c: "") == {}


# ---- 監査: program修正依頼にしない ----

def test_no_photo_finding_is_not_program_fix():
    disp = A.classify_finding("ERROR", A.NO_PSA_PHOTO_MSG)
    assert disp == A.REPORT_PROGRAM, "既定は従来どおり program"
    got = A.no_psa_photo_disposition(A.NO_PSA_PHOTO_MSG, disp,
                                     {"Subject": "SUICUNE", "CardImageUrl": None})
    assert got == A.EXCLUDE_FAILCLOSED
    assert got in A._EXCLUDING, "出品は止めたまま (写真無しでは出せない)"


def test_no_photo_finding_stays_program_when_psa_has_photo():
    """PSA には写真が在るのに CSV に載っていない = 本当に生成バグ → 従来どおり program。"""
    disp = A.classify_finding("ERROR", A.NO_PSA_PHOTO_MSG)
    got = A.no_psa_photo_disposition(A.NO_PSA_PHOTO_MSG, disp,
                                     {"CardImageUrl": "http://x/a.jpg"})
    assert got == A.REPORT_PROGRAM


def test_no_photo_finding_stays_program_when_cache_missing():
    disp = A.classify_finding("ERROR", A.NO_PSA_PHOTO_MSG)
    assert A.no_psa_photo_disposition(A.NO_PSA_PHOTO_MSG, disp, None) == A.REPORT_PROGRAM


def test_other_findings_untouched():
    disp = A.classify_finding("ERROR", "カテゴリが違います")
    assert A.no_psa_photo_disposition("カテゴリが違います", disp, {}) == disp


# ---- 目視画面: 写真が無いことを出す ----

def test_viewer_shows_no_photo_column():
    t = {"cert": "63355290", "supply_image_url": "http://x/s.jpg", "cert_image_url": "",
         "cert_image_url_back": "", "csv_expected": "S4a-323"}
    labels = [lb for lb, _ in R.confirm_columns(t, "http://x/c.jpg")]
    assert any("写真なし" in lb for lb in labels), labels


def test_viewer_no_photo_column_renders_text_not_broken_img():
    cell = R._confirm_cell("")
    assert "<img" not in cell
    assert "PSA に写真が無い" in cell


def test_empty_target_has_no_columns():
    """cert が無い = 目視対象ですらない → 「写真なし」も出さない。"""
    assert R.confirm_columns({}, "") == []


def test_viewer_keeps_normal_columns_when_photo_exists():
    t = {"cert": "151301749", "supply_image_url": "http://x/s.jpg",
         "cert_image_url": "http://x/p.jpg",
         "cert_image_url_back": "", "csv_expected": "S4a-323"}
    labels = [lb for lb, _ in R.confirm_columns(t, "http://x/c.jpg")]
    assert not any("写真なし" in lb for lb in labels)
    assert "📋 PSA 表" in labels
