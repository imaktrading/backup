"""見張りがスニダンの出品を拾う (psa10_listings_for は id を返さないので url から取る・2026-10-14)。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import card_watch as C  # noqa: E402
import snkrdunk_psa_resource as S  # noqa: E402


def test_snkrdunk_listing_is_picked_up(monkeypatch):
    monkeypatch.setattr(S, "psa10_listings_for", lambda cid: [
        {"price": 13800, "image": "", "url": S.LISTING_PAGE_TMPL.format(card_id=cid, listing_id=555)}])
    out = C.search_snkrdunk({"snkrdunk_id": 147502, "name": "バリヤード"})
    assert out and out[0]["id"] == "snkr-555" and out[0]["price"] == 13800
