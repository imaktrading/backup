# -*- coding: utf-8 -*-
"""一番くじ C:Series 固定の回帰テスト (2026-06-25)。

eBay 261055 の Series は selection型で、フル作品名(自由文字列)は drop される(既存出品が
全て Series 空だった)。C:Series は有効値 "Ichiban Kuji" 固定にし、フル作品名は説明文Specsへ。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "iMak_ichibankuji"))
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakeBayAPI")))

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


def test_series_is_fixed_ichiban_kuji():
    series, prize, cr = _inputs()
    row = gen.build_row(series, prize, cr, 109.98, None)
    assert row["C:Series"] == "Ichiban Kuji"          # フル名でなく固定(selection有効値)


def test_full_series_name_kept_in_description():
    """フル作品名は捨てず説明文Specsブロックに残す(情報ロスなし)。"""
    series, prize, cr = _inputs()
    row = gen.build_row(series, prize, cr, 109.98, None)
    desc = row["*Description"]
    assert "Bizarre Adventure" in desc                # 作品名は説明文に
