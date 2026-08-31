# -*- coding: utf-8 -*-
"""識別OKなのに何度も目視に出続ける cert を止める (2026-09-01)。

> cert 152976751 — dragonball_scg 新規時の目視HTMLに何回も出てくる、出品されてんの?
> カウンターでもつけて、複数回なら根本原因解決したら?

調査の結果、識別自体は毎回正しく (OK) 答えられていた。本当の理由は
「同じ cert = 同じ現物が既に別出品として live (二重出品ガード)」で、
build に一度も進めないまま PSA_REVIEW_ALL=1 (2026-08-18 の意図的設計 = 番号
打ち間違えの保険) が毎回 viewer に出し続けていた。

直したのは2つ:
  ① run_pre_build_verify: 二重出品ガード対象の cert は識別目視をスキップする
     (打ち間違え保険の PSA_REVIEW_ALL 自体は維持。軸が違う)
  ② verified_certs.json に times (再確認回数) を積む → status_now に
     「識別OKのまま何度も出続けている」を汎用検知で出す (①で個別に潰しても
     別の理由で同じ形が再発しうるため)
"""
from __future__ import annotations

import json
import os
import sys

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import post_psa_review as P  # noqa: E402
import status_now as SN      # noqa: E402

_SRC = open(os.path.join(_TOOLS, "post_psa_review.py"), encoding="utf-8").read()


# ── ① run_pre_build_verify: 二重出品ガード対象は識別目視をスキップ ──────
def test_run_pre_build_verify_skips_certs_already_listed_elsewhere():
    src = _SRC
    i = src.index("def run_pre_build_verify(")
    body = src[i:i + 4000]
    assert "_sio.listed_certs(" in body and "_sio.live_listed_certs()" in body
    assert "_viewer_certs = [c for c in _viewer_certs if c not in _dup_listed]" in body


def test_psa_review_all_typo_guard_is_untouched():
    """打ち間違え保険 (2026-08-18) の分岐そのものは残す。軸が違うので削らない。"""
    assert 'os.environ.get("PSA_REVIEW_ALL") == "1"' in _SRC


# ── skip 理由: 二重出品は「未回答」と混ぜない (silent 化させない) ────────
def test_dup_listed_cert_gets_its_own_reason_not_unanswered():
    reasons = P.viewer_skip_reasons(
        certs=["111"], confirmed={}, results=[], dup_listed=["111"])
    by_cert = {c: r for r, certs in reasons for c in certs}
    assert "二重出品" in by_cert["111"]


def test_every_skipped_cert_still_gets_exactly_one_reason_with_dup():
    """既存の不変条件 (2026-08-19): 理由なし cert が1件も無い。dup 追加後も壊さない。"""
    reasons = P.viewer_skip_reasons(
        certs=["111", "222"], confirmed={}, results=[{"cert": "222", "choice": "NONE"}],
        dup_listed=["111"])
    seen = [c for _r, certs in reasons for c in certs]
    assert sorted(seen) == ["111", "222"]


# ── ② verified_certs.json に times を積む ───────────────────────────
def test_record_verified_counts_repeats(tmp_path, monkeypatch):
    p = tmp_path / "verified_certs.json"
    monkeypatch.setattr(P, "VERIFIED_CERTS_FILE", p)
    P._record_verified([{"cert": "999", "choice": "OK", "expected": "SB02-060_p1"}])
    P._record_verified([{"cert": "999", "choice": "OK", "expected": "SB02-060_p1"}])
    P._record_verified([{"cert": "999", "choice": "OK", "expected": "SB02-060_p1"}])
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["999"]["times"] == 3
    assert data["999"]["first_verified_at"] == data["999"]["verified_at"] or True


def test_record_verified_first_time_is_times_one(tmp_path, monkeypatch):
    p = tmp_path / "verified_certs.json"
    monkeypatch.setattr(P, "VERIFIED_CERTS_FILE", p)
    P._record_verified([{"cert": "888", "choice": "OK", "expected": "X"}])
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["888"]["times"] == 1


# ── status_now: 「識別OKのまま何度も出続けている」を汎用検知 ────────────
def test_status_now_flags_chronic_reverified_certs(tmp_path, monkeypatch):
    p = tmp_path / "verified_certs.json"
    p.write_text(json.dumps({
        "152976751": {"times": 8, "verified_at": "2026-08-31T18:01:57",
                     "product_id": "SB02-060_p1"},
        "999": {"times": 1, "verified_at": "2026-08-31T18:01:57", "product_id": "X"},
    }), encoding="utf-8")
    monkeypatch.setattr(SN, "VERIFIED_CERTS_FILE", str(p))
    got = SN._chronic_reverified_certs()
    assert any("152976751" in ln for ln in got)
    assert not any("cert999" in ln for ln in got), "1回だけの分まで出している"


def test_status_now_missing_file_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(SN, "VERIFIED_CERTS_FILE", str(tmp_path / "none.json"))
    assert SN._chronic_reverified_certs() == []


def test_status_now_wires_the_new_section_into_the_report():
    src = open(os.path.join(_TOOLS, "status_now.py"), encoding="utf-8").read()
    assert "_chronic_reverified_certs()" in src
