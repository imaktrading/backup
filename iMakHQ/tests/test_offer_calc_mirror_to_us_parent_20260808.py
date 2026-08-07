"""ミラー出品の仕入値を US本体経由で解決する (2026-08-08)。

なぜ:
    ミラー (ebay.de/uk/... の eBaymag mirror) は SKU 無し・cert 無し・itemID もシートに無い
    ので、既存3経路 (①itemID/②cert/③SKU→URL) では全て外れ、**黙って cost=0** になっていた。
    実オファー `358841114399`(uk) は US本体 `358600821584` の親で、シート row603 (F=17000/
    N=11999) が引ければ 11999 を返せる。タイトル完全一致で1件に絞れる時だけ引く
    (fail-closed: 0件 or 2件以上は特定不能 → 手入力に落とす)。

参照: 2026-08-08_offer_calc_mirror_to_us_parent_response.md
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
sys.path.insert(0, r"C:\dev\iMak\iMakeBayAPI")

import offer_calc as OC  # noqa: E402
from listing_common import pick_cost_jpy  # noqa: E402


# ---- ①〜③ の周辺: find_us_parent (④の中核) --------------------------------

def test_find_us_parent_unique_hit_returns_parent():
    """同名 US本体が1件なら parent iid を返す。"""
    table = {"Some Title": [{"iid": "358600821584",
                             "url": "https://www.ebay.com/itm/358600821584"}]}
    got = OC.find_us_parent("Some Title", table)
    assert got is not None and got["iid"] == "358600821584"


def test_find_us_parent_zero_hit_returns_none_fail_closed():
    """0件なら None (fail-closed). 黙って別カードを掴まない."""
    assert OC.find_us_parent("Unknown Title", {}) is None
    assert OC.find_us_parent("Absent", {"Something Else": [{"iid": "1"}]}) is None


def test_find_us_parent_multi_hit_returns_none_fail_closed():
    """2件以上なら None. 同名重複は特定不能 → 手入力へ."""
    table = {"Dup Title": [{"iid": "111"}, {"iid": "222"}]}
    assert OC.find_us_parent("Dup Title", table) is None


def test_find_us_parent_partial_match_not_allowed():
    """完全一致のみ. 部分一致で別カードを掴まない (誤仕入値 = 赤字承諾リスク)."""
    table = {"Charizard V PSA 10": [{"iid": "111"}]}
    assert OC.find_us_parent("Charizard VMAX PSA 10", table) is None
    assert OC.find_us_parent("Charizard V PSA 10 Rare", table) is None


def test_find_us_parent_whitespace_normalised():
    """タイトルの前後空白・連続空白は畳んで一致とみなす (US本体/ミラーは基本同一だが安全側)."""
    table = {"Some Title": [{"iid": "X"}]}
    assert OC.find_us_parent("  Some   Title  ", table)["iid"] == "X"


# ---- ページ打ち切りバグ回帰 (2026-08-08 の窓口検算がここを差し戻し) --------

def _mk_item(iid, title, host):
    return (f"<Item><ItemID>{iid}</ItemID><Title>{title}</Title>"
            f"<ListingDetails><ViewItemURL>https://{host}/itm/{iid}</ViewItemURL>"
            f"</ListingDetails></Item>")


def _mk_page(items_xml, total_pages):
    return ("<ActiveList>"
            + items_xml
            + f"<PaginationResult><TotalNumberOfPages>{total_pages}</TotalNumberOfPages>"
            "</PaginationResult></ActiveList>")


def test_pagination_does_not_break_off_when_us_count_is_zero():
    """★US件数で打ち切ってはいけない — page3〜5 が US 0件でも page6 まで舐めること。

    2026-08-08 の窓口 (BRAVO) 実測: page1=US108件 / p2=1 / p3-5=0 / p6=US58件 / ...
    US件数で打ち切ると 1,846件中 1,737件 (94%) を見落とし、ミラーの親が
    ほぼ特定できなくなる (実害: 手入力に大量に落ちる)。
    """
    pages = {}
    # page1〜2: US あり
    pages[1] = _mk_page(_mk_item(1001, "T-p1", "www.ebay.com"), total_pages=6)
    pages[2] = _mk_page(_mk_item(2001, "T-p2", "www.ebay.com"), total_pages=6)
    # page3〜5: 非US のみ (US 0件)
    pages[3] = _mk_page(_mk_item(3001, "T-uk-only", "www.ebay.co.uk"), total_pages=6)
    pages[4] = _mk_page(_mk_item(4001, "T-de-only", "www.ebay.de"), total_pages=6)
    pages[5] = _mk_page(_mk_item(5001, "T-au-only", "www.ebay.com.au"), total_pages=6)
    # page6: US 復活 — ここを見落としてはいけない
    pages[6] = _mk_page(_mk_item(6001, "T-p6-must-be-seen", "www.ebay.com"), total_pages=6)

    idx = OC.build_us_parents_index(lambda n: pages.get(n, ""))

    assert "T-p6-must-be-seen" in idx, (
        "US 0件のページで打ち切った (2026-08-08 のバグが再現)。全ページ舐めていない。")
    assert idx["T-p6-must-be-seen"][0]["iid"] == "6001"
    assert "T-p1" in idx and "T-p2" in idx


def test_pagination_stops_when_page_has_no_items_at_all():
    """<Item> が1つも無い ActiveList に到達したら打ち切る (無限ループ防止)."""
    pages = {
        1: _mk_page(_mk_item(1, "A", "www.ebay.com"), total_pages=10),
        2: "<ActiveList><PaginationResult><TotalNumberOfPages>10</TotalNumberOfPages>"
           "</PaginationResult></ActiveList>",   # <Item> 無し
    }
    call_count = {"n": 0}

    def fetch(n):
        call_count["n"] = max(call_count["n"], n)
        return pages.get(n, "")
    idx = OC.build_us_parents_index(fetch)
    assert "A" in idx and len(idx) == 1
    assert call_count["n"] == 2, "空ページ以降を呼び続けている"


def test_pagination_stops_at_total_number_of_pages():
    """TotalNumberOfPages に到達したら止まる (余分な API 呼び出しをしない)."""
    pages = {1: _mk_page(_mk_item(1, "A", "www.ebay.com"), total_pages=1)}
    call_count = {"n": 0}

    def fetch(n):
        call_count["n"] = max(call_count["n"], n)
        return pages.get(n, "")
    idx = OC.build_us_parents_index(fetch)
    assert "A" in idx
    assert call_count["n"] == 1


# ---- ドメイン判定 (US本体だけを US と扱う) -----------------------------------

def test_domain_filter_rejects_non_us_ebay_domains():
    """★`ebay.com.au` `.co.uk` `.ca` `.de` を US と誤判定しない。

    `.ebay.com/` (末尾スラッシュ付き) 判定で `www.ebay.com.au` に部分一致しない。
    """
    xml = _mk_page(
        _mk_item(1, "US Card", "www.ebay.com")
        + _mk_item(2, "AU Card", "www.ebay.com.au")
        + _mk_item(3, "UK Card", "www.ebay.co.uk")
        + _mk_item(4, "DE Card", "www.ebay.de")
        + _mk_item(5, "CA Card", "www.ebay.ca"),
        total_pages=1)
    idx = OC.build_us_parents_index(lambda n: xml if n == 1 else "")
    assert "US Card" in idx and idx["US Card"][0]["iid"] == "1"
    for t in ("AU Card", "UK Card", "DE Card", "CA Card"):
        assert t not in idx, f"{t} を US と誤判定した"


def test_active_list_scope_prevents_bleed_from_other_lists():
    """<Item> は <ActiveList> スコープ内に限定する。

    GetMyeBaySelling は ActiveList 以外の list (SoldList/UnsoldList 等) も返しうる。
    それらの Item を US本体 index に混入させると、既に売れた/取り下げた listing の iid で
    シートを引いて誤った仕入値に落ちる。TotalNumberOfPages と同じ罠 (offer_calc.py:115-117)。
    """
    xml = ("<ActiveList>"
           + _mk_item(1, "Active US", "www.ebay.com")
           + "<PaginationResult><TotalNumberOfPages>1</TotalNumberOfPages></PaginationResult>"
           "</ActiveList>"
           "<SoldList>" + _mk_item(2, "Sold US", "www.ebay.com") + "</SoldList>"
           "<UnsoldList>" + _mk_item(3, "Unsold US", "www.ebay.com") + "</UnsoldList>")
    idx = OC.build_us_parents_index(lambda n: xml if n == 1 else "")
    assert "Active US" in idx
    assert "Sold US" not in idx, "SoldList の Item が US本体 index に混入した"
    assert "Unsold US" not in idx, "UnsoldList の Item が US本体 index に混入した"


# ---- 実測経路の固定 (実機オファーはキャンセルされたので単体テストで代用) ----

def test_mirror_to_us_parent_full_path_358841114399_to_358600821584_to_11999():
    """★実測経路の固定 (2026-08-08 依頼書 §「既知」#7-8)。

    ミラー `358841114399`(ebay.co.uk) と US本体 `358600821584`(ebay.com) は同一タイトルで、
    US本体行 (row603) の N列に 11999 が入っている → pick_cost_jpy が 11999 を返す。
    実機オファーは 8/8 に買い手キャンセルで再現できないため、経路をここで固定する。
    """
    title = "Charizard PSA10 Test Fixture"
    # ① build_us_parents_index が US本体だけを拾えること
    xml = _mk_page(
        _mk_item("358841114399", title, "www.ebay.co.uk")   # ミラー — 拾わない
        + _mk_item("358600821584", title, "www.ebay.com"),  # US本体 — これだけ拾う
        total_pages=1)
    idx = OC.build_us_parents_index(lambda n: xml if n == 1 else "")
    assert "358600821584" == idx[OC._norm_title(title)][0]["iid"]

    # ② find_us_parent がミラーの title から US親 iid を1つに絞れること
    parent = OC.find_us_parent(title, idx)
    assert parent is not None and parent["iid"] == "358600821584"

    # ③ US親 iid で引いた row (COL_ITEMID=1, COL_COST_N=13) から pick_cost_jpy が 11999 を返すこと
    row = [""] * 20
    row[OC.COL_ITEMID] = "358600821584"       # B列
    row[OC.COL_COST_N] = "11999"              # N列 (SSOT)
    assert pick_cost_jpy(row) == "11999"

    # ④ cost_src に「ミラー → US本体」経路が出せる形になっていること (fetch_offers の生成文字列)
    #    ここでは形式チェックだけ (実際の生成は fetch_offers 内)。
    src_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "tools", "offer_calc.py")
    src = open(src_path, encoding="utf-8").read()
    assert "US本体" in src and "タイトル一致" in src
    assert "find_us_parent" in src
    assert "build_us_parents_index" in src


def test_mirror_detected_but_us_parent_not_found_shows_reason_in_source():
    """ミラー判定はしたが US本体を特定できない時、cost_src に理由を出す (fail-closed)。

    実装 (fetch_offers 内) が「US本体を一意に特定できず」というテキストを持つことを固定。
    """
    src_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "tools", "offer_calc.py")
    src = open(src_path, encoding="utf-8").read()
    assert "US本体を一意に特定できず" in src
    assert "手入力" in src
