# -*- coding: utf-8 -*-
"""目視画面: 未回答のまま黙って送らせない (2026-08-19).

実害 (2026-08-19 の走行):
    20件のうち **6件が未回答 (choice=PENDING) のまま送信**され、その6件は静かに
    出品対象から外れた。しかも未回答だったのは画面の1〜6番目 (一番上) で、
    本人に心当たりが無かった = **気づけない作りだった**。

    画面には "12/20 回答済" とだけ出ており、
      - 残り8件が出品されないことは書かれていない
      - 1件でも答えていれば送信ボタンが押せる
      - 送信時の確認も無い

対応: 未回答の数を赤で出し、送信時に「何件が出品されなくなるか」を確認する。
      止めはしない (意図的に一部だけ送ることもあるため)。
"""
from __future__ import annotations

import io
import os
import re

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "post_psa_review.py")


def _js():
    """viewer に埋め込む JS 行だけを1つの文字列に。"""
    return io.open(SRC, encoding="utf-8").read()


class TestUnansweredIsVisible:
    def test_status_shows_the_remaining_count(self):
        s = _js()
        i = s.index("function updateStatus()")
        blk = s[i:i + 1200]
        assert "未回答 " in blk and "出品されません" in blk

    def test_status_turns_red_while_unanswered(self):
        s = _js()
        i = s.index("function updateStatus()")
        assert "#ff6b6b" in s[i:i + 1200]

    def test_all_answered_is_marked(self):
        s = _js()
        i = s.index("function updateStatus()")
        assert "全部 回答済" in s[i:i + 1200]


class TestSubmitAsksFirst:
    def test_confirm_before_submitting_with_pending(self):
        s = _js()
        i = s.index("function submitResults()")
        blk = s[i:i + 1600]
        assert "confirm(" in blk and "未回答が " in blk
        assert "return; }" in blk, "キャンセルしたら送信しない"

    def test_confirm_is_before_the_fetch(self):
        s = _js()
        i = s.index("function submitResults()")
        blk = s[i:i + 2600]
        assert blk.index("confirm(") < blk.index("fetch(")

    def test_it_lists_which_certs(self):
        """何件かだけでなく、どれが落ちるかを出す."""
        s = _js()
        i = s.index("function submitResults()")
        assert "pending.slice(0, 8)" in s[i:i + 1600]

    def test_does_not_block_intentional_partial_send(self):
        """止めない (一部だけ送ることもある)。確認するだけ."""
        s = _js()
        i = s.index("function submitResults()")
        blk = s[i:i + 1600]
        assert "disabled = (done === 0)" not in blk     # 送信可否の条件は変えない


class TestPendingStillMeansNotListed:
    def test_pending_is_the_default_for_unanswered(self):
        assert 'ANSWERS[t.cert] || {choice: "PENDING"}' in _js()

    def test_pending_never_becomes_a_listing(self):
        """fail-closed は維持 (未回答を出品に倒さない)."""
        s = _js()
        assert re.search(r"NONE/NG/PENDING.*(入れない|build しない)", s)
