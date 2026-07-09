"""公式表画像を PicURL に追加する機能の回帰テスト (2026-07-08 ユーザー要望)。

_build_pic_url = 表 | 裏 | 公式表 | 999.png の順で組立。
_first_official_image = catalog images(JSON文字列/list) から先頭URL、gundam '/../' 正規化。
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))
import psa_to_csv as p  # noqa: E402


def test_first_official_image_json_string():
    # catalog の images は DB上 JSON文字列 → 先頭URLを返す
    assert p._first_official_image('["https://c.com/x.jpg","https://c.com/y.jpg"]') == "https://c.com/x.jpg"


def test_first_official_image_list():
    assert p._first_official_image(["https://c.com/a.png"]) == "https://c.com/a.png"


def test_first_official_image_one_piece_prefers_ja():
    # One Piece: images[0]=英語版(OP-EN) / [1]=日本語版(OP-JA) → 日本語版を選ぶ
    imgs = [
        "https://files.bandai-tcg-plus.com/card_image/OP-EN/OP06/OP06-022_d.png",
        "https://files.bandai-tcg-plus.com/card_image/OP-JA/OP06/OP06-022.png",
    ]
    assert p._first_official_image(imgs) == "https://files.bandai-tcg-plus.com/card_image/OP-JA/OP06/OP06-022.png"


def test_first_official_image_english_only_returns_empty():
    # 日本語版が無く英語版のみ → 公式画像を付けない ('')。英語版は絶対に出さない。
    assert p._first_official_image(["https://files.bandai-tcg-plus.com/card_image/OP-EN/OP06/OP06-022_d.png"]) == ""


def test_first_official_image_yugioh_ygoprodeck_excluded():
    # 遊戯王の ygoprodeck(英語/国際版DB) は日本語版公式でない → 除外 → 公式画像なし('')
    assert p._first_official_image(["https://images.ygoprodeck.com/images/cards/64163367.jpg"]) == ""


def test_first_official_image_pokemon_gundam_are_ja():
    # Pokemon(pokemon-card.com) / Gundam(gundam-gcg.com/jp) は元から日本語版 → そのまま採用
    assert p._first_official_image(["https://www.pokemon-card.com/assets/images/card_images/large/SM12a/x.jpg"]).endswith("x.jpg")
    assert "gundam-gcg.com" in p._first_official_image(["https://www.gundam-gcg.com/jp/cards/../images/cards/card/RP-025.webp"])


def test_first_official_image_gundam_dotdot_normalized():
    # gundam-gcg の /jp/cards/../images/ 混入URL を正規化 (eBay が拾える形に)
    got = p._first_official_image(["https://www.gundam-gcg.com/jp/cards/../images/cards/card/RP-025.webp"])
    assert got == "https://www.gundam-gcg.com/jp/images/cards/card/RP-025.webp"


def test_first_official_image_empty_cases():
    assert p._first_official_image(None) == ""
    assert p._first_official_image("") == ""
    assert p._first_official_image("[]") == ""
    assert p._first_official_image("not-json") == ""


def test_build_pic_url_with_official():
    # 表 | 裏 | 公式表 | 999.png
    url = p._build_pic_url({
        "CardImageUrlFront": "F", "CardImageUrlBack": "B", "CardImageUrlOfficial": "O",
    })
    assert url == "F|B|O|" + p.PIC_URL


def test_build_pic_url_without_official():
    # 公式表が無ければ従来通り 表 | 裏 | 999.png (後方互換)
    url = p._build_pic_url({"CardImageUrlFront": "F", "CardImageUrlBack": "B"})
    assert url == "F|B|" + p.PIC_URL


def test_build_pic_url_official_dedup():
    # 公式が front/back と同一なら重複追加しない
    url = p._build_pic_url({"CardImageUrlFront": "F", "CardImageUrlBack": "B", "CardImageUrlOfficial": "F"})
    assert url == "F|B|" + p.PIC_URL
