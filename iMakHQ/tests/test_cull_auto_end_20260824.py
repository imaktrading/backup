"""取下げボタンが eBay に直接送る (2026-08-24 ユーザー指示「ボタンは元々自動」)。

2026-06-05 の「自動アップ無し」を外した。根拠:
  - 送る直前に **1件ずつ eBay の実状態を見ている** (8/24 実測: 在庫復活6件 / 終了済115件 が外れた)
  - 対象は CULL のみ / $100以上 / 14日以上 / 1回 CAP件 まで
  - qty=0 = そもそも買えない出品なので売上を失わない
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import cull_end as C  # noqa: E402

SRC = os.path.join(os.path.dirname(__file__), "..", "tools", "cull_end.py")


def _picked(*ids):
    return [{"item_id": i, "title": "t"} for i in ids]


def _fake(responses):
    """itemID → 返す XML。"""
    def post(call, inner, tok, site="0"):
        import re
        iid = re.search(r"<ItemID>(\d+)</ItemID>", inner).group(1)
        return responses[iid]
    return post


OK = "<Ack>Success</Ack>"
WARN = "<Ack>Warning</Ack>"
CLOSED = "<Ack>Failure</Ack><LongMessage>Error - The auction has already been closed.</LongMessage>"
BOOM = "<Ack>Failure</Ack><LongMessage>System error. Try later.</LongMessage>"


def test_success_and_warning_both_count():
    ok, ng = C.end_on_ebay(_picked("1", "2"),
                           post_fn=_fake({"1": OK, "2": WARN}), token_fn=lambda: "t")
    assert ok == ["1", "2"] and ng == []


def test_already_closed_counts_as_done():
    """★目的は「出品が終わっていること」。既に終了済みは成功に数える."""
    ok, ng = C.end_on_ebay(_picked("1"), post_fn=_fake({"1": CLOSED}), token_fn=lambda: "t")
    assert ok == ["1"] and ng == []


def test_real_failure_is_not_counted_as_success():
    """通信/システムエラーを成功に混ぜない (silent drop を作らない)."""
    ok, ng = C.end_on_ebay(_picked("1", "2"),
                           post_fn=_fake({"1": OK, "2": BOOM}), token_fn=lambda: "t")
    assert ok == ["1"]
    assert [i for i, _m in ng] == ["2"]


def test_empty_response_is_failure():
    ok, ng = C.end_on_ebay(_picked("1"), post_fn=_fake({"1": ""}), token_fn=lambda: "t")
    assert ok == [] and [i for i, _m in ng] == ["1"]


def test_csv_only_escape_hatch_exists():
    """送らずに CSV だけ作る道を残す (緊急時・確認したい時)."""
    assert "--csv-only" in open(SRC, encoding="utf-8").read()


def test_verify_runs_before_sending():
    """★実状態の確認 → 送信 の順であること (逆なら自動化してはいけない)."""
    src = open(SRC, encoding="utf-8").read()
    i_main = src.find("def main(")
    i_verify = src.find("verify_oos(picked", i_main)
    i_send = src.find("end_on_ebay(picked)", i_main)
    assert 0 < i_verify < i_send, "確認より先に送っている"


def test_sheet_update_uses_sent_ids_not_files():
    """送った側が成功 itemID を知っているので、結果ファイルを介さない."""
    src = open(SRC, encoding="utf-8").read()
    assert "CW.apply(set(ok_ids), commit=True)" in src
