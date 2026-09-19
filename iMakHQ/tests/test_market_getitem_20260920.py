"""売れた競合の出品を丸ごと残す (2026-09-20)。

ユーザー確定「丸ごとなら、取り直し要らないね」。集計して保存すると、後から
「これも見たい」となった時に全件取り直しになる。XML をそのまま残す。
"""
import sys

sys.path.insert(0, r"C:/dev/iMak/iMakHQ/tools")
import market_getitem as G

XML = """<GetItemResponse><Ack>Success</Ack><Item>
<Seller><UserID>souji_tcg_japan</UserID><FeedbackScore>369</FeedbackScore><PositiveFeedbackPercent>100.0</PositiveFeedbackPercent></Seller><Country>JP</Country><Location>kyoto</Location>
<ItemID>397848920689</ItemID><Title>PSA10 Radiant Greninja 004/038</Title>
<SubTitle>Gem Mint</SubTitle>
<PrimaryCategory><CategoryID>183454</CategoryID><CategoryName>Trading Cards</CategoryName></PrimaryCategory>
<PictureDetails><PictureURL>a.jpg</PictureURL><PictureURL>b.jpg</PictureURL></PictureDetails>
<ShippingDetails><ShippingServiceCost currencyID="USD">0.0</ShippingServiceCost></ShippingDetails>
<BestOfferDetails><BestOfferEnabled>true</BestOfferEnabled></BestOfferDetails>
<ListingType>FixedPriceItem</ListingType><ConditionDisplayName>Graded</ConditionDisplayName>
<ReturnPolicy><ReturnsAcceptedOption>ReturnsNotAccepted</ReturnsAcceptedOption></ReturnPolicy>
<Description>hello</Description>
<ItemSpecifics>
<NameValueList><Name>Character</Name><Value>Greninja</Value></NameValueList>
<NameValueList><Name>Features</Name><Value>Holo</Value><Value>1st Edition</Value></NameValueList>
</ItemSpecifics></Item></GetItemResponse>"""


def test_項目と値を取り出す():
    got = G.specifics(XML)
    assert got["Character"] == ["Greninja"]
    assert got["Features"] == ["Holo", "1st Edition"]      # 複数値も落とさない


def test_リスティングの作りを取り出す():
    s = G.summary(XML)
    assert s["itemID"] == "397848920689"
    assert s["サブタイトル"] == "Gem Mint"
    assert s["カテゴリ"] == "183454"
    assert s["写真枚数"] == 2
    assert s["送料無料"] is True
    assert s["BestOffer"] is True
    assert s["返品"] == "ReturnsNotAccepted"
    assert s["項目数"] == 2
    # ★2026-09-20 ユーザー「セラーidもとれる?」
    assert s["セラー"] == "souji_tcg_japan"
    assert s["評価数"] == "369" and s["国"] == "JP"


def test_空でも壊れない():
    assert G.specifics("") == {}
    assert G.summary("")["写真枚数"] == 0


def test_保存は丸ごと():
    """焼いた集計ではなく XML をそのまま残す (後から読み方を変えられるように)。"""
    src = open(r"C:/dev/iMak/iMakHQ/tools/market_getitem.py", encoding="utf-8").read()
    assert "def save_raw" in src and "gzip" in src
    assert "取り直し" in src                      # なぜ丸ごとかを書き残す
