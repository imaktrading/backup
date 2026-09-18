"""トレジャーハント: KEY が無い候補でも、カード番号で売れ筋に当たること (2026-09-18)。

実害: 売れ筋一致44件のうち生きている候補3件が全て KEY 空で、product_id だけを見ていた
判定に1件も当たらず「トレジャーハント 0件」だった。
"""
import sys
sys.path.insert(0, r"C:/dev/iMak/iMakTCG")
from tcg_batch_select import load_treasure_ids, title_card_key


def _csv(tmp_path):
    p = tmp_path / "demand_market.csv"
    p.write_text("番号,product_id,和名\n240/193,,ゲンガー\n020/M-P,M-P-020,ピカチュウ\n"
                 "P-001,,ルフィ\n", encoding="utf-8-sig")
    return str(p)


def test_number_only_row_becomes_key(tmp_path):
    keys = load_treasure_ids(_csv(tmp_path))
    assert "T:240/193" in keys          # product_id が空でも番号で拾う
    assert "M-P-020" in keys            # product_id はそのまま
    assert "T:020/M-P" in keys          # 番号側も入る


def test_partial_number_does_not_match(tmp_path):
    """`EXRP-001` は `P-001` と別物 (部分一致で当てない)。"""
    keys = load_treasure_ids(_csv(tmp_path))
    assert title_card_key("PSA10 ガンダムカード EXリソース EXRP-001 リリーナ") not in keys
    assert title_card_key("PSA10 ルフィ P-001") in keys


def test_missing_file_is_empty():
    assert load_treasure_ids(r"C:/dev/nowhere/demand_market.csv") == set()
