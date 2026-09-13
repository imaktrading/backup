# -*- coding: utf-8 -*-
"""Tシャツの 🤖自動 は **先に目視** してから生成する (2026-09-13)。

ユーザー「目視が入るから、自動で動かそう。件数CAPは？」→ PSA の 🤖自動 と同じ形:
  PSA_VERIFY_BEFORE_BUILD=1 / PSA_BATCH_LIMIT=20  ⇔  UT_IDENTIFY_BEFORE_BUILD=1 / UT_BATCH_LIMIT=20

- 目視は **新しく出す候補だけ** (出品済みの KEY 埋めは手動ボタン側)。
  KEY 埋め79件が先頭に並ぶので、混ぜると最初の数回は出品0件になる
- 並びは売れ筋順 (ut_demand_words.json)
- 値は env で注入。生成側に「自動なら〜」の分岐を作らない
"""
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "iMakHQ" / "tools", ROOT / "iMakMercari", ROOT / "iMakeBayAPI"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import ut_identify as U  # noqa: E402


def _r(item_id=""):
    r = [""] * 40
    r[0] = "https://jp.mercari.com/item/m12345678901"
    r[1] = item_id
    return r


def test_only_new_drops_listed_rows():
    rows = [(2, _r(), "tab"),
            (1000005, _r("358000000001"), "sheet"),   # 出品済み = KEY 埋め
            (1000006, _r(), "sheet")]                  # まだ出していない
    assert [t[0] for t in U.only_new(rows)] == [2, 1000006]


def test_auto_button_injects_the_same_shape_as_psa():
    src = io.open(ROOT / "iMakHQ" / "control_panel.py", encoding="utf-8").read()
    i = src.index('"category": "Tシャツ", "type": "auto"')
    blk = src[i:src.index("    },\n", i)]
    assert '"UT_IDENTIFY_BEFORE_BUILD": "1"' in blk
    assert '"UT_BATCH_LIMIT": "20"' in blk


def test_generator_runs_identify_first_and_caps():
    src = io.open(ROOT / "iMakMercari" / "tshirt_listing.py", encoding="utf-8").read()
    i = src.index("def main():")
    body = src[i:]
    a = body.index('UT_IDENTIFY_BEFORE_BUILD')
    b = body.index("get_listing_targets()")
    assert a < b, "目視より先に対象を読んでいる (目視で足した行が今回の生成に入らない)"
    assert '"--new-only"' in body[a:b]
    assert "targets = targets[:_batch]" in body
