"""ミラーの発送除外は listing 側で入れる (2026-08-08 / plan B)。

なぜ:
    ポリシー側 (`ebay_exclude_regions.py`) は **その市場の自国向け除外を保存しない**。
    2026-08-02 実測で `EBAY_DE --add DE,AT` は API 成功 43/43 に対し保存は 18/43、
    `EBAY_GB --add IE` は 1/12。eBaymag でミラーを止めても listing は残る
    (8/8 実測: ebay.de の active 372件 / DE 除外済はうち 74件だけ)。
    = **listing 側の `ExcludeShipToLocation` を item ごとに入れるしかない**。

ここで固定する事故:
    1. 除外だけ送って **送料サービスを消す** (= 送れない出品が残る)
    2. 既存の除外を **上書きして減らす** (= 塞いだはずの国が開く)
    3. ページ送りを絞り込み後の件数で打ち切り、**対象を大量に見落とす**
       (2026-08-08 に offer_calc で踏んだのと同型)

参照: backlog 2026-08-02_ebaymag_stop_eu_mirrors
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import ebay_exclude_regions_item as EX  # noqa: E402


CUR = {
    "type": "Flat",
    "dom": [{"svc": "DE_EconomySppedPAK", "cur": "EUR", "cost": "6.62", "pri": "1", "loc": []}],
    "intl": [{"svc": "DE_IntlEconomySppedPAK", "cur": "EUR", "cost": "11.59", "pri": "1",
              "loc": ["AT"]}],
    "exclude": ["FR", "IT"],
    "shipto": ["Europe"],
}


# ---- 事故1: 送料サービスを消さない -----------------------------------------

def test_build_sd_keeps_domestic_service_and_cost():
    """国内サービスと料金がそのまま残る (消えると発送不能な出品になる)。"""
    xml = EX.build_sd(CUR, ["FR", "IT", "DE", "AT"])
    assert "<ShippingService>DE_EconomySppedPAK</ShippingService>" in xml
    assert '<ShippingServiceCost currencyID="EUR">6.62</ShippingServiceCost>' in xml


def test_build_sd_keeps_international_service_with_destination():
    """国際サービスと宛先 AT が残る。"""
    xml = EX.build_sd(CUR, ["FR", "IT"])
    assert "<ShippingService>DE_IntlEconomySppedPAK</ShippingService>" in xml
    assert '<ShippingServiceCost currencyID="EUR">11.59</ShippingServiceCost>' in xml
    assert "<ShipToLocation>AT</ShipToLocation>" in xml


def test_build_sd_keeps_shipping_type():
    assert "<ShippingType>Flat</ShippingType>" in EX.build_sd(CUR, [])


# ---- 事故2: 既存の除外を減らさない -----------------------------------------

def test_build_sd_emits_every_exclusion_given():
    """渡した除外が全部 XML に出る。"""
    xml = EX.build_sd(CUR, ["FR", "IT", "DE", "AT"])
    for code in ("FR", "IT", "DE", "AT"):
        assert f"<ExcludeShipToLocation>{code}</ExcludeShipToLocation>" in xml


def test_apply_is_union_not_replace():
    """本番の組み立て方 (既存 ∪ 追加) が既存を落とさない。"""
    merged = sorted(set(CUR["exclude"]) | set(EX.TARGETS["de"]["add"]))
    xml = EX.build_sd(CUR, merged)
    assert "<ExcludeShipToLocation>FR</ExcludeShipToLocation>" in xml  # 既存
    assert "<ExcludeShipToLocation>DE</ExcludeShipToLocation>" in xml  # 追加
    assert "<ExcludeShipToLocation>AT</ExcludeShipToLocation>" in xml


def test_region_names_with_spaces_survive():
    """'North America' 等の地域名 (空白入り) も落とさない。"""
    xml = EX.build_sd(CUR, ["North America", "PO Box"])
    assert "<ExcludeShipToLocation>North America</ExcludeShipToLocation>" in xml
    assert "<ExcludeShipToLocation>PO Box</ExcludeShipToLocation>" in xml


# ---- 事故3: ページ送りを絞り込み後の件数で打ち切らない ----------------------

def test_enumerate_does_not_stop_on_page_with_no_match(monkeypatch):
    """対象0件のページがあっても、後続ページの対象を拾う。

    page1 = 対象あり / page2 = US だけ (対象0件) / page3 = 対象あり。
    絞り込み後の件数で break する実装だと page3 を丸ごと落とす。
    """
    def page(item_urls, total_pages):
        items = "".join(
            f"<Item><ItemID>{i}</ItemID><ViewItemURL>{u}</ViewItemURL></Item>"
            for i, u in enumerate(item_urls, 1))
        return (f"<ActiveList>{items}<PaginationResult>"
                f"<TotalNumberOfPages>{total_pages}</TotalNumberOfPages>"
                "</PaginationResult></ActiveList>")

    pages = {
        1: page(["https://www.ebay.de/itm/a"], 3),
        2: page(["https://www.ebay.com/itm/b"], 3),
        3: page(["https://www.ebay.de/itm/c"], 3),
    }
    seen = []

    def fake_post(call, inner, tok, site="0"):
        n = int(inner.split("<PageNumber>")[1].split("<")[0])
        seen.append(n)
        return pages.get(n, "<ActiveList></ActiveList>")

    monkeypatch.setattr(EX.fx, "post", fake_post)
    got = EX.enumerate_mirror("tok", "//www.ebay.de/")
    assert seen == [1, 2, 3], f"3ページ目まで見ていない: {seen}"
    assert len(got) == 2, f"対象0件のページで打ち切った: {got}"


def test_enumerate_filters_by_domain_not_by_site():
    """ドメインで絞る。ebay.com / com.au を DE ミラーと取り違えない。"""
    body = ("<ActiveList>"
            "<Item><ItemID>1</ItemID><ViewItemURL>https://www.ebay.de/itm/a</ViewItemURL></Item>"
            "<Item><ItemID>2</ItemID><ViewItemURL>https://www.ebay.com/itm/b</ViewItemURL></Item>"
            "<Item><ItemID>3</ItemID><ViewItemURL>https://www.ebay.com.au/itm/c</ViewItemURL></Item>"
            "<PaginationResult><TotalNumberOfPages>1</TotalNumberOfPages></PaginationResult>"
            "</ActiveList>")
    EX.fx.post = lambda *a, **k: body
    assert EX.enumerate_mirror("tok", "//www.ebay.de/") == ["1"]


# ---- 対地の定義 -------------------------------------------------------------

def test_targets_uk_excludes_ireland_only_and_keeps_gb():
    """UK ミラーは IE だけ外す。GB (本国) は残す = 利益の大半は EU 外。"""
    assert EX.TARGETS["uk"]["add"] == ["IE"]
    assert "GB" not in EX.TARGETS["uk"]["add"]


def test_targets_de_covers_both_assigned_countries():
    """ebay.de の担当国は DE+AT。片方だけだと残った方から買える。"""
    assert set(EX.TARGETS["de"]["add"]) == {"DE", "AT"}
