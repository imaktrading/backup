# -*- coding: utf-8 -*-
"""一番くじの補URL補充を PSA と同じ1画面にする (2026-08-22 ユーザー指示).

「既存と新規でいいとこどりしろ。基本、PSAとは同じ作りで」

いいとこ取りの中身:
  ロジック = 既存のまま (キーワード検索 → 新品/送料込み/セラー評価で絞る →
             夜間キャッシュ → 見送りのクールダウン → 他出品が使用中のURLを掴まない)
  画面     = PSA の確証UI (`psa_resource_confirm.restock_confirm`)

★従来は identify → expand の2段 (1つ選んで、それを種に画像検索) で人が2回見ていた。
  補URLは複数本 貯めるものなので、1画面で複数選ぶ方が合う。
  画像検索の段は落とす (ユーザー判断 2026-08-22)。
"""
from __future__ import annotations

import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))

import ichibankuji_restock as R                                 # noqa: E402


class TestPSAScreen:
    def test_PSAの確証UIを使う(self):
        assert "restock_confirm" in inspect.getsource(R.pass_hoju_psa_style)

    def test_自前のHTMLは使わない(self):
        src = inspect.getsource(R.pass_hoju_psa_style)
        assert "build_identify_html" not in src and "serve_and_collect" not in src

    def test_画像検索の段は呼ばない(self):
        """★1画面に統一した (ユーザー判断)。2段だと人が2回見ることになる."""
        assert "pass_expand" not in inspect.getsource(R.pass_hoju_psa_style)


class TestKeepsExistingLogic:
    def test_候補は既存の取り方(self):
        """新品/送料込み/セラー評価の絞り込みと夜間キャッシュは既存のまま."""
        assert "_identify_scrape" in inspect.getsource(R.pass_hoju_psa_style)

    def test_書込は既存の口(self):
        """既存の補URLを消さない / 空き枠だけ / 他出品が使用中のURLは掴まない."""
        assert "plan_live_aux" in inspect.getsource(R._write_supplies_live)

    def test_見送りはクールダウンに入れる(self):
        """★同じ候補を翌日また見せない (既存の作法)."""
        assert "_add_cooldown" in inspect.getsource(R.pass_hoju_psa_style)


class TestFailClosed:
    def test_現物が見えない行は目視に出さない(self):
        src = inspect.getsource(R.pass_hoju_psa_style)
        assert "not cands or not ref" in src

    def test_未確定なら書かない(self):
        src = inspect.getsource(R.pass_hoju_psa_style)
        assert "未確定" in src and "選ばれた候補が0件" in src

    def test_URL共有ガードを組めなければ書込を中止(self):
        """判定できないまま書くと、2出品が同じ仕入元を掴む (キャンセル→Defect)."""
        assert "書込を中止" in inspect.getsource(R._write_supplies_live)


class TestButton:
    def test_hojuモードが新しい画面を呼ぶ(self):
        import io
        src = io.open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "tools", "ichibankuji_restock.py"),
            encoding="utf-8").read()
        i = src.index('elif mode == "hoju":')
        body = src[i:i + 600]
        assert "pass_hoju_psa_style" in body
        assert "pass_expand" not in body


def test_件数を数えられる():
    """パネルのヒント用。母数ではなく『押して出る件数』."""
    assert hasattr(R, "count_workload")
    src = inspect.getsource(R.count_workload)
    assert "_identify_cache_fresh" in src
