# -*- coding: utf-8 -*-
"""在庫切れを「戻す口があるか」だけで振り分ける + 在庫なしシートの状態列 (2026-08-25)。

## 何が起きていたか
在庫切れの出品が「広告で1回でも表示された」だけで RESTOCK (再仕入れ待ち) に入り、
誰も拾わないまま出品枠を食い続けていた。実測 (US 1,843件):
  - Porter 139件中 128件が在庫切れ、うち 102件が RESTOCK。放置日数の中央値81日・最長166日
  - Amazon 仕入れの G-SHOCK も 99件が同じ状態
  - 再仕入れの仕組みがあるのは PSA10 (補URL) と 一番くじ (景品の代替探索) の2つだけ

## 遠回りした経緯 (同じ失敗をしないため残す)
最初は「中古1点ものか」を仕入元URLの形で見分けようとした。これは2回外している:
  1. ホスト名だけで見て **メルカリShops (店舗)** を1点もの扱いし、8/25 の取下げで15件を巻き込んだ
  2. パスまで見るように直したが、店舗が売る **中古リール** は依然1点もので、見分けられない

## 決めたこと (ユーザー確定)
**1点ものかどうかは見ない。** 量産品でも戻す口が無ければ同じように居座る。
判定は「在庫切れ ∩ 戻す仕組みが無い → 畳む」の一行。
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


# ---- 戻す口 (再仕入れの担当) があるか ----

def test_owner_is_psa10():
    assert LF.restock_owner(_row(title="PSA 10 Pokemon Japanese Charizard #003/184")) == "PSA10"


def test_owner_is_ichibankuji():
    assert LF.restock_owner(_row(title="Ichiban Kuji One Piece A Prize Luffy")) == "一番くじ"


def test_no_owner_for_everything_else():
    """量産品でも戻す口が無ければ同じ。仕入元URLの形は見ない。"""
    assert LF.restock_owner(_row(title="YOSHIDA PORTER Tanker Shoulder Bag",
                                 supply_url="https://jp.mercari.com/item/m1")) == ""
    assert LF.restock_owner(_row(title="CASIO G-Shock GA-B2100BEG-1AJF",
                                 supply_url="https://www.amazon.co.jp/dp/B0XXXX")) == ""
    assert LF.restock_owner(_row(title="Shimano 24 SLX 70HG Baitcast Reel",
                                 supply_url="https://jp.mercari.com/shops/product/x")) == ""


# ---- バケツ振り分け ----

def test_no_owner_out_of_stock_goes_to_cull_even_with_demand():
    """戻す口が無ければ、需要があっても畳む (誰も戻さないので居座るだけ)。"""
    porter = _row(item_id="820011324380", watch=18,
                  supply_url="https://jp.mercari.com/item/m7")
    c = LF.classify([porter])
    assert porter in c["CULL"] and porter not in c["RESTOCK"]


def test_mass_produced_without_owner_also_culled():
    """Amazon 仕入れの G-SHOCK も同じ。品は戻せても戻す仕組みが無い (実測99件が滞留)。"""
    g = _row(item_id="2", title="CASIO G-Shock GW-M5610", watch=5,
             supply_url="https://www.amazon.co.jp/dp/B0XXXX")
    c = LF.classify([g])
    assert g in c["CULL"] and g not in c["RESTOCK"]


def test_ichibankuji_with_demand_stays_restock():
    k = _row(item_id="3", title="Ichiban Kuji Dragon Ball F Prize Goku", watch=4,
             supply_url="https://jp.mercari.com/item/m9")
    c = LF.classify([k])
    assert k in c["RESTOCK"] and k not in c["CULL"]


def test_psa10_keeps_the_real_demand_gate():
    """PSA10 は従来どおり実需 (広告だけの表示では戻さない)。"""
    weak = _row(item_id="4", title="PSA 10 Pokemon Japanese Pikachu #001/100",
                watch=0, impr=0, impr_total=900)
    strong = _row(item_id="5", title="PSA 10 Pokemon Japanese Pikachu #002/100", watch=2)
    c = LF.classify([weak, strong])
    assert weak in c["CULL"] and strong in c["RESTOCK"]


# ---- 在庫なしシート S列 ----

def test_status_restock():
    r = _row(item_id="9")
    # Porter は戻す仕組みが無い → 「再仕入れ」とは書かない (戻る予定に見えるため)
    assert LF.oos_status(r, cull_ids=set(), done_ids=set()) == "🛒 在庫切れ (戻す口が無い)"


def test_status_cull_done():
    r = _row(item_id="9")
    assert LF.oos_status(r, cull_ids={"9"}, done_ids={"9"}) == "🗑 取下げ 済"


def test_status_cull_pending_reasons():
    """まだ落ちていない行は **理由つき**で出す (いつまでも「未」だと読めない)。"""
    nxt = LF.oos_status(_row(item_id="9"), cull_ids={"9"}, done_ids=set())
    assert nxt.startswith("🗑 取下げ 未") and "次回" in nxt

    # ★2026-08-31: MIN_AGE を 14→1 に変更 (在庫0の間は待っても表示が増えないため、
    #   既知の若さでは待たない。0=年齢不明の sentinel だけ fail-closed で除外する)。
    #   これにより「N日未満」枝は事実上 age==0 でしか届かず、その時は「不明」枝を返す。
    unknown_age = LF.oos_status(_row(item_id="9", age_days=0), cull_ids={"9"}, done_ids=set())
    assert "出品日 不明" in unknown_age

    known_young = LF.oos_status(_row(item_id="9", age_days=1), cull_ids={"9"}, done_ids=set())
    assert "次回" in known_young, "既知の年齢 (1日) は、もう待たされない"

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
