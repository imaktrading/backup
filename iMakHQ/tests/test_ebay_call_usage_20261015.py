# -*- coding: utf-8 -*-
"""2026-10-15 Trading API の1日5000回 (全呼び出しで共有・取下げも同じ枠) を使い切った。

- GetItem / GetOrders / GetMyMessages の口 (ebay_getitem_images._headers) が数えていなかった
- メッセージの一覧は30分おきに全通の本文を取り直していた (1回 約16呼び出し)
- 上限切れの GetMyMessages が空で返り、送信0通のまま一覧を保存していた
"""
import json
import os
import sys
from datetime import datetime

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for p in (os.path.join(_ROOT, "iMakeBayAPI"), os.path.join(_ROOT, "iMakHQ", "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)


def test_headers_records_call(tmp_path, monkeypatch):
    import ebay_call_usage as U
    import ebay_getitem_images as EG
    p = str(tmp_path / "u.json")
    monkeypatch.setattr(U, "_USAGE_PATH", p)
    monkeypatch.setattr(U, "STATE_PATH", str(tmp_path / "s.json"))
    monkeypatch.setattr(EG, "_access_token", lambda: "tok")
    EG._headers("GetOrders")
    EG._headers("GetItem")
    EG._headers("GetItem")
    day = json.load(open(p, encoding="utf-8"))[U.ebay_day()]
    assert day["GetItem"] == 2 and day["GetOrders"] == 1 and day["_total"] == 3


def test_fx_still_uses_same_counter():
    import ebay_call_usage as U
    import fix_de_speedpak_shipping as fx
    assert fx._record_call is U.record_call
    assert fx.ebay_day(datetime(2026, 8, 24, 16, 0)) == "2026-08-24"


_HEAD = ("<Ack>Success</Ack><Message><Sender>bob</Sender><MessageID>{m}</MessageID>"
         "<ReceiveDate>2026-10-14T00:00:00.000Z</ReceiveDate></Message>")
_BODY = ('<Ack>Success</Ack><Message><MessageID>{m}</MessageID>'
         '<Text>&lt;div id="UserInputtedText"&gt;hi {m}&lt;/div&gt;</Text></Message>')


@pytest.fixture
def BM(tmp_path, monkeypatch):
    import buyer_messages as BM
    monkeypatch.setattr(BM, "BODY_CACHE", str(tmp_path / "bodies.json"))
    return BM


def test_bodies_fetched_only_once(BM, monkeypatch):
    sent = []

    def fake(call, body):
        sent.append(body)
        if "ReturnHeaders" in body:
            return "".join(_HEAD.format(m=m) for m in ("1", "2"))
        ids = [x for x in ("1", "2") if f"<MessageID>{x}</MessageID>" in body]
        return "<Ack>Success</Ack>" + "".join(_BODY.format(m=m)[len("<Ack>Success</Ack>"):] for m in ids)
    monkeypatch.setattr(BM, "_post", fake)
    h1 = BM.fetch_messages(30, 0)
    assert [h["text"] for h in h1] == ["hi 1", "hi 2"] and len(sent) == 2
    sent.clear()
    h2 = BM.fetch_messages(30, 0)
    assert [h["text"] for h in h2] == ["hi 1", "hi 2"]
    assert len(sent) == 1            # 2回目は一覧だけ。本文は控えから


def test_failure_is_not_saved_as_empty(BM, monkeypatch):
    monkeypatch.setattr(BM, "_post", lambda c, b: "<Ack>Failure</Ack><LongMessage>exceeded usage limit</LongMessage>")
    with pytest.raises(RuntimeError, match="exceeded usage limit"):
        BM.fetch_messages(30, 1)


# ── 使い過ぎの歯止め / 2つ目の鍵への切替 (2026-10-15 ユーザー「止める・知らせる仕組みも」) ──
@pytest.fixture
def U2(tmp_path, monkeypatch):
    import ebay_call_usage as U
    monkeypatch.setattr(U, "_USAGE_PATH", str(tmp_path / "u.json"))
    monkeypatch.setattr(U, "STATE_PATH", str(tmp_path / "s.json"))
    monkeypatch.setattr(U, "NTFY_TOPIC", str(tmp_path / "none.txt"))     # スマホには送らない
    monkeypatch.setattr(U, "sub_access_token", lambda: "SUB")
    monkeypatch.setattr(sys, "argv", ["runaway.py"])
    return U


_QUOTA = "<Ack>Failure</Ack><LongMessage>Your application has exceeded usage limit on this call</LongMessage>"


def test_quota_error_switches_to_sub_and_retries(U2):
    seen = []

    def do(h):
        seen.append(h["X-EBAY-API-IAF-TOKEN"])
        return _QUOTA if h["X-EBAY-API-IAF-TOKEN"] == "MAIN" else "<Ack>Success</Ack>"
    assert U2.send(do, "GetItem", {"X-EBAY-API-IAF-TOKEN": "MAIN"}) == "<Ack>Success</Ack>"
    assert seen == ["MAIN", "SUB"] and U2.active_key() == "sub"
    seen.clear()                                    # 同じ日の次の呼出は最初から 2つ目の鍵
    U2.send(do, "GetItem", {"X-EBAY-API-IAF-TOKEN": "MAIN"})
    assert seen == ["SUB"]


def test_day_change_returns_to_main(U2):
    U2.mark_exhausted("main", now=datetime(2026, 10, 15, 10, 0))
    assert U2.active_key(datetime(2026, 10, 15, 15, 59)) == "sub"
    assert U2.active_key(datetime(2026, 10, 15, 16, 0)) == "main"     # eBay の日が変わった


def test_one_tool_is_capped_but_takedowns_pass(U2, monkeypatch):
    monkeypatch.setattr(U2, "CALLER_LIMIT", 3)
    for _ in range(3):
        U2.record_call("GetBestOffers")
    assert U2.guard("GetBestOffers")                      # 4回目は止める
    assert U2.guard("EndItem") is None                    # 取下げは止めない
    assert U2.guard("ReviseInventoryStatus") is None
    out = U2.send(lambda h: pytest.fail("送ってはいけない"), "GetBestOffers", {"X-EBAY-API-IAF-TOKEN": "MAIN"})
    assert "<Ack>Failure</Ack>" in out and "歯止め" in out
    monkeypatch.setattr(sys, "argv", ["other.py"])        # 他の道具は止まらない
    assert U2.guard("GetBestOffers") is None


def test_notify_only_once_per_day(U2):
    assert U2.notify_once("x", "t", "b") is True
    assert U2.notify_once("x", "t", "b") is False


def test_session_guarded_post_returns_failure_response(U2, monkeypatch):
    import ebay_getitem_images as EG
    monkeypatch.setattr(U2, "CALLER_LIMIT", 1)
    U2.record_call("GetItem")
    r = EG._HTTP.post("https://api.ebay.com/ws/api.dll", data=b"x",
                      headers={"X-EBAY-API-CALL-NAME": "GetItem", "X-EBAY-API-IAF-TOKEN": "MAIN"})
    assert "<Ack>Failure</Ack>" in r.text
