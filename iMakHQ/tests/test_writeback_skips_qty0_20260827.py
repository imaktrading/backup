# -*- coding: utf-8 -*-
"""取下げた直後の行に itemID を書き戻さない (2026-08-27 の fail-OPEN)。

何が起きるか:
    `cull_end.py` は落とした行の B列を空にする。その直後に
    `itemid_writeback_audit.py --apply` が走ると、live 一覧は 2時間キャッシュなので
    **まだその出品が載っており**、「B が空なのに live に在る = 書き戻し漏れ」と
    誤判定して itemID を書き戻す。台帳が「出品中」に戻り、取下げが無かったことになる。

実測 (2026-08-27 19:42 の CULL 101件 の直後、同じキャッシュで判定):
    HIGH missing=0 / LOW missing=34 → 34件すべてが直前に落とした行、全て avail=0

なぜ運用で避けられないか:
    書き戻しは **出品くんのボタンの中の1ステップ** (監査 → 入稿 → 書戻し → 広告)。
    取下げボタンとは別に走るので、「取下げの後に書き戻さない」は人が選べない。

守ること: **avail>0 の行だけ書き戻す**。本当の漏れ (出したのに B列が空) は必ず
avail>0 なので、これで取りこぼさない。
"""
from __future__ import annotations

import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))

import itemid_writeback_audit as w                              # noqa: E402

SOLD_OUT = {"row": 187, "item_id": "358730587972", "cert": "", "sheet": "LOW"}
LIVE_OK = {"row": 2224, "item_id": "820053641904", "cert": "156684929", "sheet": "HIGH"}
LIVE = {
    "358730587972": {"avail": 0, "sku": "B0CYLNLYVH", "cur": "USD", "title": "G-Shock"},
    "820053641904": {"avail": 1, "sku": "PSA10-156684929", "cur": "USD", "title": "PSA 10"},
}


class TestQty0IsNotWrittenBack:
    def test_取下げ済_qty0_は書き戻さない(self):
        assert w.writable([SOLD_OUT], LIVE) == []

    def test_販売可能_qty1_は従来どおり書き戻す(self):
        assert w.writable([LIVE_OK], LIVE) == [LIVE_OK]

    def test_混在しても_販売可能な行だけ残る(self):
        assert w.writable([SOLD_OUT, LIVE_OK], LIVE) == [LIVE_OK]

    def test_live_に無い_itemID_は書き戻さない(self):
        assert w.writable([{"item_id": "999"}], LIVE) == []


class TestApplyUsesWritable:
    """main が `miss` ではなく `wr` (= writable の結果) を書いていること。"""

    def test_batch_update_は_wr_を回している(self):
        src = open(os.path.join(HQ, "tools", "itemid_writeback_audit.py"),
                   encoding="utf-8").read()
        assert "if wr and args.apply:" in src
        assert "for m in wr], value_input_option" in src
        assert "for m in miss], value_input_option" not in src
