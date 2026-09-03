# -*- coding: utf-8 -*-
"""パネルを開く時に残件を数え直さない (2026-08-18).

実測: 補URL の残件計算 `refresh_hoju_badge` は **18.1秒**。しかも Tk のメインスレッドで
同期に走るので、その間 画面が固まる。ホーム / 新規出品 / 既存メンテ の **どれを開いても**
同じ待ちが出ていた (書いた当時のコメントは「実測3秒」= データが増えて伸びた)。

対応:
  - 開く時は **前回値をそのまま出す** (計算しない = 一瞬)
  - 数え直すのは 🔄 を押した時と、走行が終わった後 (どうせ画面を見ていない時間)
  - 裏スレッドには回さない。過去に4回失敗している (Tk はスレッドセーフでない)
"""
from __future__ import annotations

import io
import os
import re

CP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "control_panel.py")


def _src():
    return io.open(CP, encoding="utf-8").read()


class TestOpeningDoesNotRecount:
    def test_startup_uses_the_cache(self):
        s = _src()
        assert "self.root.after(300, self.show_cached_hoju_badge)" in s
        assert "self.root.after(300, self.refresh_hoju_badge)" not in s, \
            "開いた瞬間に数え直すと 18秒 固まる"

    def test_cached_path_never_spawns_a_process(self):
        s = _src()
        i = s.index("def show_cached_hoju_badge")
        body = s[i:s.index("\n    def ", i + 1)]
        assert "subprocess" not in body and "_hoju_badge_cache()" in body

    def test_label_says_it_is_stale(self):
        """前回値だと分かるようにする (古い数字を現在値として見せない)."""
        s = _src()
        i = s.index("def show_cached_hoju_badge")
        assert "※前回値" in s[i:s.index("\n    def ", i + 1)]


class TestThereIsAWayToRecount:
    def test_button_exists_in_the_listing_panel(self):
        """このパネルには更新ボタンが無いので、数え直す口を置く."""
        s = _src()
        i = s.index("class ListingPanel:")
        body = s[i:s.index("\nclass ", i + 10)]
        assert "残件を数え直す" in body and "self._recount_hoju" in body

    def test_recount_calls_the_real_count(self):
        s = _src()
        i = s.index("def _recount_hoju")
        assert "self.refresh_hoju_badge()" in s[i:s.index("\n    def ", i + 1)]

    def test_still_recounts_after_a_run(self):
        """走行後は今までどおり数え直す (押した分だけ減ったのが見える)."""
        s = _src()
        assert re.search(r"走行後に残件を数え直す[\s\S]{0,600}self\.refresh_hoju_badge\(\)", s)


class TestNoBackgroundThreadForTk:
    def test_badge_is_not_moved_to_a_thread(self):
        """過去に4回失敗している。同じ失敗を繰り返さない."""
        s = _src()
        assert "threading.Thread(target=self.refresh_hoju_badge" not in s
        assert "threading.Thread(target=self.show_cached_hoju_badge" not in s


class TestPaintingIsSeparateFromCounting:
    def test_paint_helper_exists(self):
        s = _src()
        i = s.index("def paint_hoju_badge")
        body = s[i:s.index("\n    def ", i + 1)]
        assert "subprocess" not in body, "描画に計算を混ぜない"
        assert "b.config(" in body
