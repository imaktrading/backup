# -*- coding: utf-8 -*-
"""補URL の在庫確認に時間の上限を付ける (2026-09-12・ユーザーGO)。

実害: 9/08 に「補URLに書く直前に在庫を確かめる」を入れたが、外側 (control_panel) の
待ち時間は 120秒 のままだった。中は 1URL あたり 3秒 待って全件開くので、9/12 実測の
74本 では 5〜8分 かかる = **構造的に終われない**。
結果、補URL が **1本も足されないまま**「失敗(続行)」で毎回流れていた
(仕入元が今ゼロの出品への補充 11本 を含む)。2026-08-19 の「外側が先に殺す」と同じ形。

直し方も 8/19 と同じ: 内側に上限 → 外はその分 + 余裕。
上限に達したら残りは **確認せず通す** (driver が起きない時と同じ fail-open)。
補URL が1本も入らない方が危険だから。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "iMakHQ" / "tools", ROOT / "iMakeBayAPI"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import hoju_url_from_dupes as H  # noqa: E402


class _Clock:
    """呼ばれるたびに step 秒 進む時計 (本物の待ち時間を使わない)."""

    def __init__(self, step):
        self.t, self.step = 0.0, step

    def __call__(self):
        self.t += self.step
        return self.t


def test_budget_stops_and_keeps_the_rest(monkeypatch):
    """上限に達したら残りは落とさず通す。件数が減らないこと。"""
    urls = [f"https://jp.mercari.com/item/m{i:011d}" for i in range(50)]

    class _Drv:
        page_source = "<html>買えます</html>"

        def get(self, u):
            pass

        def quit(self):
            pass

    fake = type(sys)("mercari_psa_resource")
    fake.new_scrape_driver = lambda: _Drv()
    fake.buyable_from_detail = lambda html: True
    fake.load_not_buyable = lambda: {}
    fake.remember_not_buyable = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "mercari_psa_resource", fake)
    monkeypatch.setattr(H.time if hasattr(H, "time") else sys.modules["time"], "sleep",
                        lambda *_a: None, raising=False)

    alive, dead = H.verify_alive(urls, verbose=False, budget_sec=10, now=_Clock(1.0))
    assert dead == []
    assert len(alive) == len(urls), "時間切れで URL が消えている (補URLが痩せる)"


def test_no_budget_overrun_means_all_checked(monkeypatch):
    urls = ["https://jp.mercari.com/item/m00000000001"]

    class _Drv:
        page_source = "<html/>"

        def get(self, u):
            pass

        def quit(self):
            pass

    fake = type(sys)("mercari_psa_resource")
    fake.new_scrape_driver = lambda: _Drv()
    fake.buyable_from_detail = lambda html: False
    fake.load_not_buyable = lambda: {}
    fake.remember_not_buyable = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "mercari_psa_resource", fake)
    monkeypatch.setattr(sys.modules["time"], "sleep", lambda *_a: None, raising=False)

    alive, dead = H.verify_alive(urls, verbose=False, budget_sec=999, now=_Clock(0.1))
    assert alive == [] and len(dead) == 1, "確認できた分は今までどおり落とす"


def test_outer_timeout_is_wider_than_inner_budget():
    """外が先に死ぬと、確認した意味が丸ごと消える (今回の事故そのもの)。"""
    import io
    import re
    src = io.open(ROOT / "iMakHQ" / "control_panel.py", encoding="utf-8").read()
    i = src.index("hoju_url_from_dupes.py")
    # 説明文 (#) は数えない。動くコードの timeout= だけ見る
    nl = chr(10)
    code = nl.join(ln for ln in src[i:i + 900].split(nl)
                   if not ln.strip().startswith("#"))
    outer = int(re.search(r"timeout=(\d+)", code).group(1))
    assert outer > H.VERIFY_BUDGET_SEC, f"外 {outer}秒 <= 内 {H.VERIFY_BUDGET_SEC}秒"


def test_dangerous_urls_are_checked_first():
    """時間に上限がある以上、**仕入元が今ゼロ**の出品に足す URL から確かめる。"""
    import io
    src = io.open(ROOT / "iMakHQ" / "tools" / "hoju_url_from_dupes.py", encoding="utf-8").read()
    i = src.index("_cands = ")
    line = src[i:src.index("\n", i)]
    assert "_urgent" in line, "危ない順に並べ替えていない (アルファベット順のまま)"
