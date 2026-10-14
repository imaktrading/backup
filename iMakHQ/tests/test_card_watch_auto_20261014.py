"""補0本の仕入れ待ちは見張りを自動で始め、仕入れたら閉じる (2026-10-14 ユーザー「今後のために、修正してよ」)。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import card_watch as C  # noqa: E402

Q = {"kw": "PSA10 バリヤード 013/032", "card_no": "CLK-013", "market_no": "013/032", "name_jp": "バリヤード"}


def test_build_watch_matches_real_listing_names():
    w = C.build_watch("820209548828", "PSA 10 ... Mr. Mime", "pokemon_tcg:CLK-013", "2026/10/21", Q, 147502)
    assert w["until"] == "2026-10-21" and w["snkrdunk_id"] == 147502 and w["auto"]
    assert C.matches("【PSA10】バリヤード ポケモンカードClassic CLK 013/032", w)
    assert not C.matches("【PSA9】バリヤード CLK 013/032", w)
    assert not C.matches("バリヤード PSA10 CLK 013/032 連番セット", w)
    assert not C.matches("【PSA10】バリヤード 012/032", w)


def test_sync_adds_new_and_closes_bought():
    old = [{"for_item": "A", "auto": True}, {"for_item": "M", "auto": False}]
    want = [{"item": "A"}, {"item": "B"}]
    new, added, closed = C.sync_watches(old, want, ["A", "B"], lambda x: {"for_item": x["item"], "auto": True})
    assert added == 1 and closed == 0 and [w["for_item"] for w in new] == ["A", "M", "B"]
    new, added, closed = C.sync_watches(new, [], ["B"], lambda x: None)
    assert closed == 1 and new[0]["done"] and not new[1].get("done")      # 手で作った見張りは閉じない


def test_order_sync_calls_auto_watch():
    src = open(os.path.join(HERE, "..", "tools", "order_purchase_sync.py"), encoding="utf-8").read()
    assert "_cw.auto_from_orders(" in src
