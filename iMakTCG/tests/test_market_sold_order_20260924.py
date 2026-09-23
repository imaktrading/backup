"""出品の枠に入れる順: トレジャーハントの次は、市場で売れた枚数 (カード単位) の多い順 (2026-09-24)。
ユーザー「ルフィの〇〇のカードのように、売れるカードで並べる。ポケモンとかもね」。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import tcg_batch_select as B                                   # noqa: E402


def test_load_market_sold_keys_by_card_number(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("番号,売れた枚数\nP-043,19\n232/193,147\nP-043,3\n,5\n", encoding="utf-8-sig")
    d = B.load_market_sold(str(p))
    assert d[B.title_card_key("P-043")] == 19 and d[B.title_card_key("232/193")] == 147
    assert B.load_market_sold(str(tmp_path / "none.csv")) == {}


def test_sold_count_orders_within_group_after_treasure():
    titles = {"a": "PSA10 ワンピース ルフィ OP11-040", "b": "PSA10 ワンピース ルフィ P-043", "c": "PSA10 ワンピース ルフィ P-001",
              "t": "PSA10 ワンピース ナミ OP01-016"}
    sold = {"a": 1, "b": 19, "c": 10, "t": 0}

    def pop(c):
        return True
    pop.known = lambda c: True
    pop.treasure = lambda c: c == "t"
    pop.market_sold = lambda c: sold[c]
    pop.card_of = lambda c: c
    got = B.balanced_sample(list(titles), titles, 4, shuffle=lambda g: None, cost_of=lambda c: 1000,
                            pokemon_share=0, explore=0, popular_of=pop)
    assert got == ["t", "b", "c", "a"]


def test_treasure_to_high_accepts_chara_tab():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMakHQ", "tools"))
    import treasure_to_high as TH
    assert TH.tab_of([]) == "mercari_psa10_treasure"
    assert TH.tab_of(["--tab=chara"]) == "mercari_psa10_chara"
    import pytest
    with pytest.raises(SystemExit):
        TH.tab_of(["--tab=xxx"])
