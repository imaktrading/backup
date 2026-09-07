"""①(PSA再仕入れ 照合) のヒント件数は、押した時に実際に出る件数と同じ規則で数える (2026-09-07).

> ①はさっきやって、１やで。/ ヒントテキストの件数見て、仕事の段取りを組んでいるんだから、正確に出せよ

ヒント側だけ `_review_skip_iids(rows, today)` (= 日数で復活する数え方) を使っており、
ボタン本体 (:880 は today を渡さない = レビュー済は再表示しない) と食い違っていた。
実害: レビュー済で二度と出ない1件を「1件あります」と出し続け、押すと「照合対象なし」。
"""
import io
import os
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import psa_resource_gate as PG  # noqa: E402

HDR = ["itemID", "card_no", "title", "理由", "日付", "ebay_url"]


def test_review_skipped_stays_skipped_regardless_of_days():
    rows = [HDR, ["111", "OP13-120", "t", "違う", "2026-01-01", "u"]]
    assert PG._review_skip_iids(rows) == {"111"}, "日付が古くても再表示しない (本体の規則)"


def test_hint_uses_the_same_call_as_the_button():
    """数える側とボタン側が同じ呼び方であること (片方だけ変わると また食い違う)."""
    src = io.open(os.path.join(TOOLS, "psa_resource_gate.py"), encoding="utf-8").read()
    i = src.index("def count_workload(")
    body = src[i:src.index("\ndef ", i + 10)]
    assert "_review_skip_iids(read_tab(REVIEW_SKIP_TAB))" in body
    assert "_review_skip_iids(read_tab(REVIEW_SKIP_TAB), t)" not in body, (
        "ヒントだけ cooldown で復活させない")
