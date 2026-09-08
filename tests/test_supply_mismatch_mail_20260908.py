# -*- coding: utf-8 -*-
"""仕入元チェックの結果をメールで送る (2026-09-08 ユーザー要望)。

★0件でも送る。届かないのが「異常なし」なのか「処理が死んだ」なのか分からなくなるのが一番まずい
  (9/6 に旧トークンが切れて『ズレ0件』と嘘を出していたのと同じ形)。
"""
import os
import re
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakHQ", "tools")))

import supply_card_mismatch as S   # noqa: E402

BAT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakHQ", "tools",
                                    "run_hoju_search.bat"))


def _sus(**kw):
    d = {"itemID": "111", "cert": "c", "key": "one_piece_tcg:OP01-001", "cost": 10900,
         "cheapest": 33566, "ratio": 0.32, "title": "テスト", "urls": []}
    d.update(kw)
    return d


def test_clean_result_still_sends_a_mail():
    s, b = S.build_mail({"checked": 339, "suspects": [], "verified": False})
    assert "異常なし" in s and "339件" in s
    assert "対応は不要" in b


def test_suspects_are_listed_with_next_step():
    s, b = S.build_mail({"checked": 339, "suspects": [_sus()], "verified": False})
    assert "安く出しすぎの疑い 1件" in s
    assert "111" in b and "10,900" in b
    assert "--verify" in b            # 次にやることが本文に入っている
    assert "supply-card-mismatch" in b  # 直し方の在り処


def test_mail_says_the_flag_is_not_a_verdict():
    """①の件数を『不具合N件』と読ませない (初回は14件中0件だった)。"""
    _, b = S.build_mail({"checked": 339, "suspects": [_sus()], "verified": False})
    assert "『不具合』とは言えません" in b


def test_verified_result_reports_real_mismatches():
    sus = _sus(mismatch=1, checked=[{"url": "https://x/1", "verdict": "★不一致",
                                     "no": "OP07-033", "title": "別カード"}])
    s, b = S.build_mail({"checked": 339, "suspects": [sus], "verified": True})
    assert "安く出しすぎ 1件" in s
    assert "OP07-033" in b


def test_verified_and_clean_says_so():
    s, _ = S.build_mail({"checked": 339, "suspects": [_sus(mismatch=0, checked=[])],
                         "verified": True})
    assert "なし" in s


def test_long_list_is_truncated():
    """一覧は長くしない (読む側の時間を食う)。"""
    _, b = S.build_mail({"checked": 400, "suspects": [_sus(itemID=str(i)) for i in range(30)],
                         "verified": False})
    assert "他 15件" in b


def test_nightly_batch_sends_the_mail():
    txt = open(BAT, encoding="utf-8", errors="replace").read()
    m = re.search(r"supply_card_mismatch\.py([^\r\n]*)", txt)
    assert m, "夜間バッチに検査が入っていない"
    assert "--mail" in m.group(1), "夜間はメールまで送る (見に行かないと分からない形にしない)"


def test_price_drop_is_reported_first():
    """値下がりは『今日 起きた変化』なので、標準の一覧より先に出す。

    事故はいつも「別カードの安い供給が入った瞬間」に起きる。
    """
    s, b = S.build_mail({"checked": 336, "stat": {"listed": 463, "no_market": 127},
                         "suspects": [], "verified": False,
                         "drops": [{"itemID": "820049712142", "prev": 75000, "now": 15000,
                                    "ratio": 0.2, "title": "ルフィ DAY プロモ"}]})
    assert "値下がり 1件" in s
    assert b.startswith("★今日、仕入値が大きく下がった")
    assert "75,000円 → 15,000円" in b


def test_no_drop_no_section():
    _, b = S.build_mail({"checked": 336, "stat": {"listed": 463}, "suspects": [],
                         "verified": False, "drops": []})
    assert "値下がり" not in b
    assert "対応は不要" in b
