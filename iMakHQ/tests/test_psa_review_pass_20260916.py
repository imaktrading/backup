# -*- coding: utf-8 -*-
"""PSA 目視の「一致・見送り」(2026-09-16 ユーザー要望)。

> 出品時の目視HTMLだけど、出品前提で作られているけど、仕入元が複数枚とかも混じってるケースがある。
> 見送りボタンと理由があった方がいいのでは？
> 理由によって、永久に出さないやで。
> 仕入元が売切は、入れといて。タイムラグあるし。永久に出さないで。
  (監視くんが気づくまでラグがあるので、目視の時に人が見つけた売り切れの方が確か)

それまでは「合ってる / 違う / 該当なし」しかなく、識別は合っているのに出さない時に
「該当なし」(= カタログへの宿題) を押すしかなかった。理由が混ざるので分けた。
"""
import datetime
import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))

import post_psa_review as R  # noqa: E402

NOW = datetime.datetime(2026, 9, 16, 12, 0, 0)


def test_reasons_are_the_five_the_user_decided():
    keys = [k for k, _l, _d in R.PASS_REASONS]
    assert keys == ["bundle", "seller", "gone", "price", "other"]
    days = {k: d for k, _l, d in R.PASS_REASONS}
    assert days["gone"] == 0            # 売り切れは永久 (監視くんの気づきにはラグがある)


def test_forever_reasons_never_come_back():
    """まとめ売り / 出品者が不安 は 日数 0 = 永久に出さない。"""
    passed = {"111": {"at": "2026-01-01T00:00:00", "reason": "bundle"},
              "222": {"at": "2026-01-01T00:00:00", "reason": "seller"},
              "333": {"at": "2026-01-01T00:00:00", "reason": "gone"}}
    assert set(R.passed_active(passed, NOW)) == {"111", "222", "333"}


def test_temporary_reasons_come_back_after_the_days():
    """値段は変わるので、30日たったら また目視に出す。"""
    old = (NOW - datetime.timedelta(days=31)).isoformat(timespec="seconds")
    new = (NOW - datetime.timedelta(days=5)).isoformat(timespec="seconds")
    passed = {"old": {"at": old, "reason": "price"}, "new": {"at": new, "reason": "price"}}
    assert set(R.passed_active(passed, NOW)) == {"new"}


def test_reason_is_required_to_record():
    """理由なしの見送りは台帳に入れない (why が消えると後で戻せない)。"""
    got = R.record_passed([{"cert": "1", "choice": "PASS"},
                           {"cert": "2", "choice": "PASS", "reason": "bundle"},
                           {"cert": "3", "choice": "OK", "reason": "bundle"}], {}, now="2026-09-16T12:00:00")
    assert list(got) == ["2"]
    assert got["2"]["label"].startswith("仕入元が複数枚")


def test_viewer_drops_passed_certs_and_says_so():
    src = open(os.path.join(HQ, "tools", "post_psa_review.py"), encoding="utf-8").read()
    assert "_passed = passed_active(load_passed())" in src
    assert "一致・見送り済 → 目視に出しません" in src
    assert "_record_passed_from_results(data)" in src
    assert 'btn_{cert}_PASS' in src and "見送りの理由を選ぶ" in src
