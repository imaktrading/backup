# -*- coding: utf-8 -*-
"""在庫切れの「中古1点もの」を再仕入れ待ちに置かない + 在庫なしシートに状態を出す (2026-08-25)。

## 何が起きていたか
Porter (吉田カバン) は中古の1点もので、仕入元はメルカリの個別出品。売れた時点でその個体は
消えるので、在庫切れになったら二度と戻せない。それなのに「広告の表示があった」だけで
RESTOCK (再仕入れ待ち) に入り、誰も拾わないまま出品枠を食い続けていた。

実測 (2026-08-25 のファネル, US 1,843件):
  - Porter 139件のうち 128件が在庫切れ。うち **102件が RESTOCK**、CULL はわずか 26件
  - 放置日数の中央値 81日・最長 166日。仕入元は 107件が jp.mercari.com の個別出品
  - 再仕入れの仕組みがあるのは PSA10 (補URL) と一番くじ (景品の代替探索) だけ

## 決めたこと (ユーザー指示)
- 仕入元が中古の個別出品なら、需要があっても RESTOCK に置かず CULL に落とす
- 量産品の仕入元 (amazon / 公式 / snkrdunk) はこれまでどおり
- 仕入元URLが空の行は触らない (fail-closed)
- 在庫なしシートの S列に「どのバケツか / CULL なら取り下げ済か」を出す
"""
import os
import sys

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import cull_end          # noqa: E402
import listing_funnel as LF  # noqa: E402


def _row(**kw):
    r = {"item_id": "1", "title": "YOSHIDA PORTER Tanker Shoulder Bag", "site": "US",
         "price": 189.98, "age_days": 90, "qty": 0, "sold_qty": 0, "sales90": 0,
         "watch": 3, "impr": 0, "impr_total": 12, "supply_url": ""}
    r.update(kw)
    return r


# ---- 仕入元が中古1点ものか ----

def test_mercari_item_is_one_off():
    assert LF.is_one_off_supply(_row(supply_url="https://jp.mercari.com/item/m72314289533"))
    assert LF.is_one_off_supply(_row(supply_url="https://item.fril.jp/abc123"))


def test_mass_produced_supply_is_not_one_off():
    """量産品の仕入元は戻せる → これまでどおり再仕入れ待ちに残す。"""
    assert not LF.is_one_off_supply(_row(supply_url="https://www.amazon.co.jp/dp/B0XXXX"))
    assert not LF.is_one_off_supply(_row(supply_url="https://snkrdunk.com/products/1234"))


def test_unknown_supply_is_left_alone():
    """仕入元が分からない行は触らない (fail-closed)。"""
    assert not LF.is_one_off_supply(_row(supply_url=""))


def test_ichibankuji_is_exempt():
    """一番くじは景品の代替を探す仕組みがあるので1点もの扱いしない。"""
    assert not LF.is_one_off_supply(
        _row(title="Ichiban Kuji Dragon Ball Figure", supply_url="https://jp.mercari.com/item/m1"))


# ---- バケツ振り分け ----

def test_one_off_out_of_stock_goes_to_cull_even_with_demand():
    porter = _row(item_id="820011324380", supply_url="https://jp.mercari.com/item/m7", watch=18)
    c = LF.classify([porter])
    assert porter in c["CULL"], "中古1点ものは需要があっても取下げ側"
    assert porter not in c["RESTOCK"]


def test_mass_produced_out_of_stock_still_restock():
    gshock = _row(item_id="2", title="CASIO G-Shock GW-M5610", watch=5,
                  supply_url="https://www.amazon.co.jp/dp/B0XXXX")
    c = LF.classify([gshock])
    assert gshock in c["RESTOCK"], "量産品は再仕入れで戻せる"
    assert gshock not in c["CULL"]


# ---- 在庫なしシート S列 ----

def test_status_restock():
    r = _row(item_id="9")
    assert LF.oos_status(r, cull_ids=set(), done_ids=set()) == "🛒 再仕入れ"


def test_status_cull_done():
    r = _row(item_id="9")
    assert LF.oos_status(r, cull_ids={"9"}, done_ids={"9"}) == "🗑 取下げ 済"


def test_status_cull_pending_reasons():
    """まだ落ちていない行は **理由つき**で出す (いつまでも「未」だと読めない)。"""
    nxt = LF.oos_status(_row(item_id="9"), cull_ids={"9"}, done_ids=set())
    assert nxt.startswith("🗑 取下げ 未") and "次回" in nxt

    young = LF.oos_status(_row(item_id="9", age_days=3), cull_ids={"9"}, done_ids=set())
    assert f"{cull_end.MIN_AGE}日未満" in young

    cheap = LF.oos_status(_row(item_id="9", price=20), cull_ids={"9"}, done_ids=set())
    assert "未満は枠に効かない" in cheap

    mirror = LF.oos_status(_row(item_id="9", site="CA"), cull_ids={"9"}, done_ids=set())
    assert "ミラー" in mirror


def test_status_uses_cull_end_gates_not_a_copy():
    """門は cull_end の持ち物。表示側で数字を書き直していないこと。"""
    src = open(os.path.join(_TOOLS, "listing_funnel.py"), encoding="utf-8").read()
    i = src.index("def oos_status(")
    body = src[i:i + 1200]
    assert "MIN_AGE" not in body and "MIN_PRICE" not in body, (
        "しきい値を表示側に持たない (cull_end.end_status を呼ぶ)")


# ---- ★2026-08-25 追記: メルカリShops を巻き込んだ事故の再発防止 ----

def test_mercari_shops_is_not_one_off():
    """メルカリShops は **店舗**。量産品を売っているので仕入れ直せる。

    初版はホスト名 (jp.mercari.com) だけで判定したため Shops を1点もの扱いし、
    8/25 の取下げで 17件を巻き込んだ (うち5件は watcher 付き)。
    実例: 356886563534 CASIO G-SHOCK DW-9052-1V (watcher 3)。
    """
    assert not LF.is_one_off_supply(
        _row(supply_url="https://jp.mercari.com/shops/product/NeE5M3KATkUHc66gC8oQiV"))


def test_mercari_individual_listing_is_still_one_off():
    """個人の個別出品はこれまでどおり1点もの。"""
    assert LF.is_one_off_supply(_row(supply_url="https://jp.mercari.com/item/m72314289533"))


def test_shops_out_of_stock_stays_restock():
    w = _row(item_id="356886563534", title="CASIO G-SHOCK DW-9052-1V", watch=3,
             supply_url="https://jp.mercari.com/shops/product/NeE5M3KATkUHc66gC8oQiV")
    c = LF.classify([w])
    assert w in c["RESTOCK"] and w not in c["CULL"]
