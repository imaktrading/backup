"""tcg_promo_store + タイトル付与の回帰テスト (2026-06-24)。

検出 (other_product=promo) / レビュー要否 / set-get 往復 / タイトルに promo が
高優先で付与され 80字超では Year から落ちる、を固定。
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))
import tcg_promo_store as ps  # noqa: E402
import tcg_listing_fields as lf  # noqa: E402


def test_is_promo_variant():
    assert ps.is_promo_variant({"variant_type": "other_product"})
    assert ps.is_promo_variant({"set_name": "Other Product Card"})
    assert ps.is_promo_variant({"set_name_ebay": "Promo Cards"})
    assert not ps.is_promo_variant({"variant_type": "normal", "set_name": "Romance Dawn"})
    assert not ps.is_promo_variant({})


def test_set_get_and_review(tmp_path):
    p = str(tmp_path / "promo.json")
    cid = "P-001_OTHER PRODUCT CARD"
    # 未レビュー = needs_review True
    assert ps.needs_review({"variant_type": "other_product"}, cid, path=p)
    assert ps.get_promo(cid, path=p) == ""
    # 確定 → 取得 + レビュー済
    ps.set_promo(cid, "Ichiban Kuji Purchase Bonus", updated_at="2026-06-24", path=p)
    assert ps.get_promo(cid, path=p) == "Ichiban Kuji Purchase Bonus"
    assert ps.is_reviewed(cid, path=p)
    assert not ps.needs_review({"variant_type": "other_product"}, cid, path=p)
    # 空確定 (消す) = レビュー済・promo無し → needs_review False / get ''
    cid2 = "OP06-025_OTHER PRODUCT CARD"
    ps.set_promo(cid2, "", updated_at="2026-06-24", path=p)
    assert ps.is_reviewed(cid2, path=p)
    assert ps.get_promo(cid2, path=p) == ""
    assert not ps.needs_review({"set_name": "Other Product Card"}, cid2, path=p)


def _base_fields():
    return {
        "C:Game": "One Piece CCG", "C:Language": "Japanese",
        "C:Set": "Promo Cards", "C:Card Number": "P-001",
        "C:Character": "Monkey D. Luffy", "C:Rarity": "Promo",
        "C:Features": "", "C:Year Manufactured": "2026",
    }


def test_title_includes_promo():
    f = _base_fields()
    f["_promo"] = "Ichiban Kuji Purchase Bonus"
    t = lf.build_title_from_fields(f, grade="10")
    assert "Ichiban Kuji Purchase Bonus" in t
    assert len(t) <= 80


def test_title_drops_year_before_promo_when_long():
    """80字に収まらない時、promo は最後まで残り Year が先に落ちる。"""
    f = _base_fields()
    f["C:Character"] = "Monkey D. Luffy Straw Hat Pirates Captain"   # 長くする
    f["_promo"] = "Ichiban Kuji Purchase Bonus"
    t = lf.build_title_from_fields(f, grade="10")
    assert len(t) <= 80
    assert "Ichiban Kuji Purchase Bonus" in t   # promo 死守
    assert "2026" not in t                       # Year は犠牲に


def test_no_promo_no_change():
    f = _base_fields()
    f["_promo"] = ""
    t = lf.build_title_from_fields(f, grade="10")
    assert "Ichiban" not in t
