# -*- coding: utf-8 -*-
"""補URL の目視待ちが減らない — 3つの漏れ (2026-09-13)。

実測 2026-09-13 05:57: 待ち行列 951本。中身を数えると:
  - **886本 (93%) は itemID が空**。夜間の書き手が入れておらず、見る側は itemID で引くので
    **一度も画面に出てこなかった**。積むだけ積んで誰も見ない状態
  - 実質ユニークは 439本。残り 512本は **毎晩の積み直し**。人が見るまで消えない待ち行列なのに
    書く側が冪等でなかった

直し方 (新しい台帳は作らない。既にある値で対応を取る):
  1. 書く側が itemID を入れる (シート B列・行番号から引ける)
  2. 見る側は itemID が空なら行番号から引き直す (既に積まれた 886本 を救う)
  3. 既に待ち行列に居る (行, URL) は積み直さない
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "iMakHQ" / "tools", ROOT / "iMakeBayAPI"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import aux_pending as AP  # noqa: E402

U1 = "https://jp.mercari.com/item/m11111111111"
U2 = "https://jp.mercari.com/item/m22222222222"


def test_already_queued_is_not_queued_again():
    rows = AP.build_rows({10: [U1, U2]}, "夜間", already={(10, U1)})
    assert [r["url"] for r in rows] == [U2]


def test_same_batch_does_not_duplicate_itself():
    rows = AP.build_rows({10: [U1, U1]}, "夜間")
    assert len(rows) == 1


def test_queue_is_idempotent(tmp_path):
    p = str(tmp_path / "q.jsonl")
    assert AP.queue({10: [U1, U2]}, "夜間", path=p) == 2
    assert AP.queue({10: [U1, U2]}, "夜間", path=p) == 0, "毎晩 積み直している"
    assert len(AP.load(p)) == 2


def test_itemid_is_recorded(tmp_path):
    p = str(tmp_path / "q.jsonl")
    AP.queue({10: [U1]}, "夜間", item_of={10: "820117786279"}, path=p)
    assert AP.load(p)[0]["itemID"] == "820117786279"


def test_existing_sheet_urls_are_not_queued(tmp_path):
    p = str(tmp_path / "q.jsonl")
    n = AP.queue({10: [U1, U2]}, "夜間", existing_by_row={10: [U1]}, path=p)
    assert n == 1 and AP.load(p)[0]["url"] == U2


def test_nightly_writer_passes_itemid():
    """書く側が itemID を渡していること (ここが抜けると 93% が見えなくなる)。"""
    import io
    src = io.open(ROOT / "iMakHQ" / "tools" / "psa_hoju_fill.py", encoding="utf-8").read()
    i = src.index('source="捨てた候補の転記(夜間)"')
    call = src[max(0, i - 500):i + 200]
    assert "item_of=item_of" in call, "夜間の積み込みが itemID を渡していない"


def test_reader_recovers_blank_itemid_from_row():
    """見る側が、itemID の空いた古い行を行番号から拾い直すこと。"""
    import io
    src = io.open(ROOT / "iMakHQ" / "tools" / "psa_hoju_fill.py", encoding="utf-8").read()
    i = src.index("for _r in aux_pending.load():")
    block = src[i:i + 500]
    assert "_r.get(\"row\")" in block, "itemID が空の行を捨てている (886本が死んだ経路)"


def test_dedupe_keeps_the_oldest_one(tmp_path):
    p = str(tmp_path / "q.jsonl")
    AP.queue({10: [U1]}, "夜間", today="2026-09-10", path=p) if False else None
    rows = (AP.build_rows({10: [U1]}, "夜間", today="2026-09-10")
            + AP.build_rows({10: [U1]}, "夜間", today="2026-09-13"))
    import json
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    assert AP.dedupe(p) == 1
    left = AP.load(p)
    assert len(left) == 1 and left[0]["date"] == "2026-09-10", "いつから待っているかが消えている"
