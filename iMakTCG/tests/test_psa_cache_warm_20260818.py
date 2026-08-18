# -*- coding: utf-8 -*-
"""PSA データの先貯め (2026-08-18).

なぜ:
    出品くんの前段 (参入しないゲーム / catalog未収録 / 画像なし / 既に出品中) は
    判定に PSA データが要るのに、PSA を取るのは枠を選んだ後。だから新しいカードは
    判定できず、枠を使ってから後段で消える。
    実測 2026-08-18: 候補 912件中 PSA データ有は 235件 (25%)。20枠のうち6枠が
    「既に出品中」で消え、しかも **人が目視した後** に消えた。

守ること:
    1. 対象は「まだデータが無い cert」だけ (重複・空を除く / 順序は保つ)
    2. Cloudflare に当たったら **やめる**。夜間は人が突破できない。叩き続けない
    3. profile は1プロセス排他。起動できなければ **奪わずに終わる**
    4. 走った証跡を残す (画面だけだと止まっていても気づけない)
"""
from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from psa_cache_warm import DEFAULT_LIMIT, pending_certs  # noqa: E402

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "psa_cache_warm.py")


def _src():
    return io.open(SRC, encoding="utf-8").read()


class TestPendingSelection:
    def test_only_uncached(self):
        cached = {"111", "333"}
        assert pending_certs(["111", "222", "333", "444"],
                             lambda c: c in cached) == ["222", "444"]

    def test_dedupes_and_drops_blanks(self):
        assert pending_certs(["111", "111", "", None, " 222 "],
                             lambda c: False) == ["111", "222"]

    def test_order_is_preserved(self):
        got = pending_certs(["9", "3", "7"], lambda c: False)
        assert got == ["9", "3", "7"], "順序を変えると毎晩の続きが再現できない"

    def test_all_cached_is_empty(self):
        assert pending_certs(["1", "2"], lambda c: True) == []


class TestRateAndSafety:
    def test_default_limit_is_modest(self):
        """1日12件しか触っていなかったので、一気に上げない."""
        assert 10 <= DEFAULT_LIMIT <= 60

    def test_stops_on_cloudflare(self):
        s = _src()
        assert 'stopped = "cloudflare"' in s and "break" in s, \
            "Cloudflare で止めないと夜通し叩き続ける (BAN が一番高くつく)"

    def test_does_not_steal_the_profile(self):
        s = _src()
        assert "skip-profile-busy" in s, \
            "profile は1プロセス排他。出品くんが動いていたら見送ること"

    def test_reuses_the_existing_fetcher(self):
        """15秒待ち・CF retry・両cache書込を持っているのは get_psa_data 側。複製しない."""
        s = _src()
        assert "P.get_psa_data(driver, cert)" in s
        assert "time.sleep" not in s, "待ち時間をここで定義し直さない"

    def test_leaves_a_record(self):
        s = _src()
        assert "_record(" in s and "psa_cache_warm_last.json" in s

    def test_dry_run_does_not_open_a_browser(self):
        s = _src()
        assert s.index("if a.dry_run") < s.index("import undetected_chromedriver")
