# -*- coding: utf-8 -*-
"""神風「メッセージ」タブの裏 (buyer_messages.py) の判定 (2026-10-08)。

ユーザー確定: 変えるのは リピーターかどうか / 仕向地と値段の関税の一文 / 発送の追跡番号 の3つだけ。
関税の一文は注文の「eBay が取った税額」で決める (英国 £140 で税0 → 受け取り時の VAT を説明しなかった事故)。
"""
import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))

import buyer_messages as B  # noqa: E402


def test_customs_line_from_order_facts():
    assert "already included" in B.customs_line("US", "6.34")
    assert B.customs_line("GB", "12.0").startswith("UK VAT was already collected")      # £60 → 取り済み
    gb140 = B.customs_line("GB", "0.0")                                                  # £140 の事故の注文
    assert "may be charged" in gb140 and "£135" in gb140
    assert B.customs_line("AU", "12.9").startswith("Australian GST")
    assert B.customs_line("DE", "3").startswith("EU VAT")
    assert "€150" in B.customs_line("FR", "0")
    assert "may be charged" in B.customs_line("ID", "0.0") and "£135" not in B.customs_line("ID", "0.0")


def test_track_url_by_carrier():
    assert "japanpost" in B.track_url("Japan Post", "LX333090259JP")
    assert "LX333090259JP" in B.track_url("", "LX333090259JP")        # 運送会社が空でも番号の形で日本郵便
    assert "fedex" in B.track_url("FedEx", "123")
    assert B.track_url("Japan Post", "") == ""


def test_stage_repeat_and_todo():
    assert B.stage_of({"status": "Completed"}) == "paid"
    assert B.stage_of({"tracking": "X"}) == "shipped"
    assert B.stage_of({"tracking": "X", "delivered": "2026-10-01"}) == "arrived"
    assert B.stage_of({"status": "Cancelled", "tracking": "X"}) == "cancelled"
    hist = {"davidwalker5932": {"A": "2026-07-18T00:00:00Z", "B": "2026-10-08T00:00:00Z"}}
    assert B.is_repeat("davidwalker5932", "B", "2026-10-08T00:00:00Z", hist)
    assert not B.is_repeat("davidwalker5932", "A", "2026-07-18T00:00:00Z", hist)
    assert B.todo_for({"stage": "paid", "repeat": True}, set()) == "repeat"
    assert B.todo_for({"stage": "paid"}, {"paid"}) == ""
    assert B.todo_for({"stage": "shipped"}, set()) == ""                     # 追跡番号が無ければ発送の文は出さない
    assert B.todo_for({"stage": "shipped", "tracking": "X"}, {"paid"}) == "shipped"
    assert B.todo_for({"stage": "arrived"}, {"shipped"}) == "arrived"         # 前の段階の文は遅いので出さない


def test_render_fills_customs_and_tracking():
    ctx = {"customs": B.customs_line("GB", "0"), "carrier": "Japan Post", "tracking": "LX1",
           "track_url": B.track_url("Japan Post", "LX1")}
    s = B.render("shipped", ctx)
    assert "Tracking number: LX1" in s and "Track your parcel: https://" in s and "£135" in s
    assert "{" not in B.render("paid", {})                                   # 値が無くても型が崩れない
    assert "Welcome back" in B.render("repeat", ctx)


def test_classify_real_inquiries():
    # 直近30日に実際に来た文から
    assert B.classify("Yeah I accidentally purchased this twice if you could cancel one") == "ask_cancel"
    assert B.classify("If we can do 2 separate orders to keep it under the threshold?") == "ask_customs"
    assert B.classify("Hello do you offer combined shipping on two items?") == "ask_combine"
    assert B.classify("I think the tracking number isn't right") == "ask_shipping"
    assert B.classify("Let's meet at 107.50") == "ask_offer"
    assert B.classify("May I ask, is that any reason for such a low price compared to other sellers?") == "ask_price"
    assert B.classify("So, do you selling the 2024 One Piece Day card?") == "ask_stock"
    assert B.classify("No worries you guys are fantastic thank you") == "ask_thanks"


def test_sent_kind_and_text_fix():
    assert B.sent_kind("Thank you very much for your purchase!\n...") == "paid"
    assert B.sent_kind("Welcome back, and thank you so much for ordering from us again!") == "paid"
    assert B.sent_kind("Your item has been shipped from Osaka, Japan.") == "shipped"
    assert B.sent_kind("Hope your package arrived safely") == "arrived"
    assert B.fix_text("Letâ\x80\x99s meet") == "Let’s meet"
    assert B.fix_text("Â£135") == "£135"


def test_build_groups_threads_and_presale_questions():
    orders = [{"id": "O1", "status": "Completed", "created": "2026-10-08T00:00:00Z", "buyer": "b1", "country": "GB",
               "tax": "0", "item_id": "I1", "title": "Card", "tracking": "LX1", "carrier": "Japan Post"}]
    inbox = [{"mid": "1", "sender": "b1", "item_id": "I1", "when": "2026-10-08T01:00:00Z", "text": "you didn't pay custom charges"},
             {"mid": "2", "sender": "q1", "item_id": "I9", "when": "2026-10-08T02:00:00Z", "text": "$120", "subject": "q1 sent a message about Mew"}]
    sent = [{"mid": "3", "to": "b1", "item_id": "I1", "when": "2026-10-07T00:00:00Z", "text": "Your item has been shipped from Osaka"}]
    convs, hist = B.build(orders, inbox, sent, {}, {}, B.DEFAULT_TEMPLATES)
    o = [c for c in convs if c["kind"] == "order"][0]
    assert o["stage"] == "shipped" and o["sent"] == ["shipped"] and o["needs_reply"] and o["ask"] == "ask_customs"
    q = [c for c in convs if c["kind"] == "ask"][0]
    assert q["buyer"] == "q1" and q["ask"] == "ask_offer" and q["title"] == "Mew"
    assert hist == {"b1": {"O1": "2026-10-08T00:00:00Z"}}
