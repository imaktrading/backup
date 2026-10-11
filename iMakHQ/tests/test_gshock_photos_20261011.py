"""G-SHOCK の写真を並べて選ぶ (2026-10-11)。eBay から「写真が少ない」と指摘・999.png の手差し替えをやめる。"""
import sys

sys.path.insert(0, r"C:/dev/iMak/iMakHQ/tools")
import gshock_photos as G


def test_型番は_JF_JR_を外して揃える():
    assert G.norm_model("ga-2100-1a1jf") == "GA-2100-1A1"
    assert G.norm_model("DW-5600UE-1JR") == "DW-5600UE-1"


def test_公式ページから_その型番の写真だけを_正面_角度_着用の順に():
    base = "/content/dam/casio/product-info/locales/jp/ja/timepiece/product/watch/G/GA/GA2/"
    html = (f'"{base}GA-2100-1A1/assets/GA-2100-1A1_model01.jpg.transform/x/image.jpg"'
            f'"{base}GA-2100-1A1/assets/GA-2100-1A1_Seq03.jpg"'
            f'"{base}GA-2100-1A1/assets/GA-2100-1A1.png.transform/main/image.png"'
            f'"{base}GA-2100-1A1/assets/GA-2100-1A1_Seq02.jpg"'
            f'"{base}ga-2100-7a7/assets/GA-2100-7A7.png"')          # 関連商品は拾わない
    got = [u.rsplit("/", 1)[-1] for u in G.official_assets(html, "GA-2100-1A1JF")]
    assert got == ["GA-2100-1A1.png", "GA-2100-1A1_Seq02.jpg", "GA-2100-1A1_Seq03.jpg", "GA-2100-1A1_model01.jpg"]


def test_前に出した出品は_型番が一致する_US_の物だけ():
    rows = [{"Listing site": "US", "Title": "Casio G-SHOCK GA-2100-1A1JF Black", "Item number": "1"},
            {"Listing site": "UK", "Title": "Casio G-SHOCK GA-2100-1A1JF Black", "Item number": "2"},
            {"Listing site": "US", "Title": "Casio G-SHOCK GA-2100-1A1D", "Item number": "3"},
            {"Listing site": "US", "Title": "Casio G-SHOCK GA-2100-1A1 Black", "Item number": "4"}]
    assert G.past_item_ids(rows, "GA-2100-1A1") == ["1", "4"]


def test_答えを記録_公式は上げて_eBay_の写真はそのまま(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "CHOICE", str(tmp_path / "c.json"))
    monkeypatch.setattr(G, "PENDING", str(tmp_path / "p.json"))
    G._save(G.PENDING, {"GA-2100-1A1": {}, "DW-5600": {}})
    cands = {"GA-2100-1A1": {"official": [{"local": "C:/x/official_01.jpg"}]}}
    ans = [{"model": "GA-2100-1A1", "picks": ["C:/x/official_01.jpg", "https://i.ebayimg.com/a.jpg", "https://evil/x.jpg"]},
           {"model": "DW-5600", "skip": True}]
    ok, ng = G.apply_answers(ans, cands, log=lambda *a: None, up=lambda p: "https://i.ebayimg.com/up1.jpg")
    assert ok == 2 and ng == 0
    assert G.urls_for("GA-2100-1A1JF") == ["https://i.ebayimg.com/up1.jpg", "https://i.ebayimg.com/a.jpg"]
    assert G.urls_for("DW-5600") == []
    assert G._load(G.PENDING, {}) == {}
    assert G.add_pending("GA-2100-1A1") is False          # 選び済みは待ちに戻さない


def test_出品データ生成が選んだ写真を使い_無ければ出さない():
    src = open(r"C:/dev/iMak/iMakG-shock/gshock_to_csv.py", encoding="utf-8").read()
    assert "_GP.urls_for(_pm)" in src and "_GP.add_pending(_pm" in src
    assert "📷 写真: 選んだ写真で出した" in src
