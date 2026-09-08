"""①(PSA再仕入れ 照合) のヒント件数は、押した時に実際に出る件数と同じ規則で数える (2026-09-07).

> ①はさっきやって、１やで。/ ヒントテキストの件数見て、仕事の段取りを組んでいるんだから、正確に出せよ

★2026-09-08 訂正。9/07 はヒントを「cooldown を見ない側」に合わせたが、**合わせる先を
間違えていた**。本体はレビュー済を2か所で読む:
    :880  探索ループの新規カウント … cooldown を見ない
    :1400 HTMLに何を出すかの判定   … cooldown で復活させる  ← 画面の件数はこちら
9/07 の実害 (1件と出るのに押すと0件) は復活のせいではなく、**仕入元の在庫が無い行を
混ぜていた**ことが原因で、それは 9/05 の supply_wait 差引で解決済だった。
実測 2026-09-08: 台帳8行のうち7件が本体では復活し、ヒント1件に対し HTML は2件出た。
よってヒントは **:1400 と同じ (today を渡す)** で数える。
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


def test_review_skip_without_today_returns_all_rows():
    """today を渡さない呼び方は「全行を伏せる」(API の素の挙動)。"""
    rows = [HDR, ["111", "OP13-120", "t", "違う", "2026-01-01", "u"]]
    assert PG._review_skip_iids(rows) == {"111"}


def test_review_skip_with_today_revives_expired_rows():
    """today を渡すと cooldown 満了は復活する = HTMLに出る側の規則。"""
    rows = [HDR, ["111", "OP13-120", "t", "違う", "2026-01-01", "u"]]
    assert PG._review_skip_iids(rows, today="2026-09-08") == set()


def test_hint_uses_the_same_call_as_the_screen():
    """ヒントは **画面に出す側 (:1400)** と同じ呼び方で数える (2026-09-08 訂正)."""
    src = io.open(os.path.join(TOOLS, "psa_resource_gate.py"), encoding="utf-8").read()
    i = src.index("def count_workload(")
    body = src[i:src.index(chr(10) + "def ", i + 10)]
    assert "_review_skip_iids(read_tab(REVIEW_SKIP_TAB), today=t)" in body
    # 画面側 (:1400) も cooldown を見ている = 両者が同じ規則であることを固定する
    assert "_review_skip_iids(_skip_existing, today=_today_for_skip)" in src
