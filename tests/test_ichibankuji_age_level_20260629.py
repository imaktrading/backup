# -*- coding: utf-8 -*-
"""一番くじ 新規出品の Age Level=15+ 回帰テスト (2026-06-29 ユーザー指示)。

Bandai 一番くじ公式=対象年齢15才以上。CPSC(2026-07-08 eFiling)で児童製品(≤12歳)扱いを
外すため C:Age Level="15+" を出力する。※カテゴリ261055に Age Level の公式aspectは無く
カスタム自由文字列として記載(非児童製品の明示)。
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMak_ichibankuji")))
import ichibankuji_to_csv as gen  # noqa: E402


def _inputs():
    series = {"series_name": "一番くじ ジョジョの奇妙な冒険", "release_year": "2026",
              "price_jpy": "850", "main_image": "", "url": "",
              "mercari_url": "https://jp.mercari.com/item/m1", "prizes": []}
    prize = {"prize": "B賞", "name": "クレイジーダイヤモンド", "size_cm": "22"}
    cr = {"is_figure": True, "title": "Ichiban Kuji JoJo's B Prize Crazy Diamond Figure New",
          "franchise": "JoJo's Bizarre Adventure", "tv_show": "Jojo's Bizarre Adventure",
          "character": "Crazy Diamond", "figure_type": "Masterlise", "year": "2026",
          "item_height_in": "8.7", "item_height_cm": "22", "prize_en": "B Prize",
          "series_name_en": "Ichiban Kuji JoJo's Bizarre Adventure Diamond is Unbreakable",
          "animation_studio": "Does Not Apply"}
    return series, prize, cr


def test_age_level_is_15_plus():
    series, prize, cr = _inputs()
    row = gen.build_row(series, prize, cr, 109.98, None)
    assert row["C:Age Level"] == "15+"   # 非児童製品=CPSC対応 (Bandai公式15+)
