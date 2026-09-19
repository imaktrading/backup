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


# ---- 無駄打ちをしない (2026-09-20 ユーザー「いつも、それで失敗する」) ----

def test_取れた分は二度取りに行かない():
    """1件1ファイルで残し、既にある物は対象から外す。実機で確認:
    3件 → 2件追加 → 2件追加 と増え、先の3件の更新時刻は変わらなかった。
    """
    src = open(r"C:/dev/iMak/iMakHQ/tools/market_getitem.py", encoding="utf-8").read()
    body = src.split("def cmd_fetch(")[1]
    assert "if not have(i)" in body                  # 既にある物は取らない


def test_残り回数を見てから走る():
    src = open(r"C:/dev/iMak/iMakHQ/tools/market_getitem.py", encoding="utf-8").read()
    body = src.split("def cmd_fetch(")[1]
    assert "remaining_getitem()" in body
    assert body.index("remaining_getitem()") < body.index("requests.post")   # 走る前に見る


def test_分からない時は動かさない():
    """残り回数が取れない時に走ると、気づかないうちに枠を使い切る。"""
    src = open(r"C:/dev/iMak/iMakHQ/tools/market_getitem.py", encoding="utf-8").read()
    body = src.split("def cmd_fetch(")[1]
    i = body.index("if left is None:")
    assert "return 1" in body[i:i + 200]


def test_他の処理のぶんを残す():
    import market_getitem as G2
    assert G2.QUOTA_FLOOR >= 1000
