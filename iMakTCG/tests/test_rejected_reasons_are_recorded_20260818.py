# -*- coding: utf-8 -*-
"""弾いた理由を必ず誰かに渡す (2026-08-18).

弾くこと自体は正しい (出品の正確性が最優先)。問題は **弾いた事実がログにしか出ず、
誰にも届かない** こと。届かないと同じカードが毎日静かに落ち続ける。

実害:
  - cert151235549 (OP06-022 ヤマト): タイトル生成の不具合で毎回 自己チェック落ち。
    人がログを読むまで誰も知らなかった
  - 画像が無くて弾いたカード: catalog に画像を足せば出せるのに、依頼が出ない

対応: どちらも改善キュー (pdca.db) に積み、次の監査で
  画像なし → catalog への集約依頼 / 自己チェック落ち → program 修正の残務
に流れるようにした。
"""
from __future__ import annotations

import io
import os

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "psa_to_csv.py")


def _src():
    return io.open(SRC, encoding="utf-8").read()


class TestNoImageBecomesACatalogRequest:
    def test_queued_where_it_is_dropped(self):
        s = _src()
        i = s.index('_drop.setdefault("NO-IMAGE"')
        assert "_queue_finding(" in s[i:i + 600], "画像なしで弾いた分を記録していない"

    def test_goes_to_the_catalog_layer(self):
        """層A = catalog への集約依頼に載る層."""
        s = _src()
        i = s.index('_drop.setdefault("NO-IMAGE"')
        block = s[i:i + 600]
        assert "images" in block and "layer=" not in block, \
            "既定 layer='A' のまま catalog 依頼に載せる"


class TestSelfCheckFailureBecomesABacklogItem:
    def test_queued_where_it_is_dropped(self):
        s = _src()
        i = s.index("この商品はCSVに含めません")
        assert "_queue_finding(" in s[i:i + 700], "自己チェック落ちを記録していない"

    def test_goes_to_the_program_layer(self):
        """catalog ではなく **こちら側の不具合**。layer='code' で program 残務に流す."""
        s = _src()
        i = s.index("この商品はCSVに含めません")
        block = s[i:i + 700]
        assert 'layer="code"' in block and 'finding_type="program_fix"' in block

    def test_deduped_by_symptom_not_by_card(self):
        """同じ症状は1件に畳む (カードごとに積むと毎日増える)."""
        s = _src()
        i = s.index("この商品はCSVに含めません")
        assert 'f"selfcheck:{str(_errors[0])[:60]}"' in s[i:i + 700]


class TestRecordingNeverBlocksListing:
    def test_failure_is_swallowed(self):
        s = _src()
        i = s.index("def _queue_finding")
        body = s[i:s.index("\ndef ", i + 1)]
        assert "except Exception" in body and "出品は継続" in body, \
            "記録の失敗で出品を止めない"

    def test_it_is_a_single_helper(self):
        """記録の作法を2か所に書かない (どちらかだけ直る事故を防ぐ)."""
        s = _src()
        assert s.count("def _queue_finding") == 1
        assert s.count("_queue_finding(") >= 3     # 定義1 + 呼出2
